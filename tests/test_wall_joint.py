import pytest


def area(corners):
    aL, aR, bL, bR = corners
    ring = [aL, bL, bR, aR]
    return abs(sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(ring, ring[1:] + ring[:1]))) / 2


@pytest.fixture
def corner(viewport):
    """Two walls in one run meeting at (4, 0): 4 m along X, then 3 m along Y."""
    from myhouse import muri
    scene = viewport.scene
    muri.build_walls(scene, [(0., 0.), (4., 0.), (4., 3.)], False, 0.30, 2.7, 0.0, "W")
    w1, w2 = [g for g in scene.groups if muri.wall_data(g)]
    return scene, w1, w2


def corners(g):
    from myhouse import muri
    return muri.wall_corners(muri.wall_data(g))


def test_partner_is_found_at_the_shared_corner_only(corner):
    from myhouse import giunti
    scene, w1, w2 = corner
    assert giunti.joint_partner(scene, w1, "b") == (w2, "a")
    assert giunti.joint_partner(scene, w2, "a") == (w1, "b")
    assert giunti.joint_partner(scene, w1, "a") is None and giunti.joint_partner(scene, w2, "b") is None


def test_butt_joint_squares_both_ends_and_keeps_the_plan_area(corner):
    from myhouse import giunti, muri
    scene, w1, w2 = corner
    mitre = corners(w1), corners(w2)
    total = area(mitre[0]) + area(mitre[1])
    giunti.set_joint(scene, w1, "b", "through")
    assert (muri.wall_data(w1)["jb"], muri.wall_data(w2)["ja"]) == ("through", "butt")
    c1, c2 = corners(w1), corners(w2)
    assert c1[2][0] == pytest.approx(c1[3][0])                 # w1 ends square, across its own axis
    assert c2[0][1] == pytest.approx(c2[1][1])                 # w2 ends square against w1's face
    assert area(c1) > area(mitre[0]) and area(c2) < area(mitre[1])
    assert area(c1) + area(c2) == pytest.approx(total)          # no gap, no overlap
    assert c1[0] == pytest.approx(mitre[0][0]) and c2[3] == pytest.approx(mitre[1][3])   # far ends untouched


def test_click_cycle_through_butt_mitre(corner):
    from myhouse import giunti, muri
    scene, w1, w2 = corner
    mitre = corners(w1), corners(w2)
    seen = []
    for _ in range(3):
        kind = giunti.next_joint(w1, "b")
        giunti.set_joint(scene, w1, "b", kind)
        seen.append((muri.wall_data(w1).get("jb"), muri.wall_data(w2).get("ja")))
    assert seen == [("through", "butt"), ("butt", "through"), (None, None)]
    for got, want in zip(corners(w1) + corners(w2), mitre[0] + mitre[1]):
        assert got == pytest.approx(want)


def test_walls_of_different_thickness_joined_without_a_run(viewport):
    from myhouse import giunti, muri
    scene = viewport.scene
    muri.build_walls(scene, [(0., 0.), (4., 0.)], False, 0.30, 2.7, 0.0, "A")
    muri.build_walls(scene, [(4., 0.), (4., 3.)], False, 0.15, 2.7, 0.0, "B")
    w1, w2 = [g for g in scene.groups if muri.wall_data(g)]
    assert giunti.joint_partner(scene, w1, "b") is None                 # not joined yet
    # as Wall joining leaves them: each knows the other's far end and thickness, no shared run
    muri.rebuild_wall(w1, 0.30, 2.7, {"next": [4., 3.], "nxth": 0.15, "chain": None})
    muri.rebuild_wall(w2, 0.15, 2.7, {"prev": [0., 0.], "pth": 0.30, "chain": None})
    assert giunti.joint_partner(scene, w1, "b") == (w2, "a")
    total = area(corners(w1)) + area(corners(w2))
    giunti.set_joint(scene, w2, "a", "through")
    assert area(corners(w1)) + area(corners(w2)) == pytest.approx(total)
    assert muri.wall_data(w1)["jb"] == "butt"


def test_bonded_corner_is_released_and_split_drops_the_joint(corner):
    from myhouse import dividi, giunti, muri
    scene, w1, w2 = corner
    d = muri.wall_data(w1)
    aL, aR, bL, bR = muri.wall_corners(d)
    muri.rebuild_wall(w1, d["th"], d["h"], {"jn": {"th": d["th"], "al": d["align"], "bL": list(bL), "bR": list(bR), "aL": list(aL)}})
    giunti.set_joint(scene, w1, "b", "through")
    assert set(muri.wall_data(w1)["jn"]) == {"th", "al", "aL"}          # the other end's bond stays
    half = dividi.split(scene, w1, 2.0)
    assert "jb" not in muri.wall_data(w1) and muri.wall_data(half)["jb"] == "through"
    with pytest.raises(ValueError):
        giunti.set_joint(scene, w1, "a", "through")                    # a free end has no joint
