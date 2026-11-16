from types import SimpleNamespace
from pathlib import Path
# SPDX-License-Identifier: GPL-3.0-or-later
"""Lyrics tests. Every text below is invented for the tests."""

import time

import pytest

from yalw import lyrics as L

SONG = "\n".join([
    "[offset:0]", "[ti:Invented]",
    "[00:04.00]alpha bravo charlie delta", "[00:08.00]echo foxtrot golf hotel", "",
    "[00:12.00]sing the refrain again now", "[00:15.00]we repeat the refrain line", "[00:18.00]",
    "[00:22.00]india juliet kilo lima", "[00:26.00]mike november oscar papa", "",
    "[00:30.00]sing the refrain again now", "[00:33.00]we repeat the refrain line", "[00:36.00]",
])

ENHANCED = "[00:04.00]<00:04.00>one <00:04.50>two <00:05.20>thr<00:05.60>ee\n[00:08.00]plain line\n[00:11.00]last one here\n"

TTML = """<tt xmlns="http://www.w3.org/ns/ttml" xmlns:itunes="http://music.apple.com/lyric-ttml-internal" xmlns:ttm="http://www.w3.org/ns/ttml#metadata" itunes:timing="Word">
<body><div itunes:songPart="Verse">
<p begin="4.0" end="7.0"><span begin="4.0" end="5.0">red</span> <span begin="5.0" end="6.0">green</span> <span begin="6.0" end="7.0">blue</span></p>
<p begin="7.0" end="10.0"><span begin="7.0" end="8.0">alpha</span> <span begin="8.0" end="9.0">beta</span><span begin="9.0" end="10.0" ttm:role="x-bg">(backing)</span></p>
</div><div itunes:songPart="PreChorus"><p begin="10.0" end="12.0">just a line</p></div>
<div itunes:songPart="Chorus"><p begin="1:00.5" end="1:03.0"><span begin="1:00.5" end="1:01.0">up</span> <span begin="1:01.0" end="1:03.0">high</span></p>
<p begin="1:03.0" end="1:06.0">second chorus line</p></div></body></tt>"""


def test_lrc_basic():
    lines = L.parse_lrc(SONG)
    assert [l["t"] for l in lines][:3] == [4.0, 8.0, 12.0]
    assert lines[0]["text"] == "alpha bravo charlie delta" and lines[0]["words"] == []
    assert lines[1]["e"] == 12.0 or lines[1]["e"] <= 12.0          # an empty row ends the line it follows


def test_lrc_offset_shifts_every_line():
    shifted = L.parse_lrc("[offset:1000]\n[00:10.00]a\n[00:20.00]b\n[00:30.00]c\n")
    assert [l["t"] for l in shifted] == [9.0, 19.0, 29.0]


def test_lrc_multiple_stamps_on_one_row():
    lines = L.parse_lrc("[00:05.00][00:25.00]again\n[00:10.00]x\n[00:15.00]y\n")
    assert [l["t"] for l in lines if l["text"] == "again"] == [5.0, 25.0]


def test_enhanced_lrc_gives_word_timing():
    lines = L.parse_lrc(ENHANCED)
    assert [w["text"] for w in lines[0]["words"]] == ["one", "two", "thr", "ee"]
    assert [w["sp"] for w in lines[0]["words"]] == [True, True, False, False]   # "thr"+"ee" is one word
    assert lines[0]["words"][2]["t"] == 5.2 and lines[1]["words"] == []
    assert L._result(lines, "x")["synced"] == "word"


def test_ttml_words_parts_and_backing_vocals_skipped():
    lines = L.parse_ttml(TTML)
    assert [l["text"] for l in lines][:2] == ["red green blue", "alpha beta"]
    assert lines[0]["words"][1] == {"t": 5.0, "text": "green", "sp": True}
    assert [l["part"] for l in lines] == ["Verse", "Verse", "PreChorus", "Chorus", "Chorus"]
    assert lines[3]["t"] == 60.5 and lines[3]["e"] == 63.0               # m:ss.fff times


def test_ttml_refuses_entity_tricks():
    assert L.parse_ttml('<!DOCTYPE tt [<!ENTITY a "aaaa">]><tt><body><div><p begin="1" end="2">&a;</p></div></body></tt>') == []
    assert L.parse_ttml("not xml at all") == []


def test_chorus_comes_from_labels_and_prechorus_does_not_count():
    lines = L.parse_ttml(TTML)
    (start, end), = L.windows(lines, "chorus")
    assert start == pytest.approx(60.5 - L.LEAD) and end == pytest.approx(66.0 + L.LINGER)


def test_chorus_is_guessed_from_repetition_without_labels():
    spans = L.windows(L.parse_lrc(SONG), "chorus")
    assert len(spans) == 2
    assert spans[0][0] == pytest.approx(12.0 - L.LEAD) and spans[1][0] == pytest.approx(30.0 - L.LEAD)


def test_one_repeated_line_is_not_a_chorus():
    lines = L.parse_lrc("[00:05.00]a long unique line one\n[00:10.00]this one comes back\n[00:15.00]another unique line two\n[00:20.00]this one comes back\n[00:25.00]closing words here\n")
    assert L.windows(lines, "chorus") == []


def test_always_covers_the_whole_song():
    lines = L.parse_lrc(SONG)
    (start, end), = L.windows(lines, "always")
    assert start < lines[0]["t"] and end > lines[-1]["e"]


def test_title_and_artist_cleaning():
    assert L.clean_title("Name - Remastered 2011") == "Name"
    assert L.clean_title("Name (feat. Someone) [Live]") == "Name"
    assert L.clean_title("Name (Part 2)") == "Name (Part 2)"
    assert L.clean_artist("Lead, Guest & Other") == "Lead"


def test_wrong_version_is_rejected_by_length():
    lines = L.parse_lrc(SONG)
    assert L._plausible(lines, 40.0) and not L._plausible(lines, 20.0) and L._plausible(lines, 0)


@pytest.mark.parametrize("src,synced,genuine,order", [("Apple Music", "word", True, 0), ("LRCLIB", "word", None, 1),
                                                       ("boidu", "word", None, 2), ("Apple Music", "line", None, 4), ("LRCLIB", "line", None, 5)])
def test_ranking_prefers_real_word_timing(src, synced, genuine, order):
    assert L.rank({"source": src, "synced": synced, "genuine_word": genuine}) == order


# -- choosing between sources ---------------------------------------------------

@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return tmp_path


META = {"title": "Invented", "artist": "Nobody", "album": "", "length": 40.0}


def fake(source, synced, genuine=None, calls=None):
    lines = L.parse_lrc(SONG)

    def fn(meta):
        if calls is not None:
            calls.append(source)
        return {"source": source, "synced": synced, "lines": lines, **({"genuine_word": genuine} if genuine is not None else {})}
    return fn


def test_best_source_wins_and_result_is_cached(isolated, monkeypatch):
    calls = []
    monkeypatch.setattr(L, "FETCHERS", {"apple": fake("Apple Music", "word", True, calls), "lrclib": fake("LRCLIB", "line", None, calls),
                                        "boidu": fake("boidu", "word", None, calls)})
    assert L.find(META, ("apple", "lrclib", "boidu"))["source"] == "Apple Music"
    assert sorted(calls) == ["Apple Music", "LRCLIB", "boidu"]
    calls.clear()
    assert L.find(META, ("apple", "lrclib", "boidu"))["source"] == "Apple Music" and calls == []   # cached


def test_one_failing_source_does_not_hide_the_others(isolated, monkeypatch):
    def boom(meta):
        raise RuntimeError("provider bug")
    monkeypatch.setattr(L, "FETCHERS", {"apple": boom, "lrclib": fake("LRCLIB", "line"), "boidu": lambda m: (_ for _ in ()).throw(OSError("down"))})
    assert L.find(META, ("apple", "lrclib", "boidu"))["source"] == "LRCLIB"


def test_nothing_is_remembered_after_a_network_error(isolated, monkeypatch):
    state = {"up": False}

    def flaky(meta):
        if not state["up"]:
            raise OSError("offline")
        return fake("LRCLIB", "line")(meta)
    monkeypatch.setattr(L, "FETCHERS", {"lrclib": flaky})
    assert L.find(META, ("lrclib",)) is None
    state["up"] = True
    assert L.find(META, ("lrclib",))["source"] == "LRCLIB"           # would be None if the failure had been cached


def test_a_genuine_miss_is_remembered(isolated, monkeypatch):
    calls = []
    monkeypatch.setattr(L, "FETCHERS", {"lrclib": lambda m: calls.append(1)})
    assert L.find(META, ("lrclib",)) is None and L.find(META, ("lrclib",)) is None
    assert len(calls) == 1


def test_local_file_beats_the_network(isolated, monkeypatch):
    folder = isolated / "cache" / "yalw" / "local"
    folder.mkdir(parents=True)
    (folder / "Nobody - Invented.lrc").write_text(SONG)
    monkeypatch.setattr(L, "FETCHERS", {"apple": lambda m: pytest.fail("network used")})
    assert L.find(META, ("local", "apple"))["source"] == "local file"


def test_lyrics_published_by_the_player_win(isolated, monkeypatch):
    monkeypatch.setattr(L, "FETCHERS", {"apple": lambda m: pytest.fail("network used")})
    assert L.find({**META, "mpris": SONG}, ("apple",))["source"] == "player"


def test_no_sources_means_no_lookup(isolated):
    assert L.find(META, ()) is None


def test_only_the_proxy_host_is_followed():
    assert "lrc.red" in L.APPLE_PROXY_HOSTS and "example.com" not in L.APPLE_PROXY_HOSTS


# -- the scheduler ---------------------------------------------------------------

@pytest.fixture
def controller(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    from yalw import config
    from yalw.controller import Controller
    from yalw.runtime import Runtime
    from yalw.surface import Surface

    QGuiApplication.instance() or QGuiApplication([])
    cfg = config.from_values({**config.to_values(config.Config()), "lyrics_enabled": True, "lyrics_guess": True})
    ctl = Controller(cfg, Surface(cfg, "xcb"), Runtime(), "xcb")
    ctl.events = []
    ctl.lyricsStart.connect(lambda: ctl.events.append("start"))
    ctl.lyricsEnd.connect(lambda: ctl.events.append("end"))
    return ctl


def play(ctl, position, playing=True):
    ctl._media = {**ctl._media, "title": "Invented", "artist": "Nobody", "playing": playing, "length": 40.0,
                  "position": position, "stamp": time.time() * 1000}


def load(ctl):
    ctl._on_lyrics({"key": ["Invented", "Nobody"], "result": L._result(L.parse_lrc(SONG), "test")})


def test_card_waits_for_the_chorus_then_leaves(controller):
    play(controller, 2.0)
    load(controller)
    assert controller.events == [] and controller._lyr_timer.isActive()        # armed for the first chorus
    assert 8000 < controller._lyr_timer.remainingTime() <= 9200                # ~ (12 - 0.8) - 2 seconds
    play(controller, 13.0)
    controller._schedule_lyrics()
    assert controller.events == ["start"]
    play(controller, 25.0)                                                      # between the choruses
    controller._schedule_lyrics()
    assert controller.events == ["start", "end"]


def test_pausing_hides_the_card(controller):
    play(controller, 13.0)
    load(controller)
    assert controller.events == ["start"]
    play(controller, 13.0, playing=False)
    controller._schedule_lyrics()
    assert controller.events == ["start", "end"]


def test_seeking_into_a_chorus_shows_it_immediately(controller):
    play(controller, 5.0)
    load(controller)
    play(controller, 31.0)
    controller._schedule_lyrics()
    assert controller.events == ["start"]


def test_lyrics_for_another_song_are_dropped(controller):
    play(controller, 13.0)
    controller._on_lyrics({"key": ["Something Else", "Nobody"], "result": L._result(L.parse_lrc(SONG), "test")})
    assert controller._lyrics is None and controller.events == []


def test_switched_off_means_never(controller):
    from yalw import config
    controller.cfg = config.from_values({**config.to_values(controller.cfg), "lyrics_enabled": False})
    play(controller, 13.0)
    load(controller)
    assert controller.events == [] and controller.lyric_sources() == ()


def test_sources_follow_the_toggles(controller):
    from yalw import config
    controller.cfg = config.from_values({**config.to_values(controller.cfg), "lyrics_apple": False, "lyrics_boidu": False})
    assert controller.lyric_sources() == ("local", "lrclib")


def test_new_song_clears_the_old_words(controller):
    play(controller, 13.0)
    load(controller)
    controller._on_media({"kind": "next", "title": "Different", "artist": "Nobody", "playing": True, "length": 30.0,
                          "position": 0.0, "stamp": time.time() * 1000})
    assert controller._lyrics is None and controller.events == ["start", "end"]


# -- sections and chorus detection (invented song: verse / pre-chorus / chorus / verse / pre-chorus / chorus / chorus) --

def _song(blocks, per_line=3.0):
    """Lines from blocks of text; every block is its own section."""
    lines, t = [], 4.0
    for sec, block in enumerate(blocks):
        for text in block:
            lines.append({"t": t, "e": t + per_line, "text": text, "words": [], "part": "", "sec": sec})
            t += per_line
        t += 1.5
    return lines


VERSE_A = ["walking down the quiet avenue", "every window holds a story", "counting all the lights tonight", "nothing here is ordinary"]
VERSE_B = ["morning breaks across the harbour", "ships are leaving one by one", "somewhere someone starts to wonder", "where the long night will have gone"]
PRE = ["and it builds and it builds", "can you feel it rising now"]
CHORUS = ["oh we sing it loud and clear", "never letting go tonight", "oh we sing it loud and clear", "everything will be alright"]


def test_section_approach_picks_the_chorus_and_not_the_pre_chorus():
    lines = _song([VERSE_A, PRE, CHORUS, VERSE_B, PRE, CHORUS, CHORUS])
    spans = L.windows(lines, "chorus")
    starts = [lines[i]["t"] for i in range(len(lines)) if lines[i]["sec"] in (2, 5, 6) and (i == 0 or lines[i - 1]["sec"] != lines[i]["sec"])]
    assert len(spans) == 2 and spans[0][0] == pytest.approx(starts[0] - L.LEAD)        # sec 5 and 6 touch -> one window
    assert spans[0][1] < lines[[l["sec"] for l in lines].index(3)]["t"]                 # ...and it ends before the next verse


def test_without_section_info_the_pre_chorus_gets_glued_on():
    """The weakness the section approach fixes: repeated runs cannot tell where a chorus starts."""
    lines = _song([VERSE_A, PRE, CHORUS, VERSE_B, PRE, CHORUS, CHORUS])
    blind = [{k: v for k, v in l.items() if k != "sec"} for l in lines]
    with_sections = L.windows(lines, "chorus")
    assert L.windows(blind, "chorus")[0][0] < with_sections[0][0]


def test_song_title_breaks_a_tie_between_equally_repeated_sections():
    named = ["we are the champions of the night", "and nothing here will ever end"]
    other = ["tall buildings in the evening air", "a different thing is said here"]
    lines = _song([VERSE_A, other, named, VERSE_B, other, named])
    (a, _), = L.windows(lines, "chorus", title="Champions Of The Night")[:1]
    first_named = next(l["t"] for l in lines if "champions" in l["text"])
    assert a == pytest.approx(first_named - L.LEAD)


def test_lrc_empty_rows_become_section_breaks():
    lines = L.parse_lrc("[00:05.00]first line of one\n[00:08.00]second line of one\n[00:11.00]\n[00:14.00]first line of two\n[00:17.00]second line of two\n")
    assert [l["sec"] for l in lines] == [0, 0, 1, 1]


def test_line_ends_are_estimated_not_stretched_to_the_next_line():
    lines = L.parse_lrc("[00:05.00]short\n[01:05.00]a line that follows a long instrumental break\n[01:10.00]end\n[01:15.00]end two\n")
    assert lines[0]["e"] - lines[0]["t"] < 4.0                              # not 60 seconds of "still singing"


def test_plain_text_gives_the_synced_lines_their_sections():
    synced = L.parse_lrc("\n".join(f"[00:{5 + 3 * i:02d}.00]line number {chr(97 + i)} here" for i in range(8)))
    plain = "line number a here\nline number b here\n\nline number c here\nline number d here\nline number e here\n\nline number f here\nline number g here\nline number h here"
    assert L.apply_breaks(synced, plain)
    assert [l["sec"] for l in synced] == [0, 0, 1, 1, 1, 2, 2, 2]


def test_plain_text_of_a_different_song_is_ignored():
    synced = L.parse_lrc("\n".join(f"[00:{5 + 3 * i:02d}.00]line number {chr(97 + i)} here" for i in range(8)))
    before = [l["sec"] for l in synced]
    assert not L.apply_breaks(synced, "completely\n\nunrelated words\n\nabout something else\n\nentirely different")
    assert [l["sec"] for l in synced] == before


def test_labels_from_another_source_are_borrowed():
    labelled = {"source": "boidu", "synced": "line", "lines": [{**l, "part": "Chorus" if l["sec"] == 2 else "Verse"} for l in _song([VERSE_A, PRE, CHORUS, VERSE_B])]}
    bare = {"source": "LRCLIB", "synced": "line", "lines": _song([VERSE_A, PRE, CHORUS, VERSE_B])}
    spans, basis = L._chorus_spans(bare, [bare, labelled], "x")
    assert spans == [list(w) for w in L.windows(labelled["lines"], "chorus")] and len(spans) == 1 and basis == "labels"


def test_a_result_from_incomplete_answers_is_not_remembered(isolated, monkeypatch):
    calls = []

    def down(meta):
        raise OSError("timed out")

    def line_synced(meta):
        calls.append(1)
        return {"source": "LRCLIB", "synced": "line", "lines": L.parse_lrc(SONG)}
    monkeypatch.setattr(L, "FETCHERS", {"apple": down, "lrclib": line_synced})
    assert L.find(META, ("apple", "lrclib"))["source"] == "LRCLIB"
    assert L.find(META, ("apple", "lrclib"))["source"] == "LRCLIB"
    assert len(calls) == 2                                                    # asked again: Apple might answer this time


def test_find_stores_the_chorus_windows_with_the_result(isolated, monkeypatch):
    monkeypatch.setattr(L, "FETCHERS", {"lrclib": lambda m: {"source": "LRCLIB", "synced": "line", "lines": L.parse_lrc(SONG)}})
    assert L.find(META, ("lrclib",))["chorus"]


# -- keeping the playback position honest ---------------------------------------------

def test_position_is_re_read_while_lyrics_are_on():
    import asyncio

    from yalw import media

    seen = []
    w = media.MediaWatcher.__new__(media.MediaWatcher)
    p = media.Player(name="org.mpris.MediaPlayer2.t", status="Playing")
    w.players, w.current, w._schedule = {p.name: p}, p, seen.append

    async def run():
        task = asyncio.create_task(w._resync())
        await asyncio.sleep(0.35)
        p.status = "Paused"                                                    # a paused song needs no re-sync
        count = len(seen)
        await asyncio.sleep(0.25)
        task.cancel()
        return count, len(seen)

    old, media.RESYNC = media.RESYNC, 0.1
    try:
        before, after = asyncio.run(run())
    finally:
        media.RESYNC = old
    assert before >= 2 and after == before


# -- the wrong-version bug: "Name (English)" was picked for "Name" because its length was closest ---

@pytest.mark.parametrize("cand_title,cand_artist,ok", [
    ("Invented", "Nobody", True),
    ("Invented (English)", "Nobody", False),                     # a translation / alternate-language version
    ("Invented (Live)", "Nobody", False),
    ("Invented - Acoustic", "Nobody", False),
    ("Invented [Remix]", "Nobody", False),
    ("Invented (Remastered 2011)", "Nobody", True),              # harmless
    ("Invented (feat. Someone)", "Nobody", True),
    ("Invented", "Somebody Else", False),                         # a namesake by another artist
    ("Something Unrelated", "Nobody", False),
    ("INVENTED", "nobody", True),
])
def test_same_song_guard(cand_title, cand_artist, ok):
    assert L.same_song({"title": "Invented", "artist": "Nobody"}, cand_title, cand_artist) is ok


def test_a_tag_the_song_itself_has_is_fine():
    assert L.same_song({"title": "Invented (English)", "artist": "Nobody"}, "Invented (English)", "Nobody")


def test_apple_never_picks_the_translated_version_even_when_its_length_fits_best(monkeypatch):
    results = [{"artist_name": "Nobody", "track_name": "Invented (English)", "duration": 225, "timing_type": "line", "lyricsUrl": "https://lrc.red/english"},
               {"artist_name": "Nobody", "track_name": "Invented", "duration": 230, "timing_type": "line", "lyricsUrl": "https://lrc.red/original"},
               {"artist_name": "Other Band", "track_name": "Invented", "duration": 221, "timing_type": "word", "lyricsUrl": "https://lrc.red/namesake"}]
    fetched = []
    monkeypatch.setattr(L, "_json", lambda url, params=None: {"results": results})
    monkeypatch.setattr(L, "_http", lambda url, params=None, timeout=7: fetched.append(url) or TTML_FOR_TESTS)
    res = L.fetch_apple({"title": "Invented", "artist": "Nobody", "album": "", "length": 222.0})
    assert fetched == ["https://lrc.red/original"] and "Nobody — Invented (230s)" in res["match"]


def test_apple_asks_less_when_the_full_question_finds_nothing(monkeypatch):
    """lrc.red's search is strict: "title artist" can miss a song that "artist" alone lists."""
    asked = []
    row = {"artist_name": "Nobody", "track_name": "Invented Song Title", "duration": 222, "timing_type": "line", "lyricsUrl": "https://lrc.red/it"}

    def search(url, params=None):
        asked.append(params["q"])
        return {"results": [row] if params["q"] == "Nobody" else []}
    monkeypatch.setattr(L, "_json", search)
    monkeypatch.setattr(L, "_http", lambda url, params=None, timeout=7: TTML_FOR_TESTS)
    res = L.fetch_apple({"title": "Invented Song Title", "artist": "Nobody", "album": "", "length": 222.0})
    assert asked == ["Invented Song Title Nobody", "Nobody"] and "Invented Song Title" in res["match"]


def test_apple_stops_asking_once_something_fits_and_keeps_the_wrong_song_out(monkeypatch):
    asked = []
    wrong = {"artist_name": "Nobody", "track_name": "A Different Song", "duration": 222, "timing_type": "line", "lyricsUrl": "https://lrc.red/x"}

    def search(url, params=None):
        asked.append(params["q"])
        return {"results": [wrong]}
    monkeypatch.setattr(L, "_json", search)
    monkeypatch.setattr(L, "_http", lambda url, params=None, timeout=7: TTML_FOR_TESTS)
    assert L.fetch_apple({"title": "Invented Song Title", "artist": "Nobody", "album": "", "length": 222.0}) is None
    assert asked == ["Invented Song Title Nobody", "Nobody", "Invented Song Title", "Invented"]   # every question, none of them right


def test_the_questions_asked_of_apple():
    assert L._apple_queries("Darıldım Ben Sana", "Muhlis Akarsu") == ["Darıldım Ben Sana Muhlis Akarsu", "Muhlis Akarsu", "Darıldım Ben Sana", "Darıldım"]
    assert L._apple_queries("Telefon", "Ati242") == ["Telefon Ati242", "Ati242", "Telefon"]
    assert L._apple_queries("Aman", "") == ["Aman"]


def test_lrclib_search_skips_other_versions_and_artists(monkeypatch):
    synced = "\n".join(f"[00:{5 + 3 * i:02d}.00]some invented line number {i} here" for i in range(6))
    found = [{"artistName": "Nobody", "trackName": "Invented (English)", "duration": 221, "syncedLyrics": synced},
             {"artistName": "Other Band", "trackName": "Invented", "duration": 222, "syncedLyrics": synced},
             {"artistName": "Nobody", "trackName": "Invented", "duration": 224, "syncedLyrics": synced}]
    monkeypatch.setattr(L, "_json", lambda url, params=None: found if url.endswith("/search") else None)
    res = L.fetch_lrclib({"title": "Invented", "artist": "Nobody", "album": "", "length": 222.0})
    assert res["match"] == "Nobody — Invented (224s)"


def test_when_only_the_wrong_version_exists_nothing_is_shown(monkeypatch):
    only = [{"artist_name": "Nobody", "track_name": "Invented (English)", "duration": 222, "timing_type": "line", "lyricsUrl": "https://lrc.red/english"}]
    monkeypatch.setattr(L, "_json", lambda url, params=None: {"results": only})
    monkeypatch.setattr(L, "_http", lambda *a, **k: pytest.fail("fetched lyrics of the wrong version"))
    assert L.fetch_apple({"title": "Invented", "artist": "Nobody", "album": "", "length": 222.0}) is None


TTML_FOR_TESTS = ('<tt xmlns="http://www.w3.org/ns/ttml"><body>' + "<div>" + "".join(
    f'<p begin="{5 + 3 * i}.0" end="{7 + 3 * i}.0">invented text number {i} here</p>' for i in range(8)) + "</div></body></tt>")


# -- the card's action bar: per-song timing, hiding wrong lyrics, status -----------------

@pytest.fixture
def song(controller, tmp_path):
    """A controller with lyrics loaded for one song, and a private preferences file."""
    from yalw import prefs
    controller._prefs = prefs.SongPrefs(tmp_path / "songs.json")
    play(controller, 2.0)
    controller._song = controller._prefs.get(controller._song_key())
    load(controller)
    return controller


def test_nudging_moves_every_time_and_the_chorus_windows(song):
    before = [l["t"] for l in song._lyrics["lines"]]
    first_window = song._lyr_windows[0][0]
    song.nudgeLyrics(1.5)
    assert song.lyricsOffset == 1.5
    assert [l["t"] for l in song._lyrics["lines"]] == pytest.approx([t + 1.5 for t in before])
    assert song._lyr_windows[0][0] == pytest.approx(first_window + 1.5)
    assert song._lyrics_raw["lines"][0]["t"] == before[0]                       # the original is never overwritten


def test_nudging_also_moves_word_times():
    from yalw.controller import Controller
    lines = L.parse_lrc(ENHANCED)
    fake = type("C", (), {"_song": {"offset": 2.0}})()
    shifted = Controller._shifted(fake, {"lines": lines, "chorus": [[1.0, 5.0]]})
    assert shifted["lines"][0]["words"][1]["t"] == pytest.approx(lines[0]["words"][1]["t"] + 2.0)
    assert shifted["chorus"] == [[3.0, 7.0]]


def test_the_offset_is_remembered_across_runs(song, tmp_path):
    from yalw import prefs
    song.nudgeLyrics(-1.0)
    again = prefs.SongPrefs(tmp_path / "songs.json")
    assert again.get(song._song_key())["offset"] == -1.0
    song.nudgeLyrics(1.0)                                                       # back to zero: nothing left to remember
    assert again.__class__(tmp_path / "songs.json").get(song._song_key()) == {}


def test_the_offset_is_limited(song):
    song.nudgeLyrics(100)
    assert song.lyricsOffset == 15.0


def test_hiding_the_lyrics_of_one_song_stops_the_card_and_can_be_undone(song):
    play(song, 13.0)
    song._schedule_lyrics()
    assert song.events == ["start"]
    song.toggleSongLyrics()
    assert song.lyricsHidden and song.events == ["start", "end"]
    song._schedule_lyrics()
    assert song.events == ["start", "end"]                                      # still hidden
    song.toggleSongLyrics()
    assert not song.lyricsHidden and song.events[-1] == "start"


def test_a_hidden_song_stays_hidden_after_a_restart(song, tmp_path):
    from yalw import prefs
    song.toggleSongLyrics()
    assert prefs.SongPrefs(tmp_path / "songs.json").get(song._song_key())["hidden"] is True


def test_choices_belong_to_a_song_not_to_the_player(song):
    song.toggleSongLyrics()
    song._on_media({"kind": "next", "title": "Different", "artist": "Nobody", "playing": True, "length": 30.0, "position": 0.0, "stamp": time.time() * 1000})
    assert not song.lyricsHidden and song.lyricsOffset == 0.0


def test_silence_turns_cards_off(song):
    song.silence()
    assert song.quietOn


def test_status_is_plain_json_for_the_config_window(song):
    import json
    st = song.status()
    json.dumps(st)                                                              # must survive the trip over D-Bus
    assert st["lyrics"]["found"] and st["lyrics"]["source"] == "test" and st["song"]["title"] == "Invented"
    assert st["lyrics"]["sources"] == list(song.lyric_sources())


def test_source_health_records_answers_and_failures(isolated, monkeypatch):
    L.HEALTH.clear()

    def down(meta):
        raise OSError("timed out")
    monkeypatch.setattr(L, "FETCHERS", {"apple": down, "lrclib": lambda m: None})
    L.find(META, ("apple", "lrclib"))
    h = L.health()
    assert h["apple"]["last"] == "fail" and "timed out" in h["apple"]["error"]
    assert h["lrclib"]["last"] == "ok"


def test_prefs_file_survives_garbage(tmp_path):
    from yalw import prefs
    bad = tmp_path / "songs.json"
    bad.write_text("{not json")
    assert prefs.SongPrefs(bad).get("anything") == {}


def test_control_query_reports_a_missing_daemon(monkeypatch):
    from yalw import control
    monkeypatch.setattr(control, "_call", lambda member, args: (_ for _ in ()).throw(OSError("no bus")))
    assert control.query("Status") == (control.NOT_RUNNING, [])


# -- "found it, but behaves as if it had not" -------------------------------------------------------------

def test_lyrics_that_arrive_before_the_song_is_known_are_kept_not_dropped(controller):
    """After a restart the cached lyrics come back faster than the first media update. They used to be thrown away."""
    result = L._result(L.parse_lrc(SONG), "test")
    controller._on_lyrics({"key": ["Invented", "Nobody"], "result": result})        # the controller has heard of no song yet
    assert controller._lyrics is None and controller._pending is not None
    controller._on_media({"kind": "", "title": "Invented", "artist": "Nobody", "playing": True, "length": 40.0,
                          "position": 2.0, "stamp": time.time() * 1000})
    assert controller._lyrics is not None and controller._pending is None


def test_pending_lyrics_for_another_song_are_not_applied(controller):
    controller._on_lyrics({"key": ["Something Else", "Nobody"], "result": L._result(L.parse_lrc(SONG), "test")})
    controller._on_media({"kind": "", "title": "Invented", "artist": "Nobody", "playing": True, "length": 40.0,
                          "position": 2.0, "stamp": time.time() * 1000})
    assert controller._lyrics is None


def _no_repeats():
    return L._result(L.parse_lrc("\n".join(f"[00:{4 + 4 * i:02d}.00]an entirely different invented line number {i} here" for i in range(10))), "test")


def _guessing(controller, on):
    from yalw import config
    controller.cfg = config.from_values({**config.to_values(controller.cfg), "lyrics_guess": on})


def _labelled():
    lines = L.parse_ttml(TTML)
    spans, basis = L.chorus_windows(lines, "Invented")
    return {**L._result(lines, "test"), "chorus": [list(w) for w in spans], "chorus_basis": basis}


def test_without_a_chorus_label_the_whole_song_is_shown(controller):
    _guessing(controller, False)
    play(controller, 2.0)
    controller._set_lyrics(L._result(L.parse_lrc(SONG), "test"))        # it repeats, but nobody says where the chorus is
    assert len(controller._lyr_windows) == 1 and controller._fallback
    assert controller.status()["lyrics"]["fallback"] is True and controller.status()["lyrics"]["windows"] == 1


def test_a_labelled_chorus_gets_its_card_with_guessing_off(controller):
    _guessing(controller, False)
    play(controller, 2.0)
    result = _labelled()
    assert result["chorus_basis"] == "labels"
    controller._set_lyrics(result)
    assert controller._lyr_windows == [tuple(w) for w in result["chorus"]] and controller._lyr_windows
    assert not controller._fallback and controller.status()["lyrics"]["fallback"] is False       # a marked chorus is never replaced by the whole song


def test_guessing_picks_the_chorus_instead_of_the_whole_song(controller):
    _guessing(controller, True)
    play(controller, 2.0)
    controller._set_lyrics(L._result(L.parse_lrc(SONG), "test"))
    assert len(controller._lyr_windows) == 2 and not controller._fallback


def test_guessing_that_finds_nothing_still_shows_the_whole_song(controller):
    """A rap verse list: every line different, no label. Found lyrics are never left without a card."""
    _guessing(controller, True)
    play(controller, 2.0)
    controller._set_lyrics(_no_repeats())
    assert len(controller._lyr_windows) == 1 and controller._fallback


def test_the_demo_cards_work_with_guessing_off(controller):
    _guessing(controller, False)
    controller._lyr_force = True
    play(controller, 2.0)
    controller._set_lyrics(L._result(L.parse_lrc(SONG), "test"))
    assert controller._lyr_windows


def test_whole_song_mode_needs_no_label(controller):
    from yalw import config
    controller.cfg = config.from_values({**config.to_values(controller.cfg), "lyrics_when": "always", "lyrics_guess": False})
    play(controller, 2.0)
    controller._set_lyrics(L._result(L.parse_lrc(SONG), "test"))
    assert len(controller._lyr_windows) == 1


def test_a_real_chorus_is_a_chorus_not_the_whole_song(controller):
    play(controller, 2.0)
    load(controller)
    (a, b), *_ = controller._lyr_windows
    assert b - a < 25


def _passages():
    """A, B, A, B: two different passages that each come back once, with two one-off lines between them."""
    first = ["the first repeated passage line one", "the first repeated passage line two"]
    second = ["another repeating passage line one", "another repeating passage line two"]
    order = [first, [f"unique filler number {i} is here" for i in (1, 2)], second, [f"unique filler number {i} is here" for i in (3, 4)],
             first, [f"unique filler number {i} is here" for i in (5, 6)], second, [f"unique filler number {i} is here" for i in (7, 8)]]
    lines, t = [], 0.0
    for block in order:
        for text in block:
            lines.append({"t": t, "e": t + 2.8, "text": text, "words": [], "part": "", "sec": 0})
            t += 3.0
    return lines


def _level(lines, loud_runs, seconds=60):
    """Loudness: -10 dB over the given line ranges, -30 elsewhere."""
    return [-10.0 if any(lines[a]["t"] <= s < lines[b]["e"] for a, b in loud_runs) else -30.0 for s in range(seconds)]


def test_loudness_breaks_a_tie_between_repeated_passages_too():
    lines = _passages()
    assert len(L.chorus_windows(lines)[0]) == 4                       # nothing to choose by: every repeat counts
    spans, basis = L.chorus_windows(lines, "", _level(lines, [(4, 5), (12, 13)]))
    assert basis == "runs" and len(spans) == 2
    assert spans[0][0] == pytest.approx(lines[4]["t"] - L.LEAD) and spans[1][0] == pytest.approx(lines[12]["t"] - L.LEAD)
    spans, _ = L.chorus_windows(lines, "", _level(lines, [(0, 1), (8, 9)]))
    assert len(spans) == 2 and spans[0][0] == 0.0 and spans[1][0] == pytest.approx(lines[8]["t"] - L.LEAD)


def test_loudness_that_was_not_heard_where_it_matters_changes_nothing():
    lines = _passages()
    assert len(L.chorus_windows(lines, "", [None] * 60)[0]) == 4


def test_chorus_card_never_lingers_into_the_next_verse():
    lines = [{"t": float(i * 3), "e": float(i * 3 + 2.5), "text": f"line number {i % 4} of the song", "words": [], "part": "", "sec": i // 4}
             for i in range(12)]
    lines[4:8] = [{**l, "part": "Chorus"} for l in lines[4:8]]
    (start, end), = L.windows(lines, "chorus")
    assert lines[7]["e"] <= end < lines[8]["t"]           # the verse after the chorus starts at 24 s
    lines[7]["e"] = lines[8]["t"]                          # sung right up to the next line: no extra time at all
    (_, end), = L.windows(lines, "chorus")
    assert end == lines[8]["t"]


# -- one demo song, everywhere ---------------------------------------------------------------------------------

def test_every_demo_shows_the_same_one_song(controller):
    from yalw import demo
    assert [(t["title"], t["artist"]) for t in demo.TRACKS] == [("Never Gonna Give You Up", "Rick Astley")]
    for kind in ("new", "next", "prev", "pause", "play", "lyrics", "lyrics-words"):
        controller._on_demo(kind)
        assert (controller._media["title"], controller._media["artist"]) == ("Never Gonna Give You Up", "Rick Astley"), kind


def test_no_other_demo_song_is_left_anywhere_in_the_sources():
    root = Path(__file__).resolve().parents[1]
    for path in [*(root / "yalw").rglob("*.py"), *(root / "yalw").rglob("*.qml"), root / "README.md"]:
        text = path.read_text()
        for stale in ("Midnight City", "Neon Rain", "rickroll", "own_lyrics"):
            assert stale not in text, f"{stale!r} in {path.name}"


# -- a slow or flaky link: connections are kept, failures are retried, and the log tells the truth ---------------------

class _Reply:
    def __init__(self, status=200, body="ok", headers=None):
        self.status, self.body, self.headers = status, body, headers or {}

    def getheader(self, name):
        return self.headers.get(name)

    def read(self, limit):
        return self.body.encode()[:limit]


class _Conn:
    made: list = []
    script: list = []                          # what the next requests do: a _Reply, or an exception to raise

    def __init__(self, netloc, timeout=None):
        self.netloc, self.timeout, self.requests, self.closed = netloc, timeout, [], False
        _Conn.made.append(self)

    def request(self, method, path, headers=None):
        self.requests.append(path)
        step = _Conn.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        self._reply = step

    def getresponse(self):
        return self._reply

    def close(self):
        self.closed = True


@pytest.fixture
def conns(monkeypatch):
    _Conn.made, _Conn.script = [], []
    L._pool.__dict__.pop("conns", None)
    monkeypatch.setattr(L.http.client, "HTTPSConnection", _Conn)
    yield _Conn
    L._pool.__dict__.pop("conns", None)


def test_one_handshake_serves_every_request_to_the_same_server(conns):
    conns.script = [_Reply(body="one"), _Reply(body="two")]
    assert L._http("https://lrc.red/api/v1", {"q": "a"}) == "one" and L._http("https://lrc.red/s/x.ttml") == "two"
    assert len(conns.made) == 1 and conns.made[0].requests == ["/api/v1?q=a", "/s/x.ttml"]
    conns.script = [_Reply()]
    L._http("https://lrclib.net/api/search")
    assert len(conns.made) == 2                                          # another server: another connection


def test_a_connection_the_server_closed_is_replaced_once(conns):
    conns.script = [_Reply(body="first"), L.http.client.RemoteDisconnected("closed"), _Reply(body="second")]
    assert L._http("https://lrc.red/a") == "first"
    assert L._http("https://lrc.red/b") == "second"
    assert len(conns.made) == 2 and conns.made[0].closed


def test_a_connection_that_never_worked_is_not_retried_blindly(conns):
    conns.script = [TimeoutError("handshake timed out")]
    with pytest.raises(OSError, match="handshake"):
        L._http("https://lrc.red/a")
    assert len(conns.made) == 1


def test_http_errors_and_odd_urls(conns):
    conns.script = [_Reply(404), _Reply(503)]
    assert L._http("https://lrc.red/missing") is None
    with pytest.raises(OSError, match="503"):
        L._http("https://lrc.red/down")
    assert L._http("http://lrc.red/plain") is None and L._http("ftp://x/y") is None
    conns.script = [L.http.client.IncompleteRead(b"x")]
    with pytest.raises(OSError):
        L._http("https://lrc.red/cut")


def test_redirects_are_followed_but_never_to_plain_http(conns):
    conns.script = [_Reply(302, headers={"Location": "/new"}), _Reply(body="moved")]
    assert L._http("https://lrc.red/old") == "moved"
    conns.script = [_Reply(301, headers={"Location": "http://evil.example/x"})]
    assert L._http("https://lrc.red/old2") is None


def test_search_names_the_sources_it_could_not_reach(monkeypatch, isolated):
    def down(meta):
        raise OSError("handshake timed out")
    monkeypatch.setitem(L.FETCHERS, "lrclib", down)
    monkeypatch.setitem(L.FETCHERS, "apple", lambda meta: None)
    monkeypatch.setitem(L.FETCHERS, "boidu", lambda meta: None)
    assert L.search(META, ("apple", "lrclib", "boidu")) == (None, ["lrclib"])


class _Rt:
    def __init__(self, loop):
        self.loop = loop


def _watcher(emitted):
    from yalw import media
    w = media.MediaWatcher.__new__(media.MediaWatcher)
    w.lyric_sources, w.emit_lyrics = ("apple", "lrclib"), emitted.append
    return w


def _player(key=("T", "A", "", "")):
    return SimpleNamespace(title="T", artist="A", album="", length_us=200_000_000, url="", as_text="", key=key, lyrics_key=key)


def test_lookups_that_could_not_reach_the_network_are_retried_while_the_song_plays(monkeypatch, caplog):
    import asyncio
    import logging

    from yalw import media
    monkeypatch.setattr(media, "RETRY_DELAYS", (0.01, 0.01))
    answers = iter([(None, ["lrclib"]), (None, ["apple", "lrclib"]), ({"source": "x", "lines": [], "synced": "line"}, [])])
    monkeypatch.setattr(media.lyrics, "search", lambda meta, sources: next(answers))
    emitted: list = []
    p = _player()

    async def go():
        w = _watcher(emitted)
        w.rt = _Rt(asyncio.get_running_loop())
        await w._fetch_lyrics(p, p.key)
    with caplog.at_level(logging.INFO, logger="yalw.media"):
        asyncio.run(go())
    assert len(emitted) == 1 and emitted[0]["result"]["source"] == "x"
    assert caplog.text.count("trying again") == 2 and "none found" not in caplog.text


def test_when_the_network_never_comes_back_the_log_says_so_not_just_none_found(monkeypatch, caplog):
    import asyncio
    import logging

    from yalw import media
    monkeypatch.setattr(media, "RETRY_DELAYS", (0.01,))
    monkeypatch.setattr(media.lyrics, "search", lambda meta, sources: (None, ["apple"]))
    emitted: list = []

    async def go():
        w = _watcher(emitted)
        w.rt = _Rt(asyncio.get_running_loop())
        p = _player()
        await w._fetch_lyrics(p, p.key)
    with caplog.at_level(logging.INFO, logger="yalw.media"):
        asyncio.run(go())
    assert emitted[0]["result"] is None and "none found" in caplog.text and "could not reach apple" in caplog.text


def test_a_retry_is_dropped_when_another_song_is_playing_by_then(monkeypatch):
    import asyncio

    from yalw import media
    monkeypatch.setattr(media, "RETRY_DELAYS", (0.05,))
    monkeypatch.setattr(media.lyrics, "search", lambda meta, sources: (None, ["apple"]))
    emitted: list = []
    p = _player()

    async def go():
        w = _watcher(emitted)
        w.rt = _Rt(asyncio.get_running_loop())
        task = asyncio.ensure_future(w._fetch_lyrics(p, p.key))
        await asyncio.sleep(0.01)
        p.key = ("Other", "B", "", "")                                  # the song changed during the wait
        await task
    asyncio.run(go())
    assert emitted == []


def test_a_new_song_forgets_the_fallback_of_the_old_one(controller):
    _guessing(controller, False)
    play(controller, 2.0)
    controller._set_lyrics(_no_repeats())
    assert controller._fallback
    controller._set_lyrics(_labelled())
    assert not controller._fallback
    controller._set_lyrics(None)
    assert not controller._fallback and controller._lyr_windows == []


def test_the_demos_do_not_fall_back(controller):
    _guessing(controller, False)
    controller._lyr_force = True
    play(controller, 2.0)
    controller._set_lyrics(_no_repeats())                              # a forced demo shows the chorus or nothing
    assert controller._lyr_windows == [] and not controller._fallback


# -- a card that is held open still goes when nothing moves ------------------------------------------------------------

def test_the_idle_and_minimum_times(controller):
    assert controller.idleMs == 4000 and controller.minShowMs == 3000        # the minimum is shorter: it never outlasts the idle rule


def test_an_idle_lyrics_card_comes_back_when_the_next_line_is_about_to_be_sung(controller):
    play(controller, 10.0)
    controller._set_lyrics(_no_repeats())                         # whole song; lines every 4 s from 4 s
    controller._schedule_lyrics()
    assert controller.events == ["start"]
    controller.lyricsIdled()                                      # the card sat unchanged and went away
    assert controller._lyr_idle and controller.events == ["start"]
    play(controller, 11.0)
    controller._schedule_lyrics()                                 # the next line (12 s) is not near yet
    assert controller.events == ["start"] and controller._lyr_idle
    play(controller, 11.6)
    controller._schedule_lyrics()                                 # ...now it is
    assert controller.events == ["start", "start"] and not controller._lyr_idle


def test_an_idle_lyrics_card_stays_away_after_the_last_line(controller):
    play(controller, 38.0)
    controller._set_lyrics(_no_repeats())                         # the last line starts at 40 s
    controller._schedule_lyrics()
    play(controller, 41.0)
    controller.lyricsIdled()
    play(controller, 42.0)
    controller._schedule_lyrics()
    assert controller.events == ["start"] and controller._lyr_idle    # nothing follows: it does not come back
    play(controller, 200.0)
    controller._media["length"] = 400.0                           # (the helper's song is only 40 s long)
    controller._media["position"] = 200.0
    controller._schedule_lyrics()                                 # past the window: the flag is cleared
    assert not controller._lyr_idle and controller.events == ["start"]


def test_new_lyrics_start_afresh_after_an_idle_card(controller):
    play(controller, 10.0)
    controller._set_lyrics(_no_repeats())
    controller._schedule_lyrics()
    controller.lyricsIdled()
    controller._set_lyrics(_no_repeats())
    assert not controller._lyr_idle
