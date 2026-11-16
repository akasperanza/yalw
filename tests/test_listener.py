# SPDX-License-Identifier: GPL-3.0-or-later
"""Audio learning. No real audio device is touched: PCM is synthesised, pactl output is invented."""

import asyncio
import time

import numpy as np
import pytest

from yalw import listener as Ls
from yalw import lyrics as L

SINK_INPUTS = """Sink Input #110
\tDriver: PipeWire
\tSink: 58
\tCorked: no
\tProperties:
\t\tmedia.name = "Some Stream"
\t\tapplication.name = "Spotify"
\t\tapplication.process.binary = "spotify"
Sink Input #111
\tSink: 58
\tCorked: yes
\tProperties:
\t\tapplication.name = "Firefox"
\t\tapplication.process.binary = "firefox"
Sink Input #112
\tSink: 58
\tCorked: no
\tProperties:
\t\tapplication.name = "Firefox"
\t\tapplication.process.binary = "firefox"
Sink Input #113
\tSink: 58
\tCorked: no
\tProperties:
\t\tapplication.name = "Firefox"
\t\tapplication.process.binary = "firefox"
"""


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


# -- finding the player's own stream -------------------------------------------------------

def test_sink_inputs_are_parsed():
    inputs = Ls.parse_sink_inputs(SINK_INPUTS)
    assert [i["index"] for i in inputs] == [110, 111, 112, 113]
    assert inputs[0]["props"]["application.name"] == "Spotify" and inputs[0]["sink"] == 58
    assert [i["corked"] for i in inputs] == [False, True, False, False]


def test_sinks_are_parsed():
    assert Ls.parse_sinks("55\talsa_out.a\tPipeWire\ts32le 2ch 48000Hz\tSUSP\n58\talsa_out.b\tPipeWire\ts32le 2ch 48000Hz\tRUNNING\n") == {55: "alsa_out.a", 58: "alsa_out.b"}


def test_the_players_token_comes_from_its_bus_name():
    assert Ls.player_token("org.mpris.MediaPlayer2.spotify") == "spotify"
    assert Ls.player_token("org.mpris.MediaPlayer2.firefox.instance_1_42") == "firefox"


def test_only_the_players_own_playing_stream_is_picked():
    inputs = Ls.parse_sink_inputs(SINK_INPUTS)
    assert Ls.pick_stream("org.mpris.MediaPlayer2.spotify", inputs)["index"] == 110


def test_an_ambiguous_or_missing_stream_means_no_recording():
    inputs = Ls.parse_sink_inputs(SINK_INPUTS)
    assert Ls.pick_stream("org.mpris.MediaPlayer2.firefox.instance_1", inputs) is None      # two playing Firefox streams
    assert Ls.pick_stream("org.mpris.MediaPlayer2.vlc", inputs) is None                      # not playing at all
    assert Ls.pick_stream("org.mpris.MediaPlayer2.x", inputs) is None                        # too short to be a safe match
    assert Ls.pick_stream("org.mpris.MediaPlayer2.spotify", []) is None


def test_a_corked_stream_is_not_recorded():
    only_corked = [i for i in Ls.parse_sink_inputs(SINK_INPUTS) if i["corked"]]
    assert Ls.pick_stream("org.mpris.MediaPlayer2.firefox", only_corked) is None


# -- loudness -----------------------------------------------------------------------------

def pcm(seconds: float, amplitude: float, rate: int = Ls.RATE) -> bytes:
    t = np.arange(int(seconds * rate)) / rate
    return (np.sin(2 * np.pi * 440 * t) * amplitude * 32767).astype("<i2").tobytes()


def test_one_value_per_second_and_louder_is_higher():
    meter = Ls.LoudnessMeter()
    out = meter.feed(pcm(2, 0.5) + pcm(2, 0.05))
    assert len(out) == 4 and out[0] > out[3] + 15                   # 0.5 vs 0.05 amplitude is 20 dB apart
    assert out[0] == pytest.approx(20 * np.log10(0.5 / np.sqrt(2)), abs=0.5)


def test_chunk_boundaries_do_not_matter():
    data = pcm(3, 0.3)
    whole = Ls.LoudnessMeter().feed(data)
    meter, pieces = Ls.LoudnessMeter(), []
    for i in range(0, len(data), 777):                              # an odd size: splits samples in half
        pieces += meter.feed(data[i:i + 777])
    assert pieces == pytest.approx(whole)


def test_silence_is_floored_not_minus_infinity():
    assert Ls.LoudnessMeter().feed(pcm(1, 0.0)) == [Ls.FLOOR_DB]


# -- the store ---------------------------------------------------------------------------------

def test_save_and_load_roundtrip():
    db = [-20.0, -18.5, None, -22.0]
    assert Ls.save("A", "T", 4.0, db) == 0.75
    assert Ls.load("A", "T", 4.0) == db
    assert Ls.load("A", "Other", 4.0) is None


def test_a_second_listen_fills_the_gaps_of_the_first():
    Ls.save("A", "T", 4.0, [-20.0, None, None, -22.0])
    total = Ls.save("A", "T", 4.0, [None, -19.0, -21.0, None])
    assert total == 1.0 and Ls.load("A", "T", 4.0) == [-20.0, -19.0, -21.0, -22.0]


def test_a_newer_listen_does_not_overwrite_what_is_known():
    Ls.save("A", "T", 3.0, [-20.0, -20.0, -20.0])
    Ls.save("A", "T", 3.0, [-30.0, None, None])
    assert Ls.load("A", "T", 3.0)[0] == -30.0                       # what was heard last time the second was heard wins


def test_forgetting_removes_everything_and_counts():
    Ls.save("A", "T", 3.0, [-20.0] * 3)
    Ls.save("B", "U", 3.0, [-20.0] * 3)
    assert Ls.count_learned() == 2 and Ls.forget_all() == 2 and Ls.count_learned() == 0 and Ls.load("A", "T", 3.0) is None


def test_garbage_in_the_store_is_ignored():
    Ls.save("A", "T", 3.0, [-20.0] * 3)
    next(Ls.audio_dir().glob("*.json")).write_text("{broken")
    assert Ls.load("A", "T", 3.0) is None


def test_section_loudness_needs_most_of_the_section_heard():
    db = [-20.0] * 10 + [None] * 10
    assert Ls.section_db(db, 0, 10) == -20.0
    assert Ls.section_db(db, 5, 15) == -20.0                        # half heard is enough
    assert Ls.section_db(db, 12, 20) is None


# -- loudness settles ties between repeated sections ---------------------------------------------

VERSE_A = ["walking down the quiet avenue", "every window holds a story", "counting all the lights tonight", "nothing here is ordinary"]
VERSE_B = ["morning breaks across the harbour", "ships are leaving one by one", "somewhere someone starts to wonder", "where the long night will have gone"]
PRE = ["and it builds and it builds", "can you feel it rising now"]
HOOK = ["oh we sing it loud and clear", "never letting go tonight"]


def _song(blocks, per_line=3.0):
    lines, t = [], 4.0
    for sec, block in enumerate(blocks):
        for text in block:
            lines.append({"t": t, "e": t + per_line, "text": text, "words": [], "part": "", "sec": sec})
            t += per_line
        t += 1.5
    return lines


def _loudness(lines, loud_secs, quiet=-30.0, loud=-12.0):
    db = [quiet] * (int(lines[-1]["e"]) + 2)
    for line in lines:
        if line["sec"] in loud_secs:
            for i in range(int(line["t"]), int(line["e"])):
                db[i] = loud
    return db


def test_without_audio_a_tie_goes_to_the_longer_section():
    lines = _song([VERSE_A, PRE, HOOK, VERSE_B, PRE, HOOK])        # PRE and HOOK both come twice, both two lines
    lines = _song([VERSE_A, PRE + ["one more rising line"], HOOK, VERSE_B, PRE + ["one more rising line"], HOOK])
    spans = L.windows(lines, "chorus")
    assert spans[0][0] == pytest.approx(lines[[l["sec"] for l in lines].index(1)]["t"] - L.LEAD)   # the longer, quieter pre-chorus wins


def test_with_audio_the_loud_section_wins_the_tie():
    lines = _song([VERSE_A, PRE + ["one more rising line"], HOOK, VERSE_B, PRE + ["one more rising line"], HOOK])
    db = _loudness(lines, loud_secs={2, 5})
    spans = L.windows(lines, "chorus", loudness=db)
    first_hook = lines[[l["sec"] for l in lines].index(2)]["t"]
    assert spans[0][0] == pytest.approx(first_hook - L.LEAD) and len(spans) == 2


def test_apple_labels_are_never_overruled_by_loudness():
    lines = _song([VERSE_A, PRE, HOOK, VERSE_B, PRE, HOOK])
    for l in lines:
        l["part"] = "Chorus" if l["sec"] in (1, 4) else "Verse"     # the labelled "chorus" is the quiet one
    db = _loudness(lines, loud_secs={2, 5})
    assert L.chorus_windows(lines, "x", db)[1] == "labels"


def test_unheard_sections_fall_back_to_the_old_rule():
    lines = _song([VERSE_A, PRE + ["one more rising line"], HOOK, VERSE_B, PRE + ["one more rising line"], HOOK])
    assert L.windows(lines, "chorus", loudness=[None] * 200) == L.windows(lines, "chorus")


# -- the learner: when it listens and when it does not ---------------------------------------------

class FakePlayer:
    name = "org.mpris.MediaPlayer2.spotify"
    artist, title, key = "A", "T", ("T", "A", "", "")
    length_us = 200_000_000
    status = "Playing"

    def position_now(self):
        return 10_000_000


class FakeWatcher:
    current = FakePlayer()


class Spy(Ls.AudioLearner):
    def __init__(self):
        super().__init__(None, FakeWatcher(), lambda info: None)
        self.log = []

    async def _start(self, p, song):
        self.log.append("start")
        self.session = Ls._Session(song, None, 200)

    async def _finish(self, discard=False):
        self.log.append("discard" if discard else "finish")
        self.session = None


def tick(learner):
    asyncio.run(learner._tick())


def test_it_starts_listening_to_a_new_song_that_is_playing():
    spy = Spy()
    tick(spy)
    assert spy.log == ["start"] and spy.session.song == ("A", "T", 200)


def test_it_does_not_listen_while_paused(monkeypatch):
    spy = Spy()
    monkeypatch.setattr(FakePlayer, "status", "Paused")
    tick(spy)
    assert spy.log == [] and spy.session is None
    monkeypatch.setattr(FakePlayer, "status", "Playing")


def test_it_stops_when_the_song_is_paused_or_changes(monkeypatch):
    spy = Spy()
    tick(spy)
    monkeypatch.setattr(FakePlayer, "status", "Paused")
    tick(spy)
    assert spy.log == ["start", "finish"]
    monkeypatch.setattr(FakePlayer, "status", "Playing")
    monkeypatch.setattr(FakePlayer, "title", "Another")
    monkeypatch.setattr(FakePlayer, "key", ("Another", "A", "", ""))
    tick(spy)
    assert spy.log == ["start", "finish", "start"] and spy.session.song == ("A", "Another", 200)


def test_a_song_with_a_chorus_label_is_never_listened_to():
    spy = Spy()
    spy.skip = lambda: True
    tick(spy)
    assert spy.log == [] and spy.session is None


def test_a_label_that_arrives_late_stops_the_listening_and_keeps_nothing():
    spy = Spy()
    tick(spy)
    assert spy.log == ["start"]
    spy.skip = lambda: True                                   # the lyrics came in, with a chorus label
    tick(spy)
    assert spy.log == ["start", "discard"] and spy.session is None


def test_the_label_of_the_new_song_does_not_throw_away_the_old_one(monkeypatch):
    spy = Spy()
    tick(spy)
    monkeypatch.setattr(FakePlayer, "title", "Another")
    monkeypatch.setattr(FakePlayer, "key", ("Another", "A", "", ""))
    spy.skip = lambda: True                                   # the NEW song is labelled; the old one was heard fairly
    tick(spy)
    assert spy.log == ["start", "finish"]


def test_a_learned_song_is_never_listened_to_again():
    Ls.save("A", "T", 200, [-20.0] * 201)
    spy = Spy()
    tick(spy)
    assert spy.log == [] and spy.state == "learned"


def test_a_half_heard_song_is_listened_to_again():
    Ls.save("A", "T", 200, [-20.0] * 100 + [None] * 101)
    spy = Spy()
    tick(spy)
    assert spy.log == ["start"]


def test_after_forgetting_it_learns_the_song_again():
    Ls.save("A", "T", 200, [-20.0] * 201)
    spy = Spy()
    tick(spy)
    assert spy.log == []
    Ls.forget_all()
    tick(spy)
    assert spy.log == ["start"]


def test_when_the_stream_is_not_found_it_waits_and_retries_later(monkeypatch):
    class Quiet(Ls.AudioLearner):
        async def _start(self, p, song):                          # the real _start, with an empty pactl
            return await Ls.AudioLearner._start(self, p, song)

    async def nothing(*argv):
        return ""
    monkeypatch.setattr(Ls, "_run", nothing)
    learner = Quiet(None, FakeWatcher(), lambda info: None)
    asyncio.run(learner._tick())
    assert learner.session is None and learner._retry[("A", "T", 200)] > time.time()


# -- the controller uses what was learned ------------------------------------------------------------

@pytest.fixture
def controller(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    from yalw import config, prefs
    from yalw.controller import Controller
    from yalw.runtime import Runtime
    from yalw.surface import Surface

    QGuiApplication.instance() or QGuiApplication([])
    cfg = config.from_values({**config.to_values(config.Config()), "lyrics_enabled": True, "lyrics_guess": True})
    ctl = Controller(cfg, Surface(cfg, "xcb"), Runtime(), "xcb")
    ctl._prefs = prefs.SongPrefs(tmp_path / "songs.json")
    return ctl


def _playing(ctl, lines):
    ctl._media = {**ctl._media, "title": "T", "artist": "A", "playing": True, "length": float(int(lines[-1]["e"]) + 2),
                  "position": 2.0, "stamp": time.time() * 1000}


def _result(lines):
    spans, basis = L.chorus_windows(lines, "T")
    return {"source": "test", "synced": "line", "lines": lines, "chorus": [list(s) for s in spans], "chorus_basis": basis}


def test_windows_are_recomputed_once_the_song_has_been_heard(controller):
    lines = _song([VERSE_A, PRE + ["one more rising line"], HOOK, VERSE_B, PRE + ["one more rising line"], HOOK])
    _playing(controller, lines)
    controller._set_lyrics(_result(lines))
    before = controller._lyr_windows[0][0]
    Ls.save("A", "T", controller._media["length"], _loudness(lines, {2, 5}))
    controller._on_learned({"artist": "A", "title": "T", "length": controller._media["length"], "coverage": 1.0})
    assert controller._lyr_windows[0][0] != before and len(controller._lyr_windows) == 2


def test_features_of_another_song_are_ignored(controller):
    lines = _song([VERSE_A, PRE, HOOK, VERSE_B, PRE, HOOK])
    _playing(controller, lines)
    controller._set_lyrics(_result(lines))
    windows = list(controller._lyr_windows)
    controller._on_learned({"artist": "A", "title": "Different", "length": 10, "coverage": 1.0})
    assert controller._lyr_windows == windows


def test_learning_off_means_stored_loudness_is_not_used(controller):
    from yalw import config
    lines = _song([VERSE_A, PRE + ["one more rising line"], HOOK, VERSE_B, PRE + ["one more rising line"], HOOK])
    _playing(controller, lines)
    Ls.save("A", "T", controller._media["length"], _loudness(lines, {2, 5}))
    controller.cfg = config.from_values({**config.to_values(controller.cfg), "lyrics_learn": False})
    assert controller._load_loudness() is None and not controller._learning_on()


def test_learning_only_runs_with_lyrics_on_in_chorus_mode(controller):
    from yalw import config
    values = config.to_values(controller.cfg)
    assert controller._learning_on()
    controller.cfg = config.from_values({**values, "lyrics_guess": False})
    assert not controller._learning_on()                  # experimental: nothing is listened to unless guessing is on
    controller.cfg = config.from_values({**values, "lyrics_enabled": False})
    assert not controller._learning_on()
    controller.cfg = config.from_values({**values, "lyrics_when": "always"})
    assert not controller._learning_on()


def test_status_reports_audio_learning(controller):
    import json
    st = controller.status()
    json.dumps(st)
    assert st["audio"]["enabled"] is True and st["audio"]["state"] == "off" and st["audio"]["learned"] == 0


def test_a_partly_heard_song_is_still_used_where_it_was_heard(controller):
    lines = _song([VERSE_A, PRE, HOOK, VERSE_B, PRE, HOOK])
    _playing(controller, lines)
    db = _loudness(lines, {2, 5})
    half = [v if i % 2 == 0 else None for i, v in enumerate(db)]
    Ls.save("A", "T", controller._media["length"], half)
    assert controller._load_loudness() is not None                   # no global 60% bar any more; sections judge themselves


def test_the_controller_knows_whether_the_lyrics_are_labelled(controller):
    lines = _song([VERSE_A, PRE, HOOK, VERSE_B, PRE, HOOK])
    _playing(controller, lines)
    assert not controller.has_chorus_label()
    controller._set_lyrics(_result(lines))                    # no labels: the chorus was only guessed
    assert not controller.has_chorus_label()
    labelled = [{**l, "part": "Chorus" if l["sec"] in (2, 5) else "Verse"} for l in lines]
    controller._set_lyrics(_result(labelled))
    assert controller.has_chorus_label()
