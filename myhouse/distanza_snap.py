# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr

import copy
import dataclasses
import math

from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QFont, QMatrix4x4, QVector3D

from . import muri

ORDER = 120
PICK_PX = 16
EDGE_PX = 10
_state = {"on": False, "dist": None, "dot": None, "cache": (None, None),
          "gcache": (None, None), "touch": False,
          "typing": False, "buf": "", "cur": None, "ctl": None}


def _wall_edges(g):
    d = muri.wall_data(g)
    if d is None:
        return []
    try:
        if d.get("poly"):
            pts = [tuple(p) for p in d["poly"]]
            edges = [(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]
        else:
            aL, aR, bL, bR = muri.wall_corners(d)
            edges = [(aL, bL), (aR, bR)]
        m = muri.wall_pose(g)
        gx = getattr(g, "xform", None)
        if gx is not None:
            m = QMatrix4x4(gx) * m
        out = []
        for p, q in edges:
            a = m.map(QVector3D(p[0], p[1], 0.0))
            b = m.map(QVector3D(q[0], q[1], 0.0))
            out.append(((a.x(), a.y()), (b.x(), b.y())))
        return out
    except Exception:
        return []


EPS = 1e-5
JOIN = 1e-3


def _geom(scene):
    key = (getattr(scene, "version", None), len(scene.groups), id(scene))
    if _state["gcache"][0] == key:
        return _state["gcache"][1]
    from . import piani
    lv = piani.active_id(scene)
    W = []
    for g in scene.groups:
        d = muri.wall_data(g)
        if d is None:
            continue
        if lv and d.get("lv") not in (None, "", lv):
            continue
        edges = _wall_edges(g)
        if not edges:
            continue
        if len(edges) == 2 and not d.get("poly"):
            (a1, b1), (a2, b2) = edges
            poly = [a1, b1, b2, a2]
        else:
            poly = [e[0] for e in edges]
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        W.append((poly, edges, (min(xs), min(ys), max(xs), max(ys))))

    E = []
    for wi, (_poly, edges, _bb) in enumerate(W):
        for p, q in edges:
            dx, dy = q[0] - p[0], q[1] - p[1]
            L = math.hypot(dx, dy)
            if L < 1e-6:
                continue
            ux, uy = dx / L, dy / L
            if ux < -1e-9 or (abs(ux) <= 1e-9 and uy < 0):
                p, q, ux, uy = q, p, -ux, -uy
            E.append((wi, p, q, ux, uy))

    parent = list(range(len(E)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    buckets = {}
    keyed = []
    for i, (wi, p, q, ux, uy) in enumerate(E):
        ak = round(math.atan2(uy, ux) * 2000)
        ck = round((p[0] * -uy + p[1] * ux) / 0.001)
        keyed.append((ak, ck))
        buckets.setdefault((ak, ck), []).append(i)
    for i, (wi, p, q, ux, uy) in enumerate(E):
        ak, ck = keyed[i]
        L = math.hypot(q[0] - p[0], q[1] - p[1])
        for dc in (-1, 0, 1):
            for j in buckets.get((ak, ck + dc), ()):
                if j <= i:
                    continue
                _wj, p2, q2, _ux2, _uy2 = E[j]
                if abs((p2[0] - p[0]) * -uy + (p2[1] - p[1]) * ux) > 2e-4:
                    continue
                if abs((q2[0] - p[0]) * -uy + (q2[1] - p[1]) * ux) > 2e-4:
                    continue
                t1 = (p2[0] - p[0]) * ux + (p2[1] - p[1]) * uy
                t2 = (q2[0] - p[0]) * ux + (q2[1] - p[1]) * uy
                if min(t1, t2) <= L + JOIN and max(t1, t2) >= -JOIN:
                    ri, rj = find(i), find(j)
                    if ri != rj:
                        parent[rj] = ri
    groups = {}
    for i in range(len(E)):
        groups.setdefault(find(i), []).append(i)

    runs = []
    for members in groups.values():
        wi0, o, _q, ux, uy = E[members[0]]
        mwalls = {E[i][0] for i in members}
        ts = []
        for i in members:
            _w, p, q, _a, _b = E[i]
            ts.append((p[0] - o[0]) * ux + (p[1] - o[1]) * uy)
            ts.append((q[0] - o[0]) * ux + (q[1] - o[1]) * uy)
        tmin, tmax = min(ts), max(ts)
        if tmax - tmin < 1e-6:
            continue
        ax, ay = o[0] + ux * tmin, o[1] + uy * tmin
        bx, by = o[0] + ux * tmax, o[1] + uy * tmax
        bb = (min(ax, bx) - 1e-3, min(ay, by) - 1e-3,
              max(ax, bx) + 1e-3, max(ay, by) + 1e-3)
        cross = []
        for wj, (poly_j, edges_j, bj) in enumerate(W):
            if wj in mwalls:
                continue
            if bj[2] < bb[0] or bj[0] > bb[2] or bj[3] < bb[1] or bj[1] > bb[3]:
                continue
            for p, q in edges_j:
                sp = (p[0] - o[0]) * -uy + (p[1] - o[1]) * ux
                sq = (q[0] - o[0]) * -uy + (q[1] - o[1]) * ux
                if (sp > EPS and sq > EPS) or (sp < -EPS and sq < -EPS):
                    continue
                if abs(sp - sq) < 1e-9:
                    continue
                f = sp / (sp - sq)
                cx, cy = p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f
                s = (cx - o[0]) * ux + (cy - o[1]) * uy
                if tmin + EPS < s < tmax - EPS:
                    cross.append(s)
        cross.sort()
        merged = []
        for s in cross:
            if not merged or s - merged[-1] > 1e-4:
                merged.append(s)
        brk = [(tmin, "e")] + [(s, "w") for s in merged] + [(tmax, "e")]
        spans = []
        for (ta, ka), (tb, kb) in zip(brk, brk[1:]):
            if tb - ta < EPS:
                continue
            if "w" in (ka, kb):
                tm = (ta + tb) / 2
                mx, my = o[0] + ux * tm, o[1] + uy * tm
                blocked = False
                for sgn in (1, -1):
                    qx, qy = mx - uy * 1e-3 * sgn, my + ux * 1e-3 * sgn
                    for wj, (poly_j, _e, bj) in enumerate(W):
                        if wj in mwalls:
                            continue
                        if qx < bj[0] or qx > bj[2] or qy < bj[1] or qy > bj[3]:
                            continue
                        if _inside(poly_j, qx, qy):
                            blocked = True
                            break
                    if blocked:
                        break
                if blocked:
                    continue
            spans.append((ta, tb, ka, kb))
        runs.append({"o": o, "u": (ux, uy), "spans": spans, "walls": sorted(mwalls)})
    res = ([(poly, edges) for poly, edges, _bb in W], runs)
    _state["gcache"] = (key, res)
    return res


def _walls(scene, dist):
    W, runs = _geom(scene)
    key = (_state["gcache"][0], round(dist, 6) if dist else 0)
    if _state["cache"][0] == key:
        return _state["cache"][1]
    pts = [[] for _ in W]
    if dist and dist > 0:
        for r in runs:
            ox, oy = r["o"]
            ux, uy = r["u"]
            out = []
            for ta, tb, ka, kb in r["spans"]:
                ln = tb - ta
                if dist > ln + 1e-9:
                    continue
                from_a = not (ka == "e" and kb == "w")
                from_b = not (ka == "w" and kb == "e")
                if from_a:
                    out.append(ta + dist)
                if from_b and (not from_a or ln - dist > 1e-6):
                    out.append(tb - dist)
            xy = [(ox + ux * t, oy + uy * t) for t in out]
            for wi in r["walls"]:
                pts[wi].extend(xy)
    res = [(poly, edges, pts[i]) for i, (poly, edges) in enumerate(W)]
    _state["cache"] = (key, res)
    return res


def candidates(scene, dist: float):
    return [p for _poly, _edges, pts in _walls(scene, dist) for p in pts]


def _inside(poly, x: float, y: float) -> bool:
    ins = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            if x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                ins = not ins
    return ins


def _seg_px(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    if L2 < 1e-12:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def _pick(vp, world):
    _state["touch"] = False
    if not _state["on"]:
        return None
    cur = vp._world_to_pixel(QVector3D(world))
    if cur is None:
        return None
    dist = _state["dist"] if (_state["dist"] and _state["dist"] > 0) else None
    z = world.z()

    def px(x, y):
        return vp._world_to_pixel(QVector3D(x, y, z))

    best, bd = None, float("inf")
    near, nd = None, PICK_PX
    for poly, edges, pts in _walls(vp.scene, dist):
        touched = _inside(poly, world.x(), world.y())
        if not touched:
            for a, b in edges:
                pa, pb = px(*a), px(*b)
                if pa is None or pb is None:
                    continue
                if _seg_px(cur, pa, pb) <= EDGE_PX:
                    touched = True
                    break
        if touched:
            _state["touch"] = True
        for x, y in pts:
            p = px(x, y)
            if p is None:
                continue
            dd = math.hypot(p[0] - cur[0], p[1] - cur[1])
            if touched and dd < bd:
                best, bd = (x, y), dd
            if dd < nd:
                near, nd = (x, y), dd
    return best if best is not None else near


def _with_world(ctx, w: QVector3D):
    try:
        if dataclasses.is_dataclass(ctx):
            return dataclasses.replace(ctx, world=w)
    except Exception:
        pass
    c = copy.copy(ctx)
    try:
        c.world = w
    except Exception:
        object.__setattr__(c, "world", w)
    return c


def _snapped(ctx):
    try:
        _state["cur"] = ctx.viewport._world_to_pixel(QVector3D(ctx.world))
    except Exception:
        pass
    hit = _pick(ctx.viewport, ctx.world)
    if hit is None:
        _state["dot"] = None
        return ctx
    _state["dot"] = hit
    _state["z"] = ctx.world.z()
    return _with_world(ctx, QVector3D(hit[0], hit[1], ctx.world.z()))


def _patch_tool(tool) -> None:
    if tool is None or getattr(tool, "_mh_ds", False):
        return
    name = type(tool).__name__.lower()
    if "select" in name or "selez" in name:
        return
    try:
        on_hover, on_click = tool.on_hover, tool.on_click
        overlay = getattr(tool, "draw_overlay", None) or (lambda vp, pa: None)

        def hover(ctx):
            return on_hover(_snapped(ctx) if _state["on"] else ctx)

        def click(ctx):
            if not _state["on"]:
                return on_click(ctx)
            c = _snapped(ctx)
            used = _state["dot"] is not None
            try:
                return on_click(c)
            finally:
                if used:
                    ctl = _state.get("ctl")
                    if ctl is not None:
                        ctl.reset()

        tool.on_hover, tool.on_click = hover, click

        def draw(viewport, painter):
            overlay(viewport, painter)
            _draw_dot(viewport, painter)
        tool.draw_overlay = draw
        tool._mh_ds = True
    except Exception:
        pass


def _fmt(v) -> str:
    return f"{v:.2f}".replace(".", ",")


def _label() -> str:
    if _state["typing"]:
        return tr("Dist") + ": " + _state["buf"].replace(".", ",") + "_"
    if _state["dist"]:
        return tr("Dist") + ": " + _fmt(_state["dist"]) + " m"
    return ""


def _draw_dot(viewport, painter) -> None:
    try:
        if not _state["on"]:
            return
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        if _state["dot"] is not None:
            x, y = _state["dot"]
            p = viewport._world_to_pixel(QVector3D(x, y, _state.get("z") or 0.0))
            if p is not None:
                painter.setPen(QColor(255, 255, 255))
                painter.setBrush(QColor(230, 30, 30))
                painter.drawEllipse(QPointF(*p), 5.5, 5.5)
        cur, text = _state.get("cur"), _label()
        if cur is not None and text:
            font = QFont()
            font.setPointSize(10)
            painter.setFont(font)
            fm = painter.fontMetrics()
            w, h = fm.horizontalAdvance(text) + 12, fm.height() + 6
            rect = QRectF(cur[0] + 16, cur[1] + 18, w, h)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(30, 30, 30, 210))
            painter.drawRoundedRect(rect, 5, 5)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(QPointF(rect.x() + 6, rect.y() + 3 + fm.ascent()), text)
        painter.restore()
    except Exception:
        pass


def _install(vp) -> None:
    if getattr(vp, "_myhouse_ds_hook", False):
        return
    original = vp.set_active_tool

    def set_active_tool(tool, *a, **kw):
        _patch_tool(tool)
        _state["dot"] = None
        return original(tool, *a, **kw)

    vp.set_active_tool = set_active_tool
    vp._myhouse_ds_hook = True


_DIGITS = {getattr(Qt, f"Key_{i}"): str(i) for i in range(10)}


class _Distanza(QObject):
    def __init__(self, api) -> None:
        super().__init__(api.window)
        self.api = api
        self.action = None

    def _refresh(self, msg: str = "") -> None:
        try:
            sb = self.api.window.statusBar()
            if msg:
                sb.showMessage(msg)
            else:
                sb.clearMessage()
        except Exception:
            pass
        _state["dot"] = None
        if self.action is not None:
            self.action.setChecked(bool(_state["on"]))
        try:
            self.api.window.viewport.update()
        except Exception:
            pass

    def reset(self, msg: str = "") -> None:
        _state["on"] = False
        _state["typing"] = False
        _state["buf"] = ""
        _state["dist"] = None
        self._refresh(msg)

    def toggle(self) -> None:
        if _state["on"] or _state["typing"]:
            if not _state["touch"]:
                self.reset()
                return
        _state["on"] = True
        _state["typing"] = True
        _state["buf"] = ""
        _state["dist"] = None
        try:
            self.api.window.viewport.setFocus()
        except Exception:
            pass
        self._refresh(tr("Dist") + ": " + tr("scrivi il numero, Invio = ok · Esc = esci"))

    def _apply_buf(self) -> None:
        buf = _state["buf"]
        try:
            v = round(float(buf), 2) if buf not in ("", ".") else 0.0
        except ValueError:
            v = 0.0
        _state["dist"] = min(v, 1000.0) if v > 0 else None
        self._refresh(tr("Dist") + ": " + (buf.replace(".", ",") or "")
                      + " — " + tr("Invio = ok · Esc = esci"))

    def _wants(self, ev) -> bool:
        if not _state["typing"]:
            return False
        if (ev.modifiers() & ~Qt.KeypadModifier) != Qt.NoModifier:
            return False
        k = ev.key()
        return (k in _DIGITS or k in (Qt.Key_Comma, Qt.Key_Period, Qt.Key_Backspace,
                                      Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape))

    def eventFilter(self, obj, ev) -> bool:
        try:
            t = ev.type()
            if t == QEvent.ShortcutOverride:
                if self._wants(ev):
                    ev.accept()
                return False
            if t != QEvent.KeyPress or not _state["typing"]:
                return False
            if ev.isAutoRepeat():
                return True
            if not self._wants(ev):
                return False
            k = ev.key()
            buf = _state["buf"]
            if k in _DIGITS:
                dec = buf.split(".")[1] if "." in buf else ""
                if len(dec) < 2:
                    _state["buf"] = buf + _DIGITS[k]
                self._apply_buf()
            elif k in (Qt.Key_Comma, Qt.Key_Period):
                if "." not in buf:
                    _state["buf"] = (buf or "0") + "."
                self._apply_buf()
            elif k == Qt.Key_Backspace:
                _state["buf"] = buf[:-1]
                self._apply_buf()
            elif k in (Qt.Key_Return, Qt.Key_Enter):
                if not _state["dist"]:
                    self.reset()
                else:
                    _state["typing"] = False
                    _state["buf"] = ""
                    self._refresh(tr("Dist") + ": " + _fmt(_state["dist"]) + " m")
            elif k == Qt.Key_Escape:
                self.reset()
            return True
        except Exception:
            return False


def register(api) -> None:
    vp = api.window.viewport
    ctl = _Distanza(api)
    vp.installEventFilter(ctl)
    api._dist_ctl = ctl
    _state["ctl"] = ctl
    _install(vp)
    try:
        from PySide6.QtGui import QAction
        action = QAction(tr("Distanza"), api.window)
        tip = tr("Snap a distanza esatta dall'angolo del muro: scrivi il numero, "
                 "poi tocca un muro e appare il punto (vale una volta sola). "
                 "Ripremi per disattivare")
        action.setToolTip(tip)
        action.setStatusTip(tip)
        action.setCheckable(True)
        try:
            from PySide6.QtGui import QKeySequence
            taken = getattr(api.window, "_ext_taken_keys", set())
            seq = QKeySequence("Shift+D").toString()
            if seq and seq not in taken:
                action.setShortcut(QKeySequence("Shift+D"))
                taken.add(seq)
        except Exception:
            pass
        action.triggered.connect(lambda _c=False: ctl.toggle())
        if api.menu is not None:
            api.menu.addAction(action)
        else:
            api.window.addAction(action)
        ctl.action = action
        api._dist_action = action
    except Exception:
        pass
