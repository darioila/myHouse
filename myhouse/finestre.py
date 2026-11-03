# SPDX-License-Identifier: GPL-3.0-or-later
"""Plugin Finestre per IngeTrazo — inserisce finestre parametriche.

File della cartella myhouse/ (vedi myhouse/__init__.py).

Uso: MyHouse > Finestra, imposta le misure, poi:
  - clic              posa la finestra con lo spigolo sul punto cliccato
  - Spazio            ribalta la finestra: lo spigolo passa dall'altro lato
  - Esc               esce dal comando
  - tasto destro      esce dal comando
Se il cursore sta su un muro creato con lo strumento Muri, la finestra si
orienta lungo il muro e si centra nel suo spessore, e l'altezza da terra
parte dalla base del muro. Altrimenti si orienta lungo X e l'altezza da
terra parte dal punto cliccato.

Misure: larghezza e altezza totali, altezza da terra (soglia), 1 o 2 ante,
larghezza e profondità del telaio, larghezza del profilo dell'anta.
Doppio clic su una finestra (con lo strumento Seleziona): modifica le misure.
Ogni finestra è un gruppo (IfcWindow) con le parti Telaio e Vetro.
"""
from __future__ import annotations

import copy
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QMatrix4x4, QPen, QVector3D
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QVBoxLayout,
)

from core import bim
from core.history import Command
from core.units import fmt_len
from tools.base import Tool, ToolContext

from . import muri, piani

KEY = "myhouse_finestra"          # chiave dei parametri in group.ext
LAYER_NAME = "Finestre"
FRAME_COLOR = (0.93, 0.93, 0.90)
GLASS_COLOR = (0.62, 0.80, 0.92)
GLASS_OPACITY = 0.45
GLASS_T = 0.02                    # spessore del vetro
WALL_KEY = "myhouse_muro"         # parametri dei muri (vedi muri.py)
WALL_TOL = 0.15                   # distanza dal muro entro cui lo "aggancia"
ORDER = 40                        # posizione del pulsante nella barra


class _Settings:
    W = 1.20            # larghezza totale
    H = 1.40            # altezza totale
    sill = 0.90         # altezza da terra
    leaves = 1          # numero di ante (1 o 2)
    fw = 0.06           # telaio: larghezza del profilo
    fd = 0.07           # telaio: profondità
    sw = 0.05           # profilo dell'anta
    flip = False        # spigolo: False = sinistro, True = destro
    level = None        # piano dei muri su cui posare (None = tutti)


def _params() -> dict:
    return {"W": _Settings.W, "H": _Settings.H, "sill": _Settings.sill,
            "leaves": _Settings.leaves, "fw": _Settings.fw,
            "fd": _Settings.fd, "sw": _Settings.sw}


def _store(p: dict) -> None:
    _Settings.W, _Settings.H, _Settings.sill = p["W"], p["H"], p["sill"]
    _Settings.leaves, _Settings.fw = p["leaves"], p["fw"]
    _Settings.fd, _Settings.sw = p["fd"], p["sw"]


def validate(p: dict) -> str | None:
    n = p["leaves"]
    if p["W"] <= 2 * p["fw"] + n * 2 * p["sw"] + 0.04:
        return "Larghezza troppo piccola per telaio e ante"
    if p["H"] <= 2 * p["fw"] + 2 * p["sw"] + 0.04:
        return "Altezza troppo piccola per telaio e ante"
    return None


# ---------------------------------------------------------------------------
# Geometria (coordinate locali = mondo alla creazione)
# ---------------------------------------------------------------------------

def _axes(d: dict):
    """Versori in pianta: u lungo la larghezza, n in profondità. Con il
    ribaltamento la finestra gira di 180° attorno allo spigolo."""
    ux, uy = d["u"]
    if d.get("flip"):
        ux, uy = -ux, -uy
    return (ux, uy), (-uy, ux)


def _mapper(d: dict):
    (ux, uy), (nx, ny) = _axes(d)
    ox, oy, oz = d["o"]
    z0 = oz + d["sill"]

    def T(a, b, c):
        return QVector3D(ox + a * ux + b * nx, oy + a * uy + b * ny, z0 + c)
    return T


def _box(mesh, T, a0, a1, b0, b1, c0, c1, color, opacity=None):
    """Prisma chiuso con le normali verso l'esterno (a lungo u, b profondità,
    c verso l'alto: terna destra)."""
    quads = [
        [(a0, b0, c0), (a0, b0, c1), (a0, b1, c1), (a0, b1, c0)],   # a-
        [(a1, b0, c0), (a1, b1, c0), (a1, b1, c1), (a1, b0, c1)],   # a+
        [(a0, b0, c0), (a1, b0, c0), (a1, b0, c1), (a0, b0, c1)],   # b-
        [(a0, b1, c0), (a0, b1, c1), (a1, b1, c1), (a1, b1, c0)],   # b+
        [(a0, b0, c0), (a0, b1, c0), (a1, b1, c0), (a1, b0, c0)],   # c-
        [(a0, b0, c1), (a1, b0, c1), (a1, b1, c1), (a0, b1, c1)],   # c+
    ]
    for q in quads:
        f = mesh.add_face([T(*v) for v in q])
        # nessun colore predefinito: si applicano i materiali di IngeTrazo
        f.attrs["layer"] = LAYER_NAME
        if opacity is not None:
            f.attrs["opacity"] = opacity
            f.attrs["back"] = True


def window_meshes(d: dict):
    """(mesh del telaio con le ante, mesh del vetro) dai parametri."""
    from core.mesh import Mesh
    err = validate(d)
    if err:
        raise ValueError(err)
    T = _mapper(d)
    W, H, fw, fd, sw = d["W"], d["H"], d["fw"], d["fd"], d["sw"]
    n = int(d["leaves"])
    sd = fd * 0.6                       # profondità del profilo dell'anta
    frame, glass = Mesh(), Mesh()

    # Telaio fisso: montanti a tutta altezza, traversi in mezzo.
    fb0, fb1 = -fd / 2, fd / 2
    _box(frame, T, 0, fw, fb0, fb1, 0, H, FRAME_COLOR)
    _box(frame, T, W - fw, W, fb0, fb1, 0, H, FRAME_COLOR)
    _box(frame, T, fw, W - fw, fb0, fb1, 0, fw, FRAME_COLOR)
    _box(frame, T, fw, W - fw, fb0, fb1, H - fw, H, FRAME_COLOR)

    # Ante: un profilo ad anello e un vetro ciascuna.
    wl = (W - 2 * fw) / n
    sb0, sb1 = -sd / 2, sd / 2
    c0, c1 = fw, H - fw
    for i in range(n):
        a0 = fw + i * wl
        a1 = a0 + wl
        _box(frame, T, a0, a0 + sw, sb0, sb1, c0, c1, FRAME_COLOR)
        _box(frame, T, a1 - sw, a1, sb0, sb1, c0, c1, FRAME_COLOR)
        _box(frame, T, a0 + sw, a1 - sw, sb0, sb1, c0, c0 + sw, FRAME_COLOR)
        _box(frame, T, a0 + sw, a1 - sw, sb0, sb1, c1 - sw, c1, FRAME_COLOR)
        _box(glass, T, a0 + sw, a1 - sw, -GLASS_T / 2, GLASS_T / 2,
             c0 + sw, c1 - sw, GLASS_COLOR, GLASS_OPACITY)
    return frame, glass


def outline_lines(d: dict):
    """Gli spigoli del parallelepipedo d'ingombro (anteprima)."""
    T = _mapper(d)
    W, H, fd = d["W"], d["H"], d["fd"]
    pts = [T(a, b, c) for c in (0, H) for b in (-fd / 2, fd / 2)
           for a in (0, W)]
    # indici: c*4 + b*2 + a
    pairs = []
    for base in (0, 4):
        pairs += [(base, base + 1), (base + 2, base + 3),
                  (base, base + 2), (base + 1, base + 3)]
    pairs += [(i, i + 4) for i in range(4)]
    return [(pts[i], pts[j]) for i, j in pairs]


def _part(name, mesh, pose=None):
    from core.group import Group
    part = Group(mesh, name=name)
    part.xform = QMatrix4x4(pose) if pose is not None else QMatrix4x4()
    part.component = False
    return part


def _parts(d: dict, pose=None):
    frame, glass = window_meshes(d)
    return [_part("Telaio", frame, pose), _part("Vetro", glass, pose)]


def window_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "o" in data else None


def _pose(group) -> QMatrix4x4:
    for k in getattr(group, "children", None) or ():
        if k.xform is not None:
            return QMatrix4x4(k.xform)
    return QMatrix4x4()


def _next_name(scene) -> str:
    used = {g.name for g in scene.groups}
    n = 1
    while f"Finestra {n}" in used:
        n += 1
    return f"Finestra {n}"


def make_window(scene, p: dict, place: dict):
    from core.group import Group
    d = dict(p)
    d.update(o=list(place["o"]), u=list(place["u"]),
             flip=bool(place["flip"]))
    for k in ("lv", "lvn", "off"):
        if k in place:
            d[k] = place[k]
    parts = _parts(d)                      # solleva prima di aggiungere nulla
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    name = _next_name(scene)
    g = Group(name=name)
    g.adopt(parts)
    g.component = False
    g.layer = LAYER_NAME
    bim.tag_group(g, "IfcWindow", name)
    g.ext = {KEY: d}
    scene.groups.append(g)
    return g


def rebuild_window(group, p: dict) -> None:
    """Nuove misure, stesso posto: spostamenti e rotazioni restano."""
    d = dict(window_data(group))
    d.update(p)
    pose = _pose(group)
    group.children = _parts(d, pose)
    ext = dict(group.ext or {})
    ext[KEY] = d
    group.ext = ext


class FinestraCommand(Command):
    """Un solo passo di undo: gruppi (elenco, parti, tag, parametri, matrice)."""

    def __init__(self, mutate) -> None:
        self.mutate = mutate
        self.before = self.after = None

    @staticmethod
    def _capture(scene) -> dict:
        return {
            "mesh": scene.mesh.capture_state(),
            "layers": list(scene.layers),
            "groups": list(scene.groups),
            "state": [(g, list(g.children or ()), g.ifc and dict(g.ifc),
                       copy.deepcopy(getattr(g, "ext", None)), g.xform)
                      for g in scene.groups],
        }

    @staticmethod
    def _restore(scene, s) -> None:
        scene.mesh.restore_state(s["mesh"])
        scene.layers[:] = s["layers"]
        scene.groups[:] = s["groups"]
        for g, kids, ifc, ext, xform in s["state"]:
            g.children, g.ifc, g.xform = list(kids), ifc and dict(ifc), xform
            g.ext = copy.deepcopy(ext)
        scene.selection.intersection_update(
            set(scene.mesh.faces) | set(scene.mesh.edges) | set(scene.groups))

    def do(self, scene) -> None:
        if self.after is None:
            self.before = self._capture(scene)
            try:
                self.mutate(scene)
            except BaseException:
                self._restore(scene, self.before)
                raise
            self.after = self._capture(scene)
        else:
            self._restore(scene, self.after)
        scene.version += 1

    def undo(self, scene) -> None:
        self._restore(scene, self.before)
        scene.version += 1


# ---------------------------------------------------------------------------
# Posizione: sul muro più vicino, oppure libera lungo X
# ---------------------------------------------------------------------------

def _wall_pose(group) -> QMatrix4x4:
    return _full_pose(group)


def find_wall(scene, pt: QVector3D, level_id=None):
    """Il muro (creato con lo strumento Muri) sotto il punto, o None.
    Ritorna (A, B, centro del corpo, dati del muro), in coordinate mondo.
    Con level_id ignora i muri di altri piani (quelli senza piano restano)."""
    best, best_dist = None, None
    for g in scene.groups:
        w = (getattr(g, "ext", None) or {}).get(WALL_KEY)
        if not isinstance(w, dict) or "a" not in w:
            continue
        if level_id and w.get("lv") and w["lv"] != level_id:
            continue
        pose = _wall_pose(g)
        inv, ok = pose.inverted()
        if not ok:
            continue
        lp = inv.map(pt)
        ax, ay = w["a"]
        bx, by = w["b"]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy)
        if L < 1e-9:
            continue
        ux, uy = dx / L, dy / L
        s = (lp.x() - ax) * ux + (lp.y() - ay) * uy      # lungo il muro
        off = (lp.x() - ax) * (-uy) + (lp.y() - ay) * ux  # dall'asse, a sinistra
        th = w["th"]
        dl, dr = {"left": (0.0, th), "right": (th, 0.0)}.get(
            w["align"], (th / 2, th / 2))
        centre = (dl - dr) / 2                            # centro del corpo
        dist = abs(off - centre) - th / 2
        if dist > WALL_TOL or s < -WALL_TOL or s > L + WALL_TOL:
            continue
        if best_dist is None or dist < best_dist:
            A = pose.map(QVector3D(ax, ay, w["z0"]))
            B = pose.map(QVector3D(bx, by, w["z0"]))
            best, best_dist = (A, B, centre, w), dist
    return best


def placement(scene, world: QVector3D, flip: bool, level_id=None) -> dict:
    wall = find_wall(scene, world, level_id)
    if wall is None:
        return {"o": [world.x(), world.y(), world.z()], "u": [1.0, 0.0],
                "flip": flip}
    A, B, centre, w = wall
    dx, dy = B.x() - A.x(), B.y() - A.y()
    L = math.hypot(dx, dy)
    ux, uy = dx / L, dy / L
    s = (world.x() - A.x()) * ux + (world.y() - A.y()) * uy
    nx, ny = -uy, ux
    out = {"o": [A.x() + ux * s + nx * centre,
                 A.y() + uy * s + ny * centre, A.z()],
           "u": [ux, uy], "flip": flip}
    for k in ("lv", "lvn", "off"):          # eredita il piano del muro
        if w.get(k) is not None:
            out[k] = w[k]
    return out


def _full_pose(g) -> QMatrix4x4:
    """Matrice completa di un contenitore: la sua (se c'è) per quella del
    pezzo interno. Copre sia lo spostamento sul gruppo sia sul pezzo."""
    gx = getattr(g, "xform", None)
    m = QMatrix4x4(gx) if gx is not None else QMatrix4x4()
    return m * _pose(g)


def _opening_data(g):
    """Dati di una finestra o di una porta (le due bucano i muri)."""
    d = window_data(g)
    if d is None:
        try:
            from . import porte
            d = porte.door_data(g)
        except ImportError:
            d = None
    return d


def _signature(scene):
    """Impronta di posizione e misure di finestre e muri: cambia se qualcosa
    si sposta, ruota o viene ridimensionato."""
    sig = []
    for g in scene.groups:
        d = _opening_data(g)
        if d is None:
            d = muri.wall_data(g)
        if d is None:
            try:
                from . import tetto
                d = tetto.roof_data(g)          # anche i tetti (taglio muri)
            except ImportError:
                d = None
        if d is None:
            continue
        m = _full_pose(g)
        sig.append((id(g), tuple(round(v, 5) for v in m.data()),
                    repr(sorted((k, repr(v)) for k, v in d.items()
                                if k not in ("open", "clip")))))
    return tuple(sig)


def _openings_for_wall(wg, d, wins):
    ax, ay = d["a"]
    bx, by = d["b"]
    L = math.hypot(bx - ax, by - ay)
    if L < 1e-9:
        return []
    ux, uy = (bx - ax) / L, (by - ay) / L
    inv, ok = _full_pose(wg).inverted()
    if not ok:
        return []
    th = d["th"]
    dl, dr = muri.side_offsets(th, d["align"])
    centre = (dl - dr) / 2
    out = []
    for wgrp in wins:
        wd = _opening_data(wgrp)
        if d.get("lv") and wd.get("lv") and d["lv"] != wd["lv"]:
            continue                          # piani diversi: niente foro
        T = _mapper(wd)
        m = inv * _full_pose(wgrp)
        p0 = m.map(T(0, 0, 0))
        p1 = m.map(T(wd["W"], 0, 0))
        ph = m.map(T(0, 0, wd["H"]))
        dx, dy = p1.x() - p0.x(), p1.y() - p0.y()
        dl_ = math.hypot(dx, dy)
        if dl_ < 1e-9 or abs((dx * ux + dy * uy) / dl_) < 0.99:
            continue
        mx, my = (p0.x() + p1.x()) / 2, (p0.y() + p1.y()) / 2
        off = (mx - ax) * (-uy) + (my - ay) * ux
        if abs(off - centre) > th / 2 + WALL_TOL:
            continue
        sa = (p0.x() - ax) * ux + (p0.y() - ay) * uy
        sb = (p1.x() - ax) * ux + (p1.y() - ay) * uy
        s0, s1 = min(sa, sb), max(sa, sb)
        if s1 <= 0 or s0 >= L:
            continue
        out.append([round(s0, 4), round(s1, 4),
                    round(p0.z(), 4), round(ph.z(), 4)])
    return out


def update_openings(scene) -> int:
    """Ricalcola i fori di tutti i muri in base alle finestre presenti."""
    wins = [g for g in scene.groups if _opening_data(g) is not None]
    n = 0
    for g in scene.groups:
        d = muri.wall_data(g)
        if d is None:
            continue
        ops = _openings_for_wall(g, d, wins)
        if ops == (d.get("open") or []):
            continue
        d2 = dict(d)
        d2["open"] = ops
        g.children = [muri.wall_part(d2, muri.wall_pose(g))]
        ext = dict(g.ext or {})
        ext[muri.KEY] = d2
        g.ext = ext
        n += 1
    return n


_auto = {"pending": False, "sig": None, "timer": None}


def _start_watcher(app) -> None:
    """Controlla ogni 300 ms se una finestra o un muro si è mosso (lo
    spostamento non sempre segnala una modifica del documento)."""
    from PySide6.QtCore import QTimer
    timer = QTimer(app.window)
    timer.setInterval(300)

    def tick():
        try:
            scene = app.viewport.scene
            if getattr(scene, "edit_group", None) is not None:
                return
            sig = _signature(scene)
            if sig != _auto["sig"]:
                _auto["sig"] = sig
                _schedule_auto(app)
        except Exception:
            pass

    timer.timeout.connect(tick)
    timer.start()
    _auto["timer"] = timer


def _schedule_auto(app) -> None:
    """Ad ogni modifica del documento (spostamento, undo, ecc.) ricalcola i
    fori. Rinviato al ciclo successivo e senza undo proprio: i fori sono dati
    derivati dalle posizioni, quindi undo/redo li rigenerano da soli. Se non
    cambia nulla non tocca il documento, così non c'è nessun ciclo."""
    if _auto["pending"]:
        return
    _auto["pending"] = True

    def run():
        _auto["pending"] = False
        try:
            vp = app.viewport
            scene = vp.scene
            if getattr(scene, "edit_group", None) is not None:
                return
            changed = update_openings(scene)
            changed += muri.update_roof_clips(scene)   # muri tagliati dal tetto
            if changed:
                scene.version += 1
                vp.notify_scene_changed()
                vp.update()
        except Exception:
            pass

    from PySide6.QtCore import QTimer
    QTimer.singleShot(0, run)


# ---------------------------------------------------------------------------
# Dialogo (creazione e modifica)
# ---------------------------------------------------------------------------

def _spin(value, lo, hi):
    s = QDoubleSpinBox()
    s.setDecimals(3)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


def ask_params(parent, current: dict, title: str, ok_text: str,
               scene=None):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    W = _spin(current["W"], 0.2, 20.0)
    H = _spin(current["H"], 0.2, 20.0)
    sill = _spin(current["sill"], -10.0, 100.0)
    leaves = QComboBox()
    leaves.addItem("1 anta", 1)
    leaves.addItem("2 ante", 2)
    leaves.setCurrentIndex(leaves.findData(int(current["leaves"])))
    fw = _spin(current["fw"], 0.01, 0.5)
    fd = _spin(current["fd"], 0.02, 1.0)
    sw = _spin(current["sw"], 0.01, 0.5)
    lvl = None
    if scene is not None and piani.levels(scene):
        lvl = piani.level_combo(scene, piani.active_id(scene))
        form.addRow("Piano (muri su cui posare)", lvl)
    form.addRow("Larghezza totale (m)", W)
    form.addRow("Altezza totale (m)", H)
    form.addRow("Altezza da terra (m)", sill)
    form.addRow("Ante", leaves)
    form.addRow("Telaio: larghezza profilo (m)", fw)
    form.addRow("Telaio: profondità (m)", fd)
    form.addRow("Profilo dell'anta (m)", sw)
    lay.addLayout(form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.button(QDialogButtonBox.Ok).setText(ok_text)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return None
    if lvl is not None:
        _Settings.level = lvl.currentData() or None
        piani.set_active(_Settings.level)
    return {"W": W.value(), "H": H.value(), "sill": sill.value(),
            "leaves": leaves.currentData(), "fw": fw.value(),
            "fd": fd.value(), "sw": sw.value()}


# ---------------------------------------------------------------------------
# Strumento interattivo
# ---------------------------------------------------------------------------

class FinestraTool(Tool):
    name = "Finestra"
    shortcut = None
    description = "Inserisce finestre parametriche (1 o 2 ante)."

    def __init__(self) -> None:
        self._entering = False
        self._vp = None
        self.hover: QVector3D | None = None

    # ---- Ciclo di vita ------------------------------------------------------
    def on_activate(self, viewport) -> None:
        if self._entering:                 # richiamato da set_active_tool
            self._vp = viewport
            self.hover = None
            viewport.flash_status(
                "Finestra: clic per posarla · Spazio = ribalta · "
                "Esc / tasto destro = esci", 6000)
            return
        p = ask_params(viewport.window(), _params(), "Finestra", "Posa",
                       viewport.scene)
        if p is None:
            return
        err = validate(p)
        if err:
            viewport.flash_status("Finestra: " + err, 5000)
            return
        _store(p)
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def on_deactivate(self, viewport) -> None:
        self.hover = None

    def _exit(self, viewport) -> None:
        self.hover = None
        viewport.update()
        back = getattr(viewport.window(), "activate_select_tool", None)
        if callable(back):
            back()

    # ---- Input ----------------------------------------------------------------
    def on_hover(self, ctx: ToolContext) -> None:
        self.hover = QVector3D(ctx.world)
        ctx.viewport.update()

    def on_cancel(self, viewport) -> None:
        self.hover = None
        viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        scene = viewport.scene
        if getattr(scene, "edit_group", None) is not None:
            viewport.flash_status(
                "Chiudi il gruppo che stai modificando, poi posa la finestra",
                4000)
            return
        world = QVector3D(ctx.world)
        self.hover = world
        p = _params()
        place = placement(scene, world, _Settings.flip, _Settings.level)

        def mutate(sc):
            make_window(sc, p, place)
            update_openings(sc)

        hist = viewport.history
        hist.execute(FinestraCommand(mutate))
        if getattr(hist, "last_error", None):
            viewport.flash_status(
                "Finestra: " + str(hist.last_error).split(": ", 1)[-1], 6000)
            return
        viewport.notify_scene_changed()
        viewport.flash_status("Finestra creata", 2500)
        viewport.update()

    def context_menu(self, viewport, pos) -> bool:
        """Tasto destro: esce dal comando invece di aprire il menu."""
        self._exit(viewport)
        return True

    # ---- Tastiera ---------------------------------------------------------------
    def _buffer(self) -> str:
        return getattr(self._vp, "_value_buffer", "") or ""

    def claims_key(self, key: int, modifiers) -> bool:
        if modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        if self._buffer():
            return False
        return key in (Qt.Key_Space, Qt.Key_Escape)

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if key == Qt.Key_Space:
            _Settings.flip = not _Settings.flip
            viewport.flash_status(
                "Spigolo " + ("destro" if _Settings.flip else "sinistro"),
                2000)
            viewport.update()
            return True
        return False

    def status_clause(self) -> str:
        return (f"Spigolo {'destro' if _Settings.flip else 'sinistro'} "
                "(Spazio ribalta) · Esc / tasto destro = esci")

    # ---- Anteprima ----------------------------------------------------------------
    def rubber_band_lines(self):
        if self.hover is None:
            return []
        scene = self._vp.scene if self._vp is not None else None
        if scene is None:
            return []
        d = _params()
        d.update(placement(scene, self.hover, _Settings.flip,
                           _Settings.level))
        return outline_lines(d)

    def draw_overlay(self, viewport, painter) -> None:
        try:
            self._draw(viewport, painter)
        except Exception:        # mai rompere il ciclo di disegno
            pass

    def _draw(self, viewport, painter) -> None:
        painter.save()
        font = QFont()
        font.setPointSize(10)
        painter.setFont(font)
        fm = painter.fontMetrics()
        p = _params()
        lines = [
            f"Finestra {fmt_len(p['W'])} × {fmt_len(p['H'])} · "
            f"{int(p['leaves'])} {'anta' if p['leaves'] == 1 else 'ante'}",
            f"Da terra: {fmt_len(p['sill'])} · telaio {fmt_len(p['fw'])} × "
            f"{fmt_len(p['fd'])}",
            f"Spigolo: {'DESTRO' if _Settings.flip else 'SINISTRO'}  "
            "(Spazio ribalta)",
            "Esc / tasto destro = esci",
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


# ---------------------------------------------------------------------------
# Modifica di una finestra già posata (doppio clic o tasto destro)
# ---------------------------------------------------------------------------

def _selected_windows(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and window_data(g) is not None and g not in out:
            out.append(g)
    return out


def edit_windows(viewport, wins=None) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status("Chiudi il gruppo che stai modificando", 4000)
        return
    wins = wins or _selected_windows(scene)
    if not wins:
        viewport.flash_status("Seleziona una finestra creata con lo strumento "
                              "Finestra", 4000)
        return
    d = window_data(wins[0])
    current = {k: d[k] for k in ("W", "H", "sill", "leaves", "fw", "fd", "sw")}
    title = "Modifica finestra" if len(wins) == 1 \
        else f"Modifica {len(wins)} finestre"
    p = ask_params(viewport.window(), current, title, "Applica")
    if p is None:
        return
    err = validate(p)
    if err:
        viewport.flash_status("Finestra: " + err, 5000)
        return

    def mutate(sc):
        for g in wins:
            rebuild_window(g, p)
        update_openings(sc)

    hist = viewport.history
    hist.execute(FinestraCommand(mutate))
    if getattr(hist, "last_error", None):
        viewport.flash_status(
            "Finestra: " + str(hist.last_error).split(": ", 1)[-1], 6000)
        return
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(f"{len(wins)} finestre aggiornate", 3000)


def _hook_double_click(vp) -> None:
    """Doppio clic su una finestra = modifica le misure. Per ogni altro
    gruppo resta il comportamento precedente (entrare nel gruppo, o il
    dialogo dei muri)."""
    if getattr(vp, "_myhouse_fin_dbl", False):
        return
    original = vp.begin_group_edit

    def begin_group_edit(group, *args, **kwargs):
        g = getattr(group, "owner", None) or group
        if window_data(g) is None:
            return original(group, *args, **kwargs)
        from PySide6.QtCore import QTimer
        scene = vp.scene
        try:
            scene.select([g])
        except Exception:
            scene.selection.clear()
            scene.selection.add(g)
        vp.update()
        QTimer.singleShot(0, lambda: edit_windows(vp, [g]))

    vp.begin_group_edit = begin_group_edit
    vp._myhouse_fin_dbl = True


def _outliner_kind(group):
    d = window_data(group)
    if d is None:
        return None
    return {"type": "Finestra",
            "props": [("Larghezza", fmt_len(d["W"])),
                      ("Altezza", fmt_len(d["H"])),
                      ("Da terra", fmt_len(d["sill"])),
                      ("Ante", str(int(d["leaves"])))]
            + piani.level_props(d)}


# ---------------------------------------------------------------------------
# Registrazione sulla barra MyHouse (chiamata da myhouse/__init__.py)
# ---------------------------------------------------------------------------

def _icon():
    """Icona di una finestra a due ante, disegnata a codice."""
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(170, 210, 235))
    p.drawRect(8, 8, 32, 32)
    p.drawLine(24, 8, 24, 40)
    p.setBrush(Qt.NoBrush)
    p.drawRect(12, 12, 24, 24)
    p.end()
    return QIcon(pm)


def _register_level_kind() -> None:
    def zset(d, z):
        o = list(d["o"])
        o[2] = z
        d["o"] = o

    piani.register_kind("finestra", KEY, window_data, lambda d: d["o"][2],
                        zset, rebuild_window)


def register(api) -> None:
    _register_level_kind()
    api.add_button("Finestra", "Inserisce una finestra (1 o 2 ante)",
                   _icon(), api.run_tool(FinestraTool()))
    app = api.app
    app.on_document_changed(lambda *_a: _schedule_auto(app))
    _start_watcher(app)
    _hook_double_click(api.window.viewport)
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        from PySide6.QtCore import QTimer

        def context(menu, selection) -> None:
            if not _selected_windows(app.viewport.scene):
                return
            menu.addSeparator()
            menu.addAction(
                "Modifica finestra…",
                lambda: QTimer.singleShot(
                    0, lambda: edit_windows(app.viewport)))

        add_ctx(context)
    add_kind = getattr(app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
