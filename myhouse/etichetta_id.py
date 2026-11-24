# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QVector3D
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel,
    QVBoxLayout,
)

from tools.base import Tool, ToolContext

from . import _codici, muri

ORDER = 97
LAYER_NAME = "Etichette ID"
KEY = "mh_etichetta_id"
FILL = (1.0, 1.0, 1.0)
INK = (0.0, 0.0, 0.0)
OFF_INK = 0.002

FONT_FAMILIES = ("Arial", "Segoe UI", "Helvetica", "DejaVu Sans")
_cache = {}


def _font():
    from PySide6.QtGui import QFont
    f = QFont()
    for fam in FONT_FAMILIES:
        f.setFamily(fam)
        if f.exactMatch() or fam == FONT_FAMILIES[-1]:
            break
    f.setPixelSize(200)
    f.setBold(False)
    return f


FLAT = 0.25        # curve meno fitte (appiattimento piu' grossolano)
SIMPLIFY = 0.012   # tolleranza = 1.2% dell'altezza del testo


def _rdp(pts, tol):
    if len(pts) < 3:
        return pts
    (x0, y0), (x1, y1) = pts[0], pts[-1]
    dx, dy = x1 - x0, y1 - y0
    n = math.hypot(dx, dy)
    best, idx = -1.0, 0
    for i in range(1, len(pts) - 1):
        x, y = pts[i]
        d = (abs(dy * (x - x0) - dx * (y - y0)) / n if n > 1e-12
             else math.hypot(x - x0, y - y0))
        if d > best:
            best, idx = d, i
    if best <= tol:
        return [pts[0], pts[-1]]
    return _rdp(pts[:idx + 1], tol)[:-1] + _rdp(pts[idx:], tol)


def _simplify(pts, tol):
    if len(pts) < 8 or tol <= 0:
        return pts
    far = max(range(len(pts)),
              key=lambda i: math.hypot(pts[i][0] - pts[0][0],
                                       pts[i][1] - pts[0][1]))
    a = _rdp(pts[:far + 1], tol)
    b = _rdp(pts[far:] + [pts[0]], tol)
    out = a[:-1] + b[:-1]
    return out if len(out) >= 3 else pts


def _area(poly) -> float:
    return sum(poly[i][0] * poly[(i + 1) % len(poly)][1]
               - poly[(i + 1) % len(poly)][0] * poly[i][1]
               for i in range(len(poly))) / 2.0


def _inside(pt, poly) -> bool:
    x, y = pt
    r = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            r = not r
        j = i
    return r


def text_shape(txt: str, h: float):
    key = (txt, round(h, 6))
    if key in _cache:
        return _cache[key]
    from PySide6.QtGui import QPainterPath, QTransform
    font = _font()
    cap = QPainterPath()
    cap.addText(0, 0, font, "H")
    ch = cap.boundingRect().height() or 1.0
    s = h / ch
    path = QPainterPath()
    path.addText(0, 0, font, txt)
    br = path.boundingRect()
    if br.isEmpty():
        res = (0.0, [])
    else:
        cx, cy = br.center().x(), br.center().y()
        polys = []
        for sp in path.toSubpathPolygons(QTransform().scale(FLAT, FLAT)):
            pts = [((p.x() / FLAT - cx) * s, -(p.y() / FLAT - cy) * s)
                   for p in sp]
            if len(pts) > 1 and pts[0] == pts[-1]:
                pts.pop()
            pts = _simplify(pts, h * SIMPLIFY)
            if len(pts) >= 3 and abs(_area(pts)) > 1e-12:
                polys.append(pts)
        shapes = []
        depth = []
        for i, p in enumerate(polys):
            depth.append(sum(1 for j, q in enumerate(polys)
                             if j != i and _inside(p[0], q)))
        for i, p in enumerate(polys):
            if depth[i] % 2 == 0:
                outer = p if _area(p) > 0 else p[::-1]
                shapes.append((i, outer, []))
        for i, p in enumerate(polys):
            if depth[i] % 2 == 1:
                hole = p if _area(p) < 0 else p[::-1]
                cands = [sh for sh in shapes if _inside(p[0], sh[1])]
                if cands:
                    min(cands, key=lambda sh: abs(_area(sh[1])))[2].append(hole)
        res = (br.width() * s, [(o, hs) for _i, o, hs in shapes])
    _cache[key] = res
    return res


def label_segments(code: str, size: float, center, anchor):
    pad = 0.5 * size
    tw, _shapes = text_shape(code, size)
    w, h = tw + 2 * pad, size + 2 * pad
    cx, cy = center
    x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    segs = [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)),
            ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]
    ax, ay = anchor
    sides = [((cx, y1), 0), ((cx, y0), 1), ((x0, cy), 2), ((x1, cy), 3)]
    best = min(sides, key=lambda s: math.hypot(s[0][0] - ax, s[0][1] - ay))
    segs.append(((ax, ay), best[0]))
    return (x0, y0, x1, y1), segs


def text_edges(code: str, size: float, center):
    _w, shapes = text_shape(code, size)
    out = []
    for outer, holes in shapes:
        for poly in [outer] + holes:
            for i in range(len(poly)):
                a, b = poly[i], poly[(i + 1) % len(poly)]
                out.append(((center[0] + a[0], center[1] + a[1]),
                            (center[0] + b[0], center[1] + b[1])))
    return out


def label_mesh(code: str, size: float, center, anchor, z: float):
    from core.mesh import Mesh
    rect, segs = label_segments(code, size, center, anchor)
    mesh = Mesh()
    P = QVector3D
    x0, y0, x1, y1 = rect
    f = mesh.add_face([P(x0, y0, z), P(x1, y0, z), P(x1, y1, z), P(x0, y1, z)])
    f.attrs["color"] = FILL
    f.attrs["mat"] = tr("etichetta ID fondo")
    f.attrs["layer"] = LAYER_NAME
    zz = z + OFF_INK
    w = max(size * 0.06, 0.003)
    for (ax, ay), (bx, by) in segs:
        dx, dy = bx - ax, by - ay
        ll = math.hypot(dx, dy)
        if ll < 1e-9:
            continue
        nx, ny = -dy / ll * w / 2, dx / ll * w / 2
        ex, ey = dx / ll * w / 2, dy / ll * w / 2
        a2, b2 = (ax - ex, ay - ey), (bx + ex, by + ey)
        f = mesh.add_face([P(a2[0] - nx, a2[1] - ny, zz),
                           P(b2[0] - nx, b2[1] - ny, zz),
                           P(b2[0] + nx, b2[1] + ny, zz),
                           P(a2[0] + nx, a2[1] + ny, zz)])
        f.attrs["color"] = INK
        f.attrs["mat"] = tr("etichetta ID tratti")
        f.attrs["layer"] = LAYER_NAME
    _w, shapes = text_shape(code, size)
    for outer, holes in shapes:
        ring = [P(center[0] + x, center[1] + y, zz) for x, y in outer]
        hs = [[P(center[0] + x, center[1] + y, zz) for x, y in h] for h in holes]
        try:
            f = mesh.add_face(ring, hs) if hs else mesh.add_face(ring)
        except Exception:
            f = mesh.add_face(ring)
        f.attrs["color"] = INK
        f.attrs["mat"] = tr("etichetta ID tratti")
        f.attrs["layer"] = LAYER_NAME
    return mesh


def build_label(scene, code, size, center, anchor, z):
    from core.group import Group
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    part = Group(label_mesh(code, size, center, anchor, z),
                 name=tr("Etichetta ID"))
    part.component = False
    g = Group(name=tr("Etichetta {0}").format(code))
    g.adopt([part])
    g.component = False
    g.layer = LAYER_NAME
    g.ext = {KEY: {"code": code, "size": size, "c": list(center),
                   "a": list(anchor), "z": z}}
    scene.groups.append(g)
    return g


def _bbox(g):
    from .sezione_strati import _kid_tris
    lo = [1e18, 1e18, 1e18]
    hi = [-1e18, -1e18, -1e18]
    for kid in getattr(g, "children", None) or ():
        try:
            tris, _c = _kid_tris(g, kid)
        except Exception:
            continue
        for t in tris:
            for p in t:
                for i in range(3):
                    lo[i] = min(lo[i], p[i])
                    hi[i] = max(hi[i], p[i])
    return (lo, hi) if lo[0] < 1e17 else None


def selected_targets(scene):
    try:
        _codici.assign_missing(scene)
    except Exception:
        pass
    out, seen = [], []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g not in scene.groups or g in seen:
            continue
        cat = _codici.category(g)
        if cat is None:
            continue
        code = _codici.code_of(g, cat)
        bb = _bbox(g)
        if not code or bb is None:
            continue
        seen.append(g)
        lo, hi = bb
        out.append((code, ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2), hi[2]))
    out.sort(key=lambda t: t[0])
    return out


SNAP_PX = 14.0


def _cfg_file():
    import os
    from . import _tipi
    f = _tipi._file()
    return os.path.join(os.path.dirname(f), "etichetta_id.json") if f else None


def default_size() -> float:
    import json
    try:
        with open(_cfg_file(), "r", encoding="utf-8") as fh:
            return max(0.01, float(json.load(fh).get("size", 0.20)))
    except Exception:
        return 0.20


def _save_default(size: float) -> None:
    import json
    try:
        with open(_cfg_file(), "w", encoding="utf-8") as fh:
            json.dump({"size": size}, fh)
    except Exception:
        pass


def label_groups(scene):
    return [g for g in scene.groups
            if isinstance(getattr(g, "ext", None), dict) and KEY in g.ext]


def current_size(scene) -> float:
    for g in label_groups(scene):
        try:
            return max(0.01, float(g.ext[KEY]["size"]))
        except Exception:
            pass
    return default_size()


def set_size_all(viewport, size: float) -> int:
    from core.group import Group
    size = max(0.01, float(size))
    _save_default(size)
    res = {"n": 0}

    def mutate(sc):
        for g in label_groups(sc):
            d = dict(g.ext[KEY])
            d["size"] = size
            part = Group(label_mesh(d["code"], size, d["c"], d["a"], d["z"]),
                         name=tr("Etichetta ID"))
            part.component = False
            g.children = [part]
            ext = dict(g.ext)
            ext[KEY] = d
            g.ext = ext
            res["n"] += 1

    if label_groups(viewport.scene):
        viewport.history.execute(muri.MuriCommand(mutate))
        viewport.notify_scene_changed()
        viewport.update()
    return res["n"]


def _snap(vp, c, a, z):
    cx, cy = c
    try:
        pc = vp._world_to_pixel(QVector3D(cx, cy, z))
        px = vp._world_to_pixel(QVector3D(a[0], cy, z))
        py = vp._world_to_pixel(QVector3D(cx, a[1], z))
        if pc is not None and px is not None and abs(pc[0] - px[0]) < SNAP_PX \
                and abs(pc[1] - px[1]) < SNAP_PX * 4:
            cx = a[0]
        if pc is not None and py is not None and abs(pc[1] - py[1]) < SNAP_PX \
                and abs(pc[0] - py[0]) < SNAP_PX * 4:
            cy = a[1]
    except Exception:
        pass
    return (cx, cy)


class EtichettaIdTool(Tool):
    name = tr("Etichetta ID")
    shortcut = None
    description = tr("Mette il codice ID degli elementi selezionati in un "
                     "rettangolino con linea: clic = posiziona.")

    def __init__(self) -> None:
        self._entering = False
        self.hover = None
        self.targets = []
        self.size = 0.20

    def on_activate(self, viewport) -> None:
        self._vp = viewport
        if self._entering:
            self.hover = None
            return
        self.targets = selected_targets(viewport.scene)
        if not self.targets:
            viewport.flash_status(
                tr("Seleziona uno o più elementi con codice ID, poi premi "
                   "Etichetta ID"), 5000)
            return
        self.size = current_size(viewport.scene)
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False
        viewport.flash_status(
            tr("Etichetta ID: clic = posiziona (la linea scatta in orizzontale "
               "e verticale) · dimensione testo nel pannello Codici ID · "
               "tasto destro o Esc = esci"), 7000)

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

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover = (ctx.world.x(), ctx.world.y())
        ctx.viewport.update()

    def _centers(self, vp, p):
        out = []
        for i, (_code, anchor, ztop) in enumerate(self.targets):
            c = (p[0], p[1] - i * self.size * 2.8)
            out.append(_snap(vp, c, anchor, ztop + 0.01))
        return out

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        if getattr(vp.scene, "edit_group", None) is not None:
            vp.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        p = (ctx.world.x(), ctx.world.y())
        size = self.size
        items = list(zip(self.targets, self._centers(vp, p)))

        def mutate(scene):
            for (code, anchor, ztop), c in items:
                build_label(scene, code, size, c, anchor, ztop + 0.01)

        vp.history.execute(muri.MuriCommand(mutate))
        vp.notify_scene_changed()
        vp.flash_status(tr("Etichetta ID inserita"), 3000)
        vp.update()

    def rubber_band_lines(self):
        if self.hover is None:
            return []
        out = []
        for (code, anchor, ztop), c in zip(
                self.targets, self._centers(self._vp, self.hover)):
            _r, segs = label_segments(code, self.size, c, anchor)
            segs = segs + text_edges(code, self.size, c)
            z = ztop + 0.012
            for a, b in segs:
                out.append((QVector3D(a[0], a[1], z), QVector3D(b[0], b[1], z)))
        return out

    def draw_overlay(self, viewport, painter) -> None:
        pass


def _icon():
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.drawLine(6, 40, 20, 26)
    p.setBrush(QColor(255, 255, 255))
    p.drawRect(18, 8, 26, 18)
    p.setPen(QPen(QColor(0, 0, 0), 2))
    p.drawText(18, 8, 26, 18, Qt.AlignCenter, "ID")
    p.end()
    return QIcon(pm)


def register(api) -> None:
    api.add_button(tr("Etichetta ID"),
                   tr("Scrive il codice ID dell'elemento selezionato in un "
                      "rettangolino con linea"),
                   _icon(), api.run_tool(EtichettaIdTool()), group="Piani")
