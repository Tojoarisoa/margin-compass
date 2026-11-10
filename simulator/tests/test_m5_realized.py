from dataclasses import replace
from datetime import date, datetime, timedelta

from booncore_sim.m2_telemetry import TelemetryRow
from booncore_sim.m5_effects import Approval
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

    assert write_realized(tmp_path, 42, _rows(), []) == []
    files = write_realized(tmp_path, 42, _rows(), [A])
    t = pq.read_table(tmp_path / files[0]["path"])
    assert t.num_rows == files[0]["rows"] > 0 and {"action_id", "saved_usd", "status"} <= set(t.column_names)
