from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFormLayout, QScrollArea, QWidget

# Limiti di dimensione delle finestre di dialogo (in pixel logici, cioe' gia'
# divisi per la scala di Windows: 1600x900 al 125% = 1280x720).
MAX_W_PX = 720        # larghezza massima iniziale di un dialogo
MAX_W_FRAC = 0.92     # ...e mai oltre questa frazione dello schermo
MAX_H_FRAC = 0.85     # lascia spazio a barra del titolo e barra delle applicazioni


def _avail(dlg):
    scr = None
    try:
        scr = dlg.screen()
    except Exception:
        pass
    if scr is None:
        scr = QApplication.primaryScreen()
    return scr.availableGeometry() if scr is not None else None


def fit_dialog(dlg, want_w: int | None = None, want_h: int | None = None,
               max_w: int = MAX_W_PX) -> None:
    """Ridimensiona il dialogo senza superare lo schermo; resta ridimensionabile
    (maniglia in basso a destra)."""
    try:
        dlg.setSizeGripEnabled(True)
    except Exception:
        pass
    hint = dlg.sizeHint()
    w = want_w if want_w else hint.width()
    h = want_h if want_h else hint.height()
    av = _avail(dlg)
    if av is not None:
        w = min(w, max_w, int(av.width() * MAX_W_FRAC))
        h = min(h, int(av.height() * MAX_H_FRAC))
    dlg.resize(max(w, 320), max(h, 220))


def scroll_form(dlg, lay, form, extra_h: int = 90) -> None:
    """Mette il contenuto `form` in un'area scorrevole (verticale e, se serve,
    orizzontale); i pulsanti aggiunti dopo da chi chiama restano sempre visibili."""
    if isinstance(form, QFormLayout):
        # le righe con etichetta lunga mettono il campo sotto l'etichetta
        # invece di allargare la finestra
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
    body = QWidget()
    body.setLayout(form)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.NoFrame)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setWidget(body)
    lay.addWidget(scroll, 1)
    body.adjustSize()
    hint = body.sizeHint()
    fit_dialog(dlg, hint.width() + 40, hint.height() + extra_h)
