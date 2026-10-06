import logging
from collections import deque
from datetime import datetime, timezone
from typing import Optional, Iterable, List, Dict

from meross_iot.controller.device import GenericSubDevice
from meross_iot.model.enums import OnlineStatus, ThermostatV3Mode
from meross_iot.model.enums import Namespace
from meross_iot.model.plugin.hub import BatteryInfo



_LOGGER = logging.getLogger(__name__)


class Ms100Sensor(GenericSubDevice):
    """
    This class maps the functionality offered by the MS100 sensor device.
    The MS100 offers temperature and humidity sensing.
    Moreover, this device is capable of triggering settable alerts.
    """

    def __init__(self, hubdevice_uuid: str, subdevice_id: str, manager, **kwargs):
        super().__init__(hubdevice_uuid, subdevice_id, manager, **kwargs)
        self.__temperature = {}
        self.__humidity = {}
        self.__samples = []


    async def async_update(self,
                           timeout: Optional[float] = None,
                           *args,
                           **kwargs) -> None:

        # Make sure we issue an update at HUB level first
        await super().async_update()

        # We also need to trigger an update request for this specific sub-device
        result = await self._hub._execute_command(method="GET",
                                                  namespace=Namespace.HUB_SENSOR_ALL,
                                                  payload={'all': [{'id': self.subdevice_id}]},
                                                  timeout=timeout)

        # Retrieve the sub-device specific data and update the status
        subdevices_states = result.get('all')
        for subdev_state in subdevices_states:
            subdev_id = subdev_state.get('id')
            if subdev_id != self.subdevice_id:
                continue
            await self.async_handle_subdevice_notification(namespace=Namespace.HUB_SENSOR_ALL, data=subdev_state)
            break

    async def async_handle_push_notification(self, namespace: Namespace, data: dict) -> bool:
        locally_handled = False
        if namespace == Namespace.HUB_ONLINE:
            update_element = self._prepare_push_notification_data(data=data, filter_accessor='online')
            if update_element is not None:
                self._online = OnlineStatus(update_element.get('status', -1))
                locally_handled = True
        return locally_handled

    async def async_handle_subdevice_notification(self, namespace: Namespace, data: dict) -> bool:
        locally_handled = False
        if namespace == Namespace.HUB_ONLINE:
            self._online = OnlineStatus(data.get('online', {}).get('status', -1))
            self._last_active_time = data.get('online', {}).get('lastActiveTime')
        elif namespace == Namespace.HUB_SENSOR_ALL:
            self._online = OnlineStatus(data.get('online', {}).get('status', -1))
            self.__temperature.update(data.get('temperature', {}))
            self.__humidity.update(data.get('humidity', {}))
            locally_handled = True
        elif namespace == Namespace.HUB_SENSOR_TEMPHUM:
            latest_temperature = data.get('latestTemperature')
            latest_humidity = data.get('latestHumidity')
            synced_time = data.get('syncedTime')
            samples = data.get('sample')
            if synced_time is not None and (self.last_sampled_time is None or
                                            synced_time > self.last_sampled_time.timestamp()):
                self.__temperature['latestSampleTime'] = synced_time
                self.__temperature['latest'] = latest_temperature
                self.__humidity['latestSampleTime'] = synced_time
                self.__humidity['latest'] = latest_humidity

            self.__samples.clear()
            for sample in samples:
                temp, hum, from_ts, to_ts, unknown = sample
                self.__samples.append({
                    'from_ts': from_ts,
                    'to_ts': to_ts,
                    'temperature': float(temp) / 10,
                    'humidity': float(hum) / 10
                })

            else:
                _LOGGER.debug("Skipping temperature update as synched time is None or old compared to the latest data")
            locally_handled = True
        elif namespace == Namespace.HUB_SENSOR_ALERT:
            locally_handled = False
            # TODO: not yet implemented
        else:
            _LOGGER.warning(f"Could not handle event %s in subdevice %s handler", namespace, self.name)

        # Always call the parent handler when done with local specific logic. This gives the opportunity to all
        # ancestors to catch all events.
        parent_handled = await super().async_handle_push_notification(namespace=namespace, data=data)
        return locally_handled or parent_handled

    @property
    def last_sampled_temperature(self) -> Optional[float]:
        """
        Returns the latest sampled temperature in Celsius degrees.
        If you want to refresh this data, call `async_update` to force a full
        data refresh.

        :return: The latest sampled temperature, if available, in Celsius degree
        """
        temp = self.__temperature.get('latest')
        if temp is None:
            return None
        return float(temp) / 10.0

    @property
    def last_sampled_humidity(self) -> Optional[float]:
        """
        Exposes the latest sampled humidity, in %.
        If you want to refresh this data, call `async_update` to force a full
        data refresh.

        :return: The latest sampled humidity grade in %, if available
        """
        humidity = self.__humidity.get('latest')
        if humidity is None:
            return None
        return float(humidity) / 10.0

    @property
    def last_sampled_time(self) -> Optional[datetime]:
        """
        UTC datetime when the latest update has been sampled by the sensor

        :return: latest sampling time in UTC, if available
        """
        timestamp = self.__temperature.get('latestSampleTime')
        if timestamp is None:
            return None

        return datetime.utcfromtimestamp(timestamp)

    @property
    def min_supported_temperature(self) -> Optional[float]:
        """
        Maximum supported temperature that this device can report

        :return: float value, maximum supported temperature, if available
        """
        return self.__temperature.get('min')

    @property
    def max_supported_temperature(self) -> Optional[float]:
        """
        Minimum supported temperature that this device can report
        """
        return self.__temperature.get('max')


class Mts100v3Valve(GenericSubDevice):
    def __init__(self, hubdevice_uuid: str, subdevice_id: str, manager, **kwargs):
        super().__init__(hubdevice_uuid, subdevice_id, manager, **kwargs)
        self.__togglex = {}
        self.__timeSync = None
        self.__mode = {}
        self.__temperature = {}
        self._schedule_b_mode = None
        self._last_active_time = None
        self.__adjust = {}

    async def async_update(self,
                           timeout: Optional[float] = None,
                           *args,
                           **kwargs) -> None:
        # Make sure we issue an update at HUB level first
        await super().async_update()

        # We also need to trigger an update request for this specific sub-device
        result = await self._hub._execute_command(method="GET",
                                                  namespace=Namespace.HUB_MTS100_ALL,
                                                  payload={'all': [{'id': self.subdevice_id}]},
                                                  timeout=timeout)

        # Retrieve the sub-device specific data and update the status
        subdevices_states = result.get('all')
        for subdev_state in subdevices_states:
            subdev_id = subdev_state.get('id')
            if subdev_id != self.subdevice_id:
                continue
            await self.async_handle_subdevice_notification(namespace=Namespace.HUB_MTS100_ALL, data=subdev_state)
            break

    async def async_handle_push_notification(self, namespace: Namespace, data: dict) -> bool:
        locally_handled = False
        if namespace == Namespace.HUB_ONLINE:
            update_element = self._prepare_push_notification_data(data=data, filter_accessor='online')
            if update_element is not None:
                self._online = OnlineStatus(update_element.get('status', -1))
                locally_handled = True
        return locally_handled

    async def async_handle_subdevice_notification(self, namespace: Namespace, data: dict) -> bool:
        locally_handled = False
        if namespace == Namespace.HUB_ONLINE:
            self._online = OnlineStatus(data.get('online', {}).get('status', -1))
            self._last_active_time = data.get('online', {}).get('lastActiveTime')
        elif namespace == Namespace.HUB_MTS100_ALL:
            self._schedule_b_mode = data.get('scheduleBMode')
            self._online = OnlineStatus(data.get('online', {}).get('status', -1))
            self._last_active_time = data.get('online', {}).get('lastActiveTime')
            self.__togglex.update(data.get('togglex', {}))
            self.__timeSync = data.get('timeSync', {})
            self.__mode.update(data.get('mode', {}))
            self.__temperature.update(data.get('temperature', {}))
            self.__temperature['latestSampleTime'] = datetime.utcnow().timestamp()
            self.__adjust.update(data.get('temperature', {}))
            self.__adjust['latestSampleTime'] = datetime.utcnow().timestamp()
            locally_handled = True
        elif namespace == Namespace.HUB_TOGGLEX:
            update_element = self._prepare_push_notification_data(data=data)
            if update_element is not None:
                self.__togglex.update(update_element)
                locally_handled = True
        elif namespace == Namespace.HUB_MTS100_MODE:
            update_element = self._prepare_push_notification_data(data=data)
            if update_element is not None:
                self.__mode.update(update_element)
                locally_handled = True
        elif namespace == Namespace.HUB_MTS100_TEMPERATURE:
            update_element = self._prepare_push_notification_data(data=data)
            if update_element is not None:
                self.__temperature.update(update_element)
                self.__temperature['latestSampleTime'] = datetime.utcnow().timestamp()
                locally_handled = True
        else:
            _LOGGER.error(f"Could not handle event %s in subdevice %s handler", namespace, self.name)

        # Always call the parent handler when done with local specific logic. This gives the opportunity to all
        # ancestors to catch all events.
        parent_handled = await super().async_handle_push_notification(namespace=namespace, data=data)
        return locally_handled or parent_handled

    def is_on(self) -> Optional[bool]:
        return self.__togglex.get('onoff') == 1

    async def async_turn_off(self, timeout: Optional[float] = None, *args, **kwargs):
        await self._hub._execute_command(method="SET", namespace=Namespace.HUB_TOGGLEX,
                                         payload={'togglex': [{"id": self.subdevice_id, "onoff": 0, "channel": 0}]},
                                         timeout=timeout)
        # Assume the command was ok, so immediately update the internal state
        self.__togglex['onoff'] = 0

    async def async_turn_on(self, timeout: Optional[float] = None,
                            *args, **kwargs):
        await self._hub._execute_command(method="SET", namespace=Namespace.HUB_TOGGLEX,
                                         payload={'togglex': [{"id": self.subdevice_id, "onoff": 1, "channel": 0}]},
                                         timeout=timeout)
        # Assume the command was ok, so immediately update the internal state
        self.__togglex['onoff'] = 1

    async def async_toggle(self, timeout: float = None, *args, **kwargs):
        if self.is_on():
            await self.async_turn_off(timeout=timeout)
        else:
            await self.async_turn_on(timeout=timeout)

    @property
    def last_sampled_temperature(self) -> Optional[float]:
        """
        Current room temperature in Celsius degrees.

        :return: float number
        """
        temp = self.__temperature.get('room')
        if temp is not None:
            return float(temp) / 10.0
        else:
            return None

    async def async_get_temperature(self, timeout: Optional[float] = None, *args, **kwargs) -> Optional[float]:
        """
        Polls the device in order to retrieve the latest temperature info.
        You should not use this method so ofter: instead, rely on `last_sampled_temperature` when a cached
        value is ok.

        :return:
        """
        res = await self._hub._execute_command(method="GET", namespace=Namespace.HUB_MTS100_TEMPERATURE,
                                               payload={'temperature': [{"id": self.subdevice_id}]}, timeout=timeout)
        if res is None:
            return None

        for d in res.get('temperature'):
            if d.get('id') == self.subdevice_id:
                del d['id']
                self.__temperature.update(d)
                self.__temperature['latestSampleTime'] = datetime.utcnow().timestamp()
                break

        return self.last_sampled_temperature

    @property
    def last_sampled_time(self) -> Optional[datetime]:
        """
        UTC datetime when the latest update has been sampled by the sensor

        :return: latest sampling time in UTC, if available
        """
        timestamp = self.__temperature.get('latestSampleTime')
        if timestamp is None:
            return None

        return datetime.fromtimestamp(timestamp)

    @property
    def mode(self) -> Optional[ThermostatV3Mode]:
        m = self.__mode.get('state')
        if m is not None:
            return ThermostatV3Mode(m)

    async def async_set_mode(self, mode: ThermostatV3Mode, timeout: Optional[float] = None, *args, **kwargs) -> None:
        payload = {'mode': [{'id': self.subdevice_id, 'state': mode.value}]}
        await self._hub._execute_command(method='SET', namespace=Namespace.HUB_MTS100_MODE, payload=payload,
                                         timeout=timeout)
        self.__mode['state'] = mode.value

    @property
    def target_temperature(self) -> Optional[float]:
        temp = self.__temperature.get('currentSet')
        if temp is not None:
            return float(temp) / 10.0
        else:
            return None

    @property
    def min_supported_temperature(self) -> Optional[float]:
        temp = self.__temperature.get('min')
        if temp is not None:
            return float(temp) / 10.0
        else:
            return None

    @property
    def max_supported_temperature(self) -> Optional[float]:
        temp = self.__temperature.get('max')
        if temp is not None:
            return float(temp) / 10.0
        else:
            return None

    @property
    def is_heating(self) -> Optional[bool]:
        return self.__temperature.get('heating') == 1

    @property
    def is_window_open(self) -> Optional[bool]:
        return self.__temperature.get('openWindow') == 1

    def get_preset_temperature(self, preset: str) -> Optional[float]:
        """
        Returns the current set temperature for the given preset.

        :param preset:

        :return: float temperature value
        """
        if preset not in self.get_supported_presets():
            _LOGGER.error(f"Preset {preset} is not supported by this device.")
        val = self.__temperature.get(preset)
        if val is None:
            return None
        return float(val) / 10.0

    @staticmethod
    def get_supported_presets() -> Iterable[str]:
        """
        Returns the supported presets of this device.

        :return: an iterable of strings
        """
        return 'custom', 'comfort', 'economy', 'away'

    async def async_set_preset_temperature(self, preset: str, temperature: float, timeout: Optional[float] = None, *args,
                                           **kwargs) -> None:
        """
        Sets the preset temperature configuration.

        :param preset: string preset, as reported by `get_supported_presets()`
        :param temperature: temperature to be set for the given preset

        :return: None
        """
        if preset not in self.get_supported_presets():
            raise ValueError(f"Preset {preset} is not supported by this device. "
                             f"Valid presets are: {self.get_supported_presets()}")
        target_temp = temperature * 10
        await self._hub._execute_command(method="SET", namespace=Namespace.HUB_MTS100_TEMPERATURE,
                                         payload={'temperature': [{'id': self.subdevice_id, preset: target_temp}]},
                                         timeout=timeout)

        # Update local state
        self.__temperature[preset] = target_temp

    async def async_set_target_temperature(self, temperature: float, timeout: Optional[float] = None, *args,
                                           **kwargs) -> None:
        # The API expects the target temperature in DECIMALS, so we need to multiply the user's input by 10
        target_temp = temperature * 10
        payload = {'temperature': [{'id': self.subdevice_id, 'custom': target_temp}]}
        await self._hub._execute_command(method='SET', namespace=Namespace.HUB_MTS100_TEMPERATURE, payload=payload,
                                         timeout=timeout)
        # Update local state
        self.__temperature['currentSet'] = target_temp

    async def async_get_adjust(self, timeout: Optional[float] = None, *args, **kwargs) -> Optional[float]:
        """
        :return:
        """
        res = await self._hub._execute_command(method="GET", namespace=Namespace.HUB_MTS100_ADJUST,
                                               payload={'adjust': [{"id": self.subdevice_id}]}, timeout=timeout)
        if res is None:
            return None

        for d in res.get('adjust'):
            if d.get('id') == self.subdevice_id:
                del d['id']
                self.__adjust.update(d)
                self.__adjust['latestSampleTime'] = datetime.utcnow().timestamp()
                break

        return self.adjust

    @property
    def adjust(self) -> Optional[float]:
        """
        Returns the adjust temperature value for the sensor if available

        :return:
        """
        adjust = self.__adjust.get('temperature')
        if adjust is None:
            return None

        return float(self.__adjust.get('temperature')) / 100.0

    async def async_set_adjust(self, temperature: float, timeout: Optional[float] = None) -> None:
        # The API expects the adjust temperature in HUNDREDS (not consistent with the temperature set), so we need to multiply the user's input by 100
        # N.B. the App enforces on the frontend a limit on the adjustment (+/- 5 C°), tests show there is no limit on the API
        adjust_temp = temperature * 100
        payload = {'adjust': [{'id': self.subdevice_id, 'temperature': adjust_temp}]}
        await self._hub._execute_command(method='SET', namespace=Namespace.HUB_MTS100_ADJUST, payload=payload,
                                         timeout=timeout)
        # Update local state
        self.__adjust.update({'temperature': adjust_temp})
        self.__adjust['latestSampleTime'] = datetime.utcnow().timestamp()


class Ms405Sensor(GenericSubDevice):
    """
    Class that represents a Meross MS400 Smart Water Leak Sensor.
    """

    def __init__(self, hubdevice_uuid: str, subdevice_id: str, manager, max_events_queue_len=30, **kwargs):
        super().__init__(hubdevice_uuid, subdevice_id, manager, **kwargs)

        self._last_active_time: Optional[int] = None
        # Represents the last time we contacted the device

        self.__water_leak_state: Optional[bool] = None
        # Represents the current state

        self.__last_event_ts: Optional[int] = None
        # Represents the timestamp of the last sample (current state sampling)

        self.__cached_events: deque = deque(maxlen=max_events_queue_len)
        # Last N samples we collected

        self.__last_waterleak_event_ts: Optional[int] = None
        # Last timestamp we've seen a leak

    @property
    def is_leaking(self) -> Optional[bool]:
        """
        Returns the latest updated state available for the water leak sensor, if available.
        """
        return self.__water_leak_state

    @property
    def latest_sample_time(self) -> Optional[int]:
        """
        Returns the timestamp (GMT) of the latest available sampling.
        """
        return self.__last_event_ts

    @property
    def latest_detected_water_leak_ts(self) -> Optional[int]:
        """
        Return the timestamp (GMT) of the latest time the sensor sampled a water leak.
        """
        return self.__last_waterleak_event_ts

    @property
    def get_last_events(self) -> List[Dict]:
        """
        Returns the last cached items
        """
        return [x for x in self.__cached_events]

    async def async_update(self,
                           timeout: Optional[float] = None,
                           *args,
                           **kwargs) -> None:
        # Make sure we issue an update at HUB level first
        await super().async_update()

        # We also need to trigger an update request for this specific sub-device
        result = await self._hub._execute_command(method="GET",
                                                  #namespace=Namespace.HUB_MTS100_ALL,
                                                  namespace=Namespace.HUB_SENSOR_ALL,
                                                  payload={'all': [{'id': self.subdevice_id}]},
                                                  timeout=timeout)

        # Retrieve the sub-device specific data and update the status
        subdevices_states = result.get('all')
        for subdev_state in subdevices_states:
            subdev_id = subdev_state.get('id')
            if subdev_id != self.subdevice_id:
                continue
            await self.async_handle_subdevice_notification(namespace=Namespace.HUB_SENSOR_ALL, data=subdev_state)
            break

    def _handle_water_leak_fresh_data(self, leaking: bool, timestamp: int):
        # If handling an event with an older timestamp than the one we have, just discard it.
        if self.latest_sample_time is not None and timestamp <= self.latest_sample_time:
            return

        # If this is the first update or if it's more recent than the last we have, update the current state.
        if self.__last_event_ts is None or timestamp >= self.__last_event_ts:
            self.__last_event_ts = timestamp
            self.__water_leak_state = leaking

        # If the event is a leak and is more recent than the latest leak event, update it.
        if leaking and (self.__last_waterleak_event_ts is None or timestamp >= self.__last_waterleak_event_ts):
            self.__last_waterleak_event_ts = timestamp

        # In any case, register the event in the queue
        self.__cached_events.append({
            "leaking": leaking,
            "timestamp": timestamp
        })

    async def async_handle_push_notification(self, namespace: Namespace, data: dict) -> bool:
        locally_handled = False
        if namespace == Namespace.HUB_ONLINE:
            update_element = self._prepare_push_notification_data(data=data, filter_accessor='online')
            if update_element is not None:
                self._online = OnlineStatus(update_element.get('status', -1))
                locally_handled = True
        elif namespace == Namespace.HUB_SENSOR_WATERLEAK:
            water_leak_state = data.get('waterLeak')
            latestWaterLeak = water_leak_state.get('latestWaterLeak')
            latestSampleTime = water_leak_state.get('latestSampleTime')
            self._handle_water_leak_fresh_data(leaking=latestWaterLeak==1, timestamp=latestSampleTime)
            locally_handled = True

        return locally_handled

    async def async_handle_subdevice_notification(self, namespace: Namespace, data: dict) -> bool:
        locally_handled = False
        if namespace == Namespace.HUB_ONLINE:
            self._online = OnlineStatus(data.get('online', {}).get('status', -1))
            self._last_active_time = data.get('online', {}).get('lastActiveTime')
        elif namespace == Namespace.HUB_SENSOR_WATERLEAK:
            latestWaterLeak = data.get('latestWaterLeak')
            latestSampleTime = data.get('latestSampleTime')
            self._handle_water_leak_fresh_data(leaking=latestWaterLeak==1, timestamp=latestSampleTime)
            locally_handled = True
        elif namespace == Namespace.HUB_SENSOR_ALL:
            self._online = OnlineStatus(data.get('online', {}).get('status', -1))
            water_leak_state = data.get('waterLeak')
            if water_leak_state is not None:
                latestWaterLeak = water_leak_state.get('latestWaterLeak')
                latestSampleTime = water_leak_state.get('latestSampleTime')
                self._handle_water_leak_fresh_data(leaking=latestWaterLeak == 1, timestamp=latestSampleTime)

            locally_handled = True
        else:
            _LOGGER.warning(f"Could not handle event %s in subdevice %s handler", namespace, self.name)

        # Always call the parent handler when done with local specific logic. This gives the opportunity to all
        # ancestors to catch all events.
        parent_handled = await super().async_handle_push_notification(namespace=namespace, data=data)
        return locally_handled or parent_handled

    def __repr__(self) -> str:
        return f"<Ms400Device(uuid={self.uuid}, is_leaking={self.is_leaking})>"


class Ms200Sensor(GenericSubDevice):
    """
    Class that represents a Meross MS200 Smart Door and Window Sensor.
    """

    def __init__(self, hubdevice_uuid: str, subdevice_id: str, manager, **kwargs):
        super().__init__(hubdevice_uuid, subdevice_id, manager, **kwargs)
        self._is_open: Optional[bool] = None
        self._last_sample_time: Optional[int] = None

    @property
    def is_open(self) -> Optional[bool]:
        """Returns True if the door/window is open, False if closed, None if unknown."""
        return self._is_open

    @property
    def latest_sample_time(self) -> Optional[int]:
        """Returns the timestamp of the latest sample."""
        return self._last_sample_time

    @property
    def last_sampled_time(self) -> Optional[datetime]:
        """UTC datetime when the latest status was sampled."""
        if self._last_sample_time is not None:
            try:
                return datetime.fromtimestamp(self._last_sample_time, tz=timezone.utc)
            except Exception:
                return None
        return None

    def _handle_door_window_data(self, status: Optional[Union[int, bool, str]], timestamp: Optional[int] = None):
        if status is not None:
            if isinstance(status, dict):
                status = status.get('status', status.get('state', status.get('open')))
            str_val = str(status).strip().lower()
            self._is_open = (status == 1 or status is True or str_val in ('1', 'open', 'true', 'opened'))
            self._online = OnlineStatus.ONLINE
        if timestamp is not None:
            self._last_sample_time = timestamp

    async def async_update(self, timeout: Optional[float] = None, *args, **kwargs) -> None:
        await super().async_update()
        result = await self._hub._execute_command(
            method="GET",
            namespace=Namespace.HUB_SENSOR_ALL,
            payload={'all': [{'id': self.subdevice_id}]},
            timeout=timeout
        )
        subdevices_states = result.get('all', [])
        found = False
        for subdev_state in subdevices_states:
            if str(subdev_state.get('id', '')).strip().lower() == str(self.subdevice_id).strip().lower():
                await self.async_handle_subdevice_notification(
                    namespace=Namespace.HUB_SENSOR_ALL, data=subdev_state
                )
                found = True
                break
        if not found and len(subdevices_states) == 1:
            await self.async_handle_subdevice_notification(
                namespace=Namespace.HUB_SENSOR_ALL, data=subdevices_states[0]
            )

    async def async_handle_push_notification(self, namespace: Namespace, data: dict) -> bool:
        locally_handled = False
        if namespace == Namespace.HUB_ONLINE:
            update_element = self._prepare_push_notification_data(data=data, filter_accessor='online')
            if update_element is not None:
                self._online = OnlineStatus(update_element.get('status', -1))
                locally_handled = True
        elif namespace == Namespace.HUB_BATTERY:
            bat_data = data.get('battery', {})
            if isinstance(bat_data, list):
                for b in bat_data:
                    if isinstance(b, dict) and str(b.get('id', '')).strip().lower() == str(self.subdevice_id).strip().lower():
                        bat_data = b
                        break
                if isinstance(bat_data, list) and len(bat_data) > 0:
                    bat_data = bat_data[0]
            if isinstance(bat_data, dict):
                raw_val = bat_data.get('value') if 'value' in bat_data else bat_data.get('battery')
                if raw_val is not None:
                    try:
                        self._battery_info = BatteryInfo(battery_charge=float(raw_val), sample_ts=datetime.now(timezone.utc))
                        self._online = OnlineStatus.ONLINE
                        locally_handled = True
                    except (ValueError, TypeError):
                        pass
        elif namespace == Namespace.HUB_SENSOR_DOORWINDOW:
            door_window = data.get('doorWindow') or data.get('door')
            target_item = None
            if isinstance(door_window, list):
                for item in door_window:
                    if isinstance(item, dict) and str(item.get('id', '')).strip().lower() == str(self.subdevice_id).strip().lower():
                        target_item = item
                        break
                if target_item is None and len(door_window) > 0 and isinstance(door_window[0], dict):
                    first_id = door_window[0].get('id')
                    if first_id is None or str(first_id).strip().lower() == str(self.subdevice_id).strip().lower():
                        target_item = door_window[0]
            elif isinstance(door_window, dict):
                dev_id = door_window.get('id')
                if dev_id is None or str(dev_id).strip().lower() == str(self.subdevice_id).strip().lower():
                    target_item = door_window
            elif data.get('status') is not None and str(data.get('id', self.subdevice_id)).strip().lower() == str(self.subdevice_id).strip().lower():
                target_item = data

            if target_item is not None:
                sub_door = target_item.get('doorWindow') or target_item.get('door') if isinstance(target_item.get('doorWindow') or target_item.get('door'), dict) else target_item
                status = sub_door.get('status')
                if status is None:
                    status = sub_door.get('state')
                if status is None:
                    status = sub_door.get('open')
                lm_time = sub_door.get('lmTime') or sub_door.get('latestSampleTime') or sub_door.get('sampleTime') or sub_door.get('time')
                self._handle_door_window_data(status=status, timestamp=lm_time)
                locally_handled = True

        parent_handled = await super().async_handle_push_notification(namespace=namespace, data=data)
        return locally_handled or parent_handled

    async def async_handle_subdevice_notification(self, namespace: Namespace, data: dict) -> bool:
        locally_handled = False
        self._online = OnlineStatus.ONLINE
        if namespace == Namespace.HUB_ONLINE:
            self._online = OnlineStatus(data.get('online', {}).get('status', -1))
            self._last_active_time = data.get('online', {}).get('lastActiveTime')
            locally_handled = True
        elif namespace == Namespace.HUB_BATTERY:
            raw_val = (
                data.get('value')
                if data.get('value') is not None
                else data.get('battery')
                if data.get('battery') is not None
                else data.get('batteryValue')
            )
            if raw_val is not None:
                try:
                    self._battery_info = BatteryInfo(battery_charge=float(raw_val), sample_ts=datetime.now(timezone.utc))
                    locally_handled = True
                except (ValueError, TypeError):
                    pass
        elif namespace == Namespace.HUB_SENSOR_DOORWINDOW:
            sub_door = data.get('doorWindow') or data.get('door')
            if not isinstance(sub_door, dict) and isinstance(data, dict):
                sub_door = data
            if isinstance(sub_door, dict):
                status = sub_door.get('status')
                if status is None:
                    status = sub_door.get('state')
                if status is None:
                    status = sub_door.get('open')
                lm_time = sub_door.get('lmTime') or sub_door.get('latestSampleTime') or sub_door.get('sampleTime') or sub_door.get('time')
                self._handle_door_window_data(status=status, timestamp=lm_time)
                locally_handled = True
        elif namespace == Namespace.HUB_SENSOR_ALL:
            self._online = OnlineStatus(data.get('online', {}).get('status', -1))
            self._last_active_time = data.get('online', {}).get('lastActiveTime')
            door_window = data.get('doorWindow') or data.get('door')
            if isinstance(door_window, list) and len(door_window) > 0:
                door_window = door_window[0]
            if isinstance(door_window, dict):
                status = door_window.get('status')
                if status is None:
                    status = door_window.get('state')
                if status is None:
                    status = door_window.get('open')
                lm_time = door_window.get('lmTime') or door_window.get('latestSampleTime') or door_window.get('sampleTime')
                self._handle_door_window_data(status=status, timestamp=lm_time)
            battery_data = data.get('battery') or data.get('batteryValue')
            if battery_data is not None:
                raw_val = battery_data.get('value') or battery_data.get('battery') if isinstance(battery_data, dict) else battery_data
                if raw_val is not None:
                    try:
                        self._battery_info = BatteryInfo(battery_charge=float(raw_val), sample_ts=datetime.now(timezone.utc))
                    except (ValueError, TypeError):
                        pass
            locally_handled = True
        else:
            _LOGGER.debug(f"Event %s passed through subdevice %s handler", namespace, self.name)

        parent_handled = await super().async_handle_subdevice_notification(namespace=namespace, data=data)
        return locally_handled or parent_handled

    def __repr__(self) -> str:
        return f"<Ms200Sensor(uuid={self.uuid}, is_open={self.is_open})>"


class Gs559aSensor(GenericSubDevice):
    """
    Class that represents a Meross GS559A Smart Smoke and Heat Alarm.
    """

    STATUS_MAP = {
        17: "error_temperature",
        18: "error_smoke",
        19: "error_battery",
        20: "error_temperature_muted",
        21: "error_smoke_muted",
        22: "error_battery_muted",
        23: "alarm_test",
        24: "alarm_temperature_high",
        25: "alarm_smoke",
        26: "alarm_temperature_high_muted",
        27: "alarm_smoke_muted",
        170: "ok",
    }
    MUTE_MAP = {17: 20, 18: 21, 19: 22, 24: 26, 25: 27, None: 170}
    STATUS_ALARM = {23, 24, 25, 26, 27}
    STATUS_ERROR = {17, 18, 19, 20, 21, 22}
    STATUS_MUTED = {20, 21, 22, 26, 27}
    STATUS_SMOKE = {25, 27}
    STATUS_HEAT = {24, 26}

    def __init__(self, hubdevice_uuid: str, subdevice_id: str, manager, **kwargs):
        super().__init__(hubdevice_uuid, subdevice_id, manager, **kwargs)
        self._status: Optional[int] = None
        self._interconn: Optional[int] = None
        self._last_sample_time: Optional[int] = None

    @property
    def status(self) -> Optional[int]:
        """Returns the raw status code."""
        return self._status

    @property
    def status_description(self) -> str:
        """Returns human-readable status description."""
        if self._status is None:
            return "unknown"
        return self.STATUS_MAP.get(self._status, f"status_{self._status}")

    @property
    def is_alarm_active(self) -> bool:
        """Returns True if any alarm (smoke, heat, test) is currently active."""
        return self._status in self.STATUS_ALARM if self._status is not None else False

    @property
    def is_smoke_alarm(self) -> bool:
        """Returns True if smoke alarm is sounding."""
        return self._status in self.STATUS_SMOKE if self._status is not None else False

    @property
    def is_heat_alarm(self) -> bool:
        """Returns True if excessive heat/temperature alarm is sounding."""
        return self._status in self.STATUS_HEAT if self._status is not None else False

    @property
    def is_test_alarm(self) -> bool:
        """Returns True if alarm test mode is active."""
        return self._status == 23 if self._status is not None else False

    @property
    def is_error(self) -> bool:
        """Returns True if sensor/hardware fault or error detected."""
        return self._status in self.STATUS_ERROR if self._status is not None else False

    @property
    def is_muted(self) -> bool:
        """Returns True if alarm has been muted / silenced."""
        return self._status in self.STATUS_MUTED if self._status is not None else False

    @property
    def is_interconnected(self) -> Optional[bool]:
        """Returns True if interconnected alarms are active/enabled."""
        return (self._interconn == 1) if self._interconn is not None else None

    @property
    def latest_sample_time(self) -> Optional[int]:
        """Returns the timestamp of the latest sample."""
        return self._last_sample_time

    @property
    def last_sampled_time(self) -> Optional[datetime]:
        """UTC datetime when the latest status was sampled."""
        if self._last_sample_time is not None:
            try:
                return datetime.fromtimestamp(self._last_sample_time, tz=timezone.utc)
            except Exception:
                return None
        return None

    def _handle_smoke_data(self, status: Optional[int], interconn: Optional[int] = None,
                           timestamp: Optional[int] = None):
        if status is not None:
            self._status = status
        if interconn is not None:
            self._interconn = interconn
        if timestamp is not None:
            self._last_sample_time = timestamp

    async def async_mute_alarm(self, timeout: Optional[float] = None) -> None:
        """Mutes / silences an active alarm."""
        target_status = self.MUTE_MAP.get(self._status, 170)
        try:
            await self._hub._execute_command(
                method="SET",
                namespace=Namespace.HUB_SENSOR_SMOKE,
                payload={'smokeAlarm': [{'id': self.subdevice_id, 'status': target_status}]},
                timeout=timeout
            )
        except Exception:
            # Fallback to key 'smoke' if hub expects that
            await self._hub._execute_command(
                method="SET",
                namespace=Namespace.HUB_SENSOR_SMOKE,
                payload={'smoke': [{'id': self.subdevice_id, 'status': target_status}]},
                timeout=timeout
            )
        self._status = target_status

    async def async_test_alarm(self, timeout: Optional[float] = None) -> None:
        """Triggers an alarm sound test."""
        try:
            await self._hub._execute_command(
                method="SET",
                namespace=Namespace.HUB_SENSOR_SMOKE,
                payload={'smokeAlarm': [{'id': self.subdevice_id, 'status': 23}]},
                timeout=timeout
            )
        except Exception:
            await self._hub._execute_command(
                method="SET",
                namespace=Namespace.HUB_SENSOR_SMOKE,
                payload={'smoke': [{'id': self.subdevice_id, 'status': 23}]},
                timeout=timeout
            )
        self._status = 23

    async def async_update(self, timeout: Optional[float] = None, *args, **kwargs) -> None:
        await super().async_update()
        result = await self._hub._execute_command(
            method="GET",
            namespace=Namespace.HUB_SENSOR_ALL,
            payload={'all': [{'id': self.subdevice_id}]},
            timeout=timeout
        )
        subdevices_states = result.get('all', [])
        found = False
        for subdev_state in subdevices_states:
            if str(subdev_state.get('id', '')).strip().lower() == str(self.subdevice_id).strip().lower():
                await self.async_handle_subdevice_notification(
                    namespace=Namespace.HUB_SENSOR_ALL, data=subdev_state
                )
                found = True
                break
        if not found and len(subdevices_states) == 1:
            await self.async_handle_subdevice_notification(
                namespace=Namespace.HUB_SENSOR_ALL, data=subdevices_states[0]
            )

    async def async_handle_push_notification(self, namespace: Namespace, data: dict) -> bool:
        locally_handled = False
        if namespace == Namespace.HUB_ONLINE:
            update_element = self._prepare_push_notification_data(data=data, filter_accessor='online')
            if update_element is not None:
                self._online = OnlineStatus(update_element.get('status', -1))
                locally_handled = True
        elif namespace == Namespace.HUB_BATTERY:
            bat_data = data.get('battery', {})
            if isinstance(bat_data, list):
                for b in bat_data:
                    if isinstance(b, dict) and str(b.get('id', '')).strip().lower() == str(self.subdevice_id).strip().lower():
                        bat_data = b
                        break
                if isinstance(bat_data, list) and len(bat_data) > 0:
                    bat_data = bat_data[0]
            if isinstance(bat_data, dict):
                raw_val = bat_data.get('value') if 'value' in bat_data else bat_data.get('battery')
                if raw_val is not None:
                    try:
                        self._battery_info = BatteryInfo(battery_charge=float(raw_val), sample_ts=datetime.now(timezone.utc))
                        self._online = OnlineStatus.ONLINE
                        locally_handled = True
                    except (ValueError, TypeError):
                        pass
        elif namespace == Namespace.HUB_SENSOR_SMOKE:
            smoke_data = data.get('smokeAlarm') or data.get('smoke')
            target_item = None
            if isinstance(smoke_data, list):
                for item in smoke_data:
                    if isinstance(item, dict) and str(item.get('id', '')).strip().lower() == str(self.subdevice_id).strip().lower():
                        target_item = item
                        break
                if target_item is None and len(smoke_data) > 0 and isinstance(smoke_data[0], dict):
                    first_id = smoke_data[0].get('id')
                    if first_id is None or str(first_id).strip().lower() == str(self.subdevice_id).strip().lower():
                        target_item = smoke_data[0]
            elif isinstance(smoke_data, dict):
                dev_id = smoke_data.get('id')
                if dev_id is None or str(dev_id).strip().lower() == str(self.subdevice_id).strip().lower():
                    target_item = smoke_data
            elif data.get('status') is not None and str(data.get('id', self.subdevice_id)).strip().lower() == str(self.subdevice_id).strip().lower():
                target_item = data

            if target_item is not None:
                sub_smoke = target_item.get('smokeAlarm') or target_item.get('smoke') if isinstance(target_item.get('smokeAlarm') or target_item.get('smoke'), dict) else target_item
                status = sub_smoke.get('status')
                interconn = sub_smoke.get('interConn')
                lm_time = sub_smoke.get('lmTime') or sub_smoke.get('latestSampleTime') or sub_smoke.get('sampleTime') or sub_smoke.get('time')
                self._handle_smoke_data(status=status, interconn=interconn, timestamp=lm_time)
                self._online = OnlineStatus.ONLINE
                locally_handled = True

        parent_handled = await super().async_handle_push_notification(namespace=namespace, data=data)
        return locally_handled or parent_handled

    async def async_handle_subdevice_notification(self, namespace: Namespace, data: dict) -> bool:
        locally_handled = False
        self._online = OnlineStatus.ONLINE
        if namespace == Namespace.HUB_ONLINE:
            self._online = OnlineStatus(data.get('online', {}).get('status', -1))
            self._last_active_time = data.get('online', {}).get('lastActiveTime')
            locally_handled = True
        elif namespace == Namespace.HUB_BATTERY:
            raw_val = (
                data.get('value')
                if data.get('value') is not None
                else data.get('battery')
                if data.get('battery') is not None
                else data.get('batteryValue')
            )
            if raw_val is not None:
                try:
                    self._battery_info = BatteryInfo(battery_charge=float(raw_val), sample_ts=datetime.now(timezone.utc))
                    locally_handled = True
                except (ValueError, TypeError):
                    pass
        elif namespace == Namespace.HUB_SENSOR_SMOKE:
            sub_smoke = data.get('smokeAlarm') or data.get('smoke') if isinstance(data.get('smokeAlarm') or data.get('smoke'), dict) else data
            status = sub_smoke.get('status')
            interconn = sub_smoke.get('interConn')
            lm_time = sub_smoke.get('lmTime') or sub_smoke.get('latestSampleTime') or sub_smoke.get('sampleTime') or sub_smoke.get('time')
            self._handle_smoke_data(status=status, interconn=interconn, timestamp=lm_time)
            locally_handled = True
        elif namespace == Namespace.HUB_SENSOR_ALL:
            self._online = OnlineStatus(data.get('online', {}).get('status', -1))
            self._last_active_time = data.get('online', {}).get('lastActiveTime')
            smoke_data = data.get('smokeAlarm') or data.get('smoke')
            if isinstance(smoke_data, list) and len(smoke_data) > 0:
                smoke_data = smoke_data[0]
            if isinstance(smoke_data, dict):
                status = smoke_data.get('status')
                interconn = smoke_data.get('interConn')
                lm_time = smoke_data.get('lmTime') or smoke_data.get('latestSampleTime') or smoke_data.get('sampleTime') or smoke_data.get('time')
                self._handle_smoke_data(status=status, interconn=interconn, timestamp=lm_time)
            battery_data = data.get('battery') or data.get('batteryValue')
            if battery_data is not None:
                raw_val = battery_data.get('value') or battery_data.get('battery') if isinstance(battery_data, dict) else battery_data
                if raw_val is not None:
                    try:
                        self._battery_info = BatteryInfo(battery_charge=float(raw_val), sample_ts=datetime.now(timezone.utc))
                    except (ValueError, TypeError):
                        pass
            locally_handled = True
        else:
            _LOGGER.debug(f"Event %s passed through subdevice %s handler", namespace, self.name)

        parent_handled = await super().async_handle_subdevice_notification(namespace=namespace, data=data)
        return locally_handled or parent_handled

    def __repr__(self) -> str:
        return f"<Gs559aSensor(uuid={self.uuid}, status={self.status_description})>"