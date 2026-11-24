# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import copy
import importlib
import math
import numbers

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QVBoxLayout,
)

from tools.base import Tool, ToolContext

from ._lingua import tr
from ._scroll import scroll_form
from . import muri

ORDER = 998


KINDS = (
    dict(mod="muri", data="wall_data", builders=("wall_mesh",), how="wall"),
    dict(mod="solaio", data="slab_data", builders=("slab_mesh",),
         how="full", rebuild="rebuild_slab"),
    dict(mod="tetto", data="roof_data", builders=("roof_mesh",),
         how="full", rebuild="rebuild_roof", first_only=True),
    dict(mod="scale", data="stair_data", builders=("stair_mesh",),
         how="full", rebuild="rebuild_stair"),
    dict(mod="balaustre", data="railing_data", builders=("railing_mesh",),
         how="full", rebuild="rebuild_railing"),
    dict(mod="recinzioni", data="fence_data", builders=("fence_mesh",),
         how="full", rebuild="rebuild_fence"),
    dict(mod="pilastri", data="pillar_data", builders=("pillar_mesh",),
         how="update", rebuild="rebuild_pillar"),
    dict(mod="travi", data="beam_data", builders=("beam_mesh",),
         how="update", rebuild="rebuild_beam"),
    dict(mod="rampa", data="ramp_data", builders=("ramp_mesh",),
         how="full", rebuild="rebuild_ramp"),
    dict(mod="finestre", data="window_data", builders=("window_meshes",),
         how="update", rebuild="rebuild_window"),
    dict(mod="porte", data="door_data", builders=("door_meshes_all",),
         how="update", rebuild="rebuild_door"),
)

PLANE_TOL = 0.004
BOX_TOL = 0.005


def _module(name):
    try:
        return importlib.import_module("." + name, __package__)
    except Exception:
        return None


def _xyz(v, depth=0):
    if v is None or depth > 2:
        return None
    for attr in ("position", "pos"):
        val = getattr(v, attr, None)
        if val is None:
            continue
        if callable(val):
            try:
                val = val()
            except Exception:
                continue
        r = _xyz(val, depth + 1)
        if r:
            return r
    x = getattr(v, "x", None)
    if callable(x):
        try:
            return (float(v.x()), float(v.y()), float(v.z()))
        except Exception:
            pass
    try:
        if len(v) == 3 and all(isinstance(c, numbers.Real) for c in v):
            return (float(v[0]), float(v[1]), float(v[2]))
    except Exception:
        pass
    return None


def _collect(o, out, depth=0):
    p = _xyz(o)
    if p:
        out.append(p)
        return
    if depth > 3:
        return
    try:
        for it in o:
            _collect(it, out, depth + 1)
    except TypeError:
        pass


def face_points(face):
    pts = []
    try:
        _collect(face.triangulate(), pts)
    except Exception:
        pts = []
    if len(pts) < 3:
        for name in ("vertices", "verts", "outer", "loop", "points", "vs"):
            o = getattr(face, name, None)
            if o is None:
                continue
            if callable(o):
                try:
                    o = o()
                except Exception:
                    continue
            pts = []
            _collect(o, pts)
            if len(pts) >= 3:
                break
    return pts if len(pts) >= 3 else None


def face_sig(face):
    try:
        pts = face_points(face)
        nv = _xyz(face.normal())
        if not pts or not nv:
            return None
        ln = math.sqrt(sum(c * c for c in nv))
        if ln < 1e-9:
            return None
        n = tuple(c / ln for c in nv)
        k = float(len(pts))
        m = tuple(sum(p[i] for p in pts) / k for i in range(3))
        o = sum(n[i] * m[i] for i in range(3))
        if any(abs(sum(n[i] * p[i] for i in range(3)) - o) > 0.005
               for p in pts):
            return None
        lo = [min(p[i] for p in pts) for i in range(3)]
        hi = [max(p[i] for p in pts) for i in range(3)]
        return {"n": [round(c, 5) for c in n], "o": round(o, 5),
                "lo": [round(c, 4) for c in lo],
                "hi": [round(c, 4) for c in hi]}
    except Exception:
        return None


def _centre(s):
    return [(s["lo"][i] + s["hi"][i]) / 2 for i in range(3)]


def _inside(p, s):
    return all(s["lo"][i] - BOX_TOL <= p[i] <= s["hi"][i] + BOX_TOL
               for i in range(3))


def same_face(a, b) -> bool:
    if sum(a["n"][i] * b["n"][i] for i in range(3)) < 0.999:
        return False
    if abs(a["o"] - b["o"]) > PLANE_TOL:
        return False
    return _inside(_centre(b), a) or _inside(_centre(a), b)


def _paint(face, col, tex) -> None:
    attrs = face.attrs
    for k in ("color", "texture", "mat"):
        attrs.pop(k, None)
    muri.paint_face(face, col, tex)


def _paint_entry(face, e) -> None:
    _paint(face, e.get("col"), e.get("tex"))
    if e.get("mat"):
        face.attrs["mat"] = e["mat"]


def apply_paint(result, d) -> None:
    fp = d.get("fp") if isinstance(d, dict) else None
    base = d.get("fpb") if isinstance(d, dict) else None
    if not fp and not base:
        return
    meshes = result if isinstance(result, (tuple, list)) else [result]
    for m in meshes:
        for f in getattr(m, "faces", None) or ():
            attrs = f.attrs
            if base and (base.get("all") or (not attrs.get("color")
                                             and not attrs.get("texture"))):
                if base.get("all"):
                    _paint(f, base.get("col"), base.get("tex"))
                    if base.get("mat"):
                        f.attrs["mat"] = base["mat"]
                else:
                    muri.paint_face(f, base.get("col"), base.get("tex"))
            if not fp:
                continue
            sg = face_sig(f)
            if sg is None:
                continue
            hit = None
            for e in fp:
                if same_face(e, sg):
                    hit = e
            if hit is not None:
                _paint_entry(f, hit)


_INSTALLED = {"done": False}


def install() -> None:
    if _INSTALLED["done"]:
        return
    _INSTALLED["done"] = True
    for kind in KINDS:
        mod = _module(kind["mod"])
        if mod is None:
            continue
        for name in kind["builders"]:
            orig = getattr(mod, name, None)
            if orig is None or getattr(orig, "_pennello", False):
                continue

            def make(orig):
                def wrapped(d, *a, **k):
                    res = orig(d, *a, **k)
                    try:
                        apply_paint(res, d)
                    except Exception:
                        pass
                    return res
                wrapped._pennello = True
                wrapped.__name__ = getattr(orig, "__name__", "wrapped")
                wrapped.__doc__ = getattr(orig, "__doc__", None)
                return wrapped

            setattr(mod, name, make(orig))


class _Brush:
    col_b = None
    tex_b = None
    mode = "paint"


def ask_brush(parent):
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("Pennello"))
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    pk = muri.add_paint_rows(form, lambda k: getattr(_Brush, k, None),
                             (("b", tr("pennello")),))
    scroll_form(dlg, lay, form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.button(QDialogButtonBox.Ok).setText(tr("Dipingi"))
    bs = box.addButton(tr("Preleva e sostituisci"), QDialogButtonBox.ActionRole)
    bs.setToolTip(tr("Clic su una faccia: il suo materiale viene sostituito, "
                     "su tutti gli elementi, con il colore / texture scelti"))
    bs.clicked.connect(lambda: dlg.done(3))
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    r = dlg.exec()
    if r != QDialog.Accepted and r != 3:
        return False
    for k, v in muri.paint_results(pk).items():
        setattr(_Brush, k, v)
    _Brush.mode = "replace" if r == 3 else "paint"
    return "pick" if r == 3 else True


def _mat_key(face):
    a = face.attrs
    if a.get("mat"):
        return ("m", a["mat"])
    if a.get("texture") and a["texture"].get("path"):
        return ("t", a["texture"]["path"])
    if a.get("color"):
        return ("c", tuple(round(float(c), 3) for c in a["color"]))
    return ("n",)


class PennelloCommand(muri.MuriCommand):

    @staticmethod
    def _capture(scene) -> dict:
        s = muri.MuriCommand._capture(scene)
        s["mats"] = [(g, copy.deepcopy(getattr(g, "material", None)))
                     for g in scene.groups]
        return s

    @staticmethod
    def _restore(scene, s) -> None:
        muri.MuriCommand._restore(scene, s)
        for g, m in s["mats"]:
            g.material = m


def _pick_face(vp, x, y):
    for name in ("pick_face_placement", "pick_face_any"):
        fn = getattr(vp, name, None)
        if fn is None:
            continue
        try:
            res = fn(x, y)
        except Exception:
            continue
        if res is None:
            continue
        if isinstance(res, tuple):
            return res[0], (res[1] if len(res) > 1 else None)
        return res, None
    return None, None


def _kind_of(scene, g):
    for kind in KINDS:
        mod = _module(kind["mod"])
        fn = getattr(mod, kind["data"], None) if mod else None
        if fn is not None and fn(g) is not None:
            return kind, mod, fn
    return None


def _find_element(vp, face, placement):
    scene = vp.scene
    cands = []
    if placement is not None:
        cands += [getattr(placement, "owner", None), placement]
        try:
            cands.append(vp._owner_of(placement))
        except Exception:
            pass
    for g in [c for c in cands if c is not None and c in scene.groups] + \
            list(scene.groups):
        info = _kind_of(scene, g)
        if info is None:
            continue
        for k in g.children or ():
            if any(f is face for f in k.mesh.faces):
                return (g,) + info + (k,)
    return None


def _rebuild(kind, mod, fn, g, changes) -> None:
    d = fn(g)
    if kind["how"] == "wall":
        mod.rebuild_wall(g, d["th"], d["h"], dict(changes))
    elif kind["how"] == "full":
        nd = copy.deepcopy(d)
        for k, v in changes.items():
            if v is None:
                nd.pop(k, None)
            else:
                nd[k] = v
        getattr(mod, kind["rebuild"])(g, nd)
    else:
        getattr(mod, kind["rebuild"])(g, dict(changes))


class PennelloTool(Tool):
    name = tr("Pennello")
    shortcut = None
    description = tr("Clic su una faccia di un elemento per dipingerla.")

    def __init__(self) -> None:
        self._entering = False

    def on_activate(self, viewport) -> None:
        if self._entering:
            viewport.flash_status(
                tr("Pennello: clic su una faccia per prelevarne il materiale "
                   "e sostituirlo · tasto destro = impostazioni · Esc = esci")
                if _Brush.mode == "replace" else
                tr("Pennello: clic su una faccia · tasto destro = cambia "
                   "colore · Esc = esci"), 6000)
            return
        if not ask_brush(viewport.window()):
            return
        self._entering = True
        try:
            viewport.set_active_tool(self)
        finally:
            self._entering = False

    def on_deactivate(self, viewport) -> None:
        pass

    def claims_key(self, key: int, modifiers) -> bool:
        if modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        return key == Qt.Key_Escape

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Escape:
            viewport.update()
            back = getattr(viewport.window(), "activate_select_tool", None)
            if callable(back):
                back()
            return True
        return False

    def context_menu(self, viewport, pos) -> bool:
        ask_brush(viewport.window())
        viewport.update()
        return True

    @staticmethod
    def _screen_pos(ctx, vp):
        for ax, ay in (("screen_x", "screen_y"), ("x", "y"), ("px", "py")):
            x, y = getattr(ctx, ax, None), getattr(ctx, ay, None)
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                return float(x), float(y)
        p = getattr(vp, "_last_mouse_pos", None)
        return (p.x(), p.y()) if p is not None else (None, None)

    def _replace(self, vp, face) -> None:
        key = _mat_key(face)
        if key is None:
            vp.flash_status(tr("Questa faccia non ha un materiale da sostituire"),
                            4000)
            return
        scene = vp.scene
        todo = []
        for gg in scene.groups:
            info = _kind_of(scene, gg)
            if info is None:
                continue
            kind, mod, fn = info
            kids = list(gg.children or ())
            if kind.get("first_only"):
                kids = kids[:1]
            sigs = []
            for k in kids:
                for f in k.mesh.faces:
                    if _mat_key(f) == key:
                        sg = face_sig(f)
                        if sg is not None:
                            sigs.append(sg)
            if sigs:
                todo.append((gg, kind, mod, fn, sigs))
        if not todo:
            vp.flash_status(tr("Materiale non trovato"), 3000)
            return
        col, tex = _Brush.col_b, _Brush.tex_b

        def mutate(sc):
            for gg, kind, mod, fn, sigs in todo:
                d = fn(gg)
                fp = [e for e in copy.deepcopy(d.get("fp") or [])
                      if not any(same_face(e, s) for s in sigs)]
                for s in sigs:
                    entry = dict(s)
                    entry["col"] = copy.deepcopy(col)
                    entry["tex"] = copy.deepcopy(tex)
                    fp.append(entry)
                _rebuild(kind, mod, fn, gg, {"fp": fp})

        hist = vp.history
        hist.execute(PennelloCommand(mutate))
        if getattr(hist, "last_error", None):
            vp.flash_status(tr("Pennello: ")
                            + str(hist.last_error).split(": ", 1)[-1], 6000)
            return
        vp.notify_scene_changed()
        vp.update()
        vp.flash_status(tr("Materiale sostituito su {0} elementi").format(
            len(todo)), 3000)

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        scene = vp.scene
        if getattr(scene, "edit_group", None) is not None:
            vp.flash_status(tr("Chiudi il gruppo che stai modificando"), 4000)
            return
        x, y = self._screen_pos(ctx, vp)
        if x is None:
            return
        face, placement = _pick_face(vp, x, y)
        found = _find_element(vp, face, placement) if face is not None else None
        if found is None:
            vp.flash_status(
                tr("Clicca su una faccia di un elemento creato con gli "
                   "strumenti MyHouse"), 3000)
            return
        g, kind, mod, fn, child = found
        if _Brush.mode == "replace":
            self._replace(vp, face)
            return
        if kind.get("first_only") and child is not (g.children or [None])[0]:
            vp.flash_status(tr("Questo pezzo non si puo' dipingere"), 3000)
            return
        sig = face_sig(face)
        if sig is None:
            names = [n for n in dir(face) if not n.startswith("_")]
            vp.flash_status(
                tr("Faccia non leggibile: ") + ", ".join(names)[:300], 9000)
            return

        d = fn(g)
        fp = [e for e in copy.deepcopy(d.get("fp") or [])
              if not same_face(e, sig)]
        entry = dict(sig)
        entry["col"] = copy.deepcopy(_Brush.col_b)
        entry["tex"] = copy.deepcopy(_Brush.tex_b)
        fp.append(entry)
        changes = {"fp": fp}

        mat = getattr(g, "material", None)
        mcol = mat.get("color") if isinstance(mat, dict) else None
        if mcol:
            if not d.get("fpb"):
                changes["fpb"] = {"col": list(mcol)}

        def mutate(sc):
            _rebuild(kind, mod, fn, g, changes)
            if mcol:
                m = dict(g.material)
                m.pop("color", None)
                g.material = m or None

        hist = vp.history
        hist.execute(PennelloCommand(mutate))
        if getattr(hist, "last_error", None):
            vp.flash_status(tr("Pennello: ")
                            + str(hist.last_error).split(": ", 1)[-1], 6000)
            return
        vp.notify_scene_changed()
        vp.update()
        vp.flash_status(tr("Faccia dipinta"), 2000)


_SNAP = {"faces": None, "busy": False}


def _attr_key(f):
    a = f.attrs
    c = a.get("color")
    t = a.get("texture")
    return (tuple(c) if c else None, repr(t) if t else None, a.get("mat"))


def _elements(scene):
    for g in scene.groups:
        info = _kind_of(scene, g)
        if info is None:
            continue
        kids = list(g.children or ())
        if info[0].get("first_only"):
            kids = kids[:1]
        yield g, info, kids


def sync_native(vp) -> bool:
    if _SNAP["busy"]:
        return False
    scene = vp.scene
    old = _SNAP["faces"]
    new, changed, mats = {}, [], []
    for g, info, kids in _elements(scene):
        for k in kids:
            for f in k.mesh.faces:
                key = _attr_key(f)
                new[f] = key
                if old is not None and f in old and old[f] != key:
                    changed.append((g, info, f))
        m = getattr(g, "material", None)
        if isinstance(m, dict) and (m.get("color") or m.get("texture")):
            mats.append((g, info, m))
    _SNAP["faces"] = new
    if not changed and not mats:
        return False
    _SNAP["busy"] = True
    try:
        for g, (kind, mod, fn), f in changed:
            sig = face_sig(f)
            d = fn(g)
            if sig is None or d is None:
                continue
            e = dict(sig)
            c = f.attrs.get("color")
            e["col"] = list(c) if c else None
            e["tex"] = copy.deepcopy(f.attrs.get("texture"))
            e["mat"] = f.attrs.get("mat")
            d["fp"] = [x for x in (d.get("fp") or [])
                       if not same_face(x, sig)] + [e]
        for g, (kind, mod, fn), m in mats:
            fpb = {"col": list(m["color"]) if m.get("color") else None,
                   "all": True}
            if m.get("texture"):
                fpb["tex"] = copy.deepcopy(m["texture"])
            _rebuild(kind, mod, fn, g, {"fp": [], "fpb": fpb})
            rest = dict(g.material)
            rest.pop("color", None)
            rest.pop("texture", None)
            g.material = rest or None
        _SNAP["faces"] = {f: _attr_key(f)
                          for _g, _i, kids in _elements(scene)
                          for k in kids for f in k.mesh.faces}
    except Exception:
        return False
    finally:
        _SNAP["busy"] = False
    try:
        vp.flash_status(tr("Pennello: materiale di Inge applicato"), 2500)
    except Exception:
        pass
    return True


class _Rilascio(QObject):

    def __init__(self, vp) -> None:
        super().__init__(vp)
        self.vp = vp

    def eventFilter(self, obj, ev) -> bool:
        if ev.type() == QEvent.MouseButtonRelease:
            QTimer.singleShot(120, self._check)
        return False

    def _check(self) -> None:
        try:
            if sync_native(self.vp):
                self.vp.update()
        except Exception:
            pass


def _hook_native(vp) -> None:
    if getattr(vp, "_pennello_sync", False):
        return
    vp._pennello_sync = True
    try:
        vp._pennello_rel = _Rilascio(vp)
        vp.installEventFilter(vp._pennello_rel)
    except Exception:
        pass
    orig_notify = vp.notify_scene_changed

    def notify(*a, **k):
        try:
            sync_native(vp)
        except Exception:
            pass
        return orig_notify(*a, **k)

    vp.notify_scene_changed = notify
    hist = getattr(vp, "history", None)
    orig_exec = getattr(hist, "execute", None)
    if orig_exec is None:
        return

    def execute(cmd, *a, **k):
        r = orig_exec(cmd, *a, **k)
        try:
            if sync_native(vp):
                vp.update()
        except Exception:
            pass
        return r

    hist.execute = execute


def _icon():
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(110, 80, 50), 4))
    p.drawLine(38, 8, 20, 28)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(200, 200, 200))
    p.drawRect(15, 24, 10, 8)
    p.setBrush(QColor(220, 90, 60))
    p.drawEllipse(8, 30, 14, 12)
    p.end()
    return QIcon(pm)


_REGISTERED = {"done": False}


def register(api) -> None:
    if _REGISTERED["done"]:
        return
    _REGISTERED["done"] = True
    install()
    try:
        vp = api.window.viewport
        _SNAP["faces"] = {f: _attr_key(f)
                          for _g, _i, kids in _elements(vp.scene)
                          for k in kids for f in k.mesh.faces}
        _hook_native(vp)
    except Exception:
        pass
    api.add_button(tr("Pennello"),
                   tr("Clic su una faccia di un elemento per dipingerla"),
                   _icon(), api.run_tool(PennelloTool()))
