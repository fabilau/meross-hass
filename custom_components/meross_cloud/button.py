import logging
from typing import Dict

from meross_iot.controller.subdevice import Gs559aSensor
from meross_iot.manager import MerossManager
from meross_iot.model.http.device import HttpDeviceInfo

from homeassistant.components.button import ButtonEntity, ButtonDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from . import MerossDevice
from .common import (DOMAIN, MANAGER, HA_BUTTON, DEVICE_LIST_COORDINATOR)

_LOGGER = logging.getLogger(__name__)


class Gs559aTestButton(MerossDevice, ButtonEntity):
    """Button to initiate an alarm sound test on GS559A"""
    _device: Gs559aSensor

    def __init__(self, device: Gs559aSensor, device_list_coordinator: DataUpdateCoordinator[Dict[str, HttpDeviceInfo]], channel: int = 0):
        super().__init__(
            device=device,
            channel=channel,
            device_list_coordinator=device_list_coordinator,
            platform=HA_BUTTON,
            supplementary_classifiers=["test_button"])

        self._attr_device_class = ButtonDeviceClass.IDENTIFY
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_translation_key = "alarm_test"

    async def async_press(self) -> None:
        """Handle button press to trigger alarm test."""
        _LOGGER.info("Triggering alarm test on %s", self.name)
        await self._device.async_test_alarm(timeout=5.0)


class Gs559aMuteButton(MerossDevice, ButtonEntity):
    """Button to mute / hush an active alarm on GS559A"""
    _device: Gs559aSensor

    def __init__(self, device: Gs559aSensor, device_list_coordinator: DataUpdateCoordinator[Dict[str, HttpDeviceInfo]], channel: int = 0):
        super().__init__(
            device=device,
            channel=channel,
            device_list_coordinator=device_list_coordinator,
            platform=HA_BUTTON,
            supplementary_classifiers=["mute_button"])

        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_translation_key = "alarm_mute"

    async def async_press(self) -> None:
        """Handle button press to mute alarm."""
        _LOGGER.info("Muting alarm on %s", self.name)
        await self._device.async_mute_alarm(timeout=5.0)


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    def entity_adder_callback():
        """Discover and add button entities"""
        manager: MerossManager = hass.data[DOMAIN][MANAGER]
        coordinator = hass.data[DOMAIN][DEVICE_LIST_COORDINATOR]
        devices = manager.find_devices()

        new_entities = []

        # Handle GS559A smoke detector buttons (Test and Mute)
        smoke_sensors = filter(lambda d: isinstance(d, Gs559aSensor), devices)
        for sms in smoke_sensors:
            channels = [c.index for c in sms.channels] if len(sms.channels) > 0 else [0]
            for channel_index in channels:
                new_entities.append(
                    Gs559aTestButton(device=sms, device_list_coordinator=coordinator, channel=channel_index))
                new_entities.append(
                    Gs559aMuteButton(device=sms, device_list_coordinator=coordinator, channel=channel_index))

        unique_new_devs = filter(lambda d: d.unique_id not in hass.data[DOMAIN]["ADDED_ENTITIES_IDS"], new_entities)
        async_add_entities(list(unique_new_devs), True)

    coordinator = hass.data[DOMAIN][DEVICE_LIST_COORDINATOR]
    coordinator.async_add_listener(entity_adder_callback)
    entity_adder_callback()


def setup_platform(hass, config, async_add_entities, discovery_info=None):
    pass
