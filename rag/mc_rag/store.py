"""Vector stores with S3 Vectors semantics.

- S3VectorsStore: Amazon S3 Vectors (ADR-008), cosine index, filterable + non-filterable metadata.
- LocalVectorStore: an in-memory/JSON store for local runs and tests. Its filter evaluator implements
  the subset of the S3 Vectors filter language we use ($eq, $ne, $in, $nin, $exists, $and, $or, and
  implicit equality), so a filter that works locally means the same thing in AWS.

Metadata layout per vector: the Chunk's filterable fields plus non-filterable `text` and `heading`
(declared non-filterable on the index in infra/; text can exceed the 2 KB filterable limit).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

NON_FILTERABLE_KEYS = ("text", "heading")
PUT_BATCH = 500  # S3 Vectors: up to 500 vectors per PutVectors call
GET_BATCH = 100  # S3 Vectors: up to 100 keys per GetVectors call


@dataclass(frozen=True)
class VectorRecord:
    key: str
    vector: np.ndarray
    metadata: dict[str, Any]


@dataclass(frozen=True)
class QueryResult:
    key: str
    distance: float
    metadata: dict[str, Any]


class VectorStore(Protocol):
    def get_hashes(self, keys: list[str]) -> dict[str, str]: ...
    def put(self, records: list[VectorRecord]) -> None: ...
    def query(self, vector: np.ndarray, top_k: int, flt: dict[str, Any]) -> list[QueryResult]: ...
    def keys(self) -> list[str]: ...
    def delete(self, keys: list[str]) -> None: ...


def matches(meta: dict[str, Any], flt: dict[str, Any]) -> bool:
    """Evaluate an S3 Vectors metadata filter against one vector's metadata."""
    for key, cond in flt.items():
        if key == "$and":
            if not all(matches(meta, f) for f in cond):
                return False
        elif key == "$or":
            if not any(matches(meta, f) for f in cond):
                return False
        elif key.startswith("$"):
            raise ValueError(f"unsupported top-level operator {key}")
        elif key in NON_FILTERABLE_KEYS:
            raise ValueError(f"{key} is non-filterable")
        elif not _match_field(meta, key, cond):
            return False
    return True


def _match_field(meta: dict[str, Any], key: str, cond: Any) -> bool:
    present = key in meta
    value = meta.get(key)
    values = value if isinstance(value, list) else [value]
    if not isinstance(cond, dict):
        cond = {"$eq": cond}
    for op, arg in cond.items():
        if op == "$exists":
            ok = present == bool(arg)
        elif op == "$eq":
            ok = present and arg in values
        elif op == "$ne":
            ok = not (present and arg in values)
        elif op == "$in":
            if not isinstance(arg, list) or not arg:
                raise ValueError("$in needs a non-empty array")
            ok = present and any(v in arg for v in values)
        elif op == "$nin":
            if not isinstance(arg, list) or not arg:
                raise ValueError("$nin needs a non-empty array")
            ok = not (present and any(v in arg for v in values))
        else:
            raise ValueError(f"unsupported operator {op}")
        if not ok:
            return False
    return True


class LocalVectorStore:
    """Exact cosine search over an in-memory table; optionally persisted as JSON."""

    def __init__(self, dimensions: int, path: Path | None = None) -> None:
        self.dimensions = dimensions
        self.path = Path(path) if path else None
        self._rows: dict[str, VectorRecord] = {}
        if self.path and self.path.exists():
            data = json.loads(self.path.read_text())
            if data["dimensions"] != dimensions:
                raise ValueError(f"{self.path} holds {data['dimensions']}-dim vectors, expected {dimensions}")
            for row in data["vectors"]:
                self._rows[row["key"]] = VectorRecord(row["key"], np.asarray(row["vector"], dtype=np.float32), row["metadata"])

    def __len__(self) -> int:
        return len(self._rows)

    def get_hashes(self, keys: list[str]) -> dict[str, str]:
        return {k: self._rows[k].metadata.get("content_sha", "") for k in keys if k in self._rows}

    def put(self, records: list[VectorRecord]) -> None:
        for r in records:
            if r.vector.shape != (self.dimensions,):
                raise ValueError(f"{r.key}: expected {self.dimensions} dims")
            self._rows[r.key] = r
        self._save()

    def delete(self, keys: list[str]) -> None:
        for k in keys:
            self._rows.pop(k, None)
        self._save()

    def keys(self) -> list[str]:
        return sorted(self._rows)

    def query(self, vector: np.ndarray, top_k: int, flt: dict[str, Any]) -> list[QueryResult]:
        q = np.asarray(vector, dtype=np.float32)
        q = q / (np.linalg.norm(q) or 1.0)
        scored = []
        for r in self._rows.values():
            if not matches(r.metadata, flt):
                continue
            v = r.vector / (np.linalg.norm(r.vector) or 1.0)
            scored.append(QueryResult(r.key, float(1.0 - np.dot(q, v)), r.metadata))  # cosine distance
        scored.sort(key=lambda x: (x.distance, x.key))
        return scored[:top_k]

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rows = [{"key": r.key, "vector": [round(float(x), 7) for x in r.vector], "metadata": r.metadata}
                for r in sorted(self._rows.values(), key=lambda r: r.key)]
        self.path.write_text(json.dumps({"dimensions": self.dimensions, "vectors": rows}))


class S3VectorsStore:
    """Amazon S3 Vectors index (data-plane calls only; the bucket and index are created by CDK)."""

    def __init__(self, bucket: str, index: str, client: object | None = None) -> None:
        self.bucket, self.index = bucket, index
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.client("s3vectors", config=Config(retries={"mode": "standard", "max_attempts": 4}))
        self.client = client

    def get_hashes(self, keys: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for i in range(0, len(keys), GET_BATCH):
            resp = self.client.get_vectors(
                vectorBucketName=self.bucket, indexName=self.index, keys=keys[i:i + GET_BATCH],
                returnData=False, returnMetadata=True,
            )
            for v in resp.get("vectors", []):
                out[v["key"]] = (v.get("metadata") or {}).get("content_sha", "")
        return out

    def put(self, records: list[VectorRecord]) -> None:
        for i in range(0, len(records), PUT_BATCH):
            self.client.put_vectors(
                vectorBucketName=self.bucket, indexName=self.index,
                vectors=[{"key": r.key, "data": {"float32": [float(x) for x in r.vector]}, "metadata": r.metadata}
                         for r in records[i:i + PUT_BATCH]],
            )

    def keys(self) -> list[str]:
        out: list[str] = []
        kwargs: dict[str, Any] = {"vectorBucketName": self.bucket, "indexName": self.index}
        while True:  # keys only (returnData/returnMetadata false): needs s3vectors:ListVectors alone
            resp = self.client.list_vectors(**kwargs)
            out.extend(v["key"] for v in resp.get("vectors", []))
            if not resp.get("nextToken"):
                return sorted(out)
            kwargs["nextToken"] = resp["nextToken"]

    def delete(self, keys: list[str]) -> None:
        for i in range(0, len(keys), PUT_BATCH):
            self.client.delete_vectors(vectorBucketName=self.bucket, indexName=self.index, keys=keys[i:i + PUT_BATCH])

    def query(self, vector: np.ndarray, top_k: int, flt: dict[str, Any]) -> list[QueryResult]:
        resp = self.client.query_vectors(
            vectorBucketName=self.bucket, indexName=self.index, topK=top_k,
            queryVector={"float32": [float(x) for x in vector]}, filter=flt,
            returnMetadata=True, returnDistance=True,
        )
        return [QueryResult(v["key"], float(v.get("distance", 0.0)), v.get("metadata") or {}) for v in resp.get("vectors", [])]
