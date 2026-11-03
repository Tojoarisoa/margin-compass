"""Stage 5 (M1-05): embed knowledge/ into the vector index.

In AWS (VECTOR_BUCKET and VECTOR_INDEX set): Titan Text Embeddings V2 -> S3 Vectors.
Locally and in CI: deterministic hashing embedder -> <data_root>/rag/index.json (no network).
Unchanged chunks are skipped by content hash, so a nightly re-run makes no Bedrock calls.
"""

from __future__ import annotations

import os
from pathlib import Path

KNOWLEDGE_DIR = Path(os.environ.get("MC_KNOWLEDGE_DIR", Path(__file__).resolve().parents[2] / "knowledge"))


def embed_knowledge(data_root: Path, knowledge_dir: Path | None = None) -> dict:
    from mc_rag import HashingEmbedder, LocalVectorStore, S3VectorsStore, TitanEmbedder, index_corpus
    from mc_rag.embed import DIMENSIONS

    bucket, index = os.environ.get("VECTOR_BUCKET", ""), os.environ.get("VECTOR_INDEX", "")
    if bucket and index:
        embedder, store, target = TitanEmbedder(), S3VectorsStore(bucket, index), f"s3vectors://{bucket}/{index}"
    else:
        path = Path(data_root) / "rag" / "index.json"
        embedder, store, target = HashingEmbedder(), LocalVectorStore(DIMENSIONS, path), str(path)
    stats = index_corpus(knowledge_dir or KNOWLEDGE_DIR, embedder, store)
    return {**stats, "target": target}
