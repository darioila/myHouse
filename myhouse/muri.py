# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr
from ._imperial import FT, IN, LengthSpin, dflt
from ._scroll import scroll_form
from . import _codici, _tipi
from ._strati import (HatchPick, edit_layers, hatch_texture, layers_row,
                     layers_total, normalize_hatch)

import math
import os

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPen, QVector3D
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

import copy

from core import bim
from core.history import Command
from ._imperial import fmt_len
from tools.base import Tool, ToolContext

WALL_COLOR = (0.82, 0.80, 0.76)
REF_COLOR = QColor(0, 170, 255)
LAYER_NAME = "Muri"
KEY = "myhouse_muro"
EPS = 1e-6
ALIGN_NAMES = {"left": tr("INTERNO"), "right": tr("ESTERNO"), "center": tr("CENTRO")}
INNER_COLOR = (0.97, 0.91, 0.65)
OUTER_COLOR = (1.0, 1.0, 1.0)
INNER_NAME = tr("muro interno")
OUTER_NAME = tr("muro esterno")
NICHE_BACK_COLOR = (0.88, 0.84, 0.76)
NICHE_BACK_NAME = tr("fondo nicchia")
SHELF_COLOR = (0.55, 0.38, 0.22)
SHELF_NAME = tr("mensola nicchia")
RAD_COLOR = (0.97, 0.97, 0.97)
RAD_NAME = tr("termosifone")
RAD_CAP_COLOR = (0.62, 0.63, 0.66)
RAD_CAP_NAME = tr("attacchi termosifone")
EDGE_COLOR = (0.90, 0.89, 0.85)
EDGE_NAME = tr("bordi muro")
SKIRT_COLOR = (0.96, 0.96, 0.94)
SKIRT_NAME = tr("battiscopa")
PAINT_KEYS = ("col_l", "tex_l", "col_r", "tex_r", "col_e", "tex_e")
WALL_ZONES = (("l", tr("muro interno (lato sinistro del tracciato)")),
              ("r", tr("muro esterno (lato destro del tracciato)")),
              ("e", tr("bordi (testate, sopra, sotto, spalle dei fori)")))
TEX_DIR = r"C:\Program Files\IngeTrazo\_internal\resources\textures\library"


def paint_face(f, color=None, tex=None) -> bool:
    done = False
    if color:
        f.attrs["color"] = tuple(color)
        done = True
    if tex and tex.get("path"):
        f.attrs["texture"] = dict(tex)
        f.attrs["mat"] = os.path.splitext(os.path.basename(tex["path"]))[0]
        done = True
    return done


def paint_edge_hatch(f, q, ht) -> bool:
    if not ht or len(q) < 3:
        return False
    nx = ny = nz = 0.0
    for i in range(len(q)):
        a, b = q[i], q[(i + 1) % len(q)]
        nx += (a.y() - b.y()) * (a.z() + b.z())
        ny += (a.z() - b.z()) * (a.x() + b.x())
        nz += (a.x() - b.x()) * (a.y() + b.y())
    ln = math.sqrt(nx * nx + ny * ny + nz * nz)
    if ln < 1e-12 or nz / ln < -0.7:
        return False
    hh = ht["hatch"]
    if hh["mode"] == "fill":
        return paint_face(f, hh.get("color"), None)
    tex = hatch_texture(hh, ht.get("base"), front=nz / ln <= 0.7)
    return bool(tex) and paint_face(f, None, tex)


class ColorPick(QWidget):

    def __init__(self, cur=None):
        super().__init__()
        self.value = tuple(cur) if cur else None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.btn = QPushButton()
        self.btn.clicked.connect(self._pick)
        rst = QPushButton(tr("Predefinito"))
        rst.clicked.connect(self._reset)
        lay.addWidget(self.btn, 1)
        lay.addWidget(rst)
        self._show()

    def _show(self):
        if self.value:
            r, g, b = [int(round(c * 255)) for c in self.value]
            self.btn.setText(f"#{r:02x}{g:02x}{b:02x}")
            self.btn.setStyleSheet(f"background-color: rgb({r},{g},{b});")
        else:
            self.btn.setText(tr("Materiale predefinito"))
            self.btn.setStyleSheet("")

    def _pick(self):
        cur = (QColor(*[int(round(c * 255)) for c in self.value])
               if self.value else QColor(200, 200, 200))
        col = QColorDialog.getColor(cur, self)
        if col.isValid():
            self.value = (col.redF(), col.greenF(), col.blueF())
            self._show()

    def _reset(self):
        self.value = None
        self._show()

    def set(self, cur):
        self.value = tuple(cur) if cur else None
        self._show()

    def result(self):
        return list(self.value) if self.value else None


class TexturePick(QWidget):

    def __init__(self, cur=None):
        super().__init__()
        cur = cur or {}
        self.path = cur.get("path") or None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.btn = QPushButton()
        self.btn.clicked.connect(self._pick)
        rst = QPushButton(tr("Nessuna"))
        rst.clicked.connect(self._reset)

        def sp(val, lo, hi, tip, prefix="", suffix=""):
            w = LengthSpin()
            w.setDecimals(3)
            w.setRange(lo, hi)
            w.setValue(val)
            w.setToolTip(tip)
            w.setPrefix(prefix)
            w.setSuffix(suffix)
            return w

        self.sw = sp(cur.get("sw", 1.0), 0.01, 100.0,
                     tr("Larghezza della texture (m)"), "L ")
        self.sh = sp(cur.get("sh", 1.0), 0.01, 100.0,
                     tr("Altezza della texture (m)"), "H ")
        self.rot = sp(cur.get("rot", 0.0), -360.0, 360.0,
                      tr("Rotazione della texture"), "", "°")
        lay.addWidget(self.btn, 1)
        for w in (self.sw, self.sh, self.rot, rst):
            lay.addWidget(w)
        self._show()

    def _show(self):
        self.btn.setText(os.path.basename(self.path) if self.path
                         else tr("Nessuna texture"))

    def _pick(self):
        start = (os.path.dirname(self.path) if self.path
                 else (TEX_DIR if os.path.isdir(TEX_DIR) else ""))
        p, _ = QFileDialog.getOpenFileName(
            self, tr("Scegli la texture"), start,
            tr("Immagini (*.png *.jpg *.jpeg *.bmp)"))
        if p:
            self.path = os.path.normpath(p)
            self._show()

    def _reset(self):
        self.path = None
        self._show()

    def set(self, cur):
        cur = cur or {}
        self.path = cur.get("path") or None
        self.sw.setValue(cur.get("sw", 1.0))
        self.sh.setValue(cur.get("sh", 1.0))
        self.rot.setValue(cur.get("rot", 0.0))
        self._show()

    def result(self):
        if not self.path:
            return None
        return {"path": self.path, "sw": self.sw.value(),
                "sh": self.sh.value(), "rot": self.rot.value()}


def add_paint_rows(form, get, zones) -> dict:
    pickers = {}
    for sfx, label in zones:
        cp, tp = ColorPick(get(f"col_{sfx}")), TexturePick(get(f"tex_{sfx}"))
        form.addRow(tr("Colore {0}").format(label), cp)
        form.addRow(tr("Texture {0}").format(label), tp)
        pickers[f"col_{sfx}"], pickers[f"tex_{sfx}"] = cp, tp
    return pickers


def paint_results(pickers) -> dict:
    return {k: w.result() for k, w in pickers.items()}


def _dedupe(pts, closed):
    out = []
    for p in pts:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > EPS:
            out.append(p)
    if closed and len(out) > 1 and math.hypot(
            out[0][0] - out[-1][0], out[0][1] - out[-1][1]) <= EPS:
        out.pop()
    return out


def side_offsets(thickness: float, align: str):
    if align == "left":
        return 0.0, thickness
    if align == "right":
        return thickness, 0.0
    return thickness / 2.0, thickness / 2.0


def offset_points(pts, closed: bool, d_left: float, d_right: float):
    n = len(pts)
    seg_count = n if closed else n - 1
    normals = []
    for i in range(seg_count):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        L = math.hypot(x1 - x0, y1 - y0)
        normals.append((-(y1 - y0) / L, (x1 - x0) / L))

    left, right = [], []
    for i in range(n):
        if closed:
            n0, n1 = normals[(i - 1) % n], normals[i % n]
        else:
            n0 = normals[i - 1] if i > 0 else normals[0]
            n1 = normals[i] if i < seg_count else normals[-1]
        dot = n0[0] * n1[0] + n0[1] * n1[1]
        if dot < -0.9:
            mx, my = n1
        else:
            k = 1.0 / (1.0 + dot)
            mx, my = (n0[0] + n1[0]) * k, (n0[1] + n1[1]) * k
        x, y = pts[i]
        left.append((x + mx * d_left, y + my * d_left))
        right.append((x - mx * d_right, y - my * d_right))
    return left, right


def offset_points_var(pts, closed, dls, drs):
    n = len(pts)
    seg_count = n if closed else n - 1
    normals = []
    for i in range(seg_count):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        L = math.hypot(x1 - x0, y1 - y0)
        normals.append((-(y1 - y0) / L, (x1 - x0) / L))

    def meet(P, n0, d0, n1, d1):
        det = n0[0] * n1[1] - n0[1] * n1[0]
        dot = n0[0] * n1[0] + n0[1] * n1[1]
        if abs(det) < 1e-6 or dot < -0.9:
            return (P[0] + n1[0] * d1, P[1] + n1[1] * d1)
        return (P[0] + (d0 * n1[1] - d1 * n0[1]) / det,
                P[1] + (n0[0] * d1 - n1[0] * d0) / det)

    left, right = [], []
    for i in range(n):
        if closed:
            k0, k1 = (i - 1) % n, i % n
        else:
            k0 = i - 1 if i > 0 else 0
            k1 = i if i < seg_count else seg_count - 1
        left.append(meet(pts[i], normals[k0], dls[k0], normals[k1], dls[k1]))
        right.append(meet(pts[i], normals[k0], -drs[k0], normals[k1], -drs[k1]))
    return left, right


def wall_corners(d):
    if d.get("_cn"):
        return tuple((float(p[0]), float(p[1])) for p in d["_cn"])
    a, b = tuple(d["a"]), tuple(d["b"])
    if d.get("th_b") is not None:
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        nx, ny = -(b[1] - a[1]) / L, (b[0] - a[0]) / L
        la, ra = side_offsets(d["th"], d["align"])
        lb, rb = side_offsets(d["th_b"], d["align"])
        return ((a[0] + nx * la, a[1] + ny * la),
                (a[0] - nx * ra, a[1] - ny * ra),
                (b[0] + nx * lb, b[1] + ny * lb),
                (b[0] - nx * rb, b[1] - ny * rb))
    pts, dls, drs = [], [], []
    ol, orr = side_offsets(d["th"], d["align"])
    if d.get("prev"):
        pl_, pr_ = side_offsets(d.get("pth", d["nth"]), d["align"])
        if d.get("prev_rev"):
            pl_, pr_ = pr_, pl_
        pts.append(tuple(d["prev"]))
        dls.append(pl_)
        drs.append(pr_)
    ia = len(pts)
    pts += [a, b]
    dls.append(ol)
    drs.append(orr)
    if d.get("next"):
        nl_, nr_ = side_offsets(d.get("nxth", d["nth"]), d["align"])
        if d.get("next_rev"):
            nl_, nr_ = nr_, nl_
        pts.append(tuple(d["next"]))
        dls.append(nl_)
        drs.append(nr_)
    left, right = offset_points_var(pts, False, dls, drs)
    res = [left[ia], right[ia], left[ia + 1], right[ia + 1]]
    # butt joints: "ja" / "jb" = "through" (this wall runs to the outside of
    # the corner) or "butt" (it stops against the face of the other wall);
    # no key = the mitre above
    if d.get("ja") and d.get("prev"):
        res[0], res[1] = _butt_end(res[0], res[1], a, b, tuple(d["prev"]),
                                   d["ja"], -1.0)
    if d.get("jb") and d.get("next"):
        res[2], res[3] = _butt_end(res[2], res[3], b, a, tuple(d["next"]),
                                   d["jb"], 1.0)
    jn = d.get("jn")
    if jn and abs(jn.get("th", d["th"]) - d["th"]) < 1e-9 \
            and jn.get("al", d["align"]) == d["align"]:
        for i, k in enumerate(("aL", "aR", "bL", "bR")):
            if jn.get(k):
                res[i] = (float(jn[k][0]), float(jn[k][1]))
    return tuple(res)


def _butt_end(PL, PR, P, other, N, kind, sign):
    """The two corners of one end of a wall, cut for a butt joint instead of
    a mitre. PL, PR: the mitre corners; P: this end, other: the far end; N:
    the far end of the wall joined here. The cut runs along the joined wall:
    through its outer face for the wall that runs "through", through its
    inner face for the wall that "butt"s against it."""
    L = math.hypot(P[0] - other[0], P[1] - other[1])
    M = math.hypot(N[0] - P[0], N[1] - P[1])
    if L < 1e-9 or M < 1e-9:
        return PL, PR
    ux, uy = (P[0] - other[0]) / L * sign, (P[1] - other[1]) / L * sign
    vx, vy = (N[0] - P[0]) / M, (N[1] - P[1]) / M
    cr = ux * vy - uy * vx
    if abs(cr) < 1e-6:                     # in line: nothing to butt against
        return PL, PR
    sl = ((PL[0] - P[0]) * ux + (PL[1] - P[1]) * uy) * sign
    sr = ((PR[0] - P[0]) * ux + (PR[1] - P[1]) * uy) * sign
    outer, inner = (PL, PR) if sl > sr else (PR, PL)
    Q = outer if kind == "through" else inner

    def cut(X):
        t = ((Q[0] - X[0]) * vy - (Q[1] - X[1]) * vx) / cr
        return (X[0] + ux * t, X[1] + uy * t)
    return cut(PL), cut(PR)


def wall_th_at(d, s):
    if d.get("poly"):
        edges, tot = poly_edges(d["poly"])
        for i, (S0, S1, _p, _q) in enumerate(edges):
            if S0 <= s <= S1 and S1 - S0 > EPS:
                try:
                    return poly_depth(d["poly"], i, s - S0, d["th"])
                except Exception:
                    break
        return d["th"]
    tb = d.get("th_b")
    if tb is None:
        return d["th"]
    L = math.hypot(d["b"][0] - d["a"][0], d["b"][1] - d["a"][1])
    k = min(max(s / L, 0.0), 1.0) if L > 1e-9 else 0.0
    return d["th"] + (tb - d["th"]) * k


def _sub(segs, lo, hi):
    out = []
    for a, b in segs:
        if hi <= a + EPS or lo >= b - EPS:
            out.append((a, b))
            continue
        if lo > a + EPS:
            out.append((a, lo))
        if hi < b - EPS:
            out.append((hi, b))
    return out


NICHE_MARGIN = 0.05


def _rad_fit(r, w, hh, dep):
    try:
        n, ew, a, q, g = int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])
    except (TypeError, ValueError, IndexError):
        return None
    q = min(q, dep - 0.01)
    g = max(0.0, min(g, hh - 0.10))
    a = min(a, hh - g - 0.01)
    ew = min(ew, w - 0.08)
    if n < 1 or ew < 0.02 or a < 0.08 or q < 0.02:
        return None
    n = min(n, int((w - 0.08) / ew + 1e-9))
    return (n, ew, a, q, g)


RAD_OBJ_BACK_AT_MAX_Y = True
_rad_obj_cache = []


def _rad_obj():
    if _rad_obj_cache:
        return _rad_obj_cache[0]
    res = None
    try:
        import array
        import base64
        import sys
        import zlib
        raw = zlib.decompress(base64.b64decode("".join(_RAD_OBJ_DATA)))
        n = int.from_bytes(raw[0:4], "little")
        nf = int.from_bytes(raw[4:8], "little")
        pos = [8]

        def col(cnt):
            lo = raw[pos[0]:pos[0] + cnt]
            hi = raw[pos[0] + cnt:pos[0] + 2 * cnt]
            pos[0] += 2 * cnt
            buf = bytearray(2 * cnt)
            buf[0::2], buf[1::2] = lo, hi
            a = array.array("h")
            a.frombytes(bytes(buf))
            if sys.byteorder == "big":
                a.byteswap()
            return a

        def cum(a):
            out, t = [], 0
            for x in a:
                t += x
                out.append(t)
            return out

        xs, ys, zs = cum(col(n)), cum(col(n)), cum(col(n))
        tags = raw[pos[0]:pos[0] + nf]
        pos[0] += nf
        fi, fj, fk = cum(col(nf)), col(nf), col(nf)
        ymax = max(ys)
        if RAD_OBJ_BACK_AT_MAX_Y:
            v = [(x * 1e-4, (ymax - y) * 1e-4, z * 1e-4) for x, y, z in zip(xs, ys, zs)]
        else:
            v = [(x * 1e-4, y * 1e-4, z * 1e-4) for x, y, z in zip(xs, ys, zs)]
        f = []
        for t, i, dj, dk in zip(tags, fi, fj, fk):
            j, k = i + dj, i + dk
            tg = "W" if t == 0 else "V"
            f.append((tg, i, k, j) if RAD_OBJ_BACK_AT_MAX_Y else (tg, i, j, k))
        res = {"v": v, "f": f, "W": (max(xs) - min(xs)) * 1e-4, "D": ymax * 1e-4,
               "H": max(zs) * 1e-4}
    except Exception:
        res = None
    _rad_obj_cache.append(res)
    return res


def _niches(d, L):
    out = []
    z0 = d["z0"]
    z1 = z0 + d["h"]
    th = d.get("th", 0.0)
    if d.get("th_b") is not None:
        th = min(th, d["th_b"])
    if L < 2 * NICHE_MARGIN + 0.05 or th < 0.04:
        return out
    for n in d.get("niches") or ():
        s0, s1 = max(NICHE_MARGIN, n[0]), min(L - NICHE_MARGIN, n[1])
        lo, hi = max(z0, z0 + n[2]), min(z1 - 0.01, z0 + n[3])
        if lo - z0 < 1e-3:
            lo = z0
        dep = min(float(n[4]), th - 0.02)
        side = n[5] if len(n) > 5 and n[5] in ("L", "R") else "L"
        if s1 - s0 > 1e-3 and hi - lo > 1e-3 and dep > 1e-3:
            nm = int(n[6]) if len(n) > 6 else 0
            sp = float(n[7]) if len(n) > 7 else 0.02
            rad = None
            if len(n) > 9 and n[8] == "T" and n[9]:
                rad = _rad_fit(n[9], s1 - s0, hi - lo, dep)
                if rad is not None:
                    nm = 0
            out.append((s0 / L, s1 / L, lo, hi, dep, side, max(nm, 0), sp, rad))
    return out


def _open_ops(d, L):
    z0, z1 = d["z0"], d["z0"] + d["h"]
    out = []
    for o in d.get("open") or ():
        s0, s1 = max(0.0, o[0]), min(L, o[1])
        lo, hi = max(z0, o[2]), min(z1, o[3])
        if lo - z0 < 1e-3:
            lo = z0
        if z1 - hi < 1e-3:
            hi = z1
        if s1 - s0 > 1e-4 and hi - lo > 1e-4:
            f = 0.0
            if len(o) > 4 and o[4] and hi < z1:
                f = max(0.0, min(float(o[4]), (s1 - s0) / 2.0, hi - lo - 0.05))
            out.append((s0, s1, lo, hi, f if f > 1e-3 else 0.0))
    return out


def _arches(d, L):
    return [(s0 / L, s1 / L, hi - f, f, s0, s1 - s0)
            for s0, s1, lo, hi, f in _open_ops(d, L) if f > 0.0]


ARCH_STEP = 0.04


def _arch_z(a, t, L):
    zs, f, s0, c = a[2], a[3], a[4], a[5]
    R = (c * c / 4.0 + f * f) / (2.0 * f)
    x = t * L - s0 - c / 2.0
    return zs + f - R + math.sqrt(max(R * R - x * x, 0.0))


def _columns(d, L, nic=False):
    z0, z1 = d["z0"], d["z0"] + d["h"]
    ops = []
    extra = {t for t in (d.get("clip") or {}).get("ts", ()) if 1e-6 < t < 1 - 1e-6}
    for s0, s1, lo, hi, f in _open_ops(d, L):
        ops.append((s0 / L, s1 / L, lo, hi - f))
        if f > 0.0:
            n = max(6, min(64, int(math.ceil((s1 - s0) / ARCH_STEP))))
            extra.update((s0 + (s1 - s0) * i / n) / L for i in range(1, n))
    if nic:
        for n in _niches(d, L):
            extra.update((n[0], n[1]))
    ts = sorted({0.0, 1.0, *[o[0] for o in ops], *[o[1] for o in ops], *extra})
    cols = []
    for t0, t1 in zip(ts, ts[1:]):
        if t1 - t0 < 1e-9:
            continue
        mid = (t0 + t1) / 2
        segs = [(z0, z1)]
        for o in ops:
            if o[0] <= mid <= o[1]:
                segs = _sub(segs, o[2], o[3])
        if cols and cols[-1][2] == segs and t0 not in extra:
            cols[-1] = (cols[-1][0], t1, segs)
        else:
            cols.append((t0, t1, segs))
    return cols


def _near_poly(poly, x, y, tol=1e-3) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        L2 = dx * dx + dy * dy
        if L2 > 1e-12:
            t = max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / L2))
            if math.hypot(x0 + t * dx - x, y0 + t * dy - y) <= tol:
                return True
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) / (y1 - y0) * (x1 - x0):
            inside = not inside
    return inside


def _clip_top(d):
    clip = d.get("clip")
    if not clip or not clip.get("regions"):
        return None
    z0 = d["z0"]
    z1 = z0 + d["h"]
    regs = clip["regions"]

    def top(x, y):
        for r in regs:
            if _near_poly(r["poly"], x, y):
                a, b, c = r["pl"]
                return max(z0, min(z1, a * x + b * y + c))
        return z1
    return top


def poly_edges(pts):
    out, s = [], 0.0
    n = len(pts)
    for i in range(n):
        p, q = tuple(pts[i]), tuple(pts[(i + 1) % n])
        L = math.hypot(q[0] - p[0], q[1] - p[1])
        out.append((s, s + L, p, q))
        s += L
    return out, s


def poly_locate(d, x, y):
    edges, _tot = poly_edges(d["poly"])
    best = None
    for i, (S0, S1, p, q) in enumerate(edges):
        L = S1 - S0
        if L < EPS:
            continue
        ux, uy = (q[0] - p[0]) / L, (q[1] - p[1]) / L
        t = max(0.0, min(L, (x - p[0]) * ux + (y - p[1]) * uy))
        dist = math.hypot(p[0] + ux * t - x, p[1] + uy * t - y)
        if best is None or dist < best[4]:
            best = (i, S0 + t, (ux, uy), (-uy, ux), dist)
    return best


def add_poly_opening(group, s0, s1, z_basso, z_alto, arco=0.0) -> None:
    d = wall_data(group)
    lst = [list(o) for o in d.get("open") or ()]
    lst.append([s0, s1, z_basso, z_alto, arco])
    rebuild_wall(group, d["th"], d["h"], {"open": lst})


def poly_opening_at(d, x, y, width):
    hit = poly_locate(d, x, y)
    if hit is None:
        return None
    i, s, u, n, _dist = hit
    edges, _tot = poly_edges(d["poly"])
    S0, S1 = edges[i][0], edges[i][1]
    if width > S1 - S0 - 1e-4:
        return None
    s0 = min(max(s - width / 2.0, S0), S1 - width)
    return s0, s0 + width, i, u, n


def _ear_clip(pts):
    pts = [tuple(p) for p in pts]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
               - pts[(i + 1) % len(pts)][0] * pts[i][1]
               for i in range(len(pts)))
    if area < 0:
        pts.reverse()
    idx = list(range(len(pts)))
    tris = []
    guard = 0
    while len(idx) > 3 and guard < 100000:
        guard += 1
        m = len(idx)
        cut = None
        for k in range(m):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % m]
            a, b, c = pts[i0], pts[i1], pts[i2]
            if cross(a, b, c) <= 1e-12:
                continue
            if any(j not in (i0, i1, i2)
                   and cross(a, b, pts[j]) >= -1e-12
                   and cross(b, c, pts[j]) >= -1e-12
                   and cross(c, a, pts[j]) >= -1e-12 for j in idx):
                continue
            cut = k
            tris.append((a, b, c))
            break
        if cut is None:
            cut = min(range(m), key=lambda k: abs(cross(
                pts[idx[k - 1]], pts[idx[k]], pts[idx[(k + 1) % m]])))
        idx.pop(cut)
    if len(idx) == 3:
        a, b, c = (pts[i] for i in idx)
        if cross(a, b, c) > 1e-12:
            tris.append((a, b, c))
    return tris


def _triangulate(pg):
    if not pg.interiors:
        return _ear_clip(list(pg.exterior.coords))
    from shapely.ops import triangulate
    out = []
    for t in triangulate(pg):
        if pg.contains(t.representative_point()):
            tr_ = _ear_clip(list(t.exterior.coords))
            if tr_:
                out.append(tr_[0])
    return out


def poly_face_edges(pts):
    from shapely.geometry import LineString, Polygon
    pts = [tuple(p) for p in pts]
    if len(pts) == 4:
        edges4, _t = poly_edges(pts)
        lung = [e[1] - e[0] for e in edges4]
        return [0, 2] if lung[0] + lung[2] >= lung[1] + lung[3] else [1, 3]
    poly = Polygon(pts)
    if not poly.is_valid:
        poly = poly.buffer(0)
    edges, _tot = poly_edges(pts)
    minx, miny, maxx, maxy = poly.bounds
    reach = math.hypot(maxx - minx, maxy - miny) + 1.0
    out = []
    for i, (S0, S1, p, q) in enumerate(edges):
        L = S1 - S0
        if L < EPS:
            continue
        ux, uy = (q[0] - p[0]) / L, (q[1] - p[1]) / L
        nx, ny = -uy, ux
        M = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
        ray = LineString([(M[0] + nx * 1e-3, M[1] + ny * 1e-3),
                          (M[0] + nx * reach, M[1] + ny * reach)])
        best = None
        for j, (T0, T1, a, b) in enumerate(edges):
            if j == i or T1 - T0 < EPS:
                continue
            inter = ray.intersection(LineString([a, b]))
            if inter.is_empty:
                continue
            dist = inter.distance(ray.interpolate(0))
            if best is None or dist < best[0]:
                best = (dist, (b[0] - a[0]) / (T1 - T0),
                        (b[1] - a[1]) / (T1 - T0))
        if best is None:
            continue
        if best[1] * ux + best[2] * uy < -0.5 and L > best[0]:
            out.append(i)
    return out or list(range(len(edges)))


def poly_depth(pts, i, t, default=0.30):
    from shapely.geometry import LineString
    pts = [tuple(p) for p in pts]
    edges, _tot = poly_edges(pts)
    S0, S1, p, q = edges[i]
    L = S1 - S0
    if L < EPS:
        return default
    ux, uy = (q[0] - p[0]) / L, (q[1] - p[1]) / L
    nx, ny = -uy, ux
    x, y = p[0] + ux * t, p[1] + uy * t
    xs = [a[0] for a in pts]
    ys = [a[1] for a in pts]
    reach = math.hypot(max(xs) - min(xs), max(ys) - min(ys)) + 1.0
    ray = LineString([(x + nx * 1e-3, y + ny * 1e-3),
                      (x + nx * reach, y + ny * reach)])
    best = None
    for j, (T0, T1, a, b) in enumerate(edges):
        if j == i or T1 - T0 < EPS:
            continue
        inter = ray.intersection(LineString([a, b]))
        if inter.is_empty:
            continue
        dist = inter.distance(ray.interpolate(0)) + 1e-3
        if best is None or dist < best:
            best = dist
    return best if best is not None else default


def poly_cut_dir(poly, edges, p, q, M):
    L = math.hypot(q[0] - p[0], q[1] - p[1])
    if L < EPS:
        return 0.0, 1.0
    ux, uy = (q[0] - p[0]) / L, (q[1] - p[1]) / L
    return -uy, ux


def quad_ok(pts):
    if len(pts) != 4:
        return False
    sg = 0
    for i in range(4):
        a, b, c = pts[i], pts[(i + 1) % 4], pts[(i + 2) % 4]
        cr = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if abs(cr) < 1e-9:
            return False
        if sg == 0:
            sg = 1 if cr > 0 else -1
        elif (cr > 0) != (sg > 0):
            return False
    return True


def _hole_ext(g, nx, ny, e=2e-3):
    from shapely.affinity import translate
    from shapely.ops import unary_union
    return unary_union([g, translate(g, nx * e, ny * e),
                        translate(g, -nx * e, -ny * e)])


def _pulisci(reg, tol=2e-5, anche_vuoto=False):
    try:
        out = reg.buffer(-tol, join_style=2).buffer(tol, join_style=2)
    except Exception:
        return reg
    if out.is_empty:
        return out if anche_vuoto else reg
    if out.area < reg.area * 0.5:
        return reg
    return out


def _poly_mesh(d):
    from core.mesh import Mesh
    from shapely.geometry import Point, Polygon
    from shapely.geometry.polygon import orient
    from shapely.ops import unary_union
    P = QVector3D
    pts = [tuple(p) for p in d["poly"]]
    poly = Polygon(pts)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.geom_type != "Polygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    poly = orient(poly, 1.0)
    z0 = d["z0"]
    z1 = z0 + d["h"]
    edges, perim = poly_edges(pts)
    mesh = Mesh()

    def add(q, side):
        f = mesh.add_face(q)
        f.attrs["layer"] = LAYER_NAME
        if side == "R":
            if paint_face(f, d.get("col_r"), d.get("tex_r")) \
                    and not d.get("tex_r"):
                f.attrs["mat"] = OUTER_NAME
        elif not paint_face(f, d.get("col_e"), d.get("tex_e")):
            f.attrs["color"] = EDGE_COLOR
            f.attrs["mat"] = EDGE_NAME

    minx, miny, maxx, maxy = poly.bounds
    reach = math.hypot(maxx - minx, maxy - miny) + 1.0
    cuts = []
    for s0, s1, lo, hi, _f in _open_ops(d, perim):
        sm = (s0 + s1) / 2.0
        e = next((e for e in edges if e[0] <= sm < e[1]), None)
        if e is None:
            continue
        S0, S1, p, q = e
        a, b = max(s0, S0), min(s1, S1)
        if b - a < 1e-4:
            continue
        L = S1 - S0
        ux, uy = (q[0] - p[0]) / L, (q[1] - p[1]) / L
        nx, ny = -uy, ux
        A = (p[0] + ux * (a - S0), p[1] + uy * (a - S0))
        B = (p[0] + ux * (b - S0), p[1] + uy * (b - S0))
        nx, ny = poly_cut_dir(poly, edges, p, q,
                              ((A[0] + B[0]) / 2, (A[1] + B[1]) / 2))
        prism = Polygon([(A[0] - nx * 0.02, A[1] - ny * 0.02),
                         (B[0] - nx * 0.02, B[1] - ny * 0.02),
                         (B[0] + nx * reach, B[1] + ny * reach),
                         (A[0] + nx * reach, A[1] + ny * reach)])
        inter = poly.intersection(prism)
        geoms = [g for g in getattr(inter, "geoms", [inter])
                 if g.geom_type == "Polygon" and g.area > 1e-9]
        probe = Point((A[0] + B[0]) / 2 + nx * 1e-3,
                      (A[1] + B[1]) / 2 + ny * 1e-3)
        piece = next((g for g in geoms if g.buffer(1e-6).contains(probe)),
                     None)
        if piece is None and geoms:
            piece = min(geoms, key=lambda g: g.distance(probe))
        if len(pts) == 4 and geoms:
            for g in geoms:
                cuts.append((lo, hi, _hole_ext(g, nx, ny)))
        elif piece is not None:
            if d.get("fora_primo_spessore"):
                cuts.append((lo, hi, _hole_ext(piece, nx, ny)))
            else:
                def dist(g):
                    return g.distance(Point(A[0], A[1]).union(Point(B[0], B[1]))
                                      .convex_hull)
                cur = piece
                cuts.append((lo, hi, _hole_ext(cur, nx, ny)))
                rest = sorted((g for g in geoms if g is not piece), key=dist)
                for g in rest:
                    if g.distance(cur) < 0.02:
                        cuts.append((lo, hi, _hole_ext(g, nx, ny)))
                        cur = cur.union(g)

    zs = sorted({z0, z1}
                | {c[0] for c in cuts if z0 < c[0] < z1}
                | {c[1] for c in cuts if z0 < c[1] < z1})
    slabs = []
    for za, zb in zip(zs, zs[1:]):
        if zb - za < 1e-6:
            continue
        zm = (za + zb) / 2.0
        holes = [c[2] for c in cuts if c[0] <= zm <= c[1]]
        reg = _pulisci(poly.difference(unary_union(holes))) if holes else poly
        if slabs and slabs[-1][2].symmetric_difference(reg).area < 1e-9:
            slabs[-1] = (slabs[-1][0], zb, slabs[-1][2])
        else:
            slabs.append((za, zb, reg))

    def pieces(g):
        return [orient(x, 1.0) for x in getattr(g, "geoms", [g])
                if x.geom_type == "Polygon" and x.area > 1e-8]

    boundary = poly.boundary
    for k, (za, zb, reg) in enumerate(slabs):
        for pg in pieces(reg):
            for ring in [pg.exterior] + list(pg.interiors):
                c = list(ring.coords)
                for a, b in zip(c, c[1:]):
                    if math.hypot(b[0] - a[0], b[1] - a[1]) < 1e-7:
                        continue
                    mid = Point((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                    side = "R" if boundary.distance(mid) < 1e-6 else "E"
                    add([P(a[0], a[1], za), P(b[0], b[1], za),
                         P(b[0], b[1], zb), P(a[0], a[1], zb)], side)
        top = reg.difference(slabs[k + 1][2]) if k + 1 < len(slabs) else reg
        bot = reg.difference(slabs[k - 1][2]) if k > 0 else reg
        def convesso(pg):
            return (not pg.interiors
                    and pg.convex_hull.area - pg.area < 1e-9)

        def anello(pg):
            c = [tuple(p) for p in pg.exterior.coords[:-1]]
            out = []
            for i, p in enumerate(c):
                a, n = c[i - 1], c[(i + 1) % len(c)]
                if abs((p[0] - a[0]) * (n[1] - p[1])
                       - (p[1] - a[1]) * (n[0] - p[0])) > 1e-9:
                    out.append(p)
            return out

        top = _pulisci(top, 1e-4, True)
        bot = _pulisci(bot, 1e-4, True)
        for pg in pieces(top):
            ring = anello(pg) if convesso(pg) else None
            if ring is not None and len(ring) >= 3:
                add([P(x, y, zb) for x, y in ring], "E")
                continue
            for a, b, c in _triangulate(pg):
                add([P(a[0], a[1], zb), P(b[0], b[1], zb),
                     P(c[0], c[1], zb)], "E")
        for pg in pieces(bot):
            ring = anello(pg) if convesso(pg) else None
            if ring is not None and len(ring) >= 3:
                add([P(x, y, za) for x, y in reversed(ring)], "E")
                continue
            for a, b, c in _triangulate(pg):
                add([P(a[0], a[1], za), P(c[0], c[1], za),
                     P(b[0], b[1], za)], "E")
    return mesh


EDGE_FLAG = "hidden"


def _nascondi_giunti(mesh, d):
    aL, aR, bL, bR = wall_corners(d)
    ends = []
    if d.get("sm_a"):
        ends.append((aL, aR))
    if d.get("sm_b"):
        ends.append((bL, bR))
    if not ends:
        return

    def vic(p, q):
        return abs(p.x() - q[0]) < 1e-4 and abs(p.y() - q[1]) < 1e-4

    for e in mesh.edges:
        for A, B in ends:
            if (vic(e.a, A) or vic(e.a, B)) and (vic(e.b, A) or vic(e.b, B)):
                try:
                    setattr(e, EDGE_FLAG, True)
                except Exception:
                    pass
                break


def _lati_unici(cols, L, pl, pr, add, topf=None):
    from shapely.geometry import box
    from shapely.geometry.polygon import orient
    from shapely.ops import unary_union
    rects = [box(t0 * L, za, t1 * L, zb)
             for t0, t1, segs in cols for za, zb in segs
             if t1 > t0 and zb > za]
    if not rects:
        return
    breaks = sorted({t * L for t0, t1, _ in cols for t in (t0, t1)})

    def anello(coords):
        c = [tuple(p) for p in coords[:-1]]
        n = len(c)
        out = [p for i, p in enumerate(c)
               if abs((p[0] - c[i - 1][0]) * (c[(i + 1) % n][1] - p[1])
                      - (p[1] - c[i - 1][1]) * (c[(i + 1) % n][0] - p[0])) > 1e-9]
        res = []
        for i, p in enumerate(out):
            q = out[(i + 1) % len(out)]
            res.append(p)
            if abs(p[1] - q[1]) < 1e-9:
                lo, hi = sorted((p[0], q[0]))
                mid = [b for b in breaks if lo + 1e-7 < b < hi - 1e-7]
                if p[0] > q[0]:
                    mid.reverse()
                res.extend((b, p[1]) for b in mid)
        return res

    reg = unary_union(rects)
    for pg in getattr(reg, "geoms", [reg]):
        if pg.geom_type != "Polygon" or pg.area < 1e-8:
            continue
        pg = orient(pg, 1.0)
        ext = anello(pg.exterior.coords)
        ints = [anello(r.coords) for r in pg.interiors]
        if len(ext) < 3:
            continue
        for f, rev, side in ((pr, False, "R"), (pl, True, "L")):
            def loop(r):
                pts = [topf(f, x / L, z) if topf else f(x / L, z) for x, z in r]
                return pts[::-1] if rev else pts
            add(loop(ext), side, [loop(r) for r in ints if len(r) >= 3] or None)


def _giunto_legato(mesh, d, add) -> None:
    jn = d["jn"]
    if abs(jn.get("th", d["th"]) - d["th"]) > 1e-9 \
            or jn.get("al", d["align"]) != d["align"]:
        return
    P = QVector3D
    z0, z1 = d["z0"], d["z0"] + d["h"]
    fill = [tuple(p) for p in jn.get("fill") or ()]
    if len(fill) >= 3:
        add([P(x, y, z1) for x, y in fill], "E")
        add([P(x, y, z0) for x, y in reversed(fill)], "E")
    aL, aR, bL, bR = wall_corners(d)
    pairs = []
    if jn.get("aL") and jn.get("aR"):
        pairs.append((aL, aR))
    if jn.get("bL") and jn.get("bR"):
        pairs.append((bL, bR))
    if not pairs and len(fill) < 3:
        return

    def vic(p, q):
        return abs(p.x() - q[0]) < 1e-4 and abs(p.y() - q[1]) < 1e-4

    for e in mesh.edges:
        if abs(e.a.x() - e.b.x()) < 1e-6 and abs(e.a.y() - e.b.y()) < 1e-6:
            continue
        hide = any((vic(e.a, A) and vic(e.b, B)) or (vic(e.a, B) and vic(e.b, A))
                   for A, B in pairs)
        if not hide and len(fill) >= 3:
            hide = any(vic(e.a, q) for q in fill) and any(vic(e.b, q) for q in fill)
        if hide:
            try:
                setattr(e, EDGE_FLAG, True)
            except Exception:
                pass


def _lerp(p, q, k):
    return (p[0] + (q[0] - p[0]) * k, p[1] + (q[1] - p[1]) * k)


def _layer_subs(d):
    layers = d["layers"]
    tot = layers_total(layers)
    aL, aR, bL, bR = wall_corners(d)
    n = len(layers)
    out, acc = [], 0.0
    for i, ly in enumerate(layers):
        f0, f1 = acc / tot, (acc + float(ly["t"])) / tot
        acc += float(ly["t"])
        s = {k: v for k, v in d.items()
             if k not in ("layers", "jn", "bat_l", "bat_r", "niches")}
        s["prev"] = s["next"] = None
        s["_cn"] = [_lerp(aL, aR, f0), _lerp(aL, aR, f1),
                    _lerp(bL, bR, f0), _lerp(bL, bR, f1)]
        s["th"] = float(ly["t"])
        for side, outer in (("l", i == 0), ("r", i == n - 1)):
            s["col_" + side] = ly.get("col") or (d.get("col_" + side) if outer else None)
            s["tex_" + side] = ly.get("tex") or (d.get("tex_" + side) if outer else None)
        ce, te = ly.get("col") or d.get("col_e"), ly.get("tex") or d.get("tex_e")
        if not ce and not te:
            k = 1.0 - 0.16 * (i % 3)
            ce = [c * k for c in EDGE_COLOR]
        s["hatch"] = None
        hh = normalize_hatch(ly.get("hatch"))
        if hh and not te:
            if hh["mode"] == "fill":
                ce = hh.get("color") or ce
            else:
                s["_htop"] = {"hatch": hh, "base": ce}
        s["col_e"], s["tex_e"] = ce, te
        s["_lm"] = "%s %d" % (ly.get("name") or tr("strato"), i + 1)
        if i == 0 and d.get("bat_l"):
            s["bat_l"] = d["bat_l"]
        if i == n - 1 and d.get("bat_r"):
            s["bat_r"] = d["bat_r"]
        nic = [x for x in d.get("niches") or ()
               if ((x[5] if len(x) > 5 else "L") == "L" and i == 0)
               or ((x[5] if len(x) > 5 else "L") == "R" and i == n - 1)]
        if nic:
            s["niches"] = nic
        out.append(s)
    return out


def wall_mesh(d, mesh=None):
    if d.get("poly"):
        return _poly_mesh(d)
    from core.mesh import Mesh
    if (mesh is None and d.get("layers") and d.get("th_b") is None
            and not d.get("_hide_lay")):
        mesh = Mesh()
        for sub in _layer_subs(d):
            wall_mesh(sub, mesh)
        return mesh
    P = QVector3D
    aL, aR, bL, bR = wall_corners(d)
    L = math.hypot(d["b"][0] - d["a"][0], d["b"][1] - d["a"][1])

    ux = (d["b"][0] - d["a"][0]) / L
    uy = (d["b"][1] - d["a"][1]) / L
    ax, ay = d["a"]

    trap = d.get("th_b") is not None

    def _face(A, B):
        sA = (A[0] - ax) * ux + (A[1] - ay) * uy
        sB = (B[0] - ax) * ux + (B[1] - ay) * uy

        def f(t, z):
            if t <= 1e-9:
                return P(A[0], A[1], z)
            if t >= 1 - 1e-9:
                return P(B[0], B[1], z)
            if trap and abs(sB - sA) > 1e-9:
                k = (t * L - sA) / (sB - sA)
                return P(A[0] + (B[0] - A[0]) * k, A[1] + (B[1] - A[1]) * k, z)
            k = t * L - sA
            return P(A[0] + ux * k, A[1] + uy * k, z)
        return f

    pl = _face(aL, bL)
    pr = _face(aR, bR)

    if mesh is None:
        mesh = Mesh()

    clip_top = _clip_top(d)
    z1 = d["z0"] + d["h"]
    ht = d.get("_htop")
    if ht is None and d.get("hatch") and not d.get("layers"):
        hh = normalize_hatch(d["hatch"])
        if hh:
            ht = {"hatch": hh, "base": d.get("col_e") or EDGE_COLOR}

    def add(q, side=None, holes=None):
        f = mesh.add_face(q, holes) if holes else mesh.add_face(q)
        f.attrs["layer"] = LAYER_NAME
        if side == "L":
            if paint_face(f, d.get("col_l"), d.get("tex_l")) \
                    and not d.get("tex_l"):
                f.attrs["mat"] = INNER_NAME
        elif side == "R":
            if paint_face(f, d.get("col_r"), d.get("tex_r")) \
                    and not d.get("tex_r"):
                f.attrs["mat"] = OUTER_NAME
        elif side == "E":
            if d.get("tex_e") is None and paint_edge_hatch(f, q, ht):
                pass
            elif not paint_face(f, d.get("col_e"), d.get("tex_e")):
                f.attrs["color"] = EDGE_COLOR
                f.attrs["mat"] = EDGE_NAME
            elif d.get("_lm") and not d.get("tex_e"):
                f.attrs["mat"] = d["_lm"]
        elif side == "T":
            f.attrs["color"] = SKIRT_COLOR
            f.attrs["mat"] = SKIRT_NAME
        elif side == "B":
            f.attrs["color"] = NICHE_BACK_COLOR
            f.attrs["mat"] = NICHE_BACK_NAME
        elif side == "S":
            f.attrs["color"] = SHELF_COLOR
            f.attrs["mat"] = SHELF_NAME
        elif side == "W":
            f.attrs["color"] = RAD_COLOR
            f.attrs["mat"] = RAD_NAME
        elif side == "V":
            f.attrs["color"] = RAD_CAP_COLOR
            f.attrs["mat"] = RAD_CAP_NAME

    def face(q, side=None):
        if clip_top is None:
            add(q, side)
            return
        pts = []
        for p in q:
            if not pts or (p - pts[-1]).length() > 1e-7:
                pts.append(p)
        if len(pts) > 1 and (pts[0] - pts[-1]).length() <= 1e-7:
            pts.pop()
        if len(pts) < 3:
            return
        n = QVector3D()
        for i in range(len(pts)):
            n += QVector3D.crossProduct(pts[i], pts[(i + 1) % len(pts)])
        if n.length() < 1e-9:
            return
        n.normalize()
        if all(abs(QVector3D.dotProduct(n, p - pts[0])) < 1e-4 for p in pts):
            add(pts, side)
        else:
            for i in range(1, len(pts) - 1):
                add([pts[0], pts[i], pts[i + 1]], side)

    def tp(f, t, z, low):
        p = f(t, z)
        if clip_top is None or z < z1 - 1e-9:
            return p
        return P(p.x(), p.y(), max(low, clip_top(p.x(), p.y())))

    nics = _niches(d, L)
    arcs = _arches(d, L)
    cols = _columns(d, L, bool(nics))
    use_runs = clip_top is not None or bool(nics) or bool(arcs)
    merged = False
    if clip_top is not None and not nics and not arcs:
        merged = True
        for t0, t1, segs in cols:
            for za, zb in segs:
                if zb < z1 - 1e-9:
                    continue
                for t in (t0, t1):
                    for f in (pl, pr):
                        p = f(t, z1)
                        if clip_top(p.x(), p.y()) < za - 1e-6:
                            merged = False

    def bot(za, t):
        for a in arcs:
            if a[0] - 1e-9 <= t <= a[1] + 1e-9 and abs(a[2] - za) < 1e-6:
                return _arch_z(a, min(max(t, a[0]), a[1]), L)
        return za

    def pmf(nt, t, z):
        fr, bk = (pl, pr) if nt[5] == "L" else (pr, pl)
        a, b = fr(t, z), bk(t, z)
        w = (b - a).length()
        k = min(nt[4] / w, 0.95) if w > 1e-9 else 0.0
        return a + (b - a) * k

    def get_notch(k, za, zb):
        if not nics or k < 0 or k >= len(cols):
            return None
        mid = (cols[k][0] + cols[k][1]) / 2
        for n in nics:
            if n[0] <= mid <= n[1] and n[2] >= za - EPS and n[3] <= zb - 1e-3:
                return n
        return None

    giunti_nascosti = []

    def side_run(f, left, ts, za, zb, bt=None):
        side = "L" if left else "R"
        zl = bt if bt is not None else (lambda t: za)
        bots = [f(t, zl(t)) for t in ts]
        top = [tp(f, t, zb, zl(t)) for t in ts]
        pts = bots[::-1] + top if left else bots + top[::-1]
        out = []
        for i, p in enumerate(pts):
            a, c = pts[i - 1], pts[(i + 1) % len(pts)]
            if QVector3D.crossProduct(p - a, c - p).length() > 1e-7:
                out.append(p)
        convex = len(out) >= 3
        if convex:
            n = QVector3D()
            for i in range(len(out)):
                n += QVector3D.crossProduct(out[i], out[(i + 1) % len(out)])
            for i, p in enumerate(out):
                a, c = out[i - 1], out[(i + 1) % len(out)]
                if QVector3D.dotProduct(QVector3D.crossProduct(p - a, c - p),
                                        n) < -1e-9:
                    convex = False
                    break
        if convex:
            face(out, side)
            return
        for t in ts[1:-1]:
            giunti_nascosti.append((f(t, zl(t)), tp(f, t, zb, zl(t))))
        for t0, t1 in zip(ts, ts[1:]):
            if left:
                face([f(t1, zl(t1)), f(t0, zl(t0)), tp(f, t0, zb, zl(t0)),
                      tp(f, t1, zb, zl(t1))], side)
            else:
                face([f(t0, zl(t0)), f(t1, zl(t1)), tp(f, t1, zb, zl(t1)),
                      tp(f, t0, zb, zl(t0))], side)

    if use_runs and not merged:
        i = 0
        while i < len(cols):
            j = i
            while j + 1 < len(cols) and cols[j + 1][2] == cols[i][2]:
                j += 1
            for za, zb in cols[i][2]:
                nts = [get_notch(k, za, zb) for k in range(i, j + 1)]
                for left in (True, False):
                    sd = "L" if left else "R"
                    f = pl if left else pr
                    sig = [n if (n is not None and n[5] == sd) else None for n in nts]
                    a = 0
                    while a < len(sig):
                        b = a
                        while b + 1 < len(sig) and sig[b + 1] is sig[a]:
                            b += 1
                        ts = [cols[i + a][0]] + [cols[i + m][1] for m in range(a, b + 1)]
                        n = sig[a]
                        if n is None:
                            side_run(f, left, ts, za, zb, lambda t, za=za: bot(za, t))
                        else:
                            if n[2] - za > 1e-4:
                                side_run(f, left, ts, za, n[2])
                            side_run(f, left, ts, n[3], zb)
                        a = b + 1
            i = j + 1

    if merged:
        _lati_unici(cols, L, pl, pr, add, lambda f, t, z: tp(f, t, z, d["z0"]))
    elif not use_runs:
        _lati_unici(cols, L, pl, pr, add)

    for k, (t0, t1, segs) in enumerate(cols):
        for za, zb in segs:
            nt = get_notch(k, za, zb)
            if nt is not None and nt[2] <= za + EPS:
                if nt[5] == "L":
                    face([pr(t0, za), pmf(nt, t0, za), pmf(nt, t1, za), pr(t1, za)], "E")
                else:
                    face([pmf(nt, t0, za), pl(t0, za), pl(t1, za), pmf(nt, t1, za)], "E")
            else:
                b0z, b1z = bot(za, t0), bot(za, t1)
                face([pr(t0, b0z), pl(t0, b0z), pl(t1, b1z), pr(t1, b1z)],
                     "E")
            face([tp(pr, t0, zb, za), tp(pr, t1, zb, za),
                  tp(pl, t1, zb, za), tp(pl, t0, zb, za)], "E")
            vicine = cols[k + 1][2] if k + 1 < len(cols) else []
            if any(abs(vb - zb) < 1e-6 for va, vb in vicine):
                giunti_nascosti.append((tp(pr, t1, zb, za), tp(pl, t1, zb, za)))
            if any(abs(va - za) < 1e-6 for va, vb in vicine):
                zbase = bot(za, t1)
                giunti_nascosti.append((pr(t1, zbase), pl(t1, zbase)))
            if nt is not None:
                lo, hi = nt[2], nt[3]
                same_prev = any(get_notch(k - 1, a, b) is nt for a, b in cols[k - 1][2]) if k > 0 else False
                same_next = any(get_notch(k + 1, a, b) is nt for a, b in cols[k + 1][2]) if k + 1 < len(cols) else False
                if nt[5] == "L":
                    face([pmf(nt, t1, lo), pmf(nt, t0, lo), pmf(nt, t0, hi), pmf(nt, t1, hi)], "B")
                    if lo > za + EPS:
                        face([pmf(nt, t0, lo), pmf(nt, t1, lo), pl(t1, lo), pl(t0, lo)], "E")
                    face([pl(t0, hi), pl(t1, hi), pmf(nt, t1, hi), pmf(nt, t0, hi)], "E")
                    if not same_prev:
                        face([pmf(nt, t0, lo), pl(t0, lo), pl(t0, hi), pmf(nt, t0, hi)], "E")
                    if not same_next:
                        face([pl(t1, lo), pmf(nt, t1, lo), pmf(nt, t1, hi), pl(t1, hi)], "E")
                else:
                    face([pmf(nt, t0, lo), pmf(nt, t1, lo), pmf(nt, t1, hi), pmf(nt, t0, hi)], "B")
                    if lo > za + EPS:
                        face([pr(t0, lo), pr(t1, lo), pmf(nt, t1, lo), pmf(nt, t0, lo)], "E")
                    face([pmf(nt, t0, hi), pmf(nt, t1, hi), pr(t1, hi), pr(t0, hi)], "E")
                    if not same_prev:
                        face([pr(t0, lo), pmf(nt, t0, lo), pmf(nt, t0, hi), pr(t0, hi)], "E")
                    if not same_next:
                        face([pmf(nt, t1, lo), pr(t1, lo), pr(t1, hi), pmf(nt, t1, hi)], "E")
            prev = cols[k - 1][2] if k > 0 else []
            nxt = cols[k + 1][2] if k + 1 < len(cols) else []
            parts = [(za, zb)]
            for a, b in prev:
                parts = _sub(parts, a, b)
            for ya, yb in parts:
                ya = bot(ya, t0)
                face([pl(t0, ya), pr(t0, ya),
                      tp(pr, t0, yb, ya), tp(pl, t0, yb, ya)], "E")
            parts = [(za, zb)]
            for a, b in nxt:
                parts = _sub(parts, a, b)
            for ya, yb in parts:
                ya = bot(ya, t1)
                face([pr(t1, ya), pl(t1, ya),
                      tp(pl, t1, yb, ya), tp(pr, t1, yb, ya)], "E")

    for nt in nics:
        if nt[6] < 1:
            continue
        e = 0.005
        t0, t1 = nt[0] - e / L, nt[1] + e / L
        passo = (nt[3] - nt[2]) / (nt[6] + 1)
        sp = min(max(nt[7], 0.002), passo * 0.9)
        D = nt[4] + e

        def at(t, z, dep, nt=nt):
            fr, bk = (pl, pr) if nt[5] == "L" else (pr, pl)
            a, b = fr(t, z), bk(t, z)
            w = (b - a).length()
            return a + (b - a) * (min(dep / w, 0.99) if w > 1e-9 else 0.0)

        for m in range(1, nt[6] + 1):
            za, zb = nt[2] + passo * m - sp / 2.0, nt[2] + passo * m + sp / 2.0
            if nt[5] == "L":
                lf = lambda t, z: at(t, z, 0.0)
                rt = lambda t, z: at(t, z, D)
            else:
                lf = lambda t, z: at(t, z, D)
                rt = lambda t, z: at(t, z, 0.0)
            add([rt(t0, za), lf(t0, za), lf(t1, za), rt(t1, za)], "S")
            add([rt(t0, zb), rt(t1, zb), lf(t1, zb), lf(t0, zb)], "S")
            add([rt(t0, za), rt(t1, za), rt(t1, zb), rt(t0, zb)], "S")
            add([lf(t1, za), lf(t0, za), lf(t0, zb), lf(t1, zb)], "S")
            add([lf(t0, za), rt(t0, za), rt(t0, zb), lf(t0, zb)], "S")
            add([rt(t1, za), lf(t1, za), lf(t1, zb), rt(t1, zb)], "S")

    for nt in nics:
        if not nt[8]:
            continue
        n_el, ew, ra, rq, rg = nt[8]
        _ro = _rad_obj()
        if _ro is not None:
            tc = (nt[0] + nt[1]) / 2.0
            dback = nt[4] - 0.002
            sc = min(1.0, n_el * ew / _ro["W"], ra / _ro["H"], rq / _ro["D"])
            fr, bk = (pl, pr) if nt[5] == "L" else (pr, pl)

            def wp(x, yb, z, nt=nt, fr=fr, bk=bk, tc=tc, dback=dback, sc=sc):
                t = tc + x * sc / L
                zz = nt[2] + rg + z * sc
                a_, b_ = fr(t, zz), bk(t, zz)
                w_ = (b_ - a_).length()
                dep = max(dback - yb * sc, 0.0)
                return a_ + (b_ - a_) * (min(dep / w_, 0.99) if w_ > 1e-9 else 0.0)

            o0 = wp(0.0, 0.0, 0.0)
            ex, ey, ez = wp(0.1, 0.0, 0.0) - o0, wp(0.0, 0.1, 0.0) - o0, wp(0.0, 0.0, 0.1) - o0
            det = (ex.x() * (ey.y() * ez.z() - ey.z() * ez.y())
                   - ex.y() * (ey.x() * ez.z() - ey.z() * ez.x())
                   + ex.z() * (ey.x() * ez.y() - ey.y() * ez.x()))
            pts = [wp(*p) for p in _ro["v"]]
            for tag, i, j, k in _ro["f"]:
                add([pts[i], pts[k], pts[j]] if det < 0 else [pts[i], pts[j], pts[k]], tag)
            continue
        sg = min(0.006, ew * 0.12) / L
        tc, ht = (nt[0] + nt[1]) / 2.0, n_el * ew / L / 2.0
        z0r = nt[2] + rg
        z1r = z0r + ra
        zc = min(0.035, ra * 0.2)
        dback = nt[4] - 0.002
        dfr = dback - rq

        def at(t, z, dep, nt=nt):
            fr, bk = (pl, pr) if nt[5] == "L" else (pr, pl)
            a, b = fr(t, z), bk(t, z)
            w = (b - a).length()
            return a + (b - a) * (min(max(dep, 0.0) / w, 0.99) if w > 1e-9 else 0.0)

        def box(t0, t1, za, zb, d0, d1, tag, nt=nt):
            if nt[5] == "L":
                lf = lambda t, z: at(t, z, d0)
                rt = lambda t, z: at(t, z, d1)
            else:
                lf = lambda t, z: at(t, z, d1)
                rt = lambda t, z: at(t, z, d0)
            add([rt(t0, za), lf(t0, za), lf(t1, za), rt(t1, za)], tag)
            add([rt(t0, zb), rt(t1, zb), lf(t1, zb), lf(t0, zb)], tag)
            add([rt(t0, za), rt(t1, za), rt(t1, zb), rt(t0, zb)], tag)
            add([lf(t1, za), lf(t0, za), lf(t0, zb), lf(t1, zb)], tag)
            add([lf(t0, za), rt(t0, za), rt(t0, zb), lf(t0, zb)], tag)
            add([rt(t1, za), lf(t1, za), lf(t1, zb), rt(t1, zb)], tag)

        for i in range(n_el):
            ta = tc - ht + i * ew / L
            box(ta + sg / 2.0, ta + ew / L - sg / 2.0, z0r, z1r, dfr, dback, "W")
        for za, zb in ((z0r, z0r + zc), (z1r - zc, z1r)):
            box(tc - ht, tc + ht, za, zb, dback - rq * 0.6, dback, "W")
            for tt0, tt1 in ((tc - ht - 0.03 / L, tc - ht), (tc + ht, tc + ht + 0.03 / L)):
                box(tt0, tt1, za, zb, dback - 0.04, dback, "V")

    for side, key in (("L", "bat_l"), ("R", "bat_r")):
        bat = d.get(key)
        if not bat or bat[0] < 1e-3 or bat[1] < 1e-3:
            continue
        bz0 = d["z0"]
        f = pl if side == "L" else pr
        ox, oy = (-uy, ux) if side == "L" else (uy, -ux)
        e = 0.005
        runs, cur = [], None
        for k, (t0, t1, segs) in enumerate(cols):
            hs = 0.0
            for za, zb in segs:
                if za <= bz0 + EPS:
                    hs = min(bat[0], zb - bz0)
                    nt = get_notch(k, za, zb)
                    if nt is not None and nt[5] == side and nt[2] < bz0 + hs - EPS:
                        hs = 0.0
                    break
            if hs > 1e-4 and cur is not None and abs(cur[2] - hs) < 1e-9:
                cur[1] = t1
            elif hs > 1e-4:
                cur = [t0, t1, hs]
                runs.append(cur)
            else:
                cur = None

        mit, mit_in = {}, {}
        try:
            if d.get("th_b") is None and (d.get("prev") or d.get("next")):
                _ol, _or = side_offsets(d["th"], d["align"])
                _pts, _dl, _dr = [], [], []
                if d.get("prev"):
                    _pl, _pr = side_offsets(d.get("pth", d["nth"]), d["align"])
                    if d.get("prev_rev"):
                        _pl, _pr = _pr, _pl
                    _pts.append(tuple(d["prev"])); _dl.append(_pl); _dr.append(_pr)
                _ia = len(_pts)
                _pts += [tuple(d["a"]), tuple(d["b"])]
                _dl.append(_ol); _dr.append(_or)
                if d.get("next"):
                    _nl, _nr = side_offsets(d.get("nxth", d["nth"]), d["align"])
                    if d.get("next_rev"):
                        _nl, _nr = _nr, _nl
                    _pts.append(tuple(d["next"])); _dl.append(_nl); _dr.append(_nr)
                for _delta, _dst in ((bat[1], mit), (-e, mit_in)):
                    _dl2 = [v + (_delta if side == "L" else 0.0) for v in _dl]
                    _dr2 = [v + (_delta if side == "R" else 0.0) for v in _dr]
                    _lf, _rt = offset_points_var(_pts, False, _dl2, _dr2)
                    _o = _lf if side == "L" else _rt
                    if d.get("prev"):
                        _dst[0] = _o[_ia]
                    if d.get("next"):
                        _dst[1] = _o[_ia + 1]
        except Exception:
            mit, mit_in = {}, {}

        def pt(t, z, off, f=f, ox=ox, oy=oy):
            p = f(t, z)
            m = mit if off > 0 else mit_in
            if m:
                if t <= 1e-9 and 0 in m:
                    return P(m[0][0], m[0][1], p.z())
                if t >= 1 - 1e-9 and 1 in m:
                    return P(m[1][0], m[1][1], p.z())
            return P(p.x() + ox * off, p.y() + oy * off, p.z())

        for t0, t1, hs in runs:
            za, zb = bz0, bz0 + hs
            if side == "L":
                lf = lambda t, z: pt(t, z, bat[1])
                rt = lambda t, z: pt(t, z, -e)
            else:
                lf = lambda t, z: pt(t, z, -e)
                rt = lambda t, z: pt(t, z, bat[1])
            add([rt(t0, za), lf(t0, za), lf(t1, za), rt(t1, za)], "T")
            add([rt(t0, zb), rt(t1, zb), lf(t1, zb), lf(t0, zb)], "T")
            add([rt(t0, za), rt(t1, za), rt(t1, zb), rt(t0, zb)], "T")
            add([lf(t1, za), lf(t0, za), lf(t0, zb), lf(t1, zb)], "T")
            add([lf(t0, za), rt(t0, za), rt(t0, zb), lf(t0, zb)], "T")
            add([rt(t1, za), lf(t1, za), lf(t1, zb), rt(t1, zb)], "T")
    # nicchie: la faccia del muro e' spezzata in colonne/strisce, ma e' un
    # unico piano: nascondo i verticali sui bordi della nicchia (come per
    # porte e finestre), restano visibili solo gli spigoli reali del vano
    for nt in nics:
        fn = pl if nt[5] == "L" else pr
        for t in (nt[0], nt[1]):
            for k, (c0, c1, segs) in enumerate(cols):
                if abs(c0 - t) > 1e-9 and abs(c1 - t) > 1e-9:
                    continue
                for za, zb in segs:
                    zbt = bot(za, t)
                    giunti_nascosti.append((fn(t, zbt), tp(fn, t, zb, zbt)))
                    n_k = get_notch(k, za, zb)
                    if n_k is nt:
                        if nt[2] - za > 1e-4:
                            giunti_nascosti.append((fn(t, za), fn(t, nt[2])))
                        giunti_nascosti.append((fn(t, nt[3]),
                                                tp(fn, t, zb, za)))
    if giunti_nascosti:
        def _kp(p):
            return (round(p.x(), 4), round(p.y(), 4), round(p.z(), 4))
        chiavi = {frozenset((_kp(p), _kp(q))) for p, q in giunti_nascosti}
        for e in mesh.edges:
            try:
                if frozenset((_kp(e.a), _kp(e.b))) in chiavi:
                    setattr(e, EDGE_FLAG, True)
            except Exception:
                pass
    if d.get("sm_a") or d.get("sm_b"):
        _nascondi_giunti(mesh, d)
    if d.get("jn"):
        _giunto_legato(mesh, d, add)
    return mesh


def wall_part(d, pose=None, label=None):
    from core.group import Group
    from PySide6.QtGui import QMatrix4x4
    part = Group(wall_mesh(d), name=tr("Muro"))
    part.xform = QMatrix4x4(pose) if pose is not None else QMatrix4x4()
    part.component = False
    bim.tag_group(part, "IfcWall", label or tr("Muro"))
    return part


def wall_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "a" in data else None


def wall_pose(group):
    from PySide6.QtGui import QMatrix4x4
    for k in getattr(group, "children", None) or ():
        if k.xform is not None:
            return QMatrix4x4(k.xform)
    return QMatrix4x4()


def build_walls(scene, pts, closed, thickness, height, base_z, name,
                align="left", level=None, off=0.0, tlv=None, toff=0.0,
                paint=None, skirt=None, thickness_end=None, smooth=None,
                layers=None, hatch=None):
    from core.group import Group
    pts = _dedupe(pts, closed)
    if len(pts) < 2 or (closed and len(pts) < 3):
        return 0
    n = len(pts)
    seg_count = n if closed else n - 1

    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))

    from core.group import new_uid
    chain = new_uid()
    for i in range(seg_count):
        j = (i + 1) % n
        prev = pts[i - 1] if (closed or i > 0) else None
        nxt = pts[(j + 1) % n] if (closed or j + 1 < n) else None
        d = {"a": list(pts[i]), "b": list(pts[j]),
             "prev": list(prev) if prev else None,
             "next": list(nxt) if nxt else None,
             "z0": base_z, "th": thickness, "nth": thickness,
             "h": height, "align": align, "chain": chain}
        if layers and thickness_end is None:
            d["layers"] = copy.deepcopy(layers)
            d["th"] = d["nth"] = layers_total(layers)
        if hatch:
            d["hatch"] = copy.deepcopy(hatch)
        if thickness_end is not None:
            d["th_b"] = thickness_end
            d["prev"] = d["next"] = None
        if smooth:
            def _liscio(p):
                return any(abs(p[0] - q[0]) < 1e-6 and abs(p[1] - q[1]) < 1e-6
                           for q in smooth)
            if _liscio(pts[i]):
                d["sm_a"] = True
            if _liscio(pts[j]):
                d["sm_b"] = True
        if level:
            d.update({"lv": level["id"], "lvn": level["name"], "off": off})
        if tlv:
            d.update({"tlv": tlv, "toff": toff})
        for k, v in (paint or {}).items():
            if k in PAINT_KEYS + ("tipo_id", "tipo_nome") and v:
                d[k] = copy.deepcopy(v)
        for k, v in (skirt or {}).items():
            if k in ("bat_l", "bat_r") and v:
                d[k] = list(v)
        label = f"{name} {i + 1}"
        g = Group(name=label)
        g.adopt([wall_part(d, None, label)])
        g.component = False
        g.layer = LAYER_NAME
        g.ext = {KEY: d}
        scene.groups.append(g)
    return seg_count


def build_poly_wall(scene, pts, height, base_z, name, level=None, off=0.0,
                    tlv=None, toff=0.0, paint=None, thickness=0.30) -> int:
    from core.group import Group
    pts = _dedupe(pts, True)
    if len(pts) < 3:
        return 0
    area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
               - pts[(i + 1) % len(pts)][0] * pts[i][1]
               for i in range(len(pts)))
    if abs(area) < 1e-9:
        return 0
    if area < 0:
        pts = pts[::-1]
    edges, _tot = poly_edges(pts)
    _s0, _s1, a, b = max(edges, key=lambda e: e[1] - e[0])
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    d = {"a": list(a), "b": list(b), "prev": None, "next": None,
         "z0": base_z, "th": thickness, "nth": thickness, "h": height,
         "align": "left", "poly": [list(p) for p in pts]}
    if level:
        d.update({"lv": level["id"], "lvn": level["name"], "off": off})
    if tlv:
        d.update({"tlv": tlv, "toff": toff})
    for k, v in (paint or {}).items():
        if k in PAINT_KEYS and v:
            d[k] = copy.deepcopy(v)
    label = f"{name} {tr('irregolare')}"
    g = Group(name=label)
    g.adopt([wall_part(d, None, label)])
    g.component = False
    g.layer = LAYER_NAME
    g.ext = {KEY: d}
    scene.groups.append(g)
    return 1


def update_roof_clips(scene) -> int:
    try:
        from . import tetto
        return tetto.update_roof_clips(scene) or 0
    except ImportError:
        return 0


def rebuild_wall(group, thickness, height, extra=None):
    d = dict(wall_data(group))
    d["th"], d["h"] = thickness, height
    for k, v in (extra or {}).items():
        if v is None:
            d.pop(k, None)
        else:
            d[k] = v
    if d.get("layers"):
        d["th"] = layers_total(d["layers"])
    pose = wall_pose(group)
    group.children = [wall_part(d, pose, group.name)]
    ext = dict(group.ext or {})
    ext[KEY] = d
    group.ext = ext


def add_niche(group, s0, s1, z_basso, z_alto, profondita, lato="L",
              n_mensole=0, sp_mensola=0.02, tipo="M", termosifone=None) -> None:
    d = wall_data(group)
    lst = [list(n) for n in d.get("niches") or ()]
    lst.append([s0, s1, z_basso, z_alto, profondita, lato, int(n_mensole), sp_mensola,
                tipo, list(termosifone) if termosifone else None])
    rebuild_wall(group, d["th"], d["h"], {"niches": lst})


def update_niche(group, indice, niche=None) -> None:
    d = wall_data(group)
    lst = [list(n) for n in d.get("niches") or ()]
    if niche is None:
        lst.pop(indice)
    else:
        lst[indice] = list(niche)
    rebuild_wall(group, d["th"], d["h"], {"niches": lst or None})


def clear_niches(group) -> None:
    d = wall_data(group)
    rebuild_wall(group, d["th"], d["h"], {"niches": None})


class MuriCommand(Command):

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


class _Settings:
    used = False
    thickness = dflt(4.5 * IN, 0.30)
    height = dflt(8 * FT, 3.00)
    base_offset = 0.0
    name = tr("Muro")
    ortho = True
    auto = False
    irregular = False
    trapezoid = False
    trap_a = 0.40
    trap_b = 0.20
    layers = None
    hatch = None
    align = "left"
    level = None
    tlv = None
    toff = 0.0
    col_l = list(INNER_COLOR)
    tex_l = None
    col_r = list(OUTER_COLOR)
    tex_r = None
    col_e = None
    tex_e = None
    bat_l = None
    bat_r = None
    floor = False
    ceiling = False
    tipo_id = None
    tipo_nome = None


def settings_paint() -> dict:
    return {k: copy.deepcopy(getattr(_Settings, k, None))
            for k in PAINT_KEYS + ("tipo_id", "tipo_nome")
            if getattr(_Settings, k, None)}


def _eff_th() -> float:
    return layers_total(_Settings.layers) if _Settings.layers \
        else _Settings.thickness


BAT_H, BAT_S = 0.10, 0.012


def add_skirt_rows(form, get, height_hint=None):
    cl, cr = get("bat_l"), get("bat_r")
    mode = QComboBox()
    for key, label in (("none", tr("Nessuno")), ("L", tr("Faccia interna")),
                       ("R", tr("Faccia esterna")), ("both", tr("Entrambe"))):
        mode.addItem(label, key)
    mode.setCurrentIndex(mode.findData(
        "both" if cl and cr else "L" if cl else "R" if cr else "none"))
    cur = cl or cr or [BAT_H, BAT_S]
    h, t = _spin(cur[0], 0.01, 2.0), _spin(cur[1], 0.002, 0.5)
    form.addRow(tr("Battiscopa"), mode)
    form.addRow(tr("Battiscopa: altezza (bh) (m)"), h)
    form.addRow(tr("Battiscopa: spessore (bs) (m)"), t)
    return mode, h, t


def _set_skirt(w, t) -> None:
    mode, h, th = w
    bl, br = t.get("bat_l"), t.get("bat_r")
    mode.setCurrentIndex(max(0, mode.findData(
        "both" if bl and br else "L" if bl else "R" if br else "none")))
    cur = bl or br
    if cur:
        h.setValue(cur[0])
        th.setValue(cur[1])


def skirt_results(w) -> dict:
    mode, h, t = w
    m = mode.currentData()
    val = [h.value(), t.value()]
    return {"bat_l": list(val) if m in ("L", "both") else None,
            "bat_r": list(val) if m in ("R", "both") else None}


def _spin(value, lo, hi):
    s = LengthSpin()
    s.setDecimals(3)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


_C_LINEA = QColor(70, 70, 75)
_C_CORPO = QColor(236, 236, 230)
_C_ANTA = QColor(222, 222, 215)
_C_LEGNO = QColor(170, 125, 90)
_C_QUOTA = QColor(210, 40, 40)
_C_BIANCO = QColor(255, 255, 255)


class _Schema(QWidget):
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


def _disegno_muro(p):
    _t(p, 20, 12, tr("Pianta"), size=9)
    _r(p, 20, 55, 220, 105, _C_BIANCO)
    _r(p, 20, 50, 220, 55, _C_LEGNO)
    _r(p, 20, 105, 220, 110, _C_LEGNO)
    pen = QPen(_C_LINEA, 1.2)
    pen.setStyle(Qt.DashDotLine)
    p.setPen(pen)
    p.drawLine(QPointF(10, 80), QPointF(232, 80))
    p.drawLine(QPointF(222, 76), QPointF(232, 80))
    p.drawLine(QPointF(222, 84), QPointF(232, 80))
    _t(p, 90, 77, tr("linea tracciata"), size=9)
    _t(p, 24, 44, tr("interno"), size=8)
    _t(p, 24, 122, tr("esterno"), size=8)
    _dim(p, 250, 55, 250, 105, "s")
    _dim(p, 20, 138, 28, 138, "bs", 1)
    _t(p, 36, 141, tr("battiscopa"), size=8)
    _t(p, 290, 12, tr("Sezione"), size=9)
    p.setPen(QPen(_C_LINEA, 1.5))
    p.drawLine(QPointF(300, 150), QPointF(470, 150))
    _hatch(p, 300, 150, 470, 156)
    _t(p, 425, 146, tr("piano"), size=8)
    _r(p, 360, 30, 410, 130, _C_BIANCO)
    _r(p, 350, 118, 360, 130, _C_LEGNO)
    _r(p, 410, 118, 420, 130, _C_LEGNO)
    _dim(p, 336, 30, 336, 130, "H", -1)
    _dim(p, 336, 130, 336, 150, "b", -1)
    _dim(p, 434, 118, 434, 130, "bh")
    _dim(p, 360, 22, 410, 22, "s", 1)
    _dim(p, 410, 112, 420, 112, "bs", 1)


def ask_settings(parent, scene=None) -> bool:
    from . import piani
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("Muri"))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(_Schema(_disegno_muro))
    thick = _spin(_Settings.thickness, 0.02, 5.0)
    height = _spin(_Settings.height, 0.1, 100.0)
    base = _spin(_Settings.base_offset, -100.0, 1000.0)
    name = QLineEdit(_Settings.name)
    align = QComboBox()
    for key, label in (("left", tr("Interno")), ("right", tr("Esterno")),
                       ("center", tr("Centro"))):
        align.addItem(label, key)
    align.setCurrentIndex(align.findData(_Settings.align))
    ortho = QCheckBox(tr("Ortogonale (O / F8 durante il disegno)"))
    ortho.setChecked(_Settings.ortho)
    auto = QCheckBox(tr("Automatico: clic dentro un'area chiusa di linee (anche DWG importato)"))
    auto.setChecked(False)
    level = None
    top_cb = top_off = None
    if scene is not None and piani.levels(scene):
        level = piani.level_combo(scene, piani.active_id(scene))

        def on_level(_i) -> None:
            lv = piani.get(scene, level.currentData())
            if lv:
                height.setValue(lv["h"])
        level.currentIndexChanged.connect(on_level)
        form.addRow(tr("Piano"), level)
    form.addRow(tr("Spessore (s) (m)"), thick)
    lay_state = [copy.deepcopy(_Settings.layers)]
    lrow = layers_row(dlg, thick, lay_state)
    form.addRow(tr("Strati"), lrow)
    hatch_w = HatchPick(_Settings.hatch)
    form.addRow(tr("Retino di sezione (muro senza strati)"), hatch_w)
    trap = QCheckBox(tr("Muro trapezoidale (larghezza iniziale e finale diverse)"))
    trap.setChecked(_Settings.trapezoid)
    trap_a = _spin(_Settings.trap_a, 0.02, 5.0)
    trap_b = _spin(_Settings.trap_b, 0.02, 5.0)
    trap_box = QWidget()
    trap_form = QFormLayout(trap_box)
    trap_form.setContentsMargins(0, 0, 0, 0)
    trap_form.addRow(tr("Larghezza iniziale (m)"), trap_a)
    trap_form.addRow(tr("Larghezza finale (m)"), trap_b)

    def on_trap(on) -> None:
        trap_box.setVisible(bool(on))
        thick.setEnabled(not on)
        if on:
            auto.setChecked(False)
    trap.toggled.connect(on_trap)
    auto.toggled.connect(lambda on: on and trap.setChecked(False))
    form.addRow(trap)
    form.addRow(trap_box)
    on_trap(trap.isChecked())
    polyg = QCheckBox(tr("Muro poligonale a 4 vertici (clic sui 4 vertici: i due lati "
                         "lunghi sono le facce; porte e finestre bucano il muro)"))
    polyg.setChecked(_Settings.irregular)

    def on_polyg(on) -> None:
        if on:
            trap.setChecked(False)
            auto.setChecked(False)
        trap.setEnabled(not on)
        auto.setEnabled(not on)
        thick.setEnabled(not on and not trap.isChecked())
    polyg.toggled.connect(on_polyg)
    form.addRow(polyg)
    on_polyg(polyg.isChecked())
    form.addRow(tr("Altezza (H) (m)"), height)
    if level is not None:
        top_cb, top_off = piani.add_top_rows(form, scene, height,
                                             _Settings.tlv, _Settings.toff)
    form.addRow(tr("Lato di ricalco (Spazio lo inverte)"), align)
    form.addRow(tr("Base: sopra la quota del piano / del clic (b) (m)"), base)
    paint = add_paint_rows(form, lambda k: getattr(_Settings, k, None),
                          WALL_ZONES)
    skirt = add_skirt_rows(form, lambda k: getattr(_Settings, k, None))
    form.addRow(tr("Nome"), name)
    form.addRow(ortho)
    form.addRow(auto)
    floor_cb = QCheckBox(tr("Crea pavimento (solaio alla base, catena chiusa)"))
    floor_cb.setChecked(_Settings.floor)
    ceil_cb = QCheckBox(tr("Crea soffitto (solaio alla sommita', catena chiusa)"))
    ceil_cb.setChecked(_Settings.ceiling)
    form.addRow(floor_cb)
    form.addRow(ceil_cb)

    def _result():
        res = paint_results(paint)
        for sfx, dflt in (("l", INNER_COLOR), ("r", OUTER_COLOR)):
            c = res.get("col_" + sfx)
            if res.get("tex_" + sfx) and c and tuple(c) == tuple(dflt):
                res["col_" + sfx] = None
        L = lay_state[0] or None
        res.update(layers=copy.deepcopy(L), hatch=hatch_w.result(),
                   th=layers_total(L) if L else thick.value())
        res.update(skirt_results(skirt))
        return res

    def _set_tipo(t):
        _tipi.fill_widgets(dict(paint), dict(t, **{k: t.get(k) for k in paint}))
        lay_state[0] = copy.deepcopy(t.get("layers")) or None
        if not lay_state[0] and "th" in t:
            thick.setValue(t["th"])
        lrow.refresh()
        hatch_w.set(t.get("hatch"))
        _set_skirt(skirt, t)

    tbar = _tipi.TypeBar(dlg, form, "muro", {"tipo_id": _Settings.tipo_id},
                         _result, _set_tipo, scene, creating=True)
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.button(QDialogButtonBox.Ok).setText(tr("Disegna"))
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return False
    _Settings.irregular = polyg.isChecked()
    _Settings.thickness = thick.value()
    _Settings.height = height.value()
    _Settings.base_offset = base.value()
    _Settings.name = name.text().strip() or tr("Muro")
    _Settings.align = align.currentData()
    _Settings.ortho = ortho.isChecked()
    _Settings.trapezoid = trap.isChecked() and not _Settings.irregular
    _Settings.trap_a = trap_a.value()
    _Settings.trap_b = trap_b.value()
    _Settings.floor = floor_cb.isChecked()
    _Settings.ceiling = ceil_cb.isChecked()
    _Settings.hatch = hatch_w.result()
    _Settings.layers = (lay_state[0] if lay_state[0] and not (
        trap.isChecked() or polyg.isChecked() or auto.isChecked()) else None)
    _Settings.auto = (auto.isChecked() and not _Settings.irregular
                      and not _Settings.trapezoid)
    res = paint_results(paint)
    for sfx, dflt in (("l", INNER_COLOR), ("r", OUTER_COLOR)):
        c = res.get("col_" + sfx)
        if res.get("tex_" + sfx) and c and tuple(c) == tuple(dflt):
            res["col_" + sfx] = None
    for k, v in res.items():
        setattr(_Settings, k, v)
    for k, v in skirt_results(skirt).items():
        setattr(_Settings, k, v)
    if level is not None:
        _Settings.level = level.currentData() or None
        piani.set_active(_Settings.level)
    else:
        _Settings.level = None
    if top_cb is not None:
        _Settings.tlv = top_cb.currentData() or None
        _Settings.toff = top_off.value()
    else:
        _Settings.tlv = None
    _Settings.used = True
    r = tbar.result(_result())
    _Settings.tipo_id, _Settings.tipo_nome = r.get("tipo_id"), r.get("tipo_nome")
    return True


AUTO_MAX_T = 0.8
AUTO_MIN_T = 0.04
AUTO_TOL = 0.01
AUTO_PAR = 0.02
AUTO_GAP = 0.03
AUTO_HOLE = 2.0
AUTO_MIN_ANGLE = 0.3


def _sdir(a, b):
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    return (b[0] - a[0]) / L, (b[1] - a[1]) / L, L


def _close_gaps(lines, tol):
    from shapely.geometry import LineString, Point
    from shapely.ops import nearest_points, unary_union
    from shapely import STRtree
    union = unary_union(lines)
    pieces = list(getattr(union, "geoms", [union]))
    count, owner = {}, {}
    for n, g in enumerate(pieces):
        c = list(g.coords)
        for p in (c[0], c[-1]):
            k = (round(p[0], 4), round(p[1], 4))
            count[k] = count.get(k, 0) + 1
            owner[k] = n
    dangles = [k for k, n in count.items() if n == 1]
    if not dangles or not pieces:
        return []
    tree = STRtree(pieces)
    extra = []
    for k in dangles:
        pt = Point(k)
        best = None
        for idx in tree.query(pt.buffer(tol)):
            idx = int(idx)
            if idx == owner[k]:
                continue
            dd = pieces[idx].distance(pt)
            if dd <= tol and (best is None or dd < best[0]):
                best = (dd, pieces[idx])
        if best is not None and best[0] > 1e-6:
            q = nearest_points(best[1], pt)[0]
            extra.append(LineString([k, (q.x, q.y)]))
    return extra


def auto_faces(segs, gap=AUTO_GAP):
    from shapely.geometry import LineString
    from shapely.ops import polygonize, unary_union
    lines = []
    for (x0, y0), (x1, y1) in segs:
        if math.hypot(x1 - x0, y1 - y0) > 1e-6:
            lines.append(LineString([(round(x0, 4), round(y0, 4)),
                                     (round(x1, 4), round(y1, 4))]))
    if not lines:
        return []
    if gap > 0:
        lines += _close_gaps(lines, gap)
    return list(polygonize(unary_union(lines)))


def _fill_small_holes(poly, max_area=AUTO_HOLE):
    from shapely.geometry import Polygon
    keep = [r for r in poly.interiors if Polygon(r).area > max_area]
    if len(keep) == len(poly.interiors):
        return poly
    return Polygon(poly.exterior, keep)


def auto_area(segs, x, y):
    for R in (8.0, 30.0, None):
        if R is None:
            sub = segs
        else:
            sub = [s for s in segs
                   if max(s[0][0], s[1][0]) >= x - R and min(s[0][0], s[1][0]) <= x + R
                   and max(s[0][1], s[1][1]) >= y - R and min(s[0][1], s[1][1]) <= y + R]
        if not sub:
            continue
        poly = auto_pick(auto_faces(sub), x, y)
        if poly is None:
            continue
        if R is not None:
            x0, y0, x1, y1 = poly.bounds
            if x0 < x - R + 0.5 or y0 < y - R + 0.5 or x1 > x + R - 0.5 \
                    or y1 > y + R - 0.5:
                continue
        return _fill_small_holes(poly)
    return None


def auto_pick(faces, x, y):
    from shapely.geometry import Point
    pt = Point(x, y)
    hit = [f for f in faces if f.contains(pt)]
    return min(hit, key=lambda f: f.area) if hit else None


def _strip(a, b, d):
    a = (float(a[0]), float(a[1]))
    b = (float(b[0]), float(b[1]))
    d = float(d)
    ux, uy, L = _sdir(a, b)
    return {"a": a, "b": b, "d": d, "u": (ux, uy), "L": L}


def _strip_rect(s):
    from shapely.geometry import Polygon
    nx, ny = -s["u"][1], s["u"][0]
    h = s["d"] / 2.0
    a, b = s["a"], s["b"]
    return Polygon([(a[0] - nx * h, a[1] - ny * h), (b[0] - nx * h, b[1] - ny * h),
                    (b[0] + nx * h, b[1] + ny * h), (a[0] + nx * h, a[1] + ny * h)])


def _pair_strips(poly):
    from shapely.geometry.polygon import orient
    poly = orient(poly.simplify(0.002, preserve_topology=True), 1.0)
    rings = [list(poly.exterior.coords)[:-1]]
    rings += [list(r.coords)[:-1] for r in poly.interiors]
    segs = []
    for ring in rings:
        n = len(ring)
        for i in range(n):
            a, b = ring[i], ring[(i + 1) % n]
            if math.hypot(b[0] - a[0], b[1] - a[1]) > 1e-6:
                ux, uy, L = _sdir(a, b)
                segs.append((a, b, ux, uy, L))
    big = poly.buffer(0.003)
    out = []
    n = len(segs)
    if n < 2:
        return out, big
    import numpy as np
    ax = np.array([q[0][0] for q in segs]); ay = np.array([q[0][1] for q in segs])
    bx = np.array([q[1][0] for q in segs]); by = np.array([q[1][1] for q in segs])
    ux = np.array([q[2] for q in segs]); uy = np.array([q[3] for q in segs])
    Ls = np.array([q[4] for q in segs])
    for i in range(n - 1):
        j = slice(i + 1, n)
        nx, ny = -uy[i], ux[i]
        m = (np.abs(ux[i] * uy[j] - uy[i] * ux[j]) <= AUTO_PAR) \
            & (ux[i] * ux[j] + uy[i] * uy[j] <= 0)
        da = (ax[j] - ax[i]) * nx + (ay[j] - ay[i]) * ny
        db = (bx[j] - ax[i]) * nx + (by[j] - ay[i]) * ny
        d = (da + db) / 2.0
        m &= (da >= AUTO_MIN_T * 0.9) & (db >= AUTO_MIN_T * 0.9) \
            & (np.abs(da - db) <= 0.02) & (d >= AUTO_MIN_T) & (d <= AUTO_MAX_T)
        pa = (ax[j] - ax[i]) * ux[i] + (ay[j] - ay[i]) * uy[i]
        pb = (bx[j] - ax[i]) * ux[i] + (by[j] - ay[i]) * uy[i]
        lo = np.maximum(0.0, np.minimum(pa, pb))
        hi = np.minimum(Ls[i], np.maximum(pa, pb))
        m &= (hi - lo) >= np.maximum(0.05, 1.2 * d)
        for k in np.nonzero(m)[0]:
            dd, l0, l1 = float(d[k]), float(lo[k]), float(hi[k])
            p0 = (ax[i] + ux[i] * l0 + nx * dd / 2, ay[i] + uy[i] * l0 + ny * dd / 2)
            p1 = (ax[i] + ux[i] * l1 + nx * dd / 2, ay[i] + uy[i] * l1 + ny * dd / 2)
            st = _strip(p0, p1, dd)
            if big.contains(_strip_rect(st)):
                out.append(st)
    return out, big


def _drop_overlaps(strips):
    from shapely import STRtree
    strips = sorted(strips, key=lambda s: (round(s["d"], 3), -s["L"]))
    if not strips:
        return strips
    rects = [_strip_rect(s) for s in strips]
    tree = STRtree(rects)
    kept = set()
    for i, r in enumerate(rects):
        if any(int(k) in kept and r.intersection(rects[int(k)]).area > 0.5 * r.area
               for k in tree.query(r)):
            continue
        kept.add(i)
    return [strips[i] for i in sorted(kept)]


def _merge_collinear(strips, big):
    from shapely.geometry import Polygon
    again = True
    while again:
        again = False
        alive = [True] * len(strips)
        for i in range(len(strips)):
            if not alive[i]:
                continue
            for j in range(i + 1, len(strips)):
                if not alive[j]:
                    continue
                s, t = strips[i], strips[j]
                ux, uy = s["u"]
                if abs(ux * t["u"][1] - uy * t["u"][0]) > AUTO_PAR:
                    continue
                if abs(s["d"] - t["d"]) > AUTO_TOL:
                    continue
                nx, ny = -uy, ux
                if max(abs((p[0] - s["a"][0]) * nx + (p[1] - s["a"][1]) * ny)
                       for p in (t["a"], t["b"])) > AUTO_TOL:
                    continue
                pa = (t["a"][0] - s["a"][0]) * ux + (t["a"][1] - s["a"][1]) * uy
                pb = (t["b"][0] - s["a"][0]) * ux + (t["b"][1] - s["a"][1]) * uy
                t0, t1 = min(pa, pb), max(pa, pb)
                gap = max(t0 - s["L"], 0.0 - t1)
                if gap > AUTO_MAX_T * 1.5:
                    continue
                if gap > 0:
                    g0 = s["L"] if t0 > s["L"] else t1
                    g1 = t0 if t0 > s["L"] else 0.0
                    h = s["d"] / 2.0
                    q = [(s["a"][0] + ux * g0 + sx * nx * h,
                          s["a"][1] + uy * g0 + sx * ny * h) for sx in (-1, 1)]
                    q += [(s["a"][0] + ux * g1 + sx * nx * h,
                           s["a"][1] + uy * g1 + sx * ny * h) for sx in (1, -1)]
                    if not big.contains(Polygon(q)):
                        continue
                lo, hi = min(0.0, t0), max(s["L"], t1)
                strips[i] = _strip((s["a"][0] + ux * lo, s["a"][1] + uy * lo),
                                   (s["a"][0] + ux * hi, s["a"][1] + uy * hi),
                                   (s["d"] + t["d"]) / 2.0)
                alive[j] = False
                again = True
        strips = [st for st, ok in zip(strips, alive) if ok]
    return strips


def _join_ends(strips):
    import numpy as np
    A = np.array([t["a"] for t in strips])
    B = np.array([t["b"] for t in strips])
    AB = B - A
    L2 = np.maximum((AB ** 2).sum(axis=1), 1e-12)

    def near(E):
        P = np.array(E)
        k = np.clip(((P - A) * AB).sum(axis=1) / L2, 0.0, 1.0)
        C = A + AB * k[:, None]
        return [int(q) for q in np.nonzero(((C - P) ** 2).sum(axis=1) <= 1.44)[0]]

    ends = {}
    for i, s in enumerate(strips):
        for e in (0, 1):
            E = s["a"] if e == 0 else s["b"]
            ox, oy = (-s["u"][0], -s["u"][1]) if e == 0 else s["u"]
            best = None
            for j in near(E):
                if j == i:
                    continue
                t = strips[j]
                tx, ty = t["u"]
                sin = abs(ox * ty - oy * tx)
                if sin < AUTO_MIN_ANGLE:
                    continue
                det = -ox * ty + tx * oy
                rx, ry = t["a"][0] - E[0], t["a"][1] - E[1]
                g = (rx * -ty + tx * ry) / det
                h = (ox * ry - oy * rx) / det
                hs = s["d"] / (2.0 * sin) + 0.03
                if g < -AUTO_TOL or g > t["d"] / (2.0 * sin) + 0.03:
                    continue
                if h < -hs or h > t["L"] + hs:
                    continue
                if best is None or g < best[0]:
                    best = (g, j, h, hs, sin)
            if best is None:
                ends[(i, e)] = (E, None)
                continue
            g, j, h, hs, sin = best
            t = strips[j]
            P = (E[0] + ox * g, E[1] + oy * g)
            if h < hs or h > t["L"] - hs:
                ends[(i, e)] = (P, (round(P[0], 3), round(P[1], 3)))
            else:
                k = g - t["d"] / (2.0 * sin)
                ends[(i, e)] = ((E[0] + ox * k, E[1] + oy * k), None)
    return ends


def _chains(strips, ends):
    nodes = {}
    for (i, e), (pt, key) in ends.items():
        if key:
            nodes.setdefault(key, []).append((i, e))

    def partner(i, e):
        key = ends[(i, e)][1]
        if not key:
            return None
        lst = nodes[key]
        if len(lst) != 2:
            return None
        o = lst[1] if lst[0] == (i, e) else lst[0]
        if o[0] == i or abs(strips[o[0]]["d"] - strips[i]["d"]) > 0.003:
            return None
        return o

    used, out = set(), []
    for i in range(len(strips)):
        if i in used:
            continue
        for e in (0, 1):
            if partner(i, e) is not None:
                continue
            pts = [ends[(i, e)][0]]
            cur, entry = i, e
            for _ in range(len(strips) + 1):
                used.add(cur)
                far = 1 - entry
                pts.append(ends[(cur, far)][0])
                p = partner(cur, far)
                if p is None or p[0] in used:
                    break
                cur, entry = p
            out.append({"pts": pts, "closed": False, "t": strips[i]["d"]})
            break
    for i in range(len(strips)):
        if i in used:
            continue
        pts, cur, entry = [], i, 0
        for _ in range(len(strips) + 1):
            used.add(cur)
            pts.append(ends[(cur, entry)][0])
            p = partner(cur, 1 - entry)
            if p is None:
                break
            cur, entry = p
            if cur == i:
                break
        if len(pts) >= 3:
            out.append({"pts": pts, "closed": True, "t": strips[i]["d"]})
        elif len(pts) == 2:
            out.append({"pts": pts, "closed": False, "t": strips[i]["d"]})
    return out


def auto_footprint(poly):
    from shapely.ops import unary_union
    strips, big = _pair_strips(poly)
    strips = _drop_overlaps(strips)
    strips = _merge_collinear(strips, big)
    if not strips:
        return [], 0.0
    ends = _join_ends(strips)
    chains = _chains(strips, ends)
    cover = unary_union([_strip_rect(s) for s in strips]).buffer(0.02)
    cov = poly.intersection(cover).area / poly.area if poly.area > 0 else 0.0
    return chains, cov


def auto_room(poly):
    from shapely.geometry.polygon import orient
    poly = orient(poly.simplify(0.002, preserve_topology=True), 1.0)
    rings = [list(poly.exterior.coords)[:-1]]
    rings += [list(r.coords)[:-1] for r in poly.interiors]
    return [{"pts": r, "closed": True, "t": None} for r in rings if len(r) >= 3]


def auto_classify(poly):
    est = 2.0 * poly.area / poly.length if poly.length > 0 else 0.0
    if poly.interiors or est <= AUTO_MAX_T:
        chains, cov = auto_footprint(poly)
        if chains and (cov >= 0.6 or poly.interiors):
            return "walls", chains
    return "room", auto_room(poly)


def auto_walls(segs, x, y):
    poly = auto_area(segs, x, y)
    if poly is None:
        return None, "no_area"
    return auto_classify(poly)


def _vec_xyz(v):
    if v is None:
        return None
    try:
        x, y = v.x, v.y
        z = getattr(v, "z", 0.0)
        if callable(x):
            x, y = x(), y()
            z = z() if callable(z) else z
        return float(x), float(y), float(z)
    except Exception:
        pass
    for name in ("pos", "p", "co", "point", "position"):
        if hasattr(v, name):
            r = _vec_xyz(getattr(v, name))
            if r is not None:
                return r
    try:
        s = list(v)
        if len(s) >= 2:
            return float(s[0]), float(s[1]), float(s[2]) if len(s) > 2 else 0.0
    except Exception:
        pass
    return None


_END_NAMES = (("a", "b"), ("v0", "v1"), ("p0", "p1"), ("start", "end"),
              ("v1", "v2"), ("p", "q"), ("va", "vb"), ("p1", "p2"))


def _edge_ends(e):
    for n0, n1 in _END_NAMES:
        if hasattr(e, n0) and hasattr(e, n1):
            a, b = _vec_xyz(getattr(e, n0)), _vec_xyz(getattr(e, n1))
            if a is not None and b is not None:
                return a, b
    for name in ("verts", "vertices", "points", "ends"):
        vs = getattr(e, name, None)
        if vs is not None:
            try:
                vs = list(vs)
                if len(vs) == 2:
                    a, b = _vec_xyz(vs[0]), _vec_xyz(vs[1])
                    if a is not None and b is not None:
                        return a, b
            except Exception:
                pass
    if isinstance(e, (tuple, list)) and len(e) == 2:
        a, b = _vec_xyz(e[0]), _vec_xyz(e[1])
        if a is not None and b is not None:
            return a, b
    return None


def collect_edges(scene):
    out = []
    state = {"seen": False, "sample": None}

    def from_mesh(mesh, mat):
        raw = getattr(mesh, "edges", None)
        if raw is None:
            return
        cands = [list(raw.values()), list(raw)] if isinstance(raw, dict) \
            else [list(raw)]
        for items in cands:
            got = []
            for e in items:
                if state["sample"] is None:
                    state["sample"] = e
                ends = _edge_ends(e)
                if ends is None:
                    continue
                state["seen"] = True
                a, b = ends
                if mat is not None:
                    pa, pb = mat.map(QVector3D(*a)), mat.map(QVector3D(*b))
                    a = (pa.x(), pa.y(), pa.z())
                    b = (pb.x(), pb.y(), pb.z())
                if abs(a[2] - b[2]) > 0.02:
                    continue
                got.append((a[0], a[1], b[0], b[1], a[2]))
            if got:
                out.extend(got)
                return

    def walk(g, parent):
        ext = getattr(g, "ext", None)
        if wall_data(g) is not None or (isinstance(ext, dict) and any(
                str(k).startswith("myhouse_") for k in ext)):
            return
        m = parent
        xf = getattr(g, "xform", None)
        if xf is not None:
            from PySide6.QtGui import QMatrix4x4
            m = QMatrix4x4(xf) if parent is None else parent * QMatrix4x4(xf)
        mesh = getattr(g, "mesh", None)
        if mesh is not None:
            from_mesh(mesh, m)
        for k in getattr(g, "children", None) or ():
            walk(k, m)

    from_mesh(scene.mesh, None)
    for g in list(getattr(scene, "groups", None) or ()):
        walk(g, None)
    if out or state["seen"] or state["sample"] is None:
        return out, None
    s = state["sample"]
    attrs = [a for a in dir(s) if not a.startswith("_")][:16]
    return out, "%s: %s" % (type(s).__name__, ", ".join(attrs))


def pick_level_segments(edges, z):
    sel = [e for e in edges if abs(e[4] - z) <= 0.05]
    if not sel and edges:
        zn = min((e[4] for e in edges), key=lambda q: abs(q - z))
        sel = [e for e in edges if abs(e[4] - zn) <= 0.05]
    zl = sum(e[4] for e in sel) / len(sel) if sel else z
    return [((e[0], e[1]), (e[2], e[3])) for e in sel], zl


def wall_at(scene, x, y) -> bool:
    from PySide6.QtGui import QMatrix4x4
    for g in scene.groups:
        d = wall_data(g)
        if d is None:
            continue
        try:
            if d.get("poly"):
                corners = [tuple(p) for p in d["poly"]]
            else:
                aL, aR, bL, bR = wall_corners(d)
                corners = (aL, bL, bR, aR)
            m = wall_pose(g)
            gx = getattr(g, "xform", None)
            if gx is not None:
                m = QMatrix4x4(gx) * m
            poly = []
            for px, py in corners:
                v = m.map(QVector3D(px, py, 0.0))
                poly.append((v.x(), v.y()))
        except Exception:
            continue
        ins = False
        for i in range(len(poly)):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % len(poly)]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                ins = not ins
        if ins:
            return True
    return False


ARC_STEP = math.radians(5.0)


def arc_pts(p0, pm, p1):
    ax, ay = p0
    bx, by = pm
    cx, cy = p1
    dd = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(dd) < 1e-9:
        return [tuple(p1)]
    a2, b2, c2 = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / dd
    uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / dd
    r = math.hypot(ax - ux, ay - uy)
    a0 = math.atan2(ay - uy, ax - ux)
    am = math.atan2(by - uy, bx - ux)
    a1 = math.atan2(cy - uy, cx - ux)
    tau = 2.0 * math.pi
    ccw = (a1 - a0) % tau
    sweep = ccw if (am - a0) % tau < ccw else ccw - tau
    n = min(180, max(2, int(math.ceil(abs(sweep) / ARC_STEP))))
    pts = [(ux + r * math.cos(a0 + sweep * k / n),
            uy + r * math.sin(a0 + sweep * k / n)) for k in range(1, n)]
    return pts + [tuple(p1)]


def _build_floor_ceiling(scene, pts, thickness, align, height, base_z,
                         lvl, off) -> None:
    from . import solaio
    dl, dr = side_offsets(thickness, align)
    left, right = offset_points(pts, True, dl, dr)

    def area(q):
        return abs(sum(q[i][0] * q[(i + 1) % len(q)][1]
                       - q[(i + 1) % len(q)][0] * q[i][1]
                       for i in range(len(q)))) / 2.0
    poly = left if area(left) <= area(right) else right
    t = solaio._Settings.thickness
    paint = {k: v for k, v in solaio.settings_paint().items()
             if not k.startswith("tipo_")}
    if _Settings.floor:
        solaio.build_slab(scene, poly, t, base_z, tr("Pavimento"), lvl, off,
                          paint)
    if _Settings.ceiling:
        solaio.build_slab(scene, poly, t, base_z + height, tr("Soffitto"),
                          lvl, off + height, paint)


class MuriTool(Tool):
    name = tr("Muri")
    shortcut = None
    description = tr("Traccia muri cliccando i punti dell'asse.")
    vcb_label = tr("Lunghezza")

    def __init__(self) -> None:
        self._entering = False
        self._vp = None
        self.last_count = 0
        self._edge_cache = None
        self._pv_poly = None
        self._pv_lines = []
        self._pv_time = 0.0
        self._reset()

    def _reset(self) -> None:
        self.points: list[QVector3D] = []
        self.hover_point: QVector3D | None = None
        self.last_dir: QVector3D | None = None
        self.arc = False
        self.arc_mid: QVector3D | None = None
        self.arc_runs: list[tuple[int, int]] = []

    def _arc_points(self, end: QVector3D):
        p0 = self.points[-1]
        res = arc_pts((p0.x(), p0.y()), (self.arc_mid.x(), self.arc_mid.y()),
                      (end.x(), end.y()))
        return [QVector3D(x, y, p0.z()) for x, y in res]

    def _ortho(self, p: QVector3D) -> QVector3D:
        if not (_Settings.ortho and self.points):
            return p
        # the nearest 45° direction from the previous point (0, 45, 90, 135…):
        # the cursor is projected onto it, so along X or Y it is plain ortho
        last = self.points[-1]
        dx, dy = p.x() - last.x(), p.y() - last.y()
        if abs(dx) < EPS and abs(dy) < EPS:
            return p
        step = math.pi / 4
        ang = round(math.atan2(dy, dx) / step) * step
        ux, uy = math.cos(ang), math.sin(ang)
        if abs(ux) < 1e-9:              # exactly on an axis: no drift
            ux = 0.0
        if abs(uy) < 1e-9:
            uy = 0.0
        run = dx * ux + dy * uy
        return QVector3D(last.x() + run * ux, last.y() + run * uy, p.z())

    def _level(self):
        from . import piani
        scene = getattr(self._vp, "scene", None)
        return piani.get(scene, _Settings.level) if scene is not None else None

    def _buffer(self) -> str:
        return getattr(self._vp, "_value_buffer", "") or ""

    def on_activate(self, viewport) -> None:
        if self._entering:
            self._vp = viewport
            self._reset()
            if _Settings.irregular:
                viewport.flash_status(
                    tr("Muro poligonale: clic sui 4 vertici (si chiude da solo al "
                       "4o) · lati lunghi = facce · Esc = esci"), 6000)
                return
            viewport.flash_status(
                tr("Muri automatico: clic dentro un'area chiusa · Spazio = lato · "
                   "Esc = esci") if _Settings.auto else
                tr("Muri: clic per i punti · Spazio = lato · C = chiudi · "
                   "Invio = fine"), 6000)
            return
        if not ask_settings(viewport.window(), viewport.scene):
            return
        self.start_same(viewport)

    def start_same(self, viewport) -> None:
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def repeat(self, viewport) -> None:
        if _Settings.used:
            self.start_same(viewport)
        else:
            self.on_activate(viewport)

    def on_deactivate(self, viewport) -> None:
        self._pv_poly, self._pv_lines, self._edge_cache = None, [], None
        self._reset()

    def on_click(self, ctx: ToolContext) -> None:
        if _Settings.auto:
            self._auto_click(ctx)
            return
        raw = QVector3D(ctx.world)
        if self.arc and self.points:
            if self.arc_mid is None:
                if (raw - self.points[-1]).length() < EPS:
                    return
                self.arc_mid = raw
                ctx.viewport.flash_status(
                    tr("Arco: clic sul punto finale · A = torna a linea · "
                       "Backspace = annulla"), 4000)
                ctx.viewport.update()
                return
            if (raw - self.points[-1]).length() < EPS:
                return
            new = self._arc_points(raw)
            start = len(self.points)
            self.points.extend(new)
            self.arc_runs.append((start, len(self.points)))
            if len(self.points) >= 2:
                t = self.points[-1] - self.points[-2]
                if t.length() > EPS:
                    self.last_dir = t.normalized()
            self.hover_point = self.points[-1]
            self.arc = False
            self.arc_mid = None
            ctx.viewport.update()
            return
        if len(self.points) >= 3 and (raw - self.points[0]).length() < 1e-4:
            self._commit(ctx.viewport, closed=True)
            return
        p = self._ortho(raw)
        if self.points:
            if (p - self.points[-1]).length() < EPS:
                return
            self.last_dir = (p - self.points[-1]).normalized()
        self.points.append(p)
        self.hover_point = p
        if _Settings.trapezoid and len(self.points) >= 2:
            self._commit(ctx.viewport, closed=False)
            return
        if _Settings.irregular and len(self.points) == 4:
            self._commit(ctx.viewport, closed=True)
            return
        ctx.viewport.update()

    def on_double_click(self, ctx: ToolContext) -> None:
        self._pulisci_buffer(ctx.viewport)
        self._commit(ctx.viewport, closed=False)

    def _pulisci_buffer(self, viewport) -> None:
        buf = getattr(viewport, "_value_buffer", "") or ""
        if buf and not any(ch.isdigit() for ch in buf):
            try:
                viewport._value_buffer = ""
            except Exception:
                pass

    def on_hover(self, ctx: ToolContext) -> None:
        if _Settings.auto:
            self._auto_hover(ctx)
            return
        self.hover_point = (QVector3D(ctx.world) if self.arc
                            else self._ortho(QVector3D(ctx.world)))
        ctx.viewport.update()

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    def claims_key(self, key: int, modifiers) -> bool:
        if modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        if key == Qt.Key_F8:
            return True
        if self._buffer():
            return False
        if key == Qt.Key_Escape:
            return True
        if key in (Qt.Key_Space, Qt.Key_O):
            return True
        if key == Qt.Key_L:
            return not (_Settings.auto or _Settings.trapezoid
                        or _Settings.irregular)
        if key == Qt.Key_A:
            return not _Settings.auto and not _Settings.trapezoid
        return key == Qt.Key_C and bool(self.points)

    def _exit(self, viewport) -> None:
        self._reset()
        viewport.update()
        win = viewport.window()
        back = getattr(win, "activate_select_tool", None)
        if callable(back):
            back()

    def context_menu(self, viewport, pos) -> bool:
        if self.points:
            if len(_dedupe([(p.x(), p.y()) for p in self.points], False)) >= 2:
                self._commit(viewport, closed=False)
                if not self.points:
                    viewport.flash_status(
                        tr("{0} muri creati · clic = nuovo muro identico · "
                           "tasto destro o Esc = esci").format(self.last_count),
                        5000)
            else:
                self._reset()
                viewport.update()
            return True
        self._exit(viewport)
        return True

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if key == Qt.Key_Space:
            _Settings.align = "left" if _Settings.align == "right" else "right"
            viewport.flash_status(
                tr("Ricalco {0}").format(ALIGN_NAMES[_Settings.align].lower()), 2000)
            viewport.update()
            return True
        if key == Qt.Key_A and not _Settings.auto and not _Settings.trapezoid:
            self.arc = not self.arc
            self.arc_mid = None
            viewport.flash_status(
                tr("Muro TONDO: clic su un punto dell'arco, poi sul punto finale · "
                   "A = torna a linea") if self.arc else tr("Tratto a linea"), 3500)
            viewport.update()
            return True
        if key == Qt.Key_L and not (_Settings.auto or _Settings.trapezoid
                                    or _Settings.irregular):
            r = edit_layers(viewport.window(), copy.deepcopy(_Settings.layers))
            if r is not None:
                _Settings.layers = r or None
                viewport.flash_status(
                    tr("Strati: ") + (" + ".join(f"{l['t'] * 100:g}" for l in r)
                                      + " cm" if r else tr("nessuno (muro singolo)")),
                    3000)
            viewport.update()
            return True
        if key == Qt.Key_C and self.points:
            if len(_dedupe([(p.x(), p.y()) for p in self.points], True)) < 3:
                viewport.flash_status(tr("Per chiudere servono almeno 3 punti"), 3000)
            else:
                self._commit(viewport, closed=True)
            return True
        if key in (Qt.Key_O, Qt.Key_F8):
            _Settings.ortho = not _Settings.ortho
            if self.hover_point is not None:
                self.hover_point = self._ortho(self.hover_point)
            viewport.flash_status(
                tr("Ortogonale ") + (tr("attivo") if _Settings.ortho else tr("disattivato")),
                2000)
            viewport.update()
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter) and self.points:
            self._pulisci_buffer(viewport)
            self._commit(viewport, closed=False)
            return True
        if key == Qt.Key_Backspace and self.points:
            if self.arc_mid is not None:
                self.arc_mid = None
            elif self.arc_runs and self.arc_runs[-1][1] == len(self.points):
                del self.points[self.arc_runs.pop()[0]:]
            else:
                self.points.pop()
            viewport.update()
            return True
        return False

    def on_value(self, viewport, value) -> bool:
        if not self.points:
            return False
        last = self.points[-1]
        if isinstance(value, tuple):
            if len(value) not in (2, 3):
                return False
            new = QVector3D(last.x() + value[0], last.y() + value[1],
                            last.z() + (value[2] if len(value) == 3 else 0.0))
        else:
            if abs(value) < EPS:
                return False
            d = None
            if self.hover_point is not None:
                delta = self.hover_point - last
                if delta.length() > EPS:
                    d = delta.normalized()
            d = d or self.last_dir
            if d is None:
                return False
            new = last + d * value
        if (new - last).length() < EPS:
            return False
        self.last_dir = (new - last).normalized()
        self.points.append(new)
        self.hover_point = new
        if _Settings.trapezoid and len(self.points) >= 2:
            self._commit(viewport, closed=False)
            return True
        if _Settings.irregular and len(self.points) == 4:
            self._commit(viewport, closed=True)
            return True
        viewport.update()
        return True

    def status_clause(self) -> str:
        if _Settings.irregular:
            return tr("Muro poligonale: clic = vertice (4 in tutto, chiude da solo) · "
                      "O/F8 ortogonale · Backspace = toglie il punto")
        if _Settings.trapezoid:
            return (tr("Muro trapezoidale: clic = inizio, secondo clic o "
                       "lunghezza = fine · Ricalco {0} (Spazio) · O/F8 ortogonale")
                    .format(ALIGN_NAMES[_Settings.align].lower()))
        if _Settings.auto:
            return tr("Automatico: clic dentro un'area chiusa · Spazio = lato "
                      "(stanze) · Tasto destro o Esc = esci")
        if self.arc:
            return tr("Muro TONDO: clic = punto sull'arco, poi punto finale · "
                      "A = torna a linea · Backspace = annulla")
        return (tr("A = arco (muro tondo) · Ricalco {0} (Spazio) · Ortogonale {1} (O/F8) · C = chiudi · Invio = fine").format(ALIGN_NAMES[_Settings.align].lower(), ('ON' if _Settings.ortho else 'OFF'))
                + tr(" · L = strati") + tr(" · Tasto destro = fine, ancora = esci"))

    def value_label(self):
        if not self.points or self.hover_point is None:
            return None
        a, b = self.points[-1], self.hover_point
        if (b - a).length() < EPS:
            return None
        return (fmt_len((b - a).length()), (a + b) * 0.5)

    def rubber_band_lines(self):
        if _Settings.auto:
            return list(self._pv_lines)
        pts = list(self.points)
        if self.hover_point is not None and pts and (
                self.hover_point - pts[-1]).length() > EPS:
            if self.arc and self.arc_mid is not None:
                pts.extend(self._arc_points(self.hover_point))
            else:
                pts.append(self.hover_point)
        flat = _dedupe([(p.x(), p.y()) for p in pts], False)
        if len(flat) < 2:
            return []
        z = self.points[0].z()
        lvl = self._level()
        if lvl:
            z = lvl["z"] + _Settings.base_offset
        if _Settings.irregular:
            ring = flat + [flat[0]] if len(flat) >= 3 else flat
            return [(QVector3D(*ring[i], z), QVector3D(*ring[i + 1], z))
                    for i in range(len(ring) - 1)]
        P = QVector3D
        if _Settings.trapezoid:
            a, b = flat[0], flat[-1]
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            nx, ny = -(b[1] - a[1]) / L, (b[0] - a[0]) / L
            la, ra = side_offsets(_Settings.trap_a, _Settings.align)
            lb, rb = side_offsets(_Settings.trap_b, _Settings.align)
            aL, aR = (a[0] + nx * la, a[1] + ny * la), (a[0] - nx * ra, a[1] - ny * ra)
            bL, bR = (b[0] + nx * lb, b[1] + ny * lb), (b[0] - nx * rb, b[1] - ny * rb)
            return [(P(*a, z), P(*b, z)), (P(*aL, z), P(*bL, z)),
                    (P(*aR, z), P(*bR, z)), (P(*aL, z), P(*aR, z)),
                    (P(*bL, z), P(*bR, z))]
        d_left, d_right = side_offsets(_eff_th(), _Settings.align)
        left, right = offset_points(flat, False, d_left, d_right)
        lines = [(P(*flat[i], z), P(*flat[i + 1], z))
                 for i in range(len(flat) - 1)]
        for side in (left, right):
            lines += [(P(*side[i], z), P(*side[i + 1], z))
                      for i in range(len(side) - 1)]
        lines += [(P(*left[0], z), P(*right[0], z)),
                  (P(*left[-1], z), P(*right[-1], z))]
        return lines

    def draw_overlay(self, viewport, painter) -> None:
        try:
            self._draw(viewport, painter)
        except Exception:
            pass

    def _draw(self, viewport, painter) -> None:
        if not self.points:
            return
        painter.save()
        font = QFont()
        font.setPointSize(10)
        painter.setFont(font)
        fm = painter.fontMetrics()

        def chip(text, cx, cy, bg, fg):
            w, h = fm.horizontalAdvance(text) + 12, fm.height() + 6
            rect = QRectF(cx - w / 2, cy - h / 2, w, h)
            painter.setPen(Qt.NoPen)
            painter.setBrush(bg)
            painter.drawRoundedRect(rect, 4, 4)
            painter.setPen(QPen(fg))
            painter.drawText(rect, Qt.AlignCenter, text)

        ref = list(self.points)
        if self.hover_point is not None and (
                self.hover_point - ref[-1]).length() > EPS:
            ref.append(self.hover_point)
        if _Settings.irregular and len(ref) >= 3:
            ref.append(ref[0])
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(REF_COLOR, 3))
        for a, b in zip(ref, ref[1:]):
            pa = viewport._world_to_pixel(a)
            pb = viewport._world_to_pixel(b)
            if pa is not None and pb is not None:
                painter.drawLine(QPointF(pa[0], pa[1]), QPointF(pb[0], pb[1]))

        in_arco = set()
        for s0, e0 in self.arc_runs:
            in_arco.update(range(max(0, s0 - 1), e0 - 1))
        for i, (a, b) in enumerate(zip(self.points, self.points[1:])):
            if i in in_arco:
                continue
            px = viewport._world_to_pixel((a + b) * 0.5)
            if px is not None:
                chip(fmt_len((b - a).length()), px[0], px[1] - 14,
                     QColor(255, 255, 255, 225), QColor(20, 20, 20))
        for s0, e0 in self.arc_runs:
            if s0 < 1 or e0 > len(self.points):
                continue
            tot = sum((self.points[i + 1] - self.points[i]).length()
                      for i in range(s0 - 1, e0 - 1))
            mid = self.points[(s0 - 1 + e0 - 1) // 2]
            px = viewport._world_to_pixel(mid)
            if px is not None:
                chip(fmt_len(tot), px[0], px[1] - 14,
                     QColor(255, 255, 255, 225), QColor(20, 20, 20))

        typed = self._buffer()
        if typed:
            text = tr("Misura: {0}").format(typed)
            w = fm.horizontalAdvance(text) + 16
            h = fm.height() + 12
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(30, 30, 30, 200))
            painter.drawRoundedRect(QRectF(12, 44, w, h), 6, 6)
            painter.setPen(QPen(QColor(255, 255, 255)))
            painter.drawText(QPointF(20, 44 + 6 + fm.ascent()), text)
        painter.restore()

    def _segments(self, scene, z):
        key = (id(scene), getattr(scene, "version", None))
        if self._edge_cache is None or self._edge_cache[0] != key:
            edges, diag = collect_edges(scene)
            self._edge_cache = (key, edges, diag)
        _k, edges, diag = self._edge_cache
        segs, zl = pick_level_segments(edges, z)
        return segs, zl, diag

    def _auto_hover(self, ctx: ToolContext) -> None:
        import time
        w = QVector3D(ctx.world)
        if self._pv_poly is not None:
            try:
                from shapely.geometry import Point
                if self._pv_poly.contains(Point(w.x(), w.y())):
                    return
            except Exception:
                pass
        now = time.monotonic()
        if now - self._pv_time < 0.08:
            return
        self._pv_time = now
        poly, lines = None, []
        try:
            segs, zl, diag = self._segments(ctx.viewport.scene, w.z())
            if segs and not diag:
                poly = auto_area(segs, w.x(), w.y())
                if poly is not None:
                    P = QVector3D
                    for ring in [poly.exterior] + list(poly.interiors):
                        c = list(ring.coords)
                        lines += [(P(a[0], a[1], zl), P(b[0], b[1], zl))
                                  for a, b in zip(c, c[1:])]
        except Exception:
            poly, lines = None, []
        self._pv_poly, self._pv_lines = poly, lines
        ctx.viewport.update()

    def _auto_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        scene = vp.scene
        if getattr(scene, "edit_group", None) is not None:
            vp.flash_status(
                tr("Chiudi il gruppo che stai modificando, poi crea i muri"), 4000)
            return
        w = QVector3D(ctx.world)
        try:
            segs, zl, diag = self._segments(scene, w.z())
        except Exception as ex:
            vp.flash_status(tr("Non riesco a leggere le linee: {0}").format(ex), 6000)
            return
        if diag:
            vp.flash_status(
                tr("Non riesco a leggere gli spigoli ({0})").format(diag), 9000)
            return
        if not segs:
            vp.flash_status(
                tr("Nessuna linea trovata (scena e gruppi): serve un disegno in pianta"),
                5000)
            return
        try:
            if wall_at(scene, w.x(), w.y()):
                vp.flash_status(tr("Qui c'e' gia' un muro"), 3000)
                return
            kind, chains = auto_walls(segs, w.x(), w.y())
        except ImportError:
            vp.flash_status(
                tr("Serve la libreria shapely (pip install shapely)"), 5000)
            return
        if kind is None:
            vp.flash_status(
                tr("Il clic non e' dentro un'area chiusa: le linee devono toccarsi"),
                5000)
            return
        self._vp = vp
        lvl = self._level()
        base_z = (lvl["z"] if lvl else zl) + _Settings.base_offset
        off = _Settings.base_offset
        t, h, name = _Settings.thickness, _Settings.height, _Settings.name
        align = _Settings.align
        tlv, toff = _Settings.tlv, _Settings.toff
        paint = settings_paint()
        skirt = {k: getattr(_Settings, k) for k in ("bat_l", "bat_r")
                 if getattr(_Settings, k)}
        if tlv:
            from . import piani
            hl = piani.height_for(scene, tlv, toff,
                                  lvl["id"] if lvl else None, base_z)
            if hl is None:
                tlv = None
            else:
                h = hl
        count = [0]

        def mutate(sc):
            for c in chains:
                if kind == "walls":
                    th, al = round(c["t"], 3), "center"
                else:
                    th, al = t, align
                count[0] += build_walls(sc, c["pts"], c["closed"], th, h, base_z,
                                        name, al, lvl, off, tlv, toff, paint,
                                        skirt)
            update_roof_clips(sc)

        vp.history.execute(MuriCommand(mutate))
        vp.notify_scene_changed()
        self.last_count = count[0]
        self._pv_poly, self._pv_lines = None, []
        vp.flash_status(
            (tr("{0} muri creati dall'area (spessori dalle linee)") if kind == "walls"
             else tr("{0} muri creati lungo il contorno della stanza"))
            .format(count[0]), 4000)
        vp.update()

    def _commit_poly(self, viewport) -> None:
        if getattr(viewport.scene, "edit_group", None) is not None:
            viewport.flash_status(
                tr("Chiudi il gruppo che stai modificando, poi crea i muri"), 4000)
            return
        pts2d = _dedupe([(p.x(), p.y()) for p in self.points], True)
        if len(pts2d) != 4:
            viewport.flash_status(
                tr("Il muro poligonale ha 4 vertici: i due lati lunghi sono "
                   "le facce, quelli corti le testate"), 4000)
            return
        if not quad_ok(pts2d):
            viewport.flash_status(
                tr("I 4 punti devono formare un quadrilatero convesso "
                   "(senza lati incrociati): ritraccia l'ultimo punto"), 5000)
            if self.points:
                self.points.pop()
            viewport.update()
            return
        try:
            import shapely
        except ImportError:
            viewport.flash_status(
                tr("Serve la libreria shapely (pip install shapely)"), 5000)
            return
        lvl = self._level()
        base_z = (lvl["z"] if lvl else self.points[0].z()) \
            + _Settings.base_offset
        off = _Settings.base_offset
        h, name = _Settings.height, _Settings.name
        tlv, toff = _Settings.tlv, _Settings.toff
        paint = settings_paint()
        if tlv:
            from . import piani
            hl = piani.height_for(viewport.scene, tlv, toff,
                                  lvl["id"] if lvl else None, base_z)
            if hl is None:
                viewport.flash_status(
                    tr("Nessun piano di arrivo: uso l'altezza indicata"), 4000)
                tlv = None
            else:
                h = hl
        count = [0]

        def mutate(scene):
            count[0] = build_poly_wall(scene, pts2d, h, base_z, name, lvl,
                                       off, tlv, toff, paint,
                                       _Settings.thickness)

        viewport.history.execute(MuriCommand(mutate))
        viewport.notify_scene_changed()
        self.last_count = count[0]
        viewport.flash_status(tr("Muro irregolare creato"), 3000)
        self._reset()
        viewport.update()

    def _commit(self, viewport, closed: bool) -> None:
        if _Settings.irregular:
            self._commit_poly(viewport)
            return
        if getattr(viewport.scene, "edit_group", None) is not None:
            viewport.flash_status(
                tr("Chiudi il gruppo che stai modificando, poi crea i muri"), 4000)
            return
        pts2d = _dedupe([(p.x(), p.y()) for p in self.points], closed)
        if len(pts2d) < 2 or (closed and len(pts2d) < 3):
            self._reset()
            viewport.update()
            return
        lvl = self._level()
        base_z = (lvl["z"] if lvl else self.points[0].z()) \
            + _Settings.base_offset
        off = _Settings.base_offset
        t, h, name = _Settings.thickness, _Settings.height, _Settings.name
        align = _Settings.align
        tlv, toff = _Settings.tlv, _Settings.toff
        paint = settings_paint()
        skirt = {k: getattr(_Settings, k) for k in ("bat_l", "bat_r")
                 if getattr(_Settings, k)}
        if tlv:
            from . import piani
            hl = piani.height_for(viewport.scene, tlv, toff,
                                  lvl["id"] if lvl else None, base_z)
            if hl is None:
                viewport.flash_status(
                    tr("Nessun piano di arrivo: uso l'altezza indicata"), 4000)
                tlv = None
            else:
                h = hl
        count = [0]

        t_end = None
        layers = None
        if _Settings.trapezoid:
            t, t_end = _Settings.trap_a, _Settings.trap_b
        elif _Settings.layers:
            layers = copy.deepcopy(_Settings.layers)
            t = layers_total(layers)

        smooth = []
        for s0, e0 in self.arc_runs:
            for k in range(s0, e0 - 1):
                if 0 <= k < len(self.points):
                    smooth.append((self.points[k].x(), self.points[k].y()))

        def mutate(scene):
            count[0] = build_walls(scene, pts2d, closed, t, h, base_z, name,
                                   align, lvl, off, tlv, toff, paint, skirt,
                                   t_end, smooth, layers, _Settings.hatch)
            if closed and t_end is None and (_Settings.floor
                                             or _Settings.ceiling):
                _build_floor_ceiling(scene, pts2d, t, align, h, base_z, lvl,
                                     off)
            update_roof_clips(scene)

        viewport.history.execute(MuriCommand(mutate))
        viewport.notify_scene_changed()
        self.last_count = count[0]
        viewport.flash_status(tr("{0} muri creati").format(count[0]), 3000)
        self._reset()
        viewport.update()


ORDER = 10


def _wall_icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(215, 205, 190))
    p.drawRect(5, 17, 38, 14)
    p.drawLine(16, 17, 16, 31)
    p.drawLine(27, 17, 27, 31)
    p.drawLine(37, 17, 37, 31)
    p.end()
    return QIcon(pm)


def _selected_walls(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and wall_data(g) is not None and g not in out:
            out.append(g)
    return out


def sync_joints(scene, walls) -> None:
    def near(p, q):
        return math.hypot(p[0] - q[0], p[1] - q[1]) < 1e-6

    allw = [(g, wall_data(g)) for g in scene.groups if wall_data(g)]
    todo = []
    for g in walls:
        d = wall_data(g)
        if d is None:
            continue
        if g not in todo:
            todo.append(g)
        if not d.get("chain"):
            continue
        for g2, d2 in allw:
            if g2 is not g and d2.get("chain") == d["chain"] and any(
                    near(p, q) for p in (d2["a"], d2["b"])
                    for q in (d["a"], d["b"])) and g2 not in todo:
                todo.append(g2)
    for g in todo:
        d = wall_data(g)
        if d.get("th_b") is not None or not d.get("chain"):
            continue
        extra = {}
        for g2, d2 in allw:
            if g2 is g or d2.get("chain") != d["chain"]:
                continue
            if (near(d2["b"], d["a"]) or near(d2["a"], d["a"])) \
                    and d.get("prev"):
                extra["pth"] = d2["th"]
            if (near(d2["a"], d["b"]) or near(d2["b"], d["b"])) \
                    and d.get("next"):
                extra["nxth"] = d2["th"]
        if any(d.get(k) != v for k, v in extra.items()):
            rebuild_wall(g, d["th"], d["h"], extra)


def _w_mat(g):
    from PySide6.QtGui import QMatrix4x4
    m = wall_pose(g)
    gx = getattr(g, "xform", None)
    if gx is not None:
        m = QMatrix4x4(gx) * m
    return m


def _inter(p0, u0, p1, u1):
    det = u0[0] * u1[1] - u0[1] * u1[0]
    if abs(det) < 1e-6:
        return None
    t = ((p1[0] - p0[0]) * u1[1] - (p1[1] - p0[1]) * u1[0]) / det
    return (p0[0] + u0[0] * t, p0[1] + u0[1] * t)


def _ls_point(lines):
    a11 = a12 = a22 = b1 = b2 = 0.0
    for (p, u) in lines:
        nx, ny = -u[1], u[0]
        a11 += nx * nx
        a12 += nx * ny
        a22 += ny * ny
        c = nx * p[0] + ny * p[1]
        b1 += nx * c
        b2 += ny * c
    det = a11 * a22 - a12 * a12
    if abs(det) < 1e-6:
        return None
    return ((b1 * a22 - b2 * a12) / det, (a11 * b2 - a12 * b1) / det)


def lega_muri_calcola(walls):
    import itertools
    info = []
    for g in walls:
        d = wall_data(g)
        m = _w_mat(g)
        inv = m.inverted()[0]
        A = m.map(QVector3D(d["a"][0], d["a"][1], 0.0))
        B = m.map(QVector3D(d["b"][0], d["b"][1], 0.0))
        A, B = (A.x(), A.y()), (B.x(), B.y())
        L = math.hypot(B[0] - A[0], B[1] - A[1])
        if L < 1e-6:
            return None
        u = ((B[0] - A[0]) / L, (B[1] - A[1]) / L)
        dl, dr = side_offsets(d["th"], d["align"])
        info.append({"g": g, "d": d, "inv": inv, "A": A, "B": B, "L": L,
                     "u": u, "dl": dl, "dr": dr})
    n = len(info)
    maxth = max(w["d"]["th"] for w in info)
    best = None
    for combo in itertools.product(("a", "b", "t"), repeat=n):
        if all(c == "t" for c in combo):
            continue
        lines = [(w["A"], w["u"]) for w in info]
        ends = [(w["A"] if c == "a" else w["B"])
                for w, c in zip(info, combo) if c != "t"]
        J = _ls_point(lines)
        if J is None:
            J = (sum(p[0] for p in ends) / len(ends),
                 sum(p[1] for p in ends) / len(ends))
        cost = 0.0
        ok = True
        for w, c in zip(info, combo):
            if c == "t":
                t = ((J[0] - w["A"][0]) * w["u"][0]
                     + (J[1] - w["A"][1]) * w["u"][1])
                marg = 1.5 * maxth
                if t < marg or t > w["L"] - marg:
                    ok = False
                    break
                dist = abs(-(J[0] - w["A"][0]) * w["u"][1]
                           + (J[1] - w["A"][1]) * w["u"][0])
                cost += dist * dist + (1.5 * maxth) ** 2
            else:
                P = w["A"] if c == "a" else w["B"]
                cost += (P[0] - J[0]) ** 2 + (P[1] - J[1]) ** 2
        if not ok:
            continue
        if best is None or cost < best[0]:
            best = (cost, combo, J)
    if best is None:
        return None
    cost, combo, J = best
    if math.sqrt(cost / n) > max(1.5, 6 * maxth):
        return None

    arms = []
    for w, c in zip(info, combo):
        sides = [(w["u"], 1)] if c == "a" else [((-w["u"][0], -w["u"][1]), -1)] \
            if c == "b" else [(w["u"], 1), ((-w["u"][0], -w["u"][1]), -1)]
        for (u, sg) in sides:
            oL, oR = (w["dl"], w["dr"]) if sg == 1 else (w["dr"], w["dl"])
            if c == "a":
                P0 = w["A"]
            elif c == "b":
                P0 = w["B"]
            else:
                P0 = J
            nx, ny = -u[1], u[0]
            arms.append({"w": w, "u": u, "sg": sg, "c": c, "ang":
                         math.atan2(u[1], u[0]),
                         "pl": (P0[0] + nx * oL, P0[1] + ny * oL),
                         "pr": (P0[0] - nx * oR, P0[1] - ny * oR)})
    arms.sort(key=lambda a: a["ang"])
    na = len(arms)
    corner_l = {}
    corner_r = {}
    for i in range(na):
        p, q = arms[i], arms[(i + 1) % na]
        if p["w"] is q["w"]:
            continue
        X = _inter(p["pl"], p["u"], q["pr"], q["u"])
        lim = max(1.5, 8 * maxth)
        if X is None or math.hypot(X[0] - J[0], X[1] - J[1]) > lim:
            def foot(P, u):
                t = (J[0] - P[0]) * u[0] + (J[1] - P[1]) * u[1]
                return (P[0] + u[0] * t, P[1] + u[1] * t)
            X = foot(p["pl"], p["u"])
            Xq = foot(q["pr"], q["u"])
            corner_l[i] = X
            corner_r[(i + 1) % na] = Xq
            continue
        corner_l[i] = X
        corner_r[(i + 1) % na] = X

    fill_pts = None
    if na >= 3 and all(a["c"] != "t" for a in arms) \
            and all(i in corner_l for i in range(na)):
        fill_pts = [corner_l[i] for i in range(na)]

    out = {}
    for i, a in enumerate(arms):
        w = a["w"]
        if a["c"] == "t":
            continue
        cl = corner_l.get(i)
        cr = corner_r.get(i)
        jn = out.setdefault(w["g"], {})

        def loc(P):
            v = w["inv"].map(QVector3D(P[0], P[1], 0.0))
            return [v.x(), v.y()]
        if a["c"] == "a":
            if cl:
                jn["aL"] = loc(cl)
            if cr:
                jn["aR"] = loc(cr)
        else:
            if cl:
                jn["bR"] = loc(cl)
            if cr:
                jn["bL"] = loc(cr)
    if out and fill_pts:
        w0 = next(a["w"] for a in arms if a["c"] != "t")
        jn0 = out.setdefault(w0["g"], {})
        jn0["fill"] = []
        for P in fill_pts:
            v = w0["inv"].map(QVector3D(P[0], P[1], 0.0))
            jn0["fill"].append([v.x(), v.y()])
    return out or None


def lega_muri(viewport, walls=None) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    walls = walls or _selected_walls(scene)
    if not 2 <= len(walls) <= 4:
        viewport.flash_status(tr("Seleziona da 2 a 4 muri da legare"), 4000)
        return
    if any(wall_data(g).get("poly") or wall_data(g).get("th_b") is not None
           for g in walls):
        viewport.flash_status(
            tr("Muri irregolari o trapezoidali: non si possono legare"), 5000)
        return
    res = lega_muri_calcola(walls)
    if not res:
        viewport.flash_status(tr("I muri scelti non si incontrano in un punto"),
                              5000)
        return

    def mutate(sc):
        for g, jn in res.items():
            d = wall_data(g)
            old_jn = d.get("jn") or {}
            if abs(old_jn.get("th", d["th"]) - d["th"]) > 1e-9 \
                    or old_jn.get("al", d["align"]) != d["align"]:
                old_jn = {}
            new_jn = dict(old_jn)
            for k, v in jn.items():
                new_jn[k] = v
            jn = new_jn
            jn["th"], jn["al"] = d["th"], d["align"]
            rebuild_wall(g, d["th"], d["h"], {"jn": jn})

    hist = viewport.history
    hist.execute(MuriCommand(mutate))
    if getattr(hist, "last_error", None):
        viewport.flash_status(tr("Muri: ") + str(hist.last_error).split(": ", 1)[-1],
                              6000)
        return
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("{0} muri legati").format(len(walls)), 3000)


def edit_walls(viewport, walls=None) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    walls = walls or _selected_walls(scene)
    if not walls:
        viewport.flash_status(tr("Seleziona un muro creato con lo strumento Muri"),
                              4000)
        return
    chains = {wall_data(g).get("chain") for g in walls} - {None}
    first = wall_data(walls[0])
    dlg = QDialog(viewport.window())
    dlg.setWindowTitle(tr("Modifica muro") if len(walls) == 1
                       else tr("Modifica {0} muri (catena)").format(len(walls)))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(_Schema(_disegno_muro))
    thick = _spin(first["th"], 0.02, 5.0)
    height = _spin(first["h"], 0.1, 100.0)
    thick_b = None
    if first.get("th_b") is not None:
        thick_b = _spin(first["th_b"], 0.02, 5.0)
        form.addRow(tr("Larghezza iniziale (m)"), thick)
        form.addRow(tr("Larghezza finale (m)"), thick_b)
    else:
        form.addRow(tr("Spessore (s) (m)"), thick)
    form.addRow(tr("Altezza (H) (m)"), height)
    from . import piani
    has_levels = bool(piani.levels(scene))
    top_cb = top_off = None
    if has_levels:
        top_cb, top_off = piani.add_top_rows(form, scene, height,
                                             first.get("tlv"),
                                             first.get("toff", 0.0))
    init_off = first.get("off", first["z0"])
    if has_levels:
        lvl_cb = piani.level_combo(scene, first.get("lv"))
        off_sp = _spin(init_off, -100.0, 1000.0)
        form.addRow(tr("Piano"), lvl_cb)
        form.addRow(tr("Distanza dal piano (Nessuno: quota base) (b) (m)"), off_sp)
    lay_state = [copy.deepcopy(first.get("layers"))]
    lay_ok = first.get("th_b") is None and not first.get("poly")
    lrow = None
    if lay_ok:
        lrow = layers_row(dlg, thick, lay_state)
        form.addRow(tr("Strati"), lrow)
    hatch_w = HatchPick(first.get("hatch"))
    form.addRow(tr("Retino di sezione (muro senza strati)"), hatch_w)
    skirt_w = add_skirt_rows(form, first.get)
    paint_w = add_paint_rows(form, first.get, WALL_ZONES)

    def _res():
        L = lay_state[0] or None
        out = dict(paint_results(paint_w), layers=copy.deepcopy(L),
                   hatch=hatch_w.result(),
                   th=layers_total(L) if L else thick.value())
        out.update(skirt_results(skirt_w))
        return out

    def _set_t(t):
        _tipi.fill_widgets(dict(paint_w), dict(t, **{k: t.get(k) for k in paint_w}))
        lay_state[0] = copy.deepcopy(t.get("layers")) or None
        if not lay_state[0] and "th" in t:
            thick.setValue(t["th"])
        lrow.refresh()
        hatch_w.set(t.get("hatch"))
        _set_skirt(skirt_w, t)

    tbar = (_tipi.TypeBar(dlg, form, "muro", first, _res, _set_t, scene)
            if lay_ok else None)
    cf = _codici.CodeField(form, walls, "muro", scene, at=2 if tbar else 1)
    chain_cb = None
    if chains:
        chain_cb = QCheckBox(tr("Solo i muri selezionati "
                                "(non tutta la catena)"))
        chain_cb.setChecked(False)
        form.addRow(chain_cb)
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return
    cf.apply(dlg)
    pt, st = None, "ok"
    if tbar is not None:
        pt = tbar.result(_res())
        st = _tipi.resolve_edit(viewport.window(), scene, "muro", pt)
        if st == "cancel":
            return
    if chain_cb is not None and not chain_cb.isChecked():
        walls = list(walls)
        for g in scene.groups:
            d = wall_data(g)
            if d and d.get("chain") in chains and g not in walls:
                walls.append(g)
    t, h = thick.value(), height.value()
    hatch_res = hatch_w.result()
    bat_extra = {k: v for k, v in skirt_results(skirt_w).items()
                 if v != first.get(k)}
    paint_extra = {k: v for k, v in paint_results(paint_w).items()
                   if v != first.get(k)}
    extra = None
    if has_levels:
        lid, off = lvl_cb.currentData() or None, off_sp.value()
        if lid != first.get("lv") or abs(off - init_off) > 1e-9:
            lv = piani.get(scene, lid)
            extra = ({"lv": lv["id"], "lvn": lv["name"], "off": off,
                      "z0": lv["z"] + off} if lv else
                     {"lv": None, "lvn": None, "off": None, "z0": off})

    tlv = (top_cb.currentData() or None) if top_cb is not None else None
    toff = top_off.value() if top_off is not None else 0.0
    failed = [0]

    def mutate(sc):
        for g in walls:
            ex = dict(extra or {})
            ex.update(paint_extra)
            ex.update(bat_extra)
            if hatch_res != first.get("hatch"):
                ex["hatch"] = hatch_res
            if lay_ok and lay_state[0] != first.get("layers"):
                ex["layers"] = copy.deepcopy(lay_state[0])
            if thick_b is not None and wall_data(g).get("th_b") is not None:
                ex["th_b"] = thick_b.value()
            hh = h
            if top_cb is not None:
                ex["tlv"], ex["toff"] = None, None
                if tlv:
                    d = wall_data(g)
                    z0 = ex.get("z0", d["z0"])
                    lid = ex["lv"] if "lv" in ex else d.get("lv")
                    hl = piani.height_for(sc, tlv, toff, lid, z0)
                    if hl is None:
                        failed[0] += 1
                    else:
                        hh = hl
                        ex["tlv"], ex["toff"] = tlv, toff
            if pt is not None:
                ex["tipo_id"], ex["tipo_nome"] = pt.get("tipo_id"), pt.get("tipo_nome")
            rebuild_wall(g, t, hh, ex)
        if st == "type":
            def _rb(g, q):
                dd = wall_data(g)
                if dd.get("th_b") is not None or dd.get("poly"):
                    return
                rebuild_wall(g, q.get("th", dd["th"]), dd["h"],
                             {k: v for k, v in q.items() if k != "th"})
            _tipi.update_instances(sc, "muro", pt["tipo_id"], _rb)
        sync_joints(sc, walls)
        update_roof_clips(sc)
        try:
            from . import sezione_strati
            sezione_strati.rebuild_sections(sc)
        except Exception:
            pass
        try:
            from . import finestre
            finestre.update_openings(sc)
        except ImportError:
            pass

    hist = viewport.history
    hist.execute(MuriCommand(mutate))
    if getattr(hist, "last_error", None):
        viewport.flash_status(tr("Muri: ") + str(hist.last_error).split(": ", 1)[-1],
                              6000)
        return
    viewport.notify_scene_changed()
    viewport.update()
    if failed[0]:
        viewport.flash_status(
            tr("Nessun piano di arrivo valido (sotto la base?): "
            "uso l'altezza indicata"), 6000)
        return
    viewport.flash_status(tr("{0} muri aggiornati").format(len(walls)), 3000)


def edit_wall_paint(viewport, walls=None) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    walls = walls or _selected_walls(scene)
    if not walls:
        viewport.flash_status(tr("Seleziona un muro creato con lo strumento Muri"),
                              4000)
        return
    first = wall_data(walls[0])
    dlg = QDialog(viewport.window())
    dlg.setWindowTitle(tr("Colori e texture muro") if len(walls) == 1
                       else tr("Colori e texture di {0} muri").format(len(walls)))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    pk = add_paint_rows(form, first.get, WALL_ZONES)
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return
    changed = {k: v for k, v in paint_results(pk).items()
               if v != first.get(k)}
    if not changed:
        return

    def mutate(sc):
        for g in walls:
            d = wall_data(g)
            rebuild_wall(g, d["th"], d["h"], dict(changed))

    hist = viewport.history
    hist.execute(MuriCommand(mutate))
    if getattr(hist, "last_error", None):
        viewport.flash_status(tr("Muri: ") + str(hist.last_error).split(": ", 1)[-1],
                              6000)
        return
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("Materiali applicati a {0} muri").format(len(walls)),
                          3000)


def top_props(d):
    if not d.get("tlv"):
        return []
    arrivo = (tr("Piano successivo") if d["tlv"] == "next"
              else tr("Piano di arrivo"))
    return [(tr("Altezza fino a"), arrivo),
            (tr("Distanza dall'arrivo"), fmt_len(d.get("toff", 0.0)))]


def _outliner_kind(group):
    d = wall_data(group)
    if d is None:
        return None
    from . import piani
    return {"type": tr("Muro"),
            "props": ([(tr("Larghezza iniziale"), fmt_len(d["th"])),
                       (tr("Larghezza finale"), fmt_len(d["th_b"]))]
                      if d.get("th_b") is not None else
                      [(tr("Spessore"), fmt_len(d["th"]))])
            + [(tr("Altezza"), fmt_len(d["h"]))]
            + piani.level_props(d) + top_props(d)}


def _hook_double_click(vp) -> None:
    if getattr(vp, "_myhouse_muri_dbl", False):
        return
    original = vp.begin_group_edit

    def begin_group_edit(group, *args, **kwargs):
        g = getattr(group, "owner", None) or group
        if wall_data(g) is None:
            return original(group, *args, **kwargs)
        from PySide6.QtCore import QTimer
        scene = vp.scene
        try:
            scene.select([g])
        except Exception:
            scene.selection.clear()
            scene.selection.add(g)
        vp.update()
        QTimer.singleShot(0, lambda: edit_walls(vp, [g]))

    vp.begin_group_edit = begin_group_edit
    vp._myhouse_muri_dbl = True


def _register_level_kind() -> None:
    from . import piani

    def zset(d, z):
        d["z0"] = z

    def hset(d, h):
        d["h"] = h

    piani.register_kind(
        "muro", KEY, wall_data, lambda d: d["z0"], zset,
        lambda g, d: setattr(g, "children", [wall_part(d, wall_pose(g), g.name)]),
        lambda d: d["h"], hset)


def register(api) -> None:
    _register_level_kind()
    tool = MuriTool()
    api.add_button(tr("Muri"), tr("Traccia muri cliccando i punti dell'asse"),
                   _wall_icon(), api.run_tool(tool))
    app = api.app
    _hook_double_click(api.window.viewport)

    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QKeySequence, QShortcut

        def nuovo_muro() -> None:
            vp = app.viewport
            if getattr(vp, "_value_buffer", ""):
                return
            if getattr(vp.scene, "edit_group", None) is not None:
                vp.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
                return
            if _Settings.used:
                tool.start_same(vp)
            else:
                tool.on_activate(vp)

        sc = QShortcut(QKeySequence("Shift+M"), api.window)
        sc.setContext(Qt.WindowShortcut)
        sc.activated.connect(lambda: QTimer.singleShot(0, nuovo_muro))
        tool._shortcut_shift_m = sc
    except Exception:
        pass
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        from PySide6.QtCore import QTimer

        def context(menu, selection) -> None:
            scene = app.viewport.scene
            walls = _selected_walls(scene)
            if _Settings.used and (walls or not scene.selection):
                menu.addAction(
                    tr("Nuovo muro (stesse impostazioni)  Shift+M"),
                    lambda: QTimer.singleShot(
                        0, lambda: tool.start_same(app.viewport)))
            if not walls:
                return
            menu.addSeparator()
            if 2 <= len(walls) <= 4:
                menu.addAction(
                    tr("Lega muri"),
                    lambda: QTimer.singleShot(
                        0, lambda: lega_muri(app.viewport)))
            menu.addAction(
                tr("Colori e texture muro…"),
                lambda: QTimer.singleShot(
                    0, lambda: edit_wall_paint(app.viewport)))
            menu.addAction(
                tr("Modifica muro…"),
                lambda: QTimer.singleShot(
                    0, lambda: edit_walls(app.viewport)))

        add_ctx(context)
    add_kind = getattr(app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)


_RAD_OBJ_DATA = (
    "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"
    "bA+hqFRK3dNn3u2j0zTUFmLVbm5gsi2kadcB1/7p23d4HCm9GsKMwW7CeoNUWmYodfjiDMkIUqVsIPX13lSP8ig5wqal9ctVZ09N"
    "TSMlpVzNfLUqtUbLE5SSmpaekZmVnaDIRo0eM7Z83PgJE90FhUXFetSQhcPyC5yTMw4UlRFshc0cdBaUmJQS6oGRw8yzztew1NAh"
    "/kGc4Qdw7uYfvmlDZ+qL0sK581TXzr38innzb5x77RXzr/vTE3feNfeme+66c961850Or99HuV12m8dqYUOEb8CSb+WKb75etujL"
    "pYu/ijYlGAg3Zv7cP732zyfeevP9f8+77e1/XX7Drdc9+JvqA6++sm/vP17eX3X/vR9+8Hblk8UvPP/cs9c/8NhvC3/3zoJfP/DX"
    "p95795mnd+38+9/yH1rw9q9++dKLjxb84uffrVy/7uOFi7/aX1VZsWzpiuVffvGfjzes37P73XeWLV275s1/vvXmc88+9+w/33j9"
    "tffeXfD2M0+/8fqrr3z04aIvsck+/LB0uPn7KVSHTJ2BoqpVfp3DSli6rtKUcTCthvJ4JHsmFRnpfYziyNN/XfLt7x578YWFH/3z"
    "jS+/eGfBN19//tnf//bIw7999KEHf//4b37997/99SmJ9C9/Pj6HeeYibw2Erd89Klnag4MSN9fVsqMlZfS4s+//F8sG3/q8dsx8"
    "itgdRw6vX9d8tP5gX++K5RX7DjXt3rV1y9o1S77t6nQ6OtqtFq/H79u7Z9nSEnJwLvmmp9vt2r6tscHjttvaWjdvqqr8biWZyZId"
    "xTJDyzFzv8Pucq5e5dtVVxsKbtxwYH9NdcBPWJvVsnPnjr7ewB/+QlFF1K0hpd/7JF3E/p7961N/ZJ8nCk43/EYfMpA7brv6qnsv"
    "nXvtNVffdsf1191+x10//cmtFH3LbT+59c7bbrzhzjuaGm+57TcTZt0xf95tt9/10+ajjQ233HrzTeRBomk5dtdPX35J+mpb6ytP"
    "HmripFRC04xMKpWzqeF4TnZGlvD6ceIh1G8UbzmdaP2SyZO5p5+4fShV/pDV4UoQrcws/GvMzEpvLcA7IwrLx5Hzx41PTZs6jZyd"
    "nTNz2uQpU8/lxLF8fH5BaVn5uHOKzjt/fFnuuMnnl49LLSifzNAed8Cv1Uglap1c5ljyzderV/VZzCuWr/3i8696e7q7OvutCpWS"
    "DeldTruN+LzBcmxcfs55M0vHXTqFeGefO25OdtqkCTPHiW0R23IG2jLI18aPGq1n2O/2c9aUZFJ7UGMSkkJGU/vxWIo+4grOCyd2"
    "6tLgHLRwdRxHuD/8zkFPkSap5AgeFcQZ5hd6sAHMmcN5suj7SrBUE3qWUlLPW2V0s/Db3NXZU1N98HB/Y8PR9ua9ezZvXL92Tcv2"
    "bVUKJU/d5m3frTm4+Nuly1eu31Rbf2BvZXPV7u27jjYeJmxLO4vFpaT29HOOBcs5hugWBFiiaUCiMp1qG0sapXQWHThA+kL7HJL0"
    "KlLTvy9rL63wykhRiCYsZ6QrDQFtYZ1WPizkVjikduJmXfJjpLnNQfmpErWZkKDSk65R2g81eXrcRKZUeHar/E61hgxtXdk46xp5"
    "yvUe3rxK/L6doZ07PG6vJxhwOfv7aqrb2441Nza4nJ0dVsuunYcPbd1Ssa/+4K6dFfsq9u3eteTbFctbW9auWfzV0SO9Pf/5eNnS"
    "zZt2bN+9a++e5ctWr9qx/cD+vXuWLtm2daBu9Or8MoraI6P65FQfRbltyoCpg1H5A1V7dcrWbDtrkdCVo4xy3W69qeHddxZ9ufCj"
    "BW9/8P6/3vrm6y8+p3F4w7mmTIZVw+TuZqrGMKkM42TrU42OjH3p6l2umkxD977ebOkOiu6rGX9wShtxGjr5xRP0d6E5+Tl1VY6G"
    "vlJqZUn27vZxSy+p3YNcdmkdSpbdbt5CS6jJL03T6B/7HUVEIJ4WEFcMAHHF8svyEIjfrfpRAzGMwxQmDEMm6JTrfaPGGSWueulI"
    "bWMvyakWws9eQHo5SIYhONnRc4MfQTi8pLZhEkWHgchBcPq07StYdotZo6fI7j0iEE8LiPcMAPGeu995AIH4s/t+tECkvLU+o01n"
    "RRQeZgZ0YiDobJZ9iipxTnXWlO59rXJlGGAUycllt9+D8OKg1o3ajqIH6UkEKrnBX6iRyBGltf1exVJtR6qSm42iaG52ikOLtoVQ"
    "wzLS80YMR7TorRaH2+X3jkDnoLRkwsTjjxrZEDoexE+CR3SBejI84He7rBaf9/ChUNDc39fb2dHacrCOFJr729tajjkdVZW7dh7Y"
    "X7GvtmZ/1e5dtTXVByr27a/au2fD+n17d2zH2usaGIlSJZUZudqwjvzcvIw0vUGuMKWkZxakst09vX39Zou1urZi/96de441NzVG"
    "JInHbAKtZlsgSEx2V0qq2xcm+vY7fnrnXXffc2/EZyJFhDYemztv3nqpTKW+du6Nc1WyO+fNvena+Tq1Ui9VmT5VqQN+NhQkvpdf"
    "eP6V5559681wJfv2yhW7dnqrD1Ru2zqINXfedfaUyZNmTJ82deY5s2cpR1x04VkTc3NGHCkZWVgwdszoUakp6Wnk3PPOzc7KzBhX"
    "XlY6YfwF5+e3kqnFRaIv+1/jy+ZFvjvICNTbh6lWFaWmSYhkRXRzATFg7GxqFTU3OI+9jhBqKclHDe0mZURHrSRefqY5wJeRymlm"
    "UsxrfznGGf5qOtXOa/KVGC8kZpKBObxEwTPUwLFTRnp7UAJqa9rb9u3tMrsON+z/8vNPP7GikFGVGzbv7Hzvg48+3n2gztx+dMv2"
    "piN7KmoONh4L5+6zdPX6ghRtd1H5SlTiSlQBlIraN5mQYwFavdd3hPg9h0M2XQepk28fto1g20hJt4U6B/NT9aXBmZkNym3ZxC71"
    "EW9Pn6HT0EQazbXsHre+x4aqR6pwWRhJ+mSjgjpITmt6qH8G7SRTtQqvd0pXQ31/ikOj8nkDfnN/Q73btcHl83rcPd2HmhobGhuq"
    "D9isO3fU1Xa0NzbU1W5Y39e7a2dN9f6q9et2bF+xvP7gsqVfLaqp3rxp1XcUpfDyU2zh2g/45X0qbr7G4qN0+kNy2k/T+43qNp2b"
    "7lVK9haw2erd7pTWdWs//2z7tpUr+nq7Oj/8AE1m3fZtNMM5ljL5wo/ee/etN99ZwDDZLfq8lCWjVkxl5Azjd6NL0WU0aYtWjfC2"
    "Hw26N++83FL6hfPTTwK+L78g7Nv/oizmPgr7Gnnw/r9lSkLJl3xrye/g9HZAu1h5aXMJCR26qveYeadkRMFX51mq5zc35y2fem5N"
    "9YQvv0BUUAztZxQDfOzu0fPP7u5lLBKJkW2Jn1ktHlkcIGPJxOKe4pEd7W2tTY3ddWZrd8fBurpas6Wultr7wZ6P6Ip9Rw4d2C9X"
    "ELqqcs2B/dV796D1HsUSki4J9FKUhyJ+qVfO9MmUoWC+V78jxeFwyblKMqxWG6Wvra7c37+yEm3igf21NbXVFlvLMXPf1tr/fPwe"
    "8qy2+tWXqmsPYK/seJ/6lL75hj9/vPCDD+cwtKyIKlcVT5ryH/c/F77x+o9WadiStIQ121I7uqPWtKc/3+3j2uEPjbC7ioplcqlM"
    "UTVmbEmprCE7JyNTJxs9prSstGzyFLQZY8hF58ycPOWCmTPGlJwj1ZdWFJSQmzPKJo8j5WTSSPk5U8oaRk8pzxwza8LECePInVNy"
    "JpdOrR49w+3auMGzc4fTYVJt3ZLy3UojYVPT00LBjGVLM9eu2ZOllEoYhU5LU4aAXy7TqPW+6X3ZE8lP4lsSVYIUUZO0yNl+dDE7"
    "8Fo+KR5b3tszWioZN37E8AkT05SKsyZNnnL21LLSgvxp02ecM9NhP1er8bhHphgNOdkBv8XMZpBZlq1EQ3ItZlSGKuI0H/V5vYus"
    "FrIer8zxuFuWd3V2rMFzXW+VxWyz9vakB3rNHn9GttZgGuFwKzUXWuyzZl965RU5+cWll1x08VWXXS5VpJ5/QcHw886lJKM6e2bO"
    "IeOJor3N3C8aJtEwiYZJNEyiYRINk2iYRMMkGibRMImGSTRMomESDZNomETDJBom0TCJhkk0TGcYYy1xyjX8MvaCvtGSK2qI5OqG"
    "zZuStY0lO7av+m7jhm1bV323b+/Xizes//yzPbvXrV2zes3qdWtXrtiyedfOlRXffrN0yVeLNm1cvuz1N37z4e3P/xaZRlEtXsoz"
    "fAQhwRy3d+QKNmcNvZo8o1iVv4zMvmU6+c7xRcdbT/yJvKBcQq74/ePkAvIsWUKuIt888vBtt5KLKFYiIDbU2dXNMl3YEayik2Y1"
    "rK6dZk1saivNZrLZx2g235RqTEnLMJj0Rp0hNT09LSVNp9Hq3bqRo9L1WRlGvZQxeVNNOr3Lo5CplR63uFTitJZKVA4slaismCBR"
    "+Z37D/x4l0rQgxY69B6cUhVbkJNi1Y7c6N14TLC2R7eccrIMwy8xa235zlWvoD2Si2tMG52xJTvzpm2vHFiy8+2S4wtl8iX1Wzav"
    "qkKxW7FubVgQt2399psN63dsr6xY9d2XXyxf9vXipUs2rOe2p+zb+9Wizz9LwDkVWc6ApVNHSSbJt6qFNOSE32SbJyGHCyXGnZM9"
    "SoYJHSEOpXIUk1E/i71w58WskjBET0ZuLyPEOZ11DecaUdV5BbWdneFwTqQrr1x7KbtqOcNeTeazN7A3rfpJaDkxsqlsOpvZmpmx"
    "mvyKnEtmzj6HzEDeTiNT95xNppBjJJ2kbUeNriRmvcFg5FpqQiHOyx9WYDCm6bIydXk52Sk6is41FeinlydfNJIyaUq+OnUeGi+S"
    "2dnR19vW2tx01dXtbW2tLceaj95ybU935hVHDvf3BfydHc1H21rb244c7u1pbXE6jhwmKpVSpUwxqfGbZGoaVEqDVr2XSDKJR446"
    "QGPMU7Eet53KLmZmNs6QnE1N3R8IDvMNp86mJjWy1FnSIsNWMg4bpEpPW3kZeVjk+/8W38+apFLrDeMnZGWXls3AYcjY8mMKojhG"
    "Dge2lbGqzaRNe4xsOz/LW6WtJPYeW0Yqq1daQnIjIe15VGuPKhjKy2/xFiozfBQznB02+ZqJo2ao1JS1tv7y6eNKx48bmWHMnDyG"
    "7dOPIX0TxhtNir4x2RMnX3JxyaxLLpazAcKwMlZhJwN+dXcuO5Ydx05gz9qnNZGUIjniAC2FNyCV0YzbRw6o9rOVwVCgUnFUUrt9"
    "KxVeaeTy+ENKFXXlVRarZ4t657Dh7KZFX27ZyEgYSXff1fNpeWhtaCPZenRTxn5SYdwm2xHaINQX0WVL2HOFw9D58lC2kmF4jS0v"
    "LRwzegzx4wjRkD+Mco4tH18etBxt7uvs8lEuu8Nt7en1eHGAyo4tGz25DL36MnYM6yUjK8tCozCmJTMqzg2dx17AcphOpqEmTZhQ"
    "vm8TkY+dSNGVVA1VSe2lDvh2U/swdoCq8W/Da7W+XYpKoqmga2imdtkqLCjE/OSWWy/+djFG+xY8j0cLtfqjhRRtafv3qxTtafvb"
    "3/m9eLlVBz73P/jQwxd+9aUyM6vvxTdx6HtwxdLhIxx/fxLpOPDY7zDZLs3KlvdMS/78F4p2rueurEtO6WN/lQwfsenpf6LXmXL7"
    "zzDNhsvv/MXdN2LadfOvpejGbedcihc/euy3jz7y8EPPPX/V3HmWx3/34G8umbVWKlv4yovnzDTv/9UvR5/z6wcKqIKb/l973wEf"
    "R3XtPWdme1fvvVuyZBv3BtjYhFBssGkGTA2E5P0ILfXlPQLk4xFIeEleHnwhhAeEEDDYxL1XybKs3i3JVm+WVtrey9x3Z1fyzszu"
    "SjK85Pvitzva2dnZmTtz75x7/ucc3fs/9+Vu2nTH7bc99eT8lx7efuv37tz8rSeKX3r8Mc1dv1iZ/egjm1fee4/8oQdvfu7urU9/"
    "e9miLXd99zsrVkPvA9tWvwgZkIcbpxKyYA2UjxVAG6xz4Dc0CCphseGYpDyq190AG6EQv8/Ambg6z3HqDKyHb8I+uNO2BzbAHXC3"
    "+jBshdtgi+Nz2EztgxvQF3A9bPKs9t6O9sMD4jWi21GtZQlqyDyFmiGr/ENUj5oSKlCtZC2sRDWoHhagZtRKlaImSxnMQ632QtSK"
    "mlBr9HLU6spL24hqHIWQQier56FRfO7opSSUjMZdyxJiY6LjM9NScytrzlZ8uON41cfvf/nXP753ob0De4ZtlWfrtOOfffrBJ82y"
    "wWLd4+n37t8X+lH88jfI7TKbLHaHTCr/6MM/f/Ll8XMVDaVYSnPpnOoz1c29PQeO9PVif7F1uH1w6Nj+tp6Du1sOHO0daf3y6IVW"
    "xkLoG2jrL9j45a49+3uHx7GOu4xvdCSaRoNoAOs5h4ZGVmzFm5FJdWAX45HLFUio1IBNpFLQLiSmZbSJprWkl6KFtJ2m+/1bMaCR"
    "CjyUV4SsIjJ3AKkk2FYcD1UH26DObsA62oTs/mvLhjtkSo8m0ZsieMBCiXO95sERk1aHVjhtXZ1btj7v9uzfd/TI4UOl2VnXz9eI"
    "Ee2lbOfOVpSfPoXtFzuFQCGIcXiLrF0AYhIMtF7201p42fkKvLpQJIxTKiRitSom+qjBVL4CwCqBzEzBAEUNuUAK4CFtLgt4xOAV"
    "OWiv1GP2inIgi6Zot87z0x7zv4veRm9h9Qogd5IGl8NNSawyKcgEQkCOvn959aPt3//BO+96Xyc37d3jff5/s069MpHbN10L2/Am"
    "bP3bmcnHTJwNnPiBp2BEJ9ElJGKM6as8nuPpkKO+2AyZQosFgjR6Eil61V4N4+swIE5LUDZTpkhsddBiuwusGnHozoQScGEdgHL9"
    "ljgyJDBztHXB69E87I5EXUZitxW88zOQmjLCZFQSUhQux3dpgj6U4enGnk2GUoutkTiUZDJg55uyWU1n9+87WVE+fWmjgUb5qBcv"
    "eah4xMu2bIbReDzp7sGKhFS3IVE2uUyHJreRtFykewTfg9O8DZ+5Fp/HnL3uUjfqPXEM9Qq9lNB4noRNMJQMZhEITJ5bh+VO5LEr"
    "HRBDRWvq5/dqeqDbegk97b4J1qe4Ue/D27fd//D2+7be+d3vPP3tp5781t1bH9h27z13b33owTs3P/Tgbbfef989dz/x+H3Mri3b"
    "7gfkdTvtVotRP9na0qYzYORzuDx33YkKUDG2J8rQIrQYG0gr0Gr8xvsGKf+kSyuFN9AQUCRpIalhoyB6XKMFodXpdiW65R6wWc2g"
    "S78MaCFeitB1vtKWJFyP5uNylqFVz/z2Fz+EZ+Ena5f82+sf7/zje9md8OLLj5eWLS391VtwoGz+40/U1e9qXrBm6bI33nzyZw9t"
    "x+pLj4xIhwxIi0ZQH8JWIZrAbwOaxOrMivd2onE0ljyJ2tGY5/IMRCkI8dgTAgQmUyuEOISlKEAxyqcG5FCNBF2L/eJ9DX5NM5Xw"
    "uCRRKP6F6RIJDr3cNBsqEcigzrltXkp1gptC/go7XBADBuvWgrhSUbg0d9OVCnDRIRRIgopmSAqHUCiO2DAPBLEZO1AYhhx6inaR"
    "IaWl/VwXtJ/KFeFP3xtNkUTSHIZGRE/x4tD+ZNr+Y31roLm5C9m8G4iV357HmoG45DwcYsNZ6ET4QohC0BcjvqgjNJUCHLHJd1mi"
    "QrAlNMAx7GsNmonpcCg+2OLK30ejEBVg8x3x+VPYkh9UMr/fXEnyGHRggDKR4BIsEVxCRWKW3kdjQ4AmgCdFbEqVEIqA14aIJYWB"
    "Fg/sCHUcwf6Z4DIjXWkeTp8MNO104wWyuX4NwlgeyWggSWxAdL4Scy6bIWrG43jCwCIZ5HXumQpCiJNlGYU/ikMH+hVfwZxFHEpT"
    "NtawGnZuJaO5NjRCHs8cSVwD7UpwajDn+gZ1V/ZPHmpOJXlJXz5X5gy8hY1AZkH+Ty+z9nrxQbwXQQS2ub/6imQ+vVhf4S2SJHBx"
    "JMnrqVN6nbFe5i64vK4cGuLZnXdGOsCrzenKLjS8/KHgDhIs+ZG6ROryt65L6NtCLOuIqwwRIjgcgSwUYxuo7DULTFhc04gIQuaZ"
    "NPacFP4VAzqAzixTlg37V5CLbS2w02lcsXYCB06DOuGZLsTjoSifJkdXScp9lRr8KyBc8ANl8VojxM67EA7h2MkfODYo29tglXTF"
    "Xwg0u9+YRaz2ZA72XHEmPHgf04QRQfxKguiaLsTlEgrxXpfr2hZExCd9JlgOJdvQIbjiyIggi12UYF2PcBPINX2GQBARxK8kiM7p"
    "QpxOkQjvdTqvWUHkONIsv5xF73/FncF/IhFujanrOzmywhHUgHwhBKGormWIHyRAyDr1ms1YmH7IVjSjJzBXD2cWj9Ay9Qr2mWdy"
    "IANgY5968bORSMJc0H7lQXHPDOmFXk0WChTaAY3Ysv9AtiwrNhOIw/KIu9lcwQFNzurTrKwC3OgtJzcXywaaiwZHsyl3rgJnB1m5"
    "kTE28iBOvq5ArQLhJpYCJ3gx86+SVon9dP5n9HfYDDVcvc1OpxKmKa8QW/PjPvxcd4G4CrdxCZqmWbFK7n8bECtAzuQs4loYwf8X"
    "4D6ZoMgqt6qhpIUJYQeivvz/QgSsCw6wccOQ4doc15P2f15pKpqAQDq4qTdN+APG16jSQKEvRHCDmAjxA/thydVRuNBUiJAvC1o4"
    "tlvAlSIQX7kgNGO+ruD/8bBCm7N0es4/ohAvMQAignocEWqb4AfMZ71koAdGgCkCTBFgigBTBJgiwBQBpggwRYApAkwRYIoAUwSY"
    "IsAUAaYIMEWAKQJMEWCKANPfVcYQCndn4f8x+lXUJnt0v290M8EMdkf+8e+cx0iwmi1oCE6I/7POsISeDE8EfQk/HDMyVGIOQyWG"
    "pwsZHk5OxnuHh6/dMTsIhRmRM4WxgeI4KVc5SM4a0z7dHiMEGp4uMilp5k45k775Sm3CRokQk3m4GIEI3mSHEBlgAyYGy+4LkcWe"
    "nauZO5cj6IirtwLD4iV/JlTQjI6ZhAeFHN2POFnMryiqwOSBgFkVaff/H9qdZX5wUYY1mYU7so41oofrBYQAVxRsdCGEQj0JbjZz"
    "XtW4EMjDfa5PE6h1kOM1g+nHmtjHMaaCfBOeNR+oDwqb9zm8JHBEly9yLG+Y7W6xcAwFvAW2quW0AmtcFwo6lX36zOPLAtucnVxH"
    "kOPKsSc9fp0OwxHRgP3JmWjIlQuCPT+S4z5zbhPxplMFDPfAkFPiCkBx5hCyJ2Fy97AfW5ChNofRd2g2MxpxbELuteY+yC+0S8DZ"
    "YjUZYks5r3LsNPUso3CG8YCcGWWcKbC8bkYHXmzVMb0HsdzxQE+EMNYjB2ECHYUTHmCP0mRboby5fMw3GsCXANg38xQQHdGp7Gm3"
    "iB/2CWHVz/l4FEZhhwjOoOBY4kxqhTvzFoVcI07IMXCTbM3AiUPy3G6ODAYaPAgJAn4qERjBziqV63SwZ3IHOSacCeCBHVfvK4T/"
    "IczCeTTsoBS3JqGFlOAbWqEce4LvrvknOs9pIaY+SSr0olQ1NuTn6SZJSibNzsrIFFAMPcf5qr7BeIvd4ZZ2XPSgCb06QROTmBR7"
    "qVcglimHRg3m5Mtafi7xRKHLGQerChrq0yQdFzxuFcggAVQQDXF4Kw5SwOp1uzwWs5NGDjuQu3aaDuzf8VljQ/X5jz7sNOrb2wzN"
    "e3afOf3+H2tPHD9ymPrkz5Vne3uiIQa2LEjDJcVANjx4XU/3hfbA3U9OmE3Mp8nocsbGWC0k5fWolHHxObkMxQjzy4RWpSYpvU4s"
    "MZqUKpIy6ANnj4+RVFq620VSNdVeKSlzint7CgtIKjcHyIxMkmJoa8sWpAJDj0VSY2TRvFioOjc6olI2NynkUdEkSVJu4eBAWqrT"
    "wZRnt5lN8XHMXZCU0zE54d+7EJi1xz0+dh5FRylVF7vml5KUSjmhzc7yuCXiG6Gmuq9Xr7t5AZdXlxz08/QJYEQikVBDmsGYgYS+"
    "pJ6US2ldGQPpibAIksHjI2Ki3S6hqBai+3OhFuLl5BkSvNQpqPaecKfigxLxshh/poOU8JVsMihimU8zKRAMZAoE3SoJKbmULcsa"
    "UTiTHUmedFUayrvINCbZbdFk+c5Z7mOqbVooEHSsFEySkto1xtbSU0nlqe2JVYKamIq4cyt+dz76QppQToljf4OPvfjORYtG9mdB"
    "99OXBV/2f3v0152OCYW2WDfPlmJNdoolIAER/MjYn1sva42T20+3F5GeHzabejIL3il+oYLOfvf9zOU5uQupVFFGTHJ8dFectjCF"
    "pLJwhVMgCUqgrxdIh10BCeN5EAU5IJWkwU9+rIbXXpJBBi6aaXXhxfmtEya5MSq3CNdW7ZWc8pI5xVZFFRKaQGAWp83LlCTLxauk"
    "G5tKWg16t4CkartblzSoYksMvSWSkRSycrcgO1WuSzurzS+Qe8YXnS0dFYxQB6SfJZcnjiXYxHbQuax2A0ikScnyRJKaVzQybAK9"
    "zgy1NZuhWegqMerSpp/oKZQmZ57oyUKzpHy9UWSQ6uQTynH15aiRGF30vIe0MK/TDaV3V0svwSUYgotwwXWukqxnHmeXvBPvGdbK"
    "oFVfa+gAq0UsanJHScey6+l+VZf3i0SbulW4VZh6McXophWSCmHn/XaFM/aLns3C9DdSf5H1y9R30/5QuLPIm0CTTbrTp5TgiK50"
    "dsqrLzdRlV2N0BFfi9plAymj0A1jMKy+2KUaVY4oLJMTwxDoM0aD3ca8mb7EZH5MTLBZp3+T4eMQMJ+NDX29Y+OXLg7rJo0dF0Z9"
    "ZDitLYMxsXFYXGuPnfRx1TSeKu9q76yvONfWXFVz6GgnvqqvlcTV60hdHH6yYC1fZVAobWdWeqiJGP38iyXN1iZjW/E5sGnpSYgh"
    "E71ecWxfNuxKiBNYcnaWOBqLOxd3XIfk9ozewp6CuLyLtF4Gy7HyiSqEmdNbshRZccn80rIFCxddB5mQBxCriMvCAiVMaG4qAnlm"
    "i9EwqektAIimnzmdBetuCCLEDsGOPfUSSXyvRo1G05fpAWrHU5mwBeAuuA22+tZ3w7/C43A/fm/Be8wOlxNsVpPRbtDTXuSrwJ7d"
    "Yslfv9z3xed7d+28UhWPe6oyd8FvcQlvw/uwHf4v3IvLexaa4ddYK7wFjfAkfAANdB68Aa/DM3U/gB/Bu/AMvALvwc+hyv0aPA+/"
    "h3+CX+LKfgcOwnH4E+yExqh6917YL9sBH8MJa3X8H2AvdVTzn/C263Vcyu/w9d6D31M/h//Q/9r5YdrnIrGKNAsM6chBK0myvaTB"
    "E21ISLsgilO3ykFjV9nlArKGXNyd2xslJEV1UVS8pCdJan+V3h37Q3iz5SPl79p32N5VfZn8qes1xQvwfXgOfgzfa3vN+wophJds"
    "M7ewr3GZpqU7qqGECnFs15VjLzHH9mk0hjZU0LFg2dMPL696R/9Z02s/+XwrQhfMZDeufy9cAC3shzrcEc9DORyF3TAKZhgGvY9F"
    "qgb2Qv5d3q0ewRhY4Sx0gg2MMAinoQG335qN5/Iqc2sX98MkmMACh+F8VRtW2CehCVrABbTXgNHkHL6C6+WXSdKbu52W/eTHr6JX"
    "JD/94Stv/Ov3JS/Kn1c+qzZp9NG67Y47cr7xz3fCptxHyLvhEe+j9EMYe7aTD8F2+l54hO762Xa0cMEj5BZ4mHoU9eI7eYi8H557"
    "VpHZD4/Sv4Lf/HoQXsa1wL3USwIFQhAD7otaZjs5Polm7w+/jeGAwrKOe7rFjNHvagmYC5Ow3u7qTILBgSRsDWRCGdyQuwB3zhWw"
    "LC0Fr5fCWnxESscCLIFF+NdcuMH3eQN+Z8ASuGoCZnyVBPxeg89fCg77WrgFX20h/hapS6Quf/u6BNvaJMXws/m3XU4GTRMTaqqd"
    "DkTHxBaXNDXGxBYWREcd2M9Y4Sbj0VsO3nrgm+1tJOUnssOWT2pfL0nFxvR0k5REbDH728vtcrtiYlNSGUs2Ll6AS43GkCAUdVxg"
    "riTx2UJhea0bpL47DctrPUhjfcdQMMViPeajj8aeP6kCmgaTsiuTHE+ykW63ojlvQu0V1+W6BbUJjfNbS+qSamPH42kEazXgVigH"
    "MqFdGSXWZ7Wl22wp5hxTISqw5vWX9BWb1UaZUC7HloQKwJMOpqaLdtuYTA0SVG2l++UKHnt1KCrrqZeQDa8WJ3gBWwpgF7tFFu8E"
    "1rlD0Ic1o0U5MqEnq+CSvRxr9gvSKqij6uC8ezfW9ANYx++EnqTxzI9hr/S0vDLq/ESNcR8cHq4kmyQ15B5bhY2Kto9IKYXM5dK4"
    "xY2LainVpDRrkEy2mxS0VK8WyEiywT1vOIoW0ypBtVotjO6MjZn8A3zu/Ej0e/gv1zsNX6o/oyj4s73DE2uJEpvVCc66+BZ51HnB"
    "LVZbqySR1FjGUuu0l5IFwvhz6SnDJPS0pLTf2+gyZ3YqJgSFYjjoKTAmz6+OGTaUKfcm3tzdtromN0pPgwIUhld0deVHN6h+tWL9"
    "z3+qRj9CyBMRxK8niPtR2jfo/kOHr11BDMjhYJlfDDs0Qld+pVLVdbv2MppIKWjRrjvBEr8lRnPZOCOSfhHMzz5VoGxb3TmwOOro"
    "BhL8gqhayYhgOZbHDUfVWAxrUEQQv54gPoGe+T3d/9S3r11BRG5GJ+b1qUUL/jJvSieaWzRJ+qVNWCWuHpSIhVKtwuIXMORJRXVY"
    "vjYcVY35tR0JfD2JBTW5rWDS6SiR7M1XekZyYzulsskYJhpFUkx0ipGWgUEgEyANsvE+tUZvtlldjpyi0rLCgoWLZvYaaS9jeLic"
    "HrdK23EhO8+F/QA9OLyXsJ0/CVr3CG6/dsicNykfgn6XWdgAVeNNrjqq1d5InydbsW9WB41UjeuEtZauFJOovZMSSGVCURRzNXyN"
    "9NS0hDi1RiyJjolPzIilx8a1E5M6vaGlrb6ptqrmYp+8S+bvSVLfJ/dedUa3B0WbrDGxNqf/ph9+5NHHHn/iW09O20y5MST0922B"
    "E/tFIMce6F24Z2zB/udW/E0NMvjLBjm4aK8HOd96841f/+L1d972u9F1tWLJ+SpHS3PD2YrgpnkcW0KLYSV2vFfDOsjpuQkW4fbu"
    "6c7HFlYJzIMYbCGtTWfssAQohUJYgK2vwYHlqbkRW/YfxpZNS/d/jgzn5Lqc3ZcGB+Sk2qoyJSX7dXNGpkZNUsuWHz60e8vOuz+/"
    "d8c9e/ekp0nENmvRPJXy4AGHndHojH5mtDejmfPyGe3PpGGhBMze+LjhIUaTHzxAUpkZusmERAHlsEvEvgb1ZVKDsJnUOsJmUhvy"
    "n63HbjcTO7UCKZ2cwHqzP550yMnaYif0RLmUdle3Rmy0KkdS2pMrs84WdhbQIFtYCJ7za8YTyU5p0dmC5I5FE6aFzqWOJe6M0bKL"
    "13etbStpPV8HYIB4zTIJhgcB0KuByaT2lcJDq0gYW04q4u1wualj0gLjAA5wYa3SAVaXFTnENtkY9ug7odPbDAbZOWiD4YlObRuc"
    "wFWrghZno+r4UKV5P1xQ7YUvoEV5WnIILGrpJbVYTIpdEubqTe6oSXnsULzKYCPJRK1Kiu+nls5w0Y5kp1xSnWSLiRmUxk4cE30K"
    "Z0UHHNq40ZgPcMntqrN6ChjDUgwfwXvwNrwLl7OihqMzlfuLD6tzTjq2DDt7NR6pbdGZTVUDt/bohYVRO4osK1rmf+IE2w5sIPgy"
    "qWlFTModknofpExatt0iXV5VosCQ48rYKbm+V39Ly8Wt430xfZa0vP3py3etNbeuaxlZGH/45h1iLDfjUrVFKJ1uR62ZUjFN2BNl"
    "lgzk8iOr+VjQ5ksWKcfH8jF0D0KXpN1tgBFvO7TRetxwZM1H4KXq7JfMTVoJkHQDbtIWqHG7GoV2x0pxAuWYUIisUlG1Z1G62+FW"
    "nytNMsdYYy+Lu+UXlZ0Gg1Gqltla6Cby4IGmwRrUFN8qaaGN6f3yiYQ2wcfiD9QtwhbrrybbRlsEjYL/+uAvJHXvSw/86dyHt3xM"
    "gixv3eJvPfX7rj8Zfvcfz/z2WlUajIl3lZnU8sUYjBob5mOA6OxIgUQQdZXgOy3CVynCMLIhfw3eWoO3VmOoqq8rgG0LmXqU5i8u"
    "E+NfOjuW4nPWYegpg8dKUnApLc2r4KozqTkmtIvggRxuTaYXIOWKuHj/dlNjdNTIMEmlp+XlX3UmNVi3paJckZZaokOxMTKpxdzb"
    "44AvPtfDieM6+pbNNuH+faNw9IgeVBmNDTqFQTiOrjqTmnfBcol4yDMpiQBTBJgiwBQBpggwRYApAkwRYIoAUwSYIsAUAaYIMEWA"
    "KQJMEWCKAFMEmCLAFAGmv7OMDaWxlOl4BqMCJrIab2vd3Lapc8vO06HG79IorhIOwcn4CryuhV1YYX6qrYZjcAQvx+AAnMHqsx7+"
    "Cnvgi/FTsA9+9+yNOQBH0EGPNGXQpnLk5JMHhLQgpfAouf74kcP/57XDh/btXb9uJRw6uOOzd97+F+rNN/bsvu2mH1M3bnz9zT27"
    "77j9r+deoB+CDTeRXmHgZkfJsXHqMhqHMcmobEwxqhrWjEYPxw7GDycOJvenDqb3Z8RCDK52NESBBuJxheNAgUVdBfMS1WMJeIsa"
    "d+Bf1WDHHUUKtsjgsa85VKIeCcro/qbma3eoBAn8gQ7MiJzqKwNyshwZp77RnyBxsMb2ZB8SWG0dHmaImT1acEzbmhktPbXQkmJU"
    "Tw3Z2cIdsrMHzdwpQw+OOAONuNsdwB3Q3xErcAc8AZW4Ix6CHbgT7sLd8QScgmrcZb+AT8e4cu5XZlJZZwdJ9fYkJqSn6VPY95Dm"
    "e1qdWd2ZFblVS86tcEV745BZOjJPX2xaV31T1cYa6XlFlfpcfmXR3jv2WMyrKiwJi/CJDSO3k8e83zgoXyzYv+nwN/dTp4Qnth6/"
    "9+j9hx+YfHA8aix2lOmuSaMJ0LRh7U1r1q9uWFW/sm5F7fKaZdVLzy+pij8XVxmri5mUIt2khoyiY1E8raKVZDqZgb+pyEQqjUwG"
    "FU1S0ZTaW6oMOWgEFtPpKBYweEFi2gi27gY9F7s2mYcEg9APvXAnPSa8je52ToBLOYK/D3qGdN3ecfEAbY7rNsqkUiRF0aSMlqLE"
    "hM4OKR3lldXQsXaBTWKSQm5iclu0m3bn6deYVtUua1zelD+Y1ZvdsaxzcdeStuvacy/mVZSX5a3IkknjyG/e8sKxSLv/v2r3xTny"
    "IQ0sRMnOIrRaSVKlkoGC/rLu0rNFFcVnlgwt7r/x7A0HixqzGkpN840J4/Fx4yqZziPyOtKG0skBh4O0QqbdkODMcmfTSvOS8UVo"
    "lUxOG3Qd+pWo0FF2OUGSiErQxGSJZ0K3wB0tm9AmwxLlRrTOtDFbYqdsIovEJDNK9fJJpVY9FtU2v6WsaWHDdXWLa6MhRir2klTf"
    "AEYGrPspcEJza1NLQ5MXGpp6+9suVPgFRYChygtMAu9NBig/XVWZDafLP4dTsQKhACZgKy2GY0dOnaw4c7q8qaG+9uy5c2dPHmfr"
    "i+lhS8z0vCyQK+wOoyELyCHaW4gNwRJwOR12TVSW2WIuhVLQ9/ZNjF52gtVkthnGtXYHibw0VVS4BOa1FbWWNJc25jcUtc9rKWkq"
    "xfKztuL60zeeXH983YnQGmohLvH0KfHKRUA2NLVeaGiqrW9uqa6pq2mobW5sbTp7prW5reX8uYZ6RX1dawvV1nqYGc1jfeDBhzZu"
    "2IU3J0xv4LV+8sjRPwGpHxr8DTaDhgb/jTFRRlMbmz/7/LnnX7hp/efSxKQJ7dvDQF6o3pudY3a9jO+juelHvvmVBw//8YM9+34G"
    "pOXEcbznuDb0nb4qyM45XfWf2OqMgafwiSe7H/vu2H342OPH7gSy6+zhb+CdH334A3gRnoc37rhri173I3gW1h0Tiv704S9Xr9E1"
    "Nf5T8Wp4JgMyMu/L3QR3wG3w5PyXYPut34PN8ETxS/CY5q5frMyGRzavhHvk8ODNz8FW+PayRXAXfGfFaujt2bb6RXxuXnpdbWV3"
    "VsGateVnCtLbWtetxu8bG+orzy7OPXa0/ExvT0P9xhsLr9u44czpM6frao8fO3N6/U3fvHXf3jvv2rN7A5aSuzcfPrT1ltu2btnw"
    "+Y7NW/btveHGL3Zef8OmzavX3L50/84H1q1Ze/sdtXVLljbUnTrZ3Ji17cMP6huaGipaapvXXr9yVU1tfe2Chc0NrS2lZU3NZQvm"
    "Fbe2FRa1tjW1tR5YvqK1LS9/4801zYVFKanJKfOKRy/Xa0fbkpKTU8YvL0uIjYmOz0xLzY2rgQp6B4am9zEgvedu72huammrPFuH"
    "zdRPJZ/A0eXvP/7Le3fcs88e+lH8ZsDtMpssdodMKtd9CJ8kH3dUZDtK+nP7cnqyzyibUQ86gnpRK17a0RDaj7/vRgd8e47i9268"
    "ZwD1J2ws3oW3htFY3OXY0ZgRxk6MGYjuj3JgSLZGWTRmtUllVO9CjEeuQEKRhrRZsb4ziY0yvWKS1pLj1KhwWDxI95MT1JhwVDyc"
    "PCKlKVKElOlkrivvUq6EVGaMh6zD4IAd9Ez5ysuKUfmIbDjaNO6xJ4pTBA9Ys8ZyDTGTgyMmrQ6tcNq6Oju2Pu/2HNx39MjhQwez"
    "s66fr7kF0V7KduPZivLTp04aY9yOaG93kVUl6yqgQEDKDQq9bCL25ZdfeeWfX/3pzy3COKVCIlarYqJBX9x/OlMqsFED/UUu+5BL"
    "KVWBmpQLAQmsXreUzvGYHWKvljZmmSiDW+exyv/53595+8W3XvhVNNYCYreLIs3IGiuTemW0kBRRQjf5/UfkR34w+q7h9U2b7tkD"
    "zz/3v1mnTvsHYgnzGRdvMpqMdhsz+ZiJszkdlCAltbeHhEsXRULae9XHczydlCExYwaMpQ3IJZMZfYpe9fiUr9Of2JvcnX0plylT"
    "LHG4xOACKy0OM+2STsSlNVOSPKZUgzdhMkmfqOOux/SXdaOT49FjUZc1BrHUavHSGXa1xmia1CUlK5TLISXV1N/Xn5HZ3ZOSmaHR"
    "TvT0xkmSUg1GRTxls5rO7t93sqJ8+tJGA+3NL+jt6+3Lyy8uGE5gWzam+EuJPTGt0S2xbTmi7Ilc3QOT26QPyrfpHpl8TP+oedvH"
    "D+avX6vMu545e11+d0lv3zG8JXIIRKZqj+TW9OExucXhlB0TPF2PKDtyKGKU0Zqo2l5nj7RbdgldpG6i1yNwe3r7tsP9sB22Ut+F"
    "p7E2/xZstW6De/D6Qflm94OaW433wd2ux6XMtE1mEC7yup12q8Won2xtadMZMPI5XB76TndBYXFJ2YKykkULFl+3dMmKlatXrlhW"
    "sKi4cCjTN+XRZsHCRMFwllDgsAkFI9HjCdoCS6EzzZXoTvUUeAvNabr0y/FjCQtXL1xQVHjdouJ5ZaVLFl+/Zn7JiuXLlq5aibrf"
    "WPjsCz/50RL0OtqJ3nN0Vr34w8dFZagUvQUHDs5HT9D1qFm4Bi1Db1I/Q9sLB/v1RqNFZzCYtKMjQ329PV1m64TebDToJicsNqtF"
    "O9l5YXxibHxyor1lTHt5fBaWRRSC6ZBNu8YmLgyRC537M5dQITQrzawsEUTolGvcfWyKhqCaIP49heZhZBEWBdNlsEsnuFfi5I9E"
    "/N/4d8+nN+GTpIRoLxREIRKWAYPF4nGFpwOFeApTmbBpRPg2aAi8mRXQUwti1r7bmz7Uv0ZTRzPUr4Bo4C7BHEQchiYuGweXTiZA"
    "3MGhJeFx3ISWWzSTHE9zpgBznC/zuI8JE/EL9B/I1O4Km5u/msw2TLUD7U+qGMQAh1Aw8RpB00HcXGzCXxSGSg5xf+cSRBIsshgW"
    "wy+LIYpFqci6fKh75pwazCzGhItogiaCa4eCe10QuV4IWjk2jXVIkiq2ULOISwnEb2su8RiLcjuIQRn9TzDpESG0H/F1CudyZc/C"
    "NxvUiiHSUc5M/8ZhekJhSG8RCuZAC0MXF5pah9UuBGIrVDbpFovNiM35xSedDb7W7GTBnK7s8czO8Xbl0jxmdF73mWUhZvjFQzFL"
    "2DYL9DsvSRBe5tIktvyYNYGYrcDixb95vV7CS+M34UV4IZhTfNv4jQ9Hvt99e5gyfVtewPrKi0iCJHGpPP5xAIL2f0IQxXoY5mg0"
    "m8DNgYB5DmL/NyFgJsLxMUfqEqnL36YuM8EIm1c1lGXIZtoLbWNzSwhd8pyyTszGGMlOjMFhbufozTAmDcHmfg53MJfFbeqmPIii"
    "EKPJv2IqinDsuyg0jyoKa5SxTVeOhc8iPUTcLCBcPkQWyWAIJm/EzfPAMltZDcJO3EBAgE2S4PIYBlDM4z+DmsFIiQji3ATRhYRC"
    "hFyua1gQ2eIX+GQzprMS5gCXhZaVgAVxGK3dLG5h/BJEBPFrCqITiUQIOZ3XriDSCPGzMLHT2LDYk30foumH4SRQOD05vQtQSMZg"
    "ZpdMFmxfWKdec3UJrRaW18BPtUPw6Fr5aTRYIbGZL2eZegX7zGEtJY7c26de/DpIJKFLYI70X4h7ZkgvdBZba5bUXChiy/7j2bI8"
    "fR1CHNnRA14QJUQLhaKg5uv3r5UUhxuBY5PME9wwGy/uxFZjbLwLjuDxc4ldfZAIsdnQ2QoyKAoWHJ9BvOgCCsfQHTqVGidkGiZx"
    "GFen8EpGXNVOsNJV8VLc+DKM8WLo05cFHtU9iwCbkweImGNklWMecIMvUyXRbIJ+dpCRG2dEBMF/FgTnJBQcv/IFUaewzX8zNBOO"
    "Bvad+VOp8WKC15LSCPPvoNkzqSFOWrNZ4WO2PVedSQ0hRMy5hnNLnxgik1qQGcuST17eAA7r+9VlUgvk5IgAUwSYIsAUAaYIMEWA"
    "KQJMEWCKAFMEmCLAFAGmCDBFgCkCTBFgigBTBJgiwBQBpr+njIUaRjxLgmMUZhA1EX4/+IZ409NKCnw9mgCa+WMJM+cuuLojON8n"
    "ItAMF/ZfNvyC/Gu/IpleR4ZKfL2hEsMoORmh4eFrefAYCjUih4WxBA/6ESdlNxE814BAI9whO0lo5k4ZrgmvaplVCaNQgwn4Zcw0"
    "pYJdHpr1Bgk0SzU4zcbXXbPBG2vkO9swYeWj5efh5eWHJji5yAl+amw0t7aeeVRgpN3/5u2OWJ7LnJomkBg6eFZMQCWwZyWwE0az"
    "2mC2+QysQVcspwXxDBWCc++IZU4T7ITSodBiRjuCgykEa0RsiAzyc2q6WZB0DpMQuZYWYpleQXm82Ro2MMiXYA3uYp3KPX0GOOKU"
    "dwVB+am8Cb53NJcRZXMdrM61E7i2QzhbgG9aci0M/pn8KZyhr8w9e6byQhj8QQ42f+4ZL9E8ETpCQQQyoHNGXc81ZjFbbnOWxkB8"
    "KxeFMzl4ieZRuCqEnAhIEMGKD3u5gZfvEPD9Av493Ez1rDhMCFRH7NlgnHlrBHfiV2CuFx9IuEEpxhNnJqCC7x6xDU9HdGqwoPJt"
    "/nB6ZpbjUTCKEvy4SYh5vcQMth3BnYqGwtrOiA3RKPDJEawQccig1uEr6XBOJMFFdf5cZRR4diwLmi0TXO3DnkyIQvY+fgAreFjw"
    "nFGUq2YRN0h2FdDIhLfYNWCHLrnPYXqi89W9/htQCR9P"
)
