"""Writes the landing files: Parquet with synthetic-data metadata, plus a deterministic manifest.

Same seed and profile give byte-identical output: nothing time-dependent is written.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from . import GENERATOR, __version__
from .catalog import PRICE_CATALOG_V1
from .config import SimConfig
from .revenue import InvoiceLine
from .telemetry import UsageRow
from .tenants import Tenant

MONEY = pa.decimal128(14, 2)

SCHEMAS: dict[str, pa.Schema] = {
    "tenants/tenants.parquet": pa.schema(
        [
            ("tenant_id", pa.string()), ("segment", pa.string()), ("plan", pa.string()),
            ("arr_usd", MONEY), ("ai_addon_arr_usd", MONEY), ("discount_pct", pa.decimal128(5, 2)),
            ("unlimited_ai", pa.bool_()), ("contract_start", pa.date32()), ("renewal_date", pa.date32()),
        ]
    ),
    "s1_llm_telemetry/telemetry_daily.parquet": pa.schema(
        [
            ("usage_date", pa.date32()), ("tenant_id", pa.string()), ("feature_id", pa.string()),
            ("gen_ai_provider_name", pa.string()), ("gen_ai_request_model", pa.string()),
            ("gen_ai_operation_name", pa.string()), ("request_count", pa.int64()),
            ("gen_ai_usage_input_tokens", pa.int64()), ("gen_ai_usage_output_tokens", pa.int64()),
            ("gen_ai_usage_cache_read_input_tokens", pa.int64()), ("retry_count", pa.int64()),
        ]
    ),
    "s3_revenue/subscriptions.parquet": pa.schema(
        [
            ("tenant_id", pa.string()), ("plan", pa.string()), ("contract_start", pa.date32()),
            ("renewal_date", pa.date32()), ("arr_usd", MONEY), ("ai_addon_arr_usd", MONEY),
            ("discount_pct", pa.decimal128(5, 2)), ("unlimited_ai", pa.bool_()), ("currency", pa.string()),
        ]
    ),
    "s3_revenue/invoices.parquet": pa.schema(
        [
            ("invoice_id", pa.string()), ("tenant_id", pa.string()), ("billing_period_start", pa.date32()),
            ("billing_period_end", pa.date32()), ("line_type", pa.string()), ("amount_usd", MONEY),
            ("currency", pa.string()),
        ]
    ),
    "s5_price_catalog/price_catalog.parquet": pa.schema(
        [
            ("model_id", pa.string()), ("provider", pa.string()), ("tier", pa.string()),
            ("input_usd_per_mtok", pa.float64()), ("output_usd_per_mtok", pa.float64()),
            ("cache_read_usd_per_mtok", pa.float64()), ("batch_discount_pct", pa.float64()),
            ("baa_covered", pa.bool_()), ("eu_region", pa.bool_()), ("effective_from", pa.date32()),
            ("effective_to", pa.date32()),
        ]
    ),
    "labels/patterns.parquet": pa.schema(
        [
            ("pattern_id", pa.string()), ("pattern_type", pa.string()), ("feature_id", pa.string()),
            ("tenant_scope", pa.string()), ("model_scope", pa.string()), ("start_date", pa.date32()),
            ("end_date", pa.date32()), ("affected_metric", pa.string()), ("magnitude", pa.float64()),
            ("expected_impact_usd_per_day", MONEY), ("detectable_by", pa.string()),
        ]
    ),
}


def _records(cfg: SimConfig, tenants: list[Tenant], usage: list[UsageRow], invoices: list[InvoiceLine], labels: list[dict]):
    from decimal import Decimal

    return {
        "tenants/tenants.parquet": [
            {k: getattr(t, k) for k in SCHEMAS["tenants/tenants.parquet"].names} for t in tenants
        ],
        "s1_llm_telemetry/telemetry_daily.parquet": [
            {k: getattr(r, k) for k in SCHEMAS["s1_llm_telemetry/telemetry_daily.parquet"].names} for r in usage
        ],
        "s3_revenue/subscriptions.parquet": [
            {**{k: getattr(t, k) for k in SCHEMAS["s3_revenue/subscriptions.parquet"].names if k != "currency"}, "currency": "USD"}
            for t in tenants
        ],
        "s3_revenue/invoices.parquet": [{**asdict(i), "currency": "USD"} for i in invoices],
        "s5_price_catalog/price_catalog.parquet": [
            {**asdict(PRICE_CATALOG_V1[m]), "effective_to": None} for m in cfg.models
        ],
        "labels/patterns.parquet": [
            {**l, "expected_impact_usd_per_day": Decimal(str(l["expected_impact_usd_per_day"]))} for l in labels
        ],
    }


def write_landing(out_dir: Path, cfg: SimConfig, tenants, usage, invoices, labels) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        b"synthetic": b"true",
        b"generator": GENERATOR.encode(),
        b"generator_version": __version__.encode(),
        b"profile": cfg.profile.encode(),
        b"seed": str(cfg.seed).encode(),
    }
    files = []
    for rel, rows in _records(cfg, tenants, usage, invoices, labels).items():
        schema = SCHEMAS[rel].with_metadata(metadata)
        table = pa.Table.from_pylist(rows, schema=schema)
        path = out_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, path, compression="zstd")
        files.append({"path": rel, "rows": table.num_rows, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})

    manifest = {
        "generator": GENERATOR,
        "generator_version": __version__,
        "synthetic": True,
        "profile": cfg.profile,
        "seed": cfg.seed,
        "window": {"start": cfg.start.isoformat(), "end": cfg.end.isoformat(), "days": cfg.days},
        "patterns": list(cfg.patterns),
        "files": files,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest
