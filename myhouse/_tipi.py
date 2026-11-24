# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import copy
import json
import os
import tempfile
import time
import uuid

EXT_KEY = {
    "muro": "myhouse_muro", "porta": "myhouse_porta",
    "finestra": "myhouse_finestra", "pilastro": "myhouse_pilastro",
    "trave": "myhouse_trave", "solaio": "myhouse_solaio",
    "tetto": "myhouse_tetto",
    "plinto": "myhouse_pilastro", "platea": "myhouse_platea",
    "trave_rovescia": "myhouse_trave_rovescia",
    "scala": "myhouse_scala", "balaustra": "myhouse_balaustra",
    "recinzione": "myhouse_recinzione",
}

SUB = {"plinto": "plinto", "platea": "p", "trave_rovescia": "p"}

TYPE_KEYS = {
    "muro": ("th", "layers", "hatch", "bat_l", "bat_r", "col_*", "tex_*"),
    "porta": ("model", "W", "H", "fw", "fd", "sw", "leaves", "handle", "arch",
              "arch_h", "asym", "w1", "slide", "hatch", "col_*", "tex_*"),
    "finestra": ("W", "H", "leaves", "tipo", "fw", "fd", "sw", "sth", "sti",
                 "ste", "spt", "spl", "spd", "spw", "sbd", "sba", "sub",
                 "nv", "nh", "dv", "dh", "shut", "cur", "cuh", "hatch",
                 "col_*", "tex_*"),
    "pilastro": ("shape", "w", "dp", "dia", "tf", "tw", "plinto"),
    "trave": ("shape", "w", "h", "tf", "tw", "sagoma", "sag_taglio",
              "sag_lung"),
    "solaio": ("th", "layers", "mat", "col_*", "tex_*"),
    "tetto": ("th", "layers", "col_*", "tex_*"),
    "plinto": ("tipo", "L", "P", "H", "dz", "Hv", "Lt", "Pt", "bs", "bh"),
    "platea": ("H", "Hb", "off", "bs"),
    "trave_rovescia": ("tipo", "B", "H", "Hc", "Wc", "He", "E", "dz"),
    "scala": ("w", "tread", "kind", "th", "bw", "tt", "fix", "emb",
              "winders", "rail", "col_*", "tex_*"),
    "balaustra": ("h", "style", "gap", "round", "t", "hr", "bot", "post",
                  "vt", "col_*", "tex_*"),
    "recinzione": ("kind", "wall", "h", "post", "sz", "bot", "dh", "dg",
                   "dt", "gap", "bt", "spear", "rl", "ru", "rt", "mh", "mt"),
}
ID_KEY, NAME_KEY = "tipo_id", "tipo_nome"

STD_ID = {c: "std_" + c for c in EXT_KEY}

STD_TYPES = {
    "muro": ("Muro 30 cm", {"th": 0.30}),
    "porta": ("Porta 90×210", {
        "model": "porta", "W": 0.90, "H": 2.10, "fw": 0.06, "fd": 0.12,
        "sw": 0.04, "leaves": 1, "handle": "lever", "arch": "none",
        "arch_h": 0.30, "asym": False, "w1": 0.0, "slide": False}),
    "finestra": ("Finestra 120×140", {
        "W": 1.20, "H": 1.40, "leaves": 1, "fw": 0.06, "fd": 0.07,
        "sw": 0.05}),
    "pilastro": ("Pilastro 30×30", {
        "shape": "square", "w": 0.30, "dp": 0.30, "dia": 0.35, "tf": 0.02,
        "tw": 0.012}),
    "trave": ("Trave 30×50", {
        "shape": "rect", "w": 0.30, "h": 0.50, "tf": 0.02, "tw": 0.012,
        "sagoma": "NESSUNA", "sag_taglio": 50.0, "sag_lung": 0.25}),
    "solaio": ("Solaio 25 cm", {"th": 0.25}),
    "tetto": ("Tetto 20 cm", {"th": 0.20}),
    "plinto": ("Plinto 100×100", {
        "tipo": "rect", "L": 1.0, "P": 1.0, "H": 0.50, "dz": 0.0,
        "Hv": 0.25, "Lt": 0.0, "Pt": 0.0, "bs": 0.10, "bh": 0.10}),
    "platea": ("Platea 40 cm", {"H": 0.40, "Hb": 0.10, "off": 0.50,
                                "bs": 0.10}),
    "trave_rovescia": ("Trave rovescia 80×40", {
        "tipo": "rect", "B": 0.80, "H": 0.40, "Hc": 0.30, "Wc": 0.0,
        "He": 0.15, "E": 0.0, "dz": 0.0}),
    "scala": ("Scala 100 cm", {
        "w": 1.00, "tread": 0.30, "kind": "piena", "th": 0.15, "bw": 0.08,
        "tt": 0.04, "fix": "left", "emb": 0.12, "winders": 1}),
    "balaustra": ("Balaustra 100 cm", {
        "h": 1.00, "style": "vert", "gap": 0.10, "round": True, "t": 0.02,
        "hr": 0.05, "bot": 0.05, "post": 1.00, "vt": 0.012}),
    "recinzione": ("Recinzione 180 cm", {
        "kind": "doghe", "wall": False, "h": 1.80, "post": 2.00, "sz": 0.08,
        "bot": 0.05, "dh": 0.14, "dg": 0.02, "dt": 0.025, "gap": 0.12,
        "bt": 0.02, "spear": 0.10, "rl": 0.20, "ru": 0.20, "rt": 0.03,
        "mh": 0.60, "mt": 0.20}),
}


def _std_params(cat: str) -> dict:
    p = copy.deepcopy(STD_TYPES[cat][1])
    if cat == "finestra":
        try:
            from . import finestre
            for name in ("DIV_DEFAULT", "SHUT_DEFAULT", "CURT_DEFAULT",
                         "SILL_DEFAULT", "TIPO_DEFAULT", "SPAL_DEFAULT"):
                for k, v in getattr(finestre, name).items():
                    p.setdefault(k, copy.deepcopy(v))
        except Exception:
            pass
    return p


def _std_entry(cat: str) -> dict:
    return {"nome": STD_TYPES[cat][0], "p": _std_params(cat), "rev": 1,
            "t": int(time.time())}

INSTANCE_LABELS = (
    "Piano", "Nome", "Altezza da terra", "Altezza (H)", "Rotazione",
    "Punto di aggancio", "Base:", "Lato di ricalco", "Distanza dal piano",
    "Faccia superiore", "Gronda", "Sporto", "Apertura", "I punti cliccati",
    "Traccia la trave", "Altezza fino a", "Distanza dalla quota di arrivo",
    "Codice (ID)", "Quota di partenza", "La linea", "Ortogonale",
)


def italicize_instance_rows(form) -> None:
    try:
        from PySide6.QtWidgets import QFormLayout, QLabel
        from ._lingua import original
    except Exception:
        return
    for i in range(form.rowCount()):
        item = form.itemAt(i, QFormLayout.LabelRole)
        lab = item.widget() if item is not None else None
        if not isinstance(lab, QLabel):
            continue
        txt = original(lab.text()) or lab.text()
        if any(txt.startswith(p) for p in INSTANCE_LABELS):
            f = lab.font()
            f.setItalic(True)
            lab.setFont(f)
            lab.setToolTip(_tr("Proprietà dell'istanza: non fa parte del tipo "
                               "e non si salva con lui (corsivo)"))


def is_type_key(cat: str, k: str) -> bool:
    for t in TYPE_KEYS.get(cat, ()):
        if (t.endswith("*") and k.startswith(t[:-1])) or k == t:
            return True
    return False


def split(cat: str, d: dict):
    t, i = {}, {}
    for k, v in d.items():
        if k in (ID_KEY, NAME_KEY):
            continue
        v = copy.deepcopy(v)
        if cat == "pilastro" and k == "plinto" and isinstance(v, dict):
            v.pop(ID_KEY, None)
            v.pop(NAME_KEY, None)
        (t if is_type_key(cat, k) else i)[k] = v
    return t, i


def _file():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    for root in (base, tempfile.gettempdir()):
        p = os.path.join(root, "IngeTrazo_tipi")
        try:
            os.makedirs(p, exist_ok=True)
            return os.path.join(p, "tipi.json")
        except OSError:
            continue
    return None


def _all(path=None) -> dict:
    path = path or _file()
    if path and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
    return {}


def _write(data, path=None) -> bool:
    path = path or _file()
    if not path:
        return False
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def load(cat: str, path=None) -> dict:
    data = _all(path)
    t = data.get(cat)
    lib = {}
    if isinstance(t, dict):
        lib = {k: v for k, v in t.items()
               if isinstance(v, dict) and isinstance(v.get("p"), dict)}
    if lib or cat not in STD_TYPES:
        return lib
    entry = _std_entry(cat)
    lib = {STD_ID[cat]: entry}
    if not isinstance(t, dict):
        data[cat] = {}
    data[cat][STD_ID[cat]] = entry
    _write(data, path)
    return lib


def find_by_name(cat, nome, path=None):
    for tid, t in load(cat, path).items():
        if t.get("nome") == nome:
            return tid
    return None


def save_type(cat, nome, params, tid=None, path=None):
    nome = (nome or "").strip()
    if not nome or not params:
        return None
    data = _all(path)
    lib = data.setdefault(cat, {})
    tid = tid or uuid.uuid4().hex[:12]
    old = lib.get(tid) or {}
    lib[tid] = {"nome": nome, "p": split(cat, params)[0],
                "rev": int(old.get("rev", 0)) + 1, "t": int(time.time())}
    return tid if _write(data, path) else None


def rename_type(cat, tid, nome, path=None) -> bool:
    data = _all(path)
    t = data.get(cat, {}).get(tid)
    if not t or not (nome or "").strip():
        return False
    t["nome"] = nome.strip()
    return _write(data, path)


def duplicate_type(cat, tid, nome, path=None):
    t = load(cat, path).get(tid)
    return save_type(cat, nome, t["p"], path=path) if t else None


def delete_type(cat, tid, path=None) -> bool:
    if len(load(cat, path)) <= 1:
        return False
    data = _all(path)
    if tid not in data.get(cat, {}):
        return False
    del data[cat][tid]
    return _write(data, path)


def get_params(group, cat):
    d = (getattr(group, "ext", None) or {}).get(EXT_KEY[cat])
    sub = SUB.get(cat)
    if sub and isinstance(d, dict):
        d = d.get(sub)
    return d if isinstance(d, dict) and d else None


def set_params(group, cat, nd) -> None:
    ext = dict(group.ext or {})
    key, sub = EXT_KEY[cat], SUB.get(cat)
    if sub:
        outer = dict(ext[key])
        outer[sub] = nd
        ext[key] = outer
    else:
        ext[key] = nd
    group.ext = ext


def _groups(scene, cat):
    for g in getattr(scene, "groups", ()):
        d = get_params(g, cat)
        if d is not None:
            yield g, d


def type_of(group, cat):
    return (get_params(group, cat) or {}).get(ID_KEY)


def params_for_assign(cat, tid, path=None):
    t = load(cat, path).get(tid)
    if not t:
        return None
    return dict(copy.deepcopy(t["p"]), **{ID_KEY: tid, NAME_KEY: t["nome"]})


def usage(scene, cat) -> dict:
    out = {}
    for _g, d in _groups(scene, cat):
        if d.get(ID_KEY):
            out[d[ID_KEY]] = out.get(d[ID_KEY], 0) + 1
    return out


def instances(scene, cat, tid):
    return [g for g, d in _groups(scene, cat) if d.get(ID_KEY) == tid]


def detach(group, cat) -> None:
    d = dict(get_params(group, cat) or {})
    d.pop(ID_KEY, None)
    d.pop(NAME_KEY, None)
    set_params(group, cat, d)


_PAINT = ("col_", "tex_")


def _core(p: dict) -> dict:
    return {k: _norm(v) for k, v in p.items()
            if v and k not in (ID_KEY, NAME_KEY) and not k.startswith(_PAINT)}


def _round(v):
    return ("%g" % round(v * 100, 1))


def auto_name(cat: str, p: dict) -> str:
    try:
        if cat in ("muro", "solaio", "tetto"):
            lab = {"muro": "Muro", "solaio": "Solaio", "tetto": "Tetto"}[cat]
            return "%s %s cm%s" % (lab, _round(p["th"]),
                                   " (strati)" if p.get("layers") else "")
        if cat in ("porta", "finestra"):
            return "%s %s×%s" % ("Porta" if cat == "porta" else "Finestra",
                                 _round(p["W"]), _round(p["H"]))
        if cat == "pilastro":
            sh = p.get("shape", "square")
            if sh == "round":
                return "Pilastro Ø%s" % _round(p["dia"])
            if sh == "square":
                return "Pilastro %s×%s" % (_round(p["w"]), _round(p["w"]))
            return "Pilastro %s%s×%s" % ("I " if sh == "ibeam" else "",
                                         _round(p["w"]), _round(p["dp"]))
        if cat == "trave":
            return "Trave %s×%s" % (_round(p["w"]), _round(p["h"]))
        if cat == "plinto":
            return "Plinto %s×%s" % (_round(p["L"]), _round(p["P"]))
        if cat == "platea":
            return "Platea %s cm" % _round(p["H"])
        if cat == "trave_rovescia":
            return "Trave rovescia %s×%s" % (_round(p["B"]), _round(p["H"]))
        if cat == "scala":
            return "Scala %s cm" % _round(p["w"])
        if cat == "balaustra":
            return "Balaustra H %s" % _round(p["h"])
        if cat == "recinzione":
            return "Recinzione H %s" % _round(p["h"])
    except (KeyError, TypeError, ValueError):
        pass
    return cat.replace("_", " ").capitalize()


def type_for_params(cat: str, p: dict, path=None):
    mine = _core(split(cat, p)[0])
    lib = load(cat, path)
    for tid, t in lib.items():
        if _core(t["p"]) == mine:
            return tid, t["nome"]
    base = auto_name(cat, p)
    names = {t["nome"] for t in lib.values()}
    nome, i = base, 2
    while nome in names:
        nome = "%s (%d)" % (base, i)
        i += 1
    tid = save_type(cat, nome, p, path=path)
    return (tid, nome) if tid else (None, None)


def assign_untyped(scene, path=None) -> int:
    n = 0
    for cat in EXT_KEY:
        for g, d in list(_groups(scene, cat)):
            if d.get(ID_KEY):
                continue
            tid, nome = type_for_params(cat, d, path)
            if not tid:
                continue
            nd = dict(d)
            nd[ID_KEY], nd[NAME_KEY] = tid, nome
            set_params(g, cat, nd)
            n += 1
    return n


def sync_from_scene(scene, cat, path=None) -> int:
    data = _all(path)
    lib = data.setdefault(cat, {})
    n = 0
    for _g, d in _groups(scene, cat):
        tid = d.get(ID_KEY)
        if tid and tid not in lib:
            lib[tid] = {"nome": d.get(NAME_KEY) or tid,
                        "p": split(cat, d)[0], "rev": 1, "t": int(time.time())}
            n += 1
    if n:
        _write(data, path)
    return n


def settle(group, cat, path=None) -> None:
    d = get_params(group, cat)
    if d is None:
        return
    t = load(cat, path).get(d.get(ID_KEY) or "")
    if t and same_type_params(cat, d, t["p"]):
        return
    tid, nome = type_for_params(cat, d, path)
    if tid:
        nd = dict(d)
        nd[ID_KEY], nd[NAME_KEY] = tid, nome
        set_params(group, cat, nd)


def update_instances(scene, cat, tid, rebuild, path=None) -> int:
    p = params_for_assign(cat, tid, path)
    if p is None:
        return 0
    n = 0
    for g in instances(scene, cat, tid):
        rebuild(g, copy.deepcopy(p))
        n += 1
    return n


def _tr(s):
    try:
        from ._lingua import tr
        return tr(s)
    except Exception:
        return s


def _norm(v):
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in sorted(v.items())}
    return v


def same_type_params(cat, p, lib_params) -> bool:
    mine = split(cat, p)[0]
    return all(_norm(mine[k]) == _norm(lib_params.get(k))
               for k in mine if k in lib_params)


class TypeBar:

    def __init__(self, dlg, form, cat, cur, get_p, set_p, scene=None,
                 creating=False, at=1, path=None, tscene=None):
        from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QPushButton,
                                       QWidget)
        self.dlg, self.cat, self.scene = dlg, cat, tscene or scene
        self.get_p, self.set_p, self.creating = get_p, set_p, creating
        self.path = path
        self.combo = QComboBox()
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.combo, 1)
        for text, fn in ((_tr("Salva…"), self._save),
                         (_tr("Rinomina…"), self._rename),
                         (_tr("Duplica…"), self._dup),
                         (_tr("Elimina"), self._delete)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, f=fn: f())
            lay.addWidget(b)
        form.insertRow(at, _tr("Tipo"), box)
        if self.scene is not None:
            try:
                sync_from_scene(self.scene, cat, path)
            except Exception:
                pass
        lib = load(cat, path)
        if cur.get(ID_KEY) in lib:
            self._fill(cur.get(ID_KEY))
        elif creating:
            self._fill(None)
            self._picked()
        else:
            tid = None
            try:
                tid = type_for_params(cat, get_p(), path)[0]
            except Exception:
                pass
            self._fill(tid)
        self.combo.currentIndexChanged.connect(self._picked)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: italicize_instance_rows(form))

    def _fill(self, select=None):
        lib = load(self.cat, self.path)
        used = usage(self.scene, self.cat) if self.scene is not None else {}
        self.combo.blockSignals(True)
        self.combo.clear()
        for tid, t in sorted(lib.items(), key=lambda kv: kv[1]["nome"].lower()):
            n = used.get(tid, 0)
            self.combo.addItem(f'{t["nome"]} ({n})' if n else t["nome"], tid)
        i = self.combo.findData(select) if select else -1
        if i < 0:
            i = max(0, self.combo.findData(STD_ID.get(self.cat)))
        self.combo.setCurrentIndex(i)
        self.combo.blockSignals(False)

    def tid(self):
        return self.combo.currentData()

    def _picked(self, _i=None):
        tid = self.tid()
        t = load(self.cat, self.path).get(tid) if tid else None
        if t:
            self.set_p(copy.deepcopy(t["p"]))

    def _ask_name(self, title, text=""):
        from PySide6.QtWidgets import QInputDialog
        s, ok = QInputDialog.getText(self.dlg, title, _tr("Nome del tipo"),
                                     text=text)
        s = (s or "").strip()
        return s if ok and s else None

    def _save(self):
        from PySide6.QtWidgets import QMessageBox
        cur = load(self.cat, self.path).get(self.tid() or "")
        nome = self._ask_name(_tr("Salva tipo"), cur["nome"] if cur else "")
        if not nome:
            return
        tid = find_by_name(self.cat, nome, self.path)
        if tid and QMessageBox.question(
                self.dlg, _tr("Salva tipo"),
                _tr("Esiste già un tipo «{0}»: sovrascriverlo?").format(nome)
        ) != QMessageBox.Yes:
            return
        tid = save_type(self.cat, nome, self.get_p(), tid=tid, path=self.path)
        if not tid:
            QMessageBox.warning(self.dlg, _tr("Salva tipo"),
                                _tr("Impossibile scrivere la libreria dei tipi."))
            return
        self._fill(tid)

    def _rename(self):
        tid = self.tid()
        if not tid:
            return
        nome = self._ask_name(_tr("Rinomina tipo"),
                              load(self.cat, self.path)[tid]["nome"])
        if nome and rename_type(self.cat, tid, nome, self.path):
            self._fill(tid)

    def _dup(self):
        tid = self.tid()
        if not tid:
            return
        nome = self._ask_name(_tr("Duplica tipo"),
                              load(self.cat, self.path)[tid]["nome"] + " 2")
        new = duplicate_type(self.cat, tid, nome, self.path) if nome else None
        if new:
            self._fill(new)

    def _delete(self):
        from PySide6.QtWidgets import QMessageBox
        tid = self.tid()
        if not tid:
            return
        if len(load(self.cat, self.path)) <= 1:
            QMessageBox.information(self.dlg, _tr("Elimina tipo"),
                                    _tr("Deve esistere almeno un tipo."))
            return
        n = len(instances(self.scene, self.cat, tid)) if self.scene is not None else 0
        if n:
            QMessageBox.information(
                self.dlg, _tr("Elimina tipo"),
                _tr("Il tipo è usato da {0} oggetti: assegna loro un altro "
                    "tipo prima di eliminarlo.").format(n))
            return
        msg = _tr("Eliminare il tipo «{0}»?").format(
            load(self.cat, self.path)[tid]["nome"])
        if QMessageBox.question(self.dlg, _tr("Elimina tipo"), msg) != QMessageBox.Yes:
            return
        delete_type(self.cat, tid, self.path)
        self._fill(None)
        self._picked()

    def result(self, p: dict) -> dict:
        tid = self.tid()
        t = load(self.cat, self.path).get(tid) if tid else None
        if t and self.creating and not same_type_params(self.cat, p, t["p"]):
            t = None
        if t:
            p[ID_KEY], p[NAME_KEY] = tid, t["nome"]
        else:
            p[ID_KEY], p[NAME_KEY] = type_for_params(self.cat, p, self.path)
        return p


def resolve_edit(parent, scene, cat, p, path=None) -> str:
    tid = p.get(ID_KEY)
    t = load(cat, path).get(tid) if tid else None
    if not t:
        p[ID_KEY], p[NAME_KEY] = type_for_params(cat, p, path)
        return "ok"
    if same_type_params(cat, p, t["p"]):
        return "ok"
    n = len(instances(scene, cat, tid)) if scene is not None else 0
    if n > 1:
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox(parent)
        box.setWindowTitle(_tr("Modifica tipo"))
        box.setText(_tr("Il tipo «{0}» è usato da {1} oggetti.").format(t["nome"], n))
        box.setInformativeText(_tr("Aggiornare il tipo (tutti gli oggetti) o "
                                   "modificare solo questo oggetto?"))
        b_all = box.addButton(_tr("Aggiorna il tipo"), QMessageBox.AcceptRole)
        b_one = box.addButton(_tr("Solo questo oggetto"), QMessageBox.ActionRole)
        box.addButton(_tr("Annulla"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is b_one:
            p[ID_KEY], p[NAME_KEY] = type_for_params(cat, p, path)
            return "single"
        if box.clickedButton() is not b_all:
            return "cancel"
    if save_type(cat, t["nome"], p, tid=tid, path=path) is None:
        return "ok"
    return "type"


def set_widget(w, v) -> None:
    from PySide6.QtWidgets import QCheckBox, QComboBox
    if hasattr(w, "set") and callable(w.set):
        w.set(v)
    elif isinstance(w, QCheckBox):
        w.setChecked(bool(v))
    elif isinstance(w, QComboBox):
        w.setCurrentIndex(max(0, w.findData(v)))
    elif hasattr(w, "setValue"):
        w.setValue(v)


def get_widget(w):
    from PySide6.QtWidgets import QCheckBox, QComboBox
    if hasattr(w, "result") and callable(w.result):
        return w.result()
    if isinstance(w, QCheckBox):
        return w.isChecked()
    if isinstance(w, QComboBox):
        return w.currentData()
    return w.value()


def widgets_io(widgets: dict, paint=()):
    def get():
        return {k: get_widget(w) for k, w in widgets.items()}

    def set_(t):
        fill_widgets(widgets, dict(t, **{k: t.get(k) for k in paint}))
    return get, set_


def fill_widgets(widgets: dict, t: dict) -> None:
    for k, w in widgets.items():
        if k in t:
            set_widget(w, t[k])


FORMAT = "myhouse-tipi"


def sync_all(scene, path=None) -> int:
    return sum(sync_from_scene(scene, c, path) for c in EXT_KEY)


def summary(cat: str, p: dict, maxn: int = 5) -> str:
    out = []
    for k, v in p.items():
        if k.startswith(("col_", "tex_")) or v in (None, "", False):
            continue
        if k == "layers":
            out.append("strati: %d" % len(v))
        elif isinstance(v, float):
            out.append("%s=%g" % (k, round(v, 3)))
        elif isinstance(v, (int, str)):
            out.append("%s=%s" % (k, v))
        if len(out) >= maxn:
            break
    return ", ".join(out)


def export_types(dest: str, cats=None, path=None) -> int:
    data = _all(path)
    cats = list(cats) if cats else list(EXT_KEY)
    out = {c: data.get(c, {}) for c in cats if data.get(c)}
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump({"formato": FORMAT, "versione": 1, "tipi": out}, fh,
                  ensure_ascii=False, indent=1)
    return sum(len(v) for v in out.values())


def import_types(src: str, path=None):
    with open(src, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    if not isinstance(doc, dict) or doc.get("formato") != FORMAT:
        raise ValueError("not a MyHouse types file")
    data = _all(path)
    added = renamed = skipped = 0
    for cat, lib_in in (doc.get("tipi") or {}).items():
        if cat not in EXT_KEY or not isinstance(lib_in, dict):
            continue
        lib = data.setdefault(cat, {})
        for tid, t in lib_in.items():
            if not (isinstance(t, dict) and isinstance(t.get("p"), dict)
                    and t.get("nome")):
                continue
            mine = lib.get(tid)
            if mine is None:
                lib[tid] = {"nome": t["nome"], "p": t["p"],
                            "rev": int(t.get("rev", 1)), "t": int(time.time())}
                added += 1
            elif _norm(mine["p"]) == _norm(t["p"]):
                skipped += 1
            else:
                new = uuid.uuid4().hex[:12]
                lib[new] = {"nome": "%s (importato)" % t["nome"], "p": t["p"],
                            "rev": 1, "t": int(time.time())}
                renamed += 1
    _write(data, path)
    return added, renamed, skipped


def migrate_old_layer_types(path=None) -> int:
    path = path or _file()
    if not path:
        return 0
    data = _all(path)
    flags = data.get("_migrazioni")
    if not isinstance(flags, dict):
        flags = data["_migrazioni"] = {}
    if flags.get("strati"):
        return 0
    old_path = os.path.join(os.path.dirname(path), "tipi_strati.json")
    n = 0
    try:
        with open(old_path, "r", encoding="utf-8") as fh:
            old = json.load(fh)
    except (OSError, ValueError):
        old = {}
    for cat, by_name in (old.items() if isinstance(old, dict) else ()):
        if cat not in ("muro", "solaio", "tetto") or not isinstance(by_name, dict):
            continue
        lib = data.setdefault(cat, {})
        have = {t.get("nome") for t in lib.values() if isinstance(t, dict)}
        for nome, layers in by_name.items():
            if not (isinstance(layers, list) and layers) or nome in have:
                continue
            try:
                th = sum(float(l["t"]) for l in layers)
            except (KeyError, TypeError, ValueError):
                continue
            lib[uuid.uuid4().hex[:12]] = {
                "nome": str(nome), "p": {"th": th, "layers": layers},
                "rev": 1, "t": int(time.time())}
            n += 1
    flags["strati"] = True
    _write(data, path)
    return n
