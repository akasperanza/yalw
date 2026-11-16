# SPDX-License-Identifier: GPL-3.0-or-later
"""The object QML talks to: holds the current state and relays UI commands."""

import json
import logging
import os
import time
from collections import deque

from PySide6.QtCore import Property, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFontDatabase

from . import __version__, demo, i18n, lastsong, listener, lyrics, notice, prefs
from .config import Config
from .runtime import Runtime
from .builtin import power
from .surface import Surface, style_map

log = logging.getLogger("yalw.controller")

LIVE_RETURN_MS = 700     # after another card has gone, a live card waits this long before it comes back
MIN_SHOW_SECONDS = 3.0   # a card that came up stays at least this long, whatever asks it to go (no open-shut-open flicker)
IDLE_SECONDS = 4.0       # a card that is held open (hovered, action bar, lyrics) goes after this long with no movement

FONT_CHOICES = ("Inter", "Adwaita Sans", "SF Pro Display", "Cantarell", "Noto Sans", "DejaVu Sans")

def pick_font(preferred: str = "") -> str:
    families = set(QFontDatabase.families())
    if preferred in families:
        return preferred
    return next((f for f in FONT_CHOICES if f in families), "sans-serif")


class Controller(QObject):
    # state → QML
    mediaChanged = Signal()
    btChanged = Signal()
    noticeChanged = Signal()
    # moments → QML
    mediaEvent = Signal(str, str)     # kind, direction
    mediaUpdated = Signal()
    mediaGone = Signal()
    bluetoothEvent = Signal()
    noticeEvent = Signal()           # an extension / script / YALW itself wants a small card
    liveChanged = Signal()
    liveEvent = Signal()             # the live card has a new value (or comes back after another card)
    liveGone = Signal(str)           # take the live card with this key off the screen
    btUpdated = Signal()
    lyricsChanged = Signal()
    lyricsStart = Signal()            # a chorus (or the song) begins: show the lyrics card
    lyricsEnd = Signal()
    # worker threads → GUI thread
    mediaIn = Signal(object)
    btIn = Signal(object)
    noticeIn = Signal(object)
    lyricsIn = Signal(object)
    learnedIn = Signal(object)         # the audio learner finished a song
    demoIn = Signal(str)
    quitIn = Signal()
    quietIn = Signal(str)
    reloadIn = Signal()

    def __init__(self, cfg: Config, surface: Surface, runtime: Runtime, backend: str):
        super().__init__()
        self.cfg, self.surface, self.runtime, self.backend = cfg, surface, runtime, backend
        self.media_watcher = None
        self._media: dict = {"title": "", "artist": "", "album": "", "art": "", "accent": "#7c8cff",
                             "playing": False, "length": 0.0, "position": 0.0, "stamp": 0.0}
        self._bt: dict = {"name": "", "icon": "bluetooth", "battery": -1, "charging": False, "address": "", "connected": True}
        self._notice: dict = {"title": "", "subtitle": "", "icon": "bell", "accent": "", "progress": -1.0, "value": "",
                              "badge": "", "seconds": 4.5, "key": "", "source": ""}
        self._notice_times: deque[float] = deque()
        self._live: dict[str, dict] = {}      # live cards by key, the newest last
        self._live_key = ""                   # the one the screen belongs to
        self._live_muted: set[str] = set()    # dismissed by the user: silent until its owner clears it
        self._live_times: deque[float] = deque()
        self._window_up = False
        self._live_notice: dict = {}
        self.extensions = None                # the ExtensionHost, once it is running
        self._demo: demo.Demo | None = None
        self._quiet = False
        self._forcing = False                 # demo events always show, whatever the toggles say
        self._started = time.time()
        self._prefs = prefs.SongPrefs()
        self._song: dict = {}                 # remembered choices for the song that is playing
        self._db: list | None = None         # per-second loudness of the playing song, once learned
        self._pending: dict | None = None     # lyrics that arrived before we knew which song is playing
        self._lyrics_raw: dict | None = None  # as found; ``_lyrics`` is the same, shifted by the song's offset
        self._lyrics: dict | None = None
        self._lyr_windows: list[tuple[float, float]] = []
        self._fallback = False                # no chorus known: the card stays for the whole song
        self._lyr_idle = False                # the lyrics card went away unchanged; it returns with the next line
        self._lyr_idle_until = 0.0
        self._lyr_showing = False
        self._lyr_force = False               # the lyrics demos work even with lyrics switched off
        self._lyr_timer = QTimer(self)
        self._lyr_timer.setSingleShot(True)
        self._lyr_timer.setTimerType(Qt.TimerType.PreciseTimer)   # the default may be 5% late: a chorus is missed
        self._lyr_timer.timeout.connect(self._schedule_lyrics)
        self._font = pick_font(cfg.font)
        self._labels = i18n.strings(cfg.language)
        self.mediaIn.connect(self._on_real_media)
        self.btIn.connect(self._on_bt)
        self.noticeIn.connect(self._on_notice)
        self.lyricsIn.connect(self._on_lyrics)
        self.learnedIn.connect(self._on_learned)
        self.audio_learner = None
        self.demoIn.connect(self._on_demo)
        self.quietIn.connect(self._on_quiet)

    # -- constant layout facts for QML -------------------------------------

    stageW = Property(int, lambda s: s.surface.stage_w, constant=True)
    stageH = Property(int, lambda s: s.surface.stage_h, constant=True)
    insetX = Property(int, lambda s: s.surface.inset_x, constant=True)
    insetY = Property(int, lambda s: s.surface.inset_y, constant=True)
    alignH = Property(str, lambda s: s.cfg.align_h, constant=True)
    alignV = Property(str, lambda s: s.cfg.align_v, constant=True)
    mediaSeconds = Property(float, lambda s: s.cfg.media_seconds, constant=True)
    idleMs = Property(int, lambda s: int(IDLE_SECONDS * 1000), constant=True)
    minShowMs = Property(int, lambda s: int(MIN_SHOW_SECONDS * 1000), constant=True)
    bluetoothSeconds = Property(float, lambda s: s.cfg.bluetooth_seconds, constant=True)
    fontFamily = Property(str, lambda s: s._font, constant=True)
    connectedLabel = Property(str, lambda s: s._labels["connected"], constant=True)
    disconnectedLabel = Property(str, lambda s: s._labels["disconnected"], constant=True)
    chargingLabel = Property(str, lambda s: s._labels["charging"], constant=True)
    labels = Property("QVariantMap", lambda s: s._labels, constant=True)         # the card's own words
    songLine = Property(str, lambda s: s._labels["song_line"], constant=True)     # "{title} · {artist}" or the reverse
    style = Property("QVariantMap", lambda s: s._style(), constant=True)

    def _style(self) -> dict:
        return style_map(self.cfg)

    media = Property("QVariantMap", lambda s: s._media, notify=mediaChanged)
    lyrics = Property("QVariantMap", lambda s: s._lyrics_view(), notify=lyricsChanged)
    bt = Property("QVariantMap", lambda s: s._bt, notify=btChanged)
    notice = Property("QVariantMap", lambda s: s._notice, notify=noticeChanged)
    liveNotice = Property("QVariantMap", lambda s: s._live_notice, notify=liveChanged)

    # -- window management --------------------------------------------------

    @Slot()
    def showWindow(self) -> None:
        self._window_up = True
        self.surface.show()

    @Slot()
    def hideWindow(self) -> None:
        self._window_up = False
        self.surface.hide()
        if self._live:
            QTimer.singleShot(LIVE_RETURN_MS, self._live_resume)   # whatever was in the way is gone: the live card comes back

    @Slot(float, float, float, float)
    def setInputRect(self, x: float, y: float, w: float, h: float) -> None:
        self.surface.set_input(round(x), round(y), round(w), round(h))

    # -- commands from the card --------------------------------------------

    @Slot()
    def playPause(self) -> None:
        if self._demo:
            self._on_media(self._demo.toggle())
        elif self.media_watcher:
            self.runtime.submit(self.media_watcher.command("playpause"))

    @Slot()
    def next(self) -> None:
        if self._demo:
            self._on_media(self._demo.step("next"))
        elif self.media_watcher:
            self.runtime.submit(self.media_watcher.command("next"))

    @Slot()
    def previous(self) -> None:
        if self._demo:
            self._on_media(self._demo.step("prev"))
        elif self.media_watcher:
            self.runtime.submit(self.media_watcher.command("previous"))

    @Slot(float)
    def seek(self, fraction: float) -> None:
        if self._demo:
            self._on_media(self._demo.seek(fraction))
        elif self.media_watcher:
            self.runtime.submit(self.media_watcher.seek_fraction(fraction))

    # -- inbound events -----------------------------------------------------

    @Slot(str)
    def _on_quiet(self, mode: str) -> None:
        self._quiet = {"on": True, "off": False}.get(mode, not self._quiet)
        log.info("quiet mode %s", "on" if self._quiet else "off")
        self.lyricsChanged.emit()
        if self._quiet:
            self.mediaGone.emit()          # drop whatever card is up
            self.liveGone.emit(self._live_key)
        else:
            self._live_resume()

    def _allowed(self, kind: str) -> bool:
        if self._forcing:
            return True
        if self._quiet:
            return False
        return {"new": self.cfg.new_track, "next": self.cfg.skip, "prev": self.cfg.skip,
                "play": self.cfg.play_pause, "pause": self.cfg.play_pause}.get(kind, False)

    @Slot(object)
    def _on_real_media(self, payload: dict) -> None:
        self._demo = None                                  # a real player wins over the demo
        self._lyr_force = False
        self._on_media(payload)
        lastsong.remember(self._media)                     # for YALW Config's preview

    def _on_media(self, payload: dict) -> None:
        kind = payload.get("kind", "")
        if kind == "gone":
            self.mediaGone.emit()
            return
        song = (self._media["title"], self._media["artist"])
        self._media = {**self._media, **{k: payload[k] for k in self._media if k in payload}}
        if (self._media["title"], self._media["artist"]) != song:
            self._song = self._prefs.get(self._song_key())
            self._db = self._load_loudness()
            self._set_lyrics(None)                         # new song: forget the old words until the new ones arrive
            late, self._pending = self._pending, None
            if late and tuple(late["key"]) == (self._media["title"], self._media["artist"]):
                self._set_lyrics(late["result"])           # ...unless they were already waiting for it
        if kind:
            log.info("media %-5s %s — %s", kind, payload.get("artist", ""), payload.get("title", ""))
        self.mediaChanged.emit()
        if kind and self._allowed(kind):
            self.mediaEvent.emit(kind, payload.get("direction", "none"))
        else:
            self.mediaUpdated.emit()
        self._schedule_lyrics()

    @Slot(object)
    def _on_bt(self, payload: dict) -> None:
        if payload["type"] == "disconnected":
            self._bt = {**self._bt, **{k: payload[k] for k in self._bt if k in payload}, "battery": -1, "charging": False, "connected": False}
            log.info("bluetooth disconnected: %s", self._bt["name"])
            self.btChanged.emit()
            if self._forcing or (self.cfg.bluetooth_disconnect and not self._quiet):
                self.bluetoothEvent.emit()
        elif payload["type"] == "connected":
            self._bt = {**self._bt, **{k: payload[k] for k in self._bt if k in payload}, "connected": True}
            log.info("bluetooth connected: %s (%s) battery=%s charging=%s", self._bt["name"], self._bt["icon"],
                     self._bt["battery"], self._bt["charging"])
            self.btChanged.emit()
            if self._forcing or (self.cfg.bluetooth and not self._quiet):
                self.bluetoothEvent.emit()
        elif payload["type"] == "battery" and payload["address"] == self._bt["address"]:
            self._bt = {**self._bt, "battery": payload["battery"], "charging": payload["charging"]}
            self.btChanged.emit()
            self.btUpdated.emit()

    # -- small cards from extensions and scripts -----------------------------------------------

    def notify_json(self, text: str) -> str:
        """``yalw notify`` / the D-Bus ``Notify`` call. "" when it was accepted, otherwise why not. Any thread."""
        if len(text) > 4096:
            return "the notice is too large"
        now = time.monotonic()
        try:
            raw = json.loads(text)
            if isinstance(raw, dict) and raw.get("clear"):            # {"clear": "key"}: take a live card away
                self.noticeIn.emit({"clear": str(raw["clear"])[:notice.KEY_MAX], "source": "notify"})
                return ""
            card = notice.make(raw)
        except ValueError as exc:                    # includes malformed JSON
            return str(exc)
        times, limit, span, what = ((self._live_times, 10, 1, "live updates (limit 10 a second)") if card.live
                                    else (self._notice_times, 30, 60, "notices (limit 30 a minute)"))
        while times and now - times[0] > span:
            times.popleft()
        if len(times) >= limit:
            return f"too many {what}"
        times.append(now)
        self.noticeIn.emit(card.payload("notify"))
        return ""

    @Slot(object)
    def _on_notice(self, payload: dict) -> None:
        if payload.get("clear"):
            self._live_clear(payload["clear"])
            return
        if payload.get("live"):
            self._live_update(payload)
            return
        if self._quiet and not self._forcing:
            return
        self._notice = {**payload, "seconds": payload.get("seconds") or self.cfg.notice_seconds}
        log.info("notice %-10s %s", payload.get("source", ""), payload.get("title", ""))
        self.noticeChanged.emit()
        self.noticeEvent.emit()

    # -- live cards: they stay until cleared; one is on the screen at a time, the others wait their turn ----------------

    def _live_update(self, payload: dict) -> None:
        key = payload["key"]
        self._live.pop(key, None)
        self._live[key] = payload                                    # the newest goes last
        if key in self._live_muted or self._quiet:
            return
        if self._live_key in ("", key) or self._live_key not in self._live:
            first = self._live_key != key
            self._live_key = key
            self._live_notice = payload
            if first:
                log.info("live   %-10s %s", payload.get("source", ""), payload.get("title") or key)
            self.liveChanged.emit()
            self.liveEvent.emit()

    def _live_clear(self, key: str) -> None:
        self._live_muted.discard(key)
        if self._live.pop(key, None) is None:
            return
        if key == self._live_key:
            self._live_key = ""
            self.liveGone.emit(key)

    def _live_resume(self) -> None:
        """Put a live card on the screen if nothing else is there (after another card, or when quiet mode ends)."""
        if self._window_up or self._quiet:
            return
        key = self._live_key if self._live_key in self._live and self._live_key not in self._live_muted else ""
        if not key:
            key = next((k for k in reversed(self._live) if k not in self._live_muted), "")
        if key:
            self._live_key = key
            self._live_notice = self._live[key]
            self.liveChanged.emit()
            self.liveEvent.emit()

    @Slot(str)
    def liveDismissed(self, key: str) -> None:
        """The user double-clicked the live card away: it stays away until its owner clears it (and starts it again)."""
        if key in self._live:
            self._live_muted.add(key)
            log.info("live card %s dismissed by the user", key)
        if key == self._live_key:
            self._live_key = ""

    def _sample_notice(self, kind: str) -> dict:
        language = i18n.resolve(self.cfg.language)
        if kind == "charger":
            return notice.make(power.describe(False, 64, power.CHARGING, 2820, language)).payload("demo")
        if kind == "charger-unplug":
            return notice.make(power.describe(True, 64, power.DISCHARGING, 11400, language)).payload("demo")
        return notice.make({"title": "Build finished", "subtitle": "yalw · 12 s", "icon": "circle-check", "accent": "#3ddc97"}).payload("demo")

    # -- lyrics -----------------------------------------------------------------

    def lyric_sources(self) -> tuple[str, ...]:
        """Sources to ask for the current song; empty while lyrics are switched off."""
        c = self.cfg
        if not c.lyrics_enabled:
            return ()
        return tuple(n for n, on in (("local", c.lyrics_local), ("apple", c.lyrics_apple),
                                      ("lrclib", c.lyrics_lrclib), ("boidu", c.lyrics_boidu)) if on)

    def _lyrics_view(self) -> dict:
        if not self._lyrics:
            return {"lines": [], "synced": "", "source": ""}
        lines = self._lyrics["lines"]
        if not self.cfg.lyrics_words:
            lines = [{**l, "words": []} for l in lines]
        return {"lines": lines, "synced": "word" if self.cfg.lyrics_words and self._lyrics["synced"] == "word" else "line",
                "source": self._lyrics["source"]}

    def _lyrics_on(self) -> bool:
        if self._song.get("hidden") and not self._lyr_force:
            return False
        return self._lyr_force or (self.cfg.lyrics_enabled and not self._quiet)

    def _shifted(self, result: dict | None) -> dict | None:
        """``result`` with every time moved by the song's remembered offset."""
        off = self._song.get("offset", 0.0)
        if not result or not off:
            return result
        move = lambda l: {**l, "t": l["t"] + off, "e": l["e"] + off, "words": [{**w, "t": w["t"] + off} for w in l["words"]]}
        out = {**result, "lines": [move(l) for l in result["lines"]]}
        if result.get("chorus") is not None:
            out["chorus"] = [[a + off, b + off] for a, b in result["chorus"]]
        return out

    def _windows_for(self, result: dict, when: str) -> list[tuple[float, float]]:
        """When the lyrics card is up. The chorus if it is known: marked by the source, or (guessing on) found in repeated
        lines. When it is not, the whole song (``_fallback``): found lyrics are never left without a card."""
        lines, title = result["lines"], self._media["title"]
        if when != "chorus":
            return lyrics.windows(lines, when)
        if result.get("chorus_basis") == "labels" and result.get("chorus"):
            return [tuple(w) for w in result["chorus"]]
        found: list[tuple[float, float]] = []
        if self.cfg.lyrics_guess or self._lyr_force:
            if self._db:
                found = lyrics.windows(lines, "chorus", title, loudness=self._db)           # we have heard this song
            elif result.get("chorus") is not None:
                found = [tuple(w) for w in result["chorus"]]                                # worked out (once) when it was found
            else:
                found = lyrics.windows(lines, "chorus", title)
        if found or self._lyr_force:
            return found
        self._fallback = True
        return lyrics.windows(lines, "always")

    def _set_lyrics(self, result: dict | None) -> None:
        self._lyr_timer.stop()
        self._finish_lyrics()
        self._lyrics_raw = result
        result = self._lyrics = self._shifted(result)
        when = "chorus" if self._lyr_force else self.cfg.lyrics_when
        self._fallback = False
        self._lyr_idle = False
        self._lyr_windows = self._windows_for(result, when) if result else []
        if result:
            log.info("lyrics: %s, %s sync, %d lines, %d window(s)%s", result["source"], result["synced"],
                     len(result["lines"]), len(self._lyr_windows), f' — matched {result["match"]}' if result.get("match") else "")
        self.lyricsChanged.emit()

    @Slot(object)
    def _on_lyrics(self, payload: dict) -> None:
        if tuple(payload["key"]) != (self._media["title"], self._media["artist"]):
            self._pending = payload                        # keep it: we may simply not have heard of this song yet
            return
        self._pending = None
        self._set_lyrics(payload["result"])
        self._schedule_lyrics()

    # -- what the audio learner heard ------------------------------------------------------------

    def _learning_on(self) -> bool:
        c = self.cfg
        return bool(c.lyrics_enabled and c.lyrics_guess and c.lyrics_learn and c.lyrics_when == "chorus")

    def _load_loudness(self) -> list | None:
        m = self._media
        if not self._learning_on() or not m["length"]:
            return None
        db = listener.load(m["artist"], m["title"], m["length"])
        return db or None

    @Slot(object)
    def _on_learned(self, info: dict) -> None:
        m = self._media
        if (info["artist"], info["title"]) != (m["artist"], m["title"]):
            return
        self._db = self._load_loudness()
        if self._lyrics_raw:
            self._set_lyrics(self._lyrics_raw)
            self._schedule_lyrics()

    def has_chorus_label(self) -> bool:
        """The playing song's lyrics say where the chorus is, so listening to it would change nothing."""
        return bool(self._lyrics and self._lyrics.get("chorus_basis") == "labels")

    @Slot()
    def forgetAudio(self) -> None:
        listener.forget_all()
        self._db = None
        if self._lyrics_raw:
            self._set_lyrics(self._lyrics_raw)

    def _position_now(self) -> float:
        m = self._media
        pos = m["position"] + ((time.time() * 1000 - m["stamp"]) / 1000 if m["playing"] else 0.0)
        return min(pos, m["length"]) if m["length"] else pos

    def _begin_lyrics(self) -> None:
        if not self._lyr_showing:
            self._lyr_showing = True
            self.lyricsStart.emit()

    def _finish_lyrics(self) -> None:
        if self._lyr_showing:
            self._lyr_showing = False
            self.lyricsEnd.emit()

    @Slot()
    def _schedule_lyrics(self) -> None:
        """Decide, from the playback position, whether the lyrics card is up now or when it will be."""
        self._lyr_timer.stop()
        if not self._lyrics or not self._lyrics_on() or not self._media["playing"]:
            self._finish_lyrics()
            return
        now = self._position_now()
        for start, end in self._lyr_windows:
            if now < start:
                self._lyr_idle = False
                self._finish_lyrics()
                self._lyr_timer.start(max(1, int((start - now) * 1000)))
                return
            if now < end:
                if self._lyr_idle and now < self._lyr_idle_until:          # gone for lack of movement: wait for the next line
                    self._lyr_timer.start(max(1, int((min(self._lyr_idle_until, end) - now) * 1000)))
                    return
                self._lyr_idle = False
                self._begin_lyrics()
                self._lyr_timer.start(max(1, int((end - now) * 1000)))
                return
        self._lyr_idle = False
        self._finish_lyrics()

    @Slot()
    def lyricsIdled(self) -> None:
        """The lyrics card sat unchanged for ``IDLE_SECONDS`` and went away (an instrumental stretch, a held line).
        It comes back when the next line is about to be sung."""
        now = self._position_now()
        following = next((l["t"] for l in (self._lyrics or {}).get("lines", []) if l["t"] > now + 0.3), None)
        self._lyr_showing = False                                          # so that the return is announced again
        self._lyr_idle = True
        self._lyr_idle_until = float("inf") if following is None else following - 0.5
        self._schedule_lyrics()

    # -- the card's action bar ----------------------------------------------------

    def _song_key(self) -> str:
        return prefs.key(self._media["artist"], self._media["title"])

    def _remember(self, **changes) -> None:
        name = f'{self._media["artist"]} — {self._media["title"]}'
        self._song = self._prefs.set(self._song_key(), name=name, **changes)
        self.lyricsChanged.emit()

    @Property(float, notify=lyricsChanged)
    def lyricsOffset(self) -> float:
        return self._song.get("offset", 0.0)

    @Property(bool, notify=lyricsChanged)
    def lyricsHidden(self) -> bool:
        return bool(self._song.get("hidden"))

    @Property(bool, notify=lyricsChanged)
    def hasLyrics(self) -> bool:
        return bool(self._lyrics_raw)

    @Slot(float)
    def nudgeLyrics(self, seconds: float) -> None:
        """Move this song's lyrics earlier (negative) or later; remembered for next time."""
        if self._lyrics_raw is None:
            return
        offset = max(-15.0, min(15.0, round(self._song.get("offset", 0.0) + seconds, 2)))
        self._remember(offset=offset)
        self._set_lyrics(self._lyrics_raw)
        self._schedule_lyrics()

    @Slot()
    def toggleSongLyrics(self) -> None:
        """The lyrics for this song are wrong (or fine again): stop / resume showing them."""
        self._remember(hidden=not self._song.get("hidden"))
        self._schedule_lyrics()

    @Slot()
    def silence(self) -> None:
        self._on_quiet("on")

    @Slot()
    def raisePlayer(self) -> None:
        if self.media_watcher:
            self.runtime.submit(self.media_watcher.command("raise"))

    @Property(bool, notify=lyricsChanged)
    def quietOn(self) -> bool:
        return self._quiet

    def status(self) -> dict:
        """What YALW Config shows. Read from the D-Bus thread: plain values only."""
        m, current = self._media, self._lyrics
        return {
            "version": __version__, "pid": os.getpid(), "uptime": time.time() - self._started,
            "backend": self.backend, "quiet": self._quiet, "bluetooth": self.runtime.system_bus is not None,
            "players": len(self.media_watcher.players) if self.media_watcher else 0,
            "song": {"title": m["title"], "artist": m["artist"], "playing": m["playing"], "accent": m.get("accent", "")},
            "lyrics": {"enabled": self.cfg.lyrics_enabled, "sources": list(self.lyric_sources()),
                       "found": bool(current), "source": (current or {}).get("source", ""), "match": (current or {}).get("match", ""),
                       "synced": (current or {}).get("synced", ""), "windows": len(self._lyr_windows), "fallback": self._fallback,
                       "offset": self._song.get("offset", 0.0), "hidden": bool(self._song.get("hidden")),
                       "health": lyrics.health()},
            "extensions": self.extensions.status() if self.extensions else [],
            "audio": {"enabled": self._learning_on(), "state": self.audio_learner.state if self.audio_learner else "off",
                      "learned": listener.count_learned(), "using": bool(self._db)},
        }

    @Slot(str)
    def _on_demo(self, kind: str) -> None:
        self._forcing = True
        try:
            self._run_demo(kind)
        finally:
            self._forcing = False

    def _run_demo(self, kind: str) -> None:
        if kind in ("charger", "charger-unplug", "notice"):
            self._on_notice(self._sample_notice(kind))
            return
        if kind == "bluetooth-off":
            self._on_bt({"type": "disconnected", "address": "demo:off", **demo.BLUETOOTH["bluetooth"]})
            return
        if kind in demo.BLUETOOTH:
            self._on_bt({"type": "connected", "address": f"demo:{kind}", **demo.BLUETOOTH[kind]})
            return
        if kind in ("lyrics", "lyrics-words"):
            if self._demo is None:
                self._demo = demo.Demo()
            self._lyr_force = True
            payload, sample = self._demo.lyrics_scene(words=kind == "lyrics-words")
            self._on_media(payload)
            self._set_lyrics(sample)
            self._schedule_lyrics()
            return
        if self._demo is None:
            self._demo = demo.Demo()
            if kind in ("play", "pause"):                 # needs a baseline to flip from
                self._demo.playing = kind == "pause"
        payload = self._demo.step(kind)
        if payload is None:
            log.warning("unknown demo kind %r", kind)
            return
        self._on_media(payload)
