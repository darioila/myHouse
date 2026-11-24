# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr
from ._imperial import FT, IN, LengthSpin, dflt
from ._scroll import scroll_form

import copy
import math

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPen, QPolygonF, QVector3D
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QLabel, QPushButton, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QLineEdit, QVBoxLayout,
)

from core import bim
from . import _ifc
from tools.base import Tool, ToolContext

from . import _codici, _tipi, muri
from ._strati import (layer_subs_flat, layers_row, layers_total,
                     paint_layer_face)

ORDER = 20
SLAB_COLOR = (0.72, 0.72, 0.70)
PAINT_KEYS = ("col_top", "tex_top", "col_side", "tex_side",
              "col_bottom", "tex_bottom")
SLAB_ZONES = (("top", tr("parte superiore")), ("side", tr("parte laterale")),
              ("bottom", tr("parte inferiore")))
TOP_COLOR = (1.0, 0.75, 0.80)
SIDE_COLOR = (1.0, 1.0, 1.0)
BOTTOM_COLOR = (1.0, 1.0, 1.0)
ZONE_DEFAULT = {"top": TOP_COLOR, "side": SIDE_COLOR, "bottom": BOTTOM_COLOR}
ZONE_MAT = {"top": tr("pavimento"), "side": tr("frontalino"),
            "bottom": tr("soffitto")}
LAYER_NAME = "Solai"
KEY = "myhouse_solaio"
EPS = 1e-6
GAP_TOL = 0.01
SCAVO_KEY = "myhouse_scavo"
SCAVO_LAYER = "Scavi"
SCAVO_ZONES = (("wall", tr("pareti")), ("floor", tr("fondo")))
SCAVO_COLORS = {"wall": (0.62, 0.55, 0.48), "floor": (0.55, 0.50, 0.44)}
SCAVO_MAT = {"wall": tr("pareti scavo"), "floor": tr("fondo scavo")}
SCAVO_PAINT_KEYS = ("col_wall", "tex_wall", "col_floor", "tex_floor")
MAX_ANGLE = 75.0


class _Settings:
    thickness = dflt(6 * IN, 0.20)
    z_top = 0.0
    name = tr("Solaio")
    auto = False
    used = False
    mat = None
    spline = False
    level = None
    col_top = list(TOP_COLOR)
    tex_top = None
    col_side = list(SIDE_COLOR)
    tex_side = None
    col_bottom = list(BOTTOM_COLOR)
    tex_bottom = None
    layers = None
    tipo_id = None
    tipo_nome = None


def settings_paint() -> dict:
    return {k: copy.deepcopy(getattr(_Settings, k, None))
            for k in PAINT_KEYS + ("mat", "tipo_id", "tipo_nome")
            if getattr(_Settings, k, None)}


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
            if any(inside(p, a, b, c) for p in idx
                   if p not in (a, b, c)
                   and pts[p] not in (pts[a], pts[b], pts[c])):
                continue
            tris.append((a, b, c))
            idx.pop(k)
            break
        else:
            break
    if len(idx) == 3:
        tris.append(tuple(idx))
    return tris


def _is_convex(pts) -> bool:
    n = len(pts)
    for i in range(n):
        a, b, c = pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        if (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) < -EPS:
            return False
    return True


def _in_poly(pt, poly) -> bool:
    x, y = pt
    ins = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and \
                x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            ins = not ins
    return ins


def _crosses(p, q, r, s_) -> bool:
    def o(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return (o(p, q, r) * o(p, q, s_) < -EPS * EPS
            and o(r, s_, p) * o(r, s_, q) < -EPS * EPS)


def _merge_holes(outer, holes):
    ring = list(outer)
    hs = []
    for h in holes:
        h = [tuple(p) for p in h]
        if _area(h) > 0:
            h.reverse()
        hs.append(h)
    hs.sort(key=lambda h: -max(p[0] for p in h))
    for n, h in enumerate(hs):
        k = max(range(len(h)), key=lambda i: h[i][0])
        m = h[k]
        others = hs[n + 1:]
        cands = sorted(range(len(ring)),
                       key=lambda i: (ring[i][0] < m[0] - EPS,
                                      math.dist(ring[i], m)))
        best = None
        for i in cands:
            v = ring[i]
            segs = [(ring[j], ring[(j + 1) % len(ring)])
                    for j in range(len(ring))]
            for o in others + [h]:
                segs += [(o[j], o[(j + 1) % len(o)]) for j in range(len(o))]
            if not any(_crosses(m, v, p, q) for p, q in segs):
                best = i
                break
        if best is None:
            best = cands[0]
        hh = h[k:] + h[:k]
        ring = ring[:best + 1] + hh + [hh[0]] + [ring[best]] + ring[best + 1:]
    return ring


_APP = {"app": None}


def _mat_attrs(name, scene=None):
    if not name:
        return None
    try:
        sc = scene if scene is not None else _APP["app"].viewport.scene
        mat = sc.materials.get(name)
        return dict(mat.face_attrs()) if mat is not None else None
    except Exception:
        return None


def _mat_combo(scene, current=None):
    try:
        mats = sorted(scene.materials) if scene is not None else []
    except Exception:
        mats = []
    if not mats and not current:
        return None
    cb = QComboBox()
    cb.addItem(tr("(predefinito)"), None)
    for m in mats:
        cb.addItem(m, m)
    if current and cb.findData(current) < 0:
        cb.addItem(current, current)
    cb.setCurrentIndex(max(0, cb.findData(current)))
    return cb


def _ask_material(viewport, current, label=tr("Materiale"), extra=None):
    mats = sorted(viewport.scene.materials)
    if not mats:
        viewport.flash_status(tr("Il documento non ha materiali"), 3000)
        return None
    dlg = QDialog(viewport.window())
    dlg.setWindowTitle(label)
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    combos = {}
    for key, text, cur in [("mat", label, current)] + list(extra or []):
        cb = QComboBox()
        cb.addItem(tr("(predefinito)"), None)
        for m in mats:
            cb.addItem(m, m)
        i = cb.findData(cur)
        cb.setCurrentIndex(max(0, i))
        form.addRow(text, cb)
        combos[key] = cb
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return None
    return {k: c.currentData() for k, c in combos.items()}


def slab_mesh(d, mesh=None):
    from core.mesh import Mesh
    if (mesh is None and d.get("layers") and not d.get("_lay")
            and not d.get("_hide_lay")):
        mesh = Mesh()
        eff = _scavi_eff(d)
        for sub in layer_subs_flat(d):
            sub = dict(sub)
            sub["_scavi_eff"] = eff
            slab_mesh(sub, mesh)
        return mesh
    P = QVector3D
    pts = [tuple(p) for p in d["poly"]]
    if _area(pts) < 0:
        pts.reverse()
    holes = [[tuple(p) for p in h] for h in d.get("holes", [])]
    sv = d.get("_scavi_eff")
    if sv is None:
        sv = _scavi_eff(d)
    dz = d.get("_dz", 0.0)
    cuts_top, cuts_all = [], []
    for s_ in sv:
        dep = s_["depth"]
        if dep <= dz + EPS:
            continue
        poly_s = [tuple(p) for p in s_["poly"]]
        if dep >= dz + d["th"] - EPS:
            cuts_all.append(poly_s)
        else:
            cuts_top.append(poly_s)
    zt = d["z"] - d.get("_dz", 0.0)
    zb = zt - d["th"]
    if mesh is None:
        mesh = Mesh()
    ma = _mat_attrs(d.get("mat"))

    def paint(f, zone=None, q=None):
        if zone and paint_layer_face(f, q, zone, d, ZONE_MAT):
            f.attrs["layer"] = LAYER_NAME
            return
        done = False
        if zone:
            done = muri.paint_face(f, d.get("col_" + zone),
                                   d.get("tex_" + zone))
            if done and not d.get("tex_" + zone):
                f.attrs["mat"] = ZONE_MAT[zone]
        if ma and not done:
            f.attrs.update(copy.deepcopy(ma))
        f.attrs["layer"] = LAYER_NAME

    def face(q, zone=None):
        paint(mesh.add_face(q), zone, q)

    def tri_fallback():
        h_t = holes + cuts_top + cuts_all
        h_b = holes + cuts_all
        ring = _merge_holes(pts, h_t) if h_t else pts
        for a, b, c in _triangulate(ring):
            face([P(*ring[a], zt), P(*ring[b], zt), P(*ring[c], zt)], "top")
        ring = _merge_holes(pts, h_b) if h_b else pts
        for a, b, c in _triangulate(ring):
            face([P(*ring[c], zb), P(*ring[b], zb), P(*ring[a], zb)],
                 "bottom")

    def _cw(h):
        return list(reversed(h)) if _area(h) > 0 else list(h)

    hs_top = [_cw(h) for h in holes + cuts_top + cuts_all]
    hs_bot = [list(reversed(_cw(h))) for h in holes + cuts_all]
    specs = ((pts, hs_top, zt, "top"),
             (list(reversed(pts)), hs_bot, zb, "bottom"))
    try:
        probe = Mesh()
        for q, hh, z, zone in specs:
            probe.add_face([P(*p, z) for p in q],
                           [[P(*p, z) for p in h] for h in hh])
        for q, hh, z, zone in specs:
            f = mesh.add_face([P(*p, z) for p in q],
                              [[P(*p, z) for p in h] for h in hh])
            paint(f, zone)
    except Exception:
        tri_fallback()
    loops = [pts] + [list(reversed(h)) if _area(h) > 0 else h for h in holes]
    for loop in loops:
        n = len(loop)
        for i in range(n):
            j = (i + 1) % n
            face([P(*loop[i], zb), P(*loop[j], zb),
                  P(*loop[j], zt), P(*loop[i], zt)], "side")
    if d.get("_pits") and not d.get("_lay"):
        for s_ in d.get("scavi") or []:
            scavo_mesh(dict(s_), d, mesh)
    return mesh


def slab_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "poly" in data else None


def rebuild_slab(group, d, scene=None) -> None:
    from core.group import Group
    part = Group(slab_mesh(d), name=tr("Solaio"))
    part.component = False
    group.children = [part]
    _ifc.tag(group, "IfcSlab")
    ext = dict(group.ext or {})
    ext[KEY] = dict(d)
    group.ext = ext
    _refresh_scavi(d, scene)


def build_slab(scene, poly, thickness, z_top, name, level=None,
               off=0.0, paint=None, layers=None) -> None:
    from core.group import Group
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    d = {"poly": [list(p) for p in poly], "th": thickness, "z": z_top}
    if layers:
        d["layers"] = copy.deepcopy(layers)
        d["th"] = layers_total(layers)
    if level:
        d.update({"lv": level["id"], "lvn": level["name"], "off": off})
    for k, v in (paint or {}).items():
        if k in PAINT_KEYS + ("mat", "tipo_id", "tipo_nome") and v:
            d[k] = copy.deepcopy(v)
    part = Group(slab_mesh(d), name=tr("Solaio"))
    part.component = False
    g = Group(name=name)
    g.adopt([part])
    g.component = False
    g.layer = LAYER_NAME
    _ifc.tag(g, "IfcSlab", name)
    g.ext = {KEY: d}
    scene.groups.append(g)


def _wall_polygon_world(group):
    d = muri.wall_data(group)
    aL, aR, bL, bR = muri.wall_corners(d)
    from PySide6.QtGui import QMatrix4x4
    m = muri.wall_pose(group)
    gx = getattr(group, "xform", None)
    if gx is not None:
        m = QMatrix4x4(gx) * m
    out = []
    for x, y in (aL, bL, bR, aR):
        v = m.map(QVector3D(x, y, 0.0))
        out.append((v.x(), v.y()))
    return out


def find_room(scene, x: float, y: float, level_id=None):
    from shapely.geometry import Point, Polygon
    from shapely.ops import unary_union

    polys = []
    for g in scene.groups:
        wd = muri.wall_data(g)
        if wd is None:
            continue
        if level_id and wd.get("lv") != level_id:
            continue
        p = Polygon(_wall_polygon_world(g))
        if not p.is_valid:
            p = p.buffer(0)
        polys.append(p.buffer(GAP_TOL, join_style=2))
    if not polys:
        return None
    union = unary_union(polys)
    pt = Point(x, y)
    geoms = getattr(union, "geoms", [union])
    for poly in geoms:
        for ring in poly.interiors:
            room = Polygon(ring)
            if room.contains(pt):
                room = room.buffer(GAP_TOL, join_style=2)
                room = room.simplify(0.001)
                return list(room.exterior.coords)[:-1]
    return None


def find_footprint(scene, x=None, y=None, level_id=None):
    """Outer outline (list of points) of the walls joined together: of the
    building (x, y) is in or nearest to, or of the largest one when no point
    is given. None if there are no walls. With level_id only that level's
    walls count, or every wall if that level has none.
    Raises ImportError without shapely."""
    from shapely.geometry import Point, Polygon
    from shapely.ops import unary_union

    def plans(level):
        out = []
        for g in scene.groups:
            wd = muri.wall_data(g)
            if wd is None or (level and wd.get("lv") != level):
                continue
            p = Polygon(_wall_polygon_world(g))
            if not p.is_valid:
                p = p.buffer(0)
            out.append(p.buffer(GAP_TOL, join_style=2))   # closes the gaps
        return out

    polys = plans(level_id) or (plans(None) if level_id else [])
    if not polys:
        return None
    union = unary_union(polys)
    shells = [Polygon(g.exterior) for g in getattr(union, "geoms", [union])]
    if x is None or y is None:
        shell = max(shells, key=lambda s: s.area)
    else:
        pt = Point(x, y)
        shell = min(shells, key=lambda s: s.distance(pt))
    foot = shell.buffer(-GAP_TOL, join_style=2).simplify(0.001)
    if foot.is_empty:
        return None
    if foot.geom_type != "Polygon":
        foot = max(foot.geoms, key=lambda s: s.area)
    return [(px, py) for px, py in list(foot.exterior.coords)[:-1]]


def _spin(value, lo, hi):
    s = LengthSpin()
    s.setDecimals(3)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


def _disegno_solaio(p):
    r, t, dim, ext = muri._r, muri._t, muri._dim, muri._ext
    t(p, 20, 12, tr("Pianta"), size=9)
    r(p, 20, 22, 200, 150, muri._C_BIANCO)
    r(p, 32, 34, 188, 138, muri._C_CORPO)
    r(p, 60, 60, 110, 100, muri._C_BIANCO)
    t(p, 70, 84, tr("foro"), size=9)
    p.setPen(QPen(muri._C_QUOTA, 1.5))
    p.drawLine(QPointF(142, 82), QPointF(152, 92))
    p.drawLine(QPointF(152, 82), QPointF(142, 92))
    t(p, 126, 110, tr("clic (auto)"), size=8)
    t(p, 250, 12, tr("Sezione"), size=9)
    r(p, 250, 94, 280, 160, muri._C_BIANCO)
    r(p, 410, 94, 440, 160, muri._C_BIANCO)
    r(p, 250, 54, 440, 94, muri._C_CORPO)
    pen = QPen(muri._C_LINEA, 1.2)
    pen.setStyle(Qt.DashDotLine)
    p.setPen(pen)
    p.drawLine(QPointF(236, 74), QPointF(454, 74))
    t(p, 340, 70, tr("quota piano"), size=8)
    dim(p, 236, 54, 236, 74, "z", -1)
    dim(p, 454, 54, 454, 94, "s")
    ext(p, 236, 54, 250, 54)
    t(p, 320, 125, tr("muri sotto"), size=8)


def _layer_presets():
    try:
        from . import sezione_strati
        return sezione_strati.presets_as_layers(sezione_strati.SOLAI_PRESETS)
    except Exception:
        return None


def ask_settings(parent, scene=None) -> bool:
    from . import piani
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("Solaio"))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(muri._Schema(_disegno_solaio))
    thick = _spin(_Settings.thickness, 0.02, 5.0)
    z = _spin(_Settings.z_top, -100.0, 1000.0)
    name = QLineEdit(_Settings.name)
    auto = QCheckBox(tr("Automatico: clic dentro una stanza chiusa da muri"))
    auto.setChecked(False)
    level = None
    if scene is not None and piani.levels(scene):
        level = piani.level_combo(scene, piani.active_id(scene))
        form.addRow(tr("Piano"), level)
    form.addRow(tr("Spessore (s) (m)"), thick)
    lay_state = [copy.deepcopy(_Settings.layers)]
    lrow = layers_row(dlg, thick, lay_state, _layer_presets(), kind="solaio")
    form.addRow(tr("Strati"), lrow)
    form.addRow(tr("Faccia superiore: sopra la quota del piano / da terra (z) (m)"), z)
    mat_cb = _mat_combo(scene, _Settings.mat)
    if mat_cb is not None:
        form.addRow(tr("Materiale (dal documento)"), mat_cb)
    paint = muri.add_paint_rows(form, lambda k: getattr(_Settings, k, None),
                                SLAB_ZONES)
    form.addRow(tr("Nome"), name)
    form.addRow(auto)

    def _result():
        res = muri.paint_results(paint)
        for zone, dflt in ZONE_DEFAULT.items():
            c = res.get("col_" + zone)
            if res.get("tex_" + zone) and c and tuple(c) == tuple(dflt):
                res["col_" + zone] = None
        L = lay_state[0] or None
        return dict(res, layers=copy.deepcopy(L),
                    th=layers_total(L) if L else thick.value(),
                    mat=mat_cb.currentData() if mat_cb is not None else None)

    def _set_tipo(t):
        w = dict(paint)
        if mat_cb is not None:
            w["mat"] = mat_cb
        _tipi.fill_widgets(w, dict(t, **{k: t.get(k) for k in paint}, mat=t.get("mat")))
        lay_state[0] = copy.deepcopy(t.get("layers")) or None
        if not lay_state[0] and "th" in t:
            thick.setValue(t["th"])
        lrow.refresh()

    tbar = _tipi.TypeBar(dlg, form, "solaio", {"tipo_id": _Settings.tipo_id},
                         _result, _set_tipo, scene, creating=True)
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return False
    _Settings.layers = lay_state[0] or None
    _Settings.thickness = (layers_total(_Settings.layers) if _Settings.layers
                           else thick.value())
    _Settings.z_top = z.value()
    _Settings.name = name.text().strip() or tr("Solaio")
    _Settings.auto = auto.isChecked()
    _Settings.mat = mat_cb.currentData() if mat_cb is not None else None
    res = muri.paint_results(paint)
    for zone, dflt in ZONE_DEFAULT.items():
        c = res.get("col_" + zone)
        if res.get("tex_" + zone) and c and tuple(c) == tuple(dflt):
            res["col_" + zone] = None
    for k, v in res.items():
        setattr(_Settings, k, v)
    if level is not None:
        _Settings.level = level.currentData() or None
        piani.set_active(_Settings.level)
    else:
        _Settings.level = None
    _Settings.used = True
    r = tbar.result(_result())
    _Settings.tipo_id, _Settings.tipo_nome = r.get("tipo_id"), r.get("tipo_nome")
    return True


def _ortho(points, p):
    if not (muri._Settings.ortho and points):
        return p
    last = points[-1]
    if abs(p.x() - last.x()) >= abs(p.y() - last.y()):
        return QVector3D(p.x(), last.y(), p.z())
    return QVector3D(last.x(), p.y(), p.z())


def _spline_closed(pts):
    P = [(p[0], p[1]) for p in pts]
    n = len(P)
    if n < 3:
        return P
    out = []
    for i in range(n):
        p0, p1, p2, p3 = P[i - 1], P[i], P[(i + 1) % n], P[(i + 2) % n]

        def tj(ti, a, b):
            return ti + max(math.hypot(b[0] - a[0], b[1] - a[1]), 1e-9) ** 0.5

        t0 = 0.0
        t1 = tj(t0, p0, p1)
        t2 = tj(t1, p1, p2)
        t3 = tj(t2, p2, p3)
        steps = max(6, min(32, int(math.hypot(p2[0] - p1[0],
                                              p2[1] - p1[1]) / 0.15)))

        def mix(a, b, wa, wb):
            return (a[0] * wa + b[0] * wb, a[1] * wa + b[1] * wb)

        for k in range(steps):
            t = t1 + (t2 - t1) * k / steps
            a1 = mix(p0, p1, (t1 - t) / (t1 - t0), (t - t0) / (t1 - t0))
            a2 = mix(p1, p2, (t2 - t) / (t2 - t1), (t - t1) / (t2 - t1))
            a3 = mix(p2, p3, (t3 - t) / (t3 - t2), (t - t2) / (t3 - t2))
            b1 = mix(a1, a2, (t2 - t) / (t2 - t0), (t - t0) / (t2 - t0))
            b2 = mix(a2, a3, (t3 - t) / (t3 - t1), (t - t1) / (t3 - t1))
            out.append(mix(b1, b2, (t2 - t) / (t2 - t1), (t - t1) / (t2 - t1)))
    return out


def _toggle_ortho(tool, viewport) -> None:
    muri._Settings.ortho = not muri._Settings.ortho
    if tool.hover_point is not None:
        tool.hover_point = _ortho(tool.points, tool.hover_point)
    viewport.flash_status(
        tr("Ortogonale ") + (tr("attivo") if muri._Settings.ortho else tr("disattivato")),
        2000)
    viewport.update()


class SolaioTool(Tool):
    name = tr("Solaio")
    shortcut = None
    description = tr("Crea un solaio: automatico (clic in una stanza) o a punti.")

    def __init__(self) -> None:
        self._entering = False
        self._reset()

    def _reset(self) -> None:
        self.points: list[QVector3D] = []
        self.hover_point: QVector3D | None = None

    def on_activate(self, viewport) -> None:
        if self._entering:
            self._reset()
            _Settings.spline = False
            viewport.flash_status(
                tr("Solaio: clic dentro una stanza chiusa da muri")
                if _Settings.auto else
                tr("Solaio: clic per i vertici · S = spline · C/Invio = crea · "
                "Esc = esci"),
                6000)
            return
        if not ask_settings(viewport.window(), viewport.scene):
            return
        self.start_same(viewport)

    def start_same(self, viewport) -> None:
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def on_deactivate(self, viewport) -> None:
        self._reset()

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        p = QVector3D(ctx.world)
        if _Settings.auto:
            try:
                poly = find_room(vp.scene, p.x(), p.y(), _Settings.level)
            except ImportError:
                vp.flash_status(tr("Serve shapely: pip install shapely"), 6000)
                return
            if poly is None:
                vp.flash_status(
                    tr("Nessuna stanza chiusa qui: controlla che i muri si "
                    "chiudano (o usa il modo manuale)"), 5000)
                return
            self._commit(vp, poly)
            return
        if not _Settings.spline:
            p = _ortho(self.points, p)
        if self.points and (p - self.points[-1]).length() < EPS:
            return
        self.points.append(p)
        self.hover_point = p
        vp.update()

    def on_hover(self, ctx: ToolContext) -> None:
        self._scene = ctx.viewport.scene
        p = QVector3D(ctx.world)
        self.hover_point = (p if _Settings.auto or _Settings.spline
                            else _ortho(self.points, p))
        ctx.viewport.update()

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    def claims_key(self, key: int, modifiers) -> bool:
        if modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        if key == Qt.Key_F8:
            return True
        if key in (Qt.Key_O, Qt.Key_S) and not _Settings.auto:
            return True
        return key == Qt.Key_Escape or (
            key == Qt.Key_C and bool(self.points))

    def _exit(self, viewport) -> None:
        self._reset()
        viewport.update()
        back = getattr(viewport.window(), "activate_select_tool", None)
        if callable(back):
            back()

    def _finish(self, viewport) -> bool:
        pts = muri._dedupe([(p.x(), p.y()) for p in self.points], True)
        if len(pts) < 3:
            viewport.flash_status(tr("Servono almeno 3 vertici"), 3000)
            return False
        if _Settings.spline:
            pts = muri._dedupe(_spline_closed(pts), True)
        self._commit(viewport, pts)
        return not self.points

    def context_menu(self, viewport, pos) -> bool:
        if self.points and not _Settings.auto:
            n = len(muri._dedupe([(p.x(), p.y()) for p in self.points], True))
            if n >= 3:
                if self._finish(viewport):
                    viewport.flash_status(
                        tr("Solaio creato · clic = nuovo solaio identico · "
                           "tasto destro o Esc = esci"), 5000)
            else:
                self._reset()
                viewport.flash_status(tr("Contorno annullato"), 2500)
                viewport.update()
            return True
        self._exit(viewport)
        return True

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if key == Qt.Key_S and not _Settings.auto:
            _Settings.spline = not _Settings.spline
            viewport.flash_status(
                tr("Spline attiva: i punti guidano una curva chiusa")
                if _Settings.spline else tr("Spline disattivata"), 3000)
            viewport.update()
            return True
        if key in (Qt.Key_O, Qt.Key_F8) and not (
                _Settings.auto and key == Qt.Key_O):
            _toggle_ortho(self, viewport)
            return True
        if _Settings.auto:
            return False
        if key in (Qt.Key_C, Qt.Key_Return, Qt.Key_Enter) and self.points:
            self._finish(viewport)
            return True
        if key == Qt.Key_Backspace and self.points:
            self.points.pop()
            viewport.update()
            return True
        return False

    def rubber_band_lines(self):
        if _Settings.auto or not self.points:
            return []
        pts = list(self.points)
        if self.hover_point is not None:
            pts.append(self.hover_point)
        z = self._top_z()
        P = QVector3D
        if _Settings.spline and len(pts) >= 3:
            cur = _spline_closed([(p.x(), p.y()) for p in pts])
            return [(P(a[0], a[1], z), P(b[0], b[1], z))
                    for a, b in zip(cur, cur[1:] + cur[:1])]
        lines = [(P(a.x(), a.y(), z), P(b.x(), b.y(), z))
                 for a, b in zip(pts, pts[1:])]
        if len(pts) >= 3:
            lines.append((P(pts[-1].x(), pts[-1].y(), z),
                          P(pts[0].x(), pts[0].y(), z)))
        return lines

    def _top_z(self, scene=None) -> float:
        from . import piani
        sc = scene if scene is not None else getattr(self, "_scene", None)
        lv = piani.get(sc, _Settings.level) if sc is not None else None
        return (lv["z"] if lv else 0.0) + _Settings.z_top

    def _commit(self, viewport, poly) -> None:
        if getattr(viewport.scene, "edit_group", None) is not None:
            viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        from . import piani
        t, name = _Settings.thickness, _Settings.name
        lvl = piani.get(viewport.scene, _Settings.level)
        z = self._top_z(viewport.scene)
        off = _Settings.z_top
        paint = settings_paint()
        layers = copy.deepcopy(_Settings.layers)

        def mutate(scene):
            build_slab(scene, poly, t, z, name, lvl, off, paint, layers)

        viewport.history.execute(muri.MuriCommand(mutate))
        viewport.notify_scene_changed()
        viewport.flash_status(tr("Solaio creato"), 3000)
        self._reset()
        viewport.update()


def _slab_at(scene, pts, only=None):
    for g in scene.groups:
        d = slab_data(g)
        if only is not None and (d is None or d["poly"] != only):
            continue
        if d and all(_in_poly(p, d["poly"]) for p in pts):
            return d
    return None


class ForoSolaioTool(Tool):
    name = tr("Foro solaio")
    shortcut = None
    description = (tr("Fora un solaio: clic per i vertici del foro dentro il "
                   "solaio, C/Invio = crea, Esc = esci."))

    def __init__(self) -> None:
        self._entering = False
        self._reset()

    def _reset(self) -> None:
        self.points: list[QVector3D] = []
        self.hover_point: QVector3D | None = None
        self._z = 0.0

    _target = None

    def start(self, viewport, poly) -> None:
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False
        self._target = [list(p) for p in poly]

    def on_activate(self, viewport) -> None:
        if not self._entering:
            self._entering = True
            try:
                viewport.set_active_tool(self)
            finally:
                self._entering = False
            return
        self._reset()
        viewport.flash_status(
            tr("Foro: clic per i vertici dentro il solaio · C/Invio = crea "
            "· Backspace = annulla punto · Esc = esci"), 6000)

    def on_deactivate(self, viewport) -> None:
        self._reset()
        self._target = None

    def on_click(self, ctx: ToolContext) -> None:
        p = QVector3D(ctx.world)
        if not self.points:
            d = _slab_at(ctx.viewport.scene, [(p.x(), p.y())], self._target)
            if d is None:
                ctx.viewport.flash_status(tr("Clicca dentro un solaio"), 3000)
                return
            self._z = d["z"]
        p = _ortho(self.points, p)
        if self.points and (p - self.points[-1]).length() < EPS:
            return
        self.points.append(p)
        self.hover_point = p
        ctx.viewport.update()

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = _ortho(self.points, QVector3D(ctx.world))
        ctx.viewport.update()

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    def claims_key(self, key: int, modifiers) -> bool:
        if modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        if key in (Qt.Key_O, Qt.Key_F8):
            return True
        return key == Qt.Key_Escape or (
            key == Qt.Key_C and bool(self.points))

    def _exit(self, viewport) -> None:
        self._reset()
        viewport.update()
        back = getattr(viewport.window(), "activate_select_tool", None)
        if callable(back):
            back()

    def context_menu(self, viewport, pos) -> bool:
        self._exit(viewport)
        return True

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if key in (Qt.Key_O, Qt.Key_F8):
            _toggle_ortho(self, viewport)
            return True
        if key in (Qt.Key_C, Qt.Key_Return, Qt.Key_Enter) and self.points:
            pts = muri._dedupe([(p.x(), p.y()) for p in self.points], True)
            if len(pts) < 3:
                viewport.flash_status(tr("Servono almeno 3 vertici"), 3000)
            else:
                self._commit(viewport, pts)
            return True
        if key == Qt.Key_Backspace and self.points:
            self.points.pop()
            viewport.update()
            return True
        return False

    def rubber_band_lines(self):
        if not self.points:
            return []
        pts = list(self.points)
        if self.hover_point is not None:
            pts.append(self.hover_point)
        P = QVector3D
        z = self._z
        lines = [(P(a.x(), a.y(), z), P(b.x(), b.y(), z))
                 for a, b in zip(pts, pts[1:])]
        if len(pts) >= 3:
            lines.append((P(pts[-1].x(), pts[-1].y(), z),
                          P(pts[0].x(), pts[0].y(), z)))
        return lines

    def _commit(self, viewport, hole) -> None:
        if getattr(viewport.scene, "edit_group", None) is not None:
            viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        target = _slab_at(viewport.scene, hole, self._target)
        if target is None:
            viewport.flash_status(
                tr("Il foro deve stare tutto dentro un solaio"), 4000)
            return
        key_poly = [list(p) for p in target["poly"]]
        hole = [list(p) for p in hole]

        def mutate(scene):
            for g in scene.groups:
                d = slab_data(g)
                if d is not None and d["poly"] == key_poly:
                    nd = copy.deepcopy(d)
                    nd.setdefault("holes", []).append(hole)
                    rebuild_slab(g, nd)
                    return

        viewport.history.execute(muri.MuriCommand(mutate))
        viewport.notify_scene_changed()
        viewport.flash_status(tr("Foro creato (Ctrl+Z per annullare)"), 3000)
        self._reset()
        viewport.update()
        if self._target is not None:
            self._exit(viewport)


_FORO = ForoSolaioTool()
_EDIT = {"dlg": None}

# ======================================================================
#  SCAVO: foro NON passante nel solaio (profondità e bordi a scelta)
# ======================================================================
class _ScavoSettings:
    depth = 0.10
    angle = 0.0
    name = tr("Scavo")
    col_wall = list(SCAVO_COLORS["wall"])
    tex_wall = None
    col_floor = list(SCAVO_COLORS["floor"])
    tex_floor = None


def scavo_data(group):
    data = (getattr(group, "ext", None) or {}).get(SCAVO_KEY)
    return data if isinstance(data, dict) and "poly" in data else None


def _scavi_eff(d):
    """Scavi del solaio con profondità limitata allo spessore (mai passante)."""
    th = d["th"]
    out = []
    for s_ in d.get("scavi") or []:
        dep = min(float(s_["depth"]), th - 0.005)
        if dep > EPS:
            out.append({"poly": s_["poly"], "depth": dep})
    return out


def _inset(pts, off):
    """Poligono (antiorario) rimpicciolito di `off`, stessi vertici."""
    n = len(pts)
    pts = [tuple(p) for p in pts]
    if off <= EPS or n < 3:
        return pts
    k = off
    for _ in range(30):
        out = []
        for i in range(n):
            p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % n]
            e1 = (p1[0] - p0[0], p1[1] - p0[1])
            e2 = (p2[0] - p1[0], p2[1] - p1[1])
            l1 = math.hypot(*e1) or 1e-12
            l2 = math.hypot(*e2) or 1e-12
            n1 = (-e1[1] / l1, e1[0] / l1)
            n2 = (-e2[1] / l2, e2[0] / l2)
            den = max(1.0 + n1[0] * n2[0] + n1[1] * n2[1], 0.05)
            out.append((p1[0] + (n1[0] + n2[0]) * k / den,
                        p1[1] + (n1[1] + n2[1]) * k / den))
        ok = _area(out) > EPS
        if ok:
            for i in range(n):
                a, b = out[i], out[(i + 1) % n]
                o0, o1 = pts[i], pts[(i + 1) % n]
                if ((b[0] - a[0]) * (o1[0] - o0[0])
                        + (b[1] - a[1]) * (o1[1] - o0[1])) <= 0:
                    ok = False
                    break
        if ok:
            return out
        k *= 0.8
    return pts


def scavo_mesh(sd, slab_d, mesh=None):
    from core.mesh import Mesh
    P = QVector3D
    pts = [tuple(p) for p in sd["poly"]]
    if _area(pts) < 0:
        pts.reverse()
    zt = slab_d["z"]
    dep = max(min(float(sd["depth"]), slab_d["th"] - 0.005), 0.001)
    zf = zt - dep
    ang = min(max(float(sd.get("angle") or 0.0), 0.0), MAX_ANGLE)
    fl = _inset(pts, dep * math.tan(math.radians(ang)))
    if mesh is None:
        mesh = Mesh()

    def paint(f, zone):
        col = sd.get("col_" + zone) or list(SCAVO_COLORS[zone])
        tex = sd.get("tex_" + zone)
        done = muri.paint_face(f, col, tex)
        if done and not tex:
            f.attrs["mat"] = SCAVO_MAT[zone]
        f.attrs["layer"] = SCAVO_LAYER

    try:
        paint(mesh.add_face([P(*p, zf) for p in fl]), "floor")
    except Exception:
        for a, b, c in _triangulate(fl):
            paint(mesh.add_face([P(*fl[a], zf), P(*fl[b], zf),
                                 P(*fl[c], zf)]), "floor")
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        paint(mesh.add_face([P(*pts[i], zt), P(*pts[j], zt),
                             P(*fl[j], zf), P(*fl[i], zf)]), "wall")
    return mesh


def rebuild_scavo(group, sd, slab_d) -> None:
    from core.group import Group
    part = Group(scavo_mesh(sd, slab_d), name=tr("Scavo"))
    part.component = False
    group.children = [part]
    try:
        _ifc.tag(group, "IfcBuildingElementProxy")
    except Exception:
        pass
    ext = dict(group.ext or {})
    ext[SCAVO_KEY] = dict(sd)
    group.ext = ext


def _refresh_scavi(d, scene=None) -> None:
    """Riallinea la geometria degli scavi dopo una modifica del solaio."""
    if not d.get("scavi"):
        return
    try:
        sc = scene if scene is not None else _APP["app"].viewport.scene
        for gg in sc.groups:
            sd = scavo_data(gg)
            if sd is not None and sd["slab"] == d["poly"]:
                rebuild_scavo(gg, sd, d)
    except Exception:
        pass


def _find_slab(scene, key):
    for g in scene.groups:
        d = slab_data(g)
        if d is not None and d["poly"] == key:
            return g
    return None


def _find_scavo(scene, key):
    for g in scene.groups:
        d = scavo_data(g)
        if d is not None and d["poly"] == key:
            return g
    return None


def _apply_scavi(scene, slab_key) -> None:
    """Rilegge gli scavi della scena, aggiorna il solaio e le loro mesh."""
    g = _find_slab(scene, slab_key)
    if g is None:
        return
    nd = copy.deepcopy(slab_data(g))
    lst = []
    for gg in scene.groups:
        sd = scavo_data(gg)
        if sd is not None and sd["slab"] == nd["poly"]:
            lst.append({"poly": [list(p) for p in sd["poly"]],
                        "depth": sd["depth"],
                        "angle": sd.get("angle") or 0.0})
    if lst:
        nd["scavi"] = lst
    else:
        nd.pop("scavi", None)
    rebuild_slab(g, nd, scene)
    for gg in scene.groups:
        sd = scavo_data(gg)
        if sd is not None and sd["slab"] == nd["poly"]:
            rebuild_scavo(gg, sd, nd)


def build_scavo(scene, slab_g, poly, st) -> None:
    from core.group import Group
    slab_d = slab_data(slab_g)
    if not any(ly.name == SCAVO_LAYER for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(SCAVO_LAYER))
    sd = {"poly": [list(p) for p in poly], "depth": st["depth"],
          "angle": st["angle"], "slab": [list(p) for p in slab_d["poly"]]}
    for k in SCAVO_PAINT_KEYS:
        if st.get(k):
            sd[k] = copy.deepcopy(st[k])
    name = st.get("name") or tr("Scavo")
    part = Group(scavo_mesh(sd, slab_d), name=tr("Scavo"))
    part.component = False
    g = Group(name=name)
    g.adopt([part])
    g.component = False
    g.layer = SCAVO_LAYER
    try:
        _ifc.tag(g, "IfcBuildingElementProxy", name)
    except Exception:
        pass
    g.ext = {SCAVO_KEY: sd}
    scene.groups.append(g)
    _apply_scavi(scene, sd["slab"])


def _disegno_scavo(p):
    r, t, dim, ext = muri._r, muri._t, muri._dim, muri._ext
    t(p, 20, 12, tr("Sezione"), size=9)
    r(p, 20, 50, 440, 120, muri._C_CORPO)
    p.setPen(QPen(muri._C_LINEA, 1.5))
    p.setBrush(muri._C_BIANCO)
    p.drawPolygon(QPolygonF([QPointF(120, 50), QPointF(340, 50),
                             QPointF(310, 95), QPointF(150, 95)]))
    t(p, 205, 76, tr("scavo"), size=9)
    dim(p, 90, 50, 90, 95, "h", -1)
    ext(p, 90, 50, 120, 50)
    t(p, 345, 92, "α", size=9)
    t(p, 20, 140, tr("α = 0: bordi verticali"), size=8)
    t(p, 250, 140, tr("sotto lo scavo il solaio resta"), size=8)


def _pget(d):
    def get(k):
        v = d.get(k)
        if v is None and k.startswith("col_"):
            c = SCAVO_COLORS.get(k[4:])
            return list(c) if c else None
        return v
    return get


def _scavo_widgets(form, get):
    form.addRow(muri._Schema(_disegno_scavo))
    name = QLineEdit(get("name") or tr("Scavo"))
    depth = _spin(get("depth") or 0.10, 0.005, 50.0)
    mode = QComboBox()
    mode.addItem(tr("Verticali"), False)
    mode.addItem(tr("Inclinati"), True)
    a0 = float(get("angle") or 0.0)
    mode.setCurrentIndex(1 if a0 > EPS else 0)
    ang = _spin(a0 if a0 > EPS else 45.0, 1.0, MAX_ANGLE)
    ang.setDecimals(1)
    ang.setSuffix(" °")
    ang.setEnabled(a0 > EPS)
    mode.currentIndexChanged.connect(
        lambda *_: ang.setEnabled(bool(mode.currentData())))
    form.addRow(tr("Nome"), name)
    form.addRow(tr("Profondità (h) (m) - non passante"), depth)
    form.addRow(tr("Bordi"), mode)
    form.addRow(tr("Inclinazione dalla verticale (α)"), ang)
    paint = muri.add_paint_rows(form, get, SCAVO_ZONES)
    return name, depth, mode, ang, paint


def _scavo_values(name, depth, mode, ang, paint):
    res = {"name": name.text().strip() or tr("Scavo"),
           "depth": depth.value(),
           "angle": ang.value() if mode.currentData() else 0.0}
    res.update(muri.paint_results(paint))
    return res


def ask_scavo_settings(parent) -> bool:
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("Scavo"))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    w = _scavo_widgets(form, lambda k: getattr(_ScavoSettings, k, None))
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return False
    for k, v in _scavo_values(*w).items():
        setattr(_ScavoSettings, k, v)
    return True


class ScavoTool(ForoSolaioTool):
    name = tr("Scavo")
    description = tr("Scavo nel solaio (foro non passante): clic per i "
                     "vertici dentro il solaio, C/Invio = crea, Esc = esci.")

    def on_activate(self, viewport) -> None:
        if self._entering:
            self._reset()
            viewport.flash_status(
                tr("Scavo: clic per i vertici dentro il solaio · C/Invio = "
                   "crea · Backspace = annulla punto · Esc = esci"), 6000)
            return
        if not ask_scavo_settings(viewport.window()):
            return
        self.start_same(viewport)

    def start_same(self, viewport) -> None:
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def _commit(self, viewport, poly) -> None:
        if getattr(viewport.scene, "edit_group", None) is not None:
            viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        target = _slab_at(viewport.scene, poly, self._target)
        if target is None:
            viewport.flash_status(
                tr("Lo scavo deve stare tutto dentro un solaio"), 4000)
            return
        key = [list(p) for p in target["poly"]]
        poly = [list(p) for p in poly]
        st = {k: copy.deepcopy(getattr(_ScavoSettings, k, None))
              for k in ("name", "depth", "angle") + SCAVO_PAINT_KEYS}
        limited = st["depth"] >= target["th"] - 0.005

        def mutate(scene):
            sg = _find_slab(scene, key)
            if sg is not None:
                build_scavo(scene, sg, poly, st)

        viewport.history.execute(muri.MuriCommand(mutate))
        viewport.notify_scene_changed()
        viewport.flash_status(
            tr("Profondità limitata allo spessore del solaio (foro non passante)")
            if limited else tr("Scavo creato (Ctrl+Z per annullare)"), 4000)
        self._reset()
        viewport.update()
        if self._target is not None:
            self._exit(viewport)


def _selected_scavi(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and scavo_data(g) is not None and g not in out:
            out.append(g)
    return out


def edit_scavo(viewport) -> None:
    scene = viewport.scene
    sel = _selected_scavi(scene)
    if len(sel) != 1:
        viewport.flash_status(tr("Seleziona uno scavo"), 3000)
        return
    g = sel[0]
    sd = scavo_data(g)
    key = [list(p) for p in sd["poly"]]
    skey = [list(p) for p in sd["slab"]]
    old = _EDIT["dlg"]
    if old is not None:
        try:
            old.close()
        except RuntimeError:
            pass
    dlg = QDialog(viewport.window())
    dlg.setWindowTitle(tr("Modifica scavo"))
    dlg.setAttribute(Qt.WA_DeleteOnClose, True)
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    w = _scavo_widgets(form, _pget(dict(sd, name=getattr(g, "name", "")
                                        or tr("Scavo"))))
    scroll_form(dlg, lay, form)

    def apply() -> None:
        res = _scavo_values(*w)

        def mutate(sc):
            gg = _find_scavo(sc, key)
            if gg is None:
                return
            nd = copy.deepcopy(scavo_data(gg))
            nd["depth"] = res["depth"]
            nd["angle"] = res["angle"]
            for k in SCAVO_PAINT_KEYS:
                if res.get(k):
                    nd[k] = res[k]
                else:
                    nd.pop(k, None)
            gg.name = res["name"]
            ext = dict(gg.ext or {})
            ext[SCAVO_KEY] = nd
            gg.ext = ext
            _apply_scavi(sc, skey)

        viewport.history.execute(muri.MuriCommand(mutate))
        viewport.notify_scene_changed()
        viewport.update()
        viewport.flash_status(tr("Scavo modificato"), 3000)

    box = QDialogButtonBox()
    b_apply = box.addButton(tr("Applica"), QDialogButtonBox.AcceptRole)
    b_close = box.addButton(tr("Chiudi"), QDialogButtonBox.RejectRole)
    b_apply.clicked.connect(apply)
    b_close.clicked.connect(dlg.close)
    lay.addWidget(box)
    _EDIT["dlg"] = dlg
    dlg.show()


def remove_scavi(viewport) -> None:
    scene = viewport.scene
    sel = _selected_scavi(scene)
    if not sel:
        viewport.flash_status(tr("Seleziona uno scavo"), 3000)
        return
    keys = [([list(p) for p in scavo_data(g)["poly"]],
             [list(p) for p in scavo_data(g)["slab"]]) for g in sel]

    def mutate(sc):
        slabs = []
        for k, sk in keys:
            gg = _find_scavo(sc, k)
            if gg is not None:
                sc.groups.remove(gg)
            if sk not in slabs:
                slabs.append(sk)
        for sk in slabs:
            _apply_scavi(sc, sk)

    viewport.history.execute(muri.MuriCommand(mutate))
    try:
        scene.selection.clear()
    except Exception:
        pass
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("Scavo rimosso"), 3000)


def _scavo_icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(190, 190, 185))
    p.drawRect(6, 16, 36, 18)
    p.setBrush(QColor(255, 255, 255))
    p.drawPolygon(QPolygonF([QPointF(12, 16), QPointF(36, 16),
                             QPointF(32, 27), QPointF(16, 27)]))
    p.end()
    return QIcon(pm)


def _add_scavo_button(api, tool) -> None:
    api.add_button(
        tr("Scavo"),
        tr("Scavo nel solaio: foro non passante, bordi verticali o inclinati"),
        _scavo_icon(), api.run_tool(tool), group="Solaio")



def _selected_slabs(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and slab_data(g) is not None and g not in out:
            out.append(g)
    return out


def set_slab_material(viewport) -> None:
    scene = viewport.scene
    sel = _selected_slabs(scene)
    if not sel:
        viewport.flash_status(tr("Seleziona un solaio"), 3000)
        return
    keys = [[list(p) for p in slab_data(g)["poly"]] for g in sel]
    res = _ask_material(viewport, slab_data(sel[0]).get("mat"))
    if res is None:
        return
    name = res["mat"]

    def mutate(sc):
        for gg in sc.groups:
            dd = slab_data(gg)
            if dd is not None and dd["poly"] in keys:
                nd = copy.deepcopy(dd)
                if name:
                    nd["mat"] = name
                else:
                    nd.pop("mat", None)
                rebuild_slab(gg, nd)

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("Materiale applicato"), 3000)


def edit_slab(viewport) -> None:
    from . import piani
    scene = viewport.scene
    sel = _selected_slabs(scene)
    if len(sel) != 1:
        viewport.flash_status(tr("Seleziona un solaio"), 3000)
        return
    g = sel[0]
    d = slab_data(g)
    key = [list(p) for p in d["poly"]]
    has_lv = bool(d.get("lv")) and piani.get(scene, d["lv"]) is not None

    old = _EDIT["dlg"]
    if old is not None:
        try:
            old.close()
        except RuntimeError:
            pass
    dlg = QDialog(viewport.window())
    dlg.setWindowTitle(tr("Modifica solaio"))
    dlg.setAttribute(Qt.WA_DeleteOnClose, True)
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(muri._Schema(_disegno_solaio))
    name = QLineEdit(getattr(g, "name", "") or tr("Solaio"))
    thick = _spin(d["th"], 0.02, 5.0)
    lay_state = [copy.deepcopy(d.get("layers"))]
    z = _spin(d.get("off", d["z"]) if has_lv else d["z"], -100.0, 1000.0)
    form.addRow(tr("Nome"), name)
    form.addRow(tr("Spessore (s) (m)"), thick)
    lrow = layers_row(dlg, thick, lay_state, _layer_presets(), kind="solaio")
    form.addRow(tr("Strati"), lrow)
    form.addRow(tr("Faccia superiore: sopra il piano (z) (m)") if has_lv
                else tr("Faccia superiore: da terra (z) (m)"), z)
    mat_cb = _mat_combo(scene, d.get("mat"))
    if mat_cb is not None:
        form.addRow(tr("Materiale (dal documento)"), mat_cb)
    paint_w = muri.add_paint_rows(form, d.get, SLAB_ZONES)

    def _result():
        L = lay_state[0] or None
        return dict(muri.paint_results(paint_w), layers=copy.deepcopy(L),
                    th=layers_total(L) if L else thick.value(),
                    mat=mat_cb.currentData() if mat_cb is not None else None)

    def _set_tipo(t):
        w = dict(paint_w)
        if mat_cb is not None:
            w["mat"] = mat_cb
        _tipi.fill_widgets(w, dict(t, **{k: t.get(k) for k in paint_w}, mat=t.get("mat")))
        lay_state[0] = copy.deepcopy(t.get("layers")) or None
        if not lay_state[0] and "th" in t:
            thick.setValue(t["th"])
        lrow.refresh()

    tbar = _tipi.TypeBar(dlg, form, "solaio", d, _result, _set_tipo, scene)
    cf = _codici.CodeField(form, [g], "solaio", scene, at=2)
    scroll_form(dlg, lay, form)
    n_holes = len(d.get("holes", []))
    info = QLabel(tr("Fori: {0}").format(n_holes))
    lay.addWidget(info)

    def find(sc):
        for gg in sc.groups:
            dd = slab_data(gg)
            if dd is not None and dd["poly"] == key:
                return gg, dd
        return None, None

    def _rebuild_tipo(g, q):
        nd = dict(slab_data(g))
        nd.update(q)
        rebuild_slab(g, {k: v for k, v in nd.items() if v is not None})

    def change(fn, msg, after=None) -> None:
        def mutate(sc):
            gg, dd = find(sc)
            if gg is None:
                return
            nd = copy.deepcopy(dd)
            fn(sc, gg, nd)
            rebuild_slab(gg, nd, sc)
            if after is not None:
                after(sc)
            try:
                from . import sezione_strati
                sezione_strati.rebuild_sections(sc)
            except Exception:
                pass

        viewport.history.execute(muri.MuriCommand(mutate))
        viewport.notify_scene_changed()
        viewport.update()
        viewport.flash_status(msg, 3000)

    def apply() -> None:
        cf.apply(dlg)
        pt = tbar.result(_result())
        st = _tipi.resolve_edit(dlg, scene, "solaio", pt)
        if st == "cancel":
            return

        def fn(sc, gg, nd):
            nd["tipo_id"], nd["tipo_nome"] = pt.get("tipo_id"), pt.get("tipo_nome")
            if not nd["tipo_id"]:
                nd.pop("tipo_id", None)
                nd.pop("tipo_nome", None)
            if lay_state[0]:
                nd["layers"] = copy.deepcopy(lay_state[0])
                nd["th"] = layers_total(lay_state[0])
            else:
                nd.pop("layers", None)
                nd["th"] = thick.value()
            if nd.get("lv") and piani.get(sc, nd["lv"]):
                nd["off"] = z.value()
                nd["z"] = piani.get(sc, nd["lv"])["z"] + z.value()
            else:
                nd["z"] = z.value()
            gg.name = name.text().strip() or tr("Solaio")
            if mat_cb is not None:
                if mat_cb.currentData():
                    nd["mat"] = mat_cb.currentData()
                else:
                    nd.pop("mat", None)
            for k, v in muri.paint_results(paint_w).items():
                if v:
                    nd[k] = v
                else:
                    nd.pop(k, None)

        change(fn, tr("Solaio modificato"),
               (lambda sc: _tipi.update_instances(sc, "solaio", pt["tipo_id"],
                                                  _rebuild_tipo))
               if st == "type" else None)

    def drill() -> None:
        dlg.close()
        _FORO.start(viewport, key)

    def clear() -> None:
        def fn(sc, gg, nd):
            nd.pop("holes", None)

        change(fn, tr("Fori rimossi"))
        info.setText(tr("Fori: 0"))

    b_drill = QPushButton(tr("Fora solaio"))
    b_drill.clicked.connect(drill)
    lay.addWidget(b_drill)
    if n_holes:
        b_clear = QPushButton(tr("Rimuovi tutti i fori"))
        b_clear.clicked.connect(clear)
        lay.addWidget(b_clear)
    box = QDialogButtonBox()
    b_apply = box.addButton(tr("Applica"), QDialogButtonBox.AcceptRole)
    b_close = box.addButton(tr("Chiudi"), QDialogButtonBox.RejectRole)
    b_apply.clicked.connect(apply)
    b_close.clicked.connect(dlg.close)
    lay.addWidget(box)
    _EDIT["dlg"] = dlg
    dlg.show()


def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(190, 190, 185))
    p.drawRect(6, 22, 36, 8)
    p.setBrush(QColor(215, 205, 190))
    p.drawRect(6, 10, 6, 12)
    p.drawRect(36, 10, 6, 12)
    p.end()
    return QIcon(pm)


def _outliner_kind(group):
    d = slab_data(group)
    if d is None:
        sv = scavo_data(group)
        if sv is None:
            return None
        from ._imperial import fmt_len
        return {"type": tr("Scavo"),
                "props": [(tr("Profondità"), fmt_len(sv["depth"])),
                          (tr("Inclinazione"),
                           "%g°" % float(sv.get("angle") or 0.0))]}
    from ._imperial import fmt_len
    from . import piani
    return {"type": tr("Solaio"),
            "props": [(tr("Spessore"), fmt_len(d["th"])),
                      (tr("Altezza da terra"), fmt_len(d["z"]))]
            + piani.level_props(d)}


def _register_level_kind() -> None:
    from . import piani

    def zset(d, z):
        d["z"] = z

    piani.register_kind("solaio", KEY, slab_data, lambda d: d["z"], zset,
                        rebuild_slab)


def _hook_double_click(vp) -> None:
    if getattr(vp, "_myhouse_solaio_dbl", False):
        return
    original = getattr(vp, "begin_group_edit", None)
    if original is None:
        return

    def begin_group_edit(group, *args, **kwargs):
        g = getattr(group, "owner", None) or group
        is_slab = slab_data(g) is not None
        if not is_slab and scavo_data(g) is None:
            return original(group, *args, **kwargs)
        scene = vp.scene
        try:
            scene.select([g])
        except Exception:
            scene.selection.clear()
            scene.selection.add(g)
        vp.update()
        QTimer.singleShot(
            0, lambda: (edit_slab if is_slab else edit_scavo)(vp))

    vp.begin_group_edit = begin_group_edit
    vp._myhouse_solaio_dbl = True


def register(api) -> None:
    _APP["app"] = api.app
    try:
        _hook_double_click(api.app.viewport)
    except Exception:
        pass
    _register_level_kind()
    tool = SolaioTool()
    scavo_tool = ScavoTool()
    api.add_button(tr("Solaio"), tr("Crea un solaio (automatico in una stanza)"),
                   _icon(), api.run_tool(tool), group="Solaio", main=True)
    _add_scavo_button(api, scavo_tool)
    add_ctx = getattr(api.app, "add_context_menu", None)
    if add_ctx is not None:
        def context(menu, selection) -> None:
            scene = api.app.viewport.scene
            n = len(_selected_slabs(scene))
            ns = len(_selected_scavi(scene))
            if ns:
                menu.addSeparator()
                if ns == 1:
                    menu.addAction(
                        tr("Modifica scavo…"),
                        lambda: QTimer.singleShot(
                            0, lambda: edit_scavo(api.app.viewport)))
                menu.addAction(
                    tr("Rimuovi scavo"),
                    lambda: QTimer.singleShot(
                        0, lambda: remove_scavi(api.app.viewport)))
            if _Settings.used and (n or not scene.selection):
                menu.addAction(
                    tr("Nuovo solaio (stesse impostazioni)"),
                    lambda: QTimer.singleShot(
                        0, lambda: tool.start_same(api.app.viewport)))
            if n == 0:
                return
            menu.addSeparator()
            if n == 1:
                menu.addAction(
                    tr("Modifica solaio…"),
                    lambda: QTimer.singleShot(
                        0, lambda: edit_slab(api.app.viewport)))
            menu.addAction(
                tr("Materiale solaio…"),
                lambda: QTimer.singleShot(
                    0, lambda: set_slab_material(api.app.viewport)))
            menu.addAction(
                tr("Scavo nel solaio…"),
                lambda: QTimer.singleShot(
                    0, lambda: api.app.viewport.set_active_tool(scavo_tool)))

        add_ctx(context)
    add_kind = getattr(api.app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
