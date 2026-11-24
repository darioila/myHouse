# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._scroll import scroll_form
from ._lingua import tr
from ._imperial import LengthSpin

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPen, QVector3D
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QVBoxLayout,
)

from core import bim
from . import _ifc
from tools.base import Tool, ToolContext

from . import muri

ORDER = 43
LAYER_NAME = "Volte"
KEY = "myhouse_volta"
COLOR_VOLTA = (0.85, 0.82, 0.76)
SEG_ARCO = 24
SEG_LUNGHEZZA = 8
SEG_GUSCIO = 48

TIPI = (
    ("BOTTE", tr("Volta a botte")),
    ("VELA", tr("Volta a vela")),
    ("CROCIERA", tr("Volta a crociera")),
    ("PADIGLIONE", tr("Volta a padiglione")),
)


class _Settings:
    tipo = "BOTTE"
    lato = 0
    z = 3.0
    sp = 0.15
    dentro = False
    ortho = True


class V:
    __slots__ = ("x", "y", "z")

    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = x, y, z

    def __add__(self, o):
        return V(self.x + o.x, self.y + o.y, self.z + o.z)

    def __sub__(self, o):
        return V(self.x - o.x, self.y - o.y, self.z - o.z)

    def __mul__(self, k):
        return V(self.x * k, self.y * k, self.z * k)

    def lerp(self, o, t):
        return V(self.x + (o.x - self.x) * t, self.y + (o.y - self.y) * t,
                 self.z + (o.z - self.z) * t)

    @property
    def length(self):
        return math.sqrt(self.x ** 2 + self.y ** 2 + self.z ** 2)

    def normalized(self):
        L = self.length
        return V(self.x / L, self.y / L, self.z / L) if L > 0 else V()


def _genera_botte(punti, lato, spessore):
    p = list(punti)
    k = int(lato) % 4
    p0, p1, p2, p3 = p[k], p[(k + 1) % 4], p[(k + 2) % 4], p[(k + 3) % 4]
    nS, nA = SEG_LUNGHEZZA, SEG_ARCO
    sp = spessore
    verts = []
    for i in range(nS + 1):
        s = i / nS
        a = p0.lerp(p1, s)
        b = p3.lerp(p2, s)
        c = (a + b) * 0.5
        e1 = V(a.x - c.x, a.y - c.y, 0.0)
        r = e1.length
        if r < 0.01:
            return None
        e1 = e1.normalized()
        for rr in ((r, r + sp) if sp >= 0.0 else (max(r + sp, 0.005), r)):
            for j in range(nA + 1):
                t = math.pi * j / nA
                verts.append(c + e1 * (rr * math.cos(t)) + V(0.0, 0.0, rr * math.sin(t)))
    n1 = nA + 1
    base = lambda i: i * 2 * n1
    inn = lambda i, j: base(i) + j
    out = lambda i, j: base(i) + n1 + j
    facce = []
    for i in range(nS):
        for j in range(nA):
            facce.append((inn(i, j), inn(i + 1, j), inn(i + 1, j + 1), inn(i, j + 1)))
            facce.append((out(i, j), out(i + 1, j), out(i + 1, j + 1), out(i, j + 1)))
    for i in (0, nS):
        for j in range(nA):
            facce.append((inn(i, j), inn(i, j + 1), out(i, j + 1), out(i, j)))
    for j in (0, nA):
        for i in range(nS):
            facce.append((inn(i, j), out(i, j), out(i + 1, j), inn(i + 1, j)))
    return verts, facce


def _shell(p, hfun, modo, n, sp):
    zb = (p[0].z + p[1].z + p[2].z + p[3].z) * 0.25
    S = [(1.0 - math.cos(math.pi * i / n)) * 0.5 for i in range(n + 1)]
    verts, facce, perimetri = [], [], []

    def pos(s, t):
        return p[0].lerp(p[1], s).lerp(p[3].lerp(p[2], s), t)

    def combina(ha, hb):
        if modo == 'min':
            return min(ha, hb)
        if modo == 'max':
            return max(ha, hb)
        return ha

    def u_bordo(i, j):
        if j == 0:
            return S[i]
        if i == n:
            return 1.0 + S[j]
        if j == n:
            return 2.0 + (1.0 - S[i])
        return 3.0 + (1.0 - S[j])

    for add in ((0.0, sp) if sp >= 0.0 else (sp, 0.0)):
        idx = [[0] * (n + 1) for _ in range(n + 1)]
        D = [[0.0] * (n + 1) for _ in range(n + 1)]
        for i in range(n + 1):
            for j in range(n + 1):
                s, t = S[i], S[j]
                q = pos(s, t)
                ha, hb = hfun(s, t, add)
                verts.append(V(q.x, q.y, zb + combina(ha, hb)))
                idx[i][j] = len(verts) - 1
                D[i][j] = ha - hb
        peri = [(u_bordo(i, j), idx[i][j]) for i in range(n + 1) for j in range(n + 1)
                if i in (0, n) or j in (0, n)]
        if modo == 'vela':
            for i in range(n):
                for j in range(n):
                    facce.append((idx[i][j], idx[i + 1][j], idx[i + 1][j + 1], idx[i][j + 1]))
        else:
            cross = {}

            def incrocio(a, b):
                key = (a, b) if a < b else (b, a)
                if key in cross:
                    return cross[key]
                da, db = D[a[0]][a[1]], D[b[0]][b[1]]
                lam = da / (da - db)
                s = S[a[0]] + lam * (S[b[0]] - S[a[0]])
                t = S[a[1]] + lam * (S[b[1]] - S[a[1]])
                q = pos(s, t)
                ha, hb = hfun(s, t, add)
                verts.append(V(q.x, q.y, zb + combina(ha, hb)))
                k = len(verts) - 1
                cross[key] = k
                if a[0] == b[0] and a[0] in (0, n) or a[1] == b[1] and a[1] in (0, n):
                    if a[1] == 0 and b[1] == 0:
                        u = s
                    elif a[0] == n and b[0] == n:
                        u = 1.0 + t
                    elif a[1] == n and b[1] == n:
                        u = 2.0 + (1.0 - s)
                    else:
                        u = 3.0 + (1.0 - t)
                    peri.append((u, k))
                return k

            def triangolo(tri):
                sg = [1 if D[a][b] > 1e-9 else (-1 if D[a][b] < -1e-9 else 0) for a, b in tri]
                if not (1 in sg and -1 in sg):
                    facce.append(tuple(idx[a][b] for a, b in tri))
                    return
                P, N = [], []
                for k in range(3):
                    a, b = tri[k], tri[(k + 1) % 3]
                    sa, sb = sg[k], sg[(k + 1) % 3]
                    v = idx[a[0]][a[1]]
                    if sa >= 0:
                        P.append(v)
                    if sa <= 0:
                        N.append(v)
                    if sa * sb < 0:
                        c = incrocio(a, b)
                        P.append(c)
                        N.append(c)
                for poly in (P, N):
                    for k in range(1, len(poly) - 1):
                        facce.append((poly[0], poly[k], poly[k + 1]))

            for i in range(n):
                for j in range(n):
                    sc = (S[i] + S[i + 1]) * 0.5
                    tc = (S[j] + S[j + 1]) * 0.5
                    if abs(sc - tc) <= abs(sc + tc - 1.0):
                        triangolo([(i, j), (i + 1, j), (i + 1, j + 1)])
                        triangolo([(i, j), (i + 1, j + 1), (i, j + 1)])
                    else:
                        triangolo([(i, j), (i + 1, j), (i, j + 1)])
                        triangolo([(i + 1, j), (i + 1, j + 1), (i, j + 1)])
        peri.sort()
        perimetri.append(peri)
    A, B = perimetri
    la, lb = len(A), len(B)
    ia = ib = 0
    while ia < la or ib < lb:
        avanza_a = False
        if ia < la:
            ua_n = A[ia + 1][0] if ia + 1 < la else 4.0
            ub_n = (B[ib + 1][0] if ib + 1 < lb else 4.0) if ib < lb else 9.0
            avanza_a = ib >= lb or ua_n <= ub_n
        if avanza_a:
            facce.append((A[ia % la][1], A[(ia + 1) % la][1], B[ib % lb][1]))
            ia += 1
        else:
            facce.append((A[ia % la][1], B[(ib + 1) % lb][1], B[ib % lb][1]))
            ib += 1
    return verts, facce


def _quad_offset(p, d):
    if abs(d) < 1e-9:
        return list(p)
    ar = sum(p[k].x * p[(k + 1) % 4].y - p[(k + 1) % 4].x * p[k].y for k in range(4))
    sg = 1.0 if ar >= 0 else -1.0
    rette = []
    for k in range(4):
        a, b = p[k], p[(k + 1) % 4]
        ex, ey = b.x - a.x, b.y - a.y
        ln = math.hypot(ex, ey)
        if ln < 1e-9:
            return list(p)
        nx, ny = sg * ey / ln, -sg * ex / ln
        rette.append((a.x + nx * d, a.y + ny * d, ex, ey))
    out = []
    for k in range(4):
        x1, y1, dx1, dy1 = rette[(k - 1) % 4]
        x2, y2, dx2, dy2 = rette[k]
        den = dx1 * dy2 - dy1 * dx2
        if abs(den) < 1e-9:
            return list(p)
        tt = ((x2 - x1) * dy2 - (y2 - y1) * dx2) / den
        out.append(V(x1 + dx1 * tt, y1 + dy1 * tt, p[k].z))
    return out


def _genera_vela(p, n, spessore):
    c = (p[0] + p[1] + p[2] + p[3]) * 0.25
    R = max(math.hypot(q.x - c.x, q.y - c.y) for q in p)
    if R < 0.01:
        return None

    def hfun(s, t, add):
        q = p[0].lerp(p[1], s).lerp(p[3].lerp(p[2], s), t)
        d2 = (q.x - c.x) ** 2 + (q.y - c.y) ** 2
        return math.sqrt(max((R + add) ** 2 - d2, 0.0)), 0.0

    return _shell(p, hfun, 'vela', n, spessore)


def _genera_crociera(p, n, padiglione, spessore):
    for k in range(4):
        a, b = p[k], p[(k + 1) % 4]
        if math.hypot(a.x - b.x, a.y - b.y) < 0.02:
            return None

    def hfun(s, t, add):
        a = p[0].lerp(p[1], s)
        b = p[3].lerp(p[2], s)
        c = p[0].lerp(p[3], t)
        d = p[1].lerp(p[2], t)
        ca = math.hypot(b.x - a.x, b.y - a.y)
        cb = math.hypot(d.x - c.x, d.y - c.y)
        ra, ua = ca / 2 + add, (t - 0.5) * ca
        rb, ub = cb / 2 + add, (s - 0.5) * cb
        return (math.sqrt(max(ra * ra - ua * ua, 0.0)), math.sqrt(max(rb * rb - ub * ub, 0.0)))

    return _shell(p, hfun, 'min' if padiglione else 'max', n, spessore)


def _orienta(verts, facce):
    fs = [list(f) for f in facce if len(set(f)) == len(f) and len(f) >= 3]
    lati = {}
    for fi, f in enumerate(fs):
        for k in range(len(f)):
            a, b = f[k], f[(k + 1) % len(f)]
            lati.setdefault((min(a, b), max(a, b)), []).append(fi)
    vicini = [[] for _ in fs]
    for fl in lati.values():
        if len(fl) == 2:
            vicini[fl[0]].append(fl[1])
            vicini[fl[1]].append(fl[0])

    def dirigge(f, a, b):
        for k in range(len(f)):
            if f[k] == a and f[(k + 1) % len(f)] == b:
                return 1
            if f[k] == b and f[(k + 1) % len(f)] == a:
                return -1
        return 0

    visto = [False] * len(fs)
    for s0 in range(len(fs)):
        if visto[s0]:
            continue
        visto[s0] = True
        pila = [s0]
        while pila:
            fi = pila.pop()
            for fj in vicini[fi]:
                if visto[fj]:
                    continue
                comuni = set(fs[fi]) & set(fs[fj])
                if len(comuni) >= 2:
                    a, b = sorted(comuni)[:2]
                    for k in range(len(fs[fi])):
                        x, y = fs[fi][k], fs[fi][(k + 1) % len(fs[fi])]
                        if x in comuni and y in comuni:
                            a, b = x, y
                            break
                    if dirigge(fs[fi], a, b) == dirigge(fs[fj], a, b):
                        fs[fj].reverse()
                visto[fj] = True
                pila.append(fj)
    vol = 0.0
    for f in fs:
        v0 = verts[f[0]]
        for k in range(1, len(f) - 1):
            v1, v2 = verts[f[k]], verts[f[k + 1]]
            vol += (v0.x * (v1.y * v2.z - v1.z * v2.y)
                    - v0.y * (v1.x * v2.z - v1.z * v2.x)
                    + v0.z * (v1.x * v2.y - v1.y * v2.x))
    if vol < 0:
        for f in fs:
            f.reverse()
    return fs


def volta_geometria(d):
    z = float(d["z"])
    sp = max(float(d["sp"]), 0.005)
    p = [V(float(x), float(y), z) for x, y in d["pts"]]
    if d.get("dentro"):
        sp = -sp
    else:
        p = _quad_offset(p, sp)
        sp = -sp
    tipo = d.get("tipo", "BOTTE")
    if tipo == "BOTTE":
        ris = _genera_botte(p, int(d.get("lato", 0)), sp)
    elif tipo == "VELA":
        ris = _genera_vela(p, SEG_GUSCIO, sp)
    elif tipo == "CROCIERA":
        ris = _genera_crociera(p, SEG_GUSCIO, False, sp)
    else:
        ris = _genera_crociera(p, SEG_GUSCIO, True, sp)
    if ris is None:
        return None
    verts, facce = ris
    return verts, _orienta(verts, facce)


def volta_mesh(d):
    from core.mesh import Mesh
    ris = volta_geometria(d)
    if ris is None:
        return None
    verts, facce = ris
    mesh = Mesh()
    for f in facce:
        fc = mesh.add_face([QVector3D(verts[i].x, verts[i].y, verts[i].z) for i in f])
        fc.attrs["layer"] = LAYER_NAME
        muri.paint_face(fc, d.get("col", COLOR_VOLTA), d.get("tex"))
    _nascondi_spigoli_lisci(mesh, verts, facce)
    return mesh


def _nascondi_spigoli_lisci(mesh, verts, facce, soglia_gradi=35.0) -> None:
    def key(x, y, z):
        return (round(x, 4), round(y, 4), round(z, 4))

    def normale(f):
        nx = ny = nz = 0.0
        for i in range(len(f)):
            a, b = verts[f[i]], verts[f[(i + 1) % len(f)]]
            nx += (a.y - b.y) * (a.z + b.z)
            ny += (a.z - b.z) * (a.x + b.x)
            nz += (a.x - b.x) * (a.y + b.y)
        ln = math.sqrt(nx * nx + ny * ny + nz * nz)
        return (nx / ln, ny / ln, nz / ln) if ln > 1e-12 else None

    lati = {}
    for f in facce:
        nm = normale(f)
        for i in range(len(f)):
            a, b = verts[f[i]], verts[f[(i + 1) % len(f)]]
            k = frozenset((key(a.x, a.y, a.z), key(b.x, b.y, b.z)))
            lati.setdefault(k, []).append(nm)
    cmin = math.cos(math.radians(soglia_gradi))
    nascosti = set()
    for k, ns in lati.items():
        if len(ns) == 2 and ns[0] and ns[1]:
            dot = sum(p * q for p, q in zip(ns[0], ns[1]))
            if abs(dot) >= cmin:
                nascosti.add(k)
    flag = getattr(muri, "EDGE_FLAG", "hidden")
    for e in mesh.edges:
        try:
            k = frozenset((key(e.a.x(), e.a.y(), e.a.z()),
                           key(e.b.x(), e.b.y(), e.b.z())))
            if k in nascosti:
                setattr(e, flag, True)
        except Exception:
            pass


def volta_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "pts" in data else None


def _volta_part(d):
    from core.group import Group
    m = volta_mesh(d)
    if m is None:
        return None
    part = Group(m, name=tr("Volta"))
    part.component = False
    return part


def rebuild_volta(group, d) -> bool:
    part = _volta_part(d)
    if part is None:
        return False
    group.children = [part]
    _ifc.tag(group, "IfcSlab")
    ext = dict(group.ext or {})
    ext[KEY] = dict(d)
    group.ext = ext
    return True


def build_volta(scene, d, name) -> bool:
    from core.group import Group
    part = _volta_part(d)
    if part is None:
        return False
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    g = Group(name=name)
    g.adopt([part])
    g.component = False
    g.layer = LAYER_NAME
    try:
        _ifc.tag(g, "IfcSlab", name)
    except Exception:
        try:
            _ifc.tag(g, "IfcBuildingElementProxy", name)
        except Exception:
            pass
    g.ext = {KEY: d}
    scene.groups.append(g)
    return True


def _spin(value, lo, hi):
    s = LengthSpin()
    s.setDecimals(3)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


def _dim_grande(p, x1, y1, x2, y2, txt, lato=1):
    p.setPen(QPen(muri._C_QUOTA, 1.3))
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    w = 8 * len(txt) + 2
    if abs(y1 - y2) < 1e-6:
        for x in (x1, x2):
            p.drawLine(QPointF(x, y1 - 3), QPointF(x, y1 + 3))
        muri._t(p, (x1 + x2) / 2 - w / 2, y1 + (-5 if lato > 0 else 14), txt, muri._C_QUOTA, 14, True)
    else:
        for y in (y1, y2):
            p.drawLine(QPointF(x1 - 3, y), QPointF(x1 + 3, y))
        muri._t(p, x1 + (6 if lato > 0 else -w - 4), (y1 + y2) / 2 + 5, txt, muri._C_QUOTA, 14, True)


def _disegno_volta(p):
    r, t, dim, ext = muri._r, muri._t, _dim_grande, muri._ext
    from PySide6.QtGui import QPainterPath
    from PySide6.QtGui import QPolygonF
    q, line = muri._C_QUOTA, muri._C_LINEA
    t(p, 10, 12, tr("Botte: sezione"), size=12)
    p.setPen(QPen(line, 1.5))
    p.drawLine(QPointF(10, 150), QPointF(200, 150))
    muri._hatch(p, 10, 150, 200, 156)
    r(p, 44, 100, 64, 150, muri._C_CORPO)
    r(p, 156, 100, 176, 150, muri._C_CORPO)
    cx, cy, R, ri = 110.0, 100.0, 60.0, 52.0
    path = QPainterPath()
    path.moveTo(cx - R, cy)
    path.arcTo(QRectF(cx - R, cy - R, 2 * R, 2 * R), 180, -180)
    path.lineTo(cx + ri, cy)
    path.arcTo(QRectF(cx - ri, cy - ri, 2 * ri, 2 * ri), 0, 180)
    path.closeSubpath()
    p.setPen(QPen(line, 1.2))
    p.setBrush(muri._C_LEGNO)
    p.drawPath(path)
    pen = QPen(line, 1)
    pen.setStyle(Qt.DashDotLine)
    p.setPen(pen)
    p.drawLine(QPointF(30, 100), QPointF(190, 100))
    t(p, 84, 118, tr("imposta"), size=11)
    ext(p, 32, 100, 44, 100)
    dim(p, 32, 100, 32, 150, "z", -1)
    dim(p, 110, 40, 110, 48, "s", 1)
    t(p, 225, 12, tr("Pianta"), size=12)
    P = [(240, 124), (360, 114), (372, 52), (250, 44)]
    p.setPen(QPen(line, 1.2))
    p.setBrush(muri._C_CORPO)
    p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in P]))
    pen = QPen(line, 1)
    pen.setStyle(Qt.DashLine)
    p.setPen(pen)
    for u in (0.25, 0.5, 0.75):
        a = (P[0][0] + u * (P[3][0] - P[0][0]), P[0][1] + u * (P[3][1] - P[0][1]))
        b = (P[1][0] + u * (P[2][0] - P[1][0]), P[1][1] + u * (P[2][1] - P[1][1]))
        p.drawLine(QPointF(*a), QPointF(*b))
    for k, (x, y) in enumerate(P):
        dx = -12 if x < 300 else 6
        dy = 12 if y > 90 else -4
        t(p, x + dx, y + dy, str(k + 1), muri._C_QUOTA, 14, True)
    t(p, 272, 142, tr("Lato 1"), size=11)
    t(p, 394, 88, tr("Lato 2"), size=11)
    t(p, 225, 166, tr("la botte corre lungo il lato scelto"), size=11)


def ask_volta(parent, cur: dict, title=None):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title or tr("Volta"))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    form.addRow(muri._Schema(_disegno_volta))
    tipo = QComboBox()
    for k, nome in TIPI:
        tipo.addItem(nome, k)
    tipo.setCurrentIndex(max(0, tipo.findData(cur.get("tipo", "BOTTE"))))
    lato = QComboBox()
    lato.addItem(tr("Lato 1"), 0)
    lato.addItem(tr("Lato 2"), 1)
    lato.setCurrentIndex(0 if int(cur.get("lato", 0)) % 4 < 1 else 1)
    z = _spin(cur["z"], -100.0, 1000.0)
    sp = _spin(cur["sp"], 0.005, 5.0)
    dentro = QCheckBox(tr("Spessore verso l'interno (la superficie tracciata resta l'esterno)"))
    dentro.setChecked(bool(cur.get("dentro")))
    form.addRow(tr("Tipo di volta"), tipo)
    form.addRow(tr("Lato su cui si sviluppa (botte)"), lato)
    form.addRow(tr("Altezza da terra, quota d'imposta (z) (m)"), z)
    form.addRow(tr("Spessore (s) (m)"), sp)
    form.addRow(dentro)
    scroll_form(dlg, lay, form)

    def on_tipo(_i=None):
        lato.setEnabled(tipo.currentData() == "BOTTE")
    tipo.currentIndexChanged.connect(on_tipo)
    on_tipo()
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return None
    return {"tipo": tipo.currentData(), "lato": lato.currentData(),
            "z": z.value(), "sp": sp.value(), "dentro": dentro.isChecked()}


class VoltaTool(Tool):
    name = tr("Volta")
    shortcut = None
    description = tr("Crea una volta (botte, vela, crociera, padiglione) su 4 punti.")

    def __init__(self) -> None:
        self._entering = False
        self.points: list[tuple[float, float]] = []
        self.hover = None

    def on_activate(self, viewport) -> None:
        self._scene = viewport.scene
        if self._entering:
            self.points, self.hover = [], None
            viewport.flash_status(
                tr("Clicca i 4 punti della volta · O = ortogonale · "
                   "Backspace = annulla punto · Esc = esci"), 7000)
            return
        cur = {"tipo": _Settings.tipo, "lato": _Settings.lato, "z": _Settings.z,
               "sp": _Settings.sp, "dentro": _Settings.dentro}
        res = ask_volta(viewport.window(), cur)
        if res is None:
            return
        _Settings.tipo, _Settings.lato = res["tipo"], res["lato"]
        _Settings.z, _Settings.sp, _Settings.dentro = res["z"], res["sp"], res["dentro"]
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def on_deactivate(self, viewport) -> None:
        self.points, self.hover = [], None

    def on_cancel(self, viewport) -> None:
        self.points, self.hover = [], None
        viewport.update()

    def _exit(self, viewport) -> None:
        self.points, self.hover = [], None
        viewport.update()
        back = getattr(viewport.window(), "activate_select_tool", None)
        if callable(back):
            back()

    def context_menu(self, viewport, pos) -> bool:
        if self.points:
            self.points = []
            viewport.update()
        else:
            self._exit(viewport)
        return True

    def claims_key(self, key: int, modifiers) -> bool:
        if modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        return key in (Qt.Key_Escape, Qt.Key_O, Qt.Key_F8) or (
            key == Qt.Key_Backspace and bool(self.points))

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if key in (Qt.Key_O, Qt.Key_F8):
            _Settings.ortho = not _Settings.ortho
            viewport.flash_status(
                tr("Ortogonale ") + (tr("attivo") if _Settings.ortho
                                     else tr("disattivato")), 2000)
            viewport.update()
            return True
        if key == Qt.Key_Backspace and self.points:
            self.points.pop()
            viewport.update()
            return True
        return False

    def _constrain(self, x, y):
        if not _Settings.ortho or not self.points:
            return (x, y)
        lx, ly = self.points[-1]
        if abs(x - lx) >= abs(y - ly):
            return (x, ly)
        return (lx, y)

    def on_hover(self, ctx: ToolContext) -> None:
        x, y = self._constrain(ctx.world.x(), ctx.world.y())
        self.hover = (x, y)
        ctx.viewport.update()

    def _dati(self):
        return {"pts": [list(p) for p in self.points], "tipo": _Settings.tipo,
                "lato": _Settings.lato, "z": _Settings.z, "sp": _Settings.sp,
                "dentro": _Settings.dentro, "col": COLOR_VOLTA}

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        if getattr(vp.scene, "edit_group", None) is not None:
            vp.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        x, y = self._constrain(ctx.world.x(), ctx.world.y())
        if self.points and math.hypot(x - self.points[-1][0], y - self.points[-1][1]) < 1e-4:
            return
        self.points.append((x, y))
        if len(self.points) < 4:
            vp.update()
            return
        d = self._dati()
        self.points = []
        if volta_geometria(d) is None:
            vp.flash_status(tr("Impossibile creare la volta: i punti sono troppo vicini"), 4000)
            vp.update()
            return
        name = tr("Volta")

        def mutate(scene):
            build_volta(scene, d, name)

        vp.history.execute(muri.MuriCommand(mutate))
        vp.notify_scene_changed()
        vp.flash_status(tr("Volta creata"), 3000)
        vp.update()

    def draw_overlay(self, viewport, painter) -> None:
        try:
            self._draw(viewport, painter)
        except Exception:
            pass

    def _draw(self, viewport, painter) -> None:
        from PySide6.QtCore import QPointF
        if not self.points:
            return
        pts = list(self.points)
        if self.hover is not None:
            pts.append(self.hover)
        pix = [viewport._world_to_pixel(QVector3D(x, y, _Settings.z)) for x, y in pts]
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(0, 170, 255), 2))
        for i in range(len(pix) - 1):
            if pix[i] is not None and pix[i + 1] is not None:
                painter.drawLine(QPointF(*pix[i]), QPointF(*pix[i + 1]))
        if len(pix) == 4 and pix[0] is not None and pix[3] is not None:
            painter.drawLine(QPointF(*pix[3]), QPointF(*pix[0]))
        painter.setBrush(QColor(220, 30, 30))
        for p in pix[:len(self.points)]:
            if p is not None:
                painter.drawEllipse(QPointF(*p), 4, 4)
        painter.restore()


def _selected_volte(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and volta_data(g) is not None and g not in out:
            out.append(g)
    return out


def edit_volta(viewport, group) -> None:
    if getattr(viewport.scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    d = volta_data(group)
    if d is None:
        return
    res = ask_volta(viewport.window(), d, tr("Modifica volta"))
    if res is None:
        return
    q = dict(d)
    q.update(res)
    if volta_geometria(q) is None:
        viewport.flash_status(tr("Impossibile aggiornare la volta"), 3000)
        return

    def mutate(sc):
        rebuild_volta(group, q)

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("Volta aggiornata"), 3000)


def _hook_double_click(vp) -> None:
    if getattr(vp, "_myhouse_volta_dbl", False):
        return
    original = vp.begin_group_edit

    def begin_group_edit(group, *args, **kwargs):
        g = getattr(group, "owner", None) or group
        if volta_data(g) is None:
            return original(group, *args, **kwargs)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: edit_volta(vp, g))

    vp.begin_group_edit = begin_group_edit
    vp._myhouse_volta_dbl = True


def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    from PySide6.QtCore import QRectF
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(217, 209, 194))
    p.drawChord(QRectF(6, 10, 36, 36), 0, 180 * 16)
    p.drawLine(6, 28, 42, 28)
    p.end()
    return QIcon(pm)


def register(api) -> None:
    tool = VoltaTool()
    api.add_button(tr("Volta"), tr("Crea una volta (botte, vela, crociera, padiglione)"),
                   _icon(), api.run_tool(tool), group="Archi e volte")
    app = api.app
    _hook_double_click(api.window.viewport)
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        from PySide6.QtCore import QTimer

        def context(menu, selection) -> None:
            vs = _selected_volte(app.viewport.scene)
            if not vs:
                return
            menu.addSeparator()
            menu.addAction(
                tr("Modifica volta…"),
                lambda: QTimer.singleShot(0, lambda: edit_volta(app.viewport, vs[0])))

        add_ctx(context)
    add_kind = getattr(app, "add_outliner_kind", None)
    if add_kind is not None:
        def kind(group):
            d = volta_data(group)
            if d is None:
                return None
            from ._imperial import fmt_len
            return {"type": tr("Volta"),
                    "props": [(tr("Tipo"), dict(TIPI).get(d.get("tipo"), "")),
                              (tr("Altezza da terra"), fmt_len(d["z"])),
                              (tr("Spessore"), fmt_len(d["sp"]))]}
        add_kind(kind)
