# SPDX-License-Identifier: GPL-3.0-or-later
"""Synced lyrics: find them, parse them, and work out where the choruses are.

Sources, in the order they are trusted:

``mpris``   lyrics the player itself publishes (``xesam:asText``)
``local``   a ``.lrc`` file next to the song, or in ``~/.cache/yalw/local``
``apple``   Apple Music lyrics, word-timed, through the community proxy lrc.red
``lrclib``  lrclib.net — open database of synced lyrics
``boidu``   lyrics-api.boidu.dev — second Apple Music proxy

Nothing here ships lyrics: they are fetched at run time, only while the lyrics
feature is switched on, and only the artist/title/album/length of the song that
is playing leave the machine.

A line is ``{"t", "e", "text", "words": [{"t", "text", "sp"}], "part"}``;
``words`` is empty for line-synced lyrics, ``part`` is the song section Apple
labels ("Chorus", "Verse", ...) or "".
"""

import difflib
import hashlib
import http.client
import json
import logging
import re
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import art
from .listener import section_db
from .config import cache_dir

log = logging.getLogger("yalw.lyrics")

USER_AGENT = "yalw/0.1 (synced lyrics lookup)"
APPLE_PROXY_HOSTS = ("lrc.red",)
NEGATIVE_TTL = 3 * 24 * 3600
CACHE_LIMIT = 24 * 1024 * 1024
MAX_BYTES = 1_500_000
LEAD = 0.8            # the card arrives this long before a chorus starts
LINGER = 1.4          # ...and stays this long after it ends
HEALTH: dict[str, dict] = {}      # per source: how its last answers went (shown in YALW Config)


def _note(name: str, ok: bool, error: str = "") -> None:
    h = HEALTH.setdefault(name, {"ok": 0, "fail": 0, "last": "", "error": "", "ts": 0.0})
    h["ok" if ok else "fail"] += 1
    h.update(last="ok" if ok else "fail", error=error, ts=time.time())


def health() -> dict[str, dict]:
    return {k: dict(v) for k, v in HEALTH.items()}


NETWORK_SOURCES = ("apple", "lrclib", "boidu")
ALL_SOURCES = ("local", *NETWORK_SOURCES)

# -- parsing -----------------------------------------------------------------

_STAMP = re.compile(r"\[(\d+):(\d+(?:[.:]\d+)?)\]")
_WORD_STAMP = re.compile(r"<(\d+):(\d+(?:[.:]\d+)?)>")
_OFFSET = re.compile(r"^\[offset:\s*([+-]?\d+)\s*\]", re.I | re.M)


def _lrc_secs(minutes: str, rest: str) -> float:
    return int(minutes) * 60 + float(rest.replace(":", "."))


def sung_seconds(text: str) -> float:
    """How long a line takes to sing, from its length (measured against Apple's real timings)."""
    return min(8.0, max(2.0, 0.075 * len(text) + 1.3))


def _finish(lines: list[dict]) -> list[dict]:
    """Sort and cap line ends at something a person could sing."""
    lines.sort(key=lambda l: l["t"])
    for line in lines:
        line["e"] = max(line["t"] + 0.5, min(line["e"], line["t"] + 12))
    return lines


def set_sections(lines: list[dict], starts: set[int]) -> None:
    """Number the song sections; ``starts`` are the indexes of lines that open a new one."""
    sec = 0
    for i, line in enumerate(lines):
        if i in starts and i > 0:
            sec += 1
        line["sec"] = sec


def apply_breaks(lines: list[dict], plain: str) -> bool:
    """Take section breaks from a plain-text version of the same lyrics (blank lines between stanzas).

    The plain text has no times, so its lines are matched to ``lines`` in order. Gives up
    (and changes nothing) when the two do not look like the same song."""
    entries, pending = [], False
    for row in plain.splitlines():
        if not row.strip():
            pending = True
        else:
            entries.append((_norm(row), pending))
            pending = False
    starts = {i for i in range(1, len(lines)) if lines[i].get("sec") != lines[i - 1].get("sec")}
    j = misses = 0
    for i, line in enumerate(lines):
        key = _norm(line["text"])
        for k in range(j, min(j + 3, len(entries))):
            if entries[k][0] == key or difflib.SequenceMatcher(None, entries[k][0], key).ratio() >= 0.85:
                if entries[k][1]:
                    starts.add(i)
                j = k + 1
                break
        else:
            misses += 1
    if misses > len(lines) * 0.25 or len(starts) < 2:
        return False
    set_sections(lines, starts)
    return True


def parse_lrc(text: str) -> list[dict]:
    """LRC, including the "enhanced" form with ``<mm:ss.xx>`` word stamps."""
    offset = int(m.group(1)) / 1000 if (m := _OFFSET.search(text)) else 0.0
    rows: list[tuple[float, str]] = []
    for row in text.splitlines():
        pos, stamps = 0, []
        while (m := _STAMP.match(row, pos)):
            stamps.append(_lrc_secs(m[1], m[2]))
            pos = m.end()
        rows += [(t - offset, row[pos:]) for t in stamps]
    rows.sort(key=lambda r: r[0])

    lines, sec, gap = [], 0, False
    for i, (t, body) in enumerate(rows):
        nxt = rows[i + 1][0] if i + 1 < len(rows) else t + 6
        plain = _WORD_STAMP.sub("", body).strip()
        if not plain:
            gap = bool(lines)                         # an empty row ends the line before it and starts a new section
            continue
        sec += gap
        gap = False
        words = _lrc_words(body, t) if _WORD_STAMP.search(body) else []
        lines.append({"t": t, "e": min(nxt, t + sung_seconds(plain)), "text": plain, "words": words, "part": "", "sec": sec})
    return _finish(lines)


def _lrc_words(body: str, line_t: float) -> list[dict]:
    pieces = re.split(r"(<\d+:\d+(?:[.:]\d+)?>)", body)
    words, t = [], line_t
    for piece in pieces:
        if m := _WORD_STAMP.fullmatch(piece):
            t = _lrc_secs(m[1], m[2])
        elif piece.strip():
            words.append({"t": t, "text": piece.strip(), "sp": piece != piece.rstrip()})
    if words:
        words[-1]["sp"] = False
    return words


def _ttml_time(value: str | None) -> float | None:
    """``27.395``, ``12.5s``, ``1:00.964`` or ``01:02:03.5`` → seconds."""
    if not value:
        return None
    try:
        total = 0.0
        for part in value.strip().removesuffix("s").split(":"):
            total = total * 60 + float(part)
        return total
    except ValueError:
        return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attr(element: ET.Element, name: str) -> str | None:
    for key, value in element.attrib.items():
        if _local(key) == name:
            return value
    return None


def parse_ttml(text: str) -> list[dict]:
    """Apple Music TTML: line or word timing, with the song-section label per line."""
    if re.search(r"<!(DOCTYPE|ENTITY)", text) or len(text) > MAX_BYTES:
        return []                                      # refuse entity tricks from the network
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []

    lines = []
    for sec, div in enumerate(e for e in root.iter() if _local(e.tag) == "div"):
        part = _attr(div, "songPart") or ""
        for p in (e for e in div if _local(e.tag) == "p"):
            t, e = _ttml_time(p.get("begin")), _ttml_time(p.get("end"))
            if t is None:
                continue
            words = []
            spans = [s for s in p if _local(s.tag) == "span" and _attr(s, "role") != "x-bg"]   # skip backing vocals
            for span in spans:
                wt = _ttml_time(span.get("begin"))
                word = "".join(span.itertext()).strip()
                if wt is not None and word:
                    words.append({"t": wt, "text": word, "sp": bool(span.tail and span.tail[:1].isspace())})
            if words:
                words[-1]["sp"] = False
                plain = " ".join(w["text"] if w["sp"] or i == len(words) - 1 else w["text"] + "\0"
                                 for i, w in enumerate(words)).replace("\0 ", "")
            else:
                plain = " ".join("".join(p.itertext()).split())
            if plain:
                lines.append({"t": t, "e": e if e is not None else t + 4, "text": plain, "words": words, "part": part, "sec": sec})
    return _finish(lines)


def parse_lyricsfile(text: str) -> list[dict]:
    """LRCLIB's ``lyricsfile`` (YAML, may carry word timing). Needs PyYAML; skipped without it."""
    try:
        import yaml
        data = yaml.safe_load(text)
    except Exception:  # noqa: BLE001 - optional dependency, hostile input
        return []
    lines = []
    for row in (data or {}).get("lines") or []:
        try:
            t, e, plain = row["start_ms"] / 1000, row["end_ms"] / 1000, str(row["text"]).strip()
            words = [{"t": w["start_ms"] / 1000, "text": str(w["text"]).strip(), "sp": True}
                     for w in row.get("words") or [] if str(w.get("text", "")).strip()]
        except (KeyError, TypeError):
            continue
        if words:
            words[-1]["sp"] = False
        if plain:
            lines.append({"t": t, "e": e, "text": plain, "words": words, "part": "", "sec": 0})
    return _finish(lines)


def _result(lines: list[dict], source: str) -> dict | None:
    if len(lines) < 3:
        return None
    return {"source": source, "synced": "word" if any(l["words"] for l in lines) else "line", "lines": lines}


# -- where are the choruses? ----------------------------------------------------

def _norm(text: str) -> str:
    return re.sub(r"[^\w]+", "", text.lower())


def _similar(a: str, b: str, threshold: float = 0.82) -> bool:
    if a == b:
        return True
    return min(len(a), len(b)) >= 6 and difflib.SequenceMatcher(None, a, b).ratio() >= threshold


def _runs(indexes: list[int]) -> list[tuple[int, int]]:
    runs: list[list[int]] = []
    for i in indexes:
        if runs and i == runs[-1][1] + 1:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    return [(a, b) for a, b in runs]


def _is_chorus(part: str) -> bool:
    """"Chorus" yes; "PreChorus" and "PostChorus" no."""
    p = part.lower()
    return p.startswith("chorus") or p in ("hook", "refrain")


def _spans(lines: list[dict], runs: list[tuple[int, int]]) -> list[tuple[float, float]]:
    spans: list[list[float]] = []
    for a, b in runs:
        start, end = max(0.0, lines[a]["t"] - LEAD), lines[b]["e"] + LINGER
        if b + 1 < len(lines):
            end = max(lines[b]["e"], min(end, lines[b + 1]["t"] - 0.15))      # linger only over silence, never into the next verse
        if spans and start - spans[-1][1] < 2.5:
            spans[-1][1] = max(spans[-1][1], end)
        else:
            spans.append([start, end])
    return [(a, b) for a, b in spans]


def _sections(lines: list[dict]) -> list[list[int]]:
    out: list[list[int]] = []
    for i, line in enumerate(lines):
        if out and lines[out[-1][-1]].get("sec") == line.get("sec"):
            out[-1].append(i)
        else:
            out.append([i])
    return out


def _section_runs(lines: list[dict], title: str, loudness: list | None = None) -> list[tuple[int, int]] | None:
    """Chorus = the section that comes back most often. Ties go to the loudest one when we have heard
    the song (see ``listener``), else to the one naming the song, then the longer.

    Needs real section boundaries; None if the lyrics do not have them."""
    secs = _sections(lines)
    if len(secs) < 3 or max(len(s) for s in secs) > 0.6 * len(lines):
        return None
    keys = [[_norm(lines[i]["text"]) for i in s] for s in secs]

    def alike(x: int, y: int) -> bool:
        a = sum(1 for k in keys[x] if any(_similar(k, o) for o in keys[y])) / len(keys[x])
        b = sum(1 for o in keys[y] if any(_similar(o, k) for k in keys[x])) / len(keys[y])
        return min(a, b) >= 0.5

    family = list(range(len(secs)))

    def root(x: int) -> int:
        while family[x] != x:
            family[x] = family[family[x]]
            x = family[x]
        return x

    for x in range(len(secs)):
        for y in range(x + 1, len(secs)):
            if alike(x, y):
                family[root(x)] = root(y)
    groups: dict[int, list[int]] = {}
    for x in range(len(secs)):
        groups.setdefault(root(x), []).append(x)

    name = _norm(title)

    def score(members: list[int]) -> tuple:
        named = sum(1 for m in members for k in keys[m] if len(name) >= 4 and name in k)
        return (len(members), named, sum(len(secs[m]) for m in members) / len(members))

    repeated = [m for m in groups.values() if len(m) >= 2]
    if not repeated:
        return []
    if loudness:
        most = max(len(m) for m in repeated)
        tied = [m for m in repeated if len(m) == most]

        def loud(members: list[int]) -> float | None:
            heard = [section_db(loudness, lines[secs[m][0]]["t"], lines[secs[m][-1]]["e"]) for m in members]
            heard = [h for h in heard if h is not None]
            return sum(heard) / len(heard) if heard else None

        levels = {id(m): loud(m) for m in tied}
        if len(tied) > 1 and all(v is not None for v in levels.values()):
            return [(secs[m][0], secs[m][-1]) for m in sorted(max(tied, key=lambda m: levels[id(m)]))]
    return [(secs[m][0], secs[m][-1]) for m in sorted(max(repeated, key=score))]


def _repeated_runs(lines: list[dict], loudness: list | None = None) -> list[tuple[int, int]]:
    """No section boundaries to go on: runs of lines that come back later in the song.

    Several different passages may repeat; if two of them repeat equally often the louder one is the
    chorus (when we have heard the song), and only that one is kept."""
    counts: dict[str, int] = {}
    for line in lines:
        counts[_norm(line["text"])] = counts.get(_norm(line["text"]), 0) + 1
    repeated = [i for i, l in enumerate(lines) if len(_norm(l["text"])) >= 8 and counts[_norm(l["text"])] >= 2]
    runs = [r for r in _runs(repeated) if r[1] > r[0]]
    if not loudness or len(runs) < 3:
        return runs

    keys = [{_norm(lines[i]["text"]) for i in range(a, b + 1)} for a, b in runs]
    family = list(range(len(runs)))

    def root(x: int) -> int:
        while family[x] != x:
            family[x] = family[family[x]]
            x = family[x]
        return x

    for x in range(len(runs)):
        for y in range(x + 1, len(runs)):
            if len(keys[x] & keys[y]) >= 0.5 * min(len(keys[x]), len(keys[y])):
                family[root(x)] = root(y)
    groups: dict[int, list[int]] = {}
    for x in range(len(runs)):
        groups.setdefault(root(x), []).append(x)

    most = max(len(g) for g in groups.values())
    tied = [g for g in groups.values() if len(g) == most]
    if len(tied) < 2:
        return runs

    def loud(group: list[int]) -> float | None:
        heard = [section_db(loudness, lines[runs[i][0]]["t"], lines[runs[i][1]]["e"]) for i in group]
        heard = [h for h in heard if h is not None]
        return sum(heard) / len(heard) if heard else None

    levels = [loud(g) for g in tied]
    if any(v is None for v in levels):
        return runs
    return [runs[i] for i in sorted(tied[levels.index(max(levels))])]


def chorus_windows(lines: list[dict], title: str = "", loudness: list | None = None) -> tuple[list[tuple[float, float]], str]:
    """(time spans of the chorus, how they were found: "labels" | "sections" | "runs").

    Best evidence first: Apple's own "Chorus" labels, then whole sections that repeat (the loudest
    wins a tie), then plain repetition of lines (the least reliable)."""
    if not lines:
        return [], "runs"
    labelled = [i for i, l in enumerate(lines) if _is_chorus(l.get("part", ""))]
    if labelled:
        return _spans(lines, _runs(labelled)), "labels"
    runs = _section_runs(lines, title, loudness)
    if runs is None:
        return _spans(lines, _repeated_runs(lines, loudness)), "runs"
    return _spans(lines, runs), "sections"


def windows(lines: list[dict], when: str = "chorus", title: str = "", loudness: list | None = None) -> list[tuple[float, float]]:
    """Time spans (seconds) during which the lyrics card should be up."""
    if not lines:
        return []
    if when == "always":
        return [(max(0.0, lines[0]["t"] - 1.5), lines[-1]["e"] + LINGER)]
    return chorus_windows(lines, title, loudness)[0]


# -- title hygiene ------------------------------------------------------------------

_NOISE = r"remaster(?:ed)?|live|official|audio|video|music video|lyric|lyrics|visuali[sz]er|version|edit|radio edit|mono|stereo|explicit|clean|deluxe|\d{4}"
_BRACKETS = re.compile(rf"\s*[\(\[][^)\]]*\b(?:{_NOISE}|feat\.?|ft\.?|featuring|with)\b[^)\]]*[\)\]]", re.I)
_DASH_TAIL = re.compile(rf"\s+[-–—]\s+(?:{_NOISE})\b.*$", re.I)
_QUALIFIERS = ("live", "remix", "acoustic", "instrumental", "karaoke", "cover")


def clean_title(title: str) -> str:
    out = _DASH_TAIL.sub("", _BRACKETS.sub("", title)).strip()
    return out or title.strip()


def clean_artist(artist: str) -> str:
    return re.split(r",|&| feat\.?| ft\.?| featuring | x ", artist, maxsplit=1, flags=re.I)[0].strip()


def _qualifier_penalty(wanted: str, candidate: str) -> int:
    w, c = wanted.lower(), candidate.lower()
    return sum(30 for q in _QUALIFIERS if (q in w) != (q in c))


_HARMLESS_TAG = re.compile(r"^(?:feat|ft|featuring|with|remaster|mono|stereo|explicit|clean|deluxe|official|original|\d{4})")


def _tags(title: str) -> set[str]:
    """Qualifiers in brackets or after a dash: "(English)", "[Live]", "- Acoustic"."""
    found = {_norm(m) for m in re.findall(r"[(\[]([^)\]]+)[)\]]", title)}
    if m := re.search(r"\s[-–—]\s(.+)$", title):
        found.add(_norm(m.group(1)))
    return {t for t in found if t and not _HARMLESS_TAG.match(t)}


def same_song(meta: dict, cand_title: str, cand_artist: str) -> bool:
    """Is a catalogue entry this song, and not a translation, live take, remix or namesake?

    The search services happily return other versions (and other artists' songs with the same
    name); showing their words under the wrong song is far worse than showing nothing."""
    if _tags(cand_title) - _tags(meta["title"]):
        return False                                           # "Name (English)" is not "Name"
    if not _similar(_norm(clean_title(cand_title)), _norm(clean_title(meta["title"])), 0.8):
        return False
    wanted, got = _norm(clean_artist(meta["artist"])), _norm(clean_artist(cand_artist or ""))
    return not (wanted and got) or wanted in got or got in wanted


# -- network -----------------------------------------------------------------------

HTTP_TIMEOUT = 20          # a slow link (weak Wi-Fi, a DPI-bypass tool in the way) can need 10 s for the handshake alone
POOL_IDLE = 25.0           # a kept-alive connection older than this is not trusted any more
_pool = threading.local()


def _connection(netloc: str, timeout: float, fresh: bool) -> list:
    """[connection, time of last use (0 = never used)] for this thread and host. One TLS handshake serves
    every request a lookup makes to the same server (a handshake can take seconds on a bad link)."""
    conns = _pool.__dict__.setdefault("conns", {})
    entry = conns.get(netloc)
    if entry is not None and (fresh or time.monotonic() - entry[1] > POOL_IDLE):
        entry[0].close()
        entry = None
    if entry is None:
        entry = conns[netloc] = [http.client.HTTPSConnection(netloc, timeout=timeout), 0.0]
    return entry


def _http(url: str, params: dict | None = None, timeout: float = HTTP_TIMEOUT, _hops: int = 0) -> str | None:
    """Body as text; None for 4xx (not found); OSError for network trouble and 5xx."""
    if params:
        url += "?" + urllib.parse.urlencode(params)
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        return None
    path = (parts.path or "/") + (("?" + parts.query) if parts.query else "")
    for attempt in (0, 1):
        entry = _connection(parts.netloc, timeout, fresh=attempt == 1)
        reused = entry[1] > 0
        try:
            entry[0].request("GET", path, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
            response = entry[0].getresponse()
            data = response.read(MAX_BYTES + 1)
        except (http.client.HTTPException, OSError) as exc:
            entry[0].close()
            _pool.conns.pop(parts.netloc, None)
            stale = isinstance(exc, (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError))
            if attempt == 0 and reused and stale:          # the server closed an idle connection: once more, on a fresh one
                continue
            raise OSError(str(exc) or type(exc).__name__) from exc
        entry[1] = time.monotonic()
        if len(data) > MAX_BYTES or (response.getheader("Connection") or "").lower() == "close":
            entry[0].close()
            _pool.conns.pop(parts.netloc, None)
        status = response.status
        if status in (301, 302, 303, 307, 308) and _hops < 3 and response.getheader("Location"):
            return _http(urllib.parse.urljoin(url, response.getheader("Location")), None, timeout, _hops + 1)
        if 400 <= status < 500:
            return None
        if status >= 300:
            raise OSError(f"HTTP {status}")
        return data.decode("utf-8", "replace") if len(data) <= MAX_BYTES else None
    return None


def _json(url: str, params: dict | None = None):
    body = _http(url, params)
    try:
        return json.loads(body) if body else None
    except ValueError:
        return None


def _plausible(lines: list[dict], length: float) -> bool:
    """Reject lyrics that clearly belong to a different version of the song."""
    return bool(lines) and (length <= 0 or lines[-1]["t"] <= length + 8)


def _apple_queries(title: str, artist: str) -> list[str]:
    """What to ask lrc.red, in turn. Its search is strict: for some songs "title artist" finds nothing while
    the artist alone, or the title alone, lists the very same song. So when the full question misses, ask less."""
    first = title.split()[0] if len(title.split()) > 1 else ""
    return list(dict.fromkeys(q for q in (f"{title} {artist}".strip(), artist, title, first if len(first) >= 4 else "") if q))


def fetch_apple(meta: dict) -> dict | None:
    title, artist = clean_title(meta["title"]), clean_artist(meta["artist"])
    length = meta["length"]

    def acceptable(rows: list[dict]) -> list[dict]:
        rows = [r for r in rows if r.get("lyricsUrl") and same_song(meta, r.get("track_name", ""), r.get("artist_name", ""))]
        if length:
            rows = [r for r in rows if not r.get("duration") or abs(float(r["duration"]) - length) <= 15]
        return rows

    candidates: list[dict] = []
    for query in _apple_queries(title, artist):
        candidates = acceptable((_json("https://lrc.red/api/v1", {"q": query}) or {}).get("results", []))
        if candidates:
            break

    def score(r: dict) -> float:
        s = 15 if r.get("timing_type") == "word" else 0
        if (a := _norm(artist)) and (c := _norm(r.get("artist_name", ""))) and (a in c or c in a):
            s += 20
        if length and r.get("duration"):
            s -= abs(float(r["duration"]) - length) * 2
        if (a := _norm(meta["album"])) and (c := _norm(r.get("album_name", ""))) and (a in c or c in a):
            s += 10                                            # same album: very likely the same recording
        return s - _qualifier_penalty(meta["title"], r.get("track_name", ""))

    for r in sorted(candidates, key=score, reverse=True)[:3]:
        url = r["lyricsUrl"]
        if urllib.parse.urlparse(url).hostname not in APPLE_PROXY_HOSTS:
            continue
        lines = parse_ttml(_http(url) or "")
        if _plausible(lines, length) and (res := _result(lines, "Apple Music")):
            res["genuine_word"] = r.get("timing_type") == "word"     # else the proxy guessed the word times
            res["match"] = f'{r.get("artist_name")} — {r.get("track_name")} ({r.get("duration")}s)'
            return res
    return None


def fetch_boidu(meta: dict) -> dict | None:
    params = {"s": clean_title(meta["title"]), "a": clean_artist(meta["artist"])}
    if meta["album"]:
        params["al"] = meta["album"]
    if meta["length"]:
        params["d"] = round(meta["length"])
    data = _json("https://lyrics-api.boidu.dev/getLyrics", params)
    lines = parse_ttml((data or {}).get("ttml", "")) if isinstance(data, dict) else []
    return _result(lines, "boidu") if _plausible(lines, meta["length"]) else None


def fetch_lrclib(meta: dict) -> dict | None:
    title, artist, length = clean_title(meta["title"]), clean_artist(meta["artist"]), meta["length"]
    base = "https://lrclib.net/api"
    params = {"track_name": title, "artist_name": artist}
    if meta["album"]:
        params["album_name"] = meta["album"]
    if length:
        params["duration"] = round(length)
    item = _json(f"{base}/get", params) if length else None
    if item and not same_song(meta, item.get("trackName", ""), item.get("artistName", "")):
        item = None
    if not item or not item.get("syncedLyrics"):
        found = _json(f"{base}/search", {"track_name": title, "artist_name": artist}) or []
        found = [r for r in found if r.get("syncedLyrics") and same_song(meta, r.get("trackName", ""), r.get("artistName", ""))
                 and (not length or abs((r.get("duration") or 0) - length) <= 8)]
        item = min(found, key=lambda r: abs((r.get("duration") or 0) - length)) if found else None
    if not item:
        return None
    lines = parse_lyricsfile(item["lyricsfile"]) if item.get("hasWordSync") and item.get("lyricsfile") else []
    lines = lines or parse_lrc(item["syncedLyrics"])
    if item.get("plainLyrics"):
        apply_breaks(lines, item["plainLyrics"])        # the plain text separates stanzas; the synced text barely does
    res = _result(lines, "LRCLIB") if _plausible(lines, length) else None
    if res:
        res["match"] = f'{item.get("artistName")} — {item.get("trackName")} ({item.get("duration")}s)'
    return res


def fetch_local(meta: dict) -> dict | None:
    safe = lambda s: re.sub(r"[\\/\0]", "_", s)
    spots = []
    if meta.get("url", "").startswith("file://"):
        spots.append(Path(urllib.parse.unquote(urllib.parse.urlparse(meta["url"]).path)).with_suffix(".lrc"))
    for folder in (cache_dir() / "local", Path.home() / ".lyrics"):
        spots += [folder / f"{safe(meta['artist'])} - {safe(meta['title'])}.lrc", folder / f"{safe(meta['title'])}.lrc"]
    for spot in spots:
        try:
            if spot.is_file() and spot.stat().st_size < MAX_BYTES:
                if res := _result(parse_lrc(spot.read_text(errors="replace")), "local file"):
                    return res
        except OSError:
            continue
    return None


FETCHERS = {"apple": fetch_apple, "lrclib": fetch_lrclib, "boidu": fetch_boidu}

# -- choosing ------------------------------------------------------------------------

def rank(result: dict) -> int:
    """Lower is better: real word timing beats guessed word timing beats line timing."""
    src, word = result["source"], result["synced"] == "word"
    if word:
        return 0 if src == "Apple Music" and result.get("genuine_word") else 1 if src == "LRCLIB" else 2 if src != "Apple Music" else 3
    return {"Apple Music": 4, "LRCLIB": 5}.get(src, 6)


def _chorus_spans(best: dict, results: list[dict], title: str) -> tuple[list[list[float]], str]:
    """Chorus windows for ``best`` and how they were found. If another source labelled the sections,
    its labels win: it is the same recording, so the times line up even when the lines came from elsewhere."""
    for other in sorted(results, key=rank):
        if any(_is_chorus(l.get("part", "")) for l in other["lines"]):
            return [list(w) for w in windows(other["lines"], "chorus", title)], "labels"
    spans, basis = chorus_windows(best["lines"], title)
    return [list(w) for w in spans], basis


def _cache_file(meta: dict, sources: tuple[str, ...]) -> Path:
    key = "|".join(("v5", meta["artist"], meta["title"], meta["album"], str(round(meta["length"])), ",".join(sorted(sources))))
    return cache_dir() / "lyrics" / (hashlib.sha1(key.encode()).hexdigest() + ".json")


def cached(meta: dict, sources: tuple[str, ...]) -> dict | None:
    """The lyrics ``find`` stored for this song, if any. Reads the cache only: no network, no waiting."""
    net = tuple(s for s in NETWORK_SOURCES if s in sources)
    if not net or not meta.get("title"):
        return None
    try:
        data = json.loads(_cache_file({"album": "", "length": 0.0, **meta}, net).read_text())
    except (OSError, ValueError):
        return None
    result = data.get("result") if isinstance(data, dict) else None
    return result if isinstance(result, dict) and result.get("lines") else None


def find(meta: dict, sources: tuple[str, ...]) -> dict | None:
    """Best lyrics for ``meta`` ({artist, title, album, length, url, mpris}) or None. Blocking."""
    return search(meta, sources)[0]


def search(meta: dict, sources: tuple[str, ...]) -> tuple[dict | None, list[str]]:
    """(best lyrics or None, the sources that could not be reached). A miss with unreachable sources is not a
    real "no": the caller may try again later."""
    if not meta.get("title"):
        return None, []
    meta = {"album": "", "length": 0.0, "url": "", "mpris": "", **meta}

    if meta["mpris"] and (res := _result(parse_lrc(meta["mpris"]), "player")):
        return res, []
    if "local" in sources and (res := fetch_local(meta)):
        return res, []

    net = tuple(s for s in NETWORK_SOURCES if s in sources)
    if not net:
        return None, []
    cache = _cache_file(meta, net)
    try:
        cached = json.loads(cache.read_text())
        if cached.get("result") or time.time() - cached.get("ts", 0) < NEGATIVE_TTL:
            return cached.get("result"), []
    except (OSError, ValueError):
        pass

    results, unreachable = [], []

    def run(name: str):
        try:
            outcome = FETCHERS[name](meta)
            _note(name, True)
            return outcome
        except OSError as exc:
            log.info("%s unreachable: %s", name, exc)
            _note(name, False, str(exc)[:80])
            return "failed"
        except Exception:  # noqa: BLE001 - one bad provider must not hide the others
            log.exception("%s failed", name)
            _note(name, False, "internal error")
            return "failed"

    with ThreadPoolExecutor(max_workers=len(net)) as pool:
        for name, outcome in zip(net, pool.map(run, net)):
            if outcome == "failed":
                unreachable.append(name)
            elif outcome:
                results.append(outcome)
    failed = bool(unreachable)

    best = min(results, key=rank) if results else None
    if best:
        best["chorus"], best["chorus_basis"] = _chorus_spans(best, results, meta["title"])
    # A miss is only remembered when every source answered; a result that is merely the best of
    # what answered (a better source timed out) is shown but not kept, so the next play retries.
    complete = not failed or (best is not None and rank(best) == 0)
    if complete:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"ts": time.time(), "result": best}))
            art.prune(cache.parent, CACHE_LIMIT)
        except OSError:
            pass
    return best, unreachable
