# SPDX-License-Identifier: GPL-3.0-or-later
"""A card when the charger is plugged in (and, if asked, when it is unplugged). Reads UPower on the system bus."""

import asyncio

from dbus_fast import MessageType

from ..runtime import add_match, call

NAME = "Power"
DESCRIPTION = "A card when the charger is plugged in or unplugged."
VERSION = "1.0"
AUTHOR = "YALW"
API = 1

UPOWER = "org.freedesktop.UPower"
ROOT = "/org/freedesktop/UPower"
DISPLAY = ROOT + "/devices/DisplayDevice"
PROPS = "org.freedesktop.DBus.Properties"
SETTLE = 1.2        # a USB-C charger can flap for a moment: announce where it settles, once

CHARGING, DISCHARGING, FULL = 1, 2, 4

TEXTS = {
    "en": {"plugged": "Plugged in", "unplugged": "On battery", "charging": "Charging", "full": "Fully charged", "idle": "Not charging",
           "to_full": "{t} to full", "left": "{t} left", "on_battery": "Running on battery", "h": "h", "min": "min"},
    "tr": {"plugged": "Şarja takıldı", "unplugged": "Pilde çalışıyor", "charging": "Şarj oluyor", "full": "Tamamen dolu", "idle": "Şarj olmuyor",
           "to_full": "dolmasına {t}", "left": "{t} kaldı", "on_battery": "Pil kullanılıyor", "h": "sa", "min": "dk"},
    "de": {"plugged": "Netzteil angeschlossen", "unplugged": "Im Akkubetrieb", "charging": "Lädt", "full": "Voll geladen", "idle": "Lädt nicht",
           "to_full": "noch {t} bis voll", "left": "noch {t}", "on_battery": "Läuft im Akkubetrieb", "h": "Std.", "min": "Min."},
    "es": {"plugged": "Cargador conectado", "unplugged": "Con batería", "charging": "Cargando", "full": "Carga completa", "idle": "No está cargando",
           "to_full": "{t} para llenarse", "left": "{t} restantes", "on_battery": "Funcionando con batería", "h": "h", "min": "min"},
}


def duration(seconds: int, words: dict) -> str:
    minutes = round(seconds / 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours} {words['h']} {minutes} {words['min']}" if hours else f"{max(minutes, 1)} {words['min']}"


def level_colour(percent: float) -> str:
    return "#ff5d6c" if percent <= 15 else "#ffb347" if percent <= 35 else "#3ddc97"


def describe(on_battery: bool, level: float | None, state: int, seconds: int, language: str) -> dict:
    """The card (``notify`` arguments) for a plug / unplug moment. ``level`` is None when there is no battery."""
    words = TEXTS.get(language, TEXTS["en"])
    ring = {} if level is None else {"progress": level / 100, "accent": level_colour(level)}
    if on_battery:
        icon = "battery-warning" if level is not None and level <= 15 else "battery-low" if level is not None and level < 40 \
            else "battery-medium" if level is not None and level < 80 else "battery-full"
        subtitle = words["left"].format(t=duration(seconds, words)) if seconds > 0 else words["on_battery"]
        return {"title": words["unplugged"], "subtitle": subtitle, "icon": icon, "key": "power", **ring}
    icon = "battery-charging" if state == CHARGING else "plug-zap"
    if level is None:                                   # no battery to draw: the words have to say it
        return {"title": words["plugged"], "icon": icon, "key": "power", "accent": "#3ddc97"}
    return {"title": "", "icon": icon, "key": "power", **ring}      # just the icon and the level filling up


async def _battery(bus) -> tuple[float | None, int, int]:
    """(percentage or None without a battery, state, seconds to full / to empty)."""
    try:
        (props,) = await call(bus, UPOWER, DISPLAY, PROPS, "GetAll", "s", ["org.freedesktop.UPower.Device"])
    except RuntimeError:
        return None, 0, 0
    present = props["IsPresent"].value if "IsPresent" in props else True
    state = int(props["State"].value) if "State" in props else 0
    seconds = int(props["TimeToFull" if state == CHARGING else "TimeToEmpty"].value) if ("TimeToFull" in props and "TimeToEmpty" in props) else 0
    return (float(props["Percentage"].value) if present and "Percentage" in props else None), state, seconds


async def _on_battery(bus) -> bool:
    (value,) = await call(bus, UPOWER, ROOT, PROPS, "Get", "ss", [UPOWER, "OnBattery"])
    return bool(value.value)


async def run(yalw) -> None:
    bus = await yalw.system_bus()
    changes: asyncio.Queue = asyncio.Queue()

    def on_message(msg) -> None:
        if msg.message_type == MessageType.SIGNAL and msg.member == "PropertiesChanged" and msg.path == ROOT \
                and msg.body[0] == UPOWER and "OnBattery" in msg.body[1]:
            changes.put_nowait(bool(msg.body[1]["OnBattery"].value))

    await add_match(bus, f"type='signal',sender='{UPOWER}',interface='{PROPS}',member='PropertiesChanged',path='{ROOT}'")
    bus.add_message_handler(on_message)
    last = await _on_battery(bus)                       # where we start from: nothing is announced for it

    while True:
        wanted = await changes.get()
        await asyncio.sleep(SETTLE)
        while not changes.empty():
            wanted = changes.get_nowait()
        if wanted == last:
            continue
        last = wanted
        if not yalw.settings.get("unplugged" if wanted else "plugged"):
            continue
        level, state, seconds = await _battery(bus)
        for _ in range(3):                              # UPower may still say "discharging" a moment after the plug
            if wanted or state != DISCHARGING:
                break
            await asyncio.sleep(0.7)
            level, state, seconds = await _battery(bus)
        yalw.notify(**describe(wanted, level, state, seconds, yalw.language))
