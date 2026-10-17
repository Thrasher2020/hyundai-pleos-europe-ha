"""Reverse geocoding for Pleos Vehicle Data."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import ClientError, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"


async def async_reverse_geocode(
    hass: HomeAssistant,
    latitude: float,
    longitude: float,
) -> dict[str, Any] | None:
    """Convert latitude/longitude to a readable address."""

    session = async_get_clientsession(hass)

    params = {
        "lat": str(latitude),
        "lon": str(longitude),
        "format": "jsonv2",
        "addressdetails": "1",
        "zoom": "18",
    }

    headers = {
        "User-Agent": "HomeAssistant-PleosVehicle/1.0"
    }

    try:
        async with session.get(
            NOMINATIM_URL,
            params=params,
            headers=headers,
            timeout=ClientTimeout(total=15),
        ) as response:
            response.raise_for_status()
            result = await response.json()

        if not isinstance(result, dict):
            return None

        return result

    except (ClientError, TimeoutError, ValueError) as err:
        _LOGGER.warning(
            "Reverse geocoding failed for %s,%s: %s",
            latitude,
            longitude,
            err,
        )
        return None
