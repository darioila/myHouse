# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
    QWidget,
)

from ._scroll import fit_dialog
from ._lingua import tr
from ._imperial import LengthSpin

ORDER = 910

_K = "myhouse_hdri/"
_fatto = {"patch": False}


_BLENDER_FN = '''
def _use_hdri(scene, path, strength, rot_deg):
    """Cielo = immagine HDRI; il sole (e la luna) del cielo si tolgono."""
    for ob in list(bpy.data.objects):
        if ob.type == "LIGHT" and ob.data.type == "SUN":
            bpy.data.objects.remove(ob, do_unlink=True)
    world = bpy.data.worlds.new("hdri")
    scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    mp = nt.nodes.new("ShaderNodeMapping")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    env.image = bpy.data.images.load(path)
    mp.inputs["Rotation"].default_value[2] = math.radians(rot_deg)
    bg.inputs["Strength"].default_value = strength
    nt.links.new(tc.outputs["Generated"], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], env.inputs["Vector"])
    nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    say("hdri", path)


def main():
'''

_BLENDER_CALL = '''    _hdri = os.environ.get("INGETRAZO_HDRI", "")
    if _hdri and os.path.isfile(_hdri):
        try:
            _use_hdri(scene, _hdri,
                      float(os.environ.get("INGETRAZO_HDRI_STRENGTH", "1")),
                      float(os.environ.get("INGETRAZO_HDRI_ROT", "0")))
        except Exception as exc:  # noqa: BLE001 - il cielo normale resta
            say("hdri", "failed", exc)
    add_lights(scene, job.get("lights") or [])
'''


def _patched_script(original: Path) -> Path | None:
    try:
        text = original.read_text(encoding="utf-8").replace("\r\n", "\n")
        pairs = (
            ("import json\nimport math\nimport sys\n",
             "import json\nimport math\nimport os\nimport sys\n"),
            ("\ndef main():\n", _BLENDER_FN),
            ('    add_lights(scene, job.get("lights") or [])\n', _BLENDER_CALL),
        )
        for old, new in pairs:
            if text.count(old) != 1:
                return None
            text = text.replace(old, new)
        folder = Path(tempfile.gettempdir()) / "myhouse_hdri"
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"render_scene_{original.stat().st_mtime_ns}.py"
        if not dest.is_file():
            dest.write_text(text, encoding="utf-8")
        return dest
    except Exception:
        return None


def _leggi() -> dict:
    s = QSettings()
    return {"on": s.value(_K + "on", False, type=bool),
            "path": s.value(_K + "path", "", type=str),
            "forza": s.value(_K + "forza", 1.0, type=float),
            "rot": s.value(_K + "rot", 0.0, type=float)}


def _scrivi(c: dict) -> None:
    s = QSettings()
    for k, v in c.items():
        s.setValue(_K + k, v)


def _attivo(c: dict) -> bool:
    return bool(c["on"] and c["path"] and os.path.isfile(c["path"]))


def _patch() -> None:
    if _fatto["patch"]:
        return
    from core import render_blender as rb
    env_orig, cmd_orig = rb.clean_env, rb.command

    def clean_env(*a, **k):
        env = dict(env_orig(*a, **k))
        c = _leggi()
        if _attivo(c):
            env["INGETRAZO_HDRI"] = c["path"]
            env["INGETRAZO_HDRI_STRENGTH"] = str(c["forza"])
            env["INGETRAZO_HDRI_ROT"] = str(c["rot"])
        return env

    def command(*a, **k):
        argv = cmd_orig(*a, **k)
        if not _attivo(_leggi()):
            return argv
        try:
            out = []
            for x in argv:
                norm = str(x).replace("\\", "/")
                if norm.endswith("/render_scene.py"):
                    mine = _patched_script(Path(str(x)))
                    x = str(mine) if mine is not None else x
                out.append(x)
            return out
        except Exception:
            return argv

    rb.clean_env, rb.command = clean_env, command
    _fatto["patch"] = True


def _find_panel():
    from PySide6.QtWidgets import QApplication
    for w in QApplication.allWidgets():
        if type(w).__name__ == "RenderPanel" and hasattr(w, "set_sync"):
            return w
    return None


def _ricarica_anteprima() -> None:
    panel = _find_panel()
    try:
        sync = panel._sync
        if sync.active:
            sync._scene_key = None
    except Exception:
        pass


def _chiedi(parent, cur: dict):
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("HDRI al posto del cielo"))
    lay = QVBoxLayout(dlg)
    on = QCheckBox(tr("Usa un'immagine HDRI al posto del cielo"))
    on.setChecked(cur["on"])
    lay.addWidget(on)

    riga = QWidget()
    h = QHBoxLayout(riga)
    h.setContentsMargins(0, 0, 0, 0)
    path = QLineEdit(cur["path"])
    path.setPlaceholderText(tr("File .hdr o .exr"))
    sfoglia = QPushButton(tr("Scegli…"))

    def scegli() -> None:
        start = str(Path(path.text()).parent) if path.text() else ""
        f, _ = QFileDialog.getOpenFileName(
            dlg, tr("Scegli HDRI"), start,
            tr("HDRI (*.hdr *.exr);;Tutti i file (*.*)"))
        if f:
            path.setText(f)
            on.setChecked(True)

    sfoglia.clicked.connect(scegli)
    h.addWidget(path, 1)
    h.addWidget(sfoglia)

    form = QFormLayout()
    form.addRow(tr("Immagine"), riga)
    forza = LengthSpin()
    forza.setRange(0.05, 20.0)
    forza.setSingleStep(0.1)
    forza.setValue(cur["forza"])
    rot = LengthSpin()
    rot.setRange(0.0, 360.0)
    rot.setSingleStep(15.0)
    rot.setSuffix(" °")
    rot.setValue(cur["rot"])
    form.addRow(tr("Intensità"), forza)
    form.addRow(tr("Rotazione"), rot)
    lay.addLayout(form)
    nota = QLabel(tr("Con l'HDRI il sole del pannello Ombre non viene usato: "
                     "la luce viene dall'immagine. Ruota l'HDRI per spostare "
                     "il sole."))
    nota.setWordWrap(True)
    lay.addWidget(nota)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    fit_dialog(dlg)
    if dlg.exec() != QDialog.Accepted:
        return None
    return {"on": on.isChecked(), "path": path.text().strip(),
            "forza": forza.value(), "rot": rot.value()}


def _open(api) -> None:
    vp = api.window.viewport
    try:
        _patch()
    except Exception:
        vp.flash_status(tr("Plugin Render con Blender non disponibile"), 4000)
        return
    res = _chiedi(api.window, _leggi())
    if res is None:
        return
    if res["on"] and not os.path.isfile(res["path"]):
        vp.flash_status(tr("File HDRI non trovato"), 4000)
        res["on"] = False
    _scrivi(res)
    _ricarica_anteprima()
    vp.flash_status(tr("HDRI attivo nei prossimi render e nell'anteprima")
                    if res["on"] else tr("HDRI disattivato: cielo normale"),
                    5000)


def _icon() -> QIcon:
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.setBrush(QColor(120, 170, 230))
    p.drawEllipse(7, 7, 34, 34)
    p.setBrush(QColor(240, 200, 80))
    p.drawEllipse(26, 12, 8, 8)
    p.setBrush(Qt.NoBrush)
    p.drawArc(7, 14, 34, 20, 0, -180 * 16)
    p.drawPolyline([QPoint(10, 38), QPoint(20, 30), QPoint(28, 36),
                    QPoint(38, 30)])
    p.end()
    return QIcon(pm)


def register(api) -> None:
    try:
        _patch()
    except Exception:
        pass
