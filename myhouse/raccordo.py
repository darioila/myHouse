# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr

import copy
import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPen, QVector3D

from ._imperial import fmt_len

from .muri import (KEY, PAINT_KEYS, MuriCommand, _selected_walls,
                   build_walls, rebuild_wall, update_roof_clips, wall_corners,
                   wall_data, wall_part, wall_pose)

ORDER = 11


FILL_MAX_GAP = 3.0
FILL_MIN_GAP = 0.02
FILL_LAT = 0.02
FILL_PAR = 0.02
FILL_TH = 0.005
FILL_Z = 0.05
FILL_TOUCH = 0.03
CORNER_SIN = 0.2
CORNER_TRIM = 0.05
_CORNER_KEYS = ("a", "b", "prev", "next", "prev_rev", "next_rev", "chain", "nth",
                "open", "niches")
CORNER_ALL = 50.0


def _pt_seg_dist(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 < 1e-12 else max(0.0, min(1.0, ((p[0] - a[0]) * dx
                                                  + (p[1] - a[1]) * dy) / L2))
    return math.hypot(p[0] - (a[0] + dx * t), p[1] - (a[1] + dy * t))


def _in_poly(p, poly) -> bool:
    ins = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > p[1]) != (y2 > p[1]) and \
                p[0] < (x2 - x1) * (p[1] - y1) / (y2 - y1) + x1:
            ins = not ins
    return ins


def _near_poly2(p, poly, tol) -> bool:
    if _in_poly(p, poly):
        return True
    n = len(poly)
    return any(_pt_seg_dist(p, poly[i], poly[(i + 1) % n]) <= tol
               for i in range(n))


def find_wall_gaps(infos, max_gap=FILL_MAX_GAP, only=None):
    ends = []
    for k, w in enumerate(infos):
        ux, uy = w["cb"][0] - w["ca"][0], w["cb"][1] - w["ca"][1]
        L = math.hypot(ux, uy)
        if L < 1e-6:
            continue
        ux, uy = ux / L, uy / L
        for e, free, p, o in (("a", w["free_a"], w["ca"], (-ux, -uy)),
                              ("b", w["free_b"], w["cb"], (ux, uy))):
            if not free:
                continue
            if any(j != k and _near_poly2(p, infos[j]["poly"], FILL_TOUCH)
                   for j in range(len(infos))):
                continue
            ends.append((k, e, p, o))

    def clear(p, o, along, th) -> bool:
        nx, ny = -o[1], o[0]
        n = max(1, int(along / 0.05))
        for s in range(1, n):
            t = along * s / n
            for off in (0.0, th * 0.4, -th * 0.4):
                q = (p[0] + o[0] * t + nx * off, p[1] + o[1] * t + ny * off)
                if any(_in_poly(q, w["poly"]) for w in infos):
                    return False
        return True

    cands = []
    for i in range(len(ends)):
        k1, e1, p1, o1 = ends[i]
        for j in range(i + 1, len(ends)):
            k2, e2, p2, o2 = ends[j]
            if k1 == k2:
                continue
            if only and infos[k1]["g"] not in only and infos[k2]["g"] not in only:
                continue
            if abs(o1[0] * o2[1] - o1[1] * o2[0]) > FILL_PAR \
                    or o1[0] * o2[0] + o1[1] * o2[1] >= 0:
                continue
            vx, vy = p2[0] - p1[0], p2[1] - p1[1]
            along = vx * o1[0] + vy * o1[1]
            lat = abs(o1[0] * vy - o1[1] * vx)
            if not (FILL_MIN_GAP <= along <= max_gap) or lat > FILL_LAT:
                continue
            w1, w2 = infos[k1], infos[k2]
            if abs(w1["th"] - w2["th"]) > FILL_TH \
                    or abs(w1["z"] - w2["z"]) > FILL_Z:
                continue
            if not clear(p1, o1, along, w1["th"]):
                continue
            cands.append((along, i, j))

    gaps, used = [], set()
    for along, i, j in sorted(cands):
        if i in used or j in used:
            continue
        used.update((i, j))
        k1, e1, p1, o1 = ends[i]
        q = (p1[0] + o1[0] * along, p1[1] + o1[1] * along)
        a, b = (p1, q) if e1 == "b" else (q, p1)
        gaps.append({"ref": k1, "other": ends[j][0], "a": a, "b": b,
                     "len": along})
    return gaps


def _xy_identity(m) -> bool:
    try:
        o = m.map(QVector3D(0.0, 0.0, 0.0))
        x = m.map(QVector3D(1.0, 0.0, 0.0))
        y = m.map(QVector3D(0.0, 1.0, 0.0))
        return (abs(o.x()) < 1e-6 and abs(o.y()) < 1e-6
                and abs(x.x() - 1.0) < 1e-6 and abs(x.y()) < 1e-6
                and abs(y.x()) < 1e-6 and abs(y.y() - 1.0) < 1e-6)
    except Exception:
        return False


def _xy_rigid(m) -> bool:
    try:
        o = m.map(QVector3D(0.0, 0.0, 0.0))
        x = m.map(QVector3D(1.0, 0.0, 0.0))
        y = m.map(QVector3D(0.0, 1.0, 0.0))
        ax, ay = x.x() - o.x(), x.y() - o.y()
        bx, by = y.x() - o.x(), y.y() - o.y()
        return (abs(math.hypot(ax, ay) - 1.0) < 1e-6
                and abs(math.hypot(bx, by) - 1.0) < 1e-6
                and abs(ax * bx + ay * by) < 1e-6
                and ax * by - ay * bx > 0)
    except Exception:
        return False


def _w_pt(m, q):
    v = m.map(QVector3D(q[0], q[1], 0.0))
    return [v.x(), v.y()]


def _world_d(d, m):
    try:
        return dict(d, a=_w_pt(m, d["a"]), b=_w_pt(m, d["b"]))
    except Exception:
        return dict(d)


def _l_pt(w, q):
    inv, ok = w["m"].inverted()
    v = (inv if ok else w["m"]).map(QVector3D(q[0], q[1], 0.0))
    return [v.x(), v.y()]


def _wall_infos(scene):
    from PySide6.QtGui import QMatrix4x4
    infos = []
    for g in scene.groups:
        d = wall_data(g)
        if d is None:
            continue
        try:
            aL, aR, bL, bR = wall_corners(d)
            m = wall_pose(g)
            gx = getattr(g, "xform", None)
            if gx is not None:
                m = QMatrix4x4(gx) * m

            def W(q):
                v = m.map(QVector3D(q[0], q[1], 0.0))
                return (v.x(), v.y())
            pts = [W(aL), W(bL), W(bR), W(aR)]
            z = m.map(QVector3D(0.0, 0.0, d["z0"])).z()
        except Exception:
            continue
        infos.append({
            "g": g, "d": d, "poly": pts, "z": z, "th": d["th"],
            "ca": ((pts[0][0] + pts[3][0]) / 2, (pts[0][1] + pts[3][1]) / 2),
            "cb": ((pts[1][0] + pts[2][0]) / 2, (pts[1][1] + pts[2][1]) / 2),
            "free_a": not d.get("prev"), "free_b": not d.get("next"),
            "ident": _xy_identity(m), "rigid": _xy_rigid(m),
            "m": m, "dw": _world_d(d, m)})
    return infos


_SWAP = {"col_l": "col_r", "col_r": "col_l", "tex_l": "tex_r", "tex_r": "tex_l",
         "bat_l": "bat_r", "bat_r": "bat_l"}


def _norm(v):
    return list(v) if isinstance(v, (list, tuple)) else (v or None)


def _same_paint(d1, d2, rev) -> bool:
    for k in PAINT_KEYS + ("bat_l", "bat_r"):
        k2 = _SWAP.get(k, k) if rev else k
        if _norm(d1.get(k)) != _norm(d2.get(k2)):
            return False
    return True


def plan_merges(infos, gaps):
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for gp in gaps:
        parent[find(gp["ref"])] = find(gp["other"])
    comps = {}
    for gp in gaps:
        comps.setdefault(find(gp["ref"]), []).append(gp)
    merges, rest = [], []
    for cg in comps.values():
        mem = sorted({gp["ref"] for gp in cg} | {gp["other"] for gp in cg})
        ref = mem[0]
        dr = infos[ref]["d"]
        r0 = dr["a"]
        ux, uy = dr["b"][0] - r0[0], dr["b"][1] - r0[1]
        L = math.hypot(ux, uy)
        ux, uy = ux / L, uy / L
        ok, ends = True, []
        for k in mem:
            w = infos[k]
            d = w["d"]
            vx, vy = d["b"][0] - d["a"][0], d["b"][1] - d["a"][1]
            rev = vx * ux + vy * uy < 0
            if (not w.get("ident", True) or d.get("align") != "center"
                    or d.get("open") or d.get("niches")
                    or abs(d["th"] - dr["th"]) > FILL_TH
                    or abs(d["h"] - dr["h"]) > FILL_Z
                    or abs(w["z"] - infos[ref]["z"]) > FILL_Z
                    or d.get("lv") != dr.get("lv")
                    or (d.get("tlv"), d.get("toff") or 0.0)
                    != (dr.get("tlv"), dr.get("toff") or 0.0)
                    or not _same_paint(dr, d, rev)):
                ok = False
                break
            for pt, nb in ((d["a"], d.get("prev")), (d["b"], d.get("next"))):
                s_ = (pt[0] - r0[0]) * ux + (pt[1] - r0[1]) * uy
                ends.append((s_, tuple(pt), nb))
        if not ok:
            rest += cg
            continue
        lo = min(ends, key=lambda e: e[0])
        hi = max(ends, key=lambda e: e[0])
        merges.append({"ref": ref, "members": mem, "gaps": cg,
                       "a": lo[1], "b": hi[1],
                       "prev": lo[2], "next": hi[2]})
    return merges, rest


def _corner_ok(w) -> bool:
    d = w["d"]
    return bool(w.get("rigid", True) and not d.get("poly")
                and d.get("th_b") is None)


def _corner_eval(infos, k1, k2, reach):
    w1, w2 = infos[k1], infos[k2]
    n = len(infos)
    for w in (w1, w2):
        d = w["d"]
        if not w.get("rigid", True):
            return None, tr("un muro e' scalato o specchiato")
        if d.get("poly") or d.get("th_b") is not None:
            return None, tr("un muro e' a poligono o a spessore variabile")
    d1, d2 = w1["dw"], w2["dw"]
    if d1.get("align") != d2.get("align"):
        return None, tr("ricalco diverso")
    if abs(w1["z"] - w2["z"]) > FILL_Z:
        return None, tr("quota diversa")
    nb = any(d.get("prev") or d.get("next") for d in (d1, d2))
    if abs(d1["th"] - d2["th"]) > FILL_TH and nb:
        return None, tr("spessori diversi e un muro e' gia' collegato ad altri")
    hit = _line_hit(d1, d2)
    if hit is None:
        return None, tr("muri paralleli")
    P, t1, t2, L1, L2 = hit
    r1 = _end_over(d1, L1, t1, d2["th"], reach)
    r2 = _end_over(d2, L2, t2, d1["th"], reach)
    if r1 is None or r2 is None:
        return None, tr("estremo gia' collegato o incrocio troppo lontano")
    for k, w, e, over in ((k1, w1, r1[0], r1[1]), (k2, w2, r2[0], r2[1])):
        p = w["ca"] if e == "a" else w["cb"]
        if any(j not in (k1, k2)
               and _near_poly2(p, infos[j]["poly"], FILL_TOUCH)
               for j in range(n)):
            return None, tr("un terzo muro tocca l'estremo")
        if over > 0.05:
            ux, uy = P[0] - p[0], P[1] - p[1]
            m = max(1, int(over / 0.05))
            for st in range(1, m + 1):
                q = (p[0] + ux * st / m, p[1] + uy * st / m)
                if any(j not in (k1, k2) and _in_poly(q, infos[j]["poly"])
                       for j in range(n)):
                    return None, tr("un terzo muro attraversa l'angolo")
    return (abs(r1[1]) + abs(r2[1]), k1, r1[0], k2, r2[0], P), None


def _corner_reason(infos, k1, k2, reach) -> str:
    return _corner_eval(infos, k1, k2, reach)[1] or "?"


def _line_hit(d1, d2):
    a1, b1, a2, b2 = d1["a"], d1["b"], d2["a"], d2["b"]
    u1x, u1y = b1[0] - a1[0], b1[1] - a1[1]
    u2x, u2y = b2[0] - a2[0], b2[1] - a2[1]
    L1, L2 = math.hypot(u1x, u1y), math.hypot(u2x, u2y)
    if L1 < 1e-6 or L2 < 1e-6:
        return None
    u1x, u1y, u2x, u2y = u1x / L1, u1y / L1, u2x / L2, u2y / L2
    det = u1x * u2y - u1y * u2x
    if abs(det) < CORNER_SIN:
        return None
    dx, dy = a2[0] - a1[0], a2[1] - a1[1]
    t1 = (dx * u2y - dy * u2x) / det
    t2 = (dx * u1y - dy * u1x) / det
    return (a1[0] + u1x * t1, a1[1] + u1y * t1), t1, t2, L1, L2


def _end_over(d, L, t, other_th, max_reach):
    e = "a" if t < L / 2 else "b"
    over = -t if e == "a" else t - L
    if d.get("prev" if e == "a" else "next") or d.get("sm_" + e):
        return None
    if over > max_reach or over < -(other_th / 2 + CORNER_TRIM) \
            or L + over < 0.05:
        return None
    return e, over


def find_wall_corners(infos, max_reach=FILL_MAX_GAP, only=None):
    n = len(infos)
    cands = []
    for k1 in range(n):
        w1 = infos[k1]
        if not _corner_ok(w1):
            continue
        for k2 in range(k1 + 1, n):
            w2 = infos[k2]
            if not _corner_ok(w2):
                continue
            if only and w1["g"] not in only and w2["g"] not in only:
                continue
            cand, _why = _corner_eval(infos, k1, k2, max_reach)
            if cand is not None:
                cands.append(cand)
    out, used = [], set()
    for cost, k1, e1, k2, e2, P in sorted(cands):
        if (k1, e1) in used or (k2, e2) in used:
            continue
        used.update(((k1, e1), (k2, e2)))
        out.append({"k1": k1, "e1": e1, "k2": k2, "e2": e2, "P": P,
                    "cost": cost})
    return out


def apply_corners(sc, infos, corners) -> int:
    from core.group import new_uid
    cur = {}
    for c in corners:
        for k in (c["k1"], c["k2"]):
            if k not in cur:
                cur[k] = dict(infos[k]["d"])
    for c in corners:
        for k, e in ((c["k1"], c["e1"]), (c["k2"], c["e2"])):
            cur[k][e] = _l_pt(infos[k], c["P"])
    relabel = {}
    for c in corners:
        k1, e1, k2, e2 = c["k1"], c["e1"], c["k2"], c["e2"]
        for k, e, o, oe in ((k1, e1, k2, e2), (k2, e2, k1, e1)):
            far = cur[o]["b" if oe == "a" else "a"]
            far = _l_pt(infos[k], _w_pt(infos[o]["m"], far))
            cur[k]["prev" if e == "a" else "next"] = far
            rk = "prev_rev" if e == "a" else "next_rev"
            if e == oe and cur[k].get("align") != "center":
                cur[k][rk] = True
            else:
                cur[k].pop(rk, None)
        d1, d2 = cur[k1], cur[k2]
        if abs(d1["th"] - d2["th"]) <= FILL_TH:
            cid = d1.get("chain") or d2.get("chain") or new_uid()
            for dd in (d1, d2):
                if dd.get("chain") and dd["chain"] != cid:
                    relabel[dd["chain"]] = cid
                dd["chain"] = cid
                dd["nth"] = dd["th"]
        else:
            d1["nth"], d2["nth"] = d2["th"], d1["th"]
            d1.pop("chain", None)
            d2.pop("chain", None)
    for k, dd in cur.items():
        d0 = infos[k]["d"]
        ux, uy = d0["b"][0] - d0["a"][0], d0["b"][1] - d0["a"][1]
        L = math.hypot(ux, uy)
        delta = ((d0["a"][0] - dd["a"][0]) * ux
                 + (d0["a"][1] - dd["a"][1]) * uy) / L
        if abs(delta) > 1e-9:
            for key in ("open", "niches"):
                if dd.get(key):
                    lst = [list(o) for o in dd[key]]
                    for o in lst:
                        o[0] += delta
                        o[1] += delta
                    dd[key] = lst
        if dd.get("chain") in relabel:
            dd["chain"] = relabel[dd["chain"]]
    done = {infos[k]["g"] for k in cur}
    if relabel:
        for g in sc.groups:
            d = wall_data(g)
            if g not in done and d and d.get("chain") in relabel:
                ext = dict(g.ext or {})
                ext[KEY] = dict(d, chain=relabel[d["chain"]])
                g.ext = ext
    for k, dd in cur.items():
        g = infos[k]["g"]
        try:
            rebuild_wall(g, dd["th"], dd["h"],
                         {key: dd[key] for key in _CORNER_KEYS if key in dd})
        except Exception:
            pass
        g.children = [wall_part(dd, wall_pose(g), g.name)]
        ext = dict(g.ext or {})
        ext[KEY] = dd
        g.ext = ext
    return len(corners)


def infos_by_group(infos, g):
    return next((w for w in infos if w["g"] is g), None)


def raccordo_muri(viewport, max_gap=FILL_MAX_GAP) -> int:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(
            tr("Chiudi il gruppo che stai modificando, poi usa Raccordo muri"), 4000)
        return 0
    sel = _selected_walls(scene)
    only = sel or None
    reach = max(max_gap, CORNER_ALL) if len(sel) == 2 else max_gap
    infos = _wall_infos(scene)
    gaps = find_wall_gaps(infos, max_gap, only)
    if not gaps and not find_wall_corners(infos, reach, only):
        if len(sel) == 2:
            ka = next((i for i, w in enumerate(infos) if w["g"] is sel[0]), None)
            kb = next((i for i, w in enumerate(infos) if w["g"] is sel[1]), None)
            why = (_corner_reason(infos, ka, kb, reach)
                   if ka is not None and kb is not None else "?")
            viewport.flash_status(
                tr("I due muri non si possono unire ad angolo: ") + why, 6000)
        else:
            viewport.flash_status(
                tr("Nessun vuoto o angolo da raccordare (massimo {0})")
                .format(fmt_len(max_gap)), 5000)
        return 0
    merges, rest = plan_merges(infos, gaps)
    made, joined = [0], [0]

    def mutate(sc):
        for m in merges:
            w = infos[m["ref"]]
            d = w["d"]
            rebuild_wall(w["g"], d["th"], d["h"],
                         {"a": list(m["a"]), "b": list(m["b"]),
                          "prev": list(m["prev"]) if m["prev"] else None,
                          "next": list(m["next"]) if m["next"] else None})
            for k in m["members"]:
                if k != m["ref"]:
                    g = infos[k]["g"]
                    if g in sc.groups:
                        sc.groups.remove(g)
                    try:
                        sc.selection.discard(g)
                    except Exception:
                        pass
        for gp in rest:
            w = infos[gp["ref"]]
            d = w["d"]
            lv = ({"id": d["lv"], "name": d.get("lvn")} if d.get("lv") else None)
            paint = {k: copy.deepcopy(d[k]) for k in PAINT_KEYS if d.get(k)}
            skirt = {k: list(d[k]) for k in ("bat_l", "bat_r") if d.get(k)}
            made[0] += build_walls(
                sc, [gp["a"], gp["b"]], False, d["th"], d["h"], w["z"],
                tr("Raccordo"), "center", lv, d.get("off") or 0.0,
                d.get("tlv"), d.get("toff") or 0.0, paint, skirt)
        fresh = _wall_infos(sc)
        only2 = None
        if only:
            only2 = list(only) + [infos[m["ref"]]["g"] for m in merges]
        joined[0] = apply_corners(sc, fresh,
                                  find_wall_corners(fresh, reach, only2))
        update_roof_clips(sc)

    hist = viewport.history
    hist.execute(MuriCommand(mutate))
    if getattr(hist, "last_error", None):
        viewport.flash_status(
            tr("Muri: ") + str(hist.last_error).split(": ", 1)[-1], 6000)
        return 0
    viewport.notify_scene_changed()
    viewport.update()
    parts = []
    if gaps:
        parts.append(tr("{0} vuoti chiusi: {1} muri fusi in uno, {2} raccordi a parte")
                     .format(len(gaps), len(merges), made[0]))
    if joined[0]:
        parts.append(tr("{0} angoli uniti con giunto a sbieco").format(joined[0]))
    viewport.flash_status(" · ".join(parts), 5000)
    return len(gaps) + joined[0]


class RaccordoMuriTool:
    name = tr("Raccordo muri")
    description = tr("Raccorda i vuoti (porte, finestre) tra muri allineati e unisce ad angolo i muri con un estremo libero.")
    max_gap = FILL_MAX_GAP

    def on_activate(self, viewport) -> None:
        from PySide6.QtCore import QTimer
        from ._imperial import ask_length
        val, ok = ask_length(
            viewport.window(), tr("Raccordo muri"),
            tr("Distanza massima da raccordare (m): vuoti tra muri allineati\n"
               "e angoli tra muri non allineati\n"
               "Con dei muri selezionati: solo quelli che li toccano\n"
               "(con 2 soli muri selezionati l'angolo non ha limite)"),
            RaccordoMuriTool.max_gap, 0.05, 50.0)
        if ok:
            RaccordoMuriTool.max_gap = val
            raccordo_muri(viewport, val)
        back = getattr(viewport.window(), "activate_select_tool", None)
        if callable(back):
            QTimer.singleShot(0, back)


def _raccordo_icon():
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QIcon, QPainter, QPixmap, QPolygon
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(215, 205, 190))
    p.drawPolygon(QPolygon([QPoint(11, 5), QPoint(25, 5), QPoint(25, 29),
                            QPoint(43, 29), QPoint(43, 43), QPoint(11, 43)]))
    p.setPen(QPen(QColor(220, 40, 40), 2))
    p.drawLine(11, 29, 25, 29)
    p.end()
    return QIcon(pm)


def register(api) -> None:
    api.add_button(tr("Raccordo muri"),
                   tr("Chiude i vuoti tra muri allineati e unisce ad angolo i muri con legatura perfetta"),
                   _raccordo_icon(), api.run_tool(RaccordoMuriTool()))
    app = api.app
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        from PySide6.QtCore import QTimer

        def context(menu, selection) -> None:
            if not _selected_walls(app.viewport.scene):
                return
            menu.addAction(
                tr("Raccordo muri vicino ai selezionati"),
                lambda: QTimer.singleShot(
                    0, lambda: raccordo_muri(app.viewport)))

        add_ctx(context)
