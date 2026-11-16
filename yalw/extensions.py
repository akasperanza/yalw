# SPDX-License-Identifier: GPL-3.0-or-later
"""Extensions: small Python programs that watch for something and ask YALW to show a card.

* **Discovery never runs code.** ``discover`` reads an extension's name and description from the source with
  ``ast``; the file is only imported when the user has enabled it (YALW Config → Extensions, or
  ``yalw extension enable``). YALW never enables an extension by itself.
* **Each running extension lives in its own thread with its own event loop.** If it blocks, crashes or hangs, the
  media watcher and every other extension carry on. A crash is logged and the extension is restarted a few times,
  then left stopped; YALW Config shows why.
* **An extension can only ask for cards** (``Api.notify``), which are sanitised (``notice.make``) and rate limited.
  It is not sandboxed otherwise: it is a program running with your permissions. Enable only what you trust.

``docs/EXTENSIONS.md`` is the guide for people writing them."""

import ast
import asyncio
import importlib
import importlib.util
import inspect
import logging
import re
import sys
import threading
import time
import tomllib
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import __version__, i18n, notice
from .config import Config, extension_settings_dir, extensions_dir, state_dir

log = logging.getLogger("yalw.ext")

API_VERSION = 1
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
META = ("NAME", "DESCRIPTION", "VERSION", "AUTHOR", "API")
MAX_SOURCE = 512 * 1024
MIN_GAP = 0.5                    # seconds between two cards from one extension; a newer one replaces a waiting one
MAX_PER_MINUTE = 12
LIVE_GAP = 0.25                  # seconds between two redraws of one live card: the newest value wins
LIVE_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,24}$")
MAX_LIVE = 4                     # live cards one extension may keep at once
RESTART_DELAYS = (2.0, 6.0, 20.0)
BUILTIN = ("power",)


@dataclass(frozen=True)
class Info:
    id: str
    name: str
    description: str
    version: str
    author: str
    api: int
    path: Path
    builtin: bool = False
    readable: bool = True            # False: the source could not even be parsed (it will fail when loaded, with its own message)

    @property
    def compatible(self) -> bool:
        return self.api == API_VERSION or not self.readable


# -- finding extensions (without running them) --------------------------------------------------

def _entry(path: Path) -> Path | None:
    if path.is_file() and path.suffix == ".py":
        return path
    if path.is_dir():
        for name in ("extension.py", "__init__.py"):
            if (path / name).is_file():
                return path / name
    return None


def _static_meta(entry: Path) -> dict | None:
    """NAME, DESCRIPTION ... from the source, as plain literals. Nothing is executed. None: not parseable."""
    try:
        if entry.stat().st_size > MAX_SOURCE:
            return {}                                   # parseable or not, we do not read a blob this size
        tree = ast.parse(entry.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError, UnicodeDecodeError):
        return None
    found: dict = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in META:
            try:
                found[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    return found


def _info(path: Path, entry: Path, builtin: bool = False) -> Info:
    meta = _static_meta(entry)
    readable = meta is not None
    meta = meta or {}
    text = lambda key, limit: str(meta.get(key, ""))[:limit] if isinstance(meta.get(key), (str, int, float)) else ""
    api = meta.get("API")
    ident = path.stem if path.is_file() else path.name
    return Info(id=ident, name=text("NAME", 60) or ident, description=text("DESCRIPTION", 200), version=text("VERSION", 20),
                author=text("AUTHOR", 60), api=api if isinstance(api, int) and not isinstance(api, bool) else 0, path=path, builtin=builtin,
                readable=readable)


def discover(root: Path | None = None) -> list[Info]:
    """The user's installed extensions: ``<root>/*.py`` and ``<root>/*/extension.py``. Never imports anything."""
    root = root or extensions_dir()
    try:
        children = sorted(root.iterdir())
    except OSError:
        return []
    found = []
    for path in children:
        stem = path.stem if path.is_file() else path.name
        entry = _entry(path)
        if entry is None or not ID_PATTERN.match(stem):
            continue
        found.append(_info(path, entry))
    return found


def builtin_info(ident: str) -> Info:
    path = Path(__file__).parent / "builtin" / f"{ident}.py"
    return _info(path, path, builtin=True)


# -- what an extension is handed ---------------------------------------------------------------------

class Api:
    """The ``yalw`` argument of an extension's ``async def run(yalw)``."""

    api_version = API_VERSION
    version = __version__

    def __init__(self, runner: "_Runner"):
        self._runner = runner
        self.id = runner.info.id
        self.name = runner.info.name
        self.language = runner.host.language
        self.settings = dict(runner.settings)
        self.log = logging.getLogger(f"yalw.ext.{self.id}")
        self._lock = threading.Lock()
        self._sent: deque[float] = deque()
        self._last = 0.0
        self._waiting: notice.Notice | None = None
        self._warned = 0.0
        self._live_keys: set[str] = set()
        self._live_last: dict[str, float] = {}
        self._live_waiting: dict[str, notice.Notice] = {}

    # -- cards -----------------------------------------------------------------------------

    def notify(self, title: str, subtitle: str = "", *, icon: str = "bell", accent: str | None = None, progress: float | None = None,
               value: str | None = None, badge: str | None = None, seconds: float | None = None, key: str | None = None) -> bool:
        """Show a card. Safe to call from any thread. False if it was refused (bad input, or too many cards)."""
        try:
            card = notice.make({"title": title, "subtitle": subtitle, "icon": icon, "accent": accent, "progress": progress,
                                "value": value, "badge": badge, "seconds": seconds, "key": key})
        except ValueError as exc:
            self.log.error("notify() refused: %s", exc)
            return False
        now = time.monotonic()
        with self._lock:
            while self._sent and now - self._sent[0] > 60:
                self._sent.popleft()
            if len(self._sent) >= MAX_PER_MINUTE:
                if now - self._warned > 60:
                    self._warned = now
                    self.log.warning("too many cards (limit %d a minute); dropping the rest", MAX_PER_MINUTE)
                return False
            self._sent.append(now)
            wait = self._last + MIN_GAP - now
            if wait > 0:                                   # too soon after the last one: the newest waits its turn
                first = self._waiting is None
                self._waiting = card
                if first:
                    timer = threading.Timer(wait, self._flush)
                    timer.daemon = True
                    timer.start()
                return True
            self._last = now
        self._runner.host.emit(card, self.id)
        return True

    def _flush(self) -> None:
        with self._lock:
            card, self._waiting = self._waiting, None
            self._last = time.monotonic()
        if card is not None:
            self._runner.host.emit(card, self.id)

    # -- live cards: they stay, and you keep redrawing them --------------------------------------

    def live(self, key: str, title: str = "", subtitle: str = "", *, icon: str = "bell", accent: str | None = None,
             progress: float | None = None, value: str | None = None, badge: str | None = None) -> bool:
        """Show (or redraw) a card that stays until ``clear(key)``, the user double-clicks it away or the extension stops.

        Call it as often as the value changes (a redraw is at most every 0.25 s; the newest value wins). Without a title
        and subtitle, a `progress` makes the lone ring. Safe from any thread. False if refused (bad input, too many)."""
        if not isinstance(key, str) or not LIVE_KEY.match(key):
            self.log.error("live() refused: the key %r must be 1-24 characters of letters, digits, . _ : -", key)
            return False
        full = f"{self.id}.{key}"
        try:
            card = notice.make({"title": title, "subtitle": subtitle, "icon": icon, "accent": accent, "progress": progress,
                                "value": value, "badge": badge, "key": full, "live": True})
        except ValueError as exc:
            self.log.error("live() refused: %s", exc)
            return False
        now = time.monotonic()
        with self._lock:
            if full not in self._live_keys and len(self._live_keys) >= MAX_LIVE:
                self.log.error("live() refused: at most %d live cards at once (clear one first)", MAX_LIVE)
                return False
            self._live_keys.add(full)
            wait = self._live_last.get(full, 0.0) + LIVE_GAP - now
            if wait > 0:
                first = full not in self._live_waiting
                self._live_waiting[full] = card
                if first:
                    timer = threading.Timer(wait, self._flush_live, args=(full,))
                    timer.daemon = True
                    timer.start()
                return True
            self._live_last[full] = now
        self._runner.host.emit(card, self.id)
        return True

    def _flush_live(self, full: str) -> None:
        with self._lock:
            card = self._live_waiting.pop(full, None)
            if card is None or full not in self._live_keys:           # cleared while it waited
                return
            self._live_last[full] = time.monotonic()
        self._runner.host.emit(card, self.id)

    def clear(self, key: str) -> None:
        """Take a live card away (nothing happens if there is none with that key)."""
        if not isinstance(key, str):
            return
        full = f"{self.id}.{key}"
        with self._lock:
            known = full in self._live_keys
            self._live_keys.discard(full)
            self._live_waiting.pop(full, None)
            self._live_last.pop(full, None)
        if known:
            self._runner.host.emit_clear(full, self.id)

    def close(self) -> None:
        """Called when the extension stops: whatever it left on screen goes."""
        with self._lock:
            keys, self._live_keys = list(self._live_keys), set()
            self._live_waiting.clear()
        for full in keys:
            self._runner.host.emit_clear(full, self.id)

    # -- helpers ------------------------------------------------------------------------------

    def tr(self, texts: dict[str, str]) -> str:
        """The text for the user's language: ``yalw.tr({"en": "Hello", "tr": "Merhaba"})``; English if there is no match."""
        return texts.get(self.language) or texts.get("en") or next(iter(texts.values()), "")

    @property
    def data_dir(self) -> Path:
        """A folder of your own to keep files in (created on first use)."""
        path = state_dir() / "ext" / self.id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def spawn(self, coro) -> asyncio.Task:
        """Run a coroutine alongside ``run``; it is cancelled when the extension stops."""
        return asyncio.get_running_loop().create_task(coro)

    async def system_bus(self):
        """A connected dbus-fast ``MessageBus`` on the system bus (UPower, NetworkManager, BlueZ ...), closed for you."""
        return await self._runner.connect("system")

    async def session_bus(self):
        """A connected dbus-fast ``MessageBus`` on the session bus, closed for you."""
        return await self._runner.connect("session")


# -- running them ---------------------------------------------------------------------------------------

class _Runner:
    """One extension: a thread, an event loop, a supervisor that restarts it if it crashes."""

    def __init__(self, info: Info, host: "ExtensionHost", settings: dict, module=None):
        self.info, self.host, self.settings, self.module = info, host, settings, module
        self.state = "starting"          # starting | running | crashed | failed | stopped
        self.error = ""
        self.loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._buses: list = []
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._main, name=f"yalw-ext-{info.id}", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        if self._ready.wait(timeout=1) and self.loop is not None and self._stop is not None:
            try:
                self.loop.call_soon_threadsafe(self._stop.set)
            except RuntimeError:
                pass                                   # the loop is already closed
        self._thread.join(timeout=2)

    async def connect(self, which: str):
        from dbus_fast import BusType
        from dbus_fast.aio import MessageBus

        bus = await MessageBus(bus_type=BusType.SYSTEM if which == "system" else BusType.SESSION).connect()
        self._buses.append(bus)
        return bus

    def _load(self):
        if self.module is not None:
            return self.module
        entry = _entry(self.info.path)
        name = f"yalw_ext_{self.info.id}"
        package = self.info.path.is_dir()
        spec = importlib.util.spec_from_file_location(name, entry, submodule_search_locations=[str(self.info.path)] if package else None)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    def _main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop, self._stop = loop, asyncio.Event()
        self._ready.set()
        try:
            loop.run_until_complete(self._supervise())
        except Exception:  # noqa: BLE001 - nothing an extension does may escape its thread
            log.exception("extension %s: supervisor failed", self.info.id)
        finally:
            self._cleanup(loop)

    def _cleanup(self, loop: asyncio.AbstractEventLoop) -> None:
        try:
            tasks = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for task in tasks:
                task.cancel()
            if tasks:
                loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            for bus in self._buses:
                try:
                    bus.disconnect()
                except Exception:  # noqa: BLE001
                    pass
        finally:
            loop.close()
            if self.state in ("starting", "running"):
                self.state = "stopped"

    async def _supervise(self) -> None:
        try:
            module = self._load()
        except BaseException as exc:  # noqa: BLE001 - includes SyntaxError and SystemExit from a careless module
            self._fail("failed", f"could not load: {type(exc).__name__}: {exc}", exc)
            return
        run = getattr(module, "run", None)
        if not inspect.iscoroutinefunction(run):
            self._fail("failed", "it must define `async def run(yalw)`")
            return

        crashes = 0
        while not self._stop.is_set():
            self.state, self.error = "running", ""
            api = Api(self)
            task = asyncio.ensure_future(run(api))
            stopper = asyncio.ensure_future(self._stop.wait())
            await asyncio.wait({task, stopper}, return_when=asyncio.FIRST_COMPLETED)
            stopper.cancel()
            if self._stop.is_set():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                api.close()
                return
            try:
                task.result()
            except asyncio.CancelledError:
                api.close()
                return
            except BaseException as exc:  # noqa: BLE001
                api.close()
                crashes += 1
                self.error = f"{type(exc).__name__}: {exc}"[:200]
                log.error("extension %s crashed (%d): %s", self.info.id, crashes, self.error, exc_info=exc)
                if crashes > len(RESTART_DELAYS):
                    self.state = "stopped"
                    self.error = f"crashed {crashes} times, last: {self.error}"
                    return
                self.state = "crashed"
                try:
                    await asyncio.wait_for(self._stop.wait(), RESTART_DELAYS[crashes - 1])
                except asyncio.TimeoutError:
                    pass
                continue
            await self._stop.wait()                       # `run` returned: it may have left tasks or callbacks behind
            return

    def _fail(self, state: str, message: str, exc: BaseException | None = None) -> None:
        self.state, self.error = state, message[:200]
        log.error("extension %s: %s", self.info.id, message, exc_info=exc)


class ExtensionHost:
    """Starts the built-in extensions that are wanted and the user's extensions that are enabled."""

    def __init__(self, cfg: Config, emit: Callable[[dict], None], root: Path | None = None):
        self.cfg, self._emit, self.root = cfg, emit, root
        self.language = i18n.resolve(cfg.language)
        self.runners: dict[str, _Runner] = {}

    def emit(self, card: notice.Notice, source: str) -> None:
        self._emit(card.payload(source))

    def emit_clear(self, key: str, source: str) -> None:
        self._emit({"clear": key, "source": source})

    def start(self) -> None:
        wanted = {"power": self.cfg.power_plugged or self.cfg.power_unplugged}
        for ident in BUILTIN:
            if wanted.get(ident):
                module = importlib.import_module(f"yalw.builtin.{ident}")
                settings = {"plugged": self.cfg.power_plugged, "unplugged": self.cfg.power_unplugged}
                self._run(builtin_info(ident), settings, module)
        enabled = set(self.cfg.extensions_enabled)
        for info in discover(self.root):
            if info.id not in enabled or info.id in self.runners:
                continue
            if not info.compatible:
                log.warning("extension %s needs API %s, this YALW offers %s: not started", info.id, info.api or "?", API_VERSION)
                continue
            self._run(info, load_settings(info.id))
        log.info("extensions running: %s", ", ".join(self.runners) or "none")

    def _run(self, info: Info, settings: dict, module=None) -> None:
        runner = self.runners[info.id] = _Runner(info, self, settings, module)
        runner.start()

    def stop(self) -> None:
        for runner in self.runners.values():
            runner.stop()

    def status(self) -> list[dict]:
        return [{"id": r.info.id, "name": r.info.name, "state": r.state, "error": r.error, "builtin": r.info.builtin}
                for r in self.runners.values()]


def load_settings(ident: str) -> dict:
    """``~/.config/yalw/extensions/<id>.toml``: the user's settings for one extension (empty if there are none)."""
    path = extension_settings_dir() / f"{ident}.toml"
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as exc:
        log.warning("ignoring unreadable settings %s: %s", path, exc)
        return {}
