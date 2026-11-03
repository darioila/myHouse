# SPDX-License-Identifier: GPL-3.0-or-later
"""Plugin Solaio per IngeTrazo / MyHouse — crea solai BIM (IfcSlab).

Uso: Extensions > Solaio, scegli spessore e altezza da terra, poi:
  - modo AUTOMATICO: clic dentro una stanza chiusa da muri -> il solaio
    prende da solo il contorno interno dei muri (muri creati con "Muri").
  - modo MANUALE: clic per i vertici, C o Invio chiude e crea, O/F8 = ortogonale.
  - Esc esce dal comando, tasto destro esce.
Fori: Extensions > Foro solaio, clic per i vertici del foro dentro il solaio,
C o Invio crea. Ctrl+Z annulla.

"Altezza da terra" = quota della faccia SUPERIORE del solaio (il pavimento);
lo spessore va verso il basso.

Il rilevamento automatico usa la libreria shapely (pip install shapely).
"""
from __future__ import annotations

import copy
import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPen, QVector3D
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QLabel, QPushButton, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QLineEdit, QVBoxLayout,
)

from core import bim
from tools.base import Tool, ToolContext

from . import muri

ORDER = 20
SLAB_COLOR = (0.72, 0.72, 0.70)
LAYER_NAME = "Solai"
KEY = "myhouse_solaio"          # parametri in group.ext
EPS = 1e-6
GAP_TOL = 0.01                  # fessure tra muri più piccole di 1 cm = chiuse


class _Settings:
    thickness = 0.20
    z_top = 0.0                 # altezza da terra (faccia superiore)
    name = "Solaio"
    auto = True
    spline = False              # modo manuale: contorno curvo (tasto S)
    level = None                # id del piano (None = nessuno)


# ---------------------------------------------------------------------------
# Geometria pura
# ---------------------------------------------------------------------------

def _area(pts) -> float:
    return 0.5 * sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
                     - pts[(i + 1) % len(pts)][0] * pts[i][1]
                     for i in range(len(pts)))


def _triangulate(pts):
    """Ear clipping per poligoni semplici (anche concavi). Ritorna triangoli
    di indici, orientati antiorari."""
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
                continue                       # vertice concavo/collineare
            if any(inside(p, a, b, c) for p in idx
                   if p not in (a, b, c)
                   and pts[p] not in (pts[a], pts[b], pts[c])):
                continue
            tris.append((a, b, c))
            idx.pop(k)
            break
        else:
            break                              # poligono degenerato
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
    """Unisce i fori al contorno con "ponti": un unico anello da triangolare."""
    ring = list(outer)                       # antiorario
    hs = []
    for h in holes:
        h = [tuple(p) for p in h]
        if _area(h) > 0:
            h.reverse()                      # orario
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
    """Attributi di faccia del materiale `name` del documento, o None."""
    if not name:
        return None
    try:
        sc = scene if scene is not None else _APP["app"].viewport.scene
        mat = sc.materials.get(name)
        return dict(mat.face_attrs()) if mat is not None else None
    except Exception:
        return None


def _ask_material(viewport, current, label="Materiale", extra=None):
    """Dialogo: sceglie un materiale del documento. extra = lista di
    (chiave, etichetta, valore attuale) per altri materiali. Ritorna un dict
    {chiave: nome|None} oppure None se annullato."""
    mats = sorted(viewport.scene.materials)
    if not mats:
        viewport.flash_status("Il documento non ha materiali", 3000)
        return None
    dlg = QDialog(viewport.window())
    dlg.setWindowTitle(label)
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    combos = {}
    for key, text, cur in [("mat", label, current)] + list(extra or []):
        cb = QComboBox()
        cb.addItem("(predefinito)", None)
        for m in mats:
            cb.addItem(m, m)
        i = cb.findData(cur)
        cb.setCurrentIndex(max(0, i))
        form.addRow(text, cb)
        combos[key] = cb
    lay.addLayout(form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return None
    return {k: c.currentData() for k, c in combos.items()}


def slab_mesh(d):
    """Mesh del solaio dai suoi dati: d["poly"], d["th"], d["z"],
    d["holes"] (opzionale: lista di poligoni)."""
    from core.mesh import Mesh
    P = QVector3D
    pts = [tuple(p) for p in d["poly"]]
    if _area(pts) < 0:
        pts.reverse()                          # antiorario
    holes = [[tuple(p) for p in h] for h in d.get("holes", [])]
    zt, zb = d["z"], d["z"] - d["th"]
    mesh = Mesh()
    ma = _mat_attrs(d.get("mat"))

    def paint(f):
        if ma:
            f.attrs.update(copy.deepcopy(ma))
        # nessun colore predefinito: le facce restano senza materiale
        f.attrs["layer"] = LAYER_NAME

    def face(q):
        paint(mesh.add_face(q))

    def tri_fallback():
        ring = _merge_holes(pts, holes) if holes else pts
        for a, b, c in _triangulate(ring):
            face([P(*ring[a], zt), P(*ring[b], zt), P(*ring[c], zt)])
            face([P(*ring[c], zb), P(*ring[b], zb), P(*ring[a], zb)])

    hs_top = [list(reversed(h)) if _area(h) > 0 else list(h) for h in holes]
    hs_bot = [list(reversed(h)) for h in hs_top]
    try:
        # una sola faccia sopra e una sotto (anche con fori): niente
        # triangoli visibili
        for q, hh, z, rev in ((pts, hs_top, zt, False),
                              (list(reversed(pts)), hs_bot, zb, True)):
            f = mesh.add_face([P(*p, z) for p in q],
                              [[P(*p, z) for p in h] for h in hh])
            paint(f)
    except Exception:
        mesh = Mesh()
        tri_fallback()
    loops = [pts] + [list(reversed(h)) if _area(h) > 0 else h for h in holes]
    for loop in loops:
        n = len(loop)
        for i in range(n):
            j = (i + 1) % n
            face([P(*loop[i], zb), P(*loop[j], zb),
                  P(*loop[j], zt), P(*loop[i], zt)])
    return mesh


def slab_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "poly" in data else None


def rebuild_slab(group, d) -> None:
    """Nuova geometria dai dati d, stesso gruppo."""
    from core.group import Group
    part = Group(slab_mesh(d), name="Solaio")
    part.component = False
    group.children = [part]
    ext = dict(group.ext or {})
    ext[KEY] = dict(d)
    group.ext = ext


def build_slab(scene, poly, thickness, z_top, name, level=None,
               off=0.0) -> None:
    from core.group import Group
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    d = {"poly": [list(p) for p in poly], "th": thickness, "z": z_top}
    if level:                           # piano: z = quota piano + off
        d.update({"lv": level["id"], "lvn": level["name"], "off": off})
    part = Group(slab_mesh(d), name="Solaio")
    part.component = False
    g = Group(name=name)
    g.adopt([part])
    g.component = False
    g.layer = LAYER_NAME
    bim.tag_group(g, "IfcSlab", name)
    g.ext = {KEY: d}
    scene.groups.append(g)


# ---------------------------------------------------------------------------
# Rilevamento automatico della stanza
# ---------------------------------------------------------------------------

def _wall_polygon_world(group):
    """Pianta del muro (4 angoli) in coordinate mondo."""
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
    """Contorno interno (lista di punti) della stanza chiusa che contiene
    (x, y), oppure None. Con level_id usa solo i muri di quel piano.
    Solleva ImportError se manca shapely."""
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
        polys.append(p.buffer(GAP_TOL, join_style=2))   # chiude le fessure
    if not polys:
        return None
    union = unary_union(polys)
    pt = Point(x, y)
    geoms = getattr(union, "geoms", [union])
    for poly in geoms:
        for ring in poly.interiors:
            room = Polygon(ring)
            if room.contains(pt):
                room = room.buffer(GAP_TOL, join_style=2)  # annulla l'offset
                room = room.simplify(0.001)
                return list(room.exterior.coords)[:-1]
    return None


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
    from . import piani
    dlg = QDialog(parent)
    dlg.setWindowTitle("Solaio")
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    thick = _spin(_Settings.thickness, 0.02, 5.0)
    z = _spin(_Settings.z_top, -100.0, 1000.0)
    name = QLineEdit(_Settings.name)
    auto = QCheckBox("Automatico: clic dentro una stanza chiusa da muri")
    auto.setChecked(_Settings.auto)
    level = None
    if scene is not None and piani.levels(scene):
        level = piani.level_combo(scene, piani.active_id(scene))
        form.addRow("Piano", level)
    form.addRow("Spessore (m)", thick)
    form.addRow("Faccia superiore: sopra la quota del piano / da terra (m)", z)
    form.addRow("Nome", name)
    form.addRow(auto)
    lay.addLayout(form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return False
    _Settings.thickness = thick.value()
    _Settings.z_top = z.value()
    _Settings.name = name.text().strip() or "Solaio"
    _Settings.auto = auto.isChecked()
    if level is not None:
        _Settings.level = level.currentData() or None
        piani.set_active(_Settings.level)
    else:
        _Settings.level = None
    return True


def _ortho(points, p):
    """Con l'ortogonale dei muri attivo, il punto cade sull'asse X o Y del
    punto precedente (quello dominante)."""
    if not (muri._Settings.ortho and points):
        return p
    last = points[-1]
    if abs(p.x() - last.x()) >= abs(p.y() - last.y()):
        return QVector3D(p.x(), last.y(), p.z())
    return QVector3D(last.x(), p.y(), p.z())


def _spline_closed(pts):
    """Curva chiusa (Catmull-Rom centripeta) che passa per i punti (x, y):
    ritorna il contorno come poligono con molti lati."""
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
        "Ortogonale " + ("attivo" if muri._Settings.ortho else "disattivato"),
        2000)
    viewport.update()


# ---------------------------------------------------------------------------
# Strumento
# ---------------------------------------------------------------------------

class SolaioTool(Tool):
    name = "Solaio"
    shortcut = None
    description = "Crea un solaio: automatico (clic in una stanza) o a punti."

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
                "Solaio: clic dentro una stanza chiusa da muri"
                if _Settings.auto else
                "Solaio: clic per i vertici · S = spline · C/Invio = crea · "
                "Esc = esci",
                6000)
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

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        p = QVector3D(ctx.world)
        if _Settings.auto:
            try:
                poly = find_room(vp.scene, p.x(), p.y(), _Settings.level)
            except ImportError:
                vp.flash_status("Serve shapely: pip install shapely", 6000)
                return
            if poly is None:
                vp.flash_status(
                    "Nessuna stanza chiusa qui: controlla che i muri si "
                    "chiudano (o usa il modo manuale)", 5000)
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

    def context_menu(self, viewport, pos) -> bool:
        self._exit(viewport)
        return True

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if key == Qt.Key_S and not _Settings.auto:
            _Settings.spline = not _Settings.spline
            viewport.flash_status(
                "Spline attiva: i punti guidano una curva chiusa"
                if _Settings.spline else "Spline disattivata", 3000)
            viewport.update()
            return True
        if key in (Qt.Key_O, Qt.Key_F8) and not (
                _Settings.auto and key == Qt.Key_O):
            _toggle_ortho(self, viewport)
            return True
        if _Settings.auto:
            return False
        if key in (Qt.Key_C, Qt.Key_Return, Qt.Key_Enter) and self.points:
            pts = muri._dedupe([(p.x(), p.y()) for p in self.points], True)
            if len(pts) < 3:
                viewport.flash_status("Servono almeno 3 vertici", 3000)
            else:
                if _Settings.spline:
                    pts = muri._dedupe(_spline_closed(pts), True)
                self._commit(viewport, pts)
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
        """Quota assoluta della faccia superiore (piano + distanza)."""
        from . import piani
        sc = scene if scene is not None else getattr(self, "_scene", None)
        lv = piani.get(sc, _Settings.level) if sc is not None else None
        return (lv["z"] if lv else 0.0) + _Settings.z_top

    def _commit(self, viewport, poly) -> None:
        if getattr(viewport.scene, "edit_group", None) is not None:
            viewport.flash_status("Chiudi il gruppo che stai modificando", 4000)
            return
        from . import piani
        t, name = _Settings.thickness, _Settings.name
        lvl = piani.get(viewport.scene, _Settings.level)
        z = self._top_z(viewport.scene)
        off = _Settings.z_top

        def mutate(scene):
            build_slab(scene, poly, t, z, name, lvl, off)

        viewport.history.execute(muri.MuriCommand(mutate))
        viewport.notify_scene_changed()
        viewport.flash_status("Solaio creato", 3000)
        self._reset()
        viewport.update()


# ---------------------------------------------------------------------------
# Strumento Foro (aperture nel solaio)
# ---------------------------------------------------------------------------

def _slab_at(scene, pts, only=None):
    """Primo solaio il cui contorno contiene tutti i punti, o None.
    only = contorno di un solaio preciso (da "Fora solaio")."""
    for g in scene.groups:
        d = slab_data(g)
        if only is not None and (d is None or d["poly"] != only):
            continue
        if d and all(_in_poly(p, d["poly"]) for p in pts):
            return d
    return None


class ForoSolaioTool(Tool):
    name = "Foro solaio"
    shortcut = None
    description = ("Fora un solaio: clic per i vertici del foro dentro il "
                   "solaio, C/Invio = crea, Esc = esci.")

    def __init__(self) -> None:
        self._entering = False
        self._reset()

    def _reset(self) -> None:
        self.points: list[QVector3D] = []
        self.hover_point: QVector3D | None = None
        self._z = 0.0

    _target = None

    def start(self, viewport, poly) -> None:
        """Avvia il foro su UN solaio (dal pannello di modifica)."""
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
            "Foro: clic per i vertici dentro il solaio · C/Invio = crea "
            "· Backspace = annulla punto · Esc = esci", 6000)

    def on_deactivate(self, viewport) -> None:
        self._reset()
        self._target = None

    def on_click(self, ctx: ToolContext) -> None:
        p = QVector3D(ctx.world)
        if not self.points:
            d = _slab_at(ctx.viewport.scene, [(p.x(), p.y())], self._target)
            if d is None:
                ctx.viewport.flash_status("Clicca dentro un solaio", 3000)
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
                viewport.flash_status("Servono almeno 3 vertici", 3000)
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
            viewport.flash_status("Chiudi il gruppo che stai modificando", 4000)
            return
        target = _slab_at(viewport.scene, hole, self._target)
        if target is None:
            viewport.flash_status(
                "Il foro deve stare tutto dentro un solaio", 4000)
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
        viewport.flash_status("Foro creato (Ctrl+Z per annullare)", 3000)
        self._reset()
        viewport.update()
        if self._target is not None:
            self._exit(viewport)


# ---------------------------------------------------------------------------
# Modifica solaio (tasto destro > Modifica solaio…)
# ---------------------------------------------------------------------------

_FORO = ForoSolaioTool()
_EDIT = {"dlg": None}


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
        viewport.flash_status("Seleziona un solaio", 3000)
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
    viewport.flash_status("Materiale applicato", 3000)


def edit_slab(viewport) -> None:
    from . import piani
    scene = viewport.scene
    sel = _selected_slabs(scene)
    if len(sel) != 1:
        viewport.flash_status("Seleziona un solaio", 3000)
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
    dlg.setWindowTitle("Modifica solaio")
    dlg.setAttribute(Qt.WA_DeleteOnClose, True)
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    name = QLineEdit(getattr(g, "name", "") or "Solaio")
    thick = _spin(d["th"], 0.02, 5.0)
    z = _spin(d.get("off", d["z"]) if has_lv else d["z"], -100.0, 1000.0)
    form.addRow("Nome", name)
    form.addRow("Spessore (m)", thick)
    form.addRow("Faccia superiore: sopra il piano (m)" if has_lv
                else "Faccia superiore: da terra (m)", z)
    lay.addLayout(form)
    n_holes = len(d.get("holes", []))
    info = QLabel(f"Fori: {n_holes}")
    lay.addWidget(info)

    def find(sc):
        for gg in sc.groups:
            dd = slab_data(gg)
            if dd is not None and dd["poly"] == key:
                return gg, dd
        return None, None

    def change(fn, msg) -> None:
        def mutate(sc):
            gg, dd = find(sc)
            if gg is None:
                return
            nd = copy.deepcopy(dd)
            fn(sc, gg, nd)
            rebuild_slab(gg, nd)

        viewport.history.execute(muri.MuriCommand(mutate))
        viewport.notify_scene_changed()
        viewport.update()
        viewport.flash_status(msg, 3000)

    def apply() -> None:
        def fn(sc, gg, nd):
            nd["th"] = thick.value()
            if nd.get("lv") and piani.get(sc, nd["lv"]):
                nd["off"] = z.value()
                nd["z"] = piani.get(sc, nd["lv"])["z"] + z.value()
            else:
                nd["z"] = z.value()
            gg.name = name.text().strip() or "Solaio"

        change(fn, "Solaio modificato")

    def drill() -> None:
        dlg.close()
        _FORO.start(viewport, key)

    def clear() -> None:
        def fn(sc, gg, nd):
            nd.pop("holes", None)

        change(fn, "Fori rimossi")
        info.setText("Fori: 0")

    b_drill = QPushButton("Fora solaio")
    b_drill.clicked.connect(drill)
    lay.addWidget(b_drill)
    if n_holes:
        b_clear = QPushButton("Rimuovi tutti i fori")
        b_clear.clicked.connect(clear)
        lay.addWidget(b_clear)
    box = QDialogButtonBox()
    b_apply = box.addButton("Applica", QDialogButtonBox.AcceptRole)
    b_close = box.addButton("Chiudi", QDialogButtonBox.RejectRole)
    b_apply.clicked.connect(apply)
    b_close.clicked.connect(dlg.close)
    lay.addWidget(box)
    _EDIT["dlg"] = dlg
    dlg.show()


# ---------------------------------------------------------------------------
# Registrazione
# ---------------------------------------------------------------------------

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
        return None
    from core.units import fmt_len
    from . import piani
    return {"type": "Solaio",
            "props": [("Spessore", fmt_len(d["th"])),
                      ("Altezza da terra", fmt_len(d["z"]))]
            + piani.level_props(d)}


def _register_level_kind() -> None:
    from . import piani

    def zset(d, z):
        d["z"] = z

    piani.register_kind("solaio", KEY, slab_data, lambda d: d["z"], zset,
                        rebuild_slab)


def register(api) -> None:
    _APP["app"] = api.app
    _register_level_kind()
    api.add_button("Solaio", "Crea un solaio (automatico in una stanza)",
                   _icon(), api.run_tool(SolaioTool()))
    add_ctx = getattr(api.app, "add_context_menu", None)
    if add_ctx is not None:
        def context(menu, selection) -> None:
            n = len(_selected_slabs(api.app.viewport.scene))
            if n == 0:
                return
            menu.addSeparator()
            if n == 1:
                menu.addAction(
                    "Modifica solaio…",
                    lambda: QTimer.singleShot(
                        0, lambda: edit_slab(api.app.viewport)))
            menu.addAction(
                "Materiale solaio…",
                lambda: QTimer.singleShot(
                    0, lambda: set_slab_material(api.app.viewport)))

        add_ctx(context)
    add_kind = getattr(api.app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
