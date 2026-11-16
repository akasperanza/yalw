# YALW — Yet Another Live Widget

**English** · [Türkçe](README.tr.md)

Small floating cards for the Linux desktop. When something happens, a card appears in the corner of your screen
for a moment and goes away: a new song, a Bluetooth device, the charger being plugged in, or anything *you* teach it
with a few lines of Python.

<!-- screenshots go here -->

| Event | Card |
|---|---|
| New song | Cover, title, artist, progress bar |
| Next / previous song | The same card; the text slides in the direction you skipped |
| Play / pause | The cover dims or lights up, a badge appears |
| Bluetooth device connected / lost | Icon by device type, name, battery ring (⚡ while charging); grey when it disconnects |
| Charger plugged in (optionally: unplugged) | A bare, transparent ring that fills from 0 to your battery level, with a charge icon and the number counting up inside; it fades in where your cards live, no sliding |
| **Lyrics** (off by default) | When the chorus starts, a card shows the lyrics; word-timed lyrics fade in word by word, line-timed ones line by line |
| **Cards from extensions** | Anyone can add their own events; see [Extensions](#extensions) |

Hover a card to pause its timer and reveal **previous / play-pause / next** buttons. Nothing stays forever though:
a card that is held open with the pointer closes after 4 seconds without movement. A card shows for at least 3 seconds
(no open-shut-open flicker), and it does not appear at all if your pointer is where it would appear.

* **Double-click** a card: it fades away quickly.
* **Right-click**: a small action strip opens: open the player, lyrics 0.5 s earlier / later, *wrong lyrics: hide for this song*,
  silence all cards. Lyrics timing and hiding are remembered per song.
* Drag the progress bar to seek.

## Which desktops it works on

YALW picks how to draw at start-up:

* **layer-shell** — KDE Plasma, Hyprland, sway, niri, COSMIC, labwc… a real overlay surface pinned to the edge.
* **xcb** — X11 sessions, and Wayland compositors without layer-shell (**GNOME**): an always-on-top window through XWayland.
* **wayland** — last resort: an ordinary Wayland window (the compositor decides where it goes).

`yalw doctor` tells you which one it will use.

> **Honest status:** YALW was developed and tested on **GNOME (Wayland, through XWayland)**. The layer-shell path (KDE,
> Hyprland, sway…) and X11 sessions are written but have never been run by the author on a real desktop. The charger
> card was tested against a fake UPower, not yet on a real plug and unplug. Bug reports from other desktops are very welcome.

## Install

You need Linux, Python ≥ 3.11 and a user session with D-Bus. `bluez` (Bluetooth cards) and `upower` (charger card) are
optional. The installer needs no root:

```bash
git clone https://github.com/akasperanza/yalw && cd yalw
./install.sh                # install or update (no start-at-login: ./install.sh --no-service)
```

It puts YALW in its own virtual environment under `~/.local/share/yalw-app`, links `yalw` into `~/.local/bin`, adds
**YALW Config** to the application menu and starts YALW at login (a systemd user service, or an XDG autostart entry if
there is no systemd session). If PySide6 ≥ 6.6 and dbus-fast are already installed (Arch: `pyside6`, `python-dbus-fast`)
it uses those; otherwise pip downloads them once.

By hand instead: `pipx install .` (then `yalw install` for the menu entry and start-at-login).
For a real overlay on KDE, Hyprland and friends, install `layer-shell-qt` as well.

```bash
yalw doctor        # which display path will be used
yalw demo all      # see the cards
yalw config        # the settings window (also in the application menu)
```

To remove it:

```bash
./uninstall.sh              # keeps your settings and extensions
./uninstall.sh --purge      # deletes those too (asks first; --yes does not ask)
```

## Usage

```bash
yalw run                    # start (the installer already starts it at login)
yalw demo all               # sample events, one after another
yalw demo bluetooth-low     # one sample (yalw demo -h lists them)
yalw config                 # YALW Config
yalw reload                 # after editing the config file by hand
yalw quiet on|off|toggle    # silence every card (presentations, games)
yalw install                # start at login
yalw uninstall
```

Demo kinds: `new next prev pause play bluetooth bluetooth-low bluetooth-charging bluetooth-keyboard bluetooth-speaker bluetooth-off lyrics lyrics-words charger charger-unplug notice`

## Lyrics

Turn them on in `yalw config` → **Lyrics** (off by default). Two modes: **chorus only** (the card comes down when the
chorus starts and leaves when it ends) or **the whole song**. The lyrics follow the playback position; they pause when
you pause and jump when you seek.

When the lyrics source marks the chorus itself, the card stays for the chorus. When it does not, the card stays for the
whole song, so a song with lyrics is never left without a card. An **experimental, off-by-default** switch tries to find
the chorus in the text instead (repeated sections), and can use a per-second loudness count from the player's own audio
stream to break ties: only numbers are kept, never audio, and nothing leaves your computer.

| Source | What it gives |
|---|---|
| The player's own lyrics / a local `.lrc` file | Next to the song, or `~/.cache/yalw/local/Artist - Title.lrc`; comes first |
| Apple Music, through the [lrc.red](https://lrc.red) proxy | Word-timed, with section labels |
| [LRCLIB](https://lrclib.net) | Line-timed (sometimes word-timed) |
| boidu (`lyrics-api.boidu.dev`) | A second Apple Music proxy |

All are asked in parallel and the best result wins (real word timing > guessed word timing > line timing). Results are
cached in `~/.cache/yalw/lyrics`.

> **Privacy and terms:** with lyrics on, the artist, title, album and length of the playing song are sent to these
> services; with lyrics off nothing is sent. lrc.red and boidu are community proxies for Apple Music lyrics that Apple does
> not endorse, and they can disappear or change at any time; using them is your choice, and each source can be switched off
> in the Lyrics tab. YALW does not distribute lyrics; it fetches and shows them at run time.

## Extensions

Adding a new event (a VPN connecting, a build finishing, a download completing…) takes a few lines; YALW draws the card.
Two ways in, both end up on the same card:

```sh
yalw notify "Backup finished" "2.4 GB in 38 s" --icon circle-check             # from any script
yalw notify "Downloading" "ubuntu.iso" --icon download --progress 42 --key dl   # a ring; the same key updates the card

yalw extension new coffee      # writes ~/.local/share/yalw/extensions/coffee.py, a working template
yalw extension enable coffee   # or YALW Config → Extensions
yalw extensions                # what is installed and what runs
```

A Python extension defines `async def run(yalw)` and calls `yalw.notify(...)` when something happens. It can also keep a
**live widget** on screen with `yalw.live(key, ...)` (a processor load, a download, a timer) that stays until cleared.
The full guide is in [docs/EXTENSIONS.md](docs/EXTENSIONS.md); three examples are in `examples/extensions/`.

**Trust:** an extension is a Python program running with your permissions; it is not sandboxed. So YALW never enables an
extension by itself (copying a file into the folder does nothing), never runs code while looking for extensions, and runs
each in its own thread so that a stuck one cannot stop the rest. Only enable extensions you have read or trust.

## YALW Config

A small settings window (`yalw config`) with a **live preview card** on top: it draws the real cards with your settings
as they are right now. Every change is saved automatically after a short pause and applied to the running daemon.
Languages: Türkçe, English, Deutsch, Español, or automatic. The tabs: General (position on a mini screen, margin, monitor),
Appearance (compact mode, size, corners, accent colour from the cover or fixed, shadow, equalizer, reduced motion, font),
Events, Bluetooth, Extensions, Lyrics and Status (is it running, the song, which lyrics source answered, the log).

## Config file

`~/.config/yalw/config.toml` — every key is explained inside the file. Edit it by hand if you like, then `yalw reload`.
Invalid values fall back to the default; numbers out of range are clamped.

Example, no cards for browser tabs: `[media] ignore = ["firefox"]`

On Hyprland you can give layer rules to the `yalw` namespace, e.g. `layerrule = blur, yalw`.

## Notes

* The device type comes from BlueZ's `Icon` field (and the name); icons are [Lucide](https://lucide.dev) (ISC).
* BlueZ does not report a charging *state*; the ⚡ shows only when UPower says the device is charging.
* MPRIS has no previous/next distinction; the card's own buttons are exact, and for media keys YALW infers the direction
  from the song history and position.
* Covers are cached in `~/.cache/yalw/art` (64 MB at most). The player provides the cover address; YALW only downloads that.
* Tests: `QT_QPA_PLATFORM=offscreen python -m pytest` (280 tests).
* License: GPL-3.0-or-later (`LICENSE`). The bundled Lucide icons are ISC-licensed (`yalw/assets/lucide/LICENSE`).
