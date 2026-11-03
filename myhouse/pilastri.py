# SPDX-License-Identifier: GPL-3.0-or-later
"""Plugin Pilastro per IngeTrazo / MyHouse — crea pilastri BIM (IfcColumn).

Uso: MyHouse > Pilastro, scegli forma (rettangolare, quadrato, tondo),
misure, altezza e altezza da terra, poi:
  - clic            posa un pilastro con il centro sul punto cliccato
                    (puoi posarne quanti ne vuoi)
  - Esc o tasto destro   esce dal comando
Doppio clic su un pilastro (strumento Seleziona) o "Modifica pilastro…" nel
menu del tasto destro: cambia forma, misure, altezza, quota, rotazione.

"Altezza da terra" = quota della faccia INFERIORE del pilastro; l'altezza
va verso l'alto.
Altezza legata al piano: con "Altezza fino a" la faccia SUPERIORE del
pilastro arriva alla quota del piano scelto ("Piano successivo" o uno preciso)
+ una distanza, e segue il piano se questo cambia quota.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPen, QVector3D
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QLineEdit, QVBoxLayout,
)

from core import bim
from tools.base import Tool, ToolContext

from . import muri, piani

ORDER = 41
COLUMN_COLOR = (0.78, 0.77, 0.74)
LAYER_NAME = "Pilastri"
KEY = "myhouse_pilastro"        # parametri in group.ext
SEGMENTS = 32                   # lati del pilastro tondo
SHAPES = [("rect", "Rettangolare"), ("square", "Quadrato"), ("round", "Tondo")]


class _Settings:
    shape = "square"
    w = 0.30                    # larghezza (rettangolare / quadrato)
    dp = 0.40                   # profondità (rettangolare)
    dia = 0.35                  # diametro (tondo)
    h = 3.00                    # altezza
    z0 = 0.0                    # altezza da terra (faccia inferiore)
    rot = 0.0                   # rotazione in gradi
    name = "Pilastro"
    level = None                # id del piano (None = nessuno)
    tlv = None                  # altezza legata: "next" o id del piano
    toff = 0.0                  # distanza dalla quota di arrivo


def _params() -> dict:
    return {"shape": _Settings.shape, "w": _Settings.w, "dp": _Settings.dp,
            "dia": _Settings.dia, "h": _Settings.h, "z0": _Settings.z0,
            "rot": _Settings.rot, "name": _Settings.name}


def _store(p: dict) -> None:
    for k in ("shape", "w", "dp", "dia", "h", "z0", "rot", "name"):
        setattr(_Settings, k, p[k])
    _Settings.level = p.get("lv")
    _Settings.tlv = p.get("tlv")
    _Settings.toff = p.get("toff") or 0.0


def _linked_height(scene, level_id, tlv, toff, zb):
    """Altezza che porta la faccia superiore al piano di arrivo, o None."""
    if not tlv:
        return None
    return piani.height_for(scene, tlv, toff, level_id, zb)


# ---------------------------------------------------------------------------
# Geometria pura
# ---------------------------------------------------------------------------

def footprint(d, cx=None, cy=None):
    """Contorno in pianta (antiorario) centrato in (cx, cy)."""
    cx = d["c"][0] if cx is None else cx
    cy = d["c"][1] if cy is None else cy
    if d["shape"] == "round":
        r = d["dia"] / 2
        return [(cx + r * math.cos(2 * math.pi * i / SEGMENTS),
                 cy + r * math.sin(2 * math.pi * i / SEGMENTS))
                for i in range(SEGMENTS)]
    w = d["w"]
    dp = w if d["shape"] == "square" else d["dp"]
    a = math.radians(d.get("rot", 0.0))
    ca, sa = math.cos(a), math.sin(a)
    out = []
    for x, y in ((-w / 2, -dp / 2), (w / 2, -dp / 2),
                 (w / 2, dp / 2), (-w / 2, dp / 2)):
        out.append((cx + x * ca - y * sa, cy + x * sa + y * ca))
    return out


def pillar_mesh(d):
    from core.mesh import Mesh
    P = QVector3D
    pts = footprint(d)
    zb, zt = d["z0"], d["z0"] + d["h"]
    mesh = Mesh()

    def face(q):
        f = mesh.add_face(q)
        # nessun colore predefinito: si applicano i materiali di IngeTrazo
        f.attrs["layer"] = LAYER_NAME

    face([P(*p, zt) for p in pts])                   # sopra
    face([P(*p, zb) for p in reversed(pts)])         # sotto
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        face([P(*pts[i], zb), P(*pts[j], zb), P(*pts[j], zt), P(*pts[i], zt)])
    return mesh


def pillar_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "c" in data else None


def build_pillar(scene, d) -> None:
    from core.group import Group
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    part = Group(pillar_mesh(d), name="Pilastro")
    part.component = False
    g = Group(name=d["name"])
    g.adopt([part])
    g.component = False
    g.layer = LAYER_NAME
    bim.tag_group(g, "IfcColumn", d["name"])
    g.ext = {KEY: d}
    scene.groups.append(g)


def rebuild_pillar(group, p: dict) -> None:
    """Nuove misure, stesso posto."""
    d = dict(pillar_data(group))
    d.update(p)
    for k in [k for k, v in d.items() if v is None]:     # None = togli
        d.pop(k)
    from core.group import Group
    part = Group(pillar_mesh(d), name="Pilastro")
    part.component = False
    group.children = [part]
    group.name = d["name"]
    ext = dict(group.ext or {})
    ext[KEY] = d
    group.ext = ext


# ---------------------------------------------------------------------------
# Dialogo (creazione e modifica)
# ---------------------------------------------------------------------------

def _spin(value, lo, hi):
    s = QDoubleSpinBox()
    s.setDecimals(3)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


def ask_params(parent, cur: dict, title: str, scene=None):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    shape = QComboBox()
    for key, label in SHAPES:
        shape.addItem(label, key)
    shape.setCurrentIndex([k for k, _ in SHAPES].index(cur["shape"]))
    w = _spin(cur["w"], 0.02, 20.0)
    dp = _spin(cur["dp"], 0.02, 20.0)
    dia = _spin(cur["dia"], 0.02, 20.0)
    h = _spin(cur["h"], 0.05, 100.0)
    z0 = _spin(cur["z0"], -100.0, 1000.0)
    rot = _spin(cur["rot"], -360.0, 360.0)
    name = QLineEdit(cur["name"])
    lvl = None
    top_cb = top_off = None
    if scene is not None and piani.levels(scene):
        lvl = piani.level_combo(scene, cur.get("lv"))
    form.addRow("Forma", shape)
    if lvl is not None:
        form.addRow("Piano", lvl)
    form.addRow("Larghezza (m)", w)
    form.addRow("Profondità (m)", dp)
    form.addRow("Diametro (m)", dia)
    form.addRow("Altezza (m)", h)
    if lvl is not None:                 # faccia superiore legata a un piano
        top_cb, top_off = piani.add_top_rows(form, scene, h, cur.get("tlv"),
                                             cur.get("toff", 0.0))
    form.addRow("Altezza da terra / dal piano - faccia inferiore (m)", z0)
    form.addRow("Rotazione (°)", rot)
    form.addRow("Nome", name)
    lay.addLayout(form)

    def sync() -> None:                    # abilita solo i campi che servono
        k = shape.currentData()
        w.setEnabled(k in ("rect", "square"))
        dp.setEnabled(k == "rect")
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
    return {"shape": shape.currentData(), "w": w.value(), "dp": dp.value(),
            "dia": dia.value(), "h": h.value(), "z0": z0.value(),
            "rot": rot.value(), "name": name.text().strip() or "Pilastro",
            "lv": (lvl.currentData() or None) if lvl is not None else None,
            "tlv": (top_cb.currentData() or None) if top_cb is not None
            else None,
            "toff": top_off.value() if top_off is not None else 0.0}


# ---------------------------------------------------------------------------
# Strumento
# ---------------------------------------------------------------------------

class PilastroTool(Tool):
    name = "Pilastro"
    shortcut = None
    description = "Crea pilastri rettangolari, quadrati o tondi."

    def __init__(self) -> None:
        self._entering = False
        self.hover_point: QVector3D | None = None

    def on_activate(self, viewport) -> None:
        self._vp = viewport
        if self._entering:
            self.hover_point = None
            viewport.flash_status(
                "Pilastro: clic per posare il centro · Esc = esci", 6000)
            return
        cur = _params()
        cur["lv"] = piani.active_id(viewport.scene)
        cur["tlv"], cur["toff"] = _Settings.tlv, _Settings.toff
        p = ask_params(viewport.window(), cur, "Pilastro", viewport.scene)
        if p is None:
            return
        _store(p)
        piani.set_active(p.get("lv"))
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def on_deactivate(self, viewport) -> None:
        self.hover_point = None

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
        return key == Qt.Key_Escape

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        return False

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = QVector3D(ctx.world)
        ctx.viewport.update()

    def rubber_band_lines(self):
        if self.hover_point is None:
            return []
        P = QVector3D
        d = {"shape": _Settings.shape, "w": _Settings.w, "dp": _Settings.dp,
             "dia": _Settings.dia, "rot": _Settings.rot}
        pts = footprint(d, self.hover_point.x(), self.hover_point.y())
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
            vp.flash_status("Chiudi il gruppo che stai modificando", 4000)
            return
        d = _params()
        d["c"] = [ctx.world.x(), ctx.world.y()]
        d["z0"], extra = piani.place(vp.scene, _Settings.level, _Settings.z0,
                                     ctx.world.z())   # piano, o punto cliccato
        d.update(extra)
        if _Settings.tlv:               # altezza = fino al piano di arrivo
            hl = _linked_height(vp.scene, _Settings.level, _Settings.tlv,
                                _Settings.toff, d["z0"])
            if hl is None:
                vp.flash_status(
                    "Nessun piano di arrivo: uso l'altezza indicata", 4000)
            else:
                d.update(h=hl, tlv=_Settings.tlv, toff=_Settings.toff)

        def mutate(scene):
            build_pillar(scene, d)
            try:
                muri.update_roof_clips(scene)
            except Exception:
                pass

        vp.history.execute(muri.MuriCommand(mutate))
        vp.notify_scene_changed()
        vp.flash_status("Pilastro creato", 2500)
        vp.update()


# ---------------------------------------------------------------------------
# Modifica di un pilastro esistente
# ---------------------------------------------------------------------------

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
        viewport.flash_status("Chiudi il gruppo che stai modificando", 4000)
        return
    groups = groups or _selected_pillars(scene)
    if not groups:
        viewport.flash_status("Seleziona un pilastro", 3000)
        return
    d0 = pillar_data(groups[0])
    cur = {k: d0[k]
           for k in ("shape", "w", "dp", "dia", "h", "z0", "rot", "name")}
    if d0.get("lv"):
        cur["z0"] = d0.get("off", d0["z0"])       # distanza dal piano
    cur["lv"] = d0.get("lv")
    cur["tlv"], cur["toff"] = d0.get("tlv"), d0.get("toff", 0.0)
    p = ask_params(viewport.window(), cur, "Modifica pilastro", scene)
    if p is None:
        return
    if len(groups) > 1:
        p.pop("name")                       # più pilastri: ognuno tiene il nome

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
            q["tlv"], q["toff"] = None, None            # None = togli
            if tlv:
                hl = _linked_height(sc, q["lv"], tlv, toff, q["z0"])
                if hl is None:
                    failed[0] += 1
                else:
                    q.update(h=hl, tlv=tlv, toff=toff)
            rebuild_pillar(g, q)

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    if failed[0]:
        viewport.flash_status(
            "Nessun piano di arrivo valido (sotto la base?): "
            "uso l'altezza indicata", 6000)
        return
    viewport.flash_status(f"{len(groups)} pilastri aggiornati", 3000)


def _hook_double_click(vp) -> None:
    """Doppio clic su un pilastro = modifica."""
    if getattr(vp, "_myhouse_pilastri_dbl", False):
        return
    original = vp.begin_group_edit

    def begin_group_edit(group, *args, **kwargs):
        g = getattr(group, "owner", None) or group
        if pillar_data(g) is None:
            return original(group, *args, **kwargs)
        from PySide6.QtCore import QTimer
        try:
            vp.scene.select([g])
        except Exception:
            vp.scene.selection.clear()
            vp.scene.selection.add(g)
        vp.update()
        QTimer.singleShot(0, lambda: edit_pillars(vp, [g]))

    vp.begin_group_edit = begin_group_edit
    vp._myhouse_pilastri_dbl = True


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
    from core.units import fmt_len
    if d["shape"] == "round":
        size = f"Ø {fmt_len(d['dia'])}"
    elif d["shape"] == "square":
        size = f"{fmt_len(d['w'])} × {fmt_len(d['w'])}"
    else:
        size = f"{fmt_len(d['w'])} × {fmt_len(d['dp'])}"
    return {"type": "Pilastro",
            "props": [("Sezione", size), ("Altezza", fmt_len(d["h"])),
                      ("Altezza da terra", fmt_len(d["z0"]))]
            + piani.level_props(d) + muri.top_props(d)}


def _register_level_kind() -> None:
    def zset(d, z):
        d["z0"] = z

    def hset(d, h):                      # il piano cambia quota: nuova altezza
        d["h"] = h

    piani.register_kind("pilastro", KEY, pillar_data, lambda d: d["z0"],
                        zset, rebuild_pillar, lambda d: d["h"], hset)


def register(api) -> None:
    _register_level_kind()
    api.add_button("Pilastro", "Crea un pilastro (rettangolare, quadrato, tondo)",
                   _icon(), api.run_tool(PilastroTool()))
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
                "Modifica pilastro…",
                lambda: QTimer.singleShot(
                    0, lambda: edit_pillars(app.viewport)))

        add_ctx(context)
    add_kind = getattr(app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
