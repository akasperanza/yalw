# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-song choices (lyrics timing offset, lyrics hidden), remembered between runs."""

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path

from .config import state_dir

log = logging.getLogger("yalw.prefs")


def key(artist: str, title: str) -> str:
    return hashlib.sha1(f"{artist}\n{title}".lower().encode()).hexdigest()[:16]


class SongPrefs:
    def __init__(self, path: Path | None = None):
        self.path = path or state_dir() / "songs.json"
        try:
            self._data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self._data = {}

    def get(self, song: str) -> dict:
        return dict(self._data.get(song, {}))

    def set(self, song: str, name: str = "", **changes) -> dict:
        """Merge ``changes`` into the song's entry; defaults are not stored."""
        entry = {**self._data.get(song, {}), **changes}
        if not entry.get("offset"):
            entry.pop("offset", None)
        if not entry.get("hidden"):
            entry.pop("hidden", None)
        if "offset" in entry or "hidden" in entry:               # "name" is only a label for whoever reads the file
            entry["name"] = name or entry.get("name", "")
            self._data[song] = entry
        else:
            self._data.pop(song, None)
        self._save()
        return self.get(song)

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
            with os.fdopen(fd, "w") as handle:
                json.dump(self._data, handle, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError as exc:
            log.warning("could not save song preferences: %s", exc)
