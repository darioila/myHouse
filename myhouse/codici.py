# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._scroll import fit_dialog
from ._lingua import tr
from ._imperial import LengthSpin

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QHeaderView,
    QInputDialog, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

from . import _codici, etichetta_id

ORDER = 96


def _sort_key(item):
    g, cat = item
    code = _codici.code_of(g, cat) or ""
    num = _codici._number(cat, code)
    return (cat, 0 if num is not None else 1, num or 0, code)


class CodiciDialog(QDialog):
    def __init__(self, viewport) -> None:
        super().__init__(viewport.window())
        self.vp = viewport
        self.setWindowTitle(tr("Codici ID degli elementi"))
        fit_dialog(self, 640, 460)
        try:
            _codici.assign_missing(viewport.scene)
        except Exception:
            pass
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.addItem(tr("Tutte le categorie"), None)
        for cat, (_p, label) in _codici.PREFIX.items():
            self.filter.addItem(tr(label), cat)
        self.filter.currentIndexChanged.connect(lambda _i: self.fill())
        top.addWidget(self.filter, 1)
        lay.addLayout(top)
        from PySide6.QtWidgets import QDoubleSpinBox, QLabel
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel(tr("Dimensione testo etichette ID (m)")))
        self.size_sp = LengthSpin()
        self.size_sp.setDecimals(3)
        self.size_sp.setRange(0.01, 20.0)
        self.size_sp.setSingleStep(0.05)
        self.size_sp.setValue(etichetta_id.current_size(viewport.scene))
        self.size_sp.setToolTip(tr("Vale per tutte le etichette ID: cambiandola "
                                   "si aggiornano tutte"))
        self.size_sp.setKeyboardTracking(False)
        self.size_sp.valueChanged.connect(self._size_changed)
        size_row.addWidget(self.size_sp)
        size_row.addStretch(1)
        lay.addLayout(size_row)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [tr("Codice"), tr("Categoria"), tr("Nome")])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.doubleClicked.connect(lambda _i: self.rename())
        lay.addWidget(self.table)
        row = QHBoxLayout()
        for text, fn in ((tr("Rinomina…"), self.rename),
                         (tr("Seleziona nel disegno"), self.select)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, f=fn: f())
            row.addWidget(b)
        row.addStretch(1)
        close = QPushButton(tr("Chiudi"))
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)
        self.items: list = []
        self.fill()

    def _size_changed(self, v: float) -> None:
        n = etichetta_id.set_size_all(self.vp, v)
        self.vp.flash_status(
            tr("Dimensione testo etichette ID: {0} m · aggiornate {1}"
               ).format(round(v, 3), n), 3000)

    def fill(self, keep=None) -> None:
        cat_f = self.filter.currentData()
        els = [e for e in _codici.elements(self.vp.scene)
               if cat_f is None or e[1] == cat_f]
        els.sort(key=_sort_key)
        self.items = els
        self.table.setRowCount(len(els))
        for r, (g, cat) in enumerate(els):
            d = (g.ext or {}).get(_codici.EXT_CATEGORY_KEY.get(cat, "")) or {}
            if cat != "plinto":
                for k, c in _codici.EXT_CATEGORY.items():
                    if c == cat and isinstance((g.ext or {}).get(k), dict):
                        d = g.ext[k]
                        break
            name = d.get("name") or ""
            self.table.setItem(r, 0, QTableWidgetItem(_codici.code_of(g, cat) or ""))
            self.table.setItem(r, 1, QTableWidgetItem(tr(_codici.PREFIX[cat][1])))
            self.table.setItem(r, 2, QTableWidgetItem(str(name)))
        if keep is not None:
            for r, (g, cat) in enumerate(els):
                if g is keep[0] and cat == keep[1]:
                    self.table.selectRow(r)

    def _current(self):
        r = self.table.currentRow()
        return self.items[r] if 0 <= r < len(self.items) else None

    def rename(self) -> None:
        cur = self._current()
        if cur is None:
            return
        g, cat = cur
        old = _codici.code_of(g, cat) or ""
        text, ok = QInputDialog.getText(self, tr("Rinomina codice"),
                                        tr("Codice (ID)"), text=old)
        if not ok or text.strip() == old:
            return
        done, why = _codici.set_code(self.vp.scene, g, cat, text)
        if not done:
            QMessageBox.warning(
                self, tr("Codice (ID)"),
                tr("Codice già usato da un altro elemento: non cambiato.")
                if why == "duplicate" else tr("Codice vuoto: non cambiato."))
            return
        self.fill(keep=cur)

    def select(self) -> None:
        cur = self._current()
        if cur is None:
            return
        scene = self.vp.scene
        try:
            scene.select([cur[0]])
        except Exception:
            try:
                scene.selection.clear()
                scene.selection.add(cur[0])
            except Exception:
                return
        self.vp.update()


def open_codici(viewport) -> None:
    CodiciDialog(viewport).exec()


def _safe_assign(vp) -> None:
    scene = vp.scene
    if getattr(scene, "edit_group", None) is not None:
        return
    try:
        if _codici.assign_missing(scene):
            vp.update()
    except Exception:
        pass


def _hook(vp) -> None:
    if getattr(vp, "_myhouse_codici_hook", False):
        return
    timer = QTimer()
    timer.setSingleShot(True)
    timer.setInterval(300)
    timer.timeout.connect(lambda: _safe_assign(vp))
    poll = QTimer()
    poll.setInterval(2000)
    poll.timeout.connect(lambda: _safe_assign(vp))
    poll.start()
    vp._myhouse_codici_timers = (timer, poll)
    original = getattr(vp, "notify_scene_changed", None)
    if callable(original):
        def notify(*a, **kw):
            r = original(*a, **kw)
            timer.start()
            return r
        vp.notify_scene_changed = notify
    vp._myhouse_codici_hook = True


def _icon():
    from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(235, 235, 225))
    p.drawRoundedRect(6, 12, 36, 24, 4, 4)
    f = QFont()
    f.setBold(True)
    f.setPixelSize(15)
    p.setFont(f)
    p.drawText(6, 12, 36, 24, Qt.AlignCenter, "M01")
    p.end()
    return QIcon(pm)


def register(api) -> None:
    api.add_button(tr("Codici ID"),
                   tr("Elenco dei codici (ID) degli elementi: rinomina e seleziona"),
                   _icon(), lambda: open_codici(api.window.viewport), group="Piani")
    try:
        _hook(api.window.viewport)
        _safe_assign(api.window.viewport)
    except Exception:
        pass
