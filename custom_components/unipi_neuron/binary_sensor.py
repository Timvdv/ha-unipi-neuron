"""Support for Unipi product line binary sensors."""
import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, generate_entity_id
from homeassistant.util import slugify
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Map EVOK versions to their input device types
EVOK_INPUT_TYPES = {
    2: ["input"],
    3: ["di"]
}

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

    entry_unique_id = entry.unique_id or entry.entry_id
    device_name = entry.title or entry.data.get("name") or unipi_hub.name or entry.entry_id
    device_slug = slugify(device_name)

    sensors = []
    # Get EVOK version from device type
    evok_version = 3 if "M3" in unipi_hub._devtype else 2  # Adjust based on actual devtype
    
    for (device, circuit), value in unipi_hub.cache.items():
        if device in EVOK_INPUT_TYPES[evok_version]:
            if isinstance(value, dict) and "alias" in value:
                name = value["alias"]
                if name.startswith("al_"):
                    name = name[3:]
            else:
                name = f"UniPi {device} {circuit}"
            sensors.append(
                UnipiBinarySensor(hass, unipi_hub, entry_unique_id, device_slug, name, circuit, device)
            )

    if sensors:
        async_add_entities(sensors)
        _LOGGER.info("Added %d binary sensors for %s", len(sensors), unipi_hub.name)
    else:
        _LOGGER.debug("No binary sensor devices found for UniPi '%s'", unipi_hub.name)

class UnipiBinarySensor(BinarySensorEntity):
    """Representation of binary sensors on UniPi Device."""

    def __init__(self, hass, unipi_hub, entry_unique_id, device_slug, name, circuit, device):
        """Initialize Unipi binary sensor."""
        self._hass = hass
        self._unipi_hub = unipi_hub
        self._circuit = circuit
        self._device = device
        self._device_slug = device_slug
        self._attr_unique_id = f"{entry_unique_id}_{device}_{circuit}"
        self._attr_name = name
        self._state = None

        object_id = f"unipi_{self._device_slug}_{device}_{circuit}"
        self.entity_id = generate_entity_id("binary_sensor.{}", object_id, hass=self._hass)

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
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal, self._update_callback)
        )
        self._update_callback()

    @callback
    def _update_callback(self):
        """State has changed"""
        raw_state = self._unipi_hub.evok_state_get(self._device, self._circuit)
        _LOGGER.debug("Binary Sensor '%s': Raw state received: %s", self._attr_name, raw_state)
        
        # Handle list structures (unlikely but possible)
        if isinstance(raw_state, list) and len(raw_state) > 0:
            first_item = raw_state[0]
            if isinstance(first_item, dict):
                value = first_item.get("value")
            else:
                value = first_item
        elif isinstance(raw_state, dict):
            value = raw_state.get("value")
        else:
            value = raw_state

        # Convert to integer for reliable comparison
        try:
            int_value = int(float(value)) if value not in [None, ""] else 0
        except (TypeError, ValueError):
            int_value = 0
            _LOGGER.warning("Invalid value for binary sensor '%s': %s", self._attr_name, value)
            
        self._state = int_value == 1
        self.async_write_ha_state()
