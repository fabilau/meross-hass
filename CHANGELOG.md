# 1.4.0 (2026-10-06)
- **Fix Random Daily Freezes & Connection Deadlock**:
  - Solved deadlock in `_async_get_create_mqtt_client` where disconnected MQTT clients blocked forever waiting on `conn_evt.wait()` without a timeout. Added strict 15-second timeout and automatic reconnection fallback.
  - Fixed thread-safety violations: scheduled MQTT disconnect/subscribe events onto the asyncio loop using `call_soon_threadsafe()`.
  - Added exponential reconnect backoff (`reconnect_delay_set(min_delay=1, max_delay=30)`) to avoid broker disconnect bans.
  - Debounced reconnect subscribe handling (`_on_subscribe`) and staggered device status queries to prevent reconnect storms.
  - Fixed memory leak: guaranteed cleanup of `_pending_messages_futures` in `finally:` block on command timeouts.
  - Added background watchdog health-check (`async_health_check_and_heal`) in coordinator poll to detect stalled sockets and auto-heal.
  - Updated MQTT credentials dynamically on token renewal.
  - Fixed battery polling storm: disabled aggressive 30s polling on `BatterySensorWrapper` (`should_poll = False`) and added timeout protection.
- **Full Support for GS559A Smart Smoke and Heat Alarm**:
  - Smoke detection binary sensor (`smoke` device class)
  - Heat/high-temperature alarm binary sensor (`heat` device class)
  - Hardware/sensor problem & error binary sensor (`problem` device class)
  - Alarm test mode binary sensor (`safety` device class)
  - Alarm muted state binary sensor (`sound` device class)
  - Descriptive status sensor with raw status and interconnection state attributes
  - Button to trigger alarm sound test (`async_test_alarm`)
  - Button to mute/silence active alarm (`async_mute_alarm`)
  - Subdevice battery sensor
- **Full Support for MS200 Smart Door and Window Sensor**:
  - Open/closed binary sensor (`door` device class) with latest sample timestamp attributes
  - Subdevice battery sensor
- **Home Assistant Compatibility Fixes**:
  - Fixed options dialog ("Configure") crashing on Home Assistant 2025.12+ (`OptionsFlow.config_entry` can no longer be assigned).
  - Fixed setting light color temperature: Kelvin values were treated as mireds. Lights now use the Kelvin API (`color_temp_kelvin`, 2700–6500 K) instead of the deprecated mired properties.
  - Fixed crash (`AttributeError`) instead of re-authentication when the API rejected the token during setup.
  - Unloading now uses `async_unload_platforms`; the coordinator receives its config entry explicitly.
  - Fixed `NameError` on Python < 3.14 caused by a missing `MerossCloudCreds` import.
  - Removed invalid `domains` key from `hacs.json` (failed HACS validation).
- **New Diagnostic Tool & Comprehensive Test Suite**:
  - Added `tools/meross_diagnostic.py` CLI tool to validate real hardware accounts and observe live push notifications.
  - Added automated test suite in `tests/`: unit tests with mocked Home Assistant plus config flow, setup/unload, options and reauth tests against a real Home Assistant (CI: 2025.6 and 2026.2).

# 1.3.11 (2026-01-22)
- Address #584 (fix HTTP API server breaking changes)

# 1.3.1beta2 (2025-09-25)
- Address #567 (fix SSL blocking call and ATTR_COLOR_TEMP_KELVIN deprecation)

# 1.3.10beta1 (2025-09-21)
- Update low-level dependency to 0.4.9.2, so to address #569
- Attempt to address #479

# 1.3.9 (2025-08-22)
- Address #563: let HA re-authenticate in case of expired token or password change

# 1.3.8 (2025-08-22)
- Address #552, #568 and similar.

# 1.3.7 (2025-06-18)
- Merge #555 to fix config_entries.async_forward_entry_setup deprecation (thanks @Easen!)

# 1.3.6 (2025-03-17)
- Updated meross_iot dependency to 0.4.9.0 which fixes issues with paho-mqtt
- Set Min HA version to 2025.3

# 1.3.5 & 1.3.4 - RETIRED

# 1.3.2beta1 (2024-05-04)
- Using MerossIot v0.4.7.2b3 which should add support for HomeKit Hubs (addressing #435 and possibly #400)
- Add support for BatteryLevel sensors for Meross SubDevices
- Address #499

# 1.3.1 (2024-04-28)
- Fix light platform deprecations
- Fix climate platform deprecations
- Add OPENING and CLOSING transient states for garage openers (#493)
- Change log verbosity from INFO to DEBUG (addresses #481)

# 1.3.1beta1 (2024-04-25)
- Implement MFA support (addressing #467)
- Avoid storing username/password credentials (addressing #486)

<!--next-version-placeholder-->
# 1.3.0 (2024-04-25)
- Add support for Meross OilDiffuser
- Refactor Meross Humidifier
- Update low level library to version 0.4.7.0
- Addressing #484 

# 1.2.12 (2024-01-27)
- Merge PR #449, fixing #448. Credits to @mguilherme

# 1.2.11 (2024-01-27)
- Using the latest API Endpoints from Meross, version 0.4.6.0
- Fix logging errors
- Fix deprecated constants usage

# 1.2.10 (2023-10-15)
- Using the latest API Endpoints from Meross
- Supporting energy sensor for plugs (#460, thanks to @benoitm974)
- Fixes component unloading issue (thanks to @TheHolyRoger)
- Attention: this version is not compatible with local-only addon

# 1.2.9b0 (2023-09-18)
- Update low-level library to v0.4.6.0rc2 to support new API endpoints
- Merged PR #447

# 1.2.8 (2022-01-05)
- Update low-level library to v0.4.5.7, addressing issue #414

# 1.2.7 (2023-01-04)
- Update low-level library to v0.4.5.4 to solve issue #412

# 1.2.6 (2022-07-27)
- Add roller shutter (MSR100) support
- Add thermostat (MTS200) support
- Implement support for LAN-LOCAL HTTP transport mode
- Update dependency to low-level meross_iot library (0.4.5.0)

# 1.2.5rc5 (2022-06-24)
- Fix log error caused by wrong variable reference

# 1.2.5rc (2022-06-23)
- Set addon to run on internal network
- Set default values for IP:PORT when using local addon and no mDNS info is gathered.

# 1.2.5rc3 (2022-06-23)
- Set addon to run on host network to make mDNS work
- Improve setup & UI experience

# 1.2.5rc2 (2022-06-18)

- Fix import error preventing the component from loading via HA

# 1.2.5rc1 (2022-06-18) - RETIRED

- Removed zeroconf HA discovery support as it is now managed via setup config flow.
- This component is now working with the [Meross Local Addon](https://github.com/albertogeniola/ha-meross-local-broker) (still in alpha, though).

# 1.2.5rc0 (2022-06-12)

- Merges 1.2.4-rc1 features with the latest master release (v1.2.4)  

# 1.2.4 (2022-06-12)

- Merges pull request #365 that fixes MSS3XX consumption readings

## 1.2.4-rc1 (2022-06-06)

### Feature

- Updated low-level library to MerossIot v0.4.4.7

## 1.2.4-rc0 (2022-06-05)

### Feature

- Updated low-level library to MerossIot v0.4.4.6

## 1.2.3 (2022-06-03)

### Feature

- Updated low-level library to MerossIot v0.4.4.5

## 1.2.2 (2022-05-29)

### Feature

- Prepared component for integration with the Meross local-addon
- Updated HACS badge URL (thanks to @wrt54g)

## 1.2.1 (2022-01-30)

### Feature

- Upgraded low-level library dependency to 0.4.4.4
- Added MSG200 Support  
- Updated default polling intervals: sensor polling every 30s, API discovery every 120s
- Added option to set a custom user-agent for HTTP communication against Meross API


## 1.2.0rc2 (2022-01-18)

### Feature

- Upgraded low-level library dependency to 0.4.4.3
- Improved HACS documentation
- Added .devcontainer and .vscode tasks to support local-debugging
