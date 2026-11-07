"""Command line.

  uv run mc-rag index --knowledge ../knowledge --store ../data/local/rag/index.json
  uv run mc-rag query --tenant bc-t0003 "Is AI usage unlimited?" --store ../data/local/rag/index.json

The local embedder is deterministic hashing (no network). `--embedder titan` calls Bedrock and needs
AWS credentials; `--s3vectors BUCKET/INDEX` targets the AWS index instead of a local file.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .bm25 import BM25Index
from .corpus import load_corpus
from .embed import DIMENSIONS, HashingEmbedder, TitanEmbedder
from .golden import GOLDEN_PATH, evaluate, load_cases
from .index import index_corpus
from .retrieve import hybrid_retrieve, retrieve
from .store import LocalVectorStore, S3VectorsStore


def _store(args):
    if args.s3vectors:
        bucket, _, index = args.s3vectors.partition("/")
        return S3VectorsStore(bucket, index)
    return LocalVectorStore(DIMENSIONS, Path(args.store))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mc-rag")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("index", "query", "eval"):
        s = sub.add_parser(name)
        s.add_argument("--embedder", choices=("hashing", "titan"), default="hashing")
        s.add_argument("--store", default="../data/local/rag/index.json")
        s.add_argument("--s3vectors", default="", help="BUCKET/INDEX in S3 Vectors")
        if name in ("index", "eval"):
            s.add_argument("--knowledge", default="../knowledge")
        if name == "eval":
            s.add_argument("--golden", default=str(GOLDEN_PATH))
            s.add_argument("--top-k", type=int, default=5)
        elif name == "query":
            s.add_argument("--mode", choices=("hybrid", "vector"), default="hybrid")
            s.add_argument("--knowledge", default="../knowledge")
            s.add_argument("--tenant", required=True)
            s.add_argument("--top-k", type=int, default=5)
            s.add_argument("text")
    args = p.parse_args(argv)
    embedder = TitanEmbedder() if args.embedder == "titan" else HashingEmbedder()
    store = _store(args)
    if args.cmd == "index":
        print(json.dumps(index_corpus(Path(args.knowledge), embedder, store)))
    elif args.cmd == "eval":
        # Index promotion gate: exit 1 unless recall@k meets the EV-04 gate with no cross-tenant hits.
        result = evaluate(load_cases(Path(args.golden)), embedder=embedder, store=store,
                          bm25=BM25Index(load_corpus(Path(args.knowledge))), top_k=args.top_k)
        print(json.dumps(result))
        return 0 if result["passed"] else 1
    else:
        if args.mode == "hybrid":
            hits = hybrid_retrieve(args.text, tenant_id=args.tenant, embedder=embedder, store=store,
                                   bm25=BM25Index(load_corpus(Path(args.knowledge))), top_k=args.top_k)
        else:
            hits = retrieve(args.text, tenant_id=args.tenant, embedder=embedder, store=store, top_k=args.top_k)
        for h in hits:
            print(json.dumps({"key": h.key, "score": round(h.score, 4), "tenant_id": h.tenant_id,
                              "clause_type": h.clause_type, "heading": h.heading}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
