import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME, CONF_TYPE
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN  # Ensure we have DOMAIN = "unipi_neuron"


@callback
def unipi_neuron_entries(hass: HomeAssistant):
    """Return existing entry names for unipi_neuron domain."""
    return {
        entry.data[CONF_NAME] for entry in hass.config_entries.async_entries(DOMAIN)
    }


class UnipiNeuronConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the Unipi Neuron integration."""

    VERSION = 1

    def __init__(self):
        self._name: str | None = None
        self._ip_address: str | None = None
        self._errors: dict = {}

    async def async_step_import(self, user_input):
        """Handle configuration import from YAML."""
        existing = unipi_neuron_entries(self.hass)
        if user_input[CONF_NAME] in existing:
            return self.async_abort(reason="name_exists")
        return self.async_create_entry(
            title=user_input[CONF_NAME],
            data={
                "name": user_input[CONF_NAME],
                "ip_address": user_input[CONF_IP_ADDRESS],
                "reconnect_time": user_input.get("reconnect_time", 30),
                "type": user_input.get(CONF_TYPE, "CUSTOM"),
            },
        )

    async def async_step_user(self, user_input=None):
        """Handle the initial step initiated by the user (manual entry)."""
        self._errors = {}
        if user_input is not None:
            existing = unipi_neuron_entries(self.hass)
            if user_input[CONF_NAME] in existing:
                self._errors["base"] = "name_exists"
            else:
                # Go ahead and create the entry
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        "name": user_input[CONF_NAME],
                        "ip_address": user_input[CONF_IP_ADDRESS],
                        "reconnect_time": user_input.get("reconnect_time", 30),
                        "type": user_input.get(CONF_TYPE, "CUSTOM"),
                    },
                )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_NAME): cv.string,
                vol.Required(CONF_IP_ADDRESS): cv.string,
                vol.Optional("reconnect_time", default=30): cv.positive_int,
                vol.Optional(CONF_TYPE, default="CUSTOM"): cv.string,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=self._errors
        )

    async def async_step_zeroconf(self, discovery_info: dict):
        """
        Handle discovery via zeroconf (mDNS).
        discovery_info typically has keys like 'host', 'addresses', 'hostname', 'type', etc.
        """
        self._errors = {}
        host = discovery_info.get("host")
        if not host:
            addresses = discovery_info.get("addresses")
            if addresses:
                host = addresses[0]
        if not host:
            return self.async_abort(reason="cannot_connect")

        discovered_name = discovery_info.get("name", f"UniPi_{host}")
        self._name = discovered_name
        self._ip_address = host

        # Set a unique ID so that we don't add duplicates
        await self.async_set_unique_id(self._ip_address, raise_on_progress=False)
        self._abort_if_unique_id_configured()

        # We proceed directly to create the config entry or confirm
        return await self.async_step_discovery_confirm()

    async def async_step_ssdp(self, discovery_info: dict):
        """
        Handle discovery via SSDP.
        discovery_info might have 'ssdp_location' or 'ssdp_st' etc.
        We'll parse out a host from the location if possible.
        """
        self._errors = {}
        location = discovery_info.get("ssdp_location")
        host = None
        if location and "://" in location:
            host_part = location.split("//", 1)[1]
            host = host_part.split("/", 1)[0].split(":")[0]
        if not host:
            # Try to use addresses list if available
            addresses = discovery_info.get("addresses")
            if addresses:
                host = addresses[0]

        if not host:
            return self.async_abort(reason="cannot_connect")

        self._name = f"UniPi_{host}"
        self._ip_address = host

        # Set a unique ID so that we don't add duplicates
        await self.async_set_unique_id(self._ip_address, raise_on_progress=False)
        self._abort_if_unique_id_configured()

        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(self, user_input=None):
        """Automatically create an entry from discovered device without user confirmation."""
        if user_input is not None:
            # This would be used if you wanted a confirmation form;
            # but we’re doing automatic creation.
            pass

        return self.async_create_entry(
            title=self._name,
            data={
                "name": self._name,
                "ip_address": self._ip_address,
                "reconnect_time": 30,
                "type": "CUSTOM",
            },
        )