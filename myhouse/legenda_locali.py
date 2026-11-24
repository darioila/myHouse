# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QVector3D

from tools.base import Tool, ToolContext

from . import etichetta_id, muri, stanza

ORDER = 99
KEY = "mh_legenda_locali"
FILL = (1.0, 1.0, 1.0)
INK = (0.0, 0.0, 0.0)
OFF_Z = 0.02
OFF_INK = 0.002
ROW_H = 2.2
PAD = 0.7
LINE_W = 0.07
DESC = ("gjpqy", 0.29)
DESC_SMALL = (",;", 0.20)


def _natural(name: str):
    return [int(t) if t.isdigit() else t.casefold()
            for t in re.split(r"(\d+)", name.strip())]


def _level_of(scene, d: dict):
    from . import piani
    if d.get("lv"):
        return d["lv"]
    lvs = piani.levels(scene)
    if not lvs:
        return None
    z = float(d.get("z", 0.0)) - stanza.OFF_Z
    best = None
    for lv in lvs:
        if lv["z"] <= z + 0.05:
            best = lv["id"]
    return best or lvs[0]["id"]


def room_rows(scene, level_id):
    rows = []
    for g in scene.groups:
        ext = getattr(g, "ext", None)
        if not (isinstance(ext, dict) and stanza.KEY in ext):
            continue
        d = ext[stanza.KEY]
        if level_id and _level_of(scene, d) != level_id:
            continue
        try:
            rows.append(((d.get("name") or "").strip() or tr("senza nome"),
                         float(d["area"]), float(d["perim"])))
        except Exception:
            continue
    rows.sort(key=lambda r: _natural(r[0]))
    return rows


def _cells(rows):
    head = (tr("Locale"), tr("Area"), tr("Perimetro"))
    body = [(n, stanza._num(a) + " m\u00b2", stanza._num(p) + " m")
            for n, a, p in rows]
    tot = (tr("Totale"), stanza._num(sum(r[1] for r in rows)) + " m\u00b2",
           stanza._num(sum(r[2] for r in rows)) + " m")
    return [head] + body + [tot]


def layout(rows, size: float):
    pad = PAD * size
    title = tr("Legenda locali")
    cells = _cells(rows)
    widths = [0.0, 0.0, 0.0]
    for row in cells:
        for i, t in enumerate(row):
            widths[i] = max(widths[i], etichetta_id.text_shape(t, size)[0])
    widths = [w + 2 * pad for w in widths]
    tw = etichetta_id.text_shape(title, size)[0] + 2 * pad
    if tw > sum(widths):
        widths[0] += tw - sum(widths)
    return widths, ROW_H * size, sum(widths), len(cells) + 1


def _rects(rows, size: float, x0: float, y0: float):
    widths, rh, total, n = layout(rows, size)
    h = rh * n
    segs = []
    for i in range(n + 1):
        y = y0 - i * rh
        segs.append(((x0, y), (x0 + total, y)))
    xs = [x0]
    for w in widths:
        xs.append(xs[-1] + w)
    segs.append(((xs[0], y0), (xs[0], y0 - h)))
    segs.append(((xs[-1], y0), (xs[-1], y0 - h)))
    for x in xs[1:-1]:
        segs.append(((x, y0 - rh), (x, y0 - h)))
    return segs


def _text_baseline_shift(txt: str, shapes, size: float) -> float:
    ys = [p[1] for outer, _h in shapes for p in outer]
    if not ys:
        return 0.0
    ymin = min(ys)
    depth = 0.0
    if any(c in txt for c in DESC[0]):
        depth = DESC[1] * size
    elif any(c in txt for c in DESC_SMALL[0]):
        depth = DESC_SMALL[1] * size
    baseline = ymin + depth
    return -size / 2.0 - baseline


LAYER_LEG = "Legenda locali"
LEGEND_NATIVE = True    # testi nativi leggeri, dimensione fissa con lo zoom


def cell_texts(rows, size: float, x0: float, y0: float):
    """(testo, cx, cy) di titolo e celle, al centro di ciascuna cella."""
    widths, rh, total, _n = layout(rows, size)
    out = [(tr("Legenda locali"), x0 + total / 2.0, y0 - rh / 2.0)]
    xs = [x0]
    for w in widths:
        xs.append(xs[-1] + w)
    for i, row in enumerate(_cells(rows)):
        cy = y0 - rh * (i + 1) - rh / 2.0
        for j, t in enumerate(row):
            out.append((t, (xs[j] + xs[j + 1]) / 2.0, cy))
    return out


def legend_groups(scene):
    return [g for g in scene.groups
            if isinstance(getattr(g, "ext", None), dict) and KEY in g.ext
            and g.ext[KEY].get("t")]


def sync_legend_labels(scene) -> None:
    from core.textlabel import TextLabel
    scene.text_labels[:] = [t for t in scene.text_labels
                            if getattr(t, "layer", None) != LAYER_LEG]
    if not LEGEND_NATIVE:
        return
    for g in legend_groups(scene):
        d = g.ext[KEY]
        z = float(d.get("z", 0.0)) + OFF_INK
        for txt, cx, cy in d["t"]:
            scene.text_labels.append(TextLabel(
                QVector3D(cx, cy, z), QVector3D(0.0, 0.0, 0.0), txt,
                LAYER_LEG))


def table_mesh(rows, size: float, x0: float, y0: float, z: float):
    from core.mesh import Mesh
    if LEGEND_NATIVE:
        return stanza._marker_mesh((x0, y0), z)
    P = QVector3D
    mesh = Mesh()
    layer = stanza.LAYER_NAME

    def face(ring, color, mat, zz):
        f = mesh.add_face([P(x, y, zz) for x, y in ring])
        f.attrs["color"] = color
        f.attrs["mat"] = mat
        f.attrs["layer"] = layer

    widths, rh, total, n = layout(rows, size)
    face([(x0, y0 - rh * n), (x0 + total, y0 - rh * n),
          (x0 + total, y0), (x0, y0)], FILL, tr("legenda locali fondo"), z)

    GREY = (0.86, 0.86, 0.86)
    for r in (1, n - 1):
        face([(x0, y0 - rh * (r + 1)), (x0 + total, y0 - rh * (r + 1)),
              (x0 + total, y0 - rh * r), (x0, y0 - rh * r)], GREY,
             tr("legenda locali fondo"), z + OFF_INK / 2)

    lw = LINE_W * size
    for (ax, ay), (bx, by) in _rects(rows, size, x0, y0):
        if ay == by:
            ring = [(ax, ay - lw / 2), (bx, ay - lw / 2),
                    (bx, ay + lw / 2), (ax, ay + lw / 2)]
        else:
            ring = [(ax - lw / 2, by), (ax + lw / 2, by),
                    (ax + lw / 2, ay), (ax - lw / 2, ay)]
        face(ring, INK, tr("legenda locali bordo"), z + OFF_INK)

    def text(txt, cx, cy, mode, cell_x0, cell_w):
        w, shapes = etichetta_id.text_shape(txt, size)
        dy = _text_baseline_shift(txt, shapes, size)
        pad = PAD * size
        if mode == "l":
            cx = cell_x0 + pad + w / 2
        elif mode == "r":
            cx = cell_x0 + cell_w - pad - w / 2
        else:
            cx = cell_x0 + cell_w / 2
        for outer, holes in shapes:
            ring = [P(cx + x, cy + dy + y, z + OFF_INK) for x, y in outer]
            hs = [[P(cx + x, cy + dy + y, z + OFF_INK) for x, y in h]
                  for h in holes]
            try:
                f = mesh.add_face(ring, hs) if hs else mesh.add_face(ring)
            except Exception:
                f = mesh.add_face(ring)
            f.attrs["color"] = INK
            f.attrs["mat"] = tr("legenda locali testo")
            f.attrs["layer"] = layer

    if LEGEND_NATIVE:
        return mesh
    text(tr("Legenda locali"), 0, y0 - rh / 2, "c", x0, total)
    xs = [x0]
    for w in widths:
        xs.append(xs[-1] + w)
    for i, row in enumerate(_cells(rows)):
        cy = y0 - rh * (i + 1) - rh / 2
        for j, t in enumerate(row):
            text(t, 0, cy, "l" if j == 0 else "r", xs[j], widths[j])
    return mesh


def build_table(scene, rows, size, x0, y0, z, level_id):
    from core.group import Group
    if not any(ly.name == stanza.LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(stanza.LAYER_NAME))
    part = Group(table_mesh(rows, size, x0, y0, z), name=tr("Tabella locali"))
    part.component = False
    g = Group(name=tr("Legenda locali"))
    g.adopt([part])
    g.component = False
    g.layer = stanza.LAYER_NAME
    g.ext = {KEY: {"lv": level_id or "", "size": size, "c": [x0, y0], "z": z,
                   "n": len(rows)}}
    if LEGEND_NATIVE:
        cells = _cells(rows)
        g.ext[KEY]["cells"] = [list(r) for r in cells]
        g.ext[KEY]["title"] = tr("Legenda locali")
    scene.groups.append(g)
    return g


def _old_tables(scene, level_id):
    return [g for g in scene.groups
            if isinstance(getattr(g, "ext", None), dict) and KEY in g.ext
            and (g.ext[KEY].get("lv") or None) == (level_id or None)]


class LegendaLocaliTool(Tool):
    name = tr("Legenda locali")
    shortcut = None
    description = tr("Clic = posiziona la tabella con le stanze del piano "
                     "(nome, m\u00b2, perimetro) in ordine alfabetico.")

    def __init__(self) -> None:
        self._entering = False
        self.hover = None
        self.rows = []
        self.size = 0.20
        self.level = None

    def on_activate(self, viewport) -> None:
        self._vp = viewport
        if self._entering:
            self.hover = None
            return
        from . import piani
        self.level = piani.active_id(viewport.scene)
        self.rows = room_rows(viewport.scene, self.level)
        if not self.rows:
            viewport.flash_status(
                tr("Nessuna stanza su questo piano: inserisci prima le "
                   "etichette con il comando Stanza"), 6000)
            return
        self.size = etichetta_id.current_size(viewport.scene)
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False
        viewport.flash_status(
            tr("Legenda locali ({0} stanze): clic = angolo in alto a sinistra "
               "della tabella · tasto destro o Esc = esci").format(
                len(self.rows)), 7000)

    def on_deactivate(self, viewport) -> None:
        self.hover = None

    def on_cancel(self, viewport) -> None:
        self.hover = None
        viewport.update()

    def _exit(self, viewport) -> None:
        self.hover = None
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
        self.hover = (ctx.world.x(), ctx.world.y())
        ctx.viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        if getattr(vp.scene, "edit_group", None) is not None:
            vp.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        from . import piani
        x0, y0 = ctx.world.x(), ctx.world.y()
        rows = room_rows(vp.scene, self.level) or self.rows
        size, level = self.size, self.level
        lv = piani.get(vp.scene, level)
        z = (lv["z"] if lv else 0.0) + OFF_Z

        def mutate(scene):
            for old in _old_tables(scene, level):
                scene.groups.remove(old)
            build_table(scene, rows, size, x0, y0, z, level)

        vp.history.execute(muri.MuriCommand(mutate))
        vp.notify_scene_changed()
        vp.flash_status(tr("Legenda locali inserita: {0} stanze").format(
            len(rows)), 4000)
        vp.update()

    def rubber_band_lines(self):
        if self.hover is None or not self.rows:
            return []
        lv = None
        try:
            from . import piani
            lv = piani.get(self._vp.scene, self.level)
        except Exception:
            pass
        z = (lv["z"] if lv else 0.0) + OFF_Z + 0.01
        x0, y0 = self.hover
        widths, rh, total, n = layout(self.rows, self.size)
        out = []
        for a, b in _rects(self.rows, self.size, x0, y0):
            out.append((QVector3D(a[0], a[1], z), QVector3D(b[0], b[1], z)))
        return out

    def draw_overlay(self, viewport, painter) -> None:
        pass


def _icon():
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(255, 255, 255))
    p.drawRect(6, 8, 36, 32)
    p.setBrush(QColor(200, 200, 200))
    p.drawRect(6, 8, 36, 8)
    p.drawLine(6, 24, 42, 24)
    p.drawLine(6, 32, 42, 32)
    p.drawLine(22, 16, 22, 40)
    p.end()
    return QIcon(pm)


def register(api) -> None:
    if _LEG["ctl"] is None:
        _LEG["ctl"] = _LegCtl(api.window.viewport)
    api.add_button(tr("Legenda locali"),
                   tr("Tabella con le stanze del piano (nome, m\u00b2, "
                      "perimetro) in ordine alfabetico"),
                   _icon(), api.run_tool(LegendaLocaliTool()), group="Piani")


# ---- Tabella disegnata in pixel (testo e tabella insieme, sempre in scala) --

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget


def overlay_groups(scene):
    return [g for g in scene.groups
            if isinstance(getattr(g, "ext", None), dict) and KEY in g.ext
            and g.ext[KEY].get("cells")]


class _LegOverlay(QWidget):
    def __init__(self, vp, ctl) -> None:
        super().__init__(vp)
        self.ctl = ctl
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(vp.rect())
        self.show()
        self.raise_()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            self.ctl.draw(p)
        except Exception:
            pass
        finally:
            p.end()


class _LegResize(QObject):
    def __init__(self, ctl) -> None:
        super().__init__(ctl.vp)
        self.ctl = ctl

    def eventFilter(self, obj, ev):
        if obj is not self.ctl.vp:
            return False
        t = ev.type()
        if t == QEvent.Resize:
            self.ctl.overlay.setGeometry(self.ctl.vp.rect())
        elif t == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
            return self.ctl.press(ev)
        elif t == QEvent.MouseMove and self.ctl.drag is not None:
            return self.ctl.move(ev)
        elif t == QEvent.MouseButtonRelease and self.ctl.drag is not None:
            return self.ctl.release(ev)
        return False


class _LegCtl:
    def __init__(self, vp) -> None:
        self.vp = vp
        self.overlay = _LegOverlay(vp, self)
        self.filter = _LegResize(self)
        vp.installEventFilter(self.filter)
        self._sig = None
        self.rects = []
        self.drag = None
        self.timer = QTimer(vp)
        self.timer.timeout.connect(self._tick)
        self.timer.start(80)

    def _select_active(self) -> bool:
        if getattr(self.vp.scene, "edit_group", None) is not None:
            return False
        for n in ("active_tool", "tool", "_tool", "current_tool"):
            t = getattr(self.vp, n, None)
            if t is not None:
                nm = (str(getattr(t, "name", "")) or type(t).__name__).lower()
                return "sel" in nm
        return True

    def _hit(self, pos):
        x, y = pos.x(), pos.y()
        for r, g in reversed(self.rects):
            if r.contains(x, y):
                return g
        return None

    def press(self, ev) -> bool:
        if self._hidden() or not self._select_active():
            return False
        g = self._hit(ev.position())
        if g is None:
            return False
        sc = self.vp.scene
        if not (ev.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier)):
            sc.selection.clear()
        sc.selection.add(g)
        d = g.ext[KEY]
        self.drag = {"g": g, "p": ev.position(), "c0": list(d.get("c")),
                     "moved": False}
        self.overlay.update()
        self.vp.update()
        return True

    def _world_delta(self, d, dx, dy):
        """Spostamento in pixel -> metri sul piano della legenda."""
        c, z = d["c"], float(d.get("z", 0.0))
        P = self.vp._world_to_pixel
        p0 = P(QVector3D(c[0], c[1], z))
        px = P(QVector3D(c[0] + 1.0, c[1], z))
        py = P(QVector3D(c[0], c[1] + 1.0, z))
        if p0 is None or px is None or py is None:
            return None
        a, b = px[0] - p0[0], px[1] - p0[1]
        cc, dd = py[0] - p0[0], py[1] - p0[1]
        det = a * dd - b * cc
        if abs(det) < 1e-9:
            return None
        return ((dx * dd - dy * cc) / det, (a * dy - b * dx) / det)

    def move(self, ev) -> bool:
        dr = self.drag
        g = dr["g"]
        d = dict(g.ext[KEY])
        dx, dy = ev.position().x() - dr["p"].x(), ev.position().y() - dr["p"].y()
        w = self._world_delta(d, dx, dy)
        if w is not None:
            d["c"] = [d["c"][0] + w[0], d["c"][1] + w[1]]
            ext = dict(g.ext)
            ext[KEY] = d
            g.ext = ext
            dr["p"] = ev.position()
            dr["moved"] = True
            self.overlay.update()
        return True

    def release(self, ev) -> bool:
        dr, self.drag = self.drag, None
        g = dr["g"]
        if dr["moved"]:
            final = list(g.ext[KEY]["c"])
            ext = dict(g.ext)
            ext[KEY] = dict(ext[KEY], c=dr["c0"])
            g.ext = ext          # stato iniziale, poi un solo passo di undo

            def mutate(sc):
                from core.group import Group
                e = dict(g.ext)
                dd = dict(e[KEY], c=final)
                e[KEY] = dd
                g.ext = e
                part = Group(stanza._marker_mesh(final, float(dd.get("z", 0.0))),
                             name=tr("Tabella locali"))
                part.component = False
                g.children = [part]

            self.vp.history.execute(muri.MuriCommand(mutate))
            self.vp.notify_scene_changed()
        self.overlay.update()
        self.vp.update()
        return True

    def _hidden(self) -> bool:
        for ly in self.vp.scene.layers:
            if ly.name == stanza.LAYER_NAME and getattr(ly, "visible", True) is False:
                return True
        return False

    def _anchor_px(self, d):
        c = d.get("c") or [0.0, 0.0]
        px = self.vp._world_to_pixel(
            QVector3D(c[0], c[1], float(d.get("z", 0.0))))
        return None if px is None else (round(px[0], 1), round(px[1], 1))

    def _tick(self) -> None:
        try:
            sc = self.vp.scene
            sig = (self._hidden(), self.vp.width(), self.vp.height(),
                   tuple(id(x) for x in sc.selection),
                   tuple((id(g), str(g.ext[KEY].get("cells")),
                          self._anchor_px(g.ext[KEY]))
                         for g in overlay_groups(sc)))
        except Exception:
            return
        if sig != self._sig:
            self._sig = sig
            self.overlay.update()

    def draw(self, p: QPainter) -> None:
        self.rects = []
        if self._hidden():
            return
        font = QFont()
        font.setPointSize(9)
        p.setFont(font)
        fm = p.fontMetrics()
        for g in overlay_groups(self.vp.scene):
            d = g.ext[KEY]
            a = self._anchor_px(d)
            if a is None:
                continue
            cells = [list(r) for r in d["cells"]]
            if cells and len(cells[0]) > 1 and cells[0][1] == "m\u00b2":
                cells[0][1] = tr("Area")   # legende gia' inserite
            title = d.get("title") or ""
            pad = 8.0
            rh = fm.height() * 1.6
            widths = [0.0, 0.0, 0.0]
            for row in cells:
                for i, t in enumerate(row):
                    widths[i] = max(widths[i], fm.horizontalAdvance(t))
            widths = [w + 2 * pad for w in widths]
            tw = fm.horizontalAdvance(title) + 2 * pad
            if tw > sum(widths):
                widths[0] += tw - sum(widths)
            total = sum(widths)
            n = len(cells) + 1
            x0, y0 = a
            self.rects.append((QRectF(x0, y0, total, n * rh), g))
            grey, white = QColor(220, 220, 220), QColor(255, 255, 255)
            for r in range(n):
                col = grey if r in (1, n - 1) else white
                p.fillRect(QRectF(x0, y0 + r * rh, total, rh), col)
            p.setPen(QPen(QColor(0, 0, 0), 1.2))
            for r in range(n + 1):
                p.drawLine(QPointF(x0, y0 + r * rh), QPointF(x0 + total, y0 + r * rh))
            xs = [x0]
            for w in widths:
                xs.append(xs[-1] + w)
            p.drawLine(QPointF(xs[0], y0), QPointF(xs[0], y0 + n * rh))
            p.drawLine(QPointF(xs[-1], y0), QPointF(xs[-1], y0 + n * rh))
            for x in xs[1:-1]:
                p.drawLine(QPointF(x, y0 + rh), QPointF(x, y0 + n * rh))
            if g in self.vp.scene.selection:
                p.setPen(QPen(QColor(243, 115, 41), 3))
                p.setBrush(Qt.NoBrush)
                p.drawRect(QRectF(x0, y0, total, n * rh))
            p.setPen(QPen(QColor(0, 0, 0), 1.2))
            bold = QFont(font)
            bold.setBold(True)
            p.setFont(bold)
            p.drawText(QRectF(x0, y0, total, rh), Qt.AlignCenter, title)
            p.setFont(font)
            for i, row in enumerate(cells):
                for j, t in enumerate(row):
                    rect = QRectF(xs[j] + pad, y0 + (i + 1) * rh,
                                  widths[j] - 2 * pad, rh)
                    p.drawText(rect, (Qt.AlignLeft if j == 0 else Qt.AlignRight)
                               | Qt.AlignVCenter, t)


_LEG = {"ctl": None}
