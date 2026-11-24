# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr
from ._imperial import LengthSpin
from ._scroll import scroll_form

import copy
import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPen, QVector3D
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QLineEdit, QSpinBox, QVBoxLayout)

from core import bim
from . import _ifc
from tools.base import Tool, ToolContext

from . import muri, tetto

ORDER = 54
LAYER_NAME = "Grondaie"
KEY = "myhouse_grondaia"
EPS = 1e-6
PICK = 0.8
WALL_T = 0.003
HOOK_T = 0.004
HOOK_W = 0.03
HOOK_ARM = 0.025

GUT_COLOR = (0.62, 0.64, 0.66)
HOOK_COLOR = (0.30, 0.31, 0.33)
PIPE_COLOR = (0.62, 0.64, 0.66)
ZONES = (("g", tr("grondaia")), ("h", tr("ganci grondaia")),
         ("p", tr("pluviale")))
ZONE_MAT = {"g": tr("grondaia"), "h": tr("ganci grondaia"),
            "p": tr("pluviale")}
PAINT_KEYS = ("col_g", "tex_g", "col_h", "tex_h", "col_p", "tex_p")
KINDS = (("rect", tr("Rettangolare")), ("round", tr("Tonda")))


class _S:
    kind = "rect"
    w = 0.12
    h = 0.10
    hooks = 4
    pipe = True
    dp = 0.10
    dist = 0.0
    pos = 0.0
    qf = 0.0
    drop = 0.0
    name = tr("Grondaia")
    col_g = list(GUT_COLOR)
    tex_g = None
    col_h = list(HOOK_COLOR)
    tex_h = None
    col_p = list(PIPE_COLOR)
    tex_p = None


def _params_from_settings() -> dict:
    d = {"kind": _S.kind, "w": _S.w, "h": _S.h, "hooks": _S.hooks,
         "pipe": _S.pipe, "dp": _S.dp, "dist": _S.dist, "pos": _S.pos,
         "qf": _S.qf, "drop": _S.drop}
    for k in PAINT_KEYS:
        v = getattr(_S, k, None)
        if v:
            d[k] = copy.deepcopy(v)
    return d


def _dot(a, b) -> float:
    return QVector3D.dotProduct(a, b)


def _cross(a, b):
    return QVector3D.crossProduct(a, b)


def _area2(poly) -> float:
    return sum(poly[i][0] * poly[(i + 1) % len(poly)][1]
               - poly[(i + 1) % len(poly)][0] * poly[i][1]
               for i in range(len(poly))) / 2.0


def _frame(a, b, hint):
    dv = (b - a).normalized()
    eu = QVector3D(hint[0], hint[1], 0.0)
    eu = (eu - dv * _dot(eu, dv)).normalized()
    ev = _cross(eu, dv).normalized()
    if ev.z() < 0:
        ev = -ev
    return dv, eu, ev


def _depth(d) -> float:
    return max(d["h"], 0.004) if d["kind"] == "rect" else max(d["w"], 0.004) / 2.0


def gutter_poly(d):
    t = WALL_T
    if d["kind"] == "rect":
        w, h = max(d["w"], 0.01), max(d["h"], 0.01)
        return [(0.0, 0.0), (0.0, -h), (w, -h), (w, 0.0),
                (w - t, 0.0), (w - t, -h + t), (t, -h + t), (t, 0.0)]
    R = max(d["w"], 0.01) / 2.0
    n = 16
    out = [(R + R * math.cos(math.pi + math.pi * k / n),
            R * math.sin(math.pi + math.pi * k / n)) for k in range(n + 1)]
    out[0], out[-1] = (0.0, 0.0), (2 * R, 0.0)
    r = max(R - t, 0.001)
    inn = [(R + r * math.cos(math.pi + math.pi * k / n),
            r * math.sin(math.pi + math.pi * k / n)) for k in range(n, -1, -1)]
    return out + inn


def hook_poly(d):
    t, br = HOOK_T, HOOK_ARM
    if d["kind"] == "rect":
        w, h = max(d["w"], 0.01), max(d["h"], 0.01)
        return [(-t, br), (-t, -h - t), (w + t, -h - t), (w + t, br),
                (w, br), (w, -h), (0.0, -h), (0.0, br)]
    R = max(d["w"], 0.01) / 2.0
    n = 16
    out = [(-t, br), (-t, 0.0)]
    out += [(R + (R + t) * math.cos(math.pi + math.pi * k / n),
             (R + t) * math.sin(math.pi + math.pi * k / n))
            for k in range(1, n)]
    out += [(2 * R + t, 0.0), (2 * R + t, br), (2 * R, br), (2 * R, 0.0)]
    out += [(R + R * math.cos(math.pi + math.pi * k / n),
             R * math.sin(math.pi + math.pi * k / n))
            for k in range(n - 1, 0, -1)]
    out += [(0.0, 0.0), (0.0, br)]
    return out


def _painter(d, zone):
    col, tex = d.get("col_" + zone), d.get("tex_" + zone)

    def apply(f):
        f.attrs["layer"] = LAYER_NAME
        if muri.paint_face(f, col, tex) and not tex:
            f.attrs["mat"] = ZONE_MAT[zone]
    return apply


def _face(mesh, pts, expected, paint) -> None:
    nx = ny = nz = 0.0
    n = len(pts)
    for i in range(n):
        p, q = pts[i], pts[(i + 1) % n]
        nx += (p.y() - q.y()) * (p.z() + q.z())
        ny += (p.z() - q.z()) * (p.x() + q.x())
        nz += (p.x() - q.x()) * (p.y() + q.y())
    if nx * expected.x() + ny * expected.y() + nz * expected.z() < 0:
        pts = list(reversed(pts))
    paint(mesh.add_face(pts))


def _prism(mesh, poly, c0, c1, eu, ev, paint) -> None:
    poly = list(poly)
    if _area2(poly) < 0:
        poly.reverse()
    dv = (c1 - c0).normalized()
    r0 = [c0 + eu * u + ev * v for u, v in poly]
    r1 = [c1 + eu * u + ev * v for u, v in poly]
    n = len(poly)
    for i in range(n):
        j = (i + 1) % n
        dx, dy = poly[j][0] - poly[i][0], poly[j][1] - poly[i][1]
        _face(mesh, [r0[i], r0[j], r1[j], r1[i]],
              eu * dy + ev * (-dx), paint)
    for a, b, c in tetto._triangulate(poly):
        _face(mesh, [r0[a], r0[b], r0[c]], -dv, paint)
        _face(mesh, [r1[a], r1[b], r1[c]], dv, paint)


def _tube(mesh, pts, r, paint, nseg=20) -> None:
    dirs = [(pts[i + 1] - pts[i]).normalized() for i in range(len(pts) - 1)]
    tang = [dirs[0]]
    for i in range(1, len(pts) - 1):
        tang.append((dirs[i - 1] + dirs[i]).normalized())
    tang.append(dirs[-1])
    ref = QVector3D(1.0, 0.0, 0.0) if abs(tang[0].x()) < 0.9 \
        else QVector3D(0.0, 1.0, 0.0)
    n1 = (ref - tang[0] * _dot(ref, tang[0])).normalized()
    rings = []
    for i, p in enumerate(pts):
        t = tang[i]
        n1 = (n1 - t * _dot(n1, t)).normalized()
        n2 = _cross(t, n1)
        w, c = None, 1.0
        if 0 < i < len(pts) - 1:
            dw = dirs[i] - dirs[i - 1]
            if dw.length() > 1e-9:
                w, c = dw.normalized(), max(_dot(dirs[i - 1], t), 0.2)
        ring = []
        for k in range(nseg):
            a = 2.0 * math.pi * k / nseg
            off = n1 * (math.cos(a) * r) + n2 * (math.sin(a) * r)
            if w is not None:
                off = off + w * (_dot(off, w) * (1.0 / c - 1.0))
            ring.append(p + off)
        rings.append(ring)
    for i in range(len(pts) - 1):
        mid = (pts[i] + pts[i + 1]) * 0.5
        for k in range(nseg):
            j = (k + 1) % nseg
            q = [rings[i][k], rings[i][j], rings[i + 1][j], rings[i + 1][k]]
            ctr = (q[0] + q[1] + q[2] + q[3]) * 0.25
            _face(mesh, q, ctr - mid, paint)
    _face(mesh, list(rings[0]), -dirs[0], paint)
    _face(mesh, list(rings[-1]), dirs[-1], paint)


def _pts3(d):
    return [QVector3D(*p) for p in d["pts"]]


def _lengths(pts):
    ls = [(pts[i + 1] - pts[i]).length() for i in range(len(pts) - 1)]
    return ls, sum(ls)


def _locate(pts, ls, s):
    acc = 0.0
    for i, ln in enumerate(ls):
        if s <= acc + ln or i == len(ls) - 1:
            return i, min(max(s - acc, 0.0), ln)
        acc += ln
    return 0, 0.0


def gutter_mesh(d):
    from core.mesh import Mesh
    mesh = Mesh()
    pts = _pts3(d)
    paint = _painter(d, "g")
    poly = gutter_poly(d)
    for a, b in zip(pts, pts[1:]):
        if (b - a).length() < EPS:
            continue
        _dv, eu, ev = _frame(a, b, d["eu"])
        _prism(mesh, poly, a, b, eu, ev, paint)
    return mesh


def hooks_mesh(d):
    n = int(d.get("hooks") or 0)
    if n < 1:
        return None
    from core.mesh import Mesh
    mesh = Mesh()
    pts = _pts3(d)
    ls, total = _lengths(pts)
    if total < EPS:
        return None
    paint = _painter(d, "h")
    poly = hook_poly(d)
    hw = HOOK_W / 2.0
    for k in range(n):
        i, sl = _locate(pts, ls, total * (k + 0.5) / n)
        a, b = pts[i], pts[i + 1]
        dv, eu, ev = _frame(a, b, d["eu"])
        sl = min(max(sl, hw), max(ls[i] - hw, hw))
        c = a + dv * sl
        _prism(mesh, poly, c - dv * hw, c + dv * hw, eu, ev, paint)
    return mesh


def pipe_path(d):
    if not d.get("pipe"):
        return None
    pts = _pts3(d)
    ls, total = _lengths(pts)
    if total < EPS:
        return None
    dia = max(d["dp"], 0.02)
    margin = dia / 2.0 + 0.02
    if total <= 2.0 * margin:
        s = total / 2.0
    else:
        s = min(max(d["pos"] * total, margin), total - margin)
    i, sl = _locate(pts, ls, s)
    a, b = pts[i], pts[i + 1]
    dv, eu, ev = _frame(a, b, d["eu"])
    uc = max(d["w"], 0.01) / 2.0
    p0 = a + dv * sl + eu * uc + ev * (-_depth(d) + 0.01)
    up = QVector3D(0.0, 0.0, 1.0)
    wall = QVector3D(-eu.x(), -eu.y(), 0.0)
    wall = wall.normalized() if wall.length() > 1e-9 else QVector3D()
    D = max(d.get("dist", 0.0), 0.0)
    if D < 1e-4:
        return [p0, QVector3D(p0.x(), p0.y(), min(d["qf"], p0.z() - 0.3))]
    if d.get("drop", 0.0) > 1e-4:
        fall = d["drop"]
    else:
        fall = max(d.get("th", 0.0) + dia / 2.0 + 0.02, dia, 0.10)
    p1 = p0 - up * fall
    p2 = p1 + wall * D - up * D
    return [p0, p1, p2, QVector3D(p2.x(), p2.y(), min(d["qf"], p2.z() - 0.2))]


def _hide_edges(mesh) -> None:
    flag = getattr(muri, "EDGE_FLAG", "hidden")
    for e in mesh.edges:
        try:
            setattr(e, flag, True)
        except Exception:
            pass


def pipe_mesh(d):
    path = pipe_path(d)
    if not path:
        return None
    from core.mesh import Mesh
    mesh = Mesh()
    _tube(mesh, path, max(d["dp"], 0.02) / 2.0, _painter(d, "p"))
    _hide_edges(mesh)
    return mesh


def pipe_target(d, x, y):
    pts = _pts3(d)
    ls, total = _lengths(pts)
    if total < EPS:
        return 0.0, 0.0
    best, acc = None, 0.0
    for i, ln in enumerate(ls):
        a, b = pts[i], pts[i + 1]
        dx, dy = b.x() - a.x(), b.y() - a.y()
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 < EPS else max(
            0.0, min(1.0, ((x - a.x()) * dx + (y - a.y()) * dy) / L2))
        px, py = a.x() + t * dx, a.y() + t * dy
        dd = math.hypot(px - x, py - y)
        if best is None or dd < best[0]:
            best = (dd, acc + t * ln, px, py)
        acc += ln
    _dd, s, px, py = best
    hx, hy = d["eu"]
    hl = math.hypot(hx, hy) or 1.0
    hx, hy = hx / hl, hy / hl
    uc = max(d["w"], 0.01) / 2.0
    bx, by = px + hx * uc, py + hy * uc
    dist = -((x - bx) * hx + (y - by) * hy)
    return min(max(s / total, 0.0), 1.0), min(max(dist, 0.0), 5.0)


def gutter_parts(d) -> list:
    from core.group import Group
    parts = []
    for mesh, name in ((gutter_mesh(d), tr("Grondaia")),
                       (hooks_mesh(d), tr("Ganci grondaia")),
                       (pipe_mesh(d), tr("Pluviale"))):
        if mesh is None:
            continue
        part = Group(mesh, name=name)
        part.component = False
        parts.append(part)
    return parts


def gutter_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "pts" in data else None


def rebuild_gutter(group, d) -> None:
    group.children = gutter_parts(d)
    _ifc.tag(group, "IfcBuildingElementProxy")
    ext = dict(group.ext or {})
    ext[KEY] = dict(d)
    group.ext = ext


def build_gutter(scene, d, name) -> None:
    from core.group import Group
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    g = Group(name=name)
    g.adopt(gutter_parts(d))
    g.component = False
    g.layer = LAYER_NAME
    _ifc.tag(g, "IfcBuildingElementProxy", name)
    g.ext = {KEY: d}
    scene.groups.append(g)


def _edge_points(group, d, i):
    from shapely.geometry import Point, Polygon
    M = tetto._group_matrix(group)
    poly = [tuple(p) for p in d["poly"]]
    if tetto._area(poly) < 0:
        poly.reverse()
    n = len(poly)
    p, q = poly[i], poly[(i + 1) % n]
    dx, dy = q[0] - p[0], q[1] - p[1]
    L2 = dx * dx + dy * dy
    if L2 < EPS:
        return None, None
    loc = [(0.0, p[0], p[1], tetto._z_at(d, *p))]
    for c in d.get("ctrl") or ():
        t = ((c[0] - p[0]) * dx + (c[1] - p[1]) * dy) / L2
        if 1e-4 < t < 1 - 1e-4 and math.hypot(
                p[0] + t * dx - c[0], p[1] + t * dy - c[1]) < 1e-4:
            loc.append((t, c[0], c[1], c[2]))
    loc.append((1.0, q[0], q[1], tetto._z_at(d, *q)))
    loc.sort(key=lambda r: r[0])
    pts = [M.map(QVector3D(x, y, z)) for _t, x, y, z in loc]
    keep = [pts[0]]
    for k in range(1, len(pts) - 1):
        a, b = keep[-1], pts[k + 1]
        ab = b - a
        if ab.length() < EPS or _cross(pts[k] - a, ab).length() / ab.length() > 1e-3:
            keep.append(pts[k])
    keep.append(pts[-1])
    world = Polygon([(v.x(), v.y()) for v in
                     (M.map(QVector3D(x, y, 0.0)) for x, y in poly)])
    a, b = keep[0], keep[-1]
    ex, ey = b.y() - a.y(), -(b.x() - a.x())
    ln = math.hypot(ex, ey) or 1.0
    ex, ey = ex / ln, ey / ln
    mid = ((a.x() + b.x()) / 2.0, (a.y() + b.y()) / 2.0)
    try:
        if world.contains(Point(mid[0] + ex * 0.05, mid[1] + ey * 0.05)):
            ex, ey = -ex, -ey
    except Exception:
        pass
    return keep, (ex, ey)


def _seg_dist(x, y, a, b) -> float:
    dx, dy = b.x() - a.x(), b.y() - a.y()
    L2 = dx * dx + dy * dy
    if L2 < EPS:
        return math.hypot(x - a.x(), y - a.y())
    t = max(0.0, min(1.0, ((x - a.x()) * dx + (y - a.y()) * dy) / L2))
    return math.hypot(a.x() + t * dx - x, a.y() + t * dy - y)


def nearest_edge(scene, x, y):
    best = None
    for g in scene.groups:
        d = tetto.roof_data(g)
        if d is None:
            continue
        M = tetto._group_matrix(g)
        poly = [tuple(p) for p in d["poly"]]
        if tetto._area(poly) < 0:
            poly.reverse()
        n = len(poly)
        for i in range(n):
            a = M.map(QVector3D(*poly[i], 0.0))
            b = M.map(QVector3D(*poly[(i + 1) % n], 0.0))
            dist = _seg_dist(x, y, a, b)
            if dist <= PICK and (best is None or dist < best[0]):
                best = (dist, g, d, i)
    if best is None:
        return None
    _dist, g, d, i = best
    pts, eu = _edge_points(g, d, i)
    if not pts:
        return None
    return {"pts": [[v.x(), v.y(), v.z()] for v in pts], "eu": list(eu),
            "th": float(d.get("th", 0.0)), "roof": g}


def _spin(value, lo, hi, dec=3):
    s = LengthSpin()
    s.setDecimals(dec)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


def ask_params(parent, cur: dict, name: str):
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("Grondaia"))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    kind = QComboBox()
    for key, label in KINDS:
        kind.addItem(label, key)
    kind.setCurrentIndex(max(0, kind.findData(cur["kind"])))
    w = _spin(cur["w"], 0.03, 0.60)
    h = _spin(cur["h"], 0.03, 0.60)
    hooks = QSpinBox()
    hooks.setRange(0, 200)
    hooks.setValue(int(cur["hooks"]))
    pipe = QCheckBox(tr("Pluviale (discendente)"))
    pipe.setChecked(bool(cur["pipe"]))
    dp = _spin(cur["dp"], 0.03, 0.40)
    dist = _spin(cur["dist"], 0.0, 5.0)
    pos = _spin(cur["pos"], 0.0, 1.0, 2)
    qf = _spin(cur["qf"], -50.0, 100.0)
    drop = _spin(cur["drop"], 0.0, 5.0)
    form.addRow(tr("Tipo di grondaia"), kind)
    form.addRow(tr("Larghezza (diametro se tonda) (m)"), w)
    form.addRow(tr("Altezza (m)"), h)
    form.addRow(tr("Numero ganci a U (0 = nessuno)"), hooks)
    form.addRow(pipe)
    pipe_rows = [(tr("Diametro pluviale (m)"), dp),
                 (tr("Distanza dal muro: spostamento verso il muro (m)"), dist),
                 (tr("Posizione lungo il bordo (0 = inizio, 1 = fine)"), pos),
                 (tr("Quota finale del pluviale (m)"), qf),
                 (tr("Primo tratto verticale (m, 0 = automatico)"), drop)]
    for lab, wd in pipe_rows:
        form.addRow(lab, wd)
    paint = muri.add_paint_rows(form, cur.get, ZONES)
    nm = QLineEdit(name)
    form.addRow(tr("Nome"), nm)

    def sync(_i=0) -> None:
        h.setEnabled(kind.currentData() == "rect")
        for _l, wd in pipe_rows:
            wd.setEnabled(pipe.isChecked())
    kind.currentIndexChanged.connect(sync)
    pipe.toggled.connect(sync)
    sync()
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return None
    res = {"kind": kind.currentData(), "w": w.value(), "h": h.value(),
           "hooks": hooks.value(), "pipe": pipe.isChecked(),
           "dp": dp.value(), "dist": dist.value(), "pos": pos.value(),
           "qf": qf.value(), "drop": drop.value()}
    for k, v in muri.paint_results(paint).items():
        if v:
            res[k] = v
    return res, (nm.text().strip() or tr("Grondaia"))


def ask_settings(parent) -> bool:
    r = ask_params(parent, _params_from_settings(), _S.name)
    if r is None:
        return False
    res, name = r
    for k in ("kind", "w", "h", "hooks", "pipe", "dp", "dist", "pos", "qf",
              "drop"):
        setattr(_S, k, res[k])
    for k in PAINT_KEYS:
        setattr(_S, k, res.get(k))
    _S.name = name
    return True


MSG = tr("Grondaia: clic sul bordo di un tetto · Esc o tasto destro = esci")


class GrondaiaTool(Tool):
    name = tr("Grondaia")
    shortcut = None
    description = tr("Mette una grondaia con ganci e pluviale sul bordo di un tetto.")

    def __init__(self) -> None:
        self._entering = False
        self.hover = None
        self.pending = None

    def on_activate(self, viewport) -> None:
        if self._entering:
            self.hover = None
            self.pending = None
            viewport.flash_status(MSG, 7000)
            return
        if not ask_settings(viewport.window()):
            return
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def on_deactivate(self, viewport) -> None:
        self.hover = None
        self.pending = None

    def on_cancel(self, viewport) -> None:
        self.hover = None
        self.pending = None
        viewport.update()

    def _exit(self, viewport) -> None:
        if self.pending is not None:
            self.pending = None
            viewport.flash_status(MSG, 4000)
            viewport.update()
            return
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

    def on_hover(self, ctx: ToolContext) -> None:
        if self.pending is not None:
            try:
                self.pending["pos"], self.pending["dist"] = pipe_target(
                    self.pending, ctx.world.x(), ctx.world.y())
            except Exception:
                pass
            ctx.viewport.update()
            return
        try:
            self.hover = nearest_edge(ctx.viewport.scene,
                                      ctx.world.x(), ctx.world.y())
        except Exception:
            self.hover = None
        ctx.viewport.update()

    def rubber_band_lines(self):
        if self.pending is not None:
            pts = _pts3(self.pending)
            lines = list(zip(pts, pts[1:]))
            try:
                path = pipe_path(self.pending)
            except Exception:
                path = None
            if path:
                lines += list(zip(path, path[1:]))
            return lines
        if not self.hover:
            return []
        pts = [QVector3D(*p) for p in self.hover["pts"]]
        return list(zip(pts, pts[1:]))

    def draw_overlay(self, viewport, painter) -> None:
        try:
            if self.pending is not None:
                path = pipe_path(self.pending) or []
                painter.save()
                painter.setRenderHint(painter.RenderHint.Antialiasing)
                for p in path:
                    pc = viewport._world_to_pixel(p)
                    if pc is None:
                        continue
                    painter.setPen(QPen(QColor(255, 255, 255), 1.5))
                    painter.setBrush(QColor(240, 150, 30))
                    painter.drawEllipse(QPointF(pc[0], pc[1]), 4, 4)
                painter.restore()
                return
            if not self.hover:
                return
            painter.save()
            painter.setRenderHint(painter.RenderHint.Antialiasing)
            for p in self.hover["pts"]:
                pc = viewport._world_to_pixel(QVector3D(*p))
                if pc is None:
                    continue
                painter.setPen(QPen(QColor(255, 255, 255), 1.5))
                painter.setBrush(QColor(40, 190, 90))
                painter.drawEllipse(QPointF(pc[0], pc[1]), 4, 4)
            painter.restore()
        except Exception:
            pass

    def _commit(self, vp, d) -> None:
        name = _S.name

        def mutate(scene):
            build_gutter(scene, d, name)

        vp.history.execute(muri.MuriCommand(mutate))
        vp.notify_scene_changed()
        vp.flash_status(tr("Grondaia creata"), 3000)
        vp.update()

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        if getattr(vp.scene, "edit_group", None) is not None:
            vp.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        if self.pending is not None:
            d = self.pending
            self.pending = None
            try:
                d["pos"], d["dist"] = pipe_target(
                    d, ctx.world.x(), ctx.world.y())
                gutter_parts(d)
            except Exception as ex:
                vp.flash_status(tr("Grondaia: ") + str(ex), 6000)
                return
            self._commit(vp, d)
            return
        try:
            edge = nearest_edge(vp.scene, ctx.world.x(), ctx.world.y())
        except ImportError:
            vp.flash_status(tr("Serve shapely: pip install shapely"), 6000)
            return
        if edge is None:
            vp.flash_status(
                tr("Nessun bordo di tetto vicino: clicca vicino al bordo "
                   "di un tetto"), 4000)
            return
        d = _params_from_settings()
        d.update({"pts": edge["pts"], "eu": edge["eu"], "th": edge["th"]})
        try:
            gutter_parts(d)
        except Exception as ex:
            vp.flash_status(tr("Grondaia: ") + str(ex), 6000)
            return
        if d.get("pipe"):
            self.pending = d
            self.hover = None
            vp.flash_status(
                tr("Pluviale: muovi il mouse lungo la grondaia e verso/"
                   "lontano dal muro · clic = conferma · Esc = annulla"),
                8000)
            vp.update()
            return
        self._commit(vp, d)


def _selected_gutters(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and gutter_data(g) is not None and g not in out:
            out.append(g)
    return out


def edit_gutter(viewport, group=None) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    sel = [group] if group is not None else _selected_gutters(scene)
    if not sel:
        viewport.flash_status(tr("Seleziona una grondaia"), 3000)
        return
    d0 = gutter_data(sel[0])
    r = ask_params(viewport.window(), d0, sel[0].name)
    if r is None:
        return
    res, _name = r

    def mutate(sc):
        for g in sel:
            q = dict(gutter_data(g))
            for k in PAINT_KEYS:
                q.pop(k, None)
            q.update(res)
            rebuild_gutter(g, q)

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("Grondaia aggiornata"), 3000)


def _outliner_kind(group):
    d = gutter_data(group)
    if d is None:
        return None
    from ._imperial import fmt_len
    _ls, total = _lengths(_pts3(d))
    props = [(tr("Tipo"), dict(KINDS).get(d["kind"], d["kind"])),
             (tr("Lunghezza"), fmt_len(total)),
             (tr("Ganci"), str(int(d.get("hooks") or 0)))]
    if d.get("pipe"):
        props.append((tr("Pluviale"), f"Ø {fmt_len(d['dp'])}"))
    return {"type": tr("Grondaia"), "props": props}


def _icon():
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QIcon, QPainter, QPixmap, QPolygon
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(170, 90, 75))
    p.drawPolygon(QPolygon([QPoint(4, 20), QPoint(24, 5), QPoint(44, 20)]))
    p.setBrush(QColor(215, 205, 190))
    p.drawRect(10, 20, 28, 22)
    p.setBrush(QColor(160, 165, 170))
    p.drawRect(2, 18, 42, 5)
    p.drawRect(38, 22, 5, 20)
    p.end()
    return QIcon(pm)


def _hook_double_click(vp) -> None:
    if getattr(vp, "_myhouse_grondaia_dbl", False):
        return
    original = vp.begin_group_edit

    def begin_group_edit(group, *args, **kwargs):
        g = getattr(group, "owner", None) or group
        if gutter_data(g) is None:
            return original(group, *args, **kwargs)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: edit_gutter(vp, g))

    vp.begin_group_edit = begin_group_edit
    vp._myhouse_grondaia_dbl = True


def register(api) -> None:
    _hook_double_click(api.window.viewport)
    tool = GrondaiaTool()
    api.add_button(tr("Grondaia"),
                   tr("Grondaia con ganci a U e pluviale sul bordo del tetto"),
                   _icon(), api.run_tool(tool))
    app = api.app
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        from PySide6.QtCore import QTimer

        def context(menu, selection) -> None:
            if not _selected_gutters(app.viewport.scene):
                return
            menu.addSeparator()
            menu.addAction(
                tr("Modifica grondaia…"),
                lambda: QTimer.singleShot(
                    0, lambda: edit_gutter(app.viewport)))

        add_ctx(context)
    add_kind = getattr(app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
