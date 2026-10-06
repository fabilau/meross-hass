"""End-to-end tests inside a real Home Assistant instance.

Requires ``pytest-homeassistant-custom-component`` (see requirements_ha.txt). The Meross
cloud is mocked; everything on the Home Assistant side (config flow, entry setup,
platform forwarding, options flow, reauth) runs for real.
"""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant import config_entries  # noqa: E402
from homeassistant.config_entries import ConfigEntryState  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.meross_cloud.common import (  # noqa: E402
    CONF_HTTP_ENDPOINT,
    CONF_MQTT_SKIP_CERT_VALIDATION,
    CONF_OPT_CUSTOM_USER_AGENT,
    CONF_OPT_LAN,
    CONF_OPT_LAN_HTTP_FIRST,
    CONF_OVERRIDE_MQTT_ENDPOINT,
    CONF_STORED_CREDS,
    CONF_WORKING_MODE,
    CONF_WORKING_MODE_CLOUD_MODE,
    DOMAIN,
)
from meross_iot.model.credentials import MerossCloudCreds  # noqa: E402
from meross_iot.model.http.exception import BadLoginException, UnauthorizedException  # noqa: E402

API_URL = "https://iotx-eu.meross.com"
PKG = "custom_components.meross_cloud"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def _creds() -> MerossCloudCreds:
    return MerossCloudCreds(
        token="token",
        key="key",
        user_id="user-id",
        user_email="user@example.com",
        issued_on=datetime(2026, 1, 1),
        domain=API_URL,
        mqtt_domain="mqtt-eu.meross.com",
    )


def _entry_data() -> dict:
    creds = _creds()
    return {
        CONF_HTTP_ENDPOINT: API_URL,
        CONF_OVERRIDE_MQTT_ENDPOINT: None,
        CONF_MQTT_SKIP_CERT_VALIDATION: False,
        CONF_STORED_CREDS: {
            "domain": creds.domain,
            "mqtt_domain": creds.mqtt_domain,
            "token": creds.token,
            "key": creds.key,
            "user_id": creds.user_id,
            "user_email": creds.user_email,
            "issued_on": creds.issued_on.isoformat(),
        },
    }


@pytest.fixture
def mock_cloud():
    """Mock the Meross HTTP client and MQTT manager used during entry setup."""
    client = MagicMock()
    client.async_list_devices = AsyncMock(return_value=[])
    manager = MagicMock()
    manager.async_init = AsyncMock()
    manager.async_device_discovery = AsyncMock(return_value=[])
    manager.async_health_check_and_heal = AsyncMock()
    manager.find_devices.return_value = []
    with patch(f"{PKG}.get_or_test_creds", AsyncMock(return_value=(client, [], False))), \
            patch(f"{PKG}.MerossManager", return_value=manager):
        yield manager


async def test_config_flow_cloud_creates_entry(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_WORKING_MODE: CONF_WORKING_MODE_CLOUD_MODE}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "configure_manager"

    with patch(f"{PKG}.config_flow.MerossFlowHandler._test_authorization", AsyncMock(return_value=_creds())), \
            patch(f"{PKG}.async_setup_entry", AsyncMock(return_value=True)), \
            patch(f"{PKG}.async_unload_entry", AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_HTTP_ENDPOINT: API_URL,
                "username": "user@example.com",
                "password": "secret",
                CONF_MQTT_SKIP_CERT_VALIDATION: False,
            },
        )
        await hass.async_block_till_done()
        # Unload while the setup/unload mocks are still active
        assert await hass.config_entries.async_unload(result["result"].entry_id)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == API_URL
    data = result["data"]
    assert data[CONF_HTTP_ENDPOINT] == API_URL
    assert data[CONF_STORED_CREDS]["token"] == "token"
    assert "password" not in data and "secret" not in str(data)


async def test_config_flow_invalid_credentials(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_WORKING_MODE: CONF_WORKING_MODE_CLOUD_MODE}
    )
    with patch(f"{PKG}.config_flow.MerossFlowHandler._test_authorization",
               AsyncMock(side_effect=BadLoginException("bad"))):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_HTTP_ENDPOINT: API_URL,
                "username": "user@example.com",
                "password": "wrong",
                CONF_MQTT_SKIP_CERT_VALIDATION: False,
            },
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_credentials"}


async def test_setup_and_unload_entry(hass, mock_cloud):
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data(), unique_id=API_URL)
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    mock_cloud.async_init.assert_awaited_once()
    mock_cloud.async_device_discovery.assert_awaited()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    mock_cloud.close.assert_called_once()


async def test_options_flow(hass, mock_cloud):
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data(), unique_id=API_URL)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_OPT_CUSTOM_USER_AGENT: "test-agent", CONF_OPT_LAN: CONF_OPT_LAN_HTTP_FIRST},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_OPT_CUSTOM_USER_AGENT: "test-agent", CONF_OPT_LAN: CONF_OPT_LAN_HTTP_FIRST}


async def test_expired_token_starts_reauth(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data(), unique_id=API_URL)
    entry.add_to_hass(hass)

    with patch(f"{PKG}.get_or_test_creds", AsyncMock(side_effect=UnauthorizedException())):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(flow["context"]["source"] == config_entries.SOURCE_REAUTH for flow in flows)
