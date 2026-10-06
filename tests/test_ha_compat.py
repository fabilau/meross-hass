"""Import every integration module against a real Home Assistant installation.

The other tests run against lightweight mocks (see conftest.py). This module only runs
when the real ``homeassistant`` package is installed and catches API incompatibilities
(removed constants, renamed classes, changed base classes) before a release.
"""
import importlib
import json
from pathlib import Path

import pytest

import homeassistant

if getattr(homeassistant, "__file__", None) is None:
    pytest.skip("real Home Assistant is not installed", allow_module_level=True)

COMPONENT_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "meross_cloud"
MODULES = sorted(p.stem for p in COMPONENT_DIR.glob("*.py") if p.stem != "__init__")


def test_component_package_imports():
    importlib.import_module("custom_components.meross_cloud")


@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module):
    importlib.import_module(f"custom_components.meross_cloud.{module}")


def test_platforms_expose_setup_entry():
    from custom_components.meross_cloud.common import MEROSS_PLATFORMS

    for platform in MEROSS_PLATFORMS:
        module = importlib.import_module(f"custom_components.meross_cloud.{platform}")
        assert callable(getattr(module, "async_setup_entry", None)), platform


def test_config_flow_registered():
    from homeassistant import config_entries
    from custom_components.meross_cloud import config_flow
    from custom_components.meross_cloud.common import DOMAIN

    assert issubclass(config_flow.MerossFlowHandler, config_entries.ConfigFlow)
    assert config_entries.HANDLERS.get(DOMAIN) is config_flow.MerossFlowHandler


def test_manifest_matches_hacs_minimum_version():
    from awesomeversion import AwesomeVersion

    manifest = json.loads((COMPONENT_DIR / "manifest.json").read_text())
    hacs = json.loads((COMPONENT_DIR.parent.parent / "hacs.json").read_text())
    assert manifest["domain"] == "meross_cloud"
    assert AwesomeVersion(manifest["version"]).valid
    assert AwesomeVersion(homeassistant.const.__version__) >= AwesomeVersion(hacs["homeassistant"])


async def test_light_color_temperature_uses_kelvin():
    from unittest.mock import AsyncMock, MagicMock
    from homeassistant.components.light import ATTR_COLOR_TEMP_KELVIN
    from custom_components.meross_cloud.light import (
        LightEntityWrapper, MAX_COLOR_TEMP_KELVIN, MIN_COLOR_TEMP_KELVIN,
    )

    device = MagicMock()
    device.name, device.type, device.internal_id, device.channels = "Bulb", "msl120", "uuid", []
    device.get_light_is_on.return_value = True
    device.get_supports_temperature.return_value = True
    device.async_set_light_color = AsyncMock()
    light = LightEntityWrapper(channel=0, device=device, device_list_coordinator=MagicMock())

    for kelvin, expected in ((MAX_COLOR_TEMP_KELVIN, 100), (MIN_COLOR_TEMP_KELVIN, 1), (1000, 1), (9000, 100)):
        await light.async_turn_on(**{ATTR_COLOR_TEMP_KELVIN: kelvin})
        assert device.async_set_light_color.await_args.kwargs["temperature"] == expected

    device.get_color_temperature.return_value = 100
    assert light.color_temp_kelvin == MAX_COLOR_TEMP_KELVIN
    device.get_color_temperature.return_value = 0
    assert light.color_temp_kelvin == MIN_COLOR_TEMP_KELVIN
    assert light.min_color_temp_kelvin == MIN_COLOR_TEMP_KELVIN
    assert light.max_color_temp_kelvin == MAX_COLOR_TEMP_KELVIN
