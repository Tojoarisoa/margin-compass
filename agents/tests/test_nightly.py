import json
from datetime import date, timedelta
from decimal import Decimal

import duckdb
import pyarrow.parquet as pq

from mc_agents import nightly


def _gold(tmp_path, leaks=True):
    gold = tmp_path / "gold"
    gold.mkdir()
    start = date(2026, 10, 1)
    rows = [(start + timedelta(days=i), t, Decimal(r), Decimal(m)) for i in range(31)
            for t, r, m in (("bc-t0001", "100", "40"), ("bc-t0002", "50", "-10"), ("bc-t0003", "80", "-1"))]
    duckdb.sql("select * from (values " + ",".join(f"(DATE '{d}','{t}',{r},{m})" for d, t, r, m in rows)
               + ") v(margin_date, tenant_id, revenue_usd, margin_usd)").write_parquet(str(gold / "fct_m2_tenant_margin.parquet"))
    if leaks:
        duckdb.sql("""select * from (values ('F4','cost',DATE '2026-10-20','open',20.0::decimal(18,6),3.5),
            ('F2','cost',DATE '2026-10-05','closed',9.0::decimal(18,6),5.0),
            ('F1','cost',DATE '2026-10-25','open',1.0::decimal(18,6),2.0))
            v(feature_id, metric, start_date, status, impact_usd_per_day, peak_ratio)""").write_parquet(str(gold / "fct_margin_leaks.parquet"))
    return tmp_path


def test_ranks_open_leaks_and_losing_tenants(tmp_path):
    acts = nightly.review(_gold(tmp_path) / "gold", "r1")
    # F2 closed on 2026-10-05, within 28 days of the latest leak: drafted at low confidence; profitable tenant excluded
    assert {a.target for a in acts} == {"F4/cost", "F1/cost", "F2/cost", "bc-t0002", "bc-t0003"}
    assert [a.score for a in acts] == sorted((a.score for a in acts), reverse=True)
    top = acts[0]
    assert top.target == "F4/cost" and top.impact_usd_month == Decimal("600.00") and top.score == Decimal("240.00")
    t2 = next(a for a in acts if a.target == "bc-t0002")
    assert t2.impact_usd_month == Decimal("300.00") and t2.approver == "revops_lead" and t2.status == "proposed"


def test_write_is_deterministic_and_brief_copies_figures(tmp_path):
    root = _gold(tmp_path)
    assert nightly.write(root, "r1") == ["publish/latest/margin_brief.json", "publish/latest/actions.json"]
    first = pq.read_table(root / "gold" / "fct_actions.parquet").to_pylist()
    nightly.write(root, "r1")
    assert pq.read_table(root / "gold" / "fct_actions.parquet").to_pylist() == first
    brief = json.loads((root / "publish" / "latest" / "margin_brief.json").read_text())
    assert brief["action_count"] == 5 and "llm_calls" not in brief  # public surface: no call counts (AGENTS.md §6)
    assert brief["total_impact_usd_month"] == "$1,230.00" and brief["top_actions"][0]["impact_usd_month"] == "$600.00"


def test_queue_lists_every_action_with_role_and_risk(tmp_path):
    root = _gold(tmp_path)
    nightly.write(root, "r1")
    q = json.loads((root / "publish" / "latest" / "actions.json").read_text())
    assert q["schema_version"] == "actions.v0" and len(q["actions"]) == 5
    assert all(a["status"] == "proposed" and a["approver"] and a["risk"] and a["assumptions"] for a in q["actions"])
    assert q["actions"][0]["impact_usd_month"] == "$600.00"


def test_missing_marts_give_an_empty_brief(tmp_path):
    (tmp_path / "gold").mkdir()
    nightly.write(tmp_path, "r0")
    brief = json.loads((tmp_path / "publish" / "latest" / "margin_brief.json").read_text())
    assert brief["action_count"] == 0 and brief["headline"].startswith("No margin")


def _gold_trend(tmp_path):
    gold = tmp_path / "gold"
    gold.mkdir()
    start = date(2026, 9, 6)  # 56 days ending 2026-10-31
    vals = []
    for i in range(56):
        d = start + timedelta(days=i)
        late = i >= 28
        # t1: 40% -> 30% (falling, renews in 30 days); t2: steady 50%; t3: steady 20% (low, renews in 200 days)
        vals += [(d, "t1", 100, 30 if late else 40), (d, "t2", 100, 50), (d, "t3", 100, 20)]
    duckdb.sql("select * from (values " + ",".join(f"(DATE '{d}','{t}',{r},{m})" for d, t, r, m in vals)
               + ") v(margin_date, tenant_id, revenue_usd, margin_usd)").write_parquet(str(gold / "fct_m2_tenant_margin.parquet"))
    duckdb.sql("""select * from (values ('t1',DATE '2025-11-30',true),('t2',DATE '2025-11-30',true),
        ('t3',DATE '2025-05-19',true)) v(tenant_id, renewal_date, is_current)""").write_parquet(str(gold / "dim_tenant.parquet"))
    return gold


def test_deteriorating_margin_and_renewals(tmp_path):
    acts = {a.target: a for a in nightly.review(_gold_trend(tmp_path), "r1")}
    assert set(acts) == {"t1/margin-trend", "t1/renewal"}  # t2 healthy; t3 is low but renews in 200 days
    # 10 points of 2,800 revenue over 28 days, scaled to 30 days
    assert acts["t1/margin-trend"].impact_usd_month == Decimal("300.00")
    assert acts["t1/renewal"].approver == "revops_lead" and "30 days" in acts["t1/renewal"].title


def test_plan_below_target_drafts_a_pricing_action(tmp_path):
    root = _gold(tmp_path, leaks=False)
    duckdb.sql("select * from (values ('bc-t0001','pro',true,DATE '2020-01-01'),"
               "('bc-t0002','pro',true,DATE '2020-01-01'),('bc-t0003','ent',true,DATE '2020-01-01'))"
               " v(tenant_id, plan, is_current, renewal_date)").write_parquet(str(root / "gold" / "dim_tenant.parquet"))
    acts = nightly.review(root / "gold", "r1")
    plan = next(a for a in acts if a.action_type == "ACT-2")
    # pro: 28 days x (100+50) revenue = 4200, margin 28 x 30 = 840 -> 20%; gap 10 points -> 420 per 28 days -> 450/month
    assert plan.target == "plan/pro" and plan.impact_usd_month == Decimal("450.00")
    assert plan.approver == "pricing_committee" and plan.status == "proposed"
    assert not any(a.target == "plan/ent" for a in acts)  # one tenant only


def test_write_with_llm_adds_insights_and_memory(tmp_path):
    from mc_agents.llm import LLMResponse

    class Fake:
        def complete(self, req):
            return LLMResponse([{"text": "Check the latest release first."}], "end_turn", 300, 40)

    root = _gold(tmp_path)
    nightly.write(root, "r1", client=Fake())
    brief = json.loads((root / "publish" / "latest" / "margin_brief.json").read_text())
    assert all(a["insight"] == "Check the latest release first." for a in brief["top_actions"])
    assert (root / "memory" / "episodic.jsonl").read_text().count("\n") >= 5


def test_failing_llm_still_writes_plain_brief(tmp_path):
    class Boom:
        def complete(self, req):
            raise RuntimeError("down")

    root = _gold(tmp_path)
    nightly.write(root, "r1", client=Boom())
    brief = json.loads((root / "publish" / "latest" / "margin_brief.json").read_text())
    assert brief["action_count"] > 0 and all("insight" not in a for a in brief["top_actions"])


def test_cli_nightly_without_live_writes_brief(tmp_path, capsys):
    from mc_agents.cli import main
    root = _gold(tmp_path)
    assert main(["nightly", "--data-root", str(root), "--run-id", "r1"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["live"] is False and out["insights"] == 0 and out["actions"] > 0
