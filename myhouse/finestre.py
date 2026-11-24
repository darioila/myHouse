# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr
from ._imperial import FT, IN, LengthSpin, dflt, imperial
from ._scroll import scroll_form

import copy
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QFont, QMatrix4x4, QPen, QPolygonF, QVector3D,
)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QLabel, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from core import bim
from . import _ifc
from core.history import Command
from ._imperial import fmt_len
from tools.base import Tool, ToolContext

from . import _codici, _tipi, muri, piani
from ._strati import HatchPick, doorwin_hatch

KEY = "myhouse_finestra"
LAYER_NAME = "Finestre"
FRAME_COLOR = (0.93, 0.93, 0.90)
GLASS_COLOR = (0.62, 0.80, 0.92)
GLASS_OPACITY = 0.45
GLASS_T = 0.02
WALL_KEY = "myhouse_muro"
WALL_TOL = 0.15
ORDER = 40
DIV_KEYS = ("sub", "nv", "nh", "dv", "dh")
# Mulled windows: with a web thickness > 0 the sashes are separate windows in
# one frame, divided by a fixed mullion shaped like an "I" in plan: a web (mw)
# between the windows and a flange on the front (mf1) and on the back (mf2),
# each reaching mc past the web, so every window sits in a channel.
MULLION_KEYS = ("mw", "mf1", "mf2", "mc")
MULLION_DEFAULT = {"mw": 0.0, "mf1": dflt(0.5 * IN, 0.012),
                   "mf2": dflt(0.5 * IN, 0.012), "mc": dflt(0.75 * IN, 0.02)}
DIV_DEFAULT = {"sub": None, "nv": 0, "nh": 0, "dv": 0.03, "dh": 0.03}


SHOW_HELP_BOX = False


def _counts(d: dict):
    nv, nh = int(d.get("nv", 0)), int(d.get("nh", 0))
    sub = d.get("sub")
    if sub is None:
        sub = bool(nv or nh)
    return (nv, nh) if sub else (0, 0)
PAINT_KEYS = ("col_frame", "tex_frame", "col_glass", "tex_glass",
              "col_shut", "tex_shut", "col_handle", "tex_handle",
              "col_curt", "tex_curt", "col_rod", "tex_rod",
              "col_sill", "tex_sill")
DEFAULT_PAINT = {"frame": (0.95, 0.95, 0.92),
                 "glass": (0.70, 0.85, 0.95),
                 "shut": (0.35, 0.45, 0.35),
                 "handle": (0.72, 0.72, 0.75),
                 "curt": (0.94, 0.94, 0.91),
                 "rod": (0.42, 0.27, 0.15),
                 "sill": (0.93, 0.93, 0.90)}
ZONE_NAME = {"frame": tr("telaio finestra"), "glass": tr("vetro finestra"),
             "shut": tr("oscuranti finestra"),
             "handle": tr("maniglia finestra"),
             "curt": tr("tenda finestra"), "rod": tr("bastone tenda"),
             "sill": tr("soglia finestra")}
WIN_ZONES = (("frame", tr("telaio e ante")), ("glass", tr("vetro")),
             ("sill", tr("soglia")),
             ("shut", tr("tapparella / napoletane")),
             ("handle", tr("maniglie")),
             ("curt", tr("tenda")), ("rod", tr("bastone della tenda")))
SHUT_KEYS = ("shut", "shv")
SHUT_DEFAULT = {"shut": "", "shv": 0}
CURT_KEYS = ("cur", "cuh", "cuv")
CURT_DEFAULT = {"cur": False, "cuh": 0.0, "cuv": 0}
SILL_KEYS = ("sth", "sti", "ste")
SILL_DEFAULT = {"sth": 0.02, "sti": 0.02, "ste": 0.02}
TIPO_KEYS = ("tipo", "slv")
TIPO_DEFAULT = {"tipo": "", "slv": 0}
SPAL_KEYS = ("spt", "spl", "spd", "spw", "sbd", "sba")
SPAL_DEFAULT = {"spt": "", "spl": "e", "spd": 0.10, "spw": 0.05,
                "sbd": 0.15, "sba": 45.0}
CURT_ABOVE = 0.20


# Standard US sizes by window type, in inches, from Pella's standard-size
# charts (pella.com/ideas/windows/standard-window-sizes): every width of a
# type comes in every one of its heights, except where "tallest" caps a narrow
# slider. Picture windows have no chart there, only four common sizes.
# Adding a type or a size is a change to this table and nothing else.
STANDARD_SIZES = {
    "hung": {
        "label": tr("A ghigliottina (singola/doppia)"),
        "widths": [24, 28, 30, 32, 36, 38, 42, 48, 54],
        "heights": [36, 38, 42, 46, 48, 52, 54, 60, 62, 66, 72, 78]},
    "casement": {
        "label": tr("A battente"),
        "widths": [18, 24, 28, 30, 32, 36],
        "heights": [30, 36, 42, 48, 54, 60, 66, 72]},
    "awning": {
        "label": tr("A sporgere"),
        "widths": [20.5, 24, 28, 30, 32, 36, 42, 48, 54, 60],
        "heights": [18, 24, 30, 36, 40, 48, 54, 60]},
    "sliding": {
        "label": tr("Scorrevole"),
        "widths": [24, 30, 36, 48, 60, 72],
        "heights": [18, 24, 30, 36, 42, 48, 54, 60, 72],
        "tallest": {24: 42, 30: 54, 36: 60}},
    "picture": {
        "label": tr("Fissa"),
        "sizes": [(36, 24), (60, 36), (72, 48), (48, 60)]},
}


def standard_sizes(style: str):
    """[(width, height)] in inches of one window type, narrowest first."""
    t = STANDARD_SIZES.get(style)
    if t is None:
        return []
    if "sizes" in t:
        return list(t["sizes"])
    top = t.get("tallest", {})
    return [(w, h) for w in t["widths"] for h in t["heights"]
            if h <= top.get(w, h)]


def size_code(w: float, h: float) -> str:
    """The trade's notation for a size in inches: feet and inches of width,
    then of height: 32 x 62 is "2852" (2'8" x 5'2"), 24 x 46 is "20310"."""
    def part(v):
        return f"{int(v // 12)}{v % 12:g}".replace(".", "")
    return part(w) + part(h)


def size_label(w: float, h: float) -> str:
    return f'{size_code(w, h)} — {w:g}" × {h:g}"'


def style_label(style) -> str:
    t = STANDARD_SIZES.get(style or "")
    return t["label"] if t else ""


class _Settings:
    # US standard sizes: a key of STANDARD_SIZES, or "" (always "" in metric)
    style = dflt("hung", "")
    W = dflt(32 * IN, 1.20)
    H = dflt(48 * IN, 1.40)
    sill = dflt(36 * IN, 0.90)
    leaves = 1
    fw = dflt(2.5 * IN, 0.06)
    fd = dflt(2.75 * IN, 0.07)
    sw = dflt(2.0 * IN, 0.05)
    sub = None
    nv = 0
    nh = 0
    dv = 0.03
    dh = 0.03
    mw = MULLION_DEFAULT["mw"]
    mf1 = MULLION_DEFAULT["mf1"]
    mf2 = MULLION_DEFAULT["mf2"]
    mc = MULLION_DEFAULT["mc"]
    flip = False
    mid = False             # held by the middle (Space: left, middle, right)
    level = None
    shut = ""
    shv = 0
    col_shut = list(DEFAULT_PAINT["shut"])
    tex_shut = None
    cur = False
    cuh = 0.0
    cuv = 0
    col_curt = list(DEFAULT_PAINT["curt"])
    tex_curt = None
    col_rod = list(DEFAULT_PAINT["rod"])
    tex_rod = None
    col_handle = list(DEFAULT_PAINT["handle"])
    tex_handle = None
    tipo = ""
    spt = ""
    spl = "e"
    spd = 0.10
    spw = 0.05
    sbd = 0.15
    sba = 45.0
    slv = 0
    sth = 0.02
    sti = 0.02
    ste = 0.02
    col_sill = list(DEFAULT_PAINT["sill"])
    tex_sill = None
    col_frame = list(DEFAULT_PAINT["frame"])
    tex_frame = None
    col_glass = list(DEFAULT_PAINT["glass"])
    tex_glass = None
    hatch = None
    tipo_id = None
    tipo_nome = None


def settings_paint() -> dict:
    return {k: copy.deepcopy(getattr(_Settings, k, None))
            for k in PAINT_KEYS if getattr(_Settings, k, None)}


def _params() -> dict:
    p = {"W": _Settings.W, "H": _Settings.H, "sill": _Settings.sill,
         "leaves": _Settings.leaves, "fw": _Settings.fw,
         "fd": _Settings.fd, "sw": _Settings.sw}
    for k in (DIV_KEYS + MULLION_KEYS + SHUT_KEYS + CURT_KEYS + SILL_KEYS
              + TIPO_KEYS + SPAL_KEYS):
        p[k] = getattr(_Settings, k)
    p.update(settings_paint())
    if _Settings.hatch:
        p["hatch"] = copy.deepcopy(_Settings.hatch)
    p["tipo_id"], p["tipo_nome"] = _Settings.tipo_id, _Settings.tipo_nome
    p["style"] = _Settings.style
    return p


def _store(p: dict) -> None:
    _Settings.W, _Settings.H, _Settings.sill = p["W"], p["H"], p["sill"]
    _Settings.leaves, _Settings.fw = p["leaves"], p["fw"]
    _Settings.fd, _Settings.sw = p["fd"], p["sw"]
    _Settings.style = p.get("style") or ""
    for k in DIV_KEYS:
        setattr(_Settings, k, p.get(k, DIV_DEFAULT[k]))
    for k in MULLION_KEYS:
        setattr(_Settings, k, p.get(k, MULLION_DEFAULT[k]))
    for k in SHUT_KEYS:
        setattr(_Settings, k, p.get(k, SHUT_DEFAULT[k]))
    for k in CURT_KEYS:
        setattr(_Settings, k, p.get(k, CURT_DEFAULT[k]))
    for k in SILL_KEYS:
        setattr(_Settings, k, p.get(k, SILL_DEFAULT[k]))
    for k in TIPO_KEYS:
        setattr(_Settings, k, p.get(k, TIPO_DEFAULT[k]))
    for k in SPAL_KEYS:
        setattr(_Settings, k, p.get(k, SPAL_DEFAULT[k]))
    for k in PAINT_KEYS:
        setattr(_Settings, k, p.get(k))
    _Settings.hatch = copy.deepcopy(p.get("hatch")) or None
    _Settings.tipo_id, _Settings.tipo_nome = p.get("tipo_id"), p.get("tipo_nome")


def _mullion(p: dict) -> float:
    """Web thickness of the mullion between two windows: 0 for a single
    sash, for a sliding window and for windows saved before mullions."""
    if p.get("tipo") == "sc" or int(p["leaves"]) < 2:
        return 0.0
    return max(0.0, float(p.get("mw") or 0.0))


def _flanges(p: dict):
    """(front flange thickness, back flange thickness, channel depth) of the
    I-shaped mullion. A flange needs both a thickness and a channel depth."""
    if not _mullion(p):
        return 0.0, 0.0, 0.0
    f1, f2, c = (max(0.0, float(p.get(k, MULLION_DEFAULT[k]) or 0.0))
                 for k in MULLION_KEYS[1:])
    return (f1, f2, c) if c > 0 else (0.0, 0.0, 0.0)


def sash_width(p: dict) -> float:
    """Width of each sash: what is left between the frame and the mullions."""
    n = int(p["leaves"])
    return (p["W"] - 2 * p["fw"] - (n - 1) * _mullion(p)) / n


def mullion_profile(x0, x1, y0, y1, f1, f2, c):
    """Plan outline of one mullion, counter-clockwise seen from above: an "I"
    whose web runs from x0 to x1 (along the wall) and from y0 to y1 (the depth
    of the sashes), with a flange f1 thick in front of y0 and one f2 thick
    behind y1, each reaching c past the web so the windows sit in the two
    channels. Without a flange that end is just the end of the web."""
    front = ([(x0, y0), (x0 - c, y0), (x0 - c, y0 - f1),
              (x1 + c, y0 - f1), (x1 + c, y0), (x1, y0)]
             if f1 > 0 else [(x0, y0), (x1, y0)])
    back = ([(x1, y1), (x1 + c, y1), (x1 + c, y1 + f2),
             (x0 - c, y1 + f2), (x0 - c, y1), (x0, y1)]
            if f2 > 0 else [(x1, y1), (x0, y1)])
    return front + back


def _prism(mesh, T, outline, c0, c1):
    """Closed vertical prism over a counter-clockwise plan outline."""
    faces = [[(a, b, c1) for a, b in outline],
             [(a, b, c0) for a, b in reversed(outline)]]
    for (pa, pb), (qa, qb) in zip(outline, outline[1:] + outline[:1]):
        faces.append([(pa, pb, c0), (qa, qb, c0), (qa, qb, c1), (pa, pb, c1)])
    for q in faces:
        f = mesh.add_face([T(*v) for v in q])
        f.attrs["layer"] = LAYER_NAME


def validate(p: dict) -> str | None:
    n = 2 if p.get("tipo") == "sc" else p["leaves"]
    if p["W"] <= (2 * p["fw"] + (n - 1) * _mullion(p)
                  + n * 2 * p["sw"] + 0.04):
        return tr("Larghezza troppo piccola per telaio e ante")
    if _flanges(p)[2] > p["sw"]:
        return tr("Il canale del montante è più profondo della larghezza del profilo dell'anta")
    if p["H"] <= 2 * p["fw"] + 2 * p["sw"] + 0.04:
        return tr("Altezza troppo piccola per telaio e ante")
    nv, nh = _counts(p)
    dv, dh = p.get("dv", 0.03), p.get("dh", 0.03)
    iw = (p["W"] - 2 * p["fw"] - (n - 1) * _mullion(p)) / n - 2 * p["sw"]
    ih = p["H"] - 2 * p["fw"] - 2 * p["sw"]
    if (iw - nv * dv) / (nv + 1) < 0.02:
        return tr("Divisioni verticali troppo numerose o spesse per l'anta")
    if (ih - nh * dh) / (nh + 1) < 0.02:
        return tr("Divisioni orizzontali troppo numerose o spesse per l'anta")
    if p.get("sth", SILL_DEFAULT["sth"]) <= 0:
        return tr("Lo spessore della soglia deve essere maggiore di zero")
    return None


def _axes(d: dict):
    ux, uy = d["u"]
    if d.get("flip"):
        ux, uy = -ux, -uy
    return (ux, uy), (-uy, ux)


def _mapper(d: dict):
    (ux, uy), (nx, ny) = _axes(d)
    ox, oy, oz = d["o"]
    z0 = oz + d["sill"]

    def T(a, b, c):
        return QVector3D(ox + a * ux + b * nx, oy + a * uy + b * ny, z0 + c)
    return T


class PaintMesh:

    def __init__(self, mesh, d, zone, name=None, opacity=None) -> None:
        self.mesh = mesh
        self._col = d.get("col_" + zone)
        self._tex = d.get("tex_" + zone)
        self._name = name
        self._opacity = opacity

    def add_face(self, *a, **k):
        f = self.mesh.add_face(*a, **k)
        done = muri.paint_face(f, self._col, self._tex)
        if self._name and done and not (self._tex and self._tex.get("path")):
            f.attrs["mat"] = self._name
        if self._opacity is not None and "opacity" not in f.attrs:
            f.attrs["opacity"] = self._opacity
            f.attrs["back"] = True
        return f

    def __getattr__(self, name):
        return getattr(self.__dict__["mesh"], name)


def clean_paint(d: dict) -> dict:
    for k in list(d):
        if k.startswith(("col_", "tex_")) and not d[k]:
            del d[k]
    return d


def _box(mesh, T, a0, a1, b0, b1, c0, c1, color, opacity=None):
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
        if opacity is not None:
            f.attrs["opacity"] = opacity
            f.attrs["back"] = True


def _sc_layout(d: dict):
    W, fw, sw = d["W"], d["fw"], d["sw"]
    ov = sw
    wl = (W - 2 * fw + ov) / 2
    return wl, (W - 2 * fw) - wl, ov


def _sc_sashes(d: dict):
    W, fw, fd = d["W"], d["fw"], d["fd"]
    wl, smax, _ov = _sc_layout(d)
    t = fd / 2 - 0.014
    shift = smax * max(0, min(100, int(d.get("slv", 0)))) / 100.0
    ca, cb = fd / 4, -fd / 4
    a = (fw, fw + wl, ca - t / 2, ca + t / 2)
    b = (W - fw - wl - shift, W - fw - shift, cb - t / 2, cb + t / 2)
    return [a, b]


def _sc_meshes(d: dict, frame, glass, T):
    W, H, fw, fd, sw = d["W"], d["H"], d["fw"], d["fd"], d["sw"]
    nv, nh = _counts(d)
    dv, dh = d.get("dv", 0.03), d.get("dh", 0.03)
    fb0, fb1 = -fd / 2, fd / 2
    _box(frame, T, 0, fw, fb0, fb1, 0, H, FRAME_COLOR)
    _box(frame, T, W - fw, W, fb0, fb1, 0, H, FRAME_COLOR)
    _box(frame, T, fw, W - fw, fb0, fb1, 0, fw, FRAME_COLOR)
    _box(frame, T, fw, W - fw, fb0, fb1, H - fw, H, FRAME_COLOR)
    rib, rh = 0.01, min(0.025, fw * 0.6)
    for bc in (fb0 + rib / 2, 0.0, fb1 - rib / 2):
        _box(frame, T, fw, W - fw, bc - rib / 2, bc + rib / 2, fw, fw + rh,
             FRAME_COLOR)
        _box(frame, T, fw, W - fw, bc - rib / 2, bc + rib / 2, H - fw - rh,
             H - fw, FRAME_COLOR)
    c0, c1 = fw + rh * 0.5, H - fw - rh * 0.5
    for a0, a1, sb0, sb1 in _sc_sashes(d):
        _box(frame, T, a0, a0 + sw, sb0, sb1, c0, c1, FRAME_COLOR)
        _box(frame, T, a1 - sw, a1, sb0, sb1, c0, c1, FRAME_COLOR)
        _box(frame, T, a0 + sw, a1 - sw, sb0, sb1, c0, c0 + sw, FRAME_COLOR)
        _box(frame, T, a0 + sw, a1 - sw, sb0, sb1, c1 - sw, c1, FRAME_COLOR)
        x0, x1, z0, z1 = a0 + sw, a1 - sw, c0 + sw, c1 - sw
        pw = (x1 - x0 - nv * dv) / (nv + 1)
        ph = (z1 - z0 - nh * dh) / (nh + 1)
        for j in range(nv):
            bx = x0 + (j + 1) * pw + j * dv
            _box(frame, T, bx, bx + dv, sb0, sb1, z0, z1, FRAME_COLOR)
        for k in range(nh):
            bz = z0 + (k + 1) * ph + k * dh
            _box(frame, T, x0, x1, sb0, sb1, bz, bz + dh, FRAME_COLOR)
        bm = (sb0 + sb1) / 2
        for j in range(nv + 1):
            gx0 = x0 + j * (pw + dv)
            for k in range(nh + 1):
                gz0 = z0 + k * (ph + dh)
                _box(glass, T, gx0, gx0 + pw, bm - GLASS_T / 2,
                     bm + GLASS_T / 2, gz0, gz0 + ph, GLASS_COLOR,
                     GLASS_OPACITY)


def window_meshes(d: dict):
    from core.mesh import Mesh
    err = validate(d)
    if err:
        raise ValueError(err)
    T = _mapper(d)
    W, H, fw, fd, sw = d["W"], d["H"], d["fw"], d["fd"], d["sw"]
    n = int(d["leaves"])
    nv, nh = _counts(d)
    dv, dh = d.get("dv", 0.03), d.get("dh", 0.03)
    sd = fd * 0.6
    frame = PaintMesh(Mesh(), d, "frame", ZONE_NAME["frame"])
    glass = PaintMesh(Mesh(), d, "glass", ZONE_NAME["glass"])
    if d.get("tipo") == "sc":
        _sc_meshes(d, frame, glass, T)
        return frame.mesh, glass.mesh

    fb0, fb1 = -fd / 2, fd / 2
    _box(frame, T, 0, fw, fb0, fb1, 0, H, FRAME_COLOR)
    _box(frame, T, W - fw, W, fb0, fb1, 0, H, FRAME_COLOR)
    _box(frame, T, fw, W - fw, fb0, fb1, 0, fw, FRAME_COLOR)
    _box(frame, T, fw, W - fw, fb0, fb1, H - fw, H, FRAME_COLOR)

    # with a mullion the sashes are separate windows in one frame: its web
    # sits between two of them and its flanges lap over their stiles
    mw = _mullion(d)
    f1, f2, mc = _flanges(d)
    wl = sash_width(d)
    sb0, sb1 = -sd / 2, sd / 2
    c0, c1 = fw, H - fw
    for i in range(n):
        a0 = fw + i * (wl + mw)
        a1 = a0 + wl
        if mw > 0 and i < n - 1:
            _prism(frame, T, mullion_profile(a1, a1 + mw, sb0, sb1,
                                             f1, f2, mc), c0, c1)
        _box(frame, T, a0, a0 + sw, sb0, sb1, c0, c1, FRAME_COLOR)
        _box(frame, T, a1 - sw, a1, sb0, sb1, c0, c1, FRAME_COLOR)
        _box(frame, T, a0 + sw, a1 - sw, sb0, sb1, c0, c0 + sw, FRAME_COLOR)
        _box(frame, T, a0 + sw, a1 - sw, sb0, sb1, c1 - sw, c1, FRAME_COLOR)
        x0, x1 = a0 + sw, a1 - sw
        z0, z1 = c0 + sw, c1 - sw
        pw = (x1 - x0 - nv * dv) / (nv + 1)
        ph = (z1 - z0 - nh * dh) / (nh + 1)
        for j in range(nv):
            bx = x0 + (j + 1) * pw + j * dv
            _box(frame, T, bx, bx + dv, sb0, sb1, z0, z1, FRAME_COLOR)
        for k in range(nh):
            bz = z0 + (k + 1) * ph + k * dh
            _box(frame, T, x0, x1, sb0, sb1, bz, bz + dh, FRAME_COLOR)
        for j in range(nv + 1):
            gx0 = x0 + j * (pw + dv)
            for k in range(nh + 1):
                gz0 = z0 + k * (ph + dh)
                _box(glass, T, gx0, gx0 + pw, -GLASS_T / 2, GLASS_T / 2,
                     gz0, gz0 + ph, GLASS_COLOR, GLASS_OPACITY)
    return frame.mesh, glass.mesh


def sill_mesh(d: dict):
    from core.mesh import Mesh
    T = _mapper(d)
    W = d["W"]
    th = max(0.001, float(d.get("sth", SILL_DEFAULT["sth"])))
    si = max(0.0, float(d.get("sti", SILL_DEFAULT["sti"])))
    se = max(0.0, float(d.get("ste", SILL_DEFAULT["ste"])))
    wth = d.get("wth")
    half = (wth / 2) if wth else (d["fd"] / 2)
    sill = PaintMesh(Mesh(), d, "sill", ZONE_NAME["sill"])
    r = _reveal_pts(d)
    if r is None:
        _box(sill, T, 0, W, -(half + si), half + se, -th, 0, FRAME_COLOR)
        return sill.mesh
    pts, _big = r
    seq = pts[::-1] if d.get("spl", "e") == "e" else pts
    left = ([(-seq[0][1], -(half + si))] + [(-e, b) for b, e in seq]
            + [(-seq[-1][1], half + se)])
    right = ([(W + seq[-1][1], half + se)]
             + [(W + e, b) for b, e in reversed(seq)]
             + [(W + seq[0][1], -(half + si))])
    _fill_prism(sill, T, left + right, -th, 0.0,
                lambda f, _b: f.attrs.__setitem__("layer", LAYER_NAME))
    return sill.mesh


def _slat(mesh, T, a0, a1, sect):
    def add(pts):
        f = mesh.add_face([T(*v) for v in pts])
        f.attrs["layer"] = LAYER_NAME

    add([(a0, b, c) for b, c in reversed(sect)])
    add([(a1, b, c) for b, c in sect])
    n = len(sect)
    for i in range(n):
        p, q = sect[i], sect[(i + 1) % n]
        add([(a0, q[0], q[1]), (a1, q[0], q[1]),
             (a1, p[0], p[1]), (a0, p[0], p[1])])


def _roller(mesh, T, d):
    W, H, fw, fd = d["W"], d["H"], d["fw"], d["fd"]
    g, th, pitch, sh = 0.03, 0.016, 0.045, 0.04
    b0 = fd / 2 + 0.004
    c0, c1 = 0.0, H
    x0, x1 = g, W - g
    _box(mesh, T, 0.0, x0, b0, b0 + 0.04, c0, c1, None)
    _box(mesh, T, x1, W, b0, b0 + 0.04, c0, c1, None)
    hc = max(0.0, min(100.0, float(d.get("shv", 0)))) / 100.0 * (c1 - c0)
    if hc < 0.01:
        return
    n = int(math.ceil(hc / pitch))
    for i in range(n):
        zt = c1 - i * pitch
        zb = max(zt - sh, c1 - hc)
        if zt - zb < 0.005:
            continue
        _box(mesh, T, x0, x1, b0 + 0.008, b0 + 0.008 + th, zb, zt, None)
    bar = min(0.03, hc)
    _box(mesh, T, x0, x1, b0 + 0.002, b0 + 0.002 + 0.03, c1 - hc, c1 - hc + bar,
         None)


def _leaf_handle(hw, T, x, zc, dr=1) -> None:
    for s_ in (-1,):
        inn, out = s_ * 0.0175, s_ * 0.0675
        lo, hi = (min(inn, out), max(inn, out))
        _box(hw, T, x - 0.025, x + 0.025, min(inn, s_ * 0.0275),
             max(inn, s_ * 0.0275), zc - 0.025, zc + 0.025, None)
        _box(hw, T, x - 0.01, x + 0.01, lo, hi, zc - 0.01, zc + 0.01, None)
        _box(hw, T, x - 0.01, x + 0.01, min(out, out - s_ * 0.018),
             max(out, out - s_ * 0.018), zc - 0.11, zc + 0.01, None)


def _persiana(mesh, T, d, side, x0, pw, Hp, bh, ang, hw=None):
    t = 0.035
    c, s = math.cos(ang), math.sin(ang)

    def PT(x, y, z):
        if side == 0:
            return T(x0 + x * c - y * s, bh + x * s + y * c, z)
        return T(x0 - x * c - y * s, bh + x * s - y * c, z)

    st, rl = 0.05, 0.06
    _box(mesh, PT, 0, st, -t / 2, t / 2, 0, Hp, None)
    _box(mesh, PT, pw - st, pw, -t / 2, t / 2, 0, Hp, None)
    _box(mesh, PT, st, pw - st, -t / 2, t / 2, 0, rl, None)
    _box(mesh, PT, st, pw - st, -t / 2, t / 2, Hp - rl, Hp, None)
    sect = [(-t / 2, 0.02), (t / 2, 0.0), (t / 2, 0.01), (-t / 2, 0.03)]
    if side == 1:
        sect = [(-y, z) for y, z in reversed(sect)]
    avail = Hp - 2 * rl - 0.03
    n = int(avail / 0.04 + 1e-9) + 1 if avail >= 0 else 0
    pitch = avail / (n - 1) if n > 1 else 0.04
    for j in range(n):
        z0 = rl + j * pitch
        _slat(mesh, PT, st, pw - st,
              [(y, z + z0) for y, z in sect])
    if hw is not None and side == 0:
        _leaf_handle(hw, PT, pw - st / 2 - 0.0, min(1.0, Hp * 0.47), 1)


def shutter_mesh(d: dict, hw=None):
    kind = d.get("shut") or ""
    if kind not in ("tap", "nap"):
        return None
    from core.mesh import Mesh
    T = _mapper(d)
    mesh = PaintMesh(Mesh(), d, "shut", ZONE_NAME["shut"])
    if kind == "tap":
        _roller(mesh, T, d)
    else:
        W, H, fd = d["W"], d["H"], d["fd"]
        pct = max(0.0, min(100.0, float(d.get("shv", 0))))
        ang = math.radians(180.0 * pct / 100.0)
        n = max(1, int(d.get("leaves", 1)))
        wl = W / n
        pw = wl - 0.002
        wth = d.get("wth")
        bh = (wth / 2 + 0.0025 + 0.0175) if wth else (fd / 2 + 0.01 + 0.0175)
        for i in range(n):
            if i < n / 2:
                _persiana(mesh, T, d, 0, i * wl, pw, H, bh, ang, hw)
            else:
                _persiana(mesh, T, d, 1, (i + 1) * wl, pw, H, bh, ang, hw)
    return mesh.mesh


def curtain_auto_height(d: dict) -> float:
    return max(0.1, d["H"] + CURT_ABOVE + d["sill"])


def _cyl(mesh, T, a0, a1, b, c, r, n=12):
    pts = [(b + r * math.cos(2 * math.pi * i / n),
            c + r * math.sin(2 * math.pi * i / n)) for i in range(n)]
    for i in range(n):
        p, q = pts[i], pts[(i + 1) % n]
        f = mesh.add_face([T(a0, *p), T(a1, *p), T(a1, *q), T(a0, *q)])
        f.attrs["layer"] = LAYER_NAME
        _hide_edges(f)
    f = mesh.add_face([T(a0, *p) for p in reversed(pts)])
    f.attrs["layer"] = LAYER_NAME
    f = mesh.add_face([T(a1, *p) for p in pts])
    f.attrs["layer"] = LAYER_NAME


def _curtain_geom(d: dict):
    W, H, fd = d["W"], d["H"], d["fd"]
    wth = d.get("wth")
    half = (wth / 2) if wth else (fd / 2)
    over = 0.15
    b_rod = -(half + 0.09)
    b_cur = b_rod
    c_top = H + CURT_ABOVE
    h = float(d.get("cuh") or 0.0)
    if h <= 0:
        h = curtain_auto_height(d)
    h = max(0.1, h)
    return -over, W + over, b_cur, b_rod, c_top, c_top - h


def _panel(mesh, T, x0, x1, bc, c0, c1, fabric, side):
    w = max(0.02, x1 - x0)
    fabric = max(fabric, w)
    n = max(2, int(math.ceil(fabric / 0.14)))
    lam = w / n
    amp = 0.5 * math.sqrt(max(0.0, (fabric / (2 * n)) ** 2
                              - (w / (2 * n)) ** 2))
    amp = min(amp, 0.11)
    steps = n * 6
    prof = []
    for i in range(steps + 1):
        a = x0 + w * i / steps
        b = bc + amp * math.sin(2 * math.pi * i / steps * n)
        t = i / steps
        k = (1 - t) if side == 0 else t
        prof.append((a, b, c0 + 0.04 * k))

    for (a, b, cb), (a2, b2, cb2) in zip(prof, prof[1:]):
        f = mesh.add_face([T(a, b, cb), T(a2, b2, cb2),
                           T(a2, b2, c1), T(a, b, c1)])
        f.attrs["layer"] = LAYER_NAME
        f.attrs["back"] = True
        _hide_edges(f)


def _hide_edges(f) -> None:
    for e in (getattr(f, "edges", None) or ()):
        for attr, val in (("soft", True), ("smooth", True), ("hidden", True)):
            try:
                if hasattr(e, attr):
                    setattr(e, attr, val)
            except Exception:
                pass
        attrs = getattr(e, "attrs", None)
        if isinstance(attrs, dict):
            attrs.update(soft=True, smooth=True, hidden=True)


def curtain_meshes(d: dict):
    if not d.get("cur"):
        return None, None
    from core.mesh import Mesh
    T = _mapper(d)
    a_l, a_r, b_cur, b_rod, c_top, c_bot = _curtain_geom(d)
    L = a_r - a_l
    pct = max(0.0, min(100.0, float(d.get("cuv", 0)))) / 100.0
    cloth = PaintMesh(Mesh(), d, "curt", ZONE_NAME["curt"])
    rod = PaintMesh(Mesh(), d, "rod", ZONE_NAME["rod"])

    rr = 0.014
    c_rod = c_top + rr + 0.012
    _cyl(rod, T, a_l, a_r, b_rod, c_rod, rr)
    wth = d.get("wth")
    wall_b = -((wth / 2) if wth else (d["fd"] / 2))
    for a in (a_l + 0.08, a_r - 0.08):
        _box(rod, T, a - 0.01, a + 0.01, b_rod, wall_b, c_rod - 0.012,
             c_rod + 0.012, None)

    half_w = L / 2
    fabric = half_w * 1.5
    w = half_w * (1.0 - 0.78 * pct)
    _panel(cloth, T, a_l, a_l + w, b_cur, c_bot, c_top, fabric, 0)
    _panel(cloth, T, a_r - w, a_r, b_cur, c_bot, c_top, fabric, 1)
    return cloth.mesh, rod.mesh


def _arch_rise(d: dict) -> float:
    try:
        from . import porte
        return porte.arch_rise(d)
    except ImportError:
        return 0.0


def _outline_arch(T, W, H, fd, rise):
    zs = H - rise
    R = (W * W / 4.0 + rise * rise) / (2.0 * rise)
    cz = zs + rise - R
    th_r = math.atan2(zs - cz, W / 2.0)
    th_l = math.pi - th_r
    n = 24
    arc = [(W / 2.0 + R * math.cos(th_l + (th_r - th_l) * i / n),
            cz + R * math.sin(th_l + (th_r - th_l) * i / n)) for i in range(n + 1)]
    lines = []
    for b in (-fd / 2, fd / 2):
        lines += [(T(0, b, 0), T(W, b, 0)), (T(0, b, 0), T(0, b, zs)),
                  (T(W, b, 0), T(W, b, zs))]
        lines += [(T(p[0], b, p[1]), T(q[0], b, q[1])) for p, q in zip(arc, arc[1:])]
    for a, c in ((0, 0), (W, 0), (0, zs), (W, zs), (W / 2.0, H)):
        lines.append((T(a, -fd / 2, c), T(a, fd / 2, c)))
    return lines


def outline_lines(d: dict):
    T = _mapper(d)
    W, H, fd = d["W"], d["H"], d["fd"]
    rise = _arch_rise(d)
    if rise > 1e-3:
        return _outline_arch(T, W, H, fd, rise)
    pts = [T(a, b, c) for c in (0, H) for b in (-fd / 2, fd / 2)
           for a in (0, W)]
    pairs = []
    for base in (0, 4):
        pairs += [(base, base + 1), (base + 2, base + 3),
                  (base, base + 2), (base + 1, base + 3)]
    pairs += [(i, i + 4) for i in range(4)]
    return [(pts[i], pts[j]) for i, j in pairs]


def _sash_handle(hw, T, x, zc, sd, dr=1) -> None:
    for s_ in (-1,):
        inn, out = s_ * sd / 2, s_ * (sd / 2 + 0.04)
        rs = s_ * (sd / 2 + 0.008)
        _box(hw, T, x - 0.025, x + 0.025, min(inn, rs), max(inn, rs),
             zc - 0.025, zc + 0.025, None)
        _box(hw, T, x - 0.01, x + 0.01, min(inn, out), max(inn, out),
             zc - 0.01, zc + 0.01, None)
        _box(hw, T, x - 0.01, x + 0.01, min(out, out - s_ * 0.016),
             max(out, out - s_ * 0.016), zc - 0.10, zc + 0.01, None)


_MAN_V = ((-0.02222,-0.00919,0),(-0.02372,-0.00769,0),(-0.02297,-0.00899,0),(-0.02352,-0.00844,0),(-0.02372,0.11523,0),(-0.02222,0.11673,0),(-0.02352,0.11598,0),(-0.02297,0.11652,0),(-0.02222,-0.00919,0.00616),(-0.02222,-0.00769,0.00766),(-0.02372,-0.00769,0.00616),(-0.02222,-0.00899,0.0069),(-0.02297,-0.00899,0.00616),(-0.02294,-0.0088,0.00687),(-0.02297,-0.00769,0.00746),(-0.02222,-0.00844,0.00746),(-0.02294,-0.00841,0.00726),(-0.02352,-0.00844,0.00616),(-0.02352,-0.00769,0.0069),(-0.02332,-0.00841,0.00687),(-0.02222,0.11673,0.00616),(-0.02372,0.11523,0.00616),(-0.02222,0.11523,0.00766),(-0.02297,0.11653,0.00616),(-0.02222,0.11653,0.0069),(-0.02294,0.11633,0.00687),(-0.02352,0.11523,0.0069),(-0.02352,0.11598,0.00616),(-0.02332,0.11594,0.00687),(-0.02222,0.11598,0.00746),(-0.02297,0.11523,0.00746),(-0.02294,0.11594,0.00726),(0.02372,-0.00769,0),(0.02222,-0.00919,0),(0.02352,-0.00844,0),(0.02297,-0.00899,0),(0.02222,0.11673,0),(0.02372,0.11523,0),(0.02297,0.11652,0),(0.02352,0.11598,0),(0.02222,-0.00919,0.00616),(0.02372,-0.00769,0.00616),(0.02222,-0.00769,0.00766),(0.02297,-0.00899,0.00616),(0.02222,-0.00899,0.0069),(0.02294,-0.0088,0.00687),(0.02352,-0.00769,0.0069),(0.02352,-0.00844,0.00616),(0.02332,-0.00841,0.00687),(0.02222,-0.00844,0.00746),(0.02297,-0.00769,0.00746),(0.02294,-0.00841,0.00726),(0.02222,0.11673,0.00616),(0.02222,0.11523,0.00766),(0.02372,0.11523,0.00616),(0.02222,0.11653,0.0069),(0.02297,0.11653,0.00616),(0.02294,0.11633,0.00687),(0.02297,0.11523,0.00746),(0.02222,0.11598,0.00746),(0.02294,0.11594,0.00726),(0.02352,0.11598,0.00616),(0.02352,0.11523,0.0069),(0.02332,0.11594,0.00687),(-0.01448,0.03343,0.02039),(-0.01298,0.03193,0.02039),(-0.01298,0.03343,0.02189),(-0.01428,0.03269,0.02039),(-0.01428,0.03343,0.02114),(-0.01408,0.03272,0.0211),(-0.01298,0.03214,0.02114),(-0.01373,0.03214,0.02039),(-0.01369,0.03233,0.0211),(-0.01373,0.03343,0.02169),(-0.01298,0.03269,0.02169),(-0.01369,0.03272,0.02149),(-0.01448,0.0615,0.02039),(-0.01298,0.0615,0.02189),(-0.01298,0.063,0.02039),(-0.01428,0.0615,0.02114),(-0.01428,0.06225,0.02039),(-0.01408,0.06222,0.0211),(-0.01298,0.06225,0.02169),(-0.01373,0.0615,0.02169),(-0.01369,0.06222,0.02149),(-0.01373,0.0628,0.02039),(-0.01298,0.0628,0.02114),(-0.01369,0.0626,0.0211),(0.01298,0.03193,0.02039),(0.01448,0.03343,0.02039),(0.01298,0.03343,0.02189),(0.01372,0.03214,0.02039),(0.01298,0.03214,0.02114),(0.01369,0.03233,0.0211),(0.01427,0.03343,0.02114),(0.01427,0.03269,0.02039),(0.01408,0.03272,0.0211),(0.01298,0.03269,0.02169),(0.01372,0.03343,0.02169),(0.01369,0.03272,0.02149),(0.01298,0.063,0.02039),(0.01298,0.0615,0.02189),(0.01448,0.0615,0.02039),(0.01298,0.0628,0.02114),(0.01372,0.0628,0.02039),(0.01369,0.0626,0.0211),(0.01372,0.0615,0.02169),(0.01298,0.06225,0.02169),(0.01369,0.06222,0.02149),(0.01427,0.06225,0.02039),(0.01427,0.0615,0.02114),(0.01408,0.06222,0.0211),(-0.01448,0.0615,0.00916),(-0.01298,0.063,0.00916),(-0.01298,0.0615,0.00766),(-0.01428,0.06225,0.00916),(-0.01428,0.0615,0.00841),(-0.01408,0.06222,0.00844),(-0.01298,0.0628,0.00841),(-0.01373,0.0628,0.00916),(-0.01369,0.0626,0.00844),(-0.01373,0.0615,0.00786),(-0.01298,0.06225,0.00786),(-0.01369,0.06222,0.00805),(-0.01448,0.03343,0.00916),(-0.01298,0.03343,0.00766),(-0.01298,0.03193,0.00916),(-0.01428,0.03343,0.00841),(-0.01428,0.03269,0.00916),(-0.01408,0.03272,0.00844),(-0.01298,0.03269,0.00786),(-0.01373,0.03343,0.00786),(-0.01369,0.03272,0.00805),(-0.01373,0.03214,0.00916),(-0.01298,0.03214,0.00841),(-0.01369,0.03233,0.00844),(0.01298,0.03193,0.00916),(0.01298,0.03343,0.00766),(0.01448,0.03343,0.00916),(0.01298,0.03214,0.00841),(0.01372,0.03214,0.00916),(0.01369,0.03233,0.00844),(0.01372,0.03343,0.00786),(0.01298,0.03269,0.00786),(0.01369,0.03272,0.00805),(0.01427,0.03269,0.00916),(0.01427,0.03343,0.00841),(0.01408,0.03272,0.00844),(0.01298,0.063,0.00916),(0.01448,0.0615,0.00916),(0.01298,0.0615,0.00766),(0.01372,0.0628,0.00916),(0.01298,0.0628,0.00841),(0.01369,0.0626,0.00844),(0.01427,0.0615,0.00841),(0.01427,0.06225,0.00916),(0.01408,0.06222,0.00844),(0.01298,0.06225,0.00786),(0.01372,0.0615,0.00786),(0.01369,0.06222,0.00805),(-0.01448,0.03343,0.02339),(-0.01298,0.03343,0.02189),(-0.01298,0.03193,0.02339),(-0.01428,0.03343,0.02264),(-0.01428,0.03269,0.02339),(-0.01408,0.03272,0.02267),(-0.01298,0.03269,0.02209),(-0.01373,0.03343,0.02209),(-0.01369,0.03272,0.02228),(-0.01373,0.03214,0.02339),(-0.01298,0.03214,0.02264),(-0.01369,0.03233,0.02267),(-0.01448,0.0615,0.02339),(-0.01298,0.063,0.02339),(-0.01298,0.0615,0.02189),(-0.01428,0.06225,0.02339),(-0.01428,0.0615,0.02264),(-0.01408,0.06222,0.02267),(-0.01298,0.0628,0.02264),(-0.01373,0.0628,0.02339),(-0.01369,0.0626,0.02267),(-0.01373,0.0615,0.02209),(-0.01298,0.06225,0.02209),(-0.01369,0.06222,0.02228),(0.01298,0.03193,0.02339),(0.01298,0.03343,0.02189),(0.01448,0.03343,0.02339),(0.01298,0.03214,0.02264),(0.01372,0.03214,0.02339),(0.01369,0.03233,0.02267),(0.01372,0.03343,0.02209),(0.01298,0.03269,0.02209),(0.01369,0.03272,0.02228),(0.01427,0.03269,0.02339),(0.01427,0.03343,0.02264),(0.01408,0.03272,0.02267),(0.01298,0.063,0.02339),(0.01448,0.0615,0.02339),(0.01298,0.0615,0.02189),(0.01372,0.0628,0.02339),(0.01298,0.0628,0.02264),(0.01369,0.0626,0.02267),(0.01427,0.0615,0.02264),(0.01427,0.06225,0.02339),(0.01408,0.06222,0.02267),(0.01298,0.06225,0.02209),(0.01372,0.0615,0.02209),(0.01369,0.06222,0.02228),(-0.01448,0.0615,0.03664),(-0.01298,0.063,0.03674),(-0.01428,0.06225,0.03669),(-0.01373,0.0628,0.03673),(-0.01292,0.03043,0.03464),(-0.01453,0.03343,0.03603),(-0.01298,0.03193,0.03309),(-0.01369,0.03137,0.03483),(-0.01294,0.03117,0.03439),(-0.01367,0.03168,0.03459),(-0.01428,0.0327,0.0351),(-0.01427,0.03246,0.03533),(-0.0141,0.03218,0.03483),(-0.01296,0.03171,0.03383),(-0.01372,0.03216,0.03402),(-0.01368,0.03193,0.03433),(0.01292,0.03043,0.03464),(0.01298,0.03193,0.03309),(0.01448,0.03343,0.03603),(0.01294,0.03117,0.03439),(0.01368,0.03137,0.03483),(0.01367,0.03168,0.03459),(0.01371,0.03216,0.03402),(0.01296,0.03171,0.03383),(0.01368,0.03193,0.03433),(0.01425,0.03246,0.03533),(0.01425,0.0327,0.0351),(0.01408,0.03218,0.03483),(0.01298,0.063,0.03674),(0.01448,0.0615,0.03664),(0.01373,0.0628,0.03673),(0.01427,0.06225,0.03669),(-0.01448,0.0615,0.04603),(-0.01298,0.0615,0.04753),(-0.01298,0.063,0.04603),(-0.01428,0.0615,0.04678),(-0.01428,0.06225,0.04603),(-0.01408,0.06222,0.04675),(-0.01298,0.06225,0.04733),(-0.01372,0.0615,0.04733),(-0.01369,0.06222,0.04714),(-0.01373,0.0628,0.04603),(-0.01298,0.0628,0.04678),(-0.01369,0.0626,0.04675),(-0.01448,0.03193,0.04603),(-0.01298,0.03193,0.04753),(-0.01427,0.03193,0.04678),(-0.01373,0.03193,0.04733),(0.01298,0.03193,0.04753),(0.01448,0.03193,0.04603),(0.01373,0.03193,0.04733),(0.01427,0.03193,0.04678),(0.01298,0.063,0.04603),(0.01298,0.0615,0.04753),(0.01448,0.0615,0.04603),(0.01298,0.0628,0.04678),(0.01372,0.0628,0.04603),(0.01369,0.0626,0.04675),(0.01372,0.0615,0.04733),(0.01298,0.06225,0.04733),(0.01369,0.06222,0.04714),(0.01427,0.06225,0.04603),(0.01427,0.0615,0.04678),(0.01408,0.06222,0.04675),(0.0078,-0.11523,0.03962),(0.00931,-0.11523,0.04112),(0.00775,-0.11673,0.04117),(0.00855,-0.11523,0.03982),(0.00778,-0.11597,0.03985),(0.0085,-0.11594,0.04004),(0.00908,-0.11597,0.04115),(0.0091,-0.11523,0.04037),(0.00888,-0.11594,0.04043),(0.00776,-0.11652,0.04042),(0.00851,-0.11652,0.04117),(0.00848,-0.11633,0.04044),(-0.0078,-0.11523,0.03962),(-0.00775,-0.11673,0.04117),(-0.00931,-0.11523,0.04112),(-0.00778,-0.11597,0.03985),(-0.00855,-0.11523,0.03982),(-0.0085,-0.11594,0.04004),(-0.00851,-0.11652,0.04117),(-0.00776,-0.11652,0.04042),(-0.00848,-0.11633,0.04044),(-0.00911,-0.11523,0.04037),(-0.00908,-0.11597,0.04115),(-0.00889,-0.11594,0.04043),(0.0078,-0.11523,0.04753),(0.00775,-0.11673,0.04603),(0.00931,-0.11523,0.04603),(0.00778,-0.11597,0.04733),(0.00855,-0.11523,0.04733),(0.0085,-0.11594,0.04714),(0.00851,-0.11652,0.04603),(0.00776,-0.11652,0.04678),(0.00848,-0.11633,0.04675),(0.0091,-0.11523,0.04678),(0.00908,-0.11597,0.04603),(0.00888,-0.11594,0.04675),(-0.0078,-0.11523,0.04753),(-0.00931,-0.11523,0.04603),(-0.00775,-0.11673,0.04603),(-0.00856,-0.11523,0.04733),(-0.00778,-0.11597,0.04733),(-0.0085,-0.11594,0.04714),(-0.00908,-0.11597,0.04603),(-0.00911,-0.11523,0.04678),(-0.00889,-0.11594,0.04675),(-0.00776,-0.11652,0.04678),(-0.00851,-0.11652,0.04603),(-0.00848,-0.11633,0.04675))
_MAN_F = ((8,11,13,12),(11,15,16,13),(9,14,16,15),(14,18,19,16),(10,17,19,18),(17,12,13,19),(13,16,19),(20,23,25,24),(23,27,28,25),(21,26,28,27),(26,30,31,28),(22,29,31,30),(29,24,25,31),(25,28,31),(40,43,45,44),(43,47,48,45),(41,46,48,47),(46,50,51,48),(42,49,51,50),(49,44,45,51),(45,48,51),(52,55,57,56),(55,59,60,57),(53,58,60,59),(58,62,63,60),(54,61,63,62),(61,56,57,63),(57,60,63),(64,67,69,68),(67,71,72,69),(65,70,72,71),(70,74,75,72),(66,73,75,74),(73,68,69,75),(69,72,75),(76,79,81,80),(79,83,84,81),(77,82,84,83),(82,86,87,84),(78,85,87,86),(85,80,81,87),(81,84,87),(88,91,93,92),(91,95,96,93),(89,94,96,95),(94,98,99,96),(90,97,99,98),(97,92,93,99),(93,96,99),(100,103,105,104),(103,107,108,105),(101,106,108,107),(106,110,111,108),(102,109,111,110),(109,104,105,111),(105,108,111),(112,115,117,116),(115,119,120,117),(113,118,120,119),(118,122,123,120),(114,121,123,122),(121,116,117,123),(117,120,123),(124,127,129,128),(127,131,132,129),(125,130,132,131),(130,134,135,132),(126,133,135,134),(133,128,129,135),(129,132,135),(136,139,141,140),(139,143,144,141),(137,142,144,143),(142,146,147,144),(138,145,147,146),(145,140,141,147),(141,144,147),(148,151,153,152),(151,155,156,153),(149,154,156,155),(154,158,159,156),(150,157,159,158),(157,152,153,159),(153,156,159),(160,163,165,164),(163,167,168,165),(161,166,168,167),(166,170,171,168),(162,169,171,170),(169,164,165,171),(165,168,171),(172,175,177,176),(175,179,180,177),(173,178,180,179),(178,182,183,180),(174,181,183,182),(181,176,177,183),(177,180,183),(184,187,189,188),(187,191,192,189),(185,190,192,191),(190,194,195,192),(186,193,195,194),(193,188,189,195),(189,192,195),(196,199,201,200),(199,203,204,201),(197,202,204,203),(202,206,207,204),(198,205,207,206),(205,200,201,207),(201,204,207),(212,215,217,216),(215,219,220,217),(213,218,220,219),(218,222,223,220),(214,221,223,222),(221,216,217,223),(217,220,223),(224,227,229,228),(227,231,232,229),(225,230,232,231),(230,234,235,232),(226,233,235,234),(233,228,229,235),(229,232,235),(240,243,245,244),(243,247,248,245),(241,246,248,247),(246,250,251,248),(242,249,251,250),(249,244,245,251),(245,248,251),(260,263,265,264),(263,267,268,265),(261,266,268,267),(266,270,271,268),(262,269,271,270),(269,264,265,271),(265,268,271),(272,275,277,276),(275,279,280,277),(273,278,280,279),(278,282,283,280),(274,281,283,282),(281,276,277,283),(277,280,283),(284,287,289,288),(287,291,292,289),(285,290,292,291),(290,294,295,292),(286,293,295,294),(293,288,289,295),(289,292,295),(296,299,301,300),(299,303,304,301),(297,302,304,303),(302,306,307,304),(298,305,307,306),(305,300,301,307),(301,304,307),(308,311,313,312),(311,315,316,313),(309,314,316,315),(314,318,319,316),(310,317,319,318),(317,312,313,319),(313,316,319),(10,1,3,17),(17,3,2,12),(12,2,0,8),(4,21,27,6),(6,27,23,7),(7,23,20,5),(21,10,18,26),(26,18,14,30),(30,14,9,22),(42,9,15,49),(49,15,11,44),(44,11,8,40),(22,53,59,29),(29,59,55,24),(24,55,52,20),(53,42,50,58),(58,50,46,62),(62,46,41,54),(32,41,47,34),(34,47,43,35),(35,43,40,33),(54,37,39,61),(61,39,38,56),(56,38,36,52),(76,64,68,79),(79,68,73,83),(83,73,66,77),(90,66,74,97),(97,74,70,92),(92,70,65,88),(77,101,107,82),(82,107,103,86),(86,103,100,78),(101,90,98,106),(106,98,94,110),(110,94,89,102),(114,125,131,121),(121,131,127,116),(116,127,124,112),(136,126,134,139),(139,134,130,143),(143,130,125,137),(113,148,152,118),(118,152,157,122),(122,157,150,114),(149,138,146,154),(154,146,142,158),(158,142,137,150),(88,136,140,91),(91,140,145,95),(95,145,138,89),(148,100,104,151),(151,104,109,155),(155,109,102,149),(64,124,128,67),(67,128,133,71),(71,133,126,65),(112,76,80,115),(115,80,85,119),(119,85,78,113),(174,161,167,181),(181,167,163,176),(176,163,160,172),(184,162,170,187),(187,170,166,191),(191,166,161,185),(173,196,200,178),(178,200,205,182),(182,205,198,174),(197,186,194,202),(202,194,190,206),(206,190,185,198),(224,212,216,227),(227,216,221,231),(231,221,214,225),(172,208,210,175),(175,210,211,179),(179,211,209,173),(237,197,203,239),(239,203,199,238),(238,199,196,236),(162,214,222,169),(169,222,218,164),(164,218,213,160),(225,184,188,230),(230,188,193,234),(234,193,186,226),(240,252,254,243),(243,254,255,247),(247,255,253,241),(241,261,267,246),(246,267,263,250),(250,263,260,242),(261,256,258,266),(266,258,259,270),(270,259,257,262),(208,240,244,210),(210,244,249,211),(211,249,242,209),(262,237,239,269),(269,239,238,264),(264,238,236,260),(274,285,291,281),(281,291,287,276),(276,287,284,272),(296,308,312,299),(299,312,317,303),(303,317,310,297),(285,310,318,290),(290,318,314,294),(294,314,309,286),(297,274,282,302),(302,282,278,306),(306,278,273,298),(252,309,315,254),(254,315,311,255),(255,311,308,253),(298,257,259,305),(305,259,258,300),(300,258,256,296),(212,284,288,215),(215,288,293,219),(219,293,286,213),(226,273,279,233),(233,279,275,228),(228,275,272,224),(8,0,33,40),(1,10,21,4),(52,36,5,20),(9,42,53,22),(41,32,37,54),(64,76,112,124),(66,90,101,77),(88,65,126,136),(78,100,148,113),(102,89,138,149),(125,114,150,137),(172,160,213,208),(161,174,198,185),(162,184,225,214),(196,173,209,236),(186,197,237,226),(208,213,252,240),(236,209,242,260),(252,213,286,309),(212,224,272,284),(226,237,262,257),(226,257,298,273),(253,256,261,241),(256,253,308,296),(285,274,297,310))


_MAN_H = 0.18
_MAN_S = _MAN_H / (max(v[1] for v in _MAN_V) - min(v[1] for v in _MAN_V))


def _lever(hw, T, x, zc, b_surf) -> None:
    for f in _MAN_F:
        pts = [T(x + _MAN_V[i][0] * _MAN_S, b_surf - _MAN_V[i][2] * _MAN_S,
                 zc + _MAN_V[i][1] * _MAN_S)
               for i in f]
        fc = hw.add_face(pts)
        fc.attrs["layer"] = LAYER_NAME


def handle_mesh(d: dict):
    from core.mesh import Mesh
    T = _mapper(d)
    W, H, fw, fd, sw = d["W"], d["H"], d["fw"], d["fd"], d["sw"]
    n = int(d["leaves"])
    sd = fd * 0.6
    hw = PaintMesh(Mesh(), d, "handle", ZONE_NAME["handle"])
    zc = min(fw + (H - 2 * fw) * 0.47, H - fw - 0.1)
    if d.get("tipo") == "sc":
        ra0, _ra1, rb0, _rb1 = _sc_sashes(d)[1]
        _lever(hw, T, ra0 + sw / 2, zc, rb0)
    else:
        mw = _mullion(d)
        wl = sash_width(d)
        for i in range(n):
            if mw > 0:                 # separate windows: a lever on each
                _lever(hw, T, fw + i * (wl + mw) + wl - sw / 2, zc, -sd / 2)
            elif n == 1 or i < n - 1:
                xm = fw + (i + 1) * wl
                _lever(hw, T, xm - sw / 2 if n == 1 else xm + sw / 2, zc,
                       -sd / 2)
    if (d.get("shut") or "") == "nap":
        shutter_mesh(d, hw)
    return hw.mesh


def _reveal_pts(d: dict):
    t = d.get("spt") or ""
    wth = d.get("wth")
    if t not in ("ris", "str", "rs") or not wth or wth < 0.05:
        return None
    sgn = 1.0 if d.get("spl", "e") == "e" else -1.0
    half = wth / 2.0
    dr = max(0.0, min(float(d.get("spd", SPAL_DEFAULT["spd"])), wth - 0.02))
    lr = max(0.0, float(d.get("spw", SPAL_DEFAULT["spw"])))
    tg = math.tan(math.radians(max(0.0, min(80.0, float(
        d.get("sba", SPAL_DEFAULT["sba"]))))))
    sd = max(0.0, float(d.get("sbd", SPAL_DEFAULT["sbd"])))
    if t == "ris":
        tp = [(0, lr), (dr, lr), (dr, 0), (wth, 0)]
    elif t == "str":
        sd = min(sd, wth - 0.02)
        tp = [(0, sd * tg), (sd, 0), (wth, 0)]
    else:
        sd = min(sd, max(0.0, wth - dr - 0.02))
        tp = [(0, lr), (dr, lr), (dr, 0), (wth - sd, 0), (wth, sd * tg)]
    pts = [(sgn * (half - t_), e) for t_, e in tp]
    big = max(e for _b, e in pts)
    if big < 1e-4:
        return None
    return pts, big


def reveal_extent(d: dict) -> float:
    r = _reveal_pts(d)
    return r[1] if r else 0.0


def _dedupe_ring(ring):
    out = []
    for q in ring:
        if not out or abs(q[0] - out[-1][0]) > 1e-6 \
                or abs(q[1] - out[-1][1]) > 1e-6:
            out.append(q)
    if len(out) > 1 and abs(out[0][0] - out[-1][0]) < 1e-6 \
            and abs(out[0][1] - out[-1][1]) < 1e-6:
        out.pop()
    return out


def _fill_prism(mesh, T, ring, c0, c1, style=None) -> None:
    ring = _dedupe_ring(ring)
    if len(ring) < 3:
        return
    area = sum(ring[i][0] * ring[(i + 1) % len(ring)][1]
               - ring[(i + 1) % len(ring)][0] * ring[i][1]
               for i in range(len(ring)))
    if area < 0:
        ring.reverse()

    def add(pts, mid_b=None):
        f = mesh.add_face([T(*v) for v in pts])
        if style is not None:
            style(f, mid_b)
        else:
            f.attrs["color"] = muri.EDGE_COLOR
            f.attrs["mat"] = muri.EDGE_NAME
            f.attrs["layer"] = muri.LAYER_NAME

    for a, b, c in muri._ear_clip(ring):
        add([(a[0], a[1], c1), (b[0], b[1], c1), (c[0], c[1], c1)])
        add([(a[0], a[1], c0), (c[0], c[1], c0), (b[0], b[1], c0)])
    n = len(ring)
    for i in range(n):
        j = (i + 1) % n
        add([(ring[i][0], ring[i][1], c0), (ring[j][0], ring[j][1], c0),
             (ring[j][0], ring[j][1], c1), (ring[i][0], ring[i][1], c1)],
            (ring[i][1] + ring[j][1]) / 2.0)
    _nascondi_linee_prisma(mesh, T, ring, c0, c1)


def _nascondi_linee_prisma(mesh, T, ring, c0, c1) -> None:
    real = getattr(mesh, "mesh", mesh)
    n = len(ring)

    def key(a, b, c):
        p = T(a, b, c)
        return (round(p.x(), 4), round(p.y(), 4), round(p.z(), 4))

    def ekey(p, q):
        return frozenset((p, q))

    keep = set()
    hide = set()
    for i in range(n):
        j = (i + 1) % n
        for c in (c0, c1):
            keep.add(ekey(key(ring[i][0], ring[i][1], c),
                          key(ring[j][0], ring[j][1], c)))
        a, b, c_ = ring[i - 1], ring[i], ring[j]
        cr = ((b[0] - a[0]) * (c_[1] - b[1])
              - (b[1] - a[1]) * (c_[0] - b[0]))
        if abs(cr) < 1e-9:
            hide.add(ekey(key(b[0], b[1], c0), key(b[0], b[1], c1)))
    zs = {round(T(0, 0, c).z(), 4) for c in (c0, c1)}
    for e in real.edges:
        try:
            k = ekey((round(e.a.x(), 4), round(e.a.y(), 4), round(e.a.z(), 4)),
                     (round(e.b.x(), 4), round(e.b.y(), 4), round(e.b.z(), 4)))
            za, zb = round(e.a.z(), 4), round(e.b.z(), 4)
            diag = za == zb and za in zs and k not in keep
            if diag or k in hide:
                setattr(e, muri.EDGE_FLAG, True)
        except Exception:
            pass


def reveal_mesh(d: dict):
    r = _reveal_pts(d)
    if r is None:
        return None
    from core.mesh import Mesh
    pts, big = r
    T = _mapper(d)
    W, H = d["W"], d["H"]
    left = [(-e, b) for b, e in pts] + [(-big, pts[-1][0]),
                                        (-big, pts[0][0])]
    right = [(W - x, y) for x, y in left]
    wp = d.get("wpaint") or {}
    pos_left = not d.get("flip")

    def style(f, mid_b):
        f.attrs["layer"] = muri.LAYER_NAME
        if mid_b is None:
            zone = "e"
        else:
            zone = "l" if (mid_b > 0) == pos_left else "r"
        tex = wp.get("tex_" + zone)
        if zone == "e":
            if not muri.paint_face(f, wp.get("col_e"), tex):
                f.attrs["color"] = muri.EDGE_COLOR
                f.attrs["mat"] = muri.EDGE_NAME
        elif muri.paint_face(f, wp.get("col_" + zone), tex) and not tex:
            f.attrs["mat"] = (muri.INNER_NAME if zone == "l"
                              else muri.OUTER_NAME)

    mesh = Mesh()
    _fill_prism(mesh, T, left, 0.0, H, style)
    _fill_prism(mesh, T, right, 0.0, H, style)
    return mesh


def _part(name, mesh, pose=None):
    from core.group import Group
    part = Group(mesh, name=name)
    part.xform = QMatrix4x4(pose) if pose is not None else QMatrix4x4()
    part.component = False
    return part


def _parts(d: dict, pose=None):
    frame, glass = window_meshes(d)
    parts = [_part(tr("Telaio"), frame, pose), _part(tr("Vetro"), glass, pose),
             _part(tr("Soglia"), sill_mesh(d), pose)]
    rv = reveal_mesh(d)
    if rv is not None:
        parts.append(_part(tr("Spalletta"), rv, pose))
    shut = shutter_mesh(d)
    if shut is not None:
        parts.append(_part(tr("Oscuranti"), shut, pose))
    parts.append(_part(tr("Maniglia"), handle_mesh(d), pose))
    cloth, rod = curtain_meshes(d)
    if cloth is not None:
        parts.append(_part(tr("Tenda"), cloth, pose))
        parts.append(_part(tr("Bastone tenda"), rod, pose))
    return parts


def window_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "o" in data else None


def _pose(group) -> QMatrix4x4:
    for k in getattr(group, "children", None) or ():
        if k.xform is not None:
            return QMatrix4x4(k.xform)
    return QMatrix4x4()


def _next_name(scene) -> str:
    used = {g.name for g in scene.groups}
    n = 1
    while tr("Finestra {0}").format(n) in used:
        n += 1
    return tr("Finestra {0}").format(n)


def make_window(scene, p: dict, place: dict):
    from core.group import Group
    d = clean_paint(dict(p))
    d.update(o=list(place["o"]), u=list(place["u"]),
             flip=bool(place["flip"]))
    for k in ("lv", "lvn", "off", "wth", "wpaint"):
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
    _ifc.tag(g, "IfcWindow", name)
    g.ext = {KEY: d}
    scene.groups.append(g)
    return g


def rebuild_window(group, p: dict) -> None:
    d = dict(window_data(group))
    d.update(p)
    clean_paint(d)
    pose = _pose(group)
    group.children = _parts(d, pose)
    _ifc.tag(group, "IfcWindow")
    ext = dict(group.ext or {})
    ext[KEY] = d
    group.ext = ext


class FinestraCommand(Command):

    def __init__(self, mutate) -> None:
        self.mutate = mutate
        self.before = self.after = None

    @staticmethod
    def _capture(scene) -> dict:
        return {
            "mesh": scene.mesh.capture_state(),
            "layers": list(scene.layers),
            "groups": list(scene.groups),
            "state": [(g, list(g.children or ()), g.ifc and dict(g.ifc),
                       copy.deepcopy(getattr(g, "ext", None)), g.xform)
                      for g in scene.groups],
        }

    @staticmethod
    def _restore(scene, s) -> None:
        scene.mesh.restore_state(s["mesh"])
        scene.layers[:] = s["layers"]
        scene.groups[:] = s["groups"]
        for g, kids, ifc, ext, xform in s["state"]:
            g.children, g.ifc, g.xform = list(kids), ifc and dict(ifc), xform
            g.ext = copy.deepcopy(ext)
        scene.selection.intersection_update(
            set(scene.mesh.faces) | set(scene.mesh.edges) | set(scene.groups))

    def do(self, scene) -> None:
        if self.after is None:
            self.before = self._capture(scene)
            try:
                self.mutate(scene)
            except BaseException:
                self._restore(scene, self.before)
                raise
            self.after = self._capture(scene)
        else:
            self._restore(scene, self.after)
        scene.version += 1

    def undo(self, scene) -> None:
        self._restore(scene, self.before)
        scene.version += 1


def _wall_pose(group) -> QMatrix4x4:
    return _full_pose(group)


def _poly_hit(w, lp, pose):
    pts = [tuple(p) for p in w["poly"]]
    edges, _tot = muri.poly_edges(pts)
    best = None
    for i in muri.poly_face_edges(pts):
        S0, S1, p, q = edges[i]
        L = S1 - S0
        if L < 1e-9:
            continue
        ux, uy = (q[0] - p[0]) / L, (q[1] - p[1]) / L
        t = (lp.x() - p[0]) * ux + (lp.y() - p[1]) * uy
        if t < -WALL_TOL or t > L + WALL_TOL:
            continue
        o = (lp.x() - p[0]) * (-uy) + (lp.y() - p[1]) * ux
        th = muri.poly_depth(pts, i, max(0.0, min(L, t)), w.get("th", 0.3))
        dist = max(-o, o - th)
        if dist > WALL_TOL:
            continue
        if best is None or abs(o) < best[0]:
            A = pose.map(QVector3D(p[0], p[1], w["z0"]))
            B = pose.map(QVector3D(q[0], q[1], w["z0"]))
            best = (abs(o), A, B, th / 2.0, dict(w, th=th), dist)
    if best is None:
        return None
    return best[1], best[2], best[3], best[4], best[5]


def find_wall(scene, pt: QVector3D, level_id=None):
    best, best_dist = None, None
    for g in scene.groups:
        w = (getattr(g, "ext", None) or {}).get(WALL_KEY)
        if not isinstance(w, dict) or "a" not in w:
            continue
        if level_id and w.get("lv") and w["lv"] != level_id:
            continue
        pose = _wall_pose(g)
        inv, ok = pose.inverted()
        if not ok:
            continue
        lp = inv.map(pt)
        if w.get("poly"):
            hit = _poly_hit(w, lp, pose)
            if hit is not None and (best_dist is None or hit[4] < best_dist):
                best, best_dist = hit[:4], hit[4]
            continue
        ax, ay = w["a"]
        bx, by = w["b"]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy)
        if L < 1e-9:
            continue
        ux, uy = dx / L, dy / L
        s = (lp.x() - ax) * ux + (lp.y() - ay) * uy
        off = (lp.x() - ax) * (-uy) + (lp.y() - ay) * ux
        th = muri.wall_th_at(w, min(max(s, 0.0), L))
        dl, dr = {"left": (0.0, th), "right": (th, 0.0)}.get(
            w["align"], (th / 2, th / 2))
        centre = (dl - dr) / 2
        dist = abs(off - centre) - th / 2
        if dist > WALL_TOL or s < -WALL_TOL or s > L + WALL_TOL:
            continue
        if best_dist is None or dist < best_dist:
            A = pose.map(QVector3D(ax, ay, w["z0"]))
            B = pose.map(QVector3D(bx, by, w["z0"]))
            best, best_dist = (A, B, centre,
                               dict(w, th=th) if w.get("th_b") is not None
                               else w), dist
    return best


def _wall_paint(w: dict) -> dict:
    return {k: copy.deepcopy(w[k]) for k in muri.PAINT_KEYS if w.get(k)}


def placement(scene, world: QVector3D, flip: bool, level_id=None) -> dict:
    wall = find_wall(scene, world, level_id)
    if wall is None:
        return {"o": [world.x(), world.y(), world.z()], "u": [1.0, 0.0],
                "flip": flip}
    A, B, centre, w = wall
    dx, dy = B.x() - A.x(), B.y() - A.y()
    L = math.hypot(dx, dy)
    ux, uy = dx / L, dy / L
    s = (world.x() - A.x()) * ux + (world.y() - A.y()) * uy
    nx, ny = -uy, ux
    out = {"o": [A.x() + ux * s + nx * centre,
                 A.y() + uy * s + ny * centre, A.z()],
           "u": [ux, uy], "flip": flip}
    for k in ("lv", "lvn", "off"):
        if w.get(k) is not None:
            out[k] = w[k]
    out["wth"] = w["th"]
    out["wpaint"] = _wall_paint(w)
    return out


def next_edge(settings) -> None:
    """Space while placing: the cursor holds the left edge, then the middle,
    then the right edge (the unit flipped, as before), then the left again."""
    if settings.mid:
        settings.mid, settings.flip = False, True
    elif settings.flip:
        settings.flip = False
    else:
        settings.mid = True


def edge_word(settings, caps: bool = False) -> str:
    """Which part the cursor holds, as the status texts say it."""
    if settings.mid and not settings.flip:
        return tr("CENTRO") if caps else tr("centro")
    if settings.flip:
        return tr("DESTRO") if caps else tr("destro")
    return tr("SINISTRO") if caps else tr("sinistro")


def place_edge(scene, world: QVector3D, settings, width: float) -> dict:
    """placement() for the edge chosen with Space: held by the middle, the
    unit is moved back by half its width along the wall."""
    place = placement(scene, world, settings.flip, settings.level)
    if settings.mid and not settings.flip:
        (ux, uy), _n = _axes(place)
        ox, oy, oz = place["o"]
        place["o"] = [ox - ux * width / 2, oy - uy * width / 2, oz]
    return place


def _full_pose(g) -> QMatrix4x4:
    gx = getattr(g, "xform", None)
    m = QMatrix4x4(gx) if gx is not None else QMatrix4x4()
    return m * _pose(g)


def _opening_data(g):
    d = window_data(g)
    if d is None:
        try:
            from . import porte
            d = porte.door_data(g)
        except ImportError:
            d = None
    return d


def _signature(scene):
    sig = []
    for g in scene.groups:
        d = _opening_data(g)
        if d is None:
            d = muri.wall_data(g)
        if d is None:
            try:
                from . import tetto
                d = tetto.roof_data(g)
            except ImportError:
                d = None
        if d is None:
            try:
                from . import lucernari
                d = lucernari.sky_data(g)
            except ImportError:
                d = None
        if d is None:
            try:
                from . import abbaino
                d = abbaino.abb_data(g)
            except ImportError:
                d = None
        if d is None:
            continue
        m = _full_pose(g)
        sig.append((id(g), tuple(round(v, 5) for v in m.data()),
                    repr(sorted((k, repr(v)) for k, v in d.items()
                                if k not in ("open", "clip", "holes")))))
    return tuple(sig)


def _poly_openings(wg, d, wins):
    pts = [tuple(p) for p in d["poly"]]
    edges, _tot = muri.poly_edges(pts)
    faces = muri.poly_face_edges(pts)
    inv, ok = _full_pose(wg).inverted()
    if not ok:
        return []
    out = []
    for wgrp in wins:
        wd = _opening_data(wgrp)
        if d.get("lv") and wd.get("lv") and d["lv"] != wd["lv"]:
            continue
        T = _mapper(wd)
        m = inv * _full_pose(wgrp)
        p0 = m.map(T(0, 0, 0))
        p1 = m.map(T(wd["W"], 0, 0))
        ph = m.map(T(0, 0, wd["H"]))
        dx, dy = p1.x() - p0.x(), p1.y() - p0.y()
        dl_ = math.hypot(dx, dy)
        if dl_ < 1e-9:
            continue
        mx, my = (p0.x() + p1.x()) / 2, (p0.y() + p1.y()) / 2
        best = None
        for i in faces:
            S0, S1, p, q = edges[i]
            L = S1 - S0
            if L < 1e-9:
                continue
            ux, uy = (q[0] - p[0]) / L, (q[1] - p[1]) / L
            par = abs((dx * ux + dy * uy) / dl_)
            if par < 0.99:
                continue
            o = (mx - p[0]) * (-uy) + (my - p[1]) * ux
            tm = (mx - p[0]) * ux + (my - p[1]) * uy
            th = muri.poly_depth(pts, i, max(0.0, min(L, tm)), d.get("th", 0.3))
            if o < -WALL_TOL or o > th + WALL_TOL:
                continue
            ta = (p0.x() - p[0]) * ux + (p0.y() - p[1]) * uy
            tb = (p1.x() - p[0]) * ux + (p1.y() - p[1]) * uy
            ex = reveal_extent(wd)
            lo, hi = max(0.0, min(ta, tb) - ex), min(L, max(ta, tb) + ex)
            if hi - lo < 1e-4:
                continue
            key = abs(o - th / 2.0)
            if (best is None or par > best[0] + 1e-6
                    or (abs(par - best[0]) <= 1e-6 and key < best[1] - 1e-9)):
                best = (par, key, S0 + lo, S0 + hi)
        if best is None:
            continue
        op = [round(best[2], 4), round(best[3], 4),
              round(p0.z(), 4), round(ph.z(), 4)]
        rise = _arch_rise(wd)
        if rise > 1e-3:
            op.append(round(rise, 4))
        out.append(op)
    return out


def _openings_for_wall(wg, d, wins):
    if d.get("poly"):
        return _poly_openings(wg, d, wins)

    ax, ay = d["a"]
    bx, by = d["b"]
    L = math.hypot(bx - ax, by - ay)
    if L < 1e-9:
        return []
    ux, uy = (bx - ax) / L, (by - ay) / L
    inv, ok = _full_pose(wg).inverted()
    if not ok:
        return []
    out = []
    for wgrp in wins:
        wd = _opening_data(wgrp)
        if d.get("lv") and wd.get("lv") and d["lv"] != wd["lv"]:
            continue
        T = _mapper(wd)
        m = inv * _full_pose(wgrp)
        p0 = m.map(T(0, 0, 0))
        p1 = m.map(T(wd["W"], 0, 0))
        ph = m.map(T(0, 0, wd["H"]))
        dx, dy = p1.x() - p0.x(), p1.y() - p0.y()
        dl_ = math.hypot(dx, dy)
        if dl_ < 1e-9 or abs((dx * ux + dy * uy) / dl_) < 0.99:
            continue
        mx, my = (p0.x() + p1.x()) / 2, (p0.y() + p1.y()) / 2
        off = (mx - ax) * (-uy) + (my - ay) * ux
        sm = (mx - ax) * ux + (my - ay) * uy
        th = muri.wall_th_at(d, sm)
        dl, dr = muri.side_offsets(th, d["align"])
        centre = (dl - dr) / 2
        if abs(off - centre) > th / 2 + WALL_TOL:
            continue
        sa = (p0.x() - ax) * ux + (p0.y() - ay) * uy
        sb = (p1.x() - ax) * ux + (p1.y() - ay) * uy
        s0, s1 = min(sa, sb), max(sa, sb)
        if s1 <= 0 or s0 >= L:
            continue
        ex = reveal_extent(wd)
        s0, s1 = s0 - ex, s1 + ex
        op = [round(s0, 4), round(s1, 4), round(p0.z(), 4), round(ph.z(), 4)]
        rise = _arch_rise(wd)
        if rise > 1e-3:
            op.append(round(rise, 4))
        out.append(op)
    return out


def update_openings(scene) -> int:
    wins = [g for g in scene.groups if _opening_data(g) is not None]
    n = 0
    for g in scene.groups:
        d = muri.wall_data(g)
        if d is None:
            continue
        ops = _openings_for_wall(g, d, wins)
        if ops == (d.get("open") or []):
            continue
        d2 = dict(d)
        d2["open"] = ops
        g.children = [muri.wall_part(d2, muri.wall_pose(g), g.name)]
        _ifc.tag(g, "IfcWall")
        ext = dict(g.ext or {})
        ext[muri.KEY] = d2
        g.ext = ext
        n += 1
    return n


_auto = {"pending": False, "sig": None, "timer": None}


def _start_watcher(app) -> None:
    from PySide6.QtCore import QTimer
    timer = QTimer(app.window)
    timer.setInterval(300)

    def tick():
        try:
            scene = app.viewport.scene
            if getattr(scene, "edit_group", None) is not None:
                return
            sig = _signature(scene)
            if sig != _auto["sig"]:
                _auto["sig"] = sig
                _schedule_auto(app)
        except Exception:
            pass

    timer.timeout.connect(tick)
    timer.start()
    _auto["timer"] = timer


def _schedule_auto(app) -> None:
    if _auto["pending"]:
        return
    _auto["pending"] = True

    def run():
        _auto["pending"] = False
        try:
            vp = app.viewport
            scene = vp.scene
            if getattr(scene, "edit_group", None) is not None:
                return
            changed = update_openings(scene)
            changed += muri.update_roof_clips(scene)
            if changed:
                scene.version += 1
                vp.notify_scene_changed()
                vp.update()
        except Exception:
            pass

    from PySide6.QtCore import QTimer
    QTimer.singleShot(0, run)


from PySide6.QtWidgets import QWidget as _QWidget

_C_LINEA = QColor(70, 70, 75)
_C_CORPO = QColor(236, 236, 230)
_C_ANTA = QColor(222, 222, 215)
_C_VETRO = QColor(176, 208, 232)
_C_LEGNO = QColor(170, 125, 90)
_C_QUOTA = QColor(210, 40, 40)
_C_BIANCO = QColor(255, 255, 255)


class _Schema(_QWidget):
    VW, VH = 480, 170

    def __init__(self, fn):
        super().__init__()
        self._fn = fn
        self.setMinimumHeight(150)
        self.setMaximumHeight(190)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return int(w * self.VH / self.VW)

    def paintEvent(self, ev):
        from PySide6.QtGui import QPainter
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = min(self.width() / self.VW, self.height() / self.VH)
        p.translate((self.width() - self.VW * s) / 2, (self.height() - self.VH * s) / 2)
        p.scale(s, s)
        try:
            self._fn(p)
        finally:
            p.end()


def _r(p, x0, y0, x1, y1, fill=_C_CORPO):
    p.setPen(QPen(_C_LINEA, 1.2))
    p.setBrush(fill)
    p.drawRect(QRectF(x0, y0, x1 - x0, y1 - y0))


def _t(p, x, y, txt, col=_C_LINEA, size=9, bold=False):
    f = QFont()
    f.setPixelSize(size)
    f.setBold(bold)
    p.setFont(f)
    p.setPen(col)
    p.drawText(int(x), int(y), txt)


def _dim(p, x1, y1, x2, y2, txt, lato=1):
    p.setPen(QPen(_C_QUOTA, 1.1))
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    w = 6 * len(txt) + 2
    if abs(y1 - y2) < 1e-6:
        for x in (x1, x2):
            p.drawLine(QPointF(x, y1 - 3), QPointF(x, y1 + 3))
        _t(p, (x1 + x2) / 2 - w / 2, y1 + (-4 if lato > 0 else 11), txt, _C_QUOTA, 10, True)
    else:
        for y in (y1, y2):
            p.drawLine(QPointF(x1 - 3, y), QPointF(x1 + 3, y))
        _t(p, x1 + (5 if lato > 0 else -w - 3), (y1 + y2) / 2 + 4, txt, _C_QUOTA, 10, True)


def _ext(p, x1, y1, x2, y2):
    pen = QPen(_C_QUOTA, 0.8)
    pen.setStyle(Qt.DashLine)
    p.setPen(pen)
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def _hatch(p, x0, y0, x1, y1):
    p.setPen(QPen(QColor(150, 150, 150), 1))
    if y1 - y0 > x1 - x0:
        for y in range(int(y0), int(y1), 6):
            p.drawLine(QPointF(x0, y + 6), QPointF(x1, y))
    else:
        for x in range(int(x0), int(x1), 6):
            p.drawLine(QPointF(x, y1), QPointF(x + 6, y0))


def _muro(p, x0, y0, x1, y1):
    _r(p, x0, y0, x1, y1, _C_BIANCO)
    p.save()
    p.setClipRect(QRectF(x0, y0, x1 - x0, y1 - y0))
    p.setPen(QPen(QColor(150, 150, 150), 1))
    h = y1 - y0
    for k in range(int(-h), int(x1 - x0), 7):
        p.drawLine(QPointF(x0 + k, y1), QPointF(x0 + k + h, y0))
    p.restore()


def _disegno_finestra(p):
    p.setPen(QPen(_C_LINEA, 1.5))
    p.drawLine(QPointF(20, 154), QPointF(225, 154))
    _hatch(p, 20, 154, 225, 160)
    _r(p, 40, 20, 200, 120, _C_CORPO)
    _r(p, 50, 30, 190, 110, _C_BIANCO)
    for a, b in ((50, 119), (121, 190)):
        _r(p, a, 30, b, 110, _C_ANTA)
        _r(p, a + 7, 37, b - 7, 103, _C_VETRO)
    _dim(p, 40, 12, 200, 12, "W")
    _dim(p, 26, 20, 26, 120, "H", -1)
    _dim(p, 214, 120, 214, 154, "h")
    _dim(p, 40, 134, 50, 134, "f", -1)
    _dim(p, 121, 37, 128, 37, "a", 1)
    _t(p, 70, 168, tr("Prospetto"), size=9)
    _muro(p, 250, 40, 300, 120)
    _muro(p, 400, 40, 450, 120)
    _r(p, 300, 56, 311, 104, _C_CORPO)
    _r(p, 389, 56, 400, 104, _C_CORPO)
    _r(p, 311, 74, 355, 79, _C_ANTA)
    _r(p, 345, 81, 389, 86, _C_ANTA)
    _dim(p, 300, 132, 400, 132, "W", -1)
    _dim(p, 300, 48, 311, 48, "f", 1)
    _ext(p, 300, 56, 340, 56)
    _ext(p, 300, 104, 340, 104)
    _dim(p, 340, 56, 340, 104, "p", -1)
    _t(p, 320, 168, tr("Sezione orizzontale"), size=9)


def _disegno_spalletta(p):
    def poly(pts):
        p.setPen(QPen(_C_LINEA, 1.2))
        p.setBrush(_C_CORPO)
        p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in pts]))

    def view(ox, left, title):
        _t(p, ox, 10, title, size=9)
        poly([(ox + x, y) for x, y in left])
        poly([(ox + 130 - x, y) for x, y in left])
        _r(p, ox + 40, 62, ox + 48, 78, _C_CORPO)
        _r(p, ox + 82, 62, ox + 90, 78, _C_CORPO)
        p.setPen(QPen(QColor(90, 140, 190), 2))
        p.drawLine(QPointF(ox + 48, 70), QPointF(ox + 82, 70))

    def arc(cx, cy, start, span):
        p.setPen(QPen(_C_QUOTA, 1))
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(cx - 14, cy - 14, 28, 28), int(start * 16),
                  int(span * 16))

    o = 24
    view(o, [(0, 30), (30, 30), (30, 55), (40, 55), (40, 110), (0, 110)],
         tr("Risega"))
    _dim(p, o + 30, 26, o + 40, 26, "lr", 1)
    _ext(p, o + 30, 30, o + 65, 30)
    _ext(p, o + 40, 55, o + 65, 55)
    _dim(p, o + 65, 30, o + 65, 55, "dr", 1)
    o = 176
    view(o, [(0, 30), (15, 30), (40, 60), (40, 110), (0, 110)],
         tr("Strombata"))
    _ext(p, o + 15, 30, o + 65, 30)
    _ext(p, o + 40, 60, o + 65, 60)
    _dim(p, o + 65, 30, o + 65, 60, "ds", 1)
    _ext(p, o + 40, 60, o + 40, 34)
    arc(o + 40, 60, 90, 40)
    _t(p, o + 31, 52, "\u03b1", _C_QUOTA, 10, True)
    o = 328
    view(o, [(0, 30), (30, 30), (30, 52), (40, 52), (40, 85), (28, 110),
             (0, 110)], tr("Risega + strombata"))
    _dim(p, o + 30, 26, o + 40, 26, "lr", 1)
    _ext(p, o + 30, 30, o + 65, 30)
    _ext(p, o + 40, 52, o + 65, 52)
    _dim(p, o + 65, 30, o + 65, 52, "dr", 1)
    _ext(p, o + 40, 85, o + 65, 85)
    _ext(p, o + 28, 110, o + 65, 110)
    _dim(p, o + 65, 85, o + 65, 110, "ds", 1)
    _ext(p, o + 40, 85, o + 40, 108)
    arc(o + 40, 85, 244, 26)
    _t(p, o + 31, 101, "\u03b1", _C_QUOTA, 10, True)
    _t(p, 24, 140, tr("Pianta (esempio con il lato esterno in alto). lr, dr = "
                      "risega; ds, \u03b1 = strombata."), size=8)
    _t(p, 24, 152, tr("\u03b1 e' l'angolo dalla normale al muro. Nella risega + "
                      "strombata la strombata e' sul lato opposto."), size=8)


def _spin(value, lo, hi):
    s = LengthSpin()
    s.setDecimals(3)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


def _paint_res(paint) -> dict:
    res = muri.paint_results(paint)
    for zone, dflt in DEFAULT_PAINT.items():
        c = res.get("col_" + zone)
        if res.get("tex_" + zone) and c and tuple(c) == tuple(dflt):
            res["col_" + zone] = None
    return res


def ask_params(parent, current: dict, title: str, ok_text: str,
               scene=None, tscene=None, groups=None):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(_Schema(_disegno_finestra))
    form.addRow(_Schema(_disegno_spalletta))
    W = _spin(current["W"], 0.2, 20.0)
    H = _spin(current["H"], 0.2, 20.0)
    sill = _spin(current["sill"], -10.0, 100.0)
    leaves = QComboBox()
    leaves.addItem(tr("1 anta"), 1)
    for n in range(2, 9):
        leaves.addItem(tr("{0} ante").format(n), n)
    leaves.setCurrentIndex(leaves.findData(int(current["leaves"])))
    mull = {k: _spin(current.get(k, MULLION_DEFAULT[k]) or 0.0, 0.0, hi)
            for k, hi in zip(MULLION_KEYS, (0.5, 0.2, 0.2, 0.2))}
    mull["mw"].setToolTip(tr("Montante fisso tra una finestra e la successiva (finestre accoppiate in un unico telaio): lo spessore dell'anima della \"I\". 0 = nessun montante."))
    mull["mf1"].setToolTip(tr("Spessore dell'aletta del montante sul lato anteriore della finestra. 0 = nessuna aletta su questo lato."))
    mull["mf2"].setToolTip(tr("Spessore dell'aletta del montante sul lato posteriore della finestra. 0 = nessuna aletta su questo lato."))
    mull["mc"].setToolTip(tr("Di quanto ogni aletta sporge oltre l'anima del montante, sopra il bordo della finestra da ciascun lato."))
    fw = _spin(current["fw"], 0.01, 0.5)
    fd = _spin(current["fd"], 0.02, 1.0)
    sw = _spin(current["sw"], 0.01, 0.5)
    sub = QCheckBox(tr("Suddividi l'anta con listelli (vetro a riquadri)"))
    sub_cur = current.get("sub")
    if sub_cur is None:
        sub_cur = bool(int(current.get("nv", 0)) or int(current.get("nh", 0)))
    sub.setChecked(bool(sub_cur))
    nv = QSpinBox()
    nv.setRange(0, 20)
    nv.setValue(int(current.get("nv", 0)))
    nh = QSpinBox()
    nh.setRange(0, 20)
    nh.setValue(int(current.get("nh", 0)))
    dv = _spin(current.get("dv", 0.03), 0.005, 0.3)
    dh = _spin(current.get("dh", 0.03), 0.005, 0.3)
    tipo = QComboBox()
    tipo.addItem(tr("Battente"), "")
    tipo.addItem(tr("Scorrevole (2 ante su guide)"), "sc")
    tipo.setCurrentIndex(max(0, tipo.findData(current.get("tipo", ""))))
    slv = QSpinBox()
    slv.setRange(0, 100)
    slv.setValue(int(current.get("slv", 0)))
    sth = _spin(current.get("sth", SILL_DEFAULT["sth"]), 0.001, 0.5)
    sti = _spin(current.get("sti", SILL_DEFAULT["sti"]), 0.0, 1.0)
    ste = _spin(current.get("ste", SILL_DEFAULT["ste"]), 0.0, 1.0)
    spt = QComboBox()
    spt.addItem(tr("Nessuna (squadrata)"), "")
    spt.addItem(tr("Risega"), "ris")
    spt.addItem(tr("Strombata"), "str")
    spt.addItem(tr("Risega + strombata sul lato opposto"), "rs")
    spt.setCurrentIndex(max(0, spt.findData(current.get("spt", ""))))
    spt.setToolTip(tr("Vale per le finestre posate su un muro: il foro nel "
                      "muro viene allargato e la muratura ricostruita fino "
                      "al profilo scelto (solo ai lati)."))
    spl = QComboBox()
    spl.addItem(tr("Esterno"), "e")
    spl.addItem(tr("Interno"), "i")
    spl.setCurrentIndex(max(0, spl.findData(current.get("spl", "e"))))
    spd = _spin(current.get("spd", SPAL_DEFAULT["spd"]), 0.0, 2.0)
    spw = _spin(current.get("spw", SPAL_DEFAULT["spw"]), 0.0, 2.0)
    sbd = _spin(current.get("sbd", SPAL_DEFAULT["sbd"]), 0.0, 2.0)
    sba = _spin(current.get("sba", SPAL_DEFAULT["sba"]), 0.0, 80.0)
    sba.setSuffix("\u00b0")
    shut = QComboBox()
    shut.addItem(tr("Nessuno"), "")
    shut.addItem(tr("Tapparella"), "tap")
    shut.addItem(tr("Napoletane"), "nap")
    shut.setCurrentIndex(max(0, shut.findData(current.get("shut", ""))))
    shv = QSpinBox()
    shv.setRange(0, 100)
    shv.setValue(int(current.get("shv", 0)))
    shv_lbl = QLabel()

    prev = [shut.currentData()]

    def _shut_changed(*_a):
        k = shut.currentData()
        if k != prev[0]:
            if k == "nap":
                shv.setValue(100)
            elif k == "tap":
                shv.setValue(0)
            prev[0] = k
        shv_lbl.setText(
            tr("Tapparella: 0 = alzata, 100 = abbassata") if k == "tap" else
            tr("Napoletane: 0 = chiuse, 100 = aperte") if k == "nap" else
            tr("Apertura oscuranti (0-100)"))
        shv.setEnabled(bool(k))
    shut.currentIndexChanged.connect(_shut_changed)
    _shut_changed()
    cur = QCheckBox(tr("Tenda interna con bastone"))
    cur.setChecked(bool(current.get("cur", False)))
    auto_h = curtain_auto_height(current)
    cuh = _spin(float(current.get("cuh") or 0.0) or auto_h, 0.1, 10.0)
    cuv = QSpinBox()
    cuv.setRange(0, 100)
    cuv.setValue(int(current.get("cuv", 0)))
    cuv_lbl = QLabel(tr("Tenda: 0 = chiusa, 100 = aperta"))

    def _cur_changed(on):
        for w in (cuh, cuv):
            w.setEnabled(on)
        cuv_lbl.setEnabled(on)
    cur.toggled.connect(_cur_changed)
    _cur_changed(cur.isChecked())
    lvl = None
    if scene is not None and piani.levels(scene):
        lvl = piani.level_combo(scene, piani.active_id(scene))
        form.addRow(tr("Piano (muri su cui posare)"), lvl)
    # US standard sizes: a shortcut that fills the width and height (only in
    # feet and inches; the table is of US sizes)
    style = QComboBox()
    style.addItem(tr("Personalizzata"), "")
    for key, t in STANDARD_SIZES.items():
        style.addItem(t["label"], key)
    style.setCurrentIndex(max(0, style.findData(current.get("style") or "")))
    size = QComboBox()
    size.setToolTip(tr("Misure standard USA per questo tipo di finestra: piedi e pollici di larghezza, poi di altezza (2852 = 2'8\" × 5'2\"). Scegliendone una si impostano larghezza e altezza totali. L'elenco è solo una scorciatoia: qualsiasi larghezza e altezza si può scrivere nelle due caselle qui sotto."))

    def match_size(_v=0.0) -> None:        # typed sizes: show what they are
        here = (round(W.value() / IN, 3), round(H.value() / IN, 3))
        hit = [i for i in range(1, size.count())
               if tuple(size.itemData(i)) == here]
        size.blockSignals(True)
        size.setCurrentIndex(hit[0] if hit else 0)
        size.blockSignals(False)

    def fill_sizes(_i=0) -> None:          # the sizes of the chosen type
        size.blockSignals(True)
        size.clear()
        size.addItem(tr("Personalizzata (scrivi larghezza e altezza qui sotto)"), None)
        for w_in, h_in in standard_sizes(style.currentData()):
            size.addItem(size_label(w_in, h_in), (w_in, h_in))
        size.blockSignals(False)
        size.setEnabled(size.count() > 1)
        match_size()

    def pick_size(_i=0) -> None:
        wh = size.currentData()
        if wh is not None:
            W.setValue(wh[0] * IN)
            H.setValue(wh[1] * IN)
    style.currentIndexChanged.connect(fill_sizes)
    size.currentIndexChanged.connect(pick_size)
    W.valueChanged.connect(match_size)
    H.valueChanged.connect(match_size)
    fill_sizes()
    if imperial():
        form.addRow(tr("Misure standard USA: tipo"), style)
        form.addRow(tr("Misure standard USA: misura"), size)
    form.addRow(tr("Larghezza totale (W) (m)"), W)
    form.addRow(tr("Altezza totale (H) (m)"), H)
    form.addRow(tr("Altezza da terra (h) (m)"), sill)
    form.addRow(tr("Tipo di finestra"), tipo)
    form.addRow(tr("Ante"), leaves)
    form.addRow(tr("Montante: spessore dell'anima (0 = nessuno) (m)"), mull["mw"])
    form.addRow(tr("Montante: spessore dell'aletta anteriore (m)"), mull["mf1"])
    form.addRow(tr("Montante: spessore dell'aletta posteriore (m)"), mull["mf2"])
    form.addRow(tr("Montante: profondità del canale (m)"), mull["mc"])
    form.addRow(tr("Apertura scorrevole (0 = chiusa, 100 = aperta)"), slv)

    def _mullion_changed(*_a):
        can = tipo.currentData() != "sc" and leaves.currentData() > 1
        mull["mw"].setEnabled(can)
        on = can and mull["mw"].value() > 0
        for k in MULLION_KEYS[1:]:
            mull[k].setEnabled(on)
    leaves.currentIndexChanged.connect(_mullion_changed)
    mull["mw"].valueChanged.connect(_mullion_changed)

    def _tipo_changed(*_a):
        sc = tipo.currentData() == "sc"
        if sc:
            leaves.setCurrentIndex(leaves.findData(2))
        leaves.setEnabled(not sc)
        slv.setEnabled(sc)
        lbl = form.labelForField(slv)
        if lbl is not None:
            lbl.setEnabled(sc)
    tipo.currentIndexChanged.connect(_tipo_changed)
    _tipo_changed()
    tipo.currentIndexChanged.connect(_mullion_changed)
    _mullion_changed()
    form.addRow(tr("Telaio: larghezza profilo (f) (m)"), fw)
    form.addRow(tr("Telaio: profondità (p) (m)"), fd)
    form.addRow(tr("Profilo dell'anta (a) (m)"), sw)
    form.addRow(tr("Soglia: spessore (m)"), sth)
    form.addRow(tr("Soglia: sporgenza interna (m)"), sti)
    form.addRow(tr("Soglia: sporgenza esterna (m)"), ste)
    form.addRow(tr("Spalletta"), spt)
    form.addRow(tr("Spalletta: lato della risega / strombata"), spl)
    form.addRow(tr("Risega: profondita' (dr) (m)"), spd)
    form.addRow(tr("Risega: larghezza per lato (lr) (m)"), spw)
    form.addRow(tr("Strombata: profondita' (ds) (m)"), sbd)
    form.addRow(tr("Strombata: angolo (\u03b1) (\u00b0)"), sba)

    def _spal_changed(*_a):
        k = spt.currentData() or ""
        on = {spl: bool(k), spd: k in ("ris", "rs"), spw: k in ("ris", "rs"),
              sbd: k in ("str", "rs"), sba: k in ("str", "rs")}
        for w, en in on.items():
            w.setEnabled(en)
            lbl = form.labelForField(w)
            if lbl is not None:
                lbl.setEnabled(en)
    spt.currentIndexChanged.connect(_spal_changed)
    _spal_changed()
    form.addRow(sub)
    form.addRow(tr("Listelli verticali per anta (n.)"), nv)
    form.addRow(tr("Spessore listelli verticali (m)"), dv)
    form.addRow(tr("Listelli orizzontali per anta (n.)"), nh)
    form.addRow(tr("Spessore listelli orizzontali (m)"), dh)

    def _sub_changed(on):
        for w in (nv, dv, nh, dh):
            w.setEnabled(on)
            lbl = form.labelForField(w)
            if lbl is not None:
                lbl.setEnabled(on)
        if on and nv.value() == 0 and nh.value() == 0:
            nv.setValue(1)
            nh.setValue(1)

    sub.toggled.connect(_sub_changed)
    _sub_changed(sub.isChecked())
    form.addRow(tr("Oscuranti"), shut)
    form.addRow(shv_lbl, shv)
    form.addRow(cur)
    form.addRow(tr("Altezza tenda (m) (parte 20 cm sopra la finestra)"), cuh)
    form.addRow(cuv_lbl, cuv)
    paint = muri.add_paint_rows(form, current.get, WIN_ZONES)
    hatch_w = HatchPick(doorwin_hatch(current.get("hatch")))
    hatch_w.setToolTip(tr("Retino della finestra nella sezione (uno solo, non a strati)"))
    form.addRow(tr("Retino di sezione (uno solo)"), hatch_w)

    def _result():
        return {"W": W.value(), "H": H.value(), "sill": sill.value(),
                "leaves": 2 if tipo.currentData() == "sc" else leaves.currentData(),
                "tipo": tipo.currentData() or "", "slv": slv.value(),
                "fw": fw.value(),
                "fd": fd.value(), "sw": sw.value(),
                "sth": sth.value(), "sti": sti.value(), "ste": ste.value(),
                "spt": spt.currentData() or "", "spl": spl.currentData(),
                "spd": spd.value(), "spw": spw.value(),
                "sbd": sbd.value(), "sba": sba.value(),
                "sub": sub.isChecked(),
                "style": style.currentData() or "",
                **{k: mull[k].value() for k in MULLION_KEYS},
                "nv": nv.value(), "nh": nh.value(),
                "dv": dv.value(), "dh": dh.value(),
                "shut": shut.currentData() or "", "shv": shv.value(),
                "cur": cur.isChecked(), "cuv": cuv.value(),
                "cuh": 0.0 if abs(cuh.value() - auto_h) < 0.0005 else cuh.value(),
                "hatch": hatch_w.result() or {"mode": "none"},
                **_paint_res(paint)}

    def _set_tipo(t):
        tw_ = {"tipo": tipo, "leaves": leaves, "W": W, "H": H, "fw": fw,
               "fd": fd, "sw": sw, "sth": sth, "sti": sti, "ste": ste,
               "spt": spt, "spl": spl, "spd": spd, "spw": spw, "sbd": sbd,
               "sba": sba, "sub": sub, "nv": nv, "nh": nh, "dv": dv,
               "dh": dh, "shut": shut, "cur": cur}
        tw_.update(mull)
        tw_.update(paint)
        _tipi.fill_widgets(tw_, dict(t, **{k: t.get(k) for k in paint}))
        if "hatch" in t:
            hatch_w.set(t.get("hatch"))
        if "cuh" in t:
            cuh.setValue(float(t["cuh"] or 0.0) or auto_h)

    tbar = _tipi.TypeBar(dlg, form, "finestra", current, _result, _set_tipo,
                         scene, creating=scene is not None, tscene=tscene)
    cf = (_codici.CodeField(form, groups, "finestra", tscene or scene, at=2)
          if groups else None)
    scroll_form(dlg, lay, form)
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


class FinestraTool(Tool):
    name = tr("Finestra")
    shortcut = None
    description = tr("Inserisce finestre parametriche (da 1 a 8 ante).")

    def __init__(self) -> None:
        self._entering = False
        self._vp = None
        self.hover: QVector3D | None = None

    def on_activate(self, viewport) -> None:
        if self._entering:
            self._vp = viewport
            self.hover = None
            viewport.flash_status(
                tr("Finestra: clic per posarla · Spazio = ribalta · "
                "Esc / tasto destro = esci"), 6000)
            return
        p = ask_params(viewport.window(), _params(), tr("Finestra"), tr("Posa"),
                       viewport.scene)
        if p is None:
            return
        err = validate(p)
        if err:
            viewport.flash_status(tr("Finestra: ") + err, 5000)
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
                tr("Chiudi il gruppo che stai modificando, poi posa la finestra"),
                4000)
            return
        world = QVector3D(ctx.world)
        self.hover = world
        p = _params()
        place = place_edge(scene, world, _Settings, p["W"])

        def mutate(sc):
            make_window(sc, p, place)
            update_openings(sc)

        hist = viewport.history
        hist.execute(FinestraCommand(mutate))
        if getattr(hist, "last_error", None):
            viewport.flash_status(
                tr("Finestra: ") + str(hist.last_error).split(": ", 1)[-1], 6000)
            return
        viewport.notify_scene_changed()
        viewport.flash_status(tr("Finestra creata"), 2500)
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
        return key in (Qt.Key_Space, Qt.Key_Escape)

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if key == Qt.Key_Space:
            next_edge(_Settings)
            viewport.flash_status(
                tr("Spigolo ") + edge_word(_Settings),
                2000)
            viewport.update()
            return True
        return False

    def status_clause(self) -> str:
        return (tr("Spigolo {0} (Spazio ribalta) · Esc / tasto destro = esci").format(edge_word(_Settings)))

    def rubber_band_lines(self):
        if self.hover is None:
            return []
        scene = self._vp.scene if self._vp is not None else None
        if scene is None:
            return []
        d = _params()
        d.update(place_edge(scene, self.hover, _Settings, d["W"]))
        return outline_lines(d)

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
            tr("Finestra {0} × {1} · {2} {3}").format(fmt_len(p['W']), fmt_len(p['H']), int(p['leaves']), (tr('anta') if p['leaves'] == 1 else tr('ante'))),
            tr("Da terra: {0} · telaio {1} × {2}").format(fmt_len(p['sill']), fmt_len(p['fw']), fmt_len(p['fd'])),
            tr("Spigolo: {0}  (Spazio ribalta)").format(edge_word(_Settings, True)),
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


def _selected_windows(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and window_data(g) is not None and g not in out:
            out.append(g)
    return out


def _wall_th(scene, g):
    d = window_data(g)
    try:
        pt = _full_pose(g).map(_mapper(d)(d["W"] / 2, 0, 0))
        wall = find_wall(scene, pt, d.get("lv"))
    except Exception:
        return None
    return wall[3]["th"] if wall else None


def _wall_extra(scene, g) -> dict:
    d = window_data(g)
    try:
        pt = _full_pose(g).map(_mapper(d)(d["W"] / 2, 0, 0))
        wall = find_wall(scene, pt, d.get("lv"))
    except Exception:
        return {}
    if not wall:
        return {}
    return {"wth": wall[3]["th"], "wpaint": _wall_paint(wall[3])}


def edit_windows(viewport, wins=None) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    wins = wins or _selected_windows(scene)
    if not wins:
        viewport.flash_status(tr("Seleziona una finestra creata con lo strumento "
                              "Finestra"), 4000)
        return
    d = window_data(wins[0])
    current = {k: d[k] for k in ("W", "H", "sill", "leaves", "fw", "fd", "sw")}
    current.update({k: d.get(k, DIV_DEFAULT[k]) for k in DIV_KEYS})
    # absent in windows made before mullions: none
    current.update({k: d.get(k, 0.0 if k == "mw" else MULLION_DEFAULT[k])
                    for k in MULLION_KEYS})
    current.update({k: d.get(k, SHUT_DEFAULT[k]) for k in SHUT_KEYS})
    current.update({k: d.get(k, CURT_DEFAULT[k]) for k in CURT_KEYS})
    current.update({k: d.get(k, SILL_DEFAULT[k]) for k in SILL_KEYS})
    current.update({k: d.get(k, TIPO_DEFAULT[k]) for k in TIPO_KEYS})
    current.update({k: d.get(k, SPAL_DEFAULT[k]) for k in SPAL_KEYS})
    current.update({k: d.get(k) for k in PAINT_KEYS})
    current["hatch"] = d.get("hatch")
    current["tipo_id"], current["tipo_nome"] = d.get("tipo_id"), d.get("tipo_nome")
    current["style"] = d.get("style") or ""
    title = tr("Modifica finestra") if len(wins) == 1 \
        else tr("Modifica {0} finestre").format(len(wins))
    p = ask_params(viewport.window(), current, title, tr("Applica"),
                   tscene=scene, groups=wins)
    if p is None:
        return
    err = validate(p)
    if err:
        viewport.flash_status(tr("Finestra: ") + err, 5000)
        return
    st = _tipi.resolve_edit(viewport.window(), scene, "finestra", p)
    if st == "cancel":
        return

    paint_changed = {k: p.get(k) for k in PAINT_KEYS + ("hatch",)
                     if p.get(k) != current.get(k)}
    geom = {k: v for k, v in p.items() if k not in PAINT_KEYS + ("hatch",)}

    def mutate(sc):
        for g in wins:
            extra = _wall_extra(sc, g)
            rebuild_window(g, {**geom, **paint_changed, **extra})
        if st == "type":
            _tipi.update_instances(
                sc, "finestra", p["tipo_id"],
                lambda g, q: rebuild_window(g, {**q, **_wall_extra(sc, g)}))
        for g in wins:
            link = (window_data(g) or {}).get("ang")
            if not link:
                continue
            for h in list(sc.groups):
                hd = window_data(h)
                if h in wins or hd is None or hd.get("ang") != link:
                    continue
                rebuild_window(h, {"H": p["H"], "sill": p["sill"],
                                   **_wall_extra(sc, h)})
        update_openings(sc)

    hist = viewport.history
    hist.execute(FinestraCommand(mutate))
    if getattr(hist, "last_error", None):
        viewport.flash_status(
            tr("Finestra: ") + str(hist.last_error).split(": ", 1)[-1], 6000)
        return
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("{0} finestre aggiornate").format(len(wins)), 3000)


def _hook_double_click(vp) -> None:
    if getattr(vp, "_myhouse_fin_dbl", False):
        return
    original = vp.begin_group_edit

    def begin_group_edit(group, *args, **kwargs):
        g = getattr(group, "owner", None) or group
        if window_data(g) is None:
            return original(group, *args, **kwargs)
        from PySide6.QtCore import QTimer
        scene = vp.scene
        try:
            scene.select([g])
        except Exception:
            scene.selection.clear()
            scene.selection.add(g)
        vp.update()
        QTimer.singleShot(0, lambda: edit_windows(vp, [g]))

    vp.begin_group_edit = begin_group_edit
    vp._myhouse_fin_dbl = True


def _outliner_kind(group):
    d = window_data(group)
    if d is None:
        return None
    return {"type": tr("Finestra"),
            "props": ([(tr("Misure standard USA: tipo"), style_label(d.get("style")))]
                      if style_label(d.get("style")) else [])
            + [(tr("Larghezza"), fmt_len(d["W"])),
                      (tr("Altezza"), fmt_len(d["H"])),
                      (tr("Da terra"), fmt_len(d["sill"])),
                      (tr("Ante"), str(int(d["leaves"])))]
            + ([(tr("Montante"), fmt_len(_mullion(d)))] if _mullion(d) else [])
            + piani.level_props(d)}


def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(170, 210, 235))
    p.drawRect(8, 8, 32, 32)
    p.drawLine(24, 8, 24, 40)
    p.setBrush(Qt.NoBrush)
    p.drawRect(12, 12, 24, 24)
    p.end()
    return QIcon(pm)


def _register_level_kind() -> None:
    def zset(d, z):
        o = list(d["o"])
        o[2] = z
        d["o"] = o

    piani.register_kind("finestra", KEY, window_data, lambda d: d["o"][2],
                        zset, rebuild_window)


def register(api) -> None:
    _register_level_kind()
    api.add_button(tr("Finestra"), tr("Inserisce una finestra (da 1 a 8 ante)"),
                   _icon(), api.run_tool(FinestraTool()))
    app = api.app
    app.on_document_changed(lambda *_a: _schedule_auto(app))
    _start_watcher(app)
    _hook_double_click(api.window.viewport)
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        from PySide6.QtCore import QTimer

        def context(menu, selection) -> None:
            if not _selected_windows(app.viewport.scene):
                return
            menu.addSeparator()
            menu.addAction(
                tr("Modifica finestra…"),
                lambda: QTimer.singleShot(
                    0, lambda: edit_windows(app.viewport)))

        add_ctx(context)
    add_kind = getattr(app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
