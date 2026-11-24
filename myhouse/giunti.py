# SPDX-License-Identifier: GPL-3.0-or-later
"""Wall joint, for MyHouse: mitre or butt joint at a corner.

Click a wall near a corner to change how the two walls meet. Each click moves
to the next of three joints:
    mitre (as drawn)  ->  the clicked wall runs through, the other butts
    against it  ->  the other wall runs through  ->  mitre again
The two walls must already meet in a corner: drawn in one run, or joined with
Wall joining. A corner bonded by hand (Bond walls) is released at that end,
since its fixed corners would hide the joint.

Esc / right-click leaves the command; each change is one undo step.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D

from tools.base import ToolContext

from . import finestre, muri
from ._lingua import tr
from .allunga import _pose_key, _same, plain, wall_group
from .dividi import _WallClickTool

ORDER = 14                       # after Walls, Adopt, Stretch and Split wall
JOINTS = (None, "through", "butt")


def joint_partner(scene, group, end: str):
    """(group, end) of the wall that meets this end in a corner, or None. The
    two walls mitre into each other: each one's neighbour point at that end
    is the far end of the other. That holds for walls drawn in one run and
    for walls joined later, of the same thickness or not."""
    d = muri.wall_data(group)
    near = "prev" if end == "a" else "next"
    if d is None or not d.get(near):
        return None
    P, far = d[end], d["b" if end == "a" else "a"]
    key = _pose_key(group)
    for g in scene.groups:
        w = muri.wall_data(g)
        if w is None or g is group or _pose_key(g) != key:
            continue
        for e, other, nb in (("a", "b", "prev"), ("b", "a", "next")):
            if (_same(w[e], P) and _same(w.get(nb), far)
                    and _same(d[near], w[other])):
                return g, e
    return None


def joint_kind(group, end: str):
    return (muri.wall_data(group) or {}).get("j" + end)


def set_joint(scene, group, end: str, kind) -> None:
    """kind: "through" = this wall runs through and the other butts against
    it; "butt" = the other way round; None = mitre."""
    if kind not in JOINTS:
        raise ValueError(tr("giunto sconosciuto"))
    if not plain(muri.wall_data(group)):
        raise ValueError(tr("un muro poligonale o a spessore variabile non ha giunti"))
    mate = joint_partner(scene, group, end)
    if mate is None:
        raise ValueError(tr("questa estremità non incontra un altro muro in un angolo"))
    other = {"through": "butt", "butt": "through", None: None}[kind]
    for g, e, k in ((group, end, kind), (mate[0], mate[1], other)):
        w = muri.wall_data(g)
        extra = {"j" + e: k}
        if w.get("jn"):                    # bonded corners would hide the joint
            jn = {c: v for c, v in w["jn"].items()
                  if c not in (e + "L", e + "R")}
            extra["jn"] = jn if any(c in jn for c in ("aL", "aR", "bL", "bR")) else None
        muri.rebuild_wall(g, w["th"], w["h"], extra)
    muri.update_roof_clips(scene)
    finestre.update_openings(scene)


def next_joint(group, end: str):
    return {None: "through", "through": "butt", "butt": None}[
        joint_kind(group, end)]


class JointTool(_WallClickTool):
    name = tr("Giunto tra muri")
    description = tr("Cambia un angolo tra giunto a sghembo e di testa: il muro "
                     "su cui fai clic è passante, un altro clic per il contrario.")
    label = tr("Giunto tra muri")
    prompt = tr("clic su un muro vicino a un angolo: quello passa, l'altro si attesta contro di esso (altro clic: al contrario, poi a sghembo)")

    def on_hover(self, ctx: ToolContext) -> None:
        self.marks = []
        hit = wall_group(ctx.viewport.scene, QVector3D(ctx.world))
        if hit is not None and joint_partner(ctx.viewport.scene, *hit):
            g, end = hit
            A, B = self._axis(g)
            P, far = (A, B) if end == "a" else (B, A)
            run = far - P
            if run.length() > 1e-9:
                u = run.normalized()
                n = QVector3D(-u.y(), u.x(), 0.0) * 0.25
                self.marks = [(P, P + u * min(0.6, run.length())),
                              (P - n, P + n)]
        ctx.viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        scene = viewport.scene
        hit = wall_group(scene, QVector3D(ctx.world))
        if hit is None:
            viewport.flash_status(
                tr("Clic su un muro creato con lo strumento Muri, vicino a un angolo"),
                4000)
            return
        g, end = hit
        if joint_partner(scene, g, end) is None:
            viewport.flash_status(
                tr("Giunto tra muri: questa estremità non incontra un altro muro in un angolo (i muri disegnati separatamente si uniscono prima con Raccordo muri)"), 6000)
            return
        kind = next_joint(g, end)
        if self._run(viewport, lambda sc: set_joint(sc, g, end, kind)):
            if kind == "through":
                msg = tr("Giunto di testa: {name} è passante · clic di nuovo per cambiare").format(name=g.name)
            elif kind == "butt":
                msg = tr("Giunto di testa: {name} si attesta contro l'altro muro · clic di nuovo per cambiare").format(name=g.name)
            else:
                msg = tr("Angolo a sghembo · clic di nuovo per cambiare")
            viewport.flash_status(msg, 5000)


def _icon():
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
    pm = QPixmap(32, 32)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 1.5))
    p.setBrush(QColor(200, 170, 130))
    p.drawRect(QRectF(4, 4, 8, 24))          # an L corner with a butt joint
    p.drawRect(QRectF(12, 20, 16, 8))
    p.setPen(QPen(QColor(30, 110, 200), 2.2))
    p.drawLine(QPointF(12, 18), QPointF(12, 30))
    p.end()
    return QIcon(pm)


def register(api) -> None:
    start = api.run_tool(JointTool())
    api.add_button(tr("Giunto tra muri"),
                   tr("Giunto di testa o a sghembo in un angolo: clic sul muro passante; altro clic per il contrario, poi a sghembo"),
                   _icon(), start)
    app = api.app
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        from PySide6.QtCore import QTimer

        def context(menu, selection) -> None:
            if not muri._selected_walls(app.viewport.scene):
                return
            menu.addAction(tr("Giunto tra muri (di testa / a sghembo)…"),
                           lambda: QTimer.singleShot(0, start))

        add_ctx(context)
