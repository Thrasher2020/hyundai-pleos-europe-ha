"""Coordinator for the Pleos Vehicle Data integration."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import DistanceConverter

from .api import PleosAuthError, PleosClient, PleosError
from .const import (
    CONF_BATTERY_CAPACITY,
    CONF_TANK_CAPACITY,
    DEFAULT_BATTERY_CAPACITY,
    DEFAULT_TANK_CAPACITY,
    DOMAIN,
    KEY_ELECTRIC_ECONOMY,
    KEY_ELECTRIC_ECONOMY_AVERAGE,
    KEY_ELECTRIC_ECONOMY_TODAY,
    KEY_ELECTRIC_ECONOMY_UNIT,
    KEY_FUEL_ECONOMY,
    KEY_FUEL_ECONOMY_AVERAGE,
    KEY_FUEL_ECONOMY_TODAY,
    KEY_FUEL_ECONOMY_UNIT,
    KEY_LAST_POLLED,
    LITRES_PER_UK_GALLON,
    MAX_ODOMETER_STEP,
    LEVEL_RISE,
    SCAN_INTERVAL,
    STORAGE_VERSION,
)
from .readings import (
    battery_level,
    dig,
    fuel_level,
    last_updated,
    length_unit,
    odometer,
)

_LOGGER = logging.getLogger(__name__)

# Pause before retrying a vehicle that Pleos refused, so a brief server
# problem has a moment to clear.
RETRY_DELAY_SECONDS = 5

# Fuel economy follows the car's own unit: miles per UK gallon for a car
# showing miles, litres per 100 km for one showing kilometres.
ECONOMY_UNITS = {
    UnitOfLength.MILES: "mpg",
    UnitOfLength.KILOMETERS: "L/100km",
}

# Electric economy likewise: miles per kilowatt-hour for a car showing
# miles, kilowatt-hours per 100 km for one showing kilometres.
ELECTRIC_ECONOMY_UNITS = {
    UnitOfLength.MILES: "mi/kWh",
    UnitOfLength.KILOMETERS: "kWh/100km",
}


def capacity_from_entry(entry: ConfigEntry, key: str, default: float) -> float:
    """Return a configured capacity, falling back to the default."""
    value = entry.options.get(key, entry.data.get(key))
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value)
    return default


def tank_capacity_from_entry(entry: ConfigEntry) -> float:
    """Return the configured fuel tank size in litres."""
    return capacity_from_entry(entry, CONF_TANK_CAPACITY, DEFAULT_TANK_CAPACITY)


def battery_capacity_from_entry(entry: ConfigEntry) -> float:
    """Return the configured battery size in kilowatt-hours."""
    return capacity_from_entry(entry, CONF_BATTERY_CAPACITY, DEFAULT_BATTERY_CAPACITY)


def fuel_economy_value(distance: float, litres: float, unit: str | None) -> float | None:
    """Return the distance covered per unit of fuel, in the car's own unit."""
    if unit is None or distance <= 0 or litres <= 0:
        return None
    if unit == UnitOfLength.MILES:
        return round(distance / (litres / LITRES_PER_UK_GALLON), 1)
    kilometres = DistanceConverter.convert(distance, unit, UnitOfLength.KILOMETERS)
    return round(litres / kilometres * 100, 1)


def electric_economy_value(distance: float, kwh: float, unit: str | None) -> float | None:
    """Return the distance covered per unit of energy, in the car's own unit."""
    if unit is None or distance <= 0 or kwh <= 0:
        return None
    if unit == UnitOfLength.MILES:
        return round(distance / kwh, 1)
    kilometres = DistanceConverter.convert(distance, unit, UnitOfLength.KILOMETERS)
    return round(kwh / kilometres * 100, 1)


def upload_day(data: dict[str, Any]) -> str | None:
    """Return the local date the car uploaded this data, as an ISO string.

    Falls back to when it was polled if Pleos sends no timestamp.
    """
    uploaded = last_updated(data) or data.get(KEY_LAST_POLLED)
    if not isinstance(uploaded, datetime):
        return None
    return dt_util.as_local(uploaded).date().isoformat()


@dataclass
class EconomyState:
    """Distance driven and energy used, accumulated per vehicle.

    Kept across restarts, so the totals do not start again every time Home
    Assistant is restarted. The Pleos API has no economy figure of its own,
    whether for fuel or for electricity.
    """

    last_odometer: float | None = None
    last_level: float | None = None
    window_distance: float = 0.0
    window_energy: float = 0.0
    average_distance: float = 0.0
    average_energy: float = 0.0
    # The local date (ISO) the today_ totals belong to.
    today: str | None = None
    today_distance: float = 0.0
    today_energy: float = 0.0


class PleosVehicleCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Polls Pleos for every vehicle on the API key."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: PleosClient,
        vehicles: list[dict[str, Any]],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        self.vehicles: dict[str, dict[str, Any]] = {v["vin"]: v for v in vehicles}
        self.tank_capacity = tank_capacity_from_entry(config_entry)
        self.battery_capacity = battery_capacity_from_entry(config_entry)
        self._fuel_economy: dict[str, EconomyState] = {}
        self._electric_economy: dict[str, EconomyState] = {}
        self._last_good: dict[str, dict[str, Any]] = {}
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{config_entry.entry_id}")

    async def async_load_fuel_economy(self) -> None:
        """Restore the economy accumulators after a restart or reload."""
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            return
        names = [field.name for field in fields(EconomyState)]
        for vin, values in stored.items():
            if not isinstance(values, dict):
                continue
            for key, target in (
                ("fuel", self._fuel_economy),
                ("electric", self._electric_economy),
            ):
                block = values.get(key)
                if isinstance(block, dict):
                    target[vin] = EconomyState(
                        **{name: block[name] for name in names if name in block}
                    )

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        data: dict[str, dict[str, Any]] = {}
        updated = False
        try:
            for vin in self.vehicles:
                try:
                    vehicle_data = await self._async_fetch_vehicle(vin)
                except PleosAuthError:
                    raise
                except PleosError as err:
                    previous = self._last_good.get(vin)
                    if previous is None:
                        raise
                    _LOGGER.warning(
                        "Pleos data could not be refreshed, keeping the last values: %s",
                        err,
                    )
                    data[vin] = previous
                    continue
                _LOGGER.debug(
                    "Pleos distanceToEmpties: %s",
                    dig(vehicle_data, "powertrains", "distanceToEmpties") or "missing",
                )
                data[vin] = {
                    **vehicle_data,
                    "vin": vin,
                    KEY_LAST_POLLED: datetime.now(UTC),
                }
                self._last_good[vin] = data[vin]
                updated = self._update_fuel_economy(vin, data[vin]) or updated
                updated = self._update_electric_economy(vin, data[vin]) or updated
        except PleosAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except PleosError as err:
            raise UpdateFailed(str(err)) from err
        if updated:
            await self._store.async_save(
                {
                    vin: {
                        "fuel": asdict(self._fuel_economy.get(vin, EconomyState())),
                        "electric": asdict(
                            self._electric_economy.get(vin, EconomyState())
                        ),
                    }
                    for vin in self.vehicles
                }
            )
        return data

    async def _async_fetch_vehicle(self, vin: str) -> dict[str, dict[str, Any]]:
        """Fetch one vehicle, retrying once on a fresh token if Pleos refuses."""
        try:
            return await self.client.async_get_vehicle_data(vin)
        except PleosAuthError:
            raise
        except PleosError:
            self.client.reset_token()
            await asyncio.sleep(RETRY_DELAY_SECONDS)
            return await self.client.async_get_vehicle_data(vin)

    def _update_fuel_economy(self, vin: str, data: dict[str, Any]) -> bool:
        """Add the fuel economy figures to one vehicle's data.

        Pleos reports the fuel level as a percentage and never reports litres
        burned, so economy is worked out from the distance driven and the drop
        in the fuel level since the previous update. Returns whether a reading
        was folded in.
        """
        state = self._fuel_economy.setdefault(vin, EconomyState())
        unit = length_unit(data)
        data[KEY_FUEL_ECONOMY_UNIT] = ECONOMY_UNITS.get(unit) if unit else None
        today = self._start_day(state)

        current_odometer = odometer(data)
        current_level = fuel_level(data)
        if current_odometer is not None and current_level is not None:
            self._fold(
                state,
                current_odometer,
                current_level,
                self.tank_capacity,
                counts_today=upload_day(data) == today,
            )

        data[KEY_FUEL_ECONOMY] = fuel_economy_value(
            state.window_distance, state.window_energy, unit
        )
        data[KEY_FUEL_ECONOMY_AVERAGE] = fuel_economy_value(
            state.average_distance, state.average_energy, unit
        )
        data[KEY_FUEL_ECONOMY_TODAY] = fuel_economy_value(
            state.today_distance, state.today_energy, unit
        )
        return current_odometer is not None and current_level is not None

    def _update_electric_economy(self, vin: str, data: dict[str, Any]) -> bool:
        """Add the electric economy figures to one vehicle's data.

        Pleos reports the battery state of charge as a percentage and never
        reports kilowatt-hours used, so economy is worked out the same way as
        fuel economy but from the battery level and the battery capacity.
        Returns whether a reading was folded in.
        """
        state = self._electric_economy.setdefault(vin, EconomyState())
        unit = length_unit(data)
        data[KEY_ELECTRIC_ECONOMY_UNIT] = ELECTRIC_ECONOMY_UNITS.get(unit) if unit else None
        today = self._start_day(state)

        current_odometer = odometer(data)
        current_level = battery_level(data)
        if current_odometer is not None and current_level is not None:
            self._fold(
                state,
                current_odometer,
                current_level,
                self.battery_capacity,
                counts_today=upload_day(data) == today,
            )

        data[KEY_ELECTRIC_ECONOMY] = electric_economy_value(
            state.window_distance, state.window_energy, unit
        )
        data[KEY_ELECTRIC_ECONOMY_AVERAGE] = electric_economy_value(
            state.average_distance, state.average_energy, unit
        )
        data[KEY_ELECTRIC_ECONOMY_TODAY] = electric_economy_value(
            state.today_distance, state.today_energy, unit
        )
        return current_odometer is not None and current_level is not None

    def _start_day(self, state: EconomyState) -> str:
        """Zero the day's totals once a new local day has begun.

        Returns today's local date as an ISO string.
        """
        today = dt_util.now().date().isoformat()
        if state.today != today:
            state.today = today
            state.today_distance = 0.0
            state.today_energy = 0.0
        return today

    def _fold(
        self,
        state: EconomyState,
        current_odometer: float,
        current_level: float,
        capacity: float,
        counts_today: bool,
    ) -> None:
        """Fold one reading into an accumulator.

        Most cars only upload occasionally, so a reading can cover many days of
        driving. The level is quantised to one percent, but summing the drops
        telescopes, so a whole window is accurate where a single update is not.
        An interval counts towards today when the car uploaded it today, so a
        trip uploaded just before midnight is not put on the next day.
        """
        previous_odometer = state.last_odometer
        previous_level = state.last_level
        state.last_odometer = current_odometer
        state.last_level = current_level
        if previous_odometer is None or previous_level is None:
            # First reading for this vehicle: nothing to compare against yet.
            return

        distance = current_odometer - previous_odometer
        # A fall, or an implausibly large jump, is a unit change or a replaced
        # instrument cluster rather than distance driven. Skip the whole
        # interval, and carry on from the new reading.
        if not 0 <= distance <= MAX_ODOMETER_STEP:
            return

        # A rise in the level is a refuel or a recharge. The energy added and
        # the energy burned in the same interval cannot be told apart, so the
        # interval is skipped, and the window starts again from the new
        # reading. The day carries on. A small rise is rounding noise, and a
        # drop is energy used.
        if previous_level - current_level <= -LEVEL_RISE:
            state.window_distance = 0.0
            state.window_energy = 0.0
            return

        state.average_distance += distance
        state.window_distance += distance
        if counts_today:
            state.today_distance += distance
        level_lost = previous_level - current_level
        if level_lost > 0:
            energy = level_lost / 100 * capacity
            state.average_energy += energy
            state.window_energy += energy
            if counts_today:
                state.today_energy += energy


type PleosConfigEntry = ConfigEntry[PleosVehicleCoordinator]
