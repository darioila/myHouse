# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from ._lingua import tr

import importlib
import sys
import types

_root = __name__.split(".")[0]
if _root != __name__ and _root not in sys.modules:
    _stub = types.ModuleType(_root)
    _stub.__path__ = []
    sys.modules[_root] = _stub
import logging
import pkgutil
import traceback

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QMenu, QToolBar, QToolButton

log = logging.getLogger("ingetrazo.plugins")

TITLE = "myHouse 1.4"
VERSION="1.4.0"

GROUPS = {
    "Tetto": ("tetto", "lucern", "comignol", "grond"),
    "Muri": ("muro", "muri", "raccord", "nicchi"),
    "Scale": ("scala", "rampa", "chiocciol"),
    "Balaustre": ("balaustr", "recinzion", "recinsion"),
    "Fondazioni": ("plinto", "rovescia", "platea"),
    "Finestre": ("finestr",),
    "Porte": ("porta", "porte"),
}


def _auto_group(text: str):
    from ._lingua import original
    t = (original(text) or "").lower()
    for name, words in GROUPS.items():
        if any(w in t for w in words):
            return name
    return None


class _Flyout:

    def __init__(self, bar, title: str) -> None:
        self.title = title
        self.btn = QToolButton(bar)
        self.btn.setPopupMode(QToolButton.MenuButtonPopup)
        self.btn.setToolButtonStyle(bar.toolButtonStyle())
        self.btn.setIconSize(bar.iconSize())
        self.menu = QMenu(self.btn)
        self.btn.setMenu(self.menu)
        bar.addWidget(self.btn)
        self.first = True

    def add(self, action, main: bool = False) -> None:
        self.menu.addAction(action)
        if self.first or main:
            self.first = False
            self._use(action)

    def _use(self, action) -> None:
        self.btn.setDefaultAction(action)
        self.btn.setToolTip(f"{tr(self.title)} — {action.text()}")


class Api:

    def __init__(self, app, bar, menu) -> None:
        self.app = app
        self.window = app.window
        self.bar = bar
        self.menu = menu
        self.last = None
        self._flyouts = {}

    def add_button(self, text, tip, icon, fn, shortcut=None, group=None, main=False):
        action = QAction(icon, text, self.window)
        action.setToolTip(f"{text} — {tip}")
        action.setStatusTip(tip)
        if shortcut:
            taken = getattr(self.window, "_ext_taken_keys", set())
            seq = QKeySequence(shortcut).toString()
            if seq and seq not in taken:
                action.setShortcut(QKeySequence(shortcut))
                taken.add(seq)
        action.triggered.connect(lambda _checked=False: fn())
        group = group or _auto_group(text)
        placed = False
        if group:
            try:
                fly = self._flyouts.get(group)
                if fly is None:
                    fly = _Flyout(self.bar, group)
                    self._flyouts[group] = fly
                fly.add(action, main)
                placed = True
            except Exception:
                log.exception("myhouse: flyout %r non creato, uso pulsante semplice", group)
        if not placed:
            self.bar.addAction(action)
        if self.menu is not None:
            self.menu.addAction(action)
        return action

    def add_separator(self) -> None:
        self.bar.addSeparator()

    def run_tool(self, tool):
        window = self.window

        def go():
            self.last = tool
            tool.on_activate(window.viewport)
        return go

    def repeat_last(self) -> None:
        tool = self.last
        vp = self.window.viewport
        if tool is None:
            vp.flash_status(tr("Nessun comando da ripetere"), 3000)
            return
        if getattr(vp.scene, "edit_group", None) is not None:
            vp.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        fn = (getattr(tool, "repeat", None) or getattr(tool, "start_same", None)
              or tool.on_activate)
        fn(vp)


def _is_select_tool(vp) -> bool:
    for attr in ("tool", "active_tool", "current_tool", "_tool", "_active_tool"):
        t = getattr(vp, attr, None)
        if t is not None and not callable(t):
            n = type(t).__name__.lower()
            return "select" in n or "selez" in n
    return False


class _RepeatOnRightClick(QObject):

    def __init__(self, api) -> None:
        super().__init__(api.window)
        self.api = api

    def eventFilter(self, obj, ev) -> bool:
        if ev.type() != QEvent.ContextMenu or self.api.last is None:
            return False
        try:
            vp = self.api.window.viewport
            if vp.scene.selection or not _is_select_tool(vp):
                return False
            QTimer.singleShot(0, self.api.repeat_last)
            return True
        except Exception:
            return False


class _DoppioTriplo(QObject):

    def __init__(self, vp, core, pannello) -> None:
        super().__init__(vp)
        self.vp = vp
        self.core = core
        self.pannello = pannello
        self._via_invio = False

    def begin(self, group, *args, **kwargs):
        if self._via_invio or getattr(self.vp.scene, "edit_group", None) is not None:
            return self.pannello(group, *args, **kwargs)
        return self.core(group, *args, **kwargs)

    def eventFilter(self, obj, ev) -> bool:
        try:
            if (ev.type() == QEvent.KeyPress
                    and ev.key() in (Qt.Key_Return, Qt.Key_Enter)
                    and not ev.isAutoRepeat()
                    and _is_select_tool(self.vp)):
                sel = list(self.vp.scene.selection)
                if not sel:
                    return False
                g = sel[0]
                g = getattr(g, "owner", None) or g

                def apri():
                    self._via_invio = True
                    try:
                        self.pannello(g)
                    finally:
                        self._via_invio = False
                QTimer.singleShot(0, apri)
                return True
        except Exception:
            log.exception("myhouse: Invio sul pannello")
        return False


def _load_features():
    ok, errors = [], []
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"{__name__}.{info.name}")
            if not callable(getattr(mod, "register", None)):
                raise AttributeError(tr("manca la funzione register(api)"))
            ok.append((getattr(mod, "ORDER", 100), info.name, mod))
        except BaseException as exc:
            log.exception("myhouse: errore nel file %r", info.name)
            errors.append((info.name, traceback.format_exc()))
    ok.sort(key=lambda t: (t[0], t[1]))
    return ok, errors


def setup(app) -> None:
    win = app.window
    make_bar = getattr(win, "_new_toolbar", None)
    if make_bar is not None:
        bar = make_bar(TITLE, "myhouse_toolbar")
    else:
        bar = QToolBar(TITLE, win)
        bar.setObjectName("myhouse_toolbar")
        win.addToolBar(bar)
    api = Api(app, bar, app.add_menu(TITLE))

    from . import _lingua
    _lingua.sync_from_app(app)
    vp0 = win.viewport
    core_begin = getattr(vp0, "begin_group_edit", None)
    features, errors = _load_features()
    for _order, name, mod in features:
        try:
            mod.register(api)
        except Exception as exc:
            log.exception("myhouse: register() fallita in %r", name)
            errors.append((name, traceback.format_exc()))

    try:
        if core_begin is not None and not getattr(vp0, "_myhouse_dt", False):
            dt = _DoppioTriplo(vp0, core_begin, vp0.begin_group_edit)
            vp0.begin_group_edit = dt.begin
            vp0.installEventFilter(dt)
            vp0._myhouse_dt = dt
    except Exception:
        log.exception("myhouse: doppio/triplo clic non installato")

    try:
        filt = _RepeatOnRightClick(api)
        win.viewport.installEventFilter(filt)
        api._repeat_filter = filt
    except Exception:
        log.exception("myhouse: filtro tasto destro non installato")
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        def ctx_repeat(menu, selection) -> None:
            if api.last is None or app.viewport.scene.selection:
                return
            nome = getattr(api.last, "name", "") or ""
            menu.addAction(tr("Ripeti: {0}").format(nome),
                           lambda: QTimer.singleShot(0, api.repeat_last))
        add_ctx(ctx_repeat)

    if errors:
        _report_errors(win, api, errors)


def _report_errors(win, api, errors) -> None:
    import os
    text = "\n".join(f"=== {n} ===\n{m}" for n, m in errors)
    try:
        path = os.path.join(os.path.dirname(__file__), "myhouse_errori.log")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    except Exception:
        pass

    def show(name, message):
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox(win)
        box.setWindowTitle(f"myHouse - errore in {name}")
        box.setText(f"Errore in {name}. Copia il testo qui sotto.")
        box.setDetailedText(message)
        box.setIcon(QMessageBox.Warning)
        box.exec()

    for name, message in errors:
        action = QAction(tr("⚠ {0} (errore)").format(name), win)
        last = message.strip().splitlines()[-1] if message.strip() else ""
        action.setToolTip(last)
        action.triggered.connect(
            lambda _c=False, n=name, m=message: show(n, m))
        if api.menu is not None:
            api.menu.addAction(action)
