"""Run the leak detector on M2 gold: daily LLM cost per feature -> `fct_margin_leaks`, scored against PT-01..PT-07 (EV-03)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from .detect import Alert, Params, detect
from .score import Label, score

PATTERNS = tuple(f"PT-0{i}" for i in range(1, 8))
MONEY6 = pa.decimal128(18, 6)
SCHEMA = pa.schema([
    ("feature_id", pa.string()), ("tenant_id", pa.string()), ("metric", pa.string()), ("start_date", pa.date32()), ("detected_date", pa.date32()),
    ("end_date", pa.date32()), ("impact_usd_per_day", MONEY6), ("peak_ratio", pa.float64()), ("status", pa.string()),
    ("run_id", pa.string()),
])


def daily_cost(gold: Path) -> tuple[dict[str, list[float]], list[date]]:
    t = pq.read_table(gold / "fct_unit_cost.parquet", columns=["cost_date", "feature_id", "llm_cost_usd"])
    rows = t.to_pylist()
    start, end = min(r["cost_date"] for r in rows), max(r["cost_date"] for r in rows)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    totals: dict[tuple[date, str], float] = {}
    for r in rows:
        k = (r["cost_date"], r["feature_id"])
        totals[k] = totals.get(k, 0.0) + float(r["llm_cost_usd"])
    return {f: [totals.get((d, f), 0.0) for d in days] for f in sorted({r["feature_id"] for r in rows})}, days


def read_labels(path: Path) -> list[tuple[str, Label]]:
    rows = pq.read_table(path).to_pylist()
    return [(r["feature_id"] if "feature_id" in r else r["feature"], Label(r["pattern_id"], r["start_date"], r["end_date"])) for r in rows if r["pattern_id"] in PATTERNS]


def score_by_feature(alerts: dict[str, list[Alert]], labels: list[tuple[str, Label]]) -> dict:
    """EV-03 with features kept apart: an alert only counts against labels on its own feature."""
    per = {f: score(alerts.get(f, []), [lab for lf, lab in labels if lf == f]) for f in {lf for lf, _ in labels} | set(alerts)}
    n_alerts = sum(s["alerts"] for s in per.values())
    tp = sum(round(s["precision"] * s["alerts"]) for s in per.values() if s["alerts"])
    found = [p for s in per.values() for p in s["found"]]
    delays = [d for f, s in per.items() for d in [s["mttd_days"]] * len(s["found"]) if d is not None]
    precision = tp / n_alerts if n_alerts else 1.0
    recall = len(found) / len(labels) if labels else 1.0
    mttd = round(sum(delays) / len(delays), 2) if delays else None
    return {"precision": round(precision, 4), "recall": round(recall, 4), "mttd_days": mttd, "alerts": n_alerts,
            "labels": len(labels), "found": sorted(found), "missed": sorted({lab.pattern_id for _, lab in labels} - set(found)),
            "passed": bool(labels) and precision >= 0.8 and recall >= 0.8 and mttd is not None and mttd < 1.0 + 1e-9}


FEATURE_PARAMS = Params(min_rel=0.08, k=4.0, min_run=1)  # unit-cost series: volume steps cancel, so a small shift is a real one
SURGE_MIN_PEAK = 2.0  # feature cost alerts are kept only as surges (peak at least 2x); smaller steps are growth, not leaks
TENANT_MULT = 4.0  # a tenant-day is a surge when it exceeds this multiple of the tenant's trailing 28-day mean
TENANT_RUN = 3  # consecutive surge days needed (tenant series are sparse, so a short run is noise)
TENANT_BASE = 28
DEDUPE_DAYS = 3  # a tenant alert starting this close to a feature alert is explained by it


def _ratio(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.where(b > 0, a / np.where(b > 0, b, 1.0), 0.0)


def usage_series(silver: Path, days: list[date]) -> dict[str, dict]:
    """Daily matrices from the priced usage: per feature and per (feature, tenant), as float arrays over `days`."""
    cols = ["usage_date", "tenant_id", "feature_id", "request_count", "input_tokens", "uncached_input_tokens", "retry_count", "llm_cost_usd"]
    t = pq.read_table(silver / "slv_m2_llm_usage_priced.parquet", columns=cols)
    t = t.set_column(7, "llm_cost_usd", t["llm_cost_usd"].cast(pa.float64()))
    day_ix = {d: i for i, d in enumerate(days)}
    measures = [c for c in cols[3:]]

    def grouped(keys: list[str]) -> dict[tuple, dict[str, np.ndarray]]:
        g = t.group_by(["usage_date", *keys]).aggregate([(m, "sum") for m in measures]).to_pydict()
        out: dict[tuple, dict[str, np.ndarray]] = {}
        for i, d in enumerate(g["usage_date"]):
            k = tuple(g[x][i] for x in keys)
            ent = out.setdefault(k, {m: np.zeros(len(days)) for m in measures})
            for m in measures:
                ent[m][day_ix[d]] = float(g[f"{m}_sum"][i] or 0)
        return out

    return {"feature": grouped(["feature_id"]), "tenant": grouped(["feature_id", "tenant_id"])}


def tenant_surges(days: list[date], x: np.ndarray) -> list[Alert]:
    """Runs of `TENANT_RUN` days above `TENANT_MULT` x the trailing mean, once the tenant has `TENANT_BASE` days of history.
    Dated at the first surge day, detected on the last day of the minimum run; `impact_per_day` is in the series' units."""
    c = np.concatenate([[0.0], np.cumsum(x)])
    nz = np.nonzero(x)[0]
    first = int(nz[0]) if len(nz) else len(x)
    out: list[Alert] = []
    run: list[int] = []
    last_end = -1
    for t in range(first + TENANT_BASE, len(x)):
        trail = (c[t] - c[t - TENANT_BASE]) / TENANT_BASE
        if trail >= 1.0 and x[t] > TENANT_MULT * trail:
            run.append(t)
            if len(run) == TENANT_RUN and run[0] > last_end:
                tr = [(c[u] - c[u - TENANT_BASE]) / TENANT_BASE for u in run]
                out.append(Alert(days[run[0]], days[t], days[t], round(float(np.mean([x[u] - b for u, b in zip(run, tr, strict=True)])), 6),
                                 round(float(max(x[u] / b for u, b in zip(run, tr, strict=True))), 4)))
                last_end = t
        else:
            run = []
    return out


def detect_usage(silver: Path, days: list[date]) -> list[dict]:
    """Detector families over the priced usage; each alert is a dict (feature, tenant or None, metric, Alert)."""
    u = usage_series(silver, days)
    found: list[dict] = []
    feat_alerts: dict[str, list[Alert]] = {}

    def add(feature: str, tenant: str | None, metric: str, alerts: list[Alert]) -> None:
        for a in alerts:
            found.append({"feature_id": feature, "tenant_id": tenant, "metric": metric, "alert": a})
            if tenant is None:
                feat_alerts.setdefault(feature, []).append(a)

    for (f,), m in sorted(u["feature"].items()):
        add(f, None, "llm_cost_per_request_usd", detect(days, list(_ratio(m["llm_cost_usd"], m["request_count"])), FEATURE_PARAMS))
        add(f, None, "cache_miss_share", detect(days, list(_ratio(m["uncached_input_tokens"], m["input_tokens"])), FEATURE_PARAMS))
        add(f, None, "llm_cost_usd_per_day", [a for a in detect(days, list(m["llm_cost_usd"])) if a.peak_ratio >= SURGE_MIN_PEAK])
    for (f, tn), m in sorted(u["tenant"].items()):
        for a in tenant_surges(days, m["retry_count"]):
            if not any(abs((a.start - b.start).days) <= DEDUPE_DAYS for b in feat_alerts.get(f, [])):
                found.append({"feature_id": f, "tenant_id": tn, "metric": "tenant_retry_count", "alert": a})
    return found


def run_detector(gold: Path, labels_path: Path | None, run_id: str, silver: Path | None = None) -> dict:
    series, days = daily_cost(gold)
    silver = silver if silver is not None else gold.parent / "silver"
    if (silver / "slv_m2_llm_usage_priced.parquet").exists():
        found = detect_usage(silver, days)
    else:  # no usage detail: daily cost per feature only
        found = [{"feature_id": f, "tenant_id": None, "metric": "llm_cost_usd_per_day", "alert": a}
                 for f, v in series.items() for a in detect(days, v)]
    alerts: dict[str, list[Alert]] = {}
    for x in found:
        alerts.setdefault(x["feature_id"], []).append(x["alert"])
    rows = [{"feature_id": x["feature_id"], "tenant_id": x["tenant_id"], "metric": x["metric"], "start_date": x["alert"].start,
             "detected_date": x["alert"].detected, "end_date": x["alert"].end,
             "impact_usd_per_day": Decimal(str(x["alert"].impact_per_day)), "peak_ratio": x["alert"].peak_ratio,
             "status": "open" if x["alert"].end is None else "closed", "run_id": run_id} for x in found]
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA.with_metadata({b"synthetic": b"true"})),
                   gold / "fct_margin_leaks.parquet", compression="zstd")
    result = {"alerts": len(rows)}
    if labels_path is not None and labels_path.exists():
        result["ev03"] = score_by_feature(alerts, read_labels(labels_path))
    return result
