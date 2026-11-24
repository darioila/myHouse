# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr
from ._imperial import LengthSpin
from ._scroll import scroll_form

import copy
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPen, QVector3D
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QLineEdit, QSpinBox, QVBoxLayout,
)

from core import bim
from . import _ifc
from tools.base import Tool, ToolContext

from . import _codici, finestre, muri, piani

ORDER = 72
LAYER_NAME = "Scale"
KEY = "myhouse_chiocciola"
EPS = 1e-9
POLE_SIDES = 24
PAINT_KEYS = ("col_step", "tex_step", "col_pole", "tex_pole",
              "col_rail", "tex_rail")
ZONES = (("step", tr("gradini")), ("pole", tr("palo")),
         ("rail", tr("corrimano e correnti")))
DEFAULT_MATS = {
    "step": ((0.72, 0.52, 0.32), tr("pedate chiocciola")),
    "pole": ((0.35, 0.36, 0.40), tr("palo chiocciola")),
    "rail": ((0.15, 0.15, 0.17), tr("balaustra chiocciola")),
}
GEOM_KEYS = ("tipo", "a", "b", "cdeg", "n", "th", "pole", "cw", "rail",
             "roff", "rh", "rd", "cd", "nr")

DEFAULTS = {
    "tipo": "A",
    "a": 0.70,
    "b": 0.20,
    "cdeg": 20.0,
    "n": 15,
    "th": 0.05,
    "pole": 0.15,
    "cw": False,
    "rail": True,
    "roff": 0.05,
    "rh": 0.90,
    "rd": 0.05,
    "cd": 0.02,
    "nr": 3,
}

_S = dict(DEFAULTS)
_S.update({"z": 0.0, "name": tr("Scala a chiocciola"), "level": None,
           "tlv": None, "toff": 0.0})
for _k in PAINT_KEYS:
    _S[_k] = None


def _params(d) -> dict:
    g = lambda k: d.get(k, DEFAULTS[k])
    return {
        "tipo": g("tipo"),
        "a": max(float(g("a")), 0.05),
        "b": max(float(g("b")), 0.005),
        "c": math.radians(max(1.0, min(float(g("cdeg")), 90.0))),
        "n": max(1, int(g("n"))),
        "d": max(float(g("th")), 0.001),
        "e": max(float(g("pole")), 0.0),
        "f": float(g("roff")),
        "g": max(float(g("rh")), 0.0),
        "h": max(float(g("rd")), 0.001),
        "i": max(float(g("cd")), 0.001),
        "corr": bool(g("rail")),
        "ncorr": max(0, int(g("nr"))),
        "sg": -1.0 if g("cw") else 1.0,
    }


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _len(a):
    return math.sqrt(_dot(a, a))


def _unit(a):
    ln = _len(a)
    return (a[0] / ln, a[1] / ln, a[2] / ln) if ln > 1e-12 else (0.0, 0.0, 0.0)


def _area2(poly) -> float:
    s = 0.0
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % len(poly)]
        s += x0 * y1 - x1 * y0
    return s


def chiocciola_meshes(d):
    from core.mesh import Mesh
    par = _params(d)
    a, b, c, n, dd = par["a"], par["b"], par["c"], par["n"], par["d"]
    e, sg = par["e"], par["sg"]
    cx, cy = d["ctr"]
    ang = d.get("ang", 0.0)
    z0 = d["z"]
    ca, sa = math.cos(ang), math.sin(ang)

    def W(x, y, z):
        return (cx + x * ca - y * sa, cy + x * sa + y * ca, z0 + z)

    steps = finestre.PaintMesh(Mesh(), d, "step")
    pole = finestre.PaintMesh(Mesh(), d, "pole")
    rail = finestre.PaintMesh(Mesh(), d, "rail")

    def add(m, pts):
        f = m.add_face([QVector3D(*p) for p in pts])
        f.attrs["layer"] = LAYER_NAME
        zone = ("step" if m is steps else "pole" if m is pole else "rail")
        if not (d.get("col_" + zone) or d.get("tex_" + zone)) and not any(
                k in f.attrs for k in ("color", "texture", "mat")):
            col, nm = DEFAULT_MATS[zone]
            f.attrs["color"] = col
            f.attrs["mat"] = nm
        return f

    def quad(m, v0, v1, v2, v3):
        nrm = _unit(_cross(_sub(v1, v0), _sub(v2, v0)))
        if abs(_dot(nrm, _sub(v3, v0))) > 5e-4:
            add(m, [v0, v1, v2])
            add(m, [v0, v2, v3])
        else:
            add(m, [v0, v1, v2, v3])

    r_in = e / 2.0 * 0.8 if e > 0.002 else 0.0
    seg_arco = 1 if par["tipo"] == "A" else max(
        1, int(math.ceil(math.degrees(c) / 10.0)))
    for k in range(n):
        th0 = sg * k * c
        poly = [(r_in * math.cos(th0), r_in * math.sin(th0))
                if r_in > 1e-6 else (0.0, 0.0)]
        for m in range(seg_arco + 1):
            th = th0 + sg * c * m / seg_arco
            poly.append((a * math.cos(th), a * math.sin(th)))
        if r_in > 1e-6:
            th1 = th0 + sg * c
            poly.append((r_in * math.cos(th1), r_in * math.sin(th1)))
        if _area2(poly) < 0:
            poly.reverse()
        zt = (k + 1) * b
        zb = max(zt - dd, 0.0)
        add(steps, [W(x, y, zt) for x, y in poly])
        add(steps, [W(x, y, zb) for x, y in reversed(poly)])
        for i in range(len(poly)):
            j = (i + 1) % len(poly)
            (xi, yi), (xj, yj) = poly[i], poly[j]
            add(steps, [W(xi, yi, zb), W(xj, yj, zb),
                        W(xj, yj, zt), W(xi, yi, zt)])

    if e > 0.002:
        rr, zt = e / 2.0, n * b
        ring = [(rr * math.cos(2 * math.pi * j / POLE_SIDES),
                 rr * math.sin(2 * math.pi * j / POLE_SIDES))
                for j in range(POLE_SIDES)]
        add(pole, [W(x, y, 0.0) for x, y in reversed(ring)])
        add(pole, [W(x, y, zt) for x, y in ring])
        for j in range(POLE_SIDES):
            jj = (j + 1) % POLE_SIDES
            add(pole, [W(ring[j][0], ring[j][1], 0.0),
                       W(ring[jj][0], ring[jj][1], 0.0),
                       W(ring[jj][0], ring[jj][1], zt),
                       W(ring[j][0], ring[j][1], zt)])
        _soften(pole.mesh)

    if par["corr"]:
        R = max(a - par["f"], 0.02)
        per = max(2, int(math.ceil(math.degrees(c) / 6.0)))
        tot = n * per

        def elica(up):
            pts = []
            for q in range(tot + 1):
                phi = c * n * q / tot
                th = sg * phi
                pts.append((R * math.cos(th), R * math.sin(th),
                            b * (phi / c + 0.5) + up))
            return pts

        def sweep(pts, r, seg):
            rings = []
            for idx, pt in enumerate(pts):
                p0 = pts[max(idx - 1, 0)]
                p1 = pts[min(idx + 1, len(pts) - 1)]
                T = _sub(p1, p0)
                if _len(T) < 1e-9:
                    continue
                T = _unit(T)
                rif = (pt[0], pt[1], 0.0)
                if _len(rif) < 1e-9:
                    rif = (1.0, 0.0, 0.0)
                N = _sub(rif, _mul(T, _dot(rif, T)))
                if _len(N) < 1e-9:
                    N = _cross((0.0, 0.0, 1.0), T)
                N = _unit(N)
                B = _cross(T, N)
                ring = []
                for j in range(seg):
                    t = 2.0 * math.pi * j / seg
                    q = (pt[0] + (N[0] * math.cos(t) + B[0] * math.sin(t)) * r,
                         pt[1] + (N[1] * math.cos(t) + B[1] * math.sin(t)) * r,
                         pt[2] + (N[2] * math.cos(t) + B[2] * math.sin(t)) * r)
                    ring.append(W(*q))
                rings.append(ring)
            if len(rings) < 2:
                return
            for k in range(len(rings) - 1):
                r0, r1 = rings[k], rings[k + 1]
                for j in range(seg):
                    jj = (j + 1) % seg
                    quad(rail, r0[j], r0[jj], r1[jj], r1[j])
            add(rail, list(reversed(rings[0])))
            add(rail, rings[-1])

        sweep(elica(par["g"]), par["h"] / 2.0, 10)
        for j in range(1, par["ncorr"] + 1):
            sweep(elica(par["g"] * j / (par["ncorr"] + 1.0)),
                  par["i"] / 2.0, 6)
        _soften(rail.mesh)
    return steps.mesh, pole.mesh, rail.mesh


def _soften(mesh) -> None:
    try:
        for e in mesh.edges:
            fs = list(e.faces)
            if len(fs) != 2:
                continue
            if all(len(list(f.vertices)) <= 4 for f in fs):
                e.soft = True
                e.hidden = True
    except Exception:
        pass


def _parts(d, pose=None):
    steps, pole, rail = chiocciola_meshes(d)
    parts = [finestre._part(tr("Gradini"), steps, pose)]
    if len(pole.faces):
        parts.append(finestre._part(tr("Palo"), pole, pose))
    if len(rail.faces):
        parts.append(finestre._part(tr("Corrimano"), rail, pose))
    return parts


def chioc_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "ctr" in data else None


def rebuild_chiocciola(group, p: dict) -> None:
    d = dict(chioc_data(group))
    d.update(p)
    finestre.clean_paint(d)
    pose = finestre._pose(group)
    group.children = _parts(d, pose)
    _ifc.tag(group, "IfcStair")
    ext = dict(group.ext or {})
    ext[KEY] = d
    group.ext = ext


def build_chiocciola(scene, d, name):
    from core.group import Group
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    g = Group(name=name)
    g.adopt(_parts(d))
    g.component = False
    g.layer = LAYER_NAME
    _ifc.tag(g, "IfcStair", name)
    g.ext = {KEY: d}
    scene.groups.append(g)
    return g


def apply_top(scene, d, tlv, toff, level) -> bool:
    n = max(1, int(d.get("n", DEFAULTS["n"])))
    h = piani.height_for(scene, tlv, toff, level, d["z"])
    if h is None or h <= EPS:
        return False
    d["b"] = h / n
    d["tlv"], d["toff"] = tlv, toff
    return True


def _apply_place(scene, d, meta) -> bool:
    for k in ("lv", "lvn", "off", "tlv", "toff"):
        d.pop(k, None)
    z, extra = piani.place(scene, meta["lid"], meta["off"])
    d["z"] = z
    d.update(extra)
    if meta["tlv"]:
        return apply_top(scene, d, meta["tlv"], meta["toff"], meta["lid"])
    return True


def _spin(value, lo, hi, dec=3):
    s = LengthSpin()
    s.setDecimals(dec)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


def _dim_grande(p, x1, y1, x2, y2, txt, lato=1):
    p.setPen(QPen(muri._C_QUOTA, 1.3))
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    w = 8 * len(txt) + 2
    if abs(y1 - y2) < 1e-6:
        for x in (x1, x2):
            p.drawLine(QPointF(x, y1 - 3), QPointF(x, y1 + 3))
        muri._t(p, (x1 + x2) / 2 - w / 2, y1 + (-5 if lato > 0 else 14), txt, muri._C_QUOTA, 14, True)
    else:
        for y in (y1, y2):
            p.drawLine(QPointF(x1 - 3, y), QPointF(x1 + 3, y))
        muri._t(p, x1 + (6 if lato > 0 else -w - 4), (y1 + y2) / 2 + 5, txt, muri._C_QUOTA, 14, True)


def _disegno_chiocciola(p):
    r, t, dim, ext = muri._r, muri._t, _dim_grande, muri._ext
    from PySide6.QtGui import QPolygonF
    q, line = muri._C_QUOTA, muri._C_LINEA

    def foglia(x, y, txt, bx, by):
        p.setPen(QPen(q, 1.1))
        p.drawLine(QPointF(x, y), QPointF(bx + 4, by - 4))
        t(p, bx - 4, by + 2, txt, q, 14, True)

    t(p, 10, 12, tr("Pianta (tipo A)"), size=12)
    cx, cy, a = 55.0, 108.0, 80.0
    c = math.radians(35)
    pts = [(cx + a, cy), (cx + a * math.cos(c), cy - a * math.sin(c)),
           (cx + a * math.cos(2 * c), cy - a * math.sin(2 * c))]
    p.setPen(QPen(line, 1.2))
    p.setBrush(muri._C_ANTA)
    p.drawPolygon(QPolygonF([QPointF(cx, cy), QPointF(*pts[1]), QPointF(*pts[2])]))
    p.setBrush(muri._C_CORPO)
    p.drawPolygon(QPolygonF([QPointF(cx, cy), QPointF(*pts[0]), QPointF(*pts[1])]))
    p.setBrush(muri._C_BIANCO)
    p.drawEllipse(QPointF(cx, cy), 8, 8)
    pen = QPen(line, 1)
    pen.setStyle(Qt.DashLine)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(cx - 66, cy - 66, 132, 132), 0, int(math.degrees(c) * 16))
    p.setPen(QPen(q, 1.1))
    p.drawArc(QRectF(cx - 28, cy - 28, 56, 56), 0, int(math.degrees(c) * 16))
    t(p, cx + 33 * math.cos(c / 2), cy - 33 * math.sin(c / 2) + 5, "c", q, 14, True)
    dim(p, cx, cy + 14, cx + a, cy + 14, "a", -1)
    ext(p, cx, cy + 8, cx, cy + 14)
    ext(p, cx + a, cy, cx + a, cy + 14)
    dim(p, cx + a - 14, cy - 8, cx + a, cy - 8, "f", 1)
    foglia(cx - 6, cy - 6, "e", cx - 24, cy - 16)

    t(p, 235, 12, tr("Sezione"), size=12)
    p.setPen(QPen(line, 1.5))
    p.drawLine(QPointF(235, 150), QPointF(355, 150))
    muri._hatch(p, 235, 150, 355, 156)
    r(p, 245, 48, 257, 150, muri._C_BIANCO)
    for y in (128, 112, 96, 80):
        r(p, 257, y, 330, y + 6, muri._C_LEGNO)
    ext(p, 245, 40, 245, 48)
    ext(p, 257, 40, 257, 48)
    dim(p, 245, 40, 257, 40, "e", 1)
    ext(p, 330, 68, 330, 80)
    dim(p, 257, 68, 330, 68, "a", 1)
    ext(p, 330, 96, 342, 96)
    ext(p, 330, 112, 342, 112)
    dim(p, 342, 96, 342, 112, "b", 1)
    ext(p, 330, 80, 342, 80)
    ext(p, 330, 86, 342, 86)
    dim(p, 342, 80, 342, 86, "d", 1)
    t(p, 235, 168, "n = " + tr("numero alzate"), size=11)

    t(p, 372, 12, tr("Corrimano"), size=12)
    r(p, 375, 128, 450, 134, muri._C_LEGNO)
    pen = QPen(line, 1)
    pen.setStyle(Qt.DashDotLine)
    p.setPen(pen)
    p.drawLine(QPointF(436, 134), QPointF(436, 56))
    p.setPen(QPen(line, 1.2))
    for y in (111, 94, 77):
        p.setBrush(muri._C_BIANCO)
        p.drawEllipse(QPointF(436, y), 3, 3)
    p.setBrush(muri._C_LEGNO)
    p.drawEllipse(QPointF(436, 60), 7, 7)
    ext(p, 436, 60, 462, 60)
    ext(p, 450, 128, 462, 128)
    dim(p, 462, 60, 462, 128, "g", 1)
    ext(p, 436, 134, 436, 146)
    ext(p, 450, 134, 450, 146)
    dim(p, 436, 146, 450, 146, "f", -1)
    foglia(429, 57, "h", 402, 52)
    foglia(433, 94, "i", 402, 96)


def ask_params(parent, cur: dict, scene, title: str, edit: bool = False,
               groups=None):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(muri._Schema(_disegno_chiocciola))
    cf = (_codici.CodeField(form, groups, "scala", scene, at=1)
          if groups else None)
    g = lambda k: cur.get(k, DEFAULTS.get(k))

    tipo = QComboBox()
    tipo.addItem(tr("A: gradino a spicchio (bordo esterno rettilineo)"), "A")
    tipo.addItem(tr("B: gradino a settore (bordo esterno ad arco)"), "B")
    tipo.setCurrentIndex(max(0, tipo.findData(g("tipo"))))
    a = _spin(g("a"), 0.1, 10.0)
    b = _spin(g("b"), 0.02, 1.0)
    cdeg = _spin(g("cdeg"), 1.0, 90.0, 2)
    n = QSpinBox()
    n.setRange(1, 400)
    n.setValue(int(g("n")))
    th = _spin(g("th"), 0.005, 0.5)
    pole = _spin(g("pole"), 0.0, 2.0)
    cw = QCheckBox(tr("Senso orario (Spazio durante il disegno)"))
    cw.setChecked(bool(g("cw")))
    rail = QCheckBox(tr("Corrimano e correnti intermedi"))
    rail.setChecked(bool(g("rail")))
    roff = _spin(g("roff"), -1.0, 5.0)
    rh = _spin(g("rh"), 0.0, 3.0)
    rd = _spin(g("rd"), 0.005, 0.5)
    cd = _spin(g("cd"), 0.005, 0.5)
    nr = QSpinBox()
    nr.setRange(0, 20)
    nr.setValue(int(g("nr")))

    name = QLineEdit(_S["name"]) if not edit else None
    lvl = top_cb = top_off = None
    if scene is not None and piani.levels(scene):
        lvl = piani.level_combo(
            scene, cur.get("lv") if edit else piani.active_id(scene))
        form.addRow(tr("Piano di partenza"), lvl)
    init_off = cur.get("off", cur.get("z", 0.0)) if edit else _S["z"]
    off = _spin(init_off, -100.0, 1000.0)
    form.addRow(tr("Quota di partenza: da terra / sopra il piano (m)"), off)
    if lvl is not None:
        top_cb, top_off = piani.add_top_rows(
            form, scene, _spin(3.0, 0.1, 100.0), cur.get("tlv"),
            cur.get("toff", 0.0))
    form.addRow(tr("Tipo di gradino"), tipo)
    form.addRow(tr("Larghezza gradino (a)"), a)
    form.addRow(tr("Alzata (b)"), b)
    form.addRow(tr("Angolo gradino (c, gradi)"), cdeg)
    form.addRow(tr("Numero alzate"), n)
    form.addRow(tr("Spessore gradino (d)"), th)
    form.addRow(tr("Diametro palo (e)"), pole)
    form.addRow(cw)
    form.addRow(rail)
    form.addRow(tr("Offset linee guida (f)"), roff)
    form.addRow(tr("Altezza linee guida (g)"), rh)
    form.addRow(tr("Diametro corrimano (h)"), rd)
    form.addRow(tr("Diametro correnti (i)"), cd)
    form.addRow(tr("N. correnti intermedi"), nr)
    pk = muri.add_paint_rows(form, cur.get, ZONES)
    if name is not None:
        form.addRow(tr("Nome"), name)
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return None
    if cf is not None:
        cf.apply(parent)
    vals = {"tipo": tipo.currentData(), "a": a.value(), "b": b.value(),
            "cdeg": cdeg.value(), "n": n.value(), "th": th.value(),
            "pole": pole.value(), "cw": cw.isChecked(),
            "rail": rail.isChecked(), "roff": roff.value(),
            "rh": rh.value(), "rd": rd.value(), "cd": cd.value(),
            "nr": nr.value()}
    vals.update(muri.paint_results(pk))
    meta = {"lid": (lvl.currentData() or None) if lvl is not None else None,
            "off": off.value(),
            "tlv": (top_cb.currentData() or None) if top_cb is not None
            else None,
            "toff": top_off.value() if top_off is not None else 0.0,
            "name": name.text().strip() if name is not None else None}
    return vals, meta


class ChiocciolaTool(Tool):
    name = tr("Scala a chiocciola")
    shortcut = None
    description = tr("Scala a chiocciola: clic 1 = centro, clic 2 = primo gradino.")

    def __init__(self) -> None:
        self._entering = False
        self._vp = None
        self._reset()

    def _reset(self) -> None:
        self.center = None
        self.hover = None

    def on_activate(self, viewport) -> None:
        self._vp = viewport
        if self._entering:
            self._reset()
            viewport.flash_status(
                tr("Chiocciola: clic 1 = centro · clic 2 = primo gradino · "
                   "Spazio = senso · Esc = esci"), 7000)
            return
        res = ask_params(viewport.window(), _S, viewport.scene,
                         tr("Scala a chiocciola"))
        if res is None:
            return
        vals, meta = res
        _S.update(vals)
        _S["z"], _S["level"] = meta["off"], meta["lid"]
        _S["tlv"], _S["toff"] = meta["tlv"], meta["toff"]
        _S["name"] = meta["name"] or tr("Scala a chiocciola")
        if meta["lid"] is not None or piani.levels(viewport.scene):
            piani.set_active(meta["lid"])
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
        return key in (Qt.Key_Escape, Qt.Key_Space)

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if key == Qt.Key_Space:
            _S["cw"] = not _S["cw"]
            viewport.flash_status(
                tr("Senso orario") if _S["cw"] else tr("Senso antiorario"),
                2000)
            viewport.update()
            return True
        return False

    def _place(self):
        vp = self._vp
        if vp is None:
            return _S["z"], {}
        return piani.place(vp.scene, _S["level"], _S["z"])

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover = QVector3D(ctx.world)
        ctx.viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        if getattr(vp.scene, "edit_group", None) is not None:
            vp.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        x, y = ctx.world.x(), ctx.world.y()
        if self.center is None:
            self.center = (x, y)
            vp.update()
            return
        if math.hypot(x - self.center[0], y - self.center[1]) < 1e-3:
            vp.flash_status(tr("Sposta il mouse: direzione del primo gradino"),
                            3000)
            return
        self._commit(vp, math.atan2(y - self.center[1], x - self.center[0]))

    def _commit(self, viewport, ang: float) -> None:
        d = {k: _S[k] for k in GEOM_KEYS}
        for k in PAINT_KEYS:
            if _S[k]:
                d[k] = copy.deepcopy(_S[k])
        d["ctr"] = [self.center[0], self.center[1]]
        d["ang"] = ang
        meta = {"lid": _S["level"], "off": _S["z"], "tlv": _S["tlv"],
                "toff": _S["toff"]}
        linked = _apply_place(viewport.scene, d, meta)
        if _S["tlv"] and not linked:
            viewport.flash_status(
                tr("Nessun piano di arrivo: uso l'alzata indicata"), 4000)
        name = _S["name"]

        def mutate(scene):
            build_chiocciola(scene, d, name)

        viewport.history.execute(muri.MuriCommand(mutate))
        viewport.notify_scene_changed()
        viewport.flash_status(
            tr("Scala a chiocciola creata · altezza {0:.2f} m").format(
                d["n"] * d["b"]), 4000)
        self._reset()
        viewport.update()

    def rubber_band_lines(self):
        ctr = self.center
        if ctr is None and self.hover is not None:
            ctr = (self.hover.x(), self.hover.y())
        if ctr is None:
            return []
        par = _params(_S)
        a, c, n, sg = par["a"], par["c"], par["n"], par["sg"]
        ang0 = 0.0
        if self.center is not None and self.hover is not None:
            dx, dy = self.hover.x() - ctr[0], self.hover.y() - ctr[1]
            if math.hypot(dx, dy) > 1e-6:
                ang0 = math.atan2(dy, dx)
        z = self._place()[0]
        P = QVector3D
        lines = []
        npt = 48
        for q in range(npt):
            t0, t1 = 2 * math.pi * q / npt, 2 * math.pi * (q + 1) / npt
            lines.append((P(ctr[0] + a * math.cos(t0), ctr[1] + a * math.sin(t0), z),
                          P(ctr[0] + a * math.cos(t1), ctr[1] + a * math.sin(t1), z)))
        for k in range(min(n, 400) + 1):
            th = ang0 + sg * k * c
            lines.append((P(ctr[0], ctr[1], z),
                          P(ctr[0] + a * math.cos(th),
                            ctr[1] + a * math.sin(th), z)))
        return lines


def _selected(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and chioc_data(g) is not None and g not in out:
            out.append(g)
    return out


def edit_chiocciola(viewport, groups=None) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    groups = groups or _selected(scene)
    if not groups:
        viewport.flash_status(
            tr("Seleziona una scala a chiocciola creata con lo strumento"), 4000)
        return
    first = chioc_data(groups[0])
    res = ask_params(viewport.window(), first, scene,
                     tr("Modifica scala a chiocciola"), edit=True,
                     groups=groups)
    if res is None:
        return
    vals, meta = res
    failed = [0]

    def mutate(sc):
        for g in groups:
            d = dict(chioc_data(g))
            d.update(vals)
            if not _apply_place(sc, d, meta):
                failed[0] += 1
            rebuild_chiocciola(g, d)

    hist = viewport.history
    hist.execute(muri.MuriCommand(mutate))
    if getattr(hist, "last_error", None):
        viewport.flash_status(
            tr("Scala: ") + str(hist.last_error).split(": ", 1)[-1], 6000)
        return
    viewport.notify_scene_changed()
    viewport.update()
    if failed[0]:
        viewport.flash_status(
            tr("Nessun piano di arrivo valido: uso l'alzata indicata"), 6000)
        return
    viewport.flash_status(tr("Scala a chiocciola aggiornata"), 3000)


def _hook_double_click(vp) -> None:
    if getattr(vp, "_myhouse_chioc_dbl", False):
        return
    original = vp.begin_group_edit

    def begin_group_edit(group, *args, **kwargs):
        g = getattr(group, "owner", None) or group
        if chioc_data(g) is None:
            return original(group, *args, **kwargs)
        from PySide6.QtCore import QTimer
        scene = vp.scene
        try:
            scene.select([g])
        except Exception:
            scene.selection.clear()
            scene.selection.add(g)
        vp.update()
        QTimer.singleShot(0, lambda: edit_chiocciola(vp, [g]))

    vp.begin_group_edit = begin_group_edit
    vp._myhouse_chioc_dbl = True


def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(215, 205, 190))
    p.drawEllipse(5, 5, 38, 38)
    for k in range(7):
        t = 2 * math.pi * k / 7
        p.drawLine(24, 24, int(24 + 19 * math.cos(t)), int(24 + 19 * math.sin(t)))
    p.setBrush(QColor(90, 90, 95))
    p.drawEllipse(19, 19, 10, 10)
    p.end()
    return QIcon(pm)


def _outliner_kind(group):
    d = chioc_data(group)
    if d is None:
        return None
    from ._imperial import fmt_len
    par = _params(d)
    return {"type": tr("Scala a chiocciola"),
            "props": [(tr("Alzate"), str(par["n"])),
                      (tr("Alzata"), fmt_len(par["b"])),
                      (tr("Altezza"), fmt_len(par["n"] * par["b"])),
                      (tr("Larghezza gradino"), fmt_len(par["a"])),
                      (tr("Giri"), f"{par['n'] * math.degrees(par['c']) / 360:.2f}")]
            + piani.level_props(d)}


def _register_level_kind() -> None:
    def zset(d, z):
        d["z"] = z

    def hget(d):
        return max(1, int(d.get("n", DEFAULTS["n"]))) * d["b"]

    def hset(d, h):
        n = max(1, int(d.get("n", DEFAULTS["n"])))
        if h > EPS:
            d["b"] = h / n

    piani.register_kind("chiocciola", KEY, chioc_data, lambda d: d["z"], zset,
                        rebuild_chiocciola, hget, hset)


def register(api) -> None:
    _register_level_kind()
    api.add_button(tr("Scala a chiocciola"),
                   tr("Crea una scala a chiocciola con corrimano e correnti"),
                   _icon(), api.run_tool(ChiocciolaTool()))
    app = api.app
    _hook_double_click(api.window.viewport)
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        from PySide6.QtCore import QTimer

        def context(menu, selection) -> None:
            if not _selected(app.viewport.scene):
                return
            menu.addSeparator()
            menu.addAction(
                tr("Modifica scala a chiocciola…"),
                lambda: QTimer.singleShot(
                    0, lambda: edit_chiocciola(app.viewport)))

        add_ctx(context)
    add_kind = getattr(app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
