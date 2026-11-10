from dataclasses import replace
from datetime import date, datetime, timedelta

from booncore_sim.m2_telemetry import TelemetryRow
from booncore_sim.m5_effects import RAMP_DAYS, Approval, apply_act1, lag_days, share

A = Approval("act-1", "ACT-1", "F4/cost", date(2026, 3, 1))


def _rows(n=400):
    base = TelemetryRow(datetime(2026, 2, 1), "day", "t1", "F4", "p", "m", "chat", False, 10, 1000, 200, 0, 0)
    return [replace(base, usage_ts=datetime(2026, 2, 1) + timedelta(days=i), tenant_id=f"t{i % 5}") for i in range(n)]


def test_no_effect_before_approval_plus_lag_and_without_approvals():
    rows = _rows()
    assert apply_act1(rows, [], 42) is rows
    out = apply_act1(rows, [A], 42)
    start = A.approved_on + timedelta(days=lag_days(42, A))
    assert all(o == r for o, r in zip(out, rows, strict=True) if o.usage_ts.date() < start)


def test_ramp_is_partial_bounded_and_deterministic():
    assert share(42, A, A.approved_on) == 0.0
    late = A.approved_on + timedelta(days=lag_days(42, A) + RAMP_DAYS + 30)
    assert 0.60 <= share(42, A, late) <= 0.95
    out = apply_act1(_rows(), [A], 42)
    assert out == apply_act1(_rows(), [A], 42)
    tail = [o for o in out if o.usage_ts.date() >= late]
    frac = sum(o.is_batch for o in tail) / len(tail)
    assert 0.4 < frac < 1.0
    assert all(o.feature_id == "F4" for o in out)


def test_other_features_and_action_types_are_untouched():
    rows = [replace(r, feature_id="F1") for r in _rows(50)]
    assert apply_act1(rows, [A], 42) == rows
    assert apply_act1(_rows(50), [replace(A, action_type="ACT-3")], 42) == _rows(50)
