import asyncio
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from yalw import config, control, extensions, notice
from yalw.builtin import power

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "extensions"


# -- the notice: everything from outside is cleaned ---------------------------------------------

def test_a_notice_needs_a_title():
    with pytest.raises(ValueError):
        notice.make({"subtitle": "no title"})
    with pytest.raises(ValueError):
        notice.make({"title": "   \n "})
    with pytest.raises(ValueError):
        notice.make("a string")
    assert notice.make({"progress": 0.4}).title == ""                  # a ring may stand on its own


def test_text_is_cut_to_size_and_stripped_of_control_characters():
    card = notice.make({"title": "a" * 200, "subtitle": "line one\nline two\x00\x1b[31m", "value": "123456"})
    assert len(card.title) == notice.TITLE_MAX and card.title.endswith("…")
    assert "\n" not in card.subtitle and "\x00" not in card.subtitle and "\x1b" not in card.subtitle
    assert card.value == "1234…"[: notice.VALUE_MAX] or len(card.value) <= notice.VALUE_MAX


def test_only_icons_that_ship_with_yalw_are_accepted():
    assert notice.make({"title": "x", "icon": "plug-zap"}).icon == "plug-zap"
    assert notice.make({"title": "x", "icon": "../../etc/passwd"}).icon == "bell"
    assert notice.make({"title": "x", "icon": "does-not-exist", "badge": "nope"}).badge == ""
    assert len(notice.icons()) >= 170


def test_colours_progress_seconds_and_keys_are_validated():
    card = notice.make({"title": "x", "accent": "#AABBCC", "progress": 3, "seconds": 999, "key": "a b"})
    assert (card.accent, card.progress, card.seconds, card.key) == ("#aabbcc", 1.0, 30.0, "")
    card = notice.make({"title": "x", "accent": "javascript:1", "progress": "nan", "seconds": "soon", "key": "dl-1"})
    assert (card.accent, card.progress, card.seconds, card.key) == ("", None, None, "dl-1")
    assert notice.make({"title": "x", "progress": True}).progress is None
    assert notice.make({"title": "x", "progress": -4}).progress == 0.0


def test_the_ring_shows_the_percentage_unless_told_otherwise():
    assert notice.make({"title": "x", "progress": 0.78}).payload()["value"] == "78"
    assert notice.make({"title": "x", "progress": 0.78, "value": "OK"}).payload()["value"] == "OK"
    assert notice.make({"title": "x"}).payload()["progress"] == -1.0


# -- finding extensions never runs them -------------------------------------------------------------------

def write(root: Path, name: str, body: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


GOOD = 'NAME = "Hello"\nDESCRIPTION = "Says hello."\nVERSION = "1.2"\nAUTHOR = "me"\nAPI = 1\n\nasync def run(yalw):\n    yalw.notify("hello")\n'


def test_discovery_reads_metadata_without_executing_anything(tmp_path):
    marker = tmp_path / "marker"
    write(tmp_path / "ext", "evil.py", f'NAME = "Evil"\nAPI = 1\nopen({str(marker)!r}, "w").write("ran")\nraise SystemExit(1)\n')
    found = {i.id: i for i in extensions.discover(tmp_path / "ext")}
    assert found["evil"].name == "Evil" and found["evil"].compatible
    assert not marker.exists()


def test_discovery_finds_files_and_folders_and_skips_the_rest(tmp_path):
    root = tmp_path / "ext"
    write(root, "hello.py", GOOD)
    write(root, "folder/extension.py", GOOD.replace("Hello", "Folder"))
    write(root, "_private.py", GOOD)
    write(root, ".hidden.py", GOOD)
    write(root, "Bad Name.py", GOOD)
    write(root, "notes.txt", "x")
    write(root, "empty/readme.md", "x")
    found = {i.id: i for i in extensions.discover(root)}
    assert set(found) == {"hello", "folder"}
    assert found["hello"].version == "1.2" and found["hello"].author == "me" and found["folder"].name == "Folder"


def test_metadata_must_be_plain_literals_and_the_api_must_match(tmp_path):
    write(tmp_path, "tricky.py", 'import os\nNAME = os.environ["HOME"]\nAPI = 1 + 0\n')
    write(tmp_path, "future.py", 'NAME = "Future"\nAPI = 2\n')
    write(tmp_path, "none.py", "x = 1\n")
    found = {i.id: i for i in extensions.discover(tmp_path)}
    assert found["tricky"].name == "tricky"                          # not a literal: ignored, the id is used instead
    assert found["future"].api == 2 and not found["future"].compatible
    assert not found["none"].compatible and found["none"].name == "none"


def test_a_huge_or_broken_source_is_not_parsed(tmp_path):
    write(tmp_path, "big.py", 'NAME = "Big"\n' + "#" * extensions.MAX_SOURCE)
    write(tmp_path, "broken.py", "def (:\n")
    found = {i.id: i for i in extensions.discover(tmp_path)}
    assert found["big"].name == "big" and found["broken"].name == "broken"
    assert not found["big"].compatible                                # a blob that size is never run unseen
    assert found["broken"].compatible                                 # unparseable: let it fail loudly when enabled, with the real error


def test_a_missing_folder_is_simply_empty(tmp_path):
    assert extensions.discover(tmp_path / "nowhere") == []


# -- running them -----------------------------------------------------------------------------------------

def make_host(tmp_path, enabled, **extra):
    got: list[dict] = []
    values = {**config.to_values(config.Config()), "power_plugged": False, "power_unplugged": False,
              "extensions_enabled": enabled, **extra}
    host = extensions.ExtensionHost(config.from_values(values), got.append, root=tmp_path)
    return host, got


def wait_for(predicate, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_only_enabled_extensions_are_ever_loaded(tmp_path):
    marker = tmp_path / "off-ran"
    write(tmp_path, "on.py", GOOD)
    write(tmp_path, "off.py", f'NAME = "Off"\nAPI = 1\nopen({str(marker)!r}, "w").write("x")\nasync def run(yalw):\n    pass\n')
    host, got = make_host(tmp_path, ["on"])
    host.start()
    try:
        assert wait_for(lambda: got)
        assert got[0]["title"] == "hello" and got[0]["source"] == "on"
        assert list(host.runners) == ["on"] and not marker.exists()
    finally:
        host.stop()


def test_an_extension_built_for_another_api_is_not_started(tmp_path):
    write(tmp_path, "future.py", GOOD.replace("API = 1", "API = 2"))
    host, got = make_host(tmp_path, ["future"])
    host.start()
    assert host.runners == {} and got == []


def test_a_crashing_extension_is_restarted_then_left_stopped_and_others_carry_on(tmp_path, monkeypatch):
    monkeypatch.setattr(extensions, "RESTART_DELAYS", (0.02, 0.02, 0.02))
    write(tmp_path, "crashy.py", 'NAME = "Crashy"\nAPI = 1\nasync def run(yalw):\n    raise RuntimeError("boom")\n')
    write(tmp_path, "fine.py", GOOD)
    host, got = make_host(tmp_path, ["crashy", "fine"])
    host.start()
    try:
        assert wait_for(lambda: host.runners["crashy"].state == "stopped")
        assert "crashed 4 times" in host.runners["crashy"].error and "boom" in host.runners["crashy"].error
        assert [g["title"] for g in got] == ["hello"] and host.runners["fine"].state == "running"
    finally:
        host.stop()


def test_a_broken_extension_reports_why_it_could_not_start(tmp_path):
    write(tmp_path, "syntax.py", "NAME = 'S'\nAPI = 1\ndef (:\n")
    write(tmp_path, "sync.py", "NAME = 'Sync'\nAPI = 1\ndef run(yalw):\n    pass\n")
    write(tmp_path, "exits.py", "NAME = 'E'\nAPI = 1\nraise SystemExit(3)\n")
    host, _ = make_host(tmp_path, ["syntax", "sync", "exits"])
    host.start()
    try:
        assert wait_for(lambda: all(r.state == "failed" for r in host.runners.values()))
        assert "could not load" in host.runners["syntax"].error and "async def run" in host.runners["sync"].error
        assert "could not load" in host.runners["exits"].error
        assert {s["id"]: s["state"] for s in host.status()} == {"syntax": "failed", "sync": "failed", "exits": "failed"}
    finally:
        host.stop()


def test_an_extension_that_blocks_does_not_hold_up_the_others(tmp_path):
    write(tmp_path, "blocker.py", "import time\nNAME = 'B'\nAPI = 1\nasync def run(yalw):\n    time.sleep(1.5)\n")
    write(tmp_path, "quick.py", GOOD)
    host, got = make_host(tmp_path, ["blocker", "quick"])
    started = time.time()
    host.start()
    try:
        assert wait_for(lambda: got, timeout=1.0)
        assert time.time() - started < 1.0
    finally:
        host.stop()


def test_stopping_cancels_a_running_extension_and_closes_its_loop(tmp_path):
    write(tmp_path, "waits.py", 'NAME = "W"\nAPI = 1\nimport asyncio\nasync def run(yalw):\n    await asyncio.sleep(60)\n')
    host, _ = make_host(tmp_path, ["waits"])
    host.start()
    runner = host.runners["waits"]
    assert wait_for(lambda: runner.state == "running")
    began = time.time()
    host.stop()
    assert time.time() - began < 1.5 and not runner._thread.is_alive()


def test_an_extension_that_returns_keeps_working_through_what_it_spawned(tmp_path):
    write(tmp_path, "spawner.py", 'NAME = "S"\nAPI = 1\nimport asyncio\n'
                                  "async def later(yalw):\n    await asyncio.sleep(0.05)\n    yalw.notify('late')\n"
                                  "async def run(yalw):\n    yalw.spawn(later(yalw))\n")
    host, got = make_host(tmp_path, ["spawner"])
    host.start()
    try:
        assert wait_for(lambda: got) and got[0]["title"] == "late"
    finally:
        host.stop()


def test_settings_language_and_data_dir_reach_the_extension(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    config.extension_settings_dir().mkdir(parents=True)
    (config.extension_settings_dir() / "echo.toml").write_text('minutes = 3\nname = "x"\n')
    write(tmp_path / "ext", "echo.py", 'NAME = "Echo"\nAPI = 1\n'
          "async def run(yalw):\n"
          "    (yalw.data_dir / 'seen.txt').write_text('ok')\n"
          "    yalw.notify(yalw.tr({'en': 'English', 'tr': 'Türkçe'}), str(yalw.settings['minutes']) + yalw.settings['name'])\n")
    host, got = make_host(tmp_path / "ext", ["echo"], language="tr")
    host.start()
    try:
        assert wait_for(lambda: got)
        assert (got[0]["title"], got[0]["subtitle"]) == ("Türkçe", "3x")
        assert (tmp_path / "state" / "yalw" / "ext" / "echo" / "seen.txt").read_text() == "ok"
    finally:
        host.stop()


def test_unreadable_settings_are_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config.extension_settings_dir().mkdir(parents=True)
    (config.extension_settings_dir() / "bad.toml").write_text("this is [not toml")
    assert extensions.load_settings("bad") == {} and extensions.load_settings("missing") == {}


# -- Api.notify: limits ----------------------------------------------------------------------------------

def make_api(monkeypatch, gap=0.0):
    monkeypatch.setattr(extensions, "MIN_GAP", gap)
    sent: list = []
    host = SimpleNamespace(language="en", emit=lambda card, source: sent.append((card, source)),
                           emit_clear=lambda key, source: sent.append(("clear", key)))
    runner = SimpleNamespace(info=SimpleNamespace(id="t", name="T"), host=host, settings={})
    return extensions.Api(runner), sent


def test_notify_refuses_bad_input_without_raising(monkeypatch):
    api, sent = make_api(monkeypatch)
    assert api.notify("") is False and api.notify("ok") is True
    assert [c.title for c, _ in sent] == ["ok"]


def test_at_most_twelve_cards_a_minute(monkeypatch):
    api, sent = make_api(monkeypatch)
    results = [api.notify(f"n{i}") for i in range(20)]
    assert results.count(True) == extensions.MAX_PER_MINUTE == len(sent)


def test_cards_that_come_too_fast_are_coalesced_the_newest_wins(monkeypatch):
    api, sent = make_api(monkeypatch, gap=0.25)
    for i in range(4):
        assert api.notify(f"n{i}")
    assert [c.title for c, _ in sent] == ["n0"]                      # the first at once, the rest wait their turn...
    assert wait_for(lambda: len(sent) == 2, timeout=1.5)
    assert [c.title for c, _ in sent] == ["n0", "n3"]                # ...and only the newest of them is shown


def test_tr_falls_back_to_english(monkeypatch):
    api, _ = make_api(monkeypatch)
    api.language = "de"
    assert api.tr({"en": "Hi", "tr": "Selam"}) == "Hi" and api.tr({"de": "Hallo", "en": "Hi"}) == "Hallo"
    assert api.tr({"fr": "Salut"}) == "Salut"


# -- the built-in power extension --------------------------------------------------------------------------

def test_the_plugged_in_card_is_just_an_icon_and_the_level():
    card = power.describe(False, 64, power.CHARGING, 2820, "en")
    assert card["title"] == "" and "subtitle" not in card and card["progress"] == 0.64 and card["key"] == "power"
    assert card["icon"] == "battery-charging" and "badge" not in card
    made = notice.make(card)                                           # and it passes the same checks as anyone's
    assert made.title == "" and made.payload()["value"] == "64"
    assert power.describe(False, 100, power.FULL, 0, "en")["icon"] == "plug-zap"


def test_the_unplugged_card_warns_when_the_battery_is_low():
    card = power.describe(True, 12, power.DISCHARGING, 5400, "en")
    assert card["title"] == "On battery" and card["subtitle"] == "1 h 30 min left" and card["icon"] == "battery-warning"
    assert card["accent"] == "#ff5d6c"
    assert power.describe(True, 90, 2, 0, "en")["subtitle"] == "Running on battery" and power.describe(True, 90, 2, 0, "en")["icon"] == "battery-full"


def test_no_battery_means_no_ring():
    card = power.describe(False, None, 0, 0, "en")
    assert "progress" not in card and notice.make(card).progress is None and card["title"] == "Plugged in"


@pytest.mark.parametrize("language", ["en", "tr", "de", "es"])
def test_every_language_has_every_power_text(language):
    assert set(power.TEXTS[language]) == set(power.TEXTS["en"])


V = SimpleNamespace


class FakeBus:
    def __init__(self):
        self.handlers = []

    def add_message_handler(self, handler):
        self.handlers.append(handler)

    def send(self, on_battery: bool):
        from dbus_fast import MessageType
        msg = SimpleNamespace(message_type=MessageType.SIGNAL, member="PropertiesChanged", path=power.ROOT,
                              body=[power.UPOWER, {"OnBattery": V(value=on_battery)}, []])
        for handler in self.handlers:
            handler(msg)


class FakeApi:
    language = "en"

    def __init__(self, bus, settings):
        self.bus, self.settings, self.cards = bus, settings, []

    async def system_bus(self):
        return self.bus

    def tr(self, texts):
        return texts.get(self.language) or texts["en"]

    def notify(self, title, subtitle="", **kwargs):
        self.cards.append({"title": title, "subtitle": subtitle, **kwargs})
        return True


def drive_power(monkeypatch, settings, script):
    """Run the real ``power.run`` against a fake UPower. ``script(bus)`` is an async function that makes things happen."""
    state = {"on_battery": False}

    async def fake_call(bus, destination, path, interface, member, signature="", body=None):
        if member == "Get":
            return [V(value=state["on_battery"])]
        return [{"IsPresent": V(value=True), "Percentage": V(value=82.0), "State": V(value=1 if not state["on_battery"] else 2),
                 "TimeToFull": V(value=1800), "TimeToEmpty": V(value=7200)}]

    async def no_match(bus, rule):
        return None
    monkeypatch.setattr(power, "call", fake_call)
    monkeypatch.setattr(power, "add_match", no_match)
    monkeypatch.setattr(power, "SETTLE", 0.05)
    bus = FakeBus()
    api = FakeApi(bus, settings)

    async def main():
        task = asyncio.ensure_future(power.run(api))
        await asyncio.sleep(0.05)
        await script(bus, state)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    asyncio.run(main())
    return api.cards


def test_plugging_in_shows_one_card(monkeypatch):
    async def script(bus, state):
        state["on_battery"] = True
        bus.send(True)
        await asyncio.sleep(0.2)
        state["on_battery"] = False
        bus.send(False)
        await asyncio.sleep(0.3)
    cards = drive_power(monkeypatch, {"plugged": True, "unplugged": False}, script)
    assert [c["title"] for c in cards] == [""] and cards[0]["progress"] > 0      # unplugging was not asked for


def test_a_flapping_charger_is_announced_once_where_it_settles(monkeypatch):
    async def script(bus, state):
        for value in (True, False, True, False):                     # a USB-C charger renegotiating
            bus.send(value)
            await asyncio.sleep(0.005)
        await asyncio.sleep(0.4)
    assert drive_power(monkeypatch, {"plugged": True, "unplugged": True}, script) == []     # it ended where it began


def test_both_directions_when_both_are_wanted(monkeypatch):
    async def script(bus, state):
        state["on_battery"] = True
        bus.send(True)
        await asyncio.sleep(0.25)
        state["on_battery"] = False
        bus.send(False)
        await asyncio.sleep(0.3)
    cards = drive_power(monkeypatch, {"plugged": True, "unplugged": True}, script)
    assert [c["title"] for c in cards] == ["On battery", ""]


# -- scripts and the command line -------------------------------------------------------------------------

@pytest.fixture
def qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication
    return QGuiApplication.instance() or QGuiApplication([])


@pytest.fixture
def controller(qt):
    from yalw.controller import Controller
    from yalw.runtime import Runtime
    from yalw.surface import Surface
    cfg = config.Config()
    ctl = Controller(cfg, Surface(cfg, "xcb"), Runtime(), "xcb")
    ctl.cards = []
    ctl.noticeEvent.connect(lambda: ctl.cards.append(dict(ctl._notice)))
    return ctl


def test_a_notice_from_a_script_reaches_the_card(controller):
    assert controller.notify_json(json.dumps({"title": "Done", "subtitle": "ok", "icon": "check", "seconds": 7})) == ""
    assert controller.cards[-1]["title"] == "Done" and controller.cards[-1]["seconds"] == 7 and controller.cards[-1]["source"] == "notify"


def test_a_notice_without_a_time_gets_the_users_setting(controller):
    controller.notify_json(json.dumps({"title": "x"}))
    assert controller.cards[-1]["seconds"] == config.Config().notice_seconds


def test_bad_notices_are_refused_with_a_reason(controller):
    assert "title" in controller.notify_json("{}")
    assert controller.notify_json("not json") != ""
    assert "large" in controller.notify_json("x" * 5000)
    assert controller.cards == []


def test_scripts_are_limited_to_thirty_a_minute(controller):
    results = [controller.notify_json(json.dumps({"title": f"n{i}"})) for i in range(35)]
    assert results.count("") == 30 and "too many" in results[-1]


def test_quiet_mode_silences_extension_cards_too(controller):
    controller._on_quiet("on")
    controller.notify_json(json.dumps({"title": "x"}))
    assert controller.cards == []
    controller._on_quiet("off")
    controller.notify_json(json.dumps({"title": "x"}))
    assert len(controller.cards) == 1


def test_the_demo_cards(controller):
    for kind in ("charger", "charger-unplug", "notice"):
        controller._on_demo(kind)
    assert [c["source"] for c in controller.cards] == ["demo"] * 3
    assert controller.cards[0]["icon"] == "battery-charging" and controller.cards[0]["title"] == "" and controller.cards[1]["title"] in ("On battery", "Pilde çalışıyor")


def test_the_status_lists_the_extensions(controller):
    assert controller.status()["extensions"] == []
    controller.extensions = SimpleNamespace(status=lambda: [{"id": "power", "state": "running"}])
    assert controller.status()["extensions"] == [{"id": "power", "state": "running"}]
    json.dumps(controller.status())


def test_the_control_interface_hands_notices_on():
    from yalw.runtime import Control
    def notify(ctl, text):                                        # the way the bus calls it (the plain attribute is a wrapper)
        return {m.name: m for m in ctl._get_methods(ctl)}["Notify"].fn(ctl, text)
    ctl = Control(lambda k: None, lambda: None, lambda m: None, lambda: None, on_notice=lambda text: "refused: " + text)
    assert notify(ctl, "{}") == "refused: {}"
    assert notify(Control(lambda k: None, lambda: None, lambda m: None, lambda: None), "{}") == ""


def run_cli(monkeypatch, argv, reply=("ok", [""])):
    from yalw import __main__ as cli
    sent = []
    monkeypatch.setattr(control, "query", lambda member, *args: sent.append((member, args)) or reply)
    monkeypatch.setattr(control, "send", lambda member, *args: sent.append((member, args)) or reply[0])
    monkeypatch.setattr("sys.argv", ["yalw", *argv])
    return cli.main(), sent


def test_cli_notify_sends_the_card(monkeypatch):
    code, sent = run_cli(monkeypatch, ["notify", "Backup", "2 GB", "--icon", "check", "--progress", "78", "--key", "bk"])
    payload = json.loads(sent[0][1][0])
    assert code == 0 and sent[0][0] == "Notify"
    assert payload == {"title": "Backup", "subtitle": "2 GB", "icon": "check", "progress": 0.78, "key": "bk"}      # 78 means 78 %


def test_cli_notify_reports_problems(monkeypatch, capsys):
    assert run_cli(monkeypatch, ["notify", ""])[0] == 2
    assert run_cli(monkeypatch, ["notify", "x"], reply=(control.NOT_RUNNING, []))[0] == 1
    assert run_cli(monkeypatch, ["notify", "x"], reply=(control.OUTDATED, []))[0] == 1
    assert run_cli(monkeypatch, ["notify", "x"], reply=("ok", ["too many notices"]))[0] == 1
    assert "too many notices" in capsys.readouterr().err


def test_cli_extension_new_writes_a_template_that_is_a_valid_extension(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    code, _ = run_cli(monkeypatch, ["extension", "new", "Coffee Break"])
    found = extensions.discover()
    assert code == 0 and [i.id for i in found] == ["coffee-break"]
    assert found[0].name == "Coffee Break" and found[0].compatible and "async def run(yalw)" in found[0].path.read_text()
    assert run_cli(monkeypatch, ["extension", "new", "Coffee Break"])[0] == 1       # never overwrites
    assert run_cli(monkeypatch, ["extension", "new", "Bad/Name"])[0] == 2


def test_cli_enable_and_disable_change_only_the_list(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    write(config.extensions_dir(), "coffee.py", GOOD)
    config.save({**config.to_values(config.Config()), "scale": 1.3})
    assert run_cli(monkeypatch, ["extension", "enable", "coffee"])[0] == 0
    assert config.load().extensions_enabled == ("coffee",) and config.load().scale == 1.3
    assert run_cli(monkeypatch, ["extension", "enable", "ghost"])[0] == 1
    assert run_cli(monkeypatch, ["extension", "disable", "coffee"])[0] == 0
    assert config.load().extensions_enabled == ()


def test_cli_lists_what_is_installed(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    write(config.extensions_dir(), "coffee.py", GOOD)
    assert run_cli(monkeypatch, ["extensions"], reply=(control.NOT_RUNNING, []))[0] == 0
    out = capsys.readouterr().out
    assert "power" in out and "built in" in out and "coffee" in out and "Hello 1.2" in out


# -- YALW Config -----------------------------------------------------------------------------------------

@pytest.fixture
def model(qt, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    write(config.extensions_dir(), "coffee.py", GOOD)
    write(config.extensions_dir(), "future.py", GOOD.replace("API = 1", "API = 2"))
    from yalw.configapp import ConfigModel
    return ConfigModel(autosave=False)


def test_config_lists_extensions_with_their_state(model):
    listed = {e["id"]: e for e in model.extensionList}
    assert set(listed) == {"coffee", "future"} and not listed["coffee"]["enabled"] and listed["coffee"]["state"] == ""
    assert listed["coffee"]["name"] == "Hello" and listed["future"]["compatible"] is False


def test_switching_an_extension_on_changes_only_the_list(model):
    model.setExtension("coffee", True)
    assert model.values["extensions_enabled"] == ["coffee"] and model.dirty
    model.setExtension("ghost", True)                                  # not installed: nothing happens
    assert model.values["extensions_enabled"] == ["coffee"]
    model.setExtension("coffee", False)
    assert model.values["extensions_enabled"] == []


def test_config_shows_how_the_daemon_says_each_extension_is_doing(model):
    model.setExtension("coffee", True)
    model._set_daemon({"checked": True, "running": True, "info": {"extensions": [{"id": "coffee", "state": "crashed", "error": "boom"}]}})
    coffee = {e["id"]: e for e in model.extensionList}["coffee"]
    assert coffee["enabled"] and coffee["state"] == "crashed" and coffee["error"] == "boom"


def test_the_charger_events_and_the_notice_time_are_settings(model):
    assert model.values["power_plugged"] is True and model.values["power_unplugged"] is False
    model.set("power_unplugged", True)
    model.set("notice_seconds", 99)
    assert model.values["power_unplugged"] is True and model.values["notice_seconds"] == 30


def test_the_preview_has_sample_notices(model):
    cards = model.previewNotices
    assert len(cards) >= 3 and all((c["title"] or c["progress"] >= 0) and c["icon"] for c in cards)


# -- the examples that ship with YALW ----------------------------------------------------------------------

def test_the_shipped_examples_are_valid_extensions():
    found = {i.id: i for i in extensions.discover(EXAMPLES)}
    assert set(found) == {"network", "low_battery", "cpu_load"} and all(i.compatible and i.description for i in found.values())


def test_the_low_battery_example_warns_once_per_discharge(monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("low_battery_example", EXAMPLES / "low_battery.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    readings = iter([(50.0, 2), (19.0, 2), (18.0, 2), (30.0, 1), (15.0, 2)])
    sleeps = []

    async def fake_battery(bus):
        return next(readings)

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 5:
            raise asyncio.CancelledError

    monkeypatch.setattr(module, "battery", fake_battery)
    monkeypatch.setattr(module.asyncio, "sleep", fake_sleep)
    api = FakeApi(FakeBus(), {})
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(module.run(api))
    assert [c["title"] for c in api.cards] == ["Battery low", "Battery low"]       # at 19 %, and again after a recharge
    assert api.cards[0]["progress"] == pytest.approx(0.19)


def test_config_fields_for_extensions_have_safe_defaults():
    cfg = config.Config()
    assert cfg.extensions_enabled == () and cfg.power_plugged is True and cfg.power_unplugged is False
    assert config.from_values({**config.to_values(cfg), "extensions_enabled": ["A", " b ", ""]}).extensions_enabled == ("a", "b")


def test_every_qml_string_exists(qt):
    import re
    from yalw import i18n
    qml = Path(extensions.__file__).parent / "qml"
    used = set()
    for path in qml.glob("*.qml"):
        used |= set(re.findall(r"\btr\.(\w+)", path.read_text()))
        used |= set(re.findall(r"\bstrings\.(\w+)", path.read_text()))
    assert used <= set(i18n.STRINGS["en"]), used - set(i18n.STRINGS["en"])


# -- live cards ------------------------------------------------------------------------------------------

def test_a_live_notice_needs_a_key():
    with pytest.raises(ValueError):
        notice.make({"title": "cpu", "live": True})
    card = notice.make({"title": "cpu", "live": True, "key": "cpu"})
    assert card.live and card.payload()["live"] is True
    assert notice.make({"title": "cpu"}).live is False and notice.make({"title": "x", "live": "yes", "key": "k"}).live is False


def test_live_cards_belong_to_their_extension_and_come_off_with_clear(monkeypatch):
    monkeypatch.setattr(extensions, "LIVE_GAP", 0.0)
    api, sent = make_api(monkeypatch)
    assert api.live("cpu", progress=0.4) is True                     # a lone ring needs no title
    card, source = sent[0]
    assert card.key == "t.cpu" and card.live and card.title == "" and card.progress == 0.4 and source == "t"
    api.clear("cpu")
    assert sent[-1] == ("clear", "t.cpu")
    api.clear("cpu")                                                # nothing left to clear
    assert len(sent) == 2


def test_live_refuses_bad_keys_and_too_many(monkeypatch):
    monkeypatch.setattr(extensions, "LIVE_GAP", 0.0)
    api, sent = make_api(monkeypatch)
    assert api.live("", "x") is False and api.live("a b", "x") is False and api.live("k" * 60, "x") is False
    assert all(api.live(f"k{i}", "x") for i in range(extensions.MAX_LIVE))
    assert api.live("one-too-many", "x") is False
    assert api.live("k0", "again") is True                           # redrawing one that exists is always fine
    assert api.notify("a plain card") is True                        # live cards do not use the cards-a-minute allowance


def test_live_redraws_are_thinned_and_the_newest_value_wins(monkeypatch):
    monkeypatch.setattr(extensions, "LIVE_GAP", 0.2)
    api, sent = make_api(monkeypatch)
    for value in range(40):                                          # a busy loop: 40 values in a blink
        api.live("cpu", progress=value / 100)
    assert len(sent) == 1
    assert wait_for(lambda: len(sent) == 2, 1.0)
    assert sent[1][0].progress == 0.39                               # what is shown is the latest value, not the first
    assert not wait_for(lambda: len(sent) > 2, 0.4)


def test_clearing_cancels_a_redraw_that_was_waiting(monkeypatch):
    monkeypatch.setattr(extensions, "LIVE_GAP", 0.2)
    api, sent = make_api(monkeypatch)
    api.live("cpu", progress=0.1)
    api.live("cpu", progress=0.2)
    api.clear("cpu")
    time.sleep(0.4)
    assert sent[-1] == ("clear", "t.cpu")
    assert not any(getattr(c, "progress", None) == 0.2 for c, _ in sent)


def test_what_an_extension_leaves_on_screen_goes_when_it_stops(monkeypatch):
    monkeypatch.setattr(extensions, "LIVE_GAP", 0.0)
    api, sent = make_api(monkeypatch)
    api.live("a", "x")
    api.live("b", "y")
    api.close()
    assert sorted(k for c, k in sent if c == "clear") == ["t.a", "t.b"]


def live_controller(controller):
    controller.shown = []
    controller.gone = []
    controller.liveEvent.connect(lambda: controller.shown.append(dict(controller._live_notice)))
    controller.liveGone.connect(controller.gone.append)
    return controller


def live(controller, key, title="x", **extra):
    controller.noticeIn.emit(notice.make({"title": title, "key": key, "live": True, **extra}).payload("t"))


def test_a_live_card_is_redrawn_by_each_update(controller):
    ctl = live_controller(controller)
    live(ctl, "cpu", progress=0.2)
    live(ctl, "cpu", progress=0.5)
    assert [c["progress"] for c in ctl.shown] == [0.2, 0.5]
    assert ctl.cards == []                                            # it is not an ordinary card


def test_one_live_card_owns_the_screen_and_the_next_waits(controller):
    ctl = live_controller(controller)
    live(ctl, "a", "first")
    live(ctl, "b", "second")
    assert [c["title"] for c in ctl.shown] == ["first"]               # b is queued, a is not pushed off by it
    ctl.noticeIn.emit({"clear": "a", "source": "t"})
    assert ctl.gone == ["a"]
    ctl._window_up = False
    ctl._live_resume()
    assert ctl.shown[-1]["title"] == "second"


def test_a_dismissed_live_card_stays_away_until_its_owner_clears_it(controller):
    ctl = live_controller(controller)
    live(ctl, "cpu", progress=0.2)
    ctl.liveDismissed("cpu")
    live(ctl, "cpu", progress=0.3)                                    # the owner keeps sending values: still silent
    ctl._live_resume()
    assert len(ctl.shown) == 1
    ctl.noticeIn.emit({"clear": "cpu", "source": "t"})
    live(ctl, "cpu", progress=0.4)                                    # a new start after a clear shows again
    assert [c["progress"] for c in ctl.shown] == [0.2, 0.4]


def test_a_live_card_comes_back_after_another_card(controller):
    ctl = live_controller(controller)
    live(ctl, "cpu", progress=0.2)
    ctl._window_up = True
    ctl.hideWindow = lambda: None                                     # the other card is still up: no return yet
    ctl._live_resume()
    assert len(ctl.shown) == 1
    ctl._window_up = False
    ctl._live_resume()
    assert len(ctl.shown) == 2 and ctl.shown[-1]["progress"] == 0.2


def test_quiet_mode_takes_live_cards_off_and_brings_them_back(controller):
    ctl = live_controller(controller)
    live(ctl, "cpu", progress=0.2)
    ctl._on_quiet("on")
    assert ctl.gone == ["cpu"]
    live(ctl, "cpu", progress=0.3)
    assert len(ctl.shown) == 1                                        # nothing is drawn while it is quiet
    ctl._on_quiet("off")
    assert ctl.shown[-1]["progress"] == 0.3


def test_live_and_clear_through_the_script_door(controller):
    ctl = live_controller(controller)
    assert ctl.notify_json(json.dumps({"title": "", "progress": 0.4, "key": "build", "live": True})) == ""
    assert ctl.shown[-1]["progress"] == 0.4
    assert "key" in ctl.notify_json(json.dumps({"title": "x", "live": True}))
    assert ctl.notify_json(json.dumps({"clear": "build"})) == ""
    assert ctl.gone == ["build"]
    for _ in range(10):
        ctl.notify_json(json.dumps({"title": "x", "key": "k", "live": True}))
    assert "too many" in ctl.notify_json(json.dumps({"title": "x", "key": "k", "live": True}))


def test_the_cpu_load_example_draws_a_lone_ring(monkeypatch):
    import importlib.util
    path = Path(__file__).parent.parent / "examples" / "extensions" / "cpu_load.py"
    assert extensions._info(path, path).compatible
    spec = importlib.util.spec_from_file_location("cpu_load_example", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    busy, total = module.read_cpu()
    assert 0 <= busy <= total
    calls: list = []
    api = SimpleNamespace(settings={"interval": 0.5}, live=lambda *a, **k: calls.append((a, k)) or True)

    async def go():
        task = asyncio.ensure_future(module.run(api))
        await asyncio.sleep(0.8)
        task.cancel()

    asyncio.run(go())
    assert calls and calls[0][0] == ("cpu",) and 0 <= calls[0][1]["progress"] <= 1 and "title" not in calls[0][1]
