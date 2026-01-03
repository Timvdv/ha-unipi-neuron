"""Platform for light integration via Unipi."""
import logging
import asyncio

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    LightEntity,
    ColorMode
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, generate_entity_id
from homeassistant.util import slugify
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from websockets.exceptions import ConnectionClosedError

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

LIGHT_DEVICES = ("relay", "led", "ro", "do")

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    """Set up the Unipi Lights from a config entry."""
    unipi_hub = hass.data[DOMAIN].get(entry.entry_id)
    if not unipi_hub:
        _LOGGER.error("No UniPi client found for entry %s", entry.title)
        return

    entry_unique_id = entry.unique_id or entry.entry_id
    device_name = entry.title or entry.data.get("name") or unipi_hub.name or entry.entry_id
    device_slug = slugify(device_name)

    lights = []
    for (device, circuit), value in unipi_hub.cache.items():
        if device in LIGHT_DEVICES:
            mode = "on_off"
            if isinstance(value, dict) and "alias" in value:
                name = value["alias"]
                if name.startswith("al_"):
                    name = name[3:]
            else:
                name = f"UniPi Light {device} {circuit}"
            lights.append(
                UnipiLight(hass, unipi_hub, entry_unique_id, device_slug, name, circuit, device, mode)
            )

    async_add_entities(lights)
    _LOGGER.debug("Added %d UniPi lights for entry '%s'", len(lights), entry.title)


class UnipiLight(LightEntity):
    """Representation of a Light attached to a UniPi relay or digital output."""

    def __init__(self, hass, unipi_hub, entry_unique_id, device_slug, name, circuit, device, mode):
        """Initialize the UniPi Light."""
        self._hass = hass
        self._unipi_hub = unipi_hub
        self._circuit = circuit
        self._device = device
        self._dimmable = (mode == "pwm")
        self._device_slug = device_slug
        self._attr_unique_id = f"{entry_unique_id}_{device}_{circuit}"
        self._attr_name = name
        self._lock = asyncio.Lock()
        
        object_id = f"unipi_{self._device_slug}_{device}_{circuit}"
        self.entity_id = generate_entity_id("light.{}", object_id, hass=self._hass)

        if self._dimmable:
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.BRIGHTNESS
            self._brightness = 0
        else:
            self._attr_supported_color_modes = {ColorMode.ONOFF}
            self._attr_color_mode = ColorMode.ONOFF
            self._brightness = None

        self._state = False

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information for this entity to show up as a device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._unipi_hub.name)},
            name=self._unipi_hub.name,
            manufacturer="UniPi",
            model=self._unipi_hub._devtype,
        )

    @property
    def is_on(self):
        """Return true if light is on."""
        return self._state

    @property
    def brightness(self):
        """Return the brightness of the light (0..255), or None if not dimmable."""
        return self._brightness

    async def async_turn_on(self, **kwargs):
        """Instruct the light to turn on."""
        async with self._lock:
            try:
                if self._dimmable:
                    new_brightness = kwargs.get(ATTR_BRIGHTNESS, 255)
                    duty_value = round(new_brightness / 255 * 100)
                    _LOGGER.info(
                        "Turn ON dimmable light '%s' brightness=%d => duty=%d%%",
                        self._attr_name, new_brightness, duty_value
                    )
                    dict_to_send = {"pwm_duty": str(duty_value)}
                    await self._unipi_hub.evok_send(self._device, self._circuit, dict_to_send)
                    # Update cache immediately
                    self._unipi_hub.cache[(self._device, self._circuit)] = {'value': duty_value}
                    self._brightness = new_brightness
                    self._state = True
                else:
                    _LOGGER.info("Turn ON light '%s' (on_off mode)", self._attr_name)
                    await self._unipi_hub.evok_send(self._device, self._circuit, "1")
                    # Update cache immediately
                    self._unipi_hub.cache[(self._device, self._circuit)] = {'value': 1}
                    self._state = True

                self.async_write_ha_state()
            except ConnectionClosedError as e:
                _LOGGER.warning("Connection closed when turning on light '%s': %s", self._attr_name, e)

    async def async_turn_off(self, **kwargs):
        """Instruct the light to turn off."""
        async with self._lock:
            try:
                if self._dimmable:
                    _LOGGER.info("Turn OFF dimmable light '%s' => set duty=0%%", self._attr_name)
                    dict_to_send = {"pwm_duty": "0"}
                    await self._unipi_hub.evok_send(self._device, self._circuit, dict_to_send)
                    # Update cache immediately
                    self._unipi_hub.cache[(self._device, self._circuit)] = {'value': 0}
                    self._brightness = 0
                    self._state = False
                else:
                    _LOGGER.info("Turn OFF light '%s'", self._attr_name)
                    await self._unipi_hub.evok_send(self._device, self._circuit, "0")
                    # Update cache immediately
                    self._unipi_hub.cache[(self._device, self._circuit)] = {'value': 0}
                    self._state = False

                self.async_write_ha_state()
            except ConnectionClosedError as e:
                _LOGGER.warning("Connection closed when turning off light '%s': %s", self._attr_name, e)

    async def async_added_to_hass(self):
        """Subscribe to dispatch updates for real-time changes."""
        signal = f"{DOMAIN}_{self._unipi_hub.name}_{self._device}_{self._circuit}"
        _LOGGER.debug("Connecting signal: %s for UniPi Light '%s'", signal, self._attr_name)
        async_dispatcher_connect(self.hass, signal, self._update_callback)
        self._update_callback()

    @callback
    def _update_callback(self):
        """Receive update from the hub (dispatcher)."""
        raw_state = self._unipi_hub.evok_state_get(self._device, self._circuit)
        if isinstance(raw_state, dict):
            raw_value = raw_state.get("value", 0)
        else:
            raw_value = raw_state if raw_state is not None else 0

        if self._dimmable:
            if isinstance(raw_value, (int, float)) and raw_value > 0:
                self._brightness = min(255, int(raw_value / 100 * 255))
                self._state = True
            else:
                self._brightness = 0
                self._state = False
        else:
            self._state = bool(raw_value)

        self.async_write_ha_state()
