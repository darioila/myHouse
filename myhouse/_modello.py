# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

from tools.base import Tool

ORDER = 100


class EsempioTool(Tool):
    name = "Esempio"
    shortcut = None

    def on_activate(self, viewport):
        viewport.flash_status("Ciao da MyHouse!", 3000)

    def on_deactivate(self, viewport):
        pass


def _icon():
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
