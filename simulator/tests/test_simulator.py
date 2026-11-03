"""M1-01 minimal BoonCore simulator (spec §11): shape, determinism, labels, revenue, safety."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from booncore_sim.catalog import PRICE_CATALOG_V1, token_cost_usd
from booncore_sim.cli import main, run
from booncore_sim.config import M1

CENT = Decimal("0.01")  # money is rounded half-up to the cent, like the generator

FILES = (
    "tenants/tenants.parquet",
    "s1_llm_telemetry/telemetry_daily.parquet",
    "s3_revenue/subscriptions.parquet",
    "s3_revenue/invoices.parquet",
    "s5_price_catalog/price_catalog.parquet",
    "labels/patterns.parquet",
)


@pytest.fixture(scope="module")
def out(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("m1")
    run("m1", None, d, run_id="test-run")
    return d


def rows(out: Path, rel: str) -> list[dict]:
    return pq.read_table(out / rel).to_pylist()


# --- Scope (spec §11) ------------------------------------------------------------------------
def test_window_is_90_days_from_2025_08_01_to_2025_10_29():
    assert (M1.start, M1.end, M1.days) == (date(2025, 8, 1), date(2025, 10, 29), 90)


def test_twenty_tenants_ten_imaging_mixed_plans(out):
    tenants = rows(out, "tenants/tenants.parquet")
    assert len(tenants) == 20
    assert sum(t["segment"] == "imaging" for t in tenants) == 10
    assert {t["plan"] for t in tenants} == {"starter", "growth", "enterprise"}
    assert len({t["tenant_id"] for t in tenants}) == 20


def test_telemetry_is_f1_only_two_tiers_inside_the_window(out):
    usage = rows(out, "s1_llm_telemetry/telemetry_daily.parquet")
    assert {r["feature_id"] for r in usage} == {"F1"}
    assert {r["gen_ai_request_model"] for r in usage} == {"a-small", "a-mid"}
    assert min(r["usage_date"] for r in usage) == M1.start
    assert max(r["usage_date"] for r in usage) == M1.end
    assert len(usage) <= 20 * 2 * 90  # day x tenant x model upper bound (PLAN.md §7.5)


def test_one_row_per_day_tenant_feature_model(out):
    usage = rows(out, "s1_llm_telemetry/telemetry_daily.parquet")
    keys = [(r["usage_date"], r["tenant_id"], r["feature_id"], r["gen_ai_request_model"]) for r in usage]
    assert len(keys) == len(set(keys))


def test_token_counts_are_consistent(out):
    for r in rows(out, "s1_llm_telemetry/telemetry_daily.parquet"):
        assert r["request_count"] > 0
        assert 0 <= r["gen_ai_usage_cache_read_input_tokens"] <= r["gen_ai_usage_input_tokens"]
        assert r["gen_ai_usage_output_tokens"] >= r["request_count"]
        assert 0 <= r["retry_count"] <= r["request_count"]


def test_weekend_volume_is_about_20_percent_of_weekdays(out):
    usage = rows(out, "s1_llm_telemetry/telemetry_daily.parquet")
    per_day: dict[date, int] = {}
    for r in usage:
        per_day[r["usage_date"]] = per_day.get(r["usage_date"], 0) + r["request_count"]
    weekday = [v for d, v in per_day.items() if d.weekday() < 5]
    weekend = [v for d, v in per_day.items() if d.weekday() >= 5]
    ratio = (sum(weekend) / len(weekend)) / (sum(weekday) / len(weekday))
    assert 0.15 < ratio < 0.25


# --- PT-01 prompt regression (spec §8) ---------------------------------------------------------
def test_pt01_raises_input_tokens_per_request_by_about_40_percent(out):
    usage = rows(out, "s1_llm_telemetry/telemetry_daily.parquet")

    def tokens_per_request(rs):
        return sum(r["gen_ai_usage_input_tokens"] for r in rs) / sum(r["request_count"] for r in rs)

    pre = [r for r in usage if M1.pt01_start - timedelta(days=21) <= r["usage_date"] < M1.pt01_start]
    post = [r for r in usage if M1.pt01_start <= r["usage_date"] < M1.pt01_start + timedelta(days=21)]
    assert 1.35 < tokens_per_request(post) / tokens_per_request(pre) < 1.45


def test_pt01_is_labeled_with_positive_impact(out):
    (label,) = rows(out, "labels/patterns.parquet")
    assert label["pattern_id"] == "PT-01"
    assert label["start_date"] == M1.pt01_start
    assert label["end_date"] is None
    assert label["magnitude"] == pytest.approx(0.40)
    assert label["expected_impact_usd_per_day"] > Decimal("0")


# --- Revenue (S3), exact to the cent ------------------------------------------------------------
def test_invoices_cover_three_months_with_two_lines_per_tenant(out):
    invoices = rows(out, "s3_revenue/invoices.parquet")
    assert len(invoices) == 20 * 3 * 2
    assert {i["billing_period_start"] for i in invoices} == {date(2025, 8, 1), date(2025, 9, 1), date(2025, 10, 1)}
    assert {i["line_type"] for i in invoices} == {"subscription", "ai_addon"}


def test_invoice_lines_match_contract_terms_to_the_cent(out):
    subs = {s["tenant_id"]: s for s in rows(out, "s3_revenue/subscriptions.parquet")}
    for i in rows(out, "s3_revenue/invoices.parquet"):
        s = subs[i["tenant_id"]]
        annual = s["ai_addon_arr_usd"] if i["line_type"] == "ai_addon" else s["arr_usd"] - s["ai_addon_arr_usd"]
        expected = (annual / 12 * (1 - s["discount_pct"])).quantize(CENT, ROUND_HALF_UP)
        assert i["amount_usd"] == expected
        assert i["amount_usd"].as_tuple().exponent == -2


def test_ai_addon_is_35_percent_of_arr(out):
    for s in rows(out, "s3_revenue/subscriptions.parquet"):
        assert s["ai_addon_arr_usd"] == (s["arr_usd"] * Decimal("0.35")).quantize(CENT, ROUND_HALF_UP)


# --- Price catalog (S5) ------------------------------------------------------------------------
def test_price_catalog_has_the_two_m1_models_with_cache_at_10_percent(out):
    catalog = {r["model_id"]: r for r in rows(out, "s5_price_catalog/price_catalog.parquet")}
    assert set(catalog) == {"a-small", "a-mid"}
    for r in catalog.values():
        assert r["cache_read_usd_per_mtok"] == pytest.approx(r["input_usd_per_mtok"] * 0.10)


def test_cached_tokens_are_not_double_counted():
    price = PRICE_CATALOG_V1["a-mid"]
    all_cached = token_cost_usd(price, input_tokens=1_000_000, cache_read_tokens=1_000_000, output_tokens=0)
    none_cached = token_cost_usd(price, input_tokens=1_000_000, cache_read_tokens=0, output_tokens=0)
    assert all_cached == pytest.approx(0.30) and none_cached == pytest.approx(3.00)
    with pytest.raises(ValueError):
        token_cost_usd(price, input_tokens=10, cache_read_tokens=11, output_tokens=0)


# --- Determinism, labeling, safety ---------------------------------------------------------
def test_same_seed_gives_byte_identical_files(out, tmp_path):
    run("m1", None, tmp_path, run_id="second-run")
    for rel in (*FILES, "manifest.json"):
        assert (out / rel).read_bytes() == (tmp_path / rel).read_bytes(), rel


def test_different_seed_gives_different_data(out, tmp_path):
    run("m1", 7, tmp_path, run_id="other-seed")
    assert (out / FILES[1]).read_bytes() != (tmp_path / FILES[1]).read_bytes()


def test_every_file_is_labeled_synthetic(out):
    for rel in FILES:
        metadata = pq.read_schema(out / rel).metadata
        assert metadata[b"synthetic"] == b"true", rel
        assert metadata[b"generator"] == b"booncore-simulator", rel
    assert json.loads((out / "manifest.json").read_text())["synthetic"] is True


def test_manifest_row_counts_and_hashes_match_files(out):
    import hashlib

    manifest = json.loads((out / "manifest.json").read_text())
    assert [f["path"] for f in manifest["files"]] == list(FILES)
    for f in manifest["files"]:
        assert pq.read_metadata(out / f["path"]).num_rows == f["rows"]
        assert hashlib.sha256((out / f["path"]).read_bytes()).hexdigest() == f["sha256"]


def test_no_prompt_or_response_content_columns(out):
    """AGENTS.md rule 16: metadata and token counts only."""
    forbidden = ("prompt", "response", "message", "content", "text", "body")
    for rel in FILES:
        for name in pq.read_schema(out / rel).names:
            assert not any(word in name for word in forbidden), f"{rel}: {name}"


def test_cli_logs_are_json_with_one_run_id(tmp_path, capsys):
    assert main(["--profile", "m1", "--out", str(tmp_path)]) == 0
    lines = [json.loads(line) for line in capsys.readouterr().err.strip().splitlines()]
    assert lines[0]["event"] == "simulation_started" and lines[-1]["event"] == "simulation_finished"
    assert len({line["run_id"] for line in lines}) == 1
    assert all(line["component"] == "simulator" for line in lines)
