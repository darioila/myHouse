# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr
from ._imperial import LengthSpin
from ._scroll import scroll_form

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPen, QVector3D
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QLineEdit, QVBoxLayout,
)

from core import bim
from . import _ifc
from ._imperial import fmt_len
from tools.base import Tool, ToolContext

from . import _tipi, muri, piani

ORDER = 44
KEY = "myhouse_platea"
LAYER_NAME = "Fondazioni"
PLATEA_COLOR = (0.58, 0.58, 0.56)
PLATEA_MAT = tr("materiale platea")
BASE_COLOR = (0.70, 0.70, 0.68)
BASE_MAT = tr("materiale base platea")
CLOSE_TOL = 0.02


class _Settings:
    H = 0.40
    Hb = 0.10
    off = 0.50
    bs = 0.10
    name = tr("Platea")
    ortho = True
    level = None
    zoff = 0.0
    tipo_id = None
    tipo_nome = None


KEYS = ("H", "Hb", "off", "bs")


def _params() -> dict:
    return {k: getattr(_Settings, k) for k in KEYS + ("tipo_id", "tipo_nome")}


def _area(pts) -> float:
    return sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
               - pts[(i + 1) % len(pts)][0] * pts[i][1]
               for i in range(len(pts))) / 2.0


def _offset(pts, dist):
    from shapely.geometry import Polygon
    from shapely.geometry.polygon import orient
    poly = Polygon(pts)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.geom_type != "Polygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    if abs(dist) > 1e-9:
        poly = poly.buffer(dist, join_style=2, mitre_limit=5.0)
        if poly.geom_type != "Polygon":
            poly = max(poly.geoms, key=lambda g: g.area)
    poly = orient(poly, 1.0)
    out = []
    c = [tuple(p) for p in poly.exterior.coords[:-1]]
    for i, p in enumerate(c):
        a, n = c[i - 1], c[(i + 1) % len(c)]
        if abs((p[0] - a[0]) * (n[1] - p[1])
               - (p[1] - a[1]) * (n[0] - p[0])) > 1e-9:
            out.append(p)
    return out


def _convex(pts) -> bool:
    n = len(pts)
    for i in range(n):
        a, b, c = pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        if (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) < -1e-9:
            return False
    return True


def solids(d):
    p = d["p"]
    z = d["z"]
    out = []
    top = _offset(d["pts"], p["off"])
    out.append((top, z - p["H"], z, "platea"))
    if p["Hb"] > 1e-6:
        out.append((_offset(d["pts"], p["off"] + p["bs"]),
                    z - p["H"] - p["Hb"], z - p["H"], "base"))
    return out


def platea_parts(d):
    from core.group import Group
    from core.mesh import Mesh
    P = QVector3D
    parts = []
    for ring, zl, zh, kind in solids(d):
        mesh = Mesh()
        base = kind == "base"

        def face(q, base=base, mesh=mesh):
            f = mesh.add_face(q)
            f.attrs["color"] = BASE_COLOR if base else PLATEA_COLOR
            f.attrs["mat"] = BASE_MAT if base else PLATEA_MAT
            f.attrs["layer"] = LAYER_NAME

        if _convex(ring):
            face([P(x, y, zh) for x, y in ring])
            face([P(x, y, zl) for x, y in reversed(ring)])
        else:
            for a, b, c in muri._ear_clip(ring):
                face([P(a[0], a[1], zh), P(b[0], b[1], zh), P(c[0], c[1], zh)])
                face([P(a[0], a[1], zl), P(c[0], c[1], zl), P(b[0], b[1], zl)])
        n = len(ring)
        for i in range(n):
            j = (i + 1) % n
            face([P(*ring[i], zl), P(*ring[j], zl),
                  P(*ring[j], zh), P(*ring[i], zh)])
        part = Group(mesh, name=tr("Base platea") if base else tr("Platea"))
        part.component = False
        parts.append(part)
    return parts


def platea_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "pts" in data else None


def build_platea(scene, d) -> None:
    from core.group import Group
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    g = Group(name=d["name"])
    g.adopt(platea_parts(d))
    g.component = False
    g.layer = LAYER_NAME
    _ifc.tag(g, "IfcFooting", d["name"])
    g.ext = {KEY: d}
    scene.groups.append(g)


def rebuild_platea(group, p: dict, name=None, extra=None) -> None:
    d = dict(platea_data(group))
    d["p"] = dict(p)
    if name:
        d["name"] = name
    for k, v in (extra or {}).items():
        if v is None:
            d.pop(k, None)
        else:
            d[k] = v
    group.children = platea_parts(d)
    _ifc.tag(group, "IfcFooting")
    group.name = d["name"]
    ext = dict(group.ext or {})
    ext[KEY] = d
    group.ext = ext


def _spin(value, lo, hi):
    s = LengthSpin()
    s.setDecimals(3)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


def _disegno_platea(p):
    r, tx, dim, ext = muri._r, muri._t, muri._dim, muri._ext
    tx(p, 10, 12, tr("Pianta"), size=9)
    pen = QPen(muri._C_LINEA, 1)
    pen.setStyle(Qt.DashLine)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRect(20, 30, 200, 120)
    r(p, 36, 46, 204, 134, muri._C_CORPO)
    p.setPen(QPen(muri._C_LINEA, 1))
    p.setBrush(QColor(255, 255, 255))
    p.drawRect(60, 66, 120, 48)
    tx(p, 78, 94, tr("poligono tracciato"), size=8)
    dim(p, 36, 56, 60, 56, "Off", 1)
    dim(p, 20, 40, 36, 40, "s", 1)
    tx(p, 290, 12, tr("Sezione"), size=9)
    r(p, 300, 60, 450, 100, muri._C_CORPO)
    r(p, 290, 100, 460, 114, muri._C_CORPO)
    dim(p, 470, 60, 470, 100, "H", 1)
    dim(p, 470, 100, 470, 114, "Hb", 1)
    ext(p, 280, 60, 450, 60)
    tx(p, 300, 54, tr("quota del primo punto"), size=8)


def ask_params(parent, cur: dict, title: str, name=None, scene=None):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(muri._Schema(_disegno_platea))
    H = _spin(cur["H"], 0.02, 10.0)
    Hb = _spin(cur["Hb"], 0.0, 5.0)
    off = _spin(cur["off"], 0.0, 20.0)
    bs = _spin(cur["bs"], 0.0, 5.0)
    nm = QLineEdit(name if name is not None else _Settings.name)
    lvl = None
    zoff = _spin(cur.get("zoff", 0.0), -100.0, 1000.0)
    if scene is not None and piani.levels(scene):
        lvl = piani.level_combo(scene, cur.get("lv"))
        form.addRow(tr("Piano"), lvl)
    form.addRow(tr("Altezza da terra / dal piano - faccia superiore (z) (m)"),
                zoff)
    ws = {"H": H, "Hb": Hb, "off": off, "bs": bs}
    _get, _set = _tipi.widgets_io(ws)
    tbar = _tipi.TypeBar(dlg, form, "platea", cur, _get, _set, scene,
                         creating=name is None)
    form.addRow(tr("Spessore platea (H) (m)"), H)
    form.addRow(tr("Spessore base (Hb) (m) - 0 = nessuna base"), Hb)
    form.addRow(tr("Offset esterno della platea (Off) (m)"), off)
    form.addRow(tr("Base: sporgenza oltre la platea (s) (m)"), bs)
    form.addRow(tr("Nome"), nm)
    ortho = None
    if name is None:
        ortho = QCheckBox(tr("Ortogonale (O / F8 durante il disegno)"))
        ortho.setChecked(_Settings.ortho)
        form.addRow(ortho)
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return None
    res = {**tbar.result(_get()),
           "_name": nm.text().strip() or tr("Platea"),
           "zoff": zoff.value(),
           "lv": (lvl.currentData() or None) if lvl is not None else None}
    if ortho is not None:
        res["_ortho"] = ortho.isChecked()
    return res


class PlateaTool(Tool):
    name = tr("Platea")
    shortcut = None
    description = tr("Traccia una fondazione a platea (poligono con offset esterno).")

    def __init__(self) -> None:
        self._entering = False
        self._vp = None
        self.points: list[QVector3D] = []
        self.hover_point: QVector3D | None = None

    def _reset(self) -> None:
        self.points = []
        self.hover_point = None

    def _ortho(self, p: QVector3D) -> QVector3D:
        if not (_Settings.ortho and self.points):
            return p
        last = self.points[-1]
        if abs(p.x() - last.x()) >= abs(p.y() - last.y()):
            return QVector3D(p.x(), last.y(), p.z())
        return QVector3D(last.x(), p.y(), p.z())

    def on_activate(self, viewport) -> None:
        self._vp = viewport
        if self._entering:
            self._reset()
            viewport.flash_status(
                tr("Platea: clic per i vertici · C/Invio/doppio clic = chiudi · "
                   "Esc = esci"), 6000)
            return
        cur = _params()
        cur["lv"] = piani.active_id(viewport.scene)
        cur["zoff"] = _Settings.zoff
        p = ask_params(viewport.window(), cur, tr("Platea"), None,
                       viewport.scene)
        if p is None:
            return
        _Settings.name = p.pop("_name")
        _Settings.ortho = p.pop("_ortho", True)
        _Settings.level = p.pop("lv")
        _Settings.zoff = p.pop("zoff")
        piani.set_active(_Settings.level)
        for k, v in p.items():
            setattr(_Settings, k, v)
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

    def claims_key(self, key: int, modifiers) -> bool:
        if modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        if key in (Qt.Key_Escape, Qt.Key_O, Qt.Key_F8):
            return True
        return key == Qt.Key_C and bool(self.points)

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if key in (Qt.Key_O, Qt.Key_F8):
            _Settings.ortho = not _Settings.ortho
            viewport.flash_status(
                tr("Ortogonale ") + (tr("attivo") if _Settings.ortho
                                     else tr("disattivato")), 2000)
            viewport.update()
            return True
        if key == Qt.Key_C and self.points:
            self._commit(viewport)
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter) and self.points:
            self._commit(viewport)
            return True
        if key == Qt.Key_Backspace and self.points:
            self.points.pop()
            viewport.update()
            return True
        return False

    def context_menu(self, viewport, pos) -> bool:
        if self.points:
            if len(self.points) >= 3:
                self._commit(viewport)
            else:
                self._reset()
                viewport.update()
        else:
            self._exit(viewport)
        return True

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = self._ortho(QVector3D(ctx.world))
        ctx.viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        raw = QVector3D(ctx.world)
        if len(self.points) >= 3 and (raw - self.points[0]).length() < CLOSE_TOL:
            self._commit(ctx.viewport)
            return
        p = self._ortho(raw)
        if self.points and (p - self.points[-1]).length() < 1e-6:
            return
        self.points.append(p)
        self.hover_point = p
        ctx.viewport.update()

    def on_double_click(self, ctx: ToolContext) -> None:
        self._commit(ctx.viewport)

    def status_clause(self) -> str:
        return (tr("Platea: clic = vertice · Ortogonale {0} (O/F8) · C/Invio = chiudi · "
                   "Backspace = toglie il punto").format(
                       "ON" if _Settings.ortho else "OFF"))

    def value_label(self):
        if not self.points or self.hover_point is None:
            return None
        a, b = self.points[-1], self.hover_point
        if (b - a).length() < 1e-6:
            return None
        return (fmt_len((b - a).length()), (a + b) * 0.5)

    def rubber_band_lines(self):
        pts = list(self.points)
        if self.hover_point is not None and pts and (
                self.hover_point - pts[-1]).length() > 1e-6:
            pts.append(self.hover_point)
        if len(pts) < 2:
            return []
        z = self.points[0].z()
        if self._vp is not None:
            z = piani.place(self._vp.scene, _Settings.level, _Settings.zoff,
                            z)[0]
        P = QVector3D
        flat = [(p.x(), p.y()) for p in pts]
        lines = [(P(*flat[i], z), P(*flat[i + 1], z))
                 for i in range(len(flat) - 1)]
        if len(flat) >= 3:
            lines.append((P(*flat[-1], z), P(*flat[0], z)))
            try:
                ring = _offset(flat, _Settings.off)
                lines += [(P(*ring[i], z), P(*ring[(i + 1) % len(ring)], z))
                          for i in range(len(ring))]
            except Exception:
                pass
        return lines

    def _commit(self, viewport) -> None:
        if getattr(viewport.scene, "edit_group", None) is not None:
            viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        flat = []
        for p in self.points:
            q = (p.x(), p.y())
            if not flat or math.hypot(q[0] - flat[-1][0], q[1] - flat[-1][1]) > 1e-6:
                flat.append(q)
        if len(flat) < 3 or abs(_area(flat)) < 1e-9:
            viewport.flash_status(tr("Per la platea servono almeno 3 punti"), 3000)
            return
        try:
            import shapely
        except ImportError:
            viewport.flash_status(
                tr("Serve la libreria shapely (pip install shapely)"), 5000)
            return
        if _area(flat) < 0:
            flat.reverse()
        z, extra = piani.place(viewport.scene, _Settings.level,
                               _Settings.zoff, self.points[0].z())
        d = {"pts": [list(p) for p in flat], "z": z,
             "p": _params(), "name": _Settings.name}
        d.update(extra)

        def mutate(scene):
            build_platea(scene, d)

        viewport.history.execute(muri.MuriCommand(mutate))
        viewport.notify_scene_changed()
        viewport.flash_status(
            tr("Platea creata · clic = nuova platea · Esc = esci"), 4000)
        self._reset()
        viewport.update()


def _selected(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and platea_data(g) is not None and g not in out:
            out.append(g)
    return out


def edit_platee(viewport, groups=None) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    groups = groups or _selected(scene)
    if not groups:
        viewport.flash_status(tr("Seleziona una platea"), 3000)
        return
    d0 = platea_data(groups[0])
    cur = dict(_params())
    cur.update(d0["p"])
    cur["tipo_id"] = d0["p"].get("tipo_id")
    cur["lv"] = d0.get("lv")
    cur["zoff"] = d0.get("off", d0["z"]) if d0.get("lv") else d0["z"]
    p = ask_params(viewport.window(), cur, tr("Modifica platea"), d0["name"],
                   scene)
    if p is None:
        return
    name = p.pop("_name")
    p.pop("_ortho", None)
    zoff, lid = p.pop("zoff"), p.pop("lv")
    st = _tipi.resolve_edit(viewport.window(), scene, "platea", p)
    if st == "cancel":
        return

    def mutate(sc):
        lv = piani.get(sc, lid)
        extra = ({"lv": lv["id"], "lvn": lv["name"], "off": zoff,
                  "z": lv["z"] + zoff} if lv else
                 {"lv": None, "lvn": None, "off": None, "z": zoff})
        for g in groups:
            rebuild_platea(g, p, name if len(groups) == 1 else None, extra)
        if st == "type":
            _tipi.update_instances(sc, "platea", p["tipo_id"],
                                   lambda g, q: rebuild_platea(g, q))

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("{0} platee aggiornate").format(len(groups)), 3000)


def _hook_double_click(vp) -> None:
    if getattr(vp, "_myhouse_platea_dbl", False):
        return
    original = vp.begin_group_edit

    def begin_group_edit(group, *args, **kwargs):
        g = getattr(group, "owner", None) or group
        if platea_data(g) is None:
            return original(group, *args, **kwargs)
        from PySide6.QtCore import QTimer
        try:
            vp.scene.select([g])
        except Exception:
            vp.scene.selection.clear()
            vp.scene.selection.add(g)
        vp.update()
        QTimer.singleShot(0, lambda: edit_platee(vp, [g]))

    vp.begin_group_edit = begin_group_edit
    vp._myhouse_platea_dbl = True


def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(170, 168, 160))
    p.drawRect(4, 32, 40, 10)
    p.setBrush(QColor(150, 148, 140))
    p.drawRect(8, 24, 32, 8)
    p.setBrush(QColor(200, 198, 190))
    p.drawRect(14, 6, 6, 18)
    p.drawRect(28, 6, 6, 18)
    p.end()
    return QIcon(pm)


def _outliner_kind(group):
    d = platea_data(group)
    if d is None:
        return None
    p = d["p"]
    return {"type": tr("Platea"),
            "props": [(tr("Spessore platea"), fmt_len(p["H"])),
                      (tr("Spessore base"), fmt_len(p["Hb"])),
                      (tr("Offset esterno"), fmt_len(p["off"])),
                      (tr("Quota faccia superiore"), fmt_len(d["z"]))]
            + piani.level_props(d)}


def _register_level_kind() -> None:
    def zset(d, z):
        d["z"] = z

    def rebuild(g, d):
        g.children = platea_parts(d)
        _ifc.tag(g, "IfcFooting")
        ext = dict(g.ext or {})
        ext[KEY] = d
        g.ext = ext

    piani.register_kind("platea", KEY, platea_data, lambda d: d["z"], zset,
                        rebuild, lambda d: d["p"]["H"],
                        lambda d, h: None)


def register(api) -> None:
    _register_level_kind()
    api.add_button(tr("Platea"), tr("Fondazione a platea (poligono con offset esterno)"),
                   _icon(), api.run_tool(PlateaTool()))
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
                tr("Modifica platea…"),
                lambda: QTimer.singleShot(
                    0, lambda: edit_platee(app.viewport)))

        add_ctx(context)
    add_kind = getattr(app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
