import pytest
from PySide6.QtWidgets import QComboBox, QDialog, QFormLayout


def rows(dlg):
    """{label text: field widget} of every form row of a dialog."""
    out = {}
    for form in dlg.findChildren(QFormLayout):
        for r in range(form.rowCount()):
            li, fi = form.itemAt(r, QFormLayout.LabelRole), form.itemAt(r, QFormLayout.FieldRole)
            if li is not None and fi is not None and li.widget() is not None and fi.widget() is not None:
                out[li.widget().text()] = fi.widget()
    return out


@pytest.fixture
def door_dialog(myhouse, window, monkeypatch):
    """Runs porte.ask_params with 'play(rows)' in place of the user; returns its result."""
    from myhouse import _imperial, porte
    def run(play, units="metric", **current):
        monkeypatch.setattr(_imperial, "_setting", units)

        def fake_exec(dlg):
            dlg.show()
            play(rows(dlg))
            dlg.close()
            return QDialog.Accepted
        monkeypatch.setattr(QDialog, "exec", fake_exec)
        base = dict(porte._params_geom(), W=0.90, H=2.10, fw=0.06, fd=0.12, sw=0.04, leaves=1, model="porta")
        base.update(current)
        return porte.ask_params(window, base, "Door", "Place")
    return run


def label(italian):
    from myhouse._lingua import tr
    return tr(italian)


W, H, DW, DH = "Larghezza totale (W) (m)", "Altezza totale (H) (m)", "Larghezza porta, senza telaio (m)", "Altezza porta, senza telaio (m)"
FW, LEAVES, A1 = "Telaio: larghezza profilo (f) (m) · 0 = senza telaio", "Ante", "Anta 1: larghezza (a1) (m)"


def test_door_size_is_the_unit_less_the_frame(myhouse):
    from myhouse import porte
    d = dict(W=0.90, H=2.10, fw=0.06, leaves=1, model="porta")
    assert porte.door_size(d) == pytest.approx((0.90 - 0.12 - 0.006, 2.10 - 0.06 - 0.006))
    assert porte.door_size(dict(d, leaves=2)) == pytest.approx((0.90 - 0.12 - 0.012, 2.10 - 0.066))
    assert porte.door_size(dict(d, model="varco")) == pytest.approx((0.90, 2.10))    # the hole itself
    assert porte.door_size(dict(d, fw=0.0)) == pytest.approx((0.90, 2.10))           # no frame


def test_dialog_shows_the_slab_and_keeps_it_when_the_frame_changes(door_dialog):
    seen = {}

    def play(r):
        seen["start"] = (r[label(DW)].value(), r[label(DH)].value())
        r[label(DW)].setValue(0.80)                       # an 80 cm door
        seen["total"] = r[label(W)].value()
        r[label(FW)].setValue(0.10)                       # a wider frame: the door stays 80
        seen["after"] = (r[label(DW)].value(), r[label(W)].value())
        r[label(W)].setValue(1.20)                        # typing the hole instead
        seen["slab"] = r[label(DW)].value()
    p = door_dialog(play)
    assert seen["start"] == pytest.approx((0.774, 2.034))
    assert seen["total"] == pytest.approx(0.80 + 0.12 + 0.006)
    assert seen["after"] == pytest.approx((0.80, 0.80 + 0.20 + 0.006))
    assert seen["slab"] == pytest.approx(1.20 - 0.20 - 0.006)
    assert p["W"] == pytest.approx(1.20) and p["fw"] == pytest.approx(0.10)


def test_dialog_two_leaves_and_asymmetric_follow(door_dialog):
    seen = {}

    def play(r):
        leaves = r[label(LEAVES)]
        leaves.setCurrentIndex(leaves.findData(2))
        seen["two"] = (r[label(DW)].value(), r[label(W)].value())          # slab kept, one more gap in the hole
        leaves.setCurrentIndex(leaves.findData(3))
        r[label(A1)].setValue(0.50)
        seen["asym"] = (r[label(W)].value(), r[label(DW)].value())
    door_dialog(play)
    assert seen["two"] == pytest.approx((0.774, 0.774 + 0.12 + 0.012))
    w, dw = seen["asym"]
    assert dw == pytest.approx(w - 0.12 - 0.012)


def typed(field, text):
    """Types text over a field's content, one key at a time, as a user does."""
    from PySide6.QtTest import QTest
    field.setFocus()
    field.selectAll()
    QTest.keyClicks(field, text)
    return field.lineEdit().text()


def test_dialog_typing_a_door_size_is_not_overwritten(door_dialog):
    seen = {}

    def play(r):
        seen["text"] = typed(r[label(DW)], "0.8")         # "0" alone is below every limit
        seen["w"] = (r[label(DW)].value(), r[label(W)].value())
        seen["text_h"] = typed(r[label(DH)], "2")
        seen["h"] = (r[label(DH)].value(), r[label(H)].value())
        seen["editable"] = not r[label(W)].isReadOnly()
    door_dialog(play)
    assert seen["text"] == "0.8" and seen["text_h"] == "2"
    assert seen["w"] == pytest.approx((0.80, 0.80 + 0.126))
    assert seen["h"] == pytest.approx((2.0, 2.0 + 0.066))
    assert seen["editable"]                               # metric: the totals can still be typed


def test_dialog_imperial_door_size_drives_the_totals(door_dialog):
    IN = 0.0254
    seen = {}

    def ft(italian):
        return label(italian).replace("(m)", "(ft-in)")

    def play(r):
        dw, dh, w, h, fw = (r[ft(k)] for k in (DW, DH, W, H, FW))
        seen["text"] = typed(dw, "30")                    # 30": "3" alone must not be rewritten
        seen["text_h"] = typed(dh, "6'8")
        seen["size"] = (dw.value(), dh.value(), w.value(), h.value())
        seen["locked"] = w.isReadOnly() and h.isReadOnly()
        fw.setValue(1.5 * IN)                             # a wider frame: door kept, totals grow
        seen["frame"] = (dw.value(), dh.value(), w.value(), h.value())
        leaves = r[label(LEAVES)]
        leaves.setCurrentIndex(leaves.findData(2))
        seen["two"] = (dw.value(), w.value())
    p = door_dialog(play, units="imperial", fw=0.75 * IN)
    assert seen["text"] == "30" and seen["text_h"] == "6'8"
    assert seen["locked"]
    assert seen["size"] == pytest.approx((30 * IN, 80 * IN, 31.5 * IN + 0.006, 80.75 * IN + 0.006))
    assert seen["frame"] == pytest.approx((30 * IN, 80 * IN, 33 * IN + 0.006, 81.5 * IN + 0.006))
    assert seen["two"] == pytest.approx((30 * IN, 33 * IN + 0.012))
    assert p["W"] == pytest.approx(33 * IN + 0.012) and p["H"] == pytest.approx(81.5 * IN + 0.006)


def bbox_x(mesh):
    xs = [v.position.x() for v in mesh.vertices]
    return min(xs), max(xs)


def test_bifold_panels_and_knobs(myhouse):
    from myhouse import porte
    base = dict(porte._params_geom(), W=1.60, H=2.10, fw=0.02, fd=0.12, sw=0.035, model="bifold",
                o=[0., 0., 0.], u=[1., 0.], flip=False)
    for leaves, panels, knobs in ((1, 2, 1), (2, 4, 2)):
        d = dict(base, leaves=leaves)
        assert porte._panels("bifold", leaves) == panels and porte.validate(d) is None
        frame, leaf, glass, hw = porte.door_meshes_all(d)
        assert len(leaf.faces) == 6 * panels                 # one box each
        assert len(hw.faces) == 12 * knobs                   # stem and knob
        lo, hi = bbox_x(leaf)
        assert (lo, hi) == pytest.approx((0.02 + 0.003, 1.60 - 0.02 - 0.003))
    assert not porte.can_open(base) and porte.arch_rise(dict(base, arch="full")) == 0.0
    assert porte.door_size(dict(base, leaves=2)) == pytest.approx((1.60 - 0.04 - 0.024, 2.10 - 0.026))


def test_dialog_choosing_bifold_proposes_a_closet_front(door_dialog):
    seen = {}

    def play(r):
        model, leaves = r[label("Modello")], r[label(LEAVES)]
        model.setCurrentIndex(model.findData("bifold"))
        seen["leaves"] = (leaves.currentData(), leaves.itemText(1), leaves.isEnabled())
        seen["thick"] = r[label("Spessore anta (a) (m)")].value()
        seen["arch"] = r[label("Forma della parte alta")].isEnabled()
    p = door_dialog(play)
    assert seen["leaves"] == (2, "Dual bi-fold (4 panels)", True)
    assert seen["thick"] == pytest.approx(0.035) and seen["arch"] is False
    assert (p["model"], p["leaves"], p["arch"], p["asym"], p["slide"]) == ("bifold", 2, "none", False, False)


def span_along(mesh, u):
    ts = [v.position.x() * u[0] + v.position.y() * u[1] for v in mesh.vertices]
    return min(ts), max(ts)


def test_reversed_door_stays_in_its_hole(myhouse):
    from myhouse import porte
    d = dict(porte._params_geom(), W=0.90, H=2.10, fw=0.06, fd=0.12, sw=0.04, leaves=1, model="porta",
             o=[2., 1., 0.], u=[1., 0.], flip=False)
    r = dict(d, **porte.reversed_place(d))
    assert r["o"] == pytest.approx([2.9, 1., 0.]) and r["flip"] is True
    frame, _leaf, _glass, hw = porte.door_meshes_all(d)
    frame_r, _l, _g, hw_r = porte.door_meshes_all(r)
    assert span_along(frame_r, (1, 0)) == pytest.approx(span_along(frame, (1, 0)))   # same hole
    mid = 2.45
    side = lambda m: sum(span_along(m, (1, 0))) / 2 > mid
    assert side(hw) != side(hw_r)                                                   # handle changed side
    back = dict(r, **porte.reversed_place(r))
    assert back["o"] == pytest.approx(d["o"]) and back["flip"] is False


def test_reverse_placed_door_and_while_placing(viewport, monkeypatch):
    from PySide6.QtGui import QVector3D
    from myhouse import finestre, muri, porte
    scene = viewport.scene
    muri.build_walls(scene, [(0., 0.), (5., 0.)], False, 0.30, 2.7, 0.0, "W")
    p = dict(porte._params_geom(), W=0.90, H=2.10, fw=0.06, fd=0.12, sw=0.04, leaves=1, model="porta")
    monkeypatch.setattr(porte._Settings, "rev", False)
    plain = porte.place_at(scene, QVector3D(2., 0.1, 0.), p)
    monkeypatch.setattr(porte._Settings, "rev", True)
    turned = porte.place_at(scene, QVector3D(2., 0.1, 0.), p)
    assert turned["flip"] != plain["flip"]
    assert abs(turned["o"][0] - plain["o"][0]) == pytest.approx(0.90)
    porte.make_door(scene, p, plain)
    finestre.update_openings(scene)
    door = next(g for g in scene.groups if porte.door_data(g))
    wall = next(g for g in scene.groups if muri.wall_data(g))
    hole = [list(o) for o in muri.wall_data(wall)["open"]]
    porte.reverse_doors(viewport, [door])
    assert porte.door_data(door)["flip"] != plain["flip"]
    after = [list(o) for o in muri.wall_data(wall)["open"]]
    assert len(after) == len(hole) == 1 and after[0][:4] == pytest.approx(hole[0][:4])   # the hole did not move
