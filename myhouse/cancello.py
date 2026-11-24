# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr
from ._imperial import LengthSpin
from ._scroll import scroll_form

import copy
import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPen, QVector3D
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QLineEdit, QVBoxLayout,
)

from core import bim
from . import _ifc
from tools.base import Tool, ToolContext

from . import muri, piani

ORDER = 83
KEY = "myhouse_cancello"
LAYER_NAME = "Cancelli"
MIN_LEN = 0.30
CENTER_GAP = 0.04
CENTER_POST = 0.08
SPEAR_STEM = 0.03
SPEAR_H = 0.07
ARC_STEPS = 16
PAINT_KEYS = ("col_f", "tex_f", "col_p", "tex_p", "col_c", "tex_c")
ZONES = (("f", tr("telaio")),
         ("p", tr("riempimento (pannello, doghe, barre)")),
         ("c", tr("pilastrino")))
ZONE_NAME = {"f": tr("telaio cancello"), "p": tr("riempimento cancello"),
             "c": tr("pilastrino cancello")}
ZONE_COLOR = {"f": (0.18, 0.20, 0.22), "p": (0.24, 0.27, 0.30),
              "c": (0.90, 0.89, 0.86)}

STYLES = [
    ("hslat", tr("Doghe orizzontali")),
    ("bars", tr("Barre verticali con puntali (ferro battuto)")),
    ("vslat", tr("Doghe verticali in basso e barre in alto")),
    ("mixed", tr("Pannello pieno in basso e barre in alto")),
    ("panelarc", tr("Pannello ad arco con fascia di barre in alto")),
]

CAPS = [
    ("pyramid", tr("Piramide")),
    ("none", tr("Nessuna (solo cappello)")),
    ("sphere", tr("Sfera")),
]

PROFILES = [
    ("arc", tr("Arco (piu' alto al centro)")),
    ("ogee", tr("A onda (S) verso il centro")),
]

LOWS = [
    ("panel", tr("Pannello pieno")),
    ("bars", tr("Barre")),
]

DEFAULTS = {
    "h": 1.80, "c": 0.05, "style": "hslat", "leaves": 2, "f": 0.0,
    "fw": 0.05, "fd": 0.05, "pt": 0.02, "t": 0.016, "gap": 0.11,
    "sl": 0.12, "sg": 0.02, "vw": 0.10, "pan": 0.80, "spear": True,
    "pl": False, "pr": False, "pw": 0.30, "pd": 0.30, "ph": 2.00,
    "cap": "pyramid", "profile": "arc", "band": 0.0, "ricci": False, "low": "panel",
    "open": 0.0, "opdir": 1,
}


class _Settings:
    vals = dict(DEFAULTS)
    name = tr("Cancello")
    ortho = True
    level = None
    paint: dict = {}


def _paint_dict() -> dict:
    return {k: copy.deepcopy(v) for k, v in _Settings.paint.items() if v}


def gate_axes(d):
    a, b = d["pts"][0], d["pts"][1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy)
    if L < 1e-9:
        return tuple(a), (1.0, 0.0), (0.0, 1.0), 0.0
    u = (dx / L, dy / L)
    return tuple(a), u, (-u[1], u[0]), L


def gate_length(d) -> float:
    return gate_axes(d)[3]


def _top_fn(d, L):
    H, f = d["h"], d.get("f", 0.0)
    ogee = d.get("profile", "arc") == "ogee"

    def top(s):
        if ogee:
            t = min(s, L - s) / (L / 2.0)
            t = max(0.0, min(1.0, t))
            return H - f * (1.0 - (3 * t * t - 2 * t * t * t))
        q = 2.0 * s / L - 1.0
        return H - f * q * q
    return top


RICCI_BAND = 0.20


def _band(d) -> float:
    band = d.get("band", 0.0)
    if band > 0.04:
        return band
    if d.get("ricci") and d.get("style", "hslat") != "hslat":
        return RICCI_BAND
    return 0.0


class _Attrs:
    def __init__(self) -> None:
        self.attrs = {}


def _zone_attrs(d, zone):
    h = _Attrs()
    if muri.paint_face(h, d.get("col_" + zone), d.get("tex_" + zone)):
        return h.attrs
    return None


class _Build:

    def __init__(self, d) -> None:
        from core.mesh import Mesh
        self.d = d
        self.mesh = Mesh()
        self.o, self.u, self.n, self.L = gate_axes(d)
        self.attrs = {z: _zone_attrs(d, z) for z, _ in ZONES}
        self.hidden = set()
        self.hinge = None

    def _rot(self, s, y):
        if self.hinge is None:
            return s, y
        h, a = self.hinge
        c, sn = math.cos(a), math.sin(a)
        return h + (s - h) * c - y * sn, (s - h) * sn + y * c

    def P(self, s, y, z):
        s, y = self._rot(s, y)
        o, u, n = self.o, self.u, self.n
        return QVector3D(o[0] + u[0] * s + n[0] * y,
                         o[1] + u[1] * s + n[1] * y, o[2] + z)

    def key(self, s, y, z):
        p = self.P(s, y, z)
        return (round(p.x(), 4), round(p.y(), 4), round(p.z(), 4))

    def hide(self, p, q):
        self.hidden.add(frozenset((self.key(*p), self.key(*q))))

    def vec(self, s, y, z):
        u, n = self.u, self.n
        if self.hinge is not None:
            a = self.hinge[1]
            c, sn = math.cos(a), math.sin(a)
            s, y = s * c - y * sn, s * sn + y * c
        return (u[0] * s + n[0] * y, u[1] * s + n[1] * y, z)

    def face(self, pts, want, zone) -> None:
        v = [self.P(*p) for p in pts]
        nx = ny = nz = 0.0
        for i in range(len(v)):
            a, b = v[i], v[(i + 1) % len(v)]
            nx += (a.y() - b.y()) * (a.z() + b.z())
            ny += (a.z() - b.z()) * (a.x() + b.x())
            nz += (a.x() - b.x()) * (a.y() + b.y())
        w = self.vec(*want)
        if nx * w[0] + ny * w[1] + nz * w[2] < 0:
            v.reverse()
        f = self.mesh.add_face(v)
        at = self.attrs.get(zone)
        if at:
            f.attrs.update(copy.deepcopy(at))
        else:
            f.attrs["color"] = ZONE_COLOR[zone]
            f.attrs["mat"] = ZONE_NAME[zone]
        f.attrs["layer"] = LAYER_NAME

    def prism(self, ring, y0, y1, zone, skip=()) -> None:
        n = len(ring)
        if n < 3:
            return
        area = sum(ring[i][0] * ring[(i + 1) % n][1]
                   - ring[(i + 1) % n][0] * ring[i][1] for i in range(n))
        sg = 1.0 if area >= 0 else -1.0
        self.face([(s, y1, z) for s, z in ring], (0, 1, 0), zone)
        self.face([(s, y0, z) for s, z in ring], (0, -1, 0), zone)
        for i in range(n):
            j = (i + 1) % n
            (si, zi), (sj, zj) = ring[i], ring[j]
            if abs(sj - si) < 1e-9 and abs(zj - zi) < 1e-9:
                continue
            if i in skip:
                for y in (y0, y1):
                    self.hide((si, y, zi), (sj, y, zj))
                for s, z in ((si, zi), (sj, zj)):
                    self.hide((s, y0, z), (s, y1, z))
                continue
            self.face([(si, y0, zi), (sj, y0, zj), (sj, y1, zj), (si, y1, zi)],
                      (sg * (zj - zi), 0.0, -sg * (sj - si)), zone)

    def box(self, s0, s1, z0, z1, y0, y1, zone) -> None:
        self.prism([(s0, z0), (s1, z0), (s1, z1), (s0, z1)], y0, y1, zone)

    def pyramid(self, sc, zb, wx, wy, h, zone) -> None:
        c = [(sc - wx / 2, -wy / 2, zb), (sc + wx / 2, -wy / 2, zb),
             (sc + wx / 2, wy / 2, zb), (sc - wx / 2, wy / 2, zb)]
        apex = (sc, 0.0, zb + h)
        mid = (sc, 0.0, zb + h / 3)
        self.face(c, (0.0, 0.0, -1.0), zone)
        for i in range(4):
            a, b = c[i], c[(i + 1) % 4]
            cen = ((a[0] + b[0] + apex[0]) / 3, (a[1] + b[1] + apex[1]) / 3,
                   (a[2] + b[2] + apex[2]) / 3)
            self.face([a, b, apex], (cen[0] - mid[0], cen[1] - mid[1],
                                      cen[2] - mid[2]), zone)

    def sphere(self, sc, zc, r, zone, nu=16, nv=8) -> None:
        def pt(i, j):
            th = math.pi * j / nv
            ph = 2 * math.pi * (i % nu) / nu
            return (sc + r * math.sin(th) * math.cos(ph),
                    r * math.sin(th) * math.sin(ph),
                    zc + r * math.cos(th))
        for j in range(nv):
            for i in range(nu):
                q = [pt(i, j), pt(i + 1, j), pt(i + 1, j + 1), pt(i, j + 1)]
                if j == 0:
                    q = [q[0], q[2], q[3]]
                elif j == nv - 1:
                    q = [q[0], q[1], q[2]]
                cx = sum(p[0] for p in q) / len(q) - sc
                cy = sum(p[1] for p in q) / len(q)
                cz = sum(p[2] for p in q) / len(q) - zc
                self.face(q, (cx, cy, cz), zone)

    def finish(self):
        if self.hidden:
            flag = getattr(muri, "EDGE_FLAG", "hidden")
            for e in self.mesh.edges:
                try:
                    k = frozenset(((round(e.a.x(), 4), round(e.a.y(), 4),
                                    round(e.a.z(), 4)),
                                   (round(e.b.x(), 4), round(e.b.y(), 4),
                                    round(e.b.z(), 4))))
                    if k in self.hidden:
                        setattr(e, flag, True)
                except Exception:
                    pass
        return self.mesh


def _strips(b, d, sa, sb, za, zb, y, zone, tin=None) -> None:
    if sb - sa < 0.004:
        return
    if tin is None:
        b.box(sa, sb, za, zb, -y, y, zone)
        return
    top = lambda s: min(zb, tin(s))
    n = max(1, min(80, math.ceil((sb - sa) / 0.05)))
    ss = [sa + (sb - sa) * k / n for k in range(n + 1)]
    if all(abs(top(s) - zb) < 1e-9 for s in ss):
        b.box(sa, sb, za, zb, -y, y, zone)
        return
    for k in range(n):
        p, q = ss[k], ss[k + 1]
        tp, tq = top(p), top(q)
        hp, hq = tp - za > 0.004, tq - za > 0.004
        if not hp and not hq:
            continue
        if hp and hq:
            ring = [(p, za), (q, za), (q, tq), (p, tp)]
            skip = set()
            if k < n - 1:
                skip.add(1)
            if k > 0:
                skip.add(3)
        elif hq:
            ring = [(p, za), (q, za), (q, tq)]
            skip = {1} if k < n - 1 else set()
        else:
            ring = [(p, za), (q, za), (p, tp)]
            skip = {2} if k > 0 else set()
        b.prism(ring, -y, y, zone, skip)


def _rail(b, d, sa, sb, lo, hi, y, zone="f") -> None:
    N = 1 if d.get("f", 0.0) < 0.005 else (ARC_STEPS * 2 if sb - sa > 1.0
                                            else ARC_STEPS)
    ss = [sa + (sb - sa) * k / N for k in range(N + 1)]
    for k in range(N):
        p, q = ss[k], ss[k + 1]
        skip = set()
        if k < N - 1:
            skip.add(1)
        if k > 0:
            skip.add(3)
        b.prism([(p, lo(p)), (q, lo(q)), (q, hi(q)), (p, hi(p))],
                -y, y, zone, skip)


def _circle(b, sc, zc, r, th, y) -> None:
    n = 16
    hl = r * math.sin(math.pi / n) * 1.15
    for i in range(n):
        a = 2 * math.pi * i / n
        cs, cz = sc + r * math.cos(a), zc + r * math.sin(a)
        ts, tz = -math.sin(a), math.cos(a)
        ns, nz = math.cos(a), math.sin(a)
        h = th / 2
        ring = [(cs - ts * hl - ns * h, cz - tz * hl - nz * h),
                (cs + ts * hl - ns * h, cz + tz * hl - nz * h),
                (cs + ts * hl + ns * h, cz + tz * hl + nz * h),
                (cs - ts * hl + ns * h, cz - tz * hl + nz * h)]
        b.prism(ring, -y, y, "p")


def _bars(b, d, sa, sb, zlo, spear, zlo_fn=None, ricci=False,
          zhi=None) -> None:
    L, fw, t = b.L, d["fw"], d["t"]
    top = _top_fn(d, L)
    wi = sb - sa
    m = max(1, math.ceil(wi / (d["gap"] + t) - 1e-9))
    for k in range(1, m):
        sc = sa + wi * k / m
        z0 = zlo_fn(sc) if zlo_fn else zlo
        ztop = top(sc) - fw if not spear else top(sc) + SPEAR_STEM
        if zhi is not None:
            ztop = zhi
        if ztop - z0 < 0.02:
            continue
        b.box(sc - t / 2, sc + t / 2, z0, ztop, -t / 2, t / 2, "p")
        if spear:
            b.pyramid(sc, ztop, t * 1.6, t * 1.6, SPEAR_H, "p")
    band = _band(d)
    if ricci and band > 0.04:
        pitch = wi / m
        r = min((pitch - t) / 2 * 0.92, band / 2 * 0.92)
        if r > 0.02:
            for k in range(m):
                sc = sa + pitch * (k + 0.5)
                zc = top(sc) - fw - band / 2
                _circle(b, sc, zc, r, max(0.008, t * 0.8), t / 2)


def _band_rail(b, d, sa, sb) -> None:
    band = _band(d)
    if band <= 0.04:
        return
    L, fw = b.L, d["fw"]
    top = _top_fn(d, L)
    fb = fw * 0.6
    _rail(b, d, sa, sb, lambda s: top(s) - fw - band - fb,
          lambda s: top(s) - fw - band, d["fd"] / 2 * 0.9)


def _leaf(b, d, s0, s1) -> None:
    L, fw, fd, c = b.L, d["fw"], d["fd"], d["c"]
    top = _top_fn(d, L)
    pt, style = d["pt"], d.get("style", "hslat")
    band = _band(d)
    y = fd / 2
    b.box(s0, s1, c, c + fw, -y, y, "f")
    _rail(b, d, s0, s1, lambda s: top(s) - fw, top, y)
    for sa, sb in ((s0, s0 + fw), (s1 - fw, s1)):
        b.prism([(sa, c + fw), (sb, c + fw), (sb, top(sb) - fw),
                 (sa, top(sa) - fw)], -y, y, "f")
    sa, sb = s0 + fw, s1 - fw
    zlo = c + fw
    pan = max(zlo + 0.05, min(d["pan"], d["h"] - 0.2))
    spear = bool(d.get("spear", True)) and style in ("bars", "mixed",
                                                       "panelarc")
    ricci = bool(d.get("ricci"))
    h2 = pt / 2
    fb = fw * 0.6
    if style == "hslat":
        tin = lambda s: top(s) - fw
        za = zlo + d["sg"]
        for _ in range(300):
            if tin(L / 2) - za < 0.02:
                break
            _strips(b, d, sa, sb, za, za + d["sl"], h2, "p", tin)
            za += d["sl"] + d["sg"]
        return
    if style == "bars":
        _band_rail(b, d, sa, sb)
        _bars(b, d, sa, sb, zlo, spear, ricci=ricci)
        return
    rz = fw / 2
    b.box(sa, sb, pan - rz, pan + rz, -y, y, "f")
    zl_hi = pan - rz
    if style in ("mixed", "panelarc") and d.get("low", "panel") == "panel" \
            or style == "mixed":
        _strips(b, d, sa, sb, zlo, zl_hi, h2, "p")
    elif style == "panelarc":
        _bars(b, d, sa, sb, zlo, False, zhi=zl_hi)
    else:
        n = max(1, math.ceil((sb - sa) / max(0.03, d["vw"])))
        w = (sb - sa) / n
        for i in range(n):
            _strips(b, d, sa + i * w + 0.002, sa + (i + 1) * w - 0.002,
                    zlo, zl_hi, h2, "p")
    if style == "panelarc":
        _band_rail(b, d, sa, sb)
        if band:
            ptop = lambda s: top(s) - fw - band - fb
        else:
            ptop = lambda s: top(s) - fw
        _strips(b, d, sa, sb, pan + rz, d["h"], h2, "p", ptop)
        if band:
            _bars(b, d, sa, sb, 0.0, spear,
                  zlo_fn=lambda s: top(s) - fw - band, ricci=ricci)
    else:
        _band_rail(b, d, sa, sb)
        _bars(b, d, sa, sb, pan + rz, spear, ricci=ricci)


def _pillar(b, d, sc) -> None:
    pw, pd, ph = d["pw"], d["pd"], d["ph"]
    ov, ch = 0.03, 0.05
    b.box(sc - pw / 2, sc + pw / 2, 0.0, ph, -pd / 2, pd / 2, "c")
    b.box(sc - pw / 2 - ov, sc + pw / 2 + ov, ph, ph + ch,
          -pd / 2 - ov, pd / 2 + ov, "c")
    cap = d.get("cap", "pyramid")
    if cap == "pyramid":
        b.pyramid(sc, ph + ch, pw, pd, 0.10, "c")
    elif cap == "sphere":
        r = max(0.03, min(pw, pd) / 2)
        b.sphere(sc, ph + ch + r, r, "c")


def gate_mesh(d):
    b = _Build(d)
    L = b.L
    if L < 1e-6:
        return b.mesh
    ang = math.radians(90.0 * max(0.0, min(100.0, float(d.get("open", 0.0))))
                       / 100.0) * (1 if int(d.get("opdir", 1)) >= 0 else -1)
    if int(d.get("leaves", 2)) >= 2 and L > 0.8:
        w = (L - CENTER_GAP) / 2
        b.hinge = (0.0, ang) if abs(ang) > 1e-9 else None
        _leaf(b, d, 0.0, w)
        b.hinge = (L, -ang) if abs(ang) > 1e-9 else None
        _leaf(b, d, L - w, L)
        b.hinge = None
        if abs(ang) < 1e-9:
            top = _top_fn(d, L)
            cw, fd = CENTER_POST, d["fd"] + 0.01
            b.box(L / 2 - cw / 2, L / 2 + cw / 2, d["c"], top(L / 2),
                  -fd / 2, fd / 2, "f")
    else:
        b.hinge = (0.0, ang) if abs(ang) > 1e-9 else None
        _leaf(b, d, 0.0, L)
        b.hinge = None
    if d.get("pl"):
        _pillar(b, d, -d["pw"] / 2)
    if d.get("pr"):
        _pillar(b, d, L + d["pw"] / 2)
    return b.finish()


def outline_lines(d):
    b = _Build(d)
    L = b.L
    if L < 1e-6:
        return []
    top = _top_fn(d, L)
    c, P = d["c"], b.P
    n = ARC_STEPS * 3 if d.get("f", 0.0) >= 0.005 else 1
    ss = [L * k / n for k in range(n + 1)]
    lines = [(P(0, 0, c), P(L, 0, c)), (P(0, 0, c), P(0, 0, top(0))),
             (P(L, 0, c), P(L, 0, top(L)))]
    for a, e in zip(ss, ss[1:]):
        lines.append((P(a, 0, top(a)), P(e, 0, top(e))))
    if int(d.get("leaves", 2)) >= 2:
        lines.append((P(L / 2, 0, c), P(L / 2, 0, top(L / 2))))
    for flag, sc in (("pl", -d["pw"] / 2), ("pr", L + d["pw"] / 2)):
        if d.get(flag):
            h, w = d["pw"] / 2, d["pd"] / 2
            pts = [P(sc - h, -w, 0), P(sc + h, -w, 0), P(sc + h, w, 0),
                   P(sc - h, w, 0)]
            for i in range(4):
                a, e = pts[i], pts[(i + 1) % 4]
                lines.append((a, e))
                lines.append((QVector3D(a.x(), a.y(), a.z() + d["ph"]),
                              QVector3D(e.x(), e.y(), e.z() + d["ph"])))
                lines.append((a, QVector3D(a.x(), a.y(), a.z() + d["ph"])))
    return lines


def gate_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "pts" in data else None


def rebuild_gate(group, d) -> None:
    from core.group import Group
    part = Group(gate_mesh(d), name=tr("Cancello"))
    part.component = False
    group.children = [part]
    _ifc.tag(group, "IfcRailing")
    ext = dict(group.ext or {})
    ext[KEY] = dict(d)
    group.ext = ext


def build_gate(scene, d, name):
    from core.group import Group
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    part = Group(gate_mesh(d), name=tr("Cancello"))
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


def _disegno_cancello(p):
    from PySide6.QtCore import QPointF
    r, t, dim = muri._r, muri._t, muri._dim
    t(p, 10, 12, tr("Prospetto"), size=9)
    p.setPen(QPen(muri._C_LINEA, 1.5))
    p.drawLine(QPointF(10, 150), QPointF(330, 150))
    muri._hatch(p, 10, 150, 330, 155)
    r(p, 12, 26, 44, 150, muri._C_CORPO)
    r(p, 8, 20, 48, 26, muri._C_CORPO)
    r(p, 54, 40, 304, 46, muri._C_CORPO)
    r(p, 54, 140, 304, 146, muri._C_CORPO)
    r(p, 54, 40, 60, 146, muri._C_CORPO)
    r(p, 298, 40, 304, 146, muri._C_CORPO)
    r(p, 176, 40, 182, 146, muri._C_CORPO)
    for k in range(10):
        y = 52 + 9 * k
        r(p, 62, y, 174, y + 6, muri._C_LEGNO)
        r(p, 184, y, 296, y + 6, muri._C_LEGNO)
    dim(p, 320, 40, 320, 150, "H", 1)
    dim(p, 40, 146, 40, 150, "c", -1)
    dim(p, 54, 166, 304, 166, "L", 1)
    dim(p, 306, 100, 306, 146, "p", 1)
    t(p, 350, 40, tr("H = altezza"), size=8)
    t(p, 350, 58, tr("c = distanza da terra"), size=8)
    t(p, 350, 76, tr("L = clic sui due punti"), size=8)
    t(p, 350, 94, tr("p = altezza parte piena"), size=8)


def _form(form, init, scene=None, with_level=False):
    w = {}
    w["h"] = _spin(init["h"], 0.5, 6.0)
    w["c"] = _spin(init["c"], 0.0, 1.0)
    w["style"] = QComboBox()
    for k, lab in STYLES:
        w["style"].addItem(lab, k)
    w["style"].setCurrentIndex(max(0, w["style"].findData(init["style"])))
    w["leaves"] = QComboBox()
    w["leaves"].addItem(tr("1 anta"), 1)
    w["leaves"].addItem(tr("2 ante"), 2)
    w["leaves"].setCurrentIndex(1 if int(init["leaves"]) >= 2 else 0)
    w["f"] = _spin(init["f"], 0.0, 1.5)
    w["fw"] = _spin(init["fw"], 0.01, 0.30)
    w["fd"] = _spin(init["fd"], 0.01, 0.30)
    w["pt"] = _spin(init["pt"], 0.003, 0.20)
    w["t"] = _spin(init["t"], 0.005, 0.10)
    w["gap"] = _spin(init["gap"], 0.02, 1.0)
    w["sl"] = _spin(init["sl"], 0.03, 0.60)
    w["sg"] = _spin(init["sg"], 0.003, 0.30)
    w["vw"] = _spin(init["vw"], 0.03, 0.50)
    w["pan"] = _spin(init["pan"], 0.2, 4.0)
    w["profile"] = QComboBox()
    for k, lab in PROFILES:
        w["profile"].addItem(lab, k)
    w["profile"].setCurrentIndex(max(0, w["profile"].findData(init["profile"])))
    w["low"] = QComboBox()
    for k, lab in LOWS:
        w["low"].addItem(lab, k)
    w["low"].setCurrentIndex(max(0, w["low"].findData(init["low"])))
    w["band"] = _spin(init["band"], 0.0, 1.5)
    w["open"] = _spin(init["open"], 0.0, 100.0)
    w["open"].setDecimals(0)
    w["open"].setSingleStep(5)
    w["opdir"] = QComboBox()
    w["opdir"].addItem(tr("Verso sinistra della direzione di tracciamento"), 1)
    w["opdir"].addItem(tr("Verso destra della direzione di tracciamento"), -1)
    w["opdir"].setCurrentIndex(0 if int(init["opdir"]) >= 0 else 1)
    w["ricci"] = QCheckBox(tr("Ricci tondi decorativi nella fascia"))
    w["ricci"].setChecked(bool(init["ricci"]))
    w["spear"] = QCheckBox(tr("Puntali sulle barre (ferro battuto)"))
    w["spear"].setChecked(bool(init["spear"]))
    w["cap"] = QComboBox()
    for k, lab in CAPS:
        w["cap"].addItem(lab, k)
    w["cap"].setCurrentIndex(max(0, w["cap"].findData(init.get("cap", "pyramid"))))
    w["pl"] = QCheckBox(tr("Pilastrino a sinistra (primo punto)"))
    w["pl"].setChecked(bool(init["pl"]))
    w["pr"] = QCheckBox(tr("Pilastrino a destra (secondo punto)"))
    w["pr"].setChecked(bool(init["pr"]))
    w["pw"] = _spin(init["pw"], 0.10, 1.0)
    w["pd"] = _spin(init["pd"], 0.10, 1.0)
    w["ph"] = _spin(init["ph"], 0.5, 6.0)
    form.addRow(muri._Schema(_disegno_cancello))
    lvl = None
    if with_level and scene is not None and piani.levels(scene):
        lvl = piani.level_combo(scene, piani.active_id(scene))
        form.addRow(tr("Piano (la quota resta quella dei punti cliccati)"), lvl)
    form.addRow(tr("Altezza cancello (H) (m)"), w["h"])
    form.addRow(tr("Distanza da terra (c) (m)"), w["c"])
    form.addRow(tr("Disegno"), w["style"])
    form.addRow(tr("Ante"), w["leaves"])
    form.addRow(tr("Apertura (0 = chiuso, 100 = aperto)"), w["open"])
    form.addRow(tr("Le ante si aprono"), w["opdir"])
    form.addRow(tr("Profilo superiore"), w["profile"])
    form.addRow(tr("Arco: freccia (0 = profilo dritto) (m)"), w["f"])
    form.addRow(tr("Telaio: larghezza tubolare (m)"), w["fw"])
    form.addRow(tr("Telaio: profondita' (m)"), w["fd"])
    form.addRow(tr("Spessore pannello / doghe (m)"), w["pt"])
    form.addRow(tr("Doghe orizzontali: altezza (m)"), w["sl"])
    form.addRow(tr("Doghe orizzontali: spazio tra le doghe (m)"), w["sg"])
    form.addRow(tr("Doghe verticali: larghezza (m)"), w["vw"])
    form.addRow(tr("Altezza parte bassa (p) (m)"), w["pan"])
    form.addRow(tr("Pannello ad arco: parte bassa"), w["low"])
    form.addRow(tr("Fascia di barre in alto: altezza (0 = nessuna) (m)"),
                w["band"])
    form.addRow(w["ricci"])
    form.addRow(tr("Barre: spessore (m)"), w["t"])
    form.addRow(tr("Barre: spazio libero (m)"), w["gap"])
    form.addRow(w["spear"])
    form.addRow(w["pl"])
    form.addRow(w["pr"])
    form.addRow(tr("Pilastrino: larghezza (m)"), w["pw"])
    form.addRow(tr("Pilastrino: profondita' (m)"), w["pd"])
    form.addRow(tr("Pilastrino: altezza da terra (m)"), w["ph"])
    form.addRow(tr("Pilastrino: sommita'"), w["cap"])

    def values() -> dict:
        v = {}
        for k, wd in w.items():
            if isinstance(wd, QDoubleSpinBox):
                v[k] = wd.value()
            elif isinstance(wd, QCheckBox):
                v[k] = wd.isChecked()
            else:
                v[k] = wd.currentData()
        return v

    return w, values, lvl


def ask_settings(parent, scene=None) -> bool:
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("Cancello"))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    _w, values, lvl = _form(form, _Settings.vals, scene, True)
    paint = muri.add_paint_rows(form, lambda k: _Settings.paint.get(k), ZONES)
    name = QLineEdit(_Settings.name)
    ortho = QCheckBox(tr("Ortogonale (O / F8 durante il disegno)"))
    ortho.setChecked(_Settings.ortho)
    form.addRow(tr("Nome"), name)
    form.addRow(ortho)
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return False
    _Settings.vals = values()
    _Settings.paint = muri.paint_results(paint)
    _Settings.ortho = ortho.isChecked()
    _Settings.name = name.text().strip() or tr("Cancello")
    _Settings.level = (lvl.currentData() or None) if lvl is not None else None
    if lvl is not None:
        piani.set_active(_Settings.level)
    return True


class CancelloTool(Tool):
    name = tr("Cancello")
    shortcut = None
    description = tr("Crea un cancello: clic su due punti in pianta.")

    def __init__(self) -> None:
        self._entering = False
        self._reset()

    def _reset(self) -> None:
        self.start = None
        self.hover = None

    def _ortho(self, p: QVector3D) -> QVector3D:
        if not (_Settings.ortho and self.start):
            return p
        s = self.start
        if abs(p.x() - s[0]) >= abs(p.y() - s[1]):
            return QVector3D(p.x(), s[1], p.z())
        return QVector3D(s[0], p.y(), p.z())

    def status_clause(self) -> str:
        return tr("Ortogonale {0} (O/F8) · Esc = esci").format(
            "ON" if _Settings.ortho else "OFF")

    def on_activate(self, viewport) -> None:
        if self._entering:
            self._reset()
            viewport.flash_status(
                tr("Cancello: clic sul primo e sul secondo punto · O/F8 = "
                   "ortogonale · Backspace = annulla · Esc = esci"), 6000)
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
        return self.start is not None and key == Qt.Key_Backspace

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if key in (Qt.Key_O, Qt.Key_F8):
            _Settings.ortho = not _Settings.ortho
            if self.hover is not None:
                self.hover = self._ortho(self.hover)
            viewport.flash_status(
                tr("Ortogonale ") + (tr("attivo") if _Settings.ortho
                                     else tr("disattivato")), 2000)
            viewport.update()
            return True
        if key == Qt.Key_Backspace and self.start is not None:
            self._reset()
            viewport.update()
            return True
        return False

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover = self._ortho(QVector3D(ctx.world))
        ctx.viewport.update()

    def _dict(self, a, b):
        d = dict(_Settings.vals)
        d["pts"] = [list(a), list(b)]
        d.update(_paint_dict())
        return d

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        if getattr(vp.scene, "edit_group", None) is not None:
            vp.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        q = self._ortho(QVector3D(ctx.world))
        p = (q.x(), q.y(), q.z())
        if self.start is None:
            self.start = p
            vp.update()
            return
        if math.hypot(p[0] - self.start[0], p[1] - self.start[1]) < MIN_LEN:
            vp.flash_status(tr("Cancello troppo corto"), 2500)
            return
        d = self._dict(self.start, p)
        name = _Settings.name
        lv = piani.get(vp.scene, _Settings.level)
        if lv:
            d.update({"lv": lv["id"], "lvn": lv["name"],
                      "off": min(self.start[2], p[2]) - lv["z"]})

        def mutate(scene):
            build_gate(scene, d, name)

        vp.history.execute(muri.MuriCommand(mutate))
        vp.notify_scene_changed()
        vp.flash_status(tr("Cancello creato · {0:.2f} m").format(
            gate_length(d)), 3500)
        self._reset()
        vp.update()

    def rubber_band_lines(self):
        if self.start is None or self.hover is None:
            return []
        h = self.hover
        if math.hypot(h.x() - self.start[0], h.y() - self.start[1]) < 0.05:
            return []
        return outline_lines(self._dict(self.start, (h.x(), h.y(), h.z())))


def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(90, 92, 98))
    p.drawRect(3, 6, 5, 36)
    p.drawRect(40, 6, 5, 36)
    p.drawRect(10, 12, 28, 26)
    p.drawLine(24, 12, 24, 38)
    for y in (18, 24, 30):
        p.drawLine(10, y, 38, y)
    p.end()
    return QIcon(pm)


def _selected_gates(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and gate_data(g) is not None and g not in out:
            out.append(g)
    return out


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


def edit_gates(viewport, groups=None) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    groups = [g for g in (groups or _selected_gates(scene))
              if gate_data(g) is not None]
    if not groups:
        viewport.flash_status(tr("Seleziona un cancello"), 3000)
        return
    first = gate_data(groups[0])
    init = {k: first.get(k, DEFAULTS[k]) for k in DEFAULTS}
    dlg = QDialog(viewport.window())
    dlg.setWindowTitle(tr("Modifica cancello") if len(groups) == 1
                       else tr("Modifica {0} cancelli").format(len(groups)))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    _w, values, _l = _form(form, init)
    paint = muri.add_paint_rows(form, first.get, ZONES)
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return
    changed = _changed(values(), init)
    paint_changed = {k: v for k, v in muri.paint_results(paint).items()
                     if v != first.get(k)}
    if not changed and not paint_changed:
        return

    def mutate(sc):
        for gg in groups:
            dd = gate_data(gg)
            if gg not in sc.groups or dd is None:
                continue
            nd = copy.deepcopy(dd)
            nd.update(changed)
            for k, v in paint_changed.items():
                if v:
                    nd[k] = v
                else:
                    nd.pop(k, None)
            rebuild_gate(gg, nd)

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("Cancello aggiornato"), 3000)


def _hook_double_click(vp) -> None:
    if getattr(vp, "_myhouse_cancello_dbl", False):
        return
    original = getattr(vp, "begin_group_edit", None)
    if original is None:
        return

    def begin_group_edit(group, *args, **kwargs):
        g = getattr(group, "owner", None) or group
        if gate_data(g) is None:
            return original(group, *args, **kwargs)
        scene = vp.scene
        try:
            scene.select([g])
        except Exception:
            scene.selection.clear()
            scene.selection.add(g)
        vp.update()
        QTimer.singleShot(0, lambda: edit_gates(vp, [g]))

    vp.begin_group_edit = begin_group_edit
    vp._myhouse_cancello_dbl = True


def _outliner_kind(group):
    d = gate_data(group)
    if d is None:
        return None
    from ._imperial import fmt_len
    return {"type": tr("Cancello"),
            "props": [(tr("Altezza"), fmt_len(d["h"])),
                      (tr("Larghezza"), fmt_len(gate_length(d))),
                      (tr("Ante"), str(int(d.get("leaves", 2))))]
            + piani.level_props(d)}


def _register_level_kind() -> None:
    def zget(d):
        return min(p[2] for p in d["pts"])

    def zset(d, z):
        delta = z - zget(d)
        d["pts"] = [[p[0], p[1], p[2] + delta] for p in d["pts"]]

    piani.register_kind("cancello", KEY, gate_data, zget, zset, rebuild_gate)


def register(api) -> None:
    _register_level_kind()
    try:
        _hook_double_click(api.window.viewport)
    except Exception:
        pass
    add_ctx = getattr(api.app, "add_context_menu", None)
    if add_ctx is not None:
        def context(menu, selection) -> None:
            if not _selected_gates(api.app.viewport.scene):
                return
            menu.addSeparator()
            menu.addAction(
                tr("Modifica cancello…"),
                lambda: QTimer.singleShot(
                    0, lambda: edit_gates(api.app.viewport)))

        add_ctx(context)
    api.add_button(tr("Cancello"),
                   tr("Crea un cancello (doghe, ferro battuto, pannello, arco, pilastrini)"),
                   _icon(), api.run_tool(CancelloTool()), group="Balaustre")
    add_kind = getattr(api.app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
