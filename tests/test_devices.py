"""Unit tests for newly added Meross devices: MS200 and GS559A."""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock

from meross_iot.controller.subdevice import Ms200Sensor, Gs559aSensor
from meross_iot.device_factory import build_meross_subdevice
from meross_iot.model.enums import Namespace, OnlineStatus
from meross_iot.model.http.subdevice import HttpSubdeviceInfo


@pytest.fixture
def mock_hub_and_manager():
    mock_manager = MagicMock()
    mock_hub = MagicMock()
    mock_hub.online_status = OnlineStatus.ONLINE
    mock_hub._execute_command = AsyncMock()
    mock_manager.find_devices.return_value = [mock_hub]
    return mock_hub, mock_manager


class TestMs200Sensor:
    def test_factory_creation(self, mock_hub_and_manager):
        mock_hub, mock_manager = mock_hub_and_manager

        for dev_type in ["ms200", "ms200h", "doorwindow"]:
            info = HttpSubdeviceInfo(
                sub_device_id=f"id_{dev_type}",
                sub_device_type=dev_type,
                sub_device_name=f"Door {dev_type}",
                sub_device_icon_id="icon1",
            )
            device = build_meross_subdevice(info, "hub_uuid", {}, mock_manager)
            assert isinstance(device, Ms200Sensor)
            assert device.subdevice_id == f"id_{dev_type}"
            assert device.name == f"Door {dev_type}"

    def test_initial_state(self, mock_hub_and_manager):
        _, mock_manager = mock_hub_and_manager
        sensor = Ms200Sensor(
            hubdevice_uuid="hub_1",
            subdevice_id="sub_1",
            manager=mock_manager,
            subdevice_type="ms200",
            name="Front Door",
        )
        assert sensor.is_open is None
        assert sensor.latest_sample_time is None
        assert sensor.last_sampled_time is None

    @pytest.mark.asyncio
    async def test_push_notification_door_open_closed(self, mock_hub_and_manager):
        _, mock_manager = mock_hub_and_manager
        sensor = Ms200Sensor(
            hubdevice_uuid="hub_1",
            subdevice_id="sub_1",
            manager=mock_manager,
            subdevice_type="ms200",
            name="Front Door",
        )

        # Push notification: Door Open (status = 1)
        push_open = {
            "doorWindow": {
                "id": "sub_1",
                "status": 1,
                "lmTime": 1700000000,
            }
        }
        handled = await sensor.async_handle_push_notification(
            Namespace.HUB_SENSOR_DOORWINDOW, push_open
        )
        assert handled is True
        assert sensor.is_open is True
        assert sensor.latest_sample_time == 1700000000
        assert sensor.last_sampled_time == datetime.fromtimestamp(1700000000, tz=timezone.utc)

        # Push notification: Door Closed (status = 0)
        push_closed = {
            "doorWindow": {
                "id": "sub_1",
                "status": 0,
                "lmTime": 1700000050,
            }
        }
        handled = await sensor.async_handle_push_notification(
            Namespace.HUB_SENSOR_DOORWINDOW, push_closed
        )
        assert handled is True
        assert sensor.is_open is False
        assert sensor.latest_sample_time == 1700000050

    @pytest.mark.asyncio
    async def test_push_notification_as_list(self, mock_hub_and_manager):
        _, mock_manager = mock_hub_and_manager
        sensor = Ms200Sensor(
            hubdevice_uuid="hub_1",
            subdevice_id="sub_1",
            manager=mock_manager,
            subdevice_type="ms200",
            name="Front Door",
        )

        # Some hubs wrap payload in a list
        push_list = {
            "doorWindow": [
                {
                    "id": "sub_1",
                    "status": 1,
                    "latestSampleTime": 1700001000,
                }
            ]
        }
        handled = await sensor.async_handle_push_notification(
            Namespace.HUB_SENSOR_DOORWINDOW, push_list
        )
        assert handled is True
        assert sensor.is_open is True
        assert sensor.latest_sample_time == 1700001000

    @pytest.mark.asyncio
    async def test_subdevice_notification_all_payload(self, mock_hub_and_manager):
        _, mock_manager = mock_hub_and_manager
        sensor = Ms200Sensor(
            hubdevice_uuid="hub_1",
            subdevice_id="sub_1",
            manager=mock_manager,
            subdevice_type="ms200",
            name="Front Door",
        )

        all_data = {
            "id": "sub_1",
            "online": {"status": 1, "lastActiveTime": 1700002000},
            "doorWindow": {"status": 0, "lmTime": 1700002000},
        }
        handled = await sensor.async_handle_subdevice_notification(
            Namespace.HUB_SENSOR_ALL, all_data
        )
        assert handled is True
        assert sensor.is_open is False
        assert sensor.online_status == OnlineStatus.ONLINE


class TestGs559aSensor:
    def test_factory_creation(self, mock_hub_and_manager):
        mock_hub, mock_manager = mock_hub_and_manager

        for dev_type in ["gs559", "gs559a", "gs559ah", "smokealarm"]:
            info = HttpSubdeviceInfo(
                sub_device_id=f"id_{dev_type}",
                sub_device_type=dev_type,
                sub_device_name=f"Smoke {dev_type}",
                sub_device_icon_id="icon_smoke",
            )
            device = build_meross_subdevice(info, "hub_uuid", {}, mock_manager)
            assert isinstance(device, Gs559aSensor)
            assert device.subdevice_id == f"id_{dev_type}"
            assert device.name == f"Smoke {dev_type}"

    def test_initial_state(self, mock_hub_and_manager):
        _, mock_manager = mock_hub_and_manager
        sensor = Gs559aSensor(
            hubdevice_uuid="hub_1",
            subdevice_id="sub_smoke",
            manager=mock_manager,
            subdevice_type="gs559a",
            name="Living Room Smoke",
        )
        assert sensor.status is None
        assert sensor.status_description == "unknown"
        assert sensor.is_alarm_active is False
        assert sensor.is_smoke_alarm is False
        assert sensor.is_heat_alarm is False
        assert sensor.is_test_alarm is False
        assert sensor.is_error is False
        assert sensor.is_muted is False
        assert sensor.is_interconnected is None

    @pytest.mark.parametrize(
        "status_code, expected_desc, expected_alarm, expected_smoke, expected_heat, expected_test, expected_error, expected_muted",
        [
            (170, "ok", False, False, False, False, False, False),
            (25, "alarm_smoke", True, True, False, False, False, False),
            (24, "alarm_temperature_high", True, False, True, False, False, False),
            (23, "alarm_test", True, False, False, True, False, False),
            (27, "alarm_smoke_muted", True, True, False, False, False, True),
            (26, "alarm_temperature_high_muted", True, False, True, False, False, True),
            (17, "error_temperature", False, False, False, False, True, False),
            (18, "error_smoke", False, False, False, False, True, False),
            (19, "error_battery", False, False, False, False, True, False),
            (20, "error_temperature_muted", False, False, False, False, True, True),
            (21, "error_smoke_muted", False, False, False, False, True, True),
            (22, "error_battery_muted", False, False, False, False, True, True),
        ],
    )
    def test_status_code_mappings(
        self,
        mock_hub_and_manager,
        status_code,
        expected_desc,
        expected_alarm,
        expected_smoke,
        expected_heat,
        expected_test,
        expected_error,
        expected_muted,
    ):
        _, mock_manager = mock_hub_and_manager
        sensor = Gs559aSensor(
            hubdevice_uuid="hub_1",
            subdevice_id="sub_smoke",
            manager=mock_manager,
            subdevice_type="gs559a",
        )
        sensor._handle_smoke_data(status=status_code)

        assert sensor.status == status_code
        assert sensor.status_description == expected_desc
        assert sensor.is_alarm_active == expected_alarm
        assert sensor.is_smoke_alarm == expected_smoke
        assert sensor.is_heat_alarm == expected_heat
        assert sensor.is_test_alarm == expected_test
        assert sensor.is_error == expected_error
        assert sensor.is_muted == expected_muted

    @pytest.mark.asyncio
    async def test_push_notification_smoke_alarm(self, mock_hub_and_manager):
        _, mock_manager = mock_hub_and_manager
        sensor = Gs559aSensor(
            hubdevice_uuid="hub_1",
            subdevice_id="sub_smoke",
            manager=mock_manager,
            subdevice_type="gs559a",
        )

        push_data = {
            "smokeAlarm": {
                "id": "sub_smoke",
                "status": 25,
                "interConn": 1,
                "lmTime": 1700005000,
            }
        }
        handled = await sensor.async_handle_push_notification(
            Namespace.HUB_SENSOR_SMOKE, push_data
        )
        assert handled is True
        assert sensor.is_smoke_alarm is True
        assert sensor.is_alarm_active is True
        assert sensor.is_interconnected is True
        assert sensor.latest_sample_time == 1700005000
        assert sensor.last_sampled_time == datetime.fromtimestamp(1700005000, tz=timezone.utc)

    @pytest.mark.asyncio
    async def test_push_notification_alternative_smoke_key(self, mock_hub_and_manager):
        _, mock_manager = mock_hub_and_manager
        sensor = Gs559aSensor(
            hubdevice_uuid="hub_1",
            subdevice_id="sub_smoke",
            manager=mock_manager,
            subdevice_type="gs559a",
        )

        push_data = {
            "smoke": [
                {
                    "id": "sub_smoke",
                    "status": 170,
                    "interConn": 0,
                    "latestSampleTime": 1700006000,
                }
            ]
        }
        handled = await sensor.async_handle_push_notification(
            Namespace.HUB_SENSOR_SMOKE, push_data
        )
        assert handled is True
        assert sensor.status == 170
        assert sensor.status_description == "ok"
        assert sensor.is_alarm_active is False
        assert sensor.is_interconnected is False

    @pytest.mark.asyncio
    async def test_async_test_alarm(self, mock_hub_and_manager):
        mock_hub, mock_manager = mock_hub_and_manager
        sensor = Gs559aSensor(
            hubdevice_uuid="hub_1",
            subdevice_id="sub_smoke",
            manager=mock_manager,
            subdevice_type="gs559a",
        )

        await sensor.async_test_alarm()

        mock_hub._execute_command.assert_called_once_with(
            method="SET",
            namespace=Namespace.HUB_SENSOR_SMOKE,
            payload={"smokeAlarm": [{"id": "sub_smoke", "status": 23}]},
            timeout=None,
        )
        assert sensor.is_test_alarm is True
        assert sensor.status == 23

    @pytest.mark.asyncio
    async def test_async_mute_alarm(self, mock_hub_and_manager):
        mock_hub, mock_manager = mock_hub_and_manager
        sensor = Gs559aSensor(
            hubdevice_uuid="hub_1",
            subdevice_id="sub_smoke",
            manager=mock_manager,
            subdevice_type="gs559a",
        )

        # Active smoke alarm (25) -> mute target is 27
        sensor._handle_smoke_data(status=25)
        assert sensor.is_smoke_alarm is True
        assert sensor.is_muted is False

        await sensor.async_mute_alarm()

        mock_hub._execute_command.assert_called_with(
            method="SET",
            namespace=Namespace.HUB_SENSOR_SMOKE,
            payload={"smokeAlarm": [{"id": "sub_smoke", "status": 27}]},
            timeout=None,
        )
        assert sensor.is_muted is True
        assert sensor.status == 27


class TestManifestAndHacsJson:
    def test_manifest_and_hacs_structure(self):
        import json
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        manifest_path = repo_root / "custom_components" / "meross_cloud" / "manifest.json"
        hacs_path = repo_root / "hacs.json"

        assert manifest_path.is_file(), "manifest.json must exist"
        assert hacs_path.is_file(), "hacs.json must exist"

        manifest = json.loads(manifest_path.read_text())
        assert manifest.get("domain") == "meross_cloud"
        assert manifest.get("name")
        assert manifest.get("version")
        assert manifest.get("documentation")
        assert manifest.get("issue_tracker")
        assert isinstance(manifest.get("codeowners"), list)

        hacs = json.loads(hacs_path.read_text())
        assert hacs.get("name")
        assert "domains" not in hacs, "'domains' key is forbidden in hacs.json"

