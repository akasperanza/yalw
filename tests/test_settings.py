# SPDX-License-Identifier: GPL-3.0-or-later
import re
from pathlib import Path

import pytest

from yalw import config, i18n

QML_DIR = Path(config.__file__).parent / "qml"


# -- schema ------------------------------------------------------------------

def test_every_default_is_valid_for_its_own_spec():
    for spec in config.FIELDS:
        assert config.coerce(spec, spec.default) == spec.default, spec.attr


def test_field_names_and_keys_are_unique():
    assert len({f.attr for f in config.FIELDS}) == len(config.FIELDS)
    assert len({(f.table, f.key) for f in config.FIELDS}) == len(config.FIELDS)


def test_save_then_load_roundtrips_every_field(tmp_path):
    values = config.to_values(config.Config())
    values.update(position="bottom-right", scale=1.25, accent="#FF8800", ignore_players=["Firefox", "mpv"],
                  font="Inter", language="tr", battery_low=10, battery_warn=40, equalizer=False)
    path = config.save(values, tmp_path / "c.toml")
    loaded = config.load(path)
    assert (loaded.position, loaded.scale, loaded.accent) == ("bottom-right", 1.25, "#ff8800")
    assert loaded.ignore_players == ("firefox", "mpv")
    assert (loaded.language, loaded.battery_low, loaded.equalizer) == ("tr", 10, False)
    assert config.save(config.to_values(loaded), tmp_path / "again.toml").read_text() == path.read_text()


@pytest.mark.parametrize("attr,raw,expected", [
    ("scale", 9, 1.6), ("scale", -1, 0.7), ("margin", "abc", 44), ("margin", "12", 12),     # junk -> default; a numeric string is tolerated
    ("accent", "red", "auto"), ("accent", "auto", "auto"), ("bluetooth_accent", "#ABCDEF", "#abcdef"),
    ("language", "fr", "auto"), ("shadow", "yes", True), ("battery_low", 0, 1),
])
def test_bad_values_are_repaired(attr, raw, expected):
    assert config.coerce(config.BY_ATTR[attr], raw) == expected


def test_old_format_file_still_loads(tmp_path):
    path = tmp_path / "old.toml"
    path.write_text('position = "top-left"\nmargin = 20\n[events]\nskip = false\n[timing]\nmedia = 3.0\n')
    cfg = config.load(path)
    assert (cfg.position, cfg.margin, cfg.skip, cfg.media_seconds) == ("top-left", 20, False, 3.0)
    assert cfg.scale == 1.0 and cfg.accent == "auto"          # new keys fall back to defaults


# -- translations -------------------------------------------------------------

def test_every_language_has_every_string():
    english = set(i18n.STRINGS["en"])
    for code, table in i18n.STRINGS.items():
        assert set(table) == english, f"{code}: missing {english - set(table)}, extra {set(table) - english}"


def test_languages_in_config_match_translations():
    assert set(config.LANGUAGES) == {"auto", *i18n.STRINGS}


def test_auto_follows_the_environment(monkeypatch):
    for var in ("LC_ALL", "LC_MESSAGES", "LANGUAGE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LANG", "tr_TR.UTF-8")
    assert i18n.resolve("auto") == "tr"
    monkeypatch.setenv("LANG", "xx_XX.UTF-8")
    assert i18n.resolve("auto") in i18n.STRINGS            # unknown → fallback, never a crash
    assert i18n.resolve("de") == "de"


def test_qml_only_uses_strings_that_exist():
    used = set()
    for qml in QML_DIR.glob("Cfg*.qml"):
        used |= set(re.findall(r"\.tr\.(\w+)", qml.read_text()))
        used |= set(re.findall(r'win\.tr\[modelData\[1\]\]|"((?:tab|preview)_\w+)"', qml.read_text()))
    used.discard("")
    assert used, "no string references found; the pattern is stale"
    assert used <= set(i18n.STRINGS["en"]), used - set(i18n.STRINGS["en"])


# -- config window model ------------------------------------------------------

@pytest.fixture
def model(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    from yalw.configapp import ConfigModel

    QGuiApplication.instance() or QGuiApplication([])
    return ConfigModel()


def test_changes_are_saved_on_their_own_after_a_pause(model, tmp_path, monkeypatch):
    from yalw import control
    monkeypatch.setattr(control, "send", lambda *a: control.NOT_RUNNING)
    assert not model.dirty
    model.set("scale", 1.3)
    assert model.dirty and model.values["scale"] == 1.3 and model._save_timer.isActive()
    model._save_timer.timeout.emit()                       # the pause is over
    assert not model.dirty and not model._save_timer.isActive()
    assert config.load(tmp_path / "yalw" / "config.toml").scale == 1.3


def test_model_rejects_junk_and_clamps(model):
    model.set("scale", 99)
    assert model.values["scale"] == 1.6
    model.set("nonsense", 1)
    assert "nonsense" not in model.values
    model.set("accent", "not-a-colour")
    assert model.values["accent"] == "auto"


def test_model_parses_the_ignore_list_field(model):
    model.set("ignore_players", " Firefox ,, chromium ")
    assert model.values["ignore_players"] == ["firefox", "chromium"]


def test_battery_thresholds_stay_ordered(model):
    model.set("battery_low", 40)
    assert model.values["battery_warn"] > model.values["battery_low"]
    model.set("battery_warn", 10)
    assert model.values["battery_low"] < model.values["battery_warn"]


def test_language_switch_updates_strings_and_reset_keeps_it(model):
    model.set("language", "tr")
    assert model.strings["reset"] == "Varsayılana dön"
    model.set("scale", 1.4)
    model.reset()
    assert model.values["scale"] == 1.0 and model.values["language"] == "tr"


def test_apply_saves_without_a_daemon(model, tmp_path, monkeypatch):
    from yalw import control
    monkeypatch.setattr(control, "send", lambda *a: control.NOT_RUNNING)
    model.set("position", "bottom-left")
    model.apply()
    assert not model.dirty
    assert config.load(tmp_path / "yalw" / "config.toml").position == "bottom-left"
    assert model.status == model.strings["st_saved_only"]


# -- compact mode ------------------------------------------------------------

def test_compact_cards_are_wider_and_shorter():
    from yalw.surface import Surface

    normal = Surface(config.Config(), "xcb")
    compact = Surface(config.from_values({**config.to_values(config.Config()), "compact": True}), "xcb")
    assert compact.card_w > normal.card_w and compact.media_h < normal.media_h and compact.lyrics_h < normal.lyrics_h
    assert compact.stage_w > normal.stage_w and compact.stage_h < normal.stage_h     # the window follows the cards


def test_the_song_line_reads_in_the_natural_order_of_each_language():
    for code, first in (("tr", "{artist}"), ("en", "{title}"), ("de", "{title}"), ("es", "{title}")):
        line = i18n.strings(code)["song_line"]
        assert "{title}" in line and "{artist}" in line and line.startswith(first), code


def test_config_model_learns_whether_the_daemon_runs(model):
    model._set_daemon({"checked": True, "running": True, "info": {"version": "x"}})
    assert model.daemon["running"] and model.daemon["info"]["version"] == "x"
    model._set_daemon({"checked": True, "running": False, "info": {}})
    assert not model.daemon["running"]


def test_config_model_tails_the_log(model, tmp_path, monkeypatch):
    log = tmp_path / "yalw.log"
    log.write_text("".join(f"line {i}\n" for i in range(500)))
    monkeypatch.setattr("yalw.configapp.log_path", lambda: log)
    model.refreshLog()
    assert model.log.splitlines()[-1] == "line 499" and len(model.log.splitlines()) == 160


def test_config_model_without_a_log_file_is_just_empty(model, tmp_path, monkeypatch):
    monkeypatch.setattr("yalw.configapp.log_path", lambda: tmp_path / "missing.log")
    model.refreshLog()
    assert model.log == ""


def test_control_calls_before_the_controller_exists_are_harmless():
    from yalw.app import _when_ready
    holder: dict = {}
    status = _when_ready(holder, lambda c: c.status(), default="{}")
    demo = _when_ready(holder, lambda c, kind: c.demo(kind))
    assert status() == "{}" and demo("new") is None                  # used to raise KeyError and log a traceback

    class Controller:
        def status(self): return '{"ok": 1}'
        def demo(self, kind): return kind
    holder["controller"] = Controller()
    assert status() == '{"ok": 1}' and demo("new") == "new"


# -- live preview and quiet saving ------------------------------------------------------

def test_the_preview_is_drawn_from_the_settings_as_they_are_now(model):
    assert model.style["cardW"] == 400
    model.set("compact", True)
    assert (model.style["cardW"], model.style["mediaH"]) == (480, 104)
    model.set("media_radius", 12)
    assert model.style["mediaRadius"] == 12
    assert any(l["words"] for l in model.previewLyrics["lines"])
    model.set("lyrics_words", False)
    assert model.previewLyrics["synced"] == "line" and not any(l["words"] for l in model.previewLyrics["lines"])
    model.set("language", "tr")
    assert model.songLine == i18n.STRINGS["tr"]["song_line"] and model.labels["reset"] == "Varsayılana dön"


def test_preview_media_starts_where_asked(model):
    song = model.freshMedia(30)
    assert song["position"] == 30 and song["playing"] and song["title"] == "Never Gonna Give You Up"


def test_a_card_is_shown_on_screen_only_for_changes_about_where_it_sits(model, monkeypatch):
    from yalw import control
    sent = []
    monkeypatch.setattr(control, "send", lambda *a: sent.append(a) or "ok")
    model.set("shadow", False)
    model.apply()
    assert [a[0] for a in sent] == ["Reload"]
    sent.clear()
    model.set("position", "bottom-left")
    model.apply()
    assert [a[0] for a in sent] == ["Reload", "Demo"]


def test_reset_is_saved_too_and_shows_where_the_card_goes(model, monkeypatch):
    from yalw import control
    sent = []
    monkeypatch.setattr(control, "send", lambda *a: sent.append(a) or "ok")
    model.set("scale", 1.4)
    model.apply()
    sent.clear()
    model.reset()
    assert model.dirty and model._save_timer.isActive()
    model.apply()
    assert not model.dirty and model.values["scale"] == 1.0
    assert [a[0] for a in sent] == ["Reload", "Demo"]


def test_the_accent_follows_the_song_that_is_playing(model):
    from yalw.configapp import DEFAULT_ACCENT
    assert model.pal["accent"] == DEFAULT_ACCENT
    model._set_daemon({"checked": True, "running": True, "info": {"song": {"title": "x", "accent": "#336699"}}})
    assert model.pal["accent"] == "#336699" and model.pal["onAccent"] == "#ffffff"
    model._set_daemon({"checked": True, "running": True, "info": {"song": {"title": "x", "accent": "#f2d479"}}})
    assert model.pal["onAccent"] != "#ffffff"                 # dark text on a light accent
    model._set_daemon({"checked": True, "running": True, "info": {"song": {"title": "x", "accent": "javascript:1"}}})
    assert model.pal["accent"] == DEFAULT_ACCENT              # nothing but a plain colour gets in
    model._set_daemon({"checked": True, "running": True, "info": {"song": {"title": "", "accent": "#336699"}}})
    assert model.pal["accent"] == DEFAULT_ACCENT              # no song, no song colour


# -- the preview shows the song that played last -----------------------------------------

def test_the_last_song_is_remembered_with_its_cover(tmp_path):
    from yalw import lastsong
    cover = tmp_path / "c.png"
    cover.write_bytes(b"not really a png")
    assert lastsong.load() is None
    song = {"title": "Aman", "artist": "Ruhi Su", "album": "Bir", "art": cover.as_uri(), "accent": "#c0a050", "length": 45.0}
    assert lastsong.remember(song)
    assert not lastsong.remember(song)                                   # unchanged: nothing is rewritten
    cover.unlink()                                                        # the cache may be pruned later: our copy stays
    got = lastsong.load()
    assert (got["title"], got["artist"], got["accent"], got["length"]) == ("Aman", "Ruhi Su", "#c0a050", 45.0)
    assert got["cover"].startswith("file://") and Path(got["cover"][7:]).read_bytes() == b"not really a png"
    assert not lastsong.remember({"title": "", "artist": "x"})            # no song, nothing to keep


def test_a_cover_that_arrives_late_is_added(tmp_path):
    from yalw import lastsong
    song = {"title": "T", "artist": "A", "album": "", "art": "", "accent": "#336699", "length": 100.0}
    assert lastsong.remember(song) and lastsong.load()["cover"] == ""
    cover = tmp_path / "late.png"
    cover.write_bytes(b"x")
    assert lastsong.remember({**song, "art": cover.as_uri()})
    assert lastsong.load()["cover"] != ""


def test_the_preview_plays_the_last_song_and_wears_its_colour(model, tmp_path):
    from yalw import lastsong
    assert model.freshMedia(30)["title"] == "Never Gonna Give You Up"      # nothing played yet: the demo song
    cover = tmp_path / "c.png"
    cover.write_bytes(b"x")
    lastsong.remember({"title": "Aman", "artist": "Ruhi Su", "album": "", "art": cover.as_uri(), "accent": "#c0a050", "length": 200.0})
    seen = []
    model.previewChanged.connect(lambda: seen.append(1))
    model._set_daemon({"checked": True, "running": False, "info": {}})     # the next poll notices it
    assert seen and model.freshMedia(30)["title"] == "Aman"
    song = model.freshMedia(500)
    assert Path(song["art"][7:]).name.startswith("last-song-cover-") and song["accent"] == "#c0a050" and song["position"] == 80.0
    assert model.pal["accent"] == "#c0a050"                                # nothing playing now: still the last song's colour


def test_a_snapshot_model_never_saves_anything(tmp_path, monkeypatch):
    from PySide6.QtGui import QGuiApplication
    from yalw import control
    from yalw.configapp import ConfigModel
    QGuiApplication.instance() or QGuiApplication([])
    sent = []
    monkeypatch.setattr(control, "send", lambda *a: sent.append(a) or "ok")
    quiet = ConfigModel(autosave=False)
    path = tmp_path / "_config" / "yalw" / "config.toml"
    before = path.read_text()                              # loading writes the defaults when there is no file yet
    quiet.set("language", "es")
    quiet.reset()
    assert not quiet._save_timer.isActive() and not sent
    assert path.read_text() == before


# -- the lyrics preview shows the last song's lyrics, or says where they will come ------------------------

def _remember_song(tmp_path, **extra):
    from yalw import lastsong
    song = {"title": "Aman", "artist": "Ruhi Su", "album": "Bir", "art": "", "accent": "#c0a050", "length": 200.0, **extra}
    lastsong.remember(song)
    return lastsong.load()


def _cache_lyrics(last, lines, chorus=None, source="Apple Music"):
    import json
    import time

    from yalw import lyrics
    meta = {"title": last["title"], "artist": last["artist"], "album": last["album"], "length": last["length"]}
    path = lyrics._cache_file(meta, ("apple", "lrclib", "boidu"))
    path.parent.mkdir(parents=True, exist_ok=True)
    result = {"source": source, "synced": "line", "lines": lines, "chorus": chorus or [], "chorus_basis": "labels" if chorus else "runs"}
    path.write_text(json.dumps({"ts": time.time(), "result": result}))


LINES = [{"t": 10.0 + 4 * i, "e": 13.5 + 4 * i, "text": f"gerçek bir dize sayısı {i}", "words": [], "part": "", "sec": 0} for i in range(8)]


def test_with_no_lyrics_the_preview_says_where_they_will_come(model):
    model.set("language", "en")                          # "auto" follows the machine running the tests
    lyr = model.previewLyrics
    assert [l["text"] for l in lyr["lines"]] == ["Lyrics will appear here"] and lyr["synced"] == "word"
    words = lyr["lines"][0]["words"]
    assert [w["text"] for w in words] == ["Lyrics", "will", "appear", "here"] and [w["t"] for w in words] == sorted(w["t"] for w in words)
    assert model.previewLyricsLoop == 5.5 and model.freshLyricsMedia()["position"] == 0.0
    model.set("language", "tr")
    assert model.previewLyrics["lines"][0]["text"] == "Sözler buraya gelecek"


def test_the_placeholder_is_line_by_line_when_word_timing_is_off(model):
    model.set("lyrics_words", False)
    lyr = model.previewLyrics
    assert lyr["synced"] == "line" and lyr["lines"][0]["words"] == []


def test_a_last_song_without_found_lyrics_still_shows_the_placeholder_with_its_header(model, tmp_path):
    model.set("language", "en")                          # "auto" follows the machine running the tests
    _remember_song(tmp_path)
    model._set_daemon({"checked": True, "running": False, "info": {}})
    assert model.previewLyrics["lines"][0]["text"] == "Lyrics will appear here"
    assert model.freshLyricsMedia()["title"] == "Aman"


def test_the_last_songs_own_lyrics_are_shown_word_by_word_from_its_chorus(model, tmp_path):
    last = _remember_song(tmp_path)
    _cache_lyrics(last, LINES, chorus=[[26.0, 38.0]])
    model._set_daemon({"checked": True, "running": False, "info": {}})
    lyr = model.previewLyrics
    assert [l["text"] for l in lyr["lines"]] == [l["text"] for l in LINES] and lyr["source"] == "Apple Music" and lyr["synced"] == "word"
    first = lyr["lines"][0]
    assert [w["text"] for w in first["words"]] == ["gerçek", "bir", "dize", "sayısı", "0"]            # a line-timed source, spread into words
    assert first["t"] <= first["words"][0]["t"] < first["words"][-1]["t"] < first["e"]
    assert model.previewLyricsLoop == 14.0
    media = model.freshLyricsMedia()
    assert media["position"] == pytest.approx(25.7) and (media["title"], media["artist"]) == ("Aman", "Ruhi Su")


def test_real_word_timing_is_kept(model, tmp_path):
    last = _remember_song(tmp_path)
    timed = [{**LINES[0], "words": [{"t": 10.0, "text": "tek", "sp": False}]}]
    _cache_lyrics(last, timed)
    model._set_daemon({"checked": True, "running": False, "info": {}})
    assert model.previewLyrics["lines"][0]["words"] == [{"t": 10.0, "text": "tek", "sp": False}]


def test_turning_every_lyrics_source_off_goes_back_to_the_placeholder(model, tmp_path):
    model.set("language", "en")                          # "auto" follows the machine running the tests
    last = _remember_song(tmp_path)
    _cache_lyrics(last, LINES)
    model._set_daemon({"checked": True, "running": False, "info": {}})
    assert model.previewLyrics["lines"][0]["text"].startswith("gerçek")
    for source in ("lyrics_apple", "lyrics_lrclib", "lyrics_boidu"):
        model.set(source, False)
    assert model.previewLyrics["lines"][0]["text"] == "Lyrics will appear here"


def test_a_new_last_song_changes_the_preview(model, tmp_path):
    model.set("language", "en")                          # "auto" follows the machine running the tests
    last = _remember_song(tmp_path)
    _cache_lyrics(last, LINES)
    model._set_daemon({"checked": True, "running": False, "info": {}})
    seen = []
    model.previewChanged.connect(lambda: seen.append(1))
    from yalw import lastsong
    lastsong.remember({"title": "Another", "artist": "B", "album": "", "art": "", "accent": "#112233", "length": 120.0})
    model._set_daemon({"checked": True, "running": False, "info": {}, "x": 1})
    assert seen and model.previewLyrics["lines"][0]["text"] == "Lyrics will appear here"            # nothing found for this one yet


def test_cached_lyrics_come_from_disk_only(tmp_path):
    import json

    from yalw import lyrics
    meta = {"title": "T", "artist": "A", "album": "", "length": 100.0}
    assert lyrics.cached(meta, ("apple",)) is None
    path = lyrics._cache_file(meta, ("apple",))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ts": 1, "result": None}))                 # a remembered "not found"
    assert lyrics.cached(meta, ("apple",)) is None
    path.write_text("junk")
    assert lyrics.cached(meta, ("apple",)) is None
    path.write_text(json.dumps({"ts": 1, "result": {"source": "x", "lines": [{"t": 1, "e": 2, "text": "hi"}]}}))
    assert lyrics.cached(meta, ("apple",))["source"] == "x"
    assert lyrics.cached(meta, ("local",)) is None and lyrics.cached({**meta, "title": ""}, ("apple",)) is None


def test_every_song_gets_a_cover_file_of_its_own_so_the_preview_never_keeps_the_old_one(tmp_path):
    import json

    from yalw import lastsong
    first, second = tmp_path / "a.png", tmp_path / "b.png"
    first.write_bytes(b"cover one")
    second.write_bytes(b"cover two")
    lastsong.remember({"title": "One", "artist": "A", "album": "", "art": first.as_uri(), "accent": "#111111", "length": 100.0})
    one = lastsong.load()["cover"]
    lastsong.remember({"title": "Two", "artist": "B", "album": "", "art": second.as_uri(), "accent": "#222222", "length": 100.0})
    two = lastsong.load()["cover"]
    assert one and two and one != two                                       # QML reloads an image only when its address changes
    assert Path(two[7:]).read_bytes() == b"cover two" and not Path(one[7:]).exists()
    assert len(list(Path(two[7:]).parent.glob("last-song-cover*.img"))) == 1
    # an old-format file or a name that is not ours is never followed
    meta = Path(two[7:]).parent / "last-song.json"
    data = json.loads(meta.read_text())
    for bad in (True, "../../etc/passwd", "last-song-cover.img", 7):
        meta.write_text(json.dumps({**data, "cover": bad}))
        assert lastsong.load()["cover"] == ""


def test_a_cover_that_arrives_late_does_not_replace_a_cover_the_song_already_has(tmp_path):
    from yalw import lastsong
    cover = tmp_path / "c.png"
    cover.write_bytes(b"x")
    song = {"title": "T", "artist": "A", "album": "", "art": cover.as_uri(), "accent": "#333333", "length": 90.0}
    lastsong.remember(song)
    uri = lastsong.load()["cover"]
    assert not lastsong.remember(song) and lastsong.load()["cover"] == uri
