# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr
from ._imperial import FT, IN, dflt
from ._scroll import scroll_form

import copy
import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPen, QVector3D
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
    QVBoxLayout,
)

from core import bim
from . import _ifc
from tools.base import Tool, ToolContext

from . import balaustre as bal
from . import _tipi, muri, piani

ORDER = 81
COLOR = (0.24, 0.25, 0.27)
POST_COLOR = (0.24, 0.25, 0.27)
POST_NAME = tr("pali recinzione")
BAR_COLOR = (0.15, 0.15, 0.17)
BAR_NAME = tr("barre recinzione")
SLAT_COLOR = (0.60, 0.42, 0.26)
SLAT_NAME = tr("doghe recinzione")
WALL_COLOR = (0.86, 0.84, 0.79)
WALL_NAME = tr("muretto recinzione")
WCAP = 0.04
WCAP_OVER = 0.03
LAYER_NAME = "Recinzioni"
KEY = "myhouse_recinzione"
TOP_GAP = 0.05
CAP = 0.02

KINDS = (("doghe", tr("Doghe orizzontali")), ("ferro", tr("Ferro battuto")))


def _norm(d):
    if d.get("kind") == "muretto":
        d = dict(d)
        d["kind"], d["wall"] = "ferro", True
    return d


class _S:
    kind = "doghe"
    h = dflt(6 * FT, 1.80)
    post = dflt(8 * FT, 2.00)
    sz = dflt(3.5 * IN, 0.08)
    bot = dflt(2 * IN, 0.05)
    dh = dflt(5.5 * IN, 0.14)
    dg = dflt(0.75 * IN, 0.02)
    dt = dflt(1 * IN, 0.025)
    gap = dflt(4 * IN, 0.12)
    bt = dflt(0.75 * IN, 0.02)
    spear = dflt(4 * IN, 0.10)
    rl = dflt(8 * IN, 0.20)
    ru = dflt(8 * IN, 0.20)
    rt = dflt(1.25 * IN, 0.03)
    wall = False
    mh = 0.60
    mt = 0.20
    name = tr("Recinzione")
    level = None
    tipo_id = None
    tipo_nome = None


def _polys(mesh, polys, centre, attrs):
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


def _inset(segs, d):
    if not d.get("wall") or not segs:
        return segs
    ins = max(0.0, d.get("sz", 0.08)) / 2 + 0.02

    def same(p, q):
        return all(abs(p[i] - q[i]) < 1e-6 for i in range(3))

    if len(segs) >= 3 and same(segs[-1]["b"], segs[0]["a"]):
        return segs
    out = [dict(s) for s in segs]
    first, last = out[0], out[-1]
    s0 = first
    if first is last and first["lp"] < 2 * ins + 0.1:
        return segs
    if first["lp"] > ins + 0.05:
        a, b, u, lp = first["a"], first["b"], first["u"], first["lp"]
        k = ins / lp
        first["a"] = (a[0] + u[0] * ins, a[1] + u[1] * ins,
                      a[2] + (b[2] - a[2]) * k)
        first["lp"] = lp - ins
    if last["lp"] > ins + 0.05:
        a, b, u, lp = last["a"], last["b"], last["u"], last["lp"]
        k = ins / lp
        last["b"] = (b[0] - u[0] * ins, b[1] - u[1] * ins,
                     b[2] - (b[2] - a[2]) * k)
        last["lp"] = lp - ins
    del s0
    return out


def layout(d):
    segs = bal.segments(d)
    d = _norm(d)
    full = segs
    segs = _inset(segs, d)
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
    return full, posts, bars


def fence_mesh(d):
    from core.mesh import Mesh
    mesh = Mesh()
    d = _norm(d)
    segs, posts, bars = layout(d)
    fsegs = _inset(segs, d)
    ma = bal._mat_attrs(d.get("mat")) or {
        "color": POST_COLOR, "mat": POST_NAME}
    ferro = d["kind"] == "ferro"
    muretto = bool(d.get("wall"))
    mb = bal._mat_attrs(d.get("mat2")) or (
        {"color": BAR_COLOR, "mat": BAR_NAME} if ferro
        else {"color": SLAT_COLOR, "mat": SLAT_NAME})
    h, sz = d["h"], d["sz"]
    body = h - (d["spear"] if ferro else 0.0)
    mh = 0.0
    if muretto:
        mh = max(WCAP + 0.05, min(d.get("mh", 0.60), body - 0.2))
        mw = bal._mat_attrs(d.get("mat3")) or {
            "color": WALL_COLOR, "mat": WALL_NAME}
        mt = max(0.05, d.get("mt", 0.20))
        for seg, (c0, c1) in zip(segs, bal._miters(segs, d)):
            a, b, u = seg["a"], seg["b"], seg["u"]
            n = (-u[1], u[0], 0.0)
            zc = (mh - WCAP) / 2
            _tube(mesh, (a[0], a[1], a[2] + zc), (b[0], b[1], b[2] + zc),
                  n, mt / 2, zc, mw, c0, c1)
            zk = mh - WCAP / 2
            _tube(mesh, (a[0], a[1], a[2] + zk), (b[0], b[1], b[2] + zk),
                  n, mt / 2 + WCAP_OVER, WCAP / 2, mw, c0, c1)

    for x, y, zb, u in posts:
        n = (-u[1], u[0], 0.0)
        if ferro:
            _tube(mesh, (x, y, zb + mh), (x, y, zb + body), n, sz / 2,
                  sz / 2, ma)
            _spear(mesh, x, y, zb + body, u, sz / 2, sz * 1.4, sz * 1.2, ma)
        else:
            _tube(mesh, (x, y, zb + mh), (x, y, zb + h), n, sz / 2, sz / 2,
                  ma)
            c = sz / 2 + CAP / 2
            _tube(mesh, (x, y, zb + h), (x, y, zb + h + CAP), n, c, c, ma)

    if ferro:
        bt = d["bt"]
        for x, y, zb, u in bars:
            n = (-u[1], u[0], 0.0)
            _tube(mesh, (x, y, zb + mh + d["bot"]), (x, y, zb + body), n,
                  bt / 2, bt / 2, mb)
            _spear(mesh, x, y, zb + body, u, bt / 2, max(3 * bt, 0.05),
                   d["spear"], mb)
        rt = d["rt"]
        for seg, (c0, c1) in zip(fsegs, bal._miters(fsegs, d)):
            a, b, u = seg["a"], seg["b"], seg["u"]
            n = (-u[1], u[0], 0.0)
            for off in (mh + d["rl"], body - d["ru"]):
                _tube(mesh, (a[0], a[1], a[2] + off),
                      (b[0], b[1], b[2] + off), n, rt * 0.4, rt / 2, ma,
                      c0, c1)
        return mesh

    z0, z1 = mh + d["bot"], h - TOP_GAP
    if z1 - z0 < 0.03:
        return mesh
    dg = d["dg"]
    k = max(1, int((z1 - z0 + dg) / (d["dh"] + dg) + 1e-9))
    dh = ((z1 - z0) - (k - 1) * dg) / k
    post_d = max(0.3, d["post"])
    for seg in fsegs:
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
    part = Group(fence_mesh(d), name=tr("Recinzione"))
    part.component = False
    group.children = [part]
    _ifc.tag(group, "IfcRailing")
    ext = dict(group.ext or {})
    ext[KEY] = dict(d)
    group.ext = ext


def build_fence(scene, d, name) -> None:
    from core.group import Group
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    part = Group(fence_mesh(d), name=tr("Recinzione"))
    part.component = False
    g = Group(name=name)
    g.adopt([part])
    g.component = False
    g.layer = LAYER_NAME
    _ifc.tag(g, "IfcRailing", name)
    g.ext = {KEY: d}
    scene.groups.append(g)


def _disegno_recinzione(p):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPen, QPolygonF
    r, t, dim, ext = muri._r, muri._t, muri._dim, muri._ext
    p.setPen(QPen(muri._C_LINEA, 1.5))
    p.drawLine(QPointF(10, 150), QPointF(250, 150))
    muri._hatch(p, 10, 150, 250, 154)
    r(p, 20, 25, 30, 150, muri._C_CORPO)
    r(p, 205, 25, 215, 150, muri._C_CORPO)
    r(p, 18, 22, 32, 25, muri._C_ZOCC if hasattr(muri, "_C_ZOCC") else muri._C_LINEA)
    r(p, 203, 22, 217, 25, muri._C_LINEA)
    for k in range(6):
        r(p, 30, 122 - 16 * k, 205, 134 - 16 * k, muri._C_LEGNO)
    dim(p, 10, 22, 10, 150, "H", -1)
    dim(p, 60, 134, 60, 150, "b", 1)
    dim(p, 25, 12, 210, 12, "i", 1)
    dim(p, 20, 166, 30, 166, "s", 1)
    dim(p, 222, 106, 222, 118, "d", -1)
    dim(p, 222, 102, 222, 106, "g", 1)
    r(p, 238, 106, 244, 118, muri._C_LEGNO)
    dim(p, 238, 102, 244, 102, "t", 1)
    t(p, 70, 166, tr("Doghe orizzontali"), size=8)
    p.setPen(QPen(muri._C_LINEA, 1.5))
    p.drawLine(QPointF(268, 150), QPointF(478, 150))
    muri._hatch(p, 268, 150, 478, 154)
    r(p, 300, 28, 308, 150, muri._C_CORPO)
    r(p, 466, 28, 474, 150, muri._C_CORPO)
    for k in range(5):
        x = 330 + 30 * k
        r(p, x, 45, x + 3, 150, muri._C_CORPO)
        p.setPen(QPen(muri._C_LINEA, 1))
        p.setBrush(muri._C_CORPO)
        p.drawPolygon(QPolygonF([QPointF(x - 2, 45), QPointF(x + 1.5, 30), QPointF(x + 5, 45)]))
    r(p, 308, 118, 466, 124, muri._C_LEGNO)
    r(p, 308, 58, 466, 64, muri._C_LEGNO)
    dim(p, 280, 28, 280, 150, "H", -1)
    dim(p, 305, 12, 470, 12, "i", 1)
    dim(p, 338, 30, 338, 45, "pt", 1)
    dim(p, 368, 45, 368, 58, "r2", 1)
    dim(p, 398, 118, 398, 124, "rt", 1)
    dim(p, 428, 124, 428, 150, "r1", 1)
    dim(p, 331, 90, 361, 90, "g", 1)
    dim(p, 330, 140, 333, 140, "q", 1)
    t(p, 350, 166, tr("Ferro battuto"), size=8)


def ask_settings(parent, scene=None) -> bool:
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("Recinzione"))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(muri._Schema(_disegno_recinzione))
    kind = QComboBox()
    for key, label in KINDS:
        kind.addItem(label, key)
    kind.setCurrentIndex(max(0, kind.findData(_S.kind)))
    wall = QCheckBox(tr("Su muretto (sotto la recinzione)"))
    wall.setChecked(bool(_S.wall))
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
    mh = sp(_S.mh, 0.10, 3.0)
    mt = sp(_S.mt, 0.05, 1.0)
    name = QLineEdit(_S.name)
    ortho = QCheckBox(tr("Ortogonale (O / F8 durante il disegno)"))
    ortho.setChecked(bal._Settings.ortho)
    lvl = None
    if scene is not None and piani.levels(scene):
        lvl = piani.level_combo(scene, piani.active_id(scene))
        form.addRow(tr("Piano (la quota resta quella dei punti cliccati)"), lvl)
    form.addRow(tr("Tipo di recinzione"), kind)
    form.addRow(wall)
    form.addRow(tr("Altezza totale (H) (m)"), h)
    form.addRow(tr("Passo dei pali (i) (m)"), post)
    form.addRow(tr("Sezione pali (s) (m)"), sz)
    form.addRow(tr("Distanza da terra (b) (m)"), bot)
    rows_d = [(tr("Altezza doga (d) (m)"), dh), (tr("Spazio tra le doghe (g) (m)"), dg),
              (tr("Spessore doga (t) (m)"), dt)]
    rows_f = [(tr("Spazio tra le barre (g) (m)"), gap), (tr("Sezione barre (q) (m)"), bt),
              (tr("Altezza punta (pt) (m)"), spear),
              (tr("Traverso basso: distanza da terra (r1) (m)"), rl),
              (tr("Traverso alto: sotto la cima delle barre (r2) (m)"), ru),
              (tr("Altezza traversi (rt) (m)"), rt)]
    rows_m = [(tr("Muretto: altezza con cappello (m)"), mh),
              (tr("Muretto: spessore (m)"), mt)]
    for lab, w in rows_d + rows_f + rows_m:
        form.addRow(lab, w)
    form.addRow(tr("Nome"), name)
    form.addRow(ortho)
    _get, _set = _tipi.widgets_io(
        {"kind": kind, "wall": wall, "h": h, "post": post, "sz": sz,
         "bot": bot, "dh": dh, "dg": dg, "dt": dt, "gap": gap, "bt": bt,
         "spear": spear, "rl": rl, "ru": ru, "rt": rt, "mh": mh, "mt": mt})
    tbar = _tipi.TypeBar(dlg, form, "recinzione", {"tipo_id": _S.tipo_id},
                         _get, _set, scene, creating=True)

    def sync(_i=0) -> None:
        k = kind.currentData()
        for _l, w in rows_d:
            w.setEnabled(k == "doghe")
        for _l, w in rows_f:
            w.setEnabled(k == "ferro")
        for _l, w in rows_m:
            w.setEnabled(wall.isChecked())
    kind.currentIndexChanged.connect(sync)
    wall.toggled.connect(sync)
    sync()
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return False
    _S.kind = kind.currentData()
    _S.wall = wall.isChecked()
    for attr, w in (("h", h), ("post", post), ("sz", sz), ("bot", bot),
                    ("dh", dh), ("dg", dg), ("dt", dt), ("gap", gap),
                    ("bt", bt), ("spear", spear), ("rl", rl), ("ru", ru),
                    ("rt", rt), ("mh", mh), ("mt", mt)):
        setattr(_S, attr, w.value())
    _S.name = name.text().strip() or tr("Recinzione")
    bal._Settings.ortho = ortho.isChecked()
    _S.level = (lvl.currentData() or None) if lvl is not None else None
    if lvl is not None:
        piani.set_active(_S.level)
    r = tbar.result(_get())
    _S.tipo_id, _S.tipo_nome = r.get("tipo_id"), r.get("tipo_nome")
    return True


class RecinzioneTool(bal.BalaustraTool):
    name = tr("Recinzione")
    shortcut = None
    description = tr("Crea una recinzione: clic sui punti della polilinea.")

    def on_activate(self, viewport) -> None:
        if self._entering:
            self._reset()
            viewport.flash_status(
                tr("Recinzione: clic sui punti · O/F8 = ortogonale · "
                "Invio = concludi · C = chiudi · Esc = esci"), 7000)
            return
        if not ask_settings(viewport.window(), viewport.scene):
            return
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def _dict(self, pts):
        return {"pts": [list(p) for p in pts], "kind": _S.kind, "wall": _S.wall,
                "h": _S.h,
                "post": _S.post, "sz": _S.sz, "bot": _S.bot, "dh": _S.dh,
                "dg": _S.dg, "dt": _S.dt, "gap": _S.gap, "bt": _S.bt,
                "spear": _S.spear, "rl": _S.rl, "ru": _S.ru, "rt": _S.rt,
                "mh": _S.mh, "mt": _S.mt,
                **({"tipo_id": _S.tipo_id, "tipo_nome": _S.tipo_nome}
                   if _S.tipo_id else {})}

    def _commit(self, viewport) -> None:
        d = self._dict(self.points)
        if not bal.segments(d):
            viewport.flash_status(tr("Servono almeno 2 punti distinti"), 3000)
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
            tr("Recinzione creata · {0} pali, {1} barre").format(len(posts), len(bars)), 3500)
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
        viewport.flash_status(tr("Seleziona una recinzione"), 3000)
        return
    d0 = fence_data(sel[0])
    keys = [[list(p) for p in fence_data(g)["pts"]] for g in sel]
    d0 = _norm(d0)
    ferro = d0.get("kind") == "ferro"
    extra = [("mat2", tr("Materiale barre") if ferro else tr("Materiale doghe"),
              d0.get("mat2"))]
    if d0.get("wall"):
        extra.append(("mat3", tr("Materiale muretto"), d0.get("mat3")))
    res = bal._ask_material(viewport, d0.get("mat"), tr("Materiale pali e ")
                            + (tr("traversi") if ferro else tr("cappelli")), extra)
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
    viewport.flash_status(tr("Materiale applicato"), 3000)


def edit_fences(viewport, groups=None) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    groups = [g for g in (groups or _selected_fences(scene))
              if fence_data(g) is not None]
    if not groups:
        viewport.flash_status(tr("Seleziona una recinzione"), 3000)
        return
    first = _norm(fence_data(groups[0]))
    num = ("h", "post", "sz", "bot", "dh", "dg", "dt", "gap", "bt", "spear",
           "rl", "ru", "rt", "mh", "mt")
    init = {k: first.get(k, getattr(_S, k)) for k in num}
    init["kind"] = first.get("kind", _S.kind)
    init["wall"] = bool(first.get("wall", False))
    dlg = QDialog(viewport.window())
    dlg.setWindowTitle(tr("Modifica recinzione") if len(groups) == 1
                       else tr("Modifica {0} recinzioni").format(len(groups)))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(muri._Schema(_disegno_recinzione))
    kind = QComboBox()
    for key, label in KINDS:
        kind.addItem(label, key)
    kind.setCurrentIndex(max(0, kind.findData(init["kind"])))
    wall = QCheckBox(tr("Su muretto (sotto la recinzione)"))
    wall.setChecked(init["wall"])
    sp = bal._spin
    w = {"h": sp(init["h"], 0.3, 6.0), "post": sp(init["post"], 0.3, 10.0),
         "sz": sp(init["sz"], 0.02, 0.5), "bot": sp(init["bot"], 0.0, 1.0),
         "dh": sp(init["dh"], 0.02, 0.6), "dg": sp(init["dg"], 0.0, 0.3),
         "dt": sp(init["dt"], 0.005, 0.3), "gap": sp(init["gap"], 0.02, 1.0),
         "bt": sp(init["bt"], 0.005, 0.1), "spear": sp(init["spear"], 0.0, 0.4),
         "rl": sp(init["rl"], 0.0, 2.0), "ru": sp(init["ru"], 0.0, 2.0),
         "rt": sp(init["rt"], 0.01, 0.2), "mh": sp(init["mh"], 0.10, 3.0),
         "mt": sp(init["mt"], 0.05, 1.0)}
    form.addRow(tr("Tipo di recinzione"), kind)
    form.addRow(wall)
    form.addRow(tr("Altezza totale (H) (m)"), w["h"])
    form.addRow(tr("Passo dei pali (i) (m)"), w["post"])
    form.addRow(tr("Sezione pali (s) (m)"), w["sz"])
    form.addRow(tr("Distanza da terra (b) (m)"), w["bot"])
    rows_d = [(tr("Altezza doga (d) (m)"), w["dh"]),
              (tr("Spazio tra le doghe (g) (m)"), w["dg"]),
              (tr("Spessore doga (t) (m)"), w["dt"])]
    rows_f = [(tr("Spazio tra le barre (g) (m)"), w["gap"]),
              (tr("Sezione barre (q) (m)"), w["bt"]),
              (tr("Altezza punta (pt) (m)"), w["spear"]),
              (tr("Traverso basso: distanza da terra (r1) (m)"), w["rl"]),
              (tr("Traverso alto: sotto la cima delle barre (r2) (m)"), w["ru"]),
              (tr("Altezza traversi (rt) (m)"), w["rt"])]
    rows_m = [(tr("Muretto: altezza con cappello (m)"), w["mh"]),
              (tr("Muretto: spessore (m)"), w["mt"])]
    for lab, wd in rows_d + rows_f + rows_m:
        form.addRow(lab, wd)
    _get, _set = _tipi.widgets_io(dict(w, kind=kind, wall=wall))
    tbar = _tipi.TypeBar(dlg, form, "recinzione", first, _get, _set, scene)

    def sync(_i=0) -> None:
        k = kind.currentData()
        for _l, wd in rows_d:
            wd.setEnabled(k == "doghe")
        for _l, wd in rows_f:
            wd.setEnabled(k == "ferro")
        for _l, wd in rows_m:
            wd.setEnabled(wall.isChecked())
    kind.currentIndexChanged.connect(sync)
    wall.toggled.connect(sync)
    sync()
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return
    new = {k: wd.value() for k, wd in w.items()}
    new["kind"], new["wall"] = kind.currentData(), wall.isChecked()
    changed = bal._changed(new, init)
    tp = tbar.result(_get())
    st = _tipi.resolve_edit(viewport.window(), scene, "recinzione", tp)
    if st == "cancel":
        return
    if (not changed and tp.get("tipo_id") == first.get("tipo_id")
            and st != "type"):
        return

    def mutate(sc):
        for gg in groups:
            dd = fence_data(gg)
            if gg not in sc.groups or dd is None:
                continue
            nd = _norm(copy.deepcopy(dd))
            nd.update(changed)
            nd["tipo_id"], nd["tipo_nome"] = tp.get("tipo_id"), tp.get("tipo_nome")
            rebuild_fence(gg, nd)
        if st == "type":
            _tipi.update_instances(
                sc, "recinzione", tp["tipo_id"],
                lambda g, q: rebuild_fence(g, {**_norm(fence_data(g)), **q}))

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("Recinzione aggiornata"), 3000)


def _hook_double_click(vp) -> None:
    if getattr(vp, "_myhouse_recinzione_dbl", False):
        return
    original = getattr(vp, "begin_group_edit", None)
    if original is None:
        return

    def begin_group_edit(group, *args, **kwargs):
        g = getattr(group, "owner", None) or group
        if fence_data(g) is None:
            return original(group, *args, **kwargs)
        scene = vp.scene
        try:
            scene.select([g])
        except Exception:
            scene.selection.clear()
            scene.selection.add(g)
        vp.update()
        QTimer.singleShot(0, lambda: edit_fences(vp, [g]))

    vp.begin_group_edit = begin_group_edit
    vp._myhouse_recinzione_dbl = True


def _outliner_kind(group):
    d = fence_data(group)
    if d is None:
        return None
    d = _norm(d)
    from ._imperial import fmt_len
    length = 0.0
    for seg in bal.segments(d):
        a, b = seg["a"], seg["b"]
        length += math.sqrt(sum((b[i] - a[i]) ** 2 for i in range(3)))
    _s, posts, bars = layout(d)
    props = [(tr("Tipo"), dict(KINDS).get(d["kind"], d["kind"])),
             (tr("Altezza"), fmt_len(d["h"])),
             (tr("Lunghezza"), fmt_len(length)),
             (tr("Pali"), str(len(posts)))]
    if d["kind"] == "ferro":
        props.append((tr("Barre"), str(len(bars))))
    if d.get("wall"):
        props.append((tr("Altezza muretto"), fmt_len(d.get("mh", 0.6))))
    return {"type": tr("Recinzione"), "props": props + piani.level_props(d)}


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
    try:
        _hook_double_click(api.window.viewport)
    except Exception:
        pass
    add_ctx = getattr(api.app, "add_context_menu", None)
    if add_ctx is not None:
        def context(menu, selection) -> None:
            if not _selected_fences(api.app.viewport.scene):
                return
            menu.addSeparator()
            menu.addAction(
                tr("Modifica recinzione…"),
                lambda: QTimer.singleShot(
                    0, lambda: edit_fences(api.app.viewport)))
            menu.addAction(
                tr("Materiale recinzione…"),
                lambda: QTimer.singleShot(
                    0, lambda: set_fence_material(api.app.viewport)))

        add_ctx(context)
    api.add_button(tr("Recinzione"), tr("Crea una recinzione (doghe o ferro battuto, anche su muretto)"),
                   _icon(), api.run_tool(RecinzioneTool()))
    add_kind = getattr(api.app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
