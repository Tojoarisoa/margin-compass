from dataclasses import replace
from datetime import date, datetime, timedelta

from booncore_sim.m2_telemetry import TelemetryRow
from booncore_sim.m5_effects import Approval, lag_days
from booncore_sim.m5_realized import MEASUREMENT_WINDOW_DAYS, realized_by_action

A = Approval("act-1", "ACT-1", "F4/cost", date(2026, 3, 1))


def _rows(n=120):
    base = TelemetryRow(datetime(2026, 2, 1), "day", "t1", "F4", "provider_a", "a-frontier", "chat", False,
                        50, 100000, 20000, 0, 0)
    return [replace(base, usage_ts=datetime(2026, 2, 1) + timedelta(days=i), tenant_id=f"t{j}")
            for i in range(n) for j in range(5)]


def test_no_approvals_no_rows():
    assert realized_by_action(_rows(), [], 42) == []


def test_batch_shift_saves_money_only_after_approval_and_window_labels():
    out = realized_by_action(_rows(), [A], 42)
    assert out and all(r.day >= A.approved_on for r in out)
    assert all(r.saved_usd > 0 for r in out)
    cutoff = A.approved_on + timedelta(days=MEASUREMENT_WINDOW_DAYS)
    assert all((r.status == "realized") == (r.day >= cutoff) for r in out)


def test_deterministic():
    assert realized_by_action(_rows(), [A], 7) == realized_by_action(_rows(), [A], 7)


def test_write_realized(tmp_path):
    import pyarrow.parquet as pq

    from booncore_sim.m2_writer import write_realized

    assert write_realized(tmp_path, 42, _rows(), [], None, "2026-02") == []
    files = write_realized(tmp_path, 42, _rows(), [A], None, "2026-02")
    assert files[0]["path"] == "s5_realized/month=2026-02/realized_cost.parquet"
    t = pq.read_table(tmp_path / files[0]["path"])
    assert t.num_rows == files[0]["rows"] > 0 and {"action_id", "saved_usd", "status"} <= set(t.column_names)


def test_write_month_lands_realized_only_with_approvals(tmp_path, monkeypatch):
    """M5-04: a backfill month chunk (mode `month`) writes the month's realized effect from its baseline rows, and
    the telemetry it writes carries the approvals. Without approvals there is no realized file."""
    import pyarrow.parquet as pq

    from booncore_sim import m2_outcomes, m2_writer

    monkeypatch.setattr(m2_writer, "patterned_month", lambda seed, tenants, month, approvals=None: (_rows(), _rows()[:1]))
    monkeypatch.setattr(m2_outcomes, "generate_month", lambda seed, tenants, month: (_rows()[:1], _rows()[:1]))
    plain = m2_writer.write_month(tmp_path / "plain", 42, [], 11)
    assert not any(f["path"].startswith("s5_realized/") for f in plain)
    files = m2_writer.write_month(tmp_path / "approved", 42, [], 11, [A])
    real = [f for f in files if f["path"].startswith("s5_realized/")]
    assert len(real) == 1 and real[0]["path"].startswith("s5_realized/month=")
    t = pq.read_table(tmp_path / "approved" / real[0]["path"]).to_pylist()
    assert [(r["action_id"], r["saved_usd"]) for r in t] == [
        (r.action_id, r.saved_usd) for r in realized_by_action(_rows(), [A], 42)]
    tel = tmp_path / "approved" / next(f["path"] for f in files if f["path"].endswith("/telemetry.parquet"))
    assert sum(pq.read_table(tel).column("is_batch").to_pylist()) > 0  # ACT-1 shifted rows to batch


def test_churn_loses_revenue_only_from_churn_day():
    from decimal import Decimal
    from types import SimpleNamespace

    from booncore_sim.m5_effects import churn_day

    t = SimpleNamespace(tenant_id="t1", arr_usd=Decimal("36500"), discount_pct=Decimal("0.10"))
    cd = None
    for n in range(500):
        a3 = Approval(f"act3-{n}", "ACT-3", "t1/cap", date(2026, 3, 1))
        cd = churn_day(42, a3)
        if cd is not None:
            break
    assert cd is not None
    out = realized_by_action(_rows(), [a3], 42, [t])
    assert all((r.revenue_delta_usd < 0) == (r.day >= cd) for r in out)
    assert {r.revenue_delta_usd for r in out if r.day >= cd} == {-90.0}  # 36500 * 0.9 / 365
    assert all(r.revenue_delta_usd == 0 for r in realized_by_action(_rows(), [a3], 42))


def test_act2_plan_target_realizes_savings_for_that_plan():
    from decimal import Decimal
    from types import SimpleNamespace

    a2 = Approval("act2-plan", "ACT-2", "plan/growth", date(2026, 3, 1))
    ts = [SimpleNamespace(tenant_id=f"t{i}", plan="growth" if i < 2 else "starter", arr_usd=Decimal("36500"),
                          ai_addon_arr_usd=Decimal("3650"), discount_pct=Decimal("0")) for i in range(5)]
    out = realized_by_action(_rows(), [a2], 42, ts)
    assert out and all(r.saved_usd >= 0 for r in out) and any(r.saved_usd > 0 for r in out)
    start = a2.approved_on + timedelta(days=lag_days(42, a2))
    # Add-on price +10% on the two growth tenants: 2 * 3650 * 0.10 / 365 = $2.00 a day from approval plus lag.
    assert {r.revenue_delta_usd for r in out if r.day >= start} == {2.0}
    assert all(r.revenue_delta_usd == 0 for r in out if r.day < start)
    assert realized_by_action(_rows(), [a2], 42) == []  # without tenants the plan is unknown
