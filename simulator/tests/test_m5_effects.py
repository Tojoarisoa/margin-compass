import json
from dataclasses import replace
from datetime import date, datetime, timedelta

from booncore_sim.m2_telemetry import TelemetryRow
from booncore_sim.m5_effects import (
    RAMP_DAYS,
    Approval,
    apply_act1,
    apply_act2_act3,
    apply_effects,
    churn_day,
    lag_days,
    load_approvals,
    share,
)

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


def test_act2_cuts_only_the_feature_after_lag_and_is_deterministic():
    a = Approval("act-2", "ACT-2", "F4/price", date(2026, 3, 1))
    rows = _rows()
    out = apply_act2_act3(rows, [a], 42)
    assert out == apply_act2_act3(rows, [a], 42)
    start = a.approved_on + timedelta(days=lag_days(42, a))
    assert all(o == r for o, r in zip(out, rows, strict=True) if o.usage_ts.date() < start)
    assert out[-1].request_count < rows[-1].request_count
    other = [replace(r, feature_id="F1") for r in rows]
    assert apply_act2_act3(other, [a], 42) == other


def test_act3_hits_one_tenant_and_may_churn():
    assert apply_act2_act3(_rows(), [], 42) == _rows()
    rows = _rows()
    churned = [i for i in range(300) if churn_day(i, Approval("c", "ACT-3", "t1/cap", date(2026, 3, 1)))]
    assert 0 < len(churned) < 60  # about 6%
    seed = churned[0]
    a = Approval("c", "ACT-3", "t1/cap", date(2026, 3, 1))
    out = apply_act2_act3(rows, [a], seed)
    assert all(o.tenant_id == "t1" for o in out if o not in rows)
    assert not [o for o in out if o.tenant_id == "t1" and o.usage_ts.date() >= churn_day(seed, a)]
    assert [o for o in out if o.tenant_id == "t2"] == [r for r in rows if r.tenant_id == "t2"]


def test_apply_effects_without_approvals_is_identity():
    rows = _rows(20)
    assert apply_effects(rows, [], 42) is rows


def test_load_approvals(tmp_path):
    assert load_approvals(tmp_path / "missing.jsonl") == []
    f = tmp_path / "approvals.jsonl"
    f.write_text(
        '{"action_id":"a1","action_type":"ACT-1","target":"F4/cost","decision":"approved","decided_at":"2026-03-01T10:00:00Z"}\n'
        '{"action_id":"a2","action_type":"ACT-2","target":"F4/price","decision":"rejected","decided_at":"2026-03-01"}\n'
        '{"action_id":"a3","action_type":"ACT-1","target":"F1/cost","decision":"approved","decided_at":"2026-03-02"}\n'
        '{"action_id":"a3","action_type":"ACT-1","target":"F1/cost","decision":"rejected","decided_at":"2026-03-05"}\n'
    )
    assert load_approvals(f) == [Approval("a1", "ACT-1", "F4/cost", date(2026, 3, 1))]


def test_window_mapping_places_decisions_60_days_before_the_data_date(tmp_path):
    """Owner 2026-11-26, option (b): decisions made after the window take effect from data date - 60 days, labeled."""
    from booncore_sim.m2_tenants import WINDOW_END
    from booncore_sim.m5_effects import DECISION_LEAD_DAYS, load_approvals

    f = tmp_path / "approvals.jsonl"
    f.write_text(json.dumps({"action_id": "act-1", "action_type": "ACT-3", "target": "bc-t0011/cap",
                             "decision": "approved", "decided_at": "2026-11-11T16:05:00Z"}) + "\n")
    [real] = load_approvals(f)
    assert real.approved_on == date(2026, 11, 11) and not real.simulated_date
    [mapped] = load_approvals(f, data_date=WINDOW_END)
    assert DECISION_LEAD_DAYS == 60 and mapped.approved_on == date(2026, 9, 1) and mapped.simulated_date
    assert mapped.approved_on > WINDOW_END - timedelta(days=90)  # inside the window, with room to realize


def test_act2_plan_target_cuts_only_tenants_on_that_plan():
    """The nightly review drafts ACT-2 as "plan/<plan>"; it must reach that plan's tenants (M5-04 step 4c-1)."""
    a = Approval("act-2p", "ACT-2", "plan/growth", date(2026, 3, 1))
    rows = _rows()
    plans = {"t0": "growth", "t1": "growth", "t2": "starter", "t3": "enterprise", "t4": "starter"}
    out = apply_act2_act3(rows, [a], 42, plans)
    assert out == apply_act2_act3(rows, [a], 42, plans)
    changed = {o.tenant_id for o, r in zip(out, rows, strict=True) if o != r}
    assert changed == {"t0", "t1"}
    start = a.approved_on + timedelta(days=lag_days(42, a))
    assert all(o == r for o, r in zip(out, rows, strict=True) if o.usage_ts.date() < start)
    assert apply_act2_act3(rows, [a], 42) == rows  # no plan map: nothing to target
    assert apply_effects(rows, [a], 42, plans) == out


def test_load_approvals_reads_notice_days_and_rejects_bad_values(tmp_path):
    import json

    import pytest

    from booncore_sim.m5_effects import effective_on
    f = tmp_path / "a.jsonl"
    rec = {"action_id": "a2", "action_type": "ACT-2", "target": "plan/growth", "decision": "approved",
           "decided_at": "2026-03-01T00:00:00Z", "notice_days": 14}
    f.write_text(json.dumps(rec) + "\n")
    [a] = load_approvals(f)
    assert a.notice_days == 14 and effective_on(a) == date(2026, 3, 15)
    for bad in (-1, 1.5, True, "7"):
        f.write_text(json.dumps({**rec, "notice_days": bad}) + "\n")
        with pytest.raises(ValueError):
            load_approvals(f)
