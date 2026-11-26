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
gable edges not at all (a straight skeleton; gable ends that share a corner
are worked out apart, see _solve_cross). A corner of the shrinking
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
    if n >= 3:
        ends = {int(i) % n for i in gables}
        if (n - len(ends) >= 2
                and any((i + 1) % n in ends for i in ends)):
            return _solve_cross(pts, ends, slope)
    return _solve(pts, gables, slope)


def _solve(outline, gables=(), slope=1.0):
    """The roof as one shrinking outline."""
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


# ---------------------------------------------------------------------------
# Gable ends next to each other
# ---------------------------------------------------------------------------
# Two gable ends that share a corner leave the shrinking outline nothing to
# close that corner with: it would stand still and the two planes left would
# climb all the way up to it. What is built there is a cross gable: the roof
# of each gable end on its own (the other ends sloping), one laid over the
# other, the higher surface on top. Each gable end keeps its triangle, the
# ridges meet inside and a valley runs down to the shared corner.

def _fit_plane(pts3):
    """(a, b, c) of z = a·x + b·y + c through the points, or None."""
    best, plane = 1e-9, None
    for i in range(len(pts3)):
        for j in range(i + 1, len(pts3)):
            for k in range(j + 1, len(pts3)):
                a, b, c = pts3[i], pts3[j], pts3[k]
                u = [b[m] - a[m] for m in range(3)]
                v = [c[m] - a[m] for m in range(3)]
                nz = u[0] * v[1] - u[1] * v[0]
                if abs(nz) > best:
                    best = abs(nz)
                    pa = -(u[1] * v[2] - u[2] * v[1]) / nz
                    pb = -(u[2] * v[0] - u[0] * v[2]) / nz
                    plane = (pa, pb, a[2] - pa * a[0] - pb * a[1])
    return plane


def _same_plane(p, q) -> bool:
    return (abs(p[0] - q[0]) + abs(p[1] - q[1]) < 1e-5
            and abs(p[2] - q[2]) < 1e-4)


def _polygons(geom):
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    return [g for g in getattr(geom, "geoms", ()) if g.geom_type == "Polygon"]


def _segments(geom):
    if geom.geom_type in ("LineString", "LinearRing"):
        c = list(geom.coords)
        return list(zip(c, c[1:]))
    return [s for g in getattr(geom, "geoms", ()) for s in _segments(g)]


def _solve_cross(pts, gables, slope):
    from shapely.geometry import LinearRing, LineString, Point, Polygon
    from shapely.ops import polygonize, unary_union

    n = len(pts)
    # -- the roof of every gable end on its own, as (region, plane) ----------
    roofs = []
    for g in sorted(gables):
        p, lines, hs = _solve(pts, {g}, 1.0)
        faces = []
        for region in polygonize(unary_union(
                [LinearRing(p)] + [LineString(ln) for ln in lines])):
            pts3 = []
            for x, y in list(region.exterior.coords)[:-1]:
                h = min(hs, key=lambda q: _dist(q, (x, y)))
                if _dist(h, (x, y)) < 1e-4:
                    pts3.append((x, y, h[2]))
            plane = _fit_plane(pts3)
            if plane is None:
                raise RoofError("a roof plane cannot be worked out")
            faces.append((region, plane))
        roofs.append(faces)

    def top(x, y):
        """The plane on top at (x, y)."""
        pt, best, bz = Point(x, y), None, -math.inf
        for faces in roofs:
            _r, pl = min(faces, key=lambda f: f[0].distance(pt))
            z = pl[0] * x + pl[1] * y + pl[2]
            if z > bz + 1e-7:
                best, bz = pl, z
        return best, bz

    # -- lay them over each other: cut every piece where two planes cross ----
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    big = 4 * (max(xs) - min(xs) + max(ys) - min(ys)) + 10
    cells = roofs[0]
    for faces in roofs[1:]:
        new = []
        for pa_poly, pa in cells:
            for pb_poly, pb in faces:
                for piece in _polygons(pa_poly.intersection(pb_poly)):
                    if piece.area < 1e-9:
                        continue
                    da, db, dc = pa[0] - pb[0], pa[1] - pb[1], pa[2] - pb[2]
                    g2 = da * da + db * db
                    if g2 < 1e-12:               # parallel: the higher one
                        new.append((piece, pa if dc >= 0 else pb))
                        continue
                    gl = math.sqrt(g2)
                    ox, oy = -dc * da / g2, -dc * db / g2
                    ux, uy, vx, vy = -db / gl, da / gl, da / gl, db / gl
                    half = Polygon([
                        (ox - ux * big, oy - uy * big),
                        (ox + ux * big, oy + uy * big),
                        (ox + (ux + vx) * big, oy + (uy + vy) * big),
                        (ox - (ux - vx) * big, oy - (uy - vy) * big)])
                    new += [(q, pa) for q in _polygons(piece.intersection(half))
                            if q.area >= 1e-9]
                    new += [(q, pb) for q in _polygons(piece.difference(half))
                            if q.area >= 1e-9]
        cells = new

    # -- a line wherever the plane on top changes ----------------------------
    canon: list = []

    def cid(p) -> int:
        for k, c in enumerate(canon):
            if _dist(c, p) < SNAP:
                return k
        canon.append((float(p[0]), float(p[1])))
        return len(canon) - 1

    outline_ids = [cid(p) for p in pts]
    inside = Polygon(pts)
    pairs = set()
    for a, b in _segments(unary_union([c.exterior for c, _pl in cells])):
        length = _dist(a, b)
        if length < 1e-6:
            continue
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        ox, oy = -(b[1] - a[1]) / length * 1e-4, (b[0] - a[0]) / length * 1e-4
        sides = [(mx + ox, my + oy), (mx - ox, my - oy)]
        if not all(inside.contains(Point(s)) for s in sides):
            continue                             # the outline itself
        if _same_plane(top(*sides[0])[0], top(*sides[1])[0]):
            continue
        i, j = cid(a), cid(b)
        if i != j:
            pairs.add((min(i, j), max(i, j)))

    def edge_of(p):
        for i in range(n):
            if seg_dist(p, pts[i], pts[(i + 1) % n]) < SNAP * 2:
                return i
        return None

    changed = True
    while changed:                               # cut at the points on a line
        changed = False
        ends = {k for pr in pairs for k in pr}
        for i, j in sorted(pairs):
            for k in ends:
                if k in (i, j) or seg_dist(canon[k], canon[i],
                                           canon[j]) >= SNAP * 2:
                    continue
                pairs.discard((i, j))
                pairs.add((min(i, k), max(i, k)))
                pairs.add((min(k, j), max(k, j)))
                changed = True
                break
            if changed:
                break
    changed = True
    while changed:                               # join what runs straight on
        changed = False
        at: dict = {}
        for pr in pairs:
            for k in pr:
                at.setdefault(k, []).append(pr)
        for k, prs in at.items():
            if len(prs) != 2 or edge_of(canon[k]) is not None:
                continue
            i = prs[0][0] if prs[0][1] == k else prs[0][1]
            j = prs[1][0] if prs[1][1] == k else prs[1][1]
            if i == j or seg_dist(canon[k], canon[i], canon[j]) >= SNAP * 2:
                continue
            pairs -= set(prs)
            pairs.add((min(i, j), max(i, j)))
            changed = True
            break

    lines, extra = [], {}                        # extra: edge -> ids on it
    for i, j in sorted(pairs):
        lines.append((canon[i], canon[j]))
        for k in (i, j):
            if k in outline_ids:
                continue
            e = edge_of(canon[k])
            if e is not None:
                extra.setdefault(e, set()).add(k)
    points = []
    for i in range(n):
        points.append(canon[outline_ids[i]])
        for k in sorted(extra.get(i, ()),
                        key=lambda k: _dist(canon[k], pts[i])):
            points.append(canon[k])
    used = {p for p in points} | {p for ln in lines for p in ln}
    heights = [(c[0], c[1], max(0.0, top(*c)[1]) * slope)
               for c in canon if c in used]
    return points, lines, heights
