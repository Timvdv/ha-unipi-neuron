import asyncio
import logging
import aiohttp
from websockets.exceptions import ConnectionClosedError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant import config_entries

from .const import DOMAIN
from .config_flow import UnipiNeuronConfigFlow

from evok_ws_client import *

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["binary_sensor", "light", "sensor"]

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

async def evok_connection(hass, neuron: UnipiEvokWsClient, reconnect_seconds: int, initial_connected: bool = False):
    from homeassistant.helpers.dispatcher import async_dispatcher_send

    def evok_update_dispatch_send(dev_name, device, circuit, value):
        _LOGGER.debug("Dispatcher signal: dev=%s circuit=%s -> %s", device, circuit, value)
        async_dispatcher_send(hass, f"{DOMAIN}_{dev_name}_{device}_{circuit}")

    first_run = initial_connected
    while True:
        if not first_run:
            await neuron.evok_close()
        first_run = False

        if not await neuron.evok_connect():
            _LOGGER.warning(
                "Could not connect to UniPi device '%s'. Retrying in %d seconds.",
                neuron.name, reconnect_seconds
            )
            await asyncio.sleep(reconnect_seconds)
            continue

        _LOGGER.info("Connected to UniPi device '%s' via Evok", neuron.name)
        await neuron.evok_full_state_sync()
        _LOGGER.debug("Cache after full_state_sync: %s", neuron.cache)

        while True:
            try:
                data = await neuron.evok_receive()
                # Handle both list and single dict responses
                messages = data if isinstance(data, list) else [data]
                
                for message in messages:
                    device = message.get("dev")
                    circuit = message.get("circuit")
                    value = message.get("value")
                    
                    if None in (device, circuit):
                        continue
                        
                    neuron.cache[(device, circuit)] = message
                    evok_update_dispatch_send(neuron.name, device, circuit, value)

            except ConnectionClosedError as e:
                _LOGGER.warning(
                    "Connection closed during receive from UniPi device '%s': %s",
                    neuron.name, e
                )
                break
            except Exception as e:
                _LOGGER.error("Unexpected error processing message: %s", str(e))
                break

            if not data:
                _LOGGER.warning(
                    "Connection lost to UniPi device '%s'. Reconnecting in %d seconds...",
                    neuron.name, reconnect_seconds
                )
                break
            
async def async_setup(hass: HomeAssistant, config: dict):
    _LOGGER.debug("async_setup called.")
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
    dev_type = data.get("type", "CUSTOM")
    reconnect_time = data.get("reconnect_time", 30)

    neuron = UnipiEvokWsClient(ip_addr, dev_type, dev_name)
    neuron._ip_addr = ip_addr
    neuron._name = dev_name
    neuron._devtype = dev_type

    try:
        connected = await neuron.evok_connect()
        if not connected:
            raise ConfigEntryNotReady(f"Could not connect to UniPi at {ip_addr}")
        await neuron.evok_full_state_sync()

        _LOGGER.debug("Cache right after initial full_state_sync: %s", neuron.cache)

    except Exception as err:
        raise ConfigEntryNotReady(f"Could not connect to UniPi at {ip_addr}: {err}") from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = neuron

    hass.loop.create_task(evok_connection(hass, neuron, reconnect_time, initial_connected=True))

    _LOGGER.debug("Forwarding setup to platforms: %s", PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    neuron = hass.data[DOMAIN].pop(entry.entry_id, None)
    if neuron:
        await neuron.evok_close()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return unload_ok