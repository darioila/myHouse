# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import re

EXT_CODE = "myhouse_codice"
EXT_CODE_PLINTO = "myhouse_codice_plinto"

PREFIX = {
    "muro": ("M", "Muro"),
    "solaio": ("S", "Solaio"),
    "porta": ("P", "Porta"),
    "finestra": ("F", "Finestra"),
    "pilastro": ("PL", "Pilastro"),
    "trave": ("T", "Trave"),
    "tetto": ("TT", "Tetto"),
    "scala": ("SC", "Scala"),
    "balaustra": ("B", "Balaustra"),
    "rampa": ("R", "Rampa"),
    "plinto": ("PN", "Plinto"),
    "trave_rovescia": ("TR", "Trave rovescia"),
    "platea": ("PT", "Platea"),
}

LEGACY_PREFIX = {"pilastro": ("P",), "tetto": ("T",), "platea": ("PL",),
                 "scala": ("S",), "plinto": ("PL",)}

EXT_CATEGORY = {
    "myhouse_muro": "muro", "myhouse_solaio": "solaio",
    "myhouse_porta": "porta", "myhouse_finestra": "finestra",
    "myhouse_pilastro": "pilastro", "myhouse_trave": "trave",
    "myhouse_tetto": "tetto", "myhouse_scala": "scala",
    "myhouse_chiocciola": "scala", "myhouse_rampa": "rampa", "myhouse_balaustra": "balaustra",
    "myhouse_trave_rovescia": "trave_rovescia", "myhouse_platea": "platea",
}


def category(group):
    ext = getattr(group, "ext", None) or {}
    for key, cat in EXT_CATEGORY.items():
        if isinstance(ext.get(key), dict):
            return cat
    return None


def code_of(group, cat=None):
    ext = getattr(group, "ext", None) or {}
    key = EXT_CODE_PLINTO if cat == "plinto" else EXT_CODE
    c = ext.get(key)
    return c if isinstance(c, str) and c.strip() else None


def elements(scene):
    out = []
    for g in getattr(scene, "groups", ()):
        cat = category(g)
        if cat is None:
            continue
        out.append((g, cat))
        if cat == "pilastro":
            d = g.ext.get(EXT_CATEGORY_KEY["pilastro"]) or {}
            if isinstance(d.get("plinto"), dict) and d["plinto"]:
                out.append((g, "plinto"))
    return out


EXT_CATEGORY_KEY = {"pilastro": "myhouse_pilastro"}


def _number(cat: str, code: str):
    m = re.fullmatch(re.escape(PREFIX[cat][0]) + r"(\d+)", code or "")
    return int(m.group(1)) if m else None


def _legacy_number(cat: str, code: str):
    for lp in LEGACY_PREFIX.get(cat, ()):
        if lp != PREFIX[cat][0]:
            m = re.fullmatch(re.escape(lp) + r"(\d+)", code or "")
            if m:
                return int(m.group(1))
    return None


def format_code(cat: str, n: int) -> str:
    return "%s%02d" % (PREFIX[cat][0], n)


def _free_code(cat: str, used: set) -> str:
    n = 1
    while format_code(cat, n) in used:
        n += 1
    return format_code(cat, n)


def _write(group, cat, code) -> None:
    ext = dict(group.ext or {})
    ext[EXT_CODE_PLINTO if cat == "plinto" else EXT_CODE] = code
    group.ext = ext


def assign_missing(scene) -> int:
    els = elements(scene)
    used = {c: set() for c in PREFIX}
    todo = []
    for g, cat in els:
        code = code_of(g, cat)
        if (code is None or code in used[cat]
                or _legacy_number(cat, code) is not None):
            todo.append((g, cat))
        else:
            used[cat].add(code)
    for g, cat in todo:
        n = _legacy_number(cat, code_of(g, cat))
        code = format_code(cat, n) if n is not None else None
        if code is None or code in used[cat]:
            code = _free_code(cat, used[cat])
        used[cat].add(code)
        _write(g, cat, code)
    return len(todo)


def set_code(scene, group, cat, code):
    code = (code or "").strip()
    if not code:
        return False, "empty"
    for g, c in elements(scene):
        if c == cat and g is not group and code_of(g, c) == code:
            return False, "duplicate"
    _write(group, cat, code)
    return True, ""


def _tr(s):
    try:
        from ._lingua import tr
        return tr(s)
    except Exception:
        return s


class CodeField:

    def __init__(self, form, groups, cat, scene, at=None):
        from PySide6.QtWidgets import QLineEdit
        self.scene, self.cat = scene, cat
        self.group = groups[0] if len(groups) == 1 else None
        self.edit = QLineEdit(code_of(self.group, cat) or "" if self.group is not None else "")
        self.edit.setEnabled(self.group is not None)
        if self.group is None:
            self.edit.setPlaceholderText("—")
        self.start = self.edit.text()
        self.edit.setToolTip(_tr("Codice identificativo dell'elemento (per gli abachi)"))
        label = _tr("Codice (ID)")
        if at is None:
            form.addRow(label, self.edit)
        else:
            form.insertRow(at, label, self.edit)

    def apply(self, parent=None) -> bool:
        text = self.edit.text().strip()
        if self.group is None or text == self.start:
            return True
        ok, why = set_code(self.scene, self.group, self.cat, text)
        if not ok:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                parent, _tr("Codice (ID)"),
                _tr("Codice già usato da un altro elemento: non cambiato.")
                if why == "duplicate" else _tr("Codice vuoto: non cambiato."))
        return ok
