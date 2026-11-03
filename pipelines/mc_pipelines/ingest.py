"""Stage 1 ingest: landing -> bronze, with manifest reconciliation and quarantine (PLAN.md §6.2).

Gate: every file listed in the producer manifest must exist, match its SHA-256 and row count, carry
synthetic=true metadata, and match its contracted schema. Anything else goes to quarantine/ and the
run fails. Re-ingesting the same ingest_date replaces that partition (idempotent).
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow.parquet as pq

from .contracts import EXPECTED_SCHEMAS, schema_fingerprint

log = logging.getLogger("mc_pipelines")


class IngestError(RuntimeError):
    pass


@dataclass
class IngestResult:
    ingest_date: str
    window: dict
    files: list[dict] = field(default_factory=list)
    quarantined: list[dict] = field(default_factory=list)


def _check(landing: Path, entry: dict) -> tuple[list[tuple[str, str]], str | None]:
    path = landing / entry["path"]
    if not path.exists():
        return [], "missing file"
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
        return [], "sha256 mismatch"
    meta = pq.read_metadata(path)
    if meta.num_rows != entry["rows"]:
        return [], f"row count {meta.num_rows} != manifest {entry['rows']}"
    schema = pq.read_schema(path)
    if (schema.metadata or {}).get(b"synthetic") != b"true":
        return [], "missing synthetic=true metadata"
    fields = [(f.name, str(f.type)) for f in schema]
    expected = EXPECTED_SCHEMAS.get(entry["path"])
    if expected is None:
        return fields, "no contract for this file"
    if fields != expected:
        return fields, f"schema drift: got {fields}, expected {expected}"
    return fields, None


def ingest(landing: Path, data_root: Path, ingest_date: str, run_id: str) -> IngestResult:
    manifest_path = landing / "manifest.json"
    if not manifest_path.exists():
        raise IngestError(f"no manifest.json in {landing}")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("synthetic") is not True:
        raise IngestError("producer manifest is not marked synthetic")

    result = IngestResult(ingest_date=ingest_date, window=manifest["window"])
    staged: list[tuple[Path, Path, dict]] = []
    for entry in manifest["files"]:
        fields, problem = _check(landing, entry)
        source_dir, name = entry["path"].split("/", 1)
        partition = f"{source_dir}/ingest_date={ingest_date}"
        record = {"path": entry["path"], "rows": entry["rows"], "schema_fingerprint": schema_fingerprint(fields)}
        if problem:
            target = data_root / "quarantine" / partition
            target.mkdir(parents=True, exist_ok=True)
            if (landing / entry["path"]).exists():
                shutil.copy2(landing / entry["path"], target / name)
            result.quarantined.append({**record, "reason": problem})
            log.error("file_quarantined", extra={"fields": {"path": entry["path"], "reason": problem[:200]}})
        else:
            staged.append((landing / entry["path"], data_root / "bronze" / partition, record))

    if result.quarantined:
        raise IngestError(f"{len(result.quarantined)} file(s) quarantined; bronze left unchanged")

    # Idempotent re-ingest: clear each partition once per run, before copying. Several files can share
    # a partition (s3_revenue holds subscriptions and invoices), so never clear per file.
    for target in {target for _, target, _ in staged}:
        if target.exists():
            shutil.rmtree(target)
    for src, target, record in staged:
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target / src.name)
        result.files.append(record)
        log.info("file_ingested", extra={"fields": {"path": record["path"], "rows": record["rows"]}})

    manifest_dir = data_root / "bronze" / "_manifests" / f"ingest_date={ingest_date}"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "ingestion_manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "ingest_date": ingest_date,
                "source_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                "generator": manifest.get("generator"),
                "profile": manifest.get("profile"),
                "seed": manifest.get("seed"),
                "window": manifest["window"],
                "synthetic": True,
                "files": result.files,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return result
