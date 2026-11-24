# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr
from ._imperial import FT, IN, LengthSpin, ask_length, dflt, fmt_len, imperial
from ._scroll import scroll_form

import copy
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPen, QVector3D
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QInputDialog, QLineEdit, QPushButton, QSpinBox,
    QVBoxLayout,
)

from core import bim
from . import _ifc
from tools.base import Tool, ToolContext

from . import _codici, _tetto_auto, _tipi, muri, piani, travi
from ._strati import (layer_subs_flat, layers_row, layers_total,
                     paint_layer_face)

ORDER = 50
ROOF_COLOR = (0.62, 0.33, 0.28)
LAYER_NAME = "Tetti"
KEY = "myhouse_tetto"
EPS = 1e-6
SNAP = 0.25
SAME = 1e-4
PLANAR_TOL = 0.01
PAINT_KEYS = ("col_top", "tex_top", "col_side", "tex_side",
              "col_bottom", "tex_bottom")
TOP_COLOR = (0.80, 0.10, 0.10)
SIDE_COLOR = (1.0, 1.0, 1.0)
BOTTOM_COLOR = (1.0, 1.0, 1.0)
ZONE_DEFAULT = {"top": TOP_COLOR, "side": SIDE_COLOR, "bottom": BOTTOM_COLOR}
ZONE_MAT = {"top": tr("copertura"), "side": tr("laterale tetto"),
            "bottom": tr("intradosso tetto")}
ROOF_ZONES = (("top", tr("parte superiore")),
              ("side", tr("facce laterali (bordo, lucernari)")),
              ("bottom", tr("parte inferiore (intradosso)")))


_TRAVI_DEFAULT = {"on": False, "shape": "rect", "w": 0.12, "h": 0.20,
                  "tf": 0.02, "tw": 0.012, "n": 6, "dist": "edge", "mode": "par",
                  "ins": 0.0}


class _Settings:
    thickness = dflt(8 * IN, 0.20)
    z_base = dflt(8 * FT, 3.0)
    offset = 0.5
    pitch = dflt(math.degrees(math.atan2(6, 12)), 30.0)
    name = tr("Tetto")
    level = None
    ortho = True
    rect = False
    travi = dict(_TRAVI_DEFAULT)
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
            for k in PAINT_KEYS if getattr(_Settings, k, None)}


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

    tris, guard = [], 0
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


def _is_convex(pts) -> bool:
    n = len(pts)
    for i in range(n):
        a, b, c = pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        if (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) < -EPS:
            return False
    return True


def _is_planar(pts3) -> bool:
    if len(pts3) <= 3:
        return True
    a = pts3[0]
    n = None
    for i in range(1, len(pts3) - 1):
        u = [pts3[i][k] - a[k] for k in range(3)]
        for j in range(i + 1, len(pts3)):
            v = [pts3[j][k] - a[k] for k in range(3)]
            c = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2],
                 u[0] * v[1] - u[1] * v[0])
            ln = math.sqrt(sum(x * x for x in c))
            if ln > 1e-9:
                n = tuple(x / ln for x in c)
                break
        if n:
            break
    if n is None:
        return True
    return all(abs(sum((p[k] - a[k]) * n[k] for k in range(3))) < PLANAR_TOL
               for p in pts3)


def ctrl_points(poly, lines):
    out = []
    for p in list(poly) + [q for ln in lines for q in ln]:
        if not any(math.hypot(p[0] - c[0], p[1] - c[1]) < SAME for c in out):
            out.append((p[0], p[1]))
    return out


def _lookup(ctrl, x, y):
    for cx, cy, cz in ctrl:
        if math.hypot(cx - x, cy - y) < SAME:
            return cz
    return None


def _z_at(d, x, y) -> float:
    ctrl = d["ctrl"]
    z = _lookup(ctrl, x, y)
    if z is not None:
        return z
    poly = d["poly"]
    segs = [(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly))]
    segs += [tuple(ln) for ln in d["lines"]]
    best, bz = 1e18, d["base"]
    for a, b in segs:
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy
        if L2 < EPS:
            continue
        t = max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / L2))
        dist = math.hypot(a[0] + t * dx - x, a[1] + t * dy - y)
        if dist < best:
            za = _lookup(ctrl, *a) or 0.0
            zb = _lookup(ctrl, *b) or 0.0
            best, bz = dist, za + t * (zb - za)
    return bz


def _plane(pts3):
    best, pl = 1e-9, None
    n = len(pts3)
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                a, b, c = pts3[i], pts3[j], pts3[k]
                u = [b[m] - a[m] for m in range(3)]
                v = [c[m] - a[m] for m in range(3)]
                nx = u[1] * v[2] - u[2] * v[1]
                ny = u[2] * v[0] - u[0] * v[2]
                nz = u[0] * v[1] - u[1] * v[0]
                if abs(nz) > best:
                    best = abs(nz)
                    pa, pb = -nx / nz, -ny / nz
                    pl = (pa, pb, a[2] - pa * a[0] - pb * a[1])
    return pl


def _line_int(p1, d1, p2, d2):
    cr = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(cr) <= 1e-6 * math.hypot(*d1) * math.hypot(*d2):
        return None
    t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / cr
    return (p1[0] + t * d1[0], p1[1] + t * d1[1]), t


def apply_offset(d, off):
    if off <= EPS:
        return d
    from shapely.geometry import LineString, LinearRing, Point
    from shapely.ops import polygonize, unary_union
    poly = [tuple(p) for p in d["poly"]]
    if _area(poly) < 0:
        poly.reverse()
    d = dict(d, poly=poly)
    lines = [(tuple(a), tuple(b)) for a, b in d["lines"]]
    n = len(poly)

    planes = []
    for region in polygonize(unary_union(
            [LinearRing(poly)] + [LineString(l) for l in lines])):
        ring = list(region.exterior.coords)[:-1]
        pl = _plane([(x, y, _z_at(d, x, y)) for x, y in ring])
        if pl:
            planes.append((region, pl))

    def plane_z(x, y):
        if not planes:
            return d["base"]
        _, (a, b, c) = min(planes, key=lambda rp: rp[0].distance(Point(x, y)))
        return a * x + b * y + c

    dirs, norms, opt = [], [], []
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1.0
        dirs.append((dx, dy))
        norms.append((dy / L, -dx / L))
        opt.append((a[0] + dy / L * off, a[1] - dx / L * off))

    newpos, newz, col = [], [], []
    for i in range(n):
        e0 = (i - 1) % n
        hit = _line_int(opt[e0], dirs[e0], opt[i], dirs[i])
        v = poly[i]
        if hit is None:
            col.append(True)
            p = (v[0] + norms[i][0] * off, v[1] + norms[i][1] * off)
        else:
            col.append(False)
            p = hit[0]
            if math.hypot(p[0] - v[0], p[1] - v[1]) > 6 * off:
                sx = norms[e0][0] + norms[i][0]
                sy = norms[e0][1] + norms[i][1]
                sl = math.hypot(sx, sy) or 1.0
                p = (v[0] + sx / sl * off, v[1] + sy / sl * off)
        newpos.append(p)
        newz.append(plane_z(*p))

    def vertex_at(pt):
        for i, v in enumerate(poly):
            if math.hypot(pt[0] - v[0], pt[1] - v[1]) < SAME:
                return i
        return None

    for a, b in lines:
        for E, O in ((b, a), (a, b)):
            i = vertex_at(E)
            if i is None or not col[i]:
                continue
            dv = (E[0] - O[0], E[1] - O[1])
            hit = _line_int(E, dv, opt[i], dirs[i])
            if hit is None or hit[1] <= 0:
                continue
            L = math.hypot(*dv)
            zE, zO = _z_at(d, *E), _z_at(d, *O)
            slope = (zE - zO) / L if L > EPS else 0.0
            newpos[i] = hit[0]
            newz[i] = zE + slope * math.hypot(hit[0][0] - E[0],
                                              hit[0][1] - E[1])

    def move(pt):
        i = vertex_at(pt)
        return newpos[i] if i is not None else pt

    new_lines = [(move(a), move(b)) for a, b in lines]
    ctrl = [[newpos[i][0], newpos[i][1], newz[i]] for i in range(n)]
    for a, b in lines:
        for p in (a, b):
            if vertex_at(p) is None and _lookup(ctrl, *p) is None:
                ctrl.append([p[0], p[1], _z_at(d, *p)])
    return dict(d, poly=[list(p) for p in newpos],
                lines=[[list(a), list(b)] for a, b in new_lines],
                ctrl=ctrl, spo=off)


def _hole_polys(d):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    out = []
    for h in list(d.get("holes") or ()) + list(d.get("fori") or ()):
        pg = Polygon([tuple(p) for p in h])
        if not pg.is_valid:
            pg = pg.buffer(0)
        if pg.geom_type == "Polygon" and pg.area > 1e-6:
            out.append(pg)
    if d.get("fori") and len(out) > 1:
        out = _polys_of(unary_union(out))
    return out


def _polys_of(g):
    if g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g]
    return [p for x in getattr(g, "geoms", []) for p in _polys_of(x)]


def _lines_of(g):
    if g.is_empty:
        return []
    if g.geom_type == "LineString":
        return [g]
    return [x for p in getattr(g, "geoms", []) for x in _lines_of(p)]


def _open_pieces(p, q, holes):
    if not holes:
        return [(0.0, 1.0)]
    from shapely.geometry import LineString
    from shapely.ops import unary_union
    L = math.hypot(q[0] - p[0], q[1] - p[1])
    if L < 1e-9:
        return [(0.0, 1.0)]
    seg = LineString([(p[0], p[1]), (q[0], q[1])])
    hu = unary_union(holes)
    if seg.intersection(hu).length < 1e-6:
        return [(0.0, 1.0)]
    out = []
    for part in _lines_of(seg.difference(hu)):
        if part.length < 1e-6:
            continue
        a, b = part.coords[0], part.coords[-1]
        t0 = math.hypot(a[0] - p[0], a[1] - p[1]) / L
        t1 = math.hypot(b[0] - p[0], b[1] - p[1]) / L
        out.append((min(t0, t1), max(t0, t1)))
    return out


def _triangulate_kh(pts):
    """Ear clipping per anello con ponte (keyhole): i vertici duplicati del
    ponte non bloccano le orecchie. Restituisce triangoli di indici."""
    idx = list(range(len(pts)))
    if _area(pts) < 0:
        idx.reverse()

    def cross(a, b, c):
        return ((pts[b][0] - pts[a][0]) * (pts[c][1] - pts[a][1])
                - (pts[b][1] - pts[a][1]) * (pts[c][0] - pts[a][0]))

    def same(p, q):
        return (abs(pts[p][0] - pts[q][0]) < 1e-9
                and abs(pts[p][1] - pts[q][1]) < 1e-9)

    def blocks(p, a, b, c):
        if same(p, a) or same(p, b) or same(p, c):
            return False
        return (cross(a, b, p) > EPS and cross(b, c, p) > EPS
                and cross(c, a, p) > EPS)

    tris, guard = [], 0
    while len(idx) > 3 and guard < 10000:
        guard += 1
        for k in range(len(idx)):
            a, b, c = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            if cross(a, b, c) <= EPS:
                continue
            if any(blocks(p, a, b, c) for p in idx if p not in (a, b, c)):
                continue
            tris.append((a, b, c))
            idx.pop(k)
            break
        else:
            break
    if len(idx) == 3 and cross(*idx) > EPS:
        tris.append(tuple(idx))
    return tris


def _keyhole(pg, bridges_out=None):
    from shapely.geometry import LineString
    from shapely.geometry.polygon import orient
    pg = orient(pg, 1.0)
    ring = list(pg.exterior.coords)[:-1]
    cover = pg.buffer(1e-7)
    bridges = []
    for hole in pg.interiors:
        h = list(hole.coords)[:-1]
        best = None
        for i, rv in enumerate(ring):
            for j, hv in enumerate(h):
                dist = math.hypot(rv[0] - hv[0], rv[1] - hv[1])
                if dist < 1e-9 or (best and dist >= best[0]):
                    continue
                seg = LineString([rv, hv])
                if not cover.covers(seg) or any(seg.crosses(b)
                                                for b in bridges):
                    continue
                best = (dist, i, j, seg)
        if best is None:
            continue
        _d, i, j, seg = best
        bridges.append(seg)
        if bridges_out is not None:
            bridges_out.append((tuple(ring[i]), tuple(h[j])))
        ring = ring[:i + 1] + h[j:] + h[:j] + [h[j], ring[i]] + ring[i + 1:]
    return ring


def roof_mesh(d, mesh=None):
    from core.mesh import Mesh
    if (mesh is None and d.get("layers") and not d.get("_lay")
            and not d.get("_hide_lay")):
        mesh = Mesh()
        for sub in layer_subs_flat(d):
            roof_mesh(sub, mesh)
        return mesh
    from shapely.geometry import LineString, LinearRing
    from shapely.geometry.polygon import orient
    from shapely.ops import polygonize, unary_union
    P = QVector3D
    th = d["th"]
    dz = d.get("_dz", 0.0)
    poly = [tuple(p) for p in d["poly"]]
    if _area(poly) < 0:
        poly.reverse()
    d = dict(d, poly=poly)
    if mesh is None:
        mesh = Mesh()

    def face(q, zone=None):
        f = mesh.add_face(q)
        f.attrs["layer"] = LAYER_NAME
        if zone and paint_layer_face(f, q, zone, d, ZONE_MAT):
            return
        if zone:
            if muri.paint_face(f, d.get("col_" + zone),
                               d.get("tex_" + zone)) \
                    and not d.get("tex_" + zone):
                f.attrs["mat"] = ZONE_MAT[zone]

    def emit(top):
        xy = [(p[0], p[1]) for p in top]
        if _is_planar(top) and _is_convex(xy):
            face([P(*p) for p in top], "top")
            face([P(p[0], p[1], p[2] - th) for p in reversed(top)], "bottom")
        else:
            n_ = len(xy)
            for a, b, c in _triangulate(xy):
                for u, v in ((a, b), (b, c), (c, a)):
                    if (u - v) % n_ not in (1, n_ - 1):
                        tagli.append(((xy[u][0], xy[u][1]), (xy[v][0], xy[v][1])))
                face([P(*top[a]), P(*top[b]), P(*top[c])], "top")
                face([P(top[c][0], top[c][1], top[c][2] - th),
                      P(top[b][0], top[b][1], top[b][2] - th),
                      P(top[a][0], top[a][1], top[a][2] - th)], "bottom")

    holes = _hole_polys(d)
    tagli = []
    geoms = [LinearRing(poly)] + [LineString(ln) for ln in d["lines"]]
    for region in polygonize(unary_union(geoms)):
        ring = list(orient(region, 1.0).exterior.coords)[:-1]
        top = [(x, y, _z_at(d, x, y) - dz) for x, y in ring]
        pl = _plane(top) if holes and _is_planar(top) else None
        mine = [h for h in holes
                if pl and region.intersection(h).area > 1e-6]
        if not mine:
            emit(top)
            continue
        pa, pb, pc = pl
        rest = region
        for h in mine:
            rest = rest.difference(h)
        for pg in _polys_of(rest):
            kh = _keyhole(pg, tagli)
            top2 = [(x, y, pa * x + pb * y + pc) for x, y in kh]
            n_ = len(kh)
            # triangoli (niente anelli con ponte): l'IFC li legge tutti
            for a, b, c in _triangulate_kh(kh):
                for u, v in ((a, b), (b, c), (c, a)):
                    if (u - v) % n_ not in (1, n_ - 1):
                        tagli.append(((kh[u][0], kh[u][1]),
                                      (kh[v][0], kh[v][1])))
                face([P(*top2[a]), P(*top2[b]), P(*top2[c])], "top")
                face([P(top2[c][0], top2[c][1], top2[c][2] - th),
                      P(top2[b][0], top2[b][1], top2[b][2] - th),
                      P(top2[a][0], top2[a][1], top2[a][2] - th)], "bottom")
        bound = region.boundary
        for h in mine:
            for part in _polys_of(region.intersection(h)):
                op = orient(part, -1.0)
                for ring3 in [op.exterior] + list(op.interiors):
                    r3 = list(ring3.coords)[:-1]
                    for i in range(len(r3)):
                        p, q = r3[i], r3[(i + 1) % len(r3)]
                        from shapely.geometry import Point
                        if bound.distance(Point((p[0] + q[0]) / 2,
                                                (p[1] + q[1]) / 2)) < 1e-6:
                            continue
                        zp = pa * p[0] + pb * p[1] + pc
                        zq = pa * q[0] + pb * q[1] + pc
                        face([P(p[0], p[1], zp - th),
                              P(q[0], q[1], zq - th),
                              P(q[0], q[1], zq), P(p[0], p[1], zp)], "side")
    n = len(poly)
    for i in range(n):
        j = (i + 1) % n
        zi, zj = _z_at(d, *poly[i]) - dz, _z_at(d, *poly[j]) - dz
        for t0, t1 in _open_pieces(poly[i], poly[j], holes):
            xa = poly[i][0] + (poly[j][0] - poly[i][0]) * t0
            ya = poly[i][1] + (poly[j][1] - poly[i][1]) * t0
            xb = poly[i][0] + (poly[j][0] - poly[i][0]) * t1
            yb = poly[i][1] + (poly[j][1] - poly[i][1]) * t1
            za, zb = zi + (zj - zi) * t0, zi + (zj - zi) * t1
            face([P(xa, ya, za - th), P(xb, yb, zb - th),
                  P(xb, yb, zb), P(xa, ya, za)], "side")
    _nascondi_tagli(mesh, tagli)
    return mesh


def _nascondi_tagli(mesh, tagli):
    if not tagli:
        return

    def vic(p, q):
        return abs(p.x() - q[0]) < 1e-4 and abs(p.y() - q[1]) < 1e-4

    for e in mesh.edges:
        for A, B in tagli:
            if (vic(e.a, A) and vic(e.b, B)) or (vic(e.a, B) and vic(e.b, A)):
                try:
                    setattr(e, muri.EDGE_FLAG, True)
                except Exception:
                    pass
                break


def _group_matrix(g):
    from PySide6.QtGui import QMatrix4x4
    x = getattr(g, "xform", None)
    return QMatrix4x4(x) if x is not None else QMatrix4x4()


def _roof_underside(d):
    if "poly" not in d and "segs" in d:
        from . import tetto_profilo
        return tetto_profilo.underside(d)
    from shapely.geometry import LineString, LinearRing
    from shapely.geometry.polygon import orient
    from shapely.ops import polygonize, unary_union
    poly = [tuple(p) for p in d["poly"]]
    if _area(poly) < 0:
        poly.reverse()
    dd = dict(d, poly=poly)
    out = []
    geoms = [LinearRing(poly)] + [LineString(ln) for ln in d["lines"]]
    for region in polygonize(unary_union(geoms)):
        ring = list(orient(region, 1.0).exterior.coords)[:-1]
        r3 = [(x, y, _z_at(dd, x, y) - d["th"]) for x, y in ring]
        if _is_planar(r3):
            out.append(r3)
        else:
            for a, b, c in _triangulate(ring):
                out.append([r3[a], r3[b], r3[c]])
    return out


def _wall_clip(wd, wall_group, roofs):
    from PySide6.QtGui import QMatrix4x4
    from shapely.geometry import LineString, Point, Polygon
    pose = muri.wall_pose(wall_group)
    Mw = _group_matrix(wall_group) * pose
    Mw_inv = Mw.inverted()[0]
    aL, aR, bL, bR = muri.wall_corners(wd)
    foot = Polygon([aL, bL, bR, aR])
    if not foot.is_valid:
        foot = foot.buffer(0)
    z1 = wd["z0"] + wd["h"]
    L = math.hypot(wd["b"][0] - wd["a"][0], wd["b"][1] - wd["a"][1])
    if L < EPS or foot.is_empty:
        return None
    ux = (wd["b"][0] - wd["a"][0]) / L
    uy = (wd["b"][1] - wd["a"][1]) / L
    ax, ay = wd["a"]
    faces = [LineString([aL, bL]), LineString([aR, bR])]

    regions, ts = [], set()
    for rd, Mr in roofs:
        for ring3 in _roof_underside(rd):
            loc = []
            for x, y, z in ring3:
                v = Mw_inv.map(Mr.map(QVector3D(x, y, z)))
                loc.append((v.x(), v.y(), v.z()))
            pl = _plane(loc)
            if pl is None:
                continue
            poly2 = Polygon([(p[0], p[1]) for p in loc])
            if not poly2.is_valid:
                poly2 = poly2.buffer(0)
            if poly2.is_empty or poly2.intersection(foot).area < 1e-6:
                continue
            a, b, c = pl

            def zp(x, y):
                return a * x + b * y + c

            minz = min(zp(x, y) for x, y in foot.exterior.coords)
            if minz >= z1 - 1e-6:
                continue
            regions.append({"poly": [[p[0], p[1]] for p in loc],
                            "pl": [a, b, c]})
            for ln in faces:
                seg = ln.intersection(poly2)
                parts = getattr(seg, "geoms", [seg])
                for g in parts:
                    if g.geom_type != "LineString" or g.is_empty:
                        continue
                    (x0, y0), (x1, y1) = g.coords[0], g.coords[-1]
                    zs0, zs1 = zp(x0, y0), zp(x1, y1)
                    pts = [(x0, y0), (x1, y1)]
                    if (zs0 - z1) * (zs1 - z1) < 0:
                        f = (z1 - zs0) / (zs1 - zs0)
                        pts.append((x0 + f * (x1 - x0), y0 + f * (y1 - y0)))
                    ends = [Point(ln.coords[0]), Point(ln.coords[-1])]
                    for px, py in pts:
                        if any(e.distance(Point(px, py)) < 1e-6 for e in ends):
                            continue
                        t = ((px - ax) * ux + (py - ay) * uy) / L
                        if 1e-4 < t < 1 - 1e-4:
                            ts.add(round(t, 6))
    if not regions:
        return None
    return {"regions": regions, "ts": sorted(ts)}


def _roof_low(rd) -> float:
    if "poly" not in rd and "segs" in rd:
        from . import tetto_profilo
        return tetto_profilo.low(rd)
    zs = [c[2] for c in rd.get("ctrl") or ()]
    return (min(zs) if zs else rd["base"]) - rd["th"]


def update_roof_clips(scene) -> int:
    try:
        import shapely
    except ImportError:
        return 0
    changed = 0
    roofs = []
    for g in scene.groups:
        rd = roof_data(g)
        if rd is None:
            from . import tetto_profilo
            rd = tetto_profilo.roof_data(g)
        if rd is not None:
            roofs.append((rd, _group_matrix(g)))
    for g in scene.groups:
        wd = muri.wall_data(g)
        if wd is None:
            continue
        wr = [x for x in roofs if wd["z0"] < _roof_low(x[0]) - 1e-6]
        clip = _wall_clip(wd, g, wr) if wr else None
        new = dict(wd)
        if clip:
            new["clip"] = clip
        else:
            new.pop("clip", None)
        if new == wd:
            continue
        g.children = [muri.wall_part(new, muri.wall_pose(g), g.name)]
        _ifc.tag(g, "IfcWall")
        ext = dict(g.ext or {})
        ext[muri.KEY] = new
        g.ext = ext
        changed += 1
    try:
        from . import lucernari
        changed += lucernari.update_roof_holes(scene)
    except ImportError:
        pass
    return changed


def _longest_side(poly) -> int:
    n = len(poly)
    return max(range(n), key=lambda i: math.hypot(
        poly[(i + 1) % n][0] - poly[i][0], poly[(i + 1) % n][1] - poly[i][1]))


def _side_dir(poly, side, mode):
    n = len(poly)
    a, b = poly[side], poly[(side + 1) % n]
    L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
    ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    if mode == "perp":
        ux, uy = -uy, ux
    return ux, uy


def _travi_params(tv, poly, side) -> dict:
    ux, uy = _side_dir(poly, side, tv.get("mode", "par"))
    shape = tv.get("shape", "rect")
    w = tv["w"]
    return {"shape": shape, "w": w, "h": w if shape == "round" else tv["h"],
            "tf": tv.get("tf", 0.02), "tw": tv.get("tw", 0.012),
            "n": int(tv.get("n", _TRAVI_DEFAULT["n"])),
            "dist": tv.get("dist", "edge"),
            "mode": tv.get("mode", "par"),
            "ins": max(0.0, float(tv.get("ins", 0.0))),
            "side": side, "dir": [ux, uy]}


def beam_defs(d) -> list:
    tv = d.get("travi")
    if not tv:
        return []
    from shapely.geometry import LineString, Polygon
    from shapely.ops import unary_union
    w, h = tv["w"], tv["h"]
    ux, uy = tv["dir"]
    nx, ny = -uy, ux

    groups = []
    for ring in _roof_underside(d):
        pl = _plane(ring)
        if pl is None:
            continue
        pg = Polygon([(q[0], q[1]) for q in ring])
        if not pg.is_valid:
            pg = pg.buffer(0)
        if pg.is_empty:
            continue
        for gpl, plist in groups:
            if all(abs(gpl[k] - pl[k]) < 1e-3 for k in range(3)):
                plist.append(pg)
                break
        else:
            groups.append((pl, [pg]))
    regions = []
    for pl, plist in groups:
        inner = unary_union(plist).buffer(-(w / 2 - 1e-4), join_style=2)
        if not inner.is_empty:
            regions.append((inner, pl))
    if not regions:
        return []

    poly = d["poly"]
    ss = [nx * q[0] + ny * q[1] for q in poly]
    ts = [ux * q[0] + uy * q[1] for q in poly]
    smin, smax, tmin, tmax = min(ss), max(ss), min(ts), max(ts)

    ins = min(max(0.0, float(tv.get("ins", 0.0))),
              max(0.0, (smax - smin - w) / 2.0))
    s0, s1 = smin + w / 2 + ins, smax - w / 2 - ins
    if tv.get("n") is not None:
        n = max(1, int(tv["n"]))
        if tv.get("dist", "edge") == "center":
            fw = (smax - smin - 2 * ins) / n
            positions = [smin + ins + (i + 0.5) * fw for i in range(n)]
        elif n == 1 or s1 - s0 < 1e-6:
            positions = [(s0 + s1) / 2]
        else:
            step = (s1 - s0) / (n - 1)
            positions = [s0 + i * step for i in range(n)]
    else:
        sp = max(tv.get("sp", 0.6), 0.02)
        positions, s = [], s0
        while s <= s1 + 1e-9 and len(positions) < 5000:
            positions.append(s)
            s += sp

    out = []
    for s in positions:
        line = LineString([(s * nx + (tmin - 1) * ux, s * ny + (tmin - 1) * uy),
                           (s * nx + (tmax + 1) * ux, s * ny + (tmax + 1) * uy)])
        for inner, (a, b, c) in regions:
            seg = line.intersection(inner)
            for g in getattr(seg, "geoms", [seg]):
                if g.geom_type != "LineString" or g.length < 0.05:
                    continue
                (x0, y0), (x1, y1) = g.coords[0], g.coords[-1]
                if (x1 - x0) * ux + (y1 - y0) * uy < 0:
                    x0, y0, x1, y1 = x1, y1, x0, y0
                lat = abs(a * nx + b * ny) * w / 2
                za = a * x0 + b * y0 + c + lat - h
                zb = a * x1 + b * y1 + c + lat - h
                out.append({"a": [x0, y0], "b": [x1, y1], "za": za, "zb": zb,
                            "w": w, "h": h, "shape": tv.get("shape", "rect"),
                            "tf": tv.get("tf", 0.02), "tw": tv.get("tw", 0.012)})
    return out


def beam_parts(d) -> list:
    from core.group import Group
    parts = []
    for bd in beam_defs(d):
        g = Group(travi.beam_mesh(bd), name=tr("Trave"))
        g.component = False
        try:
            _ifc.tag(g, "IfcBeam", tr("Trave"))
        except Exception:
            pass
        parts.append(g)
    return parts


def roof_parts(d) -> list:
    from core.group import Group
    part = Group(roof_mesh(d), name=tr("Tetto"))
    part.component = False
    return [part] + beam_parts(d)


def _ensure_beam_layer(scene, d) -> None:
    if d.get("travi") and not any(ly.name == travi.LAYER_NAME
                                  for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(travi.LAYER_NAME))


def roof_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "poly" in data else None


def _roof_offset(d) -> float:
    if "spo" in d:
        return float(d["spo"])
    src = d.get("src")
    if not src:
        return 0.0
    sp, dp = src["poly"], d["poly"]
    if len(sp) == len(dp) and all(abs(a[0] - b[0]) < 1e-6
                                  and abs(a[1] - b[1]) < 1e-6
                                  for a, b in zip(sp, dp)):
        return 0.0
    return float(d.get("off", 0.0))


def rebuild_roof(group, d) -> None:
    group.children = roof_parts(d)
    _ifc.tag(group, "IfcRoof")
    ext = dict(group.ext or {})
    ext[KEY] = dict(d)
    group.ext = ext


def build_roof(scene, d, name) -> None:
    from core.group import Group
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    _ensure_beam_layer(scene, d)
    g = Group(name=name)
    g.adopt(roof_parts(d))
    g.component = False
    g.layer = LAYER_NAME
    _ifc.tag(g, "IfcRoof", name)
    g.ext = {KEY: d}
    scene.groups.append(g)


def _spin(value, lo, hi):
    s = LengthSpin()
    s.setDecimals(3)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


def _disegno_travi_tetto(p):
    r, t, dim = muri._r, muri._t, muri._dim
    travi._sezioni(p, 0, 5)
    for ox, titolo, xs in ((250, tr("Dai lati"), (250, 285, 320, 355)),
                           (375, tr("Dal centro"), (388, 414, 441, 467))):
        t(p, ox, 30, titolo, size=9)
        r(p, ox, 40, ox + 105 if ox == 250 else ox + 105, 120, muri._C_BIANCO)
        for x in xs:
            lo = max(ox, min(x - 2.5, ox + 100))
            r(p, lo, 40, lo + 5, 120, muri._C_LEGNO)
    p.setPen(QPen(muri._C_QUOTA, 2.5))
    p.drawLine(QPointF(250, 120), QPointF(355, 120))
    p.drawLine(QPointF(375, 120), QPointF(480, 120))
    t(p, 280, 136, tr("lato guida"), muri._C_QUOTA, 9, True)
    t(p, 402, 136, tr("lato guida"), muri._C_QUOTA, 9, True)
    t(p, 250, 156, "n = " + tr("numero di travi"), size=9)


def _disegno_tetto(p):
    r, t, dim, ext = muri._r, muri._t, muri._dim, muri._ext
    t(p, 10, 12, tr("Pianta"), size=9)
    pen = QPen(muri._C_LINEA, 1.2)
    pen.setStyle(Qt.DashLine)
    p.setPen(pen)
    p.setBrush(muri._C_CORPO)
    p.drawRect(QRectF(20, 35, 200, 110))
    r(p, 50, 60, 190, 120, muri._C_BIANCO)
    t(p, 85, 94, tr("contorno"), size=9)
    dim(p, 20, 50, 50, 50, "o", 1)
    t(p, 270, 12, tr("Sezione"), size=9)
    p.setPen(QPen(muri._C_LINEA, 1.5))
    p.drawLine(QPointF(250, 150), QPointF(470, 150))
    muri._hatch(p, 250, 150, 470, 156)
    r(p, 300, 96, 312, 150, muri._C_BIANCO)
    r(p, 408, 96, 420, 150, muri._C_BIANCO)
    from PySide6.QtGui import QPolygonF
    pts = [(280, 92), (360, 44), (440, 92), (440, 102), (360, 54), (280, 102)]
    p.setPen(QPen(muri._C_LINEA, 1.2))
    p.setBrush(muri._C_LEGNO)
    p.drawPolygon(QPolygonF([QPointF(*q) for q in pts]))
    pen = QPen(muri._C_LINEA, 1)
    pen.setStyle(Qt.DashDotLine)
    p.setPen(pen)
    p.drawLine(QPointF(250, 130), QPointF(470, 130))
    t(p, 430, 126, tr("piano"), size=8)
    dim(p, 266, 92, 266, 130, "z", -1)
    ext(p, 266, 92, 280, 92)
    dim(p, 280, 118, 300, 118, "o", 1)
    dim(p, 452, 92, 452, 102, "s")


def ask_beams(parent, cur: dict, with_on: bool = False):
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("Travi del tetto"))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(muri._Schema(_disegno_travi_tetto))
    on = None
    if with_on:
        on = QCheckBox(tr("Travi nell'intradosso delle falde"))
        on.setChecked(bool(cur.get("on", True)))
        form.addRow(on)
    shape = QComboBox()
    shape.addItem(tr("Rettangolare"), "rect")
    shape.addItem(tr("Circolare"), "round")
    shape.addItem(tr("A I"), "ibeam")
    shape.setCurrentIndex({"rect": 0, "round": 1, "ibeam": 2}.get(
        cur.get("shape", "rect"), 0))
    w = _spin(cur.get("w", 0.12), 0.02, 5.0)
    h = _spin(cur.get("h", 0.20), 0.02, 5.0)
    tf = _spin(cur.get("tf", 0.02), 0.002, 2.0)
    tw = _spin(cur.get("tw", 0.012), 0.002, 2.0)
    nb = QSpinBox()
    nb.setRange(1, 500)
    nb.setValue(int(cur.get("n", _TRAVI_DEFAULT["n"])))
    dist = QComboBox()
    dist.addItem(tr("Dai lati (prima e ultima sui bordi)"), "edge")
    dist.addItem(tr("Dal centro (una per fascia uguale)"), "center")
    dist.setCurrentIndex(1 if cur.get("dist") == "center" else 0)
    ins = _spin(cur.get("ins", 0.0), 0.0, 50.0)
    mode = QComboBox()
    mode.addItem(tr("Parallele al lato scelto"), "par")
    mode.addItem(tr("Perpendicolari al lato scelto"), "perp")
    mode.setCurrentIndex(1 if cur.get("mode") == "perp" else 0)
    form.addRow(tr("Forma della sezione"), shape)
    form.addRow(tr("Larghezza sezione (b) (m)"), w)
    form.addRow(tr("Altezza sezione (h) (m)"), h)
    form.addRow(tr("Spessore ali (tf) (m)"), tf)
    form.addRow(tr("Spessore anima (tw) (m)"), tw)
    form.addRow(tr("Numero di travi (n)"), nb)
    form.addRow(tr("Distribuzione"), dist)
    form.addRow(tr("Rientro laterale (uguale a destra e a sinistra) (m)"), ins)
    form.addRow(tr("Verso delle travi"), mode)

    def _vis(widget, flag):
        widget.setVisible(flag)
        lbl = form.labelForField(widget)
        if lbl is not None:
            lbl.setVisible(flag)

    def _shape_changed(*_):
        k = shape.currentData()
        _vis(h, k != "round")
        _vis(tf, k == "ibeam")
        _vis(tw, k == "ibeam")
        lbl = form.labelForField(w)
        if lbl is not None:
            lbl.setText(tr("Diametro (d) (m)") if k == "round" else
                        tr("Larghezza ali (b) (m)") if k == "ibeam" else
                        tr("Larghezza sezione (b) (m)"))
        lbl = form.labelForField(h)
        if lbl is not None:
            lbl.setText(tr("Altezza totale (h) (m)") if k == "ibeam"
                        else tr("Altezza sezione (h) (m)"))

    shape.currentIndexChanged.connect(_shape_changed)
    _shape_changed()
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return None
    k = shape.currentData()
    wv, hv = w.value(), h.value()
    if k == "round":
        hv = wv
    return {"on": on.isChecked() if on is not None else True,
            "shape": k, "w": wv, "h": hv,
            "tf": min(tf.value(), max(0.002, (hv - 0.005) / 2)),
            "tw": min(tw.value(), max(0.002, wv - 0.005)),
            "n": nb.value(), "dist": dist.currentData(),
            "ins": ins.value(), "mode": mode.currentData()}


def ask_settings(parent, scene=None, editing: bool = False, groups=None) -> bool:
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("Tetto"))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(muri._Schema(_disegno_tetto))
    thick = _spin(_Settings.thickness, 0.02, 5.0)
    z = _spin(_Settings.z_base, -100.0, 1000.0)
    off = _spin(_Settings.offset, 0.0, 10.0)
    name = QLineEdit(_Settings.name)
    lvl = None
    if scene is not None and piani.levels(scene):
        lvl = piani.level_combo(scene, piani.active_id(scene))

        def on_level(_i) -> None:
            lv = piani.get(scene, lvl.currentData())
            if lv:
                z.setValue(lv["h"])
        lvl.currentIndexChanged.connect(on_level)
        form.addRow(tr("Piano che copre"), lvl)
    form.addRow(tr("Spessore (s) (m)"), thick)
    lay_state = [copy.deepcopy(_Settings.layers)]
    lrow = layers_row(dlg, thick, lay_state, kind="tetto")
    form.addRow(tr("Strati"), lrow)
    form.addRow(tr("Gronda: da terra / sopra la quota del piano (z) (m)"), z)
    form.addRow(tr("Sporto rispetto al contorno (o) (m)"), off)
    paint = muri.add_paint_rows(form, lambda k: getattr(_Settings, k, None),
                                ROOF_ZONES)
    form.addRow(tr("Nome"), name)
    ortho = QCheckBox(tr("Ortogonale (O / F8 durante il disegno)"))
    ortho.setChecked(_Settings.ortho)
    form.addRow(ortho)
    rect = QCheckBox(tr("Contorno rettangolare (2 clic su vertici opposti)"))
    rect.setChecked(_Settings.rect)
    form.addRow(rect)
    tv_cur = dict(_Settings.travi)
    tv_chk = QCheckBox(tr("Travi nell'intradosso delle falde"))
    tv_chk.setChecked(bool(tv_cur.get("on")))
    tv_btn = QPushButton(tr("Tipo, dimensioni e numero travi…"))
    tv_btn.setEnabled(tv_chk.isChecked())
    tv_chk.toggled.connect(tv_btn.setEnabled)

    def _tv_dialog() -> None:
        r = ask_beams(dlg, tv_cur)
        if r is not None:
            tv_cur.update(r)

    tv_btn.clicked.connect(_tv_dialog)
    form.addRow(tv_chk)
    form.addRow(tv_btn)

    def _result():
        res = muri.paint_results(paint)
        for zone, dflt in ZONE_DEFAULT.items():
            c = res.get("col_" + zone)
            if res.get("tex_" + zone) and c and tuple(c) == tuple(dflt):
                res["col_" + zone] = None
        L = lay_state[0] or None
        return dict(res, layers=copy.deepcopy(L),
                    th=layers_total(L) if L else thick.value())

    def _set_tipo(t):
        _tipi.fill_widgets(dict(paint), dict(t, **{k: t.get(k) for k in paint}))
        lay_state[0] = copy.deepcopy(t.get("layers")) or None
        if not lay_state[0] and "th" in t:
            thick.setValue(t["th"])
        lrow.refresh()

    tbar = _tipi.TypeBar(dlg, form, "tetto", {"tipo_id": _Settings.tipo_id},
                         _result, _set_tipo, scene, creating=not editing)
    cf = (_codici.CodeField(form, groups, "tetto", scene, at=2)
          if groups else None)
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return False
    if cf is not None:
        cf.apply(dlg)
    _Settings.ortho = ortho.isChecked()
    _Settings.rect = rect.isChecked()
    res = muri.paint_results(paint)
    for zone, dflt in ZONE_DEFAULT.items():
        c = res.get("col_" + zone)
        if res.get("tex_" + zone) and c and tuple(c) == tuple(dflt):
            res["col_" + zone] = None
    for k, v in res.items():
        setattr(_Settings, k, v)
    tv_cur["on"] = tv_chk.isChecked()
    _Settings.travi = tv_cur
    _Settings.offset = off.value()
    _Settings.layers = lay_state[0] or None
    _Settings.thickness = (layers_total(_Settings.layers) if _Settings.layers
                           else thick.value())
    _Settings.z_base = z.value()
    _Settings.name = name.text().strip() or tr("Tetto")
    _Settings.level = (lvl.currentData() or None) if lvl is not None else None
    if lvl is not None:
        piani.set_active(_Settings.level)
    r = tbar.result(_result())
    _Settings.tipo_id, _Settings.tipo_nome = r.get("tipo_id"), r.get("tipo_nome")
    return True


def _rise_in_12() -> bool:
    """Whether a pitch reads as a rise in 12: when lengths are in feet and inches."""
    return imperial()


def pitch_text(deg: float) -> str:
    """A pitch in degrees the way it is typed: 8/12 (imperial) or 30°."""
    if _rise_in_12():
        return f"{round(12.0 * math.tan(math.radians(deg)), 2):g}/12"
    return f"{round(deg, 2):g}°"


def parse_pitch(text):
    """Degrees from 8/12, 8:12, 30°, 30deg or 58%; a bare number is the rise
    in 12 (imperial) or degrees (metric). None if unreadable or not between
    1° and 80°."""
    s = str(text).strip().lower().replace(",", ".").replace(" ", "")
    try:
        if s.endswith("°"):
            deg = float(s[:-1])
        elif s.endswith("deg"):
            deg = float(s[:-3])
        elif s.endswith("%"):
            deg = math.degrees(math.atan(float(s[:-1]) / 100.0))
        elif "/" in s or ":" in s:
            rise, run = s.replace(":", "/").split("/")
            deg = math.degrees(math.atan2(float(rise), float(run)))
        elif _rise_in_12():
            deg = math.degrees(math.atan2(float(s), 12.0))
        else:
            deg = float(s)
    except (ValueError, ZeroDivisionError):
        return None
    return deg if 1.0 <= deg <= 80.0 else None


MSG = {
    "outline": tr("Tetto 1/3 contorno: clic per i vertici · W = contorno dei muri · "
               "C/Invio = chiudi · P = chiudi e calcola il tetto · "
               "Backspace = annulla · Esc = esci"),
    "rect": tr("Tetto 1/3 contorno rettangolare: clic su due vertici opposti · "
               "Backspace = annulla · Esc = esci"),
    "lines": tr("Tetto 2/3 linee interne (colmo, displuvi): due clic = una linea, "
             "si aggancia a punti e linee · P = calcola il tetto in automatico · "
             "Invio = continua · Backspace = annulla"),
    "auto": tr("Tetto automatico: clic su un lato del contorno per passare da "
               "padiglione a timpano · P = pendenza · Invio = crea tetto · "
               "Backspace = indietro"),
    "heights": tr("Tetto 3/3 quote: clic su un punto per dargli la quota · "
               "Invio = crea tetto"),
    "dir": tr("Tetto - verso delle travi: clic sul lato che lo indica · "
              "Invio = crea tetto · Backspace = indietro"),
}


class TettoTool(Tool):
    name = tr("Tetto")
    shortcut = None
    description = tr("Crea un tetto a falde con quote per punto di controllo.")

    def __init__(self) -> None:
        self._entering = False
        self._reset()

    def _reset(self) -> None:
        self.phase = "outline"
        self.points: list[tuple[float, float]] = []
        self.lines: list[tuple[tuple, tuple]] = []
        self.line_start = None
        self.heights: dict[tuple, float] = {}
        self.hover_point: QVector3D | None = None
        self.edit_group = None
        self.panel = False
        self.beam_side = None
        self._undo: list = []
        self.auto = None                # automatic roof: outline and gables

    def on_activate(self, viewport) -> None:
        self._scene = viewport.scene
        if self._entering:
            self._reset()
            viewport.flash_status(
                MSG["rect"] if _Settings.rect else MSG["outline"], 7000)
            return
        if not ask_settings(viewport.window(), viewport.scene):
            return
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def edit(self, viewport, group) -> None:
        d = roof_data(group)
        if d is None:
            return
        if getattr(viewport.scene, "edit_group", None) is not None:
            viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        src = d.get("src") or d
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False
        self.points = [tuple(p) for p in src["poly"]]
        self.lines = [(tuple(a), tuple(b)) for a, b in src["lines"]]
        zs = [c[2] for c in src["ctrl"]]
        low = min(zs) if zs else 0.0
        self.heights = {self._key(c): c[2] - low for c in src["ctrl"]}
        _Settings.thickness = d["th"]
        _Settings.layers = copy.deepcopy(d.get("layers")) or None
        _Settings.tipo_id, _Settings.tipo_nome = d.get("tipo_id"), d.get("tipo_nome")
        _Settings.level = d.get("lv")
        _Settings.z_base = d.get("off", d["base"]) if d.get("lv") else d["base"]
        _Settings.offset = _roof_offset(d)
        _Settings.name = group.name or _Settings.name
        self.edit_group = group
        tv = d.get("travi")
        if tv:
            cur = dict(_TRAVI_DEFAULT)
            cur.update({k: tv[k] for k in ("shape", "w", "h", "tf", "tw",
                                           "n", "dist", "mode", "ins") if k in tv})
            cur["on"] = True
            _Settings.travi = cur
            side = tv.get("side")
            self.beam_side = side if (side is not None
                                      and side < len(self.points)) else None
        else:
            _Settings.travi = dict(_Settings.travi, on=False)
        self.phase = "heights"
        viewport.flash_status(
            tr("Modifica tetto: clic su un punto per cambiarne la quota · "
            "Invio = applica · Esc = annulla"), 8000)
        viewport.update()

    def edit_panel(self, viewport, group) -> None:
        d = roof_data(group)
        if d is None:
            return
        if getattr(viewport.scene, "edit_group", None) is not None:
            viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        self.edit(viewport, group)
        if self.edit_group is None:
            return
        for zone, dflt in ZONE_DEFAULT.items():
            col, tex = d.get("col_" + zone), d.get("tex_" + zone)
            setattr(_Settings, "col_" + zone,
                    list(col) if col else (None if tex else list(dflt)))
            setattr(_Settings, "tex_" + zone, copy.deepcopy(tex) if tex else None)
        if d.get("lv"):
            try:
                piani.set_active(d["lv"])
            except Exception:
                pass
        if not ask_settings(viewport.window(), viewport.scene, editing=True,
                            groups=[group]):
            self._exit(viewport)
            return
        pt = {"th": _Settings.thickness, "layers": _Settings.layers,
              "tipo_id": _Settings.tipo_id, "tipo_nome": _Settings.tipo_nome}
        pt.update({k: getattr(_Settings, k, None) for k in PAINT_KEYS})
        st = _tipi.resolve_edit(viewport.window(), viewport.scene, "tetto", pt)
        if st == "cancel":
            self._exit(viewport)
            return
        _Settings.tipo_id, _Settings.tipo_nome = pt.get("tipo_id"), pt.get("tipo_nome")
        self._tipo_upd = pt["tipo_id"] if st == "type" else None
        self.panel = True
        self._commit(viewport)

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

    @staticmethod
    def _key(p):
        return (round(p[0], 3), round(p[1], 3))

    def _ctrl(self):
        return ctrl_points(self.points, self.lines)

    def _constrain(self, x, y):
        if not _Settings.ortho:
            return (x, y)
        if self.phase == "outline" and _Settings.rect:
            return (x, y)
        if self.phase == "outline" and self.points:
            last = self.points[-1]
        elif self.phase == "lines" and self.line_start is not None:
            if self._snap(x, y, commit=False) != (x, y):
                return (x, y)
            last = self.line_start
        else:
            return (x, y)
        if abs(x - last[0]) >= abs(y - last[1]):
            return (x, last[1])
        return (last[0], y)

    def _rel(self, p) -> float:
        return self.heights.get(self._key(p), 0.0)

    def _snap(self, x, y, commit=True):
        for c in self._ctrl():
            if math.hypot(c[0] - x, c[1] - y) < SNAP:
                return c
        best, hit = SNAP, None
        n = len(self.points)
        segs = [("o", i, self.points[i], self.points[(i + 1) % n])
                for i in range(n)]
        segs += [("l", i, a, b) for i, (a, b) in enumerate(self.lines)]
        for kind, i, a, b in segs:
            dx, dy = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dy * dy
            if L2 < EPS:
                continue
            t = ((x - a[0]) * dx + (y - a[1]) * dy) / L2
            if not 0.0 < t < 1.0:
                continue
            q = (a[0] + t * dx, a[1] + t * dy)
            dist = math.hypot(q[0] - x, q[1] - y)
            if dist < best:
                best, hit = dist, (kind, i, q)
        if hit is None:
            return (x, y)
        kind, i, q = hit
        if commit:
            if kind == "o":
                self.points.insert(i + 1, q)
            else:
                a, b = self.lines[i]
                self.lines[i:i + 1] = [(a, q), (q, b)]
        return q

    def _add_line(self, a, b) -> None:
        cuts = []
        lines = list(self.lines)
        out = []
        rx, ry = b[0] - a[0], b[1] - a[1]
        for c, d in lines:
            sx, sy = d[0] - c[0], d[1] - c[1]
            cr = rx * sy - ry * sx
            if abs(cr) < 1e-12:
                out.append((c, d))
                continue
            t = ((c[0] - a[0]) * sy - (c[1] - a[1]) * sx) / cr
            u = ((c[0] - a[0]) * ry - (c[1] - a[1]) * rx) / cr
            e = 1e-6
            if e < t < 1 - e and e < u < 1 - e:
                q = (a[0] + t * rx, a[1] + t * ry)
                cuts.append((t, q))
                out += [(c, q), (q, d)]
            else:
                out.append((c, d))
        pts = [a] + [q for _t, q in sorted(cuts)] + [b]
        out += list(zip(pts, pts[1:]))
        self.lines = out

    # -- automatic roof ------------------------------------------------------
    def _auto_start(self, viewport) -> None:
        """Asks the pitch and works the whole roof out from the outline:
        every edge a sloping plane, until an edge is clicked into a gable."""
        label = (tr("Pendenza: alzata su 12 (8 oppure 8/12), gradi (33.7°) o "
                    "percentuale (67%)") if _rise_in_12() else
                 tr("Pendenza: gradi (30), percentuale (58%) o alzata/base (1/2)"))
        text, ok = QInputDialog.getText(
            viewport.window(), tr("Pendenza del tetto"), label, QLineEdit.Normal,
            pitch_text(_Settings.pitch))
        if not ok:
            viewport.flash_status(MSG[self.phase], 7000)
            return
        deg = parse_pitch(text)
        if deg is None:
            viewport.flash_status(
                tr("Pendenza non riconosciuta: scrivi 8/12, 30° oppure 58%"), 5000)
            return
        _Settings.pitch = deg
        fresh = self.auto is None
        if fresh:
            self.auto = {"pts": [tuple(p) for p in self.points],
                         "gables": set()}
        if not self._auto_solve(viewport):
            if fresh:
                self.auto = None
            return
        self.phase = "auto"
        viewport.flash_status(MSG["auto"], 9000)
        viewport.update()

    def _auto_solve(self, viewport) -> bool:
        slope = math.tan(math.radians(_Settings.pitch))
        try:
            pts, lines, hs = _tetto_auto.solve(
                self.auto["pts"], self.auto["gables"], slope)
        except _tetto_auto.RoofError:
            viewport.flash_status(
                tr("Questo tetto non si può calcolare: un timpano deve stare "
                   "tra due spigoli esterni, e almeno un lato deve avere la "
                   "falda"), 6000)
            return False
        self.points = pts
        self.lines = lines
        self.heights = {self._key(h): h[2] for h in hs}
        self.line_start = None
        self._undo = []
        return True

    def _pick_edge(self, vp, world, radius=16.0):
        """Index of the outline edge nearest the cursor (in pixels)."""
        pts = self.auto["pts"]
        base = self._base()
        px = vp._world_to_pixel(QVector3D(world))
        best, edge = None, None
        for i in range(len(pts)):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            pa = vp._world_to_pixel(QVector3D(a[0], a[1], base))
            pb = vp._world_to_pixel(QVector3D(b[0], b[1], base))
            if px is None or pa is None or pb is None:
                d = _tetto_auto.seg_dist((world.x(), world.y()), a, b) * 100
            else:
                d = _tetto_auto.seg_dist((px[0], px[1]), (pa[0], pa[1]),
                                         (pb[0], pb[1]))
            if d < radius and (best is None or d < best):
                best, edge = d, i
        return edge

    def _auto_click(self, vp, world) -> None:
        i = self._pick_edge(vp, world)
        if i is None:
            vp.flash_status(tr("Clic su un lato del contorno"), 3000)
            return
        self.auto["gables"] ^= {i}
        if not self._auto_solve(vp):
            self.auto["gables"] ^= {i}       # no roof that way: as it was

    def _from_walls(self, viewport) -> None:
        """The outline is the outer face of the walls under the cursor."""
        from . import solaio
        h = self.hover_point
        try:
            poly = solaio.find_footprint(
                viewport.scene, h.x() if h is not None else None,
                h.y() if h is not None else None, _Settings.level)
        except ImportError:
            viewport.flash_status(tr("Serve shapely: pip install shapely"), 6000)
            return
        if not poly or len(poly) < 3:
            viewport.flash_status(tr("Nessun muro trovato per il contorno"), 4000)
            return
        self.points = [tuple(p) for p in poly]
        self.lines, self.heights, self.auto = [], {}, None
        self.line_start = None
        self.phase = "lines"
        viewport.flash_status(MSG["lines"], 9000)
        viewport.update()

    def _push_undo(self) -> None:
        self._undo.append((list(self.points), list(self.lines),
                           self.line_start))

    def _place(self):
        sc = getattr(self, "_scene", None)
        if sc is None:
            return _Settings.z_base, {}
        return piani.place(sc, _Settings.level, _Settings.z_base)

    def _base(self) -> float:
        return self._place()[0]

    def _z(self, p) -> float:
        base = self._base()
        return base + self._rel(p)

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        x, y = ctx.world.x(), ctx.world.y()
        if self.phase != "heights":
            x, y = self._constrain(x, y)
        if self.phase == "outline":
            if self.points and math.hypot(x - self.points[-1][0],
                                          y - self.points[-1][1]) < SAME:
                return
            if _Settings.rect and self.edit_group is None:
                if not self.points:
                    self.points.append((x, y))
                else:
                    (x0, y0), (x1, y1) = self.points[0], (x, y)
                    if abs(x1 - x0) < 0.05 or abs(y1 - y0) < 0.05:
                        vp.flash_status(
                            tr("I due vertici devono avere X e Y diverse"), 3000)
                        return
                    self.points = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
                    self.phase = "lines"
                    vp.flash_status(MSG["lines"], 7000)
                vp.update()
                return
            self.points.append((x, y))
        elif self.phase == "lines":
            self._push_undo()
            p = self._snap(x, y)
            if self.line_start is None:
                self.line_start = p
            else:
                if math.hypot(p[0] - self.line_start[0],
                              p[1] - self.line_start[1]) > SAME:
                    self._add_line(self.line_start, p)
                self.line_start = None
        elif self.phase == "auto":
            self._auto_click(vp, ctx.world)
        elif self.phase == "dir":
            i = self._nearest_side(x, y)
            if i is not None:
                self.beam_side = i
        else:
            near = self._pick(vp, ctx.world)
            if near is None:
                vp.flash_status(tr("Clicca su un quadratino rosso"), 3000)
                return
            val, ok = ask_length(
                vp.window(), tr("Quota punto"),
                tr("Quota rispetto al punto più basso (m)"),
                self._rel(near), -100.0, 1000.0)
            if ok:
                self.heights[self._key(near)] = val
        vp.update()

    def _pick(self, vp, world, radius=18.0):
        px = vp._world_to_pixel(QVector3D(world))
        best, bc = None, None
        for c in self._ctrl():
            pc = vp._world_to_pixel(QVector3D(c[0], c[1], self._z(c)))
            if px is None or pc is None:
                d = math.hypot(c[0] - world.x(), c[1] - world.y()) * 100
            else:
                d = math.hypot(pc[0] - px[0], pc[1] - px[1])
            if d < radius and (best is None or d < best):
                best, bc = d, c
        return bc

    def _nearest_side(self, x, y):
        n = len(self.points)
        best, bi = None, None
        for i in range(n):
            a, b = self.points[i], self.points[(i + 1) % n]
            dx, dy = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dy * dy
            t = max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / L2)
                    ) if L2 > EPS else 0.0
            dist = math.hypot(a[0] + t * dx - x, a[1] + t * dy - y)
            if best is None or dist < best:
                best, bi = dist, i
        return bi

    def _draw_dir(self, viewport, painter) -> None:
        from PySide6.QtCore import QPointF
        n = len(self.points)
        hover = None
        if self.hover_point is not None:
            hover = self._nearest_side(self.hover_point.x(),
                                       self.hover_point.y())
        for i, col, wd in ((hover, QColor(255, 210, 0), 3),
                           (self.beam_side, QColor(0, 170, 255), 5)):
            if i is None:
                continue
            a, b = self.points[i], self.points[(i + 1) % n]
            pa = viewport._world_to_pixel(QVector3D(a[0], a[1], self._z(a)))
            pb = viewport._world_to_pixel(QVector3D(b[0], b[1], self._z(b)))
            if pa is None or pb is None:
                continue
            painter.setPen(QPen(col, wd))
            painter.drawLine(QPointF(pa[0], pa[1]), QPointF(pb[0], pb[1]))
        if self.beam_side is None:
            return
        ux, uy = _side_dir(self.points, self.beam_side,
                           _Settings.travi.get("mode", "par"))
        cx = sum(q[0] for q in self.points) / n
        cy = sum(q[1] for q in self.points) / n
        z = self._base() + max([self._rel(c) for c in self._ctrl()] or [0.0])
        p0 = viewport._world_to_pixel(QVector3D(cx - ux * 1.5, cy - uy * 1.5, z))
        p1 = viewport._world_to_pixel(QVector3D(cx + ux * 1.5, cy + uy * 1.5, z))
        if p0 is not None and p1 is not None:
            painter.setPen(QPen(QColor(0, 170, 255), 3))
            painter.drawLine(QPointF(p0[0], p0[1]), QPointF(p1[0], p1[1]))
            painter.setBrush(QColor(0, 170, 255))
            painter.drawEllipse(QPointF(p1[0], p1[1]), 5, 5)

    def draw_overlay(self, viewport, painter) -> None:
        try:
            self._draw(viewport, painter)
        except Exception:
            pass

    def _draw(self, viewport, painter) -> None:
        from PySide6.QtCore import QPointF, QRectF
        if not self.points:
            return
        if self.phase == "auto":
            painter.save()
            try:
                self._draw_auto(viewport, painter)
            finally:
                painter.restore()
            return
        painter.save()
        hot = None
        if self.hover_point is not None and self.phase != "outline":
            hot = self._pick(viewport, self.hover_point)
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        for c in self._ctrl():
            pc = viewport._world_to_pixel(QVector3D(c[0], c[1], self._z(c)))
            if pc is None:
                continue
            big = self.phase == "heights"
            r = (7 if big else 5) + (2 if c == hot else 0)
            painter.setPen(QPen(QColor(255, 255, 255), 1.5))
            painter.setBrush(QColor(255, 210, 0) if c == hot
                             else QColor(220, 30, 30))
            painter.drawRect(QRectF(pc[0] - r, pc[1] - r, 2 * r, 2 * r))
            rel = self._rel(c)
            if self.phase == "heights" and (abs(rel) > 1e-9 or c == hot):
                painter.setPen(QPen(QColor(20, 20, 20)))
                painter.drawText(QPointF(pc[0] + r + 4, pc[1] - r),
                                 ("-" if rel < 0 else "+") + fmt_len(abs(rel)))
        if self.phase == "lines" and self.hover_point is not None:
            q = self._snap(self.hover_point.x(), self.hover_point.y(),
                           commit=False)
            pq = viewport._world_to_pixel(
                QVector3D(q[0], q[1], self._base()))
            if pq is not None:
                painter.setPen(QPen(QColor(0, 170, 255), 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(QPointF(pq[0], pq[1]), 8, 8)
        if self.phase == "dir":
            self._draw_dir(viewport, painter)
        painter.restore()

    def _draw_auto(self, viewport, painter) -> None:
        """A dot on every edge of the outline (blue = gable end) and the
        rise at the points that are above the eaves."""
        from ._imperial import fmt_len
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        pts, gables = self.auto["pts"], self.auto["gables"]
        base = self._base()
        hot = (self._pick_edge(viewport, self.hover_point)
               if self.hover_point is not None else None)
        for i in range(len(pts)):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            pm = viewport._world_to_pixel(
                QVector3D((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, base))
            if pm is None:
                continue
            gable = i in gables
            r = (9 if gable else 5) + (2 if i == hot else 0)
            painter.setPen(QPen(QColor(255, 255, 255) if gable
                                else QColor(40, 40, 40), 1.5))
            painter.setBrush(QColor(255, 210, 0) if i == hot
                             else QColor(0, 110, 220) if gable
                             else QColor(255, 255, 255))
            painter.drawEllipse(QPointF(pm[0], pm[1]), r, r)
            if gable:
                painter.setPen(QPen(QColor(20, 20, 20) if i == hot
                                    else QColor(255, 255, 255)))
                painter.drawText(QRectF(pm[0] - r, pm[1] - r, 2 * r, 2 * r),
                                 Qt.AlignCenter, tr("T"))
        painter.setPen(QPen(QColor(20, 20, 20)))
        for c in self._ctrl():
            rel = self._rel(c)
            if rel <= 1e-6:
                continue
            pc = viewport._world_to_pixel(QVector3D(c[0], c[1], self._z(c)))
            if pc is not None:
                painter.drawText(QPointF(pc[0] + 8, pc[1] - 8),
                                 "+" + fmt_len(rel))

    def on_hover(self, ctx: ToolContext) -> None:
        w = QVector3D(ctx.world)
        if self.phase not in ("heights", "auto"):
            x, y = self._constrain(w.x(), w.y())
            w = QVector3D(x, y, w.z())
        self.hover_point = w
        ctx.viewport.update()

    def claims_key(self, key: int, modifiers) -> bool:
        if modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        if key in (Qt.Key_F8, Qt.Key_O):
            return True
        if key == Qt.Key_W and self.phase == "outline" and self.edit_group is None:
            return True
        if key == Qt.Key_P and (self.phase in ("lines", "auto") or (
                self.phase == "outline" and len(self.points) >= 3)):
            return True
        return key == Qt.Key_Escape or (
            key == Qt.Key_C and bool(self.points))

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if key in (Qt.Key_O, Qt.Key_F8):
            _Settings.ortho = not _Settings.ortho
            h = self.hover_point
            if h is not None and self.phase != "heights":
                x, y = self._constrain(h.x(), h.y())
                self.hover_point = QVector3D(x, y, h.z())
            viewport.flash_status(
                tr("Ortogonale ") + (tr("attivo") if _Settings.ortho
                                     else tr("disattivato")), 2000)
            viewport.update()
            return True
        if key in (Qt.Key_C, Qt.Key_Return, Qt.Key_Enter) and self.points:
            if self.phase == "outline":
                pts = muri._dedupe(list(self.points), True)
                if len(pts) < 3:
                    viewport.flash_status(tr("Servono almeno 3 vertici"), 3000)
                    return True
                self.points = [tuple(p) for p in pts]
                self.phase = "lines"
            elif self.phase == "lines":
                self.line_start = None
                self.phase = "heights"
            else:
                if self.phase in ("heights", "auto") and _Settings.travi.get("on"):
                    self.phase = "dir"
                    if self.beam_side is None:
                        self.beam_side = _longest_side(self.points)
                    viewport.flash_status(MSG["dir"], 8000)
                    viewport.update()
                    return True
                self._commit(viewport)
                return True
            viewport.flash_status(MSG[self.phase], 7000)
            viewport.update()
            return True
        if key == Qt.Key_W and self.phase == "outline" and self.edit_group is None:
            self._from_walls(viewport)
            return True
        if key == Qt.Key_P and self.phase in ("outline", "lines", "auto"):
            if self.phase == "outline":          # close the outline first
                pts = muri._dedupe(list(self.points), True)
                if len(pts) < 3:
                    viewport.flash_status(tr("Servono almeno 3 vertici"), 3000)
                    return True
                self.points = [tuple(p) for p in pts]
                self.phase = "lines"
            self._auto_start(viewport)
            viewport.update()
            return True
        if key == Qt.Key_Backspace:
            if self.phase == "auto":             # back to the bare outline
                self.points = list(self.auto["pts"])
                self.lines, self.heights, self.auto = [], {}, None
                self.phase = "lines"
                viewport.flash_status(MSG["lines"], 7000)
            elif self.phase == "outline" and self.points:
                self.points.pop()
            elif self.phase == "lines":
                if self._undo:
                    self.points, self.lines, self.line_start = (
                        self._undo.pop())
            elif self.phase == "dir":
                self.phase = "heights"
                viewport.flash_status(MSG["heights"], 5000)
            elif self.phase == "heights" and self.heights:
                self.heights.popitem()
            viewport.update()
            return True
        return False

    def rubber_band_lines(self):
        if not self.points:
            return []
        P = QVector3D
        base = self._base()
        lines = []
        if self.phase == "outline":
            pts = list(self.points)
            if (_Settings.rect and len(pts) == 1
                    and self.hover_point is not None):
                (x0, y0), h = pts[0], self.hover_point
                pts = [(x0, y0), (h.x(), y0), (h.x(), h.y()), (x0, h.y())]
                return [(P(*pts[i], base), P(*pts[(i + 1) % 4], base))
                        for i in range(4)]
            if self.hover_point is not None:
                p = self.hover_point
                pts.append((p.x(), p.y()))
            lines = [(P(*a, base), P(*b, base)) for a, b in zip(pts, pts[1:])]
            if len(pts) >= 3:
                lines.append((P(*pts[-1], base), P(*pts[0], base)))
            return lines
        n = len(self.points)
        for i in range(n):
            a, b = self.points[i], self.points[(i + 1) % n]
            lines.append((P(*a, self._z(a)), P(*b, self._z(b))))
        for a, b in self.lines:
            lines.append((P(*a, self._z(a)), P(*b, self._z(b))))
        if self.phase == "lines" and self.line_start and self.hover_point:
            a, h = self.line_start, self.hover_point
            lines.append((P(*a, self._z(a)), P(h.x(), h.y(), self._z(a))))
        for c in self._ctrl():
            lines.append((P(*c, base), P(*c, self._z(c))))
        return lines

    def _commit(self, viewport) -> None:
        if getattr(viewport.scene, "edit_group", None) is not None:
            viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        old_d = (roof_data(self.edit_group) if self.edit_group is not None
                 else None)
        ctrl = self._ctrl()
        rels = [self._rel(c) for c in ctrl]
        low = min(rels)
        base, extra = self._place()
        d = {"poly": [list(p) for p in self.points],
             "lines": [[list(a), list(b)] for a, b in self.lines],
             "ctrl": [[c[0], c[1], base + r - low]
                      for c, r in zip(ctrl, rels)],
             "base": base, "th": _Settings.thickness,
             "rise": max(rels) - low}
        d.update(extra)
        lay = (old_d.get("layers") if old_d is not None and not self.panel
               else _Settings.layers)
        if lay:
            d["layers"] = copy.deepcopy(lay)
            d["th"] = layers_total(lay)
        tv = _Settings.travi
        if tv.get("on"):
            side = self.beam_side
            if side is None or side >= len(self.points):
                side = _longest_side(self.points)
            d["travi"] = _travi_params(tv, self.points, side)
        name = _Settings.name
        if old_d is not None and not self.panel:
            tid, tnome = old_d.get("tipo_id"), old_d.get("tipo_nome")
        else:
            tid, tnome = _Settings.tipo_id, _Settings.tipo_nome
        if tid:
            d["tipo_id"], d["tipo_nome"] = tid, tnome
        upd = getattr(self, "_tipo_upd", None)
        self._tipo_upd = None
        old = roof_data(self.edit_group) if self.edit_group is not None else None
        for k in PAINT_KEYS:
            v = (old.get(k) if old is not None and not self.panel
                 else getattr(_Settings, k, None))
            if v:
                d[k] = copy.deepcopy(v)
        if old is not None and old.get("fori"):
            d["fori"] = copy.deepcopy(old["fori"])
        d["src"] = {"poly": [list(p) for p in d["poly"]],
                    "lines": [[list(a), list(b)] for a, b in d["lines"]],
                    "ctrl": [list(c) for c in d["ctrl"]]}
        try:
            d = apply_offset(d, _Settings.offset)
            roof_mesh(d)
        except ImportError:
            viewport.flash_status(tr("Serve shapely: pip install shapely"), 6000)
            return
        target = self.edit_group

        def mutate(scene):
            if target is not None:
                _ensure_beam_layer(scene, d)
                target.children = roof_parts(d)
                _ifc.tag(target, "IfcRoof")
                ext = dict(target.ext or {})
                ext[KEY] = d
                target.ext = ext
                if upd:
                    def _rb(g, q):
                        nd = dict(roof_data(g))
                        nd.update(q)
                        rebuild_roof(g, {k: v for k, v in nd.items()
                                         if v is not None})
                    _tipi.update_instances(scene, "tetto", upd, _rb)
            else:
                build_roof(scene, d, name)
            update_roof_clips(scene)

        viewport.history.execute(muri.MuriCommand(mutate))
        viewport.notify_scene_changed()
        if target is not None:
            viewport.flash_status(tr("Tetto modificato"), 3000)
            self._exit(viewport)
            return
        viewport.flash_status(tr("Tetto creato"), 3000)
        self._reset()
        viewport.update()


def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap, QPolygon
    from PySide6.QtCore import QPoint
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(170, 90, 75))
    p.drawPolygon(QPolygon([QPoint(4, 28), QPoint(24, 10), QPoint(44, 28)]))
    p.setBrush(QColor(215, 205, 190))
    p.drawRect(10, 28, 28, 12)
    p.end()
    return QIcon(pm)


def _beam_props(d):
    tv = d.get("travi")
    if not tv:
        return []
    from ._imperial import fmt_len
    sec = (f"Ø {fmt_len(tv['w'])}" if tv.get("shape") == "round"
           else f"{fmt_len(tv['w'])} × {fmt_len(tv['h'])}")
    if tv.get("n") is not None:
        return [(tr("Travi"), sec), (tr("Numero travi"), str(tv["n"])),
                (tr("Distribuzione travi"),
                 tr("Dal centro") if tv.get("dist") == "center"
                 else tr("Dai lati"))]
    return [(tr("Travi"), sec), (tr("Interasse travi"), fmt_len(tv["sp"]))]


def _outliner_kind(group):
    d = roof_data(group)
    if d is None:
        return None
    from ._imperial import fmt_len
    return {"type": tr("Tetto"),
            "props": [(tr("Spessore"), fmt_len(d["th"])),
                      (tr("Gronda"), fmt_len(d["base"])),
                      (tr("Dislivello"), fmt_len(d.get("rise", 0.0))),
                      (tr("Sporto"), fmt_len(_roof_offset(d)))]
            + _beam_props(d) + piani.level_props(d)}


def _selected_roofs(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and roof_data(g) is not None and g not in out:
            out.append(g)
    return out


def edit_beams(viewport, group) -> None:
    if getattr(viewport.scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    d = roof_data(group)
    if d is None:
        return
    tv = d.get("travi")
    cur = dict(_TRAVI_DEFAULT)
    if tv:
        cur.update(tv)
    cur["on"] = bool(tv)
    res = ask_beams(viewport.window(), cur, with_on=True)
    if res is None:
        return

    def mutate(sc):
        q = dict(d)
        if res["on"]:
            src = (d.get("src") or d)["poly"]
            side = (tv or {}).get("side")
            if side is None or side >= len(src):
                side = _longest_side(src)
            q["travi"] = _travi_params(res, src, side)
        else:
            q.pop("travi", None)
        _ensure_beam_layer(sc, q)
        rebuild_roof(group, q)

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("Travi del tetto aggiornate"), 3000)


def edit_roof_paint(viewport, roofs=None) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    roofs = roofs or _selected_roofs(scene)
    if not roofs:
        viewport.flash_status(tr("Seleziona un tetto"), 3000)
        return
    first = roof_data(roofs[0])
    dlg = QDialog(viewport.window())
    dlg.setWindowTitle(tr("Colori e texture tetto"))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    pk = muri.add_paint_rows(form, first.get, ROOF_ZONES)
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return
    changed = {k: v for k, v in muri.paint_results(pk).items()
               if v != first.get(k)}
    if not changed:
        return

    def mutate(sc):
        for g in roofs:
            q = dict(roof_data(g))
            for k, v in changed.items():
                if v:
                    q[k] = v
                else:
                    q.pop(k, None)
            rebuild_roof(g, q)

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("Materiali applicati"), 3000)


def _hook_double_click(vp, tool) -> None:
    if getattr(vp, "_myhouse_tetto_dbl", False):
        return
    original = vp.begin_group_edit

    def begin_group_edit(group, *args, **kwargs):
        g = getattr(group, "owner", None) or group
        if roof_data(g) is None:
            return original(group, *args, **kwargs)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: tool.edit_panel(vp, g))

    vp.begin_group_edit = begin_group_edit
    vp._myhouse_tetto_dbl = True


def _register_level_kind() -> None:
    def zset(d, z):
        delta = z - d["base"]
        d["base"] = z
        d["ctrl"] = [[c[0], c[1], c[2] + delta] for c in d["ctrl"]]
        if d.get("src"):
            src = dict(d["src"])
            src["ctrl"] = [[c[0], c[1], c[2] + delta] for c in src["ctrl"]]
            d["src"] = src

    piani.register_kind("tetto", KEY, roof_data, lambda d: d["base"], zset,
                        rebuild_roof)


def register(api) -> None:
    _register_level_kind()
    tool = TettoTool()
    api.add_button(tr("Tetto"), tr("Crea un tetto a falde (contorno, linee, quote)"),
                   _icon(), api.run_tool(tool))
    app = api.app
    _hook_double_click(api.window.viewport, tool)
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        from PySide6.QtCore import QTimer

        def context(menu, selection) -> None:
            roofs = _selected_roofs(app.viewport.scene)
            if not roofs:
                return
            menu.addSeparator()
            menu.addAction(
                tr("Impostazioni tetto…"),
                lambda: QTimer.singleShot(
                    0, lambda: tool.edit_panel(app.viewport, roofs[0])))
            menu.addAction(
                tr("Modifica quote tetto…"),
                lambda: QTimer.singleShot(
                    0, lambda: tool.edit(app.viewport, roofs[0])))
            menu.addAction(
                tr("Colori e texture tetto…"),
                lambda: QTimer.singleShot(
                    0, lambda: edit_roof_paint(app.viewport)))
            menu.addAction(
                tr("Modifica travi tetto…"),
                lambda: QTimer.singleShot(
                    0, lambda: edit_beams(app.viewport, roofs[0])))

        add_ctx(context)
    add_kind = getattr(app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
