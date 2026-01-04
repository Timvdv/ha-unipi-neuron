import asyncio
import logging
import aiohttp
from websockets.exceptions import ConnectionClosedError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant import config_entries
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import DOMAIN
from .config_flow import UnipiNeuronConfigFlow
from .evok_ws_client import *

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["binary_sensor", "light", "sensor", "cover"]

def cache_getter(self):
    if not hasattr(self, '_cache'):
        self._cache = {}
    return self._cache

UnipiEvokWsClient.cache = property(cache_getter)

def name_getter(self):
    return getattr(self, '_name', "UniPi")
UnipiEvokWsClient.name = property(name_getter)

async def fetch_rest_all(self):
    url = f"http://{self._ip_addr}/rest/all"
    _LOGGER.debug("Fetching device info from %s", url)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as resp:
                data = await resp.json()
    except Exception as err:
        _LOGGER.warning("Could not fetch /rest/all from %s: %s", url, err)
        return

    for dev_info in data:
        device_type = dev_info.get("dev")
        circuit = dev_info.get("circuit")
        if device_type and circuit is not None:
            self.cache[(device_type, circuit)] = dev_info

    _LOGGER.debug("Cache after /rest/all fetch: %s", self.cache)

UnipiEvokWsClient.fetch_rest_all = fetch_rest_all

original_evok_full_state_sync = UnipiEvokWsClient.evok_full_state_sync

async def evok_full_state_sync_with_rest(self):
    await original_evok_full_state_sync(self)
    await self.fetch_rest_all()

UnipiEvokWsClient.evok_full_state_sync = evok_full_state_sync_with_rest

def evok_state_get(self, device, circuit):
    return self.cache.get((device, circuit))

UnipiEvokWsClient.evok_state_get = evok_state_get

async def evok_connection(hass, neuron: UnipiEvokWsClient, reconnect_seconds: int):
    def evok_update_dispatch_send(name, device, circuit, payload):
        """Update cache and send dispatcher signal."""
        
        _LOGGER.debug("Incoming WebSocket message: %s/%s - %s", device, circuit, payload)
        
        # Update cache with new value
        cache_key = (device, circuit)
        current = neuron.cache.get(cache_key, {})
        if isinstance(payload, dict):
            merged = dict(current) if isinstance(current, dict) else {}
            value = payload.get("value")
            if isinstance(value, dict):
                merged.update(value)
            merged.update(payload)
            neuron.cache[cache_key] = merged
        else:
            if isinstance(current, dict):
                current["value"] = payload
                neuron.cache[cache_key] = current
            else:
                neuron.cache[cache_key] = {"value": payload}
        
        _LOGGER.debug("SENDING Dispatcher on %s %s with value %s", device, circuit, payload)
        async_dispatcher_send(hass, f"{DOMAIN}_{name}_{device}_{circuit}")

    """Maintain websocket connection and handle messages."""
    while True:
        try:
            if not await neuron.evok_connect():
                _LOGGER.warning("Connection failed to %s, retrying in %ds", neuron.name, reconnect_seconds)
                await asyncio.sleep(reconnect_seconds)
                continue

            _LOGGER.info("Connected to %s", neuron.name)
            await neuron.evok_register_default_filter_dev(use_default_filter=True)
            await neuron.evok_full_state_sync()

            while True:
                if not await neuron.evok_receive(True, evok_update_dispatch_send):
                    break

        except ConnectionClosedError:
            _LOGGER.warning("Connection closed for %s", neuron.name)
        except Exception as e:
            _LOGGER.error("Unexpected error for %s: %s", neuron.name, str(e))

        _LOGGER.info("Reconnecting to %s in %ds", neuron.name, reconnect_seconds)
        await asyncio.sleep(reconnect_seconds)

async def async_setup(hass: HomeAssistant, config: dict):
    hass.data.setdefault(DOMAIN, {})

    if DOMAIN in config:
        for entry in config[DOMAIN]:
            hass.async_create_task(
                hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": config_entries.SOURCE_IMPORT},
                    data=entry
                )
            )
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = entry.data
    ip_addr = data.get("ip_address")
    dev_name = data.get("name", "UniPi")
    reconnect_time = data.get("reconnect_time", 30)

    neuron = UnipiEvokWsClient(ip_addr, data.get("type", "CUSTOM"), dev_name)
    neuron._ip_addr = ip_addr
    neuron._name = dev_name
    neuron._devtype = data.get("type", "CUSTOM")

    try:
        if not await neuron.evok_connect():
            raise ConfigEntryNotReady(f"Could not connect to {ip_addr}")
            
        await neuron.evok_full_state_sync()
    except Exception as err:
        raise ConfigEntryNotReady(f"Connection error: {err}") from err

    hass.data[DOMAIN][entry.entry_id] = neuron
    hass.loop.create_task(evok_connection(hass, neuron, reconnect_time))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    neuron = hass.data[DOMAIN].pop(entry.entry_id, None)
    if neuron:
        await neuron.evok_close()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
