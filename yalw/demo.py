# SPDX-License-Identifier: GPL-3.0-or-later
"""Synthetic events and covers, for trying the widget without a real player."""

import time
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QRadialGradient

from . import art
from .config import cache_dir

# The one demo song: every demo card, YALW Config's preview and the lyrics demos all show this.
TRACKS = [
    {"title": "Never Gonna Give You Up", "artist": "Rick Astley", "album": "Whenever You Need Somebody", "length": 213.0,
     "colors": ("#1b0b3a", "#ff3d9a", "#2bb7ff")},
]

# Original sample lyrics, written for this demo only. Sections are separated by blank entries.
_VERSE_1 = ["Streetlights hum a quiet tune", "Shadows dance along the wall",
            "Counting stars above the dunes", "Waiting for a midnight call"]
_CHORUS = ["Keep the lights on till the morning", "We are dancing in the neon rain",
           "Hold me close, there is no returning", "Singing out your name again"]
_VERSE_2 = ["Paper boats on rivers glowing", "Whispers drifting down the line",
            "Every road keeps overflowing", "With the hope that you are mine"]
DEMO_SECTIONS = [(_VERSE_1, "Verse"), (_CHORUS, "Chorus"), (_VERSE_2, "Verse"), (_CHORUS, "Chorus")]


def demo_lyrics(words: bool, start: float = 3.0, per_line: float = 3.0) -> dict:
    """The sample song as lyrics data: line-timed, or word-timed when ``words``."""
    lines, t = [], start
    for sec, (section, part) in enumerate(DEMO_SECTIONS):
        for text in section:
            tokens = text.split()
            step = (per_line - 0.4) / len(tokens)
            timed = [{"t": t + i * step, "text": w, "sp": i < len(tokens) - 1} for i, w in enumerate(tokens)] if words else []
            lines.append({"t": t, "e": t + per_line, "text": text, "words": timed, "part": "", "sec": sec})
            t += per_line
        t += 1.0
    return {"source": "demo", "synced": "word" if words else "line", "lines": lines}

BLUETOOTH = {
    "bluetooth": {"name": "MOMENTUM 4", "icon": "headphones", "battery": 78, "charging": False},
    "bluetooth-low": {"name": "AirPods Pro", "icon": "earbuds", "battery": 14, "charging": False},
    "bluetooth-charging": {"name": "Galaxy Buds2", "icon": "earbuds", "battery": 52, "charging": True},
    "bluetooth-keyboard": {"name": "Keychron K2", "icon": "keyboard", "battery": 91, "charging": False},
    "bluetooth-speaker": {"name": "JBL Flip 6", "icon": "speaker", "battery": -1, "charging": False},
}


def make_covers() -> list[Path]:
    """Abstract 640px covers, generated once."""
    out = cache_dir() / "demo"
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, track in enumerate(TRACKS):
        path = out / f"cover-{i}.png"
        if not path.exists():
            dark, hot, cool = (QColor(c) for c in track["colors"])
            img = QImage(640, 640, QImage.Format.Format_RGB32)
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            bg = QLinearGradient(0, 0, 640, 640)
            bg.setColorAt(0, dark)
            bg.setColorAt(1, cool.darker(220))
            p.fillRect(img.rect(), bg)
            for cx, cy, r, color, alpha in ((470, 190, 250, hot, 235), (170, 470, 210, cool, 190), (330, 330, 120, hot.lighter(140), 120)):
                g = QRadialGradient(QPointF(cx, cy), r)
                c = QColor(color)
                c.setAlpha(alpha)
                g.setColorAt(0, c)
                c.setAlpha(0)
                g.setColorAt(1, c)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(g)
                p.drawEllipse(QPointF(cx, cy), r, r)
            p.end()
            img.save(str(path))
        paths.append(path)
    return paths


class Demo:
    """Walks through fake tracks; also answers the card's own buttons."""

    def __init__(self) -> None:
        self.covers = make_covers()
        self.accents = [art.accent_for(p) for p in self.covers]
        self.index = 0
        self.playing = True
        self.position = 41.0
        self.stamp = time.time()

    def _now(self) -> float:
        if not self.playing:
            return self.position
        return min(self.position + time.time() - self.stamp, TRACKS[self.index]["length"])

    def payload(self, kind: str, direction: str = "none") -> dict:
        track = TRACKS[self.index]
        return {
            "kind": kind, "direction": direction,
            "title": track["title"], "artist": track["artist"], "album": track["album"],
            "art": self.covers[self.index].as_uri(), "accent": self.accents[self.index],
            "playing": self.playing, "length": track["length"],
            "position": self.position, "stamp": self.stamp * 1000,
        }

    def _reset_position(self, to: float = 0.0) -> None:
        self.position, self.stamp = to, time.time()

    def step(self, kind: str) -> dict | None:
        if kind == "new":
            self.index = (self.index + 1) % len(TRACKS)
            self.playing = True
            self._reset_position()
            return self.payload("new", "next")
        if kind == "next":
            self.index = (self.index + 1) % len(TRACKS)
            self._reset_position()
            return self.payload("next", "next")
        if kind == "prev":
            self.index = (self.index - 1) % len(TRACKS)
            self._reset_position()
            return self.payload("prev", "prev")
        if kind in ("play", "pause"):
            self._reset_position(self._now())
            self.playing = kind == "play"
            self.stamp = time.time()
            return self.payload(kind)
        return None

    def lyrics_scene(self, words: bool) -> tuple[dict, dict]:
        """The sample song, parked a few seconds before its first chorus."""
        from . import lyrics

        self.index = len(TRACKS) - 1
        self.playing = True
        sample = demo_lyrics(words)
        first_chorus = lyrics.windows(sample["lines"], "chorus")[0][0]
        self._reset_position(max(0.0, first_chorus - 7.0))
        return self.payload("new", "next"), sample

    def toggle(self) -> dict:
        return self.step("pause" if self.playing else "play")

    def seek(self, fraction: float) -> dict:
        self._reset_position(fraction * TRACKS[self.index]["length"])
        return self.payload("")
