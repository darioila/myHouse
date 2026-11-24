# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr
from ._imperial import LengthSpin
from ._scroll import scroll_form

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPen, QVector3D
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QSpinBox, QVBoxLayout,
)

from core import bim
from . import _ifc
from tools.base import Tool, ToolContext

from . import muri, tetto

ORDER = 53
LAYER_NAME = "Comignoli"
KEY = "myhouse_comignolo"
COLOR_RAME = (0.72, 0.38, 0.20)
AFFONDO = 0.03
SPESSORE_PIASTRA = 0.025
SPORGENZA_PIASTRA = 0.04

TIPI = (
    ("LAMELLE", tr("A lamelle (F430)")),
    ("TORRETTA", tr("Torretta a falde")),
    ("PIRAMIDE", tr("Padiglione (F100)")),
    ("DISCHI", tr("A dischi (F105)")),
)
_ETICHETTA_N = {"TORRETTA": tr("Gradini tetto (n)"), "DISCHI": tr("Dischi (n)")}


class _Settings:
    tipo = "LAMELLE"
    w = 0.60
    l = 0.60
    h = 0.50
    n = 4


def _axes(a, b):
    g = math.hypot(a, b)
    ey = (a / g, b / g) if g > 1e-6 else (0.0, 1.0)
    ex = (ey[1], -ey[0])
    return ex, ey


def _orient(solids):
    out = []
    for faces in solids:
        pts = [p for f in faces for p in f]
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        cz = sum(p[2] for p in pts) / len(pts)
        for f in faces:
            nx = ny = nz = 0.0
            for i in range(len(f)):
                p, q = f[i], f[(i + 1) % len(f)]
                nx += (p[1] - q[1]) * (p[2] + q[2])
                ny += (p[2] - q[2]) * (p[0] + q[0])
                nz += (p[0] - q[0]) * (p[1] + q[1])
            fx = sum(p[0] for p in f) / len(f)
            fy = sum(p[1] for p in f) / len(f)
            fz = sum(p[2] for p in f) / len(f)
            if nx * (fx - cx) + ny * (fy - cy) + nz * (fz - cz) < 0:
                f = list(reversed(f))
            out.append(f)
    return out


def chimney_faces(d):
    W = max(float(d["w"]), 0.10)
    L = max(float(d["l"]), 0.10)
    H = max(float(d["h"]), 0.15)
    n = max(int(d["n"]), 1)
    tipo = d.get("tipo", "LAMELLE")
    cx, cy = d["c"]
    a, b, c = d["pl"]
    ex, ey = _axes(a, b)

    def zr(x, y):
        return a * (cx + ex[0] * x + ey[0] * y) + b * (cy + ex[1] * x + ey[1] * y) + c

    def P(x, y, z):
        return (cx + ex[0] * x + ey[0] * y, cy + ex[1] * x + ey[1] * y, z)

    hw, hl = W / 2.0, L / 2.0
    z_hi = max(zr(sx * hw, sy * hl) for sx in (-1, 1) for sy in (-1, 1))
    z_top = z_hi + H
    solids = []

    def box(x0, x1, y0, y1, za, zb):
        v = [P(x, y, z) for z in (za, zb)
             for (x, y) in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        f = [[v[i], v[(i + 1) % 4], v[4 + (i + 1) % 4], v[4 + i]] for i in range(4)]
        f += [v[0:4], v[4:8]]
        solids.append(f)

    def zoccolo(z_sommita):
        ang = ((-hw, -hl), (hw, -hl), (hw, hl), (-hw, hl))
        vb = [P(x, y, zr(x, y) - AFFONDO) for x, y in ang]
        vt = [P(x, y, z_sommita) for x, y in ang]
        f = [[vb[i], vb[(i + 1) % 4], vt[(i + 1) % 4], vt[i]] for i in range(4)]
        f += [vb, vt]
        solids.append(f)

    def montanti(za, zb):
        p = min(0.035, W / 6.0, L / 6.0)
        for sx in (-1, 1):
            for sy in (-1, 1):
                x0, x1 = sorted((sx * hw, sx * (hw - p)))
                y0, y1 = sorted((sy * hl, sy * (hl - p)))
                box(x0, x1, y0, y1, za, zb)

    def lamelle_anelli(za, zb, quante):
        passo = (zb - za) / quante
        h_lam = passo * 0.55
        bt = min(0.04, W / 4.0, L / 4.0)
        for k in range(quante):
            z0 = za + k * passo + passo * 0.225
            z1 = z0 + h_lam
            sp = 0.025 if (k % 2 == 1) else 0.0
            A, B = hw + sp, hl + sp
            box(-A, A, -B, -B + bt, z0, z1)
            box(-A, A, B - bt, B, z0, z1)
            box(-A, -A + bt, -B + bt, B - bt, z0, z1)
            box(A - bt, A, -B + bt, B - bt, z0, z1)

    def ellisse(rx, ry, zf, seg=24):
        return [P(rx * math.cos(2 * math.pi * i / seg),
                  ry * math.sin(2 * math.pi * i / seg),
                  zf(rx * math.cos(2 * math.pi * i / seg),
                     ry * math.sin(2 * math.pi * i / seg))) for i in range(seg)]

    def tronco(r0, r1):
        m = len(r0)
        f = [[r0[i], r0[(i + 1) % m], r1[(i + 1) % m], r1[i]] for i in range(m)]
        f += [r0, r1]
        solids.append(f)

    if tipo == "TORRETTA":
        h_tetto = max(H * 0.30, 0.08)
        z_c = z_top - h_tetto
        zoccolo(z_c)
        h_corpo = z_c - z_hi
        zf0 = z_hi + 0.55 * h_corpo
        pas = 0.30 * h_corpo / 3.0
        e = 0.012
        for k in range(3):
            za_, zb_ = zf0 + k * pas, zf0 + k * pas + pas * 0.5
            box(-0.3 * W, 0.3 * W, -hl - e, -hl, za_, zb_)
            box(-0.3 * W, 0.3 * W, hl, hl + e, za_, zb_)
            box(-hw - e, -hw, -0.3 * L, 0.3 * L, za_, zb_)
            box(hw, hw + e, -0.3 * L, 0.3 * L, za_, zb_)
        passi = max(n, 2)
        sp = 0.05
        dz = h_tetto / passi
        for k in range(passi):
            semi = (hw + sp) * (1.0 - k / passi)
            box(-semi, semi, -hl - sp, hl + sp, z_c + k * dz,
                z_c + (k + 1) * dz + (0.01 if k < passi - 1 else 0.0))
    elif tipo == "PIRAMIDE":
        h_tetto = max(H * 0.30, 0.08)
        z_r = z_top - h_tetto
        z_pl = z_hi + min(0.10, H * 0.18)
        zoccolo(z_pl)
        montanti(z_pl, z_r)
        lamelle_anelli(z_pl, z_r, n)
        sp = 0.06
        base = [P(x, y, z_r) for x, y in
                ((-hw - sp, -hl - sp), (hw + sp, -hl - sp), (hw + sp, hl + sp), (-hw - sp, hl + sp))]
        apice = P(0.0, 0.0, z_top)
        solids.append([[base[i], base[(i + 1) % 4], apice] for i in range(4)] + [base])
    elif tipo == "DISCHI":
        rx_t, ry_t = hw * 0.42, hl * 0.42
        tronco(ellisse(rx_t, ry_t, lambda x, y: zr(x, y) - AFFONDO),
               ellisse(rx_t, ry_t, lambda x, y: z_top))
        zona = min(max(0.45 * H, n * 0.05), H * 0.9)
        passo = zona / n
        z_d0 = z_top - zona
        for k in range(n):
            f = max(1.0 - 0.12 * k, 0.5)
            za_ = z_d0 + k * passo
            zb_ = za_ + passo * 0.6
            tronco(ellisse(hw * f, hl * f, lambda x, y: za_),
                   ellisse(hw * f * 0.55, hl * f * 0.55, lambda x, y: zb_))
    else:
        z_pl = z_hi + min(0.08, H * 0.25)
        z_lam_fine = z_top - SPESSORE_PIASTRA
        zoccolo(z_pl)
        montanti(z_pl, z_lam_fine)
        lamelle_anelli(z_pl, z_lam_fine, n)
        sp = SPORGENZA_PIASTRA
        box(-hw - sp, hw + sp, -hl - sp, hl + sp, z_lam_fine, z_top)
    return _orient(solids)


def chimney_mesh(d):
    from core.mesh import Mesh
    mesh = Mesh()
    for pts in chimney_faces(d):
        f = mesh.add_face([QVector3D(*p) for p in pts])
        f.attrs["layer"] = LAYER_NAME
        muri.paint_face(f, d.get("col", COLOR_RAME), d.get("tex"))
    return mesh


def chimney_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "pl" in data else None


def _chimney_part(d):
    from core.group import Group
    part = Group(chimney_mesh(d), name=tr("Comignolo"))
    part.component = False
    return part


def rebuild_chimney(group, d) -> None:
    group.children = [_chimney_part(d)]
    _ifc.tag(group, "IfcChimney")
    ext = dict(group.ext or {})
    ext[KEY] = dict(d)
    group.ext = ext


def build_chimney(scene, d, name) -> None:
    from core.group import Group
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    g = Group(name=name)
    g.adopt([_chimney_part(d)])
    g.component = False
    g.layer = LAYER_NAME
    try:
        _ifc.tag(g, "IfcChimney", name)
    except Exception:
        try:
            _ifc.tag(g, "IfcBuildingElementProxy", name)
        except Exception:
            pass
    g.ext = {KEY: d}
    scene.groups.append(g)


def roof_under(scene, x, y, z=0.0):
    try:
        from shapely.geometry import LineString, LinearRing, Point
        from shapely.geometry.polygon import orient
        from shapely.ops import polygonize, unary_union
    except ImportError:
        return None
    best = None
    for g in scene.groups:
        rd = tetto.roof_data(g)
        if rd is None:
            continue
        M = tetto._group_matrix(g)
        Mi = M.inverted()[0]
        loc = Mi.map(QVector3D(x, y, z))
        poly = [tuple(p) for p in rd["poly"]]
        if tetto._area(poly) < 0:
            poly.reverse()
        dd = dict(rd, poly=poly)
        geoms = [LinearRing(poly)] + [LineString(ln) for ln in rd["lines"]]
        pt = Point(loc.x(), loc.y())
        for region in polygonize(unary_union(geoms)):
            if not region.buffer(1e-6).contains(pt):
                continue
            ring = list(orient(region, 1.0).exterior.coords)[:-1]
            top = [(px, py, tetto._z_at(dd, px, py)) for px, py in ring]
            if not tetto._is_planar(top):
                continue
            loc_pl = tetto._plane(top)
            if loc_pl is None:
                continue
            la, lb, lc = loc_pl
            pts = [M.map(QVector3D(u, v, la * u + lb * v + lc))
                   for u, v in ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0))]
            wpl = tetto._plane([(p.x(), p.y(), p.z()) for p in pts])
            if wpl is None:
                continue
            zc = wpl[0] * x + wpl[1] * y + wpl[2]
            if best is None or zc > best[1]:
                best = (wpl, zc)
    return best


def _spin(value, lo, hi):
    s = LengthSpin()
    s.setDecimals(3)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


def _dim_grande(p, x1, y1, x2, y2, txt, lato=1):
    p.setPen(QPen(muri._C_QUOTA, 1.3))
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    w = 8 * len(txt) + 2
    if abs(y1 - y2) < 1e-6:
        for x in (x1, x2):
            p.drawLine(QPointF(x, y1 - 3), QPointF(x, y1 + 3))
        muri._t(p, (x1 + x2) / 2 - w / 2, y1 + (-5 if lato > 0 else 14), txt, muri._C_QUOTA, 14, True)
    else:
        for y in (y1, y2):
            p.drawLine(QPointF(x1 - 3, y), QPointF(x1 + 3, y))
        muri._t(p, x1 + (6 if lato > 0 else -w - 4), (y1 + y2) / 2 + 5, txt, muri._C_QUOTA, 14, True)


def _disegno_comignolo(p):
    r, t, dim, ext = muri._r, muri._t, _dim_grande, muri._ext
    from PySide6.QtGui import QPolygonF
    t(p, 10, 12, tr("Pianta"), size=12)
    p.setPen(QPen(muri._C_LINEA, 1.5))
    p.drawLine(QPointF(10, 140), QPointF(200, 140))
    t(p, 150, 156, tr("gronda"), size=11)
    t(p, 158, 90, "\u2191 " + tr("pendenza"), size=11)
    r(p, 50, 50, 150, 120, muri._C_LEGNO)
    dim(p, 50, 42, 150, 42, "W", 1)
    dim(p, 38, 50, 38, 120, "L", -1)
    t(p, 10, 166, tr("tondo: W, L = diametri"), size=11)
    t(p, 235, 12, tr("Sezione"), size=12)
    k = 60.0 / 115.0
    ya = lambda x: 138 - (x - 235) * k
    p.setPen(QPen(muri._C_LINEA, 1.5))
    p.drawLine(QPointF(235, 138), QPointF(360, ya(360)))
    t(p, 262, 154, tr("falda"), size=11)
    xl, xr, top = 262.0, 322.0, ya(322) - 48
    p.setPen(QPen(muri._C_LINEA, 1.2))
    p.setBrush(muri._C_LEGNO)
    p.drawPolygon(QPolygonF([QPointF(xl, ya(xl)), QPointF(xr, ya(xr)),
                             QPointF(xr, top), QPointF(xl, top)]))
    ext(p, xl, 36, xl, top)
    ext(p, xr, 36, xr, top)
    dim(p, xl, 36, xr, 36, "L", 1)
    ext(p, xr, top, 336, top)
    ext(p, xr, ya(xr), 336, ya(xr))
    dim(p, 336, top, 336, ya(xr), "H", 1)
    t(p, 385, 12, tr("Lamelle"), size=12)
    r(p, 400, 44, 450, 120, muri._C_BIANCO)
    for y in (54, 70, 86, 102):
        r(p, 396, y, 454, y + 6, muri._C_LEGNO)
    t(p, 385, 142, "n = " + tr("numero"), size=11)
    t(p, 385, 156, tr("lamelle, gradini"), size=11)
    t(p, 385, 168, tr("o dischi"), size=11)


def ask_chimney(parent, cur: dict, title=None):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title or tr("Comignolo"))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(muri._Schema(_disegno_comignolo))
    tipo = QComboBox()
    for k, nome in TIPI:
        tipo.addItem(nome, k)
    tipo.setCurrentIndex(max(0, tipo.findData(cur.get("tipo", "LAMELLE"))))
    w = _spin(cur["w"], 0.10, 10.0)
    l = _spin(cur["l"], 0.10, 10.0)
    h = _spin(cur["h"], 0.15, 10.0)
    n = QSpinBox()
    n.setRange(1, 30)
    n.setValue(int(cur["n"]))
    form.addRow(tr("Tipo"), tipo)
    form.addRow(tr("Larghezza, lungo la gronda (W) (m)"), w)
    form.addRow(tr("Lunghezza, lungo la pendenza (L) (m)"), l)
    form.addRow(tr("Altezza dal punto piu' alto di appoggio (H) (m)"), h)
    form.addRow(tr("Lamelle / gradini / dischi (n)"), n)
    scroll_form(dlg, lay, form)

    def on_tipo(_i=None):
        et = _ETICHETTA_N.get(tipo.currentData(), tr("Lamelle (n)"))
        form.labelForField(n).setText(et)
    tipo.currentIndexChanged.connect(on_tipo)
    on_tipo()
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return None
    return {"tipo": tipo.currentData(), "w": w.value(), "l": l.value(),
            "h": h.value(), "n": n.value()}


class ComignoloTool(Tool):
    name = tr("Comignolo")
    shortcut = None
    description = tr("Inserisce un comignolo su una falda del tetto.")

    def __init__(self) -> None:
        self._entering = False
        self.hover = None

    def on_activate(self, viewport) -> None:
        self._scene = viewport.scene
        if self._entering:
            self.hover = None
            viewport.flash_status(
                tr("Clicca su una falda del tetto per inserire il comignolo. "
                   "Esc = esci"), 7000)
            return
        cur = {"tipo": _Settings.tipo, "w": _Settings.w, "l": _Settings.l,
               "h": _Settings.h, "n": _Settings.n}
        res = ask_chimney(viewport.window(), cur)
        if res is None:
            return
        _Settings.tipo, _Settings.w = res["tipo"], res["w"]
        _Settings.l, _Settings.h, _Settings.n = res["l"], res["h"], res["n"]
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def on_deactivate(self, viewport) -> None:
        self.hover = None

    def on_cancel(self, viewport) -> None:
        self.hover = None
        viewport.update()

    def _exit(self, viewport) -> None:
        self.hover = None
        viewport.update()
        back = getattr(viewport.window(), "activate_select_tool", None)
        if callable(back):
            back()

    def context_menu(self, viewport, pos) -> bool:
        self._exit(viewport)
        return True

    def claims_key(self, key: int, modifiers) -> bool:
        return key == Qt.Key_Escape

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        return False

    def _data(self, x, y, hit):
        return {"tipo": _Settings.tipo, "w": _Settings.w, "l": _Settings.l,
                "h": _Settings.h, "n": _Settings.n, "c": [x, y],
                "pl": list(hit[0]), "col": COLOR_RAME}

    def on_hover(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        x, y = ctx.world.x(), ctx.world.y()
        try:
            hit = roof_under(vp.scene, x, y, ctx.world.z())
        except Exception:
            hit = None
        self.hover = (hit, x, y) if hit else None
        vp.update()

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        if getattr(vp.scene, "edit_group", None) is not None:
            vp.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        x, y = ctx.world.x(), ctx.world.y()
        try:
            hit = roof_under(vp.scene, x, y, ctx.world.z())
        except Exception:
            hit = None
        if hit is None:
            vp.flash_status(tr("Nessuna falda del tetto sotto il cursore "
                               "(serve shapely)"), 3000)
            return
        d = self._data(x, y, hit)
        name = tr("Comignolo")

        def mutate(scene):
            build_chimney(scene, d, name)

        vp.history.execute(muri.MuriCommand(mutate))
        vp.notify_scene_changed()
        vp.flash_status(tr("Comignolo inserito"), 3000)
        vp.update()

    def draw_overlay(self, viewport, painter) -> None:
        try:
            self._draw(viewport, painter)
        except Exception:
            pass

    def _draw(self, viewport, painter) -> None:
        from PySide6.QtCore import QPointF
        if not self.hover:
            return
        hit, x, y = self.hover
        d = self._data(x, y, hit)
        ex, ey = _axes(*hit[0][:2])
        a, b, c = hit[0]
        hw, hl = _Settings.w / 2.0, _Settings.l / 2.0
        ang = ((-hw, -hl), (hw, -hl), (hw, hl), (-hw, hl))

        def pt(u, v):
            px = x + ex[0] * u + ey[0] * v
            py = y + ex[1] * u + ey[1] * v
            return (px, py, a * px + b * py + c)

        base = [pt(u, v) for u, v in ang]
        zt = max(p[2] for p in base) + _Settings.h
        alto = [(p[0], p[1], zt) for p in base]
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(0, 170, 255), 2))
        px = lambda p: viewport._world_to_pixel(QVector3D(*p))
        for i in range(4):
            j = (i + 1) % 4
            for p, q in ((base[i], base[j]), (alto[i], alto[j]), (base[i], alto[i])):
                p1, p2 = px(p), px(q)
                if p1 is not None and p2 is not None:
                    painter.drawLine(QPointF(p1[0], p1[1]), QPointF(p2[0], p2[1]))
        painter.restore()


def _selected_chimneys(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and chimney_data(g) is not None and g not in out:
            out.append(g)
    return out


def edit_chimney(viewport, group) -> None:
    if getattr(viewport.scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    d = chimney_data(group)
    if d is None:
        return
    res = ask_chimney(viewport.window(), d, tr("Modifica comignolo"))
    if res is None:
        return

    def mutate(sc):
        q = dict(d)
        q.update(res)
        rebuild_chimney(group, q)

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("Comignolo aggiornato"), 3000)


def _hook_double_click(vp) -> None:
    if getattr(vp, "_myhouse_comignolo_dbl", False):
        return
    original = vp.begin_group_edit

    def begin_group_edit(group, *args, **kwargs):
        g = getattr(group, "owner", None) or group
        if chimney_data(g) is None:
            return original(group, *args, **kwargs)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: edit_chimney(vp, g))

    vp.begin_group_edit = begin_group_edit
    vp._myhouse_comignolo_dbl = True


def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap, QPolygon
    from PySide6.QtCore import QPoint
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(170, 90, 75))
    p.drawPolygon(QPolygon([QPoint(2, 42), QPoint(46, 42), QPoint(46, 30), QPoint(2, 14)]))
    p.setBrush(QColor(184, 97, 51))
    p.drawRect(22, 8, 12, 24)
    p.drawRect(19, 4, 18, 6)
    p.end()
    return QIcon(pm)


def register(api) -> None:
    tool = ComignoloTool()
    api.add_button(tr("Comignolo"), tr("Inserisce un comignolo su una falda del tetto"),
                   _icon(), api.run_tool(tool))
    app = api.app
    _hook_double_click(api.window.viewport)
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        from PySide6.QtCore import QTimer

        def context(menu, selection) -> None:
            ch = _selected_chimneys(app.viewport.scene)
            if not ch:
                return
            menu.addSeparator()
            menu.addAction(
                tr("Modifica comignolo…"),
                lambda: QTimer.singleShot(0, lambda: edit_chimney(app.viewport, ch[0])))

        add_ctx(context)
    add_kind = getattr(app, "add_outliner_kind", None)
    if add_kind is not None:
        def kind(group):
            d = chimney_data(group)
            if d is None:
                return None
            from ._imperial import fmt_len
            return {"type": tr("Comignolo"),
                    "props": [(tr("Tipo"), dict(TIPI).get(d.get("tipo"), "")),
                              (tr("Larghezza"), fmt_len(d["w"])),
                              (tr("Lunghezza"), fmt_len(d["l"])),
                              (tr("Altezza"), fmt_len(d["h"]))]}
        add_kind(kind)
