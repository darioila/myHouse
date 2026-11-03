# SPDX-License-Identifier: GPL-3.0-or-later
"""MyHouse — plugin per IngeTrazo, una barra degli strumenti con tante funzioni.

Installazione: copia la cartella  myhouse/  in
    ~/.local/share/ingetrazo/plugins/          (Linux)
    %APPDATA%\\ingetrazo\\plugins\\               (Windows)
(Extensions > Open plugins folder) e riavvia IngeTrazo. Se avevi il vecchio
muri.py singolo, cancellalo.

Come aggiungere una funzione
----------------------------
1. Crea un nuovo file .py in questa cartella (es. porte.py): copia
   _modello.py e cambia nome, icona e strumento.
2. Il file deve avere una funzione  register(api)  che chiama
   api.add_button(...). Opzionale:  ORDER = numero  (posizione nella barra).
3. Riavvia IngeTrazo: il pulsante compare nella barra MyHouse e nel menu
   Extensions > MyHouse. Non serve modificare questo file.

Regole
------
- I file che iniziano con "_" non sono funzioni: usali per codice condiviso
  (es. _comuni.py, importato con  from ._comuni import ...).
- Un file con un errore non blocca gli altri: il suo pulsante diventa una
  voce grigia "⚠ nome (errore)" con il messaggio nel suggerimento.
- Dentro ai file usa import relativi per i file del plugin (from . import x)
  e import normali per IngeTrazo (from core import bim, from tools.base ...).
"""
from __future__ import annotations

import importlib
import logging
import pkgutil

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QToolBar

log = logging.getLogger("ingetrazo.plugins")

TITLE = "MyHouse"


class Api:
    """Quello che ogni file funzione riceve in register(api)."""

    def __init__(self, app, bar, menu) -> None:
        self.app = app
        self.window = app.window
        self.bar = bar
        self.menu = menu

    def add_button(self, text, tip, icon, fn, shortcut=None):
        """Pulsante nella barra (e voce nel menu): chiama fn() al clic."""
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
        self.bar.addAction(action)
        if self.menu is not None:
            self.menu.addAction(action)
        return action

    def add_separator(self) -> None:
        self.bar.addSeparator()

    def run_tool(self, tool):
        """Per add_button: avvia uno strumento (un oggetto Tool) di IngeTrazo."""
        window = self.window
        return lambda: tool.on_activate(window.viewport)


def _load_features():
    """Importa ogni file funzione; ritorna (ok, errori) ordinati per ORDER."""
    ok, errors = [], []
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"{__name__}.{info.name}")
            if not callable(getattr(mod, "register", None)):
                raise AttributeError("manca la funzione register(api)")
            ok.append((getattr(mod, "ORDER", 100), info.name, mod))
        except Exception as exc:                    # noqa: BLE001
            log.exception("myhouse: errore nel file %r", info.name)
            errors.append((info.name, f"{type(exc).__name__}: {exc}"))
    ok.sort(key=lambda t: (t[0], t[1]))
    return ok, errors


def setup(app) -> None:
    win = app.window
    make_bar = getattr(win, "_new_toolbar", None)
    if make_bar is not None:                 # barra come le altre di IngeTrazo
        bar = make_bar(TITLE, "myhouse_toolbar")
    else:
        bar = QToolBar(TITLE, win)
        bar.setObjectName("myhouse_toolbar")
        win.addToolBar(bar)
    api = Api(app, bar, app.add_menu(TITLE))

    features, errors = _load_features()
    for _order, name, mod in features:
        try:
            mod.register(api)
        except Exception as exc:                    # noqa: BLE001
            log.exception("myhouse: register() fallita in %r", name)
            errors.append((name, f"{type(exc).__name__}: {exc}"))

    for name, message in errors:
        action = QAction(f"\u26a0 {name} (errore)", win)
        action.setEnabled(False)
        action.setToolTip(message)
        if api.menu is not None:
            api.menu.addAction(action)
