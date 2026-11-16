# SPDX-License-Identifier: GPL-3.0-or-later
"""The song that played last, remembered so YALW Config can show it in its preview card.

Only the title, artist, album, length, accent colour and a copy of the cover are kept (one song, overwritten
each time) in ``~/.local/state/yalw``."""

import json
import logging
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

from .config import state_dir

log = logging.getLogger("yalw.lastsong")

_FIELDS = ("title", "artist", "album")
_COVER = re.compile(r"^last-song-cover-\d+\.img$")      # a new name for every cover: QML would keep showing a file whose name has not changed


def _meta_path() -> Path:
    return state_dir() / "last-song.json"


def _local(art: str) -> Path | None:
    if not art:
        return None
    path = Path(unquote(urlparse(art).path)) if art.startswith("file:") else Path(art)
    return path if path.is_file() else None


def remember(media: dict) -> bool:
    """Store the playing song if it differs from what is stored. True when something was written."""
    if not media.get("title"):
        return False
    meta = _meta_path()
    known = load() or {}
    source = _local(media.get("art", ""))
    same_song = all(known.get(k) == media.get(k, "") for k in _FIELDS)
    if same_song and (known.get("cover") or not source) and known.get("accent") == media.get("accent"):
        return False
    try:
        meta.parent.mkdir(parents=True, exist_ok=True)
        name = Path(known["cover"].removeprefix("file://")).name if same_song and known.get("cover") else ""
        if source is not None and not name:
            name = f"last-song-cover-{time.time_ns()}.img"
            shutil.copyfile(source, meta.parent / name)
        for old in meta.parent.glob("last-song-cover*.img"):                # only the current cover is kept
            if old.name != name:
                old.unlink(missing_ok=True)
        entry = {k: media.get(k, "") for k in _FIELDS}
        entry.update(accent=media.get("accent", ""), length=float(media.get("length") or 0), cover=name)
        fd, tmp = tempfile.mkstemp(dir=meta.parent, suffix=".tmp")
        with os.fdopen(fd, "w") as handle:
            json.dump(entry, handle)
        os.replace(tmp, meta)
        return True
    except OSError as exc:
        log.warning("could not remember the song: %s", exc)
        return False


def load() -> dict | None:
    """{"title", "artist", "album", "accent", "length", "cover": <file uri or "">} or None."""
    meta = _meta_path()
    try:
        data = json.loads(meta.read_text())
        entry = {k: str(data[k]) for k in _FIELDS}
        entry.update(accent=str(data.get("accent", "")), length=float(data.get("length", 0)))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    name = data.get("cover")
    cover = meta.parent / name if isinstance(name, str) and _COVER.match(name) else None
    entry["cover"] = cover.as_uri() if cover is not None and cover.is_file() else ""
    return entry if entry["title"] else None
