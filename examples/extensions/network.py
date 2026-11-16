"""A card when the network connection changes: "Connected to <name>" (Wi-Fi, cable or VPN) or "Disconnected".

Copy this file to ~/.local/share/yalw/extensions/ and enable it in YALW Config -> Extensions.
It shows the usual shape of an extension: watch a D-Bus signal, wait for things to settle, call yalw.notify()."""

import asyncio

from dbus_fast import MessageType
from dbus_fast.aio import MessageBus

NAME = "Network"
DESCRIPTION = "A card when you connect to or lose a network (Wi-Fi, cable, VPN)."
VERSION = "1.0"
AUTHOR = "YALW"
API = 1

NM = "org.freedesktop.NetworkManager"
ROOT = "/org/freedesktop/NetworkManager"
PROPS = "org.freedesktop.DBus.Properties"

ICONS = {"802-11-wireless": "wifi", "802-3-ethernet": "cable", "vpn": "shield-check", "wireguard": "shield-check"}


async def get(bus: MessageBus, path: str, interface: str, name: str):
    from dbus_fast import Message
    reply = await bus.call(Message(destination=NM, path=path, interface=PROPS, member="Get", signature="ss", body=[interface, name]))
    return None if reply.message_type == MessageType.ERROR else reply.body[0].value


async def run(yalw):
    bus = await yalw.system_bus()
    changes: asyncio.Queue = asyncio.Queue()

    def on_message(msg):
        if msg.message_type == MessageType.SIGNAL and msg.member == "PropertiesChanged" and msg.path == ROOT \
                and "PrimaryConnection" in msg.body[1]:
            changes.put_nowait(msg.body[1]["PrimaryConnection"].value)

    from dbus_fast import Message
    await bus.call(Message(destination="org.freedesktop.DBus", path="/org/freedesktop/DBus", interface="org.freedesktop.DBus",
                           member="AddMatch", signature="s",
                           body=[f"type='signal',sender='{NM}',interface='{PROPS}',member='PropertiesChanged',path='{ROOT}'"]))
    bus.add_message_handler(on_message)

    last = await get(bus, ROOT, NM, "PrimaryConnection")
    while True:
        path = await changes.get()
        await asyncio.sleep(1.5)                          # connections flap while they come up: announce where it ends
        while not changes.empty():
            path = changes.get_nowait()
        if path == last:
            continue
        last = path
        if path == "/":
            yalw.notify(yalw.tr({"en": "Disconnected", "tr": "Bağlantı koptu", "de": "Getrennt", "es": "Desconectado"}),
                        icon="wifi-off", accent="#ff5d6c", key="network")
            continue
        name = await get(bus, path, NM + ".Connection.Active", "Id") or "?"
        kind = await get(bus, path, NM + ".Connection.Active", "Type") or ""
        yalw.notify(yalw.tr({"en": "Connected", "tr": "Bağlandı", "de": "Verbunden", "es": "Conectado"}), name,
                    icon=ICONS.get(kind, "globe"), accent="#3ddc97", key="network")
