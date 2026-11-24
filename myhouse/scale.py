# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr
from ._imperial import FT, IN, LengthSpin, dflt
from ._scroll import scroll_form

import math
import os
import uuid

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPen, QVector3D
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from core import bim
from . import _ifc
from tools.base import Tool, ToolContext

from . import _codici, _tipi, muri, piani

ORDER = 70
BODY_COLOR = (0.78, 0.76, 0.72)
SILL_COLOR = (0.55, 0.45, 0.35)
STEP_DEFAULT = (0.76, 0.60, 0.42)
BODY_DEFAULT = (0.80, 0.80, 0.78)
STEP_NAME = tr("soglia scala")
BODY_NAME = tr("struttura scala")
LAYER_NAME = "Scale"
KEY = "myhouse_scala"
SILL_TH = 0.02
SILL_OVER = 0.01
MAX_POINTS = 4
EPS = 1e-9
STEEL_KINDS = ("metallo", "trave")
SBALZO_KINDS = ("sbalzo_trave", "sbalzo_muro")
EMBED = 0.12
FRAME_W = 0.08
TREAD_TH = 0.04
FLANK_SINGLE = True


class _Settings:
    w = dflt(36 * IN, 1.00)
    tread = dflt(10 * IN, 0.30)
    riser = dflt(7.75 * IN, 0.17)
    z = 0.0
    name = tr("Scala")
    ortho = True
    side = "left"
    kind = "piena"
    th = dflt(6 * IN, 0.15)
    bw = FRAME_W
    fix = "left"
    emb = EMBED
    col_step = list(STEP_DEFAULT)
    col_body = list(BODY_DEFAULT)
    tex_step = None
    tex_body = None
    tt = TREAD_TH
    level = None
    tlv = None
    toff = 0.0
    winders = 1
    rail = None
    tipo_id = None
    tipo_nome = None


def _rect(a, u, s0, s1, hw):
    ax, ay = a
    ux, uy = u
    vx, vy = -uy, ux
    def pt(s, lat):
        return (ax + ux * s + vx * lat, ay + uy * s + vy * lat)
    return [pt(s0, -hw), pt(s1, -hw), pt(s1, hw), pt(s0, hw)]


def _rect_lat(a, u, s0, s1, l0, l1):
    ax, ay = a
    ux, uy = u
    vx, vy = -uy, ux
    def pt(s, lat):
        return (ax + ux * s + vx * lat, ay + uy * s + vy * lat)
    return [pt(s0, l0), pt(s1, l0), pt(s1, l1), pt(s0, l1)]


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


def _landing_polys(a, u_in, u_out, hw, n):
    square = _rect(a, u_in, -hw, hw, hw)
    cross = u_in[0] * u_out[1] - u_in[1] * u_out[0]
    dot = u_in[0] * u_out[0] + u_in[1] * u_out[1]
    if n < 2 or abs(dot) > 0.05 or abs(abs(cross) - 1.0) > 0.05:
        return [square]
    n = min(int(n), 3)
    L = 2 * hw
    c = (a[0] - hw * u_in[0] + hw * u_out[0],
         a[1] - hw * u_in[1] + hw * u_out[1])
    e1 = (-u_out[0], -u_out[1])
    e2 = u_in

    def pt(x, y):
        return (c[0] + e1[0] * x + e2[0] * y, c[1] + e1[1] * x + e2[1] * y)

    def edge(th):
        co, si = math.cos(math.radians(th)), math.sin(math.radians(th))
        t = L / max(co, si)
        return (t * co, t * si)

    angs = [90.0 * j / n for j in range(n + 1)]
    polys = []
    for j in range(n):
        t0, t1 = angs[j], angs[j + 1]
        loc = [(0.0, 0.0), edge(t0)]
        if t0 < 45 - 1e-6 and t1 > 45 + 1e-6:
            loc.append((L, L))
        loc.append(edge(t1))
        poly = [pt(x, y) for x, y in loc]
        if _area(poly) < 0:
            poly.reverse()
        polys.append(poly)
    return polys


def layout(d):
    w, t, riser, z0 = d["w"], d["tread"], d["riser"], d["z"]
    pts = _axis_points([tuple(p) for p in d["pts"]], w, d.get("side", "center"))
    hw = w / 2
    items = []
    k = 0
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
            for body in _landing_polys(a, u_prev, u, hw, d.get("winders", 1)):
                k += 1
                ztop = z0 + k * riser
                items.append({"kind": "landing", "n": k, "ztop": ztop,
                              "body": body, "top": body,
                              "centre": (sum(q[0] for q in body) / len(body),
                                         sum(q[1] for q in body) / len(body)),
                              "winder": len(body) != 4 or d.get("winders", 1) > 1})
        has_landing_before = i > 0
        has_landing_after = i + 1 < m - 1
        s0 = hw if has_landing_before else 0.0
        s1 = length - (hw if has_landing_after else 0.0)
        n = int((s1 - s0) / t + 1e-6)
        if n >= 1:
            te = (s1 - s0) / n if (has_landing_before and has_landing_after) else t
            start = s1 - n * te if has_landing_after else s0
            for j in range(n):
                k += 1
                ztop = z0 + k * riser
                sf = start + j * te
                sb = sf + te
                items.append({
                    "kind": "step", "n": k, "ztop": ztop,
                    "fl": i, "a": a, "u": u, "sf": sf, "sb": sb,
                    "body": _rect(a, u, sf, sb, hw),
                    "top": _rect(a, u, sf - SILL_OVER, sb, hw),
                    "centre": (a[0] + u[0] * (sf + sb) / 2,
                               a[1] + u[1] * (sf + sb) / 2)})
        u_prev = u
    return items


def _area(pts) -> float:
    return 0.5 * sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
                     - pts[(i + 1) % len(pts)][0] * pts[i][1]
                     for i in range(len(pts)))


def _triangulate(pts):
    idx = list(range(len(pts)))
    if _area(pts) < 0:
        idx.reverse()

    def cross(a, b, c):
        return ((pts[b][0] - pts[a][0]) * (pts[c][1] - pts[a][1])
                - (pts[b][1] - pts[a][1]) * (pts[c][0] - pts[a][0]))

    def inside(p, a, b, c):
        return (cross(a, b, p) >= -EPS and cross(b, c, p) >= -EPS
                and cross(c, a, p) >= -EPS)

    tris = []
    guard = 0
    while len(idx) > 3 and guard < 10000:
        guard += 1
        for k in range(len(idx)):
            a, b, c = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            if cross(a, b, c) <= EPS:
                continue
            if any(inside(p, a, b, c) for p in idx if p not in (a, b, c)):
                continue
            tris.append((a, b, c))
            idx.pop(k)
            break
        else:
            break
    if len(idx) == 3:
        tris.append(tuple(idx))
    return tris


def flight_profile(steps, d, sill=SILL_TH):
    zb, riser = d["z"], d["riser"]
    sf1, send = steps[0]["sf"], steps[-1]["sb"]
    te = steps[0]["sb"] - steps[0]["sf"]
    top = []
    for it in reversed(steps):
        zt = it["ztop"] - sill
        top += [(it["sb"], zt), (it["sf"], zt)]
    bottom = [(sf1, zb), (send, zb)]
    if d.get("kind", "piena") == "ca" and te > EPS:
        slope = riser / te
        dv = d.get("th", 0.15) * math.hypot(te, riser) / te
        z1 = steps[0]["ztop"] - riser - sill

        def zs(s_):
            return z1 + (s_ - sf1) * slope - dv

        zs0, zs1 = zs(sf1), zs(send)
        if zs1 <= zb + 1e-6:
            pass
        elif zs0 < zb:
            bottom = [(sf1, zb), (sf1 + (zb - zs0) / slope, zb), (send, zs1)]
        else:
            bottom = [(sf1, zs0), (send, zs1)]
    poly = []
    for p in bottom + top:
        if not poly or abs(p[0] - poly[-1][0]) + abs(p[1] - poly[-1][1]) > 1e-9:
            poly.append(p)
    if len(poly) > 1 and (abs(poly[0][0] - poly[-1][0])
                          + abs(poly[0][1] - poly[-1][1])) < 1e-9:
        poly.pop()
    return poly


def stair_mesh(d):
    from core.mesh import Mesh
    P = QVector3D
    mesh = Mesh()
    zb = d["z"]
    hw = d["w"] / 2
    kind = d.get("kind", "piena")
    ca = kind == "ca" or kind in STEEL_KINDS or kind in SBALZO_KINDS
    tt = d.get("tt", TREAD_TH)
    bw = d.get("bw", FRAME_W)
    bw = min(bw, hw * 0.45) if kind == "metallo" else min(bw, hw * 1.8)
    fs = 1.0 if d.get("fix", "left") == "left" else -1.0
    emb = d.get("emb", EMBED)

    def face(q, color):
        f = mesh.add_face(q)
        f.attrs["layer"] = LAYER_NAME
        c = d.get("col_step") if color is SILL_COLOR else d.get("col_body")
        tex = d.get("tex_step") if color is SILL_COLOR else d.get("tex_body")
        if c:
            f.attrs["color"] = tuple(c)
            if not (tex and tex.get("path")):
                f.attrs["mat"] = STEP_NAME if color is SILL_COLOR else BODY_NAME
        if tex and tex.get("path"):
            f.attrs["texture"] = dict(tex)
            f.attrs["mat"] = os.path.splitext(os.path.basename(tex["path"]))[0]

    def box(corners, z0, z1, color):
        face([P(x, y, z1) for x, y in corners], color)
        face([P(x, y, z0) for x, y in reversed(corners)], color)
        nc = len(corners)
        for i in range(nc):
            j = (i + 1) % nc
            ci, cj = corners[i], corners[j]
            face([P(ci[0], ci[1], z0), P(cj[0], cj[1], z0),
                  P(cj[0], cj[1], z1), P(ci[0], ci[1], z1)], color)

    items = layout(d)
    flights = {}
    for it in items:
        if it["kind"] == "landing":
            thk = d.get("th", 0.15)
            if kind == "sbalzo_muro":
                thk = tt
            elif it.get("winder"):
                thk = max(thk, d["riser"])
            z0 = it["ztop"] - thk if ca else zb
            box(it["body"], max(z0, zb), it["ztop"],
                SILL_COLOR if (kind in STEEL_KINDS or kind in SBALZO_KINDS)
                else BODY_COLOR)
        else:
            flights.setdefault(it["fl"], []).append(it)
            if kind == "metallo":
                c = _rect(it["a"], it["u"], it["sf"] - SILL_OVER, it["sb"],
                          hw - bw)
                box(c, it["ztop"] - tt, it["ztop"], SILL_COLOR)
            elif kind == "trave":
                box(it["top"], it["ztop"] - tt, it["ztop"], SILL_COLOR)
            elif kind in SBALZO_KINDS:
                l0, l1 = -hw, hw
                if kind == "sbalzo_muro":
                    if fs > 0:
                        l1 += emb
                    else:
                        l0 -= emb
                c = _rect_lat(it["a"], it["u"], it["sf"] - SILL_OVER,
                              it["sb"], l0, l1)
                box(c, it["ztop"] - tt, it["ztop"], SILL_COLOR)
            else:
                box(it["top"], it["ztop"] - SILL_TH, it["ztop"], SILL_COLOR)

    def prism(poly, hi, lo, p3):
        n = len(poly)
        for i in range(n):
            p, q = poly[i], poly[(i + 1) % n]
            face([p3(p, hi), p3(q, hi), p3(q, lo), p3(p, lo)], BODY_COLOR)
        if FLANK_SINGLE:
            face([p3(t_, lo) for t_ in poly], BODY_COLOR)
            face([p3(t_, hi) for t_ in reversed(poly)], BODY_COLOR)
        else:
            for ia, ib, ic in _triangulate(poly):
                tri = (poly[ia], poly[ib], poly[ic])
                face([p3(t_, lo) for t_ in tri], BODY_COLOR)
                face([p3(t_, hi) for t_ in reversed(tri)], BODY_COLOR)

    for steps in flights.values():
        a, u = steps[0]["a"], steps[0]["u"]
        v = (-u[1], u[0])

        def p3(sz, lat):
            return P(a[0] + u[0] * sz[0] + v[0] * lat,
                     a[1] + u[1] * sz[0] + v[1] * lat, sz[1])

        if kind in STEEL_KINDS:
            poly = flight_profile(steps, dict(d, kind="ca"),
                                  sill=0.0 if kind == "metallo" else tt)
            if kind == "metallo":
                spans = [(hw, hw - bw), (-hw + bw, -hw)]
            else:
                spans = [(bw / 2, -bw / 2)]
            for hi, lo in spans:
                prism(poly, hi, lo, p3)
            continue
        if kind == "sbalzo_muro":
            continue
        if kind == "sbalzo_trave":
            poly = flight_profile(steps, dict(d, kind="ca"), sill=tt)
            if fs > 0:
                prism(poly, hw, hw - bw, p3)
            else:
                prism(poly, -hw + bw, -hw, p3)
            continue
        prism(flight_profile(steps, d), hw, -hw, p3)
    return mesh


def apply_top(scene, d, tlv, toff, level) -> bool:
    n = len(layout(d))
    if n < 1:
        return False
    h = piani.height_for(scene, tlv, toff, level, d["z"])
    if h is None or h <= EPS:
        return False
    d["riser"] = h / n
    d["tlv"], d["toff"] = tlv, toff
    return True


def stair_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "pts" in data else None


def rebuild_stair(group, d) -> None:
    from core.group import Group
    part = Group(stair_mesh(d), name=tr("Scala"))
    part.component = False
    group.children = [part]
    _ifc.tag(group, "IfcStair")
    ext = dict(group.ext or {})
    ext[KEY] = dict(d)
    group.ext = ext


def build_stair(scene, d, name) -> None:
    from core.group import Group
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    part = Group(stair_mesh(d), name=tr("Scala"))
    part.component = False
    g = Group(name=name)
    g.adopt([part])
    g.component = False
    g.layer = LAYER_NAME
    _ifc.tag(g, "IfcStair", name)
    d.setdefault("sid", uuid.uuid4().hex)
    g.ext = {KEY: d}
    scene.groups.append(g)
    return g


class _ColorPick(QWidget):

    def __init__(self, cur=None):
        super().__init__()
        self.value = tuple(cur) if cur else None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.btn = QPushButton()
        self.btn.clicked.connect(self._pick)
        rst = QPushButton(tr("Predefinito"))
        rst.clicked.connect(self._reset)
        lay.addWidget(self.btn, 1)
        lay.addWidget(rst)
        self._show()

    def _show(self):
        if self.value:
            r, g, b = [int(round(c * 255)) for c in self.value]
            self.btn.setText(f"#{r:02x}{g:02x}{b:02x}")
            self.btn.setStyleSheet(f"background-color: rgb({r},{g},{b});")
        else:
            self.btn.setText(tr("Materiale predefinito"))
            self.btn.setStyleSheet("")

    def _pick(self):
        cur = (QColor(*[int(round(c * 255)) for c in self.value])
               if self.value else QColor(200, 200, 200))
        col = QColorDialog.getColor(cur, self)
        if col.isValid():
            self.value = (col.redF(), col.greenF(), col.blueF())
            self._show()

    def _reset(self):
        self.value = None
        self._show()

    def set(self, cur):
        self.value = tuple(cur) if cur else None
        self._show()

    def result(self):
        return list(self.value) if self.value else None


TEX_DIR = r"C:\Program Files\IngeTrazo\_internal\resources\textures\library"


class _TexturePick(QWidget):

    def __init__(self, cur=None):
        super().__init__()
        cur = cur or {}
        self.path = cur.get("path") or None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.btn = QPushButton()
        self.btn.clicked.connect(self._pick)
        rst = QPushButton(tr("Nessuna"))
        rst.clicked.connect(self._reset)

        def sp(val, lo, hi, tip, prefix="", suffix=""):
            w = LengthSpin()
            w.setDecimals(3)
            w.setRange(lo, hi)
            w.setValue(val)
            w.setToolTip(tip)
            w.setPrefix(prefix)
            w.setSuffix(suffix)
            return w

        self.sw = sp(cur.get("sw", 1.0), 0.01, 100.0,
                     tr("Larghezza della texture (m)"), "L ")
        self.sh = sp(cur.get("sh", 1.0), 0.01, 100.0,
                     tr("Altezza della texture (m)"), "H ")
        self.rot = sp(cur.get("rot", 0.0), -360.0, 360.0,
                      tr("Rotazione della texture"), "", "°")
        for w in (self.btn,):
            lay.addWidget(w, 1)
        for w in (self.sw, self.sh, self.rot, rst):
            lay.addWidget(w)
        self._show()

    def _show(self):
        self.btn.setText(os.path.basename(self.path) if self.path
                         else tr("Nessuna texture"))

    def _pick(self):
        start = (os.path.dirname(self.path) if self.path
                 else (TEX_DIR if os.path.isdir(TEX_DIR) else ""))
        p, _ = QFileDialog.getOpenFileName(
            self, tr("Scegli la texture"), start,
            tr("Immagini (*.png *.jpg *.jpeg *.bmp)"))
        if p:
            self.path = os.path.normpath(p)
            self._show()

    def _reset(self):
        self.path = None
        self._show()

    def set(self, cur):
        cur = cur or {}
        self.path = cur.get("path") or None
        self.sw.setValue(cur.get("sw", 1.0))
        self.sh.setValue(cur.get("sh", 1.0))
        self.rot.setValue(cur.get("rot", 0.0))
        self._show()

    def result(self):
        if not self.path:
            return None
        return {"path": self.path, "sw": self.sw.value(),
                "sh": self.sh.value(), "rot": self.rot.value()}


def _spin(value, lo, hi):
    s = LengthSpin()
    s.setDecimals(3)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


def _disegno_scala(p):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPen, QPolygonF
    r, t, dim, ext = muri._r, muri._t, muri._dim, muri._ext
    t(p, 60, 12, tr("Profilo"), size=9)
    p.setPen(QPen(muri._C_LINEA, 1.5))
    p.drawLine(QPointF(10, 158), QPointF(230, 158))
    muri._hatch(p, 10, 158, 230, 162)
    p.setPen(QPen(muri._C_LINEA, 1.2))
    p.setBrush(muri._C_BIANCO)
    p.drawPolygon(QPolygonF([QPointF(*q) for q in
                             ((40, 130), (200, 30), (200, 50), (40, 150))]))
    p.setBrush(muri._C_CORPO)
    pts = [(40, 130), (40, 105), (80, 105), (80, 80), (120, 80), (120, 55),
           (160, 55), (160, 30), (200, 30)]
    p.drawPolygon(QPolygonF([QPointF(*q) for q in pts]))
    dim(p, 40, 98, 80, 98, "p", 1)
    dim(p, 32, 105, 32, 130, "a", -1)
    dim(p, 14, 130, 14, 158, "z", -1)
    ext(p, 14, 130, 40, 130)
    dim(p, 212, 30, 212, 50, "s")
    t(p, 250, 12, tr("Sezioni trasversali"), size=9)
    r(p, 250, 40, 258, 80, muri._C_CORPO)
    r(p, 302, 40, 310, 80, muri._C_CORPO)
    r(p, 258, 40, 302, 46, muri._C_LEGNO)
    dim(p, 250, 32, 310, 32, "L", 1)
    dim(p, 250, 90, 258, 90, "b", 1)
    dim(p, 240, 40, 240, 80, "s", -1)
    dim(p, 316, 40, 316, 46, "t")
    t(p, 255, 118, tr("metallo"), size=8)
    r(p, 368, 52, 382, 90, muri._C_CORPO)
    r(p, 340, 46, 410, 52, muri._C_LEGNO)
    dim(p, 340, 38, 410, 38, "L", 1)
    dim(p, 368, 100, 382, 100, "b", 1)
    dim(p, 360, 52, 360, 90, "s", -1)
    dim(p, 416, 46, 416, 52, "t")
    t(p, 350, 118, tr("trave"), size=8)
    muri._muro(p, 436, 30, 456, 100)
    r(p, 446, 52, 478, 58, muri._C_LEGNO)
    dim(p, 446, 72, 456, 72, "e", 1)
    t(p, 430, 118, tr("nel muro"), size=8)


def ask_settings(parent, scene=None) -> bool:
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("Scala"))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(muri._Schema(_disegno_scala))
    w = _spin(_Settings.w, 0.2, 10.0)
    tread = _spin(_Settings.tread, 0.05, 2.0)
    riser = _spin(_Settings.riser, 0.02, 1.0)
    z = _spin(_Settings.z, -100.0, 1000.0)
    name = QLineEdit(_Settings.name)
    side = QComboBox()
    side.addItem(tr("Lato sinistro della scala"), "left")
    side.addItem(tr("Lato destro della scala"), "right")
    side.addItem(tr("Asse (centro) della scala"), "center")
    side.setCurrentIndex(max(0, side.findData(_Settings.side)))
    kind = QComboBox()
    kind.addItem(tr("Piena (gradini pieni)"), "piena")
    kind.addItem(tr("In c.a. (soletta sagomata sotto)"), "ca")
    kind.addItem(tr("In metallo (fiancate laterali)"), "metallo")
    kind.addItem(tr("Supportata da trave (trave centrale)"), "trave")
    kind.addItem(tr("A sbalzo con trave laterale"), "sbalzo_trave")
    kind.addItem(tr("A sbalzo nel muro (senza trave)"), "sbalzo_muro")
    kind.setCurrentIndex(max(0, kind.findData(_Settings.kind)))
    th = _spin(_Settings.th, 0.05, 1.0)
    bw = _spin(_Settings.bw, 0.01, 1.0)
    tt = _spin(_Settings.tt, 0.01, 0.5)
    fix = QComboBox()
    fix.addItem(tr("Lato sinistro"), "left")
    fix.addItem(tr("Lato destro"), "right")
    fix.setCurrentIndex(max(0, fix.findData(_Settings.fix)))
    emb = _spin(_Settings.emb, 0.0, 1.0)
    cs, cb = _ColorPick(_Settings.col_step), _ColorPick(_Settings.col_body)
    ts, tb = _TexturePick(_Settings.tex_step), _TexturePick(_Settings.tex_body)
    wind = QComboBox()
    wind.addItem(tr("Pianerottolo quadrato (1 gradino)"), 1)
    wind.addItem(tr("2 gradini a piè d'oca"), 2)
    wind.addItem(tr("3 gradini a piè d'oca"), 3)
    wind.setCurrentIndex(max(0, wind.findData(_Settings.winders)))
    height = _spin(3.0, 0.1, 100.0)
    ortho = QCheckBox(tr("Orto: rampe sempre lungo X o Y"))
    ortho.setChecked(_Settings.ortho)
    lvl = None
    if scene is not None and piani.levels(scene):
        lvl = piani.level_combo(scene, piani.active_id(scene))
        form.addRow(tr("Piano di partenza"), lvl)
    form.addRow(tr("Larghezza scala (L) (m)"), w)
    form.addRow(tr("Pedata (p) (m)"), tread)
    form.addRow(tr("Alzata (a) (m)"), riser)
    top_cb = top_off = None
    if lvl is not None:
        top_cb, top_off = piani.add_top_rows(form, scene, height,
                                             _Settings.tlv, _Settings.toff)
    form.addRow(tr("Quota di partenza: da terra / sopra il piano (z) (m)"), z)
    form.addRow(tr("Tipologia"), kind)
    form.addRow(tr("Spessore soletta c.a. / altezza fiancata o trave (s) (m)"), th)
    form.addRow(tr("Larghezza fiancata (metallo) o trave (b) (m)"), bw)
    form.addRow(tr("Spessore gradino metallo/trave/sbalzo (t) (m)"), tt)
    form.addRow(tr("Sbalzo: lato trave o muro"), fix)
    form.addRow(tr("Sbalzo nel muro: incastro (e) (m)"), emb)
    form.addRow(tr("Colore gradini"), cs)
    form.addRow(tr("Colore travi / fiancate / corpo"), cb)
    form.addRow(tr("Texture gradini"), ts)
    form.addRow(tr("Texture travi / fiancate / corpo"), tb)
    rs, rk = _rail_combos(_Settings.rail)
    form.addRow(tr("Nelle svolte"), wind)
    form.addRow(tr("Balaustre"), rs)
    form.addRow(tr("Tipo di balaustra"), rk)
    form.addRow(tr("Nome"), name)
    form.addRow(tr("La linea che traccio è"), side)
    form.addRow(ortho)
    _get, _set = _type_io(
        {"w": w, "tread": tread, "kind": kind, "th": th, "bw": bw, "tt": tt,
         "fix": fix, "emb": emb, "winders": wind, "col_step": cs,
         "col_body": cb, "tex_step": ts, "tex_body": tb}, rs, rk)
    tbar = _tipi.TypeBar(dlg, form, "scala", {"tipo_id": _Settings.tipo_id},
                         _get, _set, scene, creating=True)
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return False
    _Settings.w, _Settings.tread = w.value(), tread.value()
    _Settings.riser, _Settings.z = riser.value(), z.value()
    _Settings.name = name.text().strip() or tr("Scala")
    _Settings.ortho = ortho.isChecked()
    _Settings.side = side.currentData()
    _Settings.kind, _Settings.th = kind.currentData(), th.value()
    _Settings.bw, _Settings.tt = bw.value(), tt.value()
    _Settings.fix, _Settings.emb = fix.currentData(), emb.value()
    _Settings.col_step, _Settings.col_body = cs.result(), cb.result()
    _Settings.tex_step, _Settings.tex_body = ts.result(), tb.result()
    for col, tex, dflt in (("col_step", "tex_step", STEP_DEFAULT),
                           ("col_body", "tex_body", BODY_DEFAULT)):
        c = getattr(_Settings, col)
        if getattr(_Settings, tex) and c and tuple(c) == tuple(dflt):
            setattr(_Settings, col, None)
    _Settings.winders = wind.currentData()
    _Settings.rail = _rail_value(rs, rk)
    _Settings.level = (lvl.currentData() or None) if lvl is not None else None
    if lvl is not None:
        piani.set_active(_Settings.level)
    if top_cb is not None:
        _Settings.tlv = top_cb.currentData() or None
        _Settings.toff = top_off.value()
    else:
        _Settings.tlv = None
    r = tbar.result(_get())
    _Settings.tipo_id, _Settings.tipo_nome = r.get("tipo_id"), r.get("tipo_nome")
    return True


class ScalaTool(Tool):
    name = tr("Scala")
    shortcut = None
    description = tr("Crea una scala: clic sui punti delle rampe, Invio conclude.")

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
                tr("Scala: clic sui punti delle rampe (2-4) · Invio = concludi "
                "· Spazio = capovolgi · P = piè d'oca · Backspace = indietro · Esc = esci"), 7000)
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
        if key in (Qt.Key_Escape, Qt.Key_Space, Qt.Key_P):
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
                + tr(" della scala"), 2500)
            viewport.update()
            return True
        if key == Qt.Key_P:
            _Settings.winders = _Settings.winders % 3 + 1
            viewport.flash_status(
                tr("Svolte: pianerottolo quadrato") if _Settings.winders == 1
                else tr("Svolte: {0} gradini a piè d'oca").format(_Settings.winders),
                2500)
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
        return _Settings.w / 2 + _Settings.tread

    def _place(self):
        vp = getattr(self, "_vp", None)
        if vp is None:
            return _Settings.z, {}
        return piani.place(vp.scene, _Settings.level, _Settings.z)

    def _dict(self, pts):
        z, extra = self._place()
        d = {"pts": [list(p) for p in pts], "w": _Settings.w,
             "tread": _Settings.tread, "riser": _Settings.riser,
             "z": z, "side": _Settings.side,
             "kind": _Settings.kind, "th": _Settings.th,
             "winders": _Settings.winders,
             "bw": _Settings.bw, "tt": _Settings.tt,
             "fix": _Settings.fix, "emb": _Settings.emb,
             "col_step": _Settings.col_step, "col_body": _Settings.col_body,
             "tex_step": _Settings.tex_step, "tex_body": _Settings.tex_body,
             "tipo_id": _Settings.tipo_id, "tipo_nome": _Settings.tipo_nome,
             **extra}
        if _Settings.rail:
            d["rail"] = dict(_Settings.rail)
        self._apply_top(d)
        return d

    def _apply_top(self, d) -> bool:
        vp = getattr(self, "_vp", None)
        if not _Settings.tlv or vp is None:
            return False
        return apply_top(vp.scene, d, _Settings.tlv, _Settings.toff,
                         _Settings.level)

    def _preview_items(self):
        pts = list(self.points)
        if self.hover is not None and len(pts) < MAX_POINTS:
            h = self._constrain(self.hover.x(), self.hover.y())
            if len(pts) < 2 or math.hypot(
                    h[0] - pts[-1][0],
                    h[1] - pts[-1][1]) >= self._min_next():
                pts.append(h)
        if len(pts) < 2:
            return []
        return layout(self._dict(pts))

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
                            "la scala qui"), 3000)
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
        items = layout(d)
        if not items:
            viewport.flash_status(tr("Rampa troppo corta per la pedata"), 3500)
            return
        linked = "tlv" in d
        if _Settings.tlv and not linked:
            viewport.flash_status(
                tr("Nessun piano di arrivo: uso l'alzata indicata"), 4000)
        name = _Settings.name

        def mutate(scene):
            g = build_stair(scene, d, name)
            sync_railings(scene, g, g.ext[KEY])

        viewport.history.execute(muri.MuriCommand(mutate))
        viewport.notify_scene_changed()
        warn = ""
        if linked and not 0.10 <= d["riser"] <= 0.22:
            warn = tr(" · ATTENZIONE: alzata fuori norma, cambia pedata o rampe")
        viewport.flash_status(
            tr("Scala creata · {0} gradini · alzata {1:.1f} cm · altezza {2:.2f} m{3}").format(len(items), d['riser'] * 100, len(items) * d['riser'], warn), 5000)
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
        for it in self._preview_items():
            z = it["ztop"]
            c = it["top"]
            for i in range(len(c)):
                a, b = c[i], c[(i + 1) % len(c)]
                lines.append((P(a[0], a[1], z), P(b[0], b[1], z)))
        return lines

    def draw_overlay(self, viewport, painter) -> None:
        try:
            self._draw_numbers(viewport, painter)
        except Exception:
            pass

    def _draw_numbers(self, viewport, painter) -> None:
        from PySide6.QtCore import QPointF
        items = self._preview_items()
        if not items:
            return
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        font = painter.font()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(QColor(20, 20, 20)))
        for it in items:
            c = it["centre"]
            pc = viewport._world_to_pixel(QVector3D(c[0], c[1], it["ztop"]))
            if pc is None:
                continue
            painter.drawText(QPointF(pc[0] - 6, pc[1] + 4), str(it["n"]))
        if self.hover is not None:
            ph = viewport._world_to_pixel(QVector3D(self.hover))
            if ph is not None:
                n = len(items)
                h = items[-1]["ztop"] - self._place()[0]
                painter.setPen(QPen(QColor(200, 20, 20)))
                painter.drawText(
                    QPointF(ph[0] + 14, ph[1] - 10),
                    tr("{0} gradini · alzata {1:.1f} cm · h {2:.2f} m").format(n, h / n * 100, h))
        painter.restore()


def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(200, 198, 190))
    for i in range(4):
        p.drawRect(6 + i * 9, 34 - i * 9, 9 + (3 - i) * 9, 9 + i * 9)
    p.end()
    return QIcon(pm)


def _outliner_kind(group):
    d = stair_data(group)
    if d is None:
        return None
    from ._imperial import fmt_len
    n = len(layout(d))
    return {"type": tr("Scala"),
            "props": [(tr("Tipologia"), {
                          "ca": tr("In c.a."), "metallo": tr("In metallo"),
                          "trave": tr("Supportata da trave"),
                          "sbalzo_trave": tr("A sbalzo con trave"),
                          "sbalzo_muro": tr("A sbalzo nel muro")}.get(
                              d.get("kind"), tr("Piena"))),
                      (tr("Larghezza"), fmt_len(d["w"])),
                      (tr("Gradini"), str(n)),
                      (tr("Alzata"), fmt_len(d["riser"])),
                      (tr("Pedata"), fmt_len(d["tread"])),
                      (tr("Altezza"), fmt_len(n * d["riser"]))]
            + piani.level_props(d)}


def _register_level_kind() -> None:
    def zset(d, z):
        d["z"] = z

    def hget(d):
        return len(layout(d)) * d["riser"]

    def hset(d, h):
        n = len(layout(d))
        if n >= 1 and h > EPS:
            d["riser"] = h / n

    piani.register_kind("scala", KEY, stair_data, lambda d: d["z"], zset,
                        rebuild_stair, hget, hset)


def _selected_stairs(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and stair_data(g) is not None and g not in out:
            out.append(g)
    return out


def edit_stairs(viewport, stairs=None) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    stairs = stairs or _selected_stairs(scene)
    if not stairs:
        viewport.flash_status(
            tr("Seleziona una scala creata con lo strumento Scala"), 4000)
        return
    g = stairs[0]
    first = stair_data(g)
    dlg = QDialog(viewport.window())
    dlg.setWindowTitle(tr("Modifica scala"))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(muri._Schema(_disegno_scala))
    w = _spin(first["w"], 0.2, 10.0)
    tread = _spin(first["tread"], 0.05, 2.0)
    riser = _spin(first["riser"], 0.02, 1.0)
    side = QComboBox()
    side.addItem(tr("Lato sinistro della scala"), "left")
    side.addItem(tr("Lato destro della scala"), "right")
    side.addItem(tr("Asse (centro) della scala"), "center")
    side.setCurrentIndex(max(0, side.findData(first.get("side", "center"))))
    kind = QComboBox()
    kind.addItem(tr("Piena (gradini pieni)"), "piena")
    kind.addItem(tr("In c.a. (soletta sagomata sotto)"), "ca")
    kind.addItem(tr("In metallo (fiancate laterali)"), "metallo")
    kind.addItem(tr("Supportata da trave (trave centrale)"), "trave")
    kind.addItem(tr("A sbalzo con trave laterale"), "sbalzo_trave")
    kind.addItem(tr("A sbalzo nel muro (senza trave)"), "sbalzo_muro")
    kind.setCurrentIndex(max(0, kind.findData(first.get("kind", "piena"))))
    th = _spin(first.get("th", 0.15), 0.05, 1.0)
    bw = _spin(first.get("bw", FRAME_W), 0.01, 1.0)
    tt = _spin(first.get("tt", TREAD_TH), 0.01, 0.5)
    fix = QComboBox()
    fix.addItem(tr("Lato sinistro"), "left")
    fix.addItem(tr("Lato destro"), "right")
    fix.setCurrentIndex(max(0, fix.findData(first.get("fix", "left"))))
    emb = _spin(first.get("emb", EMBED), 0.0, 1.0)
    cs, cb = _ColorPick(first.get("col_step")), _ColorPick(first.get("col_body"))
    ts = _TexturePick(first.get("tex_step"))
    tb = _TexturePick(first.get("tex_body"))
    wind = QComboBox()
    wind.addItem(tr("Pianerottolo quadrato (1 gradino)"), 1)
    wind.addItem(tr("2 gradini a piè d'oca"), 2)
    wind.addItem(tr("3 gradini a piè d'oca"), 3)
    wind.setCurrentIndex(max(0, wind.findData(first.get("winders", 1))))
    height = _spin(max(0.1, len(layout(first)) * first["riser"]), 0.1, 100.0)
    has_levels = bool(piani.levels(scene))
    top_cb = top_off = lvl_cb = None
    init_off = first.get("off", first["z"])
    off_sp = _spin(init_off if init_off is not None else first["z"],
                   -100.0, 1000.0)
    if has_levels:
        lvl_cb = piani.level_combo(scene, first.get("lv"))
        form.addRow(tr("Piano di partenza"), lvl_cb)
    form.addRow(tr("Larghezza scala (L) (m)"), w)
    form.addRow(tr("Pedata (p) (m)"), tread)
    form.addRow(tr("Alzata (a) (m)"), riser)
    if has_levels:
        top_cb, top_off = piani.add_top_rows(form, scene, height,
                                             first.get("tlv"),
                                             first.get("toff", 0.0))
    form.addRow(tr("Quota di partenza: da terra / sopra il piano (z) (m)"), off_sp)
    form.addRow(tr("Tipologia"), kind)
    form.addRow(tr("Spessore soletta c.a. / altezza fiancata o trave (s) (m)"), th)
    form.addRow(tr("Larghezza fiancata (metallo) o trave (b) (m)"), bw)
    form.addRow(tr("Spessore gradino metallo/trave/sbalzo (t) (m)"), tt)
    form.addRow(tr("Sbalzo: lato trave o muro"), fix)
    form.addRow(tr("Sbalzo nel muro: incastro (e) (m)"), emb)
    form.addRow(tr("Colore gradini"), cs)
    form.addRow(tr("Colore travi / fiancate / corpo"), cb)
    form.addRow(tr("Texture gradini"), ts)
    form.addRow(tr("Texture travi / fiancate / corpo"), tb)
    rs, rk = _rail_combos(first.get("rail"))
    form.addRow(tr("Nelle svolte"), wind)
    form.addRow(tr("Balaustre"), rs)
    form.addRow(tr("Tipo di balaustra"), rk)
    form.addRow(tr("La linea tracciata è"), side)
    _get, _set = _type_io(
        {"w": w, "tread": tread, "kind": kind, "th": th, "bw": bw, "tt": tt,
         "fix": fix, "emb": emb, "winders": wind, "col_step": cs,
         "col_body": cb, "tex_step": ts, "tex_body": tb}, rs, rk)
    tbar = _tipi.TypeBar(dlg, form, "scala", first, _get, _set, scene)
    cf = _codici.CodeField(form, stairs, "scala", scene, at=2)
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return
    cf.apply(viewport.window())
    vals = {"w": w.value(), "tread": tread.value(), "riser": riser.value(),
            "side": side.currentData(), "kind": kind.currentData(),
            "th": th.value(), "winders": wind.currentData(),
            "bw": bw.value(), "tt": tt.value(),
            "fix": fix.currentData(), "emb": emb.value(),
            "col_step": cs.result(), "col_body": cb.result(),
            "tex_step": ts.result(), "tex_body": tb.result()}
    rail = _rail_value(rs, rk)
    tp = tbar.result(_get())
    st = _tipi.resolve_edit(viewport.window(), scene, "scala", tp)
    if st == "cancel":
        return
    lid = (lvl_cb.currentData() or None) if lvl_cb is not None else None
    off = off_sp.value()
    tlv = (top_cb.currentData() or None) if top_cb is not None else None
    toff = top_off.value() if top_off is not None else 0.0
    failed = [0]

    def mutate(sc):
        for grp in stairs:
            d = dict(stair_data(grp))
            d.update(vals)
            d["tipo_id"], d["tipo_nome"] = tp.get("tipo_id"), tp.get("tipo_nome")
            d.setdefault("sid", uuid.uuid4().hex)
            if rail:
                d["rail"] = rail
            else:
                d.pop("rail", None)
            if has_levels or d.get("lv") is None:
                for k in ("lv", "lvn", "off"):
                    d.pop(k, None)
                z, extra = piani.place(sc, lid, off)
                d["z"] = z
                d.update(extra)
            if top_cb is not None:
                d.pop("tlv", None)
                d.pop("toff", None)
                if tlv and not apply_top(sc, d, tlv, toff, lid):
                    failed[0] += 1
            rebuild_stair(grp, d)
            sync_railings(sc, grp, d)
        if st == "type":
            def _rb(g, q):
                nd = {**stair_data(g), **q}
                if not nd.get("rail"):
                    nd.pop("rail", None)
                rebuild_stair(g, nd)
                sync_railings(sc, g, nd)
            _tipi.update_instances(sc, "scala", tp["tipo_id"], _rb)

    hist = viewport.history
    hist.execute(muri.MuriCommand(mutate))
    if getattr(hist, "last_error", None):
        viewport.flash_status(
            tr("Scala: ") + str(hist.last_error).split(": ", 1)[-1], 6000)
        return
    viewport.notify_scene_changed()
    viewport.update()
    if failed[0]:
        viewport.flash_status(
            tr("Nessun piano di arrivo valido: uso l'alzata indicata"), 6000)
        return
    viewport.flash_status(tr("Scala aggiornata"), 3000)


def railing_info(d, sides):
    w, riser = d["w"], d["riser"]
    axis = _axis_points([tuple(p) for p in d["pts"]], w, d.get("side", "center"))
    edges = {"left": _axis_points(axis, w, "right"),
             "right": _axis_points(axis, w, "left")}
    items = layout(d)
    flights = {}
    for it in items:
        if it["kind"] == "step":
            flights.setdefault(it["fl"], []).append(it)
    last_fl = max(flights) if flights else None
    out = []
    for name in (("left", "right") if sides == "both" else (sides,)):
        E = edges[name]
        path, treads = [], []
        for i in sorted(flights):
            steps = flights[i]
            A, B = axis[i], axis[i + 1]
            dx, dy = B[0] - A[0], B[1] - A[1]
            ln = math.hypot(dx, dy)
            if ln < 1e-6:
                continue
            u = (dx / ln, dy / ln)
            nx, ny = -u[1], u[0]
            sg = 1.0 if ((E[i][0] - A[0]) * nx + (E[i][1] - A[1]) * ny) >= 0 \
                else -1.0
            a = (A[0] + nx * sg * w / 2, A[1] + ny * sg * w / 2)
            s0, s1 = steps[0]["sf"], steps[-1]["sb"]
            p0 = (a[0] + u[0] * s0, a[1] + u[1] * s0, steps[0]["ztop"])
            if i == last_fl:
                sl = steps[-1]["sf"]
                p1 = (a[0] + u[0] * sl, a[1] + u[1] * sl, steps[-1]["ztop"])
            else:
                p1 = (a[0] + u[0] * s1, a[1] + u[1] * s1,
                      steps[-1]["ztop"] + riser)
            for st in steps:
                treads.append([a[0] + u[0] * st["sf"], a[1] + u[1] * st["sf"],
                               a[0] + u[0] * st["sb"], a[1] + u[1] * st["sb"],
                               st["ztop"]])
            if path:
                prev = path[-1]
                path.append((E[i][0], E[i][1], prev[2]))
            if path:
                sc = ((E[i][0] - a[0]) * u[0] + (E[i][1] - a[1]) * u[1])
                ss = max(s0, sc)
                p0 = (a[0] + u[0] * ss, a[1] + u[1] * ss,
                      steps[0]["ztop"] - riser)
            path += [p0, p1]
        if len(path) >= 2:
            out.append((path, treads))
    return out


def railing_paths(d, sides):
    return [p for p, _ in railing_info(d, sides)]


RAIL_OF = "myhouse_scala_of"


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
    for p, treads in railing_info(d, rail["side"]):
        g = balaustre.add_railing_along(scene, p, rail["style"],
                                        treads=treads)
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


def _rail_set(rs, rk, cur):
    cur = cur or {}
    rs.setCurrentIndex(max(0, rs.findData(cur.get("side"))))
    rk.setCurrentIndex(max(0, rk.findData(cur.get("style", "vert"))))


def _type_io(ws, rs, rk):
    paint = ("col_step", "col_body", "tex_step", "tex_body")
    get0, set0 = _tipi.widgets_io(ws, paint)

    def get():
        d = get0()
        d["rail"] = _rail_value(rs, rk)
        return d

    def set_(t):
        set0(t)
        _rail_set(rs, rk, t.get("rail"))
    return get, set_


def _hook_double_click(vp) -> None:
    if getattr(vp, "_myhouse_scale_dbl", False):
        return
    original = vp.begin_group_edit

    def begin_group_edit(group, *args, **kwargs):
        g = getattr(group, "owner", None) or group
        if stair_data(g) is None:
            return original(group, *args, **kwargs)
        from PySide6.QtCore import QTimer
        scene = vp.scene
        try:
            scene.select([g])
        except Exception:
            scene.selection.clear()
            scene.selection.add(g)
        vp.update()
        QTimer.singleShot(0, lambda: edit_stairs(vp, [g]))

    vp.begin_group_edit = begin_group_edit
    vp._myhouse_scale_dbl = True


def register(api) -> None:
    _register_level_kind()
    api.add_button(tr("Scala"), tr("Crea una scala con rampe e pianerottoli"),
                   _icon(), api.run_tool(ScalaTool()))
    app = api.app
    _hook_double_click(api.window.viewport)
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        from PySide6.QtCore import QTimer

        def context(menu, selection) -> None:
            if not _selected_stairs(app.viewport.scene):
                return
            menu.addSeparator()
            menu.addAction(
                tr("Modifica scala…"),
                lambda: QTimer.singleShot(
                    0, lambda: edit_stairs(app.viewport)))

        add_ctx(context)
    add_kind = getattr(app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
