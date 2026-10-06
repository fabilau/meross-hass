"""Tests for MerossManager connection stability, deadlock prevention, and leak prevention."""
import asyncio
import time
from unittest.mock import MagicMock, AsyncMock, patch
import pytest

from meross_iot.manager import MerossManager
from meross_iot.model.credentials import MerossCloudCreds
from meross_iot.model.exception import CommandTimeoutError


@pytest.fixture
def manager_instance():
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    creds = MerossCloudCreds(
        token="test_token",
        key="test_key",
        user_id="test_user_id",
        user_email="test@example.com",
        issued_on="2026-01-01T00:00:00",
        domain="iot.meross.com",
        mqtt_domain="iot.meross.com",
    )
    mock_http_client = MagicMock()
    mock_http_client.cloud_credentials = creds
    mgr = MerossManager(
        http_client=mock_http_client,
        loop=loop,
        auto_reconnect=True,
        mqtt_ssl_context=MagicMock(),
    )
    yield mgr
    mgr.close()


class TestManagerStability:
    @pytest.mark.asyncio
    async def test_get_create_mqtt_client_timeout_prevents_deadlock(self, manager_instance):
        """Verify that when an MQTT connection attempt never completes, it raises CommandTimeoutError within 15s (tested with short timeout)."""
        mgr = manager_instance
        domain = "iot.meross.com"
        port = 443

        mock_client = MagicMock()
        mock_client.is_connected.return_value = False

        with patch.object(mgr, "_new_mqtt_client", return_value=mock_client), \
             patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
            with pytest.raises(CommandTimeoutError) as exc_info:
                await mgr._async_get_create_mqtt_client(domain=domain, port=port)

            assert "timed out after 15s" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_pending_futures_cleaned_up_on_timeout(self, manager_instance):
        """Verify that when async_execute_cmd_client times out, the pending message future is removed from dict (preventing memory leak)."""
        mgr = manager_instance
        mock_client = MagicMock()
        mock_client.is_connected.return_value = True

        destination_uuid = "test_uuid_123"
        method = "GET"
        namespace = "Appliance.System.All"
        payload = {}

        with patch.object(
            mgr,
            "_async_send_and_wait_ack",
            side_effect=CommandTimeoutError(
                message="timeout", target_device_uuid=destination_uuid, timeout=0.1
            ),
        ):
            with pytest.raises(CommandTimeoutError):
                await mgr.async_execute_cmd_client(
                    client=mock_client,
                    destination_device_uuid=destination_uuid,
                    method=method,
                    namespace=namespace,
                    payload=payload,
                    timeout=0.1,
                )

            # Crucial assertion: dict must be empty after timeout, not leaked!
            assert len(mgr._pending_messages_futures) == 0

    def test_on_disconnect_threadsafe_clear(self, manager_instance):
        """Verify that _on_disconnect clears the connection event via threadsafe scheduling."""
        mgr = manager_instance
        dict_key = "iot.meross.com:443"
        conn_evt = asyncio.Event()
        conn_evt.set()
        assert conn_evt.is_set()

        mgr._mqtt_connected_and_subscribed[dict_key] = conn_evt

        mock_client = MagicMock()
        with patch.object(mgr._loop, "call_soon_threadsafe") as mock_threadsafe, \
             patch.object(mgr, "_notify_connection_drop", return_value=AsyncMock()()):
            mgr._on_disconnect(client=mock_client, userdata=dict_key, rc=1)

            mock_threadsafe.assert_called_with(conn_evt.clear)

    def test_on_subscribe_threadsafe_set_and_debounce(self, manager_instance):
        """Verify that _on_subscribe sets the event safely and debounces reconnect storm."""
        mgr = manager_instance
        dict_key = "iot.meross.com:443"
        conn_evt = asyncio.Event()
        assert not conn_evt.is_set()

        mgr._mqtt_connected_and_subscribed[dict_key] = conn_evt
        mock_client = MagicMock()

        with patch.object(mgr._loop, "call_soon_threadsafe") as mock_threadsafe, \
             patch("asyncio.run_coroutine_threadsafe"):
            # First subscribe call
            mgr._on_subscribe(client=mock_client, userdata=dict_key, mid=1, granted_qos=[1])
            mock_threadsafe.assert_any_call(conn_evt.set)
            assert hasattr(mgr, "_last_reconnect_update_ts")
            first_ts = mgr._last_reconnect_update_ts

            # Second immediate subscribe call should be debounced
            mock_threadsafe.reset_mock()
            mgr._on_subscribe(client=mock_client, userdata=dict_key, mid=2, granted_qos=[1])
            # The event is still set threadsafe, but post-reconnect update storm is skipped
            mock_threadsafe.assert_any_call(conn_evt.set)
            assert mgr._last_reconnect_update_ts == first_ts

    def test_update_credentials(self, manager_instance):
        """Verify update_credentials updates cloud credentials and MQTT client passwords dynamically."""
        mgr = manager_instance
        new_creds = MerossCloudCreds(
            token="new_token",
            key="new_key",
            user_id="new_user_id",
            user_email="new@example.com",
            issued_on="2026-02-01T00:00:00",
            domain="iot.meross.com",
            mqtt_domain="iot.meross.com",
        )

        mock_client = MagicMock()
        mgr._mqtt_clients["iot.meross.com:443"] = mock_client

        mgr.update_credentials(new_creds)

        assert mgr._cloud_creds == new_creds
        mock_client.username_pw_set.assert_called_once()
        call_args = mock_client.username_pw_set.call_args[1]
        assert call_args["username"] == "new_user_id"
        assert call_args["password"] is not None

    @pytest.mark.asyncio
    async def test_health_check_and_heal(self, manager_instance):
        """Verify async_health_check_and_heal detects disconnected client and initiates reconnect."""
        mgr = manager_instance
        dict_key = "iot.meross.com:443"
        mock_client = MagicMock()
        mock_client.is_connected.return_value = False

        mgr._mqtt_clients[dict_key] = mock_client
        conn_evt = asyncio.Event()
        conn_evt.set()
        mgr._mqtt_connected_and_subscribed[dict_key] = conn_evt

        with patch.object(mgr._loop, "call_soon_threadsafe") as mock_threadsafe:
            all_healthy = await mgr.async_health_check_and_heal()

            assert all_healthy is False
            mock_threadsafe.assert_called_with(conn_evt.clear)
            mock_client.reconnect.assert_called_once()
