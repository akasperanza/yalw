# SPDX-License-Identifier: GPL-3.0-or-later
"""Decide how the widget reaches the screen.

* ``layer-shell`` — Wayland compositors that implement wlr-layer-shell
  (KDE Plasma, Hyprland, sway, niri, COSMIC, labwc, ...). A real overlay
  surface, anchored to a screen edge.
* ``xcb``         — X11, and XWayland on compositors without layer-shell
  (GNOME). An override-redirect window that sits above everything.
* ``wayland``     — last resort: a plain Wayland window (position is up to
  the compositor).
"""

from __future__ import annotations

import ctypes.util
import json
import logging
import os
import subprocess
import sys

log = logging.getLogger("yalw.display")

# Runs in a throw-away interpreter so a misbehaving libwayland can never take
# the daemon down. Prints the interfaces the compositor advertises.
_PROBE = r"""
import ctypes, json, sys
lib = ctypes.CDLL("libwayland-client.so.0")
lib.wl_display_connect.restype = ctypes.c_void_p
lib.wl_display_connect.argtypes = [ctypes.c_char_p]
display = lib.wl_display_connect(None)
if not display:
    print("[]"); sys.exit(0)
lib.wl_proxy_marshal_constructor.restype = ctypes.c_void_p
lib.wl_proxy_marshal_constructor.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p]
iface = ctypes.addressof(ctypes.c_char.in_dll(lib, "wl_registry_interface"))
registry = lib.wl_proxy_marshal_constructor(display, 1, iface, None)  # wl_display.get_registry
seen = []
GLOBAL = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32)
REMOVE = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32)
class Listener(ctypes.Structure):
    _fields_ = [("on_global", GLOBAL), ("on_remove", REMOVE)]
listener = Listener(GLOBAL(lambda d, r, n, i, v: seen.append(i.decode())), REMOVE(lambda d, r, n: None))
lib.wl_proxy_add_listener.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
lib.wl_proxy_add_listener(registry, ctypes.byref(listener), None)
lib.wl_display_roundtrip.argtypes = [ctypes.c_void_p]
lib.wl_display_roundtrip(display)
print(json.dumps(seen))
"""


def wayland_globals() -> set[str]:
    """Interfaces advertised by the running Wayland compositor (empty if none)."""
    if not os.environ.get("WAYLAND_DISPLAY"):
        return set()
    try:
        out = subprocess.run(
            [sys.executable, "-I", "-c", _PROBE], capture_output=True, text=True, timeout=4, check=True
        ).stdout
        return set(json.loads(out))
    except (subprocess.SubprocessError, ValueError, OSError) as exc:
        log.warning("wayland probe failed: %s", exc)
        return set()


def layer_shell_usable(globals_: set[str]) -> bool:
    return (
        "zwlr_layer_shell_v1" in globals_
        and ctypes.util.find_library("LayerShellQtInterface") is not None
        and os.path.exists("/usr/lib/qt6/plugins/wayland-shell-integration/liblayer-shell.so")
    )


def session_summary() -> dict:
    return {
        "XDG_SESSION_TYPE": os.environ.get("XDG_SESSION_TYPE", ""),
        "XDG_CURRENT_DESKTOP": os.environ.get("XDG_CURRENT_DESKTOP", ""),
        "WAYLAND_DISPLAY": os.environ.get("WAYLAND_DISPLAY", ""),
        "DISPLAY": os.environ.get("DISPLAY", ""),
    }


def choose_backend(requested: str = "auto") -> str:
    requested = os.environ.get("YALW_BACKEND", requested)
    if requested != "auto":
        return requested

    on_wayland = bool(os.environ.get("WAYLAND_DISPLAY")) and os.environ.get("XDG_SESSION_TYPE", "").lower() != "x11"
    if on_wayland:
        if layer_shell_usable(wayland_globals()):
            return "layer-shell"
        if os.environ.get("DISPLAY"):
            return "xcb"
        return "wayland"
    return "xcb"


def configure_environment(backend: str) -> None:
    """Must run before QGuiApplication is created."""
    os.environ.setdefault("QT_NO_XDG_DESKTOP_PORTAL", "1")   # we never need the portal; it only logs a warning
    if backend == "layer-shell":
        os.environ["QT_QPA_PLATFORM"] = "wayland"
        os.environ["QT_WAYLAND_SHELL_INTEGRATION"] = "layer-shell"
    elif backend == "xcb":
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    else:
        os.environ["QT_QPA_PLATFORM"] = "wayland"
