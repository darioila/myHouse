# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr
from ._imperial import LengthSpin
from ._scroll import scroll_form

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPen, QVector3D
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QLineEdit, QSpinBox, QVBoxLayout,
)

from tools.base import Tool, ToolContext

from . import muri, piani

ORDER = 42
KEY = "myhouse_griglia"
LAYER_NAME = "Griglie"
LINE_COLOR = (0.12, 0.12, 0.12)
MAT_NAME = tr("materiale griglia")
Z_LIFT = 0.002
MODES = [("hl", tr("Orizzontali = lettere · Verticali = numeri")),
         ("hn", tr("Orizzontali = numeri · Verticali = lettere"))]


class _Settings:
    size = 0.30
    mode = "hl"
    first_letter = "A"
    first_number = 1
    li = 0
    ni = 1
    level = None
    ts = None
    rs = None


def _letters(i: int) -> str:
    s = ""
    i += 1
    while i > 0:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _letter_index(text: str) -> int:
    n = 0
    for ch in (text or "").upper():
        if "A" <= ch <= "Z":
            n = n * 26 + ord(ch) - 64
    return max(0, n - 1)


def _take_label(horizontal: bool) -> str:
    if horizontal == (_Settings.mode == "hl"):
        lab = _letters(_Settings.li)
        _Settings.li += 1
    else:
        lab = str(_Settings.ni)
        _Settings.ni += 1
    return lab


def _ortho(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    if abs(dy) <= abs(dx) * 0.08:
        dy = 0.0
    elif abs(dx) <= abs(dy) * 0.08:
        dx = 0.0
    return (a[0] + dx, a[1] + dy)


def _quad(a, b, w, z):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy)
    if L < 1e-9:
        return None
    nx, ny = -dy / L * w / 2, dx / L * w / 2
    P = QVector3D
    return [P(a[0] - nx, a[1] - ny, z), P(b[0] - nx, b[1] - ny, z),
            P(b[0] + nx, b[1] + ny, z), P(a[0] + nx, a[1] + ny, z)]


def _dash_ranges(L, size):
    pat = [(size * 1.6, True), (size * 0.25, False),
           (size * 0.12, True), (size * 0.25, False)]
    out = []
    t = 0.0
    i = 0
    while t < L - 1e-9:
        ln, on = pat[i % 4]
        e = min(L, t + ln)
        if on:
            out.append((t, e))
        t = e
        i += 1
    return out


def _arc(cx, cy, rx, ry, a0, a1, n=14):
    return [(cx + rx * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             cy + ry * math.sin(math.radians(a0 + (a1 - a0) * i / n)))
            for i in range(n + 1)]


def _ell(cx, cy, rx, ry):
    return _arc(cx, cy, rx, ry, 0, 360, 20)


def _flip(strokes):
    return [[(0.6 - x, 1.0 - y) for x, y in st] for st in strokes]


_SIX = [_ell(.3, .33, .3, .33), _arc(.3, .5, .3, .5, 180, 55)]
_P = [[(0, 0), (0, 1), (.35, 1)] + _arc(.35, .74, .25, .26, 90, -90)
      + [(.35, .48), (0, .48)]]

# Font propria a tratti: (tratti, larghezza). Box: x 0..larghezza, y 0..1.
_FONT = {
    "0": ([_ell(.3, .5, .3, .5)], .6),
    "1": ([[(.05, .78), (.3, 1), (.3, 0)]], .4),
    "2": ([_arc(.3, .72, .28, .28, 160, -35) + [(0, 0), (.6, 0)]], .6),
    "3": ([_arc(.28, .75, .27, .25, 150, -90),
           _arc(.28, .25, .3, .25, 90, -150)], .6),
    "4": ([[(.45, 0), (.45, 1), (0, .3), (.6, .3)]], .6),
    "5": ([[(.55, 1), (.1, 1), (.05, .55)] + _arc(.3, .33, .3, .33, 115, -150)],
          .6),
    "6": (_SIX, .6),
    "7": ([[(0, 1), (.6, 1), (.2, 0)]], .6),
    "8": ([_ell(.3, .75, .26, .25), _ell(.3, .25, .3, .25)], .6),
    "9": (_flip(_SIX), .6),
    "A": ([[(0, 0), (.3, 1), (.6, 0)], [(.12, .35), (.48, .35)]], .6),
    "B": ([[(0, 0), (0, 1)],
           [(0, 1), (.35, 1)] + _arc(.35, .75, .2, .25, 90, -90)
           + [(.35, .5), (0, .5)],
           [(0, .5), (.38, .5)] + _arc(.38, .25, .22, .25, 90, -90)
           + [(.38, 0), (0, 0)]], .6),
    "C": ([_arc(.32, .5, .3, .5, 45, 315)], .62),
    "D": ([[(0, 0), (0, 1), (.25, 1)] + _arc(.25, .5, .35, .5, 90, -90)
           + [(.25, 0), (0, 0)]], .6),
    "E": ([[(.6, 1), (0, 1), (0, 0), (.6, 0)], [(0, .5), (.45, .5)]], .6),
    "F": ([[(.6, 1), (0, 1), (0, 0)], [(0, .5), (.45, .5)]], .6),
    "G": ([_arc(.32, .5, .3, .5, 45, 330) + [(.58, .45), (.35, .45)]], .62),
    "H": ([[(0, 0), (0, 1)], [(.6, 0), (.6, 1)], [(0, .5), (.6, .5)]], .6),
    "I": ([[(0, 0), (0, 1)]], 0.0),
    "J": ([[(.5, 1), (.5, .3)] + _arc(.25, .3, .25, .3, 0, -180)], .5),
    "K": ([[(0, 0), (0, 1)], [(.6, 1), (0, .4)], [(.15, .55), (.6, 0)]], .6),
    "L": ([[(0, 1), (0, 0), (.55, 0)]], .55),
    "M": ([[(0, 0), (0, 1), (.35, .4), (.7, 1), (.7, 0)]], .7),
    "N": ([[(0, 0), (0, 1), (.6, 0), (.6, 1)]], .6),
    "O": ([_ell(.3, .5, .3, .5)], .6),
    "P": (_P, .6),
    "Q": ([_ell(.3, .5, .3, .5), [(.38, .25), (.65, -.05)]], .6),
    "R": (_P + [[(.25, .48), (.6, 0)]], .6),
    "S": ([_arc(.3, .75, .28, .25, 20, 270) + _arc(.3, .25, .3, .25, 90, -160)],
          .6),
    "T": ([[(0, 1), (.6, 1)], [(.3, 1), (.3, 0)]], .6),
    "U": ([[(0, 1), (0, .3)] + _arc(.3, .3, .3, .3, 180, 360)
           + [(.6, .3), (.6, 1)]], .6),
    "V": ([[(0, 1), (.3, 0), (.6, 1)]], .6),
    "W": ([[(0, 1), (.15, 0), (.35, .6), (.55, 0), (.7, 1)]], .7),
    "X": ([[(0, 0), (.6, 1)], [(0, 1), (.6, 0)]], .6),
    "Y": ([[(0, 1), (.3, .5), (.6, 1)], [(.3, .5), (.3, 0)]], .6),
    "Z": ([[(0, 1), (.6, 1), (0, 0), (.6, 0)]], .6),
    "-": ([[(0, .5), (.4, .5)]], .4),
    ".": ([[(0, 0), (0, .02)]], 0.0),
    "/": ([[(0, 0), (.4, 1)]], .4),
}
_GAP = 0.22


def text_size_of(d) -> float:
    return float(d.get("ts") or d["size"])


def _text_width(label, ts) -> float:
    ws = [_FONT.get(c, ([], .4))[1] for c in str(label).upper()]
    return (sum(ws) + _GAP * max(0, len(ws) - 1)) * ts


def _layout(d):
    size = text_size_of(d)
    if d.get("rs"):
        r = float(d["rs"]) / 2
    else:
        r = max(size * 0.75, math.hypot(_text_width(d["label"], size), size)
                / 2 * 1.25)
    p1, p2 = d["p1"], d["p2"]
    L = math.hypot(p2[0] - p1[0], p2[1] - p1[1]) or 1.0
    ux, uy = (p2[0] - p1[0]) / L, (p2[1] - p1[1]) / L
    return r, (p2[0] + ux * r, p2[1] + uy * r)


def _text_faces(d, bx, by, z, face) -> None:
    ts = text_size_of(d)
    lw = max(0.002, ts * 0.11)
    label = str(d["label"]).upper()
    x = bx - _text_width(label, ts) / 2
    y0 = by - ts / 2
    for ch in label:
        strokes, w = _FONT.get(ch, ([], .4))
        for st in strokes:
            pts = [(x + px * ts, y0 + py * ts) for px, py in st]
            for a, b in zip(pts, pts[1:]):
                L = math.hypot(b[0] - a[0], b[1] - a[1])
                if L < 1e-9:
                    continue
                e = lw / 2
                ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
                q = _quad((a[0] - ux * e, a[1] - uy * e),
                          (b[0] + ux * e, b[1] + uy * e), lw, z)
                if q:
                    face(q)
        x += (w + _GAP) * ts


def grid_mesh(d):
    from core.mesh import Mesh
    mesh = Mesh()
    z = d["z"]
    size = d["size"]
    lw = max(0.002, size * 0.05)
    P = QVector3D

    def face(q):
        f = mesh.add_face(q)
        f.attrs["color"] = LINE_COLOR
        f.attrs["mat"] = MAT_NAME
        f.attrs["layer"] = LAYER_NAME

    p1, p2 = d["p1"], d["p2"]
    L = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    if L > 1e-9:
        ux, uy = (p2[0] - p1[0]) / L, (p2[1] - p1[1]) / L
        for t0, t1 in _dash_ranges(L, size):
            q = _quad((p1[0] + ux * t0, p1[1] + uy * t0),
                      (p1[0] + ux * t1, p1[1] + uy * t1), lw, z)
            if q:
                face(q)
    r, (bx, by) = _layout(d)
    _text_faces(d, bx, by, z + 0.001, face)
    n = 40
    ri, ro = r - lw / 2, r + lw / 2
    for i in range(n):
        a0 = 2 * math.pi * i / n
        a1 = 2 * math.pi * (i + 1) / n
        c0, s0, c1, s1 = math.cos(a0), math.sin(a0), math.cos(a1), math.sin(a1)
        face([P(bx + ri * c0, by + ri * s0, z), P(bx + ro * c0, by + ro * s0, z),
              P(bx + ro * c1, by + ro * s1, z), P(bx + ri * c1, by + ri * s1, z)])
    return mesh


def grid_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "p1" in data else None


def build_grid(scene, d) -> None:
    from core.group import Group
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    r, bc = _layout(d)
    d["r"] = r
    d["bc"] = list(bc)
    d["tx"] = 1
    child = Group(grid_mesh(d), name=tr("Griglia"))
    child.component = False
    g = Group(name=d["name"])
    g.adopt([child])
    g.component = False
    g.layer = LAYER_NAME
    g.ext = {KEY: d}
    scene.groups.append(g)
    sync_grid_labels(scene)


def sync_grid_labels(scene) -> bool:
    n = len(scene.text_labels)
    scene.text_labels[:] = [t for t in scene.text_labels
                            if getattr(t, "layer", None) != LAYER_NAME]
    return len(scene.text_labels) != n


def rebuild_grid(group, d) -> None:
    from core.group import Group
    r, bc = _layout(d)
    d["r"] = r
    d["bc"] = list(bc)
    child = Group(grid_mesh(d), name=tr("Griglia"))
    child.component = False
    group.children = [child]
    group.name = d["name"]
    ext = dict(group.ext or {})
    ext[KEY] = d
    group.ext = ext


def _is_h(d) -> bool:
    return abs(d["p2"][0] - d["p1"][0]) >= abs(d["p2"][1] - d["p1"][1])


ALIGN_TOL = 0.4


def _align(scene, pt, horizontal=None):
    x, y = pt[0], pt[1]
    bx, gx = ALIGN_TOL, None
    by, gy = ALIGN_TOL, None
    for _g, d in grids(scene):
        h = _is_h(d)
        for e in (d["p1"], d["p2"]):
            if h and horizontal is not False and abs(e[0] - pt[0]) < bx:
                bx, gx = abs(e[0] - pt[0]), e
            if not h and horizontal is not True and abs(e[1] - pt[1]) < by:
                by, gy = abs(e[1] - pt[1]), e
    guides = []
    if gx is not None:
        x = gx[0]
    if gy is not None:
        y = gy[1]
    if gx is not None:
        guides.append(((gx[0], gx[1]), (x, y)))
    if gy is not None:
        guides.append(((gy[0], gy[1]), (x, y)))
    return (x, y), guides


def grids(scene):
    out = []
    for g in scene.groups:
        d = grid_data(g)
        if d is not None:
            out.append((g, d))
    return out


def selected_grids(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and grid_data(g) is not None and g not in out:
            out.append(g)
    return out


def edit_grids(viewport, groups=None) -> None:
    from PySide6.QtWidgets import QLabel
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    groups = [g for g in (groups or selected_grids(scene))
              if grid_data(g) is not None]
    if not groups:
        viewport.flash_status(tr("Seleziona una linea di griglia"), 3000)
        return
    first = grid_data(groups[0])
    single = len(groups) == 1
    dlg = QDialog(viewport.window())
    dlg.setWindowTitle(tr("Modifica griglia") if single
                       else tr("Modifica {0} griglie").format(len(groups)))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    label = QLineEdit(str(first["label"]))
    label.setMaxLength(6)
    label.setEnabled(single)
    ts = _spin(text_size_of(first), 0.01, 10.0)
    rs = _spin(float(first.get("rs") or 0.0), 0.0, 20.0)
    rs.setSpecialValueText(tr("Automatico"))
    form.addRow(tr("Valore (lettera o numero)"), label)
    form.addRow(tr("Dimensione testo (m)"), ts)
    form.addRow(tr("Diametro cerchio (m)"), rs)
    form.addRow(QLabel(tr("Dimensione testo e cerchio valgono per tutte le "
                          "griglie · Automatico = si adatta al testo")))
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return
    text = label.text().strip().upper()
    new_ts, new_rs = ts.value(), rs.value()

    _Settings.ts = new_ts
    _Settings.rs = new_rs if new_rs > 0 else None

    def mutate(sc):
        for g, _d in grids(sc):
            if g in groups:
                continue
            d = dict(grid_data(g))
            d["ts"] = new_ts
            d["rs"] = _Settings.rs
            d["tx"] = 1
            rebuild_grid(g, d)
        for g in groups:
            d = dict(grid_data(g))
            d["ts"] = new_ts
            d["rs"] = _Settings.rs
            if single and text and text != str(d["label"]):
                old = f"{tr('Griglia')} {d['label']}"
                d["label"] = text
                if d.get("name") == old:
                    d["name"] = f"{tr('Griglia')} {text}"
            d["tx"] = 1
            rebuild_grid(g, d)

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("Griglia aggiornata"), 3000)


def _hook_double_click(vp) -> None:
    if getattr(vp, "_myhouse_griglia_dbl", False):
        return
    original = vp.begin_group_edit

    def begin_group_edit(group, *args, **kwargs):
        g = getattr(group, "owner", None) or group
        if grid_data(g) is None:
            return original(group, *args, **kwargs)
        from PySide6.QtCore import QTimer
        try:
            vp.scene.select([g])
        except Exception:
            vp.scene.selection.clear()
            vp.scene.selection.add(g)
        vp.update()
        QTimer.singleShot(0, lambda: edit_grids(vp, [g]))

    vp.begin_group_edit = begin_group_edit
    vp._myhouse_griglia_dbl = True


def _intersect(d1, d2, ext=0.3):
    x1, y1 = d1["p1"]
    x2, y2 = d1["p2"]
    x3, y3 = d2["p1"]
    x4, y4 = d2["p2"]
    rx, ry = x2 - x1, y2 - y1
    sx, sy = x4 - x3, y4 - y3
    L1, L2 = math.hypot(rx, ry), math.hypot(sx, sy)
    den = rx * sy - ry * sx
    if L1 < 1e-9 or L2 < 1e-9 or abs(den) < 1e-6 * L1 * L2:
        return None
    t = ((x3 - x1) * sy - (y3 - y1) * sx) / den
    u = ((x3 - x1) * ry - (y3 - y1) * rx) / den
    if t * L1 < -ext or t * L1 > L1 + ext or u * L2 < -ext or u * L2 > L2 + ext:
        return None
    return (x1 + t * rx, y1 + t * ry)


def intersections(groups):
    datas = [grid_data(g) for g in groups]
    datas = [d for d in datas if d is not None]
    pts = []
    for i in range(len(datas)):
        for j in range(i + 1, len(datas)):
            p = _intersect(datas[i], datas[j])
            if p is None:
                continue
            if any(math.hypot(p[0] - q[0], p[1] - q[1]) < 0.01 for q in pts):
                continue
            pts.append(p)
    return pts


def snap_point(scene, x, y, tol=0.75):
    pts = intersections([g for g, _ in grids(scene)])
    best, bd = None, tol
    for p in pts:
        dist = math.hypot(p[0] - x, p[1] - y)
        if dist < bd:
            best, bd = p, dist
    return best


def _dist_seg(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 < 1e-12 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def pick(scene, x, y, tol=0.3):
    best, bd = None, tol
    for g, d in grids(scene):
        dist = _dist_seg((x, y), d["p1"], d["p2"])
        bc = d.get("bc")
        if bc:
            dist = min(dist, max(0.0, math.hypot(x - bc[0], y - bc[1]) - d.get("r", 0.0)))
        if dist < bd:
            best, bd = g, dist
    return best


def _spin(value, lo, hi):
    s = LengthSpin()
    s.setDecimals(3)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


def ask_params(parent):
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("Griglia"))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    size = _spin(_Settings.size, 0.01, 10.0)
    mode = QComboBox()
    for key, label in MODES:
        mode.addItem(label, key)
    mode.setCurrentIndex([k for k, _ in MODES].index(_Settings.mode))
    first_letter = QLineEdit(_Settings.first_letter)
    first_letter.setMaxLength(3)
    first_number = QSpinBox()
    first_number.setRange(0, 9999)
    first_number.setValue(_Settings.first_number)
    form.addRow(tr("Dimensione scritta (m)"), size)
    form.addRow(tr("Orientamento"), mode)
    form.addRow(tr("Prima lettera"), first_letter)
    form.addRow(tr("Primo numero"), first_number)
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return None
    return {"size": size.value(), "mode": mode.currentData(),
            "first_letter": (first_letter.text().strip().upper() or "A"),
            "first_number": first_number.value()}


def _store(p) -> None:
    _Settings.size = p["size"]
    _Settings.ts = None
    _Settings.rs = None
    _Settings.mode = p["mode"]
    _Settings.first_letter = p["first_letter"]
    _Settings.first_number = p["first_number"]
    _Settings.li = _letter_index(p["first_letter"])
    _Settings.ni = p["first_number"]


def _circle_lines(cx, cy, r, z, n=32):
    P = QVector3D
    pts = [(cx + r * math.cos(2 * math.pi * i / n),
            cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]
    return [(P(*pts[i], z), P(*pts[(i + 1) % n], z)) for i in range(n)]


class GrigliaTool(Tool):
    name = tr("Griglia")
    shortcut = None
    description = tr("Traccia griglie: linea tratto-punto con pallino e lettera o numero in sequenza.")

    def __init__(self) -> None:
        self._entering = False
        self.start = None
        self.hover_point = None
        self._z = 0.0
        self._guides = []

    def on_activate(self, viewport) -> None:
        self._vp = viewport
        if self._entering:
            self.start = None
            self.hover_point = None
            viewport.flash_status(
                tr("Griglia: clic per l'inizio, clic per la fine · Esc = esci"), 6000)
            return
        p = ask_params(viewport.window())
        if p is None:
            return
        _store(p)
        _Settings.level = piani.active_id(viewport.scene)
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def on_deactivate(self, viewport) -> None:
        self.start = None
        self.hover_point = None

    def on_cancel(self, viewport) -> None:
        if self.start is not None:
            self.start = None
        self.hover_point = None
        viewport.update()

    def _exit(self, viewport) -> None:
        self.start = None
        self.hover_point = None
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
        return key == Qt.Key_Escape

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            if self.start is not None:
                self.start = None
                viewport.update()
            else:
                self._exit(viewport)
            return True
        return False

    def _end_point(self, scene, pt):
        e = _ortho(self.start, pt)
        h = abs(e[0] - self.start[0]) >= abs(e[1] - self.start[1])
        return _align(scene, e, h)

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = QVector3D(ctx.world)
        pt = (ctx.world.x(), ctx.world.y())
        sc = ctx.viewport.scene
        if self.start is None:
            self._guides = _align(sc, pt, None)[1]
        else:
            self._guides = self._end_point(sc, pt)[1]
        ctx.viewport.update()

    def rubber_band_lines(self):
        if self.hover_point is None:
            return []
        P = QVector3D
        z = self._z if self.start is not None else self.hover_point.z()
        lines = [(P(a[0], a[1], z), P(b[0], b[1], z)) for a, b in self._guides]
        if self.start is None:
            return lines
        end = self._end_point(self._vp.scene,
                              (self.hover_point.x(), self.hover_point.y()))[0]
        lines.append((P(*self.start, z), P(*end, z)))
        L = math.hypot(end[0] - self.start[0], end[1] - self.start[1])
        if L > 1e-9:
            r = _Settings.size * 0.75
            ux, uy = (end[0] - self.start[0]) / L, (end[1] - self.start[1]) / L
            lines += _circle_lines(end[0] + ux * r, end[1] + uy * r, r, z)
        return lines

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        if getattr(vp.scene, "edit_group", None) is not None:
            vp.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        pt = (ctx.world.x(), ctx.world.y())
        if self.start is None:
            self.start = _align(vp.scene, pt, None)[0]
            self._z = ctx.world.z()
            vp.flash_status(tr("Griglia: clic per la fine della linea"), 3000)
            return
        end = self._end_point(vp.scene, pt)[0]
        if math.hypot(end[0] - self.start[0], end[1] - self.start[1]) < 0.05:
            return
        horizontal = abs(end[0] - self.start[0]) >= abs(end[1] - self.start[1])
        label = _take_label(horizontal)
        zb = piani.place(vp.scene, _Settings.level, 0.0, self._z)[0]
        d = {"p1": list(self.start), "p2": list(end), "size": _Settings.size,
             "label": label, "zb": zb, "z": zb + Z_LIFT,
             "name": f"{tr('Griglia')} {label}"}
        if _Settings.ts:
            d["ts"] = _Settings.ts
        if _Settings.rs:
            d["rs"] = _Settings.rs
        self.start = None
        self._guides = []

        def mutate(scene):
            build_grid(scene, d)

        vp.history.execute(muri.MuriCommand(mutate))
        vp.notify_scene_changed()
        vp.flash_status(tr("Griglia {0} creata").format(label), 2500)
        vp.update()


def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.drawLine(2, 24, 10, 24)
    p.drawPoint(14, 24)
    p.drawLine(18, 24, 26, 24)
    p.setBrush(QColor(255, 255, 255))
    p.drawEllipse(26, 12, 20, 20)
    f = p.font()
    f.setPixelSize(13)
    f.setBold(True)
    p.setFont(f)
    p.drawText(26, 12, 20, 20, Qt.AlignCenter, "A")
    p.drawLine(36, 34, 36, 46)
    p.end()
    return QIcon(pm)


def _outliner_kind(group):
    d = grid_data(group)
    if d is None:
        return None
    return {"type": tr("Griglia"), "props": [(tr("Etichetta"), str(d["label"]))]}


_WATCH = {}


def _watch(api) -> None:
    from PySide6.QtCore import QTimer
    state = {"sig": None}

    def tick() -> None:
        try:
            sc = api.window.viewport.scene
            changed = sync_grid_labels(sc)
            for g, d in grids(sc):
                if d.get("tx") != 1:
                    rebuild_grid(g, dict(d, tx=1))
                    changed = True
            if changed:
                api.window.viewport.update()
        except Exception:
            pass

    t = QTimer(api.window)
    t.timeout.connect(tick)
    t.start(700)
    _WATCH["t"] = t


def register(api) -> None:
    _watch(api)
    try:
        _hook_double_click(api.window.viewport)
    except Exception:
        pass
    api.add_button(tr("Griglia"),
                   tr("Traccia griglie con pallino e lettera o numero in sequenza"),
                   _icon(), api.run_tool(GrigliaTool()), group="Pilastri")
    add_kind = getattr(api.app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
