import pytest
from PySide6.QtWidgets import QDialog

from test_doors import label, rows


def window(myhouse, **kw):
    from myhouse import finestre
    d = dict(finestre._params(), W=2.40, H=1.40, sill=0.9, leaves=3, fw=0.06, fd=0.07, sw=0.05,
             o=[0., 0., 0.], u=[1., 0.], flip=False, tipo="")
    d.update(kw)
    return d


def xs(mesh):
    return sorted({round(v.position.x(), 6) for v in mesh.vertices})


def test_no_mullion_is_1_4_as_it_was(myhouse):
    from myhouse import finestre
    d = window(myhouse, mw=0.0)
    assert finestre._mullion(d) == 0.0 and finestre.sash_width(d) == pytest.approx((2.40 - 0.12) / 3)
    old = {k: v for k, v in d.items() if k not in finestre.MULLION_KEYS}     # a window saved by 1.4
    assert finestre.validate(old) is None
    f_new, g_new = finestre.window_meshes(d)
    f_old, g_old = finestre.window_meshes(old)
    assert len(f_new.faces) == len(f_old.faces) and xs(f_new) == xs(f_old) and xs(g_new) == xs(g_old)


def test_mullion_separates_the_sashes(myhouse):
    from myhouse import finestre
    plain = window(myhouse, mw=0.0)
    d = window(myhouse, mw=0.04, mf1=0.012, mf2=0.012, mc=0.02)
    wl = finestre.sash_width(d)
    assert wl == pytest.approx((2.40 - 0.12 - 2 * 0.04) / 3)
    frame, glass = finestre.window_meshes(d)
    base, _g = finestre.window_meshes(plain)
    # two mullions, each an I of 12 corners: 2 caps and 12 sides
    assert len(frame.faces) == len(base.faces) + 2 * 14
    first_web = (0.06 + wl, 0.06 + wl + 0.04)
    for x in (first_web[0], first_web[1], first_web[0] - 0.02, first_web[1] + 0.02):
        assert round(x, 6) in xs(frame)
    ys = sorted({round(v.position.y(), 6) for v in frame.vertices})
    sd = 0.07 * 0.6
    assert min(ys) == pytest.approx(-0.035) and round(-sd / 2 - 0.012, 6) in ys and round(sd / 2 + 0.012, 6) in ys
    handles = finestre.handle_mesh(d)
    assert len(handles.faces) == 3 * len(finestre.handle_mesh(window(myhouse, leaves=1)).faces)


def test_mullion_profile_shapes(myhouse):
    from myhouse import finestre
    full = finestre.mullion_profile(1.0, 1.04, -0.02, 0.02, 0.01, 0.01, 0.02)
    assert len(full) == 12 and min(p[0] for p in full) == pytest.approx(0.98) and max(p[1] for p in full) == pytest.approx(0.03)
    assert len(finestre.mullion_profile(1.0, 1.04, -0.02, 0.02, 0.0, 0.01, 0.02)) == 8     # no front flange
    assert len(finestre.mullion_profile(1.0, 1.04, -0.02, 0.02, 0.0, 0.0, 0.02)) == 4      # a plain post
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(full, full[1:] + full[:1]))
    assert area > 0                                                                         # counter-clockwise


def test_mullion_rules(myhouse):
    from myhouse import finestre
    assert finestre._mullion(window(myhouse, leaves=1, mw=0.04)) == 0.0          # one sash: nothing to divide
    assert finestre._mullion(window(myhouse, tipo="sc", leaves=2, mw=0.04)) == 0.0
    assert finestre._flanges(window(myhouse, mw=0.04, mf1=0.01, mf2=0.01, mc=0.0)) == (0.0, 0.0, 0.0)
    assert finestre.validate(window(myhouse, mw=0.04, mc=0.08)) is not None       # channel deeper than the sash
    assert finestre.validate(window(myhouse, W=0.70, leaves=4, mw=0.10)) is not None


def test_dialog_returns_and_enables_mullion(myhouse, monkeypatch):
    from myhouse import _imperial, finestre
    from conftest import _window
    monkeypatch.setattr(_imperial, "_setting", "metric")
    seen = {}

    def fake_exec(dlg):
        dlg.show()
        r = rows(dlg)
        web, front = r[label("Montante: spessore dell'anima (0 = nessuno) (m)")], r[label("Montante: spessore dell'aletta anteriore (m)")]
        leaves = r[label("Ante")]
        seen["one"] = web.isEnabled()
        leaves.setCurrentIndex(leaves.findData(3))
        seen["three"] = (web.isEnabled(), front.isEnabled())
        web.setValue(0.04)
        seen["web"] = front.isEnabled()
        dlg.close()
        return QDialog.Accepted
    monkeypatch.setattr(QDialog, "exec", fake_exec)
    cur = dict(finestre._params(), W=2.40, H=1.40, sill=0.9, leaves=1, fw=0.06, fd=0.07, sw=0.05)
    p = finestre.ask_params(_window(), cur, "Window", "Place")
    assert seen == {"one": False, "three": (True, False), "web": True}
    assert p["leaves"] == 3 and p["mw"] == pytest.approx(0.04) and p["mc"] == pytest.approx(0.02)


def test_space_cycles_left_middle_right(myhouse):
    from myhouse import finestre

    class S:
        flip, mid, level = False, False, None
    seen = []
    for _ in range(4):
        seen.append((S.flip, S.mid, finestre.edge_word(S), finestre.edge_word(S, True)))
        finestre.next_edge(S)
    assert [s[:2] for s in seen] == [(False, False), (False, True), (True, False), (False, False)]
    assert [s[2] for s in seen[:3]] == ["left", "middle", "right"]
    assert [s[3] for s in seen[:3]] == ["LEFT", "CENTER", "RIGHT"]


def test_middle_holds_the_unit_by_its_centre(viewport):
    from PySide6.QtGui import QVector3D
    from myhouse import finestre, muri, porte
    scene = viewport.scene
    muri.build_walls(scene, [(0., 0.), (6., 0.)], False, 0.30, 2.7, 0.0, "W")
    cursor = QVector3D(3., 0.1, 0.)

    class S:
        flip, mid, level = False, False, None
    left = finestre.place_edge(scene, cursor, S, 1.20)
    S.mid = True
    middle = finestre.place_edge(scene, cursor, S, 1.20)
    S.mid, S.flip = False, True
    right = finestre.place_edge(scene, cursor, S, 1.20)

    def span(place):
        (ux, _uy), _n = finestre._axes(place)
        a = place["o"][0]
        return tuple(sorted((a, a + ux * 1.20)))
    assert span(left) == pytest.approx((3.0, 4.2))
    assert span(middle) == pytest.approx((2.4, 3.6))
    assert span(right) == pytest.approx((1.8, 3.0))          # 1.4's flip, unchanged
    assert left["flip"] is False and middle["flip"] is False and right["flip"] is True


def test_us_standard_sizes_table(myhouse):
    from myhouse import finestre
    hung = finestre.standard_sizes("hung")
    assert len(hung) == 9 * 12 and (32, 62) in hung
    assert (24, 48) not in finestre.standard_sizes("sliding") and (24, 42) in finestre.standard_sizes("sliding")
    assert finestre.standard_sizes("picture") == [(36, 24), (60, 36), (72, 48), (48, 60)]
    assert finestre.standard_sizes("") == [] and finestre.style_label("") == ""
    assert finestre.size_code(32, 62) == "2852" and finestre.size_code(24, 46) == "20310"
    assert finestre.style_label("casement") == "Casement"


@pytest.mark.parametrize("mode,shown", [("imperial", True), ("metric", False)])
def test_dialog_us_sizes_only_in_feet_and_inches(myhouse, monkeypatch, mode, shown):
    from myhouse import _imperial, finestre
    from conftest import _window
    monkeypatch.setattr(_imperial, "_setting", mode)
    seen = {}

    def fake_exec(dlg):
        dlg.show()
        r = rows(dlg)
        style, size = r.get(label("Misure standard USA: tipo")), r.get(label("Misure standard USA: misura"))
        seen["rows"] = style is not None and size is not None
        if style is not None:
            style.setCurrentIndex(style.findData("hung"))
            size.setCurrentIndex(size.findText(finestre.size_label(32, 62)))
            wide = next(v for k, v in r.items() if k.startswith(label("Larghezza totale (W) (m)")[:12]))
            seen["w"] = wide.value()
            wide.setValue(1.0)                          # a size that is not in the table
            seen["custom"] = size.currentIndex()
            size.setCurrentIndex(size.findText(finestre.size_label(32, 62)))
        dlg.close()
        return QDialog.Accepted
    monkeypatch.setattr(QDialog, "exec", fake_exec)
    cur = dict(finestre._params(), W=1.20, H=1.40, sill=0.9, leaves=1, fw=0.06, fd=0.07, sw=0.05, style="")
    p = finestre.ask_params(_window(), cur, "Window", "Place")
    assert seen["rows"] is shown
    if shown:
        assert seen["w"] == pytest.approx(32 * 0.0254) and seen["custom"] == 0
        assert (p["style"], p["W"], p["H"]) == ("hung", pytest.approx(32 * 0.0254), pytest.approx(62 * 0.0254))
    else:
        assert p["style"] == "" and p["W"] == pytest.approx(1.20)
