#!/usr/bin/env python3
"""
Live Push Event Listener for Meross Cloud & Subdevices
"""
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MEROSS_CLOUD_DIR = _REPO_ROOT / "custom_components" / "meross_cloud"
if str(_MEROSS_CLOUD_DIR) not in sys.path:
    sys.path.insert(0, str(_MEROSS_CLOUD_DIR))

from meross_iot.http_api import MerossHttpClient
from meross_iot.manager import MerossManager
from meross_iot.model.enums import Namespace
from meross_iot.controller.subdevice import Ms200Sensor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logging.getLogger("meross_iot").setLevel(logging.INFO)

EMAIL = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("MEROSS_EMAIL", "")
PASSWORD = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("MEROSS_PASSWORD", "")
LISTEN_SECONDS = int(sys.argv[3]) if len(sys.argv) > 3 else 180

if not EMAIL or not PASSWORD:
    print("Usage: python listen_live_pushes.py <email> <password> [seconds]")
    sys.exit(1)

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

async def main():
    print("=" * 70)
    print("STARTING LIVE MEROSS PUSH EVENT MONITOR")
    print(f"Account: {EMAIL}")
    print(f"Listen duration: {LISTEN_SECONDS} seconds")
    print("=" * 70)

    http_client = await MerossHttpClient.async_from_user_password(
        api_base_url="https://iot.meross.com",
        email=EMAIL,
        password=PASSWORD
    )
    manager = MerossManager(http_client=http_client)
    
    # Intercept raw MQTT on_message
    received_events = []

    def raw_message_listener(client, userdata, msg):
        try:
            raw_payload = msg.payload.decode("utf-8")
            data = json.loads(raw_payload)
            header = data.get("header", {})
            payload = data.get("payload", {})
            method = header.get("method")
            namespace = header.get("namespace")
            from_device = header.get("from")
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
            
            summary = f"[{ts}] TOPIC: {msg.topic} | METHOD: {method} | NS: {namespace} | FROM: {from_device}"
            print("\n" + "#" * 70)
            print(summary)
            print("PAYLOAD:", json.dumps(payload, indent=2))
            print("#" * 70 + "\n")
            
            received_events.append({
                "time": ts,
                "topic": msg.topic,
                "method": method,
                "namespace": namespace,
                "header": header,
                "payload": payload
            })
        except Exception as e:
            print(f"[!] Error decoding raw message on {msg.topic}: {e}")

    orig_manager_on_message = manager._on_message
    def hooked_on_message(client, userdata, msg):
        raw_message_listener(client, userdata, msg)
        orig_manager_on_message(client, userdata, msg)
    manager._on_message = hooked_on_message

    await manager.async_init()
    await manager.async_device_discovery()

    # Find door sensors and hubs
    door_sensors = []
    hubs = []
    for dev in manager.find_devices():
        if isinstance(dev, Ms200Sensor) or "ms200" in getattr(dev, "type", "").lower():
            door_sensors.append(dev)
            print(f"[+] Found Door Sensor: '{dev.name}' (ID: {getattr(dev, 'subdevice_id', dev.uuid)}) - Initial is_open: {getattr(dev, 'is_open', None)}")
            async def make_subdev_cb(d):
                async def subdev_push_cb(namespace, data, device_internal_id):
                    print(f"\n🔔 [CALLBACK] PUSH EVENT TRIGGERED ON SENSOR '{d.name}'!")
                    print(f"   Namespace: {namespace}")
                    print(f"   is_open now: {d.is_open}")
                    print(f"   data: {data}\n")
                return subdev_push_cb
            dev.register_push_notification_handler_coroutine(await make_subdev_cb(dev))
        elif "msh" in getattr(dev, "type", "").lower() or "hub" in getattr(dev, "name", "").lower():
            hubs.append(dev)

    print("\n" + "=" * 70)
    print(f"READY & LISTENING FOR {LISTEN_SECONDS} SECONDS...")
    print("PLEASE OPEN OR CLOSE THE DOOR SENSOR NOW!")
    print("=" * 70 + "\n")

    for i in range(LISTEN_SECONDS):
        await asyncio.sleep(1)
        if (i + 1) % 5 == 0:
            # Poll hub doorWindow to check if hub state changed
            for hub in hubs:
                try:
                    res = await hub._execute_command("GET", Namespace.HUB_SENSOR_DOORWINDOW, {"doorWindow": []}, timeout=3.0)
                    for dw in res.get("doorWindow", []):
                        for ds in door_sensors:
                            if ds.subdevice_id.lower() == str(dw.get("id", "")).lower():
                                dw_st = dw.get("status")
                                is_op = (dw_st != 0 and dw_st is not False)
                                if ds.is_open != is_op:
                                    print(f"\n⚡ [POLL] Hub reports state transition for '{ds.name}'! Status: {dw_st} (is_open: {is_op})")
                                    ds._handle_door_window_data(dw_st, dw.get("lmTime"))
                except Exception as e:
                    pass

        if (i + 1) % 15 == 0:
            print(f"[*] Still listening... {i + 1}/{LISTEN_SECONDS}s elapsed. (Total packets captured: {len(received_events)})")
            for ds in door_sensors:
                print(f"    - Door Sensor '{ds.name}': is_open={getattr(ds, 'is_open', None)}")

    print("\n" + "=" * 70)
    print(f"MONITOR COMPLETE. Total packets captured: {len(received_events)}")
    print("=" * 70)
    for ds in door_sensors:
        print(f"[+] Door Sensor '{ds.name}': final is_open={getattr(ds, 'is_open', None)}")

    manager.close()

if __name__ == "__main__":
    asyncio.run(main())
