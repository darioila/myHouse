# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import os
import re
import unicodedata

LANGS = {"it": "Italiano", "en": "English"}
FALLBACK = "en"
_ORG, _APP, _KEY = "MyHouse", "MyHouse", "language"
_current: str | None = None
_tables: dict = {}
_EN: dict | None = None


def _english() -> dict:
    global _EN
    if _EN is None:
        try:
            from ._traduzioni_en import TR
            _EN = TR
        except Exception:
            _EN = {}
    return _EN


def _discover() -> None:
    import importlib
    import pkgutil
    import sys
    pkg = sys.modules.get(__package__ or "")
    paths = list(getattr(pkg, "__path__", None) or []) or [os.path.dirname(__file__)]
    for info in pkgutil.iter_modules(paths):
        name = info.name
        if not name.startswith("_traduzioni_"):
            continue
        code = name[len("_traduzioni_"):].lower()
        if not code or code in ("it", "en"):
            continue
        try:
            mod = importlib.import_module(f"{__package__}.{name}")
            table = getattr(mod, "TR", None)
            if isinstance(table, dict) and table:
                _tables[code] = table
                LANGS[code] = str(getattr(mod, "NAME", code))
        except Exception:
            pass


def _norm(code) -> str:
    c = str(code or "").strip().lower().replace("-", "_")[:2]
    if c in LANGS:
        return c
    return _known_code(code) or FALLBACK


def explicit_language():
    try:
        from PySide6.QtCore import QSettings
        saved = str(QSettings(_ORG, _APP).value(_KEY, "") or "").strip().lower()
        if saved in LANGS:
            return saved
    except Exception:
        pass
    return None


def _detect() -> str:
    env = os.environ.get("MYHOUSE_LANG", "").strip().lower()[:2]
    if env in LANGS:
        return env
    scelta = explicit_language()
    if scelta:
        return scelta
    host = _from_host_settings()
    if host:
        return host
    try:
        from PySide6.QtCore import QLocale
        name = QLocale.system().name().lower()
    except Exception:
        name = ""
    return _norm(name)


_MENU_WORDS = ("lingua", "language", "idioma", "langue", "sprache", "lang")
_app_menu_found = False

_ALIASES = {
    "it": ("italiano", "italian", "italien", "italienisch", "italiana"),
    "en": ("english", "inglese", "ingles", "anglais", "englisch", "ingles"),
    "es": ("espanol", "spanish", "spagnolo", "castellano", "espagnol", "spanisch"),
    "pt": ("portugues", "portuguese", "portoghese", "portugais", "portugiesisch",
           "brasil", "brazil", "brasileiro"),
    "de": ("deutsch", "german", "tedesco", "allemand", "aleman"),
    "fr": ("francais", "french", "francese", "frances", "franzosisch"),
}


def _fold(text) -> str:
    t = unicodedata.normalize("NFKD", str(text or "")).replace("&", "")
    return "".join(c for c in t if not unicodedata.combining(c)).strip().lower()


def _known_code(name):
    n = _fold(name)
    if not n:
        return None
    base = re.split(r"[(\[/,;:]|\s[-–—]\s", n)[0].strip()
    parole = re.split(r"[\s_\-]+", base)
    cand = [n, base] + parole[:1]
    for code, label in LANGS.items():
        nomi = {code, _fold(label)} | set(_ALIASES.get(code, ()))
        nomi |= {x.split()[0] for x in list(nomi) if x.split()}
        if any(c in nomi for c in cand):
            return code
    return None


def _code_from_name(name: str) -> str:
    return _known_code(name) or FALLBACK


def _text(act) -> str:
    return act.text().replace("&", "").strip()


def _titolo_lingua(title: str) -> bool:
    t = _fold(title)
    return any(w in t for w in _MENU_WORDS)


_CHIAVI_HOST = ("language", "lang", "lingua", "locale", "idioma", "ui_language",
                "uilanguage", "ui_lang")


def _from_host_settings():
    try:
        from PySide6.QtCore import QSettings
        st = QSettings()
        for k in st.allKeys():
            if str(k).replace("\\", "/").split("/")[-1].lower() not in _CHIAVI_HOST:
                continue
            v = str(st.value(k, "") or "").strip()
            if not v:
                continue
            c = _known_code(v)
            if c:
                return c
            if re.fullmatch(r"[A-Za-z]{2,3}([_-][A-Za-z]{2,4})?", v):
                return FALLBACK
    except Exception:
        pass
    return None


def sync_from_app(app) -> bool:
    global _current, _app_menu_found
    try:
        from PySide6.QtWidgets import QMenu
        win = app.window
        menus = []
        for m in win.findChildren(QMenu):
            acts = [a for a in m.actions() if a.isCheckable()]
            if not acts:
                continue
            noti = sum(1 for a in acts if _known_code(_text(a)))
            if _titolo_lingua(m.title()) or noti >= 2:
                menus.append((0 if _titolo_lingua(m.title()) else 1, m, acts))
        menus.sort(key=lambda t: t[0])
        for _p, m, acts in menus:
            _app_menu_found = True
            for a in acts:
                if a.isChecked() and not explicit_language():
                    _current = _code_from_name(_text(a))
                a.triggered.connect(
                    lambda _c=False, a=a: _set_now(
                        _code_from_name(_text(a))))
            return True
    except Exception:
        pass
    return False


def _set_now(code: str) -> None:
    global _current
    if explicit_language():
        return
    _current = _norm(code)


def app_menu_found() -> bool:
    return _app_menu_found


def language() -> str:
    global _current
    if _current is None:
        _current = _detect()
    elif _current not in LANGS:
        _current = FALLBACK
    return _current


def available() -> list:
    resto = sorted((c for c in LANGS if c not in ("it", "en")), key=lambda c: LANGS[c].lower())
    return [(c, LANGS[c]) for c in ("it", "en") + tuple(resto) if c in LANGS]


def set_language(code: str) -> None:
    code = str(code or "").strip().lower()
    if code in ("", "auto"):
        code = ""
    elif code not in LANGS:
        return
    try:
        from PySide6.QtCore import QSettings
        QSettings(_ORG, _APP).setValue(_KEY, code)
    except Exception:
        pass


def tr(text: str) -> str:
    code = language()
    if code == "it":
        return text
    if code != "en":
        t = _tables.get(code, {}).get(text)
        if t:
            return t
    return _english().get(text, text)


_rev: dict | None = None


def original(text: str) -> str:
    global _rev
    if _rev is None:
        _rev = {}
        tabelle = [_english()] + list(_tables.values())
        for tab in tabelle:
            for it, tradotto in tab.items():
                if isinstance(tradotto, str):
                    _rev.setdefault(tradotto.strip().lower(), []).append(it)
    t = str(text or "")
    return " | ".join([t] + _rev.get(t.strip().lower(), []))


_discover()
