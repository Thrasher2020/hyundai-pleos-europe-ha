"""Binary sensor platform for the Pleos Vehicle Data integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, KEY_EV_CHARGING_ESTIMATED
from .coordinator import (
    PleosConfigEntry,
    PleosVehicleCoordinator,
    estimated_charging_from_entry,
)
from .entity import PleosVehicleEntity, dig


@dataclass(frozen=True, kw_only=True)
class PleosBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a Pleos binary sensor."""

    value_fn: Callable[[dict[str, Any]], bool | None]


def _equals(expected: str, *path: str | int) -> Callable[[dict[str, Any]], bool | None]:
    def _value(data: dict[str, Any]) -> bool | None:
        value = dig(data, *path)
        return None if value is None else value == expected

    return _value


def _warning(name: str) -> Callable[[dict[str, Any]], bool]:
    def _value(data: dict[str, Any]) -> bool:
        return name in (dig(data, "status", "warnings") or [])

    return _value


def _seat_heating(row: int, side: str) -> Callable[[dict[str, Any]], bool | None]:
    def _value(data: dict[str, Any]) -> bool | None:
        heat = dig(data, "status", "seats", row, side, "heat")
        return None if heat is None else heat != "off"

    return _value


def _door_open(row: int, side: str) -> Callable[[dict[str, Any]], bool | None]:
    return _equals("open", "status", "doors", row, side)


def _door_unlocked(row: int, side: str) -> Callable[[dict[str, Any]], bool | None]:
    def _value(data: dict[str, Any]) -> bool | None:
        status = dig(data, "status", "doors", row, side)
        return None if status is None else status != "locked"

    return _value


def _all_doors_unlocked(data: dict[str, Any]) -> bool | None:
    statuses = [
        dig(data, "status", "doors", row, side)
        for row in (0, 1)
        for side in ("left", "right")
    ]
    if any(status is None for status in statuses):
        return None
    return any(status != "locked" for status in statuses)


BINARY_SENSORS: tuple[PleosBinarySensorEntityDescription, ...] = (
    PleosBinarySensorEntityDescription(
        key="is_locked",
        translation_key="is_locked",
        device_class=BinarySensorDeviceClass.LOCK,
        value_fn=_all_doors_unlocked,
    ),
    PleosBinarySensorEntityDescription(
        key="front_left_door_is_locked",
        translation_key="front_left_door_is_locked",
        device_class=BinarySensorDeviceClass.LOCK,
        value_fn=_door_unlocked(0, "left"),
    ),
    PleosBinarySensorEntityDescription(
        key="front_right_door_is_locked",
        translation_key="front_right_door_is_locked",
        device_class=BinarySensorDeviceClass.LOCK,
        value_fn=_door_unlocked(0, "right"),
    ),
    PleosBinarySensorEntityDescription(
        key="back_left_door_is_locked",
        translation_key="back_left_door_is_locked",
        device_class=BinarySensorDeviceClass.LOCK,
        value_fn=_door_unlocked(1, "left"),
    ),
    PleosBinarySensorEntityDescription(
        key="back_right_door_is_locked",
        translation_key="back_right_door_is_locked",
        device_class=BinarySensorDeviceClass.LOCK,
        value_fn=_door_unlocked(1, "right"),
    ),
    PleosBinarySensorEntityDescription(
        key="front_left_door_is_open",
        translation_key="front_left_door_is_open",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=_door_open(0, "left"),
    ),
    PleosBinarySensorEntityDescription(
        key="front_right_door_is_open",
        translation_key="front_right_door_is_open",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=_door_open(0, "right"),
    ),
    PleosBinarySensorEntityDescription(
        key="back_left_door_is_open",
        translation_key="back_left_door_is_open",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=_door_open(1, "left"),
    ),
    PleosBinarySensorEntityDescription(
        key="back_right_door_is_open",
        translation_key="back_right_door_is_open",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=_door_open(1, "right"),
    ),
    PleosBinarySensorEntityDescription(
        key="hood_is_open",
        translation_key="hood_is_open",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=_equals("open", "status", "hood"),
    ),
    PleosBinarySensorEntityDescription(
        key="trunk_is_open",
        translation_key="trunk_is_open",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=_equals("open", "status", "trunk"),
    ),
    PleosBinarySensorEntityDescription(
        key="sunroof_is_open",
        translation_key="sunroof_is_open",
        value_fn=_equals("open", "status", "sunroof"),
    ),
    PleosBinarySensorEntityDescription(
        key="ev_battery_is_charging",
        translation_key="ev_battery_is_charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=lambda data: dig(data, "batteries", "charge", "charging"),
    ),
    PleosBinarySensorEntityDescription(
        key="ev_battery_is_plugged_in",
        translation_key="ev_battery_is_plugged_in",
        device_class=BinarySensorDeviceClass.PLUG,
        value_fn=_equals("connected", "batteries", "charge", "plugin"),
    ),
    PleosBinarySensorEntityDescription(
        key="engine_is_running",
        translation_key="engine_is_running",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=_equals("on", "driving", "ignition", "status"),
    ),
    PleosBinarySensorEntityDescription(
        key="air_control_is_on",
        translation_key="air_control_is_on",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=_equals("on", "status", "climateControl", "status"),
    ),
    PleosBinarySensorEntityDescription(
        key="defrost_is_on",
        translation_key="defrost_is_on",
        value_fn=_equals("on", "status", "windshield", "defrost"),
    ),
    PleosBinarySensorEntityDescription(
        key="steering_wheel_heater_is_on",
        translation_key="steering_wheel_heater_is_on",
        value_fn=_equals("on", "status", "steeringWheelHeat"),
    ),
    PleosBinarySensorEntityDescription(
        key="front_left_seat_heater_on",
        translation_key="front_left_seat_heater_on",
        value_fn=_seat_heating(0, "left"),
    ),
    PleosBinarySensorEntityDescription(
        key="front_right_seat_heater_on",
        translation_key="front_right_seat_heater_on",
        value_fn=_seat_heating(0, "right"),
    ),
    PleosBinarySensorEntityDescription(
        key="rear_left_seat_heater_on",
        translation_key="rear_left_seat_heater_on",
        value_fn=_seat_heating(1, "left"),
    ),
    PleosBinarySensorEntityDescription(
        key="rear_right_seat_heater_on",
        translation_key="rear_right_seat_heater_on",
        value_fn=_seat_heating(1, "right"),
    ),
    PleosBinarySensorEntityDescription(
        key="fuel_level_is_low",
        translation_key="fuel_level_is_low",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_warning("lowFuel"),
    ),
    PleosBinarySensorEntityDescription(
        key="smart_key_battery_warning_is_on",
        translation_key="smart_key_battery_warning_is_on",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_warning("smartKeyBattery"),
    ),
    PleosBinarySensorEntityDescription(
        key="washer_fluid_warning_is_on",
        translation_key="washer_fluid_warning_is_on",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_warning("washFluid"),
    ),
    PleosBinarySensorEntityDescription(
        key="brake_fluid_warning_is_on",
        translation_key="brake_fluid_warning_is_on",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_warning("brakeOil"),
    ),
    PleosBinarySensorEntityDescription(
        key="oil_level_warning_is_on",
        translation_key="oil_level_warning_is_on",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_warning("engineOil"),
    ),
    PleosBinarySensorEntityDescription(
        key="tire_pressure_all_warning_is_on",
        translation_key="tire_pressure_all_warning_is_on",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_warning("tirePressureLow"),
    ),
    PleosBinarySensorEntityDescription(
        key="tire_pressure_front_left_warning_is_on",
        translation_key="tire_pressure_front_left_warning_is_on",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_warning("tirePressureFrontLeft"),
    ),
    PleosBinarySensorEntityDescription(
        key="tire_pressure_front_right_warning_is_on",
        translation_key="tire_pressure_front_right_warning_is_on",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_warning("tirePressureFrontRight"),
    ),
    PleosBinarySensorEntityDescription(
        key="tire_pressure_rear_left_warning_is_on",
        translation_key="tire_pressure_rear_left_warning_is_on",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_warning("tirePressureRearLeft"),
    ),
    PleosBinarySensorEntityDescription(
        key="tire_pressure_rear_right_warning_is_on",
        translation_key="tire_pressure_rear_right_warning_is_on",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_warning("tirePressureRearRight"),
    ),
    PleosBinarySensorEntityDescription(
        key="headlamp_status",
        translation_key="headlamp_status",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_warning("frontHeadLamp"),
    ),
    PleosBinarySensorEntityDescription(
        key="stop_lamp_left",
        translation_key="stop_lamp_left",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_warning("rearLeftStopLamp"),
    ),
    PleosBinarySensorEntityDescription(
        key="stop_lamp_right",
        translation_key="stop_lamp_right",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_warning("rearRightStopLamp"),
    ),
    PleosBinarySensorEntityDescription(
        key="turn_signal_left_front",
        translation_key="turn_signal_left_front",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_warning("frontLeftTurnSignal"),
    ),
    PleosBinarySensorEntityDescription(
        key="turn_signal_right_front",
        translation_key="turn_signal_right_front",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_warning("frontRightTurnSignal"),
    ),
    PleosBinarySensorEntityDescription(
        key="turn_signal_left_rear",
        translation_key="turn_signal_left_rear",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_warning("rearLeftTurnSignal"),
    ),
    PleosBinarySensorEntityDescription(
        key="turn_signal_right_rear",
        translation_key="turn_signal_right_rear",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_warning("rearRightTurnSignal"),
    ),
)


ESTIMATED_CHARGING_SENSOR = PleosBinarySensorEntityDescription(
    key="ev_battery_is_charging_estimated",
    translation_key="ev_battery_is_charging_estimated",
    device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
    value_fn=lambda data: data.get(KEY_EV_CHARGING_ESTIMATED),
)


class PleosVehicleBinarySensor(PleosVehicleEntity, BinarySensorEntity):
    """A binary sensor backed by Pleos vehicle data."""

    entity_description: PleosBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: PleosVehicleCoordinator,
        vin: str,
        description: PleosBinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, vin, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the binary sensor state."""
        if self.vehicle_data is None:
            return None
        return self.entity_description.value_fn(self.vehicle_data)


@callback
def _async_remove_estimated_charging(
    hass: HomeAssistant, coordinator: PleosVehicleCoordinator
) -> None:
    """Remove the estimated charging sensor from the registry when it is off."""
    registry = er.async_get(hass)
    for vin in coordinator.vehicles:
        entity_id = registry.async_get_entity_id(
            Platform.BINARY_SENSOR,
            DOMAIN,
            f"{vin}_{ESTIMATED_CHARGING_SENSOR.key}",
        )
        if entity_id is not None:
            registry.async_remove(entity_id)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PleosConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Pleos binary sensors."""
    coordinator = entry.runtime_data
    descriptions = list(BINARY_SENSORS)
    if estimated_charging_from_entry(entry):
        descriptions.append(ESTIMATED_CHARGING_SENSOR)
    else:
        _async_remove_estimated_charging(hass, coordinator)
    async_add_entities(
        PleosVehicleBinarySensor(coordinator, vin, description)
        for vin in coordinator.vehicles
        for description in descriptions
    )
