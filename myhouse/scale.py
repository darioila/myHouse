# SPDX-License-Identifier: GPL-3.0-or-later
"""Plugin Scala per IngeTrazo / MyHouse — crea scale con rampe e pianerottoli.

Uso: MyHouse > Scala, scegli larghezza, pedata, alzata e quota di partenza,
poi clic sui punti dell'asse della scala (da 2 a 4):
  - punti 1-2 = prima rampa; 2-3 = seconda rampa; 3-4 = terza rampa
  - la linea tracciata può essere il lato sinistro, il lato destro o l'asse
    della scala (guardando verso l'alto); SPAZIO la capovolge dall'altro lato
  - in ogni punto intermedio c'è un pianerottolo (quadrato largo come la scala)
  - muovendo il mouse vedi i gradini con il numero progressivo
  - Invio conclude (anche con una sola rampa); al 4° punto conclude da sola
  - Backspace toglie l'ultimo punto, Esc o tasto destro esce

Due tipologie: "Piena" (gradini pieni fino a terra) e "In c.a." (soletta
inclinata con la parte di sotto sagomata, spessore a scelta).

Ogni gradino ha sopra una soglia spessa 2 cm che sporge di 1 cm verso
l'esterno. Altezza scala = alzata x numero di gradini (il pianerottolo conta
come un gradino).

Altezza legata a un piano (come per i muri): se nel dialogo scegli un piano di
arrivo ("Piano successivo" o un piano preciso, con eventuale distanza dalla
sua quota), l'alzata viene calcolata in modo che l'ultimo gradino/pianerottolo
arrivi esattamente a quella quota: alzata = altezza / numero di gradini.
Se il piano cambia altezza, la scala si adatta.
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

ORDER = 70
BODY_COLOR = (0.78, 0.76, 0.72)
SILL_COLOR = (0.55, 0.45, 0.35)
LAYER_NAME = "Scale"
KEY = "myhouse_scala"           # parametri in group.ext
SILL_TH = 0.02                  # spessore soglia (m)
SILL_OVER = 0.01                # sporgenza soglia (m)
MAX_POINTS = 4
EPS = 1e-9
FLANK_SINGLE = True            # fianco = una faccia concava; False = triangoli


class _Settings:
    w = 1.00                    # larghezza scala
    tread = 0.30                # pedata
    riser = 0.17                # alzata
    z = 0.0                     # quota di partenza (da terra)
    name = "Scala"
    ortho = True
    side = "left"               # linea tracciata: left | right | center
    kind = "piena"              # piena | ca
    th = 0.15                   # spessore soletta in c.a. (perpendicolare)
    level = None                # id del piano (None = nessuno)
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
    """Elenco di elementi (gradini e pianerottoli) dai dati della scala.

    Ogni elemento: kind ("step"/"landing"), n (numero progressivo), ztop,
    body (angoli del corpo), top (angoli della faccia superiore), centre.
    """
    w, t, riser, z0 = d["w"], d["tread"], d["riser"], d["z"]
    pts = _axis_points([tuple(p) for p in d["pts"]], w, d.get("side", "center"))
    hw = w / 2
    items = []
    k = 0
    m = len(pts)
    u_prev = None
    for i in range(m - 1):
        a, b = pts[i], pts[i + 1]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length < 1e-6:
            continue
        u = (dx / length, dy / length)
        if i > 0 and u_prev is not None:                  # pianerottolo in a
            k += 1
            ztop = z0 + k * riser
            body = _rect(a, u_prev, -hw, hw, hw)
            items.append({"kind": "landing", "n": k, "ztop": ztop,
                          "body": body, "top": body, "centre": a})
        has_landing_before = i > 0
        has_landing_after = i + 1 < m - 1
        s0 = hw if has_landing_before else 0.0
        s1 = length - (hw if has_landing_after else 0.0)
        n = int((s1 - s0) / t + 1e-6)
        if n >= 1:
            te = (s1 - s0) / n if (has_landing_before and has_landing_after) else t
            start = s1 - n * te if has_landing_after else s0
            for j in range(n):
                k += 1
                ztop = z0 + k * riser
                sf = start + j * te
                sb = sf + te
                items.append({
                    "kind": "step", "n": k, "ztop": ztop,
                    "fl": i, "a": a, "u": u, "sf": sf, "sb": sb,
                    "body": _rect(a, u, sf, sb, hw),
                    "top": _rect(a, u, sf - SILL_OVER, sb, hw),
                    "centre": (a[0] + u[0] * (sf + sb) / 2,
                               a[1] + u[1] * (sf + sb) / 2)})
        u_prev = u
    return items


def _area(pts) -> float:
    return 0.5 * sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
                     - pts[(i + 1) % len(pts)][0] * pts[i][1]
                     for i in range(len(pts)))


def _triangulate(pts):
    """Ear clipping per poligoni semplici (anche concavi): triangoli di indici
    orientati antiorari."""
    idx = list(range(len(pts)))
    if _area(pts) < 0:
        idx.reverse()

    def cross(a, b, c):
        return ((pts[b][0] - pts[a][0]) * (pts[c][1] - pts[a][1])
                - (pts[b][1] - pts[a][1]) * (pts[c][0] - pts[a][0]))

    def inside(p, a, b, c):
        return (cross(a, b, p) >= -EPS and cross(b, c, p) >= -EPS
                and cross(c, a, p) >= -EPS)

    tris = []
    guard = 0
    while len(idx) > 3 and guard < 10000:
        guard += 1
        for k in range(len(idx)):
            a, b, c = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            if cross(a, b, c) <= EPS:
                continue
            if any(inside(p, a, b, c) for p in idx if p not in (a, b, c)):
                continue
            tris.append((a, b, c))
            idx.pop(k)
            break
        else:
            break
    if len(idx) == 3:
        tris.append(tuple(idx))
    return tris


def flight_profile(steps, d):
    """Profilo (s, z) antiorario di una rampa: gradini in cima, sotto piano
    (tipo "piena") o sagomato parallelo alla linea dei gradini ("ca")."""
    zb, riser = d["z"], d["riser"]
    sf1, send = steps[0]["sf"], steps[-1]["sb"]
    te = steps[0]["sb"] - steps[0]["sf"]
    top = []
    for it in reversed(steps):
        zt = it["ztop"] - SILL_TH
        top += [(it["sb"], zt), (it["sf"], zt)]
    bottom = [(sf1, zb), (send, zb)]
    if d.get("kind", "piena") == "ca" and te > EPS:
        slope = riser / te
        dv = d.get("th", 0.15) * math.hypot(te, riser) / te
        # spessore misurato dalla linea degli spigoli interni dei gradini
        # (la "gola"), non dalla linea dei nasi: è lo spessore strutturale
        z1 = steps[0]["ztop"] - riser - SILL_TH

        def zs(s_):
            return z1 + (s_ - sf1) * slope - dv

        zs0, zs1 = zs(sf1), zs(send)
        if zs1 <= zb + 1e-6:
            pass                                    # troppo bassa: piena
        elif zs0 < zb:
            bottom = [(sf1, zb), (sf1 + (zb - zs0) / slope, zb), (send, zs1)]
        else:
            bottom = [(sf1, zs0), (send, zs1)]
    poly = []
    for p in bottom + top:
        if not poly or abs(p[0] - poly[-1][0]) + abs(p[1] - poly[-1][1]) > 1e-9:
            poly.append(p)
    if len(poly) > 1 and (abs(poly[0][0] - poly[-1][0])
                          + abs(poly[0][1] - poly[-1][1])) < 1e-9:
        poly.pop()
    return poly


def stair_mesh(d):
    from core.mesh import Mesh
    P = QVector3D
    mesh = Mesh()
    zb = d["z"]
    hw = d["w"] / 2
    ca = d.get("kind", "piena") == "ca"

    def face(q, color):
        f = mesh.add_face(q)
        # nessun colore predefinito: si applicano i materiali di IngeTrazo
        f.attrs["layer"] = LAYER_NAME

    def box(corners, z0, z1, color):
        face([P(x, y, z1) for x, y in corners], color)             # sopra
        face([P(x, y, z0) for x, y in reversed(corners)], color)   # sotto
        for i in range(4):
            j = (i + 1) % 4
            ci, cj = corners[i], corners[j]
            face([P(ci[0], ci[1], z0), P(cj[0], cj[1], z0),
                  P(cj[0], cj[1], z1), P(ci[0], ci[1], z1)], color)

    items = layout(d)
    flights = {}
    for it in items:
        if it["kind"] == "landing":
            z0 = it["ztop"] - d.get("th", 0.15) if ca else zb
            box(it["body"], max(z0, zb), it["ztop"], BODY_COLOR)
        else:
            flights.setdefault(it["fl"], []).append(it)
            box(it["top"], it["ztop"] - SILL_TH, it["ztop"], SILL_COLOR)

    for steps in flights.values():
        a, u = steps[0]["a"], steps[0]["u"]
        v = (-u[1], u[0])

        def p3(sz, lat):
            return P(a[0] + u[0] * sz[0] + v[0] * lat,
                     a[1] + u[1] * sz[0] + v[1] * lat, sz[1])

        poly = flight_profile(steps, d)
        n = len(poly)
        for i in range(n):                  # sotto, alzate, pedate, testa
            p, q = poly[i], poly[(i + 1) % n]
            face([p3(p, hw), p3(q, hw), p3(q, -hw), p3(p, -hw)], BODY_COLOR)
        if FLANK_SINGLE:                        # fianchi: una faccia sola
            face([p3(t_, -hw) for t_ in poly], BODY_COLOR)
            face([p3(t_, hw) for t_ in reversed(poly)], BODY_COLOR)
        else:                                   # fianchi a triangoli
            for ia, ib, ic in _triangulate(poly):
                tri = (poly[ia], poly[ib], poly[ic])
                face([p3(t_, -hw) for t_ in tri], BODY_COLOR)
                face([p3(t_, hw) for t_ in reversed(tri)], BODY_COLOR)
    return mesh


def apply_top(scene, d, tlv, toff, level) -> bool:
    """Altezza legata a un piano: alzata = altezza / numero di gradini
    (il pianerottolo conta come un gradino). Il numero di gradini non dipende
    dall'alzata, quindi basta un solo calcolo. Scrive tlv/toff in d."""
    n = len(layout(d))
    if n < 1:
        return False
    h = piani.height_for(scene, tlv, toff, level, d["z"])
    if h is None or h <= EPS:
        return False
    d["riser"] = h / n
    d["tlv"], d["toff"] = tlv, toff
    return True


def stair_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "pts" in data else None


def rebuild_stair(group, d) -> None:
    """Nuova geometria dai parametri d, stesso gruppo."""
    from core.group import Group
    part = Group(stair_mesh(d), name="Scala")
    part.component = False
    group.children = [part]
    ext = dict(group.ext or {})
    ext[KEY] = dict(d)
    group.ext = ext


def build_stair(scene, d, name) -> None:
    from core.group import Group
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    part = Group(stair_mesh(d), name="Scala")
    part.component = False
    g = Group(name=name)
    g.adopt([part])
    g.component = False
    g.layer = LAYER_NAME
    bim.tag_group(g, "IfcStair", name)
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
    dlg.setWindowTitle("Scala")
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    w = _spin(_Settings.w, 0.2, 10.0)
    tread = _spin(_Settings.tread, 0.05, 2.0)
    riser = _spin(_Settings.riser, 0.02, 1.0)
    z = _spin(_Settings.z, -100.0, 1000.0)
    name = QLineEdit(_Settings.name)
    side = QComboBox()
    side.addItem("Lato sinistro della scala", "left")
    side.addItem("Lato destro della scala", "right")
    side.addItem("Asse (centro) della scala", "center")
    side.setCurrentIndex(max(0, side.findData(_Settings.side)))
    kind = QComboBox()
    kind.addItem("Piena (gradini pieni)", "piena")
    kind.addItem("In c.a. (soletta sagomata sotto)", "ca")
    kind.setCurrentIndex(max(0, kind.findData(_Settings.kind)))
    th = _spin(_Settings.th, 0.05, 1.0)
    height = _spin(3.0, 0.1, 100.0)     # altezza totale: la gestisce piani
    ortho = QCheckBox("Orto: rampe sempre lungo X o Y")
    ortho.setChecked(_Settings.ortho)
    lvl = None
    if scene is not None and piani.levels(scene):
        lvl = piani.level_combo(scene, piani.active_id(scene))
        form.addRow("Piano di partenza", lvl)
    form.addRow("Larghezza scala (m)", w)
    form.addRow("Pedata (m)", tread)
    form.addRow("Alzata (m)", riser)
    top_cb = top_off = None
    if lvl is not None:                 # arrivo legato a un piano (come i muri)
        top_cb, top_off = piani.add_top_rows(form, scene, height,
                                             _Settings.tlv, _Settings.toff)
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
    _Settings.w, _Settings.tread = w.value(), tread.value()
    _Settings.riser, _Settings.z = riser.value(), z.value()
    _Settings.name = name.text().strip() or "Scala"
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

class ScalaTool(Tool):
    name = "Scala"
    shortcut = None
    description = "Crea una scala: clic sui punti delle rampe, Invio conclude."

    def __init__(self) -> None:
        self._entering = False
        self._reset()

    def _reset(self) -> None:
        self.points: list[tuple[float, float]] = []
        self.hover: QVector3D | None = None

    # -- ciclo di vita ------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._vp = viewport
        if self._entering:
            self._reset()
            viewport.flash_status(
                "Scala: clic sui punti delle rampe (2-4) · Invio = concludi "
                "· Spazio = capovolgi · Backspace = indietro · Esc = esci", 7000)
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
                + " della scala", 2500)
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

    # -- punti ----------------------------------------------------------------
    def _constrain(self, x, y):
        if _Settings.ortho and self.points:
            px, py = self.points[-1]
            if abs(x - px) >= abs(y - py):
                return x, py
            return px, y
        return x, y

    def _min_next(self):
        return _Settings.w / 2 + _Settings.tread

    def _place(self):
        vp = getattr(self, "_vp", None)
        if vp is None:
            return _Settings.z, {}
        return piani.place(vp.scene, _Settings.level, _Settings.z)

    def _dict(self, pts):
        z, extra = self._place()
        d = {"pts": [list(p) for p in pts], "w": _Settings.w,
             "tread": _Settings.tread, "riser": _Settings.riser,
             "z": z, "side": _Settings.side,
             "kind": _Settings.kind, "th": _Settings.th, **extra}
        self._apply_top(d)
        return d

    def _apply_top(self, d) -> bool:
        """Se l'altezza è legata a un piano, ricalcola l'alzata in modo che
        la scala arrivi alla quota di quel piano. Ritorna True se applicato."""
        vp = getattr(self, "_vp", None)
        if not _Settings.tlv or vp is None:
            return False
        return apply_top(vp.scene, d, _Settings.tlv, _Settings.toff,
                         _Settings.level)

    def _preview_items(self):
        pts = list(self.points)
        if self.hover is not None and len(pts) < MAX_POINTS:
            h = self._constrain(self.hover.x(), self.hover.y())
            # dopo la 1ª rampa il pianerottolo compare solo se ti allontani
            if len(pts) < 2 or math.hypot(
                    h[0] - pts[-1][0],
                    h[1] - pts[-1][1]) >= self._min_next():
                pts.append(h)
        if len(pts) < 2:
            return []
        return layout(self._dict(pts))

    # -- eventi ---------------------------------------------------------------
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
                            "la scala qui", 3000)
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
        items = layout(d)
        if not items:
            viewport.flash_status("Rampa troppo corta per la pedata", 3500)
            return
        linked = "tlv" in d
        if _Settings.tlv and not linked:
            viewport.flash_status(
                "Nessun piano di arrivo: uso l'alzata indicata", 4000)
        name = _Settings.name

        def mutate(scene):
            build_stair(scene, d, name)

        viewport.history.execute(muri.MuriCommand(mutate))
        viewport.notify_scene_changed()
        warn = ""
        if linked and not 0.10 <= d["riser"] <= 0.22:
            warn = " · ATTENZIONE: alzata fuori norma, cambia pedata o rampe"
        viewport.flash_status(
            f"Scala creata · {len(items)} gradini · alzata "
            f"{d['riser'] * 100:.1f} cm · altezza "
            f"{len(items) * d['riser']:.2f} m{warn}", 5000)
        self._reset()
        viewport.update()

    # -- disegno -------------------------------------------------------------
    def rubber_band_lines(self):
        P = QVector3D
        lines = []
        z0 = self._place()[0]
        path = list(self.points)
        if self.hover is not None and path and len(path) < MAX_POINTS:
            path.append(self._constrain(self.hover.x(), self.hover.y()))
        for a, b in zip(path, path[1:]):
            lines.append((P(a[0], a[1], z0), P(b[0], b[1], z0)))
        for it in self._preview_items():
            z = it["ztop"]
            c = it["top"]
            for i in range(4):
                a, b = c[i], c[(i + 1) % 4]
                lines.append((P(a[0], a[1], z), P(b[0], b[1], z)))
        return lines

    def draw_overlay(self, viewport, painter) -> None:
        try:
            self._draw_numbers(viewport, painter)
        except Exception:
            pass

    def _draw_numbers(self, viewport, painter) -> None:
        from PySide6.QtCore import QPointF
        items = self._preview_items()
        if not items:
            return
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        font = painter.font()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(QColor(20, 20, 20)))
        for it in items:
            c = it["centre"]
            pc = viewport._world_to_pixel(QVector3D(c[0], c[1], it["ztop"]))
            if pc is None:
                continue
            painter.drawText(QPointF(pc[0] - 6, pc[1] + 4), str(it["n"]))
        if self.hover is not None:
            ph = viewport._world_to_pixel(QVector3D(self.hover))
            if ph is not None:
                n = len(items)
                h = items[-1]["ztop"] - self._place()[0]
                painter.setPen(QPen(QColor(200, 20, 20)))
                painter.drawText(
                    QPointF(ph[0] + 14, ph[1] - 10),
                    f"{n} gradini · alzata {h / n * 100:.1f} cm · "
                    f"h {h:.2f} m")
        painter.restore()


# ---------------------------------------------------------------------------
# Registrazione
# ---------------------------------------------------------------------------

def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(200, 198, 190))
    for i in range(4):
        p.drawRect(6 + i * 9, 34 - i * 9, 9 + (3 - i) * 9, 9 + i * 9)
    p.end()
    return QIcon(pm)


def _outliner_kind(group):
    d = stair_data(group)
    if d is None:
        return None
    from core.units import fmt_len
    n = len(layout(d))
    return {"type": "Scala",
            "props": [("Tipologia", "In c.a." if d.get("kind") == "ca"
                       else "Piena"),
                      ("Larghezza", fmt_len(d["w"])),
                      ("Gradini", str(n)),
                      ("Alzata", fmt_len(d["riser"])),
                      ("Pedata", fmt_len(d["tread"])),
                      ("Altezza", fmt_len(n * d["riser"]))]
            + piani.level_props(d)}


def _register_level_kind() -> None:
    def zset(d, z):
        d["z"] = z

    def hget(d):
        return len(layout(d)) * d["riser"]

    def hset(d, h):                      # il piano cambia altezza: nuova alzata
        n = len(layout(d))
        if n >= 1 and h > EPS:
            d["riser"] = h / n

    piani.register_kind("scala", KEY, stair_data, lambda d: d["z"], zset,
                        rebuild_stair, hget, hset)


def register(api) -> None:
    _register_level_kind()
    api.add_button("Scala", "Crea una scala con rampe e pianerottoli",
                   _icon(), api.run_tool(ScalaTool()))
    add_kind = getattr(api.app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
