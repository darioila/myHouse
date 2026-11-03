# SPDX-License-Identifier: GPL-3.0-or-later
"""Plugin Muri per IngeTrazo — traccia muri BIM (IfcWall) con il mouse.

File della cartella myhouse/ (vedi myhouse/__init__.py).

Uso: Extensions > Muri, scegli spessore, altezza e lato di ricalco, poi:
  - clic              aggiunge un punto (con gli snap)
  - numero + Invio    lunghezza del tratto nella direzione del cursore
                      (anche "dx;dy" per uno spostamento esatto)
  - Spazio            inverte il lato di ricalco (sinistro <-> destro)
  - O o F8            ortogonale on/off
  - C                 chiude la catena di muri (stanza)
  - Invio / doppio clic   termina (catena aperta)
  - Backspace         toglie l'ultimo punto
  - Esc               annulla ed esce dal comando
  - tasto destro      chiude la catena in corso ed esce dal comando
Lato di ricalco: la linea che disegni coincide con la faccia SINISTRA
(o DESTRA) del muro, guardando nel verso del tracciato; il corpo del muro
sta dall'altra parte. "Centro" mette la linea a metà spessore.
Altezza legata al piano: nel dialogo "Altezza fino a" si sceglie "Piano
successivo" o un piano preciso; la parte superiore del muro arriva alla quota
di quel piano (+ una distanza) e segue il piano se questo cambia quota.
Le lunghezze dei tratti sono scritte sullo schermo. Ogni tratto è un
IfcWall con giunti d'angolo a sghembo; tutto è UN solo passo di undo.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPen, QVector3D
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QLineEdit, QVBoxLayout,
)

import copy

from core import bim
from core.history import Command
from core.units import fmt_len
from tools.base import Tool, ToolContext

WALL_COLOR = (0.82, 0.80, 0.76)
REF_COLOR = QColor(0, 170, 255)      # lato di riferimento in tracciamento
LAYER_NAME = "Muri"
KEY = "myhouse_muro"        # chiave dei parametri in group.ext
EPS = 1e-6
ALIGN_NAMES = {"left": "SINISTRO", "right": "DESTRO", "center": "CENTRO"}


# ---------------------------------------------------------------------------
# Geometria (pura, senza GUI)
# ---------------------------------------------------------------------------

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
    """(spessore a sinistra, spessore a destra) rispetto alla linea tracciata.
    Ricalco sinistro: la linea è la faccia sinistra, il corpo sta a destra."""
    if align == "left":
        return 0.0, thickness
    if align == "right":
        return thickness, 0.0
    return thickness / 2.0, thickness / 2.0


def offset_points(pts, closed: bool, d_left: float, d_right: float):
    """Per ogni vertice, i punti delle due facce con giunto mitre."""
    n = len(pts)
    seg_count = n if closed else n - 1
    normals = []
    for i in range(seg_count):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        L = math.hypot(x1 - x0, y1 - y0)
        normals.append((-(y1 - y0) / L, (x1 - x0) / L))   # normale sinistra

    left, right = [], []
    for i in range(n):
        if closed:
            n0, n1 = normals[(i - 1) % n], normals[i % n]
        else:
            n0 = normals[i - 1] if i > 0 else normals[0]
            n1 = normals[i] if i < seg_count else normals[-1]
        dot = n0[0] * n1[0] + n0[1] * n1[1]
        if dot < -0.9:                                     # quasi inversione
            mx, my = n1
        else:
            k = 1.0 / (1.0 + dot)
            mx, my = (n0[0] + n1[0]) * k, (n0[1] + n1[1]) * k
        x, y = pts[i]
        left.append((x + mx * d_left, y + my * d_left))
        right.append((x - mx * d_right, y - my * d_right))
    return left, right


def offset_points_var(pts, closed, dls, drs):
    """Come offset_points, ma con uno spessore diverso per ogni tratto:
    ogni vertice è l'incrocio delle due rette parallele ai tratti vicini."""
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
    """(aL, aR, bL, bR) di un muro dai suoi dati, con il giunto d'angolo
    calcolato contro i tratti vicini (prev / next) com'erano alla creazione."""
    a, b = tuple(d["a"]), tuple(d["b"])
    pts, dls, drs = [], [], []
    nl, nr = side_offsets(d["nth"], d["align"])
    ol, orr = side_offsets(d["th"], d["align"])
    if d.get("prev"):
        pts.append(tuple(d["prev"]))
        dls.append(nl)
        drs.append(nr)
    ia = len(pts)
    pts += [a, b]
    dls.append(ol)
    drs.append(orr)
    if d.get("next"):
        pts.append(tuple(d["next"]))
        dls.append(nl)
        drs.append(nr)
    left, right = offset_points_var(pts, False, dls, drs)
    return left[ia], right[ia], left[ia + 1], right[ia + 1]


def _sub(segs, lo, hi):
    """Toglie l'intervallo (lo, hi) da una lista di segmenti (z)."""
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


def _columns(d, L):
    """Colonne lungo il muro: (t0, t1, segmenti pieni in z).
    d["open"] = [[s0, s1, z_basso, z_alto], ...] (s lungo l'asse da A)."""
    z0, z1 = d["z0"], d["z0"] + d["h"]
    ops = []
    for o in d.get("open") or ():
        s0, s1 = max(0.0, o[0]), min(L, o[1])
        lo, hi = max(z0, o[2]), min(z1, o[3])
        if lo - z0 < 1e-3:            # porta a terra: niente lamina sotto
            lo = z0
        if z1 - hi < 1e-3:
            hi = z1
        if s1 - s0 > 1e-4 and hi - lo > 1e-4:
            ops.append((s0 / L, s1 / L, lo, hi))
    extra = {t for t in (d.get("clip") or {}).get("ts", ()) if 1e-6 < t < 1 - 1e-6}
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
    """Punto dentro (o a meno di tol dal bordo di) un poligono 2D."""
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
    """Funzione (x, y) -> quota massima del muro sotto il tetto, oppure None.
    d["clip"] = {"regions": [{"poly": [[x, y]..], "pl": [a, b, c]}], "ts": [..]}
    (coordinate locali del muro; z = a*x + b*y + c è l'intradosso del tetto)."""
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


def wall_mesh(d):
    """La mesh (coordinate locali) di un muro, con i fori d["open"]."""
    from core.mesh import Mesh
    P = QVector3D
    aL, aR, bL, bR = wall_corners(d)
    L = math.hypot(d["b"][0] - d["a"][0], d["b"][1] - d["a"][1])

    # Asse del muro: i bordi dei fori vengono tagliati su piani PERPENDICOLARI
    # all'asse (stessa quota s su faccia sinistra e destra). Con lo stesso
    # parametro t su due facce di lunghezza diversa (giunti d'angolo a sghembo)
    # i tagli verrebbero inclinati.
    ux = (d["b"][0] - d["a"][0]) / L
    uy = (d["b"][1] - d["a"][1]) / L
    ax, ay = d["a"]

    def _face(A, B):
        sA = (A[0] - ax) * ux + (A[1] - ay) * uy      # s del vertice iniziale

        def f(t, z):
            if t <= 1e-9:
                return P(A[0], A[1], z)
            if t >= 1 - 1e-9:
                return P(B[0], B[1], z)
            k = t * L - sA                            # spostamento lungo l'asse
            return P(A[0] + ux * k, A[1] + uy * k, z)
        return f

    pl = _face(aL, bL)
    pr = _face(aR, bR)

    mesh = Mesh()

    clip_top = _clip_top(d)
    z1 = d["z0"] + d["h"]

    def add(q):
        f = mesh.add_face(q)
        # nessun colore predefinito: si applicano i materiali di IngeTrazo
        f.attrs["layer"] = LAYER_NAME

    def face(q):
        if clip_top is None:
            add(q)
            return
        pts = []                                   # toglie punti coincidenti
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
            add(pts)
        else:                                      # non piana: a ventaglio
            for i in range(1, len(pts) - 1):
                add([pts[0], pts[i], pts[i + 1]])

    def tp(f, t, z, low):
        """Punto di una faccia; sul bordo superiore, tagliato dal tetto."""
        p = f(t, z)
        if clip_top is None or z < z1 - 1e-9:
            return p
        return P(p.x(), p.y(), max(low, clip_top(p.x(), p.y())))

    cols = _columns(d, L)

    def side_run(f, left, ts, za, zb):
        """Faccia laterale di una serie di colonne: UN solo poligono, con il
        bordo alto spezzato dal tetto (niente linee verticali di giunzione)."""
        b0, b1 = f(ts[0], za), f(ts[-1], za)
        top = [tp(f, t, zb, za) for t in ts]
        pts = [b1, b0] + top if left else [b0, b1] + top[::-1]
        out = []                                   # toglie i punti allineati
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
            face(out)
            return
        for t0, t1 in zip(ts, ts[1:]):             # concavo: per colonna
            if left:
                face([f(t1, za), f(t0, za), tp(f, t0, zb, za),
                      tp(f, t1, zb, za)])
            else:
                face([f(t0, za), f(t1, za), tp(f, t1, zb, za),
                      tp(f, t0, zb, za)])

    if clip_top is not None:
        i = 0
        while i < len(cols):
            j = i
            while j + 1 < len(cols) and cols[j + 1][2] == cols[i][2]:
                j += 1
            ts = [cols[i][0]] + [cols[k][1] for k in range(i, j + 1)]
            for za, zb in cols[i][2]:
                side_run(pr, False, ts, za, zb)
                side_run(pl, True, ts, za, zb)
            i = j + 1

    for k, (t0, t1, segs) in enumerate(cols):
        for za, zb in segs:
            if clip_top is None:
                face([pr(t0, za), pr(t1, za),
                      tp(pr, t1, zb, za), tp(pr, t0, zb, za)])         # destro
                face([pl(t1, za), pl(t0, za),
                      tp(pl, t0, zb, za), tp(pl, t1, zb, za)])         # sinistro
            face([pr(t0, za), pl(t0, za), pl(t1, za), pr(t1, za)])     # sotto
            face([tp(pr, t0, zb, za), tp(pr, t1, zb, za),
                  tp(pl, t1, zb, za), tp(pl, t0, zb, za)])             # sopra
            prev = cols[k - 1][2] if k > 0 else []
            nxt = cols[k + 1][2] if k + 1 < len(cols) else []
            parts = [(za, zb)]
            for a, b in prev:
                parts = _sub(parts, a, b)
            for ya, yb in parts:                                      # testa t0
                face([pl(t0, ya), pr(t0, ya),
                      tp(pr, t0, yb, ya), tp(pl, t0, yb, ya)])
            parts = [(za, zb)]
            for a, b in nxt:
                parts = _sub(parts, a, b)
            for ya, yb in parts:                                      # testa t1
                face([pr(t1, ya), pl(t1, ya),
                      tp(pl, t1, yb, ya), tp(pr, t1, yb, ya)])
    return mesh


def wall_part(d, pose=None):
    """Il pezzo di geometria del muro (gruppo annidato con la sua matrice)."""
    from core.group import Group
    from PySide6.QtGui import QMatrix4x4
    part = Group(wall_mesh(d), name="Muro")
    part.xform = QMatrix4x4(pose) if pose is not None else QMatrix4x4()
    part.component = False
    return part


def wall_data(group):
    """I parametri del muro su un contenitore, o None per ogni altro gruppo."""
    data = (getattr(group, "ext", None) or {}).get(KEY)
    return data if isinstance(data, dict) and "a" in data else None


def wall_pose(group):
    from PySide6.QtGui import QMatrix4x4
    for k in getattr(group, "children", None) or ():
        if k.xform is not None:
            return QMatrix4x4(k.xform)
    return QMatrix4x4()


def build_walls(scene, pts, closed, thickness, height, base_z, name,
                align="left", level=None, off=0.0, tlv=None, toff=0.0):
    """Aggiunge alla scena un gruppo per ogni muro; ritorna quanti ne ha creati."""
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
        if level:                       # piano: z0 = quota piano + off
            d.update({"lv": level["id"], "lvn": level["name"], "off": off})
        if tlv:                         # parte alta legata a un piano
            d.update({"tlv": tlv, "toff": toff})
        label = f"{name} {i + 1}"
        g = Group(name=label)
        g.adopt([wall_part(d)])
        g.component = False
        g.layer = LAYER_NAME
        bim.tag_group(g, "IfcWall", label)
        g.ext = {KEY: d}
        scene.groups.append(g)
    return seg_count


def update_roof_clips(scene) -> int:
    """Regola: i muri che attraversano un tetto vengono tagliati sotto di esso.
    Ritorna quanti muri sono cambiati."""
    try:
        from . import tetto
        return tetto.update_roof_clips(scene) or 0
    except ImportError:
        return 0


def rebuild_wall(group, thickness, height, extra=None):
    """Nuovi spessore e altezza, stesso posto: il muro viene ricostruito
    dove sta ora (spostamenti e rotazioni restano). extra = altri dati da
    cambiare (z0, lv, lvn, off); un valore None toglie la chiave."""
    d = dict(wall_data(group))
    d["th"], d["h"] = thickness, height
    for k, v in (extra or {}).items():
        if v is None:
            d.pop(k, None)
        else:
            d[k] = v
    if d.get("chain"):
        d["nth"] = thickness          # tutta la catena ha lo stesso spessore
    pose = wall_pose(group)
    group.children = [wall_part(d, pose)]
    ext = dict(group.ext or {})
    ext[KEY] = d
    group.ext = ext


class MuriCommand(Command):
    """Un solo passo di undo: gruppi (elenco, parti, tag, parametri, matrice)."""

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


# ---------------------------------------------------------------------------
# Impostazioni (dialogo breve all'attivazione)
# ---------------------------------------------------------------------------

class _Settings:
    thickness = 0.30
    height = 3.00
    base_offset = 0.0
    name = "Muro"
    ortho = True
    align = "left"
    level = None                # id del piano (None = nessuno)
    tlv = None                  # altezza legata: "next" o id del piano
    toff = 0.0                  # distanza dalla quota di arrivo


def _spin(value, lo, hi):
    s = QDoubleSpinBox()
    s.setDecimals(3)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


def ask_settings(parent, scene=None) -> bool:
    from . import piani
    dlg = QDialog(parent)
    dlg.setWindowTitle("Muri")
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    thick = _spin(_Settings.thickness, 0.02, 5.0)
    height = _spin(_Settings.height, 0.1, 100.0)
    base = _spin(_Settings.base_offset, -100.0, 1000.0)
    name = QLineEdit(_Settings.name)
    align = QComboBox()
    for key, label in (("left", "Sinistro"), ("right", "Destro"),
                       ("center", "Centro")):
        align.addItem(label, key)
    align.setCurrentIndex(align.findData(_Settings.align))
    ortho = QCheckBox("Ortogonale (O / F8 durante il disegno)")
    ortho.setChecked(_Settings.ortho)
    level = None
    top_cb = top_off = None
    if scene is not None and piani.levels(scene):
        level = piani.level_combo(scene, piani.active_id(scene))

        def on_level(_i) -> None:           # l'altezza del piano è proposta
            lv = piani.get(scene, level.currentData())
            if lv:
                height.setValue(lv["h"])
        level.currentIndexChanged.connect(on_level)
        form.addRow("Piano", level)
    form.addRow("Spessore (m)", thick)
    form.addRow("Altezza (m)", height)
    if level is not None:               # parte alta legata a un piano
        top_cb, top_off = piani.add_top_rows(form, scene, height,
                                             _Settings.tlv, _Settings.toff)
    form.addRow("Lato di ricalco (Spazio lo inverte)", align)
    form.addRow("Base: sopra la quota del piano / del clic (m)", base)
    form.addRow("Nome", name)
    form.addRow(ortho)
    lay.addLayout(form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.button(QDialogButtonBox.Ok).setText("Disegna")
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return False
    _Settings.thickness = thick.value()
    _Settings.height = height.value()
    _Settings.base_offset = base.value()
    _Settings.name = name.text().strip() or "Muro"
    _Settings.align = align.currentData()
    _Settings.ortho = ortho.isChecked()
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
    return True


# ---------------------------------------------------------------------------
# Strumento interattivo (voce nel menu Extensions)
# ---------------------------------------------------------------------------

class MuriTool(Tool):
    name = "Muri"
    shortcut = None
    description = "Traccia muri cliccando i punti dell'asse."
    vcb_label = "Lunghezza"

    def __init__(self) -> None:
        self._entering = False
        self._vp = None
        self._reset()

    def _reset(self) -> None:
        self.points: list[QVector3D] = []
        self.hover_point: QVector3D | None = None
        self.last_dir: QVector3D | None = None   # per digitare senza mouse

    def _ortho(self, p: QVector3D) -> QVector3D:
        """Con l'ortogonale attivo il punto cade sull'asse X o Y del
        punto precedente (quello dominante)."""
        if not (_Settings.ortho and self.points):
            return p
        last = self.points[-1]
        if abs(p.x() - last.x()) >= abs(p.y() - last.y()):
            return QVector3D(p.x(), last.y(), p.z())
        return QVector3D(last.x(), p.y(), p.z())

    def _level(self):
        from . import piani
        scene = getattr(self._vp, "scene", None)
        return piani.get(scene, _Settings.level) if scene is not None else None

    def _buffer(self) -> str:
        return getattr(self._vp, "_value_buffer", "") or ""

    # ---- Ciclo di vita ------------------------------------------------------
    def on_activate(self, viewport) -> None:
        if self._entering:                 # richiamato da set_active_tool
            self._vp = viewport
            self._reset()
            viewport.flash_status(
                "Muri: clic per i punti · Spazio = lato · C = chiudi · "
                "Invio = fine", 6000)
            return
        # Dal menu (one-shot): chiedi i parametri e diventa lo strumento attivo.
        if not ask_settings(viewport.window(), viewport.scene):
            return
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def on_deactivate(self, viewport) -> None:
        self._reset()

    # ---- Input spaziale -----------------------------------------------------
    def on_click(self, ctx: ToolContext) -> None:
        raw = QVector3D(ctx.world)
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
        ctx.viewport.update()

    def on_double_click(self, ctx: ToolContext) -> None:
        # Il primo clic del doppio clic ha già aggiunto il punto.
        self._commit(ctx.viewport, closed=False)

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = self._ortho(QVector3D(ctx.world))
        ctx.viewport.update()

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    # ---- Tastiera -----------------------------------------------------------
    def claims_key(self, key: int, modifiers) -> bool:
        """Spazio, C, O, F8 arrivano a noi invece che alle scorciatoie della
        finestra. Le lettere e lo spazio restano della casella misure mentre
        stai digitando (es. "3cm")."""
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
        return key == Qt.Key_C and bool(self.points)

    def _exit(self, viewport) -> None:
        """Esce dal comando: torna allo strumento Seleziona."""
        self._reset()
        viewport.update()
        win = viewport.window()
        back = getattr(win, "activate_select_tool", None)
        if callable(back):
            back()

    def context_menu(self, viewport, pos) -> bool:
        """Tasto destro: chiude la catena in corso (se ha almeno un tratto)
        ed esce dal comando, invece di aprire il menu."""
        if len(_dedupe([(p.x(), p.y()) for p in self.points], False)) >= 2:
            self._commit(viewport, closed=False)
        self._exit(viewport)
        return True

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            self._exit(viewport)          # Esc: annulla la catena ed esce
            return True
        if key == Qt.Key_Space:
            _Settings.align = "left" if _Settings.align == "right" else "right"
            viewport.flash_status(
                f"Ricalco {ALIGN_NAMES[_Settings.align].lower()}", 2000)
            viewport.update()
            return True
        if key == Qt.Key_C and self.points:
            if len(_dedupe([(p.x(), p.y()) for p in self.points], True)) < 3:
                viewport.flash_status("Per chiudere servono almeno 3 punti", 3000)
            else:
                self._commit(viewport, closed=True)
            return True
        if key in (Qt.Key_O, Qt.Key_F8):
            _Settings.ortho = not _Settings.ortho
            if self.hover_point is not None:
                self.hover_point = self._ortho(self.hover_point)
            viewport.flash_status(
                "Ortogonale " + ("attivo" if _Settings.ortho else "disattivato"),
                2000)
            viewport.update()
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter) and self.points:
            self._commit(viewport, closed=False)
            return True
        if key == Qt.Key_Backspace and self.points:
            self.points.pop()
            viewport.update()
            return True
        return False

    def on_value(self, viewport, value) -> bool:
        """Misura digitata: lunghezza lungo la direzione del cursore (o
        dell'ultimo tratto), oppure "dx;dy" come spostamento esatto."""
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
        viewport.update()
        return True

    def status_clause(self) -> str:
        return (f"Ricalco {ALIGN_NAMES[_Settings.align].lower()} (Spazio) · "
                f"Ortogonale {'ON' if _Settings.ortho else 'OFF'} (O/F8) · "
                "C = chiudi · Invio = fine")

    # ---- Anteprima e misure a schermo ---------------------------------------
    def value_label(self):
        """Lunghezza del tratto in corso, vicino al cursore e nella casella
        misure."""
        if not self.points or self.hover_point is None:
            return None
        a, b = self.points[-1], self.hover_point
        if (b - a).length() < EPS:
            return None
        return (fmt_len((b - a).length()), (a + b) * 0.5)

    def rubber_band_lines(self):
        pts = list(self.points)
        if self.hover_point is not None and pts and (
                self.hover_point - pts[-1]).length() > EPS:
            pts.append(self.hover_point)
        flat = _dedupe([(p.x(), p.y()) for p in pts], False)
        if len(flat) < 2:
            return []
        z = self.points[0].z()
        lvl = self._level()
        if lvl:
            z = lvl["z"] + _Settings.base_offset
        d_left, d_right = side_offsets(_Settings.thickness, _Settings.align)
        left, right = offset_points(flat, False, d_left, d_right)
        P = QVector3D
        lines = [(P(*flat[i], z), P(*flat[i + 1], z))
                 for i in range(len(flat) - 1)]            # linea tracciata
        for side in (left, right):
            lines += [(P(*side[i], z), P(*side[i + 1], z))
                      for i in range(len(side) - 1)]
        lines += [(P(*left[0], z), P(*right[0], z)),
                  (P(*left[-1], z), P(*right[-1], z))]
        return lines

    def draw_overlay(self, viewport, painter) -> None:
        try:
            self._draw(viewport, painter)
        except Exception:        # mai rompere il ciclo di disegno
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

        # Lato di riferimento (la linea tracciata) in un colore diverso.
        ref = list(self.points)
        if self.hover_point is not None and (
                self.hover_point - ref[-1]).length() > EPS:
            ref.append(self.hover_point)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(REF_COLOR, 3))
        for a, b in zip(ref, ref[1:]):
            pa = viewport._world_to_pixel(a)
            pb = viewport._world_to_pixel(b)
            if pa is not None and pb is not None:
                painter.drawLine(QPointF(pa[0], pa[1]), QPointF(pb[0], pb[1]))

        # Lunghezza di ogni tratto già fissato.
        for a, b in zip(self.points, self.points[1:]):
            px = viewport._world_to_pixel((a + b) * 0.5)
            if px is not None:
                chip(fmt_len((b - a).length()), px[0], px[1] - 14,
                     QColor(255, 255, 255, 225), QColor(20, 20, 20))

        # Solo la misura che stai digitando (niente riquadro di aiuti).
        typed = self._buffer()
        if typed:
            text = f"Misura: {typed}"
            w = fm.horizontalAdvance(text) + 16
            h = fm.height() + 12
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(30, 30, 30, 200))
            painter.drawRoundedRect(QRectF(12, 44, w, h), 6, 6)
            painter.setPen(QPen(QColor(255, 255, 255)))
            painter.drawText(QPointF(20, 44 + 6 + fm.ascent()), text)
        painter.restore()

    # ---- Creazione ----------------------------------------------------------
    def _commit(self, viewport, closed: bool) -> None:
        if getattr(viewport.scene, "edit_group", None) is not None:
            viewport.flash_status(
                "Chiudi il gruppo che stai modificando, poi crea i muri", 4000)
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
        if tlv:                         # altezza = fino al piano di arrivo
            from . import piani
            hl = piani.height_for(viewport.scene, tlv, toff,
                                  lvl["id"] if lvl else None, base_z)
            if hl is None:
                viewport.flash_status(
                    "Nessun piano di arrivo: uso l'altezza indicata", 4000)
                tlv = None
            else:
                h = hl
        count = [0]

        def mutate(scene):
            count[0] = build_walls(scene, pts2d, closed, t, h, base_z, name,
                                   align, lvl, off, tlv, toff)
            update_roof_clips(scene)

        viewport.history.execute(MuriCommand(mutate))
        viewport.notify_scene_changed()
        viewport.flash_status(f"{count[0]} muri creati", 3000)
        self._reset()
        viewport.update()


# ---------------------------------------------------------------------------
# Registrazione sulla barra MyHouse (chiamata da myhouse/__init__.py)
# ---------------------------------------------------------------------------

ORDER = 10          # posizione del pulsante nella barra (più basso = prima)


def _wall_icon():
    """Icona di una pianta di muro, disegnata a codice (nessun file esterno)."""
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


# ---------------------------------------------------------------------------
# Modifica muro (altezza e spessore di un muro già creato)
# ---------------------------------------------------------------------------

def _selected_walls(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and wall_data(g) is not None and g not in out:
            out.append(g)
    return out


def edit_walls(viewport, walls=None) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status("Chiudi il gruppo che stai modificando", 4000)
        return
    walls = walls or _selected_walls(scene)
    if not walls:
        viewport.flash_status("Seleziona un muro creato con lo strumento Muri",
                              4000)
        return
    chains = {wall_data(g).get("chain") for g in walls} - {None}
    if chains:                         # i muri della stessa catena vanno insieme
        walls = list(walls)
        for g in scene.groups:
            d = wall_data(g)
            if d and d.get("chain") in chains and g not in walls:
                walls.append(g)
    first = wall_data(walls[0])
    dlg = QDialog(viewport.window())
    dlg.setWindowTitle("Modifica muro" if len(walls) == 1
                       else f"Modifica {len(walls)} muri (catena)")
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    thick = _spin(first["th"], 0.02, 5.0)
    height = _spin(first["h"], 0.1, 100.0)
    form.addRow("Spessore (m)", thick)
    form.addRow("Altezza (m)", height)
    from . import piani
    has_levels = bool(piani.levels(scene))
    top_cb = top_off = None
    if has_levels:                      # parte alta legata a un piano
        top_cb, top_off = piani.add_top_rows(form, scene, height,
                                             first.get("tlv"),
                                             first.get("toff", 0.0))
    init_off = first.get("off", first["z0"])
    if has_levels:
        lvl_cb = piani.level_combo(scene, first.get("lv"))
        off_sp = _spin(init_off, -100.0, 1000.0)
        form.addRow("Piano", lvl_cb)
        form.addRow("Distanza dal piano (Nessuno: quota base) (m)", off_sp)
    lay.addLayout(form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return
    t, h = thick.value(), height.value()
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
            hh = h
            if top_cb is not None:
                ex["tlv"], ex["toff"] = None, None          # None = togli
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
            rebuild_wall(g, t, hh, ex)
        update_roof_clips(sc)
        try:
            from . import finestre
            finestre.update_openings(sc)
        except ImportError:
            pass

    hist = viewport.history
    hist.execute(MuriCommand(mutate))
    if getattr(hist, "last_error", None):
        viewport.flash_status("Muri: " + str(hist.last_error).split(": ", 1)[-1],
                              6000)
        return
    viewport.notify_scene_changed()
    viewport.update()
    if failed[0]:
        viewport.flash_status(
            "Nessun piano di arrivo valido (sotto la base?): "
            "uso l'altezza indicata", 6000)
        return
    viewport.flash_status(f"{len(walls)} muri aggiornati", 3000)


def top_props(d):
    """Righe per l'outliner: altezza legata a un piano di arrivo."""
    if not d.get("tlv"):
        return []
    arrivo = ("Piano successivo" if d["tlv"] == "next"
              else "Piano di arrivo")
    return [("Altezza fino a", arrivo),
            ("Distanza dall'arrivo", fmt_len(d.get("toff", 0.0)))]


def _outliner_kind(group):
    d = wall_data(group)
    if d is None:
        return None
    from . import piani
    return {"type": "Muro",
            "props": [("Spessore", fmt_len(d["th"])),
                      ("Altezza", fmt_len(d["h"]))]
            + piani.level_props(d) + top_props(d)}


def _hook_double_click(vp) -> None:
    """Doppio clic su un muro = modifica spessore e altezza. Lo strumento
    Seleziona, sul doppio clic di un gruppo, chiama viewport.begin_group_edit:
    per i muri apriamo il dialogo, per ogni altro gruppo resta com'era."""
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

    def hset(d, h):                      # il piano cambia quota: nuova altezza
        d["h"] = h

    piani.register_kind(
        "muro", KEY, wall_data, lambda d: d["z0"], zset,
        lambda g, d: setattr(g, "children", [wall_part(d, wall_pose(g))]),
        lambda d: d["h"], hset)


def register(api) -> None:
    _register_level_kind()
    api.add_button("Muri", "Traccia muri cliccando i punti dell'asse",
                   _wall_icon(), api.run_tool(MuriTool()))
    app = api.app
    _hook_double_click(api.window.viewport)
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        from PySide6.QtCore import QTimer

        def context(menu, selection) -> None:
            if not _selected_walls(app.viewport.scene):
                return
            menu.addSeparator()
            menu.addAction(
                "Modifica muro…",
                lambda: QTimer.singleShot(
                    0, lambda: edit_walls(app.viewport)))

        add_ctx(context)
    add_kind = getattr(app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
