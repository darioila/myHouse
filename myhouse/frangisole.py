# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr
from ._scroll import scroll_form

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPen, QVector3D
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QSpinBox, QVBoxLayout)

from core import bim
from . import _ifc
from ._imperial import fmt_len
from tools.base import Tool, ToolContext

from . import finestre, muri, piani
from .finestre import FinestraCommand

KEY = "myhouse_frangisole"
LAYER_NAME = "Frangisole"
FRA_COLOR = (0.60, 0.40, 0.24)
FRA_MAT_NAME = tr("materiale frangisole")
ORDER = 100


class _Settings:
    n = 12
    t = 0.04
    H = 2.50
    p = 0.10
    orient = "vert"
    z = 0.0


def _params() -> dict:
    return {"n": _Settings.n, "t": _Settings.t, "H": _Settings.H,
            "p": _Settings.p, "orient": _Settings.orient, "z": _Settings.z}


def fra_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "a" in data else None


def _length(d: dict) -> float:
    return math.hypot(d["b"][0] - d["a"][0], d["b"][1] - d["a"][1])


def spacing(d: dict):
    n, t = int(d["n"]), d["t"]
    span = _length(d) if d["orient"] == "vert" else d["H"]
    if n < 1 or t <= 0:
        return 0.0, tr("Numero e spessore non validi")
    if n * t > span + 1e-9:
        return 0.0, tr("Troppe lamelle o spessore eccessivo: non ci stanno")
    if n == 1:
        return 0.0, None
    return (span - n * t) / (n - 1), None


def _boxes(d: dict):
    L, H, t, p = _length(d), d["H"], d["t"], d["p"]
    n, z0 = int(d["n"]), d["z"]
    gap, _err = spacing(d)
    step = t + gap
    off0 = 0.0
    if n == 1:
        off0 = ((L if d["orient"] == "vert" else H) - t) / 2.0
    out = []
    for i in range(n):
        s = off0 + i * step
        if d["orient"] == "vert":
            out.append((s, s + t, -p / 2.0, p / 2.0, z0, z0 + H))
        else:
            out.append((0.0, L, -p / 2.0, p / 2.0, z0 + s, z0 + s + t))
    return out


def _solid(mesh, vs, faces) -> None:
    c = QVector3D()
    for v in vs:
        c += v
    c /= len(vs)
    for f in faces:
        pts = [vs[i] for i in f]
        nrm = QVector3D()
        for i in range(len(pts)):
            nrm += QVector3D.crossProduct(pts[i], pts[(i + 1) % len(pts)])
        if QVector3D.dotProduct(nrm, pts[0] - c) < 0:
            pts.reverse()
        fc = mesh.add_face(pts)
        fc.attrs["color"] = FRA_COLOR
        fc.attrs["mat"] = FRA_MAT_NAME
        fc.attrs["layer"] = LAYER_NAME


_BOX_FACES = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4),
              (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]


def fra_mesh(d: dict):
    from core.mesh import Mesh
    ax, ay = d["a"][0], d["a"][1]
    L = _length(d)
    ux, uy = (d["b"][0] - ax) / L, (d["b"][1] - ay) / L
    nx, ny = -uy, ux

    def T(x, y, z):
        return QVector3D(ax + ux * x + nx * y, ay + uy * x + ny * y, z)

    mesh = Mesh()
    for x0, x1, y0, y1, z0, z1 in _boxes(d):
        vs = [T(x0, y0, z0), T(x1, y0, z0), T(x1, y1, z0), T(x0, y1, z0),
              T(x0, y0, z1), T(x1, y0, z1), T(x1, y1, z1), T(x0, y1, z1)]
        _solid(mesh, vs, _BOX_FACES)
    return mesh


def _parts(d: dict, pose=None):
    return [finestre._part(tr("Lamelle"), fra_mesh(d), pose)]


def _next_name(scene) -> str:
    used = {g.name for g in scene.groups}
    n = 1
    while tr("Frangisole {0}").format(n) in used:
        n += 1
    return tr("Frangisole {0}").format(n)


def make_frangisole(scene, d: dict):
    from core.group import Group, new_uid
    d = dict(d)
    d["id"] = new_uid()
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    name = _next_name(scene)
    g = Group(name=name)
    g.adopt(_parts(d))
    g.component = False
    g.layer = LAYER_NAME
    try:
        _ifc.tag(g, "IfcMember", name)
    except Exception:
        _ifc.tag(g, "IfcBuildingElementProxy", name)
    g.ext = {KEY: d}
    scene.groups.append(g)
    return g


def rebuild_frangisole(group, p: dict) -> None:
    d = dict(fra_data(group))
    d.update(p)
    group.children = _parts(d, finestre._pose(group))
    _ifc.tag(group, "IfcMember")
    ext = dict(group.ext or {})
    ext[KEY] = d
    group.ext = ext


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


def _disegno_frangisole(p):
    r, t, dim, ext = muri._r, muri._t, _dim_grande, muri._ext
    t(p, 10, 12, tr("Verticali"), size=12)
    p.setPen(QPen(muri._C_LINEA, 1.5))
    p.drawLine(QPointF(8, 150), QPointF(190, 150))
    muri._hatch(p, 8, 150, 190, 156)
    for i in range(4):
        x = 40 + i * 37
        r(p, x, 38, x + 9, 132, muri._C_LEGNO)
    dim(p, 40, 30, 49, 30, "t", 1)
    dim(p, 28, 38, 28, 132, "H", -1)
    ext(p, 160, 132, 180, 132)
    dim(p, 176, 132, 176, 150, "z", 1)
    t(p, 40, 166, "n = " + tr("numero lamelle"), size=11)
    t(p, 210, 12, tr("Orizzontali"), size=12)
    p.setPen(QPen(muri._C_LINEA, 1.5))
    p.drawLine(QPointF(205, 150), QPointF(385, 150))
    muri._hatch(p, 205, 150, 385, 156)
    for i in range(4):
        y = 38 + i * 28.3
        r(p, 235, y, 355, y + 9, muri._C_LEGNO)
    dim(p, 224, 38, 224, 132, "H", -1)
    ext(p, 355, 38, 366, 38)
    ext(p, 355, 47, 366, 47)
    dim(p, 366, 38, 366, 47, "t", 1)
    ext(p, 355, 132, 366, 132)
    dim(p, 366, 132, 366, 150, "z", 1)
    t(p, 405, 12, tr("Pianta"), size=12)
    r(p, 400, 36, 472, 48, muri._C_CORPO)
    r(p, 428, 48, 438, 100, muri._C_LEGNO)
    ext(p, 438, 100, 452, 100)
    dim(p, 452, 48, 452, 100, "p", 1)
    dim(p, 428, 114, 438, 114, "t", -1)


def ask_params(parent, current: dict, title: str, ok_text: str, scene=None):
    spin = finestre._spin
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(muri._Schema(_disegno_frangisole))
    n = QSpinBox()
    n.setRange(1, 500)
    n.setValue(int(current["n"]))
    t = spin(current["t"], 0.005, 2.0)
    H = spin(current["H"], 0.1, 50.0)
    p = spin(current["p"], 0.01, 2.0)
    orient = QComboBox()
    orient.addItem(tr("Verticali"), "vert")
    orient.addItem(tr("Orizzontali"), "oriz")
    orient.setCurrentIndex(1 if current["orient"] == "oriz" else 0)
    z = spin(current["z"], -100.0, 1000.0)
    if scene is not None:
        try:
            if piani.levels(scene):
                lvl = piani.level_combo(scene, piani.active_id(scene))

                def on_level(_i) -> None:
                    lv = piani.get(scene, lvl.currentData())
                    if lv:
                        z.setValue(lv["h"])
                lvl.currentIndexChanged.connect(on_level)
                form.addRow(tr("Piano di posa"), lvl)
        except Exception:
            pass
    form.addRow(tr("Orientamento lamelle"), orient)
    form.addRow(tr("Numero di lamelle (n)"), n)
    form.addRow(tr("Spessore lamella (t) (m)"), t)
    form.addRow(tr("Altezza (H) (m)"), H)
    form.addRow(tr("Profondità lamella (p) (m)"), p)
    form.addRow(tr("Quota della base (z) (m)"), z)
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.button(QDialogButtonBox.Ok).setText(ok_text)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return None
    return {"n": n.value(), "t": t.value(), "H": H.value(), "p": p.value(),
            "orient": orient.currentData(), "z": z.value()}


class FrangisoleTool(Tool):
    name = tr("Frangisole")
    shortcut = None
    description = tr("Crea un frangisole a lamelle: traccia una linea.")

    def __init__(self) -> None:
        self._entering = False
        self._reset()

    def _reset(self) -> None:
        self.points: list = []
        self.hover = None

    def on_activate(self, viewport) -> None:
        if self._entering:
            self._reset()
            viewport.flash_status(
                tr("Frangisole: 2 clic = linea lungo cui si sviluppa · "
                   "Backspace = indietro · Esc = esci"), 7000)
            return
        p = ask_params(viewport.window(), _params(), tr("Frangisole"),
                       tr("Posa"), viewport.scene)
        if p is None:
            return
        _Settings.n, _Settings.t, _Settings.H = p["n"], p["t"], p["H"]
        _Settings.p, _Settings.orient, _Settings.z = (
            p["p"], p["orient"], p["z"])
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
        return key == Qt.Key_Escape or (
            key == Qt.Key_Backspace and bool(self.points))

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if key == Qt.Key_Backspace and self.points:
            self.points.pop()
            viewport.update()
            return True
        return False

    def on_hover(self, ctx: ToolContext) -> None:
        w = QVector3D(ctx.world)
        self.hover = (w.x(), w.y())
        ctx.viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        if getattr(vp.scene, "edit_group", None) is not None:
            vp.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        x, y = ctx.world.x(), ctx.world.y()
        if self.points and math.hypot(x - self.points[0][0],
                                      y - self.points[0][1]) < 0.1:
            return
        self.points.append((x, y))
        if len(self.points) == 2:
            self._commit(vp)
        vp.update()

    def _commit(self, viewport) -> None:
        d = _params()
        d["a"], d["b"] = list(self.points[0]), list(self.points[1])
        _gap, err = spacing(d)
        if err:
            viewport.flash_status(tr("Frangisole: ") + err, 6000)
            self.points.pop()
            return

        def mutate(sc):
            make_frangisole(sc, d)

        hist = viewport.history
        hist.execute(FinestraCommand(mutate))
        if getattr(hist, "last_error", None):
            viewport.flash_status(
                tr("Frangisole: ") + str(hist.last_error).split(": ", 1)[-1],
                6000)
        else:
            viewport.notify_scene_changed()
            viewport.flash_status(tr("Frangisole creato"), 3000)
        self.points = []
        viewport.update()

    def rubber_band_lines(self):
        if not self.points:
            return []
        pts = list(self.points)
        if len(pts) == 1 and self.hover is not None:
            pts.append(self.hover)
        if len(pts) < 2:
            return []
        P = QVector3D
        z0, z1 = _Settings.z, _Settings.z + _Settings.H
        (ax, ay), (bx, by) = pts[0], pts[1]
        return [(P(ax, ay, z0), P(bx, by, z0)), (P(ax, ay, z1), P(bx, by, z1)),
                (P(ax, ay, z0), P(ax, ay, z1)), (P(bx, by, z0), P(bx, by, z1))]

    def draw_overlay(self, viewport, painter) -> None:
        try:
            from PySide6.QtCore import QPointF, QRectF
            painter.save()
            font = QFont()
            font.setPointSize(10)
            painter.setFont(font)
            fm = painter.fontMetrics()
            lines = [tr("Frangisole: clic sul punto {0}/2 della linea").format(
                         min(len(self.points) + 1, 2)),
                     tr("Backspace = indietro · Esc / tasto destro = esci")]
            w = max(fm.horizontalAdvance(s) for s in lines) + 16
            h = fm.height() * len(lines) + 12
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(30, 30, 30, 200))
            painter.drawRoundedRect(QRectF(12, 44, w, h), 6, 6)
            painter.setPen(QPen(QColor(255, 255, 255)))
            for i, s in enumerate(lines):
                painter.drawText(QPointF(20, 44 + 6 + fm.ascent()
                                         + i * fm.height()), s)
            painter.restore()
        except Exception:
            pass


def _selected(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and fra_data(g) is not None and g not in out:
            out.append(g)
    return out


def edit_frangisoli(viewport, groups=None) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    groups = groups or _selected(scene)
    if not groups:
        viewport.flash_status(tr("Seleziona un frangisole"), 4000)
        return
    d = fra_data(groups[0])
    cur = {k: d[k] for k in ("n", "t", "H", "p", "orient", "z")}
    p = ask_params(viewport.window(), cur, tr("Modifica frangisole"),
                   tr("Applica"))
    if p is None:
        return
    for g in groups:
        _gap, err = spacing({**fra_data(g), **p})
        if err:
            viewport.flash_status(tr("Frangisole: ") + err, 6000)
            return

    def mutate(sc):
        for g in groups:
            rebuild_frangisole(g, p)

    hist = viewport.history
    hist.execute(FinestraCommand(mutate))
    if getattr(hist, "last_error", None):
        viewport.flash_status(
            tr("Frangisole: ") + str(hist.last_error).split(": ", 1)[-1], 6000)
        return
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("Frangisole aggiornato"), 3000)


def _hook_double_click(vp) -> None:
    if getattr(vp, "_myhouse_fra_dbl", False):
        return
    original = vp.begin_group_edit

    def begin_group_edit(group, *args, **kwargs):
        g = getattr(group, "owner", None) or group
        if fra_data(g) is None:
            return original(group, *args, **kwargs)
        from PySide6.QtCore import QTimer
        scene = vp.scene
        try:
            scene.select([g])
        except Exception:
            scene.selection.clear()
            scene.selection.add(g)
        vp.update()
        QTimer.singleShot(0, lambda: edit_frangisoli(vp, [g]))

    vp.begin_group_edit = begin_group_edit
    vp._myhouse_fra_dbl = True


def _outliner_kind(group):
    d = fra_data(group)
    if d is None:
        return None
    gap, _err = spacing(d)
    return {"type": tr("Frangisole"),
            "props": [(tr("Lamelle"), str(int(d["n"]))),
                      (tr("Orientamento"), tr("Verticali")
                       if d["orient"] == "vert" else tr("Orizzontali")),
                      (tr("Spessore"), fmt_len(d["t"])),
                      (tr("Altezza"), fmt_len(d["H"])),
                      (tr("Distanza"), fmt_len(gap))]}


def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setPen(QPen(QColor(60, 60, 60), 1))
    p.setBrush(QColor(150, 100, 60))
    for i in range(6):
        p.drawRect(6 + i * 7, 6, 4, 36)
    p.end()
    return QIcon(pm)


def register(api) -> None:
    api.add_button(tr("Frangisole"),
                   tr("Crea un frangisole a lamelle verticali o orizzontali"),
                   _icon(), api.run_tool(FrangisoleTool()))
    app = api.app
    _hook_double_click(api.window.viewport)
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        from PySide6.QtCore import QTimer

        def context(menu, selection) -> None:
            if not _selected(app.viewport.scene):
                return
            menu.addSeparator()
            menu.addAction(
                tr("Modifica frangisole…"),
                lambda: QTimer.singleShot(
                    0, lambda: edit_frangisoli(app.viewport)))

        add_ctx(context)
    add_kind = getattr(app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
