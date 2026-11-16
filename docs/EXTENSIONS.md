# Writing YALW extensions

YALW shows small cards when something happens: a new song, a Bluetooth device, a charger being plugged in.
Extensions let **you** teach it new "somethings": a VPN connecting, a build finishing, a download completing,
the washing machine's smart plug going quiet. You decide *when*; YALW draws the card.

There are two ways in, and they end up on the same card:

| | for | needs |
|---|---|---|
| **`yalw notify`** | a shell script, a cron job, a udev rule, anything that can run a command | nothing |
| **a Python extension** | something to *watch*: a D-Bus signal, a file, a socket, a timer | a small `.py` file |

## 1. The quickest way: `yalw notify`

```sh
yalw notify "Backup finished" "2.4 GB in 38 s" --icon circle-check --accent '#3ddc97'
yalw notify "Downloading" "ubuntu.iso" --icon download --progress 42 --key dl      # a ring at 42 %
yalw notify "Downloading" "ubuntu.iso" --icon download --progress 71 --key dl      # same key: updates the card
```

Put it at the end of a script (`make && yalw notify "Build ok" --icon circle-check`), in a systemd unit's
`ExecStopPost=`, in a udev `RUN+=`. Scripts that are not on the same user session can call the D-Bus method
directly: `io.github.yalw.Control.Notify(s json) -> s` (the string it returns is empty when the card was accepted,
otherwise it says why not).

## 2. A Python extension

```sh
yalw extension new coffee       # writes ~/.local/share/yalw/extensions/coffee.py, a working template
yalw extension enable coffee    # or: YALW Config -> Extensions -> switch it on
```

An extension is one file (`coffee.py`) or a folder with an `extension.py` in it (so it can have helper modules).
It looks like this:

```python
NAME = "Coffee"                     # shown in YALW Config
DESCRIPTION = "Reminds you to get up."
VERSION = "1.0"
AUTHOR = "you"
API = 1                             # the extension API this was written for

import asyncio

async def run(yalw):
    minutes = float(yalw.settings.get("minutes", 50))
    while True:
        await asyncio.sleep(minutes * 60)
        yalw.notify(yalw.tr({"en": "Time for a break", "tr": "Mola zamanı"}), icon="coffee", accent="#c98b4a")
```

`NAME`, `DESCRIPTION`, `VERSION`, `AUTHOR` and `API` must be plain literals. YALW reads them from the source
*without running your code*, so YALW Config can list your extension before anyone has enabled it.

`run` is called once, when YALW starts (or reloads) with your extension enabled. Keep it running for as long as
you want to watch; when it returns, the extension just idles. If it raises, it is restarted (after 2, 6 and 20
seconds) and then left stopped; the reason is shown in YALW Config.

### What `yalw` gives you

| | |
|---|---|
| `yalw.notify(title, subtitle="", *, icon, accent, progress, value, badge, seconds, key)` | show a card; returns `False` if it was refused. Safe from any thread |
| `yalw.live(key, title="", subtitle="", *, icon, accent, progress, value, badge)` | a **live widget**: a card that stays and that you keep redrawing (see below) |
| `yalw.clear(key)` | take a live card away |
| `yalw.tr({"en": ..., "tr": ...})` | the text for the user's language (English if yours is missing) |
| `yalw.language` | `"en"`, `"tr"`, `"de"` or `"es"` |
| `yalw.settings` | a dict from `~/.config/yalw/extensions/<id>.toml` (empty if the file does not exist) |
| `yalw.data_dir` | a folder of your own to keep files in |
| `await yalw.system_bus()` / `await yalw.session_bus()` | a connected [dbus-fast](https://github.com/Bluetooth-Devices/dbus-fast) `MessageBus`, closed for you |
| `yalw.spawn(coro)` | run a coroutine next to `run` |
| `yalw.log` | a `logging.Logger`; its lines land in YALW's log (YALW Config -> Status shows it) |
| `yalw.id`, `yalw.name`, `yalw.version`, `yalw.api_version` | what it says |

### The card

| field | |
|---|---|
| `live` | (`notify` of a script only; extensions use `yalw.live`) the card stays until cleared |
| `title` | up to 48 characters; required unless there is a `progress` (a ring and an icon alone make a small wordless card, like the charger one) |
| `subtitle` | up to 80 characters |
| `icon` | one of the [Lucide](https://lucide.dev) icons that ship with YALW (`yalw/assets/lucide/*.svg`, 178 of them); anything else becomes `bell` |
| `accent` | `"#rrggbb"`; empty uses the user's small-card colour |
| `progress` | `0..1`; draws a ring (battery, volume, a download...) |
| `value` | up to 4 characters inside the ring; defaults to the progress in percent |
| `badge` | a small icon on the ring, e.g. `"zap"` for charging |
| `seconds` | how long it stays, 1-30; default is the user's setting |
| `key` | a card with the same key *updates* the one on screen quietly instead of replaying the animation |

Everything is cut to size and cleaned of control characters; nothing is interpreted as markup.

### Live widgets

`notify` is for something that *happened*: the card comes, stays a few seconds and goes. A live widget is for something
that *is*: a processor load, a download, a timer. It stays until you clear it, and every call with the same key
redraws it in place:

```python
async def run(yalw):
    while True:
        yalw.live("cpu", icon="cpu", progress=read_load())      # no title: just the ring
        await asyncio.sleep(2)
```

* Two looks, the same as `notify`: **a lone ring** (give a `progress`, no `title` and no `subtitle`: a transparent ring
  with the icon and the number inside) or **the full card** (icon, title, subtitle, and a ring if there is a `progress`).
* The card appears where the user put the cards, and a redraw changes the ring and the words without replaying the animation.
* It does not close by itself: neither the card time nor the "nothing moved for 4 seconds" rule apply to it. It goes when
  you call `yalw.clear(key)`, when the extension stops or crashes, when the user turns Quiet mode on (it comes back when
  it ends), or when the user **double-clicks** it. A dismissed live card stays away, however often you redraw it, until
  you `clear` it and start it again.
* Only one card is on the screen. A news card, a song or a Bluetooth device takes the screen for its time and the live card
  comes back afterwards. If two live cards exist, the one started first keeps the screen and the other waits.
* Redraws are thinned to one every 0.25 s (the newest value wins), they do not count towards the 12 cards a minute, and
  an extension may keep at most **4** live cards (keys of 1-24 letters, digits and `. _ : -`).

From a script: `yalw notify "" --progress 40 --key build --live`, then again with a new value, and
`yalw notify --clear build` when it is done.

### Limits, so one extension cannot spoil the desktop

* at most **12 cards a minute** per extension (more are dropped, with a warning in the log);
* two cards less than half a second apart: the newer one waits its turn, a still newer one replaces it;
* the user's *Quiet* mode silences extension cards too.

### Your extension runs in its own thread

with its own event loop. If it blocks (`time.sleep`, a slow `requests.get`) only it suffers: media, Bluetooth
and the other extensions carry on. Still, prefer `asyncio`. Use only the standard library and what YALW itself
needs (`dbus-fast`); do not import Qt.

## Trust

An extension is a Python program running **with your user's permissions**. It is not sandboxed. That is why:

* YALW never enables an extension by itself; copying a file into the folder does nothing until the user turns
  it on;
* discovery never executes code (it reads the metadata with `ast`);
* the Extensions page of YALW Config says so, plainly.

Only enable extensions you have read or got from someone you trust. If you share yours, keep it short enough to read.

## Built in: Power

The "charger plugged in" card is an extension too (`yalw/builtin/power.py`). It uses exactly this API, so it is a
good example of how to read a system service (UPower) and wait for a signal to settle.

## Examples

`examples/extensions/` has three you can copy: `network.py` (a card when you connect to Wi-Fi, a cable or a VPN),
`low_battery.py` (a warning once per discharge, with a setting) and `cpu_load.py` (a live ring with the processor load).

## Compatibility

`API = 1` is the contract in this document. Additions will keep it; a change that could break an extension will
bump the number, and YALW will say "needs another YALW version" next to extensions it cannot run instead of
running them wrongly.

## Trying things out

```sh
yalw demo notice            # a sample card
yalw demo charger           # the charger card
yalw extensions             # what is installed, what runs
tail -f ~/.local/state/yalw/yalw.log
```
