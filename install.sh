#!/bin/sh
# YALW installer: puts YALW in its own virtual environment under ~/.local/share/yalw-app, links `yalw` into
# ~/.local/bin, adds "YALW Config" to the application menu and starts YALW at login. Needs no root.
#
#   ./install.sh               install (or update: run it again from a newer copy of the sources)
#   ./install.sh --no-service  everything except starting YALW at login
#
# Undo it with ./uninstall.sh
set -eu

SRC=$(cd "$(dirname "$0")" && pwd)
APP="${XDG_DATA_HOME:-$HOME/.local/share}/yalw-app"
BIN="$HOME/.local/bin"
SERVICE=1

say() { printf '%s\n' "$*"; }
die() { printf 'install.sh: %s\n' "$*" >&2; exit 1; }

for arg in "$@"; do
    case "$arg" in
        --no-service) SERVICE=0 ;;
        -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "unknown option '$arg' (see --help)" ;;
    esac
done

[ -f "$SRC/pyproject.toml" ] || die "run this from the YALW folder (pyproject.toml not found next to it)"
command -v python3 >/dev/null 2>&1 || die "python3 is not installed"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || die "Python 3.11 or newer is needed (found $(python3 -V 2>&1))"
python3 -c 'import venv, ensurepip' >/dev/null 2>&1 || die "Python's venv module is missing (Debian/Ubuntu: sudo apt install python3-venv)"

# If the system already has a recent PySide6 and dbus-fast (Arch: pyside6, python-dbus-fast), use them: the same Qt as
# the rest of the desktop, and nothing big to download. Otherwise pip fetches its own.
SITE=""
if python3 - <<'PY' >/dev/null 2>&1
import PySide6, dbus_fast, sys
sys.exit(tuple(int(n) for n in PySide6.__version__.split(".")[:2]) < (6, 6))
PY
then
    SITE="--system-site-packages"
    say "using the PySide6 and dbus-fast that are already installed"
else
    say "PySide6 and dbus-fast will be downloaded into YALW's own environment (a few hundred MB, once)"
fi

# pip builds inside the source folder; remember what was there so that only our leftovers are removed.
HAD_BUILD=0; [ -e "$SRC/build" ] && HAD_BUILD=1
HAD_EGG=0; ls -d "$SRC"/*.egg-info >/dev/null 2>&1 && HAD_EGG=1

say "installing into $APP"
rm -rf "$APP/venv"
mkdir -p "$APP"
python3 -m venv $SITE "$APP/venv"
if ! "$APP/venv/bin/pip" install --disable-pip-version-check --quiet "$SRC[lyrics]"; then
    die "pip could not install YALW (is there a network connection?)"
fi
[ "$HAD_BUILD" = 1 ] || rm -rf "$SRC/build"
[ "$HAD_EGG" = 1 ] || rm -rf "$SRC"/*.egg-info

mkdir -p "$BIN"
ln -sf "$APP/venv/bin/yalw" "$BIN/yalw"
say "linked $BIN/yalw"
case ":$PATH:" in
    *":$BIN:"*) ;;
    *) say "note: $BIN is not in your PATH; add it (for fish: fish_add_path ~/.local/bin) or call $BIN/yalw" ;;
esac

command -v upower >/dev/null 2>&1 || say "note: upower is not installed: the charger card will not work (and battery levels may be missing)"
command -v bluetoothctl >/dev/null 2>&1 || say "note: bluez is not installed: Bluetooth cards will not work"

"$APP/venv/bin/yalw" doctor || true
if [ "$SERVICE" = 1 ]; then
    "$APP/venv/bin/yalw" install
else
    "$APP/venv/bin/yalw" install --no-service
fi

say ""
say "Done. Try it:  yalw demo all      Settings:  yalw config  (or YALW Config in the menu)"
say "Remove it:     $SRC/uninstall.sh"
