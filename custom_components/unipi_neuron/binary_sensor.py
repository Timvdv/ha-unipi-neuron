"""Support for Unipi product line binary sensors."""
import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
):
    """Set up Unipi binary sensors for a config entry."""
    unipi_hub = hass.data[DOMAIN].get(entry.entry_id)
    if not unipi_hub:
        _LOGGER.error("No UniPi client found for entry %s", entry.title)
        return

    sensors = []
    for (device, circuit), value in unipi_hub.cache.items():
        if device in ("input", "di"):
            if isinstance(value, dict) and "alias" in value:
                name = value["alias"]
                if name.startswith("al_"):
                    name = name[3:]
            else:
                name = f"UniPi {device} {circuit}"
            sensors.append(UnipiBinarySensor(unipi_hub, entry.unique_id, name, circuit, device))

    if sensors:
        async_add_entities(sensors)
    else:
        _LOGGER.debug("No binary sensor devices found for UniPi '%s'", unipi_hub.name)

class UnipiBinarySensor(BinarySensorEntity):
    """Representation of binary sensors on UniPi Device."""

    def __init__(self, unipi_hub, entry_unique_id, name, circuit, device):
        """Initialize Unipi binary sensor."""
        self._unipi_hub = unipi_hub
        self._attr_name = name
        self._circuit = circuit
        self._device = device
        self._state = None
        self._attr_unique_id = f"{entry_unique_id}_{device}_{circuit}"
        self._attr_friendly_name = self._attr_unique_id

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info so HA groups all sensors under one device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._unipi_hub.name)},
            name=self._unipi_hub.name,
            manufacturer="UniPi",
            model=self._unipi_hub._devtype,
        )

    @property
    def is_on(self):
        """Return True if the entity is on."""
        return self._state

    async def async_added_to_hass(self):
        """Register for dispatcher signals."""
        signal = f"{DOMAIN}_{self._unipi_hub.name}_{self._device}_{self._circuit}"
        _LOGGER.debug("Binary Sensor '%s': Connecting signal %s", self._attr_name, signal)
        async_dispatcher_connect(self.hass, signal, self._update_callback)
        self._update_callback()

    @callback
    def _update_callback(self):
        """State has changed"""
        raw_state = self._unipi_hub.evok_state_get(self._device, self._circuit)
        _LOGGER.debug("Binary Sensor '%s': Raw state received: %s", self._attr_name, raw_state)
        if isinstance(raw_state, dict):
            # Extract the 'value' field from the dictionary
            value = raw_state.get("value")
        else:
            value = raw_state
        _LOGGER.debug("Binary Sensor '%s': Extracted value: %s", self._attr_name, value)
        self._state = (value == 1)
        self.async_write_ha_state()