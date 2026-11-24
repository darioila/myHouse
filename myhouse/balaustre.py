# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr
from ._imperial import FT, IN, LengthSpin, dflt
from ._scroll import scroll_form

import copy
import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPen, QVector3D
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QCheckBox, QLineEdit, QVBoxLayout,
)

from core import bim
from . import _ifc
from tools.base import Tool, ToolContext

from . import _codici, _tipi, muri, piani

ORDER = 80
BAR_COLOR = (0.30, 0.31, 0.33)
RAIL_COLOR = (0.45, 0.30, 0.18)
RAIL_MAT_NAME = tr("materiale corrimano")
BAR_MAT_NAME = tr("materiale balaustra")
GLASS_MAT_NAME = tr("vetro balaustra")
GLASS_COLOR = (0.74, 0.90, 0.88)
GLASS_GAP = 0.02
LAYER_NAME = "Balaustre"
KEY = "myhouse_balaustra"
SIDES = 12
RING_SIDES = 20
MIN_SEG = 0.02
PAINT_KEYS = ("col_h", "tex_h", "col_a", "tex_a", "col_v", "tex_v")
RAIL_ZONES = (("h", tr("corrimano")),
              ("a", tr("aste / struttura (montanti, barre, corrente)")),
              ("v", tr("vetro (solo tipo Vetro)")))
DECO_STYLES = ("circles", "diamond", "cross")


_STYLES: list[tuple[str, str]] = [
    ("vert", tr("Verticali")),
    ("horiz", tr("Orizzontali")),
    ("glass", tr("Vetro (montanti + lastre)")),
    ("hand", tr("Solo corrimano")),
    ("circles", tr("Verticali con cerchi")),
    ("diamond", tr("Verticali con losanghe")),
    ("cross", tr("Pannelli con cerchio e croce")),
]


def register_style(key: str, label: str) -> None:
    for i, (k, _) in enumerate(_STYLES):
        if k == key:
            _STYLES[i] = (key, label)
            return
    _STYLES.append((key, label))


def styles() -> list[tuple[str, str]]:
    return list(_STYLES)


def add_railing_along(scene, pts, style, name=None, **over):
    d = {"pts": [list(p) for p in pts], "h": _Settings.h, "gap": _Settings.gap,
         "t": _Settings.t, "hr": _Settings.hr, "bot": _Settings.bot,
         "post": _Settings.post, "round": _Settings.round_, "style": style,
         "vt": _Settings.vt}
    d.update(settings_paint())
    d.update(over)
    return build_railing(scene, d, name or _Settings.name)


class _Settings:
    h = dflt(36 * IN, 1.00)
    gap = dflt(4 * IN, 0.10)
    t = dflt(0.75 * IN, 0.02)
    hr = dflt(2 * IN, 0.05)
    bot = dflt(2 * IN, 0.05)
    post = dflt(4 * FT, 1.00)
    round_ = True
    style = "vert"
    vt = dflt(0.5 * IN, 0.012)
    name = tr("Balaustra")
    ortho = True
    level = None
    col_h = None
    tex_h = None
    col_a = None
    tex_a = None
    col_v = None
    tex_v = None
    tipo_id = None
    tipo_nome = None


def _apply_type(d: dict, q: dict) -> dict:
    nd = {**d, **q}
    for k in PAINT_KEYS:
        if not nd.get(k):
            nd.pop(k, None)
    return nd


def _type_io(ws, paint):
    return _tipi.widgets_io(dict(ws, **paint), tuple(paint))


def settings_paint() -> dict:
    return {k: copy.deepcopy(getattr(_Settings, k, None))
            for k in PAINT_KEYS if getattr(_Settings, k, None)}


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _unit(a):
    n = math.sqrt(_dot(a, a)) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


def segments(d):
    pts = [tuple(p) for p in d["pts"]]
    out = []
    for a, b in zip(pts, pts[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        lp = math.hypot(dx, dy)
        if lp < MIN_SEG:
            continue
        out.append({"a": a, "b": b, "u": (dx / lp, dy / lp), "lp": lp})
    return out


def _tread_z(treads, x, y):
    best = None
    for x0, y0, x1, y1, z in treads or ():
        dx, dy = x1 - x0, y1 - y0
        l2 = dx * dx + dy * dy
        if l2 < 1e-12:
            continue
        t = ((x - x0) * dx + (y - y0) * dy) / l2
        if t < -0.01 or t > 1.01:
            continue
        if math.hypot(x0 + dx * t - x, y0 + dy * t - y) > 0.01:
            continue
        if best is None or z > best:
            best = z
    return best


def _band(d):
    style = d.get("style", "vert")
    if style == "circles":
        return min(0.25, max(0.08, d["gap"] + d["t"]))
    if style == "diamond":
        return max(0.08, min(0.25, d["h"] * 0.25))
    return 0.0


def _panels(d, seg):
    lp = seg["lp"]
    post = max(0.2, d.get("post", 1.0))
    mp = max(1, round(lp / post))
    z0, z1 = d["bot"], d["h"] - d["hr"]
    out = []
    for i in range(mp):
        w = lp / mp
        sq = min(w * 0.8, (z1 - z0) * 0.9)
        if sq < 0.15:
            continue
        out.append((lp * (i + 0.5) / mp, sq, (z0 + z1) / 2))
    return out


def bars(d):
    t, gap, h, hr = d["t"], d["gap"], d["h"], d["hr"]
    bot, post = d["bot"], max(0.2, d.get("post", 1.0))
    style = d.get("style", "vert")
    if style == "hand":
        return []
    only_posts = style == "horiz"
    band = _band(d) if style == "diamond" else 0.0
    out, seen = [], set()
    for seg in segments(d):
        a, b, u, lp = seg["a"], seg["b"], seg["u"], seg["lp"]
        if style == "glass":
            mp = max(1, round(lp / post))
            for i in range(mp + 1):
                s = lp * i / mp
                x, y = a[0] + u[0] * s, a[1] + u[1] * s
                key = (round(x, 3), round(y, 3))
                if key in seen:
                    continue
                seen.add(key)
                zb = a[2] + (b[2] - a[2]) * s / lp
                zf = _tread_z(d.get("treads"), x, y)
                out.append((x, y, zb if zf is None else min(zb, zf),
                            zb + h - hr / 2))
            continue
        m = max(1, math.ceil(lp / (gap + t) - 1e-9))
        mp = max(1, round(lp / post))
        posts = {round(i * m / mp) for i in range(mp + 1)}
        holes = []
        if style == "cross":
            holes = [(sc - sq / 2 - 1e-6, sc + sq / 2 + 1e-6)
                     for sc, sq, _z in _panels(d, seg)]
        for k in range(m + 1):
            s = lp * k / m
            x, y = a[0] + u[0] * s, a[1] + u[1] * s
            if only_posts and k not in posts:
                continue
            if k not in posts and any(lo <= s <= hi for lo, hi in holes):
                continue
            key = (round(x, 3), round(y, 3))
            if key in seen:
                continue
            seen.add(key)
            zb = a[2] + (b[2] - a[2]) * s / lp
            z0 = zb if k in posts else zb + bot + t / 2
            if k in posts:
                zf = _tread_z(d.get("treads"), x, y)
                if zf is not None:
                    z0 = min(zb, zf)
            ztop = zb + h - hr / 2
            if band and k not in posts:
                ztop -= band
            out.append((x, y, z0, ztop))
    return out


def _section(hn, hw, round_):
    if round_:
        r = max(hn, hw)
        return [(r * math.cos(2 * math.pi * i / SIDES),
                 r * math.sin(2 * math.pi * i / SIDES)) for i in range(SIDES)]
    return [(-hn, -hw), (hn, -hw), (hn, hw), (-hn, hw)]


_APP = {"app": None}


def _mat_attrs(name, scene=None):
    if not name:
        return None
    try:
        sc = scene if scene is not None else _APP["app"].viewport.scene
        mat = sc.materials.get(name)
        return dict(mat.face_attrs()) if mat is not None else None
    except Exception:
        return None


def _ask_material(viewport, current, label=tr("Materiale"), extra=None):
    mats = sorted(viewport.scene.materials)
    if not mats:
        viewport.flash_status(tr("Il documento non ha materiali"), 3000)
        return None
    dlg = QDialog(viewport.window())
    dlg.setWindowTitle(label)
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    combos = {}
    for key, text, cur in [("mat", label, current)] + list(extra or []):
        cb = QComboBox()
        cb.addItem(tr("(predefinito)"), None)
        for m in mats:
            cb.addItem(m, m)
        i = cb.findData(cur)
        cb.setCurrentIndex(max(0, i))
        form.addRow(text, cb)
        combos[key] = cb
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return None
    return {k: c.currentData() for k, c in combos.items()}


class _Attrs:

    def __init__(self) -> None:
        self.attrs = {}


def _zone_attrs(d, zone, legacy=None):
    h = _Attrs()
    if muri.paint_face(h, d.get("col_" + zone), d.get("tex_" + zone)):
        return h.attrs
    return legacy


def _tube(mesh, p0, p1, n, hn, hw, color, ext, round_=False, attrs=None,
          m0=None, m1=None, mat=None):
    P = QVector3D
    a = _unit(_sub(p1, p0))
    w = _unit(_cross(a, n))
    q0 = _sub(p0, _mul(a, 0.0 if m0 else ext))
    q1 = _add(p1, _mul(a, 0.0 if m1 else ext))
    sec = _section(hn, hw, round_)

    def ring(q, m):
        pts = []
        for dn, dw in sec:
            off = _add(_mul(n, dn), _mul(w, dw))
            if m:
                off = _add(off, _mul(a, -_dot(off, m) / _dot(a, m)))
            pts.append(_add(q, off))
        return pts

    ring0 = ring(q0, m0)
    ring1 = ring(q1, m1)
    centre = _mul(_add(q0, q1), 0.5)
    m = len(sec)
    polys = [list(reversed(ring0)), ring1]
    for i in range(m):
        j = (i + 1) % m
        polys.append([ring0[i], ring0[j], ring1[j], ring1[i]])
    for vs in polys:
        nrm = (0.0, 0.0, 0.0)
        for i in range(len(vs)):
            c1, c2 = vs[i], vs[(i + 1) % len(vs)]
            nrm = _add(nrm, ((c1[1] - c2[1]) * (c1[2] + c2[2]),
                             (c1[2] - c2[2]) * (c1[0] + c2[0]),
                             (c1[0] - c2[0]) * (c1[1] + c2[1])))
        fc = _mul(vs[0], 0.0)
        for v in vs:
            fc = _add(fc, v)
        fc = _mul(fc, 1.0 / len(vs))
        if _dot(nrm, _sub(fc, centre)) < 0:
            vs = list(reversed(vs))
        f = mesh.add_face([P(*v) for v in vs])
        if attrs:
            f.attrs.update(copy.deepcopy(attrs))
        if mat and "mat" not in f.attrs and "color" not in f.attrs:
            f.attrs["color"] = tuple(color)
            f.attrs["mat"] = mat
        f.attrs["layer"] = LAYER_NAME


def _glass(mesh, d, seg, n, mg=None) -> None:
    a, b, u, lp = seg["a"], seg["b"], seg["u"], seg["lp"]
    h, hr, bot = d["h"], d["hr"], d["bot"]
    vt = d.get("vt", 0.012)
    post = max(0.2, d.get("post", 1.0))
    mp = max(1, round(lp / post))
    z0, z1 = bot, h - hr - GLASS_GAP
    if z1 - z0 < 0.05:
        return
    inset = hr / 2 + GLASS_GAP
    mid, half = (z0 + z1) / 2, (z1 - z0) / 2
    for i in range(mp):
        s0 = lp * i / mp + inset
        s1 = lp * (i + 1) / mp - inset
        if s1 - s0 < 0.05:
            continue
        pts = []
        for s in (s0, s1):
            zb = a[2] + (b[2] - a[2]) * s / lp
            pts.append((a[0] + u[0] * s, a[1] + u[1] * s, zb + mid))
        _tube(mesh, pts[0], pts[1], n, vt / 2, half, GLASS_COLOR, 0.0, False,
              mg, mat=GLASS_MAT_NAME)


def _pt(seg, s, z):
    a, b, u, lp = seg["a"], seg["b"], seg["u"], seg["lp"]
    return (a[0] + u[0] * s, a[1] + u[1] * s,
            a[2] + (b[2] - a[2]) * s / lp + z)


def _deco_bar(mesh, d, seg, n, s0, z0, s1, z1, aa, ext=0.0) -> None:
    p0, p1 = _pt(seg, s0, z0), _pt(seg, s1, z1)
    if _dot(_sub(p1, p0), _sub(p1, p0)) < 1e-8:
        return
    t = d["t"]
    _tube(mesh, p0, p1, n, t / 2, t / 2, BAR_COLOR, ext,
          bool(d.get("round", False)), aa, mat=BAR_MAT_NAME)


def _deco_circles(mesh, d, seg, n, aa, c0, c1) -> None:
    t, gap, h, hr = d["t"], d["gap"], d["h"], d["hr"]
    bh = _band(d)
    zt = h - hr / 2
    zl = zt - bh
    a, b = seg["a"], seg["b"]
    _tube(mesh, (a[0], a[1], a[2] + zl), (b[0], b[1], b[2] + zl), n, t / 2,
          t / 2, BAR_COLOR, t / 2, bool(d.get("round", False)), aa, c0, c1,
          mat=BAR_MAT_NAME)
    lp = seg["lp"]
    m = max(1, math.ceil(lp / (gap + t) - 1e-9))
    rc = max(0.01, min((gap - t) / 2, (bh - t) / 2 * 0.9))
    zc = (zt + zl) / 2
    for k in range(m):
        sc = lp * (k + 0.5) / m
        pts = [(sc + rc * math.cos(2 * math.pi * j / RING_SIDES),
                zc + rc * math.sin(2 * math.pi * j / RING_SIDES))
               for j in range(RING_SIDES)]
        for j in range(RING_SIDES):
            p, q = pts[j], pts[(j + 1) % RING_SIDES]
            _deco_bar(mesh, d, seg, n, p[0], p[1], q[0], q[1], aa, t * 0.3)


def _deco_diamond(mesh, d, seg, n, aa, c0, c1) -> None:
    t, h, hr = d["t"], d["h"], d["hr"]
    bh = _band(d)
    zt = h - hr / 2
    zl = zt - bh
    a, b = seg["a"], seg["b"]
    _tube(mesh, (a[0], a[1], a[2] + zl), (b[0], b[1], b[2] + zl), n, t / 2,
          t / 2, BAR_COLOR, t / 2, bool(d.get("round", False)), aa, c0, c1,
          mat=BAR_MAT_NAME)
    lp = seg["lp"]
    cells = max(1, round(lp / bh))
    cw = lp / cells
    for i in range(cells):
        s0, s1 = i * cw, (i + 1) * cw
        _deco_bar(mesh, d, seg, n, s0, zl, s1, zt, aa)
        _deco_bar(mesh, d, seg, n, s0, zt, s1, zl, aa)


def _deco_cross(mesh, d, seg, n, aa) -> None:
    t = d["t"]
    for sc, sq, zc in _panels(d, seg):
        r = sq / 2
        c = (sc, zc)
        corners = [(sc - r, zc - r), (sc + r, zc - r),
                   (sc + r, zc + r), (sc - r, zc + r)]
        for i in range(4):
            p, q = corners[i], corners[(i + 1) % 4]
            _deco_bar(mesh, d, seg, n, p[0], p[1], q[0], q[1], aa, t / 2)
        mids = [(sc, zc - r), (sc + r, zc), (sc, zc + r), (sc - r, zc)]
        for i in range(4):
            p, q = mids[i], mids[(i + 1) % 4]
            _deco_bar(mesh, d, seg, n, p[0], p[1], q[0], q[1], aa, t / 2)
        rc = sq * 0.22
        pts = [(c[0] + rc * math.cos(2 * math.pi * j / RING_SIDES),
                c[1] + rc * math.sin(2 * math.pi * j / RING_SIDES))
               for j in range(RING_SIDES)]
        for j in range(RING_SIDES):
            p, q = pts[j], pts[(j + 1) % RING_SIDES]
            _deco_bar(mesh, d, seg, n, p[0], p[1], q[0], q[1], aa, t * 0.3)
        k = math.sqrt(0.5)
        for sx, sz in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            _deco_bar(mesh, d, seg, n, c[0] + sx * k * rc, c[1] + sz * k * rc,
                      corners[0][0] + (sx + 1) * r, corners[0][1] + (sz + 1) * r,
                      aa, t / 2)


def _soften(mesh) -> None:
    try:
        for e in mesh.edges:
            fs = list(e.faces)
            if len(fs) != 2:
                continue
            if all(len(list(f.vertices)) == 4 for f in fs):
                e.soft = True
                e.hidden = True
    except Exception:
        pass


def _miters(segs, d):
    def dirs(s):
        return _unit(_sub(s["b"], s["a"]))

    def same(p, q):
        return all(abs(p[i] - q[i]) < 1e-6 for i in range(3))

    def miter(s1, s2):
        a1, a2 = dirs(s1), dirs(s2)
        m = _add(a1, a2)
        if _dot(m, m) < 1e-9:
            return None
        m = _unit(m)
        return m if _dot(a1, m) > 0.2 else None

    k = len(segs)
    out = [[None, None] for _ in segs]
    for i in range(k - 1):
        if same(segs[i]["b"], segs[i + 1]["a"]):
            m = miter(segs[i], segs[i + 1])
            out[i][1] = m
            out[i + 1][0] = m
    if k >= 3 and same(segs[-1]["b"], segs[0]["a"]):
        m = miter(segs[-1], segs[0])
        out[-1][1] = m
        out[0][0] = m
    return out


def railing_mesh(d):
    from core.mesh import Mesh
    mesh = Mesh()
    t, hr, h, bot = d["t"], d["hr"], d["h"], d["bot"]
    rnd = bool(d.get("round", False))
    ma = _mat_attrs(d.get("mat"))
    mg = _mat_attrs(d.get("matg"))
    ah = _zone_attrs(d, "h", ma)
    aa = _zone_attrs(d, "a", ma)
    av = _zone_attrs(d, "v", mg)
    segs = segments(d)
    miters = _miters(segs, d)
    for seg, (c0, c1) in zip(segs, miters):
        a, b, u = seg["a"], seg["b"], seg["u"]
        n = (-u[1], u[0], 0.0)
        top0 = (a[0], a[1], a[2] + h - hr / 2)
        top1 = (b[0], b[1], b[2] + h - hr / 2)
        _tube(mesh, top0, top1, n, hr / 2, hr / 2, RAIL_COLOR, hr / 2, rnd,
              ah, c0, c1, mat=RAIL_MAT_NAME)
        style = d.get("style", "vert")
        if style == "hand":
            continue
        if style == "glass":
            _glass(mesh, d, seg, n, av)
            continue
        low0 = (a[0], a[1], a[2] + bot + t / 2)
        low1 = (b[0], b[1], b[2] + bot + t / 2)
        _tube(mesh, low0, low1, n, t / 2, t / 2, BAR_COLOR, t / 2, rnd, aa,
              c0, c1, mat=BAR_MAT_NAME)
        if style == "circles":
            _deco_circles(mesh, d, seg, n, aa, c0, c1)
        elif style == "diamond":
            _deco_diamond(mesh, d, seg, n, aa, c0, c1)
        elif style == "cross":
            _deco_cross(mesh, d, seg, n, aa)
        if style == "horiz":
            dz = top0[2] - low0[2]
            k = max(1, math.ceil(dz / (d["gap"] + t) - 1e-9))
            for i in range(1, k):
                o = dz * i / k
                _tube(mesh, (low0[0], low0[1], low0[2] + o),
                      (low1[0], low1[1], low1[2] + o), n, t / 2, t / 2,
                      BAR_COLOR, t / 2, rnd, aa, c0, c1, mat=BAR_MAT_NAME)
    pw = hr / 2 if d.get("style", "vert") == "glass" else t / 2
    for x, y, zb, zt in bars(d):
        _tube(mesh, (x, y, zb), (x, y, zt), (1.0, 0.0, 0.0), pw, pw,
              BAR_COLOR, 0.0, rnd, aa, mat=BAR_MAT_NAME)
    if rnd:
        _soften(mesh)
    return mesh


def railing_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "pts" in data else None


def rebuild_railing(group, d) -> None:
    from core.group import Group
    part = Group(railing_mesh(d), name=tr("Balaustra"))
    part.component = False
    group.children = [part]
    _ifc.tag(group, "IfcRailing")
    ext = dict(group.ext or {})
    ext[KEY] = dict(d)
    group.ext = ext


def build_railing(scene, d, name) -> None:
    from core.group import Group
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    part = Group(railing_mesh(d), name=tr("Balaustra"))
    part.component = False
    g = Group(name=name)
    g.adopt([part])
    g.component = False
    g.layer = LAYER_NAME
    _ifc.tag(g, "IfcRailing", name)
    g.ext = {KEY: d}
    scene.groups.append(g)
    return g


def _spin(value, lo, hi):
    s = LengthSpin()
    s.setDecimals(3)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


def _disegno_balaustra(p):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPen
    r, t, dim, ext = muri._r, muri._t, muri._dim, muri._ext
    t(p, 10, 12, tr("Prospetto"), size=9)
    p.setPen(QPen(muri._C_LINEA, 1.5))
    p.drawLine(QPointF(10, 150), QPointF(280, 150))
    muri._hatch(p, 10, 150, 280, 155)
    r(p, 30, 30, 38, 150, muri._C_CORPO)
    r(p, 252, 30, 260, 150, muri._C_CORPO)
    r(p, 30, 22, 260, 32, muri._C_LEGNO)
    r(p, 38, 130, 252, 136, muri._C_CORPO)
    for k in range(8):
        x = 62 + 26 * k
        r(p, x, 32, x + 4, 130, muri._C_CORPO)
    dim(p, 62 + 26 * 2 + 4, 80, 62 + 26 * 3, 80, "g", 1)
    dim(p, 14, 22, 14, 150, "H", -1)
    dim(p, 46, 136, 46, 150, "b", 1)
    dim(p, 34, 166, 256, 166, "i", 1)
    dim(p, 266, 22, 266, 32, "c")
    t(p, 305, 12, tr("Sezioni"), size=9)
    r(p, 310, 40, 334, 64, muri._C_CORPO)
    dim(p, 310, 72, 334, 72, "t", -1)
    p.setPen(QPen(muri._C_LINEA, 1.2))
    p.setBrush(muri._C_CORPO)
    p.drawEllipse(QPointF(372, 52), 12, 12)
    dim(p, 360, 52, 384, 52, "t", 1)
    p.drawEllipse(QPointF(436, 52), 15, 15)
    dim(p, 421, 52, 451, 52, "c", 1)
    t(p, 310, 92, tr("quadro"), size=8)
    t(p, 355, 92, tr("tondo"), size=8)
    t(p, 410, 92, tr("corrimano"), size=8)
    r(p, 380, 108, 388, 152, muri._C_VETRO if hasattr(muri, "_C_VETRO") else muri._C_ANTA)
    dim(p, 380, 104, 388, 104, "v", 1)
    t(p, 396, 134, tr("vetro (sezione)"), size=8)


def ask_settings(parent, scene=None) -> bool:
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("Balaustra"))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(muri._Schema(_disegno_balaustra))
    h = _spin(_Settings.h, 0.2, 5.0)
    gap = _spin(_Settings.gap, 0.01, 2.0)
    t = _spin(_Settings.t, 0.005, 0.3)
    hr = _spin(_Settings.hr, 0.005, 0.5)
    bot = _spin(_Settings.bot, 0.0, 2.0)
    post = _spin(_Settings.post, 0.2, 10.0)
    sect = QComboBox()
    sect.addItem(tr("Tonda"), True)
    sect.addItem(tr("Quadra"), False)
    sect.setCurrentIndex(0 if _Settings.round_ else 1)
    vt = _spin(_Settings.vt, 0.004, 0.05)
    style = QComboBox()
    for k, lab in styles():
        style.addItem(lab, k)
    style.setCurrentIndex(max(0, style.findData(_Settings.style)))
    name = QLineEdit(_Settings.name)
    ortho = QCheckBox(tr("Ortogonale (O / F8 durante il disegno)"))
    ortho.setChecked(_Settings.ortho)
    lvl = None
    if scene is not None and piani.levels(scene):
        lvl = piani.level_combo(scene, piani.active_id(scene))
        form.addRow(tr("Piano (la quota resta quella dei punti cliccati)"), lvl)
    form.addRow(tr("Altezza balaustra (H) (m)"), h)
    form.addRow(tr("Tipo di barre"), style)
    form.addRow(tr("Spazio tra le barre (g) (m)"), gap)
    form.addRow(tr("Sezione tubolari"), sect)
    form.addRow(tr("Spessore (diametro) tubolari (t) (m)"), t)
    form.addRow(tr("Spessore (diametro) corrimano (c) (m)"), hr)
    form.addRow(tr("Corrente basso: distanza dal piano (b) (m)"), bot)
    form.addRow(tr("Passo montanti fino a terra (i) (m)"), post)
    form.addRow(tr("Spessore vetro (v) (m)"), vt)
    paint = muri.add_paint_rows(form, lambda k: getattr(_Settings, k, None),
                                RAIL_ZONES)
    form.addRow(tr("Nome"), name)
    form.addRow(ortho)
    _get, _set = _type_io({"h": h, "style": style, "gap": gap, "round": sect,
                           "t": t, "hr": hr, "bot": bot, "post": post,
                           "vt": vt}, paint)
    tbar = _tipi.TypeBar(dlg, form, "balaustra", {"tipo_id": _Settings.tipo_id},
                         _get, _set, scene, creating=True)
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return False
    _Settings.h, _Settings.gap = h.value(), gap.value()
    _Settings.t, _Settings.hr = t.value(), hr.value()
    _Settings.bot = bot.value()
    _Settings.post, _Settings.round_ = post.value(), sect.currentData()
    _Settings.style = style.currentData()
    _Settings.vt = vt.value()
    _Settings.ortho = ortho.isChecked()
    for k, v in muri.paint_results(paint).items():
        setattr(_Settings, k, v)
    _Settings.name = name.text().strip() or tr("Balaustra")
    _Settings.level = (lvl.currentData() or None) if lvl is not None else None
    if lvl is not None:
        piani.set_active(_Settings.level)
    r = tbar.result(_get())
    _Settings.tipo_id, _Settings.tipo_nome = r.get("tipo_id"), r.get("tipo_nome")
    return True


class BalaustraTool(Tool):
    name = tr("Balaustra")
    shortcut = None
    description = tr("Crea una balaustra: clic sui punti della polilinea.")

    def __init__(self) -> None:
        self._entering = False
        self._reset()

    def _reset(self) -> None:
        self.points: list[tuple[float, float, float]] = []
        self.hover: QVector3D | None = None

    def _ortho(self, p: QVector3D) -> QVector3D:
        if not (_Settings.ortho and self.points):
            return p
        last = self.points[-1]
        if abs(p.x() - last[0]) >= abs(p.y() - last[1]):
            return QVector3D(p.x(), last[1], p.z())
        return QVector3D(last[0], p.y(), p.z())

    def status_clause(self) -> str:
        return (tr("Ortogonale {0} (O/F8) · C = chiudi · Invio = fine").format(('ON' if _Settings.ortho else 'OFF')))

    def on_activate(self, viewport) -> None:
        if self._entering:
            self._reset()
            viewport.flash_status(
                tr("Balaustra: clic sui punti (sugli spigoli della scala si "
                "inclina) · O/F8 = ortogonale · Invio = concludi · C = chiudi · "
                "Esc = esci"), 7000)
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
        if key in (Qt.Key_Escape, Qt.Key_O, Qt.Key_F8):
            return True
        return bool(self.points) and key in (
            Qt.Key_Return, Qt.Key_Enter, Qt.Key_Backspace, Qt.Key_C)

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if key in (Qt.Key_O, Qt.Key_F8):
            _Settings.ortho = not _Settings.ortho
            if self.hover is not None:
                self.hover = self._ortho(self.hover)
            viewport.flash_status(
                tr("Ortogonale ") + (tr("attivo") if _Settings.ortho else tr("disattivato")),
                2000)
            viewport.update()
            return True
        if not self.points:
            return False
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self._commit(viewport)
            return True
        if key == Qt.Key_C:
            if len(self.points) >= 3:
                self.points.append(self.points[0])
                self._commit(viewport)
            else:
                viewport.flash_status(tr("Servono almeno 3 punti per chiudere"),
                                      3000)
            return True
        if key == Qt.Key_Backspace:
            self.points.pop()
            viewport.update()
            return True
        return False

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover = self._ortho(QVector3D(ctx.world))
        ctx.viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        if getattr(vp.scene, "edit_group", None) is not None:
            vp.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        q3 = self._ortho(QVector3D(ctx.world))
        p = (q3.x(), q3.y(), q3.z())
        if self.points:
            q = self.points[-1]
            if math.hypot(p[0] - q[0], p[1] - q[1]) < MIN_SEG:
                return
        self.points.append(p)
        vp.update()

    def _dict(self, pts):
        d = {"pts": [list(p) for p in pts], "h": _Settings.h,
             "gap": _Settings.gap, "t": _Settings.t, "hr": _Settings.hr,
             "bot": _Settings.bot, "post": _Settings.post,
             "round": _Settings.round_, "style": _Settings.style,
             "vt": _Settings.vt,
             "tipo_id": _Settings.tipo_id, "tipo_nome": _Settings.tipo_nome}
        d.update(settings_paint())
        if not d["tipo_id"]:
            d.pop("tipo_id")
            d.pop("tipo_nome")
        return d

    def _commit(self, viewport) -> None:
        d = self._dict(self.points)
        if not segments(d):
            viewport.flash_status(tr("Servono almeno 2 punti distinti"), 3000)
            return
        name = _Settings.name
        lv = piani.get(viewport.scene, _Settings.level)
        if lv:
            d.update({"lv": lv["id"], "lvn": lv["name"],
                      "off": min(p[2] for p in d["pts"]) - lv["z"]})

        def mutate(scene):
            build_railing(scene, d, name)

        viewport.history.execute(muri.MuriCommand(mutate))
        viewport.notify_scene_changed()
        viewport.flash_status(
            tr("Balaustra creata · {0} barre verticali").format(len(bars(d))), 3500)
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
        lines = []
        for seg in segments(d):
            a, b = seg["a"], seg["b"]
            lines.append((P(a[0], a[1], a[2] + d["h"]),
                          P(b[0], b[1], b[2] + d["h"])))
            lines.append((P(*a), P(*b)))
        for x, y, zb, zt in bars(d):
            lines.append((P(x, y, zb), P(x, y, zt + d["hr"] / 2)))
        return lines


def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(90, 92, 98))
    p.drawRect(4, 8, 40, 5)
    p.drawRect(4, 36, 40, 3)
    for x in (6, 14, 22, 30, 38):
        p.drawLine(x + 2, 13, x + 2, 36)
    p.end()
    return QIcon(pm)


def _selected_railings(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and railing_data(g) is not None and g not in out:
            out.append(g)
    return out


def set_railing_material(viewport) -> None:
    scene = viewport.scene
    sel = _selected_railings(scene)
    if not sel:
        viewport.flash_status(tr("Seleziona una balaustra"), 3000)
        return
    d0 = railing_data(sel[0])
    keys = [[list(p) for p in railing_data(g)["pts"]] for g in sel]
    extra = ([("matg", tr("Materiale vetro"), d0.get("matg"))]
             if d0.get("style") == "glass" else [])
    res = _ask_material(viewport, d0.get("mat"), tr("Materiale struttura"), extra)
    if res is None:
        return

    def mutate(sc):
        for gg in sc.groups:
            dd = railing_data(gg)
            if dd is not None and [list(p) for p in dd["pts"]] in keys:
                nd = copy.deepcopy(dd)
                for k, v in res.items():
                    if v:
                        nd[k] = v
                    else:
                        nd.pop(k, None)
                rebuild_railing(gg, nd)

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("Materiale applicato"), 3000)


def edit_railing_paint(viewport) -> None:
    scene = viewport.scene
    sel = _selected_railings(scene)
    if not sel:
        viewport.flash_status(tr("Seleziona una balaustra"), 3000)
        return
    first = railing_data(sel[0])
    keys = [[list(p) for p in railing_data(g)["pts"]] for g in sel]
    styles_ = {railing_data(g).get("style", "vert") for g in sel}
    zones = [z for z in RAIL_ZONES
             if z[0] == "h"
             or (z[0] == "a" and styles_ - {"hand"})
             or (z[0] == "v" and "glass" in styles_)]
    dlg = QDialog(viewport.window())
    dlg.setWindowTitle(tr("Colori e texture balaustra"))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    pk = muri.add_paint_rows(form, first.get, zones)
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return
    changed = {k: v for k, v in muri.paint_results(pk).items()
               if v != first.get(k)}
    if not changed:
        return

    def mutate(sc):
        for gg in sc.groups:
            dd = railing_data(gg)
            if dd is not None and [list(p) for p in dd["pts"]] in keys:
                nd = copy.deepcopy(dd)
                for k, v in changed.items():
                    if v:
                        nd[k] = v
                    else:
                        nd.pop(k, None)
                rebuild_railing(gg, nd)
                _tipi.settle(gg, "balaustra")

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("Materiali applicati"), 3000)


def _changed(new: dict, init: dict) -> dict:
    out = {}
    for k, v in new.items():
        o = init.get(k)
        if isinstance(v, float) and isinstance(o, (int, float)):
            if abs(v - o) > 0.0006:
                out[k] = v
        elif v != o:
            out[k] = v
    return out


def edit_railings(viewport, groups=None) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    groups = [g for g in (groups or _selected_railings(scene))
              if railing_data(g) is not None]
    if not groups:
        viewport.flash_status(tr("Seleziona una balaustra"), 3000)
        return
    first = railing_data(groups[0])
    init = {"h": first.get("h", _Settings.h),
            "style": first.get("style", "vert"),
            "gap": first.get("gap", _Settings.gap),
            "round": bool(first.get("round", False)),
            "t": first.get("t", _Settings.t),
            "hr": first.get("hr", _Settings.hr),
            "bot": first.get("bot", _Settings.bot),
            "post": first.get("post", _Settings.post),
            "vt": first.get("vt", _Settings.vt)}
    dlg = QDialog(viewport.window())
    dlg.setWindowTitle(tr("Modifica balaustra") if len(groups) == 1
                       else tr("Modifica {0} balaustre").format(len(groups)))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(muri._Schema(_disegno_balaustra))
    h = _spin(init["h"], 0.2, 5.0)
    gap = _spin(init["gap"], 0.01, 2.0)
    t = _spin(init["t"], 0.005, 0.3)
    hr = _spin(init["hr"], 0.005, 0.5)
    bot = _spin(init["bot"], 0.0, 2.0)
    post = _spin(init["post"], 0.2, 10.0)
    vt = _spin(init["vt"], 0.004, 0.05)
    sect = QComboBox()
    sect.addItem(tr("Tonda"), True)
    sect.addItem(tr("Quadra"), False)
    sect.setCurrentIndex(0 if init["round"] else 1)
    style = QComboBox()
    for k, lab in styles():
        style.addItem(lab, k)
    style.setCurrentIndex(max(0, style.findData(init["style"])))
    form.addRow(tr("Altezza balaustra (H) (m)"), h)
    form.addRow(tr("Tipo di barre"), style)
    form.addRow(tr("Spazio tra le barre (g) (m)"), gap)
    form.addRow(tr("Sezione tubolari"), sect)
    form.addRow(tr("Spessore (diametro) tubolari (t) (m)"), t)
    form.addRow(tr("Spessore (diametro) corrimano (c) (m)"), hr)
    form.addRow(tr("Corrente basso: distanza dal piano (b) (m)"), bot)
    form.addRow(tr("Passo montanti fino a terra (i) (m)"), post)
    form.addRow(tr("Spessore vetro (v) (m)"), vt)
    paint = muri.add_paint_rows(form, first.get, RAIL_ZONES)
    _get, _set = _type_io({"h": h, "style": style, "gap": gap, "round": sect,
                           "t": t, "hr": hr, "bot": bot, "post": post,
                           "vt": vt}, paint)
    tbar = _tipi.TypeBar(dlg, form, "balaustra", first, _get, _set, scene)
    cf = _codici.CodeField(form, groups, "balaustra", scene, at=2)
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return
    cf.apply(viewport.window())
    tp = tbar.result(_get())
    st = _tipi.resolve_edit(viewport.window(), scene, "balaustra", tp)
    if st == "cancel":
        return
    new = {"h": h.value(), "style": style.currentData(), "gap": gap.value(),
           "round": sect.currentData(), "t": t.value(), "hr": hr.value(),
           "bot": bot.value(), "post": post.value(), "vt": vt.value()}
    changed = _changed(new, init)
    paint_changed = {k: v for k, v in muri.paint_results(paint).items()
                     if v != first.get(k)}
    new_type = tp.get("tipo_id") != first.get("tipo_id")
    if not changed and not paint_changed and not new_type and st != "type":
        return

    def mutate(sc):
        for gg in groups:
            dd = railing_data(gg)
            if gg not in sc.groups or dd is None:
                continue
            nd = copy.deepcopy(dd)
            nd.update(changed)
            for k, v in paint_changed.items():
                if v:
                    nd[k] = v
                else:
                    nd.pop(k, None)
            nd["tipo_id"], nd["tipo_nome"] = tp.get("tipo_id"), tp.get("tipo_nome")
            rebuild_railing(gg, nd)
        if st == "type":
            _tipi.update_instances(
                sc, "balaustra", tp["tipo_id"],
                lambda g, q: rebuild_railing(g, _apply_type(railing_data(g), q)))

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("Balaustra aggiornata"), 3000)


def _hook_double_click(vp) -> None:
    if getattr(vp, "_myhouse_balaustra_dbl", False):
        return
    original = getattr(vp, "begin_group_edit", None)
    if original is None:
        return

    def begin_group_edit(group, *args, **kwargs):
        g = getattr(group, "owner", None) or group
        if railing_data(g) is None:
            return original(group, *args, **kwargs)
        scene = vp.scene
        try:
            scene.select([g])
        except Exception:
            scene.selection.clear()
            scene.selection.add(g)
        vp.update()
        QTimer.singleShot(0, lambda: edit_railings(vp, [g]))

    vp.begin_group_edit = begin_group_edit
    vp._myhouse_balaustra_dbl = True


def _outliner_kind(group):
    d = railing_data(group)
    if d is None:
        return None
    from ._imperial import fmt_len
    length = 0.0
    for seg in segments(d):
        a, b = seg["a"], seg["b"]
        length += math.sqrt(sum((b[i] - a[i]) ** 2 for i in range(3)))
    return {"type": tr("Balaustra"),
            "props": [(tr("Altezza"), fmt_len(d["h"])),
                      (tr("Lunghezza"), fmt_len(length)),
                      (tr("Barre verticali"), str(len(bars(d))))]
            + piani.level_props(d)}


def _register_level_kind() -> None:
    def zget(d):
        return min(p[2] for p in d["pts"])

    def zset(d, z):
        delta = z - zget(d)
        d["pts"] = [[p[0], p[1], p[2] + delta] for p in d["pts"]]

    piani.register_kind("balaustra", KEY, railing_data, zget, zset,
                        rebuild_railing)


def register(api) -> None:
    _APP["app"] = api.app
    _register_level_kind()
    try:
        _hook_double_click(api.window.viewport)
    except Exception:
        pass
    add_ctx = getattr(api.app, "add_context_menu", None)
    if add_ctx is not None:
        def context(menu, selection) -> None:
            if not _selected_railings(api.app.viewport.scene):
                return
            menu.addSeparator()
            menu.addAction(
                tr("Modifica balaustra…"),
                lambda: QTimer.singleShot(
                    0, lambda: edit_railings(api.app.viewport)))
            menu.addAction(
                tr("Colori e texture balaustra…"),
                lambda: QTimer.singleShot(
                    0, lambda: edit_railing_paint(api.app.viewport)))
            menu.addAction(
                tr("Materiale balaustra…"),
                lambda: QTimer.singleShot(
                    0, lambda: set_railing_material(api.app.viewport)))

        add_ctx(context)
    api.add_button(tr("Balaustra"), tr("Crea una balaustra (anche inclinata su scale)"),
                   _icon(), api.run_tool(BalaustraTool()))
    add_kind = getattr(api.app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
