# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ._lingua import tr
from ._imperial import LengthSpin
from ._scroll import scroll_form

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPen, QPolygonF, QVector3D
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QLineEdit, QVBoxLayout,
)

from core import bim
from . import _ifc
from tools.base import Tool, ToolContext

from . import muri

ORDER = 66
COLOR = (0.96, 0.96, 0.96)
LAYER_NAME = "Posti auto"
KEY = "myhouse_postoauto"
IFC_CLASS = "IfcBuildingElementProxy"
SNAP_PX = 18.0

INDICE_ANGOLO = {'BASSO_SX': 0, 'BASSO_DX': 1, 'ALTO_DX': 2, 'ALTO_SX': 3}


def _intersezione(p1, t1, p2, t2):
    det = t1[0] * (-t2[1]) - t1[1] * (-t2[0])
    if abs(det) < 1e-12:
        return p2
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    u = (dx * (-t2[1]) - dy * (-t2[0])) / det
    return (p1[0] + t1[0] * u, p1[1] + t1[1] * u)


def contorno(forma, larghezza, lunghezza, angolo, hand=None):
    W = max(larghezza, 0.01)
    L = max(lunghezza, 0.01)
    if forma == 'INCLINATO':
        a = math.radians(min(max(angolo, 5.0), 85.0))
        sx = L / math.tan(a)
        k = math.sin(a)
    else:
        sx = 0.0
        k = 1.0
    Ah = max(float(hand['w']), 0.01) / k if hand else 0.0
    Wt = W + Ah
    return [(0.0, 0.0), (Wt, 0.0), (Wt + sx, L), (sx, L)], Wt * k


def _taglia(poly, m, c, ge):
    sg = 1.0 if ge else -1.0
    out, n = [], len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        da = sg * (a[0] * m[0] + a[1] * m[1] - c)
        db = sg * (b[0] * m[0] + b[1] * m[1] - c)
        if da >= 0:
            out.append(a)
        if (da > 0 and db < 0) or (da < 0 and db > 0):
            t = da / (da - db)
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def _area(poly):
    return 0.5 * sum(poly[i][0] * poly[(i + 1) % len(poly)][1]
                     - poly[(i + 1) % len(poly)][0] * poly[i][1]
                     for i in range(len(poly)))


def _base(forma, larghezza, lunghezza, striscia, angolo, lato, aggancio,
          specchia, rotazione, hand=None):
    P, perp = contorno(forma, larghezza, lunghezza, angolo, hand)
    W = max(larghezza, 0.01)
    L = max(lunghezza, 0.01)
    s = min(max(striscia, 0.0001), min(perp, L) * 0.49)
    off = [s, s, s, s]
    if lato == 'NO_DESTRO':
        off[1] = 0.0
    elif lato == 'NO_SINISTRO':
        off[3] = 0.0
    rette = []
    for i in range(4):
        p0, p1 = P[i], P[(i + 1) % 4]
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        ln = math.hypot(dx, dy)
        t = (dx / ln, dy / ln)
        n = (-t[1], t[0])
        rette.append(((p0[0] + n[0] * off[i], p0[1] + n[1] * off[i]), t))
    Q = []
    for i in range(4):
        pa, ta = rette[(i - 1) % 4]
        pb, tb = rette[i]
        Q.append(_intersezione(pa, ta, pb, tb))
    strisce = []
    for i in range(4):
        if off[i] <= 0.0:
            continue
        j = (i + 1) % 4
        strisce.append([P[i], P[j], Q[j], Q[i]])

    zebre = []
    if hand:
        sx = P[3][0]
        Ah = P[1][0] - W
        sh = min(s * math.hypot(L, sx) / L, W * 0.45)
        y0, y1 = s, L - s

        def X(x, y):
            return (x + sx * y / L, y)

        if hand.get('lato', 'DESTRO') != 'SINISTRO':
            div = [X(W - sh, y0), X(W, y0), X(W, y1), X(W - sh, y1)]
            xl, xr = W, P[1][0] - (sh if off[1] > 0 else 0.0)
        else:
            div = [X(Ah, y0), X(Ah + sh, y0), X(Ah + sh, y1), X(Ah, y1)]
            xl, xr = (sh if off[3] > 0 else 0.0), Ah
        strisce.append(div)
        interno = [X(xl, y0), X(xr, y0), X(xr, y1), X(xl, y1)]
        ln = math.hypot(sx, L)
        t = (sx / ln, L / ln)
        nn = (t[1], -t[0])
        sg = -1.0 if hand.get('inv') else 1.0
        r2 = math.sqrt(0.5)
        dv = ((t[0] + sg * nn[0]) * r2, (t[1] + sg * nn[1]) * r2)
        m = (-dv[1], dv[0])
        passo = max(float(hand.get('passo', 0.6)), 0.05)
        sw = min(max(float(hand.get('sw', 0.3)), 0.005), passo * 0.95)
        vals = [p[0] * m[0] + p[1] * m[1] for p in interno]
        c = math.floor(min(vals) / passo) * passo
        while c < max(vals):
            b = _taglia(_taglia(interno, m, c, True), m, c + sw, False)
            if len(b) >= 3 and abs(_area(b)) > 1e-6:
                zebre.append(b)
            c += passo

    origine = P[INDICE_ANGOLO.get(aggancio, 0)]
    rot = int(rotazione) % 4

    def trasforma(v):
        x, y = v[0] - origine[0], v[1] - origine[1]
        if specchia:
            x = -x
        for _ in range(rot):
            x, y = -y, x
        return (x, y)

    return strisce, zebre, trasforma


def quads(forma, larghezza, lunghezza, striscia, angolo, lato, aggancio,
          specchia, rotazione, hand=None):
    st, _z, tf = _base(forma, larghezza, lunghezza, striscia, angolo, lato,
                       aggancio, specchia, rotazione, hand)
    return [[tf(v) for v in q] for q in st]


def zebre(forma, larghezza, lunghezza, striscia, angolo, lato, aggancio,
          specchia, rotazione, hand=None):
    _s, zb, tf = _base(forma, larghezza, lunghezza, striscia, angolo, lato,
                       aggancio, specchia, rotazione, hand)
    return [[tf(v) for v in q] for q in zb]


def _orienta(verts, facce):
    vol = 0.0
    for f in facce:
        for i in range(1, len(f) - 1):
            a, b, c = verts[f[0]], verts[f[i]], verts[f[i + 1]]
            vol += (a[0] * (b[1] * c[2] - b[2] * c[1])
                    - a[1] * (b[0] * c[2] - b[2] * c[0])
                    + a[2] * (b[0] * c[1] - b[1] * c[0]))
    if vol < 0:
        facce = [tuple(reversed(f)) for f in facce]
    return facce


def solido(forma, larghezza, lunghezza, striscia, angolo, lato, aggancio,
           specchia, rotazione, spessore, altezza_da_terra, hand=None):
    args = (forma, larghezza, lunghezza, striscia, angolo, lato, aggancio,
            specchia, rotazione, hand)
    qs = quads(*args) + zebre(*args)
    z0 = altezza_da_terra
    z1 = altezza_da_terra + max(spessore, 0.0001)
    verts, inf, sup, facce, conteggio = [], {}, {}, [], {}

    def vertici(p):
        k = (round(p[0], 6), round(p[1], 6))
        if k not in inf:
            verts.append((p[0], p[1], z0))
            inf[k] = len(verts) - 1
            verts.append((p[0], p[1], z1))
            sup[k] = len(verts) - 1
        return k

    for q in qs:
        ks = [vertici(p) for p in q]
        if len(set(ks)) < 3:
            continue
        for i in range(len(ks)):
            a, b = ks[i], ks[(i + 1) % len(ks)]
            kk = (a, b) if a < b else (b, a)
            conteggio.setdefault(kk, []).append((a, b))
        facce.append(tuple(sup[k] for k in ks))
        facce.append(tuple(inf[k] for k in reversed(ks)))
    nascosti = []
    for kk, lista in conteggio.items():
        if len(lista) == 1:
            a, b = lista[0]
            facce.append((inf[a], inf[b], sup[b], sup[a]))
        elif len(lista) == 2:
            nascosti.append((inf[kk[0]], inf[kk[1]]))
            nascosti.append((sup[kk[0]], sup[kk[1]]))
    return verts, _orienta(verts, facce), nascosti


FORME = (("RETTANGOLARE", "Rettangolare"), ("INCLINATO", "Inclinato"))
AGGANCI = (("ALTO_SX", "Alto sinistra"), ("ALTO_DX", "Alto destra"),
           ("BASSO_SX", "Basso sinistra"), ("BASSO_DX", "Basso destra"))
LATI_HAND = (("DESTRO", "Destro"), ("SINISTRO", "Sinistro"))
HAND_DEFAULT = {"hand": False, "hand_w": 1.30, "hand_lato": "DESTRO",
                "hand_pass": 0.60, "hand_sw": 0.30, "hand_inv": False}
LATI = (("ENTRAMBI", "Entrambi"), ("NO_SINISTRO", "Senza sinistro"),
        ("NO_DESTRO", "Senza destro"))


class _Settings:
    forma = "RETTANGOLARE"
    larghezza = 2.5
    lunghezza = 5.0
    striscia = 0.10
    angolo = 45.0
    aggancio = "BASSO_SX"
    lato = "ENTRAMBI"
    specchia = False
    rotazione = 0
    spessore = 0.001
    hand = False
    hand_w = 1.30
    hand_lato = "DESTRO"
    hand_pass = 0.60
    hand_sw = 0.30
    hand_inv = False
    z0 = 0.0
    name = tr("Posto auto")


_CHIAVI = ("forma", "larghezza", "lunghezza", "striscia", "angolo", "aggancio",
           "lato", "specchia", "rotazione", "spessore", "z0", "name",
           "hand", "hand_w", "hand_lato", "hand_pass", "hand_sw", "hand_inv")


def _params_correnti() -> dict:
    return {k: getattr(_Settings, k) for k in _CHIAVI}


def postoauto_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "p" in data else None


def _hand(d):
    if not d.get("hand"):
        return None
    return {"w": d.get("hand_w", 1.30), "lato": d.get("hand_lato", "DESTRO"),
            "passo": d.get("hand_pass", 0.60), "sw": d.get("hand_sw", 0.30),
            "inv": bool(d.get("hand_inv", False))}


def _quads(d):
    return quads(d["forma"], d["larghezza"], d["lunghezza"], d["striscia"],
                 d["angolo"], d["lato"], d["aggancio"], d["specchia"],
                 d["rotazione"], _hand(d))


def _kp(v):
    return (round(v.x(), 4), round(v.y(), 4), round(v.z(), 4))


def postoauto_mesh(d):
    from core.mesh import Mesh
    verts, facce, nascosti = solido(
        d["forma"], d["larghezza"], d["lunghezza"], d["striscia"], d["angolo"],
        d["lato"], d["aggancio"], d["specchia"], d["rotazione"],
        d["spessore"], d["z0"], _hand(d))
    px, py, pz = d["p"]
    vs = [QVector3D(x + px, y + py, z + pz) for (x, y, z) in verts]
    mesh = Mesh()
    for f in facce:
        face = mesh.add_face([vs[i] for i in f])
        face.attrs["color"] = COLOR
        face.attrs["mat"] = tr("materiale posto auto")
        face.attrs["layer"] = LAYER_NAME
    chiavi = {frozenset((_kp(vs[a]), _kp(vs[b]))) for a, b in nascosti}
    for e in mesh.edges:
        try:
            if frozenset((_kp(e.a), _kp(e.b))) in chiavi:
                setattr(e, muri.EDGE_FLAG, True)
        except Exception:
            pass
    return mesh


def build_postoauto(scene, d, name):
    from core.group import Group
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    part = Group(postoauto_mesh(d), name=tr("Posto auto"))
    part.component = False
    g = Group(name=name)
    g.adopt([part])
    g.component = False
    g.layer = LAYER_NAME
    _ifc.tag(g, IFC_CLASS, name)
    g.ext = {KEY: d}
    scene.groups.append(g)
    return g


def rebuild_postoauto(group, p: dict) -> None:
    from core.group import Group
    d = dict(postoauto_data(group))
    d.update(p)
    part = Group(postoauto_mesh(d), name=tr("Posto auto"))
    part.component = False
    group.children = [part]
    _ifc.tag(group, IFC_CLASS)
    group.name = d.get("name", group.name)
    ext = dict(group.ext or {})
    ext[KEY] = d
    group.ext = ext


def _disegno_posto(get):
    r, t, dim, ext = muri._r, muri._t, muri._dim, muri._ext

    def disegno(p):
        c = get()
        h = _hand(c)
        P, _perp = contorno(c["forma"], c["larghezza"], c["lunghezza"],
                            c["angolo"], h)
        arg = (c["forma"], c["larghezza"], c["lunghezza"], c["striscia"],
               c["angolo"], c["lato"], "BASSO_SX", False, 0, h)
        qs = quads(*arg) + zebre(*arg)
        xs, ys = [q[0] for q in P], [q[1] for q in P]
        xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
        k = min(190.0 / ((xmax - xmin) or 1.0), 95.0 / ((ymax - ymin) or 1.0))
        x0 = 52 + (190.0 - (xmax - xmin) * k) / 2
        y1 = 30 + 95.0 - (95.0 - (ymax - ymin) * k) / 2

        def pt(x, y):
            return QPointF(x0 + (x - xmin) * k, y1 - (y - ymin) * k)

        t(p, 20, 12, tr("Pianta"), size=9)
        p.setPen(QPen(muri._C_LINEA, 1.2))
        p.setBrush(muri._C_CORPO)
        for q in qs:
            p.drawPolygon(QPolygonF([pt(*v) for v in q]))
        b0, b1 = pt(*P[0]), pt(*P[1])
        dim(p, b0.x(), y1 + 12, b1.x(), y1 + 12, "b", -1)
        top = pt(*P[3])
        dim(p, x0 - 10, y1, x0 - 10, top.y(), "l", -1)
        sk = max(min(c["striscia"], 0.49 * min(P[1][0], c["lunghezza"])) * k, 3.0)
        ext(p, b1.x(), y1, b1.x() + 18, y1)
        ext(p, b1.x(), y1 - sk, b1.x() + 18, y1 - sk)
        dim(p, b1.x() + 16, y1 - sk, b1.x() + 16, y1, "s", 1)
        if c["forma"] == "INCLINATO":
            t(p, b0.x() + 18, y1 - 6, "a", muri._C_QUOTA, 10, True)
        ins = pt(*P[INDICE_ANGOLO.get(c["aggancio"], 0)])
        p.setPen(QPen(muri._C_QUOTA, 1.2))
        p.setBrush(muri._C_QUOTA)
        p.drawEllipse(ins, 4, 4)

        t(p, 290, 40, tr("Il punto rosso e' il punto di inserimento"), size=9)
        t(p, 290, 62, tr("Spazio = specchia"), size=9)
        t(p, 290, 80, tr("R = ruota di 90°"), size=9)
        t(p, 290, 108, tr("Lati lunghi: togliendone uno, due posti"), size=8)
        t(p, 290, 120, tr("auto accostati non sovrappongono le linee"), size=8)
        if h:
            t(p, 290, 146, tr("Fascia disabili: larghezza esterna (f)"), size=8)

    return disegno


def _spin(value, lo, hi, dec=3):
    s = LengthSpin()
    s.setDecimals(dec)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


def _combo(voci, corrente):
    cb = QComboBox()
    for k, nome in voci:
        cb.addItem(tr(nome), k)
    cb.setCurrentIndex(max(0, cb.findData(corrente)))
    return cb


def ask_params(parent, cur: dict, title: str):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    lay = QVBoxLayout(dlg)
    form = QFormLayout()

    forma = _combo(FORME, cur["forma"])
    w = _spin(cur["larghezza"], 0.05, 100.0)
    ln = _spin(cur["lunghezza"], 0.05, 100.0)
    s = _spin(cur["striscia"], 0.001, 5.0)
    ang = _spin(cur["angolo"], 15.0, 75.0, 1)
    agg = _combo(AGGANCI, cur["aggancio"])
    lato = _combo(LATI, cur["lato"])
    spec = QCheckBox(tr("Specchia (Spazio)"))
    spec.setChecked(bool(cur["specchia"]))
    rot = QComboBox()
    for i in range(4):
        rot.addItem(f"{i * 90}°", i)
    rot.setCurrentIndex(int(cur["rotazione"]) % 4)
    hc = {k: cur.get(k, v) for k, v in HAND_DEFAULT.items()}
    hand = QCheckBox(tr("Posto per disabili (fascia di accesso)"))
    hand.setChecked(bool(hc["hand"]))
    hlato = _combo(LATI_HAND, hc["hand_lato"])
    hw = _spin(hc["hand_w"], 0.3, 5.0)
    hpass = _spin(hc["hand_pass"], 0.05, 5.0)
    hsw = _spin(hc["hand_sw"], 0.01, 5.0)
    hinv = QCheckBox(tr("Strisce nell'altro verso"))
    hinv.setChecked(bool(hc["hand_inv"]))
    sp = _spin(cur["spessore"], 0.0001, 1.0, 4)
    z0 = _spin(cur["z0"], -100.0, 1000.0)
    name = QLineEdit(cur["name"])

    def correnti():
        return {"forma": forma.currentData(), "larghezza": w.value(),
                "lunghezza": ln.value(), "striscia": s.value(),
                "angolo": ang.value(), "aggancio": agg.currentData(),
                "lato": lato.currentData(), "hand": hand.isChecked(),
                "hand_w": hw.value(), "hand_lato": hlato.currentData(),
                "hand_pass": hpass.value(), "hand_sw": hsw.value(),
                "hand_inv": hinv.isChecked()}

    schema = muri._Schema(_disegno_posto(correnti))
    form.addRow(schema)
    form.addRow(tr("Forma"), forma)
    form.addRow(tr("Larghezza esterna (b) (m)"), w)
    form.addRow(tr("Lunghezza esterna (l) (m)"), ln)
    form.addRow(tr("Larghezza striscia (s) (m)"), s)
    form.addRow(tr("Angolo (a) (°)"), ang)
    form.addRow(tr("Inserimento (punto rosso)"), agg)
    form.addRow(tr("Lati lunghi"), lato)
    form.addRow(hand)
    form.addRow(tr("Fascia: lato"), hlato)
    form.addRow(tr("Fascia: larghezza esterna (f) (m)"), hw)
    form.addRow(tr("Strisce a 45°: passo (m)"), hpass)
    form.addRow(tr("Strisce a 45°: larghezza (m)"), hsw)
    form.addRow(hinv)
    form.addRow(spec)
    form.addRow(tr("Rotazione"), rot)
    form.addRow(tr("Spessore strisce (m)"), sp)
    form.addRow(tr("Altezza da terra (m)"), z0)
    form.addRow(tr("Nome"), name)

    def _aggiorna(*_):
        inclinato = forma.currentData() == "INCLINATO"
        ang.setVisible(inclinato)
        lbl = form.labelForField(ang)
        if lbl is not None:
            lbl.setVisible(inclinato)
        for wd in (hlato, hw, hpass, hsw, hinv):
            wd.setEnabled(hand.isChecked())
            lbl = form.labelForField(wd)
            if lbl is not None:
                lbl.setEnabled(hand.isChecked())
        schema.update()

    forma.currentIndexChanged.connect(_aggiorna)
    for wd in (w, ln, s, ang, hw, hpass, hsw):
        wd.valueChanged.connect(_aggiorna)
    hand.toggled.connect(_aggiorna)
    hlato.currentIndexChanged.connect(_aggiorna)
    hinv.toggled.connect(_aggiorna)
    agg.currentIndexChanged.connect(_aggiorna)
    lato.currentIndexChanged.connect(_aggiorna)
    _aggiorna()

    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return None
    return {"forma": forma.currentData(), "larghezza": w.value(),
            "lunghezza": ln.value(), "striscia": s.value(),
            "angolo": ang.value(), "aggancio": agg.currentData(),
            "lato": lato.currentData(), "specchia": spec.isChecked(),
            "rotazione": rot.currentData(), "spessore": sp.value(),
            "z0": z0.value(), "name": name.text().strip() or tr("Posto auto"),
            "hand": hand.isChecked(), "hand_w": hw.value(),
            "hand_lato": hlato.currentData(), "hand_pass": hpass.value(),
            "hand_sw": hsw.value(), "hand_inv": hinv.isChecked()}


class PostoAutoTool(Tool):
    name = tr("Posto auto")
    shortcut = None
    description = tr("Inserisce un posto auto (cornice di strisce): clic = inserisci.")

    def __init__(self) -> None:
        self._entering = False
        self._reset()

    def _reset(self) -> None:
        self.hover = None

    def on_activate(self, viewport) -> None:
        self._vp = viewport
        if self._entering:
            self._reset()
            viewport.flash_status(
                tr("Posto auto: clic = inserisci · Spazio = specchia · "
                   "R = ruota 90° · tasto destro o Esc = esci"), 7000)
            return
        p = ask_params(viewport.window(), _params_correnti(), tr("Posto auto"))
        if p is None:
            return
        for k, v in p.items():
            setattr(_Settings, k, v)
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def on_deactivate(self, viewport) -> None:
        self._reset()

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    def _exit(self, viewport) -> None:
        self._reset()
        viewport.update()
        back = getattr(viewport.window(), "activate_select_tool", None)
        if callable(back):
            back()

    def context_menu(self, viewport, pos) -> bool:
        self._exit(viewport)
        return True

    def claims_key(self, key: int, modifiers) -> bool:
        if modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier
                        | Qt.ShiftModifier):
            return False
        return key in (Qt.Key_Escape, Qt.Key_Space, Qt.Key_R)

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if key == Qt.Key_Space:
            _Settings.specchia = not _Settings.specchia
            viewport.update()
            return True
        if key == Qt.Key_R:
            _Settings.rotazione = (_Settings.rotazione + 1) % 4
            viewport.update()
            return True
        return False

    def _angoli_correnti(self):
        offs = []
        for q in _quads(_params_correnti()):
            for c in q:
                if all(abs(c[0] - o[0]) > 1e-6 or abs(c[1] - o[1]) > 1e-6 for o in offs):
                    offs.append(c)
        return offs

    def _snap_strisce(self, vp, base):
        offs = self._angoli_correnti()
        bersagli = []
        for g in vp.scene.groups:
            d = postoauto_data(g)
            if d is None:
                continue
            z = d["p"][2] + d["z0"] + max(d["spessore"], 0.0001)
            for q in _quads(d):
                for c in q:
                    bersagli.append((d["p"][0] + c[0], d["p"][1] + c[1], z))
        if not offs or not bersagli:
            return None
        migliore, dmin = None, SNAP_PX
        for tx, ty, tz in bersagli:
            ts = vp._world_to_pixel(QVector3D(tx, ty, tz))
            if ts is None:
                continue
            for o in offs:
                ps = vp._world_to_pixel(QVector3D(base[0] + o[0], base[1] + o[1], tz))
                if ps is None:
                    continue
                dist = math.hypot(ps[0] - ts[0], ps[1] - ts[1])
                if dist < dmin:
                    dmin, migliore = dist, (tx - o[0], ty - o[1], base[2])
        return migliore

    def _punto(self, vp, world) -> tuple:
        base = (world.x(), world.y(), world.z())
        try:
            snap = self._snap_strisce(vp, base)
        except Exception:
            snap = None
        return snap if snap is not None else base

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover = self._punto(ctx.viewport, ctx.world)
        ctx.viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        if getattr(vp.scene, "edit_group", None) is not None:
            vp.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        d = _params_correnti()
        d["p"] = list(self._punto(vp, ctx.world))
        name = _Settings.name

        def mutate(scene):
            build_postoauto(scene, d, name)

        vp.history.execute(muri.MuriCommand(mutate))
        vp.notify_scene_changed()
        vp.flash_status(tr("Posto auto inserito · doppio clic per modificarlo"), 3000)
        vp.update()

    def rubber_band_lines(self):
        if self.hover is None:
            return []
        px, py, pz = self.hover
        z = pz + _Settings.z0 + 0.002
        linee = []
        for q in _quads(_params_correnti()):
            for i in range(4):
                a, b = q[i], q[(i + 1) % 4]
                linee.append((QVector3D(px + a[0], py + a[1], z),
                              QVector3D(px + b[0], py + b[1], z)))
        return linee

    def draw_overlay(self, viewport, painter) -> None:
        pass


def _selected(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and postoauto_data(g) is not None and g not in out:
            out.append(g)
    return out


def edit_postoauto(viewport, groups=None) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
        return
    groups = groups or _selected(scene)
    if not groups:
        viewport.flash_status(tr("Seleziona un posto auto"), 3000)
        return
    p = ask_params(viewport.window(), postoauto_data(groups[0]),
                   tr("Modifica posto auto"))
    if p is None:
        return

    def mutate(sc):
        for g in groups:
            q = dict(p)
            if len(groups) > 1:
                q.pop("name")
            rebuild_postoauto(g, q)

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(tr("{0} posti auto aggiornati").format(len(groups)), 3000)


def _hook_double_click(vp) -> None:
    if getattr(vp, "_myhouse_postoauto_dbl", False):
        return
    original = vp.begin_group_edit

    def begin_group_edit(group, *args, **kwargs):
        g = getattr(group, "owner", None) or group
        if postoauto_data(g) is None:
            return original(group, *args, **kwargs)
        from PySide6.QtCore import QTimer
        scene = vp.scene
        try:
            scene.select([g])
        except Exception:
            scene.selection.clear()
            scene.selection.add(g)
        vp.update()
        QTimer.singleShot(0, lambda: edit_postoauto(vp, [g]))

    vp.begin_group_edit = begin_group_edit
    vp._myhouse_postoauto_dbl = True


def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 3))
    p.drawLine(9, 6, 9, 42)
    p.drawLine(39, 6, 39, 42)
    p.drawLine(9, 6, 39, 6)
    p.end()
    return QIcon(pm)


def _outliner_kind(group):
    d = postoauto_data(group)
    if d is None:
        return None
    from ._imperial import fmt_len
    return {"type": tr("Posto auto disabili") if d.get("hand") else tr("Posto auto"),
            "props": [(tr("Forma"), tr(dict(FORME).get(d["forma"], d["forma"]))),
                      (tr("Larghezza"), fmt_len(d["larghezza"])),
                      (tr("Lunghezza"), fmt_len(d["lunghezza"]))]}


def register(api) -> None:
    tool = PostoAutoTool()
    api.add_button(tr("Posto auto"),
                   tr("Inserisce un posto auto (cornice di strisce)"),
                   _icon(), api.run_tool(tool))
    app = api.app
    _hook_double_click(api.window.viewport)
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        from PySide6.QtCore import QTimer

        def context(menu, selection) -> None:
            if not _selected(app.viewport.scene):
                return
            menu.addSeparator()
            menu.addAction(
                tr("Modifica posto auto…"),
                lambda: QTimer.singleShot(0, lambda: edit_postoauto(app.viewport)))

        add_ctx(context)
    add_kind = getattr(app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
