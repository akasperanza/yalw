"""A live widget: a ring in the corner that shows the processor load and keeps itself up to date.

It stays until you double-click it away (it then stays away until YALW restarts the extension) or switch the
extension off. Settings (optional): ~/.config/yalw/extensions/cpu_load.toml
    interval = 1        # seconds between two readings"""

import asyncio

NAME = "CPU load"
DESCRIPTION = "A ring that shows how busy the processor is, live."
VERSION = "1.0"
AUTHOR = "YALW"
API = 1


def read_cpu() -> tuple[int, int]:
    """(busy, total) jiffies since boot, from the first line of /proc/stat."""
    with open("/proc/stat") as handle:
        fields = [int(n) for n in handle.readline().split()[1:]]
    idle = fields[3] + fields[4]
    return sum(fields) - idle, sum(fields)


async def run(yalw):
    interval = max(0.5, float(yalw.settings.get("interval", 1)))
    busy, total = read_cpu()
    while True:
        await asyncio.sleep(interval)
        now_busy, now_total = read_cpu()
        load = (now_busy - busy) / max(1, now_total - total)
        busy, total = now_busy, now_total
        accent = "#ff5d6c" if load > 0.85 else "#ffb347" if load > 0.6 else "#3ddc97"
        yalw.live("cpu", icon="cpu", progress=load, accent=accent)       # no title: the lone ring
