# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._scroll import scroll_form
from ._lingua import tr
from ._imperial import LengthSpin

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPen, QVector3D
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QVBoxLayout,
)

from core import bim
from . import _ifc
from tools.base import Tool, ToolContext

from . import muri
from .volta import V, _orienta, _nascondi_spigoli_lisci

ORDER = 42
LAYER_NAME = "Archi"
KEY = "myhouse_arco"
COLOR_ARCO = (0.80, 0.62, 0.40)
PASSO_ANGOLO = math.pi / 24.0

LATI = (
    ("CENTRO", tr("Centro (a cavallo della corda)")),
    ("SINISTRA", tr("Sinistra della corda 1 → 2")),
    ("DESTRA", tr("Destra della corda 1 → 2")),
)


class _Settings:
    z = 2.10
    h = 0.50
    tutto = True
    giu = False
    l1 = 0.30
    l2 = 0.30
    dentro = False
    lato = "CENTRO"
    ortho = True


def _telaio(d):
    (x1, y1), (x2, y2) = d["pts"][0], d["pts"][1]
    c = math.hypot(x2 - x1, y2 - y1)
    if c < 0.02:
        return None
    ex, ey = (x2 - x1) / c, (y2 - y1) / c
    return {"c": c, "e": (ex, ey), "n": (-ey, ex),
            "mid": ((x1 + x2) / 2.0, (y1 + y2) / 2.0)}


def arco_freccia(d, c):
    h = c / 2.0 if d.get("tutto") else abs(float(d.get("h", 0.0)))
    if h < 1e-3 or h > 10.0 * c:
        return None
    return -h if d.get("giu") else h


def _profilo(c, h):
    ah = abs(h)
    sgn = 1.0 if h > 0 else -1.0
    R = (c * c / 4.0 + ah * ah) / (2.0 * ah)
    cos_a = max(-1.0, min(1.0, (R - ah) / R))
    return R, sgn * (ah - R), sgn, math.acos(cos_a)


def _raggi(R, l2, dentro):
    if dentro:
        return max(R - l2, 5e-3), R
    return R, R + l2


def _fascia(l1, lato):
    if lato == "SINISTRA":
        return 0.0, l1
    if lato == "DESTRA":
        return -l1, 0.0
    return -l1 / 2.0, l1 / 2.0


def _punto(fr, z, s, zl, off):
    return (fr["mid"][0] + fr["e"][0] * s + fr["n"][0] * off,
            fr["mid"][1] + fr["e"][1] * s + fr["n"][1] * off,
            z + zl)


def _passi(alfa):
    return max(6, int(math.ceil(2.0 * alfa / PASSO_ANGOLO)))


def _quote_valide(d):
    return (float(d.get("l1", 0)) >= 0.005 and float(d.get("l2", 0)) >= 0.005)


def arco_geometria(d):
    fr = _telaio(d)
    if fr is None or not _quote_valide(d):
        return None
    h = arco_freccia(d, fr["c"])
    if h is None:
        return None
    R, cz, sgn, alfa = _profilo(fr["c"], h)
    r_in, r_out = _raggi(R, float(d["l2"]), bool(d.get("dentro")))
    da, a = _fascia(float(d["l1"]), d.get("lato", "CENTRO"))
    z = float(d["z"])
    n = _passi(alfa)
    verts, anelli = [], []
    for i in range(n + 1):
        th = -alfa + 2.0 * alfa * i / n
        sn, cs = math.sin(th), math.cos(th)
        ring = []
        for r, off in ((r_in, da), (r_in, a), (r_out, a), (r_out, da)):
            x, y, zz = _punto(fr, z, r * sn, cz + sgn * r * cs, off)
            verts.append(V(x, y, zz))
            ring.append(len(verts) - 1)
        anelli.append(ring)
    facce = []
    for i in range(n):
        A, B = anelli[i], anelli[i + 1]
        for k in range(4):
            k2 = (k + 1) % 4
            facce.append((A[k], A[k2], B[k2], B[k]))
    facce.append(tuple(reversed(anelli[0])))
    facce.append(tuple(anelli[-1]))
    return verts, _orienta(verts, facce)


def arco_polilinee(d):
    fr = _telaio(d)
    if fr is None or not _quote_valide(d):
        return []
    h = arco_freccia(d, fr["c"])
    if h is None:
        return []
    R, cz, sgn, alfa = _profilo(fr["c"], h)
    r_in, r_out = _raggi(R, float(d["l2"]), bool(d.get("dentro")))
    da, a = _fascia(float(d["l1"]), d.get("lato", "CENTRO"))
    z = float(d["z"])
    n = _passi(alfa)
    curve = {}
    for off in (da, a):
        for r in (r_in, r_out):
            pts = []
            for i in range(n + 1):
                th = -alfa + 2.0 * alfa * i / n
                pts.append(_punto(fr, z, r * math.sin(th),
                                  cz + sgn * r * math.cos(th), off))
            curve[(off, r)] = pts
    linee = list(curve.values())
    for r in (r_in, r_out):
        for idx in (0, -1):
            linee.append([curve[(da, r)][idx], curve[(a, r)][idx]])
    for off in (da, a):
        for idx in (0, -1):
            linee.append([curve[(off, r_in)][idx], curve[(off, r_out)][idx]])
    return linee


def arco_mesh(d):
    from core.mesh import Mesh
    ris = arco_geometria(d)
    if ris is None:
        return None
    verts, facce = ris
    mesh = Mesh()
    for f in facce:
        fc = mesh.add_face([QVector3D(verts[i].x, verts[i].y, verts[i].z) for i in f])
        fc.attrs["layer"] = LAYER_NAME
        muri.paint_face(fc, d.get("col", COLOR_ARCO), d.get("tex"))
    _nascondi_spigoli_lisci(mesh, verts, facce)
    return mesh


def arco_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "pts" in data else None


def _arco_part(d):
    from core.group import Group
    m = arco_mesh(d)
    if m is None:
        return None
    part = Group(m, name=tr("Arco"))
    part.component = False
    return part


def rebuild_arco(group, d) -> bool:
    part = _arco_part(d)
    if part is None:
        return False
    group.children = [part]
    _ifc.tag(group, "IfcBeam")
    ext = dict(group.ext or {})
    ext[KEY] = dict(d)
    group.ext = ext
    return True


def build_arco(scene, d, name) -> bool:
    from core.group import Group
    part = _arco_part(d)
    if part is None:
        return False
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    g = Group(name=name)
    g.adopt([part])
    g.component = False
    g.layer = LAYER_NAME
    try:
        _ifc.tag(g, "IfcBeam", name)
    except Exception:
        try:
            _ifc.tag(g, "IfcBuildingElementProxy", name)
        except Exception:
            pass
    g.ext = {KEY: d}
    scene.groups.append(g)
    return True


def _spin(value, lo, hi):
    s = LengthSpin()
    s.setDecimals(3)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


def _disegno_arco(p):
    from PySide6.QtGui import QPainterPath
    r, t, dim, ext = muri._r, muri._t, muri._dim, muri._ext
    line = muri._C_LINEA
    t(p, 10, 12, tr("Prospetto"), size=10)
    p.setPen(QPen(line, 1.5))
    p.drawLine(QPointF(10, 150), QPointF(226, 150))
    muri._hatch(p, 10, 150, 226, 156)
    r(p, 30, 100, 50, 150, muri._C_CORPO)
    r(p, 190, 100, 210, 150, muri._C_CORPO)
    cx, R, h, sp = 120.0, 76.94, 45.0, 14.0
    cy = 100.0 - h + R
    a = math.degrees(math.asin(70.0 / R))
    Ro, Ri = R + sp, R
    path = QPainterPath()
    path.arcTo(QRectF(cx - Ro, cy - Ro, 2 * Ro, 2 * Ro), 90 + a, -2 * a)
    path.arcTo(QRectF(cx - Ri, cy - Ri, 2 * Ri, 2 * Ri), 90 - a, 2 * a)
    path.closeSubpath()
    p.setPen(QPen(line, 1.2))
    p.setBrush(muri._C_LEGNO)
    p.drawPath(path)
    ext(p, 14, 100, 226, 100)
    dim(p, 120, 55, 120, 100, "h", 1)
    dim(p, 136, 42, 136, 56, "L2", 1)
    dim(p, 22, 100, 22, 150, "z", -1)
    t(p, 44, 116, "1", muri._C_QUOTA, 12, True)
    t(p, 192, 116, "2", muri._C_QUOTA, 12, True)
    t(p, 250, 12, tr("Sezione"), size=10)
    r(p, 270, 26, 370, 56, muri._C_LEGNO)
    dim(p, 270, 26, 370, 26, "L1", 1)
    dim(p, 382, 26, 382, 56, "L2", 1)
    t(p, 250, 92, tr("Pianta"), size=10)
    r(p, 270, 104, 400, 134, muri._C_LEGNO)
    ext(p, 262, 119, 408, 119)
    t(p, 256, 140, "1", muri._C_QUOTA, 12, True)
    t(p, 402, 140, "2", muri._C_QUOTA, 12, True)
    dim(p, 414, 104, 414, 134, "L1", 1)


def ask_arco(parent, cur: dict, title=None):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title or tr("Arco"))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(muri._Schema(_disegno_arco))
    z = _spin(cur["z"], -100.0, 1000.0)
    tutto = QCheckBox(tr("Arco a tutto sesto (freccia = corda / 2)"))
    tutto.setChecked(bool(cur.get("tutto")))
    h = _spin(cur["h"], 0.001, 1000.0)
    giu = QCheckBox(tr("Arco rovesciato (curva verso il basso)"))
    giu.setChecked(bool(cur.get("giu")))
    l1 = _spin(cur["l1"], 0.005, 100.0)
    l2 = _spin(cur["l2"], 0.005, 100.0)
    dentro = QCheckBox(tr("Spessore verso l'interno (rispetto ai punti cliccati)"))
    dentro.setChecked(bool(cur.get("dentro")))
    lato = QComboBox()
    for k, nome in LATI:
        lato.addItem(nome, k)
    lato.setCurrentIndex(max(0, lato.findData(cur.get("lato", "CENTRO"))))
    form.addRow(tr("Altezza da terra, quota d'imposta (z) (m)"), z)
    form.addRow(tutto)
    form.addRow(tr("Freccia (h) (m)"), h)
    form.addRow(giu)
    form.addRow(tr("Profondità (L1) (m)"), l1)
    form.addRow(tr("Spessore dell'arco (L2) (m)"), l2)
    form.addRow(dentro)
    form.addRow(tr("Lato della profondità"), lato)
    scroll_form(dlg, lay, form)
    tutto.toggled.connect(lambda on: h.setEnabled(not on))
    h.setEnabled(not tutto.isChecked())
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return None
    return {"z": z.value(), "tutto": tutto.isChecked(), "h": h.value(),
            "giu": giu.isChecked(), "l1": l1.value(), "l2": l2.value(),
            "dentro": dentro.isChecked(), "lato": lato.currentData()}


class ArcoTool(Tool):
    name = tr("Arco")
    shortcut = None
    description = tr("Crea un arco 3D (a tutto sesto, ribassato o rialzato) su 2 punti.")
    vcb_label = tr("Freccia")

    def __init__(self) -> None:
        self._entering = False
        self.points: list[tuple[float, float]] = []
        self.hover = None

    def on_activate(self, viewport) -> None:
        if self._entering:
            self.points, self.hover = [], None
            viewport.flash_status(self._help(), 7000)
            return
        res = ask_arco(viewport.window(), self._cur())
        if res is None:
            return
        for k, v in res.items():
            setattr(_Settings, k, v)
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    @staticmethod
    def _cur() -> dict:
        return {k: getattr(_Settings, k)
                for k in ("z", "h", "tutto", "giu", "l1", "l2", "dentro", "lato")}

    @staticmethod
    def _help() -> str:
        return tr("Arco: clic sui 2 estremi (intradosso), poi clic = crea · numero + Invio = "
                  "freccia · S = tutto sesto · Spazio = rovescia · O = ortogonale · "
                  "Backspace = annulla punto · Esc = esci")

    def on_deactivate(self, viewport) -> None:
        self.points, self.hover = [], None

    def on_cancel(self, viewport) -> None:
        self.points, self.hover = [], None
        viewport.update()

    def _exit(self, viewport) -> None:
        self.points, self.hover = [], None
        viewport.update()
        back = getattr(viewport.window(), "activate_select_tool", None)
        if callable(back):
            back()

    def context_menu(self, viewport, pos) -> bool:
        if self.points:
            self.points = []
            viewport.update()
        else:
            self._exit(viewport)
        return True

    def claims_key(self, key: int, modifiers) -> bool:
        if modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        if getattr(self, "_vp", None) is not None and \
                (getattr(self._vp, "_value_buffer", "") or ""):
            return False
        return key in (Qt.Key_Escape, Qt.Key_O, Qt.Key_F8, Qt.Key_S, Qt.Key_Space) or (
            key == Qt.Key_Backspace and bool(self.points))

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
        if key == Qt.Key_S:
            _Settings.tutto = not _Settings.tutto
            viewport.flash_status(
                tr("Tutto sesto ") + (tr("attivo") if _Settings.tutto
                                      else tr("disattivato")), 2000)
            viewport.update()
            return True
        if key == Qt.Key_Space:
            _Settings.giu = not _Settings.giu
            viewport.flash_status(
                tr("Arco verso il basso") if _Settings.giu else tr("Arco verso l'alto"), 2000)
            viewport.update()
            return True
        if key == Qt.Key_Backspace and self.points:
            self.points.pop()
            viewport.update()
            return True
        return False

    def _constrain(self, x, y):
        if not _Settings.ortho or not self.points:
            return (x, y)
        lx, ly = self.points[-1]
        if abs(x - lx) >= abs(y - ly):
            return (x, ly)
        return (lx, y)

    def on_hover(self, ctx: ToolContext) -> None:
        self._vp = ctx.viewport
        self.hover = self._constrain(ctx.world.x(), ctx.world.y())
        ctx.viewport.update()

    def _dati(self, pts=None):
        d = self._cur()
        d["pts"] = [list(p) for p in (pts if pts is not None else self.points)]
        d["col"] = COLOR_ARCO
        return d

    def _crea(self, viewport) -> None:
        d = self._dati()
        self.points = []
        if arco_geometria(d) is None:
            viewport.flash_status(
                tr("Impossibile creare l'arco: punti troppo vicini o freccia nulla"), 4000)
            viewport.update()
            return
        name = tr("Arco")

        def mutate(scene):
            build_arco(scene, d, name)

        viewport.history.execute(muri.MuriCommand(mutate))
        viewport.notify_scene_changed()
        viewport.flash_status(tr("Arco creato"), 3000)
        viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        self._vp = vp
        if getattr(vp.scene, "edit_group", None) is not None:
            vp.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        if len(self.points) == 2:
            self._crea(vp)
            return
        x, y = self._constrain(ctx.world.x(), ctx.world.y())
        if self.points and math.hypot(x - self.points[-1][0], y - self.points[-1][1]) < 1e-4:
            return
        self.points.append((x, y))
        vp.update()

    def on_value(self, viewport, value) -> bool:
        if len(self.points) != 2 or isinstance(value, tuple):
            return False
        if abs(value) < 1e-3:
            return False
        _Settings.h = abs(float(value))
        _Settings.tutto = False
        _Settings.giu = _Settings.giu if value > 0 else not _Settings.giu
        self._crea(viewport)
        return True

    def status_clause(self) -> str:
        if len(self.points) == 2:
            return tr("Clic = crea l'arco · numero + Invio = freccia · S = tutto sesto · "
                      "Spazio = rovescia")
        if len(self.points) == 1:
            return tr("Clic sul secondo estremo dell'arco")
        return tr("Clic sul primo estremo dell'arco")

    def draw_overlay(self, viewport, painter) -> None:
        try:
            self._draw(viewport, painter)
        except Exception:
            pass

    def _draw(self, viewport, painter) -> None:
        if not self.points:
            return
        z = _Settings.z
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(0, 170, 255), 2))

        def px(pt):
            return viewport._world_to_pixel(QVector3D(*pt))

        def poly(pts):
            pix = [px(q) for q in pts]
            for a, b in zip(pix, pix[1:]):
                if a is not None and b is not None:
                    painter.drawLine(QPointF(*a), QPointF(*b))

        if len(self.points) == 1 and self.hover is not None:
            poly([(*self.points[0], z), (*self.hover, z)])
        elif len(self.points) == 2:
            poly([(*self.points[0], z), (*self.points[1], z)])
            for pl in arco_polilinee(self._dati()):
                poly(pl)
        painter.setBrush(QColor(220, 30, 30))
        for q in self.points:
            p = px((q[0], q[1], z))
            if p is not None:
                painter.drawEllipse(QPointF(*p), 4, 4)
        painter.restore()


def _selected_archi(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and arco_data(g) is not None and g not in out:
            out.append(g)
    return out


def edit_arco(viewport, group) -> None:
    if getattr(viewport.scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    d = arco_data(group)
    if d is None:
        return
    res = ask_arco(viewport.window(), d, tr("Modifica arco"))
    if res is None:
        return
    q = dict(d)
    q.update(res)
    if arco_geometria(q) is None:
        viewport.flash_status(tr("Impossibile aggiornare l'arco"), 3000)
        return

    def mutate(sc):
        rebuild_arco(group, q)

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("Arco aggiornato"), 3000)


def _hook_double_click(vp) -> None:
    if getattr(vp, "_myhouse_arco_dbl", False):
        return
    original = vp.begin_group_edit

    def begin_group_edit(group, *args, **kwargs):
        g = getattr(group, "owner", None) or group
        if arco_data(g) is None:
            return original(group, *args, **kwargs)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: edit_arco(vp, g))

    vp.begin_group_edit = begin_group_edit
    vp._myhouse_arco_dbl = True


def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(204, 158, 102))
    path = QPainterPath()
    path.arcTo(QRectF(5, 6, 38, 38), 180, -180)
    path.arcTo(QRectF(13, 14, 22, 22), 0, 180)
    path.closeSubpath()
    p.drawPath(path)
    p.setBrush(QColor(236, 236, 230))
    p.drawRect(5, 25, 8, 17)
    p.drawRect(35, 25, 8, 17)
    p.end()
    return QIcon(pm)


def register(api) -> None:
    tool = ArcoTool()
    api.add_button(tr("Arco"), tr("Crea un arco 3D (tutto sesto, ribassato o rialzato)"),
                   _icon(), api.run_tool(tool), group="Archi e volte")
    app = api.app
    _hook_double_click(api.window.viewport)
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        from PySide6.QtCore import QTimer

        def context(menu, selection) -> None:
            archi = _selected_archi(app.viewport.scene)
            if not archi:
                return
            menu.addSeparator()
            menu.addAction(
                tr("Modifica arco…"),
                lambda: QTimer.singleShot(0, lambda: edit_arco(app.viewport, archi[0])))

        add_ctx(context)
    add_kind = getattr(app, "add_outliner_kind", None)
    if add_kind is not None:
        def kind(group):
            d = arco_data(group)
            if d is None:
                return None
            from ._imperial import fmt_len
            fr = _telaio(d)
            h = arco_freccia(d, fr["c"]) if fr else None
            return {"type": tr("Arco"),
                    "props": [(tr("Freccia"), fmt_len(abs(h)) if h else "-"),
                              (tr("Altezza da terra"), fmt_len(d["z"])),
                              (tr("Profondità"), fmt_len(d["l1"])),
                              (tr("Spessore"), fmt_len(d["l2"]))]}
        add_kind(kind)
