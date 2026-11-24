# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr
from ._scroll import scroll_form

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPen, QVector3D
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QVBoxLayout,
)

from core import bim
from . import _ifc
from ._imperial import fmt_len
from tools.base import Tool, ToolContext

from . import finestre, muri, tetto
from .finestre import FinestraCommand

KEY = "myhouse_lucernario"
LAYER_NAME = "Lucernari"
ORDER = 52
MAX_DZ = 0.30
CORNERS = [("bl", tr("Basso sinistro")), ("br", tr("Basso destro")),
           ("tl", tr("Alto sinistro")), ("tr", tr("Alto destro"))]


class _Settings:
    W = 0.78
    H = 1.18
    sill = 0.0
    leaves = 1
    fw = 0.05
    fd = 0.10
    sw = 0.04
    corner = "bl"


def _params() -> dict:
    return {"W": _Settings.W, "H": _Settings.H, "sill": _Settings.sill,
            "leaves": _Settings.leaves, "fw": _Settings.fw,
            "fd": _Settings.fd, "sw": _Settings.sw}


def _store(p: dict) -> None:
    _Settings.W, _Settings.H, _Settings.sill = p["W"], p["H"], p["sill"]
    _Settings.leaves, _Settings.fw = p["leaves"], p["fw"]
    _Settings.fd, _Settings.sw = p["fd"], p["sw"]
    if "corner" in p:
        _Settings.corner = p["corner"]


def validate(p: dict) -> str | None:
    return finestre.validate(p)


def sky_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "o" in data else None


def _corner_offsets(corner, W, H):
    return (W if corner[1] == "r" else 0.0), (H if corner[0] == "t" else 0.0)


def _mapper(d: dict, lift: bool = True):
    ox, oy, oz = d["o"]
    er, es, en = d["er"], d["es"], d["en"]
    s = d["sill"] if lift else 0.0

    def T(a, b, c):
        k = s - b
        return QVector3D(ox + a * er[0] + c * es[0] + k * en[0],
                         oy + a * er[1] + c * es[1] + k * en[1],
                         oz + a * er[2] + c * es[2] + k * en[2])
    return T


def sky_meshes(d: dict):
    from core.mesh import Mesh
    err = validate(d)
    if err:
        raise ValueError(err)
    T = _mapper(d)
    box = finestre._box
    W, H, fw, fd, sw = d["W"], d["H"], d["fw"], d["fd"], d["sw"]
    n = int(d["leaves"])
    sd = fd * 0.6
    frame, glass = Mesh(), Mesh()
    fc, gc = finestre.FRAME_COLOR, finestre.GLASS_COLOR
    fb0, fb1 = -fd / 2, fd / 2
    box(frame, T, 0, fw, fb0, fb1, 0, H, fc)
    box(frame, T, W - fw, W, fb0, fb1, 0, H, fc)
    box(frame, T, fw, W - fw, fb0, fb1, 0, fw, fc)
    box(frame, T, fw, W - fw, fb0, fb1, H - fw, H, fc)
    wl = (W - 2 * fw) / n
    sb0, sb1 = -sd / 2, sd / 2
    c0, c1 = fw, H - fw
    gt = finestre.GLASS_T
    for i in range(n):
        a0 = fw + i * wl
        a1 = a0 + wl
        box(frame, T, a0, a0 + sw, sb0, sb1, c0, c1, fc)
        box(frame, T, a1 - sw, a1, sb0, sb1, c0, c1, fc)
        box(frame, T, a0 + sw, a1 - sw, sb0, sb1, c0, c0 + sw, fc)
        box(frame, T, a0 + sw, a1 - sw, sb0, sb1, c1 - sw, c1, fc)
        box(glass, T, a0 + sw, a1 - sw, -gt / 2, gt / 2,
            c0 + sw, c1 - sw, gc, finestre.GLASS_OPACITY)
    return frame, glass


def outline_lines(d: dict):
    T = _mapper(d)
    W, H, fd = d["W"], d["H"], d["fd"]
    pts = [T(a, b, c) for c in (0, H) for b in (-fd / 2, fd / 2)
           for a in (0, W)]
    pairs = []
    for base in (0, 4):
        pairs += [(base, base + 1), (base + 2, base + 3),
                  (base, base + 2), (base + 1, base + 3)]
    pairs += [(i, i + 4) for i in range(4)]
    return [(pts[i], pts[j]) for i, j in pairs]


def _parts(d: dict, pose=None):
    frame, glass = sky_meshes(d)
    return [finestre._part(tr("Telaio"), frame, pose),
            finestre._part(tr("Vetro"), glass, pose)]


def _next_name(scene) -> str:
    used = {g.name for g in scene.groups}
    n = 1
    while tr("Lucernario {0}").format(n) in used:
        n += 1
    return tr("Lucernario {0}").format(n)


def make_skylight(scene, p: dict, place: dict, corner: str):
    from core.group import Group
    d = dict(p)
    d.update(o=list(place["o"]), er=list(place["er"]),
             es=list(place["es"]), en=list(place["en"]), corner=corner)
    parts = _parts(d)
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    name = _next_name(scene)
    g = Group(name=name)
    g.adopt(parts)
    g.component = False
    g.layer = LAYER_NAME
    _ifc.tag(g, "IfcWindow", name)
    g.ext = {KEY: d}
    scene.groups.append(g)
    return g


def rebuild_skylight(group, p: dict) -> None:
    d = dict(sky_data(group))
    ca0, cc0 = _corner_offsets(d.get("corner", "bl"), d["W"], d["H"])
    d.update(p)
    ca1, cc1 = _corner_offsets(d.get("corner", "bl"), d["W"], d["H"])
    d["o"] = [d["o"][k] + (ca0 - ca1) * d["er"][k] + (cc0 - cc1) * d["es"][k]
              for k in range(3)]
    pose = finestre._pose(group)
    group.children = _parts(d, pose)
    _ifc.tag(group, "IfcWindow")
    ext = dict(group.ext or {})
    ext[KEY] = d
    group.ext = ext


def _rings(rd):
    from shapely.geometry import Polygon
    out = []
    for ring in tetto._roof_underside(rd):
        pl = tetto._plane(ring)
        if pl is None:
            continue
        pg = Polygon([(p[0], p[1]) for p in ring])
        if not pg.is_valid:
            pg = pg.buffer(0)
        if pg.is_empty:
            continue
        out.append((pg, (pl[0], pl[1], pl[2] + rd["th"])))
    return out


def find_roof(scene, world: QVector3D):
    from shapely.geometry import Point
    best = None
    for g in scene.groups:
        rd = tetto.roof_data(g)
        if rd is None:
            continue
        Mr = tetto._group_matrix(g)
        inv, ok = Mr.inverted()
        if not ok:
            continue
        lp = inv.map(world)
        pt = Point(lp.x(), lp.y())
        for pg, (a, b, c) in _rings(rd):
            if not pg.buffer(1e-6).contains(pt):
                continue
            zt = a * lp.x() + b * lp.y() + c
            dz = abs(zt - lp.z())
            if best is None or dz < best[0]:
                best = (dz, Mr, a, b, zt, lp, rd)
    return best


def placement(scene, world: QVector3D, corner: str, W: float, H: float):
    try:
        r = find_roof(scene, world)
    except ImportError:
        return None
    if r is None:
        return None
    _dz, Mr, pa, pb, zt, lp, _rd = r
    k = math.hypot(pa, pb)
    gx, gy = (pa / k, pb / k) if k > 1e-6 else (0.0, 1.0)
    q = math.sqrt(1 + k * k)
    es = (gx / q * 1.0, gy / q, k / q)
    en = (-k * gx / q, -k * gy / q, 1 / q)
    er = (gy, -gx, 0.0)
    P = Mr.map(QVector3D(lp.x(), lp.y(), zt))
    ws = [Mr.mapVector(QVector3D(*v)) for v in (er, es, en)]
    vec = [[v.x(), v.y(), v.z()] for v in ws]
    ca, cc = _corner_offsets(corner, W, H)
    o = [P.x() - ca * vec[0][0] - cc * vec[1][0],
         P.y() - ca * vec[0][1] - cc * vec[1][1],
         P.z() - ca * vec[0][2] - cc * vec[1][2]]
    return {"o": o, "er": vec[0], "es": vec[1], "en": vec[2]}


def _holes_for_roof(g, rd, skys, scene=None):
    from shapely.geometry import Polygon
    Mr = tetto._group_matrix(g)
    inv, ok = Mr.inverted()
    if not ok:
        return []
    rings = _rings(rd)
    out = []
    for s in skys:
        sd = sky_data(s)
        T = _mapper(sd, lift=False)
        m = inv * finestre._full_pose(s)
        W, H = sd["W"], sd["H"]
        pts = [m.map(T(a, 0, c)) for a, c in ((0, 0), (W, 0), (W, H), (0, H))]
        foot = Polygon([(p.x(), p.y()) for p in pts])
        if not foot.is_valid or foot.area < 1e-4:
            continue
        zc = sum(p.z() for p in pts) / 4
        cx, cy = foot.centroid.x, foot.centroid.y
        for pg, (a, b, c) in rings:
            if pg.intersection(foot).area < 1e-4:
                continue
            if abs(a * cx + b * cy + c - zc) > MAX_DZ:
                continue
            out.append([[round(p.x(), 4), round(p.y(), 4)] for p in pts])
            break
    if scene is not None:
        try:
            from . import abbaino
            out += abbaino.holes_for_roof(g, rd, scene)
        except ImportError:
            pass
    return out


def update_roof_holes(scene) -> int:
    try:
        import shapely
    except ImportError:
        return 0
    skys = [g for g in scene.groups if sky_data(g) is not None]
    changed = 0
    for g in scene.groups:
        rd = tetto.roof_data(g)
        if rd is None:
            continue
        holes = _holes_for_roof(g, rd, skys, scene)
        if holes == (rd.get("holes") or []):
            continue
        d2 = dict(rd)
        if holes:
            d2["holes"] = holes
        else:
            d2.pop("holes", None)
        tetto.rebuild_roof(g, d2)
        changed += 1
    return changed


def _dim_grande(p, x1, y1, x2, y2, txt, lato=1):
    p.setPen(QPen(muri._C_QUOTA, 1.3))
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    w = 8 * len(txt) + 2
    if abs(y1 - y2) < 1e-6:
        for x in (x1, x2):
            p.drawLine(QPointF(x, y1 - 3), QPointF(x, y1 + 3))
        muri._t(p, (x1 + x2) / 2 - w / 2, y1 + (-5 if lato > 0 else 14), txt, muri._C_QUOTA, 14, True)
    else:
        for y in (y1, y2):
            p.drawLine(QPointF(x1 - 3, y), QPointF(x1 + 3, y))
        muri._t(p, x1 + (6 if lato > 0 else -w - 4), (y1 + y2) / 2 + 5, txt, muri._C_QUOTA, 14, True)


def _disegno_lucernario(p):
    r, t, dim, ext = muri._r, muri._t, _dim_grande, muri._ext
    t(p, 10, 12, tr("Vista sulla falda"), size=12)
    r(p, 40, 44, 200, 132, muri._C_LEGNO)
    r(p, 50, 54, 190, 122, muri._C_BIANCO)
    r(p, 117, 54, 123, 122, muri._C_LEGNO)
    dim(p, 40, 36, 200, 36, "W", 1)
    dim(p, 28, 44, 28, 132, "H", -1)
    for x in (40, 50, 117, 123):
        ext(p, x, 132, x, 144)
    dim(p, 40, 144, 50, 144, "f", -1)
    dim(p, 117, 144, 123, 144, "s", -1)
    t(p, 255, 12, tr("Sezione"), size=12)
    r(p, 255, 96, 312, 104, muri._C_CORPO)
    r(p, 408, 96, 470, 104, muri._C_CORPO)
    r(p, 300, 54, 312, 82, muri._C_LEGNO)
    r(p, 408, 54, 420, 82, muri._C_LEGNO)
    r(p, 312, 64, 408, 68, muri._C_BIANCO)
    pen = QPen(muri._C_LINEA, 1)
    pen.setStyle(Qt.DashDotLine)
    p.setPen(pen)
    p.drawLine(QPointF(255, 96), QPointF(470, 96))
    t(p, 330, 124, tr("falda"), size=11)
    ext(p, 285, 82, 300, 82)
    dim(p, 285, 82, 285, 96, "r", -1)
    ext(p, 300, 46, 300, 54)
    ext(p, 312, 46, 312, 54)
    dim(p, 300, 46, 312, 46, "f", 1)
    ext(p, 420, 54, 434, 54)
    ext(p, 420, 82, 434, 82)
    dim(p, 434, 54, 434, 82, "d", 1)


def ask_params(parent, current: dict, title: str, ok_text: str,
               with_corner: bool = False):
    spin = finestre._spin
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(muri._Schema(_disegno_lucernario))
    W = spin(current["W"], 0.2, 20.0)
    H = spin(current["H"], 0.2, 20.0)
    sill = spin(current["sill"], -2.0, 5.0)
    leaves = QComboBox()
    leaves.addItem(tr("1 anta"), 1)
    for n in range(2, 9):
        leaves.addItem(tr("{0} ante").format(n), n)
    leaves.setCurrentIndex(leaves.findData(int(current["leaves"])))
    fw = spin(current["fw"], 0.01, 0.5)
    fd = spin(current["fd"], 0.02, 1.0)
    sw = spin(current["sw"], 0.01, 0.5)
    corner = None
    if with_corner:
        corner = QComboBox()
        for key, label in CORNERS:
            corner.addItem(label, key)
        corner.setCurrentIndex(
            max(0, corner.findData(current.get("corner", "bl"))))
        form.addRow(tr("Spigolo di inserimento (clic)"), corner)
    form.addRow(tr("Larghezza totale (W) (m)"), W)
    form.addRow(tr("Altezza totale, lungo la falda (H) (m)"), H)
    form.addRow(tr("Rialzo sulla falda (r) (m)"), sill)
    form.addRow(tr("Ante"), leaves)
    form.addRow(tr("Telaio: larghezza profilo (f) (m)"), fw)
    form.addRow(tr("Telaio: profondità (d) (m)"), fd)
    form.addRow(tr("Profilo dell'anta (s) (m)"), sw)
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.button(QDialogButtonBox.Ok).setText(ok_text)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return None
    p = {"W": W.value(), "H": H.value(), "sill": sill.value(),
         "leaves": leaves.currentData(), "fw": fw.value(),
         "fd": fd.value(), "sw": sw.value()}
    if corner is not None:
        p["corner"] = corner.currentData()
    return p


class LucernarioTool(Tool):
    name = tr("Lucernario")
    shortcut = None
    description = tr("Inserisce lucernari rettangolari che bucano il tetto.")

    def __init__(self) -> None:
        self._entering = False
        self._vp = None
        self.hover: QVector3D | None = None

    def on_activate(self, viewport) -> None:
        if self._entering:
            self._vp = viewport
            self.hover = None
            viewport.flash_status(
                tr("Lucernario: clic su un tetto · Spazio = cambia spigolo · "
                   "Esc / tasto destro = esci"), 6000)
            return
        cur = _params()
        cur["corner"] = _Settings.corner
        p = ask_params(viewport.window(), cur, tr("Lucernario"), tr("Posa"),
                       with_corner=True)
        if p is None:
            return
        err = validate(p)
        if err:
            viewport.flash_status(tr("Lucernario: ") + err, 5000)
            return
        _store(p)
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def on_deactivate(self, viewport) -> None:
        self.hover = None

    def _exit(self, viewport) -> None:
        self.hover = None
        viewport.update()
        back = getattr(viewport.window(), "activate_select_tool", None)
        if callable(back):
            back()

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover = QVector3D(ctx.world)
        ctx.viewport.update()

    def on_cancel(self, viewport) -> None:
        self.hover = None
        viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        scene = viewport.scene
        if getattr(scene, "edit_group", None) is not None:
            viewport.flash_status(
                tr("Chiudi il gruppo che stai modificando, poi posa il "
                   "lucernario"), 4000)
            return
        world = QVector3D(ctx.world)
        self.hover = world
        p = _params()
        corner = _Settings.corner
        place = placement(scene, world, corner, p["W"], p["H"])
        if place is None:
            viewport.flash_status(tr("Lucernario: clicca su un tetto"), 3000)
            return

        def mutate(sc):
            make_skylight(sc, p, place, corner)
            update_roof_holes(sc)

        hist = viewport.history
        hist.execute(FinestraCommand(mutate))
        if getattr(hist, "last_error", None):
            viewport.flash_status(
                tr("Lucernario: ") + str(hist.last_error).split(": ", 1)[-1],
                6000)
            return
        viewport.notify_scene_changed()
        viewport.flash_status(tr("Lucernario creato"), 2500)
        viewport.update()

    def context_menu(self, viewport, pos) -> bool:
        self._exit(viewport)
        return True

    def _buffer(self) -> str:
        return getattr(self._vp, "_value_buffer", "") or ""

    def claims_key(self, key: int, modifiers) -> bool:
        if modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        if self._buffer():
            return False
        return key in (Qt.Key_Space, Qt.Key_Escape)

    def _corner_label(self) -> str:
        return dict(CORNERS).get(_Settings.corner, "")

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if key == Qt.Key_Space:
            keys = [k for k, _l in CORNERS]
            i = keys.index(_Settings.corner) if _Settings.corner in keys else 0
            _Settings.corner = keys[(i + 1) % len(keys)]
            viewport.flash_status(tr("Spigolo: ") + self._corner_label(), 2000)
            viewport.update()
            return True
        return False

    def status_clause(self) -> str:
        return (tr("Spigolo {0} (Spazio cambia) · Esc / tasto destro = esci")
                .format(self._corner_label().lower()))

    def rubber_band_lines(self):
        if self.hover is None:
            return []
        scene = self._vp.scene if self._vp is not None else None
        if scene is None:
            return []
        d = _params()
        place = placement(scene, self.hover, _Settings.corner, d["W"], d["H"])
        if place is None:
            return []
        d.update(place)
        return outline_lines(d)

    def draw_overlay(self, viewport, painter) -> None:
        try:
            self._draw(viewport, painter)
        except Exception:
            pass

    def _draw(self, viewport, painter) -> None:
        painter.save()
        font = QFont()
        font.setPointSize(10)
        painter.setFont(font)
        fm = painter.fontMetrics()
        p = _params()
        lines = [
            tr("Lucernario {0} × {1} · {2} {3}").format(
                fmt_len(p['W']), fmt_len(p['H']), int(p['leaves']),
                tr('anta') if p['leaves'] == 1 else tr('ante')),
            tr("Rialzo: {0} · telaio {1} × {2}").format(
                fmt_len(p['sill']), fmt_len(p['fw']), fmt_len(p['fd'])),
            tr("Spigolo: {0}  (Spazio cambia)").format(
                self._corner_label().upper()),
            tr("Esc / tasto destro = esci"),
        ]
        w = max(fm.horizontalAdvance(t) for t in lines) + 16
        h = fm.height() * len(lines) + 12
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(30, 30, 30, 200))
        painter.drawRoundedRect(QRectF(12, 44, w, h), 6, 6)
        painter.setPen(QPen(QColor(255, 255, 255)))
        for i, t in enumerate(lines):
            painter.drawText(QPointF(20, 44 + 6 + fm.ascent()
                                     + i * fm.height()), t)
        painter.restore()


def _selected_skylights(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and sky_data(g) is not None and g not in out:
            out.append(g)
    return out


def edit_skylights(viewport, skys=None) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    skys = skys or _selected_skylights(scene)
    if not skys:
        viewport.flash_status(
            tr("Seleziona un lucernario creato con lo strumento Lucernario"),
            4000)
        return
    d = sky_data(skys[0])
    current = {k: d[k] for k in ("W", "H", "sill", "leaves", "fw", "fd", "sw")}
    title = tr("Modifica lucernario") if len(skys) == 1 \
        else tr("Modifica {0} lucernari").format(len(skys))
    p = ask_params(viewport.window(), current, title, tr("Applica"))
    if p is None:
        return
    err = validate(p)
    if err:
        viewport.flash_status(tr("Lucernario: ") + err, 5000)
        return

    def mutate(sc):
        for g in skys:
            rebuild_skylight(g, p)
        update_roof_holes(sc)

    hist = viewport.history
    hist.execute(FinestraCommand(mutate))
    if getattr(hist, "last_error", None):
        viewport.flash_status(
            tr("Lucernario: ") + str(hist.last_error).split(": ", 1)[-1], 6000)
        return
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("{0} lucernari aggiornati").format(len(skys)), 3000)


def _hook_double_click(vp) -> None:
    if getattr(vp, "_myhouse_luc_dbl", False):
        return
    original = vp.begin_group_edit

    def begin_group_edit(group, *args, **kwargs):
        g = getattr(group, "owner", None) or group
        if sky_data(g) is None:
            return original(group, *args, **kwargs)
        from PySide6.QtCore import QTimer
        scene = vp.scene
        try:
            scene.select([g])
        except Exception:
            scene.selection.clear()
            scene.selection.add(g)
        vp.update()
        QTimer.singleShot(0, lambda: edit_skylights(vp, [g]))

    vp.begin_group_edit = begin_group_edit
    vp._myhouse_luc_dbl = True


def _outliner_kind(group):
    d = sky_data(group)
    if d is None:
        return None
    return {"type": tr("Lucernario"),
            "props": [(tr("Larghezza"), fmt_len(d["W"])),
                      (tr("Altezza"), fmt_len(d["H"])),
                      (tr("Rialzo"), fmt_len(d["sill"])),
                      (tr("Ante"), str(int(d["leaves"])))]}


def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap, QPolygon
    from PySide6.QtCore import QPoint
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(170, 90, 75))
    p.drawPolygon(QPolygon([QPoint(4, 40), QPoint(14, 8),
                            QPoint(34, 8), QPoint(44, 40)]))
    p.setBrush(QColor(170, 210, 235))
    p.drawPolygon(QPolygon([QPoint(16, 30), QPoint(20, 16),
                            QPoint(28, 16), QPoint(32, 30)]))
    p.end()
    return QIcon(pm)


def register(api) -> None:
    api.add_button(tr("Lucernario"),
                   tr("Inserisce un lucernario rettangolare nel tetto"),
                   _icon(), api.run_tool(LucernarioTool()))
    app = api.app
    _hook_double_click(api.window.viewport)
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        from PySide6.QtCore import QTimer

        def context(menu, selection) -> None:
            if not _selected_skylights(app.viewport.scene):
                return
            menu.addSeparator()
            menu.addAction(
                tr("Modifica lucernario…"),
                lambda: QTimer.singleShot(
                    0, lambda: edit_skylights(app.viewport)))

        add_ctx(context)
    add_kind = getattr(app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
