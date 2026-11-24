# SPDX-License-Identifier: GPL-3.0-or-later
"""Units… in the myHouse menu: feet and inches, metric, or whatever the
document uses. Only what the dialogs show and take changes; the model stays in
metres."""
from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout,
)

from . import _imperial
from ._lingua import tr

ORDER = 9998                     # in the menu, just before Language


def ask_units(parent) -> bool:
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("Unità di myHouse"))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    box = QComboBox()
    box.addItem(tr("Segui le unità del documento"), "auto")
    box.addItem(tr("Piedi e pollici"), "imperial")
    box.addItem(tr("Metrico"), "metric")
    box.setCurrentIndex(max(0, box.findData(_imperial.setting())))
    form.addRow(tr("Lunghezze nelle finestre di myHouse"), box)
    lay.addLayout(form)
    note = QLabel(tr(
        "Il modello non cambia: cambia solo come le misure vengono mostrate e "
        "digitate. Le misure proposte da ogni strumento per un nuovo oggetto "
        "passano da quelle americane a quelle metriche al prossimo avvio di "
        "IngeTrazo."))
    note.setWordWrap(True)
    lay.addWidget(note)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    lay.addWidget(buttons)
    if dlg.exec() != QDialog.Accepted:
        return False
    _imperial.set_setting(box.currentData())
    return True


def register(api) -> None:
    menu = api.menu
    if menu is None:
        return
    action = QAction(tr("Unità…"), api.window)
    action.setStatusTip(tr("Piedi e pollici o metrico nelle finestre di myHouse"))
    action.triggered.connect(lambda _checked=False: ask_units(api.window))
    menu.addSeparator()
    menu.addAction(action)
