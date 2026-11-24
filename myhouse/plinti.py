# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr
from ._imperial import LengthSpin
from ._scroll import scroll_form

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QMatrix4x4, QPen, QVector3D
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QVBoxLayout,
)

from tools.base import Tool, ToolContext

from . import _codici, _tipi, muri, pilastri

ORDER = 42
PICK_TOL = 0.08


TYPES = [("rect", tr("Rettangolare")), ("tap", tr("Trapezoidale"))]


class _Settings:
    tipo = "rect"
    L = 1.00
    P = 1.00
    H = 0.50
    dz = 0.0
    Hv = 0.25
    Lt = 0.0
    Pt = 0.0
    bs = 0.10
    bh = 0.10
    tipo_id = None
    tipo_nome = None


KEYS = ("tipo", "L", "P", "H", "dz", "Hv", "Lt", "Pt", "bs", "bh")


def _params() -> dict:
    return {k: getattr(_Settings, k) for k in KEYS + ("tipo_id", "tipo_nome")}


def _disegno_plinto(p):
    r, tx, dim, ext = muri._r, muri._t, muri._dim, muri._ext
    tx(p, 10, 12, tr("Pianta"), size=9)
    r(p, 20, 45, 120, 125, muri._C_CORPO)
    r(p, 32, 57, 108, 113, QColor(235, 235, 235))
    r(p, 59, 75, 81, 95, QColor(255, 255, 255))
    dim(p, 32, 36, 108, 36, "L", 1)
    dim(p, 24, 57, 24, 113, "P", -1)
    dim(p, 20, 134, 32, 134, "s", -1)
    tx(p, 200, 12, tr("Prospetto"), size=9)
    p.setPen(QPen(muri._C_LINEA, 1.5))
    p.drawLine(QPointF(180, 158), QPointF(420, 158))
    r(p, 285, 20, 315, 70, QColor(255, 255, 255))
    r(p, 235, 100, 365, 126, muri._C_CORPO)
    p.setPen(QPen(muri._C_LINEA, 1.2))
    p.setBrush(QColor(235, 235, 235))
    from PySide6.QtGui import QPolygonF
    p.drawPolygon(QPolygonF([QPointF(235, 100), QPointF(365, 100),
                             QPointF(322, 70), QPointF(278, 70)]))
    r(p, 220, 126, 380, 140, muri._C_CORPO)
    dim(p, 395, 70, 395, 126, "H", 1)
    dim(p, 222, 100, 222, 126, "Hv", -1)
    dim(p, 395, 126, 395, 140, "Hb", 1)
    ext(p, 315, 70, 400, 70)
    tx(p, 330, 66, tr("dz = 0"), size=8)


def _spin(value, lo, hi):
    s = LengthSpin()
    s.setDecimals(3)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


def ask_params(parent, cur: dict, title: str, groups=None, scene=None):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(muri._Schema(_disegno_plinto))
    tipo = QComboBox()
    for key, label in TYPES:
        tipo.addItem(label, key)
    tipo.setCurrentIndex(max(0, tipo.findData(cur["tipo"])))
    L = _spin(cur["L"], 0.02, 50.0)
    P = _spin(cur["P"], 0.02, 50.0)
    H = _spin(cur["H"], 0.02, 50.0)
    dz = _spin(cur["dz"], -50.0, 50.0)
    Hv = _spin(cur["Hv"], 0.0, 50.0)
    Lt = _spin(cur["Lt"], 0.0, 50.0)
    Pt = _spin(cur["Pt"], 0.0, 50.0)
    bs = _spin(cur["bs"], 0.0, 5.0)
    bh = _spin(cur["bh"], 0.0, 5.0)
    form.addRow(tr("Tipo di plinto"), tipo)
    ws = {"tipo": tipo, "L": L, "P": P, "H": H, "dz": dz, "Hv": Hv,
          "Lt": Lt, "Pt": Pt, "bs": bs, "bh": bh}
    _get, _set = _tipi.widgets_io(ws)
    tbar = _tipi.TypeBar(dlg, form, "plinto", cur, _get, _set, scene,
                         creating=not groups)
    cf = (_codici.CodeField(form, groups, "plinto", scene, at=2)
          if groups else None)
    form.addRow(tr("Lunghezza (L) (m)"), L)
    form.addRow(tr("Larghezza (P) (m)"), P)
    form.addRow(tr("Altezza verso il basso (H) (m)"), H)
    form.addRow(tr("Parte verticale in basso (Hv) (m) - solo trapezoidale"), Hv)
    form.addRow(tr("Lunghezza in alto (m) - solo trapezoidale, 0 = pilastro + 5 cm"), Lt)
    form.addRow(tr("Larghezza in alto (m) - solo trapezoidale, 0 = pilastro + 5 cm"), Pt)
    form.addRow(tr("Distanza faccia superiore dalla base del pilastro (dz) (m)"),
                dz)
    form.addRow(tr("Base sotto il plinto: sporgenza per lato (s) (m)"), bs)
    form.addRow(tr("Base sotto il plinto: altezza (Hb) (m) - 0 = nessuna base"), bh)
    scroll_form(dlg, lay, form)

    def sync() -> None:
        on = tipo.currentData() == "tap"
        for w in (Hv, Lt, Pt):
            w.setEnabled(on)
            lbl = form.labelForField(w)
            if lbl is not None:
                lbl.setEnabled(on)

    tipo.currentIndexChanged.connect(lambda _i: sync())
    sync()
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return None
    if cf is not None:
        cf.apply(dlg)
    return tbar.result(_get())


def _world_matrix(g) -> QMatrix4x4:
    gx = getattr(g, "xform", None)
    m = QMatrix4x4(gx) if gx is not None else QMatrix4x4()
    for k in getattr(g, "children", None) or ():
        if getattr(k, "xform", None) is not None:
            return m * QMatrix4x4(k.xform)
    return m


def _pillars(scene):
    return [g for g in scene.groups if pilastri.pillar_data(g) is not None]


def _dist_to_poly(pt, poly) -> float:
    x, y = pt
    inside = True
    best = 1e9
    n = len(poly)
    sign = 0
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        cr = (bx - ax) * (y - ay) - (by - ay) * (x - ax)
        if abs(cr) > 1e-12:
            s = 1 if cr > 0 else -1
            if sign == 0:
                sign = s
            elif s != sign:
                inside = False
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
        best = min(best, math.hypot(x - (ax + t * dx), y - (ay + t * dy)))
    return 0.0 if inside else best


def _world_footprint(g):
    d = pilastri.pillar_data(g)
    m = _world_matrix(g)
    zb, zt = d["z0"], d["z0"] + d["h"]
    pts = [m.map(QVector3D(x, y, zb)) for x, y in pilastri.footprint(d)]
    top = m.map(QVector3D(d["c"][0], d["c"][1], zt)).z()
    return [(p.x(), p.y()) for p in pts], pts[0].z(), top


def _owner_pillar(obj):
    g = getattr(obj, "owner", None) or obj
    return g if pilastri.pillar_data(g) is not None else None


def pillar_at(ctx: ToolContext):
    for attr in ("entity", "hit", "picked", "obj", "target", "group"):
        g = _owner_pillar(getattr(ctx, attr, None))
        if g is not None:
            return g
    scene = ctx.viewport.scene
    w = ctx.world
    best, best_key = None, None
    for g in _pillars(scene):
        try:
            poly, zb, zt = _world_footprint(g)
        except Exception:
            continue
        dist = _dist_to_poly((w.x(), w.y()), poly)
        if dist > PICK_TOL:
            continue
        gap = max(zb - w.z(), w.z() - zt, 0.0)
        key = (round(dist, 3), gap)
        if best_key is None or key < best_key:
            best, best_key = g, key
    return best


class PlintoTool(Tool):
    name = tr("Plinto")
    shortcut = None
    description = tr("Aggiunge un plinto di fondazione sotto i pilastri.")

    def __init__(self) -> None:
        self._entering = False
        self._hover = None

    def on_activate(self, viewport) -> None:
        self._vp = viewport
        if self._entering:
            self._hover = None
            viewport.flash_status(
                tr("Plinto: clic su un pilastro per applicarlo · Esc = esci"),
                6000)
            return
        p = ask_params(viewport.window(), _params(), tr("Plinto"),
                       scene=viewport.scene)
        if p is None:
            return
        for k, v in p.items():
            setattr(_Settings, k, v)
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def on_deactivate(self, viewport) -> None:
        self._hover = None

    def on_cancel(self, viewport) -> None:
        self._hover = None
        viewport.update()

    def _exit(self, viewport) -> None:
        self._hover = None
        viewport.update()
        back = getattr(viewport.window(), "activate_select_tool", None)
        if callable(back):
            back()

    def context_menu(self, viewport, pos) -> bool:
        self._exit(viewport)
        return True

    def claims_key(self, key: int, modifiers) -> bool:
        if modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        return key == Qt.Key_Escape

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        return False

    def on_hover(self, ctx: ToolContext) -> None:
        self._hover = pillar_at(ctx)
        ctx.viewport.update()

    def rubber_band_lines(self):
        g = self._hover
        if g is None or pilastri.pillar_data(g) is None:
            return []
        d = dict(pilastri.pillar_data(g))
        d["plinto"] = _params()
        m = _world_matrix(g)
        P = QVector3D
        lines = []
        for lo, zl, hi, zh, _kind in pilastri.plinth_solids(d):
            n = len(lo)
            for i in range(n):
                j = (i + 1) % n
                lines.append((m.map(P(*lo[i], zl)), m.map(P(*lo[j], zl))))
                lines.append((m.map(P(*hi[i], zh)), m.map(P(*hi[j], zh))))
                lines.append((m.map(P(*lo[i], zl)), m.map(P(*hi[i], zh))))
        return lines

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        if getattr(vp.scene, "edit_group", None) is not None:
            vp.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        g = pillar_at(ctx)
        if g is None:
            vp.flash_status(tr("Plinto: clicca su un pilastro"), 3000)
            return
        pl = _params()

        def mutate(scene):
            pilastri.rebuild_pillar(g, {"plinto": pl})
            try:
                muri.update_roof_clips(scene)
            except Exception:
                pass

        vp.history.execute(muri.MuriCommand(mutate))
        vp.notify_scene_changed()
        vp.flash_status(tr("Plinto applicato al pilastro"), 2500)
        vp.update()


def edit_plinti(viewport, groups=None) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    groups = groups or pilastri._selected_pillars(scene)
    groups = [g for g in groups
              if (pilastri.pillar_data(g) or {}).get("plinto")]
    if not groups:
        viewport.flash_status(tr("Seleziona un pilastro con plinto"), 3000)
        return
    cur = dict(_params())
    cur.update({k: v for k, v in pilastri.pillar_data(groups[0])["plinto"].items()
                if k in KEYS + ("tipo_id", "tipo_nome")})
    cur["tipo_id"] = pilastri.pillar_data(groups[0])["plinto"].get("tipo_id")
    p = ask_params(viewport.window(), cur, tr("Modifica plinto"),
                   groups=groups, scene=scene)
    if p is None:
        return
    st = _tipi.resolve_edit(viewport.window(), scene, "plinto", p)
    if st == "cancel":
        return

    def mutate(sc):
        for g in groups:
            pilastri.rebuild_pillar(g, {"plinto": dict(p)})
        if st == "type":
            _tipi.update_instances(
                sc, "plinto", p["tipo_id"],
                lambda g, q: pilastri.rebuild_pillar(g, {"plinto": q}))
        try:
            muri.update_roof_clips(sc)
        except Exception:
            pass

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("{0} plinti aggiornati").format(len(groups)), 3000)


def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(200, 198, 190))
    p.drawRect(19, 4, 10, 22)
    p.setBrush(QColor(150, 148, 140))
    p.drawRect(8, 26, 32, 16)
    p.end()
    return QIcon(pm)


def register(api) -> None:
    api.add_button(tr("Plinto"), tr("Aggiunge un plinto di fondazione sotto i pilastri"),
                   _icon(), api.run_tool(PlintoTool()))
