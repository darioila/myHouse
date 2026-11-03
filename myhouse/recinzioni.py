# SPDX-License-Identifier: GPL-3.0-or-later
"""Plugin Recinzione per IngeTrazo / MyHouse — crea recinzioni (IfcRailing).

Uso: MyHouse > Recinzione, scegli il tipo e le misure, poi come per la
balaustra: clic sui punti della polilinea · O/F8 ortogonale · Invio conclude ·
C chiude · Backspace toglie l'ultimo punto · Esc o tasto destro esce.

Tipi:
  - Doghe orizzontali: pali quadri con cappello e doghe piatte tra i pali.
  - Ferro battuto: barre verticali con punta a lancia, due traversi (basso e
    alto) e pali più grossi ogni "passo" metri.

Come la balaustra, ogni punto prende la quota del punto cliccato: su un
terreno inclinato la recinzione segue i punti.
"""
from __future__ import annotations

import copy
import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPen, QVector3D
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
    QVBoxLayout,
)

from core import bim
from tools.base import Tool, ToolContext

from . import balaustre as bal
from . import muri, piani

ORDER = 81
COLOR = (0.24, 0.25, 0.27)
LAYER_NAME = "Recinzioni"
KEY = "myhouse_recinzione"      # parametri in group.ext
TOP_GAP = 0.05                  # doghe: spazio tra ultima doga e cima palo
CAP = 0.02                      # doghe: spessore del cappello dei pali

KINDS = (("doghe", "Doghe orizzontali"), ("ferro", "Ferro battuto"))


class _S:
    kind = "doghe"
    h = 1.80                    # altezza totale
    post = 2.00                 # passo dei pali
    sz = 0.08                   # sezione pali
    bot = 0.05                  # distanza da terra (doghe / barre)
    # doghe
    dh = 0.14                   # altezza doga
    dg = 0.02                   # spazio tra doghe
    dt = 0.025                  # spessore doga
    # ferro battuto
    gap = 0.12                  # spazio tra le barre
    bt = 0.02                   # sezione barre
    spear = 0.10                # altezza della punta
    rl = 0.20                   # traverso basso: distanza da terra
    ru = 0.20                   # traverso alto: distanza dalla cima delle barre
    rt = 0.03                   # altezza dei traversi
    name = "Recinzione"
    level = None


# ---------------------------------------------------------------------------
# Geometria
# ---------------------------------------------------------------------------

def _polys(mesh, polys, centre, attrs):
    """Aggiunge poligoni orientati verso l'esterno rispetto a centre."""
    P = QVector3D
    for vs in polys:
        nrm = (0.0, 0.0, 0.0)
        for i in range(len(vs)):
            c1, c2 = vs[i], vs[(i + 1) % len(vs)]
            nrm = bal._add(nrm, ((c1[1] - c2[1]) * (c1[2] + c2[2]),
                                 (c1[2] - c2[2]) * (c1[0] + c2[0]),
                                 (c1[0] - c2[0]) * (c1[1] + c2[1])))
        fc = (0.0, 0.0, 0.0)
        for v in vs:
            fc = bal._add(fc, v)
        fc = bal._mul(fc, 1.0 / len(vs))
        if bal._dot(nrm, bal._sub(fc, centre)) < 0:
            vs = list(reversed(vs))
        f = mesh.add_face([P(*v) for v in vs])
        if attrs:
            f.attrs.update(copy.deepcopy(attrs))
        f.attrs["layer"] = LAYER_NAME


def _tube(mesh, p0, p1, n, hn, hw, attrs, m0=None, m1=None):
    """Tubolare a sezione rettangolare lungo p0->p1 (n = direzione orizzontale
    della sezione, hn/hw = metà dimensioni). m0/m1 = normale del piano di
    mitra agli estremi (spigoli), altrimenti taglio dritto."""
    a = bal._unit(bal._sub(p1, p0))
    w = bal._unit(bal._cross(a, n))
    sec = [(-hn, -hw), (hn, -hw), (hn, hw), (-hn, hw)]

    def ring(q, m):
        pts = []
        for dn, dw in sec:
            off = bal._add(bal._mul(n, dn), bal._mul(w, dw))
            if m:
                off = bal._add(off, bal._mul(a, -bal._dot(off, m)
                                              / bal._dot(a, m)))
            pts.append(bal._add(q, off))
        return pts

    r0, r1 = ring(p0, m0), ring(p1, m1)
    polys = [list(reversed(r0)), r1]
    for i in range(4):
        j = (i + 1) % 4
        polys.append([r0[i], r0[j], r1[j], r1[i]])
    _polys(mesh, polys, bal._mul(bal._add(p0, p1), 0.5), attrs)


def _spear(mesh, x, y, z0, u, hb, w, length, attrs):
    """Punta a lancia (piramide che si allarga e poi si stringe)."""
    n = (-u[1], u[0], 0.0)

    def ring(z, h):
        return [(x + u[0] * dx + n[0] * dn, y + u[1] * dx + n[1] * dn, z)
                for dx, dn in ((-h, -h), (h, -h), (h, h), (-h, h))]

    A, B = ring(z0, hb), ring(z0 + 0.22 * length, max(w / 2, hb))
    apex = (x, y, z0 + length)
    polys = []
    for i in range(4):
        j = (i + 1) % 4
        polys.append([A[i], A[j], B[j], B[i]])
        polys.append([B[i], B[j], apex])
    _polys(mesh, polys, (x, y, z0 + 0.4 * length), attrs)


def layout(d):
    """Pali e barre: liste di (x, y, z_terra, u) con u = direzione del lato."""
    segs = bal.segments(d)
    ferro = d["kind"] == "ferro"
    post = max(0.3, d["post"])
    posts, bars, seen = [], [], set()
    for seg in segs:
        a, b, u, lp = seg["a"], seg["b"], seg["u"], seg["lp"]

        def pt(s):
            return (a[0] + u[0] * s, a[1] + u[1] * s,
                    a[2] + (b[2] - a[2]) * s / lp)

        mp = max(1, round(lp / post))
        if ferro:
            m = max(1, math.ceil(lp / (d["gap"] + d["bt"]) - 1e-9))
            mp = min(mp, m)
            idx = {round(i * m / mp) for i in range(mp + 1)}
            steps = [(k, lp * k / m, k in idx) for k in range(m + 1)]
        else:
            steps = [(i, lp * i / mp, True) for i in range(mp + 1)]
        for _k, s, is_post in steps:
            x, y, zb = pt(s)
            key = (round(x, 3), round(y, 3))
            if key in seen:
                continue
            seen.add(key)
            (posts if is_post else bars).append((x, y, zb, u))
    return segs, posts, bars


def fence_mesh(d):
    from core.mesh import Mesh
    mesh = Mesh()
    segs, posts, bars = layout(d)
    ma = bal._mat_attrs(d.get("mat"))
    mb = bal._mat_attrs(d.get("mat2")) or ma
    h, sz = d["h"], d["sz"]
    ferro = d["kind"] == "ferro"
    body = h - (d["spear"] if ferro else 0.0)       # cima del corpo

    for x, y, zb, u in posts:
        n = (-u[1], u[0], 0.0)
        if ferro:
            _tube(mesh, (x, y, zb), (x, y, zb + body), n, sz / 2, sz / 2, ma)
            _spear(mesh, x, y, zb + body, u, sz / 2, sz * 1.4, sz * 1.2, ma)
        else:
            _tube(mesh, (x, y, zb), (x, y, zb + h), n, sz / 2, sz / 2, ma)
            c = sz / 2 + CAP / 2
            _tube(mesh, (x, y, zb + h), (x, y, zb + h + CAP), n, c, c, ma)

    if ferro:
        bt = d["bt"]
        for x, y, zb, u in bars:
            n = (-u[1], u[0], 0.0)
            _tube(mesh, (x, y, zb + d["bot"]), (x, y, zb + body), n,
                  bt / 2, bt / 2, mb)
            _spear(mesh, x, y, zb + body, u, bt / 2, max(3 * bt, 0.05),
                   d["spear"], mb)
        rt = d["rt"]
        for seg, (c0, c1) in zip(segs, bal._miters(segs, d)):
            a, b, u = seg["a"], seg["b"], seg["u"]
            n = (-u[1], u[0], 0.0)
            for off in (d["rl"], body - d["ru"]):
                _tube(mesh, (a[0], a[1], a[2] + off),
                      (b[0], b[1], b[2] + off), n, rt * 0.4, rt / 2, ma,
                      c0, c1)
        return mesh

    # doghe orizzontali tra i pali
    z0, z1 = d["bot"], h - TOP_GAP
    if z1 - z0 < 0.03:
        return mesh
    dg = d["dg"]
    k = max(1, int((z1 - z0 + dg) / (d["dh"] + dg) + 1e-9))
    dh = ((z1 - z0) - (k - 1) * dg) / k
    post_d = max(0.3, d["post"])
    for seg in segs:
        a, b, u, lp = seg["a"], seg["b"], seg["u"], seg["lp"]
        n = (-u[1], u[0], 0.0)
        mp = max(1, round(lp / post_d))
        for i in range(mp):
            s0 = lp * i / mp + sz / 2
            s1 = lp * (i + 1) / mp - sz / 2
            if s1 - s0 < 0.02:
                continue
            q = []
            for s in (s0, s1):
                q.append((a[0] + u[0] * s, a[1] + u[1] * s,
                          a[2] + (b[2] - a[2]) * s / lp))
            for j in range(k):
                zc = z0 + j * (dh + dg) + dh / 2
                _tube(mesh, (q[0][0], q[0][1], q[0][2] + zc),
                      (q[1][0], q[1][1], q[1][2] + zc), n,
                      d["dt"] / 2, dh / 2, mb)
    return mesh


def fence_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "pts" in data else None


def rebuild_fence(group, d) -> None:
    from core.group import Group
    part = Group(fence_mesh(d), name="Recinzione")
    part.component = False
    group.children = [part]
    ext = dict(group.ext or {})
    ext[KEY] = dict(d)
    group.ext = ext


def build_fence(scene, d, name) -> None:
    from core.group import Group
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    part = Group(fence_mesh(d), name="Recinzione")
    part.component = False
    g = Group(name=name)
    g.adopt([part])
    g.component = False
    g.layer = LAYER_NAME
    bim.tag_group(g, "IfcRailing", name)
    g.ext = {KEY: d}
    scene.groups.append(g)


# ---------------------------------------------------------------------------
# Impostazioni
# ---------------------------------------------------------------------------

def ask_settings(parent, scene=None) -> bool:
    dlg = QDialog(parent)
    dlg.setWindowTitle("Recinzione")
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    kind = QComboBox()
    for key, label in KINDS:
        kind.addItem(label, key)
    kind.setCurrentIndex(max(0, kind.findData(_S.kind)))
    sp = bal._spin
    h = sp(_S.h, 0.3, 6.0)
    post = sp(_S.post, 0.3, 10.0)
    sz = sp(_S.sz, 0.02, 0.5)
    bot = sp(_S.bot, 0.0, 1.0)
    dh = sp(_S.dh, 0.02, 0.6)
    dg = sp(_S.dg, 0.0, 0.3)
    dt = sp(_S.dt, 0.005, 0.3)
    gap = sp(_S.gap, 0.02, 1.0)
    bt = sp(_S.bt, 0.005, 0.1)
    spear = sp(_S.spear, 0.0, 0.4)
    rl = sp(_S.rl, 0.0, 2.0)
    ru = sp(_S.ru, 0.0, 2.0)
    rt = sp(_S.rt, 0.01, 0.2)
    name = QLineEdit(_S.name)
    ortho = QCheckBox("Ortogonale (O / F8 durante il disegno)")
    ortho.setChecked(bal._Settings.ortho)
    lvl = None
    if scene is not None and piani.levels(scene):
        lvl = piani.level_combo(scene, piani.active_id(scene))
        form.addRow("Piano (la quota resta quella dei punti cliccati)", lvl)
    form.addRow("Tipo di recinzione", kind)
    form.addRow("Altezza totale (m)", h)
    form.addRow("Passo dei pali (m)", post)
    form.addRow("Sezione pali (m)", sz)
    form.addRow("Distanza da terra (m)", bot)
    rows_d = [("Altezza doga (m)", dh), ("Spazio tra le doghe (m)", dg),
              ("Spessore doga (m)", dt)]
    rows_f = [("Spazio tra le barre (m)", gap), ("Sezione barre (m)", bt),
              ("Altezza punta (m)", spear),
              ("Traverso basso: distanza da terra (m)", rl),
              ("Traverso alto: sotto la cima delle barre (m)", ru),
              ("Altezza traversi (m)", rt)]
    for lab, w in rows_d + rows_f:
        form.addRow(lab, w)
    form.addRow("Nome", name)
    form.addRow(ortho)

    def sync(_i=0) -> None:
        doghe = kind.currentData() == "doghe"
        for _l, w in rows_d:
            w.setEnabled(doghe)
        for _l, w in rows_f:
            w.setEnabled(not doghe)
    kind.currentIndexChanged.connect(sync)
    sync()
    lay.addLayout(form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return False
    _S.kind = kind.currentData()
    for attr, w in (("h", h), ("post", post), ("sz", sz), ("bot", bot),
                    ("dh", dh), ("dg", dg), ("dt", dt), ("gap", gap),
                    ("bt", bt), ("spear", spear), ("rl", rl), ("ru", ru),
                    ("rt", rt)):
        setattr(_S, attr, w.value())
    _S.name = name.text().strip() or "Recinzione"
    bal._Settings.ortho = ortho.isChecked()
    _S.level = (lvl.currentData() or None) if lvl is not None else None
    if lvl is not None:
        piani.set_active(_S.level)
    return True


# ---------------------------------------------------------------------------
# Strumento (stessi comandi della balaustra)
# ---------------------------------------------------------------------------

class RecinzioneTool(bal.BalaustraTool):
    name = "Recinzione"
    shortcut = None
    description = "Crea una recinzione: clic sui punti della polilinea."

    def on_activate(self, viewport) -> None:
        if self._entering:
            self._reset()
            viewport.flash_status(
                "Recinzione: clic sui punti · O/F8 = ortogonale · "
                "Invio = concludi · C = chiudi · Esc = esci", 7000)
            return
        if not ask_settings(viewport.window(), viewport.scene):
            return
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def _dict(self, pts):
        return {"pts": [list(p) for p in pts], "kind": _S.kind, "h": _S.h,
                "post": _S.post, "sz": _S.sz, "bot": _S.bot, "dh": _S.dh,
                "dg": _S.dg, "dt": _S.dt, "gap": _S.gap, "bt": _S.bt,
                "spear": _S.spear, "rl": _S.rl, "ru": _S.ru, "rt": _S.rt}

    def _commit(self, viewport) -> None:
        d = self._dict(self.points)
        if not bal.segments(d):
            viewport.flash_status("Servono almeno 2 punti distinti", 3000)
            return
        name = _S.name
        lv = piani.get(viewport.scene, _S.level)
        if lv:
            d.update({"lv": lv["id"], "lvn": lv["name"],
                      "off": min(p[2] for p in d["pts"]) - lv["z"]})

        def mutate(scene):
            build_fence(scene, d, name)

        viewport.history.execute(muri.MuriCommand(mutate))
        viewport.notify_scene_changed()
        _s, posts, bars = layout(d)
        viewport.flash_status(
            f"Recinzione creata · {len(posts)} pali, {len(bars)} barre", 3500)
        self._reset()
        viewport.update()

    def rubber_band_lines(self):
        pts = list(self.points)
        if self.hover is not None and pts:
            pts.append((self.hover.x(), self.hover.y(), self.hover.z()))
        if len(pts) < 2:
            return []
        d = self._dict(pts)
        P = QVector3D
        segs, posts, bars = layout(d)
        lines = []
        for seg in segs:
            a, b = seg["a"], seg["b"]
            lines.append((P(a[0], a[1], a[2] + d["h"]),
                          P(b[0], b[1], b[2] + d["h"])))
            lines.append((P(*a), P(*b)))
        for x, y, zb, _u in posts + bars:
            lines.append((P(x, y, zb), P(x, y, zb + d["h"])))
        return lines


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
    p.setBrush(QColor(90, 92, 98))
    p.drawRect(4, 14, 40, 3)
    p.drawRect(4, 32, 40, 3)
    for x in (6, 14, 22, 30, 38):
        p.drawLine(x + 2, 12, x + 2, 42)
        p.drawLine(x + 2, 6, x, 12)
        p.drawLine(x + 2, 6, x + 4, 12)
    p.end()
    return QIcon(pm)


def _selected_fences(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and fence_data(g) is not None and g not in out:
            out.append(g)
    return out


def set_fence_material(viewport) -> None:
    scene = viewport.scene
    sel = _selected_fences(scene)
    if not sel:
        viewport.flash_status("Seleziona una recinzione", 3000)
        return
    d0 = fence_data(sel[0])
    keys = [[list(p) for p in fence_data(g)["pts"]] for g in sel]
    ferro = d0.get("kind") == "ferro"
    extra = [("mat2", "Materiale barre" if ferro else "Materiale doghe",
              d0.get("mat2"))]
    res = bal._ask_material(viewport, d0.get("mat"), "Materiale pali e "
                            + ("traversi" if ferro else "cappelli"), extra)
    if res is None:
        return

    def mutate(sc):
        for gg in sc.groups:
            dd = fence_data(gg)
            if dd is not None and [list(p) for p in dd["pts"]] in keys:
                nd = copy.deepcopy(dd)
                for k, v in res.items():
                    if v:
                        nd[k] = v
                    else:
                        nd.pop(k, None)
                rebuild_fence(gg, nd)

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status("Materiale applicato", 3000)


def _outliner_kind(group):
    d = fence_data(group)
    if d is None:
        return None
    from core.units import fmt_len
    length = 0.0
    for seg in bal.segments(d):
        a, b = seg["a"], seg["b"]
        length += math.sqrt(sum((b[i] - a[i]) ** 2 for i in range(3)))
    _s, posts, bars = layout(d)
    props = [("Tipo", dict(KINDS).get(d["kind"], d["kind"])),
             ("Altezza", fmt_len(d["h"])),
             ("Lunghezza", fmt_len(length)),
             ("Pali", str(len(posts)))]
    if d["kind"] == "ferro":
        props.append(("Barre", str(len(bars))))
    return {"type": "Recinzione", "props": props + piani.level_props(d)}


def _register_level_kind() -> None:
    def zget(d):
        return min(p[2] for p in d["pts"])

    def zset(d, z):
        delta = z - zget(d)
        d["pts"] = [[p[0], p[1], p[2] + delta] for p in d["pts"]]

    piani.register_kind("recinzione", KEY, fence_data, zget, zset,
                        rebuild_fence)


def register(api) -> None:
    bal._APP["app"] = api.app
    _register_level_kind()
    add_ctx = getattr(api.app, "add_context_menu", None)
    if add_ctx is not None:
        def context(menu, selection) -> None:
            if not _selected_fences(api.app.viewport.scene):
                return
            menu.addSeparator()
            menu.addAction(
                "Materiale recinzione…",
                lambda: QTimer.singleShot(
                    0, lambda: set_fence_material(api.app.viewport)))

        add_ctx(context)
    api.add_button("Recinzione", "Crea una recinzione (doghe o ferro battuto)",
                   _icon(), api.run_tool(RecinzioneTool()))
    add_kind = getattr(api.app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
