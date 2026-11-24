# SPDX-License-Identifier: GPL-3.0-or-later
"""Split wall, for MyHouse.

Click a point on a wall and it becomes two walls that meet there. Both stay
in the same run, so the outer ends keep their corners; niches go to the half
they are in, windows and doors stay where they are and the holes are cut
again. Esc / right-click leaves the command; each cut is one undo step.
"""
from __future__ import annotations

import copy
import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D

from core import bim
from tools.base import Tool, ToolContext

from . import finestre, muri
from ._imperial import fmt_len as fmt

from ._lingua import tr
from .allunga import MIN_LEN, _pose_key, _same, plain, wall_group

ORDER = 13                       # after Walls, Adopt wall and Stretch wall


def _set_data(group, d: dict) -> None:
    ext = dict(group.ext or {})
    ext[muri.KEY] = d
    group.ext = ext


def _mates(scene, group):
    """The other walls of the same run that sit in the same place."""
    d = muri.wall_data(group)
    chain = d.get("chain")
    if not chain:
        return []
    key = _pose_key(group)
    return [g for g in scene.groups
            if g is not group and (muri.wall_data(g) or {}).get("chain")
            == chain and _pose_key(g) == key]


# ---------------------------------------------------------------------------
# Split
# ---------------------------------------------------------------------------

def split(scene, group, s: float):
    """Cuts the wall in two at the distance s from its start. The group
    keeps the first half; returns the new group, the second half."""
    from core.group import Group
    d = muri.wall_data(group)
    if d is None:
        raise ValueError(tr("non è un muro MyHouse"))
    if not plain(d):
        raise ValueError(tr("un muro poligonale o a spessore variabile non si può dividere"))
    (ax, ay), (bx, by) = d["a"], d["b"]
    L = math.hypot(bx - ax, by - ay)
    if s < MIN_LEN or s > L - MIN_LEN:
        raise ValueError(tr("il taglio è all'estremità del muro"))
    a, b = [ax, ay], [bx, by]
    p = [ax + (bx - ax) * s / L, ay + (by - ay) * s / L]
    mates = _mates(scene, group)
    if not d.get("chain"):                 # the halves must mitre together
        from core.group import new_uid
        d = dict(d, chain=new_uid(), nth=d["th"])
    d1, d2 = copy.deepcopy(d), copy.deepcopy(d)
    d1.update(b=list(p), next=list(b))
    d2.update(a=list(p), prev=list(a))
    # what belonged to the end each half no longer has, and what is worked
    # out again below (the holes) or no longer fits (bonded corners)
    for k in ("sm_b", "next_rev", "nxth", "jb", "jn", "open"):
        d1.pop(k, None)
    for k in ("sm_a", "prev_rev", "pth", "ja", "jn", "open"):
        d2.pop(k, None)
    niches = d.get("niches") or ()
    for half, keep in ((d1, [list(n) for n in niches if (n[0] + n[1]) / 2 < s]),
                       (d2, [[n[0] - s, n[1] - s] + list(n[2:]) for n in niches
                             if (n[0] + n[1]) / 2 >= s])):
        if keep:
            half["niches"] = keep
        else:
            half.pop("niches", None)
    pose = muri.wall_pose(group)

    used = {g.name for g in scene.groups}
    name, k = f"{group.name}b", 2
    while name in used:
        name, k = f"{group.name}b{k}", k + 1
    part2 = muri.wall_part(d2, pose, name)  # raises before anything changes
    group.children = [muri.wall_part(d1, pose, group.name)]
    _set_data(group, d1)
    g2 = Group(name=name)
    g2.adopt([part2])
    g2.component = False
    g2.layer = getattr(group, "layer", muri.LAYER_NAME)
    g2.material = dict(group.material) if group.material else None
    g2.hidden, g2.locked = group.hidden, group.locked
    g2.xform = group.xform
    bim.tag_group(g2, "IfcWall", name)
    ext = copy.deepcopy(dict(group.ext or {}))
    ext[muri.KEY] = d2
    g2.ext = ext
    scene.groups.insert(scene.groups.index(group) + 1, g2)

    for g in mates:                        # the neighbours now see the cut
        w = muri.wall_data(g)
        new = dict(w)
        if _same(w.get("prev"), a) and _same(w["a"], b):
            new["prev"] = list(p)
        if _same(w.get("next"), b) and _same(w["b"], a):
            new["next"] = list(p)
        if new != w:
            _set_data(g, new)
    muri.update_roof_clips(scene)
    finestre.update_openings(scene)
    return g2


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

class _WallClickTool(Tool):
    """A tool that acts on the wall under each click and stays active."""
    shortcut = None
    label = ""                # the tool's name, translated
    prompt = ""

    def __init__(self) -> None:
        self._entering = False
        self._vp = None
        self.marks = []

    def _buffer(self) -> str:
        return getattr(self._vp, "_value_buffer", "") or ""

    def on_activate(self, viewport) -> None:
        if self._entering:
            self._vp = viewport
            self.marks = []
            viewport.flash_status(
                tr("{tool}: {message}").format(tool=self.label, message=self.prompt), 6000)
            return
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def on_deactivate(self, viewport) -> None:
        self.marks = []

    def on_cancel(self, viewport) -> None:
        self.marks = []
        viewport.update()

    def claims_key(self, key: int, modifiers) -> bool:
        if modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        return key == Qt.Key_Escape and not self._buffer()

    def _exit(self, viewport) -> None:
        self.marks = []
        viewport.update()
        back = getattr(viewport.window(), "activate_select_tool", None)
        if callable(back):
            back()

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        return False

    def context_menu(self, viewport, pos) -> bool:
        self._exit(viewport)
        return True

    def status_clause(self) -> str:
        return tr("{prompt} · Esc = esci").format(prompt=self.prompt)

    def rubber_band_lines(self):
        return list(self.marks)

    @staticmethod
    def _axis(group):
        """(A, B) of the wall's drawn line, in world coordinates."""
        d = muri.wall_data(group)
        pose = finestre._full_pose(group)
        return (pose.map(QVector3D(d["a"][0], d["a"][1], d["z0"])),
                pose.map(QVector3D(d["b"][0], d["b"][1], d["z0"])))

    def _run(self, viewport, mutate) -> bool:
        scene = viewport.scene
        if getattr(scene, "edit_group", None) is not None:
            viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return False
        hist = viewport.history
        hist.execute(muri.MuriCommand(mutate))
        if getattr(hist, "last_error", None):
            viewport.flash_status(
                tr("{tool}: {message}").format(tool=self.label, message=str(hist.last_error).split(": ", 1)[-1]), 6000)
            return False
        self.marks = []
        viewport.notify_scene_changed()
        viewport.update()
        return True


class SplitTool(_WallClickTool):
    name = tr("Dividi muro")
    description = tr("Taglia in due un muro MyHouse nel punto del clic.")
    label = tr("Dividi muro")
    prompt = tr("clic sul punto del muro in cui tagliarlo")

    def _where(self, scene, world):
        hit = wall_group(scene, world)
        if hit is None:
            return None
        g = hit[0]
        A, B = self._axis(g)
        run = B - A
        L = run.length()
        if L < 1e-9:
            return None
        u = run / L
        s = QVector3D.dotProduct(world - A, u)
        return g, s, L, A, u

    def on_hover(self, ctx: ToolContext) -> None:
        self.marks = []
        hit = self._where(ctx.viewport.scene, QVector3D(ctx.world))
        if hit is not None:
            g, s, L, A, u = hit
            if MIN_LEN < s < L - MIN_LEN:
                d = muri.wall_data(g)
                p = A + u * s
                n = QVector3D(-u.y(), u.x(), 0.0)
                dl, dr = muri.side_offsets(d["th"], d["align"])
                self.marks = [(p + n * (dl + 0.05), p - n * (dr + 0.05))]
        ctx.viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        hit = self._where(viewport.scene, QVector3D(ctx.world))
        if hit is None:
            viewport.flash_status(
                tr("Clic su un muro creato con lo strumento Muri (o adottato)"),
                4000)
            return
        g, s, L, _A, _u = hit
        if self._run(viewport, lambda sc: split(sc, g, s)):
            viewport.flash_status(
                tr("Muro tagliato in due: {a} e {b} · clic su un altro muro, oppure Esc").format(a=fmt(s), b=fmt(L - s)),
                5000)


def _icon(kind: str):
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
    pm = QPixmap(32, 32)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 1.5))
    p.setBrush(QColor(200, 170, 130))
    if kind == "split":
        p.drawRect(QRectF(2, 12, 12, 8))
        p.drawRect(QRectF(18, 12, 12, 8))
        p.setPen(QPen(QColor(30, 110, 200), 2.2))
        p.drawLine(QPointF(16, 6), QPointF(16, 26))
    p.end()
    return QIcon(pm)


def register(api) -> None:
    split_start = api.run_tool(SplitTool())
    api.add_button(tr("Dividi muro"),
                   tr("Taglia un muro in due: clic sul punto del muro"),
                   _icon("split"), split_start)
    app = api.app
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        from PySide6.QtCore import QTimer

        def context(menu, selection) -> None:
            if not muri._selected_walls(app.viewport.scene):
                return
            menu.addAction(tr("Dividi muro…"),
                           lambda: QTimer.singleShot(0, split_start))

        add_ctx(context)
