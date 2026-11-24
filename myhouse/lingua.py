# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMessageBox

from . import _lingua

ORDER = 9999

_AUTO = {"it": "Automatico (come IngeTrazo / sistema)",
         "en": "Automatic (same as IngeTrazo / system)"}


def register(api) -> None:
    menu = api.menu
    if menu is None or not hasattr(menu, "addMenu"):
        return
    sub = menu.addMenu("Lingua / Language")
    group = QActionGroup(sub)
    group.setExclusive(True)
    scelta = _lingua.explicit_language()

    def choose(code) -> None:
        if code == _lingua.explicit_language():
            return
        _lingua.set_language(code or "auto")
        QMessageBox.information(
            api.window, "Lingua / Language",
            "Riavvia IngeTrazo per applicare la lingua.\n"
            "Restart IngeTrazo to apply the language.")

    voci = [(None, _AUTO["it"] + "  /  " + _AUTO["en"])] + _lingua.available()
    for code, label in voci:
        act = QAction(label, sub)
        act.setCheckable(True)
        act.setChecked(code == scelta)
        act.triggered.connect(lambda _c=False, c=code: choose(c))
        group.addAction(act)
        sub.addAction(act)
        if code is None:
            sub.addSeparator()
