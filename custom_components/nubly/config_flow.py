"""Config flow for the Nubly integration."""

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow

from .const import (
    CONF_DEVICE_ID,
    CONF_LIGHT_DISPLAY_NAME,
    CONF_LIGHT_ENTITY,
    CONF_MEDIA_ENTITY,
    CONF_ROOM_NAME,
    DOMAIN,
)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): str,
        vol.Required(CONF_ROOM_NAME): str,
        vol.Required(CONF_MEDIA_ENTITY): str,
        vol.Required(CONF_LIGHT_ENTITY): str,
        vol.Required(CONF_LIGHT_DISPLAY_NAME): str,
    }
)


class NublyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Nubly."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_DEVICE_ID])
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=user_input[CONF_ROOM_NAME],
                data=user_input,
            )

        return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA)
