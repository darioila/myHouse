import math

import pytest

L_SHAPE = [(0., 0.), (8., 0.), (8., 4.), (4., 4.), (4., 7.), (0., 7.)]


def test_solver_hip_roof_on_a_rectangle():
    from myhouse import _tetto_auto
    pts, lines, hs = _tetto_auto.solve([(0., 0.), (8., 0.), (8., 4.), (0., 4.)], (), 0.5)
    assert len(pts) == 4 and len(lines) == 5                 # four hips and the ridge
    assert max(h[2] for h in hs) == pytest.approx(1.0)        # half the 4 m span, at 1 in 2


def test_solver_gable_and_inside_corner():
    from myhouse import _tetto_auto
    pts, lines, hs = _tetto_auto.solve([(0., 0.), (8., 0.), (8., 4.), (0., 4.)], {1, 3}, 0.5)
    assert len(pts) == 6 and len(lines) == 1                  # the ridge runs gable to gable
    pts, lines, hs = _tetto_auto.solve(L_SHAPE, (), 1.0)       # a valley at the inside corner
    assert any(a == pytest.approx((4., 4.)) or b == pytest.approx((4., 4.)) for a, b in lines)
    with pytest.raises(_tetto_auto.RoofError):
        _tetto_auto.solve(L_SHAPE, set(range(6)), 1.0)         # nothing slopes


def test_pitch_text_and_parse(myhouse):
    from myhouse import tetto
    assert tetto.parse_pitch("30°") == pytest.approx(30.)
    assert tetto.parse_pitch("6/12") == pytest.approx(math.degrees(math.atan2(6, 12)))
    assert tetto.parse_pitch("100%") == pytest.approx(45.)
    assert tetto.parse_pitch("nonsense") is None and tetto.parse_pitch("89°") is None and tetto.parse_pitch("1/0") is None
    assert tetto.parse_pitch(tetto.pitch_text(22.5)) == pytest.approx(22.5)


def test_footprint_is_the_outer_face_of_the_walls(viewport):
    from myhouse import muri, solaio
    scene = viewport.scene
    muri.build_walls(scene, [(0., 0.), (6., 0.), (6., 4.), (0., 4.)], True, 0.30, 2.7, 0.0, "W", align="center")
    poly = solaio.find_footprint(scene, 3., 2.)
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    assert (min(xs), max(xs), min(ys), max(ys)) == pytest.approx((-.15, 6.15, -.15, 4.15), abs=2e-3)
    assert solaio.find_footprint(type(scene)()) is None


def test_tool_computes_and_creates_the_roof(viewport, monkeypatch):
    from myhouse import tetto
    tool = tetto.TettoTool()
    tool._scene = viewport.scene
    tool.points = list(L_SHAPE)
    tool.phase = "lines"
    monkeypatch.setattr(tetto.QInputDialog, "getText", staticmethod(lambda *a, **k: ("45°", True)))
    tool._auto_start(viewport)
    assert tool.phase == "auto" and tool.auto["gables"] == set()
    before = dict(tool.heights)
    tool.auto["gables"] ^= {0}                                  # the 8 m side becomes a gable end
    assert tool._auto_solve(viewport) and tool.heights != before
    n = len(viewport.scene.groups)
    tool._commit(viewport)
    roofs = [g for g in viewport.scene.groups if tetto.roof_data(g)]
    assert len(viewport.scene.groups) == n + 1 and len(roofs) == 1
    assert tetto.roof_data(roofs[0])["rise"] > 1.0
