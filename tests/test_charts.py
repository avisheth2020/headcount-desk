"""The chart geometry, checked by hand."""

from app import charts


def test_sparkline_runs_edge_to_edge_and_marks_the_last_point():
    s = charts.sparkline([10, 20, 15], width=100, height=20, pad=0)
    assert s["line"] == "M0.0 20.0 L50.0 0.0 L100.0 10.0"
    assert (s["x"], s["y"]) == (100.0, 10.0)
    assert (s["first"], s["last"]) == (10.0, 15.0)


def test_sparkline_needs_two_points_and_survives_a_flat_line():
    assert charts.sparkline([5]) is None and charts.sparkline([]) is None
    assert charts.sparkline([7, 7, 7]) is not None


def test_variance_is_centered_on_100():
    under = charts.variance(98)        # 2 points under, on a 10-point scale
    assert under == {"left": 30.0, "width": 20.0, "over": False, "clipped": False}
    over = charts.variance(102.5)
    assert over == {"left": 50.0, "width": 25.0, "over": True, "clipped": False}


def test_variance_clips_to_the_scale_and_says_so():
    assert charts.variance(40)["left"] == 0 and charts.variance(40)["clipped"]
    assert charts.variance(130)["width"] == 50 and charts.variance(130)["clipped"]
    assert charts.variance(None) is None


def test_share_bars_rank_largest_first_and_ignore_negatives():
    rows = charts.share_bars([{"n": 5}, {"n": 20}, {"n": -3}], "n")
    assert [r["n"] for r in rows] == [20, 5, -3]
    assert [r["bar"] for r in rows] == [100.0, 25.0, 0.0]
