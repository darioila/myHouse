# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr
from ._imperial import FT, IN, LengthSpin, dflt
from ._scroll import scroll_form

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPen, QVector3D
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QLineEdit, QPushButton, QVBoxLayout,
)

from core import bim
from . import _ifc
from tools.base import Tool, ToolContext

from . import _codici, muri, piani, _tipi

ORDER = 41
COLUMN_COLOR = (0.62, 0.63, 0.66)
COLUMN_MAT_NAME = tr("materiale pilastro")
LAYER_NAME = "Pilastri"
KEY = "myhouse_pilastro"
SEGMENTS = 32
ANCHORS = [("c", tr("Centro")),
           ("bl", tr("Spigolo basso a sinistra")),
           ("br", tr("Spigolo basso a destra")),
           ("tr", tr("Spigolo alto a destra")),
           ("tl", tr("Spigolo alto a sinistra"))]
SHAPES = [("rect", tr("Rettangolare")), ("square", tr("Quadrato")), ("round", tr("Tondo")),
          ("ibeam", tr("A I"))]


def _grid_snap(scene, x, y):
    try:
        from . import griglia
        return griglia.snap_point(scene, x, y)
    except Exception:
        return None


class _Settings:
    shape = "square"
    w = dflt(12 * IN, 0.30)
    dp = dflt(16 * IN, 0.40)
    dia = dflt(12 * IN, 0.35)
    tf = 0.02
    tw = 0.012
    h = dflt(8 * FT, 3.00)
    z0 = 0.0
    rot = 0.0
    anc = "c"
    name = tr("Pilastro")
    level = None
    tlv = None
    toff = 0.0
    tipo_id = None
    tipo_nome = None


def _params() -> dict:
    return {"shape": _Settings.shape, "w": _Settings.w, "dp": _Settings.dp,
            "dia": _Settings.dia, "h": _Settings.h, "z0": _Settings.z0,
            "rot": _Settings.rot, "name": _Settings.name,
            "anc": _Settings.anc, "tf": _Settings.tf, "tw": _Settings.tw,
            "tipo_id": _Settings.tipo_id, "tipo_nome": _Settings.tipo_nome}


def _store(p: dict) -> None:
    for k in ("shape", "w", "dp", "dia", "h", "z0", "rot", "name", "tf", "tw"):
        setattr(_Settings, k, p[k])
    _Settings.anc = p.get("anc", "c")
    _Settings.level = p.get("lv")
    _Settings.tlv = p.get("tlv")
    _Settings.toff = p.get("toff") or 0.0
    _Settings.tipo_id = p.get("tipo_id")
    _Settings.tipo_nome = p.get("tipo_nome")


def _linked_height(scene, level_id, tlv, toff, zb):
    if not tlv:
        return None
    return piani.height_for(scene, tlv, toff, level_id, zb)


def _half(d):
    if d["shape"] == "round":
        r = d["dia"] / 2
        return r, r
    return d["w"] / 2, (d["w"] if d["shape"] == "square" else d["dp"]) / 2


def anchor_offset(d, anc=None):
    anc = d.get("anc", "c") if anc is None else anc
    sx, sy = {"bl": (-1, -1), "br": (1, -1), "tr": (1, 1),
              "tl": (-1, 1)}.get(anc, (0, 0))
    hw, hd = _half(d)
    a = 0.0 if d["shape"] == "round" else math.radians(d.get("rot", 0.0))
    x, y = sx * hw, sy * hd
    return (x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a))


def center_from_anchor(d, pt):
    ox, oy = anchor_offset(d)
    return [pt[0] - ox, pt[1] - oy]


def footprint(d, cx=None, cy=None):
    cx = d["c"][0] if cx is None else cx
    cy = d["c"][1] if cy is None else cy
    if d["shape"] == "round":
        r = d["dia"] / 2
        return [(cx + r * math.cos(2 * math.pi * i / SEGMENTS),
                 cy + r * math.sin(2 * math.pi * i / SEGMENTS))
                for i in range(SEGMENTS)]
    return _rotated(_local_outline(d), d, cx, cy)


def _rotated(pts, d, cx, cy):
    a = math.radians(d.get("rot", 0.0))
    ca, sa = math.cos(a), math.sin(a)
    return [(cx + x * ca - y * sa, cy + x * sa + y * ca) for x, y in pts]


def _ibeam_parts(d):
    w, dp = d["w"], d["dp"]
    tf = max(0.001, min(d.get("tf", 0.02), (dp - 0.005) / 2))
    tw = max(0.001, min(d.get("tw", 0.012), w - 0.005))
    a, b, c = w / 2, tw / 2, dp / 2
    outline = [(a, -c), (a, -c + tf), (b, -c + tf), (b, c - tf), (a, c - tf),
               (a, c), (-a, c), (-a, c - tf), (-b, c - tf), (-b, -c + tf),
               (-a, -c + tf), (-a, -c)]
    pieces = [[(a, -c), (a, -c + tf), (-a, -c + tf), (-a, -c)],
              [(b, -c + tf), (b, c - tf), (-b, c - tf), (-b, -c + tf)],
              [(a, c - tf), (a, c), (-a, c), (-a, c - tf)]]
    return outline, pieces


def _local_outline(d):
    if d["shape"] == "ibeam":
        return _ibeam_parts(d)[0]
    w = d["w"]
    dp = w if d["shape"] == "square" else d["dp"]
    return [(-w / 2, -dp / 2), (w / 2, -dp / 2), (w / 2, dp / 2), (-w / 2, dp / 2)]


def cap_pieces(d, cx=None, cy=None):
    cx = d["c"][0] if cx is None else cx
    cy = d["c"][1] if cy is None else cy
    if d["shape"] == "ibeam":
        return [_rotated(p, d, cx, cy) for p in _ibeam_parts(d)[1]]
    return [footprint(d, cx, cy)]


def pillar_mesh(d):
    from core.mesh import Mesh
    P = QVector3D
    pts = footprint(d)
    zb, zt = d["z0"], d["z0"] + d["h"]
    mesh = Mesh()

    def face(q):
        f = mesh.add_face(q)
        f.attrs["color"] = COLUMN_COLOR
        f.attrs["mat"] = COLUMN_MAT_NAME
        f.attrs["layer"] = LAYER_NAME

    for piece in cap_pieces(d):
        face([P(*p, zt) for p in piece])
        face([P(*p, zb) for p in reversed(piece)])
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        face([P(*pts[i], zb), P(*pts[j], zb), P(*pts[j], zt), P(*pts[i], zt)])
    return mesh


PLINTH_COLOR = (0.58, 0.58, 0.56)
PLINTH_MAT_NAME = tr("materiale plinto")


PLINTH_BASE_COLOR = (0.70, 0.70, 0.68)
PLINTH_BASE_MAT_NAME = tr("materiale base plinto")


def _rect_pts(d, L, P):
    rot = 0.0 if d.get("shape") == "round" else d.get("rot", 0.0)
    return _rotated([(-L / 2, -P / 2), (L / 2, -P / 2), (L / 2, P / 2),
                     (-L / 2, P / 2)], {"rot": rot}, d["c"][0], d["c"][1])


def plinth_z(d):
    pl = d["plinto"]
    top = d["z0"] + pl.get("dz", 0.0)
    return top - pl["H"], top


def plinth_solids(d):
    pl = d["plinto"]
    L, P = pl["L"], pl["P"]
    zb, zt = plinth_z(d)
    out = []
    bh, bs = pl.get("bh", 0.0), pl.get("bs", 0.0)
    if bh > 1e-6:
        r = _rect_pts(d, L + 2 * bs, P + 2 * bs)
        out.append((r, zb - bh, r, zb, "base"))
    full = _rect_pts(d, L, P)
    if pl.get("tipo") == "tap":
        hv = max(0.0, min(pl.get("Hv", 0.0), pl["H"] - 0.01))
        hw, hd = _half(d)
        lt = pl.get("Lt") or (2 * hw + 0.10)
        pt = pl.get("Pt") or (2 * hd + 0.10)
        top = _rect_pts(d, min(lt, L), min(pt, P))
        if hv > 1e-6:
            out.append((full, zb, full, zb + hv, "plinto"))
        out.append((full, zb + hv, top, zt, "plinto"))
    else:
        out.append((full, zb, full, zt, "plinto"))
    return out


def plinth_mesh(d):
    from core.mesh import Mesh
    P = QVector3D
    mesh = Mesh()

    def face(q, kind):
        f = mesh.add_face(q)
        base = kind == "base"
        f.attrs["color"] = PLINTH_BASE_COLOR if base else PLINTH_COLOR
        f.attrs["mat"] = PLINTH_BASE_MAT_NAME if base else PLINTH_MAT_NAME
        f.attrs["layer"] = LAYER_NAME

    for lo, zl, hi, zh, kind in plinth_solids(d):
        face([P(*p, zh) for p in hi], kind)
        face([P(*p, zl) for p in reversed(lo)], kind)
        n = len(lo)
        for i in range(n):
            j = (i + 1) % n
            face([P(*lo[i], zl), P(*lo[j], zl), P(*hi[j], zh), P(*hi[i], zh)],
                 kind)
    return mesh


def _parts(d):
    from core.group import Group
    parts = [Group(pillar_mesh(d), name=tr("Pilastro"))]
    if d.get("plinto"):
        parts.append(Group(plinth_mesh(d), name=tr("Plinto")))
    for part in parts:
        part.component = False
    return parts


def pillar_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "c" in data else None


def build_pillar(scene, d) -> None:
    from core.group import Group
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    g = Group(name=d["name"])
    g.adopt(_parts(d))
    g.component = False
    g.layer = LAYER_NAME
    _ifc.tag(g, "IfcColumn", d["name"])
    g.ext = {KEY: d}
    scene.groups.append(g)


def rebuild_pillar(group, p: dict) -> None:
    d = dict(pillar_data(group))
    old_anc = d.get("anc", "c")
    d.update(p)
    for k in [k for k, v in d.items() if v is None]:
        d.pop(k)
    if d.get("anc", "c") != old_anc or "pt" not in d:
        ox, oy = anchor_offset(d)
        d["pt"] = [d["c"][0] + ox, d["c"][1] + oy]
    elif d.get("anc", "c") != "c":
        d["c"] = center_from_anchor(d, d["pt"])
    else:
        d["pt"] = list(d["c"])
    group.children = _parts(d)
    _ifc.tag(group, "IfcColumn")
    group.name = d["name"]
    ext = dict(group.ext or {})
    ext[KEY] = d
    group.ext = ext


def _spin(value, lo, hi):
    s = LengthSpin()
    s.setDecimals(3)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


def _disegno_pilastro(p):
    r, t, dim, ext = muri._r, muri._t, muri._dim, muri._ext
    t(p, 10, 12, tr("Pianta"), size=9)
    r(p, 30, 45, 90, 100, muri._C_CORPO)
    p.setPen(QPen(muri._C_LINEA, 1))
    p.setBrush(muri._C_QUOTA)
    for x, y in ((30, 45), (90, 45), (30, 100), (90, 100), (60, 72)):
        p.drawEllipse(QPointF(x, y), 2.5, 2.5)
    dim(p, 30, 36, 90, 36, "L", 1)
    dim(p, 20, 45, 20, 100, "P", -1)
    t(p, 30, 118, tr("● punti di aggancio"), size=8)
    t(p, 30, 130, tr("α = rotazione attorno al centro"), size=8)
    p.setPen(QPen(muri._C_LINEA, 1.2))
    p.setBrush(muri._C_CORPO)
    p.drawEllipse(QPointF(150, 72), 25, 25)
    dim(p, 125, 72, 175, 72, "d", 1)
    r(p, 205, 45, 265, 54, muri._C_CORPO)
    r(p, 205, 91, 265, 100, muri._C_CORPO)
    r(p, 230, 54, 240, 91, muri._C_CORPO)
    dim(p, 205, 36, 265, 36, "L", 1)
    dim(p, 195, 45, 195, 100, "P", -1)
    dim(p, 277, 45, 277, 54, "tf", 1)
    dim(p, 230, 112, 240, 112, "tw", 1)
    t(p, 320, 12, tr("Prospetto"), size=9)
    p.setPen(QPen(muri._C_LINEA, 1.5))
    p.drawLine(QPointF(300, 150), QPointF(470, 150))
    muri._hatch(p, 300, 150, 470, 156)
    r(p, 365, 25, 405, 120, muri._C_CORPO)
    dim(p, 350, 25, 350, 120, "H", -1)
    dim(p, 350, 120, 350, 150, "z", -1)
    ext(p, 405, 120, 430, 120)
    t(p, 410, 112, tr("faccia inf."), size=8)


def ask_params(parent, cur: dict, title: str, scene=None,
               creating: bool = False, groups=None):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(muri._Schema(_disegno_pilastro))
    shape = QComboBox()
    for key, label in SHAPES:
        shape.addItem(label, key)
    shape.setCurrentIndex([k for k, _ in SHAPES].index(cur["shape"]))
    w = _spin(cur["w"], 0.02, 20.0)
    dp = _spin(cur["dp"], 0.02, 20.0)
    dia = _spin(cur["dia"], 0.02, 20.0)
    tf = _spin(cur.get("tf", 0.02), 0.002, 5.0)
    tw = _spin(cur.get("tw", 0.012), 0.002, 5.0)
    h = _spin(cur["h"], 0.05, 100.0)
    z0 = _spin(cur["z0"], -100.0, 1000.0)
    rot = _spin(cur["rot"], -360.0, 360.0)
    anc = QComboBox()
    for key, label in ANCHORS:
        anc.addItem(label, key)
    anc.setCurrentIndex([k for k, _ in ANCHORS].index(cur.get("anc", "c")))
    anc.setToolTip(tr("Punto del pilastro che va sul clic. Per il pilastro "
                      "tondo si usa il quadrato che lo contiene."))
    name = QLineEdit(cur["name"])
    lvl = None
    top_cb = top_off = None
    if scene is not None and piani.levels(scene):
        lvl = piani.level_combo(scene, cur.get("lv"))
    form.addRow(tr("Forma"), shape)
    if lvl is not None:
        form.addRow(tr("Piano"), lvl)
    form.addRow(tr("Larghezza (L) (m)"), w)
    form.addRow(tr("Profondità (P) (m)"), dp)
    form.addRow(tr("Diametro (d) (m)"), dia)
    form.addRow(tr("Spessore ali (tf) (m)"), tf)
    form.addRow(tr("Spessore anima (tw) (m)"), tw)
    form.addRow(tr("Altezza (H) (m)"), h)
    if lvl is not None:
        top_cb, top_off = piani.add_top_rows(form, scene, h, cur.get("tlv"),
                                             cur.get("toff", 0.0))
    form.addRow(tr("Altezza da terra / dal piano - faccia inferiore (z) (m)"), z0)
    form.addRow(tr("Rotazione (α) (°)"), rot)
    form.addRow(tr("Punto di aggancio"), anc)
    form.addRow(tr("Nome"), name)

    def _get_tipo():
        return {"shape": shape.currentData(), "w": w.value(),
                "dp": dp.value(), "dia": dia.value(),
                "tf": tf.value(), "tw": tw.value()}

    def _set_tipo(t):
        if "shape" in t:
            shape.setCurrentIndex(max(0, shape.findData(t["shape"])))
        for k, wd in (("w", w), ("dp", dp), ("dia", dia), ("tf", tf),
                      ("tw", tw)):
            if k in t:
                wd.setValue(t[k])

    tbar = _tipi.TypeBar(dlg, form, "pilastro", cur, _get_tipo, _set_tipo,
                         scene, creating=creating)
    cf = (_codici.CodeField(form, groups, "pilastro", scene, at=2)
          if groups else None)
    scroll_form(dlg, lay, form)
    auto_flag = [False]
    if creating:
        auto_btn = QPushButton(tr("Posiziona automaticamente sulle griglie"))
        auto_btn.setToolTip(tr("Poi scegli le griglie con un clic (A = tutte) e premi Invio: "
                               "un pilastro su ogni incrocio."))

        def _auto() -> None:
            auto_flag[0] = True
            dlg.accept()

        auto_btn.clicked.connect(_auto)
        lay.addWidget(auto_btn)

    def sync() -> None:
        k = shape.currentData()
        w.setEnabled(k in ("rect", "square", "ibeam"))
        dp.setEnabled(k in ("rect", "ibeam"))
        tf.setEnabled(k == "ibeam")
        tw.setEnabled(k == "ibeam")
        dia.setEnabled(k == "round")
        rot.setEnabled(k != "round")

    shape.currentIndexChanged.connect(lambda _i: sync())
    sync()
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return None
    if cf is not None:
        cf.apply(dlg)
    wv, dpv = w.value(), dp.value()
    tfv = min(tf.value(), max(0.002, (dpv - 0.005) / 2))
    twv = min(tw.value(), max(0.002, wv - 0.005))
    res = tbar.result({"shape": shape.currentData(), "w": wv, "dp": dpv,
            "tf": tfv, "tw": twv,
            "dia": dia.value(), "h": h.value(), "z0": z0.value(),
            "rot": rot.value(), "anc": anc.currentData(),
            "name": name.text().strip() or tr("Pilastro"),
            "lv": (lvl.currentData() or None) if lvl is not None else None,
            "tlv": (top_cb.currentData() or None) if top_cb is not None
            else None,
            "toff": top_off.value() if top_off is not None else 0.0})
    if auto_flag[0]:
        res["auto"] = True
    return res


class PilastroTool(Tool):
    name = tr("Pilastro")
    shortcut = None
    description = tr("Crea pilastri rettangolari, quadrati, tondi o a I.")

    def __init__(self) -> None:
        self._entering = False
        self.hover_point: QVector3D | None = None
        self._auto = False
        self._picked = []
        self._snapped = False

    def on_activate(self, viewport) -> None:
        self._vp = viewport
        if self._entering:
            self.hover_point = None
            if self._auto:
                viewport.flash_status(
                    tr("Clic sulle griglie per sceglierle (A = tutte) · Invio = posiziona i pilastri · Esc = esci"),
                    8000)
            else:
                viewport.flash_status(
                    tr("Pilastro: clic per posare il centro · Esc = esci"), 6000)
            return
        cur = _params()
        cur["lv"] = piani.active_id(viewport.scene)
        cur["tlv"], cur["toff"] = _Settings.tlv, _Settings.toff
        cur["tipo_id"], cur["tipo_nome"] = _Settings.tipo_id, _Settings.tipo_nome
        p = ask_params(viewport.window(), cur, tr("Pilastro"), viewport.scene,
                       creating=True)
        if p is None:
            return
        _store(p)
        piani.set_active(p.get("lv"))
        auto = bool(p.get("auto"))
        picked = []
        if auto:
            try:
                from . import griglia
                picked = griglia.selected_grids(viewport.scene)
            except Exception:
                picked = []
        self._auto = auto
        self._picked = picked
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False
        self._auto = auto
        self._picked = picked
        if auto:
            viewport.update()

    def on_deactivate(self, viewport) -> None:
        self.hover_point = None
        self._auto = False
        self._picked = []

    def on_cancel(self, viewport) -> None:
        self.hover_point = None
        viewport.update()

    def _exit(self, viewport) -> None:
        self.hover_point = None
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
        if self._auto and key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_A):
            return True
        return key == Qt.Key_Escape

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if self._auto and key == Qt.Key_A:
            from . import griglia
            self._picked = [g for g, _ in griglia.grids(viewport.scene)]
            viewport.flash_status(
                tr("{0} griglie scelte · Invio = posiziona i pilastri").format(len(self._picked)), 4000)
            viewport.update()
            return True
        if self._auto and key in (Qt.Key_Return, Qt.Key_Enter):
            self._place_on_grids(viewport)
            return True
        return False

    def _place_on_grids(self, vp) -> None:
        from . import griglia
        scene = vp.scene
        if getattr(scene, "edit_group", None) is not None:
            vp.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        chosen = self._picked or [g for g, _ in griglia.grids(scene)]
        pts = griglia.intersections(chosen)
        if not pts:
            vp.flash_status(tr("Nessun incrocio tra le griglie scelte"), 4000)
            return
        existing = []
        for g in scene.groups:
            pd = pillar_data(g)
            if pd is not None:
                existing.append(pd["c"])
        pts = [p for p in pts
               if not any(math.hypot(p[0] - c[0], p[1] - c[1]) < 0.02 for c in existing)]
        if not pts:
            vp.flash_status(tr("Pilastri già presenti su tutti gli incroci"), 4000)
            return
        zw = griglia.grid_data(chosen[0]).get("zb", 0.0)
        dicts = [self._dict_at(vp, p, zw, True) for p in pts]

        def mutate(sc):
            for d in dicts:
                build_pillar(sc, d)
            try:
                muri.update_roof_clips(sc)
            except Exception:
                pass

        vp.history.execute(muri.MuriCommand(mutate))
        vp.notify_scene_changed()
        self._picked = []
        vp.flash_status(tr("{0} pilastri creati").format(len(dicts)), 3500)
        vp.update()

    def _dict_at(self, vp, pt, zw, center):
        d = _params()
        d["pt"] = [pt[0], pt[1]]
        if center:
            d["anc"] = "c"
            d["c"] = [pt[0], pt[1]]
        else:
            d["c"] = center_from_anchor(d, d["pt"])
        d["z0"], extra = piani.place(vp.scene, _Settings.level, _Settings.z0, zw)
        d.update(extra)
        if _Settings.tlv:
            hl = _linked_height(vp.scene, _Settings.level, _Settings.tlv,
                                _Settings.toff, d["z0"])
            if hl is None:
                vp.flash_status(
                    tr("Nessun piano di arrivo: uso l'altezza indicata"), 4000)
            else:
                d.update(h=hl, tlv=_Settings.tlv, toff=_Settings.toff)
        return d

    def on_hover(self, ctx: ToolContext) -> None:
        if self._auto:
            return
        w = QVector3D(ctx.world)
        s = _grid_snap(ctx.viewport.scene, w.x(), w.y())
        self._snapped = s is not None
        if s is not None:
            w.setX(s[0])
            w.setY(s[1])
        self.hover_point = w
        ctx.viewport.update()

    def rubber_band_lines(self):
        P = QVector3D
        if self._auto:
            out = []
            for g in self._picked:
                gd = (getattr(g, "ext", None) or {}).get("myhouse_griglia")
                if gd:
                    z = gd["z"] + 0.01
                    out.append((P(*gd["p1"], z), P(*gd["p2"], z)))
            return out
        if self.hover_point is None:
            return []
        d = {"shape": _Settings.shape, "w": _Settings.w, "dp": _Settings.dp,
             "dia": _Settings.dia, "rot": _Settings.rot,
             "anc": _Settings.anc, "tf": _Settings.tf, "tw": _Settings.tw}
        if self._snapped:
            cx, cy = self.hover_point.x(), self.hover_point.y()
        else:
            cx, cy = center_from_anchor(d, (self.hover_point.x(),
                                            self.hover_point.y()))
        pts = footprint(d, cx, cy)
        zb = self.hover_point.z() + _Settings.z0
        vp = getattr(self, "_vp", None)
        if vp is not None:
            zb = piani.place(vp.scene, _Settings.level, _Settings.z0,
                             self.hover_point.z())[0]
        zt = zb + _Settings.h
        if vp is not None:
            hl = _linked_height(vp.scene, _Settings.level, _Settings.tlv,
                                _Settings.toff, zb)
            if hl is not None:
                zt = zb + hl
        lines = []
        n = len(pts)
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            lines.append((P(*a, zb), P(*b, zb)))
            lines.append((P(*a, zt), P(*b, zt)))
        step = max(1, n // 4)
        for i in range(0, n, step):
            lines.append((P(*pts[i], zb), P(*pts[i], zt)))
        return lines

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        if getattr(vp.scene, "edit_group", None) is not None:
            vp.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        if self._auto:
            from . import griglia
            g = griglia.pick(vp.scene, ctx.world.x(), ctx.world.y())
            if g is None:
                vp.flash_status(tr("Nessuna griglia qui"), 2000)
                return
            if g in self._picked:
                self._picked.remove(g)
            else:
                self._picked.append(g)
            vp.flash_status(
                tr("{0} griglie scelte · Invio = posiziona i pilastri").format(len(self._picked)), 4000)
            vp.update()
            return
        pt = (ctx.world.x(), ctx.world.y())
        s = _grid_snap(vp.scene, pt[0], pt[1])
        if s is not None:
            d = self._dict_at(vp, s, ctx.world.z(), True)
        else:
            d = self._dict_at(vp, pt, ctx.world.z(), False)

        def mutate(scene):
            build_pillar(scene, d)
            try:
                muri.update_roof_clips(scene)
            except Exception:
                pass

        vp.history.execute(muri.MuriCommand(mutate))
        vp.notify_scene_changed()
        vp.flash_status(tr("Pilastro creato"), 2500)
        vp.update()


def _selected_pillars(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and pillar_data(g) is not None and g not in out:
            out.append(g)
    return out


def edit_pillars(viewport, groups=None) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    groups = groups or _selected_pillars(scene)
    if not groups:
        viewport.flash_status(tr("Seleziona un pilastro"), 3000)
        return
    d0 = pillar_data(groups[0])
    cur = {k: d0[k]
           for k in ("shape", "w", "dp", "dia", "h", "z0", "rot", "name")}
    cur["tf"], cur["tw"] = d0.get("tf", 0.02), d0.get("tw", 0.012)
    cur["anc"] = d0.get("anc", "c")
    if d0.get("lv"):
        cur["z0"] = d0.get("off", d0["z0"])
    cur["lv"] = d0.get("lv")
    cur["tlv"], cur["toff"] = d0.get("tlv"), d0.get("toff", 0.0)
    cur["tipo_id"], cur["tipo_nome"] = d0.get("tipo_id"), d0.get("tipo_nome")
    p = ask_params(viewport.window(), cur, tr("Modifica pilastro"), scene,
                   groups=groups)
    if p is None:
        return
    st = _tipi.resolve_edit(viewport.window(), scene, "pilastro", p)
    if st == "cancel":
        return
    if len(groups) > 1:
        p.pop("name")

    failed = [0]

    def mutate(sc):
        lv = piani.get(sc, p.get("lv"))
        for g in groups:
            q = dict(p, name=p.get("name", g.name))
            if lv:
                q.update(lv=lv["id"], lvn=lv["name"], off=p["z0"],
                         z0=lv["z"] + p["z0"])
            else:
                q.update(lv=None, lvn=None, off=None)
            tlv, toff = q.pop("tlv", None), q.pop("toff", 0.0)
            q["tlv"], q["toff"] = None, None
            if tlv:
                hl = _linked_height(sc, q["lv"], tlv, toff, q["z0"])
                if hl is None:
                    failed[0] += 1
                else:
                    q.update(h=hl, tlv=tlv, toff=toff)
            rebuild_pillar(g, q)
        if st == "type":
            _tipi.update_instances(sc, "pilastro", p["tipo_id"],
                                   rebuild_pillar)

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    if failed[0]:
        viewport.flash_status(
            tr("Nessun piano di arrivo valido (sotto la base?): "
            "uso l'altezza indicata"), 6000)
        return
    viewport.flash_status(tr("{0} pilastri aggiornati").format(len(groups)), 3000)


def _hook_double_click(vp) -> None:
    if getattr(vp, "_myhouse_pilastri_dbl", False):
        return
    original = vp.begin_group_edit

    def begin_group_edit(group, *args, **kwargs):
        g = getattr(group, "owner", None) or group
        if pillar_data(g) is None:
            return original(group, *args, **kwargs)
        from PySide6.QtCore import QTimer
        if getattr(group, "name", None) == tr("Plinto") and \
                (pillar_data(g) or {}).get("plinto"):
            from . import plinti
            try:
                vp.scene.select([g])
            except Exception:
                vp.scene.selection.clear()
                vp.scene.selection.add(g)
            vp.update()
            QTimer.singleShot(0, lambda: plinti.edit_plinti(vp, [g]))
            return
        try:
            vp.scene.select([g])
        except Exception:
            vp.scene.selection.clear()
            vp.scene.selection.add(g)
        vp.update()
        QTimer.singleShot(0, lambda: edit_pillars(vp, [g]))

    vp.begin_group_edit = begin_group_edit
    vp._myhouse_pilastri_dbl = True


def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(200, 198, 190))
    p.drawRect(17, 8, 14, 32)
    p.setBrush(QColor(170, 168, 160))
    p.drawRect(12, 4, 24, 6)
    p.drawRect(12, 38, 24, 6)
    p.end()
    return QIcon(pm)


def _outliner_kind(group):
    d = pillar_data(group)
    if d is None:
        return None
    from ._imperial import fmt_len
    if d["shape"] == "round":
        size = f"Ø {fmt_len(d['dia'])}"
    elif d["shape"] == "ibeam":
        size = f"I {fmt_len(d['w'])} × {fmt_len(d['dp'])}"
    elif d["shape"] == "square":
        size = f"{fmt_len(d['w'])} × {fmt_len(d['w'])}"
    else:
        size = f"{fmt_len(d['w'])} × {fmt_len(d['dp'])}"
    return {"type": tr("Pilastro"),
            "props": [(tr("Sezione"), size), (tr("Altezza"), fmt_len(d["h"])),
                      (tr("Altezza da terra"), fmt_len(d["z0"]))]
            + piani.level_props(d) + muri.top_props(d)}


def _register_level_kind() -> None:
    def zset(d, z):
        d["z0"] = z

    def hset(d, h):
        d["h"] = h

    piani.register_kind("pilastro", KEY, pillar_data, lambda d: d["z0"],
                        zset, rebuild_pillar, lambda d: d["h"], hset)


def register(api) -> None:
    _register_level_kind()
    api.add_button(tr("Pilastro"), tr("Crea un pilastro (rettangolare, quadrato, tondo, a I)"),
                   _icon(), api.run_tool(PilastroTool()), group="Pilastri", main=True)
    app = api.app
    _hook_double_click(api.window.viewport)
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        from PySide6.QtCore import QTimer

        def context(menu, selection) -> None:
            if not _selected_pillars(app.viewport.scene):
                return
            menu.addSeparator()
            menu.addAction(
                tr("Modifica pilastro…"),
                lambda: QTimer.singleShot(
                    0, lambda: edit_pillars(app.viewport)))
            if any(pillar_data(g).get("plinto")
                   for g in _selected_pillars(app.viewport.scene)):
                from . import plinti
                menu.addAction(
                    tr("Modifica plinto…"),
                    lambda: QTimer.singleShot(
                        0, lambda: plinti.edit_plinti(app.viewport)))

        add_ctx(context)
    add_kind = getattr(app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
