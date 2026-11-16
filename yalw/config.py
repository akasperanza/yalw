# SPDX-License-Identifier: GPL-3.0-or-later
"""User configuration, stored in ``$XDG_CONFIG_HOME/yalw/config.toml``.

``FIELDS`` is the single source of truth: it drives loading, validation, the
commented file written to disk, and the limits the YALW Config app shows.
"""

import json
import logging
import os
import re
import tempfile
import tomllib
from dataclasses import asdict, dataclass, field, make_dataclass
from pathlib import Path

log = logging.getLogger("yalw.config")

POSITIONS = tuple(f"{v}-{h}" for v in ("top", "bottom") for h in ("left", "center", "right"))
BACKENDS = ("auto", "layer-shell", "xcb", "wayland")
LANGUAGES = ("auto", "en", "tr", "de", "es")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class Spec:
    attr: str
    table: str            # "" = top level
    key: str
    default: object
    kind: str             # str | int | float | bool | choice | color | color_auto | list
    doc: str
    lo: float | None = None
    hi: float | None = None
    choices: tuple = ()


S = Spec
FIELDS: tuple[Spec, ...] = (
    S("language", "", "language", "auto", "choice", "auto | en | tr | de | es — language of the cards and of YALW Config.", choices=LANGUAGES),
    S("position", "", "position", "top-center", "choice", "top-left | top-center | top-right | bottom-left | bottom-center | bottom-right", choices=POSITIONS),
    S("margin", "", "margin", 44, "int", "Distance from the screen edge, in pixels.", 0, 400),
    S("monitor", "", "monitor", "", "str", 'Output name (e.g. "eDP-1"). Empty = primary monitor.'),
    S("backend", "", "backend", "auto", "choice", "auto | layer-shell | xcb | wayland. auto picks layer-shell when the compositor offers it.", choices=BACKENDS),

    S("new_track", "events", "new_track", True, "bool", "A new song starts."),
    S("skip", "events", "skip", True, "bool", "Next / previous song."),
    S("play_pause", "events", "play_pause", True, "bool", "Playback paused or resumed."),
    S("bluetooth", "events", "bluetooth", True, "bool", "A Bluetooth device connects."),
    S("bluetooth_disconnect", "events", "bluetooth_disconnect", True, "bool", "A Bluetooth device disconnects."),
    S("power_plugged", "events", "power_plugged", True, "bool", "The charger is plugged in."),
    S("power_unplugged", "events", "power_unplugged", False, "bool", "The charger is unplugged."),

    S("media_seconds", "timing", "media", 4.5, "float", "Seconds the media card stays up.", 1, 30),
    S("bluetooth_seconds", "timing", "bluetooth", 5.5, "float", "Seconds the Bluetooth card stays up.", 1, 30),
    S("notice_seconds", "timing", "notice", 4.5, "float", "Seconds a card from an extension (or `yalw notify`) stays up, unless it asks for another time.", 1, 30),

    S("ignore_players", "media", "ignore", (), "list", 'Players to ignore, matched against the MPRIS name (e.g. ["firefox"]).'),

    S("scale", "appearance", "scale", 1.0, "float", "Card size multiplier.", 0.7, 1.6),
    S("compact", "appearance", "compact", False, "bool", "Compact cards: wider and shorter."),
    S("media_radius", "appearance", "media_radius", 30, "int", "Corner radius of the media card.", 0, 44),
    S("bluetooth_radius", "appearance", "bluetooth_radius", 44, "int", "Corner radius of the small cards: Bluetooth, power and extensions (44 = pill).", 0, 44),
    S("accent", "appearance", "accent", "auto", "color_auto", 'Media accent colour: "auto" takes it from the cover, or a fixed "#rrggbb".'),
    S("bluetooth_accent", "appearance", "bluetooth_accent", "#4d8dff", "color", "Colour of the Bluetooth card."),
    S("dim", "appearance", "dim", 1.0, "float", "How strongly the cover is darkened behind the text (0 = not at all).", 0, 1.5),
    S("shadow", "appearance", "shadow", True, "bool", "Soft drop shadow."),
    S("equalizer", "appearance", "equalizer", True, "bool", "Animated bars on the media card."),
    S("show_progress", "appearance", "progress", True, "bool", "Progress bar and time labels."),
    S("hover_controls", "appearance", "hover_controls", True, "bool", "Previous / play / next buttons when hovering the card."),
    S("reduced_motion", "appearance", "reduced_motion", False, "bool", "Gentle fades instead of bouncy slides."),
    S("font", "appearance", "font", "", "str", "Font family. Empty = pick a good one automatically."),

    S("extensions_enabled", "extensions", "enabled", (), "list", 'Extensions that may run, by id (e.g. ["vpn"]). YALW never enables one by itself: extensions are programs with your permissions.'),

    S("lyrics_enabled", "lyrics", "enabled", False, "bool", "Show synced lyrics. Off by default: when on, the artist and title of the playing song are looked up online."),
    S("lyrics_when", "lyrics", "when", "chorus", "choice", "chorus = the card drops in whenever the chorus comes (when the lyrics mark it; otherwise it stays for the whole song); always = the whole song.", choices=("chorus", "always")),
    S("lyrics_guess", "lyrics", "guess_chorus", False, "bool", "Experimental. By default a card only drops in for a chorus that the lyrics source itself marks; songs without such a label show the whole song. On: look for the chorus in repeated lines when there is no label (if nothing repeats it is still the whole song)."),
    S("lyrics_words", "lyrics", "words", True, "bool", "Highlight word by word when the source has word timing (otherwise line by line)."),
    S("lyrics_learn", "lyrics", "learn_audio", True, "bool", "Experimental, part of guessing the chorus: learn each song's loudness once (only a number per second is kept, never audio) to tell the chorus from other repeated parts. Only runs while guessing is on."),
    S("lyrics_local", "lyrics", "local", True, "bool", "Source: .lrc files next to the song or in ~/.cache/yalw/local."),
    S("lyrics_apple", "lyrics", "apple", True, "bool", "Source: Apple Music lyrics through the lrc.red proxy (word timing)."),
    S("lyrics_lrclib", "lyrics", "lrclib", True, "bool", "Source: lrclib.net."),
    S("lyrics_boidu", "lyrics", "boidu", True, "bool", "Source: lyrics-api.boidu.dev."),

    S("show_battery", "bluetooth", "battery", True, "bool", "Show the battery ring when the device reports a level."),
    S("battery_low", "bluetooth", "low", 15, "int", "At or below this percentage the ring turns red.", 1, 50),
    S("battery_warn", "bluetooth", "warn", 35, "int", "At or below this percentage the ring turns amber.", 2, 80),
)
BY_ATTR = {f.attr: f for f in FIELDS}
DEFAULTS = {f.attr: f.default for f in FIELDS}

Config = make_dataclass(
    "Config",
    [(f.attr, type(f.default), field(default=f.default)) for f in FIELDS],
    frozen=True,
    namespace={
        "align_v": property(lambda self: self.position.split("-")[0]),
        "align_h": property(lambda self: self.position.split("-")[1]),
    },
)


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "yalw"


def cache_dir() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "yalw"


def state_dir() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "yalw"


def data_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "yalw"


def extensions_dir() -> Path:
    return data_dir() / "extensions"


def extension_settings_dir() -> Path:
    return config_path().parent / "extensions"


def log_path() -> Path:
    return state_dir() / "yalw.log"


def config_path() -> Path:
    return config_dir() / "config.toml"


# -- validation --------------------------------------------------------------

def coerce(spec: Spec, raw):
    """``raw`` converted and clamped to what ``spec`` allows; the default if it is unusable."""
    try:
        if spec.kind == "bool":
            if not isinstance(raw, bool):
                raise ValueError
            return raw
        if spec.kind in ("int", "float"):
            if isinstance(raw, bool):
                raise ValueError
            value = min(max(float(raw), spec.lo), spec.hi)
            return int(round(value)) if spec.kind == "int" else round(value, 3)
        if spec.kind == "choice":
            if raw not in spec.choices:
                raise ValueError
            return raw
        if spec.kind in ("color", "color_auto"):
            if spec.kind == "color_auto" and raw == "auto":
                return raw
            if not isinstance(raw, str) or not HEX.match(raw):
                raise ValueError
            return raw.lower()
        if spec.kind == "list":
            if not isinstance(raw, (list, tuple)):
                raise ValueError
            return tuple(str(i).strip().lower() for i in raw if str(i).strip())
        return str(raw)
    except (TypeError, ValueError):
        log.warning("invalid value %r for %s, using the default", raw, spec.key)
        return spec.default


def from_values(values: dict):
    return Config(**{f.attr: coerce(f, values.get(f.attr, f.default)) for f in FIELDS})


def to_values(cfg) -> dict:
    return {k: list(v) if isinstance(v, tuple) else v for k, v in asdict(cfg).items()}


# -- file --------------------------------------------------------------------

def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(json.dumps(str(v), ensure_ascii=False) for v in value) + "]"
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, int):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def render(values: dict) -> str:
    """The commented config file for ``values``."""
    lines = ["# YALW configuration. Every key is optional; edit here or with `yalw config`.", ""]
    ordered = [f for f in FIELDS if f.table == ""]
    for table in dict.fromkeys(f.table for f in FIELDS if f.table):
        ordered += [f for f in FIELDS if f.table == table]

    current = ""
    for spec in ordered:
        if spec.table != current:
            current = spec.table
            lines += ["", f"[{current}]"]
        lines.append(f"# {spec.doc}")
        lines.append(f"{spec.key} = {_toml_value(values.get(spec.attr, spec.default))}")
    return "\n".join(lines) + "\n"


def save(values: dict, path: Path | None = None) -> Path:
    """Validate and atomically write ``values``."""
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = to_values(from_values(values))
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".tmp")
    with os.fdopen(fd, "w") as handle:
        handle.write(render(clean))
    os.replace(tmp, path)
    return path


def load(path: Path | None = None):
    path = path or config_path()
    if not path.exists():
        try:
            save(DEFAULTS, path)
        except OSError as exc:
            log.warning("could not write default config: %s", exc)
        return Config()

    try:
        raw = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        log.warning("ignoring unreadable config %s: %s", path, exc)
        return Config()

    values = {}
    for spec in FIELDS:
        section = raw if spec.table == "" else raw.get(spec.table, {})
        if isinstance(section, dict) and spec.key in section:
            values[spec.attr] = section[spec.key]
    return from_values(values)
