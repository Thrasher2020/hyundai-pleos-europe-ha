"""Readings taken out of a Pleos vehicle payload."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.const import UnitOfLength
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import DistanceConverter

LENGTH_UNITS = {
    "km": UnitOfLength.KILOMETERS,
    "mile": UnitOfLength.MILES,
    "miles": UnitOfLength.MILES,
    "meter": UnitOfLength.METERS,
    "feet": UnitOfLength.FEET,
}
TIMESTAMP_BLOCKS = ("batteries", "driving", "powertrains", "status", "locations")


def dig(data: Any, *path: str | int) -> Any:
    """Return a nested value, or None when any step is missing."""
    for key in path:
        try:
            data = data[key]
        except (KeyError, IndexError, TypeError):
            return None
    return data


def timestamp(value: Any) -> datetime | None:
    """Return a Pleos timestamp as a datetime, or None if there is none."""
    return dt_util.parse_datetime(value) if isinstance(value, str) else None


def last_updated(data: dict[str, Any]) -> datetime | None:
    """Return when the car last uploaded, from the newest block timestamp."""
    stamps = [timestamp(dig(data, name, "timestamp")) for name in TIMESTAMP_BLOCKS]
    known = [stamp for stamp in stamps if stamp is not None]
    return max(known) if known else None


def length_unit(data: dict[str, Any]) -> str | None:
    """Return the length unit the car itself displays."""
    return LENGTH_UNITS.get(dig(data, "driving", "odometer", "unit"))


def odometer(data: dict[str, Any]) -> float | None:
    """Return the odometer, corrected into the car's own unit.

    Unlike the driving ranges, the vehicle API reports the odometer distance
    in kilometres while labelling it with the car's display unit: a car
    showing miles sends the km figure with a ``mile`` unit. Convert it so the
    number matches the unit the car actually displays.
    """
    raw = dig(data, "driving", "odometer", "value")
    unit = length_unit(data)
    if not isinstance(raw, (int, float)) or isinstance(raw, bool) or unit is None:
        return raw
    return round(DistanceConverter.convert(raw, UnitOfLength.KILOMETERS, unit), 1)


def fuel_level(data: dict[str, Any]) -> float | None:
    """Return the fuel level as a percentage of the tank."""
    value = dig(data, "powertrains", "engine", "fuelLevel")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return float(value)


def battery_level(data: dict[str, Any]) -> float | None:
    """Return the battery state of charge as a percentage."""
    value = dig(data, "batteries", "charge", "stateOfCharge")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return float(value)
