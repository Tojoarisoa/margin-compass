"""Data-quality scorecard and lineage from dbt artifacts (PLAN.md §6.2 Stage 3, §7.4).

Written to gold/_quality/ on every run, pass or fail, so the dashboard (M1-07) and EV-01 can read them.
Error-severity failures stop the run and move the day's bronze partitions to quarantine/.
"""

from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

CATEGORIES = ("contract", "preservation", "business_rule", "statistical")


def write_scorecard(data_root: Path, target_dir: Path, run_id: str, ingest_date: str) -> dict:
    results = json.loads((target_dir / "run_results.json").read_text())["results"]
    manifest = json.loads((target_dir / "manifest.json").read_text())
    nodes = manifest["nodes"]

    tests, models = [], []
    for r in results:
        node = nodes.get(r["unique_id"], {})
        if node.get("resource_type") == "test":
            tags = node.get("tags", [])
            category = next((c for c in CATEGORIES if c in tags), "uncategorized")
            tests.append({
                "test": node.get("name"),
                "category": category,
                "severity": node.get("config", {}).get("severity", "ERROR").lower(),
                "status": r["status"],
                "failures": r.get("failures"),
            })
        elif node.get("resource_type") == "model":
            models.append({
                "model": node.get("name"),
                "status": r["status"],
                "contract_enforced": bool(node.get("contract", {}).get("enforced")),
            })

    errors = [t for t in tests if t["status"] in ("fail", "error")]
    warnings = [t for t in tests if t["status"] == "warn"]
    scorecard = {
        "run_id": run_id,
        "ingest_date": ingest_date,
        "ev01_status": "fail" if errors or any(m["status"] == "error" for m in models) else "pass",
        "tests": {"total": len(tests), "by_status": dict(Counter(t["status"] for t in tests))},
        "by_category": {
            c: dict(Counter(t["status"] for t in tests if t["category"] == c)) for c in (*CATEGORIES, "uncategorized")
            if any(t["category"] == c for t in tests)
        },
        "models": models,
        "contracts_enforced": sorted(m["model"] for m in models if m["contract_enforced"]),
        "errors": errors,
        "warnings": warnings,
        "synthetic": True,
    }

    lineage = {
        n["name"]: sorted(nodes[p]["name"] for p in n["depends_on"]["nodes"] if p in nodes)
        for n in nodes.values()
        if n.get("resource_type") == "model"
    }
    out = data_root / "gold" / "_quality"
    out.mkdir(parents=True, exist_ok=True)
    (out / "scorecard.json").write_text(json.dumps(scorecard, indent=2, sort_keys=True) + "\n")
    (out / "lineage.json").write_text(json.dumps({"run_id": run_id, "models": lineage}, indent=2, sort_keys=True) + "\n")
    return scorecard


def quarantine_partition(data_root: Path, ingest_date: str, reason: str) -> list[str]:
    """Move every bronze partition for ingest_date to quarantine/ (Stage 3: error quarantines)."""
    moved = []
    bronze = data_root / "bronze"
    for partition in sorted(bronze.glob(f"*/ingest_date={ingest_date}")):
        target = data_root / "quarantine" / partition.relative_to(bronze)
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(partition), str(target))
        moved.append(str(partition.relative_to(bronze)))
    note = data_root / "quarantine" / f"_reason_ingest_date={ingest_date}.json"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(json.dumps({"ingest_date": ingest_date, "reason": reason, "partitions": moved}, indent=2) + "\n")
    return moved
