# SPDX-License-Identifier: GPL-3.0-or-later
"""Cover art: turn an MPRIS ``artUrl`` into a local file and pick an accent colour."""

from __future__ import annotations

import colorsys
import hashlib
import logging
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from .config import cache_dir

log = logging.getLogger("yalw.art")

DEFAULT_ACCENT = "#7c8cff"
MAX_BYTES = 8 * 1024 * 1024
CACHE_LIMIT = 64 * 1024 * 1024


def prune(folder: Path, limit: int = CACHE_LIMIT) -> None:
    """Drop the oldest covers once the cache outgrows ``limit`` bytes."""
    try:
        files = sorted((f for f in folder.iterdir() if f.is_file()), key=lambda f: f.stat().st_mtime)
        total = sum(f.stat().st_size for f in files)
        while files and total > limit:
            oldest = files.pop(0)
            total -= oldest.stat().st_size
            oldest.unlink(missing_ok=True)
    except OSError:
        pass


def resolve(url: str) -> Path | None:
    """Local path for ``url`` (downloading and caching http(s) art), or None."""
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path))
        return path if path.is_file() else None
    if parsed.scheme not in ("http", "https"):
        return None

    target = cache_dir() / "art" / hashlib.sha1(url.encode()).hexdigest()
    if target.is_file() and target.stat().st_size > 0:
        return target
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "yalw"})
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 - scheme checked above
            data = resp.read(MAX_BYTES + 1)
        if not data or len(data) > MAX_BYTES:
            return None
        tmp = target.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(target)
        prune(target.parent)
        return target
    except OSError as exc:
        log.info("cover download failed: %s", exc)
        return None


def accent_for(path: Path | str) -> str:
    """A saturated, bright colour representative of the image."""
    image = QImage(str(path))
    if image.isNull():
        return DEFAULT_ACCENT
    image = image.scaled(40, 40, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).convertToFormat(QImage.Format.Format_RGB32)

    buckets = [[0.0, 0.0, 0.0, 0.0] for _ in range(12)]  # weight, r, g, b
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            r, g, b = c.redF(), c.greenF(), c.blueF()
            h, s, v = colorsys.rgb_to_hsv(r, g, b)
            if s < 0.28 or v < 0.22:
                continue
            weight = s * v
            bucket = buckets[min(11, int(h * 12))]
            bucket[0] += weight
            bucket[1] += r * weight
            bucket[2] += g * weight
            bucket[3] += b * weight

    best = max(buckets, key=lambda b: b[0])
    if best[0] <= 0:
        return "#cfd5ea"  # greyscale art
    r, g, b = (best[i] / best[0] for i in (1, 2, 3))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    r, g, b = colorsys.hsv_to_rgb(h, max(s, 0.55), min(1.0, max(v, 0.78)))
    return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))


def prepare(url: str) -> tuple[str, str]:
    """(file:// url or "", accent) — blocking, run it off the GUI thread."""
    path = resolve(url)
    if path is None:
        return "", DEFAULT_ACCENT
    return path.as_uri(), accent_for(path)
