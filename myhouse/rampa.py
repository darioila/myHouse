# SPDX-License-Identifier: GPL-3.0-or-later
"""Plugin Rampa per IngeTrazo / MyHouse — rampe inclinate con pianerottoli.

Stessa logica del plugin Scala (scale.py). Uso: MyHouse > Rampa, scegli
larghezza, altezza da raggiungere e quota di partenza, poi clic sui punti
dell'asse della rampa (da 2 a 6):
  - punti 1-2 = prima rampa; 2-3 = seconda rampa; ecc.
  - la linea tracciata può essere il lato sinistro, il lato destro o l'asse
    (guardando verso l'alto); SPAZIO la capovolge dall'altro lato
  - in ogni punto intermedio c'è un pianerottolo piano (quadrato, largo come
    la rampa)
  - Invio conclude (anche con una sola rampa), Backspace toglie l'ultimo
    punto, Esc o tasto destro esce

Altezza da raggiungere: legata a un piano ("Piano successivo" o un piano
preciso, con eventuale distanza dalla sua quota, come per scale e muri) oppure
arbitraria. La pendenza è unica su tutte le rampe: altezza / lunghezza totale
delle parti inclinate (i pianerottoli sono piani). Se il piano cambia altezza,
la rampa si adatta.

Due tipologie: "Piena" (piena fino a terra) e "In c.a." (soletta inclinata,
spessore a scelta).
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPen, QVector3D
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QLineEdit, QVBoxLayout,
)

from core import bim
from tools.base import Tool, ToolContext

from . import muri, piani

ORDER = 71
LAYER_NAME = "Rampe"
KEY = "myhouse_rampa"           # parametri in group.ext
MAX_POINTS = 6
MAX_SLOPE = 0.08                # 8%: oltre, avviso
EPS = 1e-9


class _Settings:
    w = 1.50                    # larghezza rampa
    height = 0.50               # altezza arbitraria da raggiungere
    z = 0.0                     # quota di partenza (da terra)
    name = "Rampa"
    ortho = True
    side = "left"               # linea tracciata: left | right | center
    kind = "piena"              # piena | ca
    th = 0.15                   # spessore soletta in c.a. (verticale)
    level = None                # id del piano di partenza
    tlv = None                  # altezza legata: "next" o id del piano
    toff = 0.0                  # distanza dalla quota di arrivo


# ---------------------------------------------------------------------------
# Geometria pura
# ---------------------------------------------------------------------------

def _rect(a, u, s0, s1, hw):
    """4 angoli (antiorari) del rettangolo che va da s0 a s1 lungo u (partendo
    dal punto a) e largo da -hw a +hw."""
    ax, ay = a
    ux, uy = u
    vx, vy = -uy, ux
    def pt(s, lat):
        return (ax + ux * s + vx * lat, ay + uy * s + vy * lat)
    return [pt(s0, -hw), pt(s1, -hw), pt(s1, hw), pt(s0, hw)]


def _axis_points(pts, w, side):
    """Dalla linea tracciata (lato sinistro/destro o asse) ai punti dell'asse
    della scala. Sinistra/destra = guardando nel verso di salita."""
    off = {"left": -w / 2, "right": w / 2}.get(side, 0.0)
    if off == 0.0 or len(pts) < 2:
        return list(pts)
    normals = []
    for a, b in zip(pts, pts[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        normals.append((-dy / length, dx / length) if length > 1e-9
                       else (0.0, 0.0))
    out = []
    for i, p in enumerate(pts):
        if i == 0:
            n = normals[0]
            out.append((p[0] + n[0] * off, p[1] + n[1] * off))
        elif i == len(pts) - 1:
            n = normals[-1]
            out.append((p[0] + n[0] * off, p[1] + n[1] * off))
        else:
            n1, n2 = normals[i - 1], normals[i]
            k = 1.0 + n1[0] * n2[0] + n1[1] * n2[1]
            if k < 1e-6:
                out.append((p[0] + n1[0] * off, p[1] + n1[1] * off))
            else:
                out.append((p[0] + (n1[0] + n2[0]) * off / k,
                            p[1] + (n1[1] + n2[1]) * off / k))
    return out



def layout(d):
    """Elenco di elementi (rampe inclinate e pianerottoli) dai dati.

    Ogni elemento: kind ("flight"/"landing"), n, a, u, s0, s1, z0, z1
    (quote all'inizio e alla fine; uguali per i pianerottoli), body (angoli),
    centre. La pendenza è unica: altezza / lunghezza totale inclinata.
    """
    w, z0 = d["w"], d["z"]
    pts = _axis_points([tuple(p) for p in d["pts"]], w, d.get("side", "center"))
    hw = w / 2
    raw = []                                   # (tipo, a, u, s0, s1)
    m = len(pts)
    u_prev = None
    for i in range(m - 1):
        a, b = pts[i], pts[i + 1]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length < 1e-6:
            continue
        u = (dx / length, dy / length)
        if i > 0 and u_prev is not None:
            raw.append(("landing", a, u_prev, -hw, hw))
        s0 = hw if i > 0 else 0.0
        s1 = length - (hw if i + 1 < m - 1 else 0.0)
        if s1 - s0 > 1e-6:
            raw.append(("flight", a, u, s0, s1))
        u_prev = u
    total = sum(r[4] - r[3] for r in raw if r[0] == "flight")
    if total < 1e-6:
        return []
    slope = max(d.get("height", 0.0), 0.0) / total
    items = []
    z = z0
    for k, (kind, a, u, s0, s1) in enumerate(raw, 1):
        if kind == "flight":
            z1 = z + slope * (s1 - s0)
            items.append({"kind": kind, "n": k, "a": a, "u": u,
                          "s0": s0, "s1": s1, "z0": z, "z1": z1,
                          "slope": slope,
                          "body": _rect(a, u, s0, s1, hw),
                          "centre": (a[0] + u[0] * (s0 + s1) / 2,
                                     a[1] + u[1] * (s0 + s1) / 2)})
            z = z1
        else:
            items.append({"kind": kind, "n": k, "a": a, "u": u,
                          "s0": s0, "s1": s1, "z0": z, "z1": z,
                          "slope": 0.0,
                          "body": _rect(a, u, s0, s1, hw), "centre": a})
    return items


def total_length(d) -> float:
    return sum(it["s1"] - it["s0"] for it in layout(d)
               if it["kind"] == "flight")


def flight_profile(it, d):
    """Profilo (s, z) antiorario di una rampa inclinata."""
    zb = d["z"]
    s0, s1, z0, z1 = it["s0"], it["s1"], it["z0"], it["z1"]
    slope = it["slope"]
    bottom = [(s0, zb), (s1, zb)]
    if d.get("kind", "piena") == "ca" and slope > EPS:
        dv = d.get("th", 0.15) * math.sqrt(1 + slope * slope)
        zs0, zs1 = z0 - dv, z1 - dv
        if zs1 <= zb + 1e-6:
            pass                                    # troppo bassa: piena
        elif zs0 < zb:
            bottom = [(s0, zb), (s0 + (zb - zs0) / slope, zb), (s1, zs1)]
        else:
            bottom = [(s0, zs0), (s1, zs1)]
    poly = []
    for p in bottom + [(s1, z1), (s0, z0)]:
        if not poly or abs(p[0] - poly[-1][0]) + abs(p[1] - poly[-1][1]) > 1e-9:
            poly.append(p)
    if len(poly) > 1 and (abs(poly[0][0] - poly[-1][0])
                          + abs(poly[0][1] - poly[-1][1])) < 1e-9:
        poly.pop()
    return poly


def ramp_mesh(d):
    from core.mesh import Mesh
    P = QVector3D
    mesh = Mesh()
    zb = d["z"]
    hw = d["w"] / 2
    ca = d.get("kind", "piena") == "ca"

    def face(q):
        f = mesh.add_face(q)
        f.attrs["layer"] = LAYER_NAME      # materiali di IngeTrazo

    def box(corners, z0, z1):
        face([P(x, y, z1) for x, y in corners])
        face([P(x, y, z0) for x, y in reversed(corners)])
        for i in range(4):
            j = (i + 1) % 4
            ci, cj = corners[i], corners[j]
            face([P(ci[0], ci[1], z0), P(cj[0], cj[1], z0),
                  P(cj[0], cj[1], z1), P(ci[0], ci[1], z1)])

    for it in layout(d):
        if it["kind"] == "landing":
            z0 = it["z1"] - d.get("th", 0.15) if ca else zb
            box(it["body"], min(max(z0, zb), it["z1"] - 0.01), it["z1"])
            continue
        a, u = it["a"], it["u"]
        v = (-u[1], u[0])

        def p3(sz, lat):
            return P(a[0] + u[0] * sz[0] + v[0] * lat,
                     a[1] + u[1] * sz[0] + v[1] * lat, sz[1])

        poly = flight_profile(it, d)
        n = len(poly)
        for i in range(n):                  # sotto, testa, piano inclinato
            p, q = poly[i], poly[(i + 1) % n]
            face([p3(p, hw), p3(q, hw), p3(q, -hw), p3(p, -hw)])
        face([p3(t_, -hw) for t_ in poly])  # fianchi
        face([p3(t_, hw) for t_ in reversed(poly)])
    return mesh


def apply_top(scene, d, tlv, toff, level) -> bool:
    """Altezza legata a un piano: height = quota di arrivo - quota di
    partenza. Scrive height/tlv/toff in d."""
    h = piani.height_for(scene, tlv, toff, level, d["z"])
    if h is None or h <= EPS:
        return False
    d["height"] = h
    d["tlv"], d["toff"] = tlv, toff
    return True


def ramp_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "pts" in data else None


def rebuild_ramp(group, d) -> None:
    from core.group import Group
    part = Group(ramp_mesh(d), name="Rampa")
    part.component = False
    group.children = [part]
    ext = dict(group.ext or {})
    ext[KEY] = dict(d)
    group.ext = ext


def build_ramp(scene, d, name) -> None:
    from core.group import Group
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    part = Group(ramp_mesh(d), name="Rampa")
    part.component = False
    g = Group(name=name)
    g.adopt([part])
    g.component = False
    g.layer = LAYER_NAME
    bim.tag_group(g, "IfcRamp", name)
    g.ext = {KEY: d}
    scene.groups.append(g)


# ---------------------------------------------------------------------------
# Impostazioni
# ---------------------------------------------------------------------------

def _spin(value, lo, hi):
    s = QDoubleSpinBox()
    s.setDecimals(3)
    s.setRange(lo, hi)
    s.setValue(value)
    return s



def ask_settings(parent, scene=None) -> bool:
    dlg = QDialog(parent)
    dlg.setWindowTitle("Rampa")
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    w = _spin(_Settings.w, 0.2, 10.0)
    height = _spin(_Settings.height, 0.01, 100.0)   # altezza arbitraria
    z = _spin(_Settings.z, -100.0, 1000.0)
    name = QLineEdit(_Settings.name)
    side = QComboBox()
    side.addItem("Lato sinistro della rampa", "left")
    side.addItem("Lato destro della rampa", "right")
    side.addItem("Asse (centro) della rampa", "center")
    side.setCurrentIndex(max(0, side.findData(_Settings.side)))
    kind = QComboBox()
    kind.addItem("Piena (piena fino a terra)", "piena")
    kind.addItem("In c.a. (soletta inclinata)", "ca")
    kind.setCurrentIndex(max(0, kind.findData(_Settings.kind)))
    th = _spin(_Settings.th, 0.05, 1.0)
    ortho = QCheckBox("Orto: rampe sempre lungo X o Y")
    ortho.setChecked(_Settings.ortho)
    lvl = None
    if scene is not None and piani.levels(scene):
        lvl = piani.level_combo(scene, piani.active_id(scene))
        form.addRow("Piano di partenza", lvl)
    form.addRow("Larghezza rampa (m)", w)
    top_cb = top_off = None
    if lvl is not None:                 # arrivo legato a un piano (come i muri)
        top_cb, top_off = piani.add_top_rows(form, scene, _spin(3.0, 0.1, 100.0),
                                             _Settings.tlv, _Settings.toff)
    form.addRow("Altezza arbitraria da raggiungere (m) — se non legata "
                "a un piano", height)
    form.addRow("Quota di partenza: da terra / sopra il piano (m)", z)
    form.addRow("Tipologia", kind)
    form.addRow("Spessore soletta in c.a. (m)", th)
    form.addRow("Nome", name)
    form.addRow("La linea che traccio è", side)
    form.addRow(ortho)
    lay.addLayout(form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return False
    _Settings.w, _Settings.height = w.value(), height.value()
    _Settings.z = z.value()
    _Settings.name = name.text().strip() or "Rampa"
    _Settings.ortho = ortho.isChecked()
    _Settings.side = side.currentData()
    _Settings.kind, _Settings.th = kind.currentData(), th.value()
    _Settings.level = (lvl.currentData() or None) if lvl is not None else None
    if lvl is not None:
        piani.set_active(_Settings.level)
    if top_cb is not None:
        _Settings.tlv = top_cb.currentData() or None
        _Settings.toff = top_off.value()
    else:
        _Settings.tlv = None
    return True


# ---------------------------------------------------------------------------
# Strumento
# ---------------------------------------------------------------------------

class RampaTool(Tool):
    name = "Rampa"
    shortcut = None
    description = "Crea una rampa: clic sui punti delle rampe, Invio conclude."

    def __init__(self) -> None:
        self._entering = False
        self._reset()

    def _reset(self) -> None:
        self.points: list[tuple[float, float]] = []
        self.hover: QVector3D | None = None

    def on_activate(self, viewport) -> None:
        self._vp = viewport
        if self._entering:
            self._reset()
            viewport.flash_status(
                "Rampa: clic sui punti (2-6) · Invio = concludi "
                "· Spazio = capovolgi · Backspace = indietro · Esc = esci",
                7000)
            return
        if not ask_settings(viewport.window(), viewport.scene):
            return
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

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
        self._exit(viewport)
        return True

    def claims_key(self, key: int, modifiers) -> bool:
        if modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        if key in (Qt.Key_Escape, Qt.Key_Space):
            return True
        return bool(self.points) and key in (
            Qt.Key_Return, Qt.Key_Enter, Qt.Key_Backspace)

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if key == Qt.Key_Space:
            _Settings.side = "right" if _Settings.side == "left" else "left"
            viewport.flash_status(
                "Linea tracciata = lato "
                + ("destro" if _Settings.side == "right" else "sinistro")
                + " della rampa", 2500)
            viewport.update()
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter) and self.points:
            self._commit(viewport)
            return True
        if key == Qt.Key_Backspace and self.points:
            self.points.pop()
            viewport.update()
            return True
        return False

    def _constrain(self, x, y):
        if _Settings.ortho and self.points:
            px, py = self.points[-1]
            if abs(x - px) >= abs(y - py):
                return x, py
            return px, y
        return x, y

    def _min_next(self):
        return _Settings.w / 2 + 0.30

    def _place(self):
        vp = getattr(self, "_vp", None)
        if vp is None:
            return _Settings.z, {}
        return piani.place(vp.scene, _Settings.level, _Settings.z)

    def _dict(self, pts):
        z, extra = self._place()
        d = {"pts": [list(p) for p in pts], "w": _Settings.w,
             "height": _Settings.height, "z": z, "side": _Settings.side,
             "kind": _Settings.kind, "th": _Settings.th, **extra}
        vp = getattr(self, "_vp", None)
        if _Settings.tlv and vp is not None:
            apply_top(vp.scene, d, _Settings.tlv, _Settings.toff,
                      _Settings.level)
        return d

    def _preview_dict(self):
        pts = list(self.points)
        if self.hover is not None and len(pts) < MAX_POINTS:
            h = self._constrain(self.hover.x(), self.hover.y())
            if len(pts) < 2 or math.hypot(
                    h[0] - pts[-1][0],
                    h[1] - pts[-1][1]) >= self._min_next():
                pts.append(h)
        if len(pts) < 2:
            return None
        return self._dict(pts)

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover = QVector3D(ctx.world)
        ctx.viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        if getattr(vp.scene, "edit_group", None) is not None:
            vp.flash_status("Chiudi il gruppo che stai modificando", 4000)
            return
        x, y = self._constrain(ctx.world.x(), ctx.world.y())
        if self.points and math.hypot(
                x - self.points[-1][0], y - self.points[-1][1]) < 0.05:
            return
        if len(self.points) >= 2 and math.hypot(
                x - self.points[-1][0],
                y - self.points[-1][1]) < self._min_next():
            vp.flash_status("Rampa troppo corta · Invio per concludere "
                            "qui", 3000)
            return
        self.points.append((x, y))
        if len(self.points) >= MAX_POINTS:
            self._commit(vp)
            return
        vp.update()

    def _commit(self, viewport) -> None:
        if len(self.points) < 2:
            viewport.flash_status("Servono almeno 2 punti", 3000)
            return
        d = self._dict(self.points)
        if not layout(d):
            viewport.flash_status("Rampa troppo corta", 3500)
            return
        if _Settings.tlv and "tlv" not in d:
            viewport.flash_status(
                "Nessun piano di arrivo: uso l'altezza indicata", 4000)
        name = _Settings.name

        def mutate(scene):
            build_ramp(scene, d, name)

        viewport.history.execute(muri.MuriCommand(mutate))
        viewport.notify_scene_changed()
        slope = d["height"] / total_length(d)
        warn = (" · ATTENZIONE: pendenza oltre l'8%"
                if slope > MAX_SLOPE + 1e-9 else "")
        viewport.flash_status(
            f"Rampa creata · pendenza {slope * 100:.1f}% · altezza "
            f"{d['height']:.2f} m{warn}", 5000)
        self._reset()
        viewport.update()

    def rubber_band_lines(self):
        P = QVector3D
        lines = []
        z0 = self._place()[0]
        path = list(self.points)
        if self.hover is not None and path and len(path) < MAX_POINTS:
            path.append(self._constrain(self.hover.x(), self.hover.y()))
        for a, b in zip(path, path[1:]):
            lines.append((P(a[0], a[1], z0), P(b[0], b[1], z0)))
        d = self._preview_dict()
        for it in (layout(d) if d else []):
            c = it["body"]
            for i in range(4):
                a, b = c[i], c[(i + 1) % 4]
                za = it["z0"] if i in (0, 3) else it["z1"]
                zb_ = it["z0"] if (i + 1) % 4 in (0, 3) else it["z1"]
                lines.append((P(a[0], a[1], za), P(b[0], b[1], zb_)))
        return lines

    def draw_overlay(self, viewport, painter) -> None:
        try:
            self._draw_info(viewport, painter)
        except Exception:
            pass

    def _draw_info(self, viewport, painter) -> None:
        from PySide6.QtCore import QPointF
        d = self._preview_dict()
        if d is None or self.hover is None:
            return
        tot = total_length(d)
        if tot < 1e-6:
            return
        slope = d["height"] / tot
        ph = viewport._world_to_pixel(QVector3D(self.hover))
        if ph is None:
            return
        painter.save()
        font = painter.font()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        bad = slope > MAX_SLOPE + 1e-9
        painter.setPen(QPen(QColor(200, 20, 20) if bad else QColor(20, 90, 20)))
        painter.drawText(
            QPointF(ph[0] + 14, ph[1] - 10),
            f"pendenza {slope * 100:.1f}% · lunghezza {tot:.2f} m · "
            f"h {d['height']:.2f} m")
        painter.restore()


# ---------------------------------------------------------------------------
# Registrazione
# ---------------------------------------------------------------------------

def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap, QPolygon
    from PySide6.QtCore import QPoint
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(200, 198, 190))
    p.drawPolygon(QPolygon([QPoint(5, 40), QPoint(43, 40), QPoint(43, 12)]))
    p.end()
    return QIcon(pm)


def _outliner_kind(group):
    d = ramp_data(group)
    if d is None:
        return None
    from core.units import fmt_len
    tot = total_length(d)
    slope = d["height"] / tot if tot > EPS else 0.0
    return {"type": "Rampa",
            "props": [("Tipologia", "In c.a." if d.get("kind") == "ca"
                       else "Piena"),
                      ("Larghezza", fmt_len(d["w"])),
                      ("Altezza", fmt_len(d["height"])),
                      ("Lunghezza", fmt_len(tot)),
                      ("Pendenza", f"{slope * 100:.1f}%")]
            + piani.level_props(d)}


def _register_level_kind() -> None:
    def zset(d, z):
        d["z"] = z

    def hget(d):
        return d["height"]

    def hset(d, h):                      # il piano cambia altezza
        if h > EPS:
            d["height"] = h

    piani.register_kind("rampa", KEY, ramp_data, lambda d: d["z"], zset,
                        rebuild_ramp, hget, hset)


def register(api) -> None:
    _register_level_kind()
    api.add_button("Rampa", "Crea una rampa con pianerottoli",
                   _icon(), api.run_tool(RampaTool()))
    add_kind = getattr(api.app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
