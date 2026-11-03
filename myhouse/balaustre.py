# SPDX-License-Identifier: GPL-3.0-or-later
"""Plugin Balaustra per IngeTrazo / MyHouse — crea balaustre (IfcRailing).

Uso: MyHouse > Balaustra, scegli altezza, spazio tra le barre verticali,
spessore dei tubolari e del corrimano, poi:
  - clic sui punti della polilinea (quanti lati vuoi)
  - Invio conclude · C chiude la polilinea · Backspace toglie l'ultimo punto
  - Esc o tasto destro esce

Ogni punto prende la QUOTA del punto cliccato: su un piano a terra la balaustra
resta orizzontale; cliccando sugli spigoli di una scala (nasi dei gradini) il
tratto si inclina e segue la scala. Le barre restano verticali.

Elementi: corrimano in alto (spessore a parte), corrente in basso e barre
verticali, tutti tubolari a sezione tonda o quadra. Le barre si fermano sul
corrente in basso; solo i montanti (agli estremi e circa ogni metro) arrivano
a terra. "Altezza" = dalla quota del punto alla faccia superiore del corrimano.
"""
from __future__ import annotations

import copy
import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPen, QVector3D
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QCheckBox, QLineEdit, QVBoxLayout,
)

from core import bim
from tools.base import Tool, ToolContext

from . import muri, piani

ORDER = 80
BAR_COLOR = (0.30, 0.31, 0.33)
RAIL_COLOR = (0.22, 0.23, 0.25)
GLASS_COLOR = (0.74, 0.90, 0.88)
GLASS_GAP = 0.02                # distanza vetro-montante e vetro-corrimano
LAYER_NAME = "Balaustre"
KEY = "myhouse_balaustra"       # parametri in group.ext
SIDES = 12                      # lati della sezione tonda
MIN_SEG = 0.02                  # lati più corti di 2 cm si ignorano


class _Settings:
    h = 1.00                    # altezza (faccia superiore del corrimano)
    gap = 0.10                  # spazio libero tra le barre verticali
    t = 0.02                    # spessore tubolari
    hr = 0.05                   # spessore corrimano
    bot = 0.05                  # corrente basso: distanza dal piano
    post = 1.00                 # passo dei montanti che arrivano a terra
    round_ = True               # sezione tonda (False = quadra)
    style = "vert"              # "vert", "horiz" (barre orizzontali), "glass"
    vt = 0.012                  # spessore del vetro
    name = "Balaustra"
    ortho = True                # punti sull'asse X/Y del precedente
    level = None                # piano di appartenenza (la quota resta dei punti)


# ---------------------------------------------------------------------------
# Geometria pura
# ---------------------------------------------------------------------------

def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _unit(a):
    n = math.sqrt(_dot(a, a)) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


def segments(d):
    """Lati utili: dict con a, b (x, y, z), u (direzione in pianta), lp
    (lunghezza in pianta)."""
    pts = [tuple(p) for p in d["pts"]]
    out = []
    for a, b in zip(pts, pts[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        lp = math.hypot(dx, dy)
        if lp < MIN_SEG:
            continue
        out.append({"a": a, "b": b, "u": (dx / lp, dy / lp), "lp": lp})
    return out


def bars(d):
    """Barre verticali: lista di (x, y, z_basso, z_alto). I montanti (estremi e
    circa uno ogni d["post"] metri) arrivano al piano, le altre barre
    partono dal corrente in basso."""
    t, gap, h, hr = d["t"], d["gap"], d["h"], d["hr"]
    bot, post = d["bot"], max(0.2, d.get("post", 1.0))
    style = d.get("style", "vert")
    only_posts = style == "horiz"
    out, seen = [], set()
    for seg in segments(d):
        a, b, u, lp = seg["a"], seg["b"], seg["u"], seg["lp"]
        if style == "glass":            # solo montanti, passo regolare
            mp = max(1, round(lp / post))
            for i in range(mp + 1):
                s = lp * i / mp
                x, y = a[0] + u[0] * s, a[1] + u[1] * s
                key = (round(x, 3), round(y, 3))
                if key in seen:
                    continue
                seen.add(key)
                zb = a[2] + (b[2] - a[2]) * s / lp
                out.append((x, y, zb, zb + h - hr / 2))
            continue
        m = max(1, math.ceil(lp / (gap + t) - 1e-9))
        mp = max(1, round(lp / post))
        posts = {round(i * m / mp) for i in range(mp + 1)}
        for k in range(m + 1):
            s = lp * k / m
            x, y = a[0] + u[0] * s, a[1] + u[1] * s
            if only_posts and k not in posts:
                continue                # barre orizzontali: solo montanti
            key = (round(x, 3), round(y, 3))
            if key in seen:
                continue
            seen.add(key)
            zb = a[2] + (b[2] - a[2]) * s / lp
            z0 = zb if k in posts else zb + bot + t / 2
            out.append((x, y, z0, zb + h - hr / 2))
    return out


def _section(hn, hw, round_):
    """Sezione del tubolare: punti (dn, dw) antiorari."""
    if round_:
        r = max(hn, hw)
        return [(r * math.cos(2 * math.pi * i / SIDES),
                 r * math.sin(2 * math.pi * i / SIDES)) for i in range(SIDES)]
    return [(-hn, -hw), (hn, -hw), (hn, hw), (-hn, hw)]


_APP = {"app": None}


def _mat_attrs(name, scene=None):
    """Attributi di faccia del materiale `name` del documento, o None."""
    if not name:
        return None
    try:
        sc = scene if scene is not None else _APP["app"].viewport.scene
        mat = sc.materials.get(name)
        return dict(mat.face_attrs()) if mat is not None else None
    except Exception:
        return None


def _ask_material(viewport, current, label="Materiale", extra=None):
    """Dialogo: sceglie un materiale del documento. extra = lista di
    (chiave, etichetta, valore attuale) per altri materiali. Ritorna un dict
    {chiave: nome|None} oppure None se annullato."""
    mats = sorted(viewport.scene.materials)
    if not mats:
        viewport.flash_status("Il documento non ha materiali", 3000)
        return None
    dlg = QDialog(viewport.window())
    dlg.setWindowTitle(label)
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    combos = {}
    for key, text, cur in [("mat", label, current)] + list(extra or []):
        cb = QComboBox()
        cb.addItem("(predefinito)", None)
        for m in mats:
            cb.addItem(m, m)
        i = cb.findData(cur)
        cb.setCurrentIndex(max(0, i))
        form.addRow(text, cb)
        combos[key] = cb
    lay.addLayout(form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return None
    return {k: c.currentData() for k, c in combos.items()}


def _tube(mesh, p0, p1, n, hn, hw, color, ext, round_=False, attrs=None,
          m0=None, m1=None):
    """Tubolare lungo p0->p1 (tondo o quadro): n = direzione orizzontale della
    sezione, hn/hw = metà dimensioni; ext = prolungamento alle estremità.
    m0/m1 = normale del piano di taglio a mitra (spigolo): l'estremità viene
    tagliata su quel piano, senza prolungamento, così i due lati si uniscono
    senza buchi né sovrapposizioni."""
    P = QVector3D
    a = _unit(_sub(p1, p0))
    w = _unit(_cross(a, n))
    q0 = _sub(p0, _mul(a, 0.0 if m0 else ext))
    q1 = _add(p1, _mul(a, 0.0 if m1 else ext))
    sec = _section(hn, hw, round_)

    def ring(q, m):
        pts = []
        for dn, dw in sec:
            off = _add(_mul(n, dn), _mul(w, dw))
            if m:
                off = _add(off, _mul(a, -_dot(off, m) / _dot(a, m)))
            pts.append(_add(q, off))
        return pts

    ring0 = ring(q0, m0)
    ring1 = ring(q1, m1)
    centre = _mul(_add(q0, q1), 0.5)
    m = len(sec)
    polys = [list(reversed(ring0)), ring1]                      # teste
    for i in range(m):
        j = (i + 1) % m
        polys.append([ring0[i], ring0[j], ring1[j], ring1[i]])  # lati
    for vs in polys:
        nrm = (0.0, 0.0, 0.0)
        for i in range(len(vs)):
            c1, c2 = vs[i], vs[(i + 1) % len(vs)]
            nrm = _add(nrm, ((c1[1] - c2[1]) * (c1[2] + c2[2]),
                             (c1[2] - c2[2]) * (c1[0] + c2[0]),
                             (c1[0] - c2[0]) * (c1[1] + c2[1])))
        fc = _mul(vs[0], 0.0)
        for v in vs:
            fc = _add(fc, v)
        fc = _mul(fc, 1.0 / len(vs))
        if _dot(nrm, _sub(fc, centre)) < 0:
            vs = list(reversed(vs))
        f = mesh.add_face([P(*v) for v in vs])
        if attrs:
            f.attrs.update(copy.deepcopy(attrs))
        # nessun colore predefinito: le facce restano senza materiale
        f.attrs["layer"] = LAYER_NAME


def _glass(mesh, d, seg, n, mg=None) -> None:
    """Lastre di vetro tra i montanti di un lato."""
    a, b, u, lp = seg["a"], seg["b"], seg["u"], seg["lp"]
    h, hr, bot = d["h"], d["hr"], d["bot"]
    vt = d.get("vt", 0.012)
    post = max(0.2, d.get("post", 1.0))
    mp = max(1, round(lp / post))
    z0, z1 = bot, h - hr - GLASS_GAP            # dal piano, sotto il corrimano
    if z1 - z0 < 0.05:
        return
    inset = hr / 2 + GLASS_GAP
    mid, half = (z0 + z1) / 2, (z1 - z0) / 2
    for i in range(mp):
        s0 = lp * i / mp + inset
        s1 = lp * (i + 1) / mp - inset
        if s1 - s0 < 0.05:
            continue
        pts = []
        for s in (s0, s1):
            zb = a[2] + (b[2] - a[2]) * s / lp
            pts.append((a[0] + u[0] * s, a[1] + u[1] * s, zb + mid))
        _tube(mesh, pts[0], pts[1], n, vt / 2, half, GLASS_COLOR, 0.0, False,
              mg)


def _soften(mesh) -> None:
    """Nasconde gli spigoli tra le sfaccettature dei tubolari tondi (lati a
    4 vertici): restano visibili i contorni veri (teste e giunti)."""
    try:
        for e in mesh.edges:
            fs = list(e.faces)
            if len(fs) != 2:
                continue
            if all(len(list(f.vertices)) == 4 for f in fs):
                e.soft = True
                e.hidden = True
    except Exception:
        pass


def _miters(segs, d):
    """Per ogni lato: (m0, m1) = normali dei piani di mitra agli estremi, o
    None se l'estremo è libero. Lati consecutivi che condividono un punto si
    uniscono a mitra; se la polilinea è chiusa vale anche per primo/ultimo."""
    def dirs(s):
        return _unit(_sub(s["b"], s["a"]))

    def same(p, q):
        return all(abs(p[i] - q[i]) < 1e-6 for i in range(3))

    def miter(s1, s2):
        a1, a2 = dirs(s1), dirs(s2)
        m = _add(a1, a2)
        if _dot(m, m) < 1e-9:
            return None
        m = _unit(m)
        return m if _dot(a1, m) > 0.2 else None     # angoli troppo acuti: no

    k = len(segs)
    out = [[None, None] for _ in segs]
    for i in range(k - 1):
        if same(segs[i]["b"], segs[i + 1]["a"]):
            m = miter(segs[i], segs[i + 1])
            out[i][1] = m
            out[i + 1][0] = m
    if k >= 3 and same(segs[-1]["b"], segs[0]["a"]):
        m = miter(segs[-1], segs[0])
        out[-1][1] = m
        out[0][0] = m
    return out


def railing_mesh(d):
    from core.mesh import Mesh
    mesh = Mesh()
    t, hr, h, bot = d["t"], d["hr"], d["h"], d["bot"]
    rnd = bool(d.get("round", False))
    ma = _mat_attrs(d.get("mat"))
    mg = _mat_attrs(d.get("matg"))
    segs = segments(d)
    miters = _miters(segs, d)
    for seg, (c0, c1) in zip(segs, miters):
        a, b, u = seg["a"], seg["b"], seg["u"]
        n = (-u[1], u[0], 0.0)
        top0 = (a[0], a[1], a[2] + h - hr / 2)
        top1 = (b[0], b[1], b[2] + h - hr / 2)
        _tube(mesh, top0, top1, n, hr / 2, hr / 2, RAIL_COLOR, hr / 2, rnd,
              ma, c0, c1)
        style = d.get("style", "vert")
        if style == "glass":
            _glass(mesh, d, seg, n, mg)
            continue                    # niente corrente basso: vetro + montanti
        low0 = (a[0], a[1], a[2] + bot + t / 2)
        low1 = (b[0], b[1], b[2] + bot + t / 2)
        _tube(mesh, low0, low1, n, t / 2, t / 2, RAIL_COLOR, t / 2, rnd, ma,
              c0, c1)
        if style == "horiz":
            # barre orizzontali (parallele al corrimano) tra corrente e corrimano
            dz = top0[2] - low0[2]
            k = max(1, math.ceil(dz / (d["gap"] + t) - 1e-9))
            for i in range(1, k):
                o = dz * i / k
                _tube(mesh, (low0[0], low0[1], low0[2] + o),
                      (low1[0], low1[1], low1[2] + o), n, t / 2, t / 2,
                      BAR_COLOR, t / 2, rnd, ma, c0, c1)
    # barre: assi in pianta (u) e (n) dell'ultimo lato non servono, la sezione
    # quadra è la stessa in ogni direzione: uso gli assi del mondo
    pw = hr / 2 if d.get("style", "vert") == "glass" else t / 2   # montanti
    for x, y, zb, zt in bars(d):
        _tube(mesh, (x, y, zb), (x, y, zt), (1.0, 0.0, 0.0), pw, pw,
              BAR_COLOR, 0.0, rnd, ma)
    if rnd:
        _soften(mesh)
    return mesh


def railing_data(group):
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "pts" in data else None


def rebuild_railing(group, d) -> None:
    """Nuova geometria dai parametri d, stesso gruppo."""
    from core.group import Group
    part = Group(railing_mesh(d), name="Balaustra")
    part.component = False
    group.children = [part]
    ext = dict(group.ext or {})
    ext[KEY] = dict(d)
    group.ext = ext


def build_railing(scene, d, name) -> None:
    from core.group import Group
    if not any(ly.name == LAYER_NAME for ly in scene.layers):
        from core.layers import Layer
        scene.layers.append(Layer(LAYER_NAME))
    part = Group(railing_mesh(d), name="Balaustra")
    part.component = False
    g = Group(name=name)
    g.adopt([part])
    g.component = False
    g.layer = LAYER_NAME
    bim.tag_group(g, "IfcRailing", name)
    g.ext = {KEY: d}
    scene.groups.append(g)


# ---------------------------------------------------------------------------
# Impostazioni
# ---------------------------------------------------------------------------

def _spin(value, lo, hi):
    s = QDoubleSpinBox()
    s.setDecimals(3)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


def ask_settings(parent, scene=None) -> bool:
    dlg = QDialog(parent)
    dlg.setWindowTitle("Balaustra")
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    h = _spin(_Settings.h, 0.2, 5.0)
    gap = _spin(_Settings.gap, 0.01, 2.0)
    t = _spin(_Settings.t, 0.005, 0.3)
    hr = _spin(_Settings.hr, 0.005, 0.5)
    bot = _spin(_Settings.bot, 0.0, 2.0)
    post = _spin(_Settings.post, 0.2, 10.0)
    sect = QComboBox()
    sect.addItem("Tonda", True)
    sect.addItem("Quadra", False)
    sect.setCurrentIndex(0 if _Settings.round_ else 1)
    vt = _spin(_Settings.vt, 0.004, 0.05)
    style = QComboBox()
    style.addItem("Verticali", "vert")
    style.addItem("Orizzontali", "horiz")
    style.addItem("Vetro (montanti + lastre)", "glass")
    style.setCurrentIndex(max(0, style.findData(_Settings.style)))
    name = QLineEdit(_Settings.name)
    ortho = QCheckBox("Ortogonale (O / F8 durante il disegno)")
    ortho.setChecked(_Settings.ortho)
    lvl = None
    if scene is not None and piani.levels(scene):
        lvl = piani.level_combo(scene, piani.active_id(scene))
        form.addRow("Piano (la quota resta quella dei punti cliccati)", lvl)
    form.addRow("Altezza balaustra (m)", h)
    form.addRow("Tipo di barre", style)
    form.addRow("Spazio tra le barre (m)", gap)
    form.addRow("Sezione tubolari", sect)
    form.addRow("Spessore (diametro) tubolari (m)", t)
    form.addRow("Spessore (diametro) corrimano (m)", hr)
    form.addRow("Corrente basso: distanza dal piano (m)", bot)
    form.addRow("Passo montanti fino a terra (m)", post)
    form.addRow("Spessore vetro (m)", vt)
    form.addRow("Nome", name)
    form.addRow(ortho)
    lay.addLayout(form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return False
    _Settings.h, _Settings.gap = h.value(), gap.value()
    _Settings.t, _Settings.hr = t.value(), hr.value()
    _Settings.bot = bot.value()
    _Settings.post, _Settings.round_ = post.value(), sect.currentData()
    _Settings.style = style.currentData()
    _Settings.vt = vt.value()
    _Settings.ortho = ortho.isChecked()
    _Settings.name = name.text().strip() or "Balaustra"
    _Settings.level = (lvl.currentData() or None) if lvl is not None else None
    if lvl is not None:
        piani.set_active(_Settings.level)
    return True


# ---------------------------------------------------------------------------
# Strumento
# ---------------------------------------------------------------------------

class BalaustraTool(Tool):
    name = "Balaustra"
    shortcut = None
    description = "Crea una balaustra: clic sui punti della polilinea."

    def __init__(self) -> None:
        self._entering = False
        self._reset()

    def _reset(self) -> None:
        self.points: list[tuple[float, float, float]] = []
        self.hover: QVector3D | None = None

    def _ortho(self, p: QVector3D) -> QVector3D:
        """Con l'ortogonale attivo il punto cade sull'asse X o Y del punto
        precedente (quello dominante); la quota resta quella del punto."""
        if not (_Settings.ortho and self.points):
            return p
        last = self.points[-1]
        if abs(p.x() - last[0]) >= abs(p.y() - last[1]):
            return QVector3D(p.x(), last[1], p.z())
        return QVector3D(last[0], p.y(), p.z())

    def status_clause(self) -> str:
        return (f"Ortogonale {'ON' if _Settings.ortho else 'OFF'} (O/F8) · "
                "C = chiudi · Invio = fine")

    # -- ciclo di vita ------------------------------------------------------
    def on_activate(self, viewport) -> None:
        if self._entering:
            self._reset()
            viewport.flash_status(
                "Balaustra: clic sui punti (sugli spigoli della scala si "
                "inclina) · O/F8 = ortogonale · Invio = concludi · C = chiudi · "
                "Esc = esci", 7000)
            return
        if not ask_settings(viewport.window(), viewport.scene):
            return
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
        if modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        if key in (Qt.Key_Escape, Qt.Key_O, Qt.Key_F8):
            return True
        return bool(self.points) and key in (
            Qt.Key_Return, Qt.Key_Enter, Qt.Key_Backspace, Qt.Key_C)

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)
            return True
        if key in (Qt.Key_O, Qt.Key_F8):
            _Settings.ortho = not _Settings.ortho
            if self.hover is not None:
                self.hover = self._ortho(self.hover)
            viewport.flash_status(
                "Ortogonale " + ("attivo" if _Settings.ortho else "disattivato"),
                2000)
            viewport.update()
            return True
        if not self.points:
            return False
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self._commit(viewport)
            return True
        if key == Qt.Key_C:
            if len(self.points) >= 3:
                self.points.append(self.points[0])
                self._commit(viewport)
            else:
                viewport.flash_status("Servono almeno 3 punti per chiudere",
                                      3000)
            return True
        if key == Qt.Key_Backspace:
            self.points.pop()
            viewport.update()
            return True
        return False

    # -- eventi ---------------------------------------------------------------
    def on_hover(self, ctx: ToolContext) -> None:
        self.hover = self._ortho(QVector3D(ctx.world))
        ctx.viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        if getattr(vp.scene, "edit_group", None) is not None:
            vp.flash_status("Chiudi il gruppo che stai modificando", 4000)
            return
        q3 = self._ortho(QVector3D(ctx.world))
        p = (q3.x(), q3.y(), q3.z())
        if self.points:
            q = self.points[-1]
            if math.hypot(p[0] - q[0], p[1] - q[1]) < MIN_SEG:
                return
        self.points.append(p)
        vp.update()

    def _dict(self, pts):
        return {"pts": [list(p) for p in pts], "h": _Settings.h,
                "gap": _Settings.gap, "t": _Settings.t, "hr": _Settings.hr,
                "bot": _Settings.bot, "post": _Settings.post,
                "round": _Settings.round_, "style": _Settings.style,
                "vt": _Settings.vt}

    def _commit(self, viewport) -> None:
        d = self._dict(self.points)
        if not segments(d):
            viewport.flash_status("Servono almeno 2 punti distinti", 3000)
            return
        name = _Settings.name
        lv = piani.get(viewport.scene, _Settings.level)
        if lv:                              # off = punto più basso - piano
            d.update({"lv": lv["id"], "lvn": lv["name"],
                      "off": min(p[2] for p in d["pts"]) - lv["z"]})

        def mutate(scene):
            build_railing(scene, d, name)

        viewport.history.execute(muri.MuriCommand(mutate))
        viewport.notify_scene_changed()
        viewport.flash_status(
            f"Balaustra creata · {len(bars(d))} barre verticali", 3500)
        self._reset()
        viewport.update()

    # -- disegno -------------------------------------------------------------
    def rubber_band_lines(self):
        pts = list(self.points)
        if self.hover is not None and pts:
            pts.append((self.hover.x(), self.hover.y(), self.hover.z()))
        if len(pts) < 2:
            return []
        d = self._dict(pts)
        P = QVector3D
        lines = []
        for seg in segments(d):
            a, b = seg["a"], seg["b"]
            lines.append((P(a[0], a[1], a[2] + d["h"]),
                          P(b[0], b[1], b[2] + d["h"])))
            lines.append((P(*a), P(*b)))
        for x, y, zb, zt in bars(d):
            lines.append((P(x, y, zb), P(x, y, zt + d["hr"] / 2)))
        return lines


# ---------------------------------------------------------------------------
# Registrazione
# ---------------------------------------------------------------------------

def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(90, 92, 98))
    p.drawRect(4, 8, 40, 5)
    p.drawRect(4, 36, 40, 3)
    for x in (6, 14, 22, 30, 38):
        p.drawLine(x + 2, 13, x + 2, 36)
    p.end()
    return QIcon(pm)


def _selected_railings(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and railing_data(g) is not None and g not in out:
            out.append(g)
    return out


def set_railing_material(viewport) -> None:
    scene = viewport.scene
    sel = _selected_railings(scene)
    if not sel:
        viewport.flash_status("Seleziona una balaustra", 3000)
        return
    d0 = railing_data(sel[0])
    keys = [[list(p) for p in railing_data(g)["pts"]] for g in sel]
    extra = ([("matg", "Materiale vetro", d0.get("matg"))]
             if d0.get("style") == "glass" else [])
    res = _ask_material(viewport, d0.get("mat"), "Materiale struttura", extra)
    if res is None:
        return

    def mutate(sc):
        for gg in sc.groups:
            dd = railing_data(gg)
            if dd is not None and [list(p) for p in dd["pts"]] in keys:
                nd = copy.deepcopy(dd)
                for k, v in res.items():
                    if v:
                        nd[k] = v
                    else:
                        nd.pop(k, None)
                rebuild_railing(gg, nd)

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status("Materiale applicato", 3000)


def _outliner_kind(group):
    d = railing_data(group)
    if d is None:
        return None
    from core.units import fmt_len
    length = 0.0
    for seg in segments(d):
        a, b = seg["a"], seg["b"]
        length += math.sqrt(sum((b[i] - a[i]) ** 2 for i in range(3)))
    return {"type": "Balaustra",
            "props": [("Altezza", fmt_len(d["h"])),
                      ("Lunghezza", fmt_len(length)),
                      ("Barre verticali", str(len(bars(d))))]
            + piani.level_props(d)}


def _register_level_kind() -> None:
    def zget(d):
        return min(p[2] for p in d["pts"])

    def zset(d, z):
        delta = z - zget(d)
        d["pts"] = [[p[0], p[1], p[2] + delta] for p in d["pts"]]

    piani.register_kind("balaustra", KEY, railing_data, zget, zset,
                        rebuild_railing)


def register(api) -> None:
    _APP["app"] = api.app
    _register_level_kind()
    add_ctx = getattr(api.app, "add_context_menu", None)
    if add_ctx is not None:
        def context(menu, selection) -> None:
            if not _selected_railings(api.app.viewport.scene):
                return
            menu.addSeparator()
            menu.addAction(
                "Materiale balaustra…",
                lambda: QTimer.singleShot(
                    0, lambda: set_railing_material(api.app.viewport)))

        add_ctx(context)
    api.add_button("Balaustra", "Crea una balaustra (anche inclinata su scale)",
                   _icon(), api.run_tool(BalaustraTool()))
    add_kind = getattr(api.app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
