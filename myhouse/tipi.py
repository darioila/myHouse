# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._scroll import fit_dialog
from ._lingua import tr

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QInputDialog, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QHeaderView,
    QAbstractItemView,
)

from . import _tipi

ORDER = 95

CATS = (("muro", "Muri"), ("porta", "Porte"), ("finestra", "Finestre"),
        ("pilastro", "Pilastri"), ("trave", "Travi"), ("solaio", "Solai"),
        ("tetto", "Tetti"), ("plinto", "Plinti"), ("platea", "Platee"),
        ("trave_rovescia", "Travi rovesce"), ("scala", "Scale"),
        ("balaustra", "Balaustre"), ("recinzione", "Recinzioni"))


class _Tab(QTableWidget):
    def __init__(self, cat: str) -> None:
        super().__init__(0, 3)
        self.cat = cat
        self.setHorizontalHeaderLabels([tr("Tipo"), tr("Oggetti"), tr("Parametri")])
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        h = self.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        self.ids: list[str] = []

    def fill(self, scene) -> None:
        lib = _tipi.load(self.cat)
        used = _tipi.usage(scene, self.cat) if scene is not None else {}
        rows = sorted(lib.items(), key=lambda kv: kv[1]["nome"].lower())
        self.ids = [tid for tid, _t in rows]
        self.setRowCount(len(rows))
        for r, (tid, t) in enumerate(rows):
            self.setItem(r, 0, QTableWidgetItem(t["nome"]))
            n = QTableWidgetItem(str(used.get(tid, 0)))
            n.setTextAlignment(Qt.AlignCenter)
            self.setItem(r, 1, n)
            self.setItem(r, 2, QTableWidgetItem(_tipi.summary(self.cat, t["p"])))

    def current_id(self):
        r = self.currentRow()
        return self.ids[r] if 0 <= r < len(self.ids) else None


class TipiDialog(QDialog):
    def __init__(self, viewport) -> None:
        super().__init__(viewport.window())
        self.vp = viewport
        self.setWindowTitle(tr("Gestione tipi"))
        fit_dialog(self, 720, 420)
        try:
            _tipi.sync_all(viewport.scene)
            _tipi.assign_untyped(viewport.scene)
        except Exception:
            pass
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tab = {}
        for cat, label in CATS:
            t = _Tab(cat)
            self.tab[cat] = t
            self.tabs.addTab(t, tr(label))
        lay.addWidget(self.tabs)
        row = QHBoxLayout()
        for text, fn in ((tr("Rinomina…"), self._rename),
                         (tr("Duplica…"), self._dup),
                         (tr("Elimina"), self._delete)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, f=fn: f())
            row.addWidget(b)
        row.addStretch(1)
        for text, fn in ((tr("Apri nella cartella"), self._open_folder),
                         (tr("Esporta…"), self._export),
                         (tr("Importa…"), self._import)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, f=fn: f())
            row.addWidget(b)
        close = QPushButton(tr("Chiudi"))
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)
        self.refresh()

    def _open_folder(self) -> None:
        import os
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        f = _tipi._file()
        if not f:
            QMessageBox.warning(self, tr("Tipi"),
                                tr("Cartella dei tipi non disponibile"))
            return
        d = os.path.dirname(f)
        if not os.path.isfile(f):
            _tipi._write(_tipi._all(f), f)
        QDesktopServices.openUrl(QUrl.fromLocalFile(d))

    def _cur(self):
        t = self.tabs.currentWidget()
        return t.cat, t.current_id()

    def refresh(self) -> None:
        for t in self.tab.values():
            t.fill(self.vp.scene)

    def _rename(self) -> None:
        cat, tid = self._cur()
        if not tid:
            return
        old = _tipi.load(cat)[tid]["nome"]
        nome, ok = QInputDialog.getText(self, tr("Rinomina tipo"),
                                        tr("Nome del tipo"), text=old)
        if ok and nome.strip() and _tipi.rename_type(cat, tid, nome):
            self._rename_instances(cat, tid, nome.strip())
            self.refresh()

    def _rename_instances(self, cat, tid, nome) -> None:
        for g in _tipi.instances(self.vp.scene, cat, tid):
            d = dict(_tipi.get_params(g, cat))
            d[_tipi.NAME_KEY] = nome
            _tipi.set_params(g, cat, d)

    def _dup(self) -> None:
        cat, tid = self._cur()
        if not tid:
            return
        old = _tipi.load(cat)[tid]["nome"]
        nome, ok = QInputDialog.getText(self, tr("Duplica tipo"),
                                        tr("Nome del tipo"), text=old + " 2")
        if ok and nome.strip():
            _tipi.duplicate_type(cat, tid, nome)
            self.refresh()

    def _delete(self) -> None:
        cat, tid = self._cur()
        if not tid:
            return
        if len(_tipi.load(cat)) <= 1:
            QMessageBox.information(self, tr("Elimina tipo"),
                                    tr("Deve esistere almeno un tipo."))
            return
        n = len(_tipi.instances(self.vp.scene, cat, tid))
        if n:
            QMessageBox.information(
                self, tr("Elimina tipo"),
                tr("Il tipo è usato da {0} oggetti: assegna loro un altro "
                   "tipo prima di eliminarlo.").format(n))
            return
        msg = tr("Eliminare il tipo «{0}»?").format(_tipi.load(cat)[tid]["nome"])
        if QMessageBox.question(self, tr("Elimina tipo"), msg) != QMessageBox.Yes:
            return
        _tipi.delete_type(cat, tid)
        self.refresh()

    def _export(self) -> None:
        path, _f = QFileDialog.getSaveFileName(
            self, tr("Esporta tipi"), "tipi_myhouse.json", "JSON (*.json)")
        if not path:
            return
        try:
            n = _tipi.export_types(path)
        except OSError as exc:
            QMessageBox.warning(self, tr("Esporta tipi"), str(exc))
            return
        QMessageBox.information(self, tr("Esporta tipi"),
                                tr("{0} tipi esportati.").format(n))

    def _import(self) -> None:
        path, _f = QFileDialog.getOpenFileName(
            self, tr("Importa tipi"), "", "JSON (*.json)")
        if not path:
            return
        try:
            a, r, s = _tipi.import_types(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr("Importa tipi"),
                                tr("File non valido: {0}").format(exc))
            return
        self.refresh()
        QMessageBox.information(
            self, tr("Importa tipi"),
            tr("Aggiunti: {0} · già presenti: {1} · "
               "importati con altro nome: {2}").format(a, s, r))


def open_manager(viewport) -> None:
    TipiDialog(viewport).exec()


def _hook_scene_changes(vp) -> None:
    if getattr(vp, "_myhouse_tipi_hook", False):
        return
    original = getattr(vp, "notify_scene_changed", None)
    if not callable(original):
        return
    timer = QTimer()
    vp._myhouse_tipi_timer = timer
    timer.setSingleShot(True)
    timer.setInterval(1500)
    timer.timeout.connect(lambda: _safe_sync(vp))

    def notify(*a, **kw):
        r = original(*a, **kw)
        timer.start()
        return r

    vp.notify_scene_changed = notify
    vp._myhouse_tipi_hook = True


def _safe_sync(vp) -> None:
    try:
        _tipi.sync_all(vp.scene)
        _tipi.assign_untyped(vp.scene)
    except Exception:
        pass


def _icon():
    from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    for i, c in enumerate(((200, 198, 190), (170, 190, 215), (215, 185, 170))):
        p.setBrush(QColor(*c))
        p.drawRoundedRect(8 + i * 3, 8 + i * 11, 30, 10, 3, 3)
    p.end()
    return QIcon(pm)


def register(api) -> None:
    api.add_button(tr("Tipi"),
                   tr("Gestione dei tipi: muri, porte, finestre, pilastri, "
                      "travi, solai, tetti, plinti, platee, travi rovesce, "
                      "scale, balaustre, recinzioni"),
                   _icon(), lambda: open_manager(api.window.viewport), group="Piani")
    try:
        _tipi.migrate_old_layer_types()
    except Exception:
        pass
    try:
        _hook_scene_changes(api.window.viewport)
        _safe_sync(api.window.viewport)
    except Exception:
        pass
