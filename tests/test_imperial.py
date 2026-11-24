import pytest
from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget


@pytest.fixture
def units(myhouse, monkeypatch):
    """Sets the myHouse units for one test: units("imperial")."""
    from myhouse import _imperial

    def choose(mode):
        monkeypatch.setattr(_imperial, "_setting", mode)
        return _imperial
    return choose


def plain_spin(module, value, lo=0., hi=100.):
    return module._spin(value, lo, hi)


def form_dialog(rows):
    dlg = QDialog()
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    for label, field in rows:
        form.addRow(label, field)
    lay.addLayout(form)
    dlg.show()
    return dlg, form


def test_format_and_parse(units):
    imp = units("imperial")
    assert imp.fmt(8 * imp.FT) == "8'0\"" or imp.fmt(8 * imp.FT).startswith("8'")
    assert imp.fmt(4.5 * imp.IN).replace(" ", "") in ('41/2"', "41/2″")
    for text, metres in (("96", 96 * imp.IN), ("8'", 8 * imp.FT), ("8'6 1/2\"", 102.5 * imp.IN), ("7 4", 88 * imp.IN)):
        assert imp.parse(text) == pytest.approx(metres)
    assert imp.parse("nonsense") is None
    met = units("metric")
    assert met.parse("2.4") == pytest.approx(2.4) and met.parse("2,4") == pytest.approx(2.4)
    assert met.dflt(1, 2) == 2 and units("imperial").dflt(1, 2) == 1


def test_metric_fields_are_untouched(units, window):
    from myhouse import muri
    units("metric")
    s = plain_spin(muri, 0.3)
    dlg, form = form_dialog([("Spessore (m)", s)])
    assert not s.is_length() and s.decimals() == 3 and s.text() in ("0.300", "0,300")
    assert form.labelForField(s).text() == "Spessore (m)"
    dlg.close()


def test_imperial_field_and_label_switch_when_shown(units, window):
    from myhouse import muri
    imp = units("imperial")
    length, angle = plain_spin(muri, 4.5 * imp.IN), plain_spin(muri, 30.)
    angle.setDecimals(1)
    dlg, form = form_dialog([("Spessore (m)", length), ("Angolo (°)", angle)])
    assert length.is_length() and not angle.is_length()
    assert form.labelForField(length).text() == "Spessore (ft-in)"
    assert "1/2" in length.text() and angle.text() in ("30.0", "30,0")
    assert length.value() == pytest.approx(4.5 * imp.IN)          # still metres, exactly
    length.lineEdit().setText("8'6")
    length.interpretText()
    assert length.value() == pytest.approx(102 * imp.IN)
    length.stepBy(1)
    assert length.value() == pytest.approx(103 * imp.IN)
    form.labelForField(length).setText("Larghezza (m)")            # a dialog renaming its row later
    assert form.labelForField(length).text() == "Larghezza (ft-in)"
    dlg.close()


def test_imperial_field_inside_a_row_container_and_beside_a_label(units, window):
    from myhouse import muri
    imp = units("imperial")
    a, b, c = (plain_spin(muri, v) for v in (1., 2., 3.))
    box = QWidget()
    row = QHBoxLayout(box)
    row.addWidget(a)
    row.addWidget(b)
    loose = QWidget()
    lrow = QHBoxLayout(loose)
    lab = QLabel("Dimensione (m)")
    lrow.addWidget(lab)
    lrow.addWidget(c)
    dlg, form = form_dialog([("Lati (m)", box), ("", loose)])
    assert a.is_length() and b.is_length() and c.is_length()
    assert lab.text() == "Dimensione (ft-in)"
    dlg.close()


def test_readout_follows_the_setting(units):
    imp = units("imperial")
    assert "'" in imp.fmt_len(3.0)
    assert "'" not in units("metric").fmt_len(3.0)


def test_ask_units_and_ask_length(units, window, monkeypatch):
    from myhouse import _imperial, unita
    units("auto")
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.Accepted)
    saved = []
    monkeypatch.setattr(_imperial, "set_setting", saved.append)
    assert unita.ask_units(window) and saved == ["auto"]
    units("imperial")
    value, ok = _imperial.ask_length(window, "t", "Quota (m)", 2.4384)
    assert ok and value == pytest.approx(2.4384)
