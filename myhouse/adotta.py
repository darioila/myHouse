# SPDX-License-Identifier: GPL-3.0-or-later
"""Adopt wall for IngeTrazo / MyHouse — turns existing geometry into a wall.

Use: select one or more groups (or components) that are each a plain wall — a
box standing on its footprint — then MyHouse > Adopt wall, or right-click >
"Adopt as MyHouse wall". Each one is replaced, where it stands, by a real
MyHouse wall (IfcWall) of the same length, thickness, height and base
elevation, so it can be edited with "Edit wall…", cut by MyHouse doors and
windows, found by the automatic slab and assigned to a level.

What is read from the geometry: the smallest rectangle around its plan (long
side = the wall's axis, short side = its thickness), its lowest point and its
height. What is kept: the name, the identity (so IFC data edited on it follows),
the container's material and whether it was hidden or locked.

Limits: one wall per group; the plan must be a rectangle (an L-shaped or
curved wall is refused — split it first); openings, sloped tops and anything
else that is not the box are not carried over: the adopted wall is solid, and
the status bar says so. Loose geometry must be grouped first. One undo step.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

from core import bim

from . import muri
from ._lingua import tr

ORDER = 11                      # right after Walls
RECT_TOL = 0.98                 # plan must fill this much of its rectangle
SOLID_TOL = 0.98                # below this share of the box: "not a full box"
MIN_SIZE = 1e-3                 # metres: thinner or shorter is not a wall


# ---------------------------------------------------------------------------
# Geometry (pure)
# ---------------------------------------------------------------------------

def _hull(points):
    """Convex hull of (x, y) points, counter-clockwise."""
    pts = sorted(set((round(x, 6), round(y, 6)) for x, y in points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def half(seq):
        out = []
        for p in seq:
            while len(out) >= 2 and cross(out[-2], out[-1], p) <= 1e-12:
                out.pop()
            out.append(p)
        return out[:-1]
    return half(pts) + half(reversed(pts))


def _area(poly) -> float:
    return abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1]
                   - poly[(i + 1) % len(poly)][0] * poly[i][1]
                   for i in range(len(poly)))) / 2.0


def wall_from_points(points):
    """Wall parameters from the (x, y, z) corners of a box-shaped solid:
    {"a", "b", "th", "h", "z0", "fill"} — a and b the ends of the centre line,
    fill the share of the plan rectangle the plan really covers. Raises
    ValueError, with a message for the user, when it is not a wall."""
    if len(points) < 4:
        raise ValueError(tr("non c'è niente da misurare"))
    z0 = min(p[2] for p in points)
    h = max(p[2] for p in points) - z0
    hull = _hull([(p[0], p[1]) for p in points])
    if len(hull) < 3 or h < MIN_SIZE:
        raise ValueError(tr("è piatto, non è un muro solido"))
    best = None                     # smallest rectangle on one of the edges
    for i in range(len(hull)):
        (x0, y0), (x1, y1) = hull[i], hull[(i + 1) % len(hull)]
        L = math.hypot(x1 - x0, y1 - y0)
        if L < 1e-9:
            continue
        ux, uy = (x1 - x0) / L, (y1 - y0) / L
        s = [(x - x0) * ux + (y - y0) * uy for x, y in hull]
        t = [-(x - x0) * uy + (y - y0) * ux for x, y in hull]
        w, d = max(s) - min(s), max(t) - min(t)
        if best is None or w * d < best[0]:
            best = (w * d, (x0, y0), (ux, uy), min(s), max(s), min(t), max(t))
    rect, (ox, oy), (ux, uy), s0, s1, t0, t1 = best
    if s1 - s0 < t1 - t0:           # the long side is the axis
        ox, oy = ox + s0 * ux - t0 * uy, oy + s0 * uy + t0 * ux
        (ux, uy), s0, s1, t0, t1 = (-uy, ux), 0.0, t1 - t0, -(s1 - s0), 0.0
    length, th = s1 - s0, t1 - t0
    if th < MIN_SIZE or length < MIN_SIZE:
        raise ValueError(tr("è piatto, non è un muro solido"))
    fill = _area(hull) / rect
    if fill < RECT_TOL:
        raise ValueError(tr("la sua pianta non è un rettangolo"))
    tm = (t0 + t1) / 2.0

    def at(s):
        return [ox + s * ux - tm * uy, oy + s * uy + tm * ux]
    return {"a": at(s0), "b": at(s1), "th": th, "h": h, "z0": z0,
            "fill": fill}


# ---------------------------------------------------------------------------
# The document
# ---------------------------------------------------------------------------

def _is_myhouse(group) -> bool:
    ext = getattr(group, "ext", None) or {}
    return any(str(k).startswith("myhouse_") for k in ext)


def candidates(scene):
    """The selected top-level groups that are not MyHouse objects already."""
    picked = {getattr(e, "owner", None) or e for e in scene.selection}
    return [g for g in scene.groups              # in the document's order
            if g in picked and not _is_myhouse(g)]


def _measure(group):
    """(wall parameters, share of the box that is solid or None if unknown)."""
    from core.group import world_mesh
    mesh = world_mesh(group)
    pts = [(v.position.x(), v.position.y(), v.position.z())
           for v in mesh.vertices]
    w = wall_from_points(pts)
    length = math.hypot(w["b"][0] - w["a"][0], w["b"][1] - w["a"][1])
    try:
        vol = bim.face_set_volume(list(mesh.faces))
    except Exception:               # a measurement, never a reason to fail
        vol = None
    solid = abs(vol) / (length * w["th"] * w["h"]) if vol else None
    return w, solid


def adopt(scene, groups):
    """Replace each group by a MyHouse wall. Returns (adopted, partial,
    refused): the new walls, the names of those that were not a full box,
    and (name, reason) for those left alone. Call inside a MuriCommand."""
    from core.group import Group, new_uid
    adopted, partial, refused = [], [], []
    for old in groups:
        try:
            w, solid = _measure(old)
        except ValueError as exc:
            refused.append((old.name, str(exc)))
            continue
        d = {"a": w["a"], "b": w["b"], "prev": None, "next": None,
             "z0": w["z0"], "th": w["th"], "nth": w["th"], "h": w["h"],
             "align": "center", "chain": new_uid()}
        part = muri.wall_part(d)            # raises before anything changes
        if not any(ly.name == muri.LAYER_NAME for ly in scene.layers):
            from core.layers import Layer
            scene.layers.append(Layer(muri.LAYER_NAME))
        g = Group(name=old.name)
        g.adopt([part])
        g.component = False
        g.layer = muri.LAYER_NAME
        g.uid = old.uid                     # IFC data and scenes follow it
        g.material = dict(old.material) if old.material else None
        g.hidden, g.locked = old.hidden, old.locked
        g.ifc = dict(old.ifc) if old.ifc else None      # keeps delivery data
        bim.tag_group(g, "IfcWall", (old.ifc or {}).get("name") or old.name)
        ext = dict(old.ext or {})
        ext[muri.KEY] = d
        g.ext = ext
        scene.groups[scene.groups.index(old)] = g
        scene.selection.discard(old)
        scene.selection.add(g)
        adopted.append(g)
        if solid is not None and solid < SOLID_TOL:
            partial.append(g.name)
    if adopted:
        try:                                # doors and windows already there
            from . import finestre
            finestre.update_openings(scene)
        except ImportError:
            pass
        muri.update_roof_clips(scene)
    return adopted, partial, refused


def adopt_selected(viewport) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    groups = candidates(scene)
    if not groups:
        viewport.flash_status(
            tr("Adotta muro: seleziona un gruppo che sia un muro semplice (prima raggruppa la geometria sciolta)"), 6000)
        return
    result = {}

    def mutate(sc):
        result["r"] = adopt(sc, groups)

    hist = viewport.history
    hist.execute(muri.MuriCommand(mutate))
    if getattr(hist, "last_error", None):
        viewport.flash_status(
            tr("Adotta muro: {message}").format(message=str(hist.last_error).split(": ", 1)[-1]), 6000)
        return
    adopted, partial, refused = result.get("r", ([], [], []))
    viewport.notify_scene_changed()
    viewport.update()
    msg = [tr("muri adottati: {n}").format(n=len(adopted))] if adopted else []
    if partial:
        msg.append(tr("non è un parallelepipedo pieno, adottato come pieno: {names}").format(names=", ".join(partial)))
    if refused:
        msg.append(tr("lasciati com'erano: {names}").format(names="; ".join(
            f"{name} ({why})" for name, why in refused[:4])
            + (" …" if len(refused) > 4 else "")))
    viewport.flash_status(
        tr("Adotta muro: {message}").format(message=" · ".join(msg)), 9000)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def _icon():
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(120, 120, 120), 2, Qt.DashLine))
    p.drawRect(6, 22, 20, 18)                       # the geometry as it was
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(209, 204, 194))
    p.drawRect(22, 8, 20, 18)                       # the wall it becomes
    p.setPen(QPen(QColor(0, 140, 220), 3))
    p.drawLine(12, 16, 20, 16)
    p.drawLine(16, 12, 20, 16)
    p.drawLine(16, 20, 20, 16)
    p.end()
    return QIcon(pm)


def register(api) -> None:
    app = api.app
    api.add_button(
        tr("Adotta muro"),
        tr("Trasforma i gruppi selezionati a forma di parallelepipedo in muri MyHouse, sul posto"),
        _icon(), lambda: adopt_selected(app.viewport))
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        def context(menu, selection) -> None:
            if not candidates(app.viewport.scene):
                return
            menu.addSeparator()
            menu.addAction(
                tr("Adotta come muro MyHouse"),
                lambda: QTimer.singleShot(
                    0, lambda: adopt_selected(app.viewport)))

        add_ctx(context)
