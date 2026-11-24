# SPDX-License-Identifier: GPL-3.0-or-later
"""Lengths for the myHouse dialogs, in feet and inches or metric (shared code,
not a feature).

IngeTrazo stores every length in metres, and so does myHouse. What changes is
what the user reads and types:

  - imperial: feet and inches, in fractions down to 1/16" (96, 8', 8'6 1/2",
    7 4 for 7'4"; a bare number is inches)
  - metric: as myHouse has always worked, plain metres

Which one is the myHouse units setting (Extensions > myHouse > Units…):
"auto" follows the document's units, "imperial" and "metric" force one.

Every dialog field is a LengthSpin (each module's _spin makes one). It is a
plain QDoubleSpinBox until it is shown in imperial units beside a label that
says "(m)": then the field reads and types feet and inches (its value() stays
in METRES) and the label says "(ft-in)". Nothing changes in metric.

    from ._imperial import IN, FT, LengthSpin, fmt_len, ask_length, dflt

fmt_len(metres) is the read-out text; dflt(imperial, metric) picks a default
size (both in metres) for the units in use.
"""
from __future__ import annotations

import os
import re

from PySide6.QtCore import QSettings
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel, QVBoxLayout,
)

from core import units

IN = 0.0254          # one inch, in metres
FT = 0.3048          # one foot, in metres
FEET_FROM = 24 * IN  # shorter than this reads in inches, longer in feet-inches
_FRACTION = 2        # core.units precision: 2 = sixteenths of an inch
_FEET_INCHES = re.compile(r"^(\d+)\s+(\d+(?:\.\d+)?(?:\s+\d+/\d+)?)$")

SETTING = "myhouse/units"
MODES = ("auto", "imperial", "metric")
_METRIC = ("m", "cm", "mm")
METRES_MARK = "(m)"          # what a label of a length in metres says
IMPERIAL_MARK = "(ft-in)"    # what it says instead in feet and inches
_setting: str | None = None


def setting() -> str:
    """The saved choice: "auto", "imperial" or "metric"."""
    global _setting
    if _setting is None:        # MYHOUSE_UNITS overrides it (tests, scripts)
        value = str(os.environ.get("MYHOUSE_UNITS")
                    or QSettings().value(SETTING) or "auto")
        _setting = value if value in MODES else "auto"
    return _setting


def set_setting(value: str) -> None:
    global _setting
    _setting = value if value in MODES else "auto"
    QSettings().setValue(SETTING, _setting)


def imperial() -> bool:
    """Whether lengths are read and typed in feet and inches right now."""
    choice = setting()
    if choice == "auto":
        return units.model_unit() not in _METRIC
    return choice == "imperial"


def dflt(imperial_value, metric_value):
    """A default for the units in use: both given in metres (or both any
    other kind of value, such as a size code)."""
    return imperial_value if imperial() else metric_value


def fmt(metres: float, feet: bool | None = None) -> str:
    """A length in feet and inches: 2 1/2" or 8'6" (feet=True/False forces
    the form; None picks inches below two feet and feet-inches from there up)."""
    if feet is None:
        feet = abs(metres) >= FEET_FROM - 1e-9
    return units.format_length(metres, "ft-in-frac" if feet else "in-frac",
                               _FRACTION)


def fmt_len(metres: float) -> str:
    """A length as read-out text. With the setting on "auto" it is IngeTrazo's
    own (the document's units and precision); "imperial" and "metric" force
    feet and inches or metres."""
    choice = setting()
    if choice == "imperial":
        return fmt(metres)
    if choice == "metric" and units.model_unit() not in _METRIC:
        return units.localized(units.format_length(float(metres), "m", 3))
    return units.fmt_len(metres)


def parse(text: str):
    """Metres from typed text; None if unreadable. A bare number is inches
    (imperial) or metres; a unit can always be typed."""
    text = str(text).strip()
    if not imperial():
        value = units.parse(text, "length", unit="m").value
        if value is None and "," in text:          # 2,40 as well as 2.40
            value = units.parse(text.replace(",", "."), "length",
                                unit="m").value
        return value
    m = _FEET_INCHES.match(text)
    if m:                                # 7 2 or 7 2 1/2: feet, then inches
        text = f"{m.group(1)}'{m.group(2)}\""
    return units.parse(text, "length", unit="in").value


def _fields(item):
    """The LengthSpins of one layout item (a widget, a container or a layout)."""
    if item is None:
        return []
    w = item.widget()
    if w is not None:
        return [w] if isinstance(w, LengthSpin) else w.findChildren(LengthSpin)
    lay = item.layout()
    out = []
    if lay is not None:
        for i in range(lay.count()):
            out += _fields(lay.itemAt(i))
    return out


class LengthSpin(QDoubleSpinBox):
    """A QDoubleSpinBox that turns into a feet-and-inches field when it is
    shown, in imperial units, beside a label marked "(m)". value(), setValue()
    and the range stay in metres either way."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._length = False
        self._feet = None
        self._shown = super().decimals()   # decimals asked for by the caller

    # -- what the dialog code calls -----------------------------------------
    def setDecimals(self, n: int) -> None:
        self._shown = n
        # metres to 1/64" need more than the 3 decimals a metric field has
        super().setDecimals(max(n, 8) if imperial() else n)

    def as_length(self, feet=None) -> None:
        """From now on this field reads and types feet and inches."""
        self._length, self._feet = True, feet
        super().setDecimals(8)
        self.setValue(self.value())        # the text follows

    def is_length(self) -> bool:
        return self._length

    # -- finding the label --------------------------------------------------
    def showEvent(self, event) -> None:
        if not self._length and imperial():
            try:
                self._adopt_label()
            except Exception:              # a field must never break a dialog
                pass
        super().showEvent(event)

    def _adopt_label(self) -> None:
        label = None
        for form in self.window().findChildren(QFormLayout):
            for row in range(form.rowCount()):
                if self in _fields(form.itemAt(row, QFormLayout.FieldRole)):
                    item = form.itemAt(row, QFormLayout.LabelRole)
                    label = item.widget() if item is not None else None
                    break
            if label is not None:
                break
        if label is None:                  # a label just before it in a row
            parent = self.parentWidget()
            lay = parent.layout() if parent is not None else None
            stack = [lay] if lay is not None else []
            while stack and label is None:
                cur = stack.pop()
                for i in range(cur.count()):
                    it = cur.itemAt(i)
                    if it.layout() is not None:
                        stack.append(it.layout())
                    elif it.widget() is self and i > 0:
                        label = cur.itemAt(i - 1).widget()
        if not isinstance(label, QLabel) or (
                METRES_MARK not in label.text()
                and IMPERIAL_MARK not in label.text()):
            return
        self.as_length()
        if METRES_MARK in label.text():
            label.setText(label.text().replace(METRES_MARK, IMPERIAL_MARK))
        if not getattr(label, "_myhouse_units", False):
            plain = label.setText          # later texts keep the right unit

            def set_text(text, _plain=plain):
                _plain(str(text).replace(METRES_MARK, IMPERIAL_MARK))
            label.setText = set_text
            label._myhouse_units = True

    # -- text ---------------------------------------------------------------
    def textFromValue(self, value: float) -> str:
        if self._length:
            return fmt(value, self._feet)
        if self._shown != super().decimals():
            return self.locale().toString(float(value), "f", self._shown)
        return super().textFromValue(value)

    def valueFromText(self, text: str) -> float:
        if not self._length:
            return super().valueFromText(text)
        metres = parse(text)
        return self.value() if metres is None else metres

    def validate(self, text: str, pos: int):
        if not self._length:
            return super().validate(text, pos)
        ok = parse(text) is not None
        return (QValidator.Acceptable if ok else QValidator.Intermediate,
                text, pos)

    def stepBy(self, steps: int) -> None:
        if not self._length:
            super().stepBy(steps)
            return
        # 1/8" on small sizes, 1" on big ones
        step = IN if abs(self.value()) >= FEET_FROM - 1e-9 else IN / 8
        self.setValue(self.value() + steps * step)


def spin(value, lo, hi, feet=None):
    """A length field in the units in use: value, lo and hi in metres."""
    s = LengthSpin()
    s.setDecimals(3)
    s.setRange(lo, hi)
    s.setValue(value)
    if imperial():
        s.as_length(feet)
    return s


def ask_length(parent, title: str, label: str, metres: float,
               lo: float = -1000.0, hi: float = 1000.0):
    """Like QInputDialog.getDouble for a length in metres: (metres, ok). The
    label may say "(m)"; in feet and inches it says "(ft-in)" instead."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    box = spin(metres, lo, hi)
    if imperial():
        label = label.replace(METRES_MARK, IMPERIAL_MARK)
    form.addRow(label, box)
    lay.addLayout(form)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    lay.addWidget(buttons)
    box.selectAll()
    box.setFocus()
    ok = dlg.exec() == QDialog.Accepted
    return box.value(), ok
