# SPDX-License-Identifier: GPL-3.0-or-later
"""A *notice*: the data of one small card, as an extension, a script (``yalw notify``) or YALW itself asks for it.

Everything that arrives from outside goes through ``make``: text is cut to what fits and stripped of control
characters, icons must be ones YALW ships, colours must be plain ``#rrggbb``. What comes out is safe to hand to
the card (nothing here is ever interpreted as markup or code)."""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ICON_DIR = Path(__file__).parent / "assets" / "lucide"
DEFAULT_ICON = "bell"

TITLE_MAX = 48
SUBTITLE_MAX = 80
VALUE_MAX = 4
KEY_MAX = 48
SECONDS_MIN, SECONDS_MAX = 1.0, 30.0

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ]+")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_KEY = re.compile(r"^[A-Za-z0-9._:-]+$")


@lru_cache(maxsize=1)
def icons() -> frozenset[str]:
    """The icon names a notice may use (the Lucide icons that ship with YALW)."""
    return frozenset(p.stem for p in ICON_DIR.glob("*.svg"))


@dataclass(frozen=True)
class Notice:
    title: str
    subtitle: str = ""
    icon: str = DEFAULT_ICON
    accent: str = ""                    # "#rrggbb"; empty = YALW's default
    progress: float | None = None       # 0..1: draws a ring (battery, volume, download ...)
    value: str = ""                     # short text inside the ring; defaults to the progress in percent
    badge: str = ""                     # a small icon on the ring ("zap" for charging ...)
    seconds: float | None = None        # how long it stays; None = the user's setting
    key: str = ""                       # a notice with the same key updates the one on screen
    live: bool = False                  # stays until it is cleared (or the user dismisses it); every update with its key redraws it

    def payload(self, source: str = "") -> dict:
        """Plain values for the QML card."""
        value = self.value or ("" if self.progress is None else str(round(self.progress * 100)))
        return {"title": self.title, "subtitle": self.subtitle, "icon": self.icon, "accent": self.accent,
                "progress": -1.0 if self.progress is None else self.progress, "value": value, "badge": self.badge,
                "seconds": self.seconds or 0.0, "key": self.key, "live": self.live, "source": source}


def _text(raw, limit: int) -> str:
    text = _CONTROL.sub(" ", str(raw)).strip() if raw is not None else ""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _icon(raw, fallback: str) -> str:
    name = str(raw or "").strip().lower()
    return name if name in icons() else fallback


def make(raw: dict) -> Notice:
    """A ``Notice`` from untrusted input. Raises ``ValueError`` (with a message for the author) if there is neither a
    title nor a progress ring."""
    if not isinstance(raw, dict):
        raise ValueError("a notice is a mapping with at least a title")
    title = _text(raw.get("title"), TITLE_MAX)

    progress = raw.get("progress")
    if progress is not None and not isinstance(progress, bool):
        try:
            progress = min(max(float(progress), 0.0), 1.0)
        except (TypeError, ValueError):
            progress = None
        if progress is not None and progress != progress:        # NaN
            progress = None
    else:
        progress = None

    seconds = raw.get("seconds")
    try:
        seconds = None if seconds in (None, "", 0) or isinstance(seconds, bool) else min(max(float(seconds), SECONDS_MIN), SECONDS_MAX)
    except (TypeError, ValueError):
        seconds = None

    if not title and progress is None:
        raise ValueError("a notice needs a title (or a progress ring to stand on its own)")

    accent = str(raw.get("accent") or "")
    key = _text(raw.get("key"), KEY_MAX)
    key = key if _KEY.match(key) else ""
    live = raw.get("live") is True
    if live and not key:
        raise ValueError("a live card needs a key (letters, digits, . _ : -) so that it can be updated and cleared")
    return Notice(
        title=title,
        subtitle=_text(raw.get("subtitle"), SUBTITLE_MAX),
        icon=_icon(raw.get("icon"), DEFAULT_ICON),
        accent=accent.lower() if _HEX.match(accent) else "",
        progress=progress,
        value=_text(raw.get("value"), VALUE_MAX),
        badge=_icon(raw.get("badge"), ""),
        seconds=seconds,
        key=key,
        live=live,
    )
