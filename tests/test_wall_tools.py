import math

import pytest
from PySide6.QtGui import QVector3D


@pytest.fixture
def walls(viewport):
    """An L of two walls, 4 m then 3 m, 0.3 thick."""
    from myhouse import muri
    scene = viewport.scene
    muri.build_walls(scene, [(0., 0.), (4., 0.), (4., 3.)], False, 0.30, 2.7, 0.0, "W")
    return scene, [g for g in scene.groups if muri.wall_data(g)]


def length(d):
    return math.hypot(d["b"][0] - d["a"][0], d["b"][1] - d["a"][1])


def test_stretch_free_end_and_corner(walls):
    from myhouse import allunga, muri
    scene, (w1, w2) = walls
    assert allunga.stretch(scene, w1, "a", 5.0) == 2          # free end: the next wall's mitre sees it
    assert muri.wall_data(w1)["a"] == pytest.approx([-1.0, 0.0])
    assert muri.wall_data(w2)["prev"] == pytest.approx([-1.0, 0.0]) and muri.wall_data(w2)["a"] == pytest.approx([4.0, 0.0])
    assert allunga.stretch(scene, w1, "b", 6.0) == 2          # the corner: the next wall follows
    d1, d2 = muri.wall_data(w1), muri.wall_data(w2)
    assert d1["b"] == pytest.approx([5.0, 0.0]) and d2["a"] == pytest.approx([5.0, 0.0])
    assert d2["prev"] == pytest.approx([-1.0, 0.0]) and d1["next"] == pytest.approx([4.0, 3.0])


def test_stretch_moves_niches_with_the_far_end(walls):
    from myhouse import allunga, muri
    scene, (w1, _w2) = walls
    muri.add_niche(w1, 1.0, 1.5, 0.5, 1.5, 0.1)
    allunga.stretch(scene, w1, "a", 5.0)                      # start moves back 1 m
    n = muri.wall_data(w1)["niches"][0]
    assert (n[0], n[1]) == pytest.approx((2.0, 2.5))
    allunga.stretch(scene, w1, "b", 4.5)                      # the other end: niches stay
    assert muri.wall_data(w1)["niches"][0][0] == pytest.approx(2.0)


def test_stretch_refuses_tapered_and_too_short(walls):
    from myhouse import allunga, muri
    scene, (w1, _w2) = walls
    with pytest.raises(ValueError):
        allunga.stretch(scene, w1, "a", 0.0)
    muri.build_walls(scene, [(10., 0.), (12., 0.)], False, 0.4, 2.7, 0.0, "T", thickness_end=0.2)
    taper = scene.groups[-1]
    with pytest.raises(ValueError):
        allunga.stretch(scene, taper, "b", 3.0)


def test_wall_group_finds_the_nearer_end(walls):
    from myhouse import allunga
    scene, (w1, _w2) = walls
    assert allunga.wall_group(scene, QVector3D(0.5, 0.0, 0.0)) == (w1, "a")
    assert allunga.wall_group(scene, QVector3D(3.5, 0.0, 0.0)) == (w1, "b")


def test_split_keeps_run_and_shares_out_niches(walls):
    from myhouse import dividi, muri
    scene, (w1, w2) = walls
    muri.add_niche(w1, 0.5, 1.0, 0.5, 1.5, 0.1)
    muri.add_niche(w1, 3.0, 3.5, 0.5, 1.5, 0.1)
    g2 = dividi.split(scene, w1, 2.5)
    d1, d2 = muri.wall_data(w1), muri.wall_data(g2)
    assert length(d1) == pytest.approx(2.5) and length(d2) == pytest.approx(1.5)
    assert d1["chain"] == d2["chain"] == muri.wall_data(w2)["chain"]
    assert d1["next"] == pytest.approx([4.0, 0.0]) and d2["prev"] == pytest.approx([0.0, 0.0])
    assert d2["next"] == pytest.approx([4.0, 3.0])            # the corner is still the second half's
    assert muri.wall_data(w2)["prev"] == pytest.approx([2.5, 0.0])
    assert [n[0] for n in d1["niches"]] == pytest.approx([0.5])
    assert [n[0] for n in d2["niches"]] == pytest.approx([0.5])   # 3.0 - 2.5
    assert scene.groups.index(g2) == scene.groups.index(w1) + 1
    with pytest.raises(ValueError):
        dividi.split(scene, w1, 0.0)


def test_adopt_box_becomes_a_wall(viewport):
    from core.group import Group
    from core.mesh import Mesh
    from myhouse import adotta, muri
    scene = viewport.scene
    w = adotta.wall_from_points([(x, y, z) for x in (1., 5.) for y in (2., 2.2) for z in (0., 2.5)])
    assert (w["th"], w["h"], w["z0"]) == pytest.approx((0.2, 2.5, 0.0))
    assert math.hypot(w["b"][0] - w["a"][0], w["b"][1] - w["a"][1]) == pytest.approx(4.0)
    with pytest.raises(ValueError):                               # an L in plan is refused
        adotta.wall_from_points([(0, 0, 0), (4, 0, 0), (4, 3, 0), (3.8, 3, 0), (3.8, .2, 0), (0, .2, 0),
                                 (0, 0, 2), (4, 0, 2), (4, 3, 2), (3.8, 3, 2), (3.8, .2, 2), (0, .2, 2)])


def test_ortho_snaps_in_45_degree_steps(myhouse, monkeypatch):
    from myhouse import muri
    tool = muri.MuriTool()
    tool.points = [QVector3D(1., 1., 0.)]
    monkeypatch.setattr(muri._Settings, "ortho", True)

    def snap(x, y):
        p = tool._ortho(QVector3D(x, y, 0.))
        return p.x(), p.y()
    assert snap(4., 1.2) == pytest.approx((4., 1.))             # along X, as plain ortho
    assert snap(1.3, 5.) == pytest.approx((1., 5.))             # along Y
    assert snap(4., 3.6) == pytest.approx((3.8, 3.8))           # the 45° diagonal
    assert snap(-1., 2.8) == pytest.approx((-0.9, 2.9))         # 135°
    monkeypatch.setattr(muri._Settings, "ortho", False)
    assert snap(4., 3.6) == pytest.approx((4., 3.6))
