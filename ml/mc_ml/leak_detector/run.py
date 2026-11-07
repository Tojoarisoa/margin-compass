"""Run the leak detector on M2 gold: daily LLM cost per feature -> `fct_margin_leaks`, scored against PT-01..PT-07 (EV-03)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .detect import Alert, detect
from .score import Label, score

PATTERNS = tuple(f"PT-0{i}" for i in range(1, 8))
MONEY6 = pa.decimal128(18, 6)
SCHEMA = pa.schema([
    ("feature_id", pa.string()), ("metric", pa.string()), ("start_date", pa.date32()), ("detected_date", pa.date32()),
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
    return [(r["feature_id"], Label(r["pattern_id"], r["start_date"], r["end_date"])) for r in rows if r["pattern_id"] in PATTERNS]


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


def run_detector(gold: Path, labels_path: Path | None, run_id: str) -> dict:
    series, days = daily_cost(gold)
    alerts = {f: detect(days, v) for f, v in series.items()}
    rows = [{"feature_id": f, "metric": "llm_cost_usd_per_day", "start_date": a.start, "detected_date": a.detected,
             "end_date": a.end, "impact_usd_per_day": Decimal(str(a.impact_per_day)), "peak_ratio": a.peak_ratio,
             "status": "open" if a.end is None else "closed", "run_id": run_id}
            for f, al in alerts.items() for a in al]
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA.with_metadata({b"synthetic": b"true"})),
                   gold / "fct_margin_leaks.parquet", compression="zstd")
    result = {"alerts": len(rows)}
    if labels_path is not None and labels_path.exists():
        result["ev03"] = score_by_feature(alerts, read_labels(labels_path))
    return result
