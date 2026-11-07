"""Stage 4 train step (M1-04): seasonal-naive AI COGS forecaster -> artifacts, registry, fct_forecasts.

Deterministic: the version id is a hash of the training data and parameters, so re-running on the
same data registers nothing new (idempotent) and reproduces the same artifacts byte for byte.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from .cogs_forecast.evaluate import CANDIDATES, compare
from .cogs_forecast.seasonal_naive import SEASON, backtest, fit
from .registry import ModelVersion, Registry, should_promote

log = logging.getLogger("mc_pipelines")

MODEL_NAME = "ai_cogs_forecaster"
HORIZON_DAYS = 30
HOLDOUT_DAYS = 28
FEATURE_SCOPE = "F1 only (M1)"
MONEY6 = pa.decimal128(18, 6)

FORECAST_SCHEMA = pa.schema([
    ("forecast_date", pa.date32()), ("target_date", pa.date32()), ("feature_id", pa.string()),
    ("metric", pa.string()), ("p10_usd", MONEY6), ("p50_usd", MONEY6), ("p90_usd", MONEY6),
    ("model_name", pa.string()), ("model_version", pa.string()), ("model_alias", pa.string()),
    ("feature_scope", pa.string()), ("run_id", pa.string()),
])


def _daily_cost_by_feature(gold: Path) -> tuple[dict[str, list[float]], list[date]]:
    usage = pq.read_table(gold / "fct_llm_usage_daily.parquet", columns=["usage_date", "feature_id", "llm_cost_usd"])
    kpis = pq.read_table(gold / "agg_exec_kpis.parquet", columns=["kpi_date"])
    start, end = pc.min(kpis["kpi_date"]).as_py(), pc.max(kpis["kpi_date"]).as_py()  # the simulated window
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    grouped = usage.group_by(["usage_date", "feature_id"]).aggregate([("llm_cost_usd", "sum")]).to_pylist()
    features = sorted({r["feature_id"] for r in grouped})
    totals = {(r["usage_date"], r["feature_id"]): float(r["llm_cost_usd_sum"]) for r in grouped}
    return {f: [round(totals.get((d, f), 0.0), 6) for d in days] for f in features}, days


def _card(version: str, days: list[date], metrics: dict, data_sha: str) -> str:
    rows = "\n".join(
        f"| {f} | {m['wape']} | {m['p10_p90_coverage']} |" for f, m in metrics["by_feature"].items()
    )
    multi = "\n".join(
        f"| {f} | {name} | {sc['wape']} | {sc['pinball']} | {sc['p10_p90_coverage']} |"
        for f, scores in metrics["multi_step"].items() if scores for name, sc in scores.items()
    ) or "| (history too short) | | | | |"
    return f"""# Model card: {MODEL_NAME} {version}

> **Synthetic data.** Trained on BoonCore's simulated usage; not a forecast of any real company.

- **Model:** seasonal naive (season = {SEASON} days): each day repeats the same weekday of the last observed week. P10/P90 scale it by the 10th/90th percentile of week-over-week ratios.
- **Purpose (M1-04 stub):** baseline AI COGS forecast per feature, {HORIZON_DAYS} days ahead, so the registry, the forecast mart, and the dashboard can be built end to end. The trained forecaster and the ETS baseline replace it in M3-01 (EV-02).
- **Training data:** `fct_llm_usage_daily`, daily LLM cost per feature, {days[0]} to {days[-1]} ({len(days)} days). Data SHA-256 `{data_sha}`.
- **Scope:** {FEATURE_SCOPE}.

## Backtest (rolling origin, one step ahead, last {HOLDOUT_DAYS} days)

| Feature | WAPE | P10–P90 coverage |
| --- | --- | --- |
{rows}

Blended WAPE: {metrics['wape']}.

## Baselines, {HORIZON_DAYS}-day horizon (rolling origin, 4 origins 7 days apart; EV-02 inputs)

| Feature | Method | WAPE | Pinball | P10–P90 coverage |
| --- | --- | --- | --- | --- |
{multi}

## Limitations

- Repeats last week, so level shifts (for example the PT-01 prompt regression) are learned only a week later, and trend or seasonality beyond the week is ignored.
- Intervals assume future week-over-week variation looks like the training window; with 80% nominal coverage expected, measured coverage is reported above.
- No covariates (price changes, tenant growth). Not for decisions beyond a walking-skeleton demo.
"""


def train_cogs_forecaster(gold: Path, models_dir: Path, registry: Registry, artifact_base_uri: str, run_id: str) -> dict:
    series, days = _daily_cost_by_feature(gold)
    params = {"model": "seasonal_naive", "season": SEASON, "horizon_days": HORIZON_DAYS, "holdout_days": HOLDOUT_DAYS,
              "multi_step": {"horizon": HORIZON_DAYS, "origins": 4, "step": 7, "baselines": ["seasonal_naive", "ets"]}}
    data_sha = hashlib.sha256(json.dumps({"days": [d.isoformat() for d in days], "series": series}, sort_keys=True).encode()).hexdigest()
    version = "sn-" + hashlib.sha256((data_sha + json.dumps(params, sort_keys=True)).encode()).hexdigest()[:12]

    multi_step = {}
    for feature, values in series.items():
        try:
            multi_step[feature] = compare(values, CANDIDATES, horizon=HORIZON_DAYS, origins=4, step=7)
        except ValueError:  # history too short for 4 origins of 30 days
            multi_step[feature] = None
    models, by_feature, rows = {}, {}, []
    weighted_err = weight = 0.0
    for feature, values in series.items():
        model = fit(days, values)
        bt = backtest(values, holdout_days=HOLDOUT_DAYS)
        models[feature] = model.to_dict()
        by_feature[feature] = bt
        actual = sum(values[-HOLDOUT_DAYS:])
        weighted_err += bt["wape"] * actual
        weight += actual
        for f in model.forecast(HORIZON_DAYS):
            rows.append({"forecast_date": model.last_date, "target_date": f["target_date"], "feature_id": feature,
                         "metric": "ai_cogs_usd", **{k + "_usd": Decimal(str(round(f[k], 6))) for k in ("p10", "p50", "p90")}})
    metrics = {"wape": round(weighted_err / weight, 6) if weight else None, "by_feature": by_feature, "multi_step": multi_step}

    out = models_dir / MODEL_NAME / version
    out.mkdir(parents=True, exist_ok=True)
    (out / "model.json").write_text(json.dumps({"version": version, "params": params, "features": models}, indent=2, sort_keys=True) + "\n")
    (out / "backtest.json").write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")
    (out / "model_card.md").write_text(_card(version, days, metrics, data_sha))

    base = f"{artifact_base_uri.rstrip('/')}/{MODEL_NAME}/{version}"
    challenger = ModelVersion(
        model_name=MODEL_NAME, version=version, artifact_uri=f"{base}/model.json", card_uri=f"{base}/model_card.md",
        metrics=metrics, trained_on={"window_start": days[0].isoformat(), "window_end": days[-1].isoformat(), "data_sha256": data_sha},
        run_id=run_id, baselines=["seasonal_naive"],
    )
    registered = registry.register(challenger)
    champion_version = registry.get_alias(MODEL_NAME, "champion")
    champion = registry.get_version(MODEL_NAME, champion_version) if champion_version else None
    promoted = champion_version != version and should_promote(challenger, champion)
    if promoted:
        registry.set_alias(MODEL_NAME, "champion", version)
    alias = "champion" if (promoted or champion_version == version) else "challenger"

    table = pa.Table.from_pylist(
        [{**r, "model_name": MODEL_NAME, "model_version": version, "model_alias": alias, "feature_scope": FEATURE_SCOPE, "run_id": run_id} for r in rows],
        schema=FORECAST_SCHEMA.with_metadata({b"synthetic": b"true"}),
    )
    pq.write_table(table, gold / "fct_forecasts.parquet", compression="zstd")
    summary = {"model": MODEL_NAME, "version": version, "registered": registered, "promoted": promoted,
               "alias": alias, "wape": metrics["wape"], "forecast_rows": table.num_rows}
    log.info("train_finished", extra={"fields": summary})
    return summary
