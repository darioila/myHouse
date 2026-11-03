# SPDX-License-Identifier: GPL-3.0-or-later
"""Scheda "Piani" nel pannello laterale di IngeTrazo.

Elenco dei piani dall'alto in basso. Clic = piano di lavoro (quello proposto
ai nuovi muri/solai); doppio clic o ✎ = finestra dei piani; "+" = nuovo piano
in cima; tasto destro = modifica / elimina.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QToolButton,
    QVBoxLayout, QWidget,
)

from . import piani

_ID = Qt.UserRole


class PianiPanel(QWidget):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        head = QHBoxLayout()
        title = QLabel("Piani")
        f = QFont(title.font())
        f.setBold(True)
        title.setFont(f)
        head.addWidget(title)
        head.addStretch(1)
        edit = QToolButton()
        edit.setText("✎")
        edit.setToolTip("Modifica i piani…")
        edit.clicked.connect(lambda: piani.edit_levels(self.app.viewport))
        head.addWidget(edit)
        add = QToolButton()
        add.setText("+")
        add.setToolTip("Aggiungi un piano in cima")
        add.clicked.connect(self._add)
        head.addWidget(add)
        lay.addLayout(head)

        self.list = QListWidget()
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.itemClicked.connect(self._clicked)
        self.list.itemDoubleClicked.connect(
            lambda _it: piani.edit_levels(self.app.viewport))
        self.list.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.list, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self.refresh)
        self._bound = None
        self._seeded = None
        self.refresh()

    # ---- dati ------------------------------------------------------------
    def _bind(self) -> None:
        vp = self.app.viewport
        if vp is self._bound:
            return
        self._bound = vp
        sig = getattr(vp, "sceneVersionChanged", None)
        if sig is not None:
            sig.connect(lambda *_: self._timer.start())

    def refresh(self) -> None:
        vp = self.app.viewport
        if vp is None:
            return
        self._bind()
        if id(vp.scene) != self._seeded:       # una volta per disegno aperto
            self._seeded = id(vp.scene)
            piani.ensure_default_levels(vp)
        scene = vp.scene
        act = piani.active_id(scene)
        self.list.clear()
        for lv in reversed(piani.levels(scene)):        # il più alto in cima
            quota = "±0.00" if abs(lv["z"]) < 0.005 else f"{lv['z']:+.2f}"
            it = QListWidgetItem()
            it.setData(_ID, lv["id"])
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(4, 0, 2, 0)
            lab = QLabel(f"{lv['name']}    {quota} m   (h {lv['h']:.2f})")
            lab.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            groups = self._groups_of(scene, lv["id"])
            hidden = bool(groups) and all(g.hidden for g in groups)
            if lv["id"] == act:
                f = QFont(lab.font())
                f.setBold(True)
                lab.setFont(f)
                lab.setStyleSheet("color: #7fb3ff;")
            elif hidden:
                lab.setStyleSheet("color: #6b7280;")
            h.addWidget(lab, 1)
            eye = QToolButton()
            eye.setText("⊘" if hidden else "👁")
            eye.setAutoRaise(True)
            eye.setToolTip("Mostra gli elementi del piano" if hidden
                           else "Nascondi gli elementi del piano")
            eye.setEnabled(bool(groups))
            eye.clicked.connect(
                lambda _=False, i=lv["id"], hd=hidden: self._toggle(i, hd))
            h.addWidget(eye)
            it.setSizeHint(row.sizeHint())
            self.list.addItem(it)
            self.list.setItemWidget(it, row)

    @staticmethod
    def _groups_of(scene, lid) -> list:
        out = []
        for g in scene.groups:
            e = piani._elem(g)
            if e is not None and e[0].get("lv") == lid:
                out.append(g)
        return out

    def _toggle(self, lid, hidden: bool) -> None:
        vp = self.app.viewport
        for g in self._groups_of(vp.scene, lid):
            g.hidden = not hidden
        vp.update()
        self.refresh()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.refresh()

    # ---- azioni ----------------------------------------------------------
    def _clicked(self, it) -> None:
        piani.set_active(it.data(_ID))
        self.refresh()

    def _add(self) -> None:
        piani.add_level_on_top(self.app.viewport)
        self.refresh()

    def _menu(self, pos) -> None:
        it = self.list.itemAt(pos)
        if it is None:
            return
        lid = it.data(_ID)
        m = QMenu(self)
        m.addAction("Modifica…", lambda: piani.edit_levels(self.app.viewport))
        m.addAction("Elimina piano", lambda: self._delete(lid))
        m.exec(self.list.viewport().mapToGlobal(pos))

    def _delete(self, lid) -> None:
        vp = self.app.viewport
        new = [lv for lv in piani.levels(vp.scene) if lv["id"] != lid]
        if piani.commit_levels(vp, new):
            self.refresh()


# ---------------------------------------------------------------------------
# Registrazione
# ---------------------------------------------------------------------------

ORDER = 999


def register(api) -> None:
    """Questo modulo contiene solo la scheda "Piani" (classe PianiPanel), che
    viene creata da piani.py. Non aggiunge pulsanti né voci di menu: la
    funzione esiste solo perché il caricatore delle estensioni di MyHouse
    la richiede in ogni file della cartella."""
    return None
