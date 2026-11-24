# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr
from ._imperial import FT, IN, LengthSpin, ask_length, dflt
from ._scroll import scroll_form

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPen, QVector3D
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QInputDialog,
    QLineEdit, QVBoxLayout,
)

from core import bim
from . import _ifc
from tools.base import Tool, ToolContext

from . import _codici, muri, piani, _tipi

ORDER = 60
BEAM_COLOR = (0.70, 0.55, 0.38)
LAYER_NAME = "Travi"
KEY = "myhouse_trave"
SNAP = 0.40


class _Settings:
    shape = "rect"
    w = dflt(6 * IN, 0.20)
    tf = 0.02
    tw = 0.012
    h = dflt(12 * IN, 0.20)
    z0 = dflt(8 * FT, 3.00)
    name = tr("Trave")
    level = None
    use_z = False
    ref = "top"
    align = "center"
    sagoma = "NESSUNA"
    sag_lung = 0.25
    sag_taglio = 50.0
    tipo_id = None
    tipo_nome = None


SAGOME = (("NESSUNA", "Nessuna"), ("CURVA", "Curva"), ("DRITTA", "Dritta"))


def _sagoma_stazioni(d):
    tipo = d.get("sagoma", "NESSUNA")
    if d.get("shape", "rect") != "rect" or tipo not in ("CURVA", "DRITTA"):
        return None
    ax, ay = d["a"]
    bx, by = d["b"]
    L = math.hypot(bx - ax, by - ay)
    h = d["h"]
    q = max(0.0, min(90.0, float(d.get("sag_taglio", 50.0)))) / 100.0
    l = min(max(0.01, float(d.get("sag_lung", 0.25))), L / 2 - 1e-4)
    if L < 0.02 or q <= 0 or l <= 0:
        return None
    vq = h * q
    n = 1 if tipo == "DRITTA" else 10

    def vb(x):
        if x >= l:
            return 0.0
        if tipo == "DRITTA":
            return vq * (1.0 - x / l)
        r = 1.0 - x / l
        return vq * (1.0 - math.sqrt(max(0.0, 1.0 - r * r)))

    est = [i * l / n for i in range(n + 1)]
    st = [(x / L, vb(x)) for x in est]
    st += [(1.0 - x / L, vb(x)) for x in reversed(est)]
    return st


def beam_corners(d):
    ax, ay = d["a"]
    bx, by = d["b"]
    L = math.hypot(bx - ax, by - ay) or 1.0
    nx, ny = -(by - ay) / L * d["w"] / 2, (bx - ax) / L * d["w"] / 2
    P = QVector3D
    zab, zbb = d["za"], d["zb"]
    h = d["h"]
    return {
        "A1b": P(ax + nx, ay + ny, zab), "A2b": P(ax - nx, ay - ny, zab),
        "B1b": P(bx + nx, by + ny, zbb), "B2b": P(bx - nx, by - ny, zbb),
        "A1t": P(ax + nx, ay + ny, zab + h), "A2t": P(ax - nx, ay - ny, zab + h),
        "B1t": P(bx + nx, by + ny, zbb + h), "B2t": P(bx - nx, by - ny, zbb + h),
    }


def section_profile(d):
    shape = d.get("shape", "rect")
    w, h = d["w"], d["h"]
    if shape == "round":
        r = w / 2
        n = 32
        pts = [(r * math.cos(2 * math.pi * i / n),
                r + r * math.sin(2 * math.pi * i / n)) for i in range(n)]
        return pts, [pts]
    if shape == "ibeam":
        tf = max(0.001, min(d.get("tf", 0.02), (h - 0.005) / 2))
        tw = max(0.001, min(d.get("tw", 0.012), w - 0.005))
        a, b = w / 2, tw / 2
        pts = [(a, h), (-a, h), (-a, h - tf), (-b, h - tf), (-b, tf),
               (-a, tf), (-a, 0), (a, 0), (a, tf), (b, tf), (b, h - tf),
               (a, h - tf)]
        pieces = [[(a, h), (-a, h), (-a, h - tf), (a, h - tf)],
                  [(b, h - tf), (-b, h - tf), (-b, tf), (b, tf)],
                  [(a, tf), (-a, tf), (-a, 0), (a, 0)]]
        return pts, pieces
    pts = [(w / 2, h), (-w / 2, h), (-w / 2, 0), (w / 2, 0)]
    return pts, [pts]


def beam_mesh(d):
    from core.mesh import Mesh
    ax, ay = d["a"]
    bx, by = d["b"]
    L = math.hypot(bx - ax, by - ay) or 1.0
    nx, ny = -(by - ay) / L, (bx - ax) / L
    P = QVector3D
    pts, pieces = section_profile(d)

    def A(p):
        return P(ax + nx * p[0], ay + ny * p[0], d["za"] + p[1])

    def B(p):
        return P(bx + nx * p[0], by + ny * p[0], d["zb"] + p[1])

    mesh = Mesh()
    stz = _sagoma_stazioni(d)
    if stz is not None:
        return _beam_mesh_sagomata(d, stz, mesh, nx, ny)

    def face(vs):
        f = mesh.add_face(vs)
        f.attrs["color"] = BEAM_COLOR
        f.attrs["mat"] = tr("materiale trave")
        f.attrs["layer"] = LAYER_NAME

    n = len(pts)
    for i in range(n):
        p0, p1 = pts[i], pts[(i + 1) % n]
        face([A(p1), B(p1), B(p0), A(p0)])
    for piece in pieces:
        face([B(p) for p in piece])
        face([A(p) for p in reversed(piece)])
    return mesh


def _beam_mesh_sagomata(d, stz, mesh, nx, ny):
    ax, ay = d["a"]
    bx, by = d["b"]
    P = QVector3D
    w, h = d["w"], d["h"]

    def pt(t, u, v):
        return P(ax + (bx - ax) * t + nx * u, ay + (by - ay) * t + ny * u,
                 d["za"] + (d["zb"] - d["za"]) * t + v)

    def prof(vb):
        return [(w / 2, h), (-w / 2, h), (-w / 2, vb), (w / 2, vb)]

    def face(vs):
        f = mesh.add_face(vs)
        f.attrs["color"] = BEAM_COLOR
        f.attrs["mat"] = tr("materiale trave")
        f.attrs["layer"] = LAYER_NAME

    t0, v0 = stz[0]
    t1, v1 = stz[-1]
    face([pt(t1, -w / 2, h), pt(t1, w / 2, h), pt(t0, w / 2, h), pt(t0, -w / 2, h)])
    bot_m = [pt(t, -w / 2, v) for t, v in stz]
    bot_p = [pt(t, w / 2, v) for t, v in stz]
    face(bot_m + [pt(t1, -w / 2, h), pt(t0, -w / 2, h)])
    face([pt(t0, w / 2, h), pt(t1, w / 2, h)] + bot_p[::-1])
    for k in range(len(stz) - 1):
        (ta, va), (tb, vb) = stz[k], stz[k + 1]
        face([pt(tb, w / 2, vb), pt(tb, -w / 2, vb), pt(ta, -w / 2, va), pt(ta, w / 2, va)])
    t0, v0 = stz[0]
    t1, v1 = stz[-1]
    face([pt(t1, *p) for p in prof(v1)])
    face([pt(t0, *p) for p in reversed(prof(v0))])
    return mesh


def beam_edges(d):
    c = beam_corners(d)
    pairs = [("A1b", "B1b"), ("A2b", "B2b"), ("A1t", "B1t"), ("A2t", "B2t"),
             ("A1b", "A2b"), ("B1b", "B2b"), ("A1t", "A2t"), ("B1t", "B2t"),
             ("A1b", "A1t"), ("A2b", "A2t"), ("B1b", "B1t"), ("B2b", "B2t")]
    return [(c[a], c[b]) for a, b in pairs]


def beam_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "a" in data else None


def build_beam(scene, d, name) -> None:
    from core.group import Group
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    part = Group(beam_mesh(d), name=tr("Trave"))
    part.component = False
    g = Group(name=name)
    g.adopt([part])
    g.component = False
    g.layer = LAYER_NAME
    _ifc.tag(g, "IfcBeam", name)
    g.ext = {KEY: d}
    scene.groups.append(g)


def rebuild_beam(group, p: dict) -> None:
    d = dict(beam_data(group))
    d.update(p)
    from core.group import Group
    part = Group(beam_mesh(d), name=tr("Trave"))
    part.component = False
    group.children = [part]
    _ifc.tag(group, "IfcBeam")
    group.name = d.get("name", group.name)
    ext = dict(group.ext or {})
    ext[KEY] = d
    group.ext = ext


def _pillar_centres(scene):
    try:
        from . import pilastri
    except ImportError:
        return []
    out = []
    for g in scene.groups:
        d = pilastri.pillar_data(g)
        if d is not None:
            out.append((d["c"][0], d["c"][1]))
    return out


def snap_point(scene, x, y):
    best, hit = SNAP, None
    for cx, cy in _pillar_centres(scene):
        dist = math.hypot(cx - x, cy - y)
        if dist < best:
            best, hit = dist, (cx, cy)
    return hit if hit else (x, y)


def _shift_axis(sx, sy, x, y):
    if _Settings.align == "center":
        return sx, sy, x, y
    L = math.hypot(x - sx, y - sy)
    if L < 1e-9:
        return sx, sy, x, y
    nx, ny = -(y - sy) / L, (x - sx) / L
    k = _Settings.w / 2 * (-1 if _Settings.align == "left" else 1)
    return sx + nx * k, sy + ny * k, x + nx * k, y + ny * k


def _z_from_points(z_start: float, z_end: float):
    off = _Settings.h if _Settings.ref == "top" else 0.0
    return z_start - off, z_end - off


def _spin(value, lo, hi):
    s = LengthSpin()
    s.setDecimals(3)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


def _sezioni(p, ox=0, oy=0):
    r, t, dim = muri._r, muri._t, muri._dim
    p.save()
    p.translate(ox, oy)
    r(p, 22, 30, 72, 90, muri._C_CORPO)
    dim(p, 22, 22, 72, 22, "b", 1)
    dim(p, 14, 30, 14, 90, "h", -1)
    t(p, 18, 118, tr("rettangolare"), size=8)
    p.setPen(QPen(muri._C_LINEA, 1.2))
    p.setBrush(muri._C_CORPO)
    p.drawEllipse(QPointF(125, 60), 25, 25)
    dim(p, 100, 60, 150, 60, "d", 1)
    t(p, 108, 118, tr("circolare"), size=8)
    r(p, 175, 30, 225, 38, muri._C_CORPO)
    r(p, 175, 82, 225, 90, muri._C_CORPO)
    r(p, 196, 38, 204, 82, muri._C_CORPO)
    dim(p, 175, 22, 225, 22, "b", 1)
    dim(p, 167, 30, 167, 90, "h", -1)
    dim(p, 233, 30, 233, 38, "tf", 1)
    dim(p, 196, 100, 204, 100, "tw", 1)
    t(p, 190, 118, tr("a I"), size=8)
    p.restore()


def _disegno_trave(p):
    r, t, dim, ext = muri._r, muri._t, muri._dim, muri._ext
    _sezioni(p, 0, 0)
    p.setPen(QPen(muri._C_LINEA, 1.5))
    p.drawLine(QPointF(268, 150), QPointF(380, 150))
    muri._hatch(p, 268, 150, 380, 156)
    r(p, 278, 60, 378, 84, muri._C_CORPO)
    dim(p, 270, 84, 270, 150, "z", -1)
    dim(p, 388, 60, 388, 84, "h")
    t(p, 290, 54, tr("faccia superiore"), size=8)
    t(p, 290, 97, tr("faccia inferiore"), size=8)
    t(p, 286, 166, tr("Prospetto"), size=9)
    r(p, 426, 80, 478, 100, muri._C_CORPO)
    pen = QPen(muri._C_LINEA, 1.2)
    pen.setStyle(Qt.DashDotLine)
    p.setPen(pen)
    p.drawLine(QPointF(420, 90), QPointF(480, 90))
    dim(p, 416, 80, 416, 100, "b", -1)
    t(p, 430, 74, tr("sinistro"), size=8)
    t(p, 430, 113, tr("destro"), size=8)
    t(p, 436, 166, tr("Pianta"), size=9)


def ask_section(parent, cur: dict, title: str, with_z: bool,
                scene=None, with_pts: bool = False, groups=None):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(muri._Schema(_disegno_trave))
    shape = QComboBox()
    shape.addItem(tr("Rettangolare"), "rect")
    shape.addItem(tr("Circolare"), "round")
    shape.addItem(tr("A I"), "ibeam")
    shape.setCurrentIndex({"rect": 0, "round": 1, "ibeam": 2}.get(
        cur.get("shape", "rect"), 0))
    w = _spin(cur["w"], 0.02, 5.0)
    h = _spin(cur["h"], 0.02, 5.0)
    tf = _spin(cur.get("tf", 0.02), 0.002, 2.0)
    tw = _spin(cur.get("tw", 0.012), 0.002, 2.0)
    z0 = _spin(cur.get("z0", 0.0), -100.0, 1000.0)
    name = QLineEdit(cur["name"])
    form.addRow(tr("Forma della sezione"), shape)
    form.addRow(tr("Larghezza sezione (b) (m)"), w)
    form.addRow(tr("Altezza sezione (h) (m)"), h)
    form.addRow(tr("Spessore ali (tf) (m)"), tf)
    form.addRow(tr("Spessore anima (tw) (m)"), tw)
    sag = QComboBox()
    for kk, nome in SAGOME:
        sag.addItem(tr(nome), kk)
    sag.setCurrentIndex(max(0, sag.findData(cur.get("sagoma", "NESSUNA"))))
    sag_l = _spin(cur.get("sag_lung", 0.25), 0.01, 100.0)
    sag_q = _spin(cur.get("sag_taglio", 50.0), 0.0, 90.0)
    form.addRow(tr("Sagoma travi"), sag)
    form.addRow(tr("Sagoma travi: lunghezza (l) (m)"), sag_l)
    form.addRow(tr("Sagoma travi: taglio (q) (%)"), sag_q)

    def _vis(widget, on):
        widget.setVisible(on)
        lbl = form.labelForField(widget)
        if lbl is not None:
            lbl.setVisible(on)

    def _shape_changed(*_):
        k = shape.currentData()
        _vis(h, k != "round")
        _vis(tf, k == "ibeam")
        _vis(tw, k == "ibeam")
        _vis(sag, k == "rect")
        _vis(sag_l, k == "rect" and sag.currentData() != "NESSUNA")
        _vis(sag_q, k == "rect" and sag.currentData() != "NESSUNA")
        lbl = form.labelForField(w)
        if lbl is not None:
            lbl.setText(tr("Diametro (d) (m)") if k == "round" else
                        tr("Larghezza ali (b) (m)") if k == "ibeam" else
                        tr("Larghezza sezione (b) (m)"))
        lbl = form.labelForField(h)
        if lbl is not None:
            lbl.setText(tr("Altezza totale (h) (m)") if k == "ibeam"
                        else tr("Altezza sezione (h) (m)"))

    shape.currentIndexChanged.connect(_shape_changed)
    sag.currentIndexChanged.connect(_shape_changed)
    _shape_changed()
    lvl = None
    if with_z:
        if scene is not None and piani.levels(scene):
            lvl = piani.level_combo(scene, cur.get("lv"))
            form.addRow(tr("Piano"), lvl)
        form.addRow(tr("Altezza da terra / dal piano - faccia inferiore (z) (m)"), z0)
    chk = ref = al = None
    if with_pts:
        chk = QCheckBox(tr("Usa la quota dei punti cliccati (trave inclinata)"))
        chk.setChecked(bool(cur.get("use_z", False)))
        form.addRow(chk)
        ref = QComboBox()
        ref.addItem(tr("Superiore"), "top")
        ref.addItem(tr("Inferiore"), "bottom")
        ref.setCurrentIndex(0 if cur.get("ref", "top") == "top" else 1)
        form.addRow(tr("I punti cliccati stanno sulla faccia"), ref)
        al = QComboBox()
        al.addItem(tr("Centro"), "center")
        al.addItem(tr("Spigolo sinistro"), "left")
        al.addItem(tr("Spigolo destro"), "right")
        al.setCurrentIndex({"center": 0, "left": 1, "right": 2}.get(
            cur.get("align", "center"), 0))
        form.addRow(tr("Traccia la trave dal"), al)
    form.addRow(tr("Nome"), name)

    def _get_tipo():
        k = shape.currentData()
        return {"shape": k, "w": w.value(), "h": h.value(), "tf": tf.value(),
                "tw": tw.value(),
                "sagoma": sag.currentData() if k == "rect" else "NESSUNA",
                "sag_lung": sag_l.value(), "sag_taglio": sag_q.value()}

    def _set_tipo(t):
        if "shape" in t:
            shape.setCurrentIndex(max(0, shape.findData(t["shape"])))
        for k, wd in (("w", w), ("h", h), ("tf", tf), ("tw", tw),
                      ("sag_lung", sag_l), ("sag_taglio", sag_q)):
            if k in t:
                wd.setValue(t[k])
        if "sagoma" in t:
            sag.setCurrentIndex(max(0, sag.findData(t["sagoma"])))
        _shape_changed()

    tbar = _tipi.TypeBar(dlg, form, "trave", cur, _get_tipo, _set_tipo,
                         scene, creating=with_z)
    cf = (_codici.CodeField(form, groups, "trave", scene, at=2)
          if groups else None)
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return None
    if cf is not None:
        cf.apply(dlg)
    k = shape.currentData()
    wv, hv = w.value(), h.value()
    if k == "round":
        hv = wv
    tfv = min(tf.value(), max(0.002, (hv - 0.005) / 2))
    twv = min(tw.value(), max(0.002, wv - 0.005))
    return tbar.result({"shape": k, "tf": tfv, "tw": twv,
            "sagoma": sag.currentData() if k == "rect" else "NESSUNA",
            "sag_lung": sag_l.value(), "sag_taglio": sag_q.value(),
            "w": wv, "h": hv, "z0": z0.value(),
            "name": name.text().strip() or tr("Trave"),
            "lv": (lvl.currentData() or None) if lvl is not None else None,
            "use_z": chk.isChecked() if chk is not None else False,
            "ref": ref.currentData() if ref is not None else "top",
            "align": al.currentData() if al is not None else "center"})


class TraveTool(Tool):
    name = tr("Trave")
    shortcut = None
    description = tr("Crea una trave (clic iniziale e finale); doppio clic per inclinarla.")

    def __init__(self) -> None:
        self._entering = False
        self._reset()

    def _reset(self) -> None:
        self.mode = "create"
        self.start = None
        self.hover: QVector3D | None = None
        self.group = None
        self.d: dict | None = None

    def on_activate(self, viewport) -> None:
        self._vp = viewport
        if self._entering:
            if self.mode != "edit":
                self._reset()
                viewport.flash_status(
                    tr("Trave: clic sul punto iniziale e poi sul finale · "
                    "Esc = esci"), 6000)
            return
        p = ask_section(viewport.window(),
                        {"shape": _Settings.shape, "tf": _Settings.tf,
                         "tw": _Settings.tw,
                         "w": _Settings.w, "h": _Settings.h,
                         "z0": _Settings.z0, "name": _Settings.name,
                         "lv": piani.active_id(viewport.scene),
                         "use_z": _Settings.use_z, "ref": _Settings.ref,
                         "align": _Settings.align,
                         "sagoma": _Settings.sagoma,
                         "sag_lung": _Settings.sag_lung,
                         "sag_taglio": _Settings.sag_taglio,
                         "tipo_id": _Settings.tipo_id,
                         "tipo_nome": _Settings.tipo_nome},
                        tr("Trave"), True, viewport.scene, with_pts=True)
        if p is None:
            return
        _Settings.w, _Settings.h = p["w"], p["h"]
        _Settings.shape, _Settings.tf, _Settings.tw = p["shape"], p["tf"], p["tw"]
        _Settings.z0, _Settings.name = p["z0"], p["name"]
        _Settings.level = p.get("lv")
        _Settings.use_z, _Settings.ref = p["use_z"], p["ref"]
        _Settings.align = p["align"]
        _Settings.sagoma = p["sagoma"]
        _Settings.sag_lung, _Settings.sag_taglio = p["sag_lung"], p["sag_taglio"]
        _Settings.tipo_id = p.get("tipo_id")
        _Settings.tipo_nome = p.get("tipo_nome")
        piani.set_active(_Settings.level)
        self._activate(viewport)

    def _activate(self, viewport) -> None:
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def edit(self, viewport, group) -> None:
        d = beam_data(group)
        if d is None:
            return
        if getattr(viewport.scene, "edit_group", None) is not None:
            viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        self._reset()
        self.mode = "edit"
        self._activate(viewport)
        self.mode = "edit"
        self.group = group
        self.d = dict(d)
        viewport.flash_status(
            tr("Clic su un quadratino rosso (lato corto) per cambiarne l'altezza "
            "da terra · Invio = applica · Esc = annulla"), 8000)
        viewport.update()

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
        return key == Qt.Key_Escape

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if self.mode == "edit" and key in (Qt.Key_Return, Qt.Key_Enter):
            self._apply(viewport)
            return True
        if self.mode == "create" and key == Qt.Key_Backspace and self.start:
            self.start = None
            viewport.update()
            return True
        return False

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover = QVector3D(ctx.world)
        ctx.viewport.update()

    def _ends(self):
        d = self.d
        return [(d["a"][0], d["a"][1], d["za"] + d["h"] / 2, "za"),
                (d["b"][0], d["b"][1], d["zb"] + d["h"] / 2, "zb")]

    def _pick_end(self, vp, world, radius=22.0):
        px = vp._world_to_pixel(QVector3D(world))
        best, bk = None, None
        for x, y, z, k in self._ends():
            pc = vp._world_to_pixel(QVector3D(x, y, z))
            if px is None or pc is None:
                dist = math.hypot(x - world.x(), y - world.y()) * 100
            else:
                dist = math.hypot(pc[0] - px[0], pc[1] - px[1])
            if dist < radius and (best is None or dist < best):
                best, bk = dist, k
        return bk

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        if self.mode == "edit":
            k = self._pick_end(vp, ctx.world)
            if k is None:
                g = self.group
                self._exit(vp)
                edit_section(vp, [g])
                return
            val, ok = ask_length(
                vp.window(), tr("Quota del lato"),
                tr("Altezza da terra di questo lato (m)"),
                self.d[k], -100.0, 1000.0)
            if ok:
                self.d[k] = val
            vp.update()
            return
        if getattr(vp.scene, "edit_group", None) is not None:
            vp.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        x, y = snap_point(vp.scene, ctx.world.x(), ctx.world.y())
        if self.start is None:
            self.start = (x, y, ctx.world.z())
            vp.update()
            return
        sx, sy, sz = self.start
        if math.hypot(x - sx, y - sy) < 1e-3:
            vp.flash_status(tr("I due punti coincidono"), 3000)
            return
        if _Settings.use_z:
            za, zb = _z_from_points(sz, ctx.world.z())
            extra = {"lv": None}
        else:
            za, extra = piani.place(vp.scene, _Settings.level, _Settings.z0)
            zb = za
        ax, ay, bx, by = _shift_axis(sx, sy, x, y)
        d = {"a": [ax, ay], "b": [bx, by], "za": za, "zb": zb,
             "w": _Settings.w, "h": _Settings.h, "name": _Settings.name,
             "shape": _Settings.shape, "tf": _Settings.tf, "tw": _Settings.tw,
             "sagoma": _Settings.sagoma, "sag_lung": _Settings.sag_lung,
             "sag_taglio": _Settings.sag_taglio,
             "tipo_id": _Settings.tipo_id, "tipo_nome": _Settings.tipo_nome}
        d.update(extra)
        name = _Settings.name

        def mutate(scene):
            build_beam(scene, d, name)

        vp.history.execute(muri.MuriCommand(mutate))
        vp.notify_scene_changed()
        if _Settings.use_z:
            vp.flash_status(
                tr("Trave creata (inclinata sui punti cliccati: {0:.2f} → {1:.2f} m)")
                .format(za, zb), 4500)
        else:
            vp.flash_status(tr("Trave creata · doppio clic per inclinarla"), 3500)
        self.start = None
        vp.update()

    def _apply(self, viewport) -> None:
        group, d = self.group, self.d

        def mutate(scene):
            q = dict(d)
            lv = piani.get(scene, q.get("lv"))
            if lv:
                q["off"] = min(q["za"], q["zb"]) - lv["z"]
            rebuild_beam(group, q)

        viewport.history.execute(muri.MuriCommand(mutate))
        viewport.notify_scene_changed()
        viewport.flash_status(tr("Trave modificata"), 3000)
        self._exit(viewport)

    def rubber_band_lines(self):
        if self.mode == "edit" and self.d is not None:
            return beam_edges(self.d)
        if self.start is None or self.hover is None:
            return []
        x, y = snap_point_cache(self.hover)
        sx, sy, sz = self.start
        vp = getattr(self, "_vp", None)
        if _Settings.use_z:
            za, zb = _z_from_points(sz, self.hover.z())
        else:
            za = (piani.place(vp.scene, _Settings.level, _Settings.z0)[0]
                  if vp is not None else _Settings.z0)
            zb = za
        if math.hypot(x - sx, y - sy) < 1e-3:
            return []
        ax, ay, bx, by = _shift_axis(sx, sy, x, y)
        d = {"a": [ax, ay], "b": [bx, by], "za": za, "zb": zb,
             "w": _Settings.w, "h": _Settings.h}
        return beam_edges(d)

    def draw_overlay(self, viewport, painter) -> None:
        try:
            if self.mode == "edit" and self.d is not None:
                self._draw_ends(viewport, painter)
        except Exception:
            pass

    def _draw_ends(self, viewport, painter) -> None:
        from PySide6.QtCore import QPointF, QRectF
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        hot = None
        if self.hover is not None:
            hot = self._pick_end(viewport, self.hover)
        for x, y, z, k in self._ends():
            pc = viewport._world_to_pixel(QVector3D(x, y, z))
            if pc is None:
                continue
            r = 9 if k == hot else 7
            painter.setPen(QPen(QColor(255, 255, 255), 1.5))
            painter.setBrush(QColor(255, 210, 0) if k == hot
                             else QColor(220, 30, 30))
            painter.drawRect(QRectF(pc[0] - r, pc[1] - r, 2 * r, 2 * r))
            painter.setPen(QPen(QColor(20, 20, 20)))
            painter.drawText(QPointF(pc[0] + r + 4, pc[1] - r),
                             f"{self.d[k]:.2f} m")
        painter.restore()


_snap_scene = {"scene": None}


def snap_point_cache(p: QVector3D):
    sc = _snap_scene["scene"]
    return snap_point(sc, p.x(), p.y()) if sc is not None else (p.x(), p.y())


def _selected_beams(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and beam_data(g) is not None and g not in out:
            out.append(g)
    return out


def edit_section(viewport, groups=None) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    groups = groups or _selected_beams(scene)
    if not groups:
        viewport.flash_status(tr("Seleziona una trave"), 3000)
        return
    d0 = beam_data(groups[0])
    p = ask_section(viewport.window(), d0, tr("Modifica sezione trave"), False,
                    scene, groups=groups)
    if p is None:
        return
    st = _tipi.resolve_edit(viewport.window(), scene, "trave", p)
    if st == "cancel":
        return
    p.pop("z0")
    p.pop("lv", None)

    def mutate(sc):
        for g in groups:
            q = dict(p)
            if len(groups) > 1:
                q.pop("name")
            rebuild_beam(g, q)
        if st == "type":
            _tipi.update_instances(sc, "trave", p["tipo_id"], rebuild_beam)

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("{0} travi aggiornate").format(len(groups)), 3000)


def _hook_double_click(vp, tool) -> None:
    if getattr(vp, "_myhouse_travi_dbl", False):
        return
    original = vp.begin_group_edit

    def begin_group_edit(group, *args, **kwargs):
        g = getattr(group, "owner", None) or group
        if beam_data(g) is None:
            return original(group, *args, **kwargs)
        from PySide6.QtCore import QTimer
        _snap_scene["scene"] = vp.scene
        QTimer.singleShot(0, lambda: edit_section(vp, [g]))

    vp.begin_group_edit = begin_group_edit
    vp._myhouse_travi_dbl = True


def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(200, 198, 190))
    p.drawRect(6, 14, 8, 26)
    p.drawRect(34, 14, 8, 26)
    p.setBrush(QColor(176, 140, 96))
    p.drawRect(4, 8, 40, 8)
    p.end()
    return QIcon(pm)


def _outliner_kind(group):
    d = beam_data(group)
    if d is None:
        return None
    from ._imperial import fmt_len
    L = math.hypot(d["b"][0] - d["a"][0], d["b"][1] - d["a"][1])
    return {"type": tr("Trave"),
            "props": [(tr("Sezione"),
                       f"Ø {fmt_len(d['w'])}" if d.get("shape") == "round"
                       else f"I {fmt_len(d['w'])} × {fmt_len(d['h'])}"
                       if d.get("shape") == "ibeam"
                       else f"{fmt_len(d['w'])} × {fmt_len(d['h'])}"),
                      (tr("Lunghezza"), fmt_len(L)),
                      (tr("Quota lato A"), fmt_len(d["za"])),
                      (tr("Quota lato B"), fmt_len(d["zb"]))]
            + piani.level_props(d)}


def _register_level_kind() -> None:
    def zget(d):
        return min(d["za"], d["zb"])

    def zset(d, z):
        delta = z - zget(d)
        d["za"] += delta
        d["zb"] += delta

    piani.register_kind("trave", KEY, beam_data, zget, zset, rebuild_beam)


def register(api) -> None:
    _register_level_kind()
    tool = TraveTool()
    base_activate = tool.on_activate

    def activate(viewport):
        _snap_scene["scene"] = viewport.scene
        base_activate(viewport)

    tool.on_activate = activate
    api.add_button(tr("Trave"), tr("Crea una trave (orizzontale o inclinata)"),
                   _icon(), api.run_tool(tool))
    app = api.app
    _hook_double_click(api.window.viewport, tool)
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        from PySide6.QtCore import QTimer

        def context(menu, selection) -> None:
            beams = _selected_beams(app.viewport.scene)
            if not beams:
                return
            menu.addSeparator()
            menu.addAction(
                tr("Modifica quote trave…"),
                lambda: QTimer.singleShot(
                    0, lambda: tool.edit(app.viewport, beams[0])))
            menu.addAction(
                tr("Modifica sezione trave…"),
                lambda: QTimer.singleShot(
                    0, lambda: edit_section(app.viewport)))

        add_ctx(context)
    add_kind = getattr(app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
