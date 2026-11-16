# SPDX-License-Identifier: GPL-3.0-or-later
"""Talk to a running daemon over its ``io.github.yalw.Control`` D-Bus interface."""

import asyncio

from . import APP_ID

NOT_RUNNING = "not-running"
OUTDATED = "outdated"


async def _call(member: str, args: tuple[str, ...]) -> tuple[str, list]:
    from dbus_fast import BusType, Message, MessageType
    from dbus_fast.aio import MessageBus

    bus = await MessageBus(bus_type=BusType.SESSION).connect()
    try:
        reply = await bus.call(Message(
            destination=APP_ID, path="/" + APP_ID.replace(".", "/"), interface=APP_ID + ".Control",
            member=member, signature="s" * len(args), body=list(args)))
    finally:
        bus.disconnect()
    if reply.message_type != MessageType.ERROR:
        return "ok", list(reply.body)
    return (NOT_RUNNING if "ServiceUnknown" in (reply.error_name or "") else OUTDATED), []


def query(member: str, *args: str) -> tuple[str, list]:
    """(status, reply body). Status is "ok", ``NOT_RUNNING`` or ``OUTDATED`` (daemon predates this method)."""
    try:
        return asyncio.run(asyncio.wait_for(_call(member, args), timeout=3))
    except (OSError, asyncio.TimeoutError):
        return NOT_RUNNING, []


def send(member: str, *args: str) -> str:
    return query(member, *args)[0]
