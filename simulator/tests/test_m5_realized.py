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


def test_run_m2_all_writes_realized_only_with_approvals(tmp_path, monkeypatch):
    """`run_m2` mode `all` passes the baseline telemetry to `write_realized`, and only when approvals exist."""
    from types import SimpleNamespace

    from booncore_sim import cli, m2_run, m2_writer

    calls = []
    run = SimpleNamespace(tenants=[], telemetry=_rows())
    monkeypatch.setattr(m2_run, "generate_patterned", lambda seed, approvals=None: run)
    for name in ("write_static", "write_focus", "write_revenue", "write_dimensions", "write_month"):
        monkeypatch.setattr(m2_writer, name, lambda *a, **k: [])
    monkeypatch.setattr(m2_writer, "write_manifest", lambda out, seed, files: {"files": []})
    monkeypatch.setattr(m2_writer, "write_realized", lambda out, seed, tel, appr: calls.append((tel, appr)) or [])
    cli.run_m2(42, tmp_path, "all", None)
    assert calls == []
    path = tmp_path / "approvals.jsonl"
    path.write_text('{"action_id": "A", "action_type": "ACT-1", "target": "F4/cost", "decision": "approved", "approver": "o", "rationale": "r", '
                    '"decided_at": "2026-01-01T00:00:00+00:00"}\n')
    cli.run_m2(42, tmp_path, "all", None, path)
    assert len(calls) == 1 and calls[0][0] is run.telemetry
