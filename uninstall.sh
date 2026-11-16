#!/bin/sh
# YALW uninstaller: stops YALW, removes the start-at-login entry, the menu entry, the `yalw` command and the
# environment that install.sh made. Your settings, extensions and caches are kept unless you ask otherwise.
#
#   ./uninstall.sh           remove YALW, keep ~/.config/yalw and your extensions
#   ./uninstall.sh --purge   also delete settings, extensions, remembered songs, lyrics cache and the log (asks first)
#   ./uninstall.sh --yes     do not ask (for --purge)
set -eu

APP="${XDG_DATA_HOME:-$HOME/.local/share}/yalw-app"
BIN="$HOME/.local/bin/yalw"
PURGE=0
YES=0

say() { printf '%s\n' "$*"; }

for arg in "$@"; do
    case "$arg" in
        --purge) PURGE=1 ;;
        --yes|-y) YES=1 ;;
        -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) printf 'uninstall.sh: unknown option %s (see --help)\n' "$arg" >&2; exit 1 ;;
    esac
done

# Stop it and remove its login entry and menu entry (yalw itself knows the paths).
if [ -x "$APP/venv/bin/yalw" ]; then
    "$APP/venv/bin/yalw" uninstall || true
else
    if command -v systemctl >/dev/null 2>&1; then
        systemctl --user disable --now yalw.service >/dev/null 2>&1 || true
    fi
    rm -f "$HOME/.config/systemd/user/yalw.service" "$HOME/.config/autostart/yalw.desktop" \
          "${XDG_DATA_HOME:-$HOME/.local/share}/applications/yalw-config.desktop" \
          "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps/yalw.svg"
    command -v systemctl >/dev/null 2>&1 && systemctl --user daemon-reload >/dev/null 2>&1 || true
fi
pkill -f -- "$APP/venv/bin/python.* -m yalw run" >/dev/null 2>&1 || true     # this install's, if started by hand or by autostart (not another copy)

# The command: only our own link, never someone else's file.
if [ -L "$BIN" ] && [ "$(readlink "$BIN")" = "$APP/venv/bin/yalw" ]; then
    rm -f "$BIN"
    say "removed $BIN"
fi
if [ -d "$APP" ]; then
    rm -rf "$APP"
    say "removed $APP"
fi

CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/yalw"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/yalw"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/yalw"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/yalw"

if [ "$PURGE" = 1 ]; then
    say ""
    say "This deletes your YALW settings and everything it remembered:"
    for dir in "$CONFIG" "$DATA" "$STATE" "$CACHE"; do [ -e "$dir" ] && say "  $dir"; done
    if [ "$YES" != 1 ]; then
        printf 'Delete them? [y/N] '
        read -r answer || answer=n
        case "$answer" in y|Y|yes|YES|e|E|evet) ;; *) say "kept them."; exit 0 ;; esac
    fi
    rm -rf "$CONFIG" "$DATA" "$STATE" "$CACHE"
    say "deleted."
else
    say ""
    say "Kept (delete them with ./uninstall.sh --purge):"
    for dir in "$CONFIG" "$DATA" "$STATE" "$CACHE"; do [ -e "$dir" ] && say "  $dir"; done
fi
say "YALW is removed."
