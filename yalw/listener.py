# SPDX-License-Identifier: GPL-3.0-or-later
"""Learn how loud each second of a song is — once per song, from the player's own audio stream.

Why: the lyrics tell us which parts of a song repeat, but not which of the repeating parts is the
chorus. The chorus is usually the loudest of them, so loudness settles those ties.

What is and is not done:

* Only the stream of the player that is playing is listened to (found through PulseAudio/PipeWire's
  ``sink-inputs``), never the whole system. If that stream cannot be told apart, nothing is recorded.
* The audio is reduced to one number per second right away and thrown away. Only that list of numbers
  is kept: in memory while the song plays, then in ``~/.local/state/yalw/audio`` once it is over.
* A song that has been learned is never listened to again.
* A song whose lyrics already say where the chorus is (a label) is never listened to at all: the label wins,
  so the loudness would never be used.
"""

import asyncio
import json
import logging
import math
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

import numpy as np

from . import prefs
from .config import state_dir

log = logging.getLogger("yalw.listener")

RATE = 11025              # mono, 16 bit: plenty for a loudness reading, and almost free to process
COMPLETE = 0.85           # this much of the song heard = learned
MIN_SAVE = 0.25           # less than this is not worth a file
FLOOR_DB = -80.0


# -- the feature store -----------------------------------------------------------------

def audio_dir() -> Path:
    return state_dir() / "audio"


def _file(artist: str, title: str, length: float) -> Path:
    return audio_dir() / f"{prefs.key(artist, title)}-{round(length)}.json"


def coverage(db: list) -> float:
    return sum(v is not None for v in db) / len(db) if db else 0.0


def load(artist: str, title: str, length: float) -> list | None:
    """Per-second loudness (dB, ``None`` where unheard) for this song, or None."""
    try:
        data = json.loads(_file(artist, title, length).read_text())
        return data["db"] if data.get("v") == 1 else None
    except (OSError, ValueError, KeyError):
        return None


def save(artist: str, title: str, length: float, heard: list) -> float:
    """Merge what was heard into what is already stored (a song may be learned over several plays)."""
    old = load(artist, title, length) or []
    merged = [h if h is not None else (old[i] if i < len(old) else None) for i, h in enumerate(heard)]
    path = _file(artist, title, length)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as handle:
        json.dump({"v": 1, "name": f"{artist} — {title}", "length": round(length), "coverage": round(coverage(merged), 3),
                   "db": merged, "saved": int(time.time())}, handle)
    os.replace(tmp, path)
    return coverage(merged)


def count_learned() -> int:
    try:
        return sum(1 for _ in audio_dir().glob("*.json"))
    except OSError:
        return 0


def forget_all() -> int:
    n = count_learned()
    shutil.rmtree(audio_dir(), ignore_errors=True)
    return n


def section_db(db: list, start: float, end: float) -> float | None:
    """Mean loudness over a stretch of the song; None when too little of it was heard."""
    seconds = range(max(0, int(start)), min(len(db), math.ceil(end)))
    heard = [db[i] for i in seconds if db[i] is not None]
    return sum(heard) / len(heard) if seconds and len(heard) >= 0.5 * len(seconds) else None


# -- finding the player's own stream ---------------------------------------------------------

def parse_sink_inputs(text: str) -> list[dict]:
    """``pactl list sink-inputs`` → [{"index", "sink", "corked", "props": {...}}]."""
    out: list[dict] = []
    for block in re.split(r"\n(?=Sink Input #)", text.strip()):
        head = re.match(r"Sink Input #(\d+)", block)
        if not head:
            continue
        sink = re.search(r"^\s*Sink:\s*(\d+)", block, re.M)
        corked = re.search(r"^\s*Corked:\s*(\w+)", block, re.M)
        props = dict(re.findall(r'^\s+([\w.\-]+) = "(.*)"$', block, re.M))
        out.append({"index": int(head[1]), "sink": int(sink[1]) if sink else -1,
                    "corked": bool(corked and corked[1] == "yes"), "props": props})
    return out


def parse_sinks(text: str) -> dict[int, str]:
    """``pactl list sinks short`` → {index: name}."""
    names = {}
    for row in text.splitlines():
        parts = row.split("\t")
        if len(parts) >= 2 and parts[0].isdigit():
            names[int(parts[0])] = parts[1]
    return names


def player_token(bus_name: str) -> str:
    """``org.mpris.MediaPlayer2.firefox.instance_1_42`` → ``firefox``."""
    return bus_name.split("MediaPlayer2.", 1)[-1].split(".")[0].lower()


def pick_stream(bus_name: str, inputs: list[dict]) -> dict | None:
    """The one playing stream that belongs to this player; None if there is none or it is ambiguous."""
    token = player_token(bus_name)
    if len(token) < 3:
        return None
    mine = [s for s in inputs if not s["corked"] and any(
        token in s["props"].get(k, "").lower() for k in ("application.name", "application.process.binary"))]
    return mine[0] if len(mine) == 1 else None


# -- turning audio into numbers ------------------------------------------------------------------

class LoudnessMeter:
    """Feed it raw s16le mono PCM; it hands back one dB value per full second."""

    def __init__(self, rate: int = RATE):
        self.rate = rate
        self._rest = b""
        self._samples = np.empty(0, dtype=np.int16)

    def feed(self, pcm: bytes) -> list[float]:
        pcm = self._rest + pcm
        usable = len(pcm) - len(pcm) % 2
        self._rest = pcm[usable:]
        self._samples = np.concatenate([self._samples, np.frombuffer(pcm[:usable], dtype="<i2")])
        out = []
        while len(self._samples) >= self.rate:
            second, self._samples = self._samples[: self.rate], self._samples[self.rate:]
            rms = float(np.sqrt(np.mean((second.astype(np.float64) / 32768.0) ** 2)))
            out.append(max(FLOOR_DB, 20 * math.log10(rms + 1e-9)))
        return out


# -- the learner -------------------------------------------------------------------------------------

class _Session:
    def __init__(self, song: tuple, proc, length: float):
        self.song, self.proc = song, proc
        self.db: list = [None] * (math.ceil(length) + 1)
        self.task: asyncio.Task | None = None


async def _run(*argv: str) -> str:
    proc = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    out, _ = await proc.communicate()
    return out.decode("utf-8", "replace")


class AudioLearner:
    """Watches which song is playing and, for songs not learned yet, listens to that player's stream."""

    def __init__(self, runtime, watcher, on_learned, skip=lambda: False):
        self.rt, self.watcher, self.on_learned = runtime, watcher, on_learned
        self.skip = skip                          # () -> bool: the playing song needs no listening
        self.session: _Session | None = None
        self.state = "idle"                       # idle | listening | learned | unavailable
        self._retry: dict[tuple, float] = {}

    @staticmethod
    def available() -> bool:
        return bool(shutil.which("pactl") and shutil.which("parec"))

    async def run(self) -> None:
        if not self.available():
            self.state = "unavailable"
            log.info("audio learning needs pactl and parec; not available")
            return
        while True:
            await asyncio.sleep(1.0)
            try:
                await self._tick()
            except Exception:  # noqa: BLE001 - this must never take the widget down
                log.exception("audio learning step failed")

    def _song(self, p) -> tuple | None:
        if p is None or not p.key or p.length_us <= 0:
            return None
        return (p.artist, p.title, round(p.length_us / 1_000_000))

    @staticmethod
    def _is_learned(song: tuple) -> bool:
        return coverage(load(*song) or []) >= COMPLETE        # a 2 KB file, read once a second

    async def _tick(self) -> None:
        p = self.watcher.current
        song = self._song(p)
        skipped = song is not None and self.skip()
        want = song is not None and p.status == "Playing" and not skipped and not self._is_learned(song)
        if self.session and (not want or self.session.song != song):
            await self._finish(discard=skipped and self.session.song == song)       # the label showed up late: keep nothing
        if want and not self.session and time.time() >= self._retry.get(song, 0):
            await self._start(p, song)
        elif song is not None and self._is_learned(song) and not self.session:
            self.state = "learned"
        elif not self.session:
            self.state = "idle"

    async def _start(self, p, song: tuple) -> None:
        inputs = parse_sink_inputs(await _run("pactl", "list", "sink-inputs"))
        stream = pick_stream(p.name, inputs)
        sinks = parse_sinks(await _run("pactl", "list", "sinks", "short"))
        if stream is None or stream["sink"] not in sinks:
            self._retry[song] = time.time() + 10          # not found (yet): look again in a moment, never fall back to "everything"
            return
        proc = await asyncio.create_subprocess_exec(
            "parec", f"--monitor-stream={stream['index']}", f"--device={sinks[stream['sink']]}.monitor",
            "--format=s16le", f"--rate={RATE}", "--channels=1", "--latency-msec=100", "--client-name=yalw",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        self.session = _Session(song, proc, p.length_us / 1_000_000)
        self.session.task = self.rt.loop.create_task(self._read(self.session, p))
        self.state = "listening"
        log.info("learning the loudness of %s — %s", song[0], song[1])

    async def _read(self, session: _Session, player) -> None:
        meter = LoudnessMeter()
        while chunk := await session.proc.stdout.read(8192):
            for value in meter.feed(chunk):
                index = int(player.position_now() / 1_000_000 - 0.5)       # which second of the song this was
                if player.status == "Playing" and 0 <= index < len(session.db):
                    session.db[index] = round(value, 1)

    async def _finish(self, discard: bool = False) -> None:
        session, self.session = self.session, None
        if session is None:
            return
        if session.proc.returncode is None:
            session.proc.terminate()
            try:
                await asyncio.wait_for(session.proc.wait(), 2)
            except asyncio.TimeoutError:
                session.proc.kill()
        if session.task:
            session.task.cancel()
        heard = coverage(session.db)
        self.state = "idle"
        if discard or heard < MIN_SAVE:
            return
        artist, title, length = session.song
        total = await self.rt.loop.run_in_executor(None, save, artist, title, length, session.db)
        log.info("heard %.0f%% of %s — %s (stored: %.0f%%)", heard * 100, artist, title, total * 100)
        self.on_learned({"artist": artist, "title": title, "length": length, "coverage": total})

    async def stop(self) -> None:
        await self._finish()
