# SPDX-License-Identifier: GPL-3.0-or-later
"""MODELLO per una nuova funzione di MyHouse.

Copia questo file con un altro nome (senza "_" iniziale), ad esempio
porte.py, e cambia le parti marcate. Il nome che inizia con "_" fa sì che
questo modello NON venga caricato.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

from tools.base import Tool

ORDER = 100          # posizione nella barra (più basso = prima)


class EsempioTool(Tool):                     # <- cambia il nome
    name = "Esempio"
    shortcut = None

    def on_activate(self, viewport):
        # Strumento "una botta e via": fai qualcosa (es. apri un dialogo).
        viewport.flash_status("Ciao da MyHouse!", 3000)

    def on_deactivate(self, viewport):
        pass

    # Per uno strumento interattivo (clic nel disegno) vedi muri.py:
    # on_click, on_hover, on_cancel, on_key, rubber_band_lines, draw_overlay.


def _icon():                                 # <- disegna la tua icona
    pm = QPixmap(48, 48)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.drawEllipse(8, 8, 32, 32)
    p.end()
    return QIcon(pm)


def register(api) -> None:
    api.add_button("Esempio", "Cosa fa questo pulsante", _icon(),
                   api.run_tool(EsempioTool()))
