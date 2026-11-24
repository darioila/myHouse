# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QVector3D
from PySide6.QtWidgets import QInputDialog

from tools.base import Tool, ToolContext

from . import etichetta_id, muri, solaio

ORDER = 98
LAYER_NAME = "Stanze"
KEY = "mh_stanza"
INK = (0.0, 0.0, 0.0)
OFF_Z = 0.02
LINE_GAP = 1.7

_last_name = {"v": ""}


def poly_area(pts) -> float:
    return abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
                   - pts[(i + 1) % len(pts)][0] * pts[i][1]
                   for i in range(len(pts)))) / 2.0


def poly_perimeter(pts) -> float:
    return sum(math.hypot(pts[(i + 1) % len(pts)][0] - pts[i][0],
                          pts[(i + 1) % len(pts)][1] - pts[i][1])
               for i in range(len(pts)))


def _num(v: float) -> str:
    return f"{v:.2f}".replace(".", ",")


def lines_of(name: str, area: float, perim: float):
    out = []
    if name.strip():
        out.append(name.strip())
    out.append(_num(area) + " m\u00b2")
    out.append(_num(perim) + " m")
    return out


def _line_centers(n: int, size: float, center):
    step = size * LINE_GAP
    top = center[1] + (n - 1) * step / 2.0
    return [(center[0], top - i * step) for i in range(n)]


NATIVE = True   # testi nativi di IngeTrazo (leggeri) invece di lettere 3D


def _marker_mesh(center, z):
    """Un triangolino da 2 mm: tiene vivo il gruppo, il testo e' nativo."""
    from core.mesh import Mesh
    P = QVector3D
    mesh = Mesh()
    cx, cy = center
    f = mesh.add_face([P(cx, cy, z), P(cx + 0.002, cy, z),
                       P(cx, cy + 0.002, z)])
    f.attrs["color"] = INK
    f.attrs["mat"] = tr("etichetta stanza testo")
    f.attrs["layer"] = LAYER_NAME
    return mesh


def _room_groups(scene):
    return [g for g in scene.groups
            if isinstance(getattr(g, "ext", None), dict) and KEY in g.ext]


def sync_native_labels(scene) -> None:
    """Ricostruisce i testi nativi del livello Stanze dai gruppi stanza
    (ne converte anche i vecchi con lettere 3D)."""
    if not NATIVE:
        return
    from core.group import Group
    from core.textlabel import TextLabel
    scene.text_labels[:] = [t for t in scene.text_labels
                            if getattr(t, "layer", None) != LAYER_NAME]
    for g in _room_groups(scene):
        d = g.ext[KEY]
        c, z = d.get("c") or [0.0, 0.0], float(d.get("z", 0.0))
        try:
            kids = getattr(g, "children", None) or []
            if not kids or len(getattr(kids[0].mesh, "faces", ())) != 1:
                part = Group(_marker_mesh(c, z), name=tr("Etichetta stanza"))
                part.component = False
                g.children = [part]
        except Exception:
            pass
        text = "\n".join(lines_of(d.get("name") or "", float(d.get("area", 0)),
                                  float(d.get("perim", 0))))
        scene.text_labels.append(TextLabel(
            QVector3D(c[0], c[1], z), QVector3D(0.0, 0.0, 0.0), text,
            LAYER_NAME))
    try:
        from . import legenda_locali
        legenda_locali.sync_legend_labels(scene)
    except Exception:
        pass


def room_mesh(lines, size: float, center, z: float):
    from core.mesh import Mesh
    if NATIVE:
        return _marker_mesh(center, z)
    P = QVector3D
    mesh = Mesh()
    for txt, c in zip(lines, _line_centers(len(lines), size, center)):
        _w, shapes = etichetta_id.text_shape(txt, size)
        for outer, holes in shapes:
            ring = [P(c[0] + x, c[1] + y, z) for x, y in outer]
            hs = [[P(c[0] + x, c[1] + y, z) for x, y in h] for h in holes]
            try:
                f = mesh.add_face(ring, hs) if hs else mesh.add_face(ring)
            except Exception:
                f = mesh.add_face(ring)
            f.attrs["color"] = INK
            f.attrs["mat"] = tr("etichetta stanza testo")
            f.attrs["layer"] = LAYER_NAME
    return mesh


def build_room_label(scene, name, area, perim, size, center, z, level=None):
    from core.group import Group
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    lines = lines_of(name, area, perim)
    part = Group(room_mesh(lines, size, center, z), name=tr("Etichetta stanza"))
    part.component = False
    g = Group(name=tr("Stanza {0}").format(name.strip() or tr("senza nome")))
    g.adopt([part])
    g.component = False
    g.layer = LAYER_NAME
    g.ext = {KEY: {"name": name, "size": size, "c": list(center), "z": z,
                   "area": area, "perim": perim,
                   "lv": level or ""}}
    scene.groups.append(g)
    sync_native_labels(scene)
    return g


class StanzaTool(Tool):
    name = tr("Stanza")
    shortcut = None
    description = tr("Clic al centro di una stanza chiusa da muri: scrive nome, "
                     "area e perimetro.")

    def __init__(self) -> None:
        self._entering = False

    def on_activate(self, viewport) -> None:
        self._vp = viewport
        if self._entering:
            return
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False
        viewport.flash_status(
            tr("Stanza: clic al centro di una stanza chiusa da muri · "
               "tasto destro o Esc = esci"), 6000)

    def on_deactivate(self, viewport) -> None:
        pass

    def _exit(self, viewport) -> None:
        viewport.update()
        back = getattr(viewport.window(), "activate_select_tool", None)
        if callable(back):
            back()

    def context_menu(self, viewport, pos) -> bool:
        self._exit(viewport)
        return True

    def claims_key(self, key: int, modifiers) -> bool:
        return key == Qt.Key_Escape

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        return False

    def on_hover(self, ctx: ToolContext) -> None:
        pass

    def on_cancel(self, viewport) -> None:
        viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        if getattr(vp.scene, "edit_group", None) is not None:
            vp.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        from . import piani
        x, y = ctx.world.x(), ctx.world.y()
        lv_id = piani.active_id(vp.scene)
        try:
            poly = solaio.find_room(vp.scene, x, y, lv_id)
        except ImportError:
            vp.flash_status(tr("Serve shapely: pip install shapely"), 6000)
            return
        if poly is None:
            vp.flash_status(
                tr("Nessuna stanza chiusa qui: controlla che i muri si "
                   "chiudano"), 5000)
            return
        name, ok = QInputDialog.getText(
            vp.window(), tr("Stanza"), tr("Nome della stanza:"),
            text=_last_name["v"])
        if not ok:
            return
        _last_name["v"] = name
        area, perim = poly_area(poly), poly_perimeter(poly)
        size = etichetta_id.current_size(vp.scene)
        lv = piani.get(vp.scene, lv_id)
        z = (lv["z"] if lv else 0.0) + OFF_Z
        c = (x, y)

        def mutate(scene):
            build_room_label(scene, name, area, perim, size, c, z, lv_id)

        vp.history.execute(muri.MuriCommand(mutate))
        vp.notify_scene_changed()
        vp.flash_status(tr("Stanza: {0} m\u00b2 · perimetro {1} m").format(
            _num(area), _num(perim)), 4000)
        vp.update()


def _icon():
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 3))
    p.drawRect(6, 6, 36, 36)
    p.setPen(QPen(QColor(0, 0, 0), 2))
    p.drawLine(14, 16, 34, 16)
    p.drawLine(16, 24, 32, 24)
    p.drawLine(18, 32, 30, 32)
    p.end()
    return QIcon(pm)


def _watch(api) -> None:
    from PySide6.QtCore import QTimer
    state = {"sig": None}

    def tick() -> None:
        try:
            sc = api.window.viewport.scene
            from . import legenda_locali
            sig = tuple(id(g) for g in _room_groups(sc)
                        + legenda_locali.legend_groups(sc))
            have = sum(1 for t in sc.text_labels
                       if getattr(t, "layer", None) in (LAYER_NAME,
                                                        legenda_locali.LAYER_LEG))
            sig = (sig, have)
            if sig != state["sig"]:
                if state["sig"] is None or state["sig"][0] != sig[0]:
                    sync_native_labels(sc)
                    api.window.viewport.update()
                state["sig"] = (sig[0], sum(
                    1 for t in sc.text_labels
                    if getattr(t, "layer", None) in (
                        LAYER_NAME, legenda_locali.LAYER_LEG)))
        except Exception:
            pass

    t = QTimer(api.window)
    t.timeout.connect(tick)
    t.start(700)
    state["t"] = t
    _WATCH["t"] = t


_WATCH = {}


def register(api) -> None:
    _watch(api)
    api.add_button(tr("Stanza"),
                   tr("Clic al centro di una stanza chiusa da muri: scrive "
                      "nome, area e perimetro"),
                   _icon(), api.run_tool(StanzaTool()), group="Piani")
    api.add_button(tr("Mostra/nascondi etichette"),
                   tr("Nasconde o mostra stanze, legenda e codici per alleggerire "
                      "la vista"),
                   _icon_toggle(),
                   lambda: toggle_labels(api.window.viewport), group="Piani")


LABEL_LAYERS = ("Stanze", "Etichette ID", "Legenda locali")


def labels_hidden(scene) -> bool:
    for ly in scene.layers:
        if ly.name in LABEL_LAYERS and getattr(ly, "visible", True) is False:
            return True
    return False


def toggle_labels(viewport) -> None:
    sc = viewport.scene
    show = labels_hidden(sc)
    for ly in sc.layers:
        if ly.name in LABEL_LAYERS:
            for attr, val in (("visible", show), ("hidden", not show)):
                if hasattr(ly, attr):
                    try:
                        setattr(ly, attr, val)
                    except Exception:
                        pass
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(
        tr("Etichette mostrate") if show else tr("Etichette nascoste"), 3000)


def _icon_toggle():
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.drawRect(8, 12, 32, 24)
    p.drawLine(12, 40, 36, 8)
    p.end()
    return QIcon(pm)
