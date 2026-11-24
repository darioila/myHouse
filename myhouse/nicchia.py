# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr
from ._scroll import scroll_form

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPen, QVector3D
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QSpinBox, QVBoxLayout,
)

from ._imperial import fmt_len
from tools.base import Tool, ToolContext

from . import muri

COLOR = QColor(255, 140, 0)
ANCHORS = (("C", tr("Centro")), ("BL", tr("Basso sinistra")), ("BR", tr("Basso destra")),
           ("TL", tr("Alto sinistra")), ("TR", tr("Alto destra")))
COLOR_EDIT = QColor(0, 200, 120)
SNAP_DIST = 0.30


class _Settings:
    used = False
    width = 0.80
    height = 1.20
    sill = 0.90
    depth = 0.15
    shelves = 0
    shelf_t = 0.03
    kind = "M"
    rn = 10
    rew = 0.08
    ra = 0.58
    rq = 0.08
    rd = 0.10
    anchor = "C"


def _spin(value, lo, hi):
    return muri._spin(value, lo, hi)


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


def _disegno_nicchia(p, kind="M"):
    r, t, dim, ext = muri._r, muri._t, _dim_grande, muri._ext
    t(p, 30, 12, tr("Prospetto del muro"), size=12)
    r(p, 30, 20, 220, 150, muri._C_CORPO)
    r(p, 80, 50, 160, 120, muri._C_BIANCO)
    if kind == "T":
        for i in range(6):
            r(p, 96 + i * 9.5, 62, 96 + i * 9.5 + 8, 111, muri._C_BIANCO)
        r(p, 94, 58, 154, 63, muri._C_BIANCO)
        r(p, 90, 58, 94, 63, muri._C_ANTA)
        r(p, 154, 58, 158, 63, muri._C_ANTA)
        r(p, 90, 108, 94, 113, muri._C_ANTA)
        r(p, 154, 108, 158, 113, muri._C_ANTA)
        t(p, 118, 76, "N", muri._C_QUOTA, 14, True)
        dim(p, 96, 134, 105, 134, "e", 1)
        dim(p, 83, 58, 83, 113, "a", 1)
        dim(p, 83, 113, 83, 120, "d", -1)
    else:
        for y in (73, 96):
            r(p, 80, y, 160, y + 4, muri._C_LEGNO)
    p.setPen(QPen(muri._C_LINEA, 1.5))
    p.drawLine(QPointF(14, 150), QPointF(236, 150))
    muri._hatch(p, 14, 150, 236, 156)
    dim(p, 80, 40, 160, 40, "W", 1)
    dim(p, 68, 50, 68, 120, "H", -1)
    ext(p, 160, 120, 190, 120)
    dim(p, 190, 120, 190, 150, "h")
    p.setPen(QPen(muri._C_LINEA, 1))
    p.setBrush(muri._C_QUOTA)
    for x, y in ((80, 50), (160, 50), (80, 120), (160, 120), (120, 85)):
        p.drawEllipse(QPointF(x, y), 2.5, 2.5)
    t(p, 100, 165, tr("● punti di presa (A)"), size=11)
    t(p, 290, 12, tr("Sezione"), size=12)
    r(p, 290, 20, 390, 150, muri._C_CORPO)
    r(p, 290, 50, 350, 120, muri._C_BIANCO)
    if kind == "T":
        r(p, 314, 58, 346, 112, muri._C_BIANCO)
        r(p, 334, 58, 346, 63, muri._C_ANTA)
        r(p, 334, 107, 346, 112, muri._C_ANTA)
        dim(p, 314, 128, 346, 128, "q", 1)
    else:
        for y in (73, 96):
            r(p, 290, y, 350, y + 5, muri._C_LEGNO)
    p.setPen(QPen(muri._C_LINEA, 1.5))
    p.drawLine(QPointF(270, 150), QPointF(410, 150))
    muri._hatch(p, 270, 150, 410, 156)
    dim(p, 290, 142 if kind == "T" else 136, 350, 142 if kind == "T" else 136, "p", 1)
    if kind != "T":
        dim(p, 280, 73, 280, 78, "t", -1)
    dim(p, 400, 50, 400, 120, "H")
    dim(p, 400, 120, 400, 150, "h")
    t(p, 296, 38, tr("faccia muro"), size=11)


def _dialog(parent, v, title, ok_text, deletable=False, anchor=None):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    mode = {"k": v.get("kind", "M")}
    sch = muri._Schema(lambda pp: _disegno_nicchia(pp, mode["k"]))
    form.addRow(sch)
    w = _spin(v["width"], 0.05, 20.0)
    h = _spin(v["height"], 0.05, 20.0)
    s = _spin(v["sill"], 0.0, 20.0)
    p = _spin(v["depth"], 0.01, 2.0)
    form.addRow(tr("Larghezza (W) (m)"), w)
    form.addRow(tr("Altezza (H) (m)"), h)
    form.addRow(tr("Altezza da terra (h) (m)"), s)
    form.addRow(tr("Profondità (p) (m)"), p)
    kd = QComboBox()
    kd.addItem(tr("Mensole"), "M")
    kd.addItem(tr("Termosifone"), "T")
    kd.setCurrentIndex(max(0, kd.findData(v.get("kind", "M"))))
    form.addRow(tr("Dentro la nicchia"), kd)
    nm = QSpinBox()
    nm.setRange(0, 20)
    nm.setValue(v["shelves"])
    st = _spin(v["shelf_t"], 0.005, 0.2)
    form.addRow(tr("N. mensole (n)"), nm)
    form.addRow(tr("Spessore mensole (t) (m)"), st)
    rn = QSpinBox()
    rn.setRange(1, 60)
    rn.setValue(int(v.get("rn", _Settings.rn)))
    rew = _spin(v.get("rew", _Settings.rew), 0.02, 0.5)
    ra = _spin(v.get("ra", _Settings.ra), 0.10, 3.0)
    rq = _spin(v.get("rq", _Settings.rq), 0.02, 0.5)
    rd = _spin(v.get("rd", _Settings.rd), 0.0, 5.0)
    form.addRow(tr("N. elementi termosifone (N)"), rn)
    form.addRow(tr("Larghezza elemento (e) (m)"), rew)
    form.addRow(tr("Altezza termosifone (a) (m)"), ra)
    form.addRow(tr("Profondità termosifone (q) (m)"), rq)
    form.addRow(tr("Distanza dal fondo nicchia (d) (m)"), rd)
    shelf_w, rad_w = (nm, st), (rn, rew, ra, rq, rd)

    def sync() -> None:
        mode["k"] = kd.currentData()
        for ws, on in ((shelf_w, mode["k"] == "M"), (rad_w, mode["k"] == "T")):
            for x in ws:
                x.setVisible(on)
                lab = form.labelForField(x)
                if lab is not None:
                    lab.setVisible(on)
        sch.update()
        dlg.adjustSize()

    kd.currentIndexChanged.connect(lambda _i: sync())
    sync()
    anc = None
    if anchor is not None:
        anc = QComboBox()
        for key, label in ANCHORS:
            anc.addItem(label, key)
        anc.setCurrentIndex(max(0, anc.findData(anchor)))
        form.addRow(tr("Punto di presa (tasto A)"), anc)
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.button(QDialogButtonBox.Ok).setText(ok_text)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    if deletable:
        bd = box.addButton(tr("Elimina nicchia"), QDialogButtonBox.DestructiveRole)
        bd.clicked.connect(lambda: dlg.done(2))
    lay.addWidget(box)
    r = dlg.exec()
    if r == 2:
        return "delete"
    if r != QDialog.Accepted:
        return None
    return {"width": w.value(), "height": h.value(), "sill": s.value(),
            "depth": p.value(), "shelves": nm.value(), "shelf_t": st.value(),
            "kind": kd.currentData(), "rn": rn.value(), "rew": rew.value(),
            "ra": ra.value(), "rq": rq.value(), "rd": rd.value(),
            "anchor": anc.currentData() if anc is not None else None}


def _rad_list(kind, rn, rew, ra, rq, rd):
    return [int(rn), rew, ra, rq, rd] if kind == "T" else None


def ask_settings(parent) -> bool:
    res = _dialog(parent, {"width": _Settings.width, "height": _Settings.height,
                           "sill": _Settings.sill, "depth": _Settings.depth,
                           "shelves": _Settings.shelves, "shelf_t": _Settings.shelf_t,
                           "kind": _Settings.kind, "rn": _Settings.rn, "rew": _Settings.rew,
                           "ra": _Settings.ra, "rq": _Settings.rq, "rd": _Settings.rd},
                  tr("Nicchia"), tr("Inserisci"), anchor=_Settings.anchor)
    if res is None:
        return False
    _Settings.width, _Settings.height = res["width"], res["height"]
    _Settings.sill, _Settings.depth = res["sill"], res["depth"]
    _Settings.shelves, _Settings.shelf_t = res["shelves"], res["shelf_t"]
    _Settings.kind, _Settings.rn, _Settings.rew = res["kind"], res["rn"], res["rew"]
    _Settings.ra, _Settings.rq, _Settings.rd = res["ra"], res["rq"], res["rd"]
    _Settings.anchor = res["anchor"] or "C"
    _Settings.used = True
    return True


def _world_matrix(g):
    m = muri.wall_pose(g)
    gx = getattr(g, "xform", None)
    return gx * m if gx is not None else m


class _Hit:
    __slots__ = ("g", "d", "side", "s", "L", "u", "n", "qface", "M", "inv", "idx", "z")


def _locate(scene, world):
    best, best_dist = None, SNAP_DIST
    for g in scene.groups:
        d = muri.wall_data(g)
        if d is None:
            continue
        M = _world_matrix(g)
        inv, ok = M.inverted()
        if not ok:
            continue
        p = inv.map(QVector3D(world))
        ax, ay = d["a"]
        bx, by = d["b"]
        L = math.hypot(bx - ax, by - ay)
        if L < 1e-6:
            continue
        ux, uy = (bx - ax) / L, (by - ay) / L
        nx, ny = -uy, ux
        s = (p.x() - ax) * ux + (p.y() - ay) * uy
        q = (p.x() - ax) * nx + (p.y() - ay) * ny
        dl, dr = muri.side_offsets(d["th"], d["align"])
        qm = (dl - dr) / 2.0
        z0 = d["z0"]
        dz = max(0.0, z0 - p.z(), p.z() - (z0 + d["h"]))
        dist = math.hypot(math.hypot(max(0.0, -s, s - L),
                                     max(0.0, abs(q - qm) - d["th"] / 2.0)), dz)
        if dist < best_dist:
            best_dist = dist
            h = _Hit()
            h.g, h.d, h.s, h.L, h.M, h.inv = g, d, s, L, M, inv
            h.u, h.n = (ux, uy), (nx, ny)
            h.side = "L" if q >= qm else "R"
            h.qface = dl if h.side == "L" else -dr
            h.z = p.z()
            h.idx = None
            for i, nn in enumerate(d.get("niches") or ()):
                if (nn[5] if len(nn) > 5 else "L") != h.side or not (nn[0] <= s <= nn[1]):
                    continue
                if dz > 0.05 or z0 + nn[2] - 0.02 <= p.z() <= z0 + nn[3] + 0.02:
                    h.idx = i
                    break
            best = h
    return best


def _place(hit):
    m = muri.NICHE_MARGIN
    w = min(_Settings.width, hit.L - 2 * m)
    a = _Settings.anchor
    if a == "C":
        s0 = hit.s - w / 2.0
    else:
        viewer_right_is_u = hit.side == "R"
        s0 = hit.s - w if (a[1] == "R") == viewer_right_is_u else hit.s
    s0 = max(m, min(hit.L - m - w, s0))
    sill = _Settings.sill
    if a != "C":
        z0, zt = hit.d["z0"], hit.z
        if z0 + 0.02 < zt < z0 + hit.d["h"] - 0.02:
            sill = max(0.0, (zt - z0) - (0.0 if a[0] == "B" else _Settings.height))
    return s0, s0 + w, sill


def _depth(hit):
    return min(_Settings.depth, hit.d["th"] - 0.02)


def _corners(hit, s0, s1, sill=None, height=None, depth=None):
    d = hit.d
    ax, ay = d["a"]
    ux, uy = hit.u
    nx, ny = hit.n
    z0 = d["z0"] + (_Settings.sill if sill is None else sill)
    z1 = z0 + (_Settings.height if height is None else height)
    dep = _depth(hit) if depth is None else depth
    sgn = -1.0 if hit.side == "L" else 1.0
    out = []
    for q in (hit.qface, hit.qface + sgn * dep):
        pts = []
        for s, z in ((s0, z0), (s1, z0), (s1, z1), (s0, z1)):
            x = ax + ux * s + nx * q
            y = ay + uy * s + ny * q
            pts.append(hit.M.map(QVector3D(x, y, z)))
        out.append(pts)
    return out


class NicchiaTool(Tool):
    name = tr("Nicchia")
    shortcut = None
    description = tr("Nicchia cieca in un muro (clic sul muro).")
    vcb_label = tr("Larghezza")

    def __init__(self) -> None:
        self._entering = False
        self._vp = None
        self.hit = None

    def on_activate(self, viewport) -> None:
        if self._entering:
            self._vp = viewport
            self.hit = None
            viewport.flash_status(
                tr("Nicchia: clic su un muro · numero = larghezza · "
                   "tasto destro o Esc = esci"), 6000)
            return
        if not ask_settings(viewport.window()):
            return
        self.start_same(viewport)

    def start_same(self, viewport) -> None:
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def on_deactivate(self, viewport) -> None:
        self.hit = None

    def _exit(self, viewport) -> None:
        self.hit = None
        viewport.update()
        back = getattr(viewport.window(), "activate_select_tool", None)
        if callable(back):
            back()

    def on_hover(self, ctx: ToolContext) -> None:
        self.hit = _locate(ctx.viewport.scene, ctx.world)
        ctx.viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        if getattr(vp.scene, "edit_group", None) is not None:
            vp.flash_status(
                tr("Chiudi il gruppo che stai modificando, poi crea la nicchia"), 4000)
            return
        hit = _locate(vp.scene, ctx.world)
        if hit is None:
            vp.flash_status(tr("Clicca su un muro"), 3000)
            return
        if hit.d["th"] < 0.06:
            vp.flash_status(tr("Muro troppo sottile per una nicchia"), 4000)
            return
        if hit.L < 2 * muri.NICHE_MARGIN + 0.05:
            vp.flash_status(tr("Muro troppo corto per una nicchia"), 4000)
            return
        if hit.idx is not None:
            self._edit(vp, hit)
            return
        s0, s1, sill = _place(hit)
        g, side, dep = hit.g, hit.side, _depth(hit)
        lo, hi = sill, sill + _Settings.height

        def mutate(scene):
            muri.add_niche(g, s0, s1, lo, hi, dep, side, _Settings.shelves, _Settings.shelf_t,
                           _Settings.kind,
                           _rad_list(_Settings.kind, _Settings.rn, _Settings.rew,
                                     _Settings.ra, _Settings.rq, _Settings.rd))

        vp.history.execute(muri.MuriCommand(mutate))
        if getattr(vp.history, "last_error", None):
            vp.flash_status(tr("Nicchia: ") + str(vp.history.last_error).split(": ", 1)[-1], 6000)
            return
        vp.notify_scene_changed()
        vp.update()
        vp.flash_status(tr("Nicchia creata"), 2500)

    def _edit(self, vp, hit) -> None:
        g, idx, th, L = hit.g, hit.idx, hit.d["th"], hit.L
        nn = hit.d["niches"][idx]
        side = nn[5] if len(nn) > 5 else "L"
        kind = nn[8] if len(nn) > 8 and nn[8] in ("M", "T") else "M"
        rad = nn[9] if len(nn) > 9 and nn[9] else None
        res = _dialog(vp.window(), {
            "width": nn[1] - nn[0], "height": nn[3] - nn[2], "sill": nn[2],
            "depth": nn[4], "shelves": int(nn[6]) if len(nn) > 6 else 0,
            "shelf_t": nn[7] if len(nn) > 7 else 0.03, "kind": kind,
            "rn": rad[0] if rad else _Settings.rn, "rew": rad[1] if rad else _Settings.rew,
            "ra": rad[2] if rad else _Settings.ra, "rq": rad[3] if rad else _Settings.rq,
            "rd": rad[4] if rad else _Settings.rd},
            tr("Modifica nicchia"), tr("Applica"), True)
        if res is None:
            return
        if res == "delete":
            new = None
        else:
            m = muri.NICHE_MARGIN
            w = min(res["width"], L - 2 * m)
            c = (nn[0] + nn[1]) / 2.0
            s0 = max(m, min(L - m - w, c - w / 2.0))
            new = [s0, s0 + w, res["sill"], res["sill"] + res["height"],
                   min(res["depth"], th - 0.02), side, res["shelves"], res["shelf_t"],
                   res["kind"], _rad_list(res["kind"], res["rn"], res["rew"],
                                          res["ra"], res["rq"], res["rd"])]

        def mutate(scene):
            muri.update_niche(g, idx, new)

        vp.history.execute(muri.MuriCommand(mutate))
        if getattr(vp.history, "last_error", None):
            vp.flash_status(tr("Nicchia: ") + str(vp.history.last_error).split(": ", 1)[-1], 6000)
            return
        vp.notify_scene_changed()
        self.hit = None
        vp.update()
        vp.flash_status(tr("Nicchia eliminata") if new is None else tr("Nicchia modificata"), 2500)

    def on_cancel(self, viewport) -> None:
        self.hit = None
        viewport.update()

    def context_menu(self, viewport, pos) -> bool:
        self._exit(viewport)
        return True

    def claims_key(self, key: int, modifiers) -> bool:
        if modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        if getattr(self._vp, "_value_buffer", ""):
            return False
        return key in (Qt.Key_Escape, Qt.Key_A)

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if key == Qt.Key_A:
            ks = [k for k, _ in ANCHORS]
            _Settings.anchor = ks[(ks.index(_Settings.anchor) + 1) % len(ks)]
            viewport.flash_status(tr("Punto di presa: {0}").format(
                dict(ANCHORS)[_Settings.anchor].lower()), 2500)
            viewport.update()
            return True
        return False

    def on_value(self, viewport, value) -> bool:
        if isinstance(value, tuple) or not (0.05 <= value <= 20.0):
            return False
        _Settings.width = float(value)
        viewport.flash_status(tr("Larghezza nicchia {0}").format(fmt_len(value)), 2500)
        viewport.update()
        return True

    def status_clause(self) -> str:
        return (tr("Nicchia {0} x {1}, da terra {2}, profondità {3} · "
                   "numero = larghezza · A = punto di presa ({4}) · "
                   "tasto destro o Esc = esci").format(
            fmt_len(_Settings.width), fmt_len(_Settings.height),
            fmt_len(_Settings.sill), fmt_len(_Settings.depth),
            dict(ANCHORS)[_Settings.anchor].lower()))

    def value_label(self):
        if self.hit is None or self.hit.idx is not None:
            return None
        s0, s1, sill = _place(self.hit)
        c = _corners(self.hit, s0, s1, sill)[0]
        return (fmt_len(s1 - s0), (c[0] + c[2]) * 0.5)

    def draw_overlay(self, viewport, painter) -> None:
        try:
            self._draw(viewport, painter)
        except Exception:
            pass

    def _draw(self, viewport, painter) -> None:
        if self.hit is None:
            return
        nn = self.hit.d["niches"][self.hit.idx] if self.hit.idx is not None else None
        if nn is not None:
            front, back = _corners(self.hit, nn[0], nn[1], nn[2], nn[3] - nn[2],
                                   min(nn[4], self.hit.d["th"] - 0.02))
        else:
            s0, s1, sill = _place(self.hit)
            front, back = _corners(self.hit, s0, s1, sill)
        painter.save()
        painter.setPen(QPen(COLOR_EDIT if nn is not None else COLOR, 2))

        def px(p):
            r = viewport._world_to_pixel(p)
            return None if r is None else QPointF(r[0], r[1])

        for ring in (front, back):
            pts = [px(p) for p in ring]
            for i in range(4):
                a, b = pts[i], pts[(i + 1) % 4]
                if a is not None and b is not None:
                    painter.drawLine(a, b)
        for a, b in zip(front, back):
            pa, pb = px(a), px(b)
            if pa is not None and pb is not None:
                painter.drawLine(pa, pb)
        painter.restore()


ORDER = 12


def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(215, 205, 190))
    p.drawRect(5, 8, 38, 32)
    p.setBrush(QColor(150, 140, 125))
    p.drawRect(15, 16, 18, 20)
    p.end()
    return QIcon(pm)


def _walls_with_niches(scene):
    return [g for g in muri._selected_walls(scene)
            if muri.wall_data(g).get("niches")]


def register(api) -> None:
    tool = NicchiaTool()
    api.add_button(tr("Nicchia"), tr("Nicchia cieca in un muro"), _icon(),
                   api.run_tool(tool))
    app = api.app
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is None:
        return
    from PySide6.QtCore import QTimer

    def remove(vp) -> None:
        walls = _walls_with_niches(vp.scene)
        if not walls:
            return

        def mutate(sc):
            for g in walls:
                muri.clear_niches(g)

        vp.history.execute(muri.MuriCommand(mutate))
        vp.notify_scene_changed()
        vp.update()
        vp.flash_status(tr("Nicchie eliminate da {0} muri").format(len(walls)), 3000)

    def context(menu, selection) -> None:
        scene = app.viewport.scene
        if _Settings.used and (muri._selected_walls(scene) or not scene.selection):
            menu.addAction(tr("Nicchia (stesse impostazioni)"),
                           lambda: QTimer.singleShot(0, lambda: tool.start_same(app.viewport)))
        if _walls_with_niches(scene):
            menu.addAction(tr("Elimina nicchie del muro"),
                           lambda: QTimer.singleShot(0, lambda: remove(app.viewport)))

    add_ctx(context)
