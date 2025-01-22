"""Platform for cover integration via Unipi."""
import logging
from datetime import datetime, timedelta

from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_call_later

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STATE_IDLE = "idle"
OPER_STATE_IDLE = STATE_IDLE
OPER_STATE_CLOSING = "closing"
OPER_STATE_OPENING = "opening"
OPER_STATE_ERROR = "error"

class UnipiCover(CoverEntity):
    """Representation of a UniPi cover."""

    def __init__(self, unipi_hub, entry_unique_id, name, port_up, port_down, full_close_time, full_open_time, tilt_change_time, min_reverse_time):
        """Initialize the cover."""
        self._unipi_hub = unipi_hub
        self._attr_name = name
        self._port_up = port_up
        self._port_down = port_down
        self._full_close_time = full_close_time
        self._full_open_time = full_open_time
        self._tilt_change_time = tilt_change_time
        self._min_reverse_time = min_reverse_time
        self._attr_unique_id = f"{entry_unique_id}_cover_{port_up}_{port_down}"
        self._state = OPER_STATE_IDLE
        self._position = None
        self._tilt_value = None
        self._time_last_movement_start = 0
        self._stop_cover_timer = None
        self._attr_friendly_name = self._attr_unique_id

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._unipi_hub.name)},
            name=self._unipi_hub.name,
            manufacturer="UniPi",
            model=self._unipi_hub._devtype,
        )

    @property
    def supported_features(self):
        """Flag supported features."""
        return CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP | CoverEntityFeature.SET_POSITION

    @property
    def is_closed(self):
        """Return if the cover is closed."""
        return self._position == 0

    @property
    def is_opening(self):
        """Return true if the cover is opening."""
        return self._state == OPER_STATE_OPENING

    @property
    def is_closing(self):
        """Return true if the cover is closing."""
        return self._state == OPER_STATE_CLOSING

    @property
    def current_cover_position(self):
        """Return current position of cover."""
        return self._position

    async def async_open_cover(self, **kwargs):
        """Open the cover."""
        if self._state == OPER_STATE_CLOSING:
            await self.async_stop_cover()
        await self._set_relay_state(self._port_up, True)
        self._state = OPER_STATE_OPENING
        self._time_last_movement_start = datetime.now()
        self.async_write_ha_state()

    async def async_close_cover(self, **kwargs):
        """Close the cover."""
        if self._state == OPER_STATE_OPENING:
            await self.async_stop_cover()
        await self._set_relay_state(self._port_down, True)
        self._state = OPER_STATE_CLOSING
        self._time_last_movement_start = datetime.now()
        self.async_write_ha_state()

    async def async_stop_cover(self, **kwargs):
        """Stop the cover."""
        self._cancel_timer()
        await self._set_relay_state(self._port_up, False)
        await self._set_relay_state(self._port_down, False)
        self._state = OPER_STATE_IDLE
        self.async_write_ha_state()

    async def _set_relay_state(self, port, state):
        """Set relay state."""
        await self._unipi_hub.evok_send("relay", port, "1" if state else "0")

    def _cancel_timer(self):
        """Cancel any pending timers."""
        if self._stop_cover_timer:
            self._stop_cover_timer()
            self._stop_cover_timer = None

    async def async_added_to_hass(self):
        """Register callbacks."""
        signals = [
            f"{DOMAIN}_{self._unipi_hub.name}_relay_{self._port_up}",
            f"{DOMAIN}_{self._unipi_hub.name}_relay_{self._port_down}"
        ]
        for signal in signals:
            async_dispatcher_connect(self.hass, signal, self._update_callback)

    @callback
    def _update_callback(self):
        """Handle state updates from UniPi."""
        up_state = self._unipi_hub.evok_state_get("relay", self._port_up) or {}
        down_state = self._unipi_hub.evok_state_get("relay", self._port_down) or {}
        
        new_state = OPER_STATE_IDLE
        if up_state.get("value") == 1:
            new_state = OPER_STATE_OPENING
        elif down_state.get("value") == 1:
            new_state = OPER_STATE_CLOSING
            
        if new_state != self._state:
            self._state = new_state
            self.async_write_ha_state()

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
):
    """Set up UniPi covers from a config entry."""
    unipi_hub = hass.data[DOMAIN].get(entry.entry_id)
    if not unipi_hub:
        _LOGGER.error("No UniPi client found for entry %s", entry.title)
        return

    # In real implementation you would get cover configs from entry data
    # For demo purposes we'll create one hardcoded cover
    covers = [
        UnipiCover(
            unipi_hub=unipi_hub,
            entry_unique_id=entry.unique_id,
            name="Example Cover",
            port_up="1_01",
            port_down="1_02",
            full_close_time=40,
            full_open_time=40,
            tilt_change_time=1.5,
            min_reverse_time=1
        )
    ]
    
    async_add_entities(covers)
    _LOGGER.debug("Added %d UniPi covers for entry '%s'", len(covers), entry.title)