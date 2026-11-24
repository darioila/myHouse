# SPDX-License-Identifier: GPL-3.0-or-later
"""Automatic roof: ridges, hips and valleys worked out from an outline
(shared code, not a feature).

    points, lines, heights = solve(outline, gables, slope)

outline is the roof's plan outline, a list of (x, y) in either direction.
Every edge carries a roof plane that rises inwards at the same slope (rise
over run), except the edges whose index is in gables (edge i runs from point
i to point i + 1): those are gable ends, a vertical wall the neighbouring
planes run into.

The result is what the Roof tool draws by hand: the outline (with a point
added wherever a ridge meets a gable end), the inner lines, and the height of
every point above the eaves as (x, y, z).

How: the outline shrinks inwards, every sloped edge at the same speed and the
gable edges not at all (a straight skeleton). A corner of the shrinking
outline draws a hip or a valley as it moves; where an edge shrinks to nothing
or a corner runs into an edge, the outline is cut up and each piece carries
on. The height of a point is the distance the outline had shrunk when it got
there, times the slope. No Qt, no scene: plain numbers.
"""
from __future__ import annotations

import math

TOL = 1e-6          # metres: closer than this is the same point
SNAP = 1e-5         # points of the result closer than this are merged


class RoofError(ValueError):
    """The outline and gables given do not make a roof."""


class _Edge:
    __slots__ = ("nx", "ny", "c", "s", "dx", "dy", "key", "a", "b")

    def __init__(self, a, b, sign, speed) -> None:
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        self.dx, self.dy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        self.nx, self.ny = -self.dy * sign, self.dx * sign    # inwards
        self.c = self.nx * a[0] + self.ny * a[1]
        self.s = speed                    # the line is n·p = c + s·t
        self.a, self.b = a, b
        self.key = (round(self.nx, 7), round(self.ny, 7), round(self.c, 5),
                    speed)


def _area(pts) -> float:
    return 0.5 * sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
                     - pts[(i + 1) % len(pts)][0] * pts[i][1]
                     for i in range(len(pts)))


def _dist(p, q) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def _vertex(e1, e2, t):
    """Where two edges of the shrinking outline meet at time t."""
    det = e1.nx * e2.ny - e1.ny * e2.nx
    if abs(det) < 1e-9:
        raise RoofError("parallel edges meet")
    r1, r2 = e1.c + e1.s * t, e2.c + e2.s * t
    return ((r1 * e2.ny - r2 * e1.ny) / det, (e1.nx * r2 - e2.nx * r1) / det)


def seg_dist(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    l2 = dx * dx + dy * dy
    if l2 < 1e-18:
        return _dist(p, a)
    u = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2))
    return math.hypot(a[0] + u * dx - p[0], a[1] + u * dy - p[1])


# ---------------------------------------------------------------------------
# One moment of the shrinking outline: tidy it, cut it where it touches itself
# ---------------------------------------------------------------------------

def _clean(segs):
    """Drop the edges that have shrunk to nothing and join neighbours that
    lie on the same roof plane."""
    changed = True
    while changed and segs:
        changed = False
        kept = [s for s in segs if _dist(s[1], s[2]) > TOL]
        if len(kept) != len(segs):
            segs, changed = kept, True
        for i in range(len(segs)):
            if len(segs) < 2:
                break
            j = (i + 1) % len(segs)
            if segs[i][0].key == segs[j][0].key:
                joined = (segs[i][0], segs[i][1], segs[j][2])
                if j:
                    segs[i:j + 1] = [joined]
                else:
                    segs = [joined] + segs[1:i]
                changed = True
                break
    return segs


def _resolve(segs, ridges):
    """segs is one closed outline as (edge, start, end). Returns the outlines
    that carry on shrinking, as lists of edges; what has closed up flat goes
    to ridges as (p, q)."""
    out, stack = [], [list(segs)]
    guard = 0
    while stack:
        guard += 1
        if guard > 10000:
            raise RoofError("outline does not settle")
        s = _clean(stack.pop())
        m = len(s)
        if m < 3:
            ridges.extend((p, q) for _e, p, q in s)
            continue
        cut = None
        for i in range(m):                 # two corners in the same place
            for j in range(i + 1, m):
                if _dist(s[i][1], s[j][1]) <= TOL:
                    cut = (i, j)
                    break
            if cut:
                break
        if cut:
            i, j = cut
            stack.append(s[i:j])
            stack.append(s[j:] + s[:i])
            continue
        touch = None
        for i in range(m):                 # a corner on the middle of an edge
            p = s[i][1]
            for k in range(m):
                _e, a, b = s[k]
                if (_dist(p, a) > TOL and _dist(p, b) > TOL
                        and seg_dist(p, a, b) <= TOL):
                    touch = (k, p)
                    break
            if touch:
                break
        if touch:
            k, p = touch                   # cut the edge there, then cut
            e, a, b = s[k]                 # the outline in two at that point
            i = next(x for x in range(m) if s[x][1] is p)
            s[k:k + 1] = [(e, a, p), (e, p, b)]
            i, j = sorted((i + 1 if i > k else i, k + 1))
            stack.append(s[i:j])
            stack.append(s[j:] + s[:i])
            continue
        starts = [x[1] for x in s]
        around = sum(_dist(x[1], x[2]) for x in s)
        if abs(_area(starts)) <= TOL * around:
            ridges.extend((p, q) for _e, p, q in s)
            continue
        out.append([x[0] for x in s])
    return out


def _next_event(ring, t0) -> float:
    """The next time an edge of this outline shrinks to nothing or a corner
    runs into another edge."""
    m = len(ring)
    a = [_vertex(ring[j - 1], ring[j], 0.0) for j in range(m)]
    b1 = [_vertex(ring[j - 1], ring[j], 1.0) for j in range(m)]
    v = [(b1[j][0] - a[j][0], b1[j][1] - a[j][1]) for j in range(m)]
    best = math.inf
    for j in range(m):
        e, k = ring[j], (j + 1) % m
        l0 = (a[k][0] - a[j][0]) * e.dx + (a[k][1] - a[j][1]) * e.dy
        l1 = (v[k][0] - v[j][0]) * e.dx + (v[k][1] - v[j][1]) * e.dy
        if l1 < -1e-12:
            t = -l0 / l1
            if t0 + 1e-9 < t < best:
                best = t
    for j in range(m):
        for k in range(m):
            if k == j or k == (j - 1) % m:
                continue
            e = ring[k]
            f0 = e.nx * a[j][0] + e.ny * a[j][1] - e.c
            f1 = e.nx * v[j][0] + e.ny * v[j][1] - e.s
            if f1 >= -1e-12:
                continue
            t = -f0 / f1
            if not t0 + 1e-9 < t < best:
                continue
            q = (a[j][0] + v[j][0] * t, a[j][1] + v[j][1] * t)
            n = (k + 1) % m
            sk = (a[k][0] + v[k][0] * t, a[k][1] + v[k][1] * t)
            ek = (a[n][0] + v[n][0] * t, a[n][1] + v[n][1] * t)
            u = (q[0] - sk[0]) * e.dx + (q[1] - sk[1]) * e.dy
            length = (ek[0] - sk[0]) * e.dx + (ek[1] - sk[1]) * e.dy
            if -TOL <= u <= length + TOL:
                best = t
    return best


# ---------------------------------------------------------------------------
# The roof
# ---------------------------------------------------------------------------

def _dedupe(outline):
    pts = []
    for p in outline:
        p = (float(p[0]), float(p[1]))
        if not pts or _dist(p, pts[-1]) > 1e-4:
            pts.append(p)
    if len(pts) > 1 and _dist(pts[0], pts[-1]) <= 1e-4:
        pts.pop()
    return pts


def solve(outline, gables=(), slope=1.0):
    """(points, lines, heights) of the roof over outline: see the module
    text. Raises RoofError when these edges do not make a roof."""
    pts = _dedupe(outline)
    n = len(pts)
    if n < 3 or abs(_area(pts)) < 1e-6:
        raise RoofError("not an outline")
    gables = {int(i) % n for i in gables}
    if len(gables) >= n:
        raise RoofError("every edge is a gable")
    sign = 1.0 if _area(pts) > 0 else -1.0
    edges = [_Edge(pts[i], pts[(i + 1) % n], sign,
                   0.0 if i in gables else 1.0) for i in range(n)]

    traces, ridges, seen = [], [], []       # seen: (point, time)
    rings = _resolve([(edges[i], pts[i], pts[(i + 1) % n])
                      for i in range(n)], ridges)
    t0 = 0.0
    for _step in range(40 * n + 200):
        if not rings:
            break
        t1 = min(_next_event(r, t0) for r in rings)
        if not math.isfinite(t1):
            raise RoofError("the roof planes never meet")
        new = []
        for r in rings:
            m = len(r)
            p0 = [_vertex(r[j - 1], r[j], t0) for j in range(m)]
            p1 = [_vertex(r[j - 1], r[j], t1) for j in range(m)]
            for j in range(m):
                traces.append(((r[j - 1].key, r[j].key), p0[j], p1[j]))
                seen.append((p1[j], t1))
                for e in (r[j - 1], r[j]):
                    # a gable end is a wall under the roof: it cannot run on
                    # past its own edge into the middle of the house
                    if not e.s and seg_dist(p1[j], e.a, e.b) > SNAP:
                        raise RoofError("a gable end must lie between two "
                                        "outside corners")
            new += _resolve([(r[j], p1[j], p1[(j + 1) % m])
                             for j in range(m)], ridges)
        rings, t0 = new, t1
    else:
        raise RoofError("the roof does not close")

    # -- one copy of every point, and its height ----------------------------
    canon: list = []
    height: list = []

    def cid(p, t=0.0) -> int:
        for k, c in enumerate(canon):
            if _dist(c, p) < SNAP:
                height[k] = max(height[k], t)
                return k
        canon.append((p[0], p[1]))
        height.append(t)
        return len(canon) - 1

    outline_ids = [cid(p) for p in pts]
    for p, t in seen:
        cid(p, t)

    # -- the lines: what each corner drew, joined end to end -----------------
    segs = []                                # [key, i, j]
    for key, p, q in traces:
        i, j = cid(p), cid(q)
        if i != j:
            segs.append([key, i, j])
    merged = True
    while merged:
        merged = False
        for x in range(len(segs)):
            for y in range(len(segs)):
                if x == y or segs[x][0] != segs[y][0]:
                    continue
                if segs[x][2] == segs[y][1]:         # x then y
                    segs[x][2] = segs[y][2]
                    del segs[y]
                    merged = True
                    break
            if merged:
                break
    pairs = set()
    for _key, i, j in segs:
        if i != j:
            pairs.add((min(i, j), max(i, j)))
    for p, q in ridges:
        i, j = cid(p), cid(q)
        if i != j:
            pairs.add((min(i, j), max(i, j)))

    def edge_of(p):
        """Index of the outline edge p lies on, or None."""
        for i in range(n):
            if seg_dist(p, pts[i], pts[(i + 1) % n]) < SNAP * 2:
                return i
        return None

    lines, extra = [], {}                    # extra: edge -> ids on it
    for i, j in sorted(pairs):
        a, b = canon[i], canon[j]
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        on_edge = (edge_of(a) is not None and edge_of(b) is not None
                   and edge_of(mid) is not None)
        if not on_edge:
            lines.append((a, b))
        for k in (i, j):
            if k in outline_ids:
                continue
            e = edge_of(canon[k])
            if e is not None:
                extra.setdefault(e, set()).add(k)

    points = []
    for i in range(n):
        points.append(canon[outline_ids[i]])
        a = pts[i]
        for k in sorted(extra.get(i, ()), key=lambda k: _dist(canon[k], a)):
            points.append(canon[k])

    used = {p for p in points} | {p for ln in lines for p in ln}
    heights = [(c[0], c[1], height[k] * slope)
               for k, c in enumerate(canon) if c in used]
    return points, lines, heights
