# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr
from ._imperial import LengthSpin
from ._scroll import scroll_form

import math

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QMatrix4x4, QPen, QVector3D
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QVBoxLayout,
)

from core import bim
from . import _ifc
from tools.base import Tool, ToolContext

from . import _tipi, muri

ORDER = 43
KEY = "myhouse_trave_rovescia"
LAYER_NAME = "Fondazioni"
COLOR = (0.55, 0.55, 0.53)
MAT_NAME = tr("materiale fondazione")
TYPES = [("rect", tr("Suola rettangolare")), ("tap", tr("Suola rastremata"))]
PICK_TOL = 0.15


class _Settings:
    tipo = "rect"
    B = 0.80
    H = 0.40
    Hc = 0.30
    Wc = 0.0
    He = 0.15
    E = 0.0
    dz = 0.0
    tipo_id = None
    tipo_nome = None


def _params() -> dict:
    return {k: getattr(_Settings, k)
            for k in ("tipo", "B", "H", "Hc", "Wc", "He", "E", "dz",
                      "tipo_id", "tipo_nome")}


def _pose(g) -> QMatrix4x4:
    for k in getattr(g, "children", None) or ():
        if getattr(k, "xform", None) is not None:
            return QMatrix4x4(k.xform)
    return QMatrix4x4()


def _full_pose(g) -> QMatrix4x4:
    gx = getattr(g, "xform", None)
    m = QMatrix4x4(gx) if gx is not None else QMatrix4x4()
    return m * _pose(g)


def _geom(g):
    w = muri.wall_data(g)
    if not w or w.get("poly") or "a" not in w:
        return None
    pose = _full_pose(g)
    ax, ay = w["a"]
    bx, by = w["b"]
    z0 = w.get("z0", 0.0)
    A = pose.map(QVector3D(ax, ay, z0))
    B = pose.map(QVector3D(bx, by, z0))
    dx, dy = B.x() - A.x(), B.y() - A.y()
    L = math.hypot(dx, dy)
    if L < 1e-6:
        return None
    try:
        th = muri.wall_th_at(w, math.hypot(bx - ax, by - ay) / 2)
    except Exception:
        th = w.get("th", 0.3)
    dl, dr = {"left": (0.0, th), "right": (th, 0.0)}.get(
        w.get("align"), (th / 2, th / 2))
    ux, uy = dx / L, dy / L
    return {"A": (A.x(), A.y(), A.z()), "u": (ux, uy), "n": (-uy, ux),
            "L": L, "th": th, "centre": (dl - dr) / 2}


def _walls(scene):
    out = []
    for g in scene.groups:
        if muri.wall_data(g) is not None:
            out.append(g)
    return out


def _wchain(g):
    return (muri.wall_data(g) or {}).get("chain")


def _wall_index(scene):
    by_key, by_name = {}, {}
    for wg in _walls(scene):
        by_key.setdefault((wg.name, _wchain(wg)), wg)
        by_name.setdefault(wg.name, wg)
    return by_key, by_name


def _owner(index, d):
    by_key, by_name = index
    if "wchain" in d:
        return by_key.get((d["wname"], d["wchain"]))
    return by_name.get(d["wname"])


def wall_at(scene, pt: QVector3D):
    best, best_key = (None, None), None
    for g in _walls(scene):
        ge = _geom(g)
        if ge is None:
            continue
        ax, ay, az = ge["A"]
        px, py = pt.x() - ax, pt.y() - ay
        s = px * ge["u"][0] + py * ge["u"][1]
        off = px * ge["n"][0] + py * ge["n"][1]
        dist = abs(off - ge["centre"]) - ge["th"] / 2
        if dist > PICK_TOL or s < -PICK_TOL or s > ge["L"] + PICK_TOL:
            continue
        key = (round(dist, 3), abs(pt.z() - az))
        if best_key is None or key < best_key:
            best, best_key = (g, ge), key
    return best


def _profile(ge, p):
    wc = p["Wc"] if p["Wc"] > 1e-6 else ge["th"]
    B = max(p["B"], wc + 0.02)
    hs, hc = p["H"], p["Hc"]
    a, c = wc / 2, B / 2
    z1 = -hc
    z2 = -hc - hs
    if p["tipo"] == "tap":
        ze = z2 + max(0.0, min(p["He"], hs))
        flange = [(-a, z1), (-c, ze), (-c, z2), (c, z2), (c, ze), (a, z1)]
        outline = [(-a, 0), (-a, z1), (-c, ze), (-c, z2), (c, z2), (c, ze),
                   (a, z1), (a, 0)]
    else:
        flange = [(-c, z1), (-c, z2), (c, z2), (c, z1)]
        outline = [(-a, 0), (-a, z1), (-c, z1), (-c, z2), (c, z2), (c, z1),
                   (a, z1), (a, 0)]
    stem = [(-a, 0), (-a, z1), (a, z1), (a, 0)]
    return outline, [stem, flange]


def _mapper(ge, p):
    ax, ay, az = ge["A"]
    ux, uy = ge["u"]
    nx, ny = ge["n"]
    cen = ge["centre"]

    def P(s, b, z):
        return QVector3D(ax + ux * s + nx * (cen + b),
                         ay + uy * s + ny * (cen + b),
                         az + z + p.get("dz", 0.0))
    return P


def _s_on_plane(ge, plane, b):
    (px, py), (mx, my) = plane
    ax, ay, _az = ge["A"]
    ux, uy = ge["u"]
    nx, ny = ge["n"]
    um = ux * mx + uy * my
    if abs(um) < 1e-9:
        return None
    nm = nx * mx + ny * my
    return ((px - ax) * mx + (py - ay) * my - nm * (ge["centre"] + b)) / um


def fondazione_mesh(ge, p, ends=None):
    from core.mesh import Mesh
    P = _mapper(ge, p)
    outline, pieces = _profile(ge, p)
    ends = ends or {}

    def s_start(b):
        v = _s_on_plane(ge, ends["s"], b) if ends.get("s") else None
        return -p["E"] if v is None else v

    def s_end(b):
        v = _s_on_plane(ge, ends["e"], b) if ends.get("e") else None
        return ge["L"] + p["E"] if v is None else v

    mesh = Mesh()

    def face(q):
        f = mesh.add_face(q)
        f.attrs["color"] = COLOR
        f.attrs["mat"] = MAT_NAME
        f.attrs["layer"] = LAYER_NAME

    for piece in pieces:
        face([P(s_end(b), b, z) for b, z in piece])
        face([P(s_start(b), b, z) for b, z in reversed(piece)])
    n = len(outline)
    for i in range(n):
        j = (i + 1) % n
        (bi, zi), (bj, zj) = outline[i], outline[j]
        face([P(s_start(bi), bi, zi), P(s_start(bj), bj, zj),
              P(s_end(bj), bj, zj), P(s_end(bi), bi, zi)])
    return mesh


def _sig(ge, p, ends=None) -> str:
    def r(pl):
        return None if pl is None else tuple(
            round(v, 5) for pair in pl for v in pair)
    ends = ends or {}
    return repr((tuple(round(v, 5) for v in ge["A"]),
                 tuple(round(v, 5) for v in ge["u"]),
                 round(ge["L"], 5), round(ge["th"], 5),
                 round(ge["centre"], 5), sorted(p.items()),
                 r(ends.get("s")), r(ends.get("e"))))


CORNER_TOL = 0.15


def _end_point(ge, e):
    ax, ay, _az = ge["A"]
    ux, uy = ge["u"]
    if e == 0:
        return (ax, ay), (ux, uy)
    return (ax + ux * ge["L"], ay + uy * ge["L"]), (-ux, -uy)


def _corner_plane(ge_i, e_i, ge_j, e_j):
    (ci, di), (cj, dj) = _end_point(ge_i, e_i), _end_point(ge_j, e_j)
    pi = (ci[0] + ge_i["n"][0] * ge_i["centre"],
          ci[1] + ge_i["n"][1] * ge_i["centre"])
    pj = (cj[0] + ge_j["n"][0] * ge_j["centre"],
          cj[1] + ge_j["n"][1] * ge_j["centre"])
    tol = max(ge_i["th"], ge_j["th"]) + CORNER_TOL
    cross = di[0] * dj[1] - di[1] * dj[0]
    dot = di[0] * dj[0] + di[1] * dj[1]
    if abs(cross) < 1e-6:
        if dot < 0 and math.hypot(pi[0] - pj[0], pi[1] - pj[1]) <= CORNER_TOL:
            return (ci, (di[0], di[1]))
        return None
    t = ((pj[0] - pi[0]) * dj[1] - (pj[1] - pi[1]) * dj[0]) / cross
    P0 = (pi[0] + di[0] * t, pi[1] + di[1] * t)
    if (math.hypot(P0[0] - pi[0], P0[1] - pi[1]) > tol
            or math.hypot(P0[0] - pj[0], P0[1] - pj[1]) > tol):
        return None
    bx, by = di[0] + dj[0], di[1] + dj[1]
    bl = math.hypot(bx, by)
    if bl < 1e-6:
        return None
    bx, by = bx / bl, by / bl
    return (P0, (-by, bx))


def _corner_ends(entries):
    out = {}
    for k, ent in enumerate(entries):
        for e in (0, 1):
            cands = []
            for k2, ent2 in enumerate(entries):
                if k2 == k:
                    continue
                for e2 in (0, 1):
                    pl = _corner_plane(ent[3], e, ent2[3], e2)
                    if pl is not None:
                        cands.append(pl)
            if len(cands) == 1:
                out.setdefault(id(ent[0]), {})["s" if e == 0 else "e"] = cands[0]
    return out


def fondazione_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "wname" in data else None


def _part(mesh):
    from core.group import Group
    part = Group(mesh, name=tr("Trave rovescia"))
    part.component = False
    return part


def apply_to_wall(scene, wall_group, ge, p) -> None:
    d = {"wname": wall_group.name, "wchain": _wchain(wall_group),
         "p": dict(p), "sig": ""}
    mesh = fondazione_mesh(ge, p)
    done = False
    index = _wall_index(scene)
    for g in scene.groups:
        old = fondazione_data(g)
        if old is not None and _owner(index, old) is wall_group:
            g.children = [_part(mesh)]
            _ifc.tag(g, "IfcFooting")
            ext = dict(g.ext or {})
            ext[KEY] = d
            g.ext = ext
            done = True
            break
    if not done:
        from core.group import Group
        if not any(ly.name == LAYER_NAME for ly in scene.layers):
            from core.layers import Layer
            scene.layers.append(Layer(LAYER_NAME))
        name = tr("Trave rovescia {0}").format(wall_group.name)
        g = Group(name=name)
        g.adopt([_part(mesh)])
        g.component = False
        g.layer = LAYER_NAME
        _ifc.tag(g, "IfcFooting", name)
        g.ext = {KEY: d}
        scene.groups.append(g)
    update_fondazioni(scene)


def update_fondazioni(scene) -> int:
    index = _wall_index(scene)
    entries = []
    for g in scene.groups:
        d = fondazione_data(g)
        if d is None:
            continue
        wg = _owner(index, d)
        ge = _geom(wg) if wg is not None else None
        if ge is not None:
            entries.append((g, d, wg, ge))
    corners = _corner_ends(entries)
    changed = 0
    for g, d, _wg, ge in entries:
        ends = corners.get(id(g))
        sig = _sig(ge, d["p"], ends)
        if sig == d.get("sig"):
            continue
        g.children = [_part(fondazione_mesh(ge, d["p"], ends))]
        _ifc.tag(g, "IfcFooting")
        ext = dict(g.ext or {})
        ext[KEY] = dict(d, sig=sig)
        g.ext = ext
        changed += 1
    return changed


def _disegno_trave(p):
    r, t, dim, ext = muri._r, muri._t, muri._dim, muri._ext
    t(p, 10, 12, tr("Sezione"), size=9)
    r(p, 70, 20, 100, 70, muri._C_CORPO)
    r(p, 70, 70, 100, 100, muri._C_CORPO)
    r(p, 30, 100, 140, 130, muri._C_CORPO)
    dim(p, 30, 142, 140, 142, "B", -1)
    dim(p, 150, 100, 150, 130, "H", 1)
    dim(p, 56, 70, 56, 100, "Hc", -1)
    dim(p, 70, 62, 100, 62, "Wc", 1)
    t(p, 30, 12 + 160, tr("rettangolare"), size=8)
    p.setPen(QPen(muri._C_LINEA, 1.2))
    p.setBrush(muri._C_CORPO)
    from PySide6.QtGui import QPolygonF
    p.drawRect(260, 20, 30, 50)
    p.drawPolygon(QPolygonF([QPointF(260, 70), QPointF(290, 70),
                             QPointF(290, 100), QPointF(360, 112),
                             QPointF(360, 130), QPointF(190, 130),
                             QPointF(190, 112), QPointF(260, 100)]))
    dim(p, 372, 112, 372, 130, "He", 1)
    t(p, 220, 12 + 160, tr("rastremata"), size=8)


def _spin(value, lo, hi):
    s = LengthSpin()
    s.setDecimals(3)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


def ask_params(parent, cur: dict, title: str, scene=None, creating=False):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(muri._Schema(_disegno_trave))
    tipo = QComboBox()
    for key, label in TYPES:
        tipo.addItem(label, key)
    tipo.setCurrentIndex(max(0, tipo.findData(cur["tipo"])))
    B = _spin(cur["B"], 0.05, 20.0)
    H = _spin(cur["H"], 0.05, 5.0)
    Hc = _spin(cur["Hc"], 0.0, 5.0)
    Wc = _spin(cur["Wc"], 0.0, 5.0)
    He = _spin(cur["He"], 0.02, 5.0)
    E = _spin(cur["E"], 0.0, 5.0)
    dz = _spin(cur.get("dz", 0.0), -50.0, 50.0)
    form.addRow(tr("Tipo di suola"), tipo)
    ws = {"tipo": tipo, "B": B, "H": H, "Hc": Hc, "Wc": Wc, "He": He,
          "E": E, "dz": dz}
    _get, _set = _tipi.widgets_io(ws)
    tbar = _tipi.TypeBar(dlg, form, "trave_rovescia", cur, _get, _set,
                         scene, creating=creating)
    form.addRow(tr("Distanza dalla base del muro / del piano (dz) (m)"), dz)
    form.addRow(tr("Larghezza suola (B) (m)"), B)
    form.addRow(tr("Altezza suola (H) (m)"), H)
    form.addRow(tr("Altezza colletto (Hc) (m)"), Hc)
    form.addRow(tr("Larghezza colletto (Wc) (m) - 0 = spessore del muro"), Wc)
    form.addRow(tr("Spessore al bordo (He) (m) - solo rastremata"), He)
    form.addRow(tr("Sporgenza alle estremita' del muro (E) (m)"), E)
    scroll_form(dlg, lay, form)

    def sync() -> None:
        on = tipo.currentData() == "tap"
        He.setEnabled(on)
        lbl = form.labelForField(He)
        if lbl is not None:
            lbl.setEnabled(on)

    tipo.currentIndexChanged.connect(lambda _i: sync())
    sync()
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return None
    return tbar.result(_get())


class TraveRovesciaTool(Tool):
    name = tr("Trave rovescia")
    shortcut = None
    description = tr("Fondazione a trave rovescia sotto i muri cliccati.")

    def __init__(self) -> None:
        self._entering = False
        self._hover = None

    def on_activate(self, viewport) -> None:
        self._vp = viewport
        if self._entering:
            self._hover = None
            viewport.flash_status(
                tr("Trave rovescia: clic su un muro per applicarla · Esc = esci"),
                6000)
            return
        p = ask_params(viewport.window(), _params(), tr("Trave rovescia"),
                       viewport.scene, creating=True)
        if p is None:
            return
        for k, v in p.items():
            setattr(_Settings, k, v)
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def on_deactivate(self, viewport) -> None:
        self._hover = None

    def on_cancel(self, viewport) -> None:
        self._hover = None
        viewport.update()

    def _exit(self, viewport) -> None:
        self._hover = None
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
            self._exit(viewport)
            return True
        return False

    def on_hover(self, ctx: ToolContext) -> None:
        g, ge = wall_at(ctx.viewport.scene, ctx.world)
        self._hover = (g, ge) if g is not None else None
        ctx.viewport.update()

    def rubber_band_lines(self):
        if not self._hover:
            return []
        _g, ge = self._hover
        p = _params()
        P = _mapper(ge, p)
        outline, _pieces = _profile(ge, p)
        s0, s1 = -p["E"], ge["L"] + p["E"]
        lines = []
        n = len(outline)
        for i in range(n):
            (bi, zi), (bj, zj) = outline[i], outline[(i + 1) % n]
            lines.append((P(s0, bi, zi), P(s0, bj, zj)))
            lines.append((P(s1, bi, zi), P(s1, bj, zj)))
            lines.append((P(s0, bi, zi), P(s1, bi, zi)))
        return lines

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        if getattr(vp.scene, "edit_group", None) is not None:
            vp.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        g, ge = wall_at(vp.scene, ctx.world)
        if g is None:
            vp.flash_status(
                tr("Trave rovescia: clicca su un muro dritto"), 3000)
            return
        p = _params()

        def mutate(scene):
            apply_to_wall(scene, g, ge, p)

        vp.history.execute(muri.MuriCommand(mutate))
        vp.notify_scene_changed()
        vp.flash_status(tr("Trave rovescia applicata al muro"), 2500)
        vp.update()


def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(200, 198, 190))
    p.drawRect(19, 4, 10, 16)
    p.setBrush(QColor(150, 148, 140))
    p.drawRect(19, 20, 10, 8)
    p.drawRect(6, 28, 36, 12)
    p.end()
    return QIcon(pm)


def _selected_fondazioni(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and fondazione_data(g) is not None and g not in out:
            out.append(g)
    return out


def edit_fondazioni(viewport, groups=None) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    groups = groups or _selected_fondazioni(scene)
    if not groups:
        viewport.flash_status(tr("Seleziona una trave rovescia"), 3000)
        return
    cur = dict(_params())
    cur.update(fondazione_data(groups[0])["p"])
    cur["tipo_id"] = fondazione_data(groups[0])["p"].get("tipo_id")
    p = ask_params(viewport.window(), cur, tr("Modifica trave rovescia"),
                   scene)
    if p is None:
        return
    st = _tipi.resolve_edit(viewport.window(), scene, "trave_rovescia", p)
    if st == "cancel":
        return

    def _set_p(g, q):
        ext = dict(g.ext or {})
        ext[KEY] = dict(fondazione_data(g), p=dict(q), sig="")
        g.ext = ext

    def mutate(sc):
        for g in groups:
            _set_p(g, p)
        if st == "type":
            _tipi.update_instances(sc, "trave_rovescia", p["tipo_id"], _set_p)
        update_fondazioni(sc)

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("{0} travi rovesce aggiornate").format(len(groups)),
                          3000)


def _hook_double_click(vp) -> None:
    if getattr(vp, "_myhouse_trave_dbl", False):
        return
    original = vp.begin_group_edit

    def begin_group_edit(group, *args, **kwargs):
        g = getattr(group, "owner", None) or group
        if fondazione_data(g) is None:
            return original(group, *args, **kwargs)
        from PySide6.QtCore import QTimer
        try:
            vp.scene.select([g])
        except Exception:
            vp.scene.selection.clear()
            vp.scene.selection.add(g)
        vp.update()
        QTimer.singleShot(0, lambda: edit_fondazioni(vp, [g]))

    vp.begin_group_edit = begin_group_edit
    vp._myhouse_trave_dbl = True


def _start_watcher(app) -> None:
    timer = QTimer(app.window)
    timer.setInterval(300)

    def tick():
        try:
            vp = app.viewport
            scene = vp.scene
            if getattr(scene, "edit_group", None) is not None:
                return
            if update_fondazioni(scene):
                scene.version += 1
                vp.notify_scene_changed()
                vp.update()
        except Exception:
            pass

    timer.timeout.connect(tick)
    timer.start()
    app._trave_rovescia_timer = timer


def register(api) -> None:
    api.add_button(tr("Trave rovescia"),
                   tr("Fondazione a trave rovescia sotto i muri"),
                   _icon(), api.run_tool(TraveRovesciaTool()))
    _start_watcher(api.app)
    app = api.app
    _hook_double_click(api.window.viewport)
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        from PySide6.QtCore import QTimer

        def context(menu, selection) -> None:
            if not _selected_fondazioni(app.viewport.scene):
                return
            menu.addSeparator()
            menu.addAction(
                tr("Modifica trave rovescia…"),
                lambda: QTimer.singleShot(
                    0, lambda: edit_fondazioni(app.viewport)))

        add_ctx(context)
