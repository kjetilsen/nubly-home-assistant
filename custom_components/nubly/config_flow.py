"""Config flow for the Nubly integration."""

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_DEVICE_ID,
    CONF_LIGHT_DISPLAY_NAME,
    CONF_LIGHT_ENTITY,
    CONF_MEDIA_ENTITY,
    CONF_ROOM_NAME,
    CONF_WEATHER_ENTITY,
    DOMAIN,
)
from .discovery import async_discover_devices

CONFIGURE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ROOM_NAME): str,
        vol.Required(CONF_MEDIA_ENTITY): str,
        vol.Required(CONF_LIGHT_ENTITY): str,
        vol.Required(CONF_LIGHT_DISPLAY_NAME): str,
        vol.Optional(CONF_WEATHER_ENTITY): EntitySelector(
            EntitySelectorConfig(domain="weather"),
        ),
    }
)


class NublyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Nubly."""

    VERSION = 2

    def __init__(self) -> None:
        self._discovered: list[str] = []
        self._device_id: str | None = None

    async def async_step_user(self, user_input=None):
        """Initial step: discover devices on MQTT."""
        found = await async_discover_devices(self.hass)
        self._discovered = sorted(found)

        if self._discovered:
            return await self.async_step_pick_device()
        return await self.async_step_manual()

    async def async_step_pick_device(self, user_input=None):
        """Let the user pick a discovered device."""
        if user_input is not None:
            self._device_id = user_input[CONF_DEVICE_ID]
            return await self.async_step_configure()

        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID): SelectSelector(
                    SelectSelectorConfig(
                        options=self._discovered,
                        mode=SelectSelectorMode.DROPDOWN,
                    ),
                ),
            }
        )
        return self.async_show_form(step_id="pick_device", data_schema=schema)

    async def async_step_manual(self, user_input=None):
        """Fallback when no devices were discovered: manual device_id entry."""
        if user_input is not None:
            self._device_id = user_input[CONF_DEVICE_ID]
            return await self.async_step_configure()

        schema = vol.Schema({vol.Required(CONF_DEVICE_ID): str})
        return self.async_show_form(step_id="manual", data_schema=schema)

    async def async_step_configure(self, user_input=None):
        """Collect room name, entities, and weather entity."""
        if user_input is not None:
            await self.async_set_unique_id(self._device_id)
            self._abort_if_unique_id_configured()

            data = {CONF_DEVICE_ID: self._device_id, **user_input}
            return self.async_create_entry(
                title=user_input[CONF_ROOM_NAME],
                data=data,
            )

        return self.async_show_form(
            step_id="configure",
            data_schema=CONFIGURE_SCHEMA,
        )
