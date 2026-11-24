# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPen, QVector3D

from tools.base import Tool, ToolContext

from . import muri, tetto, tetto_profilo

ORDER = 52
SAME = 1e-4
CLOSE = 0.15


def _roof_of(group):
    d = tetto.roof_data(group)
    if d is not None:
        return "t", d
    d = tetto_profilo.roof_data(group)
    if d is not None:
        return "p", d
    return None, None


def _all_roofs(scene):
    return [g for g in scene.groups if _roof_of(g)[0]]


def _selected_roofs(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and _roof_of(g)[0] and g not in out:
            out.append(g)
    return out


def _footprint(kind, d):
    from shapely.geometry import Polygon, box
    if kind == "t":
        return Polygon([tuple(p) for p in d["poly"]]).buffer(0)
    pts = tetto_profilo.profile_pts(d)
    us = [p[0] for p in pts]
    off = d.get("off", 0.0)
    dep0 = d["d0"] - d["dir"] * off
    dep1 = d["d0"] + d["dir"] * (d["len"] + off)
    lo, hi = min(dep0, dep1), max(dep0, dep1)
    if d["pl"] == "xz":
        return box(min(us), lo, max(us), hi)
    return box(lo, min(us), hi, max(us))


def _top_z(kind, d) -> float:
    if kind == "t":
        zs = [c[2] for c in d.get("ctrl") or ()]
        return max(zs) if zs else d["base"]
    return max(z for _u, z in tetto_profilo.profile_pts(d))


def _inverse(group):
    m, ok = tetto._group_matrix(group).inverted()
    return m if ok else None


def _to_local(group, pts, z=0.0):
    inv = _inverse(group)
    if inv is None:
        return [list(p) for p in pts]
    out = []
    for x, y in pts:
        v = inv.map(QVector3D(x, y, z))
        out.append([v.x(), v.y()])
    return out


def _roof_under(scene, x, y):
    from shapely.geometry import Point
    best, bz = None, None
    for g in _all_roofs(scene):
        kind, d = _roof_of(g)
        zw = tetto._group_matrix(g).map(
            QVector3D(0, 0, _top_z(kind, d))).z()
        (lx, ly), = _to_local(g, [(x, y)], zw)
        try:
            inside = _footprint(kind, d).contains(Point(lx, ly))
        except Exception:
            inside = False
        if inside and (bz is None or zw > bz):
            best, bz = g, zw
    return best


MSG_START = tr("Fora tetto: clic per i vertici del foro (vista dall'alto) · "
               "C/Invio/tasto destro = chiudi · O = ortogonale · "
               "Backspace = annulla · Esc = esci")


class ForaTettoTool(Tool):
    name = tr("Fora tetto")
    shortcut = None
    description = tr("Fora il tetto disegnando dall'alto una poligonale chiusa.")

    def __init__(self) -> None:
        self.ortho = True
        self._entering = False
        self._reset()

    def _reset(self) -> None:
        self.points: list[tuple[float, float]] = []
        self.roofs: list = []
        self.fixed = False
        self.hover_point: QVector3D | None = None

    def on_activate(self, viewport) -> None:
        if not self._entering:
            self._entering = True
            try:
                viewport.set_active_tool(self)
            finally:
                self._entering = False
            return
        self._reset()
        sel = _selected_roofs(viewport.scene)
        if sel:
            self.roofs, self.fixed = sel, True
        viewport.flash_status(MSG_START, 8000)

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
        if len(self.points) >= 3:
            self._commit(viewport)
        else:
            self._exit(viewport)
        return True

    def _constrain(self, x, y):
        if not self.ortho or not self.points:
            return (x, y)
        last = self.points[-1]
        if abs(x - last[0]) >= abs(y - last[1]):
            return (x, last[1])
        return (last[0], y)

    def _zw(self) -> float:
        zs = []
        for g in self.roofs:
            kind, d = _roof_of(g)
            if kind:
                zs.append(tetto._group_matrix(g).map(
                    QVector3D(0, 0, _top_z(kind, d))).z())
        return max(zs) if zs else 0.0

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        x, y = self._constrain(ctx.world.x(), ctx.world.y())
        if not self.points:
            if not self.fixed:
                g = _roof_under(vp.scene, x, y)
                if g is None:
                    vp.flash_status(
                        tr("Nessun tetto sotto il punto: inizia il foro sopra "
                           "un tetto o selezionalo prima"), 4000)
                    return
                self.roofs = [g]
            self.points.append((x, y))
        else:
            if (len(self.points) >= 3 and math.hypot(
                    x - self.points[0][0], y - self.points[0][1]) < CLOSE):
                self._commit(vp)
                return
            if math.hypot(x - self.points[-1][0],
                          y - self.points[-1][1]) < SAME:
                return
            self.points.append((x, y))
        vp.update()

    def on_hover(self, ctx: ToolContext) -> None:
        w = QVector3D(ctx.world)
        x, y = self._constrain(w.x(), w.y())
        self.hover_point = QVector3D(x, y, w.z())
        ctx.viewport.update()

    def claims_key(self, key: int, modifiers) -> bool:
        if modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        if key in (Qt.Key_F8, Qt.Key_O, Qt.Key_Escape):
            return True
        return key == Qt.Key_C and bool(self.points)

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if key in (Qt.Key_O, Qt.Key_F8):
            self.ortho = not self.ortho
            h = self.hover_point
            if h is not None:
                x, y = self._constrain(h.x(), h.y())
                self.hover_point = QVector3D(x, y, h.z())
            viewport.flash_status(
                tr("Ortogonale ") + (tr("attivo") if self.ortho
                                     else tr("disattivato")), 2000)
            viewport.update()
            return True
        if key in (Qt.Key_C, Qt.Key_Return, Qt.Key_Enter) and self.points:
            self._commit(viewport)
            return True
        if key == Qt.Key_Backspace:
            if self.points:
                self.points.pop()
                if not self.points and not self.fixed:
                    self.roofs = []
            viewport.update()
            return True
        return False

    def rubber_band_lines(self):
        if not self.points:
            return []
        P = QVector3D
        z = self._zw()
        pts = list(self.points)
        if self.hover_point is not None:
            pts.append((self.hover_point.x(), self.hover_point.y()))
        lines = [(P(*a, z), P(*b, z)) for a, b in zip(pts, pts[1:])]
        if len(pts) >= 3:
            lines.append((P(*pts[-1], z), P(*pts[0], z)))
        return lines

    def draw_overlay(self, viewport, painter) -> None:
        try:
            self._draw(viewport, painter)
        except Exception:
            pass

    def _draw(self, viewport, painter) -> None:
        if not self.points:
            return
        z = self._zw()
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        for i, p in enumerate(self.points):
            pc = viewport._world_to_pixel(QVector3D(p[0], p[1], z))
            if pc is None:
                continue
            painter.setPen(QPen(QColor(255, 255, 255), 1.5))
            painter.setBrush(QColor(255, 210, 0) if i == 0
                             else QColor(220, 30, 30))
            painter.drawEllipse(QPointF(pc[0], pc[1]), 5, 5)
        painter.restore()

    def _commit(self, viewport) -> None:
        if getattr(viewport.scene, "edit_group", None) is not None:
            viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        pts = muri._dedupe(list(self.points), True)
        if len(pts) < 3:
            viewport.flash_status(tr("Servono almeno 3 vertici"), 3000)
            return
        try:
            from shapely.geometry import Polygon
        except ImportError:
            viewport.flash_status(tr("Serve shapely: pip install shapely"), 6000)
            return
        world = [tuple(p) for p in pts]
        pg = Polygon(world)
        if not pg.is_valid or pg.area < 1e-4:
            viewport.flash_status(
                tr("Poligono non valido: i lati non devono incrociarsi"), 4000)
            return
        jobs = []
        for g in self.roofs:
            kind, d = _roof_of(g)
            if not kind:
                continue
            zw = tetto._group_matrix(g).map(
                QVector3D(0, 0, _top_z(kind, d))).z()
            loc = _to_local(g, world, zw)
            try:
                if not _footprint(kind, d).intersects(Polygon(loc)):
                    continue
            except Exception:
                continue
            q = dict(d, fori=list(d.get("fori") or ()) + [loc])
            try:
                (tetto if kind == "t" else tetto_profilo).roof_mesh(q)
            except ImportError:
                viewport.flash_status(tr("Serve shapely: pip install shapely"), 6000)
                return
            except Exception as ex:
                viewport.flash_status(tr("Fora tetto: ") + str(ex), 6000)
                return
            jobs.append((g, loc))
        if not jobs:
            viewport.flash_status(tr("Il foro non tocca il tetto"), 4000)
            return

        def mutate(scene):
            for g, loc in jobs:
                kind, d = _roof_of(g)
                if not kind:
                    continue
                q = dict(d)
                q["fori"] = list(d.get("fori") or ()) + [loc]
                if kind == "t":
                    tetto.rebuild_roof(g, q)
                else:
                    tetto_profilo.rebuild(g, q)
            tetto.update_roof_clips(scene)

        viewport.history.execute(muri.MuriCommand(mutate))
        viewport.notify_scene_changed()
        viewport.flash_status(tr("Tetto forato"), 3000)
        keep, fixed = self.roofs, self.fixed
        self._reset()
        self.roofs, self.fixed = (keep, True) if fixed else ([], False)
        viewport.update()


def remove_holes(viewport) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    roofs = [g for g in _selected_roofs(scene)
             if _roof_of(g)[1].get("fori")]
    if not roofs:
        viewport.flash_status(tr("Nessun foro da togliere"), 3000)
        return

    def mutate(sc):
        for g in roofs:
            kind, d = _roof_of(g)
            q = dict(d)
            q.pop("fori", None)
            if kind == "t":
                tetto.rebuild_roof(g, q)
            else:
                tetto_profilo.rebuild(g, q)
        tetto.update_roof_clips(sc)

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("Fori tolti dal tetto"), 3000)


def _icon():
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QIcon, QPainter, QPixmap, QPolygon
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(170, 90, 75))
    p.drawPolygon(QPolygon([QPoint(4, 34), QPoint(24, 8), QPoint(44, 34)]))
    p.setBrush(QColor(255, 255, 255))
    p.drawRect(19, 20, 12, 9)
    p.end()
    return QIcon(pm)


def register(api) -> None:
    tool = ForaTettoTool()
    api.add_button(tr("Fora tetto"),
                   tr("Fora il tetto disegnando dall'alto una poligonale chiusa"),
                   _icon(), api.run_tool(tool))
    app = api.app
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        def context(menu, selection) -> None:
            roofs = [g for g in _selected_roofs(app.viewport.scene)
                     if _roof_of(g)[1].get("fori")]
            if not roofs:
                return
            menu.addSeparator()
            menu.addAction(tr("Togli fori dal tetto"),
                           lambda: remove_holes(app.viewport))

        add_ctx(context)
