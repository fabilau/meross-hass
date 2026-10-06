"""Pytest configuration and mocks for Home Assistant and Meross tests."""
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

# Add repository root and custom_components/meross_cloud to sys.path
repo_root = Path(__file__).resolve().parent.parent
meross_cloud_dir = repo_root / "custom_components" / "meross_cloud"
if str(meross_cloud_dir) not in sys.path:
    sys.path.insert(0, str(meross_cloud_dir))
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))


# If homeassistant is not installed in the environment, install lightweight mock modules
def _install_ha_mocks():
    if "homeassistant" in sys.modules:
        return

    # Base homeassistant module
    ha = types.ModuleType("homeassistant")
    ha.core = types.ModuleType("homeassistant.core")
    ha.core.HomeAssistant = MagicMock()
    ha.core.callback = lambda fn: fn

    ha.const = types.ModuleType("homeassistant.const")
    ha.const.CONF_USERNAME = "username"
    ha.const.CONF_PASSWORD = "password"
    ha.const.CONF_SCAN_INTERVAL = "scan_interval"
    ha.const.PERCENTAGE = "%"

    class EntityCategory:
        DIAGNOSTIC = "diagnostic"
        CONFIG = "config"
    ha.const.EntityCategory = EntityCategory

    class UnitOfTemperature:
        CELSIUS = "°C"
        FAHRENHEIT = "°F"
    ha.const.UnitOfTemperature = UnitOfTemperature

    class UnitOfPower:
        WATT = "W"
        KILOWATT = "kW"
    ha.const.UnitOfPower = UnitOfPower

    ha.exceptions = types.ModuleType("homeassistant.exceptions")
    class ConfigEntryNotReady(Exception):
        pass
    class ConfigEntryAuthFailed(Exception):
        pass
    class HomeAssistantError(Exception):
        pass
    ha.exceptions.ConfigEntryNotReady = ConfigEntryNotReady
    ha.exceptions.ConfigEntryAuthFailed = ConfigEntryAuthFailed
    ha.exceptions.HomeAssistantError = HomeAssistantError

    # config_entries
    ha.config_entries = types.ModuleType("homeassistant.config_entries")
    ha.config_entries.ConfigEntry = MagicMock

    # helpers
    ha.helpers = types.ModuleType("homeassistant.helpers")
    ha.helpers.config_validation = types.ModuleType("homeassistant.helpers.config_validation")
    ha.helpers.config_validation.string = str
    ha.helpers.config_validation.boolean = bool

    # entity
    ha.helpers.entity = types.ModuleType("homeassistant.helpers.entity")
    class MockEntity:
        def __init__(self, *args, **kwargs):
            self._attr_extra_state_attributes = {}
            self._attr_device_class = None
            self._attr_entity_category = None
            self._attr_translation_key = None
            self.hass = MagicMock()

        @property
        def name(self):
            return getattr(self, "_name", "MockEntity")

        @property
        def should_poll(self):
            return getattr(self, "_attr_should_poll", False)

        def async_write_ha_state(self):
            pass

    ha.helpers.entity.Entity = MockEntity

    # update_coordinator
    ha.helpers.update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")
    class MockDataUpdateCoordinator:
        def __init__(self, *args, **kwargs):
            self.data = {}
        async def async_request_refresh(self):
            pass
    class UpdateFailed(Exception):
        pass
    ha.helpers.update_coordinator.DataUpdateCoordinator = MockDataUpdateCoordinator
    ha.helpers.update_coordinator.CoordinatorEntity = MockEntity
    ha.helpers.update_coordinator.UpdateFailed = UpdateFailed

    # util.ssl
    ha.util = types.ModuleType("homeassistant.util")
    ha.util.ssl = types.ModuleType("homeassistant.util.ssl")
    ha.util.ssl.get_default_context = MagicMock()
    ha.util.ssl.get_default_no_verify_context = MagicMock()

    # components
    ha.components = types.ModuleType("homeassistant.components")

    # binary_sensor
    ha.components.binary_sensor = types.ModuleType("homeassistant.components.binary_sensor")
    class BinarySensorDeviceClass:
        DOOR = "door"
        WINDOW = "window"
        SMOKE = "smoke"
        HEAT = "heat"
        SAFETY = "safety"
        SOUND = "sound"
        PROBLEM = "problem"
        BATTERY = "battery"
        MOTION = "motion"
    class BinarySensorEntity(MockEntity):
        @property
        def is_on(self):
            return getattr(self, "_attr_is_on", None)
    ha.components.binary_sensor.BinarySensorDeviceClass = BinarySensorDeviceClass
    ha.components.binary_sensor.BinarySensorEntity = BinarySensorEntity

    # sensor
    ha.components.sensor = types.ModuleType("homeassistant.components.sensor")
    class SensorDeviceClass:
        BATTERY = "battery"
        TEMPERATURE = "temperature"
        HUMIDITY = "humidity"
        POWER = "power"
    class SensorStateClass:
        MEASUREMENT = "measurement"
        TOTAL = "total"
    class SensorEntity(MockEntity):
        @property
        def native_value(self):
            return getattr(self, "_attr_native_value", None)
    ha.components.sensor.SensorDeviceClass = SensorDeviceClass
    ha.components.sensor.SensorStateClass = SensorStateClass
    ha.components.sensor.SensorEntity = SensorEntity

    # button
    ha.components.button = types.ModuleType("homeassistant.components.button")
    class ButtonDeviceClass:
        IDENTIFY = "identify"
        RESTART = "restart"
        UPDATE = "update"
    class ButtonEntity(MockEntity):
        async def async_press(self):
            pass
    ha.components.button.ButtonDeviceClass = ButtonDeviceClass
    ha.components.button.ButtonEntity = ButtonEntity

    # switch
    ha.components.switch = types.ModuleType("homeassistant.components.switch")
    class SwitchEntity(MockEntity):
        pass
    ha.components.switch.SwitchEntity = SwitchEntity

    # light
    ha.components.light = types.ModuleType("homeassistant.components.light")
    class LightEntity(MockEntity):
        pass
    ha.components.light.LightEntity = LightEntity

    # climate
    ha.components.climate = types.ModuleType("homeassistant.components.climate")
    class ClimateEntity(MockEntity):
        pass
    ha.components.climate.ClimateEntity = ClimateEntity

    # cover
    ha.components.cover = types.ModuleType("homeassistant.components.cover")
    class CoverEntity(MockEntity):
        pass
    ha.components.cover.CoverEntity = CoverEntity

    # fan
    ha.components.fan = types.ModuleType("homeassistant.components.fan")
    class FanEntity(MockEntity):
        pass
    ha.components.fan.FanEntity = FanEntity

    ha.helpers.typing = types.ModuleType("homeassistant.helpers.typing")
    ha.helpers.typing.StateType = object

    # Register into sys.modules
    for mod_name, mod in [
        ("homeassistant", ha),
        ("homeassistant.core", ha.core),
        ("homeassistant.const", ha.const),
        ("homeassistant.exceptions", ha.exceptions),
        ("homeassistant.config_entries", ha.config_entries),
        ("homeassistant.helpers", ha.helpers),
        ("homeassistant.helpers.config_validation", ha.helpers.config_validation),
        ("homeassistant.helpers.entity", ha.helpers.entity),
        ("homeassistant.helpers.update_coordinator", ha.helpers.update_coordinator),
        ("homeassistant.helpers.typing", ha.helpers.typing),
        ("homeassistant.util", ha.util),
        ("homeassistant.util.ssl", ha.util.ssl),
        ("homeassistant.components", ha.components),
        ("homeassistant.components.binary_sensor", ha.components.binary_sensor),
        ("homeassistant.components.sensor", ha.components.sensor),
        ("homeassistant.components.button", ha.components.button),
        ("homeassistant.components.switch", ha.components.switch),
        ("homeassistant.components.light", ha.components.light),
        ("homeassistant.components.climate", ha.components.climate),
        ("homeassistant.components.cover", ha.components.cover),
        ("homeassistant.components.fan", ha.components.fan),
    ]:
        sys.modules[mod_name] = mod


_install_ha_mocks()
