"""Read-only client for the Pleos Vehicle Data API."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from .const import API_BASE_URL, REQUEST_TIMEOUT

VEHICLE_ENDPOINTS = ("batteries", "driving", "powertrains", "status", "locations")


class PleosError(Exception):
    """Base error for the Pleos API."""


class PleosAuthError(PleosError):
    """The client ID or client secret was rejected."""


class PleosConnectionError(PleosError):
    """The Pleos API could not be reached."""


class PleosTokenError(PleosError):
    """Pleos refused to issue an access token for this key."""


def _error_code(body: dict[str, Any]) -> str:
    """Return Pleos's short error code for a log message, if it sent one."""
    error = body.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    return f" ({code})" if isinstance(code, str) and code else ""


async def _async_read_body(response: aiohttp.ClientResponse) -> dict[str, Any]:
    try:
        body = await response.json(content_type=None)
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


class PleosClient:
    """Authenticated read-only client for one Pleos API key."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        client_id: str,
        client_secret: str,
        brand: str,
    ) -> None:
        self._session = session
        self._client_id = client_id
        self._client_secret = client_secret
        self.brand = brand
        self._token: str | None = None

    async def async_get_vehicles(self) -> list[dict[str, Any]]:
        """Return the vehicles this API key has access to."""
        data = await self._async_request("/vehicles/consent")
        return list(data.get("vehicles") or [])

    async def async_get_vehicle_data(self, vin: str) -> dict[str, dict[str, Any]]:
        """Return the data block of each read endpoint for one vehicle."""
        result: dict[str, dict[str, Any]] = {}
        for name in VEHICLE_ENDPOINTS:
            result[name] = await self._async_request(f"/vehicles/{vin}/{name}")
        return result

    async def _async_request(self, path: str) -> dict[str, Any]:
        """Call an authorized GET endpoint, renewing the token once if rejected."""
        if self._token is None:
            await self._async_fetch_token()
        status, body = await self._async_call("GET", path, authorized=True)
        if status in (401, 403):
            await self._async_fetch_token()
            status, body = await self._async_call("GET", path, authorized=True)
            if status in (401, 403):
                raise PleosError(
                    f"Pleos API refused the renewed token (HTTP {status} for {path})"
                )
        if status >= 400 or "error" in body:
            raise PleosError(
                f"Pleos API returned HTTP {status} for {path}{_error_code(body)}"
            )
        return body.get("data") or {}

    def reset_token(self) -> None:
        """Forget the access token so the next request fetches a new one."""
        self._token = None

    async def _async_fetch_token(self) -> None:
        status, body = await self._async_call(
            "POST",
            "/auth/personal-token",
            {"clientId": self._client_id, "clientSecret": self._client_secret},
            authorized=False,
        )
        if status in (400, 401, 403):
            raise PleosAuthError("Client ID or client secret rejected")
        token = (body.get("data") or {}).get("accessToken")
        if status >= 400 or not token:
            raise PleosTokenError(
                f"Token request failed with HTTP {status}{_error_code(body)}"
            )
        self._token = token

    async def _async_call(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        authorized: bool,
    ) -> tuple[int, dict[str, Any]]:
        headers = {"Brand": self.brand}
        if authorized:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.request(
                    method,
                    f"{API_BASE_URL}{path}",
                    headers=headers,
                    json=payload,
                ) as response:
                    return response.status, await _async_read_body(response)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise PleosConnectionError(f"Cannot reach the Pleos API: {err}") from err
