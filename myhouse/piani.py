# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr
from ._scroll import fit_dialog, scroll_form

import uuid

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor, QFont, QIcon, QPainter, QPen, QPixmap, QVector3D,
)
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import muri

ORDER = 5
KEY = "myhouse_piani"
CARRIER_NAME = tr("Piani")
NONE_LABEL = tr("Nessuno (quota libera)")

_state = {"active": None}


def _carrier(scene):
    for g in scene.groups:
        d = (getattr(g, "ext", None) or {}).get(KEY)
        if isinstance(d, dict) and "levels" in d:
            return g
    return None


def levels(scene):
    g = _carrier(scene)
    if g is None:
        return []
    out = [dict(lv) for lv in g.ext[KEY]["levels"]]
    out.sort(key=lambda lv: (lv["z"], lv["name"]))
    return out


def get(scene, level_id):
    if not level_id:
        return None
    for lv in levels(scene):
        if lv["id"] == level_id:
            return lv
    return None


def active_id(scene):
    lvs = levels(scene)
    ids = {lv["id"] for lv in lvs}
    a = _state.get("active")
    if a == "":
        return None
    if a in ids:
        return a
    return lvs[0]["id"] if lvs else None


def set_active(level_id) -> None:
    _state["active"] = level_id or ""


def _store(scene, lvls) -> None:
    data = {"levels": [dict(lv) for lv in lvls]}
    g = _carrier(scene)
    if g is None:
        from core.group import Group
        g = Group(name=CARRIER_NAME)
        g.component = False
        g.ext = {KEY: data}
        scene.groups.append(g)
    else:
        ext = dict(g.ext or {})
        ext[KEY] = data
        g.ext = ext


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def level_combo(scene, current):
    cb = QComboBox()
    cb.addItem(NONE_LABEL, "")
    for lv in levels(scene):
        cb.addItem(tr("{0}  (quota {1:.2f} m)").format(lv['name'], lv['z']), lv["id"])
    cb.setCurrentIndex(max(0, cb.findData(current or "")))
    return cb


def level_props(d):
    if not d.get("lv"):
        return []
    from ._imperial import fmt_len
    return [(tr("Piano"), d.get("lvn", "?")),
            (tr("Distanza dal piano"), fmt_len(d.get("off", 0.0)))]


def _target_h(lvs, tlv, toff, level_id, base_z):
    if not tlv:
        return None
    if tlv == "next":
        start = next((lv for lv in lvs if lv["id"] == level_id), None)
        ref = start["z"] if start else base_z
        above = [lv for lv in lvs if lv["z"] > ref + 1e-6]
        dest = min(above, key=lambda lv: lv["z"]) if above else None
    else:
        dest = next((lv for lv in lvs if lv["id"] == tlv), None)
    if dest is None:
        return None
    h = dest["z"] + (toff or 0.0) - base_z
    return h if h > 1e-6 else None


def height_for(scene, tlv, toff, level_id, base_z):
    return _target_h(levels(scene), tlv, toff, level_id, base_z)


def add_top_rows(form, scene, height_spin, tlv, toff):
    cb = QComboBox()
    cb.addItem(tr("Altezza propria (quella indicata)"), "")
    cb.addItem(tr("Piano successivo"), "next")
    for lv in levels(scene):
        cb.addItem(tr("{0}  (quota {1:.2f} m)").format(lv['name'], lv['z']), lv["id"])
    cb.setCurrentIndex(max(0, cb.findData(tlv or "")))
    off = muri._spin(toff or 0.0, -100.0, 100.0)

    def sync(_i=0) -> None:
        linked = bool(cb.currentData())
        off.setEnabled(linked)
        height_spin.setEnabled(not linked)

    cb.currentIndexChanged.connect(sync)
    sync()
    form.addRow(tr("Altezza fino a"), cb)
    form.addRow(tr("Distanza dalla quota di arrivo (m, + sopra / - sotto)"), off)
    return cb, off


_KINDS: dict = {}


def register_kind(name, key, data, zget, zset, rebuild=None,
                  hget=None, hset=None) -> None:
    _KINDS[name] = {"name": name, "key": key, "data": data, "zget": zget,
                    "zset": zset, "rebuild": rebuild,
                    "hget": hget, "hset": hset}


def place(scene, level_id, off, base=0.0):
    lv = get(scene, level_id)
    if lv:
        return lv["z"] + off, {"lv": lv["id"], "lvn": lv["name"], "off": off}
    return base + off, {}


def _elem(group):
    for kind in _KINDS.values():
        d = kind["data"](group)
        if d is not None:
            return d, kind
    return None


def _write(group, kind, d, rebuild) -> None:
    if rebuild and kind["rebuild"] is not None:
        kind["rebuild"](group, d)
    ext = dict(group.ext or {})
    ext[kind["key"]] = d
    group.ext = ext


def apply_levels(scene, new_levels) -> None:
    new_levels = sorted(new_levels, key=lambda lv: (lv["z"], lv["name"]))
    old = {lv["id"]: lv for lv in levels(scene)}
    nd = {lv["id"]: lv for lv in new_levels}
    for g in list(scene.groups):
        e = _elem(g)
        if e is None or not e[0].get("lv"):
            continue
        d, kind = e
        d = dict(d)
        lid = d["lv"]
        if lid not in nd:
            for k in ("lv", "lvn", "off"):
                d.pop(k, None)
            _write(g, kind, d, False)
            continue
        lv = nd[lid]
        delta = lv["z"] - old.get(lid, lv)["z"]
        renamed = d.get("lvn") != lv["name"]
        if abs(delta) > 1e-9:
            kind["zset"](d, kind["zget"](d) + delta)
            d["lvn"] = lv["name"]
            _write(g, kind, d, True)
        elif renamed:
            d["lvn"] = lv["name"]
            _write(g, kind, d, False)
    for g in list(scene.groups):
        e = _elem(g)
        if e is None or not e[0].get("tlv") or e[1].get("hset") is None:
            continue
        d, kind = e
        d = dict(d)
        h = _target_h(new_levels, d["tlv"], d.get("toff", 0.0), d.get("lv"),
                      kind["zget"](d))
        if h is None:
            d.pop("tlv", None)
            d.pop("toff", None)
            _write(g, kind, d, False)
        elif kind["hget"] is None or abs(kind["hget"](d) - h) > 1e-9:
            kind["hset"](d, h)
            _write(g, kind, d, True)
    _store(scene, new_levels)


def _refresh(scene) -> None:
    try:
        from . import finestre
        finestre.update_openings(scene)
    except ImportError:
        pass
    muri.update_roof_clips(scene)


_DLG = {"dlg": None}


def _levels_dialog(parent, lvls, on_apply):
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("Piani"))
    dlg.setModal(False)
    dlg.setWindowModality(Qt.NonModal)
    dlg.setAttribute(Qt.WA_DeleteOnClose, True)
    fit_dialog(dlg, 560, 340)
    lay = QVBoxLayout(dlg)
    info = QLabel(tr("Quota = pavimento finito del piano. Se cambi la quota, "
                  "muri e solai di quel piano si spostano con lui. "
                  "Altezza = altezza del singolo piano (valore proposto "
                  "ai nuovi muri)."))
    info.setWordWrap(True)
    lay.addWidget(info)
    table = QTableWidget(0, 3)
    table.setHorizontalHeaderLabels([tr("Nome"), tr("Quota (m)"), tr("Altezza (m)")])
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    table.setSelectionBehavior(QTableWidget.SelectRows)
    lay.addWidget(table)

    def add_row(lv) -> None:
        r = table.rowCount()
        table.insertRow(r)
        item = QTableWidgetItem(lv["name"])
        item.setData(Qt.UserRole, lv["id"])
        table.setItem(r, 0, item)
        table.setCellWidget(r, 1, muri._spin(lv["z"], -100.0, 1000.0))
        table.setCellWidget(r, 2, muri._spin(lv["h"], 0.1, 100.0))

    def collect():
        out = []
        for r in range(table.rowCount()):
            it = table.item(r, 0)
            out.append({"id": it.data(Qt.UserRole),
                        "name": it.text().strip() or tr("Piano {0}").format(r + 1),
                        "z": table.cellWidget(r, 1).value(),
                        "h": table.cellWidget(r, 2).value()})
        return out

    base = {"v": [dict(lv) for lv in lvls]}

    def show(items) -> None:
        table.setRowCount(0)
        for lv in items:
            add_row(lv)

    def load(items) -> None:
        base["v"] = [dict(lv) for lv in items]
        show(items)

    def add_new() -> None:
        cur = collect()
        z = max((lv["z"] + lv["h"] for lv in cur), default=0.0)
        name = tr("Piano {0}").format(len(cur)) if cur else tr("Piano terra")
        add_row({"id": new_id(), "name": name, "z": z, "h": 3.0})

    def remove() -> None:
        r = table.currentRow()
        if r < 0:
            return
        name = table.item(r, 0).text().strip() or tr("Piano {0}").format(r + 1)
        if QMessageBox.question(
                dlg, tr("Elimina piano"),
                tr("Eliminare \"{0}\"?\nI suoi elementi restano dove sono ma diventano liberi (dopo Applica).").format(name),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No) == QMessageBox.Yes:
            table.removeRow(r)

    def move(step) -> None:
        r = table.currentRow()
        r2 = r + step
        if r < 0 or r2 < 0 or r2 >= table.rowCount():
            return
        cur = collect()
        lo, hi = (r, r2) if r < r2 else (r2, r)
        a, b = cur[lo], cur[hi]
        gap = b["z"] - (a["z"] + a["h"])
        z0 = a["z"]
        b["z"] = z0
        a["z"] = z0 + b["h"] + gap
        cur[lo], cur[hi] = b, a
        show(cur)
        table.selectRow(r2)

    def apply() -> None:
        new = collect()
        old = {lv["id"]: lv for lv in base["v"]}
        moved = [lv["name"] for lv in new if lv["id"] in old
                 and abs(lv["z"] - old[lv["id"]]["z"]) > 1e-9]
        gone = [o["name"] for i, o in old.items()
                if i not in {lv["id"] for lv in new}]
        if not moved and not gone and new == base["v"]:
            return
        msg = [tr("Applicare le modifiche ai piani?")]
        if moved:
            msg.append(tr("Quota cambiata (muri e solai si spostano): ")
                       + ", ".join(moved))
        if gone:
            msg.append(tr("Piani eliminati (elementi liberi): ")
                       + ", ".join(gone))
        if QMessageBox.question(
                dlg, tr("Conferma"), "\n\n".join(msg),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes) == QMessageBox.Yes:
            on_apply(new)

    load(lvls)
    row = QHBoxLayout()
    b_add = QPushButton(tr("Aggiungi piano"))
    b_del = QPushButton(tr("Elimina piano"))
    b_up = QPushButton(tr("\u25B2 Sposta su"))
    b_dn = QPushButton(tr("\u25BC Sposta gi\u00f9"))
    b_add.clicked.connect(add_new)
    b_del.clicked.connect(remove)
    b_up.clicked.connect(lambda: move(1))
    b_dn.clicked.connect(lambda: move(-1))
    row.addWidget(b_add)
    row.addWidget(b_del)
    row.addWidget(b_up)
    row.addWidget(b_dn)
    row.addStretch(1)
    lay.addLayout(row)
    note = QLabel(tr("Eliminando un piano, i suoi elementi restano dove sono "
                  "ma diventano liberi."))
    note.setWordWrap(True)
    lay.addWidget(note)
    box = QDialogButtonBox()
    b_apply = box.addButton(tr("Applica"), QDialogButtonBox.AcceptRole)
    b_close = box.addButton(tr("Chiudi"), QDialogButtonBox.RejectRole)
    b_apply.clicked.connect(apply)
    b_close.clicked.connect(dlg.close)
    lay.addWidget(box)
    dlg.reload = load
    dlg.destroyed.connect(lambda *_: _DLG.update(dlg=None))
    return dlg


def commit_levels(viewport, new) -> bool:
    sc = viewport.scene
    if getattr(sc, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return False

    def mutate(s):
        apply_levels(s, new)
        _refresh(s)

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("{0} piani").format(len(new)), 3000)
    return True


def add_level_on_top(viewport) -> None:
    cur = levels(viewport.scene)
    z = max((lv["z"] + lv["h"] for lv in cur), default=0.0)
    name = tr("Piano {0}").format(len(cur)) if cur else tr("Piano terra")
    new = cur + [{"id": new_id(), "name": name, "z": z, "h": 3.0}]
    if commit_levels(viewport, new):
        set_active(new[-1]["id"])


def ensure_default_levels(viewport) -> None:
    if levels(viewport.scene):
        return
    ground = {"id": new_id(), "name": tr("Piano terra"), "z": 0.0, "h": 3.0}
    roof = {"id": new_id(), "name": tr("Piano copertura"), "z": 3.0, "h": 3.0}
    if commit_levels(viewport, [ground, roof]):
        set_active(ground["id"])


def edit_levels(viewport) -> None:
    scene = viewport.scene
    cur = levels(scene)
    if not cur:
        cur = [{"id": new_id(), "name": tr("Piano terra"), "z": 0.0, "h": 3.0}]

    dlg = _DLG["dlg"]
    if dlg is not None:
        try:
            dlg.reload(cur)
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            return
        except RuntimeError:
            _DLG["dlg"] = None

    def on_apply(new) -> None:
        if commit_levels(viewport, new):
            d = _DLG["dlg"]
            if d is not None:
                d.reload(levels(viewport.scene))

    dlg = _levels_dialog(viewport.window(), cur, on_apply)
    _DLG["dlg"] = dlg
    dlg.show()


def _selected_elems(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and _elem(g) is not None and g not in out:
            out.append(g)
    return out


def assign_to_level(viewport, groups=None) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    groups = groups or _selected_elems(scene)
    if not groups:
        viewport.flash_status(tr("Seleziona muri o solai"), 3000)
        return
    if not levels(scene):
        viewport.flash_status(tr("Prima crea i piani: MyHouse > Piani"), 4000)
        return
    first = _elem(groups[0])[0]
    dlg = QDialog(viewport.window())
    dlg.setWindowTitle(tr("Assegna al piano ({0} elementi)").format(len(groups)))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    cb = level_combo(scene, first.get("lv"))
    off = muri._spin(first.get("off", 0.0), -100.0, 1000.0)
    form.addRow(tr("Piano"), cb)
    form.addRow(tr("Distanza dal piano (m)"), off)
    scroll_form(dlg, lay, form)
    hint = QLabel(tr("Distanza dal piano: base del muro, faccia superiore del "
                  "solaio, faccia inferiore di pilastri e travi, quota di "
                  "partenza delle scale, gronda del tetto, punto più basso "
                  "delle balaustre. Con \"Nessuno\" l'elemento resta alla "
                  "quota attuale."))
    hint.setWordWrap(True)
    lay.addWidget(hint)
    cb.currentIndexChanged.connect(
        lambda _i: off.setEnabled(bool(cb.currentData())))
    off.setEnabled(bool(cb.currentData()))
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return
    lid, dist = cb.currentData() or None, off.value()

    def mutate(sc):
        lv = get(sc, lid)
        for g in groups:
            d, kind = _elem(g)
            d = dict(d)
            if lv:
                d.update({"lv": lv["id"], "lvn": lv["name"], "off": dist})
                kind["zset"](d, lv["z"] + dist)
            else:
                for k in ("lv", "lvn", "off"):
                    d.pop(k, None)
            if d.get("tlv") and kind.get("hset") is not None:
                h = _target_h(levels(sc), d["tlv"], d.get("toff", 0.0),
                              d.get("lv"), kind["zget"](d))
                if h is not None:
                    kind["hset"](d, h)
            _write(g, kind, d, True)
        _refresh(sc)

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("{0} elementi aggiornati").format(len(groups)), 3000)


def _icon():
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(215, 205, 190))
    p.drawRect(8, 34, 32, 7)
    p.drawRect(8, 22, 32, 7)
    p.drawRect(8, 10, 32, 7)
    p.end()
    return QIcon(pm)


def _outliner_kind(group):
    d = (getattr(group, "ext", None) or {}).get(KEY)
    if not (isinstance(d, dict) and "levels" in d):
        return None
    lvs = sorted(d["levels"], key=lambda lv: lv["z"])
    return {"type": tr("Piani"),
            "props": [(lv["name"], tr("quota {0:.2f} m · h {1:.2f} m").format(lv['z'], lv['h']))
                      for lv in lvs]}


SHOW = {"on": False, "ctl": None}
LINE_COLOR = QColor(200, 40, 40, 235)


class _PianiOverlay(QWidget):
    def __init__(self, vp, ctl) -> None:
        super().__init__(vp)
        self.ctl = ctl
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(vp.rect())
        self.show()
        self.raise_()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            self.ctl.draw(p)
        except Exception:
            pass
        finally:
            p.end()


class _PianiResize(QObject):
    def __init__(self, ctl) -> None:
        super().__init__(ctl.vp)
        self.ctl = ctl

    def eventFilter(self, obj, ev):
        if obj is self.ctl.vp and ev.type() == QEvent.Resize:
            self.ctl.overlay.setGeometry(self.ctl.vp.rect())
        return False


class _MostraPiani:
    PROBES = ((0.0, 0.0), (7.0, 3.0), (-5.0, 11.0))

    def __init__(self, vp) -> None:
        self.vp = vp
        self.overlay = _PianiOverlay(vp, self)
        self.filter = _PianiResize(self)
        vp.installEventFilter(self.filter)
        self._sig = None
        self.timer = QTimer(vp)
        self.timer.timeout.connect(self._tick)
        self.timer.start(80)

    def _y(self, x, y, z):
        px = self.vp._world_to_pixel(QVector3D(x, y, z))
        return None if px is None else px[1]

    LABEL_GAP = 1.0  # metri tra il bordo destro del 3D e il nome del piano
    _label_x = None

    def _calc_label_x(self):
        try:
            from .etichetta_id import _bbox
            lo = [1e18] * 3
            hi = [-1e18] * 3
            for g in self.vp.scene.groups:
                b = _bbox(g)
                if b:
                    for i in range(3):
                        lo[i] = min(lo[i], b[0][i])
                        hi[i] = max(hi[i], b[1][i])
            if lo[0] > 1e17:
                return None
            xs, ppm = [], 0.0
            for x in (lo[0], hi[0]):
                for y in (lo[1], hi[1]):
                    for z in (lo[2], hi[2]):
                        px = self.vp._world_to_pixel(QVector3D(x, y, z))
                        if px is not None:
                            xs.append(px[0])
            if not xs:
                return None
            cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
            p0 = self.vp._world_to_pixel(QVector3D(cx, cy, lo[2]))
            for d in ((1, 0, 0), (0, 1, 0)):
                p1 = self.vp._world_to_pixel(
                    QVector3D(cx + d[0], cy + d[1], lo[2]))
                if p0 is not None and p1 is not None:
                    ppm = max(ppm, abs(p1[0] - p0[0]))
            return max(xs) + ppm * self.LABEL_GAP
        except Exception:
            return None

    def _prospetto(self) -> bool:
        for z in (0.0, 3.0):
            ys = [self._y(x, y, z) for x, y in self.PROBES]
            if any(v is None for v in ys) or max(ys) - min(ys) > 0.75:
                return False
        a, b = self._y(0.0, 0.0, 0.0), self._y(0.0, 0.0, 3.0)
        return abs(a - b) > 4.0

    def _tick(self) -> None:
        try:
            sc = self.vp.scene
            lvs = tuple((lv["name"], lv["z"]) for lv in levels(sc))
            probe = tuple(None if v is None else round(v, 1)
                          for v in (self._y(0, 0, 0), self._y(0, 0, 1),
                                    self._y(7, 3, 0), self._y(-5, 11, 0)))
            sig = (SHOW["on"], lvs, probe, self.vp.width(), self.vp.height(),
                   len(sc.groups))
        except Exception:
            return
        if sig != self._sig:
            self._sig = sig
            self._label_x = self._calc_label_x()
            self.overlay.update()

    def draw(self, p: QPainter) -> None:
        if not SHOW["on"] or not self._prospetto():
            return
        from ._imperial import fmt_len
        w, h = self.vp.width(), self.vp.height()
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        p.setFont(font)
        fm = p.fontMetrics()
        pen = QPen(LINE_COLOR, 1.6, Qt.DashLine)
        for lv in levels(self.vp.scene):
            y = self._y(0.0, 0.0, lv["z"])
            if y is None or y < -20 or y > h + 20:
                continue
            p.setPen(pen)
            p.drawLine(QPointF(0, y), QPointF(w, y))
            text = lv["name"] + "   " + fmt_len(lv["z"])
            tw = fm.horizontalAdvance(text)
            p.setPen(QPen(LINE_COLOR))
            lx = self._label_x
            if lx is None:
                x0 = w - tw - 12
            else:
                x0 = min(max(lx, 4), w - tw - 12)
            p.drawText(QRectF(x0, y - fm.height() - 3, tw + 4, fm.height()),
                       Qt.AlignLeft | Qt.AlignVCenter, text)


def toggle_piani(viewport) -> None:
    SHOW["on"] = not SHOW["on"]
    ctl = SHOW["ctl"]
    if ctl is None:
        ctl = SHOW["ctl"] = _MostraPiani(viewport)
    ctl.overlay.update()
    viewport.flash_status(
        tr("Piani visibili in prospetto") if SHOW["on"]
        else tr("Piani nascosti"), 3000)


def _icon_mostra():
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(200, 40, 40), 2, Qt.DashLine))
    for y in (12, 24, 36):
        p.drawLine(4, y, 44, y)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(215, 205, 190))
    p.drawRect(14, 14, 20, 20)
    p.end()
    return QIcon(pm)


def register(api) -> None:
    app = api.app

    def run() -> None:
        edit_levels(app.viewport)

    api.add_button(tr("Piani"), tr("Definisci i piani (quote) dell'edificio"),
                   _icon(), run, group="Piani", main=True)
    api.add_button(tr("Mostra piani"),
                   tr("Mostra o nasconde in prospetto le linee tratteggiate dei piani "
                      "con nome e altezza da terra"),
                   _icon_mostra(), lambda: toggle_piani(app.viewport),
                   group="Piani")
    add_panel = getattr(app, "add_panel", None)
    if add_panel is not None:
        from .piani_panel import PianiPanel
        add_panel(tr("Piani"), PianiPanel(app))
    QTimer.singleShot(0, lambda: ensure_default_levels(app.viewport))
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        def context(menu, selection) -> None:
            if not _selected_elems(app.viewport.scene):
                return
            menu.addSeparator()
            menu.addAction(
                tr("Assegna al piano…"),
                lambda: QTimer.singleShot(
                    0, lambda: assign_to_level(app.viewport)))

        add_ctx(context)
    add_kind = getattr(app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
