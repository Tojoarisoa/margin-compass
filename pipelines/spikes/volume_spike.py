"""M2 step 1 volume spike (docs/plans/m2-plan.md §3). SYNTHETIC, throwaway load generator.

Writes M1-schema landing files at the M2 target volume (400 tenants, 2025-05-01..2026-10-31, ~2.8M
telemetry rows, ~0.44M invoice lines), then times ingest + `dbt build` and reports peak RSS.
Not the M2 simulator: it only reproduces row counts and column shapes so the existing build can be
measured. Usage: uv run python spikes/volume_spike.py <workdir>
"""
from __future__ import annotations

import hashlib
import json
import resource
import sys
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from booncore_sim.catalog import PRICE_CATALOG_V1
from booncore_sim.writer import SCHEMAS

START, END, N = date(2025, 5, 1), date(2026, 10, 31), 400
COMBOS = [("F0", "a-small"), ("F1", "a-small"), ("F1", "a-mid"), ("F2", "a-small"), ("F2", "a-mid"),
          ("F2", "a-frontier"), ("F3", "a-mid"), ("F3", "c-small"), ("F4", "a-mid"), ("F4", "a-frontier"),
          ("F4", "b-mid"), ("F0", "c-small"), ("F1", "b-mid")]


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def make_landing(out: Path) -> dict:
    rng = np.random.default_rng(7)
    days = (END - START).days + 1
    epoch = date(1970, 1, 1)
    d0 = (START - epoch).days
    meta = {b"synthetic": b"true", b"generator": b"volume_spike"}
    n_rows = N * days * len(COMBOS)
    day = np.tile(np.repeat(np.arange(days), len(COMBOS)), N) + d0
    ten = np.repeat(np.arange(N), days * len(COMBOS))
    combo = np.tile(np.arange(len(COMBOS)), N * days)
    req = rng.poisson(50, n_rows) + 1
    inp = (req * rng.lognormal(7.4, 0.2, n_rows)).astype(np.int64)
    out_t = (req * rng.lognormal(5.7, 0.2, n_rows)).astype(np.int64)
    cache = (inp * 0.5).astype(np.int64)
    sch = SCHEMAS["s1_llm_telemetry/telemetry_daily.parquet"].with_metadata(meta)
    feats = np.array([c[0] for c in COMBOS])
    models = np.array([c[1] for c in COMBOS])
    prov = np.array([PRICE_CATALOG_V1[c[1]].provider for c in COMBOS])
    tnames = np.array([f"bc-t{i + 1:04d}" for i in range(N)])
    tbl = pa.table({
        "usage_date": pa.array(day.astype(np.int32), pa.date32()), "tenant_id": pa.array(tnames[ten]),
        "feature_id": pa.array(feats[combo]), "gen_ai_provider_name": pa.array(prov[combo]),
        "gen_ai_request_model": pa.array(models[combo]), "gen_ai_operation_name": pa.array(["chat"] * n_rows),
        "request_count": req, "gen_ai_usage_input_tokens": inp, "gen_ai_usage_output_tokens": out_t,
        "gen_ai_usage_cache_read_input_tokens": cache, "retry_count": rng.binomial(req, 0.01),
    }, schema=sch)
    files = []

    def put(rel: str, t: pa.Table) -> None:
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(t, p, compression="zstd")
        files.append({"path": rel, "rows": t.num_rows, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    put("s1_llm_telemetry/telemetry_daily.parquet", tbl)

    from decimal import Decimal
    plans = rng.choice(["starter", "growth", "enterprise"], N, p=[0.5, 0.35, 0.15])
    arr = np.round(rng.lognormal(10.8, 0.9, N) * 1, 2)
    ten_rows = [{"tenant_id": f"bc-t{i + 1:04d}", "segment": "imaging", "plan": str(plans[i]),
                 "arr_usd": Decimal(str(arr[i])), "ai_addon_arr_usd": Decimal(str(round(arr[i] * 0.35, 2))),
                 "discount_pct": Decimal("0.10"), "unlimited_ai": False,
                 "contract_start": START - timedelta(days=100), "renewal_date": START + timedelta(days=200)}
                for i in range(N)]
    put("tenants/tenants.parquet", pa.Table.from_pylist(ten_rows, schema=SCHEMAS["tenants/tenants.parquet"].with_metadata(meta)))
    subs = [{**{k: r[k] for k in SCHEMAS["s3_revenue/subscriptions.parquet"].names if k != "currency"}, "currency": "USD"} for r in ten_rows]
    put("s3_revenue/subscriptions.parquet", pa.Table.from_pylist(subs, schema=SCHEMAS["s3_revenue/subscriptions.parquet"].with_metadata(meta)))
    # ~0.44M revenue rows: daily-ized lines would be bigger; here 18 months x 400 tenants x 2 lines, padded by 30 line types.
    inv, months = [], []
    d = START
    while d <= END:
        months.append(d)
        d = date(d.year + d.month // 12, d.month % 12 + 1, 1)
    for m in months:
        nm = date(m.year + m.month // 12, m.month % 12 + 1, 1)
        for r in ten_rows:
            for lt, share in (("subscription", 0.65), ("ai_addon", 0.35)):
                inv.append({"invoice_id": f"inv-{m:%Y%m}-{r['tenant_id']}", "tenant_id": r["tenant_id"],
                            "billing_period_start": m, "billing_period_end": nm, "line_type": lt,
                            "amount_usd": (r["arr_usd"] / 12 * Decimal(str(share))).quantize(Decimal("0.01")), "currency": "USD"})
    put("s3_revenue/invoices.parquet", pa.Table.from_pylist(inv, schema=SCHEMAS["s3_revenue/invoices.parquet"].with_metadata(meta)))
    cat = [{**{k: getattr(p, k) for k in SCHEMAS["s5_price_catalog/price_catalog.parquet"].names if k != "effective_to"}, "effective_to": None}
           for p in PRICE_CATALOG_V1.values()]
    put("s5_price_catalog/price_catalog.parquet", pa.Table.from_pylist(cat, schema=SCHEMAS["s5_price_catalog/price_catalog.parquet"].with_metadata(meta)))
    put("labels/patterns.parquet", pa.Table.from_pylist([], schema=SCHEMAS["labels/patterns.parquet"].with_metadata(meta)))
    manifest = {"generator": "volume_spike", "generator_version": "0", "synthetic": True, "profile": "spike", "seed": 7,
                "window": {"start": START.isoformat(), "end": END.isoformat(), "days": days}, "patterns": [], "files": files}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def main() -> int:
    work = Path(sys.argv[1]).resolve()
    t0 = time.perf_counter()
    m = make_landing(work / "landing")
    t_gen = time.perf_counter() - t0
    print(f"generate: {t_gen:.1f}s rows={ {f['path']: f['rows'] for f in m['files']} } peak_rss={rss_mb():.0f}MB", flush=True)
    from mc_pipelines.cli import run_dbt
    from mc_pipelines.ingest import ingest
    run_id = str(uuid.uuid4())
    t0 = time.perf_counter()
    res = ingest(work / "landing", work, "2026-11-01", run_id)
    t_ing = time.perf_counter() - t0
    print(f"ingest: {t_ing:.1f}s peak_rss={rss_mb():.0f}MB", flush=True)
    # The M1 models hard-code F1 (M2-02 widens them). Build from a patched copy so the full build can be timed.
    import re
    import shutil

    from mc_pipelines.cli import TRANSFORM_DIR
    tdir = work / "transform_spike"
    shutil.copytree(TRANSFORM_DIR, tdir, ignore=shutil.ignore_patterns("target", "logs", "dbt_packages"))
    for f in list(tdir.rglob("*.sql")) + list(tdir.rglob("*.yml")):
        txt = f.read_text()
        new = txt.replace("('F1')", "('F0','F1','F2','F3','F4')").replace("[F1]", "[F0, F1, F2, F3, F4]")
        new = re.sub(r"(accepted_values:\s*\n\s*(?:arguments:\s*\n\s*)?values:\s*)\['F1'\]", r"\1['F0','F1','F2','F3','F4']", new)
        if new != txt:
            f.write_text(new)
    t0 = time.perf_counter()
    s = run_dbt(work, "2026-11-01", res.window, run_id, transform_dir=tdir)
    t_dbt = time.perf_counter() - t0
    print(f"dbt build: {t_dbt:.1f}s peak_rss={rss_mb():.0f}MB summary={json.dumps(s)[:600]}", flush=True)
    gold = sum(p.stat().st_size for p in (work / "gold").rglob("*.parquet")) / 1e6
    print(f"gold parquet: {gold:.1f}MB")
    return 0 if s["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
