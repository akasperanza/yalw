# SPDX-License-Identifier: GPL-3.0-or-later
import os
import time

import pytest

from yalw import art
from yalw.bluetooth import device_icon
from yalw.config import Config, load
from yalw.media import MediaWatcher, Player


def _bare() -> MediaWatcher:
    w = MediaWatcher.__new__(MediaWatcher)
    w._expect = None
    w.ignore = ()
    return w


def player(title: str, length_s: int = 200) -> Player:
    return Player(name="org.mpris.MediaPlayer2.t", title=title, artist="A", length_us=length_s * 1_000_000)


# -- config ------------------------------------------------------------------

def test_missing_config_gets_written_with_defaults(tmp_path):
    path = tmp_path / "yalw" / "config.toml"
    assert load(path) == Config()
    assert path.exists()
    assert load(path) == Config()          # the generated file parses back to the defaults


def test_bad_values_fall_back(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text('position = "middle"\nbackend = "nope"\n[timing]\nmedia = 0\n')
    cfg = load(path)
    assert (cfg.position, cfg.backend) == ("top-center", "auto")
    assert cfg.media_seconds >= 1.0


def test_broken_toml_is_ignored(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text("this is = = not toml")
    assert load(path) == Config()


def test_ignore_list_is_lowercased(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text('[media]\nignore = ["Firefox", "chromium"]\n')
    assert load(path).ignore_players == ("firefox", "chromium")


# -- bluetooth ---------------------------------------------------------------

@pytest.mark.parametrize("icon,name,expected", [
    ("audio-headset", "MOMENTUM 4", "headphones"),
    ("audio-headphones", "WH-1000XM5", "headphones"),
    ("audio-card", "JBL Flip 6", "speaker"),
    ("audio-card", "Galaxy Buds2", "earbuds"),
    ("audio-headset", "AirPods Pro", "earbuds"),
    ("input-mouse", "LOGI M240", "mouse"),
    ("input-keyboard", "K2", "keyboard"),
    ("phone", "Pixel 8", "smartphone"),
    ("", "Mi Band 8", "watch"),
    ("something-new", "Thing", "bluetooth"),
])
def test_device_icon(icon, name, expected):
    assert device_icon(icon, name) == expected


# -- cover cache -------------------------------------------------------------

def test_prune_removes_oldest_first(tmp_path):
    for i in range(5):
        f = tmp_path / f"c{i}"
        f.write_bytes(b"x" * 100)
        os.utime(f, (time.time() - 100 + i, time.time() - 100 + i))
    art.prune(tmp_path, limit=250)
    assert sorted(f.name for f in tmp_path.iterdir()) == ["c3", "c4"]


def test_resolve_rejects_odd_schemes():
    assert art.resolve("ftp://example.com/a.png") is None
    assert art.resolve("") is None
    assert art.resolve("file:///definitely/not/here.png") is None


# -- skip classification -----------------------------------------------------

def test_first_song_is_new():
    w, p = _bare(), player("B")
    assert w._classify_track_change(p, None, 0, 0) == ("new", "next")


def test_skip_mid_song_is_next():
    w, p = _bare(), player("B")
    assert w._classify_track_change(p, ("A",), 30_000_000, 200_000_000)[0] == "next"


def test_song_that_ran_out_is_new():
    w, p = _bare(), player("B")
    assert w._classify_track_change(p, ("A",), 198_000_000, 200_000_000)[0] == "new"


def test_going_back_is_prev():
    w, p = _bare(), player("A")
    p.history = [p.track_key()]
    assert w._classify_track_change(p, ("B", "A", "", ""), 20_000_000, 200_000_000) == ("prev", "prev")
    assert p.history == []


def test_own_button_press_wins_over_heuristics():
    w, p = _bare(), player("B")
    w._expect = ("prev", time.time() + 2)
    assert w._classify_track_change(p, ("A",), 198_000_000, 200_000_000) == ("prev", "prev")
    assert w._expect is None


def test_expired_button_press_is_ignored():
    w, p = _bare(), player("B")
    w._expect = ("prev", time.time() - 1)
    assert w._classify_track_change(p, ("A",), 30_000_000, 200_000_000)[0] == "next"


# -- ignore list -------------------------------------------------------------

def test_ignored_players_are_never_tracked():
    import asyncio

    w = _bare()
    w.ignore = ("firefox",)
    w.players = {}
    asyncio.run(w._add("org.mpris.MediaPlayer2.firefox.instance_1_42"))   # would need a bus if it got past the filter
    assert w.players == {}


# -- bluetooth disconnect ----------------------------------------------------

def test_disconnect_is_announced_once_with_the_device_identity():
    import types

    from dbus_fast import MessageType, Variant

    from yalw.bluetooth import BluetoothWatcher

    events = []
    w = BluetoothWatcher.__new__(BluetoothWatcher)
    w.emit, w._announced = events.append, {}
    path = "/org/bluez/hci0/dev_AA"
    w.devices = {path: {"Alias": "MOMENTUM 4", "Icon": "audio-headset", "Address": "AA", "Connected": True}}

    def drop(connected):
        body = ["org.bluez.Device1", {"Connected": Variant("b", connected)}, []]
        w._on_message(types.SimpleNamespace(message_type=MessageType.SIGNAL, member="PropertiesChanged", path=path, body=body))

    drop(False)
    drop(False)                                  # BlueZ repeating itself must not repeat the card
    assert events == [{"type": "disconnected", "address": "AA", "name": "MOMENTUM 4", "icon": "headphones"}]


def test_the_install_and_uninstall_scripts_are_valid_shell():
    import os
    import subprocess
    from pathlib import Path
    root = Path(__file__).parent.parent
    for name in ("install.sh", "uninstall.sh"):
        script = root / name
        assert os.access(script, os.X_OK), f"{name} must be executable"
        assert subprocess.run(["sh", "-n", str(script)], capture_output=True).returncode == 0
        assert subprocess.run(["sh", str(script), "--nonsense"], capture_output=True).returncode != 0


def test_install_can_skip_the_service():
    import subprocess
    import sys
    from pathlib import Path
    out = subprocess.run([sys.executable, "-m", "yalw", "install", "--help"], capture_output=True, text=True,
                         cwd=Path(__file__).parent.parent)
    assert "--no-service" in out.stdout
