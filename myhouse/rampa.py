# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr
from ._imperial import FT, IN, LengthSpin, dflt
from ._scroll import scroll_form

import copy
import math
import uuid

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPen, QVector3D
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QLineEdit, QVBoxLayout,
)

from core import bim
from . import _ifc
from tools.base import Tool, ToolContext

from . import _codici, muri, piani

ORDER = 71
LAYER_NAME = "Rampe"
KEY = "myhouse_rampa"
MAX_POINTS = 6
MAX_SLOPE = 0.08
EPS = 1e-9

PAINT_KEYS = ("col_top", "tex_top", "col_side", "tex_side")
RAMP_ZONES = (("top", tr("pavimento rampa (parte superiore)")),
              ("side", tr("struttura rampa (parte laterale)")))
TOP_COLOR = (0.70, 0.70, 0.68)
SIDE_COLOR = (0.88, 0.86, 0.82)
ZONE_DEFAULT = {"top": TOP_COLOR, "side": SIDE_COLOR}
ZONE_MAT = {"top": tr("pavimento rampa"), "side": tr("struttura rampa")}


class _Settings:
    w = dflt(36 * IN, 1.50)
    height = dflt(24 * IN, 0.50)
    z = 0.0
    name = tr("Rampa")
    ortho = True
    side = "left"
    kind = "piena"
    th = dflt(6 * IN, 0.15)
    level = None
    tlv = None
    toff = 0.0
    rail = None
    col_top = list(TOP_COLOR)
    tex_top = None
    col_side = list(SIDE_COLOR)
    tex_side = None


def _rect(a, u, s0, s1, hw):
    ax, ay = a
    ux, uy = u
    vx, vy = -uy, ux
    def pt(s, lat):
        return (ax + ux * s + vx * lat, ay + uy * s + vy * lat)
    return [pt(s0, -hw), pt(s1, -hw), pt(s1, hw), pt(s0, hw)]


def _axis_points(pts, w, side):
    off = {"left": -w / 2, "right": w / 2}.get(side, 0.0)
    if off == 0.0 or len(pts) < 2:
        return list(pts)
    normals = []
    for a, b in zip(pts, pts[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        normals.append((-dy / length, dx / length) if length > 1e-9
                       else (0.0, 0.0))
    out = []
    for i, p in enumerate(pts):
        if i == 0:
            n = normals[0]
            out.append((p[0] + n[0] * off, p[1] + n[1] * off))
        elif i == len(pts) - 1:
            n = normals[-1]
            out.append((p[0] + n[0] * off, p[1] + n[1] * off))
        else:
            n1, n2 = normals[i - 1], normals[i]
            k = 1.0 + n1[0] * n2[0] + n1[1] * n2[1]
            if k < 1e-6:
                out.append((p[0] + n1[0] * off, p[1] + n1[1] * off))
            else:
                out.append((p[0] + (n1[0] + n2[0]) * off / k,
                            p[1] + (n1[1] + n2[1]) * off / k))
    return out


def layout(d):
    w, z0 = d["w"], d["z"]
    pts = _axis_points([tuple(p) for p in d["pts"]], w, d.get("side", "center"))
    hw = w / 2
    raw = []
    m = len(pts)
    u_prev = None
    for i in range(m - 1):
        a, b = pts[i], pts[i + 1]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length < 1e-6:
            continue
        u = (dx / length, dy / length)
        if i > 0 and u_prev is not None:
            raw.append(("landing", a, u_prev, -hw, hw))
        s0 = hw if i > 0 else 0.0
        s1 = length - (hw if i + 1 < m - 1 else 0.0)
        if s1 - s0 > 1e-6:
            raw.append(("flight", a, u, s0, s1))
        u_prev = u
    total = sum(r[4] - r[3] for r in raw if r[0] == "flight")
    if total < 1e-6:
        return []
    slope = max(d.get("height", 0.0), 0.0) / total
    items = []
    z = z0
    for k, (kind, a, u, s0, s1) in enumerate(raw, 1):
        if kind == "flight":
            z1 = z + slope * (s1 - s0)
            items.append({"kind": kind, "n": k, "a": a, "u": u,
                          "s0": s0, "s1": s1, "z0": z, "z1": z1,
                          "slope": slope,
                          "body": _rect(a, u, s0, s1, hw),
                          "centre": (a[0] + u[0] * (s0 + s1) / 2,
                                     a[1] + u[1] * (s0 + s1) / 2)})
            z = z1
        else:
            items.append({"kind": kind, "n": k, "a": a, "u": u,
                          "s0": s0, "s1": s1, "z0": z, "z1": z,
                          "slope": 0.0,
                          "body": _rect(a, u, s0, s1, hw), "centre": a})
    return items


def total_length(d) -> float:
    return sum(it["s1"] - it["s0"] for it in layout(d)
               if it["kind"] == "flight")


def flight_profile(it, d):
    zb = d["z"]
    s0, s1, z0, z1 = it["s0"], it["s1"], it["z0"], it["z1"]
    slope = it["slope"]
    bottom = [(s0, zb), (s1, zb)]
    if d.get("kind", "piena") == "ca" and slope > EPS:
        dv = d.get("th", 0.15) * math.sqrt(1 + slope * slope)
        zs0, zs1 = z0 - dv, z1 - dv
        if zs1 <= zb + 1e-6:
            pass
        elif zs0 < zb:
            bottom = [(s0, zb), (s0 + (zb - zs0) / slope, zb), (s1, zs1)]
        else:
            bottom = [(s0, zs0), (s1, zs1)]
    poly = []
    for p in bottom + [(s1, z1), (s0, z0)]:
        if not poly or abs(p[0] - poly[-1][0]) + abs(p[1] - poly[-1][1]) > 1e-9:
            poly.append(p)
    if len(poly) > 1 and (abs(poly[0][0] - poly[-1][0])
                          + abs(poly[0][1] - poly[-1][1])) < 1e-9:
        poly.pop()
    return poly


def ramp_mesh(d):
    from core.mesh import Mesh
    P = QVector3D
    mesh = Mesh()
    zb = d["z"]
    hw = d["w"] / 2
    ca = d.get("kind", "piena") == "ca"

    def face(q, zone="side"):
        f = mesh.add_face(q)
        f.attrs["layer"] = LAYER_NAME
        tex = d.get("tex_" + zone)
        if muri.paint_face(f, d.get("col_" + zone), tex) \
                and not (tex and tex.get("path")):
            f.attrs["mat"] = ZONE_MAT[zone]

    def box(corners, z0, z1):
        face([P(x, y, z1) for x, y in corners], "top")
        face([P(x, y, z0) for x, y in reversed(corners)])
        for i in range(4):
            j = (i + 1) % 4
            ci, cj = corners[i], corners[j]
            face([P(ci[0], ci[1], z0), P(cj[0], cj[1], z0),
                  P(cj[0], cj[1], z1), P(ci[0], ci[1], z1)])

    for it in layout(d):
        if it["kind"] == "landing":
            z0 = it["z1"] - d.get("th", 0.15) if ca else zb
            box(it["body"], min(max(z0, zb), it["z1"] - 0.01), it["z1"])
            continue
        a, u = it["a"], it["u"]
        v = (-u[1], u[0])

        def p3(sz, lat):
            return P(a[0] + u[0] * sz[0] + v[0] * lat,
                     a[1] + u[1] * sz[0] + v[1] * lat, sz[1])

        poly = flight_profile(it, d)
        n = len(poly)
        for i in range(n):
            p, q = poly[i], poly[(i + 1) % n]
            top = abs(p[0] - it["s1"]) + abs(p[1] - it["z1"]) < 1e-9
            face([p3(p, hw), p3(q, hw), p3(q, -hw), p3(p, -hw)],
                 "top" if top else "side")
        face([p3(t_, -hw) for t_ in poly])
        face([p3(t_, hw) for t_ in reversed(poly)])
    return mesh


def apply_top(scene, d, tlv, toff, level) -> bool:
    h = piani.height_for(scene, tlv, toff, level, d["z"])
    if h is None or h <= EPS:
        return False
    d["height"] = h
    d["tlv"], d["toff"] = tlv, toff
    return True


def ramp_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "pts" in data else None


def rebuild_ramp(group, d) -> None:
    from core.group import Group
    part = Group(ramp_mesh(d), name=tr("Rampa"))
    part.component = False
    group.children = [part]
    _ifc.tag(group, "IfcRamp")
    ext = dict(group.ext or {})
    ext[KEY] = dict(d)
    group.ext = ext


def build_ramp(scene, d, name):
    from core.group import Group
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    part = Group(ramp_mesh(d), name=tr("Rampa"))
    part.component = False
    g = Group(name=name)
    g.adopt([part])
    g.component = False
    g.layer = LAYER_NAME
    _ifc.tag(g, "IfcRamp", name)
    d.setdefault("sid", uuid.uuid4().hex)
    g.ext = {KEY: d}
    scene.groups.append(g)
    return g


RAIL_OF = "myhouse_scala_of"


def railing_info(d, sides):
    w = d["w"]
    hw = w / 2
    axis = _axis_points([tuple(p) for p in d["pts"]], w, d.get("side", "center"))
    edges = {"left": _axis_points(axis, w, "right"),
             "right": _axis_points(axis, w, "left")}
    items = layout(d)
    out = []
    for name in (("left", "right") if sides == "both" else (sides,)):
        sg = 1.0 if name == "left" else -1.0
        E = edges[name]
        path = []
        for it in items:
            if it["kind"] == "flight":
                a, u = it["a"], it["u"]
                nx, ny = -u[1], u[0]
                lx, ly = nx * sg * hw, ny * sg * hw
                path.append((a[0] + u[0] * it["s0"] + lx,
                             a[1] + u[1] * it["s0"] + ly, it["z0"]))
                path.append((a[0] + u[0] * it["s1"] + lx,
                             a[1] + u[1] * it["s1"] + ly, it["z1"]))
            else:
                a = it["a"]
                i = min(range(len(axis)),
                        key=lambda k: math.hypot(axis[k][0] - a[0],
                                                 axis[k][1] - a[1]))
                path.append((E[i][0], E[i][1], it["z0"]))
        clean = []
        for q in path:
            if not clean or max(abs(q[i] - clean[-1][i])
                                for i in range(3)) > 1e-6:
                clean.append(q)
        if len(clean) >= 2:
            out.append((clean, []))
    return out


def sync_railings(scene, grp, d) -> None:
    from . import balaustre
    sid = d.get("sid")
    if not sid:
        return
    for g in [g for g in scene.groups if (g.ext or {}).get(RAIL_OF) == sid]:
        scene.groups.remove(g)
    rail = d.get("rail")
    if not rail:
        return
    for p, _treads in railing_info(d, rail["side"]):
        g = balaustre.add_railing_along(scene, p, rail["style"])
        g.ext = {**(g.ext or {}), RAIL_OF: sid}


def _rail_combos(cur):
    from . import balaustre
    rs = QComboBox()
    rs.addItem(tr("Nessuna"), None)
    rs.addItem(tr("Lato sinistro"), "left")
    rs.addItem(tr("Lato destro"), "right")
    rs.addItem(tr("Entrambi i lati"), "both")
    rk = QComboBox()
    for k, lab in balaustre.styles():
        rk.addItem(lab, k)
    cur = cur or {}
    rs.setCurrentIndex(max(0, rs.findData(cur.get("side"))))
    rk.setCurrentIndex(max(0, rk.findData(cur.get("style", "vert"))))
    return rs, rk


def _rail_value(rs, rk):
    return ({"side": rs.currentData(), "style": rk.currentData()}
            if rs.currentData() else None)


def _spin(value, lo, hi):
    s = LengthSpin()
    s.setDecimals(3)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


def _disegno_rampa(p):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPen, QPolygonF
    r, t, dim, ext = muri._r, muri._t, muri._dim, muri._ext
    t(p, 100, 12, tr("Profilo"), size=9)
    p.setPen(QPen(muri._C_LINEA, 1.5))
    p.drawLine(QPointF(10, 158), QPointF(330, 158))
    muri._hatch(p, 10, 158, 330, 162)
    top = [(40, 130), (150, 78), (200, 78), (300, 26)]
    p.setPen(QPen(muri._C_LINEA, 1.2))
    p.setBrush(muri._C_CORPO)
    poly = top + [(x, y + 16) for x, y in reversed(top)]
    p.drawPolygon(QPolygonF([QPointF(*q) for q in poly]))
    t(p, 156, 72, tr("pianerottolo"), size=8)
    dim(p, 14, 130, 14, 158, "z", -1)
    ext(p, 14, 130, 40, 130)
    dim(p, 316, 26, 316, 130, "H")
    ext(p, 40, 130, 316, 130)
    ext(p, 300, 26, 316, 26)
    dim(p, 30, 130, 30, 146, "s", -1)
    t(p, 380, 12, tr("Pianta"), size=9)
    r(p, 360, 100, 440, 130, muri._C_CORPO)
    r(p, 440, 100, 470, 130, muri._C_ANTA)
    r(p, 440, 40, 470, 100, muri._C_CORPO)
    t(p, 442, 118, "", size=8)
    pen = QPen(muri._C_LINEA, 1.2)
    pen.setStyle(Qt.DashDotLine)
    p.setPen(pen)
    p.drawLine(QPointF(355, 115), QPointF(455, 115))
    p.drawLine(QPointF(455, 115), QPointF(455, 35))
    dim(p, 352, 100, 352, 130, "L", -1)
    t(p, 362, 96, tr("sinistro"), size=8)
    t(p, 362, 142, tr("destro"), size=8)
    t(p, 380, 160, tr("linea tracciata"), size=8)


def ask_settings(parent, scene=None) -> bool:
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("Rampa"))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(muri._Schema(_disegno_rampa))
    w = _spin(_Settings.w, 0.2, 10.0)
    height = _spin(_Settings.height, 0.01, 100.0)
    z = _spin(_Settings.z, -100.0, 1000.0)
    name = QLineEdit(_Settings.name)
    side = QComboBox()
    side.addItem(tr("Lato sinistro della rampa"), "left")
    side.addItem(tr("Lato destro della rampa"), "right")
    side.addItem(tr("Asse (centro) della rampa"), "center")
    side.setCurrentIndex(max(0, side.findData(_Settings.side)))
    kind = QComboBox()
    kind.addItem(tr("Piena (piena fino a terra)"), "piena")
    kind.addItem(tr("In c.a. (soletta inclinata)"), "ca")
    kind.setCurrentIndex(max(0, kind.findData(_Settings.kind)))
    th = _spin(_Settings.th, 0.05, 1.0)
    ortho = QCheckBox(tr("Orto: rampe sempre lungo X o Y"))
    ortho.setChecked(_Settings.ortho)
    lvl = None
    if scene is not None and piani.levels(scene):
        lvl = piani.level_combo(scene, piani.active_id(scene))
        form.addRow(tr("Piano di partenza"), lvl)
    form.addRow(tr("Larghezza rampa (L) (m)"), w)
    top_cb = top_off = None
    if lvl is not None:
        top_cb, top_off = piani.add_top_rows(form, scene, _spin(3.0, 0.1, 100.0),
                                             _Settings.tlv, _Settings.toff)
    form.addRow(tr("Altezza arbitraria da raggiungere (H) (m) — se non legata "
                "a un piano"), height)
    form.addRow(tr("Quota di partenza: da terra / sopra il piano (z) (m)"), z)
    form.addRow(tr("Tipologia"), kind)
    form.addRow(tr("Spessore soletta in c.a. (s) (m)"), th)
    rs, rk = _rail_combos(_Settings.rail)
    form.addRow(tr("Balaustre"), rs)
    form.addRow(tr("Tipo di balaustra"), rk)
    paint = muri.add_paint_rows(form, lambda k: getattr(_Settings, k, None),
                                RAMP_ZONES)
    form.addRow(tr("Nome"), name)
    form.addRow(tr("La linea che traccio è"), side)
    form.addRow(ortho)
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return False
    _Settings.w, _Settings.height = w.value(), height.value()
    _Settings.z = z.value()
    _Settings.name = name.text().strip() or tr("Rampa")
    _Settings.ortho = ortho.isChecked()
    _Settings.side = side.currentData()
    _Settings.kind, _Settings.th = kind.currentData(), th.value()
    _Settings.rail = _rail_value(rs, rk)
    res = muri.paint_results(paint)
    for zone, dflt in ZONE_DEFAULT.items():
        c = res.get("col_" + zone)
        if res.get("tex_" + zone) and c and tuple(c) == tuple(dflt):
            res["col_" + zone] = None
    for k, v in res.items():
        setattr(_Settings, k, v)
    _Settings.level = (lvl.currentData() or None) if lvl is not None else None
    if lvl is not None:
        piani.set_active(_Settings.level)
    if top_cb is not None:
        _Settings.tlv = top_cb.currentData() or None
        _Settings.toff = top_off.value()
    else:
        _Settings.tlv = None
    return True


class RampaTool(Tool):
    name = tr("Rampa")
    shortcut = None
    description = tr("Crea una rampa: clic sui punti delle rampe, Invio conclude.")

    def __init__(self) -> None:
        self._entering = False
        self._reset()

    def _reset(self) -> None:
        self.points: list[tuple[float, float]] = []
        self.hover: QVector3D | None = None

    def on_activate(self, viewport) -> None:
        self._vp = viewport
        if self._entering:
            self._reset()
            viewport.flash_status(
                tr("Rampa: clic sui punti (2-6) · Invio = concludi "
                "· Spazio = capovolgi · Backspace = indietro · Esc = esci"),
                7000)
            return
        if not ask_settings(viewport.window(), viewport.scene):
            return
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def on_deactivate(self, viewport) -> None:
        self._reset()

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    def _exit(self, viewport) -> None:
        self._reset()
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
        if key in (Qt.Key_Escape, Qt.Key_Space):
            return True
        return bool(self.points) and key in (
            Qt.Key_Return, Qt.Key_Enter, Qt.Key_Backspace)

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if key == Qt.Key_Space:
            _Settings.side = "right" if _Settings.side == "left" else "left"
            viewport.flash_status(
                tr("Linea tracciata = lato ")
                + (tr("destro") if _Settings.side == "right" else tr("sinistro"))
                + tr(" della rampa"), 2500)
            viewport.update()
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter) and self.points:
            self._commit(viewport)
            return True
        if key == Qt.Key_Backspace and self.points:
            self.points.pop()
            viewport.update()
            return True
        return False

    def _constrain(self, x, y):
        if _Settings.ortho and self.points:
            px, py = self.points[-1]
            if abs(x - px) >= abs(y - py):
                return x, py
            return px, y
        return x, y

    def _min_next(self):
        return _Settings.w / 2 + 0.30

    def _place(self):
        vp = getattr(self, "_vp", None)
        if vp is None:
            return _Settings.z, {}
        return piani.place(vp.scene, _Settings.level, _Settings.z)

    def _dict(self, pts):
        z, extra = self._place()
        d = {"pts": [list(p) for p in pts], "w": _Settings.w,
             "height": _Settings.height, "z": z, "side": _Settings.side,
             "kind": _Settings.kind, "th": _Settings.th, **extra}
        if _Settings.rail:
            d["rail"] = dict(_Settings.rail)
        for k in PAINT_KEYS:
            v = getattr(_Settings, k, None)
            if v:
                d[k] = copy.deepcopy(v)
        vp = getattr(self, "_vp", None)
        if _Settings.tlv and vp is not None:
            apply_top(vp.scene, d, _Settings.tlv, _Settings.toff,
                      _Settings.level)
        return d

    def _preview_dict(self):
        pts = list(self.points)
        if self.hover is not None and len(pts) < MAX_POINTS:
            h = self._constrain(self.hover.x(), self.hover.y())
            if len(pts) < 2 or math.hypot(
                    h[0] - pts[-1][0],
                    h[1] - pts[-1][1]) >= self._min_next():
                pts.append(h)
        if len(pts) < 2:
            return None
        return self._dict(pts)

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover = QVector3D(ctx.world)
        ctx.viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        if getattr(vp.scene, "edit_group", None) is not None:
            vp.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        x, y = self._constrain(ctx.world.x(), ctx.world.y())
        if self.points and math.hypot(
                x - self.points[-1][0], y - self.points[-1][1]) < 0.05:
            return
        if len(self.points) >= 2 and math.hypot(
                x - self.points[-1][0],
                y - self.points[-1][1]) < self._min_next():
            vp.flash_status(tr("Rampa troppo corta · Invio per concludere "
                            "qui"), 3000)
            return
        self.points.append((x, y))
        if len(self.points) >= MAX_POINTS:
            self._commit(vp)
            return
        vp.update()

    def _commit(self, viewport) -> None:
        if len(self.points) < 2:
            viewport.flash_status(tr("Servono almeno 2 punti"), 3000)
            return
        d = self._dict(self.points)
        if not layout(d):
            viewport.flash_status(tr("Rampa troppo corta"), 3500)
            return
        if _Settings.tlv and "tlv" not in d:
            viewport.flash_status(
                tr("Nessun piano di arrivo: uso l'altezza indicata"), 4000)
        name = _Settings.name

        def mutate(scene):
            g = build_ramp(scene, d, name)
            sync_railings(scene, g, g.ext[KEY])

        viewport.history.execute(muri.MuriCommand(mutate))
        viewport.notify_scene_changed()
        slope = d["height"] / total_length(d)
        warn = (tr(" · ATTENZIONE: pendenza oltre l'8%")
                if slope > MAX_SLOPE + 1e-9 else "")
        viewport.flash_status(
            tr("Rampa creata · pendenza {0:.1f}% · altezza {1:.2f} m{2}").format(slope * 100, d['height'], warn), 5000)
        self._reset()
        viewport.update()

    def rubber_band_lines(self):
        P = QVector3D
        lines = []
        z0 = self._place()[0]
        path = list(self.points)
        if self.hover is not None and path and len(path) < MAX_POINTS:
            path.append(self._constrain(self.hover.x(), self.hover.y()))
        for a, b in zip(path, path[1:]):
            lines.append((P(a[0], a[1], z0), P(b[0], b[1], z0)))
        d = self._preview_dict()
        for it in (layout(d) if d else []):
            c = it["body"]
            for i in range(4):
                a, b = c[i], c[(i + 1) % 4]
                za = it["z0"] if i in (0, 3) else it["z1"]
                zb_ = it["z0"] if (i + 1) % 4 in (0, 3) else it["z1"]
                lines.append((P(a[0], a[1], za), P(b[0], b[1], zb_)))
        return lines

    def draw_overlay(self, viewport, painter) -> None:
        try:
            self._draw_info(viewport, painter)
        except Exception:
            pass

    def _draw_info(self, viewport, painter) -> None:
        from PySide6.QtCore import QPointF
        d = self._preview_dict()
        if d is None or self.hover is None:
            return
        tot = total_length(d)
        if tot < 1e-6:
            return
        slope = d["height"] / tot
        ph = viewport._world_to_pixel(QVector3D(self.hover))
        if ph is None:
            return
        painter.save()
        font = painter.font()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        bad = slope > MAX_SLOPE + 1e-9
        painter.setPen(QPen(QColor(200, 20, 20) if bad else QColor(20, 90, 20)))
        painter.drawText(
            QPointF(ph[0] + 14, ph[1] - 10),
            tr("pendenza {0:.1f}% · lunghezza {1:.2f} m · h {2:.2f} m").format(slope * 100, tot, d['height']))
        painter.restore()


def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap, QPolygon
    from PySide6.QtCore import QPoint
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(200, 198, 190))
    p.drawPolygon(QPolygon([QPoint(5, 40), QPoint(43, 40), QPoint(43, 12)]))
    p.end()
    return QIcon(pm)


def _outliner_kind(group):
    d = ramp_data(group)
    if d is None:
        return None
    from ._imperial import fmt_len
    tot = total_length(d)
    slope = d["height"] / tot if tot > EPS else 0.0
    return {"type": tr("Rampa"),
            "props": [(tr("Tipologia"), tr("In c.a.") if d.get("kind") == "ca"
                       else tr("Piena")),
                      (tr("Larghezza"), fmt_len(d["w"])),
                      (tr("Altezza"), fmt_len(d["height"])),
                      (tr("Lunghezza"), fmt_len(tot)),
                      (tr("Pendenza"), f"{slope * 100:.1f}%")]
            + piani.level_props(d)}


def _register_level_kind(app=None) -> None:
    def zset(d, z):
        d["z"] = z

    def hget(d):
        return d["height"]

    def hset(d, h):
        if h > EPS:
            d["height"] = h

    def rebuild(g, d):
        rebuild_ramp(g, d)
        try:
            if app is not None and d.get("rail"):
                sync_railings(app.viewport.scene, g, d)
        except Exception:
            pass

    piani.register_kind("rampa", KEY, ramp_data, lambda d: d["z"], zset,
                        rebuild, hget, hset)


def _selected_ramps(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and ramp_data(g) is not None and g not in out:
            out.append(g)
    return out


def edit_rails(viewport) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    sel = _selected_ramps(scene)
    if not sel:
        viewport.flash_status(tr("Seleziona una rampa"), 3000)
        return
    dlg = QDialog(viewport.window())
    dlg.setWindowTitle(tr("Balaustre della rampa"))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    cf = _codici.CodeField(form, sel, "rampa", scene)
    rs, rk = _rail_combos(ramp_data(sel[0]).get("rail"))
    form.addRow(tr("Balaustre"), rs)
    form.addRow(tr("Tipo di balaustra"), rk)
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return
    cf.apply(viewport.window())
    rail = _rail_value(rs, rk)

    def mutate(sc):
        for g in sel:
            d = dict(ramp_data(g))
            d.setdefault("sid", uuid.uuid4().hex)
            if rail:
                d["rail"] = dict(rail)
            else:
                d.pop("rail", None)
            ext = dict(g.ext or {})
            ext[KEY] = d
            g.ext = ext
            sync_railings(sc, g, d)

    hist = viewport.history
    hist.execute(muri.MuriCommand(mutate))
    if getattr(hist, "last_error", None):
        viewport.flash_status(tr("Rampa: ")
                              + str(hist.last_error).split(": ", 1)[-1], 6000)
        return
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("Balaustre aggiornate"), 3000)


def register(api) -> None:
    _register_level_kind(api.app)
    api.add_button(tr("Rampa"), tr("Crea una rampa con pianerottoli"),
                   _icon(), api.run_tool(RampaTool()))
    app = api.app
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        from PySide6.QtCore import QTimer

        def context(menu, selection) -> None:
            if not _selected_ramps(app.viewport.scene):
                return
            menu.addSeparator()
            menu.addAction(
                tr("Balaustre della rampa…"),
                lambda: QTimer.singleShot(
                    0, lambda: edit_rails(app.viewport)))

        add_ctx(context)
    add_kind = getattr(api.app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
