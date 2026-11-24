# SPDX-License-Identifier: GPL-3.0-or-later
"""Stretch wall end, for MyHouse: makes a wall longer or shorter.

A MyHouse wall is rebuilt from its two stored end points, so pushing its end
face with Push/Pull does not last. This tool moves the end point itself:

  - click a wall near the end to move
  - move the mouse along the wall and click, or type the new length + Enter
  - Esc / right-click leaves the command

The wall keeps its direction. Walls drawn in the same run that meet at that
end follow it, so the corner stays joined and mitred; windows and doors stay
where they are and the holes are cut again. One undo step.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D

from tools.base import Tool, ToolContext

from . import finestre, muri
from ._imperial import fmt_len as fmt

from ._lingua import tr

ORDER = 12                       # right after Walls and Adopt wall
MIN_LEN = 0.01                   # a wall shorter than this is no wall
SAME = 1e-6                      # two stored points are the same point


def _same(p, q) -> bool:
    return (p is not None and q is not None
            and abs(p[0] - q[0]) < SAME and abs(p[1] - q[1]) < SAME)


def plain(d) -> bool:
    """A straight wall of one thickness, the kind these tools can rebuild: not
    a polygon wall and not one that tapers from one end to the other."""
    return not d.get("poly") and d.get("th_b") is None


def shift_niches(d, shift: float):
    """The wall's niches, moved along it by 'shift' (they are stored by their
    distance from the start of the wall), or None when it has none."""
    if not d.get("niches") or abs(shift) < 1e-9:
        return None
    return [[n[0] + shift, n[1] + shift] + list(n[2:]) for n in d["niches"]]


def _pose_key(group):
    return tuple(round(v, 6) for v in finestre._full_pose(group).data())


def wall_group(scene, world: QVector3D):
    """(group, end) of the wall under the point: end is "a" or "b", the end
    nearer to the point. None when there is no MyHouse wall there."""
    hit = finestre.find_wall(scene, world)
    if hit is None:
        return None
    A, B, _centre, w = hit
    for g in scene.groups:
        if muri.wall_data(g) is w:
            da = (world.x() - A.x()) ** 2 + (world.y() - A.y()) ** 2
            db = (world.x() - B.x()) ** 2 + (world.y() - B.y()) ** 2
            return g, ("a" if da < db else "b")
    return None


def stretch(scene, group, end: str, length: float) -> int:
    """Moves one end of the wall along its own direction so that the wall is
    'length' long. The walls of the same run that share that point follow.
    Returns how many walls were rebuilt."""
    d = muri.wall_data(group)
    if d is None:
        raise ValueError(tr("non è un muro MyHouse"))
    if not plain(d):
        raise ValueError(tr("un muro poligonale o a spessore variabile non si può allungare"))
    if length < MIN_LEN:
        raise ValueError(tr("il muro non avrebbe lunghezza"))
    (ax, ay), (bx, by) = d["a"], d["b"]
    L = math.hypot(bx - ax, by - ay)
    if L < 1e-9:
        raise ValueError(tr("il muro non ha una direzione"))
    ux, uy = (bx - ax) / L, (by - ay) / L
    if end == "b":
        old, new = [bx, by], [ax + ux * length, ay + uy * length]
    else:
        old, new = [ax, ay], [bx - ux * length, by - uy * length]
    if _same(old, new):
        return 0
    key, chain = _pose_key(group), d.get("chain")
    count, moved = 0, []
    for g in list(scene.groups):
        w = muri.wall_data(g)
        if w is None:
            continue
        if g is not group and (not chain or w.get("chain") != chain
                               or _pose_key(g) != key):
            continue
        keys = (end,) if g is group and not chain else ("a", "b", "prev",
                                                        "next")
        extra = {k: list(new) for k in keys if _same(w.get(k), old)}
        if g is group:
            extra[end] = list(new)
        if not extra:
            continue
        na, nb = extra.get("a", w["a"]), extra.get("b", w["b"])
        if _same(na, nb):
            raise ValueError(tr("un muro collegato non avrebbe lunghezza"))
        if g is not group and not plain(w):
            raise ValueError(tr("un muro collegato è poligonale o a spessore variabile"))
        if "a" in extra:                   # niches keep their place from end b
            old_len = math.hypot(w["b"][0] - w["a"][0], w["b"][1] - w["a"][1])
            niches = shift_niches(w, math.hypot(nb[0] - na[0], nb[1] - na[1]) - old_len)
            if niches is not None:
                extra["niches"] = niches
        extra["jn"] = None                 # bonded corners no longer fit: bond again
        muri.rebuild_wall(g, w["th"], w["h"], extra)
        moved.append(g)
        count += 1
    muri.sync_joints(scene, moved)
    muri.update_roof_clips(scene)
    finestre.update_openings(scene)
    return count


class StretchTool(Tool):
    name = tr("Allunga muro")
    shortcut = None
    description = tr("Allunga o accorcia un muro MyHouse da un'estremità.")
    vcb_label = tr("Lunghezza")

    def __init__(self) -> None:
        self._entering = False
        self._vp = None
        self._reset()

    def _reset(self) -> None:
        self.pick = None          # (group, end, fixed point, direction)
        self.length = None        # length under the cursor
        self.near = None          # before the pick: (end point, other end)

    def _buffer(self) -> str:
        return getattr(self._vp, "_value_buffer", "") or ""

    def on_activate(self, viewport) -> None:
        if self._entering:
            self._vp = viewport
            self._reset()
            viewport.flash_status(
                tr("Allunga muro: clic su un muro vicino all'estremità da spostare"), 6000)
            return
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def on_deactivate(self, viewport) -> None:
        self._reset()

    def _ends(self, scene, world):
        """(group, end, moving end, fixed end) in world coordinates."""
        hit = wall_group(scene, world)
        if hit is None:
            return None
        g, end = hit
        d = muri.wall_data(g)
        pose = finestre._full_pose(g)
        A = pose.map(QVector3D(d["a"][0], d["a"][1], d["z0"]))
        B = pose.map(QVector3D(d["b"][0], d["b"][1], d["z0"]))
        return (g, end, A, B) if end == "a" else (g, end, B, A)

    def on_hover(self, ctx: ToolContext) -> None:
        world = QVector3D(ctx.world)
        if self.pick is None:
            hit = self._ends(ctx.viewport.scene, world)
            self.near = (hit[2], hit[3]) if hit else None
        else:
            _g, _end, fixed, direction = self.pick
            self.length = max(0.0, QVector3D.dotProduct(world - fixed,
                                                        direction))
        ctx.viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        scene = viewport.scene
        if getattr(scene, "edit_group", None) is not None:
            viewport.flash_status(
                tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        world = QVector3D(ctx.world)
        if self.pick is None:
            hit = self._ends(scene, world)
            if hit is None:
                viewport.flash_status(
                    tr("Clic su un muro creato con lo strumento Muri (o adottato)"),
                    4000)
                return
            g, end, moving, fixed = hit
            run = moving - fixed
            if run.length() < 1e-9:
                return
            self.pick = (g, end, fixed, run.normalized())
            self.length = run.length()
            self.near = None
            viewport.flash_status(
                tr("Clic sulla nuova estremità, oppure digita la nuova lunghezza + Invio"), 6000)
            viewport.update()
            return
        _g, _end, fixed, direction = self.pick
        self._commit(viewport,
                     QVector3D.dotProduct(world - fixed, direction))

    def on_value(self, viewport, value) -> bool:
        if self.pick is None or isinstance(value, tuple):
            return False
        return self._commit(viewport, float(value))

    def _commit(self, viewport, length: float) -> bool:
        group, end = self.pick[0], self.pick[1]
        if length < MIN_LEN:
            viewport.flash_status(
                tr("Allunga muro: la nuova estremità deve restare dal lato del muro rispetto all'altra estremità"), 4000)
            return False
        done = [0]

        def mutate(scene):
            done[0] = stretch(scene, group, end, length)

        hist = viewport.history
        hist.execute(muri.MuriCommand(mutate))
        if getattr(hist, "last_error", None):
            viewport.flash_status(
                tr("Allunga muro: {message}").format(message=str(hist.last_error).split(": ", 1)[-1]), 6000)
            return False
        self._reset()
        viewport.notify_scene_changed()
        msg = [tr("Il muro ora è lungo {length}").format(length=fmt(length))]
        if done[0] > 1:
            msg.append(tr("muri collegati che l'hanno seguito: {n}").format(n=done[0] - 1))
        msg.append(tr("clic su un'altra estremità di muro, oppure Esc"))
        viewport.flash_status(" · ".join(msg), 5000)
        viewport.update()
        return True

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    def claims_key(self, key: int, modifiers) -> bool:
        if modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        return key == Qt.Key_Escape and not self._buffer()

    def _exit(self, viewport) -> None:
        self._reset()
        viewport.update()
        back = getattr(viewport.window(), "activate_select_tool", None)
        if callable(back):
            back()

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            if self.pick is not None:     # first Esc: let go of the wall
                self._reset()
                viewport.update()
            else:
                self._exit(viewport)
            return True
        return False

    def context_menu(self, viewport, pos) -> bool:
        self._exit(viewport)
        return True

    def status_clause(self) -> str:
        return (tr("clic sulla nuova estremità o digita la lunghezza · Esc = esci")
                if self.pick is not None
                else tr("clic su un muro vicino all'estremità da spostare · Esc = esci"))

    def value_label(self):
        if self.pick is None or self.length is None:
            return None
        _g, _end, fixed, direction = self.pick
        return (fmt(self.length), fixed + direction * (self.length / 2))

    @staticmethod
    def _tick(p: QVector3D, direction: QVector3D, size: float):
        """A short mark across the wall at p."""
        n = QVector3D(-direction.y(), direction.x(), 0.0) * size
        return (p - n, p + n)

    def rubber_band_lines(self):
        if self.pick is not None and self.length is not None:
            _g, _end, fixed, direction = self.pick
            tip = fixed + direction * self.length
            return [(fixed, tip), self._tick(tip, direction, 0.25)]
        if self.near is not None:
            moving, fixed = self.near
            run = moving - fixed
            if run.length() > 1e-9:
                return [(fixed, moving),
                        self._tick(moving, run.normalized(), 0.25)]
        return []


def _icon():
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
    pm = QPixmap(32, 32)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 1.5))
    p.setBrush(QColor(200, 170, 130))
    p.drawRect(QRectF(3, 12, 15, 8))
    pen = QPen(QColor(30, 110, 200), 2.2)
    p.setPen(pen)
    p.drawLine(QPointF(19, 16), QPointF(29, 16))          # arrow off the end
    p.drawLine(QPointF(29, 16), QPointF(25, 12))
    p.drawLine(QPointF(29, 16), QPointF(25, 20))
    p.end()
    return QIcon(pm)


def register(api) -> None:
    tool = StretchTool()
    start = api.run_tool(tool)
    api.add_button(tr("Allunga muro"),
                   tr("Allunga o accorcia un muro: clic vicino a un'estremità, poi clic sulla nuova estremità o digita la nuova lunghezza"),
                   _icon(), start)
    app = api.app
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        from PySide6.QtCore import QTimer

        def context(menu, selection) -> None:
            if not muri._selected_walls(app.viewport.scene):
                return
            menu.addAction(tr("Allunga estremità del muro…"),
                           lambda: QTimer.singleShot(0, start))

        add_ctx(context)
