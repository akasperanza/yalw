# SPDX-License-Identifier: GPL-3.0-or-later
"""YALW Config: a small settings window for the daemon."""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFontDatabase, QGuiApplication, QIcon

from . import config, control, demo, extensions, i18n, lastsong, listener, lyrics, notice
from .config import log_path
from .builtin import power
from .surface import style_map

log = logging.getLogger("yalw.config-app")

QML = Path(__file__).parent / "qml" / "CfgMain.qml"
ICON = Path(__file__).parent / "assets" / "yalw.svg"
PREVIEW_KINDS = {"media": "new", "bluetooth": "bluetooth", "lyrics": "lyrics-words"}


LOG_TAIL = 160
SAVE_DELAY_MS = 600                  # settings are saved this long after the last change
WHERE_KEYS = {"position", "margin", "monitor", "backend", "scale"}      # changes you only judge on the real screen
DEFAULT_ACCENT = "#e0a458"
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def palette(accent: str) -> dict:
    """YALW Config's colours: warm neutrals, and one accent (the colour of the song that is playing)."""
    light = QColor(accent).lightnessF() > 0.55
    return {
        "bg": "#131211", "panel": "#1b1918", "raised": "#262322", "hover": "#312d2b", "line": "#2a2726",
        "text": "#ece7e1", "muted": "#a49d95", "dim": "#756f69",
        "accent": accent, "onAccent": "#1a1612" if light else "#ffffff",
        "ok": "#7ccf9f", "warn": "#e8a24a", "bad": "#ef6b5f",
    }


class ConfigModel(QObject):
    valuesChanged = Signal()
    stringsChanged = Signal()
    statusChanged = Signal()
    daemonChanged = Signal()
    logChanged = Signal()
    palChanged = Signal()
    previewChanged = Signal()
    extensionsChanged = Signal()
    daemonIn = Signal(object)          # from the status-polling thread

    def __init__(self, autosave: bool = True) -> None:
        super().__init__()
        self._autosave = autosave                  # False for snapshots: they must never touch the real settings
        self._saved = config.to_values(config.load())
        self._values = dict(self._saved)
        self._note = ""
        self._strings = i18n.strings(self._values["language"])
        families = sorted(set(QFontDatabase.families()), key=str.casefold)
        self._fonts = [{"value": "", "text": ""}] + [{"value": f, "text": f} for f in families]
        self._monitors = [s.name() for s in QGuiApplication.screens()]
        self._daemon: dict = {"checked": False, "running": False, "info": {}}
        self._log = ""
        self._polling = False
        self._touched: set[str] = set()
        self._demo_cache: dict = {}
        self._last = lastsong.load()
        self._lyrics_memo: tuple = (None, None)
        self._installed = extensions.discover()
        self._accent = self._last_accent()
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.apply)
        self.daemonIn.connect(self._set_daemon)

    # -- read-only facts ------------------------------------------------------

    @Property("QVariantMap", constant=True)
    def specs(self) -> dict:
        return {f.attr: {"lo": f.lo, "hi": f.hi, "kind": f.kind} for f in config.FIELDS}

    @Property("QVariantMap", constant=True)
    def defaults(self) -> dict:
        return config.to_values(config.Config())

    @Property("QVariantList", constant=True)
    def monitors(self) -> list:
        return self._monitors

    @Property("QVariantList", constant=True)
    def fonts(self) -> list:
        return self._fonts

    @Property(str, constant=True)
    def fontFamily(self) -> str:                 # Label.qml reads host.fontFamily
        from .controller import pick_font
        return pick_font()

    # -- what the card views read from `host`, so the preview can show the real thing -------------------

    @Property("QVariantMap", notify=valuesChanged)
    def style(self) -> dict:
        return style_map(config.from_values(self._values))

    @Property("QVariantMap", notify=stringsChanged)
    def labels(self) -> dict:
        return self._strings

    @Property(str, notify=stringsChanged)
    def songLine(self) -> str:
        return self._strings["song_line"]

    @Property(str, notify=stringsChanged)
    def connectedLabel(self) -> str:
        return self._strings["connected"]

    @Property(str, notify=stringsChanged)
    def disconnectedLabel(self) -> str:
        return self._strings["disconnected"]

    @Property(str, notify=stringsChanged)
    def chargingLabel(self) -> str:
        return self._strings["charging"]

    @Slot()
    def previous(self) -> None: ...             # the preview's buttons are for show

    @Slot()
    def next(self) -> None: ...

    @Slot()
    def playPause(self) -> None: ...

    @Slot(float)
    def seek(self, fraction: float) -> None: ...

    def _sample(self) -> dict:
        if not self._demo_cache:
            sample = demo.Demo()
            self._demo_cache = {"media": sample.payload("new")}
        return self._demo_cache

    @Slot(float, result="QVariantMap")
    def freshMedia(self, position: float) -> dict:
        """The song that played last (the invented sample if there is none), playing from ``position`` as of now."""
        song = {**self._sample()["media"]}
        last = self._last
        if last:
            song.update(title=last["title"], artist=last["artist"], album=last["album"])
            if last["cover"]:
                song["art"] = last["cover"]
            if _HEX.match(last["accent"]):
                song["accent"] = last["accent"]
            if last["length"] > 30:
                song["length"] = last["length"]
        position = min(position, song["length"] * 0.4)
        return {**song, "playing": True, "position": position, "stamp": time.time() * 1000}

    def _refresh_last(self) -> None:
        last = lastsong.load()
        if last != self._last:
            self._last = last
            self.previewChanged.emit()

    def _last_lyrics(self) -> dict | None:
        """The lyrics YALW already found for the song that played last (from its cache), if there are any."""
        last = self._last
        if not last:
            return None
        sources = tuple(n for n in lyrics.NETWORK_SOURCES if self._values[f"lyrics_{n}"])
        key = (last["artist"], last["title"], last["album"], last["length"], sources)
        if self._lyrics_memo[0] != key:
            meta = {"title": last["title"], "artist": last["artist"], "album": last["album"], "length": last["length"]}
            self._lyrics_memo = (key, lyrics.cached(meta, sources))
        return self._lyrics_memo[1]

    @staticmethod
    def _spread_words(line: dict) -> dict:
        """The line with its words timed evenly across it, so the preview lights up word by word whatever the source gave."""
        if line.get("words"):
            return line
        tokens = line["text"].split()
        step = max((line["e"] - line["t"] - 0.4) / max(len(tokens), 1), 0.12)
        return {**line, "words": [{"t": line["t"] + i * step, "text": w, "sp": i < len(tokens) - 1} for i, w in enumerate(tokens)]}

    def _preview_lines(self) -> tuple[list[dict], float, float, str]:
        """(lines, where to start, how long to play before starting over, source): the last song's lyrics from its
        chorus on, or a placeholder when there are none."""
        found = self._last_lyrics()
        if found:
            lines = [self._spread_words(l) for l in found["lines"]]
            windows = found.get("chorus") or lyrics.chorus_windows(found["lines"])[0]
            opening = next((l["t"] for l in lines if not windows or l["t"] >= windows[0][0]), lines[0]["t"])
            start = max(0.0, opening - 0.3)                    # just before the first line of the chorus is sung
            return lines, start, 14.0, found.get("source", "")
        text = self._strings["lyrics_placeholder"]
        line = self._spread_words({"t": 1.0, "e": 4.0, "text": text, "words": [], "part": "", "sec": 0})
        return [line], 0.0, 5.5, ""

    @Property("QVariantMap", notify=valuesChanged)
    def previewLyrics(self) -> dict:
        lines, _start, _loop, source = self._preview_lines()
        if not self._values["lyrics_words"]:
            lines = [{**l, "words": []} for l in lines]
        return {"source": source or "preview", "synced": "word" if self._values["lyrics_words"] else "line", "lines": lines}

    @Property(float, notify=valuesChanged)
    def previewLyricsLoop(self) -> float:
        return self._preview_lines()[2]

    @Slot(result="QVariantMap")
    def freshLyricsMedia(self) -> dict:
        """The last song, playing from where the lyrics preview starts."""
        start = self._preview_lines()[1]
        song = self.freshMedia(0)
        return {**song, "position": min(start, max(song["length"] - 1, 0.0))}

    @Property("QVariantList", constant=True)
    def previewDevices(self) -> list:
        return [{**demo.BLUETOOTH[k], "connected": True} for k in ("bluetooth", "bluetooth-low", "bluetooth-charging", "bluetooth-speaker")]

    @Property("QVariantList", notify=stringsChanged)
    def previewNotices(self) -> list:
        """Sample cards for the preview: a charger, a plain notice and one with a ring that is not a battery."""
        language = i18n.resolve(self._values["language"])
        cards = [power.describe(False, 64, power.CHARGING, 2820, language), power.describe(True, 64, power.DISCHARGING, 11400, language),
                 {"title": "Build finished", "subtitle": "yalw · 12 s", "icon": "circle-check", "accent": "#3ddc97"},
                 {"title": "ubuntu.iso", "subtitle": "Downloading", "icon": "download", "progress": 0.42, "accent": "#4d8dff"}]
        return [notice.make(c).payload("preview") for c in cards]

    @Property("QVariantMap", notify=palChanged)
    def pal(self) -> dict:
        return palette(self._accent)

    # -- state ------------------------------------------------------------------

    @Property("QVariantMap", notify=valuesChanged)
    def values(self) -> dict:
        return self._values

    @Property("QVariantMap", notify=stringsChanged)
    def strings(self) -> dict:
        return self._strings

    @Property("QVariantList", notify=stringsChanged)
    def languages(self) -> list:
        return [{"value": "auto", "text": self._strings["language_auto"]}] + [
            {"value": code, "text": name} for code, name in i18n.LANGUAGE_NAMES.items()]

    @Property(bool, notify=valuesChanged)
    def dirty(self) -> bool:
        return self._values != self._saved

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._note

    def _say(self, key: str) -> None:
        self._note = self._strings.get(key, key) if key else ""
        self.statusChanged.emit()

    def _changed(self) -> None:
        self.valuesChanged.emit()
        self.extensionsChanged.emit()
        self._say("")

    # -- editing ----------------------------------------------------------------

    @Slot(str, "QVariant")
    def set(self, key: str, value) -> None:
        spec = config.BY_ATTR.get(key)
        if spec is None:
            return
        if spec.kind == "list" and isinstance(value, str):
            value = [part for part in value.split(",")]
        clean = config.coerce(spec, value)
        clean = list(clean) if isinstance(clean, tuple) else clean
        if self._values.get(key) == clean:
            return
        self._values = {**self._values, key: clean}
        # The two battery thresholds must stay ordered.
        if key == "battery_low" and self._values["battery_warn"] <= clean:
            self._values["battery_warn"] = min(clean + 1, int(config.BY_ATTR["battery_warn"].hi))
        if key == "battery_warn" and self._values["battery_low"] >= clean:
            self._values["battery_low"] = max(clean - 1, int(config.BY_ATTR["battery_low"].lo))
        if key == "language":
            self._strings = i18n.strings(clean)
            self.stringsChanged.emit()
        self._touched.add(key)
        self._changed()
        if self._autosave:
            self._save_timer.start()

    @Slot()
    def reset(self) -> None:
        self._values = {**config.to_values(config.Config()), "language": self._values["language"]}
        self._touched |= WHERE_KEYS
        self._changed()
        if self._autosave:
            self._save_timer.start()

    # -- is it running? what does it say? ---------------------------------------------

    @Property("QVariantMap", notify=daemonChanged)
    def daemon(self) -> dict:
        return self._daemon

    @Property(str, notify=logChanged)
    def log(self) -> str:
        return self._log

    def start_polling(self, interval_ms: int = 3000) -> None:
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self.refreshStatus)
        self._poll_timer.start(interval_ms)
        self.refreshStatus()

    @Slot()
    def refreshStatus(self) -> None:
        """Ask the daemon how it is, off the GUI thread (it may be slow or gone)."""
        if self._polling:
            return
        self._polling = True

        def work() -> None:
            state, body = control.query("Status")
            info: dict = {}
            if state == "ok" and body:
                try:
                    info = json.loads(body[0])
                except ValueError:
                    pass
            self.daemonIn.emit({"checked": True, "running": state != control.NOT_RUNNING, "outdated": state == control.OUTDATED, "info": info})

        threading.Thread(target=work, daemon=True).start()

    @Slot(object)
    def _set_daemon(self, state: dict) -> None:
        self._polling = False
        if state != self._daemon:
            self._daemon = state
            self.daemonChanged.emit()
            self.extensionsChanged.emit()
        self._refresh_last()
        song = (state.get("info") or {}).get("song") or {}
        accent = song.get("accent") if song.get("title") and _HEX.match(song.get("accent") or "") else self._last_accent()
        if accent != self._accent:
            self._accent = accent
            self.palChanged.emit()

    def _last_accent(self) -> str:
        last = self._last
        return last["accent"] if last and _HEX.match(last["accent"]) else DEFAULT_ACCENT

    # -- extensions ---------------------------------------------------------------------------

    @Property(str, constant=True)
    def extensionsPath(self) -> str:
        return str(config.extensions_dir())

    @Property("QVariantList", notify=extensionsChanged)
    def extensionList(self) -> list:
        """What is installed, whether the user has enabled it, and (from the daemon) how it is doing."""
        enabled = set(self._values["extensions_enabled"])
        running = {e["id"]: e for e in (self._daemon.get("info") or {}).get("extensions", [])}
        out = []
        for info in self._installed:
            live = running.get(info.id, {})
            out.append({"id": info.id, "name": info.name, "description": info.description, "version": info.version, "author": info.author,
                        "compatible": info.compatible, "api": info.api, "enabled": info.id in enabled,
                        "state": live.get("state", ""), "error": live.get("error", "")})
        return out

    @Slot(str, bool)
    def setExtension(self, ident: str, on: bool) -> None:
        if ident not in {i.id for i in self._installed}:
            return
        enabled = [e for e in self._values["extensions_enabled"] if e != ident]
        self.set("extensions_enabled", enabled + [ident] if on else enabled)

    @Slot()
    def rescanExtensions(self) -> None:
        self._installed = extensions.discover()
        self.extensionsChanged.emit()

    @Slot()
    def openExtensionsFolder(self) -> None:
        folder = config.extensions_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.error("cannot create %s: %s", folder, exc)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    @Property(int, notify=daemonChanged)
    def learned(self) -> int:
        return listener.count_learned()

    @Slot()
    def forgetLearned(self) -> None:
        listener.forget_all()
        self.daemonChanged.emit()

    @Slot()
    def refreshLog(self) -> None:
        try:
            with open(log_path(), "r", encoding="utf-8", errors="replace") as handle:
                text = "".join(handle.readlines()[-LOG_TAIL:])
        except OSError:
            text = ""
        if text != self._log:
            self._log = text
            self.logChanged.emit()

    @Slot()
    def copyLog(self) -> None:
        QGuiApplication.clipboard().setText(self._log)

    @Slot()
    def startOrRestart(self) -> None:
        """Start the daemon, or restart it when it is already up."""
        running = self._daemon.get("running")
        if shutil.which("systemctl") and subprocess.run(["systemctl", "--user", "cat", "yalw.service"], capture_output=True).returncode == 0:
            subprocess.Popen(["systemctl", "--user", "restart" if running else "start", "yalw.service"])
        elif running:
            control.send("Reload")
        else:
            env = {**os.environ}
            root = Path(__file__).resolve().parents[1]
            if (root / "pyproject.toml").exists():
                env["PYTHONPATH"] = f"{root}{os.pathsep}{env.get('PYTHONPATH', '')}"
            subprocess.Popen([sys.executable, "-m", "yalw", "run"], env=env, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        QTimer.singleShot(2500, self.refreshStatus)

    @Slot(bool)
    def setQuiet(self, on: bool) -> None:
        control.send("Quiet", "on" if on else "off")
        QTimer.singleShot(300, self.refreshStatus)

    # -- talking to the daemon ----------------------------------------------------

    @Slot()
    def apply(self) -> None:
        self._save_timer.stop()
        where, self._touched = self._touched & WHERE_KEYS, set()
        try:
            config.save(self._values)
        except OSError as exc:
            log.error("save failed: %s", exc)
            self._say("st_error")
            return
        self._saved = config.to_values(config.from_values(self._values))
        self._values = dict(self._saved)
        self.valuesChanged.emit()
        result = control.send("Reload")
        if result == control.OUTDATED and shutil.which("systemctl"):   # an older daemon: restart it instead
            ok = subprocess.run(["systemctl", "--user", "restart", "yalw.service"], capture_output=True).returncode == 0
            result = "ok" if ok else result
        if result == "ok":
            self._say("st_applied")
            if where:
                self._preview_when_ready("media", tries=8)       # the daemon restarts; show it where it will sit
        else:
            self._say("st_saved_only")

    def _preview_when_ready(self, kind: str, tries: int) -> None:
        if tries and control.send("Demo", PREVIEW_KINDS[kind]) != "ok":
            QTimer.singleShot(600, lambda: self._preview_when_ready(kind, tries - 1))

    @Slot(str)
    def preview(self, kind: str) -> None:
        if control.send("Demo", PREVIEW_KINDS[kind]) != "ok":
            self._say("st_not_running")


def run(snapshot: Path | None = None) -> int:
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")    # we draw our own look
    os.environ.setdefault("QT_NO_XDG_DESKTOP_PORTAL", "1")
    from PySide6.QtQml import QQmlApplicationEngine

    from .icons import LucideProvider

    app = QGuiApplication(sys.argv)
    app.setApplicationName("yalw-config")
    app.setDesktopFileName("yalw-config")
    app.setWindowIcon(QIcon(str(ICON)))

    model = ConfigModel(autosave=snapshot is None)
    if snapshot is None:
        model.start_polling()
    engine = QQmlApplicationEngine()
    engine.addImageProvider("lucide", LucideProvider())
    engine.rootContext().setContextProperty("cfg", model)
    engine.rootContext().setContextProperty("host", model)
    engine.warnings.connect(lambda items: [print("qml:", w.toString(), file=sys.stderr) for w in items])
    engine.load(str(QML))
    if not engine.rootObjects():
        print("YALW Config: the QML window failed to load", file=sys.stderr)
        return 1

    if snapshot is not None:
        _snapshot(app, engine.rootObjects()[0], model, snapshot)
    code = app.exec()
    del engine
    return code


def _snapshot(app, window, model: ConfigModel, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    shots = [("general", 0, "en"), ("appearance", 1, "en"), ("events", 2, "tr"), ("bluetooth", 3, "de"), ("lyrics", 4, "es"),
             ("extensions", 5, "en"), ("status", 6, "tr")]
    model.refreshStatus()
    state = {"i": 0}

    def step() -> None:
        if state["i"] >= len(shots):
            app.quit()
            return
        name, tab, lang = shots[state["i"]]
        model.set("language", lang)
        window.setProperty("tab", tab)

        def grab() -> None:
            window.grabWindow().save(str(out / f"config-{name}.png"))
            log.info("saved config-%s", name)
            QTimer.singleShot(150, step)

        QTimer.singleShot(700, grab)
        state["i"] += 1

    QTimer.singleShot(900, step)
