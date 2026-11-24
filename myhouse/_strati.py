# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import copy
import json
import math
import os
import tempfile

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QInputDialog, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ._lingua import tr
from ._scroll import fit_dialog

PATTERN_KINDS = ("earth", "sand", "sand_dense", "plaster", "concrete", "steel",
                 "insulation", "hollow")
HATCH_KINDS = ("fill", "lines", "cross") + PATTERN_KINDS
HATCH_MODES = (("none", tr("Nessun retino")),
               ("fill", tr("Riempimento colore")),
               ("lines", tr("Linee")),
               ("cross", tr("Linee incrociate")),
               ("insulation", tr("Isolante ondulato")),
               ("hollow", tr("Laterizio forato")),
               ("concrete", tr("Calcestruzzo")),
               ("earth", tr("Terra")),
               ("sand", tr("Sabbia")),
               ("sand_dense", tr("Sabbia fitta")),
               ("plaster", tr("Gesso")),
               ("steel", tr("Acciaio")))
DEFAULT_HATCH = {"mode": "lines", "color": None, "angle": 45.0,
                 "angle2": 135.0, "step": 0.03}


DOORWIN_HATCH = {"mode": "lines", "color": None, "angle": 45.0,
                 "angle2": 135.0, "step": 0.02}


def doorwin_hatch(h):
    if isinstance(h, dict) and h.get("mode"):
        return h
    return copy.deepcopy(DOORWIN_HATCH)


def layers_total(layers) -> float:
    return sum(float(l["t"]) for l in layers)


def layer_bands(layers):
    tot = layers_total(layers)
    out, acc = [], 0.0
    for ly in layers:
        t = float(ly["t"])
        out.append((acc / tot, (acc + t) / tot, ly))
        acc += t
    return out


def normalize_hatch(h):
    if not isinstance(h, dict) or h.get("mode") not in HATCH_KINDS:
        return None
    out = dict(DEFAULT_HATCH)
    out.update({k: v for k, v in h.items() if v is not None or k == "color"})
    if out["mode"] != "fill" and not out.get("color"):
        out["color"] = [0.0, 0.0, 0.0]
    return out


def layer_subs_flat(d):
    layers = d["layers"]
    n = len(layers)
    out, acc = [], 0.0
    for i, ly in enumerate(layers):
        t = float(ly["t"])
        s = {k: v for k, v in d.items() if k != "layers"}
        s["th"] = t
        s["_dz"] = acc
        s["_lay"] = {"i": i, "n": n, "ly": ly,
                     "lm": "%s %d" % (ly.get("name") or tr("strato"), i + 1)}
        out.append(s)
        acc += t
    return out


def paint_layer_face(f, q, zone, d, zone_mat) -> bool:
    info = d.get("_lay")
    if not info:
        return False
    from . import muri
    ly, i, n = info["ly"], info["i"], info["n"]
    outer = (zone == "top" and i == 0) or (zone == "bottom" and i == n - 1)
    col, tex = ly.get("col"), ly.get("tex")
    if outer:
        zc, zt = d.get("col_" + zone), d.get("tex_" + zone)
    else:
        zc, zt = d.get("col_side"), d.get("tex_side")
    ce, te = col or zc, tex or zt
    shade = False
    if not outer and not col and not te:
        k = 1.0 - 0.16 * (i % 3)
        ce = [c * k for c in (ce or muri.EDGE_COLOR)]
        shade = True
    hh = normalize_hatch(ly.get("hatch")) if zone == "side" else None
    if hh and not te and q is not None:
        if muri.paint_edge_hatch(f, q, {"hatch": hh, "base": ce}):
            f.attrs["mat"] = info["lm"]
            return True
    if not ce and not te:
        return False
    if muri.paint_face(f, ce, te) and not te:
        f.attrs["mat"] = (zone_mat.get(zone) if outer and not col
                          else info["lm"])
    return True


HATCH_PPM = 2000.0
HATCH_LINE_PX = 3.0
HATCH_MAX_PX = 2048
HATCH_TOP_ROT = 0.0
HATCH_FRONT_ROT = 0.0


def _hatch_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    for root in (base, tempfile.gettempdir()):
        p = os.path.join(root, "IngeTrazo_hatch")
        try:
            os.makedirs(p, exist_ok=True)
            return p
        except OSError:
            continue
    return None


def _axis(ang):
    a = float(ang) % 180.0
    s, c = math.sin(math.radians(a)), math.cos(math.radians(a))
    if abs(s) < 0.03:
        return 0.0, 1.0
    if abs(c) < 0.03:
        return 1.0, 0.0
    return s, c


def _common(ps):
    ps = [p for p in ps if p]
    if not ps:
        return 16.0
    if len(ps) == 1:
        return ps[0]
    a, b = ps
    for k in range(1, 9):
        m = round(k * a / b)
        if m >= 1 and abs(k * a - m * b) < 0.6:
            return k * a
    return a


_PAT_CELL = {"earth": (0.5, 0.5), "plaster": (0.7, 0.7), "sand": (1.76, 0.88),
             "sand_dense": (0.88, 0.44), "steel": (0.198, 0.198),
             "concrete": (1.0, 1.0)}


def _pattern_texture(hh, base, front):
    try:
        from .sezione_strati import (HOLLOW_H, HOLLOW_W, INS_MM, INS_PX, INS_PY,
                                     PAT_M, hatch_segments)
    except Exception:
        return None
    kind = hh["mode"]
    step = float(hh["step"])
    scala = max(0.1, step / 0.06)
    if kind == "hollow":
        wm, hm = HOLLOW_W * scala, HOLLOW_H * scala
    elif kind == "insulation":
        wm, hm = INS_PX * INS_MM * scala, INS_PY * INS_MM * scala
    elif kind in _PAT_CELL:
        cx, cy = _PAT_CELL[kind]
        wm, hm = cx * PAT_M * scala, cy * PAT_M * scala
    else:
        return None
    ppm = min(HATCH_PPM, HATCH_MAX_PX / max(wm, hm))
    W, H = max(8, int(round(wm * ppm))), max(8, int(round(hm * ppm)))
    bg = tuple(base or (0.93, 0.93, 0.93))
    lc = tuple(hh.get("color") or (0.0, 0.0, 0.0))
    key = "P2|%s|%.4f|%s|%s" % (kind, scala, bg, lc)
    import hashlib
    folder = _hatch_dir()
    if folder is None:
        return None
    path = os.path.join(folder, "hatch_%s.png"
                        % hashlib.md5(key.encode()).hexdigest()[:12])
    if not os.path.isfile(path):
        def qc(c):
            return QColor(*[int(round(max(0.0, min(1.0, v)) * 255)) for v in c[:3]])
        img = QImage(W, H, QImage.Format_RGB32)
        img.fill(qc(bg))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(QPen(qc(lc), max(1.0, 0.0015 * ppm) * max(1.0, scala)))
        mw, mh = wm * 0.5, hm * 0.5
        for (ua, za), (ub, zb) in hatch_segments(
                -mw, wm + mw, -mh, hm + mh, kind, step, 0.0, 0.0, None):
            p.drawLine(QPointF(ua * ppm, H - za * ppm),
                       QPointF(ub * ppm, H - zb * ppm))
        p.end()
        if not img.save(path):
            return None
    rot = (HATCH_FRONT_ROT if front else HATCH_TOP_ROT)
    if kind == "insulation":
        rot += float(hh["angle"])
    return {"path": path, "sw": W / ppm, "sh": H / ppm, "rot": rot}


def hatch_texture(h, base, front=False):
    hh = normalize_hatch(h)
    if hh and hh["mode"] in PATTERN_KINDS:
        return _pattern_texture(hh, base, front)
    if not hh or hh["mode"] not in ("lines", "cross"):
        return None
    step = max(4.0, float(hh["step"]) * HATCH_PPM)
    angs = [hh["angle"]] + ([hh["angle2"]] if hh["mode"] == "cross" else [])
    fam = [_axis(a) for a in angs]
    W = _common([step / s if s else None for s, c in fam])
    H = _common([step / abs(c) if c else None for s, c in fam])
    W = max(8, min(HATCH_MAX_PX, int(round(W))))
    H = max(8, min(HATCH_MAX_PX, int(round(H))))
    bg = tuple(base or (0.93, 0.93, 0.93))
    lc = tuple(hh.get("color") or (0.0, 0.0, 0.0))
    key = "%s|%s|%.2f|%.2f|%.4f|%s|%s" % (hh["mode"], angs[0], angs[-1], step,
                                         W * 1000 + H, bg, lc)
    import hashlib
    name = "hatch_%s.png" % hashlib.md5(key.encode()).hexdigest()[:12]
    folder = _hatch_dir()
    if folder is None:
        return None
    path = os.path.join(folder, name)
    if not os.path.isfile(path):
        def qc(c):
            return QColor(*[int(round(max(0.0, min(1.0, v)) * 255)) for v in c[:3]])
        img = QImage(W, H, QImage.Format_RGB32)
        img.fill(qc(bg))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(QPen(qc(lc), HATCH_LINE_PX))
        L = float(W + H)
        for s, c in fam:
            qs = [s * x + c * y for x in (0, W) for y in (0, H)]
            for k in range(math.floor(min(qs) / step) - 1,
                           math.ceil(max(qs) / step) + 2):
                q = k * step
                x0, y0 = s * q, c * q
                dx, dy = c, -s
                p.drawLine(QPointF(x0 - dx * L, y0 - dy * L),
                           QPointF(x0 + dx * L, y0 + dy * L))
        p.end()
        if not img.save(path):
            return None
    return {"path": path, "sw": W / HATCH_PPM, "sh": H / HATCH_PPM,
            "rot": HATCH_FRONT_ROT if front else HATCH_TOP_ROT}


class HatchPick(QWidget):

    def __init__(self, cur=None, thick=None):
        super().__init__()
        from .muri import ColorPick, _spin
        self._thick = thick
        base = dict(DEFAULT_HATCH)
        if isinstance(cur, dict) and cur.get("mode") in HATCH_KINDS:
            base.update(cur)
        else:
            base["mode"] = "none"
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.mode = QComboBox()
        for key, label in HATCH_MODES:
            self.mode.addItem(label, key)
        self.mode.setCurrentIndex(self.mode.findData(base["mode"]))
        self.col = ColorPick(base.get("color"))
        self._auto = not base.get("color")
        self.col.btn.clicked.connect(lambda: setattr(self, "_auto", False))
        self.a1 = _spin(base["angle"], -360.0, 360.0)
        self.a1.setPrefix(tr("angolo "))
        self.a1.setSuffix("°")
        self.a2 = _spin(base["angle2"], -360.0, 360.0)
        self.a2.setPrefix(tr("angolo 2 "))
        self.a2.setSuffix("°")
        self.step = _spin(base["step"] * 100.0, 0.1, 100.0)
        self.step.setPrefix(tr("passo "))
        self.step.setSuffix(" cm")
        scl = base["step"] / 0.06 if base["mode"] in PATTERN_KINDS else 1.0
        self.scl = _spin(min(max(scl, 0.1), 20.0), 0.1, 20.0)
        self.scl.setPrefix(tr("scala "))
        self.rip = QComboBox()
        self.rip.addItem(tr("ripet. —"), 0)
        for k in range(1, 11):
            self.rip.addItem(tr("ripet. {0}").format(k), k)
        self.rip.setToolTip(tr("Adatta il retino: numero di ripetizioni (1-10) "
                               "nello spessore dello strato. — = manuale."))
        self.rip.setCurrentIndex(max(0, self.rip.findData(int(base.get("rip") or 0))))
        lay.addWidget(self.mode)
        for w in (self.col, self.a1, self.a2, self.step, self.scl, self.rip):
            lay.addWidget(w)
        self.mode.currentIndexChanged.connect(self._ang0)
        self.mode.currentIndexChanged.connect(self._show)
        self.mode.currentIndexChanged.connect(self.refit)
        self.rip.currentIndexChanged.connect(self.refit)
        self.a1.valueChanged.connect(self.refit)
        self._show()
        self.refit()

    def set(self, cur) -> None:
        base = dict(DEFAULT_HATCH)
        if isinstance(cur, dict) and cur.get("mode") in HATCH_KINDS:
            base.update(cur)
        else:
            base["mode"] = "none"
        self.mode.blockSignals(True)
        self.mode.setCurrentIndex(self.mode.findData(base["mode"]))
        self.mode.blockSignals(False)
        self._auto = not base.get("color")
        self.col.set(base.get("color"))
        self.a1.setValue(base["angle"])
        self.a2.setValue(base["angle2"])
        self.step.setValue(base["step"] * 100.0)
        scl = base["step"] / 0.06 if base["mode"] in PATTERN_KINDS else 1.0
        self.scl.setValue(min(max(scl, 0.1), 20.0))
        self.rip.setCurrentIndex(max(0, self.rip.findData(int(base.get("rip") or 0))))
        self._show()
        self.refit()

    def _ang0(self, *_a) -> None:
        if self.mode.currentData() == "insulation":
            self.a1.setValue(0.0)

    def _show(self, *_a) -> None:
        m = self.mode.currentData()
        if self._auto:
            self.col.value = (0.0, 0.0, 0.0) if m not in ("fill", "none") else None
            self.col._show()
        self.col.setVisible(m != "none")
        self.a1.setVisible(m in ("lines", "cross", "insulation"))
        self.a2.setVisible(m == "cross")
        self.step.setVisible(m in ("lines", "cross"))
        self.scl.setVisible(m in PATTERN_KINDS)
        self.rip.setVisible(self._thick is not None
                            and m in ("cross", "insulation", "hollow"))

    def _auto_n(self) -> int:
        m = self.mode.currentData()
        if self._thick is None or m not in ("cross", "insulation", "hollow"):
            return 0
        return int(self.rip.currentData() or 0)

    def refit(self, *_a) -> None:
        n = self._auto_n()
        m = self.mode.currentData()
        self.step.setEnabled(not n)
        self.scl.setEnabled(not n)
        if not n:
            return
        try:
            th = float(self._thick())
            a = math.radians(self.a1.value())
            if m == "cross":
                sp = [1.0 / abs(f(a)) for f in (math.sin, math.cos)
                      if abs(f(a)) > 1e-6]
                self.step.setValue(th / (n * min(sp)) * 100.0)
            else:
                from .sezione_strati import fit_scala
                self.scl.setValue(fit_scala(m, th, self.a1.value(), n))
        except Exception:
            pass

    def result(self):
        m = self.mode.currentData()
        if m == "none":
            return None
        col = self.col.result()
        if col is None and m != "fill":
            col = [0.0, 0.0, 0.0]
        step = (self.scl.value() * 0.06 if m in PATTERN_KINDS
                else self.step.value() / 100.0)
        out = {"mode": m, "color": col,
               "angle": self.a1.value(), "angle2": self.a2.value(),
               "step": step}
        n = self._auto_n()
        if n:
            out["rip"] = n
        return out


class LayerPreview(QWidget):

    def __init__(self, get_rows):
        super().__init__()
        self._get = get_rows
        self.setFixedHeight(150)
        self.setMinimumWidth(510)

    @staticmethod
    def _qc(c, default=(0.93, 0.93, 0.93)):
        c = c or default
        return QColor(*[int(round(max(0.0, min(1.0, v)) * 255)) for v in c[:3]])

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rows = self._get()
        W, H = self.width(), self.height()
        p.fillRect(0, 0, W, H, self.palette().window())
        tot = sum(r[1] for r in rows)
        if not rows or tot <= 0:
            p.end()
            return
        lm = 84.0
        bw = min(300, W - 150 - lm)
        x0, y, usable = 6.0 + lm, 4.0, H - 8.0
        ytop = y
        scale = usable / tot
        labels = []
        for nome, t, col, hh in rows:
            h = usable * t / tot
            rect = QRectF(x0, y, bw, h)
            base = col
            if hh and hh["mode"] == "fill" and hh.get("color"):
                base = hh["color"]
            p.setClipRect(rect)
            p.fillRect(rect, self._qc(base))
            if hh and hh["mode"] in ("lines", "cross"):
                self._hatch(p, rect, hh, scale)
            elif hh and hh["mode"] in PATTERN_KINDS:
                self._pattern(p, rect, hh, scale)
            p.setClipping(False)
            p.setPen(QPen(QColor(60, 60, 60), 1))
            p.drawRect(rect)
            labels.append((y + h / 2.0, "%s  %g cm" % (nome or "", round(t * 100, 2))))
            y += h
        lh = float(max(14, p.fontMetrics().height() + 2))
        ys = [c - lh / 2.0 for c, _t in labels]
        for i in range(1, len(ys)):
            ys[i] = max(ys[i], ys[i - 1] + lh)
        over = ys[-1] + lh - H
        if over > 0:
            ys[-1] -= over
            for i in range(len(ys) - 2, -1, -1):
                ys[i] = min(ys[i], ys[i + 1] - lh)
        if ys[0] < 0:
            ys[0] = 0.0
            for i in range(1, len(ys)):
                ys[i] = max(ys[i], ys[i - 1] + lh)
        qx = x0 - 10.0
        p.setPen(QPen(QColor(0, 0, 0), 1))
        p.drawLine(QPointF(qx, ytop), QPointF(qx, ytop + usable))
        p.drawLine(QPointF(qx - 4, ytop), QPointF(qx + 4, ytop))
        p.drawLine(QPointF(qx - 4, ytop + usable), QPointF(qx + 4, ytop + usable))
        p.drawText(QRectF(0, ytop, qx - 6, usable),
                   Qt.AlignVCenter | Qt.AlignRight,
                   "TOT %g cm" % round(tot * 100, 2))
        p.setPen(QColor(0, 0, 0))
        for yy, (_c, txt) in zip(ys, labels):
            p.drawText(QRectF(x0 + bw + 10, yy, W - bw - 20, lh),
                       Qt.AlignVCenter | Qt.AlignLeft, txt)
        p.end()

    @staticmethod
    def _pattern(p, rect, hh, scale):
        try:
            from .sezione_strati import hatch_segments
            lc = hh.get("color") or (0.0, 0.0, 0.0)
            p.setPen(QPen(LayerPreview._qc(lc), 1))
            t, ln = rect.height() / scale, rect.width() / scale
            for (ua, za), (ub, zb) in hatch_segments(
                    0.0, t, 0.0, ln, hh["mode"], float(hh["step"]),
                    float(hh["angle"]), 0.0, hh.get("angle2")):
                p.drawLine(QPointF(rect.left() + za * scale,
                                   rect.top() + ua * scale),
                           QPointF(rect.left() + zb * scale,
                                   rect.top() + ub * scale))
        except Exception:
            pass

    @staticmethod
    def _hatch(p, rect, hh, scale):
        step = max(3.0, float(hh["step"]) * scale)
        lc = hh.get("color") or (0.0, 0.0, 0.0)
        p.setPen(QPen(LayerPreview._qc(lc), 1))
        angs = [hh["angle"]] + ([hh["angle2"]] if hh["mode"] == "cross" else [])
        L = rect.width() + rect.height()
        for ang in angs:
            a = math.radians(float(ang))
            dx, dy = math.cos(a), -math.sin(a)
            nx, ny = math.sin(a), math.cos(a)
            qs = [nx * x + ny * yy for x in (rect.left(), rect.right())
                  for yy in (rect.top(), rect.bottom())]
            for k in range(math.floor(min(qs) / step),
                           math.ceil(max(qs) / step) + 1):
                q = k * step
                ox, oy = nx * q, ny * q
                p.drawLine(QPointF(ox - dx * L, oy - dy * L),
                           QPointF(ox + dx * L, oy + dy * L))


def _no_reset(cp, after=None) -> None:
    for b in cp.findChildren(QPushButton):
        if b is not cp.btn:
            b.hide()

    def reset(_pos=None) -> None:
        cp._reset()
        if after:
            after()
    cp.btn.setContextMenuPolicy(Qt.CustomContextMenu)
    cp.btn.customContextMenuRequested.connect(reset)
    cp.btn.setToolTip(tr("Clic destro: torna al colore predefinito"))


def edit_layers(parent, layers, presets=None, kind="muro"):
    from .muri import ColorPick, TexturePick, _spin
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("Strati (in ordine, da un lato all'altro)"))
    lay = QVBoxLayout(dlg)
    holder = QVBoxLayout()
    holder.setSpacing(1)
    holder.setContentsMargins(4, 2, 4, 2)
    holder.addStretch(1)
    inner = QWidget()
    inner.setLayout(holder)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(inner)
    rows = []

    def preview_rows():
        out = []
        for _w, nm, th, cp, _tp, hp in rows:
            out.append((nm.text().strip(), th.value(), cp.result(),
                        normalize_hatch(hp.result())))
        return out
    preview = LayerPreview(preview_rows)
    lay.addWidget(preview, 0, Qt.AlignHCenter)
    lay.addWidget(scroll, 1)
    tick = QTimer(dlg)
    tick.timeout.connect(preview.update)
    tick.start(250)

    def add_row(ly):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        h = QHBoxLayout()
        v.addLayout(h)
        nm = QLineEdit(ly.get("name") or "")
        nm.setPlaceholderText(tr("Nome strato"))
        nm.setMinimumWidth(120)
        nm.setMaximumWidth(160)
        th = _spin(ly.get("t", 0.10), 0.001, 5.0)
        th.setSuffix(" m")
        cp, tp = ColorPick(ly.get("col")), TexturePick(ly.get("tex"))
        hp = HatchPick(ly.get("hatch"), lambda: th.value())
        hp.setToolTip(tr("Retino di sezione"))
        th.valueChanged.connect(hp.refit)
        _no_reset(cp)
        _no_reset(hp.col, lambda: (setattr(hp, "_auto", True), hp._show()))
        rm = QPushButton("✕")
        hp.layout().addStretch(1)
        rm.setFixedWidth(26)
        rm.setToolTip(tr("Elimina questo strato"))
        h.addWidget(rm)
        for x in (nm, th):
            h.addWidget(x)
        h.addWidget(cp, 1)
        h.addWidget(tp, 1)
        h2 = QHBoxLayout()
        h2.setContentsMargins(30, 0, 0, 0)
        h2.addWidget(hp)
        v.addLayout(h2)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        v.addWidget(sep)
        rec = (w, nm, th, cp, tp, hp)
        rows.append(rec)
        holder.insertWidget(holder.count() - 1, w)

        def remove():
            if len(rows) > 1:
                rows.remove(rec)
                w.setParent(None)
                w.deleteLater()
        rm.clicked.connect(remove)

    for ly in (layers or [{"t": 0.10, "name": tr("intonaco")},
                          {"t": 0.20, "name": tr("muratura")}]):
        add_row(ly)
    add = QPushButton(tr("+ Aggiungi strato (in fondo)"))
    add.clicked.connect(lambda: add_row({"t": 0.10}))
    lay.addWidget(add)
    def set_rows(new_layers) -> None:
        for rec in list(rows):
            rows.remove(rec)
            rec[0].setParent(None)
            rec[0].deleteLater()
        for ly in copy.deepcopy(new_layers):
            add_row(ly)

    def current_layers():
        return [{"t": th.value(), "col": cp.result(), "tex": tp.result(),
                 "name": nm.text().strip(), "hatch": hp.result()}
                for _w, nm, th, cp, tp, hp in rows]

    if presets:
        top = QHBoxLayout()
        top.addWidget(QLabel(tr("Preset:")))
        pcb = QComboBox()
        pcb.addItem("—")
        pcb.addItems(list(presets))
        top.addWidget(pcb, 1)
        lay.insertLayout(0, top)

        def apply_preset(_i) -> None:
            name = pcb.currentText()
            if name in presets:
                set_rows(presets[name])
        pcb.currentIndexChanged.connect(apply_preset)

    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    clear = QPushButton(tr("Nessuno strato (elemento singolo)"))
    box.addButton(clear, QDialogButtonBox.ResetRole)
    flag = {"clear": False}

    def do_clear():
        flag["clear"] = True
        dlg.accept()
    clear.clicked.connect(do_clear)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    fit_dialog(dlg, 760, 520)
    if dlg.exec() != QDialog.Accepted:
        return None
    if flag["clear"]:
        return []
    return current_layers()


def layers_row(dlg, thick, state, presets=None, kind="muro"):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    btn, clr = QPushButton(), QPushButton(tr("Nessuno strato"))

    def show():
        L = state[0]
        thick.setEnabled(not L)
        clr.setEnabled(bool(L))
        if L:
            thick.setValue(min(layers_total(L), thick.maximum()))
            btn.setText(tr("Strati: ") + " + ".join(f"{l['t'] * 100:g}" for l in L)
                        + tr(" cm (modifica…)"))
        else:
            btn.setText(tr("Elemento a strati (più spessori accostati)…"))

    def edit():
        r = edit_layers(dlg, copy.deepcopy(state[0]), presets, kind)
        if r is not None:
            state[0] = r or None
            show()

    def clear():
        state[0] = None
        show()
    btn.clicked.connect(edit)
    clr.clicked.connect(clear)
    h.addWidget(btn, 1)
    h.addWidget(clr)
    show()
    w.refresh = show
    return w
