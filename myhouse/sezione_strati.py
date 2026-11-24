# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._scroll import fit_dialog
from ._lingua import tr
from ._imperial import LengthSpin

import copy
import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QMatrix4x4, QVector3D
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from . import muri

EPS = 1e-9


def clip_chord(p0, p1, quad):
    area = 0.0
    for i in range(4):
        a, b = quad[i], quad[(i + 1) % 4]
        area += a[0] * b[1] - b[0] * a[1]
    sgn = 1.0 if area >= 0 else -1.0
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    tmin, tmax = 0.0, 1.0
    for i in range(4):
        a, b = quad[i], quad[(i + 1) % 4]
        nx, ny = -(b[1] - a[1]) * sgn, (b[0] - a[0]) * sgn
        num = nx * (p0[0] - a[0]) + ny * (p0[1] - a[1])
        den = nx * dx + ny * dy
        if abs(den) < EPS:
            if num < 0:
                return None
            continue
        tb = -num / den
        if den > 0:
            tmin = max(tmin, tb)
        else:
            tmax = min(tmax, tb)
    if tmax - tmin < 1e-6:
        return None
    return tmin, tmax


def layer_cuts(p0, p1, tmin, tmax, aL, bL, aR, bR, fracs):
    def unit_normal(a, b, toward):
        ex, ey = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(ex, ey) or 1.0
        nx, ny = -ey / ln, ex / ln
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        if nx * (toward[0] - mx) + ny * (toward[1] - my) < 0:
            nx, ny = -nx, -ny
        return nx, ny

    midL = ((aL[0] + bL[0]) / 2, (aL[1] + bL[1]) / 2)
    midR = ((aR[0] + bR[0]) / 2, (aR[1] + bR[1]) / 2)
    nL = unit_normal(aL, bL, midR)
    nR = unit_normal(aR, bR, midL)

    def dist(P, n, o):
        return n[0] * (P[0] - o[0]) + n[1] * (P[1] - o[1])

    def pt(t):
        return (p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t)

    out = []
    P1, P2 = pt(tmin), pt(tmax)
    dl1, dr1 = dist(P1, nL, aL), dist(P1, nR, aR)
    dl2, dr2 = dist(P2, nL, aL), dist(P2, nR, aR)
    for f in fracs:
        g1 = dl1 * (1 - f) - f * dr1
        g2 = dl2 * (1 - f) - f * dr2
        if abs(g1 - g2) < EPS:
            out.append(tmin)
            continue
        k = g1 / (g1 - g2)
        out.append(tmin + (tmax - tmin) * min(max(k, 0.0), 1.0))
    return sorted(out), dl2 < dl1


def opening_ranges(p0, p1, tmin, tmax, a, u, openings):
    sp0 = (p0[0] - a[0]) * u[0] + (p0[1] - a[1]) * u[1]
    ds = (p1[0] - p0[0]) * u[0] + (p1[1] - p0[1]) * u[1]
    out = []
    for o in openings or ():
        s0, s1, zb, zt = float(o[0]), float(o[1]), float(o[2]), float(o[3])
        if abs(ds) < EPS:
            if s0 <= sp0 <= s1:
                out.append((tmin, tmax, zb, zt))
            continue
        ta, tb = sorted(((s0 - sp0) / ds, (s1 - sp0) / ds))
        ta, tb = max(ta, tmin), min(tb, tmax)
        if tb - ta > 1e-6:
            out.append((ta, tb, zb, zt))
    return out


def section_rects(tmin, tmax, cuts, holes, h, rev=False):
    bps = {tmin, tmax}
    bps.update(c for c in cuts if tmin < c < tmax)
    for t0, t1, _zb, _zt in holes:
        bps.update((t0, t1))
    ts = sorted(bps)
    rects = []
    for i in range(len(ts) - 1):
        a, b = ts[i], ts[i + 1]
        if b - a < 1e-6:
            continue
        tm = (a + b) / 2
        layer = sum(1 for c in cuts if c < tm)
        if rev:
            layer = len(cuts) - layer
        free = [(0.0, h)]
        for t0, t1, zb, zt in holes:
            if t0 - 1e-9 <= tm <= t1 + 1e-9:
                nxt = []
                for f0, f1 in free:
                    if zt <= f0 or zb >= f1:
                        nxt.append((f0, f1))
                        continue
                    if zb > f0:
                        nxt.append((f0, zb))
                    if zt < f1:
                        nxt.append((zt, f1))
                free = nxt
        for f0, f1 in free:
            if f1 - f0 > 1e-6:
                rects.append((a, b, f0, f1, layer))
    return rects


def _family(u0, u1, z0, z1, ang, step):
    segs = []
    th = math.radians(ang)
    dx, dz = math.cos(th), math.sin(th)
    nx, nz = -dz, dx
    cs = [nx * u + nz * z for u in (u0, u1) for z in (z0, z1)]
    k = math.ceil(min(cs) / step)
    while k * step <= max(cs) + 1e-12:
        c = k * step
        k += 1
        lo, hi = -1e9, 1e9
        ok = True
        for p0, d, a, b in ((nx * c, dx, u0, u1), (nz * c, dz, z0, z1)):
            if abs(d) < 1e-12:
                if p0 < a - 1e-9 or p0 > b + 1e-9:
                    ok = False
                    break
                continue
            s1, s2 = (a - p0) / d, (b - p0) / d
            if s1 > s2:
                s1, s2 = s2, s1
            lo, hi = max(lo, s1), min(hi, s2)
        if not ok or hi - lo < 1e-6:
            continue
        segs.append(((nx * c + dx * lo, nz * c + dz * lo),
                     (nx * c + dx * hi, nz * c + dz * hi)))
    return segs


PAT_M = 0.25
MIN_DASH = 0.006
MAX_SEGS = 60000

_SAND = (0, -0.24, 0, -0.24, 0, -0.48, 0, -0.24, 0, -0.16, 0, -0.4)
_SAND_D = (0, -0.12, 0, -0.12, 0, -0.24, 0, -0.12, 0, -0.08, 0, -0.2)

PATTERNS = {
    "earth": [
        (0, 0, 0, 0.25, 0.25, (0.25, -0.25)),
        (0, 0, 0.09375, 0.25, 0.25, (0.25, -0.25)),
        (0, 0, 0.1875, 0.25, 0.25, (0.25, -0.25)),
        (90, 0.03125, 0.21875, 0.25, 0.25, (0.25, -0.25)),
        (90, 0.125, 0.21875, 0.25, 0.25, (0.25, -0.25)),
        (90, 0.21875, 0.21875, 0.25, 0.25, (0.25, -0.25))],
    "sand": [
        (0, 0, 0, 0.32, 0.08, _SAND),
        (120, 0.12, 0.04, 0.32, 0.08, _SAND),
        (240, 0.16, 0.2, 0.32, 0.08, _SAND)],
    "sand_dense": [
        (0, 0, 0, 0.16, 0.04, _SAND_D),
        (120, 0.06, 0.02, 0.16, 0.04, _SAND_D),
        (240, 0.08, 0.1, 0.16, 0.04, _SAND_D)],
    "steel": [
        (45, 0, 0, 0, 0.14, ()),
        (45, 0, 0.15, 0, 0.14, ())],
    "plaster": [
        (0, 0, 0, 0.2, 0.1, (0.5, -0.2))],
    "concrete": [
        (50, 0, 0, 0.16519, -0.2359158, (0.03, -0.33)),
        (355, 0, 0, -0.08151248, 0.2948947, (0.024, -0.264)),
        (100.4514, 0.02390867, -0.002091736, 0.2292235, -0.2775907,
         (0.02549608, -0.2804568)),
        (46.1842, 0, 0.08, 0.247785, -0.3538737, (0.045, -0.495)),
        (96.6356, 0.0355747, 0.07448268, 0.3438352, -0.416386,
         (0.03824412, -0.4206852)),
        (351.1842, 0, 0.08, 0.3097313, 0.4423421, (0.036, -0.396)),
        (21, 0.04, 0.06, 0.16519, -0.2359158, (0.03, -0.33)),
        (326, 0.04, 0.06, -0.08151248, 0.2948947, (0.024, -0.264)),
        (71.4514, 0.05989689, 0.04657936, 0.2292235, -0.2775907,
         (0.02549608, -0.2804568)),
        (37.5, 0, 0, 0.08492, 0.10268, (0, -0.2608, 0, -0.268, 0, -0.265)),
        (7.5, 0, 0, 0.12492, 0.14268, (0, -0.1528, 0, -0.2548, 0, -0.101)),
        (-32.5, -0.0892, 0, 0.184936, 0.10712,
         (0, -0.1, 0, -0.312, 0, -0.414)),
        (-42.5, -0.1292, 0, 0.144936, 0.18712,
         (0, -0.13, 0, -0.2072, 0, -0.294))],
}


def _pat_family(u0, u1, z0, z1, fam, f):
    ang, ox, oy, shift, off, pat = fam
    th = math.radians(ang)
    d = (math.cos(th), math.sin(th))
    n = (-d[1], d[0])
    ox, oy, shift, off = ox * f, oy * f, shift * f, off * f
    pat = [p * f for p in pat]
    if abs(off) < 1e-9:
        return []
    cs = [n[0] * (u - ox) + n[1] * (z - oy) for u in (u0, u1) for z in (z0, z1)]
    aoff = abs(off)
    sg = 1 if off > 0 else -1
    period = sum(abs(p) for p in pat)
    segs = []
    for j in range(math.floor(min(cs) / aoff), math.ceil(max(cs) / aoff) + 1):
        k = sg * j
        c = k * off
        tb = k * shift
        lo, hi = -1e9, 1e9
        ok = True
        for p0, dd, a, b in ((ox + c * n[0], d[0], u0, u1),
                             (oy + c * n[1], d[1], z0, z1)):
            if abs(dd) < 1e-12:
                if p0 < a - 1e-9 or p0 > b + 1e-9:
                    ok = False
                    break
                continue
            s1, s2 = (a - p0) / dd, (b - p0) / dd
            if s1 > s2:
                s1, s2 = s2, s1
            lo, hi = max(lo, s1), min(hi, s2)
        if not ok or hi - lo < 1e-6:
            continue
        spans = []
        if period < 1e-9:
            spans.append((lo, hi))
        else:
            pos = tb + math.floor((lo - tb) / period) * period
            while pos < hi:
                for e in pat:
                    if e >= 0:
                        a_, b_ = pos, pos + e
                        if e < MIN_DASH:
                            mid = (a_ + b_) / 2
                            a_, b_ = mid - MIN_DASH / 2, mid + MIN_DASH / 2
                        a_, b_ = max(a_, lo), min(b_, hi)
                        if b_ - a_ > 1e-6:
                            spans.append((a_, b_))
                        pos += e
                    else:
                        pos -= e
        for a_, b_ in spans:
            segs.append(((ox + c * n[0] + d[0] * a_, oy + c * n[1] + d[1] * a_),
                         (ox + c * n[0] + d[0] * b_, oy + c * n[1] + d[1] * b_)))
        if len(segs) > MAX_SEGS:
            break
    return segs


INS_PX = 26.6667
INS_PY = 80.0
INS_MM = 0.002
INS_MAX = 12000
INS_TILE = [
    [(0, 66.667), (1.146, 71.402), (4.167, 75.69), (8.437, 78.801), (13.333, 80), (18.229, 78.801), (22.5, 75.69), (25.521, 71.402), (26.667, 66.667)],
    [(13.333, 13.333), (14.479, 8.598), (17.5, 4.31), (21.771, 1.199), (26.667, 0), (31.562, 1.199), (35.833, 4.31), (38.854, 8.598), (40, 13.333)],
    [(26.667, 66.667), (25.679, 57.626), (23.21, 48.767), (20, 40), (16.79, 31.233), (14.321, 22.374), (13.333, 13.333)],
    [(13.333, 13.333), (12.346, 22.374), (9.877, 31.233), (6.667, 40), (3.457, 48.767), (0.988, 57.626), (0, 66.667)]]

ALL_KINDS = frozenset(PATTERNS) | {"insulation", "hollow"}


def _clip_seg(p, q, u0, u1, z0, z1):
    dx, dz = q[0] - p[0], q[1] - p[1]
    t0, t1 = 0.0, 1.0
    for pp, qq in ((-dx, p[0] - u0), (dx, u1 - p[0]),
                   (-dz, p[1] - z0), (dz, z1 - p[1])):
        if abs(pp) < 1e-12:
            if qq < 0:
                return None
            continue
        r = qq / pp
        if pp < 0:
            if r > t1:
                return None
            t0 = max(t0, r)
        else:
            if r < t0:
                return None
            t1 = min(t1, r)
    if t1 - t0 < 1e-6:
        return None
    return ((p[0] + dx * t0, p[1] + dz * t0), (p[0] + dx * t1, p[1] + dz * t1))


def _insulation(u0, u1, z0, z1, f, ang):
    th = math.radians(ang)
    c, s = math.cos(th), math.sin(th)
    nseg = sum(len(p) - 1 for p in INS_TILE)
    ntile = (u1 - u0) * (z1 - z0) / (INS_PX * INS_PY * f * f)
    if ntile * nseg > INS_MAX:
        f *= math.sqrt(ntile * nseg / INS_MAX)
    px, py = INS_PX * f, INS_PY * f
    pts = [(c * u + s * z, -s * u + c * z) for u in (u0, u1) for z in (z0, z1)]
    xa, xb = min(p[0] for p in pts), max(p[0] for p in pts)
    ya, yb = min(p[1] for p in pts), max(p[1] for p in pts)
    segs = []
    for j in range(math.floor(ya / py) - 1, math.ceil(yb / py) + 1):
        for i in range(math.floor(xa / px) - 2, math.ceil(xb / px) + 1):
            ox, oy = i * px, j * py
            for poly in INS_TILE:
                prev = None
                for x, y in poly:
                    a, b = ox + x * f, oy + y * f
                    cur = (c * a - s * b, s * a + c * b)
                    if prev is not None:
                        sg = _clip_seg(prev, cur, u0, u1, z0, z1)
                        if sg:
                            segs.append(sg)
                    prev = cur
        if len(segs) > MAX_SEGS:
            break
    return segs


HOLLOW_W = 0.12
HOLLOW_H = 0.19
HOLLOW_T = 0.012
HOLLOW_NX, HOLLOW_NY = 2, 3


def _hollow(u0, u1, z0, z1, f, u_ref):
    W, H, T = HOLLOW_W * f, HOLLOW_H * f, HOLLOW_T * f
    hw = (W - (HOLLOW_NX + 1) * T) / HOLLOW_NX
    hh = (H - (HOLLOW_NY + 1) * T) / HOLLOW_NY
    if hw <= 0 or hh <= 0 or W < 1e-4 or H < 1e-4:
        return []
    segs = []

    def rect(a, b, c, d):
        pts = [(a, b), (c, b), (c, d), (a, d)]
        for k in range(4):
            sg = _clip_seg(pts[k], pts[(k + 1) % 4], u0, u1, z0, z1)
            if sg:
                segs.append(sg)
    for i in range(math.floor((u0 - u_ref) / W), math.ceil((u1 - u_ref) / W)):
        for j in range(math.floor(z0 / H), math.ceil(z1 / H)):
            ox, oz = u_ref + i * W, j * H
            rect(ox, oz, ox + W, oz + H)
            for a in range(HOLLOW_NX):
                for b in range(HOLLOW_NY):
                    x = ox + T + a * (hw + T)
                    z = oz + T + b * (hh + T)
                    rect(x, z, x + hw, z + hh)
            if len(segs) > MAX_SEGS:
                return segs
    return segs


def hatch_segments(u0, u1, z0, z1, kind, step=0.06, ang=45.0, u_ref=0.0,
                   ang2=None):
    legacy = {"diag": ("lines", 45.0), "diag2": ("lines", 135.0),
              "horiz": ("lines", 0.0), "vert": ("lines", 90.0)}
    if kind in legacy:
        kind, ang = legacy[kind]
    if kind == "hollow":
        return _hollow(u0, u1, z0, z1, step / 0.06, u_ref)
    if kind == "insulation":
        f = INS_MM * step / 0.06
        du = u_ref
        return [((a[0] + du, a[1]), (b[0] + du, b[1]))
                for a, b in _insulation(u0 - du, u1 - du, z0, z1, f, ang)]
    if kind in PATTERNS:
        f = PAT_M * step / 0.06
        out = []
        for fam in PATTERNS[kind]:
            out += _pat_family(u0, u1, z0, z1, fam, f)
            if len(out) > MAX_SEGS:
                break
        return out
    if kind == "lines":
        return _family(u0, u1, z0, z1, ang, step)
    if kind == "cross":
        a2 = ang + 90.0 if ang2 is None else float(ang2)
        segs = (_family(u0 - u_ref, u1 - u_ref, z0, z1, ang, step)
                + _family(u0 - u_ref, u1 - u_ref, z0, z1, a2, step))
        return [((p[0] + u_ref, p[1]), (q[0] + u_ref, q[1])) for p, q in segs]
    return []


def _snap_points(segs, tol=2e-5):
    pts, grid, edges = [], {}, []

    def pid(p):
        kx, kz = int(math.floor(p[0] / tol)), int(math.floor(p[1] / tol))
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                for i in grid.get((kx + dx, kz + dz), ()):
                    q = pts[i]
                    if abs(q[0] - p[0]) <= tol and abs(q[1] - p[1]) <= tol:
                        return i
        pts.append(p)
        grid.setdefault((kx, kz), []).append(len(pts) - 1)
        return len(pts) - 1
    for a, b in segs:
        i, j = pid(a), pid(b)
        if i != j:
            edges.append((i, j))
    return pts, edges


def poly_area(poly):
    a = 0.0
    n = len(poly)
    for i in range(n):
        p, q = poly[i], poly[(i + 1) % n]
        a += p[0] * q[1] - q[0] * p[1]
    return a / 2.0


def simplify_loop(loop, tol=1e-9):
    pts = list(loop)
    changed = True
    while changed and len(pts) >= 3:
        changed = False
        n = len(pts)
        for i in range(n):
            a, b, c = pts[i - 1], pts[i], pts[(i + 1) % n]
            ux, uz = b[0] - a[0], b[1] - a[1]
            vx, vz = c[0] - b[0], c[1] - b[1]
            lu, lv = math.hypot(ux, uz), math.hypot(vx, vz)
            if lu < 1e-7 or lv < 1e-7 or \
                    abs(ux * vz - uz * vx) <= tol + 1e-7 * lu * lv:
                del pts[i]
                changed = True
                break
    return pts


def slice_triangles(tris, p0, p1):
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    L = math.hypot(dx, dy)
    if L < 1e-9:
        return []
    ux, uy = dx / L, dy / L
    nx, ny = -uy, ux
    segs = []
    for tri in tris:
        s, d = [], []
        for (x, y, _z) in tri:
            rx, ry = x - p0[0], y - p0[1]
            d.append(rx * nx + ry * ny)
            s.append(rx * ux + ry * uy)
        pos = [v >= 0.0 for v in d]
        if all(pos) or not any(pos):
            continue
        pts = []
        for i in range(3):
            j = (i + 1) % 3
            if pos[i] != pos[j]:
                k = d[i] / (d[i] - d[j])
                pts.append((s[i] + (s[j] - s[i]) * k,
                            tri[i][2] + (tri[j][2] - tri[i][2]) * k))
        if len(pts) == 2:
            segs.append((pts[0], pts[1]))
    return _close_loops(segs)


def slice_triangles_h(tris, zc):
    segs = []
    for tri in tris:
        d = [p[2] - zc for p in tri]
        pos = [v >= 0.0 for v in d]
        if all(pos) or not any(pos):
            continue
        pts = []
        for i in range(3):
            j = (i + 1) % 3
            if pos[i] != pos[j]:
                k = d[i] / (d[i] - d[j])
                pts.append((tri[i][0] + (tri[j][0] - tri[i][0]) * k,
                            tri[i][1] + (tri[j][1] - tri[i][1]) * k))
        if len(pts) == 2:
            segs.append((pts[0], pts[1]))
    return _close_loops(segs)


def _close_loops(segs):
    pts, edges = _snap_points(segs)
    adj = {}
    for k, (i, j) in enumerate(edges):
        adj.setdefault(i, []).append(k)
        adj.setdefault(j, []).append(k)
    used = [False] * len(edges)
    loops = []
    for k0 in range(len(edges)):
        if used[k0]:
            continue
        used[k0] = True
        start, cur = edges[k0]
        loop = [start]
        ok = False
        guard = 0
        while guard < 100000:
            guard += 1
            loop.append(cur)
            if cur == start:
                ok = True
                break
            nxt = None
            for k in adj.get(cur, ()):
                if not used[k]:
                    nxt = k
                    break
            if nxt is None:
                break
            used[nxt] = True
            a, b = edges[nxt]
            cur = b if a == cur else a
        if ok:
            poly = simplify_loop([pts[i] for i in loop[:-1]])
            if len(poly) >= 3 and abs(poly_area(poly)) > 1e-7:
                loops.append(poly)
    return loops


def layer_normal(loop):
    best = None
    n = len(loop)
    for i in range(n):
        a, b = loop[i], loop[(i + 1) % n]
        ln = math.hypot(b[0] - a[0], b[1] - a[1])
        if best is None or ln > best[0]:
            best = (ln, a, b)
    ln, a, b = best
    tx, tz = (b[0] - a[0]) / ln, (b[1] - a[1]) / ln
    ns, nz = -tz, tx
    if nz > 1e-6 or (abs(nz) <= 1e-6 and ns < 0):
        ns, nz = -ns, -nz
    return ns, nz


def to_frame(p, nrm):
    ns, nz = nrm
    return (p[0] * ns + p[1] * nz, -p[0] * nz + p[1] * ns)


def from_frame(p, nrm):
    ns, nz = nrm
    return (p[0] * ns - p[1] * nz, p[0] * nz + p[1] * ns)


def clip_halfplane(poly, a, b, c):
    out = []
    n = len(poly)
    for i in range(n):
        p, q = poly[i], poly[(i + 1) % n]
        fp = a * p[0] + b * p[1] - c
        fq = a * q[0] + b * q[1] - c
        if fp >= 0:
            out.append(p)
        if (fp >= 0) != (fq >= 0):
            k = fp / (fp - fq)
            out.append((p[0] + (q[0] - p[0]) * k, p[1] + (q[1] - p[1]) * k))
    return simplify_loop(out) if len(out) >= 3 else []


def point_in_poly(poly, x, y):
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and \
                x < (xj - xi) * (y - yi) / (yj - yi + 1e-300) + xi:
            inside = not inside
        j = i
    return inside


def clip_segments_to_poly(segs, poly):
    out = []
    n = len(poly)
    for p, q in segs:
        dx, dz = q[0] - p[0], q[1] - p[1]
        ts = [0.0, 1.0]
        for i in range(n):
            a, b = poly[i], poly[(i + 1) % n]
            ex, ez = b[0] - a[0], b[1] - a[1]
            det = dx * ez - dz * ex
            if abs(det) < 1e-12:
                continue
            t = ((a[0] - p[0]) * ez - (a[1] - p[1]) * ex) / det
            s = ((a[0] - p[0]) * dz - (a[1] - p[1]) * dx) / det
            if -1e-9 <= s <= 1 + 1e-9 and 0 < t < 1:
                ts.append(t)
        ts.sort()
        for k in range(len(ts) - 1):
            t0, t1 = ts[k], ts[k + 1]
            if t1 - t0 < 1e-7:
                continue
            tm = (t0 + t1) / 2
            if point_in_poly(poly, p[0] + dx * tm, p[1] + dz * tm):
                out.append(((p[0] + dx * t0, p[1] + dz * t0),
                            (p[0] + dx * t1, p[1] + dz * t1)))
    return out


ORDER = 12
LAYER = "Sezioni"
SEC_KEY = "myhouse_sezione_strati"
OBJ_KEY = "myhouse_sezione_obj"
LAYERED_KEYS = ("myhouse_solaio", "myhouse_tetto")
HATCH_STEP = 0.06
HATCH_W = 0.0010
OFF_FILL = 0.003
OFF_HATCH = 0.001
SIDES = (1, -1)
HATCH_COLOR = (0.0, 0.0, 0.0)

RETINI = [("solid", tr("Pieno (solo colore)")),
          ("lines", tr("Linee (con angolo)")),
          ("cross", tr("Incrociato (con angolo)")),
          ("earth", tr("Terra")),
          ("sand", tr("Sabbia")),
          ("sand_dense", tr("Sabbia fitta")),
          ("plaster", tr("Gesso")),
          ("concrete", tr("Calcestruzzo")),
          ("steel", tr("Acciaio")),
          ("insulation", tr("Isolante ondulato (con angolo)")),
          ("hollow", tr("Laterizio forato"))]
_LEGACY = {"diag": ("lines", 45.0), "diag2": ("lines", 135.0),
           "horiz": ("lines", 0.0), "vert": ("lines", 90.0)}

DEFAULT = [{"nome": tr("Strato 1"), "sp": 1.0, "retino": "lines", "ang": 45.0,
            "col": [0.93, 0.93, 0.93]}]

_INT = [0.97, 0.94, 0.86]
_LAT = [0.90, 0.60, 0.48]
_ISO = [0.99, 0.93, 0.55]
_CLS = [0.75, 0.75, 0.78]


def _preset(nome, tot, strati):
    assert abs(sum(s[1] for s in strati) - tot) < 1e-9, (nome, tot)
    return (tr(nome) + " " + str(tot) + " cm",
            [{"nome": tr(n), "sp": round(sp / 100.0, 4), "retino": r,
              "ang": float(a), "col": c} for n, sp, r, a, c in strati])


PRESETS = dict([
    _preset("Muro in laterizio", 10, [
        ("Intonaco", 1.0, "solid", 45, _INT),
        ("Laterizio", 8.0, "lines", 45, _LAT),
        ("Intonaco", 1.0, "solid", 45, _INT)]),
    _preset("Muro in laterizio", 15, [
        ("Intonaco", 1.5, "solid", 45, _INT),
        ("Laterizio", 12.0, "lines", 45, _LAT),
        ("Intonaco", 1.5, "solid", 45, _INT)]),
    _preset("Muro in laterizio", 30, [
        ("Intonaco", 1.5, "solid", 45, _INT),
        ("Laterizio", 27.0, "lines", 45, _LAT),
        ("Intonaco", 1.5, "solid", 45, _INT)]),
    _preset("Muro a cappotto", 10, [
        ("Intonaco", 1.0, "solid", 45, _INT),
        ("Laterizio", 5.0, "lines", 45, _LAT),
        ("Isolante", 3.0, "cross", 45, _ISO),
        ("Intonaco", 1.0, "solid", 45, _INT)]),
    _preset("Muro a cappotto", 15, [
        ("Intonaco", 1.5, "solid", 45, _INT),
        ("Laterizio", 8.0, "lines", 45, _LAT),
        ("Isolante", 4.0, "cross", 45, _ISO),
        ("Intonaco", 1.5, "solid", 45, _INT)]),
    _preset("Muro a cappotto", 30, [
        ("Intonaco", 1.5, "solid", 45, _INT),
        ("Laterizio", 18.0, "lines", 45, _LAT),
        ("Isolante", 9.0, "cross", 45, _ISO),
        ("Intonaco", 1.5, "solid", 45, _INT)]),
    _preset("Muro in calcestruzzo", 10, [
        ("Intonaco", 1.0, "solid", 45, _INT),
        ("Calcestruzzo", 8.0, "lines", 135, _CLS),
        ("Intonaco", 1.0, "solid", 45, _INT)]),
    _preset("Muro in calcestruzzo", 15, [
        ("Intonaco", 1.5, "solid", 45, _INT),
        ("Calcestruzzo", 12.0, "lines", 135, _CLS),
        ("Intonaco", 1.5, "solid", 45, _INT)]),
    _preset("Muro in calcestruzzo", 30, [
        ("Intonaco", 1.5, "solid", 45, _INT),
        ("Calcestruzzo", 27.0, "lines", 135, _CLS),
        ("Intonaco", 1.5, "solid", 45, _INT)]),
])


_PAV = [0.80, 0.78, 0.74]
_MAS = [0.82, 0.80, 0.70]
_BAR = [0.25, 0.25, 0.28]
_SOL = [0.70, 0.70, 0.72]


def _solaio(nome, strati):
    return (tr(nome),
            [{"nome": tr(n), "sp": round(sp / 100.0, 4), "retino": r,
              "ang": float(a), "col": c} for n, sp, r, a, c in strati])


SOLAI_PRESETS = dict([
    _solaio("Solaio interpiano (tra appartamenti)", [
        ("Pavimentazione e colla", 2.0, "solid", 45, _PAV),
        ("Massetto di finitura porta-impianti", 5.0, "sand_dense", 45, _MAS),
        ("Materassino anticalpestio", 0.5, "insulation", 0, [0.99, 0.93, 0.55]),
        ("Massetto alleggerito di sottofondo", 6.0, "sand", 45, _MAS),
        ("Soletta collaborante in c.a.", 4.0, "concrete", 45, _SOL),
        ("Travetti e pignatte in laterizio", 20.0, "hollow", 0, [0.90, 0.60, 0.48]),
        ("Intonaco al soffitto", 1.5, "solid", 45, _INT)]),
    _solaio("Solaio su cantina / garage / porticato", [
        ("Pavimentazione e colla", 2.0, "solid", 45, _PAV),
        ("Massetto di posa", 5.0, "sand_dense", 45, _MAS),
        ("Pannello isolante (XPS / PIR)", 10.0, "insulation", 0, [0.99, 0.93, 0.55]),
        ("Barriera al vapore", 0.2, "solid", 45, _BAR),
        ("Massetto alleggerito per impianti", 6.0, "sand", 45, _MAS),
        ("Soletta in c.a. + travetti e pignatte", 24.0, "concrete", 45, _SOL),
        ("Intonaco protettivo", 1.5, "solid", 45, _INT)]),
    _solaio("Solaio di copertura piana (terrazza)", [
        ("Pavimentazione per esterni", 2.0, "solid", 45, _PAV),
        ("Massetto di posa", 3.0, "sand_dense", 45, _MAS),
        ("Doppia guaina impermeabilizzante", 0.8, "solid", 45, _BAR),
        ("Pannello isolante (PUR / lana di roccia)", 12.0, "insulation", 0, [0.99, 0.93, 0.55]),
        ("Barriera al vapore", 0.2, "solid", 45, _BAR),
        ("Massetto delle pendenze", 5.0, "sand", 45, _MAS),
        ("Soletta in c.a. + travetti e pignatte", 24.0, "concrete", 45, _SOL),
        ("Intonaco civile interno", 1.5, "solid", 45, _INT)]),
])


def norm_strato(s):
    s = dict(s)
    k = s.get("retino", "solid")
    if k in _LEGACY:
        s["retino"], s["ang"] = _LEGACY[k][0], _LEGACY[k][1]
    elif k not in ("solid", "lines", "cross") and k not in ALL_KINDS:
        s["retino"] = "solid"
    s["ang"] = float(s.get("ang", 45.0))
    s["scala"] = max(0.05, float(s.get("scala", 1.0)))
    s["rip"] = int(s.get("rip", 0) or 0)
    return s


def presets_as_layers(presets):
    out = {}
    for nome, strati in presets.items():
        rows = []
        for st in strati:
            st = norm_strato(st)
            kind = st.get("retino", "solid")
            hatch = None
            if kind != "solid":
                hatch = {"mode": kind, "color": None, "angle": st["ang"],
                         "angle2": st["ang"] + 90.0,
                         "step": 0.03 if kind in ("lines", "cross") else 0.06}
            rows.append({"t": float(st["sp"]), "name": st.get("nome", ""),
                         "col": list(st["col"]) if st.get("col") else None,
                         "tex": None, "hatch": hatch})
        out[nome] = rows
    return out


def fit_scala(kind, th, ang, n):
    n = max(1, int(n))
    a = math.radians(ang)
    if kind == "hollow":
        return th / (n * HOLLOW_W)
    if kind == "insulation":
        per = (INS_PY if abs(math.sin(a)) >= 0.7071 else INS_PX) * INS_MM
        return th / (n * per)
    sp = [1.0 / abs(f(a)) for f in (math.sin, math.cos) if abs(f(a)) > 1e-6]
    return th / (n * min(sp) * HATCH_STEP)


def _from_hatch(sp, col, h, nome):
    from ._strati import normalize_hatch
    hh = normalize_hatch(h)
    base = list(col or (0.93, 0.93, 0.93))
    st = {"nome": nome or "", "sp": max(float(sp), 1e-6), "retino": "solid",
          "ang": 45.0, "col": base}
    if hh:
        if hh["mode"] == "fill":
            st["col"] = list(hh["color"] or base)
        else:
            st.update(retino=hh["mode"], ang=float(hh["angle"]),
                      ang2=float(hh["angle2"]), hcol=list(hh["color"]),
                      scala=max(0.05, float(hh["step"]) / HATCH_STEP))
    return norm_strato(st)


def _wall_layers(d):
    if d.get("layers") and d.get("_hide_lay"):
        return [_from_hatch(d.get("th", 0.3), None, None, "")]
    if d.get("layers"):
        return [_from_hatch(l["t"], l.get("col"), l.get("hatch"), l.get("name"))
                for l in d["layers"]]
    if d.get("hatch") and not d.get("strati"):
        return [_from_hatch(d.get("th", 0.3), None, d["hatch"], "")]
    return None


def get_strati(d):
    own = _wall_layers(d)
    if own:
        return own
    s = d.get("strati")
    return [norm_strato(x) for x in (s if s else DEFAULT)]


TOL = 0.0005


def default_strati(th):
    if th <= 0.0105:
        return [norm_strato({"nome": tr("Strato 1"), "sp": th if th > 0 else 0.01,
                             "retino": "solid", "col": _INT})]
    return [norm_strato({"nome": tr("Strato 1"), "sp": 0.01,
                         "retino": "solid", "col": _INT}),
            norm_strato({"nome": tr("Strato 2"), "sp": round(th - 0.01, 4),
                         "retino": "lines", "ang": 45.0,
                         "col": [0.93, 0.93, 0.93]})]


def fit_strati(strati, th):
    if th <= 0 or not strati:
        return strati
    tot = sum(max(float(s["sp"]), 1e-6) for s in strati)
    out = [dict(s, sp=round(max(float(s["sp"]), 1e-6) * th / tot, 4))
           for s in strati]
    last = round(th - sum(s["sp"] for s in out[:-1]), 4)
    if last > 0:
        out[-1]["sp"] = last
    return out


def _wall_world(g, d):
    if d.get("poly"):
        return None
    try:
        M = muri.wall_pose(g)

        def w2(p):
            v = M.map(QVector3D(p[0], p[1], 0.0))
            return (v.x(), v.y())
        aL, aR, bL, bR = (w2(p) for p in muri.wall_corners(d))
        a, b = w2(d["a"]), w2(d["b"])
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L < 1e-9:
            return None
        z0 = M.map(QVector3D(0, 0, float(d.get("z0", 0.0)))).z()
        return {"aL": aL, "aR": aR, "bL": bL, "bR": bR, "a": a,
                "u": ((b[0] - a[0]) / L, (b[1] - a[1]) / L),
                "z0": z0, "h": float(d.get("h", 0.0)),
                "open": d.get("open") or ()}
    except Exception:
        return None


def _is_object(g) -> bool:
    ext = getattr(g, "ext", None)
    if not isinstance(ext, dict) or muri.wall_data(g) is not None:
        return False
    return any(str(k).startswith("myhouse_") and k not in (SEC_KEY, OBJ_KEY)
               for k in ext)


def _obj_kind(g) -> str:
    ext = getattr(g, "ext", None) or {}
    return "layers" if any(k in ext for k in LAYERED_KEYS) else "parts"


def _selected_objects(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and _is_object(g) and g not in out:
            out.append(g)
    return out


def _obj_own_layers(g):
    ext = getattr(g, "ext", None) or {}
    for k in LAYERED_KEYS:
        d = ext.get(k)
        if isinstance(d, dict) and d.get("layers"):
            return [_from_hatch(l["t"], l.get("col"), l.get("hatch"),
                                l.get("name")) for l in d["layers"]]
    return None


def _has_pits(g) -> bool:
    d = (getattr(g, "ext", None) or {}).get("myhouse_solaio")
    return isinstance(d, dict) and bool(d.get("scavi"))


def _flat_kid(g):
    from core.group import Group
    ext = getattr(g, "ext", None) or {}
    if isinstance(ext.get("myhouse_solaio"), dict):
        from . import solaio
        m = solaio.slab_mesh(dict(ext["myhouse_solaio"], layers=None,
                                  _pits=True))
    elif isinstance(ext.get("myhouse_tetto"), dict):
        from . import tetto
        m = tetto.roof_mesh(dict(ext["myhouse_tetto"], layers=None))
    else:
        return None
    part = Group(m, name="flat")
    part.component = False
    return part


DOORWIN_KEYS = ("myhouse_porta", "myhouse_finestra")


def _doorwin_hatch(g):
    from ._strati import doorwin_hatch, normalize_hatch
    ext = getattr(g, "ext", None) or {}
    for k in DOORWIN_KEYS:
        d = ext.get(k)
        if isinstance(d, dict):
            return normalize_hatch(doorwin_hatch(d.get("hatch")))
    return None


def _doorwin_cut_part(kid, g=None) -> bool:
    name = str(getattr(kid, "name", "") or "")
    if name in (tr("Telaio"), tr("Anta"), tr("Soglia"), tr("Spalletta")):
        return True
    ext = getattr(g, "ext", None) or {}
    return name == tr("Vetro") and "myhouse_finestra" in ext


def _obj_cfg(g) -> dict:
    c = (getattr(g, "ext", None) or {}).get(OBJ_KEY)
    return c if isinstance(c, dict) else {}


def _obj_th(g) -> float:
    for k in LAYERED_KEYS:
        d = (getattr(g, "ext", None) or {}).get(k)
        if isinstance(d, dict) and d.get("th"):
            return float(d["th"])
    return 0.0


def _face_triangles(face):
    try:
        from .pennello import _collect, face_points
    except Exception:
        return []
    pts = []
    try:
        _collect(face.triangulate(), pts)
    except Exception:
        pts = []
    if len(pts) >= 3 and len(pts) % 3 == 0:
        return [tuple(pts[i:i + 3]) for i in range(0, len(pts), 3)]
    pts = face_points(face)
    if not pts:
        return []
    return [(pts[0], pts[i], pts[i + 1]) for i in range(1, len(pts) - 1)]


def _kid_tris(g, kid):
    gx = getattr(g, "xform", None)
    base = QMatrix4x4(gx) if gx is not None else None
    tris, colr = [], [None]

    def walk(n, parent):
        xf = getattr(n, "xform", None)
        m = parent
        if xf is not None:
            m = QMatrix4x4(xf) if parent is None else parent * QMatrix4x4(xf)
        mesh = getattr(n, "mesh", None)
        if mesh is not None:
            for f in mesh.faces:
                for t in _face_triangles(f):
                    if m is None:
                        tris.append(tuple(t))
                    else:
                        tris.append(tuple(
                            (lambda v: (v.x(), v.y(), v.z()))(
                                m.map(QVector3D(*p))) for p in t))
                if colr[0] is None:
                    c = (getattr(f, "attrs", None) or {}).get("color")
                    if c:
                        colr[0] = tuple(float(x) for x in c[:3])
        for k in getattr(n, "children", None) or ():
            walk(k, m)
    walk(kid, base)
    return tris, (colr[0] or (0.8, 0.8, 0.8))


def default_obj_layers(g, col=None, th=None):
    th = th if th else (_obj_th(g) or 0.20)
    if col is None:
        for kid in list(g.children or ())[:1]:
            col = _kid_tris(g, kid)[1]
    return [norm_strato({"nome": tr("Strato 1"), "sp": th, "retino": "lines",
                         "ang": 45.0, "col": list(col or (0.85, 0.85, 0.85))})]


def default_obj_parts(g):
    out = []
    for i, kid in enumerate(g.children or ()):
        _t, col = _kid_tris(g, kid)
        out.append(norm_strato({
            "nome": str(getattr(kid, "name", "") or tr("Parte {0}").format(i + 1)),
            "sp": 0.05, "retino": "lines", "ang": 45.0, "col": list(col)}))
    return out


def _newell(poly):
    nx = ny = nz = 0.0
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        nx += (a.y() - b.y()) * (a.z() + b.z())
        ny += (a.z() - b.z()) * (a.x() + b.x())
        nz += (a.x() - b.x()) * (a.y() + b.y())
    return QVector3D(nx, ny, nz)


def _emit_cell(out, p0, p1, n, poly_sz, poly_f, st, nrm, u_ref):
    Lc = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    ux, uy = (p1[0] - p0[0]) / Lc, (p1[1] - p0[1]) / Lc

    def P3(s, z, off):
        return QVector3D(p0[0] + ux * s + n[0] * off,
                         p0[1] + uy * s + n[1] * off, z)
    col = tuple(st.get("col") or (0.9, 0.9, 0.9))
    for sg in SIDES:
        out.append(([P3(s, z, OFF_FILL * sg) for s, z in poly_sz], col,
                    "fill", sg))
    kind = st.get("retino", "solid")
    if kind == "solid":
        return
    us = [p[0] for p in poly_f]
    zs = [p[1] for p in poly_f]
    segs = hatch_segments(min(us), max(us), min(zs), max(zs), kind,
                          HATCH_STEP * st.get("scala", 1.0),
                          st.get("ang", 45.0), u_ref, st.get("ang2"))
    segs = clip_segments_to_poly(segs, poly_f)
    for a, b in segs:
        sa, za = from_frame(a, nrm)
        sb, zb = from_frame(b, nrm)
        ls, lz = sb - sa, zb - za
        ll = math.hypot(ls, lz)
        if ll < 1e-6:
            continue
        ps, pz = -lz / ll * HATCH_W / 2, ls / ll * HATCH_W / 2
        for sg in SIDES:
            o = OFF_HATCH * sg
            out.append(([P3(sa + ps, za + pz, o), P3(sb + ps, zb + pz, o),
                         P3(sb - ps, zb - pz, o), P3(sa - ps, za - pz, o)],
                        tuple(st.get("hcol") or HATCH_COLOR), "hatch", sg))


def _object_faces(p0, p1, normal, g, out) -> bool:
    cfg = _obj_cfg(g)
    kids = list(g.children or ())
    layered = _obj_kind(g) == "layers"
    if layered:
        kids = kids[:1]
    n = (normal[0], normal[1])
    before = len(out)
    parts = cfg.get("parti") or []
    own = _obj_own_layers(g) if layered else None
    dw_h = _doorwin_hatch(g)
    for idx, kid in enumerate(kids):
        if own or _has_pits(g):
            kid = _flat_kid(g) or kid
        tris, col = _kid_tris(g, kid)
        if not tris:
            continue
        loops = slice_triangles(tris, p0, p1)
        if not loops:
            continue
        if layered:
            strati = own or [norm_strato(x) for x in (
                cfg.get("strati") or default_obj_layers(g, col))]
            tot = sum(max(float(x["sp"]), 1e-6) for x in strati)
            for loop in loops:
                nrm = layer_normal(loop)
                lf = [to_frame(p, nrm) for p in loop]
                umin = min(p[0] for p in lf)
                umax = max(p[0] for p in lf)
                T = umax - umin
                if T < 1e-6:
                    continue
                acc = 0.0
                for st in strati:
                    a = umin + T * acc / tot
                    acc += max(float(st["sp"]), 1e-6)
                    b = umin + T * acc / tot
                    cell = clip_halfplane(lf, 1.0, 0.0, a)
                    cell = clip_halfplane(cell, -1.0, 0.0, -b) if cell else []
                    if len(cell) < 3:
                        continue
                    _emit_cell(out, p0, p1, n,
                               [from_frame(p, nrm) for p in cell], cell, st,
                               nrm, a)
        else:
            if dw_h and _doorwin_cut_part(kid, g):
                st = _from_hatch(0.05, None, dw_h, "")
            else:
                st = norm_strato(parts[idx] if idx < len(parts) else
                                 {"retino": "lines", "ang": 45.0,
                                  "col": list(col)})
            for loop in loops:
                _emit_cell(out, p0, p1, n, loop, loop, st, (1.0, 0.0), 0.0)
    return len(out) > before


def _emit_cell_h(out, zc, ns, loop, st):
    def P3(xy, off):
        return QVector3D(xy[0], xy[1], zc + off * ns)
    col = tuple(st.get("col") or (0.9, 0.9, 0.9))
    for sg in SIDES:
        out.append(([P3(c, OFF_FILL * sg) for c in loop], col, "fill", sg))
    kind = st.get("retino", "solid")
    if kind == "solid":
        return
    xs = [p[0] for p in loop]
    ys = [p[1] for p in loop]
    segs = hatch_segments(min(xs), max(xs), min(ys), max(ys), kind,
                          HATCH_STEP * st.get("scala", 1.0),
                          st.get("ang", 45.0), 0.0, st.get("ang2"))
    segs = clip_segments_to_poly(segs, loop)
    for A, B in segs:
        dx, dy = B[0] - A[0], B[1] - A[1]
        ll = math.hypot(dx, dy)
        if ll < 1e-6:
            continue
        px, py = -dy / ll * HATCH_W / 2, dx / ll * HATCH_W / 2
        for sg in SIDES:
            o = OFF_HATCH * sg
            out.append(([P3((A[0] + px, A[1] + py), o),
                         P3((B[0] + px, B[1] + py), o),
                         P3((B[0] - px, B[1] - py), o),
                         P3((A[0] - px, A[1] - py), o)],
                        tuple(st.get("hcol") or HATCH_COLOR), "hatch", sg))


def _object_faces_h(zc, ns, g, out) -> bool:
    hh = _doorwin_hatch(g)
    if not hh:
        return False
    st = _from_hatch(0.05, None, hh, "")
    before = len(out)
    for kid in list(g.children or ()):
        if not _doorwin_cut_part(kid, g):
            continue
        tris, _col = _kid_tris(g, kid)
        if not tris:
            continue
        for loop in slice_triangles_h(tris, zc):
            _emit_cell_h(out, zc, ns, loop, st)
    return len(out) > before


def _section_faces(p0, p1, normal, walls, objs=(), hit=None):
    out = []
    D = (p1[0] - p0[0], p1[1] - p0[1])
    Lc = math.hypot(*D)
    n = (normal[0], normal[1])
    for g, d in walls:
        W = _wall_world(g, d)
        if W is None:
            continue
        quad = [W["aL"], W["bL"], W["bR"], W["aR"]]
        ch = clip_chord(p0, p1, quad)
        if ch is None:
            continue
        if hit is not None:
            hit.add(id(g))
        tmin, tmax = ch
        strati = get_strati(d)
        tot = sum(max(float(s["sp"]), 1e-6) for s in strati)
        fr, acc = [], 0.0
        for s in strati[:-1]:
            acc += max(float(s["sp"]), 1e-6)
            fr.append(acc / tot)
        cuts, rev = layer_cuts(p0, p1, tmin, tmax, W["aL"], W["bL"],
                               W["aR"], W["bR"], fr)
        holes = opening_ranges(p0, p1, tmin, tmax, W["a"], W["u"], W["open"])
        rects = section_rects(tmin, tmax, cuts, holes, W["h"], rev)

        def P(t, z, off):
            return QVector3D(p0[0] + D[0] * t + n[0] * off,
                             p0[1] + D[1] * t + n[1] * off, W["z0"] + z)

        bnd = [tmin] + list(cuts) + [tmax]

        for t0, t1, za, zb, li in rects:
            li = min(max(li, 0), len(strati) - 1)
            st = strati[li]
            k = len(cuts) - li if rev else li
            k = min(max(k, 0), len(bnd) - 2)
            u_ref = bnd[k] * Lc
            for sg in SIDES:
                out.append(([P(t0, za, OFF_FILL * sg), P(t1, za, OFF_FILL * sg),
                             P(t1, zb, OFF_FILL * sg), P(t0, zb, OFF_FILL * sg)],
                            tuple(st.get("col") or (0.9, 0.9, 0.9)), "fill", sg))
            for (ua, za2), (ub, zb2) in hatch_segments(
                    t0 * Lc, t1 * Lc, za, zb, st.get("retino"),
                    HATCH_STEP * st.get("scala", 1.0),
                    st.get("ang", 45.0), u_ref, st.get("ang2")):
                lu, lz = ub - ua, zb2 - za2
                ll = math.hypot(lu, lz)
                if ll < 1e-6:
                    continue
                pu, pz = -lz / ll * HATCH_W / 2, lu / ll * HATCH_W / 2
                for sg in SIDES:
                    o = OFF_HATCH * sg
                    out.append(([P((ua + pu) / Lc, za2 + pz, o),
                                 P((ub + pu) / Lc, zb2 + pz, o),
                                 P((ub - pu) / Lc, zb2 - pz, o),
                                 P((ua - pu) / Lc, za2 - pz, o)],
                                tuple(st.get("hcol") or HATCH_COLOR), "hatch", sg))
    for g in objs:
        try:
            if _object_faces(p0, p1, normal, g, out) and hit is not None:
                hit.add(id(g))
        except Exception:
            import traceback
            traceback.print_exc()
    return out


def build_part(scene, p0, p1, side, only):
    from core.group import Group
    from core.mesh import Mesh
    walls = []
    for g in scene.groups:
        d = muri.wall_data(g)
        if d is None or (only and g.name not in only):
            continue
        walls.append((g, d))
    objs = []
    for g in scene.groups:
        if _is_object(g) and (not only or g.name in only):
            objs.append(g)
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    L = math.hypot(dx, dy)
    if L < 1e-6:
        return None, 0
    normal = (-dy / L * side, dx / L * side)
    hit = set()
    faces = _section_faces(p0, p1, normal, walls, objs, hit)
    if not faces:
        return None, 0
    if not any(ly.name == LAYER for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER))
    mesh = Mesh()
    for quad, col, kind, sg in faces:
        nn = _newell(quad)
        if QVector3D.dotProduct(nn, QVector3D(normal[0], normal[1], 0.0)) * sg > 0:
            quad = quad[::-1]
        f = mesh.add_face(quad)
        f.attrs["layer"] = LAYER
        f.attrs["color"] = col
        f.attrs["mat"] = tr("sezione retino") if kind == "hatch" \
            else tr("sezione strato")
        try:
            from .finestre import _hide_edges
            _hide_edges(f)
        except Exception:
            pass
    part = Group(mesh, name=tr("Sezione"))
    part.xform = QMatrix4x4()
    part.component = False
    return part, len(hit)


def create_section(scene, p0, p1, plane_uid, opposto, only_names):
    from core.group import Group
    part, n = build_part(scene, p0, p1, 1, set(only_names))
    if part is None:
        return 0
    g = Group(name=tr("Sezione con strati"))
    g.adopt([part])
    g.component = False
    g.layer = LAYER
    g.ext = {SEC_KEY: {"p0": list(p0), "p1": list(p1), "uid": plane_uid,
                       "opp": bool(opposto), "walls": list(only_names)}}
    scene.groups.append(g)
    return n


def _section_groups(scene):
    return [g for g in scene.groups
            if isinstance(getattr(g, "ext", None), dict) and SEC_KEY in g.ext]


def rebuild_sections(scene) -> int:
    n = 0
    for g in _section_groups(scene):
        prm = g.ext[SEC_KEY]
        if prm.get("hz") is not None:
            zc, ns = prm["hz"], prm.get("ns", 1)
            pl = _plane_by_uid(scene, prm.get("uid"))
            hz = plane_horiz(pl) if pl is not None else None
            if hz:
                zc, ns = hz
                ext = dict(g.ext)
                ext[SEC_KEY] = dict(prm, hz=float(zc), ns=int(ns))
                g.ext = ext
            part, _c = build_part_h(scene, zc, ns, set(prm.get("walls") or ()))
            g.children = [part] if part is not None else []
            n += 1
            continue
        p0, p1 = prm["p0"], prm["p1"]
        pl = _plane_by_uid(scene, prm.get("uid"))
        if pl is not None:
            ln = plane_line(pl, prm.get("opp", False))
            if ln:
                p0, p1 = ln
                ext = dict(g.ext)
                ext[SEC_KEY] = dict(prm, p0=list(p0), p1=list(p1))
                g.ext = ext
        part, _c = build_part(scene, p0, p1, 1, set(prm.get("walls") or ()))
        if part is not None:
            g.children = [part]
            n += 1
    return n


def plane_horiz(pl):
    try:
        _px, _py, pz = _xyz(pl.point)
        _nx, _ny, nz = _xyz(pl.normal)
    except Exception:
        return None
    if abs(nz) < 0.7:
        return None
    return pz, (1 if nz > 0 else -1)


def _lerp2(p, q, k):
    return (p[0] + (q[0] - p[0]) * k, p[1] + (q[1] - p[1]) * k)


def _horizontal_faces(zc, ns, walls, hit=None, objs=()):
    out = []
    for g in objs:
        try:
            if _object_faces_h(zc, ns, g, out) and hit is not None:
                hit.add(id(g))
        except Exception:
            import traceback
            traceback.print_exc()
    for g, d in walls:
        W = _wall_world(g, d)
        if W is None:
            continue
        z0, h = W["z0"], W["h"]
        if not (z0 + 1e-6 < zc < z0 + h - 1e-6):
            continue
        if hit is not None:
            hit.add(id(g))
        rel = zc - z0
        aL, aR, bL, bR = W["aL"], W["aR"], W["bL"], W["bR"]
        Lw = (math.hypot(bL[0] - aL[0], bL[1] - aL[1])
              + math.hypot(bR[0] - aR[0], bR[1] - aR[1])) / 2.0
        thk = (math.hypot(aR[0] - aL[0], aR[1] - aL[1])
               + math.hypot(bR[0] - bL[0], bR[1] - bL[1])) / 2.0
        if Lw < 1e-6 or thk < 1e-6:
            continue
        BIG = 1e9
        holes = sorted((float(o[0]), float(o[1]))
                       for o in W["open"] if float(o[2]) < rel < float(o[3]))
        segs, cur = [], -BIG
        for h0, h1 in holes:
            if h0 > cur + 1e-6:
                segs.append((cur, h0))
            cur = max(cur, h1)
        if cur < BIG:
            segs.append((cur, BIG))
        strati = get_strati(d)
        tot = sum(max(float(s["sp"]), 1e-6) for s in strati)
        ex, ey = W["u"]
        nx, ny = -ey, ex
        if (aR[0] - aL[0]) * nx + (aR[1] - aL[1]) * ny < 0:
            nx, ny = -nx, -ny

        def Pt(t, f):
            return _lerp2(_lerp2(aL, aR, f), _lerp2(bL, bR, f), t)

        def P3(xy, off):
            return QVector3D(xy[0], xy[1], zc + off * ns)

        acc = 0.0
        for st in strati:
            f0 = acc / tot
            acc += max(float(st["sp"]), 1e-6)
            f1 = acc / tot
            full = [Pt(0.0, f0), Pt(1.0, f0), Pt(1.0, f1), Pt(0.0, f1)]
            for s0, s1 in segs:
                cell = full
                ax_, ay_ = W["a"]
                if s0 > -BIG / 2:
                    cell = clip_halfplane(cell, ex, ey, ex * ax_ + ey * ay_ + s0)
                if cell and s1 < BIG / 2:
                    cell = clip_halfplane(cell, -ex, -ey,
                                          -(ex * ax_ + ey * ay_ + s1))
                if not cell or len(cell) < 3:
                    continue
                for sg in SIDES:
                    o = OFF_FILL * sg
                    out.append(([P3(c, o) for c in cell],
                                tuple(st.get("col") or (0.9, 0.9, 0.9)),
                                "fill", sg))
                poly = [((c[0] - aL[0]) * nx + (c[1] - aL[1]) * ny,
                         (c[0] - aL[0]) * ex + (c[1] - aL[1]) * ey)
                        for c in cell]
                pu = [p[0] for p in poly]
                ps_ = [p[1] for p in poly]
                hs = hatch_segments(
                    min(pu), max(pu), min(ps_), max(ps_), st.get("retino"),
                    HATCH_STEP * st.get("scala", 1.0), st.get("ang", 45.0),
                    f0 * thk, st.get("ang2"))
                hs = clip_segments_to_poly(hs, poly)
                for (ua, sa), (ub, sb) in hs:
                    A = (aL[0] + ex * sa + nx * ua, aL[1] + ey * sa + ny * ua)
                    B = (aL[0] + ex * sb + nx * ub, aL[1] + ey * sb + ny * ub)
                    dx, dy = B[0] - A[0], B[1] - A[1]
                    ll = math.hypot(dx, dy)
                    if ll < 1e-6:
                        continue
                    px, py = -dy / ll * HATCH_W / 2, dx / ll * HATCH_W / 2
                    for sg in SIDES:
                        o = OFF_HATCH * sg
                        out.append(([P3((A[0] + px, A[1] + py), o),
                                     P3((B[0] + px, B[1] + py), o),
                                     P3((B[0] - px, B[1] - py), o),
                                     P3((A[0] - px, A[1] - py), o)],
                                    tuple(st.get("hcol") or HATCH_COLOR),
                                    "hatch", sg))
    return out


def build_part_h(scene, zc, ns, only):
    from core.group import Group
    from core.mesh import Mesh
    walls = []
    for g in scene.groups:
        d = muri.wall_data(g)
        if d is None or (only and g.name not in only):
            continue
        walls.append((g, d))
    objs = [g for g in scene.groups
            if _is_object(g) and _doorwin_hatch(g)
            and (not only or g.name in only)]
    hit = set()
    faces = _horizontal_faces(zc, ns, walls, hit, objs)
    if not faces:
        return None, 0
    if not any(ly.name == LAYER for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER))
    mesh = Mesh()
    N = QVector3D(0.0, 0.0, float(ns))
    for quad, col, kind, sg in faces:
        if QVector3D.dotProduct(_newell(quad), N) * sg > 0:
            quad = quad[::-1]
        f = mesh.add_face(quad)
        f.attrs["layer"] = LAYER
        f.attrs["color"] = col
        f.attrs["mat"] = tr("sezione retino") if kind == "hatch" \
            else tr("sezione strato")
        try:
            from .finestre import _hide_edges
            _hide_edges(f)
        except Exception:
            pass
    part = Group(mesh, name=tr("Sezione"))
    part.xform = QMatrix4x4()
    part.component = False
    return part, len(hit)


def create_section_h(scene, zc, ns, plane_uid, only_names):
    from core.group import Group
    part, n = build_part_h(scene, zc, ns, set(only_names))
    if part is None:
        return 0
    g = Group(name=tr("Sezione con strati"))
    g.adopt([part])
    g.component = False
    g.layer = LAYER
    g.ext = {SEC_KEY: {"hz": float(zc), "ns": int(ns), "uid": plane_uid,
                       "walls": list(only_names)}}
    scene.groups.append(g)
    return n


def layers_hidden(scene) -> bool:
    for g in scene.groups:
        ext = getattr(g, "ext", None) or {}
        for k, dd in ext.items():
            if isinstance(dd, dict) and dd.get("layers") and dd.get("_hide_lay"):
                return True
    return False


def set_layers_visible(viewport, visible: bool) -> int:
    from . import solaio, tetto
    res = {"n": 0}

    def mutate(sc):
        for g in list(sc.groups):
            ext = getattr(g, "ext", None) or {}
            d = muri.wall_data(g)
            if d is not None and d.get("layers"):
                muri.rebuild_wall(g, d["th"], d["h"],
                                  {"_hide_lay": None if visible else True})
                res["n"] += 1
                continue
            for mod, rb in ((solaio, solaio.rebuild_slab),
                            (tetto, tetto.rebuild_roof)):
                dd = ext.get(mod.KEY)
                if isinstance(dd, dict) and dd.get("layers"):
                    nd = dict(dd)
                    if visible:
                        nd.pop("_hide_lay", None)
                    else:
                        nd["_hide_lay"] = True
                    rb(g, nd)
                    res["n"] += 1
                    break
        rebuild_sections(sc)

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    return res["n"]


def toggle_layers(viewport) -> None:
    hide = not layers_hidden(viewport.scene)
    n = set_layers_visible(viewport, not hide)
    viewport.flash_status(
        (tr("Strati nascosti su {0} elementi") if hide
         else tr("Strati mostrati su {0} elementi")).format(n), 4000)


def _xyz(v):
    try:
        return float(v.x()), float(v.y()), float(v.z())
    except Exception:
        return float(v[0]), float(v[1]), float(v[2])


def _uid(pl):
    u = getattr(pl, "uid", None)
    return None if callable(u) or u is None else str(u)


def _plane_by_uid(scene, uid):
    if not uid:
        return None
    for p in getattr(scene, "section_planes", ()) or ():
        if _uid(p) == uid:
            return p
    return None


def _active_plane(scene):
    try:
        p = scene.active_section()
        if p is not None:
            return p
    except Exception:
        pass
    for p in getattr(scene, "section_planes", ()) or ():
        if getattr(p, "active", False):
            return p
    return None


def _fill_off(p):
    for name in dir(p):
        if name.startswith("_") or "fill" not in name.lower():
            continue
        try:
            v = getattr(p, name)
            if callable(v):
                continue
            if v is True or (v is None and name == "fill"):
                setattr(p, name, False)
        except Exception:
            pass


def _plane_attrs(p):
    out = []
    for name in dir(p):
        if name.startswith("_"):
            continue
        try:
            v = getattr(p, name)
        except Exception:
            continue
        if callable(v):
            continue
        out.append("%s=%s" % (name, repr(v)[:24]))
    return ", ".join(out)[:420]


def plane_line(pl, opposto=False):
    try:
        px, py, _pz = _xyz(pl.point)
        nx, ny, nz = _xyz(pl.normal)
    except Exception:
        return None
    ln = math.hypot(nx, ny)
    if ln < 0.5 or abs(nz) > 0.7:
        return None
    nx, ny = nx / ln, ny / ln
    sg = -1.0 if opposto else 1.0
    dx, dy = ny * sg, -nx * sg
    return ((px - dx * 500.0, py - dy * 500.0),
            (px + dx * 500.0, py + dy * 500.0))


class _StratiDialog(QDialog):
    def __init__(self, parent, strati, th_tot, can_edit, plane_ok, crea,
                 apply_cb=None, mode="walls"):
        super().__init__(parent)
        self.mode = mode
        self.setWindowTitle(tr("Strati e retini sezione"))
        fit_dialog(self, 640, 400)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.preset_lbl = QLabel(tr("Preset:"))
        top.addWidget(self.preset_lbl)
        self.preset = QComboBox()
        self.preset.addItem("—")
        self._presets = SOLAI_PRESETS if mode == "layers" else PRESETS
        self.preset.addItems(list(self._presets))
        self.preset.currentIndexChanged.connect(self._preset)
        top.addWidget(self.preset, 1)
        lay.addLayout(top)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            [tr("Nome"), tr("Spessore (cm)"), tr("Retino"), tr("Angolo (°)"),
             tr("Scala"), tr("Ripetiz."), tr("Colore")])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        lay.addWidget(self.table)
        self.info = QLabel()
        lay.addWidget(self.info)
        self.th_tot = th_tot
        self.can_edit = can_edit
        self.btns = []
        row = QHBoxLayout()
        for text, fn in ((tr("Aggiungi strato"), lambda: self._add(None)),
                         (tr("Togli strato"), self._remove),
                         (tr("Su"), lambda: self._move(-1)),
                         (tr("Giù"), lambda: self._move(1))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
            self.btns.append(b)
        lay.addLayout(row)
        self.help_lbl = QLabel(
            tr("Dallo strato SUPERIORE all'INFERIORE. La somma degli spessori "
               "deve coincidere con lo spessore dell'oggetto.")
            if mode == "layers" else
            tr("Una riga per parte dell'oggetto (telaio, vetro, plinto...): "
               "colore e retino di ciascuna parte.")
            if mode == "parts" else
            tr("Dalla faccia INTERNA (sinistra) all'ESTERNA. La somma degli "
               "spessori deve coincidere con lo spessore del muro.")
            if can_edit else
            tr("Nessun muro selezionato: gli strati si modificano selezionando "
               "uno o più muri."))
        lay.addWidget(self.help_lbl)
        self.chk_crea = QCheckBox(
            tr("Crea la sezione con gli strati sul piano di sezione attivo"))
        self.chk_crea.setChecked(plane_ok and crea)
        self.chk_crea.setVisible(plane_ok)
        lay.addWidget(self.chk_crea)
        self.chk_opp = QCheckBox(tr("Lato opposto"))
        self.chk_opp.setVisible(plane_ok)
        lay.addWidget(self.chk_opp)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.bb = bb
        self.btn_apply = QPushButton(tr("Aggiorna"))
        self.btn_apply.clicked.connect(
            lambda: apply_cb(self) if apply_cb else None)
        bb.addButton(self.btn_apply, QDialogButtonBox.ApplyRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        for st in strati:
            self._add(st)
        self.table.setEnabled(can_edit)
        for b in self.btns:
            b.setEnabled(can_edit)
        self.preset.setEnabled(can_edit)
        if mode == "parts":
            self.table.setColumnHidden(1, True)
            self.info.setVisible(False)
            for b in self.btns:
                b.setEnabled(False)
            self.preset.setEnabled(False)
            for r in range(self.table.rowCount()):
                it = self.table.item(r, 0)
                if it is not None:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
        self._upd()

    def hide_table(self) -> None:
        for w in (self.table, self.info, self.preset, self.preset_lbl,
                  self.help_lbl, *self.btns):
            w.setVisible(False)
        self.setWindowTitle(tr("Sezione con strati"))
        self.adjustSize()

    def _preset(self, i) -> None:
        name = self.preset.currentText()
        if name in self._presets:
            self.table.setRowCount(0)
            for st in fit_strati(copy.deepcopy(self._presets[name]), self.th_tot):
                self._add(st)

    def _add(self, st) -> None:
        r = self.table.rowCount()
        if st is None:
            usato = sum(self.table.cellWidget(i, 1).value()
                        for i in range(r)) / 100.0
            resto = round(self.th_tot - usato, 4)
            st = {"nome": tr("Strato {0}").format(r + 1),
                  "sp": resto if resto >= 0.01 else 0.01,
                  "retino": "solid", "col": [0.9, 0.9, 0.9]}
        st = norm_strato(st)
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(str(st.get("nome", ""))))
        sp = LengthSpin()
        sp.setDecimals(2)
        sp.setRange(0.1, 500.0)
        sp.setSingleStep(0.5)
        sp.setValue(float(st.get("sp", 0.05)) * 100.0)
        sp.valueChanged.connect(self._upd)
        self.table.setCellWidget(r, 1, sp)
        ang = LengthSpin()
        ang.setDecimals(1)
        ang.setRange(0.0, 180.0)
        ang.setSingleStep(5.0)
        ang.setValue(st["ang"])
        scl = LengthSpin()
        scl.setDecimals(2)
        scl.setRange(0.1, 20.0)
        scl.setSingleStep(0.25)
        scl.setValue(st["scala"])
        cb = QComboBox()
        for k, label in RETINI:
            cb.addItem(label, k)
        cb.setCurrentIndex(max(0, cb.findData(st["retino"])))

        rip = QComboBox()
        rip.addItem("—", 0)
        for k in range(1, 11):
            rip.addItem(str(k), k)
        rip.setToolTip(tr("Adatta il retino: numero di ripetizioni (1-10) nello "
                          "spessore dello strato (solo incrociato e isolante). "
                          "— = scala manuale."))
        rip.setCurrentIndex(max(0, rip.findData(int(st.get("rip", 0)))))

        def _abil(_i=0, c=cb, a=ang, k=scl, rp=rip, s=sp):
            kind = c.currentData()
            a.setEnabled(kind in ("lines", "cross", "insulation"))
            ok_rip = kind in ("cross", "insulation", "hollow")
            rp.setEnabled(ok_rip)
            auto = int(rp.currentData() or 0) if ok_rip else 0
            k.setEnabled(kind != "solid" and not auto)
            if auto:
                k.setValue(fit_scala(kind, s.value() / 100.0, a.value(), auto))
        cb.currentIndexChanged.connect(
            lambda _i, c=cb, a=ang: a.setValue(0.0)
            if c.currentData() == "insulation" else None)
        cb.currentIndexChanged.connect(_abil)
        rip.currentIndexChanged.connect(_abil)
        sp.valueChanged.connect(_abil)
        ang.valueChanged.connect(_abil)
        _abil()
        self.table.setCellWidget(r, 2, cb)
        self.table.setCellWidget(r, 3, ang)
        self.table.setCellWidget(r, 4, scl)
        self.table.setCellWidget(r, 5, rip)
        btn = QPushButton()
        btn.setProperty("col", list(st.get("col") or (0.9, 0.9, 0.9)))
        self._paint_btn(btn)
        btn.clicked.connect(lambda _c=False, b=btn: self._pick(b))
        self.table.setCellWidget(r, 6, btn)
        self._upd()

    @staticmethod
    def _paint_btn(btn) -> None:
        c = btn.property("col")
        btn.setStyleSheet("background-color: rgb(%d,%d,%d);"
                          % tuple(int(v * 255) for v in c))

    def _pick(self, btn) -> None:
        c = btn.property("col")
        q = QColorDialog.getColor(QColor(*[int(v * 255) for v in c]), self)
        if q.isValid():
            btn.setProperty("col", [q.redF(), q.greenF(), q.blueF()])
            self._paint_btn(btn)

    def _remove(self) -> None:
        r = self.table.currentRow()
        if r >= 0 and self.table.rowCount() > 1:
            self.table.removeRow(r)
            self._upd()

    def _move(self, k) -> None:
        r = self.table.currentRow()
        r2 = r + k
        if r < 0 or not (0 <= r2 < self.table.rowCount()):
            return
        a = self.result_list()
        a[r], a[r2] = a[r2], a[r]
        self.table.setRowCount(0)
        for st in a:
            self._add(st)
        self.table.setCurrentCell(r2, 0)

    def _upd(self) -> None:
        tot = sum(self.table.cellWidget(r, 1).value()
                  for r in range(self.table.rowCount())) / 100.0
        diff = tot - self.th_tot
        ok = (not self.can_edit) or self.th_tot <= 0 or abs(diff) <= TOL
        if getattr(self, "mode", "walls") == "parts":
            ok = True
        if getattr(self, "mode", "walls") == "layers":
            base = tr("Somma strati: {0:.2f} cm · spessore dell'oggetto: "
                      "{1:.2f} cm")
        else:
            base = tr("Somma strati: {0:.2f} cm · spessore del muro: "
                      "{1:.2f} cm")
        txt = base.format(tot * 100, self.th_tot * 100)
        if not ok:
            txt += "  —  " + tr("differenza {0:+.2f} cm: devono coincidere"
                                ).format(diff * 100)
        self.info.setText(txt)
        self.info.setStyleSheet("" if ok else "color: #c00000; font-weight: bold;")
        bb = getattr(self, "bb", None)
        if bb is not None:
            bb.button(QDialogButtonBox.Ok).setEnabled(ok)
            self.btn_apply.setEnabled(ok)

    def result_list(self):
        out = []
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            out.append({
                "nome": it.text() if it else "",
                "sp": round(self.table.cellWidget(r, 1).value() / 100.0, 4),
                "retino": self.table.cellWidget(r, 2).currentData(),
                "ang": self.table.cellWidget(r, 3).value(),
                "scala": self.table.cellWidget(r, 4).value(),
                "rip": (int(self.table.cellWidget(r, 5).currentData() or 0)
                        if self.table.cellWidget(r, 5).isEnabled() else 0),
                "col": list(self.table.cellWidget(r, 6).property("col"))})
        return out


_OPEN_DLG = None


def edit_strati(viewport) -> None:
    scene = viewport.scene
    sel = muri._selected_walls(scene)
    objs = _selected_objects(scene)
    pl = _active_plane(scene)
    plane_ok = pl is not None and (plane_line(pl) is not None
                                  or plane_horiz(pl) is not None)
    existing = [sg for sg in _section_groups(scene)
                if pl is not None
                and sg.ext[SEC_KEY].get("uid") == _uid(pl)]
    mode, targets = "walls", []
    if not sel and objs:
        mode = _obj_kind(objs[0])
        targets = [o for o in objs if _obj_kind(o) == mode]
    d0 = muri.wall_data(sel[0]) if sel else {}
    th0 = float(d0.get("th", 0.0))
    if mode == "layers":
        th0 = _obj_th(targets[0])
        c0 = _obj_cfg(targets[0])
        iniziali = ([norm_strato(x) for x in c0["strati"]] if c0.get("strati")
                    else default_obj_layers(targets[0]))
    elif mode == "parts":
        th0 = 0.0
        c0 = _obj_cfg(targets[0])
        iniziali = default_obj_parts(targets[0])
        for i, x in enumerate(c0.get("parti") or ()):
            if i < len(iniziali):
                nome = iniziali[i]["nome"]
                iniziali[i] = dict(norm_strato(x), nome=nome)
    elif not sel:
        iniziali = get_strati(d0)
    elif d0.get("strati"):
        iniziali = fit_strati(get_strati(d0), th0)
    else:
        iniziali = default_strati(th0)
    names = [g.name for g in sel]
    for g in objs:
        if g.name not in names:
            names.append(g.name)
    state = {"created": False}
    if sel and not objs and all(muri.wall_data(g).get("layers") for g in sel):
        viewport.flash_status(
            tr("Gli strati di questi muri si modificano nel pannello Muri "
               "(Strati): qui puoi creare la sezione"), 6000)

    def apply(dlg) -> None:
        strati = dlg.result_list()
        want = plane_ok and dlg.chk_crea.isChecked()
        crea = want and not state["created"]
        opp = dlg.chk_opp.isChecked()
        res = {"n": 0, "reb": 0, "err": None}

        def mutate(sc):
            try:
                for g in targets:
                    if mode == "layers" and _obj_own_layers(g):
                        continue
                    ext = dict(g.ext or {})
                    c = dict(ext.get(OBJ_KEY) or {})
                    c["strati" if mode == "layers" else "parti"] = \
                        copy.deepcopy(strati)
                    ext[OBJ_KEY] = c
                    g.ext = ext
                for g in sel:
                    if muri.wall_data(g).get("layers"):
                        continue
                    ext = dict(g.ext or {})
                    d = dict(ext[muri.KEY])
                    d["strati"] = fit_strati(copy.deepcopy(strati),
                                             float(d.get("th", 0.0)))
                    ext[muri.KEY] = d
                    g.ext = ext
                if pl is not None:
                    for sg in _section_groups(sc):
                        prm = sg.ext[SEC_KEY]
                        w = list(prm.get("walls") or [])
                        if w and prm.get("uid") == _uid(pl):
                            ext2 = dict(sg.ext)
                            ext2[SEC_KEY] = dict(prm, walls=[])
                            sg.ext = ext2
                res["reb"] = rebuild_sections(sc)
                if crea:
                    hz = plane_horiz(pl)
                    if hz:
                        res["n"] = create_section_h(sc, hz[0], hz[1], _uid(pl), [])
                    else:
                        p0, p1 = plane_line(pl, opp)
                        res["n"] = create_section(sc, p0, p1, _uid(pl), opp, [])
            except Exception:
                import traceback
                res["err"] = traceback.format_exc()

        viewport.history.execute(muri.MuriCommand(mutate))
        if res["err"]:
            QMessageBox.critical(dlg, tr("Errore nella sezione con strati"),
                                 res["err"])
            return
        if crea and res["n"]:
            state["created"] = True
        planes = [pl] if (want and pl is not None) else []
        for sg in _section_groups(scene):
            p2 = _plane_by_uid(scene, sg.ext[SEC_KEY].get("uid"))
            if p2 is not None and all(p2 is not q for q in planes):
                planes.append(p2)
        for p2 in planes:
            _fill_off(p2)
        viewport.notify_scene_changed()
        import time
        if crea:
            msg = (tr("Sezione con strati creata su {0} oggetti").format(res["n"])
                   if res["n"] else
                   tr("Nessun oggetto attraversato dalla sezione attiva"))
        else:
            msg = tr("Strati salvati su {0} oggetti · sezioni aggiornate: {1}"
                     ).format(len(sel) + len(targets), res["reb"])
        viewport.flash_status(msg, 5000)
        viewport.update()

    dlg = _StratiDialog(viewport.window(), copy.deepcopy(iniziali),
                        th0, bool(sel) or bool(targets), plane_ok,
                        not existing, apply, mode)
    if sel and not targets and all(
            muri.wall_data(g).get("layers") for g in sel):
        dlg.hide_table()
    elif targets and not sel and mode == "layers" and all(
            _obj_own_layers(o) for o in targets):
        dlg.hide_table()
        viewport.flash_status(
            tr("Gli strati di questi oggetti si modificano nel loro pannello "
               "(Strati): qui puoi creare la sezione"), 6000)
    global _OPEN_DLG
    if _OPEN_DLG is not None:
        try:
            _OPEN_DLG.close()
        except Exception:
            pass
    _OPEN_DLG = dlg
    dlg.setModal(False)
    dlg.setAttribute(Qt.WA_DeleteOnClose, True)
    dlg.accepted.connect(lambda: apply(dlg))

    def _forget(*_a):
        global _OPEN_DLG
        if _OPEN_DLG is dlg:
            _OPEN_DLG = None
    dlg.finished.connect(_forget)
    dlg.show()


AUTO_SEZIONE = True
_AUTO = {"scene": None, "seen": None, "done": None, "created": set()}


def _plane_sig(p):
    try:
        return (_uid(p), tuple(round(v, 4) for v in _xyz(p.point)),
                tuple(round(v, 4) for v in _xyz(p.normal)),
                bool(getattr(p, "active", False)))
    except Exception:
        return (_uid(p),)


def _scene_sig(scene):
    planes = tuple(_plane_sig(p) for p in
                   (getattr(scene, "section_planes", ()) or ()))
    return (id(scene), getattr(scene, "version", None), planes)


def _has_layered_walls(scene) -> bool:
    for g in scene.groups:
        d = muri.wall_data(g)
        if d is not None and (d.get("layers") or d.get("hatch")
                              or d.get("strati")):
            return True
        ext = getattr(g, "ext", None) or {}
        if _doorwin_hatch(g):
            return True
        for k in LAYERED_KEYS:
            dd = ext.get(k)
            if isinstance(dd, dict) and dd.get("layers"):
                return True
    return False


def _auto_process(viewport) -> None:
    scene = viewport.scene
    if not _has_layered_walls(scene):
        return
    pl = _active_plane(scene)
    uid = _uid(pl) if pl is not None else None
    secs = _section_groups(scene)
    create = bool(uid and (plane_line(pl) is not None
                           or plane_horiz(pl) is not None)
                  and uid not in _AUTO["created"]
                  and not any(sg.ext[SEC_KEY].get("uid") == uid for sg in secs))
    if not create and not secs:
        return
    res = {"n": 0}

    def mutate(sc):
        rebuild_sections(sc)
        if create:
            hz = plane_horiz(pl)
            if hz:
                res["n"] = create_section_h(sc, hz[0], hz[1], uid, [])
            else:
                p0, p1 = plane_line(pl)
                res["n"] = create_section(sc, p0, p1, uid, False, [])

    viewport.history.execute(muri.MuriCommand(mutate))
    if create and res["n"]:
        _AUTO["created"].add(uid)
    for sg in _section_groups(scene):
        p2 = _plane_by_uid(scene, sg.ext[SEC_KEY].get("uid"))
        if p2 is not None:
            _fill_off(p2)
    viewport.notify_scene_changed()
    viewport.update()


def _auto_tick(app) -> None:
    try:
        from PySide6.QtWidgets import QApplication
        if QApplication.activeModalWidget() is not None:
            return
        vp = app.viewport
        scene = vp.scene
        if getattr(scene, "edit_group", None) is not None:
            return
        if _AUTO["scene"] != id(scene):
            _AUTO.update(scene=id(scene), seen=None, done=None, created=set())
        sig = _scene_sig(scene)
        if sig != _AUTO["seen"]:
            _AUTO["seen"] = sig
            return
        if sig == _AUTO["done"]:
            return
        _AUTO["done"] = sig
        _auto_process(vp)
        _AUTO["done"] = _AUTO["seen"] = _scene_sig(scene)
    except Exception:
        import traceback
        traceback.print_exc()


def register(api) -> None:
    app = api.app
    if AUTO_SEZIONE:
        try:
            from PySide6.QtCore import QTimer
            timer = QTimer(api.window)
            timer.setInterval(700)
            timer.timeout.connect(lambda: _auto_tick(app))
            timer.start()
            _AUTO["timer"] = timer
        except Exception:
            pass
    try:
        from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
        pm = QPixmap(48, 48)
        pm.fill(Qt.transparent)
        pp = QPainter(pm)
        pp.setPen(QPen(QColor(60, 60, 60), 2))
        for i, c in enumerate(((255, 85, 0), (200, 198, 190), (255, 85, 0))):
            pp.setBrush(QColor(*c))
            pp.drawRect(8, 8 + i * 12, 32, 8)
        pp.setPen(QPen(QColor(200, 0, 0), 3))
        pp.drawLine(6, 42, 42, 6)
        pp.end()
        api.add_button(tr("Mostra/nascondi strati"),
                       tr("Mostra o nasconde gli strati di tutto il progetto "
                          "(senza eliminarli)"),
                       QIcon(pm), lambda: toggle_layers(app.viewport),
                       group="Muri")
    except Exception:
        pass
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is None:
        return
    from PySide6.QtCore import QTimer

    def context(menu, selection) -> None:
        sc = app.viewport.scene
        if not (muri._selected_walls(sc) or _selected_objects(sc)
                or getattr(sc, "section_planes", None)):
            return
        menu.addAction(tr("Strati e retini sezione..."),
                       lambda: QTimer.singleShot(
                           0, lambda: edit_strati(app.viewport)))

    add_ctx(context)
