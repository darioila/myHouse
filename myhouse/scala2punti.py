# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QMatrix4x4, QPainter, QPen, QPixmap, QVector3D

from ._imperial import fmt_len
from tools.base import Tool, ToolContext

from .muri import MuriCommand

ORDER = 140
EPS = 1e-6
COLORE = QColor(0, 170, 255)


def _matrice_scala(p1: QVector3D, f: float) -> QMatrix4x4:
    m = QMatrix4x4()
    m.translate(p1)
    m.scale(f)
    m.translate(-p1)
    return m


def _vertici(elem):
    for name in ("verts", "vertices", "points", "ends"):
        vs = getattr(elem, name, None)
        if vs is not None:
            try:
                return list(vs)
            except TypeError:
                pass
    for n0, n1 in (("a", "b"), ("v0", "v1"), ("p0", "p1"), ("start", "end"),
                   ("v1", "v2"), ("va", "vb")):
        if hasattr(elem, n0) and hasattr(elem, n1):
            return [getattr(elem, n0), getattr(elem, n1)]
    return []


def _leggi(v):
    for name in ("pos", "co", "p", "point", "position"):
        if hasattr(v, name):
            return name, getattr(v, name)
    return None, v


def _sposta_vertice(v, S: QMatrix4x4) -> bool:
    nome, p = _leggi(v)
    try:
        if isinstance(p, QVector3D):
            q = S.map(p)
        else:
            q = S.map(QVector3D(float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0))
    except Exception:
        return False
    try:
        if nome is not None:
            nuovo = q if isinstance(p, QVector3D) else type(p)((q.x(), q.y(), q.z()))
            setattr(v, nome, nuovo)
            return True
        if isinstance(v, QVector3D):
            v.setX(q.x())
            v.setY(q.y())
            v.setZ(q.z())
            return True
    except Exception:
        return False
    return False


def _bersagli(scene, selezione):
    gruppi, sciolti, immagini = [], [], []
    piani = list(getattr(scene, "image_planes", None) or ())
    for e in selezione:
        if any(e is ip for ip in piani):
            if e not in immagini:
                immagini.append(e)
            continue
        g = getattr(e, "owner", None) or e
        if g in scene.groups:
            if g not in gruppi:
                gruppi.append(g)
        elif e not in sciolti:
            sciolti.append(e)
    return gruppi, sciolti, immagini


class _ScalaCommand(MuriCommand):

    @staticmethod
    def _capture(scene) -> dict:
        s = MuriCommand._capture(scene)
        s["img"] = [(ip, QVector3D(ip.origin), QVector3D(ip.u), QVector3D(ip.v))
                    for ip in (getattr(scene, "image_planes", None) or ())]
        return s

    @staticmethod
    def _restore(scene, s) -> None:
        MuriCommand._restore(scene, s)
        for ip, o, u, v in s.get("img", ()):
            ip.origin, ip.u, ip.v = QVector3D(o), QVector3D(u), QVector3D(v)


class Scala2PuntiTool(Tool):
    name = tr("Scala 2 punti")
    shortcut = None
    description = tr("Scala la selezione cliccando 2 punti e digitando la misura reale.")
    vcb_label = tr("Distanza reale")

    def __init__(self) -> None:
        self._entering = False
        self._vp = None
        self.sel = []
        self._reset()

    def _reset(self) -> None:
        self.p1: QVector3D | None = None
        self.p2: QVector3D | None = None
        self.hover: QVector3D | None = None

    def on_activate(self, viewport) -> None:
        if self._entering:
            self._vp = viewport
            self._reset()
            viewport.flash_status(
                tr("Scala 2 punti: clic sul 1° punto della misura nota · Esc = esci"), 6000)
            return
        scene = viewport.scene
        if not scene.selection:
            viewport.flash_status(
                tr("Scala 2 punti: seleziona prima gli oggetti, poi premi il pulsante"), 5000)
            return
        self.sel = list(scene.selection)
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def on_deactivate(self, viewport) -> None:
        self._reset()

    def _exit(self, viewport) -> None:
        self._reset()
        viewport.update()
        back = getattr(viewport.window(), "activate_select_tool", None)
        if callable(back):
            back()

    def on_click(self, ctx: ToolContext) -> None:
        p = QVector3D(ctx.world)
        vp = ctx.viewport
        if self.p1 is None:
            self.p1 = p
            self.hover = p
            vp.flash_status(tr("Clic sul 2° punto della misura nota"), 4000)
        elif self.p2 is None:
            if (p - self.p1).length() < EPS:
                vp.flash_status(tr("I due punti coincidono: clicca un secondo punto diverso"), 3000)
                return
            self.p2 = p
            vp.flash_status(
                tr("Distanza misurata {0}: digita la distanza reale e premi Invio")
                .format(fmt_len((self.p2 - self.p1).length())), 8000)
        vp.update()

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover = QVector3D(ctx.world)
        self._vp = ctx.viewport
        ctx.viewport.update()

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    def claims_key(self, key: int, modifiers) -> bool:
        if modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        return key == Qt.Key_Escape

    def _indietro(self, viewport) -> bool:
        if self.p2 is not None:
            self.p2 = None
        elif self.p1 is not None:
            self.p1 = None
        else:
            return False
        viewport.update()
        return True

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if key == Qt.Key_Backspace and not (getattr(viewport, "_value_buffer", "") or ""):
            return self._indietro(viewport)
        return False

    def context_menu(self, viewport, pos) -> bool:
        if not self._indietro(viewport):
            self._exit(viewport)
        return True

    def on_value(self, viewport, value) -> bool:
        if self.p1 is None or self.p2 is None or isinstance(value, tuple):
            return False
        misurata = (self.p2 - self.p1).length()
        if value <= EPS:
            viewport.flash_status(tr("Digita una distanza maggiore di zero"), 3000)
            return True
        if misurata < EPS:
            return False
        self._applica(viewport, value / misurata)
        return True

    def _applica(self, viewport, fattore: float) -> None:
        scene = viewport.scene
        S = _matrice_scala(self.p1, fattore)
        gruppi, sciolti, immagini = _bersagli(scene, self.sel)
        esito = {"gruppi": 0, "vertici": 0, "saltati": 0, "immagini": 0}

        def mutate(sc):
            for g in gruppi:
                xf = getattr(g, "xform", None)
                g.xform = S * (QMatrix4x4(xf) if xf is not None else QMatrix4x4())
                esito["gruppi"] += 1
            for ip in immagini:
                ip.origin, ip.u, ip.v = (S.map(ip.origin), ip.u * fattore, ip.v * fattore)
                esito["immagini"] += 1
            visti = set()
            for e in sciolti:
                vs = _vertici(e)
                if not vs:
                    esito["saltati"] += 1
                    continue
                for v in vs:
                    if id(v) in visti:
                        continue
                    visti.add(id(v))
                    if _sposta_vertice(v, S):
                        esito["vertici"] += 1
                    else:
                        esito["saltati"] += 1

        viewport.history.execute(_ScalaCommand(mutate))
        viewport.notify_scene_changed()
        if esito["saltati"] and not (esito["gruppi"] or esito["vertici"] or esito["immagini"]):
            viewport.flash_status(
                tr("Scala 2 punti: oggetto non riconosciuto, nessuna scala applicata"), 6000)
        else:
            viewport.flash_status(tr("Scala applicata: x {0:.6g}").format(fattore), 5000)
        self._exit(viewport)

    def status_clause(self) -> str:
        if self.p1 is None:
            return tr("Clic sul 1° punto della misura nota · Esc = esci")
        if self.p2 is None:
            return tr("Clic sul 2° punto · tasto destro / Backspace = indietro · Esc = esci")
        return tr("Digita la distanza reale e premi Invio · tasto destro = indietro · Esc = esci")

    def _fine(self):
        return self.p2 if self.p2 is not None else self.hover

    def value_label(self):
        if self.p1 is None:
            return None
        b = self._fine()
        if b is None or (b - self.p1).length() < EPS:
            return None
        return (fmt_len((b - self.p1).length()), (self.p1 + b) * 0.5)

    def rubber_band_lines(self):
        b = self._fine()
        if self.p1 is None or b is None or (b - self.p1).length() < EPS:
            return []
        return [(self.p1, b)]


def _icon():
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.drawRect(6, 22, 12, 12)
    p.setPen(QPen(COLORE, 2))
    p.drawRect(20, 8, 22, 22)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.drawLine(10, 38, 40, 38)
    p.drawLine(10, 34, 10, 42)
    p.drawLine(40, 34, 40, 42)
    p.end()
    return QIcon(pm)


def register(api) -> None:
    act = api.add_button("Ridimensiona 2 punti",
                         tr("Scala la selezione: clic su 2 punti e digita la misura reale"),
                         _icon(), api.run_tool(Scala2PuntiTool()))
    act.setText(tr("Scala 2 punti"))
    act.setToolTip(tr("Scala 2 punti") + " — "
                   + tr("Scala la selezione: clic su 2 punti e digita la misura reale"))
