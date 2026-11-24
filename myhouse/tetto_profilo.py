# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr
from ._imperial import LengthSpin
from ._scroll import scroll_form

import copy
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen, QVector3D
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QLineEdit, QVBoxLayout,
)

from core import bim
from . import _ifc
from tools.base import Tool, ToolContext

from . import muri, tetto

ORDER = 51
KEY = "myhouse_tetto_profilo"
EPS = 1e-6
SAME = 1e-4
ARC_STEP = math.radians(5.0)
PLANES = (("xz", tr("Prospetto con orizzontale = X (si guarda lungo Y)")),
          ("yz", tr("Prospetto con orizzontale = Y (si guarda lungo X)")))


class _Settings:
    plane = "xz"
    length = 5.0
    thickness = 0.20
    offset = 0.3
    flip = False
    name = tr("Tetto a profilo")


def arc_points(p0, pm, p1):
    ax, ay = p0
    bx, by = pm
    cx, cy = p1
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return [tuple(p1)]
    a2, b2, c2 = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    a0 = math.atan2(ay - uy, ax - ux)
    am = math.atan2(by - uy, bx - ux)
    a1 = math.atan2(cy - uy, cx - ux)
    tau = 2.0 * math.pi
    ccw = (a1 - a0) % tau
    sweep = ccw if (am - a0) % tau < ccw else ccw - tau
    n = max(4, int(math.ceil(abs(sweep) / ARC_STEP)))
    pts = [(ux + r * math.cos(a0 + sweep * k / n),
            uy + r * math.sin(a0 + sweep * k / n)) for k in range(1, n)]
    return pts + [tuple(p1)]


def polyline(start, segs):
    pts = [tuple(start)]
    for s in segs:
        if s[0] == "A":
            new = arc_points(pts[-1], tuple(s[1]), tuple(s[2]))
        else:
            new = [tuple(s[1])]
        for q in new:
            if math.hypot(q[0] - pts[-1][0], q[1] - pts[-1][1]) > SAME:
                pts.append(q)
    return pts


def profile_pts(d):
    pts = polyline(d["start"], d["segs"])
    if pts[-1][0] < pts[0][0]:
        pts.reverse()
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        a, b, c = out[-1], pts[i], pts[i + 1]
        cr = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        dt = (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1])
        if abs(cr) < 1e-9 and dt > 0:
            continue
        out.append(b)
    out.append(pts[-1])
    return out


def _newell(p3):
    nx = ny = nz = 0.0
    for i in range(len(p3)):
        a, b = p3[i], p3[(i + 1) % len(p3)]
        nx += (a.y() - b.y()) * (a.z() + b.z())
        ny += (a.z() - b.z()) * (a.x() + b.x())
        nz += (a.x() - b.x()) * (a.y() + b.y())
    return nx, ny, nz


def _orient(p3, want):
    n = _newell(p3)
    if n[0] * want[0] + n[1] * want[1] + n[2] * want[2] < 0:
        p3.reverse()
    return p3


def _pt(d, u, z, dep) -> QVector3D:
    return QVector3D(u, dep, z) if d["pl"] == "xz" else QVector3D(dep, u, z)


def _vec(d, nu, nz, nd=0.0):
    return (nu, nd, nz) if d["pl"] == "xz" else (nd, nu, nz)


def _strip_with_holes(d, face, holes, a, b, deps, th, up, down) -> bool:
    from shapely.geometry import Point, box
    from shapely.geometry.polygon import orient
    (u0, z0), (u1, z1) = a, b
    dmin, dmax = min(deps), max(deps)
    if d["pl"] == "xz":
        rect = box(min(u0, u1), dmin, max(u0, u1), dmax)
    else:
        rect = box(dmin, min(u0, u1), dmax, max(u0, u1))
    mine = [h for h in holes if rect.intersection(h).area > 1e-6]
    if not mine:
        return False
    s = (z1 - z0) / (u1 - u0)
    if d["pl"] == "xz":
        pa, pb = s, 0.0
    else:
        pa, pb = 0.0, s
    pc = z0 - s * u0
    rest = rect
    for h in mine:
        rest = rest.difference(h)
    for pg in tetto._polys_of(rest):
        ring = tetto._keyhole(pg)
        top = [QVector3D(x, y, pa * x + pb * y + pc) for x, y in ring]
        for a, b, c in tetto._triangulate_kh(ring):
            face([top[a], top[b], top[c]], "top", up)
            face([QVector3D(top[c].x(), top[c].y(), top[c].z() - th),
                  QVector3D(top[b].x(), top[b].y(), top[b].z() - th),
                  QVector3D(top[a].x(), top[a].y(), top[a].z() - th)],
                 "bottom", down)
    bound = rect.boundary
    for h in mine:
        for part in tetto._polys_of(rect.intersection(h)):
            op = orient(part, -1.0)
            for ring in [op.exterior] + list(op.interiors):
                r3 = list(ring.coords)[:-1]
                for i in range(len(r3)):
                    p, q = r3[i], r3[(i + 1) % len(r3)]
                    if bound.distance(Point((p[0] + q[0]) / 2,
                                            (p[1] + q[1]) / 2)) < 1e-6:
                        continue
                    zp = pa * p[0] + pb * p[1] + pc
                    zq = pa * q[0] + pb * q[1] + pc
                    face([QVector3D(p[0], p[1], zp - th),
                          QVector3D(q[0], q[1], zq - th),
                          QVector3D(q[0], q[1], zq),
                          QVector3D(p[0], p[1], zp)],
                         "side", (q[1] - p[1], p[0] - q[0], 0.0))
    return True


EDGE_FLAG = "hidden"


def smooth_joints(d) -> list:
    out = []
    last = tuple(d["start"])
    for s in d["segs"]:
        if s[0] == "A":
            new = arc_points(last, tuple(s[1]), tuple(s[2]))
            out.extend(new[:-1])
        last = tuple(s[-1])
    return out


def _nascondi_giunti(mesh, d) -> None:
    joints = smooth_joints(d)
    if not joints:
        return
    th = d["th"]
    horiz = d["pl"] == "xz"

    def on_joint(p, q) -> bool:
        up, uq = (p.x(), q.x()) if horiz else (p.y(), q.y())
        if abs(up - uq) > 1e-4:
            return False
        for ju, jz in joints:
            if abs(up - ju) < 1e-4 and all(
                    abs(v.z() - jz) < 1e-4 or abs(v.z() - (jz - th)) < 1e-4
                    for v in (p, q)):
                return True
        return False

    for e in mesh.edges:
        try:
            if on_joint(e.a, e.b):
                setattr(e, EDGE_FLAG, True)
        except Exception:
            pass


def roof_mesh(d):
    from core.mesh import Mesh
    P = QVector3D
    mesh = Mesh()
    th = d["th"]
    off = d.get("off", 0.0)
    dep0 = d["d0"] - d["dir"] * off
    dep1 = d["d0"] + d["dir"] * (d["len"] + off)
    pts = profile_pts(d)

    def face(q, zone, want):
        f = mesh.add_face(_orient(list(q), want))
        f.attrs["layer"] = tetto.LAYER_NAME
        if muri.paint_face(f, d.get("col_" + zone), d.get("tex_" + zone)) \
                and not d.get("tex_" + zone):
            f.attrs["mat"] = tetto.ZONE_MAT[zone]

    holes = tetto._hole_polys(d) if d.get("fori") else []
    for i in range(len(pts) - 1):
        (u0, z0), (u1, z1) = pts[i], pts[i + 1]
        up = _vec(d, -(z1 - z0), u1 - u0)
        down = tuple(-c for c in up)
        if holes and abs(u1 - u0) >= 1e-6 and _strip_with_holes(
                d, face, holes, (u0, z0), (u1, z1), (dep0, dep1), th, up, down):
            continue
        face([_pt(d, u0, z0, dep0), _pt(d, u1, z1, dep0),
              _pt(d, u1, z1, dep1), _pt(d, u0, z0, dep1)], "top", up)
        face([_pt(d, u0, z0 - th, dep0), _pt(d, u1, z1 - th, dep0),
              _pt(d, u1, z1 - th, dep1), _pt(d, u0, z0 - th, dep1)],
             "bottom", down)
    for dep, sign in ((dep0, -1.0), (dep1, 1.0)):
        want = _vec(d, 0.0, 0.0, sign * d["dir"])
        for (u0, z0), (u1, z1) in zip(pts, pts[1:]):
            if abs(u1 - u0) < 1e-6:
                continue
            pa, pb = _pt(d, u0, z0, dep), _pt(d, u1, z1, dep)
            for t0, t1 in tetto._open_pieces((pa.x(), pa.y()),
                                             (pb.x(), pb.y()), holes):
                ua, za = u0 + (u1 - u0) * t0, z0 + (z1 - z0) * t0
                ub, zb = u0 + (u1 - u0) * t1, z0 + (z1 - z0) * t1
                face([_pt(d, ua, za, dep), _pt(d, ub, zb, dep),
                      _pt(d, ub, zb - th, dep), _pt(d, ua, za - th, dep)],
                     "side", want)
    for (u, z), sgn in ((pts[0], -1.0), (pts[-1], 1.0)):
        pa, pb = _pt(d, u, z, dep0), _pt(d, u, z, dep1)
        for t0, t1 in tetto._open_pieces((pa.x(), pa.y()),
                                         (pb.x(), pb.y()), holes):
            da, db = dep0 + (dep1 - dep0) * t0, dep0 + (dep1 - dep0) * t1
            face([_pt(d, u, z, da), _pt(d, u, z, db),
                  _pt(d, u, z - th, db), _pt(d, u, z - th, da)],
                 "side", _vec(d, sgn, 0.0))
    _nascondi_giunti(mesh, d)
    return mesh


def underside(d) -> list:
    th = d["th"]
    off = d.get("off", 0.0)
    dep0 = d["d0"] - d["dir"] * off
    dep1 = d["d0"] + d["dir"] * (d["len"] + off)
    pts = profile_pts(d)
    out = []
    for (u0, z0), (u1, z1) in zip(pts, pts[1:]):
        if abs(u1 - u0) < 1e-6:
            continue
        ring = []
        for u, z, dep in ((u0, z0, dep0), (u1, z1, dep0),
                          (u1, z1, dep1), (u0, z0, dep1)):
            v = _pt(d, u, z - th, dep)
            ring.append((v.x(), v.y(), v.z()))
        out.append(ring)
    return out


def low(d) -> float:
    return min(z for _u, z in profile_pts(d)) - d["th"]


def profile_parts(d) -> list:
    from core.group import Group
    part = Group(roof_mesh(d), name=tr("Tetto"))
    part.component = False
    return [part]


def roof_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "segs" in data else None


def rebuild(group, d) -> None:
    group.children = profile_parts(d)
    _ifc.tag(group, "IfcRoof")
    ext = dict(group.ext or {})
    ext[KEY] = dict(d)
    group.ext = ext


def build(scene, d, name) -> None:
    from core.group import Group
    if not any(ly.name == tetto.LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(tetto.LAYER_NAME))
    g = Group(name=name)
    g.adopt(profile_parts(d))
    g.component = False
    g.layer = tetto.LAYER_NAME
    _ifc.tag(g, "IfcRoof", name)
    g.ext = {KEY: d}
    scene.groups.append(g)


def _selected(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and roof_data(g) is not None and g not in out:
            out.append(g)
    return out


def _tetto_paint(scene) -> dict:
    if scene is not None:
        for e in scene.selection:
            g = getattr(e, "owner", None) or e
            if g in scene.groups:
                rd = tetto.roof_data(g)
                if rd is not None:
                    return {k: copy.deepcopy(rd.get(k))
                            for k in tetto.PAINT_KEYS if rd.get(k)}
    return tetto.settings_paint()


def _clean_paint(res: dict) -> dict:
    for zone, dflt in tetto.ZONE_DEFAULT.items():
        c = res.get("col_" + zone)
        if res.get("tex_" + zone) and c and tuple(c) == tuple(dflt):
            res["col_" + zone] = None
    return res


def _spin(value, lo, hi):
    s = LengthSpin()
    s.setDecimals(3)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


def _disegno_profilo(p):
    r, t, dim = muri._r, muri._t, muri._dim
    path = QPainterPath()
    path.moveTo(30, 112)
    path.cubicTo(30, 36, 150, 36, 150, 112)
    path.lineTo(150, 124)
    path.cubicTo(150, 48, 30, 48, 30, 124)
    path.closeSubpath()
    p.setPen(QPen(muri._C_LINEA, 1.5))
    p.setBrush(muri._C_CORPO)
    p.drawPath(path)
    dim(p, 160, 112, 160, 124, "s", 1)
    t(p, 24, 22, tr("profilo (faccia superiore)"), size=8)
    t(p, 70, 150, tr("Prospetto"), size=9)
    r(p, 280, 30, 360, 130, muri._C_CORPO)
    pen = QPen(muri._C_LINEA, 1.0)
    pen.setStyle(Qt.DashLine)
    p.setPen(pen)
    p.drawLine(QPointF(274, 50), QPointF(366, 50))
    p.drawLine(QPointF(274, 110), QPointF(366, 110))
    dim(p, 270, 50, 270, 110, "l", -1)
    dim(p, 372, 30, 372, 50, "o", 1)
    dim(p, 372, 110, 372, 130, "o", 1)
    t(p, 300, 150, tr("Pianta"), size=9)


def ask_settings(parent, scene=None) -> bool:
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("Tetto a profilo"))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(muri._Schema(_disegno_profilo))
    plane = QComboBox()
    for k, label in PLANES:
        plane.addItem(label, k)
    plane.setCurrentIndex(0 if _Settings.plane == "xz" else 1)
    length = _spin(_Settings.length, 0.05, 1000.0)
    thick = _spin(_Settings.thickness, 0.02, 5.0)
    off = _spin(_Settings.offset, 0.0, 100.0)
    flip = QCheckBox(tr("Lunghezza verso il lato opposto (Spazio durante il disegno)"))
    flip.setChecked(_Settings.flip)
    name = QLineEdit(_Settings.name)
    form.addRow(tr("Piano del prospetto"), plane)
    form.addRow(tr("Lunghezza del tetto (l) (m)"), length)
    form.addRow(tr("Spessore verso il basso (s) (m)"), thick)
    form.addRow(tr("Sporto avanti e dietro (o) (m)"), off)
    form.addRow(flip)
    src = _tetto_paint(scene)
    paint = muri.add_paint_rows(form, lambda k: src.get(k), tetto.ROOF_ZONES)
    form.addRow(tr("Nome"), name)
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return False
    _Settings.plane = plane.currentData()
    _Settings.length = length.value()
    _Settings.thickness = thick.value()
    _Settings.offset = off.value()
    _Settings.flip = flip.isChecked()
    _Settings.name = name.text().strip() or tr("Tetto a profilo")
    for k, v in _clean_paint(muri.paint_results(paint)).items():
        setattr(_Settings, k, v)
    return True


MSG_LINE = tr("Tetto a profilo - LINEA: clic = punto · A = arco · Spazio = verso "
              "lunghezza · Backspace = annulla · Invio/tasto destro = crea · "
              "Esc = esci")
MSG_ARC = tr("Tetto a profilo - ARCO: clic = punto sull'arco, poi clic = punto "
             "finale · A = torna a linea · Backspace = annulla")


class ProfiloTool(Tool):
    name = tr("Tetto a profilo")
    shortcut = None
    description = tr("Crea un tetto da un profilo (linee e archi) disegnato "
                     "in prospetto.")

    def __init__(self) -> None:
        self._entering = False
        self._reset()

    def _reset(self) -> None:
        self.start = None
        self.segs: list = []
        self.mid = None
        self.arc = False
        self.dep = 0.0
        self.flip = _Settings.flip
        self.hover = None
        self.plane = _Settings.plane
        self.edit_group = None
        self.edit_d = None
        self.moving = None

    def on_activate(self, viewport) -> None:
        if self._entering:
            self._reset()
            viewport.flash_status(MSG_LINE, 7000)
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
        if self.start is not None and self.segs:
            self._commit(viewport)
        else:
            self._exit(viewport)
        return True

    def _uz(self, w):
        return (w.x(), w.z()) if self.plane == "xz" else (w.y(), w.z())

    def _depth_of(self, w) -> float:
        return w.y() if self.plane == "xz" else w.x()

    def _last(self):
        if self.segs:
            return tuple(self.segs[-1][-1])
        return self.start

    def _dict(self):
        if self.edit_d is not None:
            e = self.edit_d
            return {"pl": e["pl"], "d0": e["d0"], "th": e["th"],
                    "len": e["len"], "off": e.get("off", 0.0), "dir": -1.0 if self.flip else 1.0}
        return {"pl": self.plane, "d0": self.dep, "th": _Settings.thickness,
                "len": _Settings.length, "off": _Settings.offset, "dir": -1.0 if self.flip else 1.0}

    @staticmethod
    def _handles(start, segs):
        out = [(("s",), tuple(start))]
        for i, s in enumerate(segs):
            if s[0] == "A":
                out.append((("m", i), tuple(s[1])))
            out.append((("p", i), tuple(s[-1])))
        return out

    def _moved(self):
        start, segs = self.start, copy.deepcopy(self.segs)
        if self.moving is not None and self.hover is not None:
            h = list(self.hover)
            r = self.moving
            if r[0] == "s":
                start = tuple(h)
            elif r[0] == "m":
                segs[r[1]][1] = h
            else:
                segs[r[1]][-1] = h
        return start, segs

    def _edit_click(self, vp, w) -> None:
        p = self._uz(w)
        if self.moving is not None:
            self.hover = p
            self.start, self.segs = self._moved()
            self.moving = None
            vp.flash_status(tr("Punto spostato · Invio = applica · Esc = annulla"),
                            4000)
        else:
            d = self._dict()
            px = vp._world_to_pixel(QVector3D(w))
            best = None
            for ref, (u, z) in self._handles(self.start, self.segs):
                pc = vp._world_to_pixel(_pt(d, u, z, d["d0"]))
                if px is None or pc is None:
                    continue
                dist = math.hypot(pc[0] - px[0], pc[1] - px[1])
                if dist < 18 and (best is None or dist < best[0]):
                    best = (dist, ref)
            if best is None:
                vp.flash_status(tr("Clicca su un punto del profilo per spostarlo"),
                                3000)
            else:
                self.moving = best[1]
                self.hover = p
                vp.flash_status(tr("Clicca la nuova posizione del punto"), 4000)
        vp.update()

    def edit(self, viewport, group) -> None:
        d = roof_data(group)
        if d is None:
            return
        if getattr(viewport.scene, "edit_group", None) is not None:
            viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False
        self.plane = d["pl"]
        self.start = tuple(d["start"])
        self.segs = copy.deepcopy(d["segs"])
        self.dep = d["d0"]
        self.flip = d["dir"] < 0
        self.edit_group = group
        self.edit_d = dict(d)
        viewport.flash_status(
            tr("Modifica profilo: clic su un punto, poi clic sulla nuova posizione · "
               "Spazio = verso · Backspace = toglie l'ultimo tratto · "
               "Invio = applica · Esc = annulla"), 8000)
        viewport.update()

    def draw_overlay(self, viewport, painter) -> None:
        if self.edit_group is None or self.start is None:
            return
        try:
            d = self._dict()
            st, sg = self._moved()
            painter.save()
            for ref, (u, z) in self._handles(st, sg):
                pc = viewport._world_to_pixel(_pt(d, u, z, d["d0"]))
                if pc is None:
                    continue
                hot = ref == self.moving
                r = 7 if ref[0] != "m" else 5
                painter.setPen(QPen(QColor(255, 255, 255), 1.5))
                painter.setBrush(QColor(255, 210, 0) if hot else
                                 QColor(0, 170, 255) if ref[0] == "m"
                                 else QColor(220, 30, 30))
                painter.drawRect(QRectF(pc[0] - r, pc[1] - r, 2 * r, 2 * r))
            painter.restore()
        except Exception:
            pass

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        w = ctx.world
        if self.edit_group is not None:
            self._edit_click(vp, w)
            return
        p = self._uz(w)
        if self.start is None:
            self.start = p
            self.dep = self._depth_of(w)
            self.flip = _Settings.flip
        else:
            last = self._last()
            if math.hypot(p[0] - last[0], p[1] - last[1]) < SAME:
                return
            if self.arc:
                if self.mid is None:
                    self.mid = p
                    vp.update()
                    return
                self.segs.append(["A", list(self.mid), list(p)])
                self.mid = None
            else:
                self.segs.append(["L", list(p)])
        self.hover = p
        vp.update()

    def on_double_click(self, ctx: ToolContext) -> None:
        if self.edit_group is None:
            self._commit(ctx.viewport)

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover = self._uz(ctx.world)
        ctx.viewport.update()

    def claims_key(self, key: int, modifiers) -> bool:
        if modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        return key in (Qt.Key_Escape, Qt.Key_A, Qt.Key_Space) or (
            key == Qt.Key_C and self.start is not None)

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if key == Qt.Key_A:
            self.arc = not self.arc
            self.mid = None
            viewport.flash_status(MSG_ARC if self.arc else MSG_LINE, 5000)
            viewport.update()
            return True
        if key == Qt.Key_Space:
            self.flip = not self.flip
            viewport.flash_status(tr("Lunghezza verso il lato opposto"), 2000)
            viewport.update()
            return True
        if key in (Qt.Key_C, Qt.Key_Return, Qt.Key_Enter):
            if self.start is not None:
                self._commit(viewport)
            return True
        if key == Qt.Key_Backspace:
            if self.moving is not None:
                self.moving = None
            elif self.mid is not None:
                self.mid = None
            elif self.segs:
                self.segs.pop()
            else:
                self.start = None
            viewport.update()
            return True
        return False

    def rubber_band_lines(self):
        if self.start is None:
            return []
        d = self._dict()
        if self.edit_group is not None:
            pts = polyline(*self._moved())
            return [(_pt(d, *a, d["d0"]), _pt(d, *b, d["d0"]))
                    for a, b in zip(pts, pts[1:])]
        pts = polyline(self.start, self.segs)
        h = self.hover
        if h is not None:
            last = self._last()
            if self.arc and self.mid is not None:
                pts += arc_points(last, self.mid, h)
            else:
                pts = pts + [h]
        return [(_pt(d, *a, d["d0"]), _pt(d, *b, d["d0"]))
                for a, b in zip(pts, pts[1:])]

    def _commit(self, viewport) -> None:
        if getattr(viewport.scene, "edit_group", None) is not None:
            viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        if self.start is None or not self.segs:
            viewport.flash_status(tr("Servono almeno 2 punti del profilo"), 3000)
            return
        target = self.edit_group
        if target is not None:
            d = dict(self.edit_d)
            d["dir"] = -1.0 if self.flip else 1.0
        else:
            d = self._dict()
            for k in tetto.PAINT_KEYS:
                v = getattr(_Settings, k, None)
                if v:
                    d[k] = copy.deepcopy(v)
        d["start"] = list(self.start)
        d["segs"] = copy.deepcopy(self.segs)
        try:
            roof_mesh(d)
        except Exception as ex:
            viewport.flash_status(tr("Tetto a profilo: ") + str(ex), 6000)
            return
        name = _Settings.name

        def mutate(scene):
            if target is not None:
                rebuild(target, d)
            else:
                build(scene, d, name)
            tetto.update_roof_clips(scene)

        viewport.history.execute(muri.MuriCommand(mutate))
        viewport.notify_scene_changed()
        if target is not None:
            viewport.flash_status(tr("Tetto a profilo modificato"), 3000)
            self._exit(viewport)
            return
        viewport.flash_status(tr("Tetto a profilo creato"), 3000)
        self._reset()
        viewport.update()


def edit_profile(viewport, roofs=None) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    roofs = roofs or _selected(scene)
    if not roofs:
        viewport.flash_status(tr("Seleziona un tetto a profilo"), 3000)
        return
    first = roof_data(roofs[0])
    dlg = QDialog(viewport.window())
    dlg.setWindowTitle(tr("Modifica tetto a profilo"))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(muri._Schema(_disegno_profilo))
    length = _spin(first["len"], 0.05, 1000.0)
    thick = _spin(first["th"], 0.02, 5.0)
    off = _spin(first.get("off", 0.0), 0.0, 100.0)
    flip = QCheckBox(tr("Lunghezza verso il lato opposto"))
    flip.setChecked(first["dir"] < 0)
    form.addRow(tr("Lunghezza del tetto (l) (m)"), length)
    form.addRow(tr("Spessore verso il basso (s) (m)"), thick)
    form.addRow(tr("Sporto avanti e dietro (o) (m)"), off)
    form.addRow(flip)
    pk = muri.add_paint_rows(form, first.get, tetto.ROOF_ZONES)
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return
    paint = _clean_paint(muri.paint_results(pk))
    changed = {k: v for k, v in paint.items() if v != first.get(k)}

    def mutate(sc):
        for g in roofs:
            q = dict(roof_data(g))
            q["len"] = length.value()
            q["th"] = thick.value()
            q["off"] = off.value()
            q["dir"] = -1.0 if flip.isChecked() else 1.0
            for k, v in changed.items():
                if v:
                    q[k] = v
                else:
                    q.pop(k, None)
            rebuild(g, q)
        tetto.update_roof_clips(sc)

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("Tetto a profilo aggiornato"), 3000)


def _icon():
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(170, 90, 75))
    path = QPainterPath()
    path.moveTo(QPoint(4, 34))
    path.lineTo(QPoint(14, 24))
    path.cubicTo(20, 10, 30, 10, 34, 24)
    path.lineTo(44, 20)
    path.lineTo(44, 30)
    path.lineTo(34, 34)
    path.cubicTo(30, 22, 20, 22, 14, 34)
    path.closeSubpath()
    p.drawPath(path)
    p.end()
    return QIcon(pm)


def _outliner_kind(group):
    d = roof_data(group)
    if d is None:
        return None
    from ._imperial import fmt_len
    return {"type": tr("Tetto a profilo"),
            "props": [(tr("Spessore"), fmt_len(d["th"])),
                      (tr("Lunghezza"), fmt_len(d["len"])),
                      (tr("Sporto"), fmt_len(d.get("off", 0.0)))]}


def _hook_double_click(vp, tool) -> None:
    if getattr(vp, "_myhouse_profilo_dbl", False):
        return
    original = vp.begin_group_edit

    def begin_group_edit(group, *args, **kwargs):
        g = getattr(group, "owner", None) or group
        if roof_data(g) is None:
            return original(group, *args, **kwargs)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: edit_profile(vp, [g]))

    vp.begin_group_edit = begin_group_edit
    vp._myhouse_profilo_dbl = True


def register(api) -> None:
    tool = ProfiloTool()
    api.add_button(tr("Tetto a profilo"),
                   tr("Crea un tetto da un profilo (linee e archi) tracciato in prospetto"),
                   _icon(), api.run_tool(tool))
    app = api.app
    _hook_double_click(api.window.viewport, tool)
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        from PySide6.QtCore import QTimer

        def context(menu, selection) -> None:
            if not _selected(app.viewport.scene):
                return
            menu.addSeparator()
            menu.addAction(
                tr("Modifica profilo (punti)…"),
                lambda: QTimer.singleShot(
                    0, lambda: tool.edit(app.viewport,
                                         _selected(app.viewport.scene)[0])))
            menu.addAction(
                tr("Modifica tetto a profilo (misure, materiali)…"),
                lambda: QTimer.singleShot(0, lambda: edit_profile(app.viewport)))

        add_ctx(context)
    add_kind = getattr(app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
