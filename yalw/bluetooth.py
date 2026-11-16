# SPDX-License-Identifier: GPL-3.0-or-later
"""BlueZ watcher: a card whenever a Bluetooth device connects."""

import asyncio
import logging
import time
from collections.abc import Callable

from dbus_fast import MessageType
from dbus_fast.aio import MessageBus

from .runtime import Runtime, add_match, call

log = logging.getLogger("yalw.bluetooth")

BLUEZ = "org.bluez"
DEVICE = "org.bluez.Device1"
BATTERY = "org.bluez.Battery1"
PROPS = "org.freedesktop.DBus.Properties"
BATTERY_GRACE = 1.0      # BlueZ publishes the battery a moment after the connection

_EARBUD_HINTS = ("buds", "airpod", "pods", "earbud", "earfun", "freebuds", "wf-", "wf_")
_SPEAKER_HINTS = ("speaker", "boom", "soundbar", "flip", "charge", "megaboom", "soundlink", "stanmore")


def device_icon(icon: str, name: str) -> str:
    """Lucide icon name for a BlueZ device."""
    n = name.lower()
    if any(h in n for h in _EARBUD_HINTS):
        return "earbuds"
    if "watch" in n or "band" in n:
        return "watch"
    if icon == "audio-card":
        if "car" in n:
            return "car"
        return "speaker"
    if icon in ("audio-headset", "audio-headphones"):
        return "headset" if "headset" in n else "headphones"
    if icon == "audio-speakers" or any(h in n for h in _SPEAKER_HINTS):
        return "speaker"
    return {
        "input-keyboard": "keyboard",
        "input-mouse": "mouse",
        "input-gaming": "gamepad-2",
        "input-tablet": "tablet",
        "phone": "smartphone",
        "computer": "laptop",
        "camera-photo": "camera",
        "camera-video": "camera",
        "printer": "printer",
        "video-display": "tv",
        "microphone": "mic",
    }.get(icon, "bluetooth")


class BluetoothWatcher:
    def __init__(self, runtime: Runtime, emit: Callable[[dict], None]):
        self.rt = runtime
        self.emit = emit
        self.bus: MessageBus = runtime.system_bus
        self.devices: dict[str, dict] = {}
        self._announced: dict[str, float] = {}

    async def start(self) -> None:
        await add_match(self.bus, f"type='signal',sender='{BLUEZ}',interface='{PROPS}',"
                                  f"member='PropertiesChanged',path_namespace='/org/bluez'")
        await add_match(self.bus, "type='signal',sender='org.freedesktop.DBus',interface='org.freedesktop.DBus',"
                                  f"member='NameOwnerChanged',arg0='{BLUEZ}'")
        await add_match(self.bus, f"type='signal',sender='{BLUEZ}',interface='org.freedesktop.DBus.ObjectManager',"
                                  f"member='InterfacesAdded'")
        await add_match(self.bus, f"type='signal',sender='{BLUEZ}',interface='org.freedesktop.DBus.ObjectManager',"
                                  f"member='InterfacesRemoved'")
        self.bus.add_message_handler(self._on_message)
        await self._scan()

    async def _scan(self) -> None:
        try:
            (objects,) = await call(self.bus, BLUEZ, "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects")
        except RuntimeError as exc:
            log.info("BlueZ not available yet (%s)", exc)
            return
        for path, interfaces in objects.items():
            self._absorb(path, interfaces)

    # -- bus traffic --------------------------------------------------------

    @staticmethod
    def _plain(props: dict) -> dict:
        return {k: v.value for k, v in props.items()}

    def _absorb(self, path: str, interfaces: dict, announce: bool = False) -> None:
        if DEVICE in interfaces:
            dev = self.devices.setdefault(path, {})
            was = dev.get("Connected", False)
            dev.update(self._plain(interfaces[DEVICE]))
            if announce and dev.get("Connected") and not was:
                self._connected(path)
        if BATTERY in interfaces:
            self.devices.setdefault(path, {}).update(self._plain(interfaces[BATTERY]))

    def _on_message(self, msg) -> None:
        if msg.message_type != MessageType.SIGNAL:
            return
        if msg.member == "NameOwnerChanged":
            if msg.body[0] == BLUEZ and msg.body[2]:        # bluetoothd (re)started: forget and re-read, quietly
                self.devices.clear()
                self.rt.spawn(self._scan())
        elif msg.member == "InterfacesAdded":
            path, interfaces = msg.body
            if path.startswith("/org/bluez"):
                self._absorb(path, interfaces, announce=True)
                if BATTERY in interfaces:
                    self._battery_changed(path)
        elif msg.member == "InterfacesRemoved":
            path, removed = msg.body
            if DEVICE in removed:
                self.devices.pop(path, None)
            elif BATTERY in removed and path in self.devices:
                self.devices[path].pop("Percentage", None)
        elif msg.member == "PropertiesChanged" and msg.path and msg.path.startswith("/org/bluez/"):
            iface, changed, _invalidated = msg.body
            dev = self.devices.setdefault(msg.path, {})
            plain = self._plain(changed)
            if iface == DEVICE:
                was = dev.get("Connected", False)
                dev.update(plain)
                if "Connected" in plain and plain["Connected"] != was:
                    if plain["Connected"]:
                        self._connected(msg.path)
                    else:
                        self._disconnected(msg.path)
            elif iface == BATTERY:
                dev.update(plain)
                if "Percentage" in plain:
                    self._battery_changed(msg.path)

    # -- events -------------------------------------------------------------

    def _disconnected(self, path: str) -> None:
        dev = self.devices.get(path, {})
        name = dev.get("Alias") or dev.get("Name") or dev.get("Address", "") or "Bluetooth"
        self._announced.pop(path, None)
        self.emit({"type": "disconnected", "address": dev.get("Address", ""), "name": name,
                   "icon": device_icon(dev.get("Icon", ""), name)})

    def _connected(self, path: str) -> None:
        now = time.time()
        if now - self._announced.get(path, 0) < 3:       # BlueZ can report the same connection twice
            return
        self._announced[path] = now
        self.rt.spawn(self._announce(path))

    async def _announce(self, path: str) -> None:
        await asyncio.sleep(BATTERY_GRACE)
        dev = self.devices.get(path, {})
        if not dev.get("Connected"):
            return
        percentage = dev.get("Percentage")
        address = dev.get("Address", "")
        self.emit({
            "type": "connected",
            "address": address,
            "name": dev.get("Alias") or dev.get("Name") or address or "Bluetooth",
            "icon": device_icon(dev.get("Icon", ""), dev.get("Alias") or dev.get("Name") or ""),
            "battery": int(percentage) if percentage is not None else -1,
            "charging": await self._charging(address),
        })

    def _battery_changed(self, path: str) -> None:
        dev = self.devices.get(path, {})
        if not dev.get("Connected") or dev.get("Percentage") is None:
            return
        self.rt.spawn(self._push_battery(path))

    async def _push_battery(self, path: str) -> None:
        dev = self.devices.get(path, {})
        address = dev.get("Address", "")
        self.emit({
            "type": "battery",
            "address": address,
            "battery": int(dev["Percentage"]),
            "charging": await self._charging(address),
        })

    async def _charging(self, address: str) -> bool:
        """BlueZ has no charging flag; UPower knows it for some devices."""
        if not address:
            return False
        try:
            (paths,) = await call(self.bus, "org.freedesktop.UPower", "/org/freedesktop/UPower",
                                  "org.freedesktop.UPower", "EnumerateDevices")
            for path in paths:
                (props,) = await call(self.bus, "org.freedesktop.UPower", path, PROPS, "GetAll", "s",
                                      ["org.freedesktop.UPower.Device"])
                serial = props["Serial"].value if "Serial" in props else ""
                if serial.lower() == address.lower():
                    return props["State"].value in (1, 5)       # charging / pending charge
        except (RuntimeError, KeyError):
            pass
        return False
