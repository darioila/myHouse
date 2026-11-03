# SPDX-License-Identifier: GPL-3.0-or-later
"""Piani (livelli) per IngeTrazo / MyHouse.

Uso: MyHouse > Piani. Si definisce l'elenco dei piani (nome, quota, altezza
predefinita). Muri e solai si creano "su un piano": la loro base parte dalla
quota del piano + una distanza propria, e l'altezza resta un valore proprio
dell'elemento (quella del piano è solo il valore proposto).

  - Cambiando la quota di un piano, muri e solai assegnati a quel piano si
    spostano con lui (un solo passo di undo).
  - Tasto destro su muri/solai selezionati > "Assegna al piano…".
  - "Nessuno" = elemento libero (quota assoluta, come prima dei piani).
  - Il solaio automatico cerca la stanza solo tra i muri dello stesso piano.

Dati: i piani stanno in un gruppo vuoto "Piani" (group.ext) così vengono
salvati col disegno e rientrano nell'undo. Ogni elemento tiene:
    "lv"  id del piano      "lvn" nome del piano (per l'outliner)
    "off" distanza dalla quota del piano (quota assoluta = piano.z + off)

Altezza legata a un piano di arrivo (muri, scale): l'elemento tiene
    "tlv"  "next" (piano successivo) o id del piano di arrivo
    "toff" distanza dalla quota di arrivo (+ sopra / - sotto)
e la sua altezza = quota di arrivo + toff - quota di base. Se un piano cambia
quota, l'altezza degli elementi legati viene ricalcolata.

Funzioni usate dagli altri file: levels, get, active_id, set_active,
level_combo, level_props, add_top_rows, height_for.
"""
from __future__ import annotations

import uuid

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from . import muri

ORDER = 5
KEY = "myhouse_piani"
CARRIER_NAME = "Piani"
NONE_LABEL = "Nessuno (quota libera)"

_state = {"active": None}       # None = automatico, "" = nessuno esplicito


# ---------------------------------------------------------------------------
# Archivio dei piani
# ---------------------------------------------------------------------------

def _carrier(scene):
    for g in scene.groups:
        d = (getattr(g, "ext", None) or {}).get(KEY)
        if isinstance(d, dict) and "levels" in d:
            return g
    return None


def levels(scene):
    """Elenco dei piani [{id, name, z, h}], dal più basso."""
    g = _carrier(scene)
    if g is None:
        return []
    out = [dict(lv) for lv in g.ext[KEY]["levels"]]
    out.sort(key=lambda lv: (lv["z"], lv["name"]))
    return out


def get(scene, level_id):
    if not level_id:
        return None
    for lv in levels(scene):
        if lv["id"] == level_id:
            return lv
    return None


def active_id(scene):
    """Piano proposto per i nuovi elementi (None = nessun piano)."""
    lvs = levels(scene)
    ids = {lv["id"] for lv in lvs}
    a = _state.get("active")
    if a == "":
        return None
    if a in ids:
        return a
    return lvs[0]["id"] if lvs else None


def set_active(level_id) -> None:
    _state["active"] = level_id or ""


def _store(scene, lvls) -> None:
    """Scrive l'elenco (da chiamare dentro un MuriCommand)."""
    data = {"levels": [dict(lv) for lv in lvls]}
    g = _carrier(scene)
    if g is None:
        from core.group import Group
        g = Group(name=CARRIER_NAME)
        g.component = False
        g.ext = {KEY: data}
        scene.groups.append(g)
    else:
        ext = dict(g.ext or {})
        ext[KEY] = data
        g.ext = ext


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def level_combo(scene, current):
    """Casella di scelta del piano; data = id del piano, "" = nessuno."""
    cb = QComboBox()
    cb.addItem(NONE_LABEL, "")
    for lv in levels(scene):
        cb.addItem(f"{lv['name']}  (quota {lv['z']:.2f} m)", lv["id"])
    cb.setCurrentIndex(max(0, cb.findData(current or "")))
    return cb


def level_props(d):
    """Righe per l'outliner di un elemento con i dati d."""
    if not d.get("lv"):
        return []
    from core.units import fmt_len
    return [("Piano", d.get("lvn", "?")),
            ("Distanza dal piano", fmt_len(d.get("off", 0.0)))]


# ---------------------------------------------------------------------------
# Altezza legata a un piano di arrivo
# ---------------------------------------------------------------------------

def _target_h(lvs, tlv, toff, level_id, base_z):
    """Altezza che porta da base_z alla quota di arrivo (+ toff), oppure None
    se non c'è un piano di arrivo valido. "next" = primo piano sopra il piano
    di partenza (o sopra base_z se l'elemento non sta su un piano)."""
    if not tlv:
        return None
    if tlv == "next":
        start = next((lv for lv in lvs if lv["id"] == level_id), None)
        ref = start["z"] if start else base_z
        above = [lv for lv in lvs if lv["z"] > ref + 1e-6]
        dest = min(above, key=lambda lv: lv["z"]) if above else None
    else:
        dest = next((lv for lv in lvs if lv["id"] == tlv), None)
    if dest is None:
        return None
    h = dest["z"] + (toff or 0.0) - base_z
    return h if h > 1e-6 else None


def height_for(scene, tlv, toff, level_id, base_z):
    """Altezza per un elemento con base a quota assoluta base_z, legato al
    piano di arrivo tlv. None se il piano di arrivo non esiste / è sotto."""
    return _target_h(levels(scene), tlv, toff, level_id, base_z)


def add_top_rows(form, scene, height_spin, tlv, toff):
    """Aggiunge al dialogo le righe 'Altezza fino a' e la distanza dalla
    quota di arrivo. Con un piano di arrivo scelto l'altezza propria
    (height_spin) viene disabilitata. Ritorna (combo, spin distanza)."""
    cb = QComboBox()
    cb.addItem("Altezza propria (quella indicata)", "")
    cb.addItem("Piano successivo", "next")
    for lv in levels(scene):
        cb.addItem(f"{lv['name']}  (quota {lv['z']:.2f} m)", lv["id"])
    cb.setCurrentIndex(max(0, cb.findData(tlv or "")))
    off = muri._spin(toff or 0.0, -100.0, 100.0)

    def sync(_i=0) -> None:
        linked = bool(cb.currentData())
        off.setEnabled(linked)
        height_spin.setEnabled(not linked)

    cb.currentIndexChanged.connect(sync)
    sync()
    form.addRow("Altezza fino a", cb)
    form.addRow("Distanza dalla quota di arrivo (m, + sopra / - sotto)", off)
    return cb, off


# ---------------------------------------------------------------------------
# Elementi legati ai piani: ogni file si registra con register_kind()
# ---------------------------------------------------------------------------

_KINDS: dict = {}


def register_kind(name, key, data, zget, zset, rebuild=None,
                  hget=None, hset=None) -> None:
    """Un tipo di elemento che può stare su un piano.
      key      chiave dei parametri in group.ext
      data     data(group) -> dict dei parametri, o None se non è di questo tipo
      zget     zget(d) -> quota di riferimento (assoluta) dell'elemento
      zset     zset(d, z): sposta la copia d in modo che zget(d) == z
      rebuild  rebuild(group, d): rifà la geometria dai parametri d
      hget     hget(d) -> altezza dell'elemento (solo per elementi che
               possono avere l'altezza legata a un piano di arrivo)
      hset     hset(d, h): imposta l'altezza h nei parametri d
    """
    _KINDS[name] = {"name": name, "key": key, "data": data, "zget": zget,
                    "zset": zset, "rebuild": rebuild,
                    "hget": hget, "hset": hset}


def place(scene, level_id, off, base=0.0):
    """Per un NUOVO elemento: (quota assoluta, dati del piano da aggiungere
    ai suoi parametri). Con un piano: quota = piano + off; senza piano:
    quota = base + off (base = quota del clic, o 0)."""
    lv = get(scene, level_id)
    if lv:
        return lv["z"] + off, {"lv": lv["id"], "lvn": lv["name"], "off": off}
    return base + off, {}


def _elem(group):
    """(dati, tipo) di un elemento che sa stare sui piani, altrimenti None."""
    for kind in _KINDS.values():
        d = kind["data"](group)
        if d is not None:
            return d, kind
    return None


def _write(group, kind, d, rebuild) -> None:
    """Salva i dati d nel gruppo; con rebuild rifà anche la geometria."""
    if rebuild and kind["rebuild"] is not None:
        kind["rebuild"](group, d)
    ext = dict(group.ext or {})
    ext[kind["key"]] = d
    group.ext = ext


def apply_levels(scene, new_levels) -> None:
    """Imposta i nuovi piani e sposta gli elementi se la quota è cambiata."""
    new_levels = sorted(new_levels, key=lambda lv: (lv["z"], lv["name"]))
    old = {lv["id"]: lv for lv in levels(scene)}
    nd = {lv["id"]: lv for lv in new_levels}
    for g in list(scene.groups):
        e = _elem(g)
        if e is None or not e[0].get("lv"):
            continue
        d, kind = e
        d = dict(d)
        lid = d["lv"]
        if lid not in nd:                       # piano eliminato: elemento libero
            for k in ("lv", "lvn", "off"):
                d.pop(k, None)
            _write(g, kind, d, False)
            continue
        lv = nd[lid]
        delta = lv["z"] - old.get(lid, lv)["z"]
        renamed = d.get("lvn") != lv["name"]
        if abs(delta) > 1e-9:
            kind["zset"](d, kind["zget"](d) + delta)
            d["lvn"] = lv["name"]
            _write(g, kind, d, True)
        elif renamed:
            d["lvn"] = lv["name"]
            _write(g, kind, d, False)
    for g in list(scene.groups):            # altezze legate al piano di arrivo
        e = _elem(g)
        if e is None or not e[0].get("tlv") or e[1].get("hset") is None:
            continue
        d, kind = e
        d = dict(d)
        h = _target_h(new_levels, d["tlv"], d.get("toff", 0.0), d.get("lv"),
                      kind["zget"](d))
        if h is None:                       # piano di arrivo sparito: libera
            d.pop("tlv", None)
            d.pop("toff", None)
            _write(g, kind, d, False)
        elif kind["hget"] is None or abs(kind["hget"](d) - h) > 1e-9:
            kind["hset"](d, h)
            _write(g, kind, d, True)
    _store(scene, new_levels)


def _refresh(scene) -> None:
    """Dopo uno spostamento: tetti e fori delle finestre."""
    try:
        from . import finestre
        finestre.update_openings(scene)
    except ImportError:
        pass
    muri.update_roof_clips(scene)


# ---------------------------------------------------------------------------
# Dialogo dei piani
# ---------------------------------------------------------------------------

_DLG = {"dlg": None}


def _levels_dialog(parent, lvls, on_apply):
    """Finestra dei piani NON modale: resta aperta mentre usi il resto."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("Piani")
    dlg.setModal(False)
    dlg.setWindowModality(Qt.NonModal)
    dlg.setAttribute(Qt.WA_DeleteOnClose, True)
    dlg.resize(560, 340)
    lay = QVBoxLayout(dlg)
    info = QLabel("Quota = pavimento finito del piano. Se cambi la quota, "
                  "muri e solai di quel piano si spostano con lui. "
                  "Altezza = altezza del singolo piano (valore proposto "
                  "ai nuovi muri).")
    info.setWordWrap(True)
    lay.addWidget(info)
    table = QTableWidget(0, 3)
    table.setHorizontalHeaderLabels(["Nome", "Quota (m)", "Altezza (m)"])
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    table.setSelectionBehavior(QTableWidget.SelectRows)
    lay.addWidget(table)

    def add_row(lv) -> None:
        r = table.rowCount()
        table.insertRow(r)
        item = QTableWidgetItem(lv["name"])
        item.setData(Qt.UserRole, lv["id"])
        table.setItem(r, 0, item)
        table.setCellWidget(r, 1, muri._spin(lv["z"], -100.0, 1000.0))
        table.setCellWidget(r, 2, muri._spin(lv["h"], 0.1, 100.0))

    def collect():
        out = []
        for r in range(table.rowCount()):
            it = table.item(r, 0)
            out.append({"id": it.data(Qt.UserRole),
                        "name": it.text().strip() or f"Piano {r + 1}",
                        "z": table.cellWidget(r, 1).value(),
                        "h": table.cellWidget(r, 2).value()})
        return out

    base = {"v": [dict(lv) for lv in lvls]}

    def show(items) -> None:
        table.setRowCount(0)
        for lv in items:
            add_row(lv)

    def load(items) -> None:
        base["v"] = [dict(lv) for lv in items]
        show(items)

    def add_new() -> None:
        cur = collect()
        z = max((lv["z"] + lv["h"] for lv in cur), default=0.0)
        name = f"Piano {len(cur)}" if cur else "Piano terra"
        add_row({"id": new_id(), "name": name, "z": z, "h": 3.0})

    def remove() -> None:
        r = table.currentRow()
        if r < 0:
            return
        name = table.item(r, 0).text().strip() or f"Piano {r + 1}"
        if QMessageBox.question(
                dlg, "Elimina piano",
                f"Eliminare \"{name}\"?\nI suoi elementi restano dove sono "
                "ma diventano liberi (dopo Applica).",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No) == QMessageBox.Yes:
            table.removeRow(r)

    def move(step) -> None:
        r = table.currentRow()
        r2 = r + step
        if r < 0 or r2 < 0 or r2 >= table.rowCount():
            return
        cur = collect()
        lo, hi = (r, r2) if r < r2 else (r2, r)
        a, b = cur[lo], cur[hi]          # a = sopra nella tabella
        gap = b["z"] - (a["z"] + a["h"])
        # scambio di posizione: il piano che sale prende la quota dell'altro
        z0 = a["z"]
        b["z"] = z0
        a["z"] = z0 + b["h"] + gap
        cur[lo], cur[hi] = b, a
        show(cur)
        table.selectRow(r2)

    def apply() -> None:
        new = collect()
        old = {lv["id"]: lv for lv in base["v"]}
        moved = [lv["name"] for lv in new if lv["id"] in old
                 and abs(lv["z"] - old[lv["id"]]["z"]) > 1e-9]
        gone = [o["name"] for i, o in old.items()
                if i not in {lv["id"] for lv in new}]
        if not moved and not gone and new == base["v"]:
            return
        msg = ["Applicare le modifiche ai piani?"]
        if moved:
            msg.append("Quota cambiata (muri e solai si spostano): "
                       + ", ".join(moved))
        if gone:
            msg.append("Piani eliminati (elementi liberi): "
                       + ", ".join(gone))
        if QMessageBox.question(
                dlg, "Conferma", "\n\n".join(msg),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes) == QMessageBox.Yes:
            on_apply(new)

    load(lvls)
    row = QHBoxLayout()
    b_add = QPushButton("Aggiungi piano")
    b_del = QPushButton("Elimina piano")
    b_up = QPushButton("\u25B2 Sposta su")
    b_dn = QPushButton("\u25BC Sposta gi\u00f9")
    b_add.clicked.connect(add_new)
    b_del.clicked.connect(remove)
    b_up.clicked.connect(lambda: move(1))
    b_dn.clicked.connect(lambda: move(-1))
    row.addWidget(b_add)
    row.addWidget(b_del)
    row.addWidget(b_up)
    row.addWidget(b_dn)
    row.addStretch(1)
    lay.addLayout(row)
    note = QLabel("Eliminando un piano, i suoi elementi restano dove sono "
                  "ma diventano liberi.")
    note.setWordWrap(True)
    lay.addWidget(note)
    box = QDialogButtonBox()
    b_apply = box.addButton("Applica", QDialogButtonBox.AcceptRole)
    b_close = box.addButton("Chiudi", QDialogButtonBox.RejectRole)
    b_apply.clicked.connect(apply)
    b_close.clicked.connect(dlg.close)
    lay.addWidget(box)
    dlg.reload = load
    dlg.destroyed.connect(lambda *_: _DLG.update(dlg=None))
    return dlg


def commit_levels(viewport, new) -> bool:
    """Applica un nuovo elenco di piani (un solo passo di undo).
    Usata dal dialogo e dal pannello laterale (piani_panel.py)."""
    sc = viewport.scene
    if getattr(sc, "edit_group", None) is not None:
        viewport.flash_status("Chiudi il gruppo che stai modificando", 4000)
        return False

    def mutate(s):
        apply_levels(s, new)
        _refresh(s)

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(f"{len(new)} piani", 3000)
    return True


def add_level_on_top(viewport) -> None:
    """Nuovo piano sopra l'ultimo (quota = quota + altezza dell'ultimo)."""
    cur = levels(viewport.scene)
    z = max((lv["z"] + lv["h"] for lv in cur), default=0.0)
    name = f"Piano {len(cur)}" if cur else "Piano terra"
    new = cur + [{"id": new_id(), "name": name, "z": z, "h": 3.0}]
    if commit_levels(viewport, new):
        set_active(new[-1]["id"])


def ensure_default_levels(viewport) -> None:
    """All'apertura: se il disegno non ha piani, crea Piano terra (quota 0)
    e Piano copertura (quota 3 m) e attiva il piano terra."""
    if levels(viewport.scene):
        return
    ground = {"id": new_id(), "name": "Piano terra", "z": 0.0, "h": 3.0}
    roof = {"id": new_id(), "name": "Piano copertura", "z": 3.0, "h": 3.0}
    if commit_levels(viewport, [ground, roof]):
        set_active(ground["id"])


def edit_levels(viewport) -> None:
    scene = viewport.scene
    cur = levels(scene)
    if not cur:
        cur = [{"id": new_id(), "name": "Piano terra", "z": 0.0, "h": 3.0}]

    dlg = _DLG["dlg"]
    if dlg is not None:
        try:
            dlg.reload(cur)
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            return
        except RuntimeError:
            _DLG["dlg"] = None

    def on_apply(new) -> None:
        if commit_levels(viewport, new):
            d = _DLG["dlg"]
            if d is not None:
                d.reload(levels(viewport.scene))

    dlg = _levels_dialog(viewport.window(), cur, on_apply)
    _DLG["dlg"] = dlg
    dlg.show()


# ---------------------------------------------------------------------------
# Assegna al piano (tasto destro su muri / solai)
# ---------------------------------------------------------------------------

def _selected_elems(scene):
    out = []
    for e in scene.selection:
        g = getattr(e, "owner", None) or e
        if g in scene.groups and _elem(g) is not None and g not in out:
            out.append(g)
    return out


def assign_to_level(viewport, groups=None) -> None:
    scene = viewport.scene
    if getattr(scene, "edit_group", None) is not None:
        viewport.flash_status("Chiudi il gruppo che stai modificando", 4000)
        return
    groups = groups or _selected_elems(scene)
    if not groups:
        viewport.flash_status("Seleziona muri o solai", 3000)
        return
    if not levels(scene):
        viewport.flash_status("Prima crea i piani: MyHouse > Piani", 4000)
        return
    first = _elem(groups[0])[0]
    dlg = QDialog(viewport.window())
    dlg.setWindowTitle(f"Assegna al piano ({len(groups)} elementi)")
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    cb = level_combo(scene, first.get("lv"))
    off = muri._spin(first.get("off", 0.0), -100.0, 1000.0)
    form.addRow("Piano", cb)
    form.addRow("Distanza dal piano (m)", off)
    lay.addLayout(form)
    hint = QLabel("Distanza dal piano: base del muro, faccia superiore del "
                  "solaio, faccia inferiore di pilastri e travi, quota di "
                  "partenza delle scale, gronda del tetto, punto più basso "
                  "delle balaustre. Con \"Nessuno\" l'elemento resta alla "
                  "quota attuale.")
    hint.setWordWrap(True)
    lay.addWidget(hint)
    cb.currentIndexChanged.connect(
        lambda _i: off.setEnabled(bool(cb.currentData())))
    off.setEnabled(bool(cb.currentData()))
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return
    lid, dist = cb.currentData() or None, off.value()

    def mutate(sc):
        lv = get(sc, lid)
        for g in groups:
            d, kind = _elem(g)
            d = dict(d)
            if lv:
                d.update({"lv": lv["id"], "lvn": lv["name"], "off": dist})
                kind["zset"](d, lv["z"] + dist)
            else:
                for k in ("lv", "lvn", "off"):
                    d.pop(k, None)
            if d.get("tlv") and kind.get("hset") is not None:
                h = _target_h(levels(sc), d["tlv"], d.get("toff", 0.0),
                              d.get("lv"), kind["zget"](d))
                if h is not None:
                    kind["hset"](d, h)
            _write(g, kind, d, True)
        _refresh(sc)

    viewport.history.execute(muri.MuriCommand(mutate))
    viewport.notify_scene_changed()
    viewport.update()
    viewport.flash_status(f"{len(groups)} elementi aggiornati", 3000)


# ---------------------------------------------------------------------------
# Registrazione
# ---------------------------------------------------------------------------

def _icon():
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(215, 205, 190))
    p.drawRect(8, 34, 32, 7)
    p.drawRect(8, 22, 32, 7)
    p.drawRect(8, 10, 32, 7)
    p.end()
    return QIcon(pm)


def _outliner_kind(group):
    d = (getattr(group, "ext", None) or {}).get(KEY)
    if not (isinstance(d, dict) and "levels" in d):
        return None
    lvs = sorted(d["levels"], key=lambda lv: lv["z"])
    return {"type": "Piani",
            "props": [(lv["name"], f"quota {lv['z']:.2f} m · h {lv['h']:.2f} m")
                      for lv in lvs]}


def register(api) -> None:
    app = api.app

    def run() -> None:
        edit_levels(app.viewport)

    api.add_button("Piani", "Definisci i piani (quote) dell'edificio",
                   _icon(), run)
    add_panel = getattr(app, "add_panel", None)
    if add_panel is not None:
        from .piani_panel import PianiPanel
        add_panel("Piani", PianiPanel(app))
    QTimer.singleShot(0, lambda: ensure_default_levels(app.viewport))
    add_ctx = getattr(app, "add_context_menu", None)
    if add_ctx is not None:
        def context(menu, selection) -> None:
            if not _selected_elems(app.viewport.scene):
                return
            menu.addSeparator()
            menu.addAction(
                "Assegna al piano…",
                lambda: QTimer.singleShot(
                    0, lambda: assign_to_level(app.viewport)))

        add_ctx(context)
    add_kind = getattr(app, "add_outliner_kind", None)
    if add_kind is not None:
        add_kind(_outliner_kind)
