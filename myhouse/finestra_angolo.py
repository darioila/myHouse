# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from ._scroll import fit_dialog
from ._lingua import tr
from ._imperial import LengthSpin

import math
import uuid

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPen
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel, QVBoxLayout,
)

from ._imperial import fmt_len
from tools.base import ToolContext
from PySide6.QtGui import QVector3D

from . import finestre, muri, piani
from .finestre import (
    FinestraCommand, FinestraTool, _Settings, _params, _store, _wall_pose,
    _wall_paint, ask_params, make_window, outline_lines, update_openings,
    validate,
)

ORDER = 41
SNAP = 0.80


SHOW_HELP_BOX = False


class _Ang:
    W2 = 1.20
    gap = 0.10
    swap = False


_sill_orig = finestre.sill_mesh


def _sill_mesh(d: dict):
    mt = d.get("mt")
    if not mt or finestre._reveal_pts(d) is not None:
        return _sill_orig(d)
    from core.mesh import Mesh
    D = finestre
    T = D._mapper(d)
    W = d["W"]
    th = max(0.001, float(d.get("sth", D.SILL_DEFAULT["sth"])))
    si = max(0.0, float(d.get("sti", D.SILL_DEFAULT["sti"])))
    se = max(0.0, float(d.get("ste", D.SILL_DEFAULT["ste"])))
    wth = d.get("wth")
    half = (wth / 2) if wth else (d["fd"] / 2)
    bo, bi = half + se, -(half + si)
    sgn = 1.0 if mt["e"] else -1.0
    ap = float(mt["ap"])
    ext = float(mt.get("oth", 2 * half)) / 2 + se
    a_e = ap + sgn * ext
    a_i = ap - sgn * ext * (half + si) / bo
    if mt["e"]:
        ring = [(0.0, bi), (0.0, bo), (a_e, bo), (a_i, bi)]
    else:
        ring = [(a_i, bi), (a_e, bo), (W, bo), (W, bi)]
    sill = D.PaintMesh(Mesh(), d, "sill", D.ZONE_NAME["sill"])
    D._fill_prism(sill, T, ring, -th, 0.0,
                  lambda f, _b: f.attrs.__setitem__("layer", D.LAYER_NAME))
    return sill.mesh


finestre.sill_mesh = _sill_mesh


_handle_orig = finestre.handle_mesh


def _handle_mesh(d: dict):
    mt = d.get("mt")
    if (not mt or not mt.get("e") or int(d.get("leaves", 1)) != 1
            or d.get("tipo") == "sc"):
        return _handle_orig(d)
    from core.mesh import Mesh
    D = finestre
    T = D._mapper(d)
    H, fw, fd, sw = d["H"], d["fw"], d["fd"], d["sw"]
    sd = fd * 0.6
    hw = D.PaintMesh(Mesh(), d, "handle", D.ZONE_NAME["handle"])
    zc = min(fw + (H - 2 * fw) * 0.47, H - fw - 0.1)
    D._lever(hw, T, fw + sw / 2, zc, -sd / 2)
    if (d.get("shut") or "") == "nap":
        D.shutter_mesh(d, hw)
    return hw.mesh


finestre.handle_mesh = _handle_mesh


def _walls(scene, level_id):
    out = []
    for g in scene.groups:
        w = (getattr(g, "ext", None) or {}).get(finestre.WALL_KEY)
        if not isinstance(w, dict) or "a" not in w or w.get("poly"):
            continue
        if level_id and w.get("lv") and w["lv"] != level_id:
            continue
        pose = _wall_pose(g)
        A = pose.map(QVector3D(w["a"][0], w["a"][1], w["z0"]))
        B = pose.map(QVector3D(w["b"][0], w["b"][1], w["z0"]))
        L = math.hypot(B.x() - A.x(), B.y() - A.y())
        if L < 1e-6:
            continue
        ux, uy = (B.x() - A.x()) / L, (B.y() - A.y()) / L
        out.append({"w": w, "A": A, "L": L, "u": (ux, uy)})
    return out


def _centre(w, s):
    th = muri.wall_th_at(w, min(max(s, 0.0), 1e9))
    dl, dr = {"left": (0.0, th), "right": (th, 0.0)}.get(
        w.get("align"), (th / 2, th / 2))
    return th, (dl - dr) / 2


def _line(wl, s_hint):
    th, c = _centre(wl["w"], s_hint)
    ux, uy = wl["u"]
    A = wl["A"]
    return (A.x() - uy * c, A.y() + ux * c), (ux, uy), th


def find_corner(scene, pt, level_id=None):
    ws = _walls(scene, level_id)
    best = None
    for i in range(len(ws)):
        for j in range(i + 1, len(ws)):
            p1, u1, _t1 = _line(ws[i], ws[i]["L"] / 2)
            p2, u2, _t2 = _line(ws[j], ws[j]["L"] / 2)
            cr = u1[0] * u2[1] - u1[1] * u2[0]
            if abs(cr) < 0.05:
                continue
            dx, dy = p2[0] - p1[0], p2[1] - p1[1]
            s1 = (dx * u2[1] - dy * u2[0]) / cr
            s2 = (dx * u1[1] - dy * u1[0]) / cr
            tol = 0.5
            if not (-tol <= s1 <= ws[i]["L"] + tol
                    and -tol <= s2 <= ws[j]["L"] + tol):
                continue
            P = (p1[0] + u1[0] * s1, p1[1] + u1[1] * s1)
            dist = math.hypot(pt.x() - P[0], pt.y() - P[1])
            if dist > SNAP or (best is not None and dist >= best[0]):
                continue
            best = (dist, i, j, P, s1, s2)
    if best is None:
        return None
    _d, i, j, P, s1, s2 = best
    out = []
    for k, s in ((i, best[4]), (j, best[5])):
        wl = ws[k]
        th, _c = _centre(wl["w"], s)
        _p, u, _t = _line(wl, s)
        r_plus, r_minus = wl["L"] - s, s
        if min(r_plus, r_minus) < 0.5:
            sgn = 1.0 if r_plus > r_minus else -1.0
        else:
            sgn = 1.0 if ((pt.x() - P[0]) * u[0] + (pt.y() - P[1]) * u[1]) >= 0 \
                else -1.0
        out.append((wl, (u[0] * sgn, u[1] * sgn), th))
    return out + [P]


def corner_places(scene, pt, level_id=None):
    c = find_corner(scene, pt, level_id)
    if c is None:
        return None
    (wa, aa, ta), (wb, ab, tb), P = c
    if _Ang.swap:
        (wa, aa, ta), (wb, ab, tb) = (wb, ab, tb), (wa, aa, ta)
    lens = (_Settings.W, _Ang.W2)
    places = []
    for (wl, a, _th), th_other, W in (((wa, aa, ta), tb, lens[0]),
                                      ((wb, ab, tb), ta, lens[1])):
        d0 = -th_other / 2.0 + _Ang.gap
        other_a = ab if wl is wa else aa
        cross = a[0] * other_a[1] - a[1] * other_a[0]
        if cross > 0:
            u = (-a[0], -a[1])
            s0 = d0 + W
        else:
            u = a
            s0 = d0
        o = (P[0] + a[0] * s0, P[1] + a[1] * s0, wl["A"].z())
        place = {"o": list(o), "u": [u[0], u[1]], "flip": False}
        near = 1 if cross > 0 else 0
        place["mt"] = {"e": near, "ap": (W + d0) if near else -d0,
                       "oth": th_other}
        w = wl["w"]
        for k in ("lv", "lvn", "off"):
            if w.get(k) is not None:
                place[k] = w[k]
        place["wth"] = _th_for(wl)
        place["wpaint"] = _wall_paint(w)
        places.append((place, W))
    return places


def _th_for(wl):
    return _centre(wl["w"], wl["L"] / 2)[0]


def _ask_extra(parent) -> bool:
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("Finestra ad angolo"))
    lay = QVBoxLayout(dlg)
    lay.addWidget(QLabel(tr(
        "La lunghezza impostata prima vale per il lato 1.\n"
        "L'altezza e l'altezza da terra sono uguali per i due lati.")))
    form = QFormLayout()
    w2 = LengthSpin()
    w2.setDecimals(3)
    w2.setRange(0.2, 20.0)
    w2.setValue(_Ang.W2)
    gap = LengthSpin()
    gap.setDecimals(3)
    gap.setRange(0.0, 5.0)
    gap.setValue(_Ang.gap)
    form.addRow(tr("Lunghezza lato 2"), w2)
    form.addRow(tr("Distanza dallo spigolo esterno"), gap)
    lay.addLayout(form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    fit_dialog(dlg)
    if dlg.exec() != QDialog.Accepted:
        return False
    _Ang.W2, _Ang.gap = w2.value(), gap.value()
    return True


class FinestraAngoloTool(FinestraTool):
    name = tr("Finestra ad angolo")
    description = tr("Due finestre su due lati di uno spigolo di muro.")

    def on_activate(self, viewport) -> None:
        if self._entering:
            self._vp = viewport
            self.hover = None
            viewport.flash_status(
                tr("Finestra ad angolo: clic sullo spigolo del muro · "
                   "Spazio = scambia i lati · Esc / tasto destro = esci"), 6000)
            return
        cur = _params()
        p = ask_params(viewport.window(), cur,
                       tr("Finestra ad angolo - lato 1"), tr("Avanti"),
                       viewport.scene)
        if p is None:
            return
        err = validate(p)
        if err:
            viewport.flash_status(tr("Finestra: ") + err, 5000)
            return
        if not _ask_extra(viewport.window()):
            return
        p2 = dict(p, W=_Ang.W2)
        err = validate(p2)
        if err:
            viewport.flash_status(tr("Finestra lato 2: ") + err, 5000)
            return
        _store(p)
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def on_click(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        scene = viewport.scene
        if getattr(scene, "edit_group", None) is not None:
            viewport.flash_status(
                tr("Chiudi il gruppo che stai modificando, poi posa la finestra"),
                4000)
            return
        world = QVector3D(ctx.world)
        self.hover = world
        pl = corner_places(scene, world, _Settings.level)
        if pl is None:
            viewport.flash_status(
                tr("Clicca vicino allo spigolo dove si incontrano due muri"),
                4000)
            return
        link = uuid.uuid4().hex[:8]
        base = _params()

        def mutate(sc):
            for (place, W), role in zip(pl, (1, 2)):
                make_window(sc, dict(base, W=W, ang=link, angr=role,
                                     mt=place["mt"]), place)
            update_openings(sc)

        hist = viewport.history
        hist.execute(FinestraCommand(mutate))
        if getattr(hist, "last_error", None):
            viewport.flash_status(
                tr("Finestra: ") + str(hist.last_error).split(": ", 1)[-1], 6000)
            return
        viewport.notify_scene_changed()
        viewport.flash_status(tr("Finestra ad angolo creata"), 2500)
        viewport.update()

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if key == Qt.Key_Space:
            _Ang.swap = not _Ang.swap
            viewport.flash_status(tr("Lati scambiati"), 1500)
            viewport.update()
            return True
        return False

    def status_clause(self) -> str:
        return tr("Clic sullo spigolo · Spazio = scambia i lati · "
                  "Esc / tasto destro = esci")

    def rubber_band_lines(self):
        if self.hover is None or self._vp is None:
            return []
        pl = corner_places(self._vp.scene, self.hover, _Settings.level)
        if pl is None:
            return []
        out = []
        for place, W in pl:
            d = _params()
            d.update(place)
            d["W"] = W
            out += outline_lines(d)
        return out

    def _draw(self, viewport, painter) -> None:
        if not SHOW_HELP_BOX:
            return
        painter.save()
        font = QFont()
        font.setPointSize(10)
        painter.setFont(font)
        fm = painter.fontMetrics()
        p = _params()
        lines = [
            tr("Finestra ad angolo: lato 1 {0} · lato 2 {1}").format(
                fmt_len(p["W"]), fmt_len(_Ang.W2)),
            tr("Altezza {0} · da terra {1}").format(
                fmt_len(p["H"]), fmt_len(p["sill"])),
            tr("Spazio = scambia i lati · Esc / tasto destro = esci"),
        ]
        w = max(fm.horizontalAdvance(t) for t in lines) + 16
        h = fm.height() * len(lines) + 12
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(30, 30, 30, 200))
        painter.drawRoundedRect(QRectF(12, 44, w, h), 6, 6)
        painter.setPen(QPen(QColor(255, 255, 255)))
        for i, t in enumerate(lines):
            painter.drawText(QPointF(20, 44 + 6 + fm.ascent() + i * fm.height()), t)
        painter.restore()


def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(170, 210, 235))
    p.drawPolygon([QPointF(6, 18), QPointF(26, 18), QPointF(26, 38), QPointF(6, 38)])
    p.drawPolygon([QPointF(26, 18), QPointF(42, 10), QPointF(42, 30), QPointF(26, 38)])
    p.end()
    return QIcon(pm)


def register(api) -> None:
    api.add_button(tr("Finestra ad angolo"),
                   tr("Inserisce due finestre ai lati di uno spigolo di muro"),
                   _icon(), api.run_tool(FinestraAngoloTool()))
