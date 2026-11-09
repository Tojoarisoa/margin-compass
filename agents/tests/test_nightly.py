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
            ('F2','cost',DATE '2026-10-05','closed',99.0::decimal(18,6),5.0),
            ('F1','cost',DATE '2026-10-25','open',1.0::decimal(18,6),2.0))
            v(feature_id, metric, start_date, status, impact_usd_per_day, peak_ratio)""").write_parquet(str(gold / "fct_margin_leaks.parquet"))
    return tmp_path


def test_ranks_open_leaks_and_losing_tenants(tmp_path):
    acts = nightly.review(_gold(tmp_path) / "gold", "r1")
    assert {a.target for a in acts} == {"F4/cost", "F1/cost", "bc-t0002", "bc-t0003"}  # closed leak and profitable tenant excluded
    assert [a.score for a in acts] == sorted((a.score for a in acts), reverse=True)
    top = acts[0]
    assert top.target == "F4/cost" and top.impact_usd_month == Decimal("600.00") and top.score == Decimal("240.00")
    t2 = next(a for a in acts if a.target == "bc-t0002")
    assert t2.impact_usd_month == Decimal("300.00") and t2.approver == "revops_lead" and t2.status == "proposed"


def test_write_is_deterministic_and_brief_copies_figures(tmp_path):
    root = _gold(tmp_path)
    assert nightly.write(root, "r1") == ["publish/latest/margin_brief.json"]
    first = pq.read_table(root / "gold" / "fct_actions.parquet").to_pylist()
    nightly.write(root, "r1")
    assert pq.read_table(root / "gold" / "fct_actions.parquet").to_pylist() == first
    brief = json.loads((root / "publish" / "latest" / "margin_brief.json").read_text())
    assert brief["action_count"] == 4 and brief["llm_calls"] == 0
    assert brief["total_impact_usd_month"] == "$960.00" and brief["top_actions"][0]["impact_usd_month"] == "$600.00"


def test_missing_marts_give_an_empty_brief(tmp_path):
    (tmp_path / "gold").mkdir()
    nightly.write(tmp_path, "r0")
    brief = json.loads((tmp_path / "publish" / "latest" / "margin_brief.json").read_text())
    assert brief["action_count"] == 0 and brief["headline"].startswith("No margin")
