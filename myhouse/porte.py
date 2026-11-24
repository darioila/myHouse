# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr
from ._scroll import scroll_form

import copy
import math

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor, QFont, QMatrix4x4, QPainter, QPen, QPolygonF, QVector3D,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QVBoxLayout, QWidget,
)

from core import bim
from . import _ifc
from ._imperial import FT, IN, dflt, fmt_len, imperial
from tools.base import Tool, ToolContext

from . import _codici, _tipi, finestre, muri, piani
from ._strati import HatchPick, doorwin_hatch
from .finestre import FinestraCommand

KEY = "myhouse_porta"
LAYER_NAME = "Porte"
FRAME_COLOR = (0.93, 0.93, 0.90)
LEAF_COLOR = (0.66, 0.49, 0.33)
MODELS = [("porta", tr("Porta")),
          ("varco", tr("Varco (solo foro, senza porta)")),
          ("porta1", tr("Porta 1 (vetro lungo)")),
          ("porta2", tr("Porta 2 (5 vetri orizzontali)")),
          ("porta3", tr("Porta 3 (strisce metalliche)")),
          ("porta4", tr("Porta 4 (vetro diviso in due)")),
          ("porta5", tr("Porta 5 (12 vetri e pannello)")),
          ("porta6", tr("Porta 6 (5 specchiature)")),
          ("porta7", tr("Porta 7 (2 specchiature)")),
          ("porta8", tr("Porta 8 (8 vetri)")),
          ("bifold", tr("A libro (armadio), singola o doppia")),
          ("garage1", tr("Garage 1 (basculante a coste)")),
          ("garage2", tr("Garage 2 (sezionale a pannelli)"))]
HANDLE_KINDS = (("lever", tr("Leva con rosetta quadra")),
                ("lever_round", tr("Leva curva con rosetta tonda e bocchetta chiave")),
                ("knob", tr("Pomolo con cilindro serratura")),
                ("pull", tr("Maniglione a barra")))
SLIDE_HANDLE_KINDS = (("slide_rect", tr("Incasso rettangolare (scorrevole)")),
                      ("slide_round", tr("Incasso tondo (scorrevole)")))
SLIDE_HANDLE_KEYS = tuple(k for k, _ in SLIDE_HANDLE_KINDS)
ARCH_KINDS = (("none", tr("Rettangolare")),
              ("full", tr("Arco a tutto sesto")),
              ("low", tr("Arco ribassato")))
GARAGE_SIZE = (dflt(9 * FT, 2.50), dflt(7 * FT, 2.20))
GLASS_COLOR = (0.75, 0.85, 0.90)
METAL_COLOR = (0.75, 0.75, 0.78)
DEFAULT_PAINT = {"frame": (0.95, 0.95, 0.92),
                 "glass": (0.70, 0.85, 0.95),
                 "handle": (0.72, 0.72, 0.75),
                 "leaf": (0.66, 0.49, 0.33)}
ZONE_NAME = {"frame": tr("telaio porta"), "leaf": tr("anta porta"),
             "glass": tr("vetro porta"), "handle": tr("maniglia porta")}


SHOW_HELP_BOX = False


def _paint_res(paint) -> dict:
    res = muri.paint_results(paint)
    for zone, dflt in DEFAULT_PAINT.items():
        c = res.get("col_" + zone)
        if res.get("tex_" + zone) and c and tuple(c) == tuple(dflt):
            res["col_" + zone] = None
    return res
GLASS = {
    "porta1": (0.15, [(0.07, 0.92)]),
    "porta4": (0.15, [(0.07, 0.48), (0.558, 0.92)]),
    "porta2": (0.17, [(0.071, 0.132), (0.268, 0.329), (0.464, 0.525),
                      (0.663, 0.724), (0.863, 0.924)]),
}
GRID = {
    "porta5": dict(mg=0.12, top=0.05, bot=0.68, cols=3, rows=4, mull=0.025,
                   panels=[(0.12, 0.88, 0.74, 0.95)]),
    "porta8": dict(mg=0.13, top=0.05, bot=0.95, cols=2, rows=4, mull=0.03,
                   panels=[]),
}
PANELS = {
    "porta6": [(0.14, 0.47, 0.05, 0.46), (0.53, 0.86, 0.05, 0.46),
               (0.14, 0.86, 0.50, 0.55),
               (0.14, 0.47, 0.60, 0.95), (0.53, 0.86, 0.60, 0.95)],
    "porta7": [(0.14, 0.86, 0.06, 0.50), (0.14, 0.86, 0.55, 0.95)],
}
STRIPS = [0.071, 0.186, 0.292, 0.397, 0.502, 0.607, 0.712, 0.818, 0.923]
ORDER = 30
GAP = 0.003                      # play between leaf and frame, each side


def _panels(model: str, leaves) -> int:
    """How many panels stand side by side in the frame. A bi-fold is two
    hinged panels for each leaf: 2 single, 4 dual (a closet front)."""
    if model == "bifold":
        return 2 * int(leaves)
    return int(leaves) if model == "porta" else 1


def _no_arch(model) -> bool:
    """Models whose top is always square."""
    return str(model).startswith("garage") or model == "bifold"


def _around(model: str, leaves, fw: float):
    """What the frame adds around the door itself: (in width, in height).
    A plain opening and a door without a frame add nothing."""
    if model == "varco" or fw < 0.005:
        return 0.0, 0.0
    return 2 * fw + 2 * GAP * _panels(model, leaves), fw + 2 * GAP


def door_size(d: dict):
    """(width, height) of the door itself, the slab, without the frame: a
    30" door is 30" wide here, and its frame sits outside that. The stored
    W and H are the whole unit, frame included (that is the hole in the wall)."""
    aw, ah = _around(d.get("model", "porta"), d["leaves"], d["fw"])
    return d["W"] - aw, d["H"] - ah

PAINT_KEYS = ("col_frame", "tex_frame", "col_leaf", "tex_leaf",
              "col_glass", "tex_glass", "col_handle", "tex_handle")
DOOR_ZONES = (("leaf", tr("anta e telaio")),
              ("glass", tr("vetro (modelli con vetri)")),
              ("handle", tr("maniglie e ferramenta")))


class _Settings:
    fw = dflt(0.75 * IN, 0.06)             # 3/4" jamb
    # W and H are the whole unit, frame included; in feet and inches a 3068
    # door (slab 3'0" x 6'8") with its frame around it
    W = dflt(36 * IN + 2 * fw + 2 * GAP, 0.90)
    H = dflt(80 * IN + fw + 2 * GAP, 2.10)
    sill = 0.0
    leaves = 1
    asym = False
    w1 = 0.0
    fd = dflt(4.5625 * IN, 0.12)           # 4 9/16" jamb depth
    sw = dflt(1.75 * IN, 0.04)
    model = "porta"
    arch = "none"
    arch_h = 0.30
    handle = "lever"
    slide = False
    open = 0.0
    flip = False
    mid = False             # held by the middle (Space: left, middle, right)
    rev = False             # reversed while placing: handle on the other side
    level = None
    col_frame = list(DEFAULT_PAINT["frame"])
    tex_frame = None
    col_leaf = list(DEFAULT_PAINT["leaf"])
    tex_leaf = None
    col_glass = list(DEFAULT_PAINT["glass"])
    tex_glass = None
    col_handle = list(DEFAULT_PAINT["handle"])
    tex_handle = None
    hatch = None
    tipo_id = None
    tipo_nome = None


def settings_paint() -> dict:
    return {k: copy.deepcopy(getattr(_Settings, k, None))
            for k in PAINT_KEYS if getattr(_Settings, k, None)}


def _params() -> dict:
    p = _params_geom()
    p.update(settings_paint())
    if _Settings.hatch:
        p["hatch"] = copy.deepcopy(_Settings.hatch)
    return p


def _params_geom() -> dict:
    return {"W": _Settings.W, "H": _Settings.H, "sill": _Settings.sill,
            "leaves": _Settings.leaves, "fw": _Settings.fw,
            "fd": _Settings.fd, "sw": _Settings.sw,
            "model": _Settings.model,
            "asym": bool(_Settings.asym and _Settings.leaves == 2
                         and _Settings.model == "porta"),
            "w1": _Settings.w1,
            "arch": ("none" if _no_arch(_Settings.model)
                     else _Settings.arch),
            "arch_h": _Settings.arch_h, "handle": _Settings.handle,
            "slide": bool(_Settings.slide), "open": float(_Settings.open),
            "tipo_id": _Settings.tipo_id, "tipo_nome": _Settings.tipo_nome}


def _store(p: dict) -> None:
    _Settings.handle = p.get("handle", "lever")
    _Settings.slide, _Settings.open = bool(p.get("slide")), float(p.get("open") or 0.0)
    _Settings.W, _Settings.H, _Settings.sill = p["W"], p["H"], p["sill"]
    _Settings.leaves, _Settings.fw = p["leaves"], p["fw"]
    _Settings.fd, _Settings.sw = p["fd"], p["sw"]
    _Settings.model = p.get("model", "porta")
    _Settings.asym, _Settings.w1 = bool(p.get("asym")), p.get("w1", 0.0)
    _Settings.arch, _Settings.arch_h = p.get("arch", "none"), p.get("arch_h", 0.30)
    for k in PAINT_KEYS:
        setattr(_Settings, k, p.get(k))
    _Settings.hatch = copy.deepcopy(p.get("hatch")) or None
    _Settings.tipo_id, _Settings.tipo_nome = p.get("tipo_id"), p.get("tipo_nome")


def arch_rise(d: dict) -> float:
    if _no_arch(d.get("model", "porta")):
        return 0.0
    kind = d.get("arch", "none")
    if kind == "full":
        return d["W"] / 2.0
    if kind == "low":
        return min(max(float(d.get("arch_h") or 0.0), 0.0), d["W"] / 2.0)
    return 0.0


def validate(p: dict) -> str | None:
    if p["W"] <= 2 * p["fw"] + 0.2 * p["leaves"]:
        return tr("Larghezza troppo piccola per telaio e ante")
    if p.get("asym") and int(p["leaves"]) == 2:
        w1 = p.get("w1", 0.0)
        if w1 < 0.2 or p["W"] - 2 * p["fw"] - w1 < 0.2:
            return tr("Le ante asimmetriche devono essere larghe almeno 20 cm")
    if p["H"] <= p["fw"] + 0.3:
        return tr("Altezza troppo piccola per telaio e anta")
    if arch_rise(p) > 0 and p["H"] - arch_rise(p) < 0.1:
        return tr("Altezza troppo piccola per l'arco")
    if arch_rise(p) > 0 and p["H"] - arch_rise(p) < p["fw"] + 0.5:
        return tr("Arco troppo alto rispetto all'altezza della porta")
    if p["sw"] >= p["fd"]:
        return tr("L'anta deve essere più sottile del telaio")
    return None


def _box(mesh, T, a0, a1, b0, b1, c0, c1, color):
    quads = [
        [(a0, b0, c0), (a0, b0, c1), (a0, b1, c1), (a0, b1, c0)],
        [(a1, b0, c0), (a1, b1, c0), (a1, b1, c1), (a1, b0, c1)],
        [(a0, b0, c0), (a1, b0, c0), (a1, b0, c1), (a0, b0, c1)],
        [(a0, b1, c0), (a0, b1, c1), (a1, b1, c1), (a1, b1, c0)],
        [(a0, b0, c0), (a0, b1, c0), (a1, b1, c0), (a1, b0, c0)],
        [(a0, b0, c1), (a1, b0, c1), (a1, b1, c1), (a0, b1, c1)],
    ]
    for q in quads:
        f = mesh.add_face([T(*v) for v in q])
        f.attrs["layer"] = LAYER_NAME


def _arch_strip(mesh, T, W, zs, f, fw, b0, b1) -> None:
    R = (W * W / 4.0 + f * f) / (2.0 * f)
    cz = zs + f - R
    n = max(8, min(48, int(math.ceil(W / 0.05))))
    th_r = math.atan2(zs - cz, W / 2.0)
    th_l = math.pi - th_r
    O, I = [], []
    for i in range(n + 1):
        th = th_l + (th_r - th_l) * i / n
        O.append((W / 2.0 + R * math.cos(th), cz + R * math.sin(th)))
        I.append((W / 2.0 + (R - fw) * math.cos(th), cz + (R - fw) * math.sin(th)))

    def add(q) -> None:
        fc = mesh.add_face([T(*v) for v in q])
        fc.attrs["layer"] = LAYER_NAME

    def p(pt, b):
        return (pt[0], b, pt[1])

    for i in range(n):
        o0, o1, i0, i1 = O[i], O[i + 1], I[i], I[i + 1]
        add([p(o0, b1), p(o1, b1), p(i1, b1), p(i0, b1)])
        add([p(i0, b0), p(i1, b0), p(o1, b0), p(o0, b0)])
        add([p(o0, b0), p(o1, b0), p(o1, b1), p(o0, b1)])
        add([p(i0, b0), p(i0, b1), p(i1, b1), p(i1, b0)])
    add([p(I[0], b0), p(O[0], b0), p(O[0], b1), p(I[0], b1)])
    add([p(I[n], b0), p(I[n], b1), p(O[n], b1), p(O[n], b0)])


def _arch_cap(mesh, T, W, x0, x1, zb, cz, Rc, b0, b1) -> None:
    n = max(8, min(40, int(math.ceil((x1 - x0) / 0.04))))
    tp = []
    for i in range(n + 1):
        x = x0 + (x1 - x0) * i / n
        tp.append((x, cz + math.sqrt(max(Rc * Rc - (x - W / 2.0) ** 2, 0.0))))

    def add(q) -> None:
        f = mesh.add_face([T(*v) for v in q])
        f.attrs["layer"] = LAYER_NAME

    add([(x0, b1, zb)] + [(x, b1, z) for x, z in tp] + [(x1, b1, zb)])
    add([(x1, b0, zb)] + [(x, b0, z) for x, z in reversed(tp)] + [(x0, b0, zb)])
    for i in range(n):
        (xa, za), (xb, zb2) = tp[i], tp[i + 1]
        add([(xa, b0, za), (xb, b0, zb2), (xb, b1, zb2), (xa, b1, za)])
    add([(x0, b0, zb), (x0, b0, tp[0][1]), (x0, b1, tp[0][1]), (x0, b1, zb)])
    add([(x1, b0, zb), (x1, b1, zb), (x1, b1, tp[-1][1]), (x1, b0, tp[-1][1])])


def _garage1(leaf, T, d, hw=None) -> None:
    W, H, fw, sw = d["W"], d["H"], d["fw"], d["sw"]
    x0, x1 = fw + 0.003, W - fw - 0.003
    z0, z1 = 0.003, H - fw - 0.003
    b0, b1 = sw / 2, sw / 2 + 0.008
    pitch = 0.10
    n = max(1, int(round((x1 - x0) / pitch)))
    step = (x1 - x0) / n
    for i in range(1, n):
        x = x0 + i * step
        _box(leaf, T, x - 0.006, x + 0.006, b0, b1, z0, z1, LEAF_COLOR)
    zh = 0.12
    for zc in (z1 - 0.12, z0 + 0.12):
        for i in range(n):
            xc = x0 + (i + 0.5) * step
            for k in range(3):
                zz = zc - zh / 2 + k * zh / 3
                _box(leaf, T, xc - 0.025, xc + 0.025, b0, b1 + 0.006,
                     zz, zz + 0.02, LEAF_COLOR)
    xm, zm = (x0 + x1) / 2, (z0 + z1) / 2
    hm = hw if hw is not None else leaf
    _box(hm, T, xm - 0.04, xm + 0.04, b1, b1 + 0.03,
         zm - 0.01, zm + 0.01, LEAF_COLOR)
    _box(hm, T, xm - 0.01, xm + 0.01, b1, b1 + 0.03,
         zm - 0.06, zm + 0.06, LEAF_COLOR)
    _box(hm, T, xm - 0.04, xm + 0.04, b1, b1 + 0.03,
         z0 + 0.20, z0 + 0.22, LEAF_COLOR)


def _garage2(leaf, T, d) -> None:
    W, H, fw, sw = d["W"], d["H"], d["fw"], d["sw"]
    x0, x1 = fw + 0.003, W - fw - 0.003
    z0, z1 = 0.003, H - fw - 0.003
    b0 = sw / 2
    n = max(2, int(round((z1 - z0) / 0.20)))
    step = (z1 - z0) / n
    for i in range(n):
        za = z0 + i * step + 0.006
        zb = z0 + (i + 1) * step - 0.006
        _box(leaf, T, x0, x1, b0, b0 + 0.008, za, zb, LEAF_COLOR)


def _cyl(mesh, T, cx, cz, r, b0, b1, n=14) -> None:
    pts = [(cx + r * math.cos(2 * math.pi * i / n),
            cz + r * math.sin(2 * math.pi * i / n)) for i in range(n)]
    for i in range(n):
        p0, p1 = pts[i], pts[(i + 1) % n]
        f = mesh.add_face([T(p0[0], b0, p0[1]), T(p0[0], b1, p0[1]),
                           T(p1[0], b1, p1[1]), T(p1[0], b0, p1[1])])
        f.attrs["layer"] = LAYER_NAME
    f = mesh.add_face([T(x, b1, z) for x, z in reversed(pts)])
    f.attrs["layer"] = LAYER_NAME
    f = mesh.add_face([T(x, b0, z) for x, z in pts])
    f.attrs["layer"] = LAYER_NAME


def _tube(mesh, T, path, radii, n=14) -> None:
    def sub(a, b):
        return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

    def cross(a, b):
        return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
                a[0] * b[1] - a[1] * b[0])

    def norm(a):
        m = math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2) or 1.0
        return (a[0] / m, a[1] / m, a[2] / m)

    rings = []
    last = len(path) - 1
    for i, (P, r) in enumerate(zip(path, radii)):
        a, b = path[max(0, i - 1)], path[min(last, i + 1)]
        tg = norm(sub(b, a))
        u = norm(cross(tg, (0.0, 0.0, 1.0)))
        v = cross(tg, u)
        rings.append([(P[0] + r * (math.cos(2 * math.pi * k / n) * u[0]
                                   + math.sin(2 * math.pi * k / n) * v[0]),
                       P[1] + r * (math.cos(2 * math.pi * k / n) * u[1]
                                   + math.sin(2 * math.pi * k / n) * v[1]),
                       P[2] + r * (math.cos(2 * math.pi * k / n) * u[2]
                                   + math.sin(2 * math.pi * k / n) * v[2]))
                      for k in range(n)])
    for i in range(last):
        c0, c1 = path[i], path[i + 1]
        for k in range(n):
            k2 = (k + 1) % n
            q = [rings[i][k], rings[i + 1][k], rings[i + 1][k2], rings[i][k2]]
            nrm = cross(sub(q[1], q[0]), sub(q[3], q[0]))
            mid = tuple(sum(p[j] for p in q) / 4 - (c0[j] + c1[j]) / 2
                        for j in range(3))
            if sum(nrm[j] * mid[j] for j in range(3)) < 0:
                q.reverse()
            f = mesh.add_face([T(*p) for p in q])
            f.attrs["layer"] = LAYER_NAME


def _vbar(mesh, T, cx, cy, r, z0, z1, n=24) -> None:
    bv = 0.004
    rings = [(z0, r * 0.80), (z0 + bv, r), (z1 - bv, r), (z1, r * 0.80)]
    pts = [[(cx + rr * math.cos(2 * math.pi * k / n),
             cy + rr * math.sin(2 * math.pi * k / n), zz) for k in range(n)]
           for zz, rr in rings]

    def add(q, c):
        a = [q[1][i] - q[0][i] for i in range(3)]
        b = [q[-1][i] - q[0][i] for i in range(3)]
        nr = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
              a[0] * b[1] - a[1] * b[0])
        m = [sum(p[i] for p in q) / len(q) - c[i] for i in range(3)]
        if sum(nr[i] * m[i] for i in range(3)) < 0:
            q = q[::-1]
        f = mesh.add_face([T(*p) for p in q])
        f.attrs["layer"] = LAYER_NAME

    zm = (z0 + z1) / 2
    for i in range(len(rings) - 1):
        for k in range(n):
            k2 = (k + 1) % n
            add([pts[i][k], pts[i + 1][k], pts[i + 1][k2], pts[i][k2]],
                (cx, cy, zm))
    add(pts[0], (cx, cy, zm))
    add(pts[-1], (cx, cy, zm))


def _handle_kind(hw, T, x, zc, sw, dr, ln, kind) -> None:
    for s in (1, -1):
        inn, out = s * sw / 2, s * (sw / 2 + 0.05)

        def box(a0, a1, c0, c1, p, q):
            _box(hw, T, a0, a1, min(p, q), max(p, q), c0, c1, METAL_COLOR)

        def cyl(cx, cz, r, p, q):
            _cyl(hw, T, cx, cz, r, min(p, q), max(p, q))

        rs = s * (sw / 2 + 0.012)
        if kind == "lever_round":
            cyl(x, zc, 0.032, inn, rs)
            cyl(x, zc, 0.027, rs, s * (sw / 2 + 0.016))
            R, r0, r1 = 0.032, 0.012, 0.0175
            ya = s * (sw / 2 + 0.016)
            cx_ = x - dr * R
            path, rad = [(x, s * (sw / 2 + 0.006), zc)], [r0]
            for k in range(0, 11):
                t = (math.pi / 2) * k / 10
                path.append((cx_ + dr * R * math.cos(t),
                             ya + s * R * math.sin(t), zc))
                rad.append(r0 + 0.001 * math.sin(t))
            yl = ya + s * R
            xs, xe = cx_, x - dr * max(ln, 0.10)
            L = abs(xe - xs)
            for k in range(1, 9):
                f = k / 8
                path.append((xs + (xe - xs) * f, yl, zc))
                rad.append(0.013 + (r1 - 0.013) * math.sin(f * math.pi * 0.5) ** 1.5)
            for k in range(1, 7):
                a = (math.pi / 2) * k / 6
                path.append((xe + (-dr) * r1 * math.sin(a) * 1.4, yl, zc))
                rad.append(max(0.0008, r1 * math.cos(a)))
            _tube(hw, T, path, rad)
            cyl(x, zc - 0.085, 0.026, inn, rs)
            cyl(x, zc - 0.085, 0.0075, rs, s * (sw / 2 + 0.014))
        elif kind == "knob":
            cyl(x, zc, 0.037, inn, rs)
            cyl(x, zc, 0.031, rs, s * (sw / 2 + 0.017))
            cyl(x, zc, 0.013, s * (sw / 2 + 0.015), s * (sw / 2 + 0.03))
            yc, ya, Rm = sw / 2 + 0.050, 0.030, 0.033
            path, rad = [(x, s * (sw / 2 + 0.026), zc)], [0.013]
            th0 = math.acos(-0.8)
            for k in range(0, 17):
                th = th0 * (1 - k / 16)
                path.append((x, s * (yc + ya * math.cos(th)), zc))
                rad.append(max(0.0008, Rm * math.sin(th)))
            _tube(hw, T, path, rad, n=24)
        elif kind == "pull":
            hl, rb, rp = 0.30, 0.016, 0.011
            yb = s * (sw / 2 + 0.065)
            for zz in (zc - hl + 0.07, zc + hl - 0.07):
                cyl(x, zz, rp, inn, yb)
            _vbar(hw, T, x, yb, rb, zc - hl, zc + hl)


def _ring(mesh, T, cx, cz, r_out, r_in, b_in, b_out, b_floor, n=24) -> None:
    sgn = 1 if b_out >= b_in else -1
    po = [(cx + r_out * math.cos(2 * math.pi * i / n),
           cz + r_out * math.sin(2 * math.pi * i / n)) for i in range(n)]
    pi_ = [(cx + r_in * math.cos(2 * math.pi * i / n),
            cz + r_in * math.sin(2 * math.pi * i / n)) for i in range(n)]

    def face(q):
        if sgn < 0:
            q = q[::-1]
        f = mesh.add_face([T(x, y, z) for x, y, z in q])
        f.attrs["layer"] = LAYER_NAME

    for i in range(n):
        j = (i + 1) % n
        face([(po[i][0], b_in, po[i][1]), (po[i][0], b_out, po[i][1]),
              (po[j][0], b_out, po[j][1]), (po[j][0], b_in, po[j][1])])
        face([(po[i][0], b_out, po[i][1]), (pi_[i][0], b_out, pi_[i][1]),
              (pi_[j][0], b_out, pi_[j][1]), (po[j][0], b_out, po[j][1])])
        face([(pi_[i][0], b_out, pi_[i][1]), (pi_[i][0], b_floor, pi_[i][1]),
              (pi_[j][0], b_floor, pi_[j][1]), (pi_[j][0], b_out, pi_[j][1])])
    face([(x, b_floor, z) for x, z in pi_])


def _handle_slide(hw, T, x, zc, sw, kind) -> None:
    for s in (1, -1):
        inn = s * sw / 2
        out = s * (sw / 2 + 0.006)
        flo = s * (sw / 2 + 0.0015)
        if kind == "slide_round":
            _ring(hw, T, x, zc, 0.027, 0.0215, inn, out, flo)
            continue
        w2, h2, t = 0.020, 0.075, 0.0075
        p0, p1 = min(inn, out), max(inn, out)
        _box(hw, T, x - w2, x + w2, p0, p1, zc - h2, zc - h2 + t, METAL_COLOR)
        _box(hw, T, x - w2, x + w2, p0, p1, zc + h2 - t, zc + h2, METAL_COLOR)
        _box(hw, T, x - w2, x - w2 + t, p0, p1, zc - h2 + t, zc + h2 - t,
             METAL_COLOR)
        _box(hw, T, x + w2 - t, x + w2, p0, p1, zc - h2 + t, zc + h2 - t,
             METAL_COLOR)
        f0, f1 = min(inn, flo), max(inn, flo)
        _box(hw, T, x - w2 + t, x + w2 - t, f0, f1, zc - h2 + t, zc + h2 - t,
             METAL_COLOR)


def _handle(hw, T, x, zc, sw, dr=1, ln=0.14, kind="lever") -> None:
    if kind in SLIDE_HANDLE_KEYS:
        _handle_slide(hw, T, x, zc, sw, kind)
        return
    if kind != "lever":
        _handle_kind(hw, T, x, zc, sw, dr, ln, kind)
        return
    for s in (1, -1):
        inn, out = s * sw / 2, s * (sw / 2 + 0.05)
        rs = s * (sw / 2 + 0.01)

        def box(a0, a1, c0, c1, p, q):
            _box(hw, T, a0, a1, min(p, q), max(p, q), c0, c1, METAL_COLOR)

        lv0, lv1 = sorted((x - dr * ln, x + dr * 0.015))
        box(x - 0.03, x + 0.03, zc - 0.03, zc + 0.03, inn, rs)
        box(x - 0.015, x + 0.015, zc - 0.012, zc + 0.012, inn, out)
        box(lv0, lv1, zc - 0.012, zc + 0.012,
            out - s * 0.02, out)
        box(x - 0.012, x + 0.012, zc - 0.085, zc - 0.06, inn, rs)


def _knob(hw, T, x, zc, sw) -> None:
    """The pull of a bi-fold panel, on the front face only."""
    _box(hw, T, x - 0.008, x + 0.008, sw / 2, sw / 2 + 0.02,
         zc - 0.008, zc + 0.008, METAL_COLOR)
    _box(hw, T, x - 0.018, x + 0.018, sw / 2 + 0.02, sw / 2 + 0.035,
         zc - 0.018, zc + 0.018, METAL_COLOR)


def _glass_leaf(model, leaf, glass, T, a0, a1, z0, z1, sw) -> None:
    mg, bands = GLASS[model]
    wl, hl = a1 - a0, z1 - z0
    gx0, gx1 = a0 + mg * wl, a1 - mg * wl
    b0, b1 = -sw / 2, sw / 2
    _box(leaf, T, a0, gx0, b0, b1, z0, z1, LEAF_COLOR)
    _box(leaf, T, gx1, a1, b0, b1, z0, z1, LEAF_COLOR)
    cur = z0
    for top, bot in sorted(bands, key=lambda t: -t[1]):
        zb, zt = z1 - bot * hl, z1 - top * hl
        if zb > cur:
            _box(leaf, T, gx0, gx1, b0, b1, cur, zb, LEAF_COLOR)
        _box(glass, T, gx0, gx1, -sw * 0.15, sw * 0.15, zb, zt,
             GLASS_COLOR)
        cur = zt
    if cur < z1:
        _box(leaf, T, gx0, gx1, b0, b1, cur, z1, LEAF_COLOR)


def _raised_panels(leaf, T, panels, a0, a1, z0, z1, sw) -> None:
    wl, hl = a1 - a0, z1 - z0
    for x0f, x1f, tf, bf in panels:
        x0, x1 = a0 + x0f * wl, a0 + x1f * wl
        zb, zt = z1 - bf * hl, z1 - tf * hl
        _box(leaf, T, x0, x1, sw / 2, sw / 2 + 0.008, zb, zt, LEAF_COLOR)
        _box(leaf, T, x0, x1, -sw / 2 - 0.008, -sw / 2, zb, zt, LEAF_COLOR)


def _grid_leaf(model, leaf, glass, T, a0, a1, z0, z1, sw) -> None:
    g = GRID[model]
    wl, hl = a1 - a0, z1 - z0
    gx0, gx1 = a0 + g["mg"] * wl, a1 - g["mg"] * wl
    zt, zb = z1 - g["top"] * hl, z1 - g["bot"] * hl
    b0, b1 = -sw / 2, sw / 2
    _box(leaf, T, a0, gx0, b0, b1, z0, z1, LEAF_COLOR)
    _box(leaf, T, gx1, a1, b0, b1, z0, z1, LEAF_COLOR)
    _box(leaf, T, gx0, gx1, b0, b1, z0, zb, LEAF_COLOR)
    _box(leaf, T, gx0, gx1, b0, b1, zt, z1, LEAF_COLOR)
    _box(glass, T, gx0, gx1, -sw * 0.15, sw * 0.15, zb, zt, GLASS_COLOR)
    m = g["mull"] / 2
    cw, ch = (gx1 - gx0) / g["cols"], (zt - zb) / g["rows"]
    for i in range(1, g["cols"]):
        x = gx0 + i * cw
        _box(leaf, T, x - m, x + m, b0, b1, zb, zt, LEAF_COLOR)
    for j in range(1, g["rows"]):
        z = zb + j * ch
        _box(leaf, T, gx0, gx1, b0, b1, z - m, z + m, LEAF_COLOR)
    _raised_panels(leaf, T, g["panels"], a0, a1, z0, z1, sw)


def door_meshes(d: dict):
    return door_meshes_all(d)[:2]


def door_meshes_all(d: dict):
    return tuple(m.mesh for m in _door_meshes_raw(d))


def can_open(d: dict) -> bool:
    m = str(d.get("model", "porta"))
    return m not in ("varco", "bifold") and not m.startswith("garage")


def _leaf_T(T, d, i, a_start, wi, n, fw, gap):
    op = float(d.get("open") or 0.0)
    if not can_open(d) or abs(op) < 1e-9:
        return T
    if d.get("slide"):
        shift = min(max(op, 0.0), 100.0) / 100.0 * (wi + fw + 0.02)
        sg = -1.0 if (n == 1 or i == 0) else 1.0
        return lambda a, b, c: T(a + sg * shift, b, c)
    th = math.radians(min(max(op, -120.0), 120.0))
    if i == 0:
        ha, phi = a_start + gap, th
    else:
        ha, phi = a_start + wi - gap, -th
    cs, sn = math.cos(phi), math.sin(phi)
    y0 = math.copysign(float(d.get("sw") or 0.0) / 2.0, th)

    def f(a, b, c):
        x, y = a - ha, b - y0
        return T(ha + x * cs - y * sn, y0 + x * sn + y * cs, c)
    return f


def _door_meshes_raw(d: dict):
    from core.mesh import Mesh
    err = validate(d)
    if err:
        raise ValueError(err)
    T = finestre._mapper(d)
    W, H, fw, fd, sw = d["W"], d["H"], d["fw"], d["fd"], d["sw"]
    n = int(d["leaves"])
    frame, leaf, glass, hw = (
        finestre.PaintMesh(Mesh(), d, "leaf" if z == "frame" else z,
                           ZONE_NAME["leaf" if z == "frame" else z],
                           finestre.GLASS_OPACITY if z == "glass" else None)
        for z in ("frame", "leaf", "glass", "handle"))
    model = d.get("model", "porta")
    n = _panels(model, n)
    if model == "varco":
        fw = 0.01
        fb0, fb1 = -fd / 2, fd / 2
        f = arch_rise(d)
        if f > 1e-3:
            zs = H - f
            _box(frame, T, 0, fw, fb0, fb1, 0, zs, FRAME_COLOR)
            _box(frame, T, W - fw, W, fb0, fb1, 0, zs, FRAME_COLOR)
            _arch_strip(frame, T, W, zs, f, fw, fb0, fb1)
            return frame, leaf, glass, hw
        _box(frame, T, 0, fw, fb0, fb1, 0, H, FRAME_COLOR)
        _box(frame, T, W - fw, W, fb0, fb1, 0, H, FRAME_COLOR)
        _box(frame, T, fw, W - fw, fb0, fb1, H - fw, H, FRAME_COLOR)
        return frame, leaf, glass, hw

    fb0, fb1 = -fd / 2, fd / 2
    nofr = fw < 0.005
    if nofr:
        fw = 0.0
    gap = 0.0 if nofr else 0.003
    f = arch_rise(d)
    arch = f > 1e-3
    if arch:
        zs = H - f
        if not nofr:
            _box(frame, T, 0, fw, fb0, fb1, 0, zs, FRAME_COLOR)
            _box(frame, T, W - fw, W, fb0, fb1, 0, zs, FRAME_COLOR)
            _arch_strip(frame, T, W, zs, f, fw, fb0, fb1)
        R = (W * W / 4.0 + f * f) / (2.0 * f)
        cz = zs + f - R
        Ri = R - fw - gap
        zl = cz + math.sqrt(max(Ri * Ri - (W / 2.0 - fw - gap) ** 2, 0.0))
        ztop = min(zs, zl) - gap
        Hh = zs
    else:
        if not nofr:
            _box(frame, T, 0, fw, fb0, fb1, 0, H, FRAME_COLOR)
            _box(frame, T, W - fw, W, fb0, fb1, 0, H, FRAME_COLOR)
            _box(frame, T, fw, W - fw, fb0, fb1, H - fw, H, FRAME_COLOR)
        ztop = H - fw - gap
        Hh = H

    if n == 2 and d.get("asym"):
        ws = [d["w1"], W - 2 * fw - d["w1"]]
    else:
        ws = [(W - 2 * fw) / n] * n
    wl = ws[0]
    starts = [fw + sum(ws[:i]) for i in range(n)]
    Ts = [_leaf_T(T, d, i, starts[i], ws[i], n, fw, gap) for i in range(n)]
    a0 = fw
    for i, wi in enumerate(ws):
        Tl = Ts[i]
        if model in GLASS:
            _glass_leaf(model, leaf, glass, Tl, a0 + gap, a0 + wi - gap,
                        gap, ztop, sw)
        elif model in GRID:
            _grid_leaf(model, leaf, glass, Tl, a0 + gap, a0 + wi - gap,
                       gap, ztop, sw)
        elif model in PANELS:
            _box(leaf, Tl, a0 + gap, a0 + wi - gap, -sw / 2, sw / 2,
                 gap, ztop, LEAF_COLOR)
            _raised_panels(leaf, Tl, PANELS[model], a0 + gap, a0 + wi - gap,
                           gap, ztop, sw)
        else:
            _box(leaf, Tl, a0 + gap, a0 + wi - gap, -sw / 2, sw / 2,
                 gap, ztop, LEAF_COLOR)
        a0 += wi
    if arch:
        _arch_cap(leaf, T, W, fw + gap, W - fw - gap, ztop, cz, Ri,
                  -sw / 2, sw / 2)
    if model == "porta3":
        x0, x1 = fw + 0.18 * wl, W - fw - 0.18 * wl
        hl = ztop - gap
        for i in range(n):
            xa = max(x0, starts[i] + gap)
            xb = min(x1, starts[i] + ws[i] - gap)
            if xb <= xa:
                continue
            for fr in STRIPS:
                zz = ztop - fr * hl
                for s in (1, -1):
                    lo = sw / 2 if s > 0 else -sw / 2 - 0.004
                    _box(hw, Ts[i], xa, xb, lo, lo + 0.004, zz - 0.006,
                         zz + 0.006, METAL_COLOR)
    if model == "bifold":
        # one knob for each pair, in the middle of its leading panel: the
        # panel away from the jamb the pair pivots on
        for i in ([1] if n == 2 else [1, 2]):
            _knob(hw, T, fw + (i + 0.5) * wl, min(36 * IN, Hh * 0.47), sw)
        return frame, leaf, glass, hw
    if model == "garage1":
        _garage1(leaf, T, d, hw)
        return frame, leaf, glass, hw
    hk = d.get("handle", "lever")
    if d.get("slide") and can_open(d):
        if hk not in SLIDE_HANDLE_KEYS:
            hk = SLIDE_HANDLE_KINDS[0][0]
    elif hk in SLIDE_HANDLE_KEYS:
        hk = "lever"
    if model == "garage2":
        _garage2(leaf, T, d)
        _handle(hw, T, W / 2, H * 0.47, sw, kind=hk)
    elif n == 2:
        zh = min(1.0, Hh * 0.47)
        if d.get("asym"):
            if ws[0] >= ws[1]:
                _handle(hw, Ts[0], fw + ws[0] - 0.05, zh, sw, 1, kind=hk)
            else:
                _handle(hw, Ts[1], fw + ws[0] + 0.05, zh, sw, -1, kind=hk)
        else:
            _handle(hw, Ts[0], fw + ws[0] - 0.05, zh, sw, 1, kind=hk)
            _handle(hw, Ts[1], fw + ws[0] + 0.05, zh, sw, 1, kind=hk)
    else:
        _handle(hw, Ts[0], W - fw - 0.06, min(1.0, Hh * 0.47), sw, kind=hk)
    return frame, leaf, glass, hw


def _line2d(mesh, T, p0, p1, z=0.002, w=0.006) -> None:
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    ln = math.hypot(dx, dy)
    if ln < 1e-9:
        return
    nx, ny = -dy / ln * w / 2, dx / ln * w / 2
    q = [(p0[0] + nx, p0[1] + ny, z), (p1[0] + nx, p1[1] + ny, z),
         (p1[0] - nx, p1[1] - ny, z), (p0[0] - nx, p0[1] - ny, z)]
    for pts in (q, q[::-1]):
        f = mesh.add_face([T(*v) for v in pts])
        f.attrs["layer"] = LAYER_NAME


def arco_apertura_mesh(d: dict):
    op = float(d.get("open") or 0.0)
    if not can_open(d) or d.get("slide") or abs(op) < 1e-9:
        return None
    from core.mesh import Mesh
    T = finestre._mapper(d)
    W, fw, sw = d["W"], d["fw"], float(d.get("sw") or 0.0)
    n = int(d["leaves"]) if d.get("model", "porta") == "porta" else 1
    gap = 0.0 if fw < 0.005 else 0.003
    fw = 0.0 if fw < 0.005 else fw
    if n == 2 and d.get("asym"):
        ws = [d["w1"], W - 2 * fw - d["w1"]]
    else:
        ws = [(W - 2 * fw) / n] * n
    th = math.radians(min(max(op, -120.0), 120.0))
    y0 = math.copysign(sw / 2.0, th)
    m = finestre.PaintMesh(Mesh(), {"col_leaf": [0.0, 0.0, 0.0]}, "leaf",
                           tr("Arco apertura"), None)
    starts = [fw, fw + ws[0]]
    for i, wi in enumerate(ws):
        wl = wi - 2 * gap
        if i == 0:
            xh, dx = starts[0] + gap, 1.0
        else:
            xh, dx = starts[1] + wi - gap, -1.0
        nseg = max(4, int(abs(th) / (math.pi / 2) * 24))
        pts = []
        for k in range(nseg + 1):
            a = th * k / nseg
            pts.append((xh + dx * wl * math.cos(a), y0 + wl * math.sin(a)))
        for k in range(0, nseg, 2):
            _line2d(m.mesh, T, pts[k], pts[k + 1])
    return m.mesh


def _parts(d: dict, pose=None):
    frame, leaf, glass, hw = door_meshes_all(d)
    parts = []
    if d.get("model", "porta") == "varco" or d["fw"] >= 0.005:
        parts.append(finestre._part(tr("Telaio"), frame, pose))
    if d.get("model", "porta") != "varco":
        parts.append(finestre._part(tr("Anta"), leaf, pose))
    if d.get("model", "porta") in GLASS or d.get("model", "porta") in GRID:
        parts.append(finestre._part(tr("Vetro"), glass, pose))
    if d.get("model", "porta") != "varco":
        parts.append(finestre._part(tr("Maniglia"), hw, pose))
    sm = arco_apertura_mesh(d)
    if sm is not None:
        parts.append(finestre._part(tr("Arco apertura"), sm, pose))
    return parts


def door_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "o" in data else None


def _next_name(scene) -> str:
    used = {g.name for g in scene.groups}
    n = 1
    while tr("Porta {0}").format(n) in used:
        n += 1
    return tr("Porta {0}").format(n)


def make_door(scene, p: dict, place: dict):
    from core.group import Group
    d = finestre.clean_paint(dict(p))
    d.update(o=list(place["o"]), u=list(place["u"]),
             flip=bool(place["flip"]))
    for k in ("lv", "lvn", "off"):
        if k in place:
            d[k] = place[k]
    parts = _parts(d)
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    name = _next_name(scene)
    g = Group(name=name)
    g.adopt(parts)
    g.component = False
    g.layer = LAYER_NAME
    _ifc.tag(g, "IfcDoor", name)
    g.ext = {KEY: d}
    scene.groups.append(g)
    return g


def rebuild_door(group, p: dict) -> None:
    d = dict(door_data(group))
    d.update(p)
    finestre.clean_paint(d)
    pose = finestre._pose(group)
    group.children = _parts(d, pose)
    _ifc.tag(group, "IfcDoor")
    ext = dict(group.ext or {})
    ext[KEY] = d
    group.ext = ext


def _disegno_porta(p):
    from PySide6.QtGui import QPainterPath
    r, t, dim, ext = finestre._r, finestre._t, finestre._dim, finestre._ext
    C, A, Q = finestre._C_CORPO, finestre._C_ANTA, finestre._C_QUOTA
    p.setPen(QPen(finestre._C_LINEA, 1.5))
    p.drawLine(QPointF(14, 158), QPointF(190, 158))
    finestre._hatch(p, 14, 158, 190, 164)
    r(p, 30, 20, 170, 150, C)
    r(p, 38, 28, 108, 150, A)
    r(p, 108, 28, 162, 150, A)
    p.setPen(QPen(finestre._C_LINEA, 1.2))
    p.setBrush(finestre._C_LINEA)
    p.drawEllipse(QPointF(102, 92), 2.5, 2.5)
    p.drawEllipse(QPointF(114, 92), 2.5, 2.5)
    dim(p, 30, 12, 170, 12, "W")
    dim(p, 16, 20, 16, 150, "H", -1)
    dim(p, 182, 150, 182, 158, "h")
    dim(p, 38, 140, 108, 140, "a1", 1)
    dim(p, 108, 140, 162, 140, "a2", 1)
    dim(p, 30, 22, 38, 22, "f", -1)
    t(p, 70, 168, tr("Prospetto"), size=9)
    path = QPainterPath()
    path.moveTo(215, 150)
    path.lineTo(215, 70)
    path.quadTo(270, 20, 325, 70)
    path.lineTo(325, 150)
    path.closeSubpath()
    p.setPen(QPen(finestre._C_LINEA, 1.2))
    p.setBrush(finestre._C_BIANCO)
    p.drawPath(path)
    ext(p, 205, 70, 215, 70)
    ext(p, 215, 70, 345, 70)
    dim(p, 345, 45, 345, 70, "r")
    dim(p, 200, 45, 200, 150, "H", -1)
    dim(p, 215, 160, 325, 160, "W", 1)
    t(p, 232, 12, tr("Varco ad arco"), size=9)
    finestre._muro(p, 370, 40, 395, 120)
    finestre._muro(p, 455, 40, 480, 120)
    r(p, 395, 56, 403, 104, C)
    r(p, 447, 56, 455, 104, C)
    r(p, 403, 74, 447, 80, A)
    dim(p, 395, 48, 403, 48, "f", 1)
    ext(p, 360, 56, 403, 56)
    ext(p, 360, 104, 403, 104)
    dim(p, 360, 56, 360, 104, "p", -1)
    dim(p, 425, 74, 425, 80, "a", 1)
    t(p, 385, 168, tr("Sezione"), size=9)


def ask_params(parent, current: dict, title: str, ok_text: str,
               scene=None, tscene=None, groups=None):
    spin = finestre._spin
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(finestre._Schema(_disegno_porta))
    W = spin(current["W"], 0.3, 20.0)
    H = spin(current["H"], 0.5, 20.0)
    # the door itself (the slab); the totals above follow it and it follows them
    dW = spin(0.3, 0.05, 20.0)
    dH = spin(0.5, 0.05, 20.0)
    for s in (dW, dH):
        s.setToolTip(tr(
            "Misura della porta vera e propria (l'anta). Il telaio le sta "
            "intorno, fuori da questa misura: il foro nel muro è più largo "
            "di due profili e più alto di uno."))
    sill = spin(current["sill"], -10.0, 100.0)
    model = QComboBox()
    for key, label in MODELS:
        model.addItem(label, key)
    model.setCurrentIndex(
        max(0, model.findData(current.get("model", "porta"))))
    leaves = QComboBox()
    leaves.addItem(tr("1 anta"), 1)
    leaves.addItem(tr("2 ante uguali"), 2)
    leaves.addItem(tr("2 ante asimmetriche"), 3)
    asym0 = bool(current.get("asym")) and int(current["leaves"]) == 2
    leaves.setCurrentIndex(
        leaves.findData(3 if asym0 else int(current["leaves"])))
    cw0 = current["W"] - 2 * current["fw"]
    w1v = current.get("w1") or 0.6 * cw0
    a1 = spin(w1v, 0.2, 10.0)
    a2 = spin(max(0.2, cw0 - w1v), 0.2, 10.0)
    arch = QComboBox()
    for key, label in ARCH_KINDS:
        arch.addItem(label, key)
    arch.setCurrentIndex(max(0, arch.findData(current.get("arch", "none"))))
    ah = spin(current.get("arch_h") or 0.30, 0.05, 10.0)
    fw = spin(current["fw"], 0.0, 0.5)
    fd = spin(current["fd"], 0.02, 1.0)
    sw = spin(current["sw"], 0.01, 0.5)
    hk = QComboBox()
    slide = QCheckBox(tr("Porta scorrevole (entra nel muro, non ruota sul cardine)"))
    slide.setChecked(bool(current.get("slide")))
    opn = spin(float(current.get("open") or 0.0), -120.0, 120.0)
    opn.setToolTip(tr("0 = chiusa. A cardine: angolo di apertura (il segno sceglie "
                      "il lato). Scorrevole: corsa in % (100 = tutta dentro il muro)."))

    def fill_handles(sl: bool, want=None) -> None:
        kinds = SLIDE_HANDLE_KINDS if sl else HANDLE_KINDS
        hk.blockSignals(True)
        hk.clear()
        for key, label in kinds:
            hk.addItem(label, key)
        i = hk.findData(want) if want is not None else -1
        hk.setCurrentIndex(i if i >= 0 else 0)
        hk.blockSignals(False)

    fill_handles(bool(current.get("slide")), current.get("handle", "lever"))

    def on_slide(*_a) -> None:
        fill_handles(slide.isChecked(), hk.currentData())
        v = opn.value()
        if slide.isChecked():
            opn.setRange(0.0, 100.0)
            opn.setSuffix(" %")
        else:
            opn.setRange(-120.0, 120.0)
            opn.setSuffix("°")
        opn.setValue(v)
    lvl = None
    if scene is not None and piani.levels(scene):
        lvl = piani.level_combo(scene, piani.active_id(scene))
        form.addRow(tr("Piano (muri su cui posare)"), lvl)
    form.addRow(tr("Modello"), model)
    form.addRow(tr("Larghezza porta, senza telaio (m)"), dW)
    form.addRow(tr("Altezza porta, senza telaio (m)"), dH)
    form.addRow(tr("Larghezza totale (W) (m)"), W)
    form.addRow(tr("Altezza totale (H) (m)"), H)
    form.addRow(tr("Altezza da terra (h) (m)"), sill)
    form.addRow(tr("Forma della parte alta"), arch)
    form.addRow(tr("Altezza arco (r) (m)"), ah)
    form.addRow(tr("Ante"), leaves)
    form.addRow(tr("Anta 1: larghezza (a1) (m)"), a1)
    form.addRow(tr("Anta 2: larghezza (a2) (m)"), a2)
    form.addRow(tr("Telaio: larghezza profilo (f) (m) · 0 = senza telaio"), fw)
    form.addRow(tr("Telaio: profondità (p) (m)"), fd)
    form.addRow(tr("Spessore anta (a) (m)"), sw)
    form.addRow(tr("Tipo di maniglia"), hk)
    form.addRow(slide)
    form.addRow(tr("Apertura (0 = chiusa) (gradi · scorrevole: %)"), opn)
    paint = muri.add_paint_rows(form, current.get, DOOR_ZONES)
    hatch_w = HatchPick(doorwin_hatch(current.get("hatch")))
    hatch_w.setToolTip(tr("Retino della porta nella sezione (uno solo, non a strati)"))
    form.addRow(tr("Retino di sezione (uno solo)"), hatch_w)

    def _result():
        asym = leaves.currentData() == 3
        return {"W": (2 * fw.value() + a1.value() + a2.value()) if asym
                else W.value(),
                "H": H.value(), "sill": sill.value(),
                "leaves": 2 if asym else leaves.currentData(), "fw": fw.value(),
                "fd": fd.value(), "sw": sw.value(),
                "model": model.currentData(),
                "handle": hk.currentData(),
                "arch": ("none" if _no_arch(model.currentData())
                         else arch.currentData()),
                "arch_h": ah.value(),
                "asym": asym, "w1": a1.value() if asym else 0.0,
                "slide": bool(slide.isChecked() and slide.isEnabled()),
                "open": opn.value() if opn.isEnabled() else 0.0,
                "hatch": hatch_w.result() or {"mode": "none"},
                **_paint_res(paint)}

    def _set_tipo(t):
        tipi_w = {"model": model, "W": W, "H": H, "fw": fw, "fd": fd,
                  "sw": sw, "arch_h": ah, "arch": arch, "handle": hk,
                  "slide": slide}
        tipi_w.update(paint)
        _tipi.fill_widgets(tipi_w, dict(t, **{k: t.get(k) for k in paint}))
        if "handle" in t:
            fill_handles(slide.isChecked(), t.get("handle"))
        if "hatch" in t:
            hatch_w.set(t.get("hatch"))
        if "leaves" in t:
            asym = bool(t.get("asym")) and int(t["leaves"]) == 2
            leaves.setCurrentIndex(leaves.findData(3 if asym else int(t["leaves"])))
            if asym and t.get("w1"):
                a1.setValue(t["w1"])
                a2.setValue(max(0.2, t["W"] - 2 * t["fw"] - t["w1"]))

    tbar = _tipi.TypeBar(dlg, form, "porta", current, _result, _set_tipo,
                         scene, creating=scene is not None, tscene=tscene)
    cf = (_codici.CodeField(form, groups, "porta", tscene or scene, at=2)
          if groups else None)
    scroll_form(dlg, lay, form)

    def on_model() -> None:
        key = model.currentData()
        garage = key.startswith("garage")
        bifold = key == "bifold"
        leaves.setItemText(0, tr("A libro singola (2 pannelli)") if bifold
                           else tr("1 anta"))
        leaves.setItemText(1, tr("A libro doppia (4 pannelli)") if bifold
                           else tr("2 ante uguali"))
        if bifold:
            if started[0]:               # just chosen: a closet front
                leaves.setCurrentIndex(leaves.findData(2))
                sw.setValue(dflt(1.375 * IN, 0.035))
            elif leaves.currentData() == 3:
                leaves.setCurrentIndex(leaves.findData(2))
        elif key != "porta":
            leaves.setCurrentIndex(leaves.findData(1))
        if garage:
            if W.value() < 1.5:
                W.setValue(GARAGE_SIZE[0])
                H.setValue(GARAGE_SIZE[1])
        leaves.setEnabled(key in ("porta", "bifold"))
        leaves.model().item(2).setEnabled(not bifold)   # no asymmetric bi-fold
        arch.setEnabled(not _no_arch(key))
        if _no_arch(key):
            arch.setCurrentIndex(arch.findData("none"))
        on_arch()
        sw.setEnabled(key != "varco")
        hk.setEnabled(key not in ("varco", "garage1", "bifold"))
        slide.setEnabled(not garage and key not in ("varco", "bifold"))
        opn.setEnabled(not garage and key not in ("varco", "bifold"))
        for zone, ok in (("leaf", key != "varco"), ("glass", key in GLASS or key in GRID),
                         ("handle", key != "varco")):
            for pre in ("col_", "tex_"):
                paint[pre + zone].setEnabled(ok)
        on_leaves()

    def on_arch() -> None:
        kind = arch.currentData()
        ah.setEnabled(kind == "low"
                      and not _no_arch(model.currentData()))
        if kind == "full":
            set_quiet(ah, min(10.0, W.value() / 2.0))

    def set_quiet(spinbox, v) -> None:
        spinbox.blockSignals(True)
        spinbox.setValue(v)
        spinbox.blockSignals(False)

    def on_leaves() -> None:
        asym = leaves.currentData() == 3
        a1.setEnabled(asym)
        a2.setEnabled(asym)
        if asym:
            cw = W.value() - 2 * fw.value()
            if abs(a1.value() + a2.value() - cw) > 1e-6:
                set_quiet(a1, 0.6 * cw)
                set_quiet(a2, cw - 0.6 * cw)

    def on_ante() -> None:
        if leaves.currentData() == 3:
            set_quiet(W, 2 * fw.value() + a1.value() + a2.value())

    def on_total() -> None:
        if leaves.currentData() == 3:
            set_quiet(a2, max(0.2, W.value() - 2 * fw.value() - a1.value()))

    def around():
        n = 1 if leaves.currentData() == 1 else 2
        return _around(model.currentData(), n, fw.value())

    driving = [False]            # the door size is setting the totals

    def slab_from_total(*_a) -> None:
        if driving[0]:           # never write back into the field being typed
            return
        aw, ah_ = around()
        set_quiet(dW, W.value() - aw)
        set_quiet(dH, H.value() - ah_)

    def total_from_slab(*_a) -> None:
        # the frame, the leaves or the model changed, or a door size was
        # typed: the door keeps its size and the hole in the wall follows
        aw, ah_ = around()
        driving[0] = True
        try:
            W.setValue(dW.value() + aw)
            H.setValue(dH.value() + ah_)
        finally:
            driving[0] = False

    def slab_settled() -> None:
        # typing is over: if a total hit its limit, show the door that fits
        if not (dW.hasFocus() or dH.hasFocus()):
            slab_from_total()

    if imperial():
        # feet and inches: doors are sized by the door itself, so the totals
        # are worked out from it and the frame, and cannot be typed
        for s in (W, H):
            s.setReadOnly(True)
            s.setButtonSymbols(QAbstractSpinBox.NoButtons)
            s.setToolTip(tr(
                "Calcolata: misura della porta più il telaio. "
                "Cambia la misura della porta o il profilo del telaio."))

    a1.valueChanged.connect(on_ante)
    a2.valueChanged.connect(on_ante)
    fw.valueChanged.connect(on_ante)
    W.valueChanged.connect(on_total)
    leaves.currentIndexChanged.connect(on_leaves)
    arch.currentIndexChanged.connect(on_arch)
    W.valueChanged.connect(on_arch)
    model.currentIndexChanged.connect(on_model)
    slide.toggled.connect(on_slide)
    started = [False]
    on_slide()
    on_model()
    started[0] = True
    slab_from_total()
    for s in (W, H, a1, a2):
        s.valueChanged.connect(slab_from_total)
    for s in (dW, dH, fw):
        s.valueChanged.connect(total_from_slab)
    for s in (dW, dH):
        s.editingFinished.connect(slab_settled)
    for c in (leaves, model):
        c.currentIndexChanged.connect(total_from_slab)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.button(QDialogButtonBox.Ok).setText(ok_text)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return None
    if cf is not None:
        cf.apply(dlg)
    if lvl is not None:
        _Settings.level = lvl.currentData() or None
        piani.set_active(_Settings.level)
    return tbar.result(_result())


def reversed_place(d: dict) -> dict:
    """The same door in the same hole, turned end for end: the handle (and
    the hinge) change side. Flipping turns the door about its corner, so the
    corner moves to the other end of the unit."""
    (ux, uy), _n = finestre._axes(d)
    ox, oy, oz = d["o"]
    return {"o": [ox + ux * d["W"], oy + uy * d["W"], oz],
            "flip": not d.get("flip")}


def place_at(scene, world, p: dict) -> dict:
    """Where the door being placed goes: on the wall under the cursor, on
    the chosen edge, reversed if R was pressed."""
    place = finestre.place_edge(scene, world, _Settings, p["W"])
    if _Settings.rev:
        place.update(reversed_place({**p, **place}))
    return place


class PortaTool(Tool):
    name = tr("Porta")
    shortcut = None
    description = tr("Inserisce porte parametriche (1 o 2 ante).")

    def __init__(self) -> None:
        self._entering = False
        self._vp = None
        self.hover: QVector3D | None = None

    def on_activate(self, viewport) -> None:
        if self._entering:
            self._vp = viewport
            self.hover = None
            viewport.flash_status(
                tr("Porta: clic per posarla · Spazio = ribalta · "
                "Esc / tasto destro = esci")
                + tr(" · R = maniglia dall'altro lato"), 6000)
            return
        p = ask_params(viewport.window(), _params(), tr("Porta"), tr("Posa"),
                       viewport.scene)
        if p is None:
            return
        err = validate(p)
        if err:
            viewport.flash_status(tr("Porta: ") + err, 5000)
            return
        _store(p)
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def on_deactivate(self, viewport) -> None:
        self.hover = None

    def _exit(self, viewport) -> None:
        self.hover = None
        viewport.update()
        back = getattr(viewport.window(), "activate_select_tool", None)
        if callable(back):
            back()

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover = QVector3D(ctx.world)
        ctx.viewport.update()

    def on_cancel(self, viewport) -> None:
        self.hover = None
        viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        scene = viewport.scene
        if getattr(scene, "edit_group", None) is not None:
            viewport.flash_status(
                tr("Chiudi il gruppo che stai modificando, poi posa la porta"),
                4000)
            return
        world = QVector3D(ctx.world)
        self.hover = world
        p = _params()
        place = place_at(scene, world, p)

        def mutate(sc):
            make_door(sc, p, place)
            finestre.update_openings(sc)

        hist = viewport.history
        hist.execute(FinestraCommand(mutate))
        if getattr(hist, "last_error", None):
            viewport.flash_status(
                tr("Porta: ") + str(hist.last_error).split(": ", 1)[-1], 6000)
            return
        viewport.notify_scene_changed()
        viewport.flash_status(tr("Porta creata"), 2500)
        viewport.update()

    def context_menu(self, viewport, pos) -> bool:
        self._exit(viewport)
        return True

    def _buffer(self) -> str:
        return getattr(self._vp, "_value_buffer", "") or ""

    def claims_key(self, key: int, modifiers) -> bool:
        if modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        if self._buffer():
            return False
        return key in (Qt.Key_Space, Qt.Key_Escape, Qt.Key_R)

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if key == Qt.Key_Space:
            finestre.next_edge(_Settings)
            viewport.flash_status(
                tr("Spigolo ") + finestre.edge_word(_Settings),
                2000)
            viewport.update()
            return True
        if key == Qt.Key_R:
            _Settings.rev = not _Settings.rev
            viewport.flash_status(
                tr("Porta ribaltata: maniglia dall'altro lato") if _Settings.rev
                else tr("Porta non ribaltata"), 2000)
            viewport.update()
            return True
        return False

    def status_clause(self) -> str:
        return (tr("Spigolo {0} (Spazio ribalta) · Esc / tasto destro = esci").format(finestre.edge_word(_Settings))
                + tr(" · R = maniglia dall'altro lato"))

    def rubber_band_lines(self):
        if self.hover is None:
            return []
        scene = self._vp.scene if self._vp is not None else None
        if scene is None:
            return []
        d = _params()
        d.update(place_at(scene, self.hover, d))
        return finestre.outline_lines(d)

    def draw_overlay(self, viewport, painter) -> None:
        try:
            self._draw(viewport, painter)
        except Exception:
            pass

    def _draw(self, viewport, painter) -> None:
        if not SHOW_HELP_BOX:
            return
        painter.save()
        font = QFont()
        font.setPointSize(10)
        painter.setFont(font)
        fm = painter.fontMetrics()
        p = _params()
        lines = [
            tr("Porta {0} × {1} · {2} {3}").format(*(fmt_len(v) for v in door_size(p)), int(p['leaves']), (tr('anta') if p['leaves'] == 1 else tr('ante')))
            + ((tr(" (asimmetriche: {0} + {1})").format(
                fmt_len(p['w1']), fmt_len(p['W'] - 2 * p['fw'] - p['w1'])))
               if p.get('asym') else ""),
            tr("Da terra: {0} · telaio {1} × {2}").format(fmt_len(p['sill']), fmt_len(p['fw']), fmt_len(p['fd'])),
            (tr("Vuoto: ") + dict(ARCH_KINDS).get(p.get("arch", "none"), "")
             + (tr(" · freccia {0}").format(fmt_len(arch_rise(p))) if arch_rise(p) else "")),
            tr("Spigolo: {0}  (Spazio ribalta)").format(finestre.edge_word(_Settings, True))
            + "  ·  " + (tr("RIBALTATA (R)") if _Settings.rev else tr("non ribaltata (R)")),
            tr("Esc / tasto destro = esci"),
        ]
        w = max(fm.horizontalAdvance(t) for t in lines) + 16
        h = fm.height() * len(lines) + 12
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(30, 30, 30, 200))
        painter.drawRoundedRect(QRectF(12, 44, w, h), 6, 6)
        painter.setPen(QPen(QColor(255, 255, 255)))
        for i, t in enumerate(lines):
            painter.drawText(QPointF(20, 44 + 6 + fm.ascent() + i * fm.height()), t)
        painter.restore()


def _selected_doors(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and door_data(g) is not None and g not in out:
            out.append(g)
    return out


def edit_doors(viewport, doors=None) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    doors = doors or _selected_doors(scene)
    if not doors:
        viewport.flash_status(
            tr("Seleziona una porta creata con lo strumento Porta"), 4000)
        return
    d = door_data(doors[0])
    current = {k: d[k] for k in ("W", "H", "sill", "leaves", "fw", "fd", "sw")}
    current["model"] = d.get("model", "porta")
    current["handle"] = d.get("handle", "lever")
    current["arch"], current["arch_h"] = d.get("arch", "none"), d.get("arch_h", 0.30)
    current["asym"], current["w1"] = d.get("asym", False), d.get("w1", 0.0)
    current["slide"], current["open"] = d.get("slide", False), d.get("open", 0.0)
    current.update({k: d.get(k) for k in PAINT_KEYS})
    current["hatch"] = d.get("hatch")
    current["tipo_id"], current["tipo_nome"] = d.get("tipo_id"), d.get("tipo_nome")
    title = tr("Modifica porta") if len(doors) == 1 \
        else tr("Modifica {0} porte").format(len(doors))
    p = ask_params(viewport.window(), current, title, tr("Applica"),
                   tscene=scene, groups=doors)
    if p is None:
        return
    err = validate(p)
    if err:
        viewport.flash_status(tr("Porta: ") + err, 5000)
        return
    st = _tipi.resolve_edit(viewport.window(), scene, "porta", p)
    if st == "cancel":
        return

    paint_changed = {k: p.get(k) for k in PAINT_KEYS + ("hatch",)
                     if p.get(k) != current.get(k)}
    geom = {k: v for k, v in p.items() if k not in PAINT_KEYS + ("hatch",)}

    def mutate(sc):
        for g in doors:
            rebuild_door(g, {**geom, **paint_changed})
        if st == "type":
            _tipi.update_instances(sc, "porta", p["tipo_id"], rebuild_door)
        finestre.update_openings(sc)

    hist = viewport.history
    hist.execute(FinestraCommand(mutate))
    if getattr(hist, "last_error", None):
        viewport.flash_status(
            tr("Porta: ") + str(hist.last_error).split(": ", 1)[-1], 6000)
        return
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("{0} porte aggiornate").format(len(doors)), 3000)


def reverse_doors(viewport, doors=None) -> None:
    """Turns the selected doors end for end, in the holes they are in."""
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    doors = doors or _selected_doors(scene)
    if not doors:
        viewport.flash_status(
            tr("Seleziona una porta creata con lo strumento Porta"), 4000)
        return

    def mutate(sc):
        for g in doors:
            rebuild_door(g, reversed_place(door_data(g)))
        finestre.update_openings(sc)

    hist = viewport.history
    hist.execute(FinestraCommand(mutate))
    if getattr(hist, "last_error", None):
        viewport.flash_status(
            tr("Porta: ") + str(hist.last_error).split(": ", 1)[-1], 6000)
        return
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("Porta ribaltata: maniglia dall'altro lato"), 3000)


def _hook_double_click(vp) -> None:
    if getattr(vp, "_myhouse_porte_dbl", False):
        return
    original = vp.begin_group_edit

    def begin_group_edit(group, *args, **kwargs):
        g = getattr(group, "owner", None) or group
        if door_data(g) is None:
            return original(group, *args, **kwargs)
        from PySide6.QtCore import QTimer
        scene = vp.scene
        try:
            scene.select([g])
        except Exception:
            scene.selection.clear()
            scene.selection.add(g)
        vp.update()
        QTimer.singleShot(0, lambda: edit_doors(vp, [g]))

    vp.begin_group_edit = begin_group_edit
    vp._myhouse_porte_dbl = True


def _outliner_kind(group):
    d = door_data(group)
    if d is None:
        return None
    names = dict(MODELS)
    return {"type": tr("Porta"),
            "props": [(tr("Modello"), names.get(d.get("model", "porta"), "Porta")),
                      (tr("Larghezza"), fmt_len(d["W"])),
                      (tr("Altezza"), fmt_len(d["H"])),
                      (tr("Porta senza telaio"),
                       " × ".join(fmt_len(v) for v in door_size(d))),
                      (tr("Da terra"), fmt_len(d["sill"])),
                      (tr("Ante"),
                       tr("{n} pannelli a libro").format(n=_panels("bifold", d["leaves"]))
                       if d.get("model") == "bifold" else str(int(d["leaves"])))]
            + ([(tr("Anta 1"), fmt_len(d["w1"])),
                (tr("Anta 2"), fmt_len(d["W"] - 2 * d["fw"] - d["w1"]))]
               if d.get("asym") else [])
            + piani.level_props(d)}


def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(170, 125, 85))
    p.drawRect(13, 6, 22, 36)
    p.setBrush(QColor(240, 220, 120))
    p.drawEllipse(28, 23, 4, 4)
    p.end()
    return QIcon(pm)


def _register_level_kind() -> None:
    def zset(d, z):
        o = list(d["o"])
        o[2] = z
        d["o"] = o

    piani.register_kind("porta", KEY, door_data, lambda d: d["o"][2],
                        zset, rebuild_door)


class _FrecceOverlay(QWidget):
    def __init__(self, vp, ctl) -> None:
        super().__init__(vp)
        self.ctl = ctl
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(vp.rect())
        self.show()
        self.raise_()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            self.ctl.draw(p)
        except Exception:
            self.ctl.rects = []
        finally:
            p.end()


class _FrecceFilter(QObject):
    def __init__(self, ctl) -> None:
        super().__init__(ctl.vp)
        self.ctl = ctl
        self._swallow = False

    def eventFilter(self, obj, ev):
        t = ev.type()
        if obj is self.ctl.vp:
            if t == QEvent.Resize:
                self.ctl.overlay.setGeometry(self.ctl.vp.rect())
            elif t in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick) \
                    and ev.button() == Qt.LeftButton:
                hit = self.ctl.hit(ev.position())
                if hit is not None:
                    self._swallow = True
                    self.ctl.apri(*hit)
                    return True
            elif t == QEvent.MouseButtonRelease and self._swallow:
                self._swallow = False
                return True
        return False


class _Frecce:
    def __init__(self, vp) -> None:
        self.vp = vp
        self.rects = []
        self.overlay = _FrecceOverlay(vp, self)
        self.filter = _FrecceFilter(self)
        vp.installEventFilter(self.filter)
        self._sig = None
        self.timer = QTimer(vp)
        self.timer.timeout.connect(self._tick)
        self.timer.start(80)

    def _active(self) -> bool:
        if getattr(self.vp.scene, "edit_group", None) is not None:
            return False
        for n in ("active_tool", "tool", "_tool", "current_tool"):
            t = getattr(self.vp, n, None)
            if t is not None:
                nm = (str(getattr(t, "name", "")) or type(t).__name__).lower()
                return "porte" not in nm and "porta" not in nm
        return True

    def _doors(self):
        out = []
        for g in _selected_doors(self.vp.scene):
            d = door_data(g)
            if d is not None and can_open(d):
                out.append(g)
        return out

    def _tick(self) -> None:
        try:
            sc = self.vp.scene
            sel = tuple((id(g), float(door_data(g).get("open") or 0.0))
                        for g in self._doors())
            probe = []
            for v in ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)):
                px = self.vp._world_to_pixel(QVector3D(*v))
                probe.append(None if px is None else
                             (round(px[0], 1), round(px[1], 1)))
            sig = (sel, getattr(sc, "version", 0), tuple(probe), self._active())
        except Exception:
            return
        if sig != self._sig:
            self._sig = sig
            self.overlay.update()

    def px(self, v):
        return self.vp._world_to_pixel(v)

    def draw(self, p: QPainter) -> None:
        self.rects = []
        if not self._active():
            return
        for g in self._doors():
            d = door_data(g)
            pose = finestre._pose(g)
            T = finestre._mapper(d)
            zc = d["H"] * 0.5
            cur = float(d.get("open") or 0.0)
            sl = bool(d.get("slide"))
            for s in (1, -1):
                if sl:
                    s0 = self.px(pose.map(T(d["W"] / 2 + s * 0.12, 0.0, zc)))
                    s1 = self.px(pose.map(T(d["W"] / 2 + s * 0.60, 0.0, zc)))
                else:
                    s0 = self.px(pose.map(T(d["W"] / 2, s * 0.12, zc)))
                    s1 = self.px(pose.map(T(d["W"] / 2, s * 0.60, zc)))
                if s0 is None or s1 is None:
                    continue
                vx, vy = s1[0] - s0[0], s1[1] - s0[1]
                n = math.hypot(vx, vy)
                if n < 6:
                    continue
                vx, vy = vx / n, vy / n
                a = (s0[0] + vx * 4, s0[1] + vy * 4)
                tip = (s0[0] + vx * 44, s0[1] + vy * 44)
                if sl:
                    opens = s == -1 or int(d.get("leaves") or 1) > 1
                    on = abs(cur - 100.0) < 1e-6 if opens else abs(cur) < 1e-6
                else:
                    on = abs(cur - 90.0 * s) < 1e-6
                col = QColor(40, 170, 80) if on else QColor(255, 204, 0)
                p.setPen(QPen(col, 3))
                p.drawLine(QPointF(*a), QPointF(*tip))
                p.setPen(Qt.NoPen)
                p.setBrush(col)
                p.drawPolygon(QPolygonF([
                    QPointF(tip[0] + vx * 12, tip[1] + vy * 12),
                    QPointF(tip[0] - vy * 7, tip[1] + vx * 7),
                    QPointF(tip[0] + vy * 7, tip[1] - vx * 7)]))
                x0 = min(a[0], tip[0] + vx * 12) - 9
                y0 = min(a[1], tip[1] + vy * 12) - 9
                x1 = max(a[0], tip[0] + vx * 12) + 9
                y1 = max(a[1], tip[1] + vy * 12) + 9
                self.rects.append((QRectF(x0, y0, x1 - x0, y1 - y0), g, s))
            c = self.px(pose.map(T(d["W"] / 2, 0.0, zc)))
            if c is not None:
                closed = abs(cur) < 1e-6
                p.setPen(QPen(QColor(255, 255, 255), 2))
                p.setBrush(QColor(40, 170, 80) if closed else QColor(255, 204, 0))
                p.drawEllipse(QPointF(*c), 9.0, 9.0)
                self.rects.append((QRectF(c[0] - 13, c[1] - 13, 26, 26), g, 0))

    def hit(self, pos):
        x, y = pos.x(), pos.y()
        for r, g, s in self.rects:
            if r.contains(x, y):
                return g, s
        return None

    def apri(self, g, s) -> None:
        d = door_data(g)
        if d is None:
            return
        cur = float(d.get("open") or 0.0)
        if s == 0 and abs(cur) < 1e-6:
            return
        if d.get("slide"):
            opens = s == -1 or int(d.get("leaves") or 1) > 1
            target = 100.0 if (opens and abs(cur - 100.0) > 1e-6) else 0.0
        else:
            target = 0.0 if abs(cur - 90.0 * s) < 1e-6 else 90.0 * s

        def mutate(sc):
            rebuild_door(g, {"open": target})
            finestre.update_openings(sc)

        hist = self.vp.history
        hist.execute(FinestraCommand(mutate))
        if getattr(hist, "last_error", None):
            self.vp.flash_status(
                tr("Porta: ") + str(hist.last_error).split(": ", 1)[-1], 6000)
            return
        self.vp.notify_scene_changed()
        self.vp.update()
        self.overlay.update()


_FRECCE = {"ctl": None}


def toggle_all_doors(viewport) -> None:
    sc = viewport.scene
    doors = []
    for g in list(sc.groups):
        d = door_data(g)
        if d is not None and can_open(d):
            doors.append(g)
    if not doors:
        viewport.flash_status(tr("Nessuna porta nel progetto"), 3000)
        return
    any_open = any(abs(float(door_data(g).get("open") or 0.0)) > 1e-6
                   for g in doors)

    def target(g):
        if any_open:
            return 0.0
        return 100.0 if door_data(g).get("slide") else 90.0

    def mutate(sc):
        for g in doors:
            rebuild_door(g, {"open": target(g)})
        finestre.update_openings(sc)

    hist = viewport.history
    hist.execute(FinestraCommand(mutate))
    if getattr(hist, "last_error", None):
        viewport.flash_status(
            tr("Porta: ") + str(hist.last_error).split(": ", 1)[-1], 6000)
        return
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(
        tr("Tutte le porte chiuse") if any_open else tr("Tutte le porte aperte"),
        3000)


def _icon_all():
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(170, 125, 85))
    p.drawRect(6, 8, 16, 32)
    p.drawPolygon(QPolygonF([QPointF(26, 8), QPointF(42, 14),
                             QPointF(42, 44), QPointF(26, 40)]))
    p.end()
    return QIcon(pm)


def register(api) -> None:
    if _FRECCE["ctl"] is None:
        _FRECCE["ctl"] = _Frecce(api.window.viewport)
    _register_level_kind()
    api.add_button(tr("Porta"), tr("Inserisce una porta (1 o 2 ante)"),
                   _icon(), api.run_tool(PortaTool()))
    api.add_button(tr("Apri/chiudi tutte le porte"),
                   tr("Apre tutte le porte del progetto; premuto di nuovo le chiude"),
                   _icon_all(),
                   lambda: toggle_all_doors(api.window.viewport))

    app = api.app
    _hook_double_click(api.window.viewport)
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        from PySide6.QtCore import QTimer

        def context(menu, selection) -> None:
            if not _selected_doors(app.viewport.scene):
                return
            menu.addSeparator()
            menu.addAction(
                tr("Modifica porta…"),
                lambda: QTimer.singleShot(
                    0, lambda: edit_doors(app.viewport)))
            menu.addAction(
                tr("Ribalta la porta (maniglia dall'altro lato)"),
                lambda: QTimer.singleShot(
                    0, lambda: reverse_doors(app.viewport)))

        add_ctx(context)
    add_kind = getattr(app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
