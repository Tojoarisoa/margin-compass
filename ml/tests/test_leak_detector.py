"""M3-02 step 1: unit-cost shift detector and EV-03 scoring."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from mc_ml.leak_detector.detect import detect
from mc_ml.leak_detector.score import Label, score

START = date(2025, 8, 1)
PATTERN = (10, 12, 11, 13, 12, 3, 2)


def series(n, noise=0.03, seed=0, shifts=()):
    rng = np.random.default_rng(seed)
    vals = []
    for i in range(n):
        v = PATTERN[i % 7] * float(rng.normal(1, noise))
        for s, e, f in shifts:
            if s <= i <= e:
                v *= f
        vals.append(v)
    return [START + timedelta(days=i) for i in range(n)], vals


def test_quiet_seasonal_series_raises_no_alert():
    d, v = series(120)
    assert detect(d, v) == []


def test_step_change_is_found_within_a_day_with_impact():
    d, v = series(120, shifts=[(60, 119, 1.4)])
    alerts = detect(d, v)
    assert len(alerts) == 1
    a = alerts[0]
    assert a.start == d[60] and (a.detected - d[60]).days <= 1 and a.end is not None  # re-baselined after max_open days
    expected = float(np.mean([PATTERN[i % 7] * 0.4 for i in range(60, 120)]))
    assert abs(a.impact_per_day - expected) / expected < 0.15


def test_bounded_spike_opens_and_closes():
    d, v = series(120, shifts=[(60, 68, 3.0)])
    (a,) = detect(d, v)
    assert a.start == d[60] and a.end == d[68]


def test_single_day_blip_is_ignored():
    d, v = series(120, shifts=[(60, 60, 2.0)])
    assert detect(d, v) == []


def test_score_precision_recall_mttd():
    d, v = series(150, shifts=[(60, 89, 1.4), (110, 118, 3.0)])
    alerts = detect(d, v)
    labels = [Label("PT-A", d[60], d[89]), Label("PT-B", d[110], d[118])]
    r = score(alerts, labels)
    assert r["recall"] == 1.0 and r["precision"] == 1.0 and r["mttd_days"] <= 1 and r["passed"]


def test_score_flags_false_positive_and_miss():
    d, v = series(120, shifts=[(60, 119, 1.4)])
    r = score(detect(d, v), [Label("PT-X", d[20], d[25])])
    assert r["recall"] == 0.0 and r["precision"] == 0.0 and not r["passed"]


def test_vectorised_baseline_matches_scalar():
    import numpy as np

    from mc_ml.leak_detector.detect import _baseline, _sigma, baseline_sigma
    rng = np.random.default_rng(3)
    x = np.maximum(rng.normal(100, 8, 120), 0)
    x[:10] = 0
    base, sig = baseline_sigma(x, 4)
    for t in range(28, 120):
        assert abs(_baseline(x, t, 4) - base[t]) < 1e-9 and abs(_sigma(x, t, 4) - sig[t]) < 1e-9


def test_long_shift_is_rebaselined_so_a_second_shift_alerts():
    from datetime import date, timedelta

    from mc_ml.leak_detector.detect import Params, detect
    days = [date(2025, 1, 1) + timedelta(i) for i in range(160)]
    x = [10.0] * 40 + [14.0] * 60 + [20.0] * 60
    alerts = detect(days, x, Params(min_rel=0.1, k=4))
    assert [a.start for a in alerts] == [days[40], days[100]] and alerts[0].end is not None
