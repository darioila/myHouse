# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr

import math

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF, QVector3D
from PySide6.QtWidgets import QLineEdit, QWidget

from . import _imperial
from ._imperial import fmt_len

from . import muri

ENABLED = False
DIST_MAX = 60.0
PAR = 0.02
TOL = 2e-3
NO_QUOTES_TOOLS = ("muri", "finestr", "recinz", "balaust", "porte", "scale")

C_INT = QColor(26, 90, 190, 225)
C_EST = QColor(205, 102, 12, 225)
C_DIST = QColor(120, 160, 225, 235)
C_EDIT = QColor(190, 150, 0, 255)


class _W:

    def __init__(self, g, d) -> None:
        self.g, self.d = g, d
        self.M = muri.wall_pose(g)
        inv, ok = self.M.inverted()
        self.Minv = inv if ok else None
        aL, aR, bL, bR = muri.wall_corners(d)
        self.aL, self.aR = self.w2(aL), self.w2(aR)
        self.bL, self.bR = self.w2(bL), self.w2(bR)
        self.a, self.b = self.w2(d["a"]), self.w2(d["b"])
        self.z0 = self.M.map(QVector3D(0, 0, float(d.get("z0", 0.0)))).z()
        self.zt = self.M.map(QVector3D(
            0, 0, float(d.get("z0", 0.0)) + float(d.get("h", 0.0)))).z()
        self.quad = (self.aL, self.bL, self.bR, self.aR)

    def w2(self, p):
        v = self.M.map(QVector3D(p[0], p[1], 0.0))
        return (v.x(), v.y())

    def local(self, x, y, z):
        v = self.Minv.map(QVector3D(x, y, z))
        return (v.x(), v.y())

    def node(self, e):
        return self.a if e == "a" else self.b


def _walls(scene):
    out = []
    for g in scene.groups:
        d = muri.wall_data(g)
        if d is None:
            continue
        try:
            out.append(_W(g, d))
        except Exception:
            continue
    return out


def _dist2(p, q):
    return math.hypot(p[0] - q[0], p[1] - q[1])


def _in_quad(p, q, tol=1e-3) -> bool:
    pos = neg = False
    for i in range(4):
        a, b = q[i], q[(i + 1) % 4]
        ex, ey = b[0] - a[0], b[1] - a[1]
        L = math.hypot(ex, ey)
        if L < 1e-9:
            continue
        dd = (ex * (p[1] - a[1]) - ey * (p[0] - a[0])) / L
        if dd > tol:
            pos = True
        elif dd < -tol:
            neg = True
    return not (pos and neg)


def _ray(o, d, quads):
    best = None
    for q in quads:
        for i in range(4):
            p, r = q[i], q[(i + 1) % 4]
            ex, ey = r[0] - p[0], r[1] - p[1]
            den = d[0] * ey - d[1] * ex
            if abs(den) < 1e-9:
                continue
            wx, wy = p[0] - o[0], p[1] - o[1]
            t = (wx * ey - wy * ex) / den
            sp = (wx * d[1] - wy * d[0]) / den
            if t > 1e-4 and -1e-6 <= sp <= 1.0 + 1e-6 and (
                    best is None or t < best):
                best = t
    return best


def _touching(w, walls):
    out = set()
    for o in walls:
        if o is w:
            continue
        for p in (w.a, w.b):
            if _dist2(p, o.a) < TOL or _dist2(p, o.b) < TOL:
                out.add(id(o.g))
    return out


def _distanze(w, walls):
    ux, uy = w.b[0] - w.a[0], w.b[1] - w.a[1]
    L = math.hypot(ux, uy)
    if L < 1e-6:
        return []
    u = (ux / L, uy / L)
    nl = (-u[1], u[0])
    mid = ((w.a[0] + w.b[0]) / 2, (w.a[1] + w.b[1]) / 2)
    skip = _touching(w, walls)
    quads = []
    for o in walls:
        if o is w or id(o.g) in skip or abs(o.z0 - w.z0) > 5.0:
            continue
        quads.append(o.quad)
    if not quads:
        return []
    mL = ((w.aL[0] + w.bL[0]) / 2, (w.aL[1] + w.bL[1]) / 2)
    mR = ((w.aR[0] + w.bR[0]) / 2, (w.aR[1] + w.bR[1]) / 2)
    prove = [("D_SX", mL, nl), ("D_DX", mR, (-nl[0], -nl[1]))]
    if not _joined(w, "a", walls):
        prove.append(("D_IN", ((w.aL[0] + w.aR[0]) / 2,
                               (w.aL[1] + w.aR[1]) / 2), (-u[0], -u[1])))
    if not _joined(w, "b", walls):
        prove.append(("D_FI", ((w.bL[0] + w.bR[0]) / 2,
                               (w.bL[1] + w.bR[1]) / 2), u))
    out = []
    for lato, o, dr in prove:
        if any(_in_quad(o, q) for q in quads):
            continue
        t = _ray(o, dr, quads)
        if t is None or t > DIST_MAX:
            continue
        out.append((lato, o, dr, t))
    return out


def _joined(w, e, walls) -> bool:
    p = w.node(e)
    for o in walls:
        if o is w:
            continue
        if _dist2(p, o.a) < TOL or _dist2(p, o.b) < TOL:
            return True
    return False


def _lengths_local(d):
    aL, aR, bL, bR = muri.wall_corners(d)
    ref = math.hypot(d["b"][0] - d["a"][0], d["b"][1] - d["a"][1])
    if d.get("align") == "right":
        out = math.hypot(bL[0] - aL[0], bL[1] - aL[1])
    else:
        out = math.hypot(bR[0] - aR[0], bR[1] - aR[1])
    return ref, out


def _value_after(w, e, mv, lato) -> float:
    d2 = dict(w.d)
    p = w.node(e)
    z = w.z0
    new = w.local(p[0] + mv[0], p[1] + mv[1], z)
    d2["a" if e == "a" else "b"] = list(new)
    ref, out = _lengths_local(d2)
    return ref if lato == "INT" else out


def _propaga(walls, iniz, escludi):
    pos = {}
    for w in walls:
        pos[(w.g, "a")] = (w.a[0], w.a[1], w.z0)
        pos[(w.g, "b")] = (w.b[0], w.b[1], w.z0)
    cella = {}

    def cell(pt):
        return (int(round(pt[0] * 100)), int(round(pt[1] * 100)),
                int(round(pt[2] * 20)))
    for nodo, pt in pos.items():
        cella.setdefault(cell(pt), []).append(nodo)
    cache = {}

    def giunto(nodo):
        r = cache.get(nodo)
        if r is not None:
            return r
        pt = pos[nodo]
        cx, cy, cz = cell(pt)
        r = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for altro in cella.get((cx + dx, cy + dy, cz + dz), ()):
                        q = pos[altro]
                        if math.hypot(q[0] - pt[0], q[1] - pt[1]) < TOL and \
                                abs(q[2] - pt[2]) < 0.05:
                            r.append(altro)
        if nodo not in r:
            r.append(nodo)
        cache[nodo] = r
        return r

    quads = [(w.g, w.quad) for w in walls]

    def attaccato(altro):
        g_seg = altro[0]
        for nn in giunto(altro):
            if nn[0] is not g_seg:
                return True
        pt = pos[altro]
        for gq, q in quads:
            if gq is g_seg or gq in escludi:
                continue
            if _in_quad((pt[0], pt[1]), q, 5e-3):
                return True
        return False

    mosso, coda = {}, []

    def muovi(nodo, v):
        for nn in giunto(nodo):
            if nn not in mosso:
                mosso[nn] = v
                coda.append(nn)

    for nodo, v in iniz.items():
        muovi(nodo, v)
    guardia = 0
    while coda and guardia < 20000:
        guardia += 1
        nn = coda.pop(0)
        v = mosso[nn]
        ln = math.hypot(v[0], v[1])
        if ln < 1e-9:
            continue
        vh = (v[0] / ln, v[1] / ln)
        g = nn[0]
        if g in escludi:
            continue
        altro = (g, "b" if nn[1] == "a" else "a")
        if altro in mosso:
            continue
        p0, p1 = pos[nn], pos[altro]
        ex, ey = p1[0] - p0[0], p1[1] - p0[1]
        le = math.hypot(ex, ey)
        if le < 1e-9:
            continue
        e = (ex / le, ey / le)
        dot = abs(vh[0] * e[0] + vh[1] * e[1])
        cr = abs(vh[0] * e[1] - vh[1] * e[0])
        if dot < PAR:
            muovi(altro, v)
        elif cr < PAR:
            if not attaccato(altro):
                muovi(altro, v)
    return mosso


def _apply_moves(scene, walls, mosso):
    by_w = {w.g: w for w in walls}
    per_g = {}
    for (g, e), v in mosso.items():
        if g in by_w:
            per_g.setdefault(g, {})[e] = v
    new = {}
    for g, ends in per_g.items():
        w = by_w[g]
        pa, pb = w.a, w.b
        if "a" in ends:
            pa = (pa[0] + ends["a"][0], pa[1] + ends["a"][1])
        if "b" in ends:
            pb = (pb[0] + ends["b"][0], pb[1] + ends["b"][1])
        if _dist2(pa, pb) < 1e-3:
            return False
        new[g] = {"a": pa, "b": pb}

    def world_end(w, e):
        n = new.get(w.g)
        return n[e] if n else w.node(e)

    chains = {by_w[g].d.get("chain") for g in new} - {None}
    touched = set(new)
    for w in walls:
        if w.d.get("chain") in chains:
            touched.add(w.g)
    for g in touched:
        w = by_w[g]
        d = w.d
        extra = {}
        n = new.get(g)
        if n:
            extra["a"] = list(w.local(n["a"][0], n["a"][1], w.z0))
            extra["b"] = list(w.local(n["b"][0], n["b"][1], w.z0))
        if d.get("th_b") is None and d.get("chain"):
            for key, e, other_e in (("prev", "a", "b"), ("next", "b", "a")):
                me = world_end(w, e)
                found = None
                for o in walls:
                    if o is w or o.d.get("chain") != d.get("chain"):
                        continue
                    for oe in ("a", "b"):
                        if _dist2(world_end(o, oe), me) < TOL:
                            oo = world_end(o, "b" if oe == "a" else "a")
                            found = list(w.local(oo[0], oo[1], w.z0))
                            break
                    if found:
                        break
                extra[key] = found
        muri.rebuild_wall(g, d["th"], d["h"], extra)
    return True


class _Edit(QLineEdit):

    def __init__(self, parent, ctl) -> None:
        super().__init__(parent)
        self.ctl = ctl

    def event(self, ev) -> bool:
        if ev.type() == QEvent.KeyPress and ev.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            self.ctl.toggle_end()
            ev.accept()
            return True
        return super().event(ev)

    def keyPressEvent(self, ev) -> None:
        if ev.key() == Qt.Key_Escape:
            self.ctl.cancel_edit()
        else:
            super().keyPressEvent(ev)

    def focusOutEvent(self, ev) -> None:
        super().focusOutEvent(ev)
        QTimer.singleShot(0, self.ctl.cancel_edit)


class _Overlay(QWidget):
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


class _Filter(QObject):
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
                if self.ctl.edit is not None:
                    return False
                hit = self.ctl.hit(ev.position())
                if hit is not None:
                    self._swallow = True
                    self.ctl.begin_edit(*hit)
                    return True
            elif t == QEvent.MouseButtonRelease and self._swallow:
                self._swallow = False
                return True
        return False


class _Quote:
    def __init__(self, vp) -> None:
        self.vp = vp
        self.rects = []
        self.edit = None
        self.field = None
        self.overlay = _Overlay(vp, self)
        self.filter = _Filter(self)
        vp.installEventFilter(self.filter)
        self._sig = None
        self.timer = QTimer(vp)
        self.timer.timeout.connect(self._tick)
        self.timer.start(80)

    def _active(self) -> bool:
        if not ENABLED:
            return False
        for n in ("active_tool", "tool", "_tool", "current_tool"):
            t = getattr(self.vp, n, None)
            if t is not None:
                nm = (str(getattr(t, "name", "")) or type(t).__name__).lower()
                return not any(k in nm for k in NO_QUOTES_TOOLS)
        return True

    def _tick(self) -> None:
        try:
            sc = self.vp.scene
            sel = tuple(id(g) for g in muri._selected_walls(sc))
            probe = []
            for v in ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)):
                px = self.vp._world_to_pixel(QVector3D(*v))
                probe.append(None if px is None else
                             (round(px[0], 1), round(px[1], 1)))
            sig = (sel, getattr(sc, "version", 0), tuple(probe),
                   self._active(), self.edit is not None)
        except Exception:
            return
        if sig != self._sig:
            self._sig = sig
            self.overlay.update()

    def px(self, x, y, z):
        return self.vp._world_to_pixel(QVector3D(x, y, z))

    def draw(self, p: QPainter) -> None:
        self.rects = []
        if not self._active():
            return
        sc = self.vp.scene
        sel = muri._selected_walls(sc)
        if not sel:
            return
        walls = _walls(sc)
        by_g = {w.g: w for w in walls}
        font = QFont()
        font.setPointSize(10)
        p.setFont(font)
        fm = p.fontMetrics()

        def chip(text, cx, cy, bg, fg=QColor(255, 255, 255)):
            w, h = fm.horizontalAdvance(text) + 12, fm.height() + 6
            r = QRectF(cx - w / 2, cy - h / 2, w, h)
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(r, 4, 4)
            p.setPen(QPen(fg))
            p.drawText(r, Qt.AlignCenter, text)
            return r

        for g in sel[:12]:
            w = by_g.get(g)
            if w is None:
                continue
            ref, out = _lengths_local(w.d)
            z = w.zt
            if w.d.get("align") == "right":
                o0, o1 = w.aL, w.bL
            else:
                o0, o1 = w.aR, w.bR
            mr = self.px((w.a[0] + w.b[0]) / 2, (w.a[1] + w.b[1]) / 2, z)
            mo = self.px((o0[0] + o1[0]) / 2, (o0[1] + o1[1]) / 2, z)
            if mr is None or mo is None:
                continue
            vx, vy = mr[0] - mo[0], mr[1] - mo[1]
            ln = math.hypot(vx, vy)
            if ln < 1.0:
                pa, pb = self.px(w.a[0], w.a[1], z), self.px(w.b[0], w.b[1], z)
                if pa is None or pb is None:
                    continue
                tx, ty = pb[0] - pa[0], pb[1] - pa[1]
                vx, vy = -ty, tx
                ln = math.hypot(vx, vy) or 1.0
            vx, vy = vx / ln, vy / ln
            for lato, pos, val, col in (
                    ("INT", (mr[0] + vx * 16, mr[1] + vy * 16), ref, C_INT),
                    ("EST", (mo[0] - vx * 16, mo[1] - vy * 16), out, C_EST)):
                txt = fmt_len(val)
                ed = self.edit
                if ed and ed["g"] is g and ed["lato"] == lato:
                    txt, col = txt + "  ⇥", C_EDIT
                r = chip(txt, pos[0], pos[1], col)
                self.rects.append((r, g, lato))
            for lato, o, dr, t in _distanze(w, walls):
                p0 = self.px(o[0], o[1], z)
                p1 = self.px(o[0] + dr[0] * t, o[1] + dr[1] * t, z)
                if p0 is None or p1 is None:
                    continue
                p.setPen(QPen(C_DIST, 1.5))
                p.drawLine(QPointF(p0[0], p0[1]), QPointF(p1[0], p1[1]))
                sx, sy = p1[0] - p0[0], p1[1] - p0[1]
                sl = math.hypot(sx, sy)
                nx, ny = (-sy / sl * 6, sx / sl * 6) if sl > 1e-3 else (0, 6)
                for q in (p0, p1):
                    p.drawLine(QPointF(q[0] + nx, q[1] + ny),
                               QPointF(q[0] - nx, q[1] - ny))
                col = C_DIST.darker(170)
                ed = self.edit
                if ed and ed["g"] is g and ed["lato"] == lato:
                    col = C_EDIT
                r = chip(fmt_len(t), (p0[0] + p1[0]) / 2,
                         (p0[1] + p1[1]) / 2, col)
                self.rects.append((r, g, lato))
        self._draw_arrow(p, by_g)

    def _draw_arrow(self, p, by_g) -> None:
        ed = self.edit
        if not ed or ed["lato"] not in ("INT", "EST"):
            return
        w = by_g.get(ed["g"])
        if w is None:
            return
        e = ed["end"]
        pt = w.node(e)
        o = w.node("a" if e == "b" else "b")
        ux, uy = pt[0] - o[0], pt[1] - o[1]
        L = math.hypot(ux, uy)
        if L < 1e-9:
            return
        ux, uy = ux / L, uy / L
        s0 = self.px(pt[0], pt[1], w.zt)
        s1 = self.px(pt[0] + ux * 0.5, pt[1] + uy * 0.5, w.zt)
        if s0 is None or s1 is None:
            return
        vx, vy = s1[0] - s0[0], s1[1] - s0[1]
        n = math.hypot(vx, vy)
        if n < 1e-3:
            return
        vx, vy = vx / n, vy / n
        tip = (s0[0] + vx * 48, s0[1] + vy * 48)
        p.setPen(QPen(QColor(255, 204, 0), 3))
        p.drawLine(QPointF(s0[0] + vx * 6, s0[1] + vy * 6),
                   QPointF(*tip))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 204, 0))
        p.drawPolygon(QPolygonF([
            QPointF(tip[0] + vx * 12, tip[1] + vy * 12),
            QPointF(tip[0] - vy * 7, tip[1] + vx * 7),
            QPointF(tip[0] + vy * 7, tip[1] - vx * 7)]))

    def hit(self, pos):
        x, y = pos.x(), pos.y()
        for r, g, lato in self.rects:
            if r.contains(x, y):
                return g, lato, r
        return None

    def begin_edit(self, g, lato, rect) -> None:
        sc = self.vp.scene
        walls = _walls(sc)
        w = next((q for q in walls if q.g is g), None)
        if w is None:
            return
        end = "b"
        if not _joined(w, "a", walls) and _joined(w, "b", walls):
            end = "a"
        st = {"g": g, "lato": lato, "end": end, "dist": None}
        if lato.startswith("D_"):
            for lt, o, dr, t in _distanze(w, walls):
                if lt == lato:
                    st["dist"] = (t, dr)
            if st["dist"] is None:
                self.vp.flash_status(tr("Quota non più valida: riprova"), 3000)
                return
            cur = st["dist"][0]
        else:
            ref, out = _lengths_local(w.d)
            cur = ref if lato == "INT" else out
        self.edit = st
        f = _Edit(self.vp, self)
        f.setText(_imperial.fmt(cur) if _imperial.imperial() else "%.3f" % cur)
        f.setFixedWidth(max(90, int(rect.width()) + 20))
        f.move(int(rect.center().x() - f.width() / 2),
               int(rect.center().y() - f.height() / 2))
        f.returnPressed.connect(self.commit)
        f.show()
        f.raise_()
        f.setFocus()
        f.selectAll()
        self.field = f
        self.vp.flash_status(
            tr("Nuovo valore (m) · Invio = conferma · Esc = annulla").replace(
                _imperial.METRES_MARK,
                _imperial.IMPERIAL_MARK if _imperial.imperial() else _imperial.METRES_MARK)
            + ("" if lato.startswith("D_") else tr(" · Tab = cambia estremo")),
            8000)
        self.overlay.update()

    def toggle_end(self) -> None:
        if self.edit and not self.edit["lato"].startswith("D_"):
            self.edit["end"] = "a" if self.edit["end"] == "b" else "b"
            self.overlay.update()

    def cancel_edit(self) -> None:
        if self.edit is None:
            return
        self.edit = None
        f, self.field = self.field, None
        if f is not None:
            f.hide()
            f.deleteLater()
        self.overlay.update()
        self.vp.update()

    def commit(self) -> None:
        ed = self.edit
        if ed is None or self.field is None:
            return
        value = _imperial.parse(self.field.text())
        if value is None:
            self.vp.flash_status(tr("Digita un numero e premi Invio"), 3000)
            self.cancel_edit()
            return
        self.cancel_edit()
        if value < 0 or (not ed["lato"].startswith("D_") and value < 1e-3):
            self.vp.flash_status(tr("Valore non valido"), 3000)
            return
        try:
            ok = self._apply(ed, value)
        except Exception as exc:
            self.vp.flash_status(tr("Quote muri: ") + str(exc), 5000)
            return
        if not ok:
            self.vp.flash_status(
                tr("Spostamento non eseguito: un muro collegato si annullerebbe"),
                5000)

    def _apply(self, ed, value) -> bool:
        sc = self.vp.scene
        walls = _walls(sc)
        w = next((q for q in walls if q.g is ed["g"]), None)
        if w is None:
            return False
        lato = ed["lato"]
        ux, uy = w.b[0] - w.a[0], w.b[1] - w.a[1]
        L = math.hypot(ux, uy)
        if L < 1e-6:
            return False
        u = (ux / L, uy / L)
        if lato.startswith("D_"):
            cur = None
            for lt, o, dr, t in _distanze(w, walls):
                if lt == lato:
                    cur, dirv = t, dr
            if cur is None:
                return False
            k = cur - value
            mv = (dirv[0] * k, dirv[1] * k)
            iniz = {(w.g, "a"): mv, (w.g, "b"): mv}
        else:
            ref, out = _lengths_local(w.d)
            cur = ref if lato == "INT" else out
            delta = value - cur
            e = ed["end"]
            sgn = 1.0 if e == "b" else -1.0
            for _ in range(8):
                mv = (u[0] * delta * sgn, u[1] * delta * sgn)
                err = value - _value_after(w, e, mv, lato)
                if abs(err) < 1e-6:
                    break
                delta += err
            mv = (u[0] * delta * sgn, u[1] * delta * sgn)
            iniz = {(w.g, e): mv}
        mosso = _propaga(walls, iniz, {w.g})
        result = {"ok": False}

        def mutate(scene):
            result["ok"] = _apply_moves(scene, walls, mosso)
            if not result["ok"]:
                raise ValueError(tr("muro di lunghezza nulla"))

        try:
            self.vp.history.execute(muri.MuriCommand(mutate))
        except Exception:
            return False
        if getattr(self.vp.history, "last_error", None):
            return False
        try:
            from . import finestre
            finestre.update_openings(sc)
        except Exception:
            pass
        self.vp.notify_scene_changed()
        self.vp.update()
        self.overlay.update()
        return True


_CTL = {"ctl": None}


def register(api) -> None:
    vp = api.window.viewport
    if _CTL["ctl"] is None:
        _CTL["ctl"] = _Quote(vp)
    app = api.app
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is None:
        return

    def toggle(on) -> None:
        global ENABLED
        ENABLED = bool(on)
        if _CTL["ctl"] is not None:
            _CTL["ctl"].overlay.update()

    def context(menu, selection) -> None:
        if not muri._selected_walls(app.viewport.scene):
            return
        act = menu.addAction(tr("Quote temporanee muri"))
        act.setCheckable(True)
        act.setChecked(ENABLED)
        act.toggled.connect(toggle)

    add_ctx(context)
