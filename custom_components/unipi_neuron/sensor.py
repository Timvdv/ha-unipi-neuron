import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

MEASUREMENT_MAPPING = {
    "temp": {"unit": "°C", "device_class": "temperature"},
    "humidity": {"unit": "%", "device_class": "humidity"},
    "vad": {"unit": "V", "device_class": None},
    "vdd": {"unit": "V", "device_class": None},
}

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    """Set up UniPi sensors based on a config entry."""
    unipi_hub = hass.data[DOMAIN].get(entry.entry_id)
    if not unipi_hub:
        _LOGGER.error("No UniPi client found for entry %s", entry.title)
        return

    sensors = []
    for (device, circuit), value in unipi_hub.cache.items():
        alias = None
        if isinstance(value, dict) and "alias" in value:
            alias = value["alias"]
            if alias.startswith("al_"):
                alias = alias[3:]

        if device == "temp":
            name = alias if alias else f"UniPi {device} {circuit}"
            sensors.append(Unipi1WireSensor(unipi_hub, entry.unique_id, name, device, circuit, measurement="temp"))
        elif device == "1wdevice" and isinstance(value, dict):
            for measurement in MEASUREMENT_MAPPING.keys():
                if measurement in value:
                    meas_name = f"{alias} {measurement}" if alias else f"UniPi {device} {circuit} {measurement}"
                    sensors.append(Unipi1WireSensor(unipi_hub, entry.unique_id, meas_name, device, circuit, measurement))
    if sensors:
        async_add_entities(sensors)
    else:
        _LOGGER.debug("No 1-wire or temp sensors found for UniPi '%s'", unipi_hub.name)

class Unipi1WireSensor(SensorEntity):
    """Representation of a UniPi 1-Wire or temp sensor for a specific measurement."""

    def __init__(self, unipi_hub, entry_unique_id, name, device, circuit, measurement):
        """Initialize the sensor."""
        self._unipi_hub = unipi_hub
        self._device = device
        self._circuit = circuit
        self._measurement = measurement
        self._attr_unique_id = f"{entry_unique_id}_{device}_{circuit}_{measurement}"
        self._attr_name = self._attr_unique_id
        self._attr_friendly_name = name
        mapping_info = MEASUREMENT_MAPPING.get(measurement, {"unit": None, "device_class": None})
        self._attr_native_unit_of_measurement = mapping_info["unit"]
        self._attr_device_class = mapping_info["device_class"]
        self._attr_native_value = None

    @property
    def device_info(self) -> DeviceInfo:
        """Link this sensor to a device in the device registry."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._unipi_hub.name)},
            name=self._unipi_hub.name,
            manufacturer="UniPi",
            model=self._unipi_hub._devtype,
        )

    async def async_added_to_hass(self):
        """Register dispatcher signal for updates."""
        signal = f"{DOMAIN}_{self._unipi_hub.name}_{self._device}_{self._circuit}"
        _LOGGER.debug("UniPi Sensor '%s' listening on dispatcher signal: %s", self._attr_name, signal)
        async_dispatcher_connect(self.hass, signal, self._update_callback)
        self._update_callback()

    @callback
    def _update_callback(self):
        """Receive update from UniPi hub dispatcher and refresh state."""
        raw_value = self._unipi_hub.evok_state_get(self._device, self._circuit)
        if raw_value is None:
            self._attr_available = False
        else:
            self._attr_available = True
            try:
                if self._device == "temp":
                    self._attr_native_value = float(raw_value.get("value", 0))
                elif isinstance(raw_value, dict):
                    if self._measurement in raw_value:
                        self._attr_native_value = float(raw_value.get(self._measurement, 0))
                    else:
                        self._attr_native_value = float(raw_value.get("value", 0))
                else:
                    self._attr_native_value = float(raw_value)
            except (TypeError, ValueError):
                _LOGGER.warning(
                    "Could not parse sensor reading '%s' for measurement '%s' from %s",
                    raw_value, self._measurement, self._attr_name
                )
                self._attr_native_value = None
        self.async_write_ha_state()