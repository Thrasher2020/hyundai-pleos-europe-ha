"""Sensor platform for the Pleos Vehicle Data integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    KEY_ELECTRIC_ECONOMY,
    KEY_ELECTRIC_ECONOMY_AVERAGE,
    KEY_ELECTRIC_ECONOMY_UNIT,
    KEY_FUEL_ECONOMY,
    KEY_FUEL_ECONOMY_AVERAGE,
    KEY_FUEL_ECONOMY_UNIT,
    KEY_LAST_POLLED,
)
from .coordinator import PleosConfigEntry, PleosVehicleCoordinator
from .entity import PleosVehicleEntity
from .readings import LENGTH_UNITS, dig, length_unit, odometer

TEMPERATURE_UNITS = {
    "C": UnitOfTemperature.CELSIUS,
    "F": UnitOfTemperature.FAHRENHEIT,
}
PRESSURE_UNITS = {
    "psi": UnitOfPressure.PSI,
    "kpa": UnitOfPressure.KPA,
    "bar": UnitOfPressure.BAR,
}
TIMESTAMP_BLOCKS = ("batteries", "driving", "powertrains", "status", "locations")
ATTR_LAST_KNOWN_AT = "last_known_at"


@dataclass(frozen=True, kw_only=True)
class PleosSensorEntityDescription(SensorEntityDescription):
    """Describes a Pleos sensor."""

    value_fn: Callable[[dict[str, Any]], Any]
    unit_fn: Callable[[dict[str, Any]], str | None] | None = None
    # Pleos sometimes sends a dash instead of a range. Keep the last number
    # received, and say when it was received, rather than going unknown.
    keep_last_known: bool = False


def _timestamp(value: Any) -> datetime | None:
    return dt_util.parse_datetime(value) if isinstance(value, str) else None


def _last_updated(data: dict[str, Any]) -> datetime | None:
    stamps = [_timestamp(dig(data, name, "timestamp")) for name in TIMESTAMP_BLOCKS]
    known = [stamp for stamp in stamps if stamp is not None]
    return max(known) if known else None


def _range_entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the usable distance-to-empty entries Pleos reports."""
    entries = dig(data, "powertrains", "distanceToEmpties")
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if _entry_value(entry) is not None]


def _entry_value(entry: Any) -> int | None:
    if not isinstance(entry, dict):
        return None
    try:
        return int(entry["value"])
    except (KeyError, TypeError, ValueError):
        return None


def _fuel_range_entry(data: dict[str, Any]) -> dict[str, Any] | None:
    """Return the petrol driving range entry.

    A plug-in hybrid reports several ``PHEV`` entries with no ``ICE``/``HEV``
    one, so the largest of them is the petrol range.
    """
    entries = _range_entries(data)
    for entry in entries:
        if entry.get("type") in ("ICE", "HEV"):
            return entry
    plug_in = [entry for entry in entries if entry.get("type") == "PHEV"]
    if plug_in:
        return max(plug_in, key=_entry_value)
    return None


def _ev_range_entry(data: dict[str, Any]) -> dict[str, Any] | None:
    """Return the electric driving range entry.

    A plug-in hybrid reports several ``PHEV`` entries with no ``EV`` one, so
    the smallest of them is the electric range.
    """
    entries = _range_entries(data)
    for entry in entries:
        if entry.get("type") == "EV":
            return entry
    plug_in = [entry for entry in entries if entry.get("type") == "PHEV"]
    if len(plug_in) > 1:
        return min(plug_in, key=_entry_value)
    return None


def _fuel_range_value(data: dict[str, Any]) -> int | None:
    return _entry_value(_fuel_range_entry(data))


def _ev_range_value(data: dict[str, Any]) -> int | None:
    return _entry_value(_ev_range_entry(data))


def _range_unit(entry: dict[str, Any] | None) -> str | None:
    return LENGTH_UNITS.get(entry.get("unit")) if entry else None


def _fuel_range_unit(data: dict[str, Any]) -> str | None:
    return _range_unit(_fuel_range_entry(data))


def _ev_range_unit(data: dict[str, Any]) -> str | None:
    return _range_unit(_ev_range_entry(data))


def _tire_value(row: int, side: str) -> Callable[[dict[str, Any]], float | None]:
    def _value(data: dict[str, Any]) -> float | None:
        raw = dig(data, "status", "tire", row, side)
        unit = dig(data, "status", "tire", row, "unit")
        if not isinstance(raw, (int, float)) or raw == 255:
            return None
        if unit == "kpa":
            return raw * 5
        if unit == "bar":
            return raw / 10
        return raw

    return _value


def _tire_unit(row: int) -> Callable[[dict[str, Any]], str | None]:
    def _unit(data: dict[str, Any]) -> str | None:
        return PRESSURE_UNITS.get(dig(data, "status", "tire", row, "unit"))

    return _unit


SENSORS: tuple[PleosSensorEntityDescription, ...] = (
    PleosSensorEntityDescription(
        key="vehicle_identification_number",
        translation_key="vehicle_identification_number",
        value_fn=lambda data: data.get("vin"),
    ),
    PleosSensorEntityDescription(
        key="odometer",
        translation_key="odometer",
        # No device_class, so the odometer stays in the car's own unit
        # (miles here) instead of being converted into the system unit.
        # readings.odometer applies the km -> car's-unit correction the API
        # omits.
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=odometer,
        unit_fn=length_unit,
    ),
    PleosSensorEntityDescription(
        key="fuel_level",
        translation_key="fuel_level",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda data: dig(data, "powertrains", "engine", "fuelLevel"),
    ),
    PleosSensorEntityDescription(
        key="fuel_driving_range",
        translation_key="fuel_driving_range",
        keep_last_known=True,
        # No device_class: with one, Home Assistant converts the value into the
        # configured length unit (km here). Pleos reports the car's own unit,
        # so leave the value and unit exactly as the car reports them.
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_fuel_range_value,
        unit_fn=_fuel_range_unit,
    ),
    PleosSensorEntityDescription(
        key="ev_driving_range",
        translation_key="ev_driving_range",
        keep_last_known=True,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_ev_range_value,
        unit_fn=_ev_range_unit,
    ),
    PleosSensorEntityDescription(
        key="fuel_economy",
        translation_key="fuel_economy",
        # Worked out by the coordinator from the odometer and the fuel level,
        # because Pleos has no economy figure and never reports litres burned.
        # No device_class exists for fuel economy, so the unit follows the car:
        # mpg for a car showing miles, L/100km for one showing kilometres.
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.get(KEY_FUEL_ECONOMY),
        unit_fn=lambda data: data.get(KEY_FUEL_ECONOMY_UNIT),
    ),
    PleosSensorEntityDescription(
        key="fuel_economy_average",
        translation_key="fuel_economy_average",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.get(KEY_FUEL_ECONOMY_AVERAGE),
        unit_fn=lambda data: data.get(KEY_FUEL_ECONOMY_UNIT),
    ),
    PleosSensorEntityDescription(
        key="ev_economy",
        translation_key="ev_economy",
        # Worked out by the coordinator from the odometer and the battery level,
        # because Pleos has no economy figure and never reports kilowatt-hours
        # used. No device class exists for electric economy, so the unit follows
        # the car: mi/kWh for a car showing miles, kWh/100km for one showing
        # kilometres.
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.get(KEY_ELECTRIC_ECONOMY),
        unit_fn=lambda data: data.get(KEY_ELECTRIC_ECONOMY_UNIT),
    ),
    PleosSensorEntityDescription(
        key="ev_economy_average",
        translation_key="ev_economy_average",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.get(KEY_ELECTRIC_ECONOMY_AVERAGE),
        unit_fn=lambda data: data.get(KEY_ELECTRIC_ECONOMY_UNIT),
    ),
    PleosSensorEntityDescription(
        key="ev_battery_percentage",
        translation_key="ev_battery_percentage",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda data: dig(data, "batteries", "charge", "stateOfCharge"),
    ),
    PleosSensorEntityDescription(
        key="ev_estimated_current_charge_duration",
        translation_key="ev_estimated_current_charge_duration",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda data: dig(data, "batteries", "charge", "remainTime"),
    ),
    PleosSensorEntityDescription(
        key="ev_target_range_charge_ac",
        translation_key="charge_target_ac",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda data: dig(
            data, "batteries", "charge", "targetStateOfCharge", "standard"
        ),
    ),
    PleosSensorEntityDescription(
        key="ev_target_range_charge_dc",
        translation_key="charge_target_dc",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda data: dig(
            data, "batteries", "charge", "targetStateOfCharge", "quick"
        ),
    ),
    PleosSensorEntityDescription(
        key="outside_temperature",
        translation_key="outside_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: dig(data, "status", "outsideTemperature", "value"),
        unit_fn=lambda data: TEMPERATURE_UNITS.get(
            dig(data, "status", "outsideTemperature", "unit")
        ),
    ),
    PleosSensorEntityDescription(
        key="air_temperature",
        translation_key="air_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: dig(
            data, "status", "climateControl", "temperature", "value"
        ),
        unit_fn=lambda data: TEMPERATURE_UNITS.get(
            dig(data, "status", "climateControl", "temperature", "unit")
        ),
    ),
    PleosSensorEntityDescription(
        key="tire_pressure_front_left",
        translation_key="tire_pressure_front_left",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_tire_value(0, "left"),
        unit_fn=_tire_unit(0),
    ),
    PleosSensorEntityDescription(
        key="tire_pressure_front_right",
        translation_key="tire_pressure_front_right",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_tire_value(0, "right"),
        unit_fn=_tire_unit(0),
    ),
    PleosSensorEntityDescription(
        key="tire_pressure_rear_left",
        translation_key="tire_pressure_rear_left",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_tire_value(1, "left"),
        unit_fn=_tire_unit(1),
    ),
    PleosSensorEntityDescription(
        key="tire_pressure_rear_right",
        translation_key="tire_pressure_rear_right",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_tire_value(1, "right"),
        unit_fn=_tire_unit(1),
    ),
    PleosSensorEntityDescription(
        key="geocoded_location",
        translation_key="geocoded_location",
        value_fn=lambda data: dig(data, "geocode", "display_name"),
    ),
    PleosSensorEntityDescription(
        key="last_polled_at",
        translation_key="last_polled_at",
        # When Home Assistant last fetched the data from Pleos. Distinct from
        # Last Updated At, which is when the car last uploaded.
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.get(KEY_LAST_POLLED),
    ),
    PleosSensorEntityDescription(
        key="last_updated_at",
        translation_key="last_updated_at",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_last_updated,
    ),
    PleosSensorEntityDescription(
        key="location_last_updated_at",
        translation_key="location_last_updated_at",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: _timestamp(dig(data, "locations", "timestamp")),
    ),
)


class PleosVehicleSensor(PleosVehicleEntity, RestoreSensor):
    """A sensor backed by Pleos vehicle data."""

    entity_description: PleosSensorEntityDescription

    def __init__(
        self,
        coordinator: PleosVehicleCoordinator,
        vin: str,
        description: PleosSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, vin, description.key)
        self.entity_description = description
        # (value, unit, when the value was last received from Pleos)
        self._known: tuple[Any, str | None, datetime | None] | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the last known value after a restart."""
        await super().async_added_to_hass()
        if not self.entity_description.keep_last_known:
            return
        restored = await self.async_get_last_sensor_data()
        state = await self.async_get_last_state()
        if restored is None or restored.native_value is None:
            return
        seen = _timestamp(state.attributes.get(ATTR_LAST_KNOWN_AT)) if state else None
        self._known = (
            restored.native_value,
            restored.native_unit_of_measurement,
            seen,
        )

    def _read(self) -> tuple[Any, str | None]:
        """Return this sensor's value and unit, keeping the last known range."""
        description = self.entity_description
        if self.vehicle_data is None:
            value, unit = None, description.native_unit_of_measurement
        else:
            value = description.value_fn(self.vehicle_data)
            if description.unit_fn is None:
                unit = description.native_unit_of_measurement
            else:
                unit = description.unit_fn(self.vehicle_data)
        if not description.keep_last_known:
            return value, unit
        if value is not None:
            seen = self.vehicle_data.get(KEY_LAST_POLLED)
            self._known = (value, unit, seen if isinstance(seen, datetime) else None)
            return value, unit
        if self._known is not None:
            return self._known[0], self._known[1]
        return None, unit

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        return self._read()[0]

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit, which may depend on the vehicle's reported units."""
        return self._read()[1]

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional sensor attributes."""
        if self.entity_description.key == "geocoded_location":
            if self.vehicle_data is None:
                return None

            geocode = self.vehicle_data.get("geocode")
            if not isinstance(geocode, dict):
                return None

            address = geocode.get("address", {})
            if not isinstance(address, dict):
                address = {}

            return {
                "latitude": dig(
                    self.vehicle_data,
                    "locations",
                    "location",
                    "latitude",
                ),
                "longitude": dig(
                    self.vehicle_data,
                    "locations",
                    "location",
                    "longitude",
                ),
                "road": address.get("road"),
                "house_number": address.get("house_number"),
                "postcode": address.get("postcode"),
                "city": (
                    address.get("city")
                    or address.get("town")
                    or address.get("village")
                    or address.get("municipality")
                ),
                "country": address.get("country"),
            }

        if not self.entity_description.keep_last_known or self._known is None:
            return None

        seen = self._known[2]
        if seen is None:
            return None

        return {ATTR_LAST_KNOWN_AT: seen.isoformat()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PleosConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Pleos sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        PleosVehicleSensor(coordinator, vin, description)
        for vin in coordinator.vehicles
        for description in SENSORS
    )
