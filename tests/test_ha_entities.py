"""Unit tests for Home Assistant entities: MS200 and GS559A platforms."""
import pytest
from unittest.mock import MagicMock, AsyncMock

from meross_iot.controller.subdevice import Ms200Sensor, Gs559aSensor
from meross_iot.model.enums import OnlineStatus
from meross_iot.model.http.subdevice import HttpSubdeviceInfo
from meross_iot.device_factory import build_meross_subdevice

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
