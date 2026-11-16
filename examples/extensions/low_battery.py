"""A card when the battery drops below a level while unplugged (default 20 %, once per discharge).

Settings (optional): ~/.config/yalw/extensions/low_battery.toml
    threshold = 15"""

import asyncio

from dbus_fast import Message, MessageType

NAME = "Low battery"
DESCRIPTION = "A warning card when the battery is low and the charger is not connected."
VERSION = "1.0"
AUTHOR = "YALW"
API = 1

UPOWER = "org.freedesktop.UPower"
DISPLAY = "/org/freedesktop/UPower/devices/DisplayDevice"
DISCHARGING = 2


async def battery(bus):
    reply = await bus.call(Message(destination=UPOWER, path=DISPLAY, interface="org.freedesktop.DBus.Properties",
                                   member="GetAll", signature="s", body=["org.freedesktop.UPower.Device"]))
    if reply.message_type == MessageType.ERROR:
        return None, 0
    props = reply.body[0]
    return float(props["Percentage"].value), int(props["State"].value)


async def run(yalw):
    threshold = float(yalw.settings.get("threshold", 20))
    bus = await yalw.system_bus()
    warned = False
    while True:
        level, state = await battery(bus)
        if level is not None:
            if state == DISCHARGING and level <= threshold and not warned:
                warned = True
                yalw.notify(yalw.tr({"en": "Battery low", "tr": "Pil azaldı", "de": "Akku schwach", "es": "Batería baja"}),
                            icon="battery-warning", progress=level / 100, accent="#ff5d6c", key="low-battery", seconds=8)
            elif state != DISCHARGING or level > threshold + 5:
                warned = False                            # plugged in, or recovered: warn again next time
        await asyncio.sleep(60)
