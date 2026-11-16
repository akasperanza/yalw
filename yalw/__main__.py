# SPDX-License-Identifier: GPL-3.0-or-later
"""``python -m yalw`` — command line front end."""

import argparse
import json
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import __version__, control
from .config import load

ROOT = Path(__file__).resolve().parents[1]
UNIT_PATH = Path.home() / ".config" / "systemd" / "user" / "yalw.service"
DEMO_KINDS = ("new", "next", "prev", "pause", "play",
              "bluetooth", "bluetooth-low", "bluetooth-charging", "bluetooth-keyboard", "bluetooth-speaker", "bluetooth-off",
              "lyrics", "lyrics-words", "charger", "charger-unplug", "notice")

AUTOSTART_PATH = Path.home() / ".config" / "autostart" / "yalw.desktop"
MENU_PATH = Path.home() / ".local" / "share" / "applications" / "yalw-config.desktop"
ICON_PATH = Path.home() / ".local" / "share" / "icons" / "hicolor" / "scalable" / "apps" / "yalw.svg"
FROM_CHECKOUT = (ROOT / "pyproject.toml").exists()


def _unit() -> str:
    env = f"Environment=PYTHONPATH={ROOT}\n" if FROM_CHECKOUT else ""
    return f"""\
[Unit]
Description=YALW — Yet Another Live Widget
After=graphical-session.target
PartOf=graphical-session.target

[Service]
ExecStart={sys.executable} -m yalw run
{env}Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical-session.target
"""


def _desktop_entry() -> str:
    env = f"env PYTHONPATH={ROOT} " if FROM_CHECKOUT else ""
    return f"""\
[Desktop Entry]
Type=Application
Name=YALW
Comment=Yet Another Live Widget
Exec={env}{sys.executable} -m yalw run
Terminal=false
X-GNOME-Autostart-enabled=true
"""


def _menu_entry() -> str:
    env = f"env PYTHONPATH={ROOT} " if FROM_CHECKOUT else ""
    return f"""\
[Desktop Entry]
Type=Application
Name=YALW Config
Comment=Settings for YALW, Yet Another Live Widget
Exec={env}{sys.executable} -m yalw config
Icon=yalw
Terminal=false
Categories=Settings;DesktopSettings;
StartupWMClass=yalw-config
"""


def _install_menu_entry() -> None:
    ICON_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__).parent / "assets" / "yalw.svg", ICON_PATH)
    MENU_PATH.parent.mkdir(parents=True, exist_ok=True)
    MENU_PATH.write_text(_menu_entry())
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(MENU_PATH.parent)], check=False, capture_output=True)


def _have_systemd_user() -> bool:
    if not shutil.which("systemctl"):
        return False
    state = subprocess.run(["systemctl", "--user", "is-system-running"], capture_output=True, text=True).stdout.strip()
    return state in ("running", "degraded")


def _check_dependencies() -> None:
    missing = []
    for module, package in (("PySide6", "PySide6"), ("dbus_fast", "dbus-fast")):
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    if missing:
        raise SystemExit(f"YALW needs {', '.join(missing)}. Arch: sudo pacman -S pyside6 python-dbus-fast"
                         f"   Others: pip install {' '.join(missing)}")


def _control(member: str, *args: str) -> None:
    status = control.send(member, *args)
    if status == control.NOT_RUNNING:
        raise SystemExit("YALW is not running (start it with: yalw run)")
    if status == control.OUTDATED:
        raise SystemExit(f"the running YALW does not understand '{member}'; "
                         "it is probably an older version: systemctl --user restart yalw")


def cmd_demo(kinds: list[str]) -> int:
    sequence = list(DEMO_KINDS[:5]) + ["bluetooth", "bluetooth-low"] if kinds == ["all"] else kinds
    for kind in sequence:
        if kind not in DEMO_KINDS:
            print(f"unknown demo kind {kind!r}; choose from: {', '.join(DEMO_KINDS)}, all", file=sys.stderr)
            return 2
    for i, kind in enumerate(sequence):
        _control("Demo", kind)
        if i < len(sequence) - 1:
            time.sleep(3.2)
    return 0


def cmd_doctor() -> int:
    from . import display

    print("session  ", display.session_summary())
    globals_ = display.wayland_globals()
    print("wayland   layer-shell:", "zwlr_layer_shell_v1" in globals_, f"({len(globals_)} globals)")
    print("backend   ", display.choose_backend(load().backend))
    return 0


def cmd_install(service: bool = True) -> int:
    _check_dependencies()
    _install_menu_entry()
    print("added 'YALW Config' to the application menu")
    if not service:
        print("no start-at-login set up (--no-service); start it with: yalw run")
    elif _have_systemd_user():
        UNIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        UNIT_PATH.write_text(_unit())
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "yalw.service"], check=True)
        subprocess.run(["systemctl", "--user", "restart", "yalw.service"], check=True)   # pick up new code
        print("installed as a systemd user service:", UNIT_PATH)
    else:
        AUTOSTART_PATH.parent.mkdir(parents=True, exist_ok=True)
        AUTOSTART_PATH.write_text(_desktop_entry())
        print("no systemd user session; installed an autostart entry:", AUTOSTART_PATH)
        print("it starts at your next login (or run: yalw run)")
    return 0


def cmd_uninstall() -> int:
    if shutil.which("systemctl"):
        subprocess.run(["systemctl", "--user", "disable", "--now", "yalw.service"], check=False, capture_output=True)
    for path in (UNIT_PATH, AUTOSTART_PATH, MENU_PATH, ICON_PATH):
        if path.exists():
            path.unlink()
            print("removed", path)
    if shutil.which("systemctl"):
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    return 0


def cmd_quiet(mode: str) -> int:
    _control("Quiet", mode)
    return 0


TEMPLATE = '''\
"""{title}: a YALW extension. The guide: docs/EXTENSIONS.md in the YALW sources."""

import asyncio

NAME = "{title}"
DESCRIPTION = "Reminds you to drink water now and then."
VERSION = "0.1"
AUTHOR = ""
API = 1


async def run(yalw):
    # Settings the user can change live in ~/.config/yalw/extensions/{ident}.toml, e.g.:  minutes = 30
    minutes = float(yalw.settings.get("minutes", 45))
    while True:
        await asyncio.sleep(minutes * 60)
        yalw.notify(
            yalw.tr({{"en": "Drink some water", "tr": "Biraz su iç", "de": "Trink etwas Wasser", "es": "Bebe un poco de agua"}}),
            icon="droplets",
            accent="#4d8dff",
        )
'''


def cmd_notify(args) -> int:
    """Show a card from the command line (or from any script): ``yalw notify "Backup done" "2.4 GB" --icon check``."""
    from . import notice

    progress = args.progress
    if progress is not None and progress > 1:
        progress /= 100                                   # 78 means 78 %
    if args.clear:
        raw = {"clear": args.clear}
    else:
        raw = {"title": args.title, "subtitle": args.subtitle, "icon": args.icon, "accent": args.accent, "progress": progress,
               "value": args.value, "badge": args.badge, "seconds": args.seconds, "key": args.key, "live": args.live or None}
        try:
            notice.make(raw)
        except ValueError as exc:
            print(f"yalw notify: {exc}", file=sys.stderr)
            return 2
    state, body = control.query("Notify", json.dumps({k: v for k, v in raw.items() if v not in (None, "")}))
    if state == control.NOT_RUNNING:
        print("YALW is not running (start it with: yalw run)", file=sys.stderr)
        return 1
    if state == control.OUTDATED:
        print("the running YALW is older and has no 'notify'; restart it: systemctl --user restart yalw", file=sys.stderr)
        return 1
    if body and body[0]:
        print(f"yalw notify: {body[0]}", file=sys.stderr)
        return 1
    return 0


def _daemon_extensions() -> dict:
    state, body = control.query("Status")
    if state != "ok" or not body:
        return {}
    try:
        return {e["id"]: e for e in json.loads(body[0]).get("extensions", [])}
    except (ValueError, KeyError):
        return {}


def cmd_extensions() -> int:
    from . import config, extensions

    cfg = load()
    running = _daemon_extensions()
    rows = [(i.id, "built in", i.name, "") for i in map(extensions.builtin_info, extensions.BUILTIN)]
    for info in extensions.discover():
        on = info.id in cfg.extensions_enabled
        state = running.get(info.id, {}).get("state", "enabled" if on else "off")
        note = "" if info.compatible else f"needs API {info.api or '?'}"
        rows.append((info.id, state, info.name + (f" {info.version}" if info.version else ""), note))
    for ident, state, name, note in rows:
        print(f"{ident:<20} {state:<9} {name}{('  (' + note + ')') if note else ''}")
    if len(rows) == len(extensions.BUILTIN):
        print(f"\nNo extensions installed. Put them in {config.extensions_dir()} (see docs/EXTENSIONS.md)")
    return 0


def cmd_extension(args) -> int:
    from . import config, extensions

    if args.action == "new":
        ident = args.name.strip().lower().replace(" ", "-")
        if not extensions.ID_PATTERN.match(ident):
            print("an extension id is lowercase letters, digits, - and _ (at most 40 characters)", file=sys.stderr)
            return 2
        target = config.extensions_dir() / f"{ident}.py"
        if target.exists():
            print(f"{target} already exists", file=sys.stderr)
            return 1
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(TEMPLATE.format(title=args.name.strip().title(), ident=ident))
        print(f"created {target}\nedit it, then: yalw extension enable {ident}")
        return 0

    ident = args.name.strip().lower()
    if args.action == "enable" and ident not in {i.id for i in extensions.discover()}:
        print(f"no extension {ident!r} in {config.extensions_dir()}", file=sys.stderr)
        return 1
    values = config.to_values(load())
    enabled = [e for e in values["extensions_enabled"] if e != ident]
    values["extensions_enabled"] = enabled + [ident] if args.action == "enable" else enabled
    config.save(values)
    print(f"{ident}: {'enabled' if args.action == 'enable' else 'disabled'}")
    if control.send("Reload") == control.NOT_RUNNING:
        print("YALW is not running; it takes effect at the next start")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="yalw", description="Yet Another Live Widget")
    parser.add_argument("--version", action="version", version=f"yalw {__version__}")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run", help="start the widget daemon (default)")
    demo = sub.add_parser("demo", help="trigger sample events on the running daemon")
    demo.add_argument("kinds", nargs="+", metavar="KIND", help=f"{', '.join(DEMO_KINDS)}, or 'all'")
    notify = sub.add_parser("notify", help="show a small card from a script: yalw notify TITLE [SUBTITLE]")
    notify.add_argument("title", nargs="?", default="", help="may be empty for a lone ring (with --progress)")
    notify.add_argument("subtitle", nargs="?", default="")
    notify.add_argument("--icon", default="bell", help="a Lucide icon name that ships with YALW (default: bell)")
    notify.add_argument("--accent", help="colour, #rrggbb")
    notify.add_argument("--progress", type=float, help="draws a ring: 0..1, or a percentage such as 78")
    notify.add_argument("--value", help="short text in the ring (default: the progress in percent)")
    notify.add_argument("--badge", help="a small icon on the ring, e.g. zap")
    notify.add_argument("--seconds", type=float, help="how long it stays (1-30)")
    notify.add_argument("--key", help="a card with the same key updates the one on screen instead of replacing it")
    notify.add_argument("--live", action="store_true", help="the card stays and is redrawn by every call with the same --key, until --clear")
    notify.add_argument("--clear", metavar="KEY", help="take the live card with this key away")
    sub.add_parser("extensions", help="list the installed extensions and whether they run")
    ext = sub.add_parser("extension", help="create, enable or disable an extension")
    ext.add_argument("action", choices=("new", "enable", "disable"))
    ext.add_argument("name")
    snap = sub.add_parser("snapshot", help="render each card state to PNG files")
    snap.add_argument("directory", type=Path)
    quiet = sub.add_parser("quiet", help="silence (or restore) all cards, e.g. while presenting")
    quiet.add_argument("mode", nargs="?", default="toggle", choices=("on", "off", "toggle"))
    cfgp = sub.add_parser("config", help="open YALW Config, the settings window")
    cfgp.add_argument("--snapshot", type=Path, metavar="DIR", help=argparse.SUPPRESS)
    sub.add_parser("reload", help="make the running daemon re-read its settings")
    sub.add_parser("doctor", help="show which display backend would be used")
    install = sub.add_parser("install", help="start at login (systemd user service, or an XDG autostart entry)")
    install.add_argument("--no-service", action="store_true", help="only add YALW Config to the application menu")
    sub.add_parser("uninstall", help="remove the systemd user service")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    cmd = args.cmd or "run"

    if cmd == "demo":
        return cmd_demo(args.kinds)
    if cmd == "reload":
        _control("Reload")
        return 0
    if cmd == "notify":
        return cmd_notify(args)
    if cmd == "extensions":
        return cmd_extensions()
    if cmd == "extension":
        return cmd_extension(args)
    if cmd == "config":
        _check_dependencies()
        from . import configapp

        return configapp.run(args.snapshot)
    if cmd == "quiet":
        return cmd_quiet(args.mode)
    if cmd == "doctor":
        return cmd_doctor()
    if cmd == "install":
        return cmd_install(service=not args.no_service)
    if cmd == "uninstall":
        return cmd_uninstall()

    _check_dependencies()
    from . import app

    cfg = load()
    if cmd == "snapshot":
        return app.snapshot(cfg, args.directory)
    return app.run(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
