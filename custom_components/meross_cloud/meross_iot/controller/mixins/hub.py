from __future__ import annotations

import logging
from typing import Optional

from meross_iot.model.enums import Namespace

_LOGGER = logging.getLogger(__name__)


class HubMixn(object):
    __PUSH_MAP = {
        Namespace.HUB_ONLINE: 'online',
        Namespace.HUB_TOGGLEX: 'togglex',
        Namespace.HUB_BATTERY: 'battery',
        Namespace.HUB_SENSOR_WATERLEAK: 'waterLeak',
        Namespace.HUB_SENSOR_DOORWINDOW: 'doorWindow',
        Namespace.HUB_SENSOR_SMOKE: 'smokeAlarm',
    }

    def __init__(self, device_uuid: str,
                 manager,
                 **kwargs):
        super().__init__(device_uuid=device_uuid, manager=manager, **kwargs)

    async def async_handle_push_notification(self, namespace: Namespace, data: dict) -> bool:
        locally_handled = False
        target_data_key = self.__PUSH_MAP.get(namespace)

        if target_data_key is not None:
            _LOGGER.debug(f"{self.__class__.__name__} handling push notification for namespace {namespace}")
            payload = data.get(target_data_key)
            if payload is None and namespace == Namespace.HUB_SENSOR_SMOKE:
                payload = data.get('smoke')
                target_data_key = 'smoke' if payload is not None else target_data_key
            elif payload is None and namespace == Namespace.HUB_SENSOR_DOORWINDOW:
                payload = data.get('door')
                target_data_key = 'door' if payload is not None else target_data_key

            if payload is None:
                _LOGGER.error(f"{self.__class__.__name__} could not find {target_data_key} attribute in push notification data: "
                              f"{data}")
                locally_handled = False
            else:
                notification_data = payload
                if isinstance(notification_data, dict):
                    notification_data = [notification_data]
                for subdev_state in notification_data:
                    subdev_id = subdev_state.get('id')

                    # Check the specific subdevice has been registered with this hub...
                    subdev = self.get_subdevice(subdevice_id=subdev_id)
                    if subdev is None:
                        _LOGGER.warning(
                            f"Received an update for a subdevice (id {subdev_id}) that has not yet been "
                            f"registered with this hub. The update will be skipped.")
                        continue
                    else:
                        await subdev.async_handle_subdevice_notification(namespace=namespace, data=subdev_state)
                locally_handled = True

        # Always call the parent handler when done with local specific logic. This gives the opportunity to all
        # ancestors to catch all events.
        parent_handled = await super().async_handle_push_notification(namespace=namespace, data=data)
        return locally_handled or parent_handled


class HubMs100Mixin(object):
    __PUSH_MAP = {
        # TODO: check this
        Namespace.HUB_SENSOR_ALERT: 'alert',
        Namespace.HUB_SENSOR_TEMPHUM: 'tempHum',
        Namespace.HUB_SENSOR_ALL: 'all',
        Namespace.HUB_SENSOR_DOORWINDOW: 'doorWindow',
        Namespace.HUB_SENSOR_SMOKE: 'smokeAlarm',
        Namespace.HUB_BATTERY: 'battery',
    }
    _execute_command: callable
    get_subdevice: callable
    uuid: str

    def __init__(self, device_uuid: str,
                 manager,
                 **kwargs):
        super().__init__(device_uuid=device_uuid, manager=manager, **kwargs)

    async def async_update(self, timeout: Optional[float] = None, *args, **kwargs) -> None:
        # Call the super implementation
        await super().async_update(*args, **kwargs)

        result = await self._execute_command(method="GET",
                                             namespace=Namespace.HUB_SENSOR_ALL,
                                             payload={'all': []},
                                             timeout=timeout)
        subdevs_data = result.get('all', [])
        for d in subdevs_data:
            dev_id = d.get('id')
            target_device = self.get_subdevice(subdevice_id=dev_id)
            if target_device is None:
                _LOGGER.warning(f"Received data for subdevice {dev_id}, which has not been registered with this "
                                f"hub yet. This update will be ignored.")
            else:
                await target_device.async_handle_subdevice_notification(namespace=Namespace.HUB_SENSOR_ALL, data=d)

        # Batch update battery for subdevices
        try:
            get_subdevs_fn = getattr(self, 'get_subdevices', None)
            subdevices = list(get_subdevs_fn()) if get_subdevs_fn else []
            abilities = getattr(self, 'abilities', {})
            if subdevices and (not abilities or Namespace.HUB_BATTERY.value in abilities or Namespace.HUB_BATTERY in abilities):
                subdev_ids = [{'id': sd.subdevice_id} for sd in subdevices]
                bat_res = await self._execute_command(method="GET",
                                                      namespace=Namespace.HUB_BATTERY,
                                                      payload={'battery': subdev_ids},
                                                      timeout=timeout)
                battery_list = bat_res.get('battery', [])
                if isinstance(battery_list, dict):
                    battery_list = [battery_list]
                if isinstance(battery_list, list):
                    for b in battery_list:
                        if isinstance(b, dict):
                            sd_id = b.get('id')
                            target_sd = self.get_subdevice(subdevice_id=sd_id)
                            if target_sd is not None:
                                await target_sd.async_handle_subdevice_notification(
                                    namespace=Namespace.HUB_BATTERY, data=b
                                )
        except Exception as e:
            _LOGGER.debug(f"Failed to batch query battery for subdevices on hub {self.uuid}: {e}")

    async def async_handle_push_notification(self, namespace: Namespace, data: dict) -> bool:
        locally_handled = False
        target_data_key = self.__PUSH_MAP.get(namespace)

        if target_data_key is not None:
            _LOGGER.debug(f"{self.__class__.__name__} handling push notification for namespace {namespace}")
            payload = data.get(target_data_key)
            if payload is None and namespace == Namespace.HUB_SENSOR_SMOKE:
                payload = data.get('smoke')
                target_data_key = 'smoke' if payload is not None else target_data_key
            elif payload is None and namespace == Namespace.HUB_SENSOR_DOORWINDOW:
                payload = data.get('door')
                target_data_key = 'door' if payload is not None else target_data_key

            if payload is None:
                _LOGGER.error(
                    f"{self.__class__.__name__} could not find {target_data_key} attribute in push notification data: "
                    f"{data}")
                locally_handled = False
            else:
                notification_data = payload
                if isinstance(notification_data, dict):
                    notification_data = [notification_data]
                for subdev_state in notification_data:
                    subdev_id = subdev_state.get('id')

                    # Check the specific subdevice has been registered with this hub...
                    subdev = self.get_subdevice(subdevice_id=subdev_id)
                    if subdev is None:
                        _LOGGER.warning(
                            f"Received an update for a subdevice (id {subdev_id}) that has not yet been "
                            f"registered with this hub. The update will be skipped.")
                        continue
                    else:
                        await subdev.async_handle_subdevice_notification(namespace=namespace, data=subdev_state)
                locally_handled = True

        # Always call the parent handler when done with local specific logic. This gives the opportunity to all
        # ancestors to catch all events.
        parent_handled = await super().async_handle_push_notification(namespace=namespace, data=data)
        return locally_handled or parent_handled


class HubMts100Mixin(object):
    __PUSH_MAP = {
        Namespace.HUB_MTS100_ALL: 'all',
        Namespace.HUB_MTS100_MODE: 'mode',
        Namespace.HUB_MTS100_TEMPERATURE: 'temperature'
    }
    _execute_command: callable
    get_subdevice: callable
    uuid: str

    def __init__(self, device_uuid: str,
                 manager,
                 **kwargs):
        super().__init__(device_uuid=device_uuid, manager=manager, **kwargs)

    async def async_update(self, timeout: Optional[float] = None, *args, **kwargs) -> None:
        try:
            # Call the super implementation
            await super().async_update(timeout=timeout, *args, **kwargs)

            result = await self._execute_command(method="GET",
                                                 namespace=Namespace.HUB_MTS100_ALL,
                                                 payload={'all': []},
                                                 timeout=timeout)
            subdevs_data = result.get('all', [])
            for d in subdevs_data:
                dev_id = d.get('id')
                target_device = self.get_subdevice(subdevice_id=dev_id)
                if target_device is None:
                    _LOGGER.warning(f"Received data for subdevice {target_device}, which has not been registered with this"
                                    f"hub yet. This update will be ignored.")
                else:
                    await target_device.async_handle_subdevice_notification(namespace=Namespace.HUB_MTS100_ALL, data=d)
        except Exception as e:
            _LOGGER.exception("Error occurred during subdevice update")

    async def async_handle_push_notification(self, namespace: Namespace, data: dict) -> bool:
        locally_handled = False
        target_data_key = self.__PUSH_MAP.get(namespace)

        if target_data_key is not None:
            _LOGGER.debug(f"{self.__class__.__name__} handling push notification for namespace {namespace}")
            payload = data.get(target_data_key)
            if payload is None:
                _LOGGER.error(f"{self.__class__.__name__} could not find {target_data_key} attribute in push notification data: "
                              f"{data}")
                locally_handled = False
            else:
                notification_data = data.get(target_data_key, [])
                for subdev_state in notification_data:
                    subdev_id = subdev_state.get('id')

                    # Check the specific subdevice has been registered with this hub...
                    subdev = self.get_subdevice(subdevice_id=subdev_id)
                    if subdev is None:
                        _LOGGER.warning(
                            f"Received an update for a subdevice (id {subdev_id}) that has not yet been "
                            f"registered with this hub. The update will be skipped.")
                        return False
                    else:
                        locally_handled = await subdev.async_handle_subdevice_notification(namespace=namespace, data=subdev_state)
                        if locally_handled:
                            break

        # Always call the parent handler when done with local specific logic. This gives the opportunity to all
        # ancestors to catch all events.
        parent_handled = await super().async_handle_push_notification(namespace=namespace, data=data)
        return locally_handled or parent_handled
