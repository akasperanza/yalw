# SPDX-License-Identifier: GPL-3.0-or-later
"""One asyncio thread owning the session-bus connection for all D-Bus work."""

import asyncio
import logging
import threading
from collections.abc import Callable, Coroutine
from typing import Any

from dbus_fast import BusType, Message, MessageType
from dbus_fast.aio import MessageBus
from dbus_fast.constants import NameFlag, RequestNameReply
from dbus_fast.service import ServiceInterface, method

from . import APP_ID

log = logging.getLogger("yalw.runtime")

DBUS = "org.freedesktop.DBus"
OBJECT_PATH = "/" + APP_ID.replace(".", "/")


class Control(ServiceInterface):
    """``io.github.yalw.Control`` — lets the CLI poke a running daemon."""

    def __init__(self, on_demo: Callable[[str], None], on_quit: Callable[[], None],
                 on_quiet: Callable[[str], None], on_reload: Callable[[], None],
                 on_status: Callable[[], str] = lambda: "{}", on_notice: Callable[[str], str] = lambda text: ""):
        super().__init__(APP_ID + ".Control")
        self._on_demo = on_demo
        self._on_quit = on_quit
        self._on_quiet = on_quiet
        self._on_reload = on_reload
        self._on_status = on_status
        self._on_notice = on_notice

    @method()
    def Demo(self, kind: "s") -> None:  # noqa: F821 - D-Bus signature, not a type
        self._on_demo(kind)

    @method()
    def Quiet(self, mode: "s") -> None:  # noqa: F821 - "on" | "off" | "toggle"
        self._on_quiet(mode)

    @method()
    def Reload(self) -> None:
        self._on_reload()

    @method()
    def Status(self) -> "s":  # noqa: F821 - JSON for YALW Config
        return self._on_status()

    @method()
    def Notify(self, notice: "s") -> "s":  # noqa: F821 - JSON in (see yalw/notice.py); "" back if it was accepted, else why not
        return self._on_notice(notice)

    @method()
    def Quit(self) -> None:
        self._on_quit()


class Runtime:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.bus: MessageBus | None = None          # session bus: MPRIS, our own control interface
        self.system_bus: MessageBus | None = None   # system bus: BlueZ, UPower
        self._thread = threading.Thread(target=self._run, name="yalw-dbus", daemon=True)
        self._ready = threading.Event()
        self.primary = False

    def start(self, control: Control | None = None) -> bool:
        """Connect and claim our bus name. False if another instance owns it."""
        self._control = control
        self._thread.start()
        self._ready.wait(timeout=5)
        return self.primary

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._connect())
        except Exception:  # noqa: BLE001
            log.exception("could not reach the session bus")
        self._ready.set()
        if self.primary:
            self.loop.run_forever()

    async def _connect(self) -> None:
        self.bus = await MessageBus(bus_type=BusType.SESSION).connect()
        reply = await self.bus.request_name(APP_ID, NameFlag.DO_NOT_QUEUE)
        self.primary = reply in (RequestNameReply.PRIMARY_OWNER, RequestNameReply.ALREADY_OWNER)
        if self.primary and self._control is not None:
            self.bus.export(OBJECT_PATH, self._control)
        if self.primary:
            try:
                self.system_bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            except Exception as exc:  # noqa: BLE001 - Bluetooth is optional
                log.warning("system bus unavailable, Bluetooth cards disabled: %s", exc)

    def submit(self, coro: Coroutine[Any, Any, Any]):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def spawn(self, coro: Coroutine[Any, Any, Any]) -> None:
        """Start a task from inside the loop thread."""
        task = self.loop.create_task(coro)
        task.add_done_callback(_log_failure)

    def stop(self) -> None:
        """Cancel what is still running, then stop the loop (no "task was destroyed" noise in the log)."""
        if not self.loop.is_running():
            return

        def shutdown() -> None:
            for task in asyncio.all_tasks(self.loop):
                task.cancel()
            self.loop.call_soon(self.loop.stop)

        self.loop.call_soon_threadsafe(shutdown)


def _log_failure(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        log.error("background task failed", exc_info=task.exception())


async def call(bus: MessageBus, destination: str, path: str, interface: str, member: str,
               signature: str = "", body: list | None = None):
    """Raw method call; returns the reply body, or raises RuntimeError."""
    reply = await bus.call(Message(destination=destination, path=path, interface=interface,
                                   member=member, signature=signature, body=body or []))
    if reply.message_type == MessageType.ERROR:
        raise RuntimeError(f"{reply.error_name}: {reply.body[0] if reply.body else ''}")
    return reply.body


async def add_match(bus: MessageBus, rule: str) -> None:
    await call(bus, DBUS, "/org/freedesktop/DBus", DBUS, "AddMatch", "s", [rule])
