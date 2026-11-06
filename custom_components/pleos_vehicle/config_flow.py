"""Config flow for the Pleos Vehicle Data integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import PleosAuthError, PleosClient, PleosError, PleosTokenError
from .const import (
    BRANDS,
    CONF_BATTERY_CAPACITY,
    CONF_BRAND,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_ESTIMATED_CHARGING,
    CONF_TANK_CAPACITY,
    CONF_VEHICLES,
    DEFAULT_BATTERY_CAPACITY,
    DEFAULT_BRAND,
    DEFAULT_TANK_CAPACITY,
    DOMAIN,
    MAX_BATTERY_CAPACITY,
    MAX_TANK_CAPACITY,
    MIN_BATTERY_CAPACITY,
    MIN_TANK_CAPACITY,
    BATTERY_CAPACITY_STEP,
    TANK_CAPACITY_STEP,
)
from .coordinator import (
    battery_capacity_from_entry,
    estimated_charging_from_entry,
    tank_capacity_from_entry,
)

BRAND_OPTIONS = [
    SelectOptionDict(value=value, label=label) for value, label in BRANDS.items()
]

CREDENTIAL_FIELDS = {
    vol.Required(CONF_CLIENT_ID): str,
    vol.Required(CONF_CLIENT_SECRET): TextSelector(
        TextSelectorConfig(type=TextSelectorType.PASSWORD)
    ),
}

TANK_CAPACITY_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=MIN_TANK_CAPACITY,
        max=MAX_TANK_CAPACITY,
        step=TANK_CAPACITY_STEP,
        unit_of_measurement=UnitOfVolume.LITERS,
        mode=NumberSelectorMode.BOX,
    )
)

BATTERY_CAPACITY_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=MIN_BATTERY_CAPACITY,
        max=MAX_BATTERY_CAPACITY,
        step=BATTERY_CAPACITY_STEP,
        unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        mode=NumberSelectorMode.BOX,
    )
)

STEP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BRAND, default=DEFAULT_BRAND): SelectSelector(
            SelectSelectorConfig(options=BRAND_OPTIONS, mode=SelectSelectorMode.DROPDOWN)
        ),
        **CREDENTIAL_FIELDS,
        vol.Required(
            CONF_TANK_CAPACITY, default=DEFAULT_TANK_CAPACITY
        ): TANK_CAPACITY_SELECTOR,
        vol.Required(
            CONF_BATTERY_CAPACITY, default=DEFAULT_BATTERY_CAPACITY
        ): BATTERY_CAPACITY_SELECTOR,
    }
)

REAUTH_SCHEMA = vol.Schema(CREDENTIAL_FIELDS)


async def _async_fetch_vehicles(
    hass: HomeAssistant, brand: str, client_id: str, client_secret: str
) -> list[dict[str, str]]:
    """Validate the credentials and return the vehicles they can read."""
    client = PleosClient(
        async_get_clientsession(hass), client_id, client_secret, brand
    )
    vehicles = await client.async_get_vehicles()
    return [
        {
            "vin": vehicle["vin"],
            "nickname": vehicle.get("nickname") or vehicle["vin"],
            "name": vehicle.get("name") or "",
            "sellname": vehicle.get("sellname") or "",
        }
        for vehicle in vehicles
        if vehicle.get("vin")
    ]


class PleosConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Pleos Vehicle Data."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the brand and the Pleos API key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                vehicles = await _async_fetch_vehicles(
                    self.hass,
                    user_input[CONF_BRAND],
                    user_input[CONF_CLIENT_ID],
                    user_input[CONF_CLIENT_SECRET],
                )
            except PleosAuthError:
                errors["base"] = "invalid_auth"
            except PleosTokenError:
                errors["base"] = "token_failed"
            except PleosError:
                errors["base"] = "cannot_connect"
            else:
                if not vehicles:
                    errors["base"] = "no_vehicles"
                else:
                    await self.async_set_unique_id(user_input[CONF_CLIENT_ID])
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"Pleos Vehicle Data ({BRANDS[user_input[CONF_BRAND]]})",
                        data={
                            CONF_BRAND: user_input[CONF_BRAND],
                            CONF_CLIENT_ID: user_input[CONF_CLIENT_ID],
                            CONF_CLIENT_SECRET: user_input[CONF_CLIENT_SECRET],
                            CONF_VEHICLES: vehicles,
                        },
                        options={
                            CONF_TANK_CAPACITY: user_input[CONF_TANK_CAPACITY],
                            CONF_BATTERY_CAPACITY: user_input[CONF_BATTERY_CAPACITY],
                        },
                    )
        return self.async_show_form(
            step_id="user", data_schema=STEP_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PleosOptionsFlow:
        """Create the options flow."""
        return PleosOptionsFlow()

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Start re-authentication after Pleos rejected the credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new Client ID and Client Secret."""
        errors: dict[str, str] = {}
        entry: ConfigEntry = self._get_reauth_entry()
        if user_input is not None:
            brand = entry.data.get(CONF_BRAND, DEFAULT_BRAND)
            try:
                vehicles = await _async_fetch_vehicles(
                    self.hass,
                    brand,
                    user_input[CONF_CLIENT_ID],
                    user_input[CONF_CLIENT_SECRET],
                )
            except PleosAuthError:
                errors["base"] = "invalid_auth"
            except PleosTokenError:
                errors["base"] = "token_failed"
            except PleosError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={**user_input, CONF_VEHICLES: vehicles},
                    reason="reauth_successful",
                )
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=REAUTH_SCHEMA, errors=errors
        )


class PleosOptionsFlow(OptionsFlow):
    """Handle the Pleos Vehicle Data options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change how the Pleos data is interpreted."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_TANK_CAPACITY,
                    default=tank_capacity_from_entry(self.config_entry),
                ): TANK_CAPACITY_SELECTOR,
                vol.Required(
                    CONF_BATTERY_CAPACITY,
                    default=battery_capacity_from_entry(self.config_entry),
                ): BATTERY_CAPACITY_SELECTOR,
                vol.Required(
                    CONF_ESTIMATED_CHARGING,
                    default=estimated_charging_from_entry(self.config_entry),
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
