# SPDX-License-Identifier: GPL-3.0-or-later
"""MPRIS watcher: turns player signals into "what just happened" events.

Event kinds sent to the UI:

``new``    a song started on its own (or the previous one had just ended)
``next``   the song was skipped forward
``prev``   the song was skipped back, or restarted with "previous"
``play`` / ``pause``   playback state flipped on the same song
"""

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from dbus_fast import MessageType
from dbus_fast.aio import MessageBus

from . import art, lyrics
from .runtime import Runtime, add_match, call

log = logging.getLogger("yalw.media")

MPRIS = "org.mpris.MediaPlayer2"
PLAYER = MPRIS + ".Player"
PATH = "/org/mpris/MediaPlayer2"
PROPS = "org.freedesktop.DBus.Properties"
DEBOUNCE = 0.12          # players emit several signals per change; wait for the dust to settle
RETRY_DELAYS = (20.0, 60.0, 180.0)     # lyrics lookups that could not reach the network are retried, while the song still plays
RESYNC = 4.0             # while lyrics are on, re-read the playback position this often (players drift, seeks go unannounced)
ART_WAIT = 1.5           # how long an event may wait for its cover before showing without
HISTORY = 8


@dataclass
class Player:
    name: str
    owner: str = ""
    status: str = "Stopped"
    title: str = ""
    artist: str = ""
    album: str = ""
    art_url: str = ""
    track_id: str = ""
    url: str = ""
    as_text: str = ""
    lyrics_key: tuple | None = None
    length_us: int = 0
    position_us: int = 0
    stamp: float = 0.0
    key: tuple | None = None
    history: list = field(default_factory=list)
    seeked_to: int | None = None
    art_file: str = ""
    art_for: str = ""
    accent: str = art.DEFAULT_ACCENT
    pending: asyncio.TimerHandle | None = None

    def position_now(self) -> int:
        if self.status == "Playing":
            return self.position_us + int((time.time() - self.stamp) * 1_000_000)
        return self.position_us

    def track_key(self) -> tuple | None:
        if not self.title:
            return None
        return (self.title, self.artist, self.album, self.track_id)


class MediaWatcher:
    def __init__(self, runtime: Runtime, emit: Callable[[dict], None], ignore: tuple[str, ...] = (),
                 lyric_sources: tuple[str, ...] = (), emit_lyrics: Callable[[dict], None] | None = None):
        self.rt = runtime
        self.emit = emit
        self.lyric_sources = lyric_sources          # empty = lyrics are off, nothing is looked up
        self.emit_lyrics = emit_lyrics
        self.ignore = ignore
        self.bus: MessageBus = runtime.bus
        self.players: dict[str, Player] = {}
        self.current: Player | None = None
        self._expect: tuple[str, float] | None = None   # ("next"/"prev", deadline) from our own buttons
        self._own_seek_until = 0.0

    # -- startup ------------------------------------------------------------

    async def start(self) -> None:
        await add_match(self.bus, "type='signal',sender='org.freedesktop.DBus',interface='org.freedesktop.DBus',"
                                  f"member='NameOwnerChanged',arg0namespace='{MPRIS}'")
        await add_match(self.bus, f"type='signal',interface='{PROPS}',member='PropertiesChanged',path='{PATH}'")
        await add_match(self.bus, f"type='signal',interface='{PLAYER}',member='Seeked',path='{PATH}'")
        self.bus.add_message_handler(self._on_message)

        if self.lyric_sources:
            self.rt.spawn(self._resync())
        (names,) = await call(self.bus, "org.freedesktop.DBus", "/org/freedesktop/DBus",
                              "org.freedesktop.DBus", "ListNames")
        for name in names:
            if name.startswith(MPRIS + "."):
                await self._add(name)

    # -- bus traffic --------------------------------------------------------

    def _on_message(self, msg) -> None:
        if msg.message_type != MessageType.SIGNAL:
            return
        if msg.member == "NameOwnerChanged" and msg.body[0].startswith(MPRIS + "."):
            name, _old, new = msg.body
            if new:
                self.rt.spawn(self._add(name))
            else:
                self._remove(name)
        elif msg.member == "PropertiesChanged" and msg.path == PATH and msg.body[0] == PLAYER:
            if (p := self._by_owner(msg.sender)) is not None:
                self._schedule(p)
        elif msg.member == "Seeked" and msg.path == PATH:
            if (p := self._by_owner(msg.sender)) is not None:
                p.seeked_to = int(msg.body[0])
                self._schedule(p)

    def _by_owner(self, owner: str) -> Player | None:
        return next((p for p in self.players.values() if p.owner == owner), None)

    async def _add(self, name: str) -> None:
        if any(word in name.lower() for word in self.ignore):
            return
        try:
            (owner,) = await call(self.bus, "org.freedesktop.DBus", "/org/freedesktop/DBus",
                                  "org.freedesktop.DBus", "GetNameOwner", "s", [name])
        except RuntimeError:
            return
        player = Player(name=name, owner=owner)
        self.players[name] = player
        if await self._refresh(player):
            player.key = player.track_key()           # baseline: no popup for what is already there
            if player.status == "Playing" or self.current is None:
                self.current = player
            if player is self.current:
                # The controller knows nothing yet (we may just have been restarted). Without this, the lyrics
                # of the song that is playing would arrive for a song it has never heard of, and be dropped.
                await self._load_art(player, wait=ART_WAIT)
                self.emit(self._payload(player, "", ""))
                self._want_lyrics(player)
            else:
                self.rt.spawn(self._load_art(player, wait=ART_WAIT))

    def _remove(self, name: str) -> None:
        gone = self.players.pop(name, None)
        if gone is None:
            return
        if gone.pending:
            gone.pending.cancel()
        if self.current is gone:
            playing = [p for p in self.players.values() if p.status == "Playing"]
            self.current = (playing or list(self.players.values()) or [None])[0]
            if self.current is None:
                self.emit({"kind": "gone"})

    # -- state --------------------------------------------------------------

    async def _refresh(self, p: Player) -> bool:
        try:
            (props,) = await call(self.bus, p.name, PATH, PROPS, "GetAll", "s", [PLAYER])
        except RuntimeError:
            return False

        p.status = props["PlaybackStatus"].value if "PlaybackStatus" in props else "Stopped"
        meta = props["Metadata"].value if "Metadata" in props else {}

        def field_(key: str, default=""):
            return meta[key].value if key in meta else default

        artists = field_("xesam:artist", [])
        p.title = str(field_("xesam:title"))
        p.artist = ", ".join(artists) if isinstance(artists, list) else str(artists)
        p.album = str(field_("xesam:album"))
        p.art_url = str(field_("mpris:artUrl"))
        p.track_id = str(field_("mpris:trackid"))
        p.url = str(field_("xesam:url"))
        p.as_text = str(field_("xesam:asText"))
        try:
            p.length_us = int(field_("mpris:length", 0))
        except (TypeError, ValueError):
            p.length_us = 0
        p.position_us = int(props["Position"].value) if "Position" in props else 0
        p.stamp = time.time()
        return True

    def _schedule(self, p: Player) -> None:
        if p.pending:
            p.pending.cancel()
        p.pending = self.rt.loop.call_later(DEBOUNCE, lambda: self.rt.spawn(self._evaluate(p)))

    # -- classification -----------------------------------------------------

    def _classify_track_change(self, p: Player, prev_key: tuple | None, prev_pos: int, prev_len: int) -> tuple[str, str]:
        key = p.track_key()
        expected, self._expect = self._expect, None
        went_back = bool(p.history) and p.history[-1] == key

        if went_back:
            p.history.pop()
        elif prev_key is not None:
            p.history = (p.history + [prev_key])[-HISTORY:]

        if prev_key is None:
            return "new", "next"
        if expected and time.time() < expected[1]:
            return expected[0], "next" if expected[0] == "next" else "prev"
        if went_back:
            return "prev", "prev"
        finished = prev_len > 0 and (prev_len - prev_pos) < 3_000_000
        if finished:
            return "new", "next"
        return "next", "next"

    async def _evaluate(self, p: Player) -> None:
        if p.name not in self.players:
            return
        prev_status, prev_key = p.status, p.key
        prev_pos, prev_len = p.position_now(), p.length_us
        seeked_to, p.seeked_to = p.seeked_to, None

        if not await self._refresh(p):
            return
        key = p.track_key()
        kind = direction = ""

        if key is not None and key != prev_key:
            kind, direction = self._classify_track_change(p, prev_key, prev_pos, prev_len)
            p.key = key
        elif (seeked_to is not None and key is not None and key == prev_key
              and seeked_to < 2_500_000 and prev_pos > 4_000_000 and time.time() > self._own_seek_until):
            kind, direction = "prev", "prev"      # "previous" on most players restarts the song
        elif key is not None and p.status != prev_status:
            if p.status == "Playing":
                kind = "play"
            elif prev_status == "Playing":
                kind = "pause"

        if kind or p.status == "Playing":
            self.current = p
        if p is not self.current:
            return

        if p.art_url != p.art_for:
            await self._load_art(p, wait=ART_WAIT if kind in ("new", "next", "prev") else 0)
        self.emit(self._payload(p, kind, direction))
        self._want_lyrics(p)

    async def _resync(self) -> None:
        """The lyrics card is timed from the playback position, so keep that position honest."""
        while True:
            await asyncio.sleep(RESYNC)
            p = self.current
            if p is not None and p.status == "Playing" and p.name in self.players:
                self._schedule(p)

    def _want_lyrics(self, p: Player) -> None:
        if self.lyric_sources and self.emit_lyrics and p.key and p.lyrics_key != p.key:
            p.lyrics_key = p.key
            self.rt.spawn(self._fetch_lyrics(p, p.key))

    async def _fetch_lyrics(self, p: Player, key: tuple) -> None:
        meta = {"title": p.title, "artist": p.artist, "album": p.album, "length": p.length_us / 1_000_000,
                "url": p.url, "mpris": p.as_text}
        for attempt, delay in enumerate((0, *RETRY_DELAYS)):
            if delay:
                await asyncio.sleep(delay)
                if p.key != key or p.lyrics_key != key:                # another song by now: not our business any more
                    return
            result, unreachable = await self.rt.loop.run_in_executor(None, lyrics.search, meta, self.lyric_sources)
            if result is not None or not unreachable or attempt == len(RETRY_DELAYS):
                break
            log.info("lyrics: could not reach %s for %s — %s; trying again in %d s", ", ".join(unreachable), p.artist, p.title,
                     RETRY_DELAYS[attempt])
        if result is None:
            reason = f"; could not reach {', '.join(unreachable)}" if unreachable else ""
            log.info("lyrics: none found for %s — %s (asked: %s%s)", p.artist, p.title, ", ".join(self.lyric_sources), reason)
        if p.key == key:                              # the song may have changed while we were away
            self.emit_lyrics({"key": [p.title, p.artist], "result": result})

    async def _load_art(self, p: Player, wait: float) -> None:
        url = p.art_url
        p.art_for = url
        task = self.rt.loop.run_in_executor(None, art.prepare, url)
        try:
            p.art_file, p.accent = await asyncio.wait_for(asyncio.shield(task), wait or 0.001)
        except asyncio.TimeoutError:
            p.art_file, p.accent = "", art.DEFAULT_ACCENT

            async def late() -> None:           # the cover arrived after the card went up
                file, accent = await task
                if p.art_for == url:
                    p.art_file, p.accent = file, accent
                    if p is self.current:
                        self.emit(self._payload(p, "", ""))

            self.rt.spawn(late())

    @staticmethod
    def _payload(p: Player, kind: str, direction: str) -> dict:
        return {
            "kind": kind,
            "direction": direction or "none",
            "title": p.title,
            "artist": p.artist,
            "album": p.album,
            "art": p.art_file,
            "accent": p.accent,
            "playing": p.status == "Playing",
            "length": p.length_us / 1_000_000,
            "position": p.position_us / 1_000_000,
            "stamp": p.stamp * 1000,
        }

    # -- commands from the UI ----------------------------------------------

    def _target(self) -> Player | None:
        return self.current or next(iter(self.players.values()), None)

    async def command(self, what: str) -> None:
        p = self._target()
        if p is None:
            return
        member = {"next": "Next", "previous": "Previous", "playpause": "PlayPause", "raise": "Raise"}[what]
        if what in ("next", "previous"):
            self._expect = ("next" if what == "next" else "prev", time.time() + 2.0)
        try:
            await call(self.bus, p.name, PATH, MPRIS if what == "raise" else PLAYER, member)
        except RuntimeError as exc:
            log.info("%s failed: %s", member, exc)

    async def seek_fraction(self, fraction: float) -> None:
        p = self._target()
        if p is None or p.length_us <= 0:
            return
        target = int(max(0.0, min(1.0, fraction)) * p.length_us)
        self._own_seek_until = time.time() + 1.5
        try:
            if p.track_id.startswith("/"):
                await call(self.bus, p.name, PATH, PLAYER, "SetPosition", "ox", [p.track_id, target])
            else:
                await call(self.bus, p.name, PATH, PLAYER, "Seek", "x", [target - p.position_now()])
        except RuntimeError as exc:
            log.info("seek failed: %s", exc)
