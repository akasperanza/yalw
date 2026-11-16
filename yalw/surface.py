# SPDX-License-Identifier: GPL-3.0-or-later
"""Window placement for each display backend.

The QML window is a fixed-size "stage" a little larger than the biggest card, so
the drop shadow has room. The card is positioned inside the stage by QML; this
module places the stage on screen and restricts input to the card itself.
"""

from __future__ import annotations

import ctypes
import logging
import math

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QRect, Qt
from PySide6.QtGui import QGuiApplication, QRegion
from PySide6.QtQuick import QQuickWindow

from .config import Config

log = logging.getLogger("yalw.surface")

CARD_MAX_W = 400
CARD_MAX_H = 214
COMPACT_W, COMPACT_MEDIA_H, COMPACT_LYRICS_H = 480, 104, 120
PAD = 56  # room for the shadow around the card


def card_sizes(cfg: Config) -> tuple[int, int, int]:
    """(card width, media-card height, lyrics-card height) before scaling. Compact cards are wider and shorter."""
    if cfg.compact:
        return COMPACT_W, COMPACT_MEDIA_H, COMPACT_LYRICS_H
    return CARD_MAX_W, CARD_MAX_H, 168


def style_map(cfg: Config) -> dict:
    """Everything the card QML needs to know about the settings (YALW and YALW Config's live preview alike)."""
    width, media_h, lyrics_h = card_sizes(cfg)
    return {
        "scale": cfg.scale, "mediaRadius": cfg.media_radius, "btRadius": cfg.bluetooth_radius,
        "accent": cfg.accent, "btAccent": cfg.bluetooth_accent, "dim": cfg.dim, "shadow": cfg.shadow,
        "equalizer": cfg.equalizer, "progress": cfg.show_progress, "hoverControls": cfg.hover_controls,
        "reducedMotion": cfg.reduced_motion, "btBattery": cfg.show_battery,
        "btLow": cfg.battery_low, "btWarn": cfg.battery_warn,
        "compact": cfg.compact, "cardW": width, "mediaH": media_h, "lyricsH": lyrics_h,
    }

# LayerShellQt::Window enums
_ANCHOR = {"top": 1, "bottom": 2, "left": 4, "right": 8}
_LAYER_OVERLAY = 3
_KEYBOARD_NONE = 0


class _Margins(ctypes.Structure):  # QMargins: left, top, right, bottom
    _fields_ = [("left", ctypes.c_int), ("top", ctypes.c_int), ("right", ctypes.c_int), ("bottom", ctypes.c_int)]


class _XcbRect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int16), ("y", ctypes.c_int16), ("width", ctypes.c_uint16), ("height", ctypes.c_uint16)]


class Surface:
    def __init__(self, cfg: Config, backend: str):
        self.cfg = cfg
        self.backend = backend
        self.window: QQuickWindow | None = None
        self._prepared = False
        self._input = QRect()
        self._xcb = None

        self.card_w, self.media_h, self.lyrics_h = card_sizes(cfg)
        self.pad = round(PAD * max(1.0, cfg.scale))     # the shadow grows with the card
        self.stage_w = math.ceil(self.card_w * cfg.scale) + 2 * self.pad
        self.stage_h = math.ceil(max(self.media_h, self.lyrics_h, 88) * cfg.scale) + 2 * self.pad
        # Distance from the stage edge to the card, per axis.
        self.inset_x = self.pad
        self.inset_y = self.pad
        if backend == "layer-shell":
            # Margins must not go negative, so a small margin shrinks the inset.
            self.inset_x = min(self.pad, cfg.margin)
            self.inset_y = min(self.pad, cfg.margin)

    # -- geometry -----------------------------------------------------------

    def screen(self):
        if self.cfg.monitor:
            for s in QGuiApplication.screens():
                if s.name() == self.cfg.monitor:
                    return s
            log.warning("monitor %r not found, using primary", self.cfg.monitor)
        return QGuiApplication.primaryScreen()

    def _xcb_position(self) -> tuple[int, int]:
        g = self.screen().geometry()
        m, h, v = self.cfg.margin, self.cfg.align_h, self.cfg.align_v
        if h == "left":
            x = g.left() + m - self.pad
        elif h == "right":
            x = g.right() + 1 - m + self.pad - self.stage_w
        else:
            x = g.center().x() + 1 - self.stage_w // 2
        y = g.top() + m - self.pad if v == "top" else g.bottom() + 1 - m + self.pad - self.stage_h
        return x, y

    # -- lifecycle ----------------------------------------------------------

    def attach(self, window: QQuickWindow) -> None:
        self.window = window

    def _prepare(self) -> None:
        win = self.window
        flags = Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus
        if self.backend == "xcb":
            flags |= Qt.WindowStaysOnTopHint | Qt.X11BypassWindowManagerHint | Qt.Tool
        win.setFlags(flags)
        win.setScreen(self.screen())
        if self.backend == "layer-shell":
            self._setup_layer_shell()
        self._prepared = True

    def _setup_layer_shell(self) -> None:
        align_h, align_v = self.cfg.align_h, self.cfg.align_v
        try:
            import shiboken6

            lib = ctypes.CDLL("libLayerShellQtInterface.so.6")
            get = lib._ZN12LayerShellQt6Window3getEP7QWindow
            get.restype = ctypes.c_void_p
            get.argtypes = [ctypes.c_void_p]
            handle = get(shiboken6.getCppPointer(self.window)[0])
            if not handle:
                raise RuntimeError("LayerShellQt::Window::get returned null")

            anchors = _ANCHOR[align_v]
            if align_h != "center":
                anchors |= _ANCHOR[align_h]
            margins = _Margins(0, 0, 0, 0)
            edge_margin = max(0, self.cfg.margin - self.pad)
            setattr(margins, align_v, edge_margin)
            if align_h != "center":
                setattr(margins, align_h, edge_margin)

            for name, argtype, value in (
                ("_ZN12LayerShellQt6Window10setAnchorsE6QFlagsINS0_6AnchorEE", ctypes.c_int, anchors),
                ("_ZN12LayerShellQt6Window8setLayerENS0_5LayerE", ctypes.c_int, _LAYER_OVERLAY),
                ("_ZN12LayerShellQt6Window24setKeyboardInteractivityENS0_21KeyboardInteractivityE", ctypes.c_int, _KEYBOARD_NONE),
            ):
                fn = getattr(lib, name)
                fn.restype = None
                fn.argtypes = [ctypes.c_void_p, argtype]
                fn(handle, value)

            set_margins = lib._ZN12LayerShellQt6Window10setMarginsERK8QMargins
            set_margins.restype = None
            set_margins.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            set_margins(handle, ctypes.byref(margins))
            # `scope` is a plain Q_PROPERTY, so no mangled QString plumbing is needed.
            shiboken6.wrapInstance(handle, QObject).setProperty("scope", "yalw")
            self._layer_lib = lib  # keep loaded
        except Exception as exc:  # noqa: BLE001 - degrade to a centred overlay
            log.warning("layer-shell setup failed (%s); the card will be centred", exc)

    def show(self) -> None:
        win = self.window
        if not self._prepared:
            self._prepare()
        if self.backend == "xcb":
            win.setPosition(*self._xcb_position())
        win.show()
        self._apply_input()

    def hide(self) -> None:
        # A hidden window never hears the pointer leave, so Qt would keep "hovered" (and the last pointer position) and
        # report a pointer over the next card that is nowhere near it. Say goodbye ourselves.
        QCoreApplication.sendEvent(self.window, QEvent(QEvent.Type.Leave))
        self.window.hide()

    # -- input region -------------------------------------------------------

    def set_input(self, x: int, y: int, w: int, h: int) -> None:
        self._input = QRect(x, y, w, h)
        if self.window is not None and self.window.isVisible():
            self._apply_input()

    def _apply_input(self) -> None:
        rect = self._input
        if rect.isEmpty() or self.window is None:
            return
        if self.backend == "xcb":
            self._xcb_input_shape(rect)
        else:
            self.window.setMask(QRegion(rect))

    def _xcb_input_shape(self, rect: QRect) -> None:
        """Clip *input* (not the picture) to the card, so the transparent
        shadow margin never swallows clicks."""
        try:
            if self._xcb is None:
                xcb = ctypes.CDLL("libxcb.so.1")
                shape = ctypes.CDLL("libxcb-shape.so.0")
                xcb.xcb_connect.restype = ctypes.c_void_p
                xcb.xcb_connect.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
                xcb.xcb_flush.argtypes = [ctypes.c_void_p]
                shape.xcb_shape_rectangles.restype = ctypes.c_uint
                shape.xcb_shape_rectangles.argtypes = [
                    ctypes.c_void_p, ctypes.c_uint8, ctypes.c_uint8, ctypes.c_uint8, ctypes.c_uint32,
                    ctypes.c_int16, ctypes.c_int16, ctypes.c_uint32, ctypes.c_void_p,
                ]
                self._xcb = (xcb, shape, xcb.xcb_connect(None, None))
            xcb, shape, conn = self._xcb
            dpr = self.window.devicePixelRatio()
            r = _XcbRect(int(rect.x() * dpr), int(rect.y() * dpr), int(rect.width() * dpr), int(rect.height() * dpr))
            # operation SET=0, destination kind INPUT=2, ordering UNSORTED=0
            shape.xcb_shape_rectangles(conn, 0, 2, 0, int(self.window.winId()), 0, 0, 1, ctypes.byref(r))
            xcb.xcb_flush(conn)
        except Exception as exc:  # noqa: BLE001
            log.warning("input shape unavailable: %s", exc)
            self._xcb = None
