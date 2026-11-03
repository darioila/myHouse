# SPDX-License-Identifier: GPL-3.0-or-later
"""Plugin Tetto per IngeTrazo / MyHouse — crea tetti BIM (IfcRoof) a falde.

Uso: Extensions > Tetto, scegli spessore e quota di gronda, poi:
  1. CONTORNO: clic per i vertici (1,2,5,4,3,6...), C/Invio chiude.
  2. LINEE INTERNE (facoltative): due clic = una linea (es. 5-6). Gli estremi
     si agganciano a vertici o lati del contorno (sul lato aggiungono un
     punto di controllo). Backspace annulla l'ultima, Invio continua.
  3. QUOTE: clic su un punto di controllo -> inserisci la quota in metri
     rispetto al punto più basso del tetto. Invio crea il tetto.
  Esc esce dal comando, tasto destro esce.

Ogni regione chiusa dalle linee diventa una falda; le quote dei punti
di controllo vengono interpolate lungo i lati e le linee.
Richiede shapely (pip install shapely).
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPen, QVector3D
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QInputDialog,
    QLineEdit, QVBoxLayout,
)

from core import bim
from tools.base import Tool, ToolContext

from . import muri, piani

ORDER = 50
ROOF_COLOR = (0.62, 0.33, 0.28)
LAYER_NAME = "Tetti"
KEY = "myhouse_tetto"
EPS = 1e-6
SNAP = 0.25                     # raggio di aggancio (m)
SAME = 1e-4                     # tolleranza per punti coincidenti
PLANAR_TOL = 0.01               # falde entro 1 cm dal piano = una sola faccia


class _Settings:
    thickness = 0.20
    z_base = 3.0                # quota del punto più basso (gronda)
    offset = 0.0                # sporto del tetto rispetto al contorno
    pitch = 30.0                # inclinazione del padiglione automatico (gradi)
    name = "Tetto"
    level = None                # id del piano che chiude (None = nessuno)


# ---------------------------------------------------------------------------
# Geometria pura
# ---------------------------------------------------------------------------

def _area(pts) -> float:
    return 0.5 * sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
                     - pts[(i + 1) % len(pts)][0] * pts[i][1]
                     for i in range(len(pts)))


def _triangulate(pts):
    """Ear clipping 2D (xy) per poligoni semplici. Triangoli antiorari."""
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
    """True se tutti i punti 3D stanno su uno stesso piano."""
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
    """Punti di controllo unici: vertici del contorno + estremi delle linee."""
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
    """Piano z = a*x + b*y + c dai tre punti con area massima."""
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
    """Intersezione di due rette. Ritorna (punto, t su retta 1) o None."""
    cr = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(cr) <= 1e-6 * math.hypot(*d1) * math.hypot(*d2):
        return None
    t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / cr
    return (p1[0] + t * d1[0], p1[1] + t * d1[1]), t


def apply_offset(d, off):
    """Sporto: sposta il contorno verso l'esterno di `off`, prolunga le linee
    interne che finiscono sul contorno e prolunga le falde (quote
    estrapolate dalla pendenza)."""
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

    # prolunga le linee che finiscono su un lato dritto del contorno
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
                ctrl=ctrl, off=off)


def roof_mesh(d):
    """Mesh del tetto: d["poly"], d["lines"], d["ctrl"] [x,y,z], d["th"]."""
    from core.mesh import Mesh
    from shapely.geometry import LineString, LinearRing
    from shapely.geometry.polygon import orient
    from shapely.ops import polygonize, unary_union
    P = QVector3D
    th = d["th"]
    poly = [tuple(p) for p in d["poly"]]
    if _area(poly) < 0:
        poly.reverse()
    d = dict(d, poly=poly)
    mesh = Mesh()

    def face(q):
        f = mesh.add_face(q)
        # nessun colore predefinito: si applicano i materiali di IngeTrazo
        f.attrs["layer"] = LAYER_NAME

    geoms = [LinearRing(poly)] + [LineString(ln) for ln in d["lines"]]
    for region in polygonize(unary_union(geoms)):
        ring = list(orient(region, 1.0).exterior.coords)[:-1]
        top = [(x, y, _z_at(d, x, y)) for x, y in ring]
        xy = [(p[0], p[1]) for p in top]
        if _is_planar(top) and _is_convex(xy):
            face([P(*p) for p in top])
            face([P(p[0], p[1], p[2] - th) for p in reversed(top)])
        else:
            for a, b, c in _triangulate(xy):
                face([P(*top[a]), P(*top[b]), P(*top[c])])
                face([P(top[c][0], top[c][1], top[c][2] - th),
                      P(top[b][0], top[b][1], top[b][2] - th),
                      P(top[a][0], top[a][1], top[a][2] - th)])
    n = len(poly)
    for i in range(n):
        j = (i + 1) % n
        zi, zj = _z_at(d, *poly[i]), _z_at(d, *poly[j])
        face([P(*poly[i], zi - th), P(*poly[j], zj - th),
              P(*poly[j], zj), P(*poly[i], zi)])
    return mesh


# ---------------------------------------------------------------------------
# Regola: i muri che attraversano il tetto vengono tagliati sotto di esso
# ---------------------------------------------------------------------------

def _group_matrix(g):
    from PySide6.QtGui import QMatrix4x4
    x = getattr(g, "xform", None)
    return QMatrix4x4(x) if x is not None else QMatrix4x4()


def _roof_underside(d):
    """[(anello 2D, (a, b, c))] delle falde: z = a*x + b*y + c è l'intradosso."""
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
        out.append([(x, y, _z_at(dd, x, y) - d["th"]) for x, y in ring])
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
            for x, y, z in ring3:                  # falda -> coordinate muro
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
                continue                           # il tetto sta sopra il muro
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
                    if (zs0 - z1) * (zs1 - z1) < 0:   # il taglio inizia qui
                        f = (z1 - zs0) / (zs1 - zs0)
                        pts.append((x0 + f * (x1 - x0), y0 + f * (y1 - y0)))
                    ends = [Point(ln.coords[0]), Point(ln.coords[-1])]
                    for px, py in pts:
                        if any(e.distance(Point(px, py)) < 1e-6 for e in ends):
                            continue           # estremo del muro: non è un taglio
                        t = ((px - ax) * ux + (py - ay) * uy) / L
                        if 1e-4 < t < 1 - 1e-4:
                            ts.add(round(t, 6))
    if not regions:
        return None
    return {"regions": regions, "ts": sorted(ts)}


def _roof_low(rd) -> float:
    """Quota più bassa dell'intradosso del tetto."""
    zs = [c[2] for c in rd.get("ctrl") or ()]
    return (min(zs) if zs else rd["base"]) - rd["th"]


def update_roof_clips(scene) -> int:
    """Ricalcola il taglio di tutti i muri contro tutti i tetti della scena.
    Ritorna quanti muri sono cambiati."""
    try:
        import shapely  # noqa: F401
    except ImportError:
        return 0
    changed = 0
    roofs = []
    for g in scene.groups:
        rd = roof_data(g)
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
        g.children = [muri.wall_part(new, muri.wall_pose(g))]
        ext = dict(g.ext or {})
        ext[muri.KEY] = new
        g.ext = ext
        changed += 1
    return changed


def roof_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "poly" in data else None


def rebuild_roof(group, d) -> None:
    """Nuova geometria dai parametri d, stesso gruppo."""
    from core.group import Group
    part = Group(roof_mesh(d), name="Tetto")
    part.component = False
    group.children = [part]
    ext = dict(group.ext or {})
    ext[KEY] = dict(d)
    group.ext = ext


def build_roof(scene, d, name) -> None:
    from core.group import Group
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    part = Group(roof_mesh(d), name="Tetto")
    part.component = False
    g = Group(name=name)
    g.adopt([part])
    g.component = False
    g.layer = LAYER_NAME
    bim.tag_group(g, "IfcRoof", name)
    g.ext = {KEY: d}
    scene.groups.append(g)


# ---------------------------------------------------------------------------
# Impostazioni
# ---------------------------------------------------------------------------

def _spin(value, lo, hi):
    s = QDoubleSpinBox()
    s.setDecimals(3)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


def ask_settings(parent, scene=None) -> bool:
    dlg = QDialog(parent)
    dlg.setWindowTitle("Tetto")
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    thick = _spin(_Settings.thickness, 0.02, 5.0)
    z = _spin(_Settings.z_base, -100.0, 1000.0)
    off = _spin(_Settings.offset, 0.0, 10.0)
    name = QLineEdit(_Settings.name)
    lvl = None
    if scene is not None and piani.levels(scene):
        lvl = piani.level_combo(scene, piani.active_id(scene))

        def on_level(_i) -> None:           # gronda = altezza del piano
            lv = piani.get(scene, lvl.currentData())
            if lv:
                z.setValue(lv["h"])
        lvl.currentIndexChanged.connect(on_level)
        form.addRow("Piano che copre", lvl)
    form.addRow("Spessore (m)", thick)
    form.addRow("Gronda: da terra / sopra la quota del piano (m)", z)
    form.addRow("Sporto rispetto al contorno (m)", off)
    form.addRow("Nome", name)
    lay.addLayout(form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return False
    _Settings.offset = off.value()
    _Settings.thickness = thick.value()
    _Settings.z_base = z.value()
    _Settings.name = name.text().strip() or "Tetto"
    _Settings.level = (lvl.currentData() or None) if lvl is not None else None
    if lvl is not None:
        piani.set_active(_Settings.level)
    return True


# ---------------------------------------------------------------------------
# Strumento
# ---------------------------------------------------------------------------

MSG = {
    "outline": "Tetto 1/3 contorno: clic per i vertici · C/Invio = chiudi · "
               "Backspace = annulla · Esc = esci",
    "lines": "Tetto 2/3 linee interne (colmo, displuvi): due clic = una linea, "
             "si aggancia a punti e linee · P = padiglione automatico · "
             "Invio = continua · Backspace = annulla",
    "heights": "Tetto 3/3 quote: clic su un punto per dargli la quota · "
               "Invio = crea tetto",
}


class TettoTool(Tool):
    name = "Tetto"
    shortcut = None
    description = "Crea un tetto a falde con quote per punto di controllo."

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
        self.edit_group = None          # tetto esistente in modifica
        self._undo: list = []

    # -- ciclo di vita -------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._scene = viewport.scene
        if self._entering:
            self._reset()
            viewport.flash_status(MSG["outline"], 7000)
            return
        if not ask_settings(viewport.window(), viewport.scene):
            return
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def edit(self, viewport, group) -> None:
        """Modifica le quote dei punti di un tetto già creato."""
        d = roof_data(group)
        if d is None:
            return
        if getattr(viewport.scene, "edit_group", None) is not None:
            viewport.flash_status("Chiudi il gruppo che stai modificando", 4000)
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
        _Settings.level = d.get("lv")
        _Settings.z_base = d.get("off", d["base"]) if d.get("lv") else d["base"]
        _Settings.offset = d.get("off", 0.0) if d.get("src") else 0.0
        _Settings.name = group.name or _Settings.name
        self.edit_group = group
        self.phase = "heights"
        viewport.flash_status(
            "Modifica tetto: clic su un punto per cambiarne la quota · "
            "Invio = applica · Esc = annulla", 8000)
        viewport.update()

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

    # -- aiuti ---------------------------------------------------------------
    @staticmethod
    def _key(p):
        return (round(p[0], 3), round(p[1], 3))

    def _ctrl(self):
        return ctrl_points(self.points, self.lines)

    def _rel(self, p) -> float:
        return self.heights.get(self._key(p), 0.0)

    def _snap(self, x, y, commit=True):
        """Aggancia a un punto di controllo, a una linea interna o a un lato
        del contorno. Con commit=True spezza la linea/il lato nel punto
        agganciato (così il punto si può alzare). Ritorna (x, y)."""
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
        """Aggiunge una linea; dove incrocia altre linee spezza entrambe."""
        cuts = []                              # (t sulla nuova, punto)
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

    def _auto_hip(self, viewport) -> None:
        """Padiglione automatico: colmo e displuvi calcolati dal contorno
        (convesso), falde sempre piane con la stessa inclinazione."""
        pts = [tuple(p) for p in self.points]
        if _area(pts) < 0:
            pts.reverse()
        if len(pts) < 3 or not _is_convex(pts):
            viewport.flash_status(
                "Padiglione automatico: serve un contorno convesso", 4000)
            return
        deg, ok = QInputDialog.getDouble(
            viewport.window(), "Padiglione automatico",
            "Inclinazione delle falde (gradi)", _Settings.pitch, 1.0, 80.0, 1)
        if not ok:
            return
        _Settings.pitch = deg
        slope = math.tan(math.radians(deg))
        n = len(pts)
        defs = []                                  # (nx, ny, c): d = n·x - c
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            dx, dy = b[0] - a[0], b[1] - a[1]
            L = math.hypot(dx, dy)
            if L < EPS:
                continue
            nx, ny = -dy / L, dx / L
            c = nx * a[0] + ny * a[1]
            if not any(abs(nx - u[0]) < 1e-6 and abs(ny - u[1]) < 1e-6
                       and abs(c - u[2]) < 1e-4 for u in defs):
                defs.append((nx, ny, c))

        def dist(p):
            return min(u[0] * p[0] + u[1] * p[1] - u[2] for u in defs)

        def clip(poly, f):
            out = []
            for i in range(len(poly)):
                p, q = poly[i], poly[(i + 1) % len(poly)]
                fp, fq = f(p), f(q)
                if fp <= 1e-9:
                    out.append(p)
                if (fp < -1e-9 and fq > 1e-9) or (fp > 1e-9 and fq < -1e-9):
                    t = fp / (fp - fq)
                    out.append((p[0] + t * (q[0] - p[0]),
                                p[1] + t * (q[1] - p[1])))
            return out

        canon: list = []

        def cid(p):
            for k, c in enumerate(canon):
                if math.hypot(c[0] - p[0], c[1] - p[1]) < 1e-4:
                    return k
            canon.append((p[0], p[1]))
            return len(canon) - 1

        outline_ids = [cid(p) for p in pts]
        faces = []
        for u in defs:
            poly = pts
            for v in defs:
                if v is u:
                    continue
                poly = clip(poly, lambda p, u=u, v=v: (
                    (u[0] - v[0]) * p[0] + (u[1] - v[1]) * p[1] - (u[2] - v[2])))
                if len(poly) < 3:
                    break
            if len(poly) >= 3 and abs(_area(poly)) > 1e-6:
                faces.append([cid(p) for p in poly])

        def on_outline(p) -> bool:
            for i in range(n):
                a, b = pts[i], pts[(i + 1) % n]
                dx, dy = b[0] - a[0], b[1] - a[1]
                L2 = dx * dx + dy * dy
                t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy)
                                 / L2)) if L2 > EPS else 0.0
                if math.hypot(a[0] + t * dx - p[0], a[1] + t * dy - p[1]) < 1e-4:
                    return True
            return False

        edges = set()
        for f in faces:
            for i in range(len(f)):
                p, q = f[i], f[(i + 1) % len(f)]
                if p == q:
                    continue
                mid = ((canon[p][0] + canon[q][0]) / 2,
                       (canon[p][1] + canon[q][1]) / 2)
                if not on_outline(mid):
                    edges.add((min(p, q), max(p, q)))
        self.points = [canon[k] for k in outline_ids]
        self.lines = [(canon[p], canon[q]) for p, q in sorted(edges)]
        self.heights = {self._key(c): slope * dist(c) for c in canon}
        self.line_start = None
        self._undo = []
        self.phase = "heights"
        viewport.flash_status(
            "Padiglione calcolato: puoi ancora cambiare le quote · "
            "Invio = crea tetto", 7000)
        viewport.update()

    def _push_undo(self) -> None:
        self._undo.append((list(self.points), list(self.lines),
                           self.line_start))

    def _place(self):
        """(quota della gronda, dati del piano) secondo le impostazioni."""
        sc = getattr(self, "_scene", None)
        if sc is None:
            return _Settings.z_base, {}
        return piani.place(sc, _Settings.level, _Settings.z_base)

    def _base(self) -> float:
        return self._place()[0]

    def _z(self, p) -> float:
        base = self._base()
        return base + self._rel(p)

    # -- eventi --------------------------------------------------------------
    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        x, y = ctx.world.x(), ctx.world.y()
        if self.phase == "outline":
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
        else:  # heights: si sceglie il quadratino più vicino al cursore (px)
            near = self._pick(vp, ctx.world)
            if near is None:
                vp.flash_status("Clicca su un quadratino rosso", 3000)
                return
            val, ok = QInputDialog.getDouble(
                vp.window(), "Quota punto",
                "Quota rispetto al punto più basso (m)",
                self._rel(near), -100.0, 1000.0, 3)
            if ok:
                self.heights[self._key(near)] = val
        vp.update()

    def _pick(self, vp, world, radius=18.0):
        """Punto di controllo più vicino al cursore (in pixel)."""
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

    def draw_overlay(self, viewport, painter) -> None:
        try:
            self._draw(viewport, painter)
        except Exception:            # mai rompere il ciclo di disegno
            pass

    def _draw(self, viewport, painter) -> None:
        from PySide6.QtCore import QPointF, QRectF
        if not self.points:
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
                                 f"{rel:+.2f} m")
        if self.phase == "lines" and self.hover_point is not None:
            q = self._snap(self.hover_point.x(), self.hover_point.y(),
                           commit=False)
            pq = viewport._world_to_pixel(
                QVector3D(q[0], q[1], self._base()))
            if pq is not None:                  # anteprima dell'aggancio
                painter.setPen(QPen(QColor(0, 170, 255), 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(QPointF(pq[0], pq[1]), 8, 8)
        painter.restore()

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = QVector3D(ctx.world)
        ctx.viewport.update()

    def claims_key(self, key: int, modifiers) -> bool:
        if modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        return key == Qt.Key_Escape or (
            key == Qt.Key_C and bool(self.points)) or (
            key == Qt.Key_P and self.phase == "lines")

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if key in (Qt.Key_C, Qt.Key_Return, Qt.Key_Enter) and self.points:
            if self.phase == "outline":
                pts = muri._dedupe(list(self.points), True)
                if len(pts) < 3:
                    viewport.flash_status("Servono almeno 3 vertici", 3000)
                    return True
                self.points = [tuple(p) for p in pts]
                self.phase = "lines"
            elif self.phase == "lines":
                self.line_start = None
                self.phase = "heights"
            else:
                self._commit(viewport)
                return True
            viewport.flash_status(MSG[self.phase], 7000)
            viewport.update()
            return True
        if key == Qt.Key_P and self.phase == "lines":
            self._auto_hip(viewport)
            return True
        if key == Qt.Key_Backspace:
            if self.phase == "outline" and self.points:
                self.points.pop()
            elif self.phase == "lines":
                if self._undo:
                    self.points, self.lines, self.line_start = (
                        self._undo.pop())
            elif self.phase == "heights" and self.heights:
                self.heights.popitem()
            viewport.update()
            return True
        return False

    # -- disegno provvisorio -------------------------------------------------
    def rubber_band_lines(self):
        if not self.points:
            return []
        P = QVector3D
        base = self._base()
        lines = []
        if self.phase == "outline":
            pts = list(self.points)
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
        for c in self._ctrl():                      # asta verticale = quota
            lines.append((P(*c, base), P(*c, self._z(c))))
        return lines

    # -- creazione -----------------------------------------------------------
    def _commit(self, viewport) -> None:
        if getattr(viewport.scene, "edit_group", None) is not None:
            viewport.flash_status("Chiudi il gruppo che stai modificando", 4000)
            return
        ctrl = self._ctrl()
        rels = [self._rel(c) for c in ctrl]
        low = min(rels)                       # quota relativa al punto basso
        base, extra = self._place()
        d = {"poly": [list(p) for p in self.points],
             "lines": [[list(a), list(b)] for a, b in self.lines],
             "ctrl": [[c[0], c[1], base + r - low]
                      for c, r in zip(ctrl, rels)],
             "base": base, "th": _Settings.thickness,
             "rise": max(rels) - low}
        d.update(extra)
        name = _Settings.name
        d["src"] = {"poly": [list(p) for p in d["poly"]],
                    "lines": [[list(a), list(b)] for a, b in d["lines"]],
                    "ctrl": [list(c) for c in d["ctrl"]]}
        try:
            d = apply_offset(d, _Settings.offset)
            roof_mesh(d)
        except ImportError:
            viewport.flash_status("Serve shapely: pip install shapely", 6000)
            return
        target = self.edit_group

        def mutate(scene):
            if target is not None:
                from core.group import Group
                part = Group(roof_mesh(d), name="Tetto")
                part.component = False
                target.children = [part]
                ext = dict(target.ext or {})
                ext[KEY] = d
                target.ext = ext
            else:
                build_roof(scene, d, name)
            update_roof_clips(scene)

        viewport.history.execute(muri.MuriCommand(mutate))
        viewport.notify_scene_changed()
        if target is not None:
            viewport.flash_status("Tetto modificato", 3000)
            self._exit(viewport)
            return
        viewport.flash_status("Tetto creato", 3000)
        self._reset()
        viewport.update()


# ---------------------------------------------------------------------------
# Registrazione
# ---------------------------------------------------------------------------

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


def _outliner_kind(group):
    d = roof_data(group)
    if d is None:
        return None
    from core.units import fmt_len
    return {"type": "Tetto",
            "props": [("Spessore", fmt_len(d["th"])),
                      ("Gronda", fmt_len(d["base"])),
                      ("Dislivello", fmt_len(d.get("rise", 0.0))),
                      ("Sporto", fmt_len(d.get("off", 0.0)))]
            + piani.level_props(d)}


def _selected_roofs(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and roof_data(g) is not None and g not in out:
            out.append(g)
    return out


def _hook_double_click(vp, tool) -> None:
    """Doppio clic su un tetto = modifica le quote dei punti."""
    if getattr(vp, "_myhouse_tetto_dbl", False):
        return
    original = vp.begin_group_edit

    def begin_group_edit(group, *args, **kwargs):
        g = getattr(group, "owner", None) or group
        if roof_data(g) is None:
            return original(group, *args, **kwargs)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: tool.edit(vp, g))

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
    api.add_button("Tetto", "Crea un tetto a falde (contorno, linee, quote)",
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
                "Modifica tetto…",
                lambda: QTimer.singleShot(
                    0, lambda: tool.edit(app.viewport, roofs[0])))

        add_ctx(context)
    add_kind = getattr(app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
