# SPDX-License-Identifier: GPL-3.0-or-later
"""Daemon entry point: wire the backends, the controller and the QML scene."""

import json
import logging
import logging.handlers
import os
import signal
import sys
import threading
import traceback
from pathlib import Path

from . import display
from .bluetooth import BluetoothWatcher
from .config import Config, log_path
from .extensions import ExtensionHost
from .listener import AudioLearner
from .media import MediaWatcher
from .runtime import Control, Runtime

log = logging.getLogger("yalw")

QML = Path(__file__).parent / "qml" / "Main.qml"


def _setup_logging() -> None:
    """Keep a small log file next to the console output: YALW Config shows it, bug reports need it."""
    try:
        log_path().parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(log_path(), maxBytes=400_000, backupCount=1, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))
        logging.getLogger().addHandler(handler)
    except OSError as exc:
        print(f"YALW: no log file ({exc})", file=sys.stderr)

    from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    levels = {QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR, QtMsgType.QtFatalMsg: logging.CRITICAL}
    qt = logging.getLogger("qt")

    def handler(kind, _ctx, text):
        if kind in levels:
            if "QBasicTimer::stop" in text:                         # which thread, doing what? (an intermittent warning)
                text += "\n" + "".join(traceback.format_stack(limit=10)) + f"thread: {threading.current_thread().name}"
            qt.log(levels[kind], text)

    qInstallMessageHandler(handler)


def _when_ready(holder: dict, call, default=None):
    """The bus name (and so the control calls) is live a moment before the controller exists. Early calls are
    ignored, and a status question gets an empty answer, which YALW Config shows as "starting"."""
    return lambda *args: call(holder["controller"], *args) if "controller" in holder else default


def _restart_in_place() -> None:
    """Re-exec the daemon with the same command line: new config, same PID (systemd stays happy)."""
    log.info("reloading")
    os.execvp(sys.orig_argv[0], sys.orig_argv)


def _build(cfg: Config, backend: str, runtime: Runtime):
    """Create the Qt application, the controller and the QML window."""
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickWindow

    from .controller import Controller
    from .icons import LucideProvider
    from .surface import Surface

    app = QGuiApplication(sys.argv)
    app.setApplicationName("yalw")
    app.setDesktopFileName("yalw")
    app.setQuitOnLastWindowClosed(False)

    surface = Surface(cfg, backend)
    controller = Controller(cfg, surface, runtime, backend)

    engine = QQmlApplicationEngine()
    engine.addImageProvider("lucide", LucideProvider())
    engine.rootContext().setContextProperty("host", controller)
    engine.load(str(QML))
    if not engine.rootObjects():
        raise SystemExit("YALW: the QML scene failed to load")
    window = engine.rootObjects()[0]
    assert isinstance(window, QQuickWindow)
    surface.attach(window)

    controller.quitIn.connect(app.quit)
    controller.reloadIn.connect(_restart_in_place)
    return app, engine, controller, window


async def _start_watchers(runtime: Runtime, controller) -> None:
    media = MediaWatcher(runtime, controller.mediaIn.emit, controller.cfg.ignore_players,
                         controller.lyric_sources(), controller.lyricsIn.emit)
    controller.media_watcher = media
    if controller._learning_on() and AudioLearner.available():
        learner = controller.audio_learner = AudioLearner(runtime, media, controller.learnedIn.emit, controller.has_chorus_label)
        runtime.spawn(learner.run())
    watchers = [("media", media)]
    if runtime.system_bus is not None:
        watchers.append(("bluetooth", BluetoothWatcher(runtime, controller.btIn.emit)))
    for name, watcher in watchers:
        try:
            await watcher.start()
        except Exception:  # noqa: BLE001 - one missing service must not stop the other
            log.exception("%s watcher could not start", name)


def run(cfg: Config) -> int:
    backend = display.choose_backend(cfg.backend)
    display.configure_environment(backend)
    _setup_logging()

    runtime = Runtime()
    holder: dict = {}
    when_ready = lambda call, default=None: _when_ready(holder, call, default)

    control = Control(
        on_demo=when_ready(lambda c, kind: c.demoIn.emit(kind)),
        on_quit=when_ready(lambda c: c.quitIn.emit()),
        on_quiet=when_ready(lambda c, mode: c.quietIn.emit(mode)),
        on_reload=when_ready(lambda c: c.reloadIn.emit()),
        on_status=when_ready(lambda c: json.dumps(c.status()), default="{}"),
        on_notice=when_ready(lambda c, text: c.notify_json(text), default="YALW is still starting"),
    )
    if not runtime.start(control):
        print("YALW is already running.", file=sys.stderr)
        return 1

    app, engine, controller, _window = _build(cfg, backend, runtime)
    holder["controller"] = controller
    log.info("display backend: %s", backend)

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    from PySide6.QtCore import QTimer
    keepalive = QTimer()                      # lets Python run its signal handlers
    keepalive.start(400)
    keepalive.timeout.connect(lambda: None)

    runtime.submit(_start_watchers(runtime, controller))
    controller.extensions = ExtensionHost(cfg, controller.noticeIn.emit)
    controller.extensions.start()
    app.aboutToQuit.connect(controller.extensions.stop)
    app.aboutToQuit.connect(runtime.stop)
    code = app.exec()
    del engine
    return code


def snapshot(cfg: Config, out_dir: Path) -> int:
    """Render every card state to PNG files (on a throw-away window)."""
    backend = display.choose_backend(cfg.backend)
    display.configure_environment(backend)
    app, engine, controller, window = _build(cfg, backend, Runtime())

    from PySide6.QtCore import QMetaObject, QObject, QTimer
    from PySide6.QtGui import QImage, QLinearGradient, QPainter, QColor

    out_dir.mkdir(parents=True, exist_ok=True)
    scenes = [
        ("media-new", "new", False), ("media-hover", "new", True), ("media-paused", "pause", False),
        ("media-next", "next", False), ("media-prev-hover", "prev", True),
        ("bt-headphones", "bluetooth", False), ("bt-low", "bluetooth-low", False),
        ("bt-charging", "bluetooth-charging", False), ("bt-keyboard", "bluetooth-keyboard", False),
        ("bt-nobattery", "bluetooth-speaker", False),
        ("notice-charger", "charger", False), ("notice-unplug", "charger-unplug", False), ("notice-generic", "notice", False),
    ]
    state = {"i": 0}

    def grab(name: str) -> None:
        shot = window.grabWindow()
        canvas = QImage(shot.size(), QImage.Format.Format_ARGB32)
        canvas.setDevicePixelRatio(shot.devicePixelRatio())
        p = QPainter(canvas)
        logical = canvas.deviceIndependentSize()
        bg = QLinearGradient(0, 0, logical.width(), logical.height())
        bg.setColorAt(0, QColor("#4a5a78"))
        bg.setColorAt(1, QColor("#8aa0b8"))
        p.fillRect(0, 0, int(logical.width()), int(logical.height()), bg)
        p.drawImage(0, 0, shot)
        p.end()
        canvas.save(str(out_dir / f"{name}.png"))
        island = window.findChild(QObject, "island")
        log.info("saved %s  slide=%.2f size=%.0fx%.0f at (%.0f,%.0f) opacity=%.2f", name,
                 island.property("slide"), island.property("width"), island.property("height"),
                 island.property("x"), island.property("y"), island.property("opacity"))

    def step() -> None:
        if state["i"] >= len(scenes):
            app.quit()
            return
        name, kind, hover = scenes[state["i"]]
        window.setProperty("forceHover", hover)
        controller._on_demo(kind)
        QTimer.singleShot(1900, lambda: (grab(name), QMetaObject.invokeMethod(window, "dismiss"),
                                         QTimer.singleShot(700, step)))
        state["i"] += 1

    if scenes:
        # `pause`/`prev` need a baseline track; prime the demo silently first.
        controller._on_demo("new")
        QMetaObject.invokeMethod(window, "dismiss")
        QTimer.singleShot(900, step)
    app.exec()
    del engine
    return 0
