# SPDX-License-Identifier: GPL-3.0-or-later
"""``image://lucide/<name>?color=rrggbb&fill=1&sw=2`` — Lucide icons, recoloured
on the fly and rasterised at whatever size QML asks for, so they stay sharp."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtSvg import QSvgRenderer

ICON_DIR = Path(__file__).parent / "assets" / "lucide"


@lru_cache(maxsize=None)
def _source(name: str) -> str:
    return (ICON_DIR / f"{Path(name).name}.svg").read_text()


class LucideProvider(QQuickImageProvider):
    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)

    def requestImage(self, id, size, requested):  # noqa: A002 - Qt signature
        name, _, query = id.partition("?")
        opts = dict(parse_qsl(query))
        color = "#" + opts.get("color", "ffffff")
        try:
            svg = _source(name)
        except OSError:
            svg = _source("bluetooth")

        svg = svg.replace('stroke="currentColor"', f'stroke="{color}"')
        svg = svg.replace('stroke-width="2"', f'stroke-width="{opts.get("sw", "2")}"')
        if opts.get("fill") == "1":
            svg = svg.replace('fill="none"', f'fill="{color}"')

        w = requested.width() if requested.width() > 0 else 24
        h = requested.height() if requested.height() > 0 else 24
        image = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        QSvgRenderer(svg.encode()).render(painter)
        painter.end()
        return image
