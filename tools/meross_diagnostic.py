#!/usr/bin/env python3
"""
Meross Diagnostic & Live Hardware Validation Tool
=================================================
This tool connects to your real Meross cloud account and validates:
1. Cloud authentication and MQTT token generation.
2. Device discovery (including Hubs, Smart Plugs, Garage Openers, etc.).
3. Subdevice recognition for GS559A (Smoke Alarm) and MS200 (Door/Window Sensor).
4. Real-time push notification monitoring (optional live event test).

Usage:
------
    python3 tools/meross_diagnostic.py --email "user@example.com" --password "secret"

Or using environment variables:
    export MEROSS_EMAIL="user@example.com"
    export MEROSS_PASSWORD="secret"
    python3 tools/meross_diagnostic.py

Optional flags:
    --listen 30       Listen for real-time device pushes for 30 seconds
    --dump            Save sanitized device JSON to meross_discovery_dump.json
"""

import os
import sys
from pathlib import Path

# Auto-detect virtualenv or switch to .venv if required packages are missing
_REPO_ROOT = Path(__file__).resolve().parent.parent
_VENV_PYTHON = _REPO_ROOT / ".venv" / "bin" / "python3"

try:
    import aiohttp
    import paho.mqtt.client
    import Cryptodome
except ImportError:
    if _VENV_PYTHON.exists() and sys.executable != str(_VENV_PYTHON):
        print(f"[*] Switching to virtual environment at {_VENV_PYTHON} ...")
        os.execv(str(_VENV_PYTHON), [str(_VENV_PYTHON)] + sys.argv)
    else:
        print("[*] Required packages missing. Creating .venv and installing requirements...")
        import subprocess
        if not _VENV_PYTHON.exists():
            subprocess.check_call([sys.executable, "-m", "venv", str(_REPO_ROOT / ".venv")])
        subprocess.check_call([str(_VENV_PYTHON), "-m", "pip", "install", "aiohttp", "paho-mqtt>=2.1.0", "pycryptodomex>=3.20.0"])
        os.execv(str(_VENV_PYTHON), [str(_VENV_PYTHON)] + sys.argv)

import argparse
import asyncio
import getpass
import json
import logging

# Add custom_components/meross_cloud to sys.path so we use the vendored meross_iot
_MEROSS_CLOUD_DIR = _REPO_ROOT / "custom_components" / "meross_cloud"
if str(_MEROSS_CLOUD_DIR) not in sys.path:
    sys.path.insert(0, str(_MEROSS_CLOUD_DIR))

from meross_iot.http_api import MerossHttpClient
from meross_iot.manager import MerossManager
from meross_iot.controller.subdevice import Ms200Sensor, Gs559aSensor
from meross_iot.model.enums import OnlineStatus

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
_LOGGER = logging.getLogger("meross_diagnostic")


async def async_main():
    parser = argparse.ArgumentParser(description="Meross Live Hardware Validation Tool")
    parser.add_argument("--email", default=os.environ.get("MEROSS_EMAIL"), help="Meross Account Email")
    parser.add_argument("--password", default=os.environ.get("MEROSS_PASSWORD"), help="Meross Account Password")
    parser.add_argument("--api-url", default="https://iot.meross.com", help="Meross API base URL (default: https://iot.meross.com)")
    parser.add_argument("--listen", type=int, default=10, help="Seconds to listen for real-time push events (default: 10)")
    parser.add_argument("--dump", action="store_true", help="Dump discovery payload to JSON")
    args = parser.parse_args()

    email = args.email
    password = args.password

    if not email:
        email = input("Meross Email: ").strip()
    if not password:
        password = getpass.getpass("Meross Password: ").strip()

    print("\n" + "=" * 60)
    print(" 🚀 MEROSS DIAGNOSTIC & DEVICE VALIDATION TOOL")
    print("=" * 60)
    print(f"[*] Logging in as: {email}")

    from meross_iot.model.http.exception import MissingMFA

    try:
        http_client = await MerossHttpClient.async_from_user_password(
            api_base_url=args.api_url,
            email=email,
            password=password,
        )
    except MissingMFA:
        print("[!] 2-Factor Authentication (MFA) enabled on this account.")
        mfa_code = input("Enter 6-digit MFA code: ").strip()
        http_client = await MerossHttpClient.async_from_user_password(
            api_base_url=args.api_url,
            email=email,
            password=password,
            mfa_code=mfa_code,
        )

    print("[✓] Login successful!")
    print(f"    User ID:     {http_client.cloud_credentials.user_id}")
    print(f"    Region Host: {http_client.cloud_credentials.domain}")
    print(f"    MQTT Host:   {http_client.cloud_credentials.mqtt_domain}")

    print("\n[*] Initializing MerossManager and connecting to MQTT...")
    manager = MerossManager(http_client=http_client, auto_reconnect=True)

    event_count = 0

    async def push_handler(push_notification, target_devices, mgr):
        nonlocal event_count
        event_count += 1
        print(f"\n[🔔 LIVE PUSH RECEIVED #{event_count}]")
        print(f"    Namespace: {push_notification.namespace}")
        print(f"    Device UUID: {push_notification.originating_device_uuid}")
        print(f"    Raw Payload: {json.dumps(push_notification.raw_data, indent=2)}")

    manager.register_push_notification_handler_coroutine(push_handler)

    print("[*] Discovering devices...")
    devices = await manager.async_device_discovery(update_subdevice_status=True)
    all_devices = manager.find_devices()

    print(f"\n[✓] Discovered {len(all_devices)} total device(s) / subdevice(s):\n")

    gs559a_count = 0
    ms200_count = 0
    dump_data = []

    for d in all_devices:
        online = "ONLINE" if d.online_status == OnlineStatus.ONLINE else "OFFLINE/UNKNOWN"
        dev_info = {
            "name": d.name,
            "uuid": d.uuid,
            "type": d.type,
            "class": d.__class__.__name__,
            "online": online,
        }

        if isinstance(d, Gs559aSensor):
            gs559a_count += 1
            dev_info["details"] = {
                "subdevice_id": d.subdevice_id,
                "status": d.status,
                "status_description": d.status_description,
                "is_smoke_alarm": d.is_smoke_alarm,
                "is_heat_alarm": d.is_heat_alarm,
                "is_error": d.is_error,
                "is_muted": d.is_muted,
                "interconnected": d.is_interconnected,
                "last_sample": str(d.last_sampled_time),
            }
            print(f"  🚨 [GS559A Smoke Detector] '{d.name}'")
            print(f"     Subdevice ID: {d.subdevice_id} | Online: {online}")
            print(f"     Status: {d.status_description} (code={d.status})")
            print(f"     Smoke: {d.is_smoke_alarm} | Heat: {d.is_heat_alarm} | Error: {d.is_error} | Muted: {d.is_muted}")
            print(f"     Last Sample: {d.last_sampled_time}")

        elif isinstance(d, Ms200Sensor):
            ms200_count += 1
            dev_info["details"] = {
                "subdevice_id": d.subdevice_id,
                "is_open": d.is_open,
                "last_sample": str(d.last_sampled_time),
            }
            state_str = "OPEN" if d.is_open else ("CLOSED" if d.is_open is False else "UNKNOWN")
            print(f"  🚪 [MS200 Door Sensor] '{d.name}'")
            print(f"     Subdevice ID: {d.subdevice_id} | Online: {online}")
            print(f"     Door State: {state_str}")
            print(f"     Last Sample: {d.last_sampled_time}")

        else:
            print(f"  📦 [{d.type}] '{d.name}' ({d.__class__.__name__}) - {online}")

        dump_data.append(dev_info)

    print("\n" + "-" * 60)
    print(f"  Summary: {gs559a_count} GS559A Smoke Detector(s), {ms200_count} MS200 Door Sensor(s)")
    print("-" * 60)

    if args.dump:
        dump_path = _REPO_ROOT / "meross_discovery_dump.json"
        with open(dump_path, "w") as f:
            json.dump(dump_data, f, indent=2)
        print(f"[✓] Sanitized device dump written to: {dump_path}")

    if args.listen > 0:
        print(f"\n[*] Listening for live push events for {args.listen} seconds...")
        print("    (You can open/close an MS200 door sensor or press the GS559A test button to see live packets)")
        await asyncio.sleep(args.listen)
        print(f"[*] Finished listening. Received {event_count} live event(s).")

    print("[*] Cleaning up and disconnecting...")
    manager.close()
    print("[✓] Done!\n")


if __name__ == "__main__":
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("\n[!] Canceled by user.")
    except Exception as e:
        print(f"\n[❌ ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
