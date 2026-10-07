from __future__ import annotations

import logging
from datetime import timedelta
from typing import Dict, Optional, Union

from meross_iot.controller.device import BaseDevice
from meross_iot.controller.subdevice import Ms405Sensor, Ms200Sensor, Gs559aSensor
from meross_iot.manager import MerossManager
from meross_iot.model.enums import OnlineStatus, Namespace
from meross_iot.model.http.device import HttpDeviceInfo

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from . import MerossDevice
from .common import (DOMAIN, MANAGER, HA_BINARY_SENSOR,
                     HA_SENSOR_POLL_INTERVAL_SECONDS, DEVICE_LIST_COORDINATOR)

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=HA_SENSOR_POLL_INTERVAL_SECONDS)


class WaterLeakSensor(MerossDevice, BinarySensorEntity):
    """Wrapper class to adapt the Meross MS405 water-leak sensor into the Homeassistant platform"""
    _device: Ms405Sensor

    def __init__(self, device: BaseDevice, device_list_coordinator: DataUpdateCoordinator[Dict[str, HttpDeviceInfo]], channel: int = 0):
        super().__init__(
            device=device,
            channel=channel,
            device_list_coordinator=device_list_coordinator,
            platform=HA_BINARY_SENSOR)

        self._attr_device_class = BinarySensorDeviceClass.MOISTURE

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def is_on(self) -> Optional[bool]:
        """Return true if the binary sensor is on."""
        if self.online or self._device.online_status != OnlineStatus.OFFLINE:
            return self._device.is_leaking
        return None


class Ms200DoorWindowSensor(MerossDevice, BinarySensorEntity):
    """Wrapper class to adapt the Meross MS200 door and window sensor into Home Assistant"""
    _device: Ms200Sensor

    def __init__(self, device: Ms200Sensor, device_list_coordinator: DataUpdateCoordinator[Dict[str, HttpDeviceInfo]], channel: int = 0):
        super().__init__(
            device=device,
            channel=channel,
            device_list_coordinator=device_list_coordinator,
            platform=HA_BINARY_SENSOR)

        self._attr_device_class = BinarySensorDeviceClass.DOOR

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._device.is_open is None and self.hass is not None:
            self.hass.async_create_task(self._async_initial_update())

    async def _async_initial_update(self) -> None:
        try:
            await self._device.async_update()
            self.async_write_ha_state()
        except Exception as e:
            _LOGGER.debug("Initial update for %s failed: %s", self.entity_id, e)

    async def async_update(self) -> None:
        try:
            await self._device.async_update()
        except Exception as e:
            _LOGGER.debug("Update for %s failed: %s", self.name, e)

    async def _async_push_notification_received(self, namespace: Namespace, data: dict, device_internal_id: str):
        if namespace in (Namespace.HUB_SENSOR_DOORWINDOW, Namespace.HUB_SENSOR_ALERT, Namespace.HUB_SENSOR_ALL):
            door_data = data.get('doorWindow') or data.get('door') or data.get('alert') or data
            if isinstance(door_data, list) and len(door_data) > 0:
                door_data = door_data[0]
            if isinstance(door_data, dict):
                st = door_data.get('status') if 'status' in door_data else door_data.get('state')
                ts = door_data.get('lmTime') or door_data.get('time')
                if st is not None:
                    self._device._handle_door_window_data(status=st, timestamp=ts)
        await super()._async_push_notification_received(namespace=namespace, data=data, device_internal_id=device_internal_id)

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def is_on(self) -> Optional[bool]:
        """Return true if the door/window is open."""
        if self.online or self._device.online_status != OnlineStatus.OFFLINE:
            return self._device.is_open
        return None

    @property
    def extra_state_attributes(self) -> dict:
        attrs = {}
        if self._device.last_sampled_time is not None:
            attrs["latest_sample_time"] = self._device.last_sampled_time.isoformat()
        return attrs


class Gs559aSmokeAlarmSensor(MerossDevice, BinarySensorEntity):
    """Smoke detection binary sensor for GS559A"""
    _device: Gs559aSensor

    def __init__(self, device: Gs559aSensor, device_list_coordinator: DataUpdateCoordinator[Dict[str, HttpDeviceInfo]], channel: int = 0):
        super().__init__(
            device=device,
            channel=channel,
            device_list_coordinator=device_list_coordinator,
            platform=HA_BINARY_SENSOR,
            supplementary_classifiers=["smoke"])

        self._attr_device_class = BinarySensorDeviceClass.SMOKE

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._device.status is None and self.hass is not None:
            self.hass.async_create_task(self._async_initial_update())

    async def _async_initial_update(self) -> None:
        try:
            await self._device.async_update()
            self.async_write_ha_state()
        except Exception as e:
            _LOGGER.debug("Initial update for %s failed: %s", self.entity_id, e)

    async def async_update(self) -> None:
        try:
            await self._device.async_update()
        except Exception as e:
            _LOGGER.debug("Update for %s failed: %s", self.name, e)

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def is_on(self) -> Optional[bool]:
        """Return true if smoke alarm is sounding."""
        if self.online or self._device.online_status != OnlineStatus.OFFLINE:
            return self._device.is_smoke_alarm
        return None


class Gs559aHeatAlarmSensor(MerossDevice, BinarySensorEntity):
    """Heat/high temperature alarm binary sensor for GS559A"""
    _device: Gs559aSensor

    def __init__(self, device: Gs559aSensor, device_list_coordinator: DataUpdateCoordinator[Dict[str, HttpDeviceInfo]], channel: int = 0):
        super().__init__(
            device=device,
            channel=channel,
            device_list_coordinator=device_list_coordinator,
            platform=HA_BINARY_SENSOR,
            supplementary_classifiers=["heat"])

        self._attr_device_class = BinarySensorDeviceClass.HEAT

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def is_on(self) -> Optional[bool]:
        """Return true if heat alarm is sounding."""
        if self.online or self._device.online_status != OnlineStatus.OFFLINE:
            return self._device.is_heat_alarm
        return None


class Gs559aAlarmProblemSensor(MerossDevice, BinarySensorEntity):
    """Problem/fault detection binary sensor for GS559A"""
    _device: Gs559aSensor

    def __init__(self, device: Gs559aSensor, device_list_coordinator: DataUpdateCoordinator[Dict[str, HttpDeviceInfo]], channel: int = 0):
        super().__init__(
            device=device,
            channel=channel,
            device_list_coordinator=device_list_coordinator,
            platform=HA_BINARY_SENSOR,
            supplementary_classifiers=["problem"])

        self._attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def is_on(self) -> Optional[bool]:
        """Return true if sensor or hardware fault is detected."""
        if self.online or self._device.online_status != OnlineStatus.OFFLINE:
            return self._device.is_error
        return None


class Gs559aAlarmTestSensor(MerossDevice, BinarySensorEntity):
    """Test mode binary sensor for GS559A"""
    _device: Gs559aSensor

    def __init__(self, device: Gs559aSensor, device_list_coordinator: DataUpdateCoordinator[Dict[str, HttpDeviceInfo]], channel: int = 0):
        super().__init__(
            device=device,
            channel=channel,
            device_list_coordinator=device_list_coordinator,
            platform=HA_BINARY_SENSOR,
            supplementary_classifiers=["test"])

        self._attr_device_class = BinarySensorDeviceClass.SAFETY

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def is_on(self) -> Optional[bool]:
        """Return true if alarm test mode is active."""
        if self.online or self._device.online_status != OnlineStatus.OFFLINE:
            return self._device.is_test_alarm
        return None


class Gs559aAlarmMutedSensor(MerossDevice, BinarySensorEntity):
    """Muted state binary sensor for GS559A"""
    _device: Gs559aSensor

    def __init__(self, device: Gs559aSensor, device_list_coordinator: DataUpdateCoordinator[Dict[str, HttpDeviceInfo]], channel: int = 0):
        super().__init__(
            device=device,
            channel=channel,
            device_list_coordinator=device_list_coordinator,
            platform=HA_BINARY_SENSOR,
            supplementary_classifiers=["muted"])

        self._attr_device_class = BinarySensorDeviceClass.SOUND

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def is_on(self) -> Optional[bool]:
        """Return true if alarm is currently muted / silenced."""
        if self.online or self._device.online_status != OnlineStatus.OFFLINE:
            return self._device.is_muted
        return None


# ----------------------------------------------
# PLATFORM METHODS
# ----------------------------------------------
async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    def entity_adder_callback():
        """Discover and adds new Meross entities"""
        manager: MerossManager = hass.data[DOMAIN][MANAGER]
        coordinator = hass.data[DOMAIN][DEVICE_LIST_COORDINATOR]
        devices = manager.find_devices()

        new_entities = []

        # Handle water leak sensors (MS400 / MS405)
        water_leak_sensors = filter(lambda d: isinstance(d, Ms405Sensor), devices)
        for wls in water_leak_sensors:
            channels = [c.index for c in wls.channels] if len(wls.channels) > 0 else [0]
            for channel_index in channels:
                new_entities.append(
                    WaterLeakSensor(device=wls, device_list_coordinator=coordinator, channel=channel_index))

        # Handle door / window sensors (MS200)
        door_window_sensors = filter(lambda d: isinstance(d, Ms200Sensor), devices)
        for dws in door_window_sensors:
            channels = [c.index for c in dws.channels] if len(dws.channels) > 0 else [0]
            for channel_index in channels:
                new_entities.append(
                    Ms200DoorWindowSensor(device=dws, device_list_coordinator=coordinator, channel=channel_index))

        # Handle smoke and heat alarm sensors (GS559A)
        smoke_sensors = filter(lambda d: isinstance(d, Gs559aSensor), devices)
        for sms in smoke_sensors:
            channels = [c.index for c in sms.channels] if len(sms.channels) > 0 else [0]
            for channel_index in channels:
                new_entities.append(
                    Gs559aSmokeAlarmSensor(device=sms, device_list_coordinator=coordinator, channel=channel_index))
                new_entities.append(
                    Gs559aHeatAlarmSensor(device=sms, device_list_coordinator=coordinator, channel=channel_index))
                new_entities.append(
                    Gs559aAlarmProblemSensor(device=sms, device_list_coordinator=coordinator, channel=channel_index))
                new_entities.append(
                    Gs559aAlarmTestSensor(device=sms, device_list_coordinator=coordinator, channel=channel_index))
                new_entities.append(
                    Gs559aAlarmMutedSensor(device=sms, device_list_coordinator=coordinator, channel=channel_index))

        unique_new_devs = filter(lambda d: d.unique_id not in hass.data[DOMAIN]["ADDED_ENTITIES_IDS"], new_entities)
        async_add_entities(list(unique_new_devs), False)

    coordinator = hass.data[DOMAIN][DEVICE_LIST_COORDINATOR]
    coordinator.async_add_listener(entity_adder_callback)
    # Run the entity adder a first time during setup
    entity_adder_callback()


def setup_platform(hass, config, async_add_entities, discovery_info=None):
    pass
