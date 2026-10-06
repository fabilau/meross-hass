"""Unit tests for Home Assistant entities: MS200 and GS559A platforms."""
import pytest
from unittest.mock import MagicMock, AsyncMock

from meross_iot.controller.subdevice import Ms200Sensor, Gs559aSensor
from meross_iot.model.enums import OnlineStatus, Namespace
from meross_iot.model.plugin.hub import BatteryInfo
from meross_iot.model.http.subdevice import HttpSubdeviceInfo
from meross_iot.device_factory import build_meross_subdevice
from custom_components.meross_cloud.common import DOMAIN

from custom_components.meross_cloud.binary_sensor import (
    Ms200DoorWindowSensor,
    Gs559aSmokeAlarmSensor,
    Gs559aHeatAlarmSensor,
    Gs559aAlarmProblemSensor,
    Gs559aAlarmTestSensor,
    Gs559aAlarmMutedSensor,
)
from custom_components.meross_cloud.sensor import (
    Gs559aStatusSensor,
    BatterySensorWrapper,
)
from custom_components.meross_cloud.button import (
    Gs559aTestButton,
    Gs559aMuteButton,
)


@pytest.fixture
def mock_coordinator():
    coord = MagicMock()
    coord.last_update_success = True
    coord.data = {}
    return coord


@pytest.fixture
def ms200_device():
    manager = MagicMock()
    hub = MagicMock()
    hub.online_status = OnlineStatus.ONLINE
    manager.find_devices.return_value = [hub]
    info = HttpSubdeviceInfo(
        sub_device_id="sub_ms200",
        sub_device_type="ms200",
        sub_device_name="Front Door",
        sub_device_icon_id="door_icon",
    )
    device = build_meross_subdevice(info, "hub_uuid", {}, manager)
    device._online = OnlineStatus.ONLINE
    return device


@pytest.fixture
def gs559a_device():
    manager = MagicMock()
    hub = MagicMock()
    hub.online_status = OnlineStatus.ONLINE
    hub._execute_command = AsyncMock()
    manager.find_devices.return_value = [hub]
    info = HttpSubdeviceInfo(
        sub_device_id="sub_gs559a",
        sub_device_type="gs559a",
        sub_device_name="Kitchen Smoke",
        sub_device_icon_id="smoke_icon",
    )
    device = build_meross_subdevice(info, "hub_uuid", {}, manager)
    device._online = OnlineStatus.ONLINE
    return device


class TestMs200Entities:
    def test_door_window_sensor_states(self, ms200_device, mock_coordinator):
        sensor = Ms200DoorWindowSensor(
            device=ms200_device,
            device_list_coordinator=mock_coordinator,
            channel=0,
        )

        assert sensor.should_poll is False

        # Initially None
        assert sensor.is_on is None

        # Opened
        ms200_device._handle_door_window_data(status=1, timestamp=1700000000)
        assert sensor.is_on is True
        assert sensor.extra_state_attributes["latest_sample_time"] is not None

        # Closed
        ms200_device._handle_door_window_data(status=0, timestamp=1700000050)
        assert sensor.is_on is False

        # Offline returns None
        ms200_device._online = OnlineStatus.OFFLINE
        assert sensor.is_on is None

    @pytest.mark.asyncio
    async def test_door_window_sensor_push_end_to_end(self, ms200_device, mock_coordinator):
        """Verify that push notifications delivered to the sensor update its state and trigger HA scheduling."""
        sensor = Ms200DoorWindowSensor(
            device=ms200_device,
            device_list_coordinator=mock_coordinator,
            channel=0,
        )
        mock_hass = MagicMock()
        mock_hass.data = {DOMAIN: {"ADDED_ENTITIES_IDS": set()}}
        sensor.hass = mock_hass
        sensor.async_schedule_update_ha_state = MagicMock()

        await sensor.async_added_to_hass()

        # Simulate push notification for door OPEN (status = 1)
        push_open = {
            "doorWindow": [
                {
                    "id": "sub_ms200",
                    "status": 1,
                    "lmTime": 1700000100,
                }
            ]
        }
        await ms200_device.async_handle_push_notification(Namespace.HUB_SENSOR_DOORWINDOW, push_open)

        assert sensor.is_on is True
        assert ms200_device.is_open is True
        sensor.async_schedule_update_ha_state.assert_called()

        # Simulate push notification for door CLOSED (status = 0)
        push_closed = {
            "doorWindow": [
                {
                    "id": "sub_ms200",
                    "status": 0,
                    "lmTime": 1700000200,
                }
            ]
        }
        await ms200_device.async_handle_push_notification(Namespace.HUB_SENSOR_DOORWINDOW, push_closed)

        assert sensor.is_on is False
        assert ms200_device.is_open is False

    @pytest.mark.asyncio
    async def test_door_window_sensor_multi_sensor_filtering(self, mock_coordinator):
        """Verify that in multi-sensor setups, push events for sensor B do not overwrite sensor A."""
        manager = MagicMock()
        hub = MagicMock()
        hub.online_status = OnlineStatus.ONLINE
        manager.find_devices.return_value = [hub]

        info1 = HttpSubdeviceInfo("sub_1", "ms200", "Sensor 1", "icon")
        info2 = HttpSubdeviceInfo("sub_2", "ms200", "Sensor 2", "icon")
        sensor1_dev = build_meross_subdevice(info1, "hub_uuid", {}, manager)
        sensor2_dev = build_meross_subdevice(info2, "hub_uuid", {}, manager)

        sensor1 = Ms200DoorWindowSensor(sensor1_dev, mock_coordinator, channel=0)
        sensor2 = Ms200DoorWindowSensor(sensor2_dev, mock_coordinator, channel=0)

        # Event specifically for sensor 2
        push_payload = {
            "doorWindow": [
                {"id": "sub_2", "status": 1, "lmTime": 1700000500}
            ]
        }
        await sensor1_dev.async_handle_push_notification(Namespace.HUB_SENSOR_DOORWINDOW, push_payload)
        await sensor2_dev.async_handle_push_notification(Namespace.HUB_SENSOR_DOORWINDOW, push_payload)

        # sensor 1 should still be untouched (None)
        assert sensor1.is_on is None
        # sensor 2 should be Open (True)
        assert sensor2.is_on is True

    @pytest.mark.asyncio
    async def test_door_window_sensor_initial_fetch_on_startup(self, ms200_device, mock_coordinator):
        """Verify that when added to Home Assistant with is_open is None, an initial fetch is triggered."""
        sensor = Ms200DoorWindowSensor(
            device=ms200_device,
            device_list_coordinator=mock_coordinator,
            channel=0,
        )
        mock_hass = MagicMock()
        mock_hass.data = {DOMAIN: {"ADDED_ENTITIES_IDS": set()}}
        def close_coro(coro):
            coro.close()
            return MagicMock()
        mock_hass.async_create_task.side_effect = close_coro
        sensor.hass = mock_hass

        assert sensor.is_on is None

        # Simulate hub answering async_update with current door state (closed)
        ms200_device.hub._execute_command = AsyncMock(return_value={
            'all': [
                {'id': 'sub_ms200', 'doorWindow': {'status': 0, 'lmTime': 1700000000}}
            ]
        })

        await sensor.async_added_to_hass()
        mock_hass.async_create_task.assert_called_once()

        await sensor._async_initial_update()
        assert sensor.is_on is False


class TestGs559aEntities:
    def test_smoke_sensor_states(self, gs559a_device, mock_coordinator):
        smoke_sensor = Gs559aSmokeAlarmSensor(
            device=gs559a_device,
            device_list_coordinator=mock_coordinator,
            channel=0,
        )
        assert smoke_sensor.should_poll is False

        # Normal ok state (170)
        gs559a_device._handle_smoke_data(status=170)
        assert smoke_sensor.is_on is False

        # Smoke alarm sounding (25)
        gs559a_device._handle_smoke_data(status=25)
        assert smoke_sensor.is_on is True

        # Smoke alarm muted (27)
        gs559a_device._handle_smoke_data(status=27)
        assert smoke_sensor.is_on is True

    def test_heat_sensor_states(self, gs559a_device, mock_coordinator):
        heat_sensor = Gs559aHeatAlarmSensor(
            device=gs559a_device,
            device_list_coordinator=mock_coordinator,
            channel=0,
        )
        assert heat_sensor.should_poll is False

        # Normal
        gs559a_device._handle_smoke_data(status=170)
        assert heat_sensor.is_on is False

        # Heat alarm sounding (24)
        gs559a_device._handle_smoke_data(status=24)
        assert heat_sensor.is_on is True

        # Heat alarm muted (26)
        gs559a_device._handle_smoke_data(status=26)
        assert heat_sensor.is_on is True

    def test_problem_sensor_states(self, gs559a_device, mock_coordinator):
        problem_sensor = Gs559aAlarmProblemSensor(
            device=gs559a_device,
            device_list_coordinator=mock_coordinator,
            channel=0,
        )
        assert problem_sensor.should_poll is False

        # Normal
        gs559a_device._handle_smoke_data(status=170)
        assert problem_sensor.is_on is False

        # Faults / Errors (17, 18, 19, 20, 21, 22)
        for err_code in [17, 18, 19, 20, 21, 22]:
            gs559a_device._handle_smoke_data(status=err_code)
            assert problem_sensor.is_on is True

    def test_test_sensor_states(self, gs559a_device, mock_coordinator):
        test_sensor = Gs559aAlarmTestSensor(
            device=gs559a_device,
            device_list_coordinator=mock_coordinator,
            channel=0,
        )
        assert test_sensor.should_poll is False

        gs559a_device._handle_smoke_data(status=170)
        assert test_sensor.is_on is False

        # Test mode active (23)
        gs559a_device._handle_smoke_data(status=23)
        assert test_sensor.is_on is True

    def test_muted_sensor_states(self, gs559a_device, mock_coordinator):
        muted_sensor = Gs559aAlarmMutedSensor(
            device=gs559a_device,
            device_list_coordinator=mock_coordinator,
            channel=0,
        )
        assert muted_sensor.should_poll is False

        gs559a_device._handle_smoke_data(status=170)
        assert muted_sensor.is_on is False

        for muted_code in [20, 21, 22, 26, 27]:
            gs559a_device._handle_smoke_data(status=muted_code)
            assert muted_sensor.is_on is True

    def test_status_sensor(self, gs559a_device, mock_coordinator):
        status_sensor = Gs559aStatusSensor(
            device=gs559a_device,
            device_list_coordinator=mock_coordinator,
            channel=0,
        )
        assert status_sensor.should_poll is False

        gs559a_device._handle_smoke_data(status=170, interconn=1, timestamp=1700000000)
        assert status_sensor.native_value == "ok"
        assert status_sensor.extra_state_attributes["raw_status"] == 170
        assert status_sensor.extra_state_attributes["interconnected"] is True

        gs559a_device._handle_smoke_data(status=25)
        assert status_sensor.native_value == "alarm_smoke"

    @pytest.mark.asyncio
    async def test_button_presses(self, gs559a_device, mock_coordinator):
        test_button = Gs559aTestButton(
            device=gs559a_device,
            device_list_coordinator=mock_coordinator,
            channel=0,
        )
        mute_button = Gs559aMuteButton(
            device=gs559a_device,
            device_list_coordinator=mock_coordinator,
            channel=0,
        )

        with pytest.MonkeyPatch().context() as mp:
            mock_test = AsyncMock()
            mock_mute = AsyncMock()
            mp.setattr(gs559a_device, "async_test_alarm", mock_test)
            mp.setattr(gs559a_device, "async_mute_alarm", mock_mute)

            await test_button.async_press()
            mock_test.assert_called_once_with(timeout=5.0)

            await mute_button.async_press()
            mock_mute.assert_called_once_with(timeout=5.0)

    @pytest.mark.asyncio
    async def test_smoke_sensor_push_end_to_end(self, gs559a_device, mock_coordinator):
        """Verify that smoke alarm push notifications update entity state and trigger HA scheduling."""
        smoke_sensor = Gs559aSmokeAlarmSensor(
            device=gs559a_device,
            device_list_coordinator=mock_coordinator,
            channel=0,
        )
        mock_hass = MagicMock()
        mock_hass.data = {DOMAIN: {"ADDED_ENTITIES_IDS": set()}}
        smoke_sensor.hass = mock_hass
        smoke_sensor.async_schedule_update_ha_state = MagicMock()

        await smoke_sensor.async_added_to_hass()

        push_alarm = {
            "smokeAlarm": [
                {
                    "id": "sub_gs559a",
                    "status": 25,
                    "lmTime": 1700000100,
                }
            ]
        }
        await gs559a_device.async_handle_push_notification(Namespace.HUB_SENSOR_SMOKE, push_alarm)
        assert smoke_sensor.is_on is True
        smoke_sensor.async_schedule_update_ha_state.assert_called()

        push_ok = {
            "smokeAlarm": [
                {
                    "id": "sub_gs559a",
                    "status": 170,
                    "lmTime": 1700000200,
                }
            ]
        }
        await gs559a_device.async_handle_push_notification(Namespace.HUB_SENSOR_SMOKE, push_ok)
        assert smoke_sensor.is_on is False


class TestBatterySensorStability:
    def test_battery_sensor_no_polling(self, ms200_device, mock_coordinator):
        """Verify BatterySensorWrapper has should_poll=False to avoid 30s query storms."""
        battery_sensor = BatterySensorWrapper(
            device=ms200_device,
            device_list_coordinator=mock_coordinator,
            channel=0,
        )
        assert battery_sensor.should_poll is False

    @pytest.mark.asyncio
    async def test_battery_sensor_async_update_timeout_resilience(self, ms200_device, mock_coordinator):
        """Verify BatterySensorWrapper.async_update gracefully catches timeouts without crashing."""
        mock_coordinator.data = {ms200_device.uuid: MagicMock(online_status=OnlineStatus.ONLINE)}
        battery_sensor = BatterySensorWrapper(
            device=ms200_device,
            device_list_coordinator=mock_coordinator,
            channel=0,
        )

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(ms200_device, "async_get_battery_life", AsyncMock(side_effect=TimeoutError("Timeout")))
            # Should not raise exception
            await battery_sensor.async_update()

    @pytest.mark.asyncio
    async def test_battery_sensor_native_value_and_push(self, ms200_device, mock_coordinator):
        """Verify BatterySensorWrapper.native_value reflects device battery and updates upon push."""
        battery_sensor = BatterySensorWrapper(
            device=ms200_device,
            device_list_coordinator=mock_coordinator,
            channel=0,
        )
        assert battery_sensor.native_value is None

        # Receive push notification with battery percentage
        await ms200_device.async_handle_push_notification(
            namespace=Namespace.HUB_BATTERY,
            data={'battery': [{'id': 'sub_ms200', 'value': 85}]}
        )
        assert ms200_device.battery_info is not None
        assert ms200_device.battery_info.remaining_charge == 85.0
        assert battery_sensor.native_value == 85.0
        assert battery_sensor.extra_state_attributes.get("latest_sample_time") is not None

    @pytest.mark.asyncio
    async def test_battery_sensor_initial_fetch_on_added_to_hass(self, ms200_device, mock_coordinator):
        """Verify BatterySensorWrapper triggers background fetch when added to hass if battery is unknown."""
        mock_coordinator.data = {ms200_device.uuid: MagicMock(online_status=OnlineStatus.ONLINE)}
        battery_sensor = BatterySensorWrapper(
            device=ms200_device,
            device_list_coordinator=mock_coordinator,
            channel=0,
        )
        mock_hass = MagicMock()
        def close_coro(coro):
            coro.close()
            return MagicMock()
        mock_hass.async_create_task.side_effect = close_coro
        battery_sensor.hass = mock_hass
        battery_sensor.platform = MagicMock()

        from datetime import datetime, timezone
        fake_bat = BatteryInfo(battery_charge=92.0, sample_ts=datetime.now(timezone.utc))
        ms200_device.async_get_battery_life = AsyncMock(return_value=fake_bat)

        await battery_sensor.async_added_to_hass()
        mock_hass.async_create_task.assert_called_once()

        await battery_sensor._async_initial_battery_fetch()
        assert battery_sensor.native_value == 92.0

    @pytest.mark.asyncio
    async def test_subdevice_get_battery_life_payload_variants(self, ms200_device):
        """Verify GenericSubDevice.async_get_battery_life handles multiple Meross hub response formats."""
        # 1. List format with 'value'
        ms200_device.hub._execute_command = AsyncMock(
            return_value={'battery': [{'id': 'sub_ms200', 'value': 77}]}
        )
        bat1 = await ms200_device.async_get_battery_life()
        assert bat1 is not None
        assert bat1.remaining_charge == 77.0

        # 2. Dict format with 'battery'
        ms200_device.hub._execute_command = AsyncMock(
            return_value={'battery': {'id': 'sub_ms200', 'battery': 64}}
        )
        bat2 = await ms200_device.async_get_battery_life()
        assert bat2 is not None
        assert bat2.remaining_charge == 64.0

        # 3. List format with 'batteryValue'
        ms200_device.hub._execute_command = AsyncMock(
            return_value={'battery': [{'id': 'sub_ms200', 'batteryValue': 52}]}
        )
        bat3 = await ms200_device.async_get_battery_life()
        assert bat3 is not None
        assert bat3.remaining_charge == 52.0

    @pytest.mark.asyncio
    async def test_gs559a_battery_push_and_subdevice_notification(self, gs559a_device):
        """Verify Gs559aSensor handles battery push and subdevice notifications."""
        await gs559a_device.async_handle_push_notification(
            namespace=Namespace.HUB_BATTERY,
            data={'battery': [{'id': 'sub_gs559a', 'value': 95}]}
        )
        assert gs559a_device.battery_info is not None
        assert gs559a_device.battery_info.remaining_charge == 95.0

        await gs559a_device.async_handle_subdevice_notification(
            namespace=Namespace.HUB_BATTERY,
            data={'id': 'sub_gs559a', 'value': 90}
        )
        assert gs559a_device.battery_info.remaining_charge == 90.0


class TestDeviceInfoFormatting:
    def test_ms200_device_info_clean_model_and_via_device(self, ms200_device, mock_coordinator):
        """Verify MS200 device info does NOT have 'unknown' suffix and has via_device pointing to hub."""
        sensor = Ms200DoorWindowSensor(
            device=ms200_device,
            device_list_coordinator=mock_coordinator,
            channel=0,
        )
        info = sensor.device_info
        assert info['model'] == "ms200"
        assert "unknown" not in info['model']
        assert "sw_version" not in info
        assert info['via_device'] == (DOMAIN, ms200_device.hub.internal_id)

    def test_gs559a_device_info_clean_model_and_via_device(self, gs559a_device, mock_coordinator):
        """Verify GS559A device info does NOT have 'unknown' suffix and has via_device pointing to hub."""
        sensor = Gs559aStatusSensor(
            device=gs559a_device,
            device_list_coordinator=mock_coordinator,
            channel=0,
        )
        info = sensor.device_info
        assert info['model'] == "gs559a"
        assert "unknown" not in info['model']
        assert "sw_version" not in info
        assert info['via_device'] == (DOMAIN, gs559a_device.hub.internal_id)

