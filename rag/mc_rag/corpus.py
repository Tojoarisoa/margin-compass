"""Parse knowledge/ Markdown into documents and structure-aware chunks (one chunk per `##` section).

The format is described in knowledge/README.md. Parsing is strict: a malformed file fails the run
instead of producing chunks with missing tenant metadata (a tenant-isolation risk).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

REQUIRED_KEYS = ("doc_id", "title", "source_type", "tenant_id", "effective_date", "synthetic")
SOURCE_TYPES = ("policy", "contract", "playbook", "schema", "metric")
SHARED_TYPES = ("policy", "playbook", "schema", "metric")  # tenant_id must be "all"
ALL_TENANTS = "all"
MAX_CHUNK_CHARS = 2_000  # Titan v2 takes 8,192 tokens; small chunks keep retrieval precise
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
_TENANT = re.compile(r"^bc-t\d{4}$")
_CLAUSE = re.compile(r"^<!--\s*clause:\s*([a-z0-9_]+)\s*-->$")


class CorpusError(ValueError):
    """A knowledge file is malformed."""


@dataclass(frozen=True)
class Document:
    doc_id: str
    title: str
    source_type: str
    tenant_id: str
    effective_date: str
    path: str
    body: str


@dataclass(frozen=True)
class Chunk:
    key: str  # stable vector key: "<doc_id>#<section number>[.<part>]"
    doc_id: str
    title: str
    heading: str
    text: str  # what is embedded: title + heading + section body
    source_type: str
    tenant_id: str
    clause_type: str
    effective_date: str
    content_sha: str  # sha256 of text; unchanged chunks are not re-embedded

    def filterable_metadata(self) -> dict[str, str]:
        return {
            "doc_id": self.doc_id, "source_type": self.source_type, "tenant_id": self.tenant_id,
            "clause_type": self.clause_type, "effective_date": self.effective_date, "content_sha": self.content_sha,
        }


def parse_document(path: Path, root: Path) -> Document:
    raw = path.read_text(encoding="utf-8")
    lines = raw.split("\n")
    if not lines or lines[0].strip() != "---":
        raise CorpusError(f"{path}: missing front matter")
    try:
        end = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration:
        raise CorpusError(f"{path}: unterminated front matter") from None
    meta: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise CorpusError(f"{path}: bad front-matter line {line!r}")
        meta[key.strip()] = value.strip()
    missing = [k for k in REQUIRED_KEYS if not meta.get(k)]
    if missing:
        raise CorpusError(f"{path}: missing front-matter keys {missing}")
    if meta["synthetic"] != "true":
        raise CorpusError(f"{path}: knowledge files must be labeled synthetic: true (AGENTS.md)")
    if not _ID.match(meta["doc_id"]):
        raise CorpusError(f"{path}: invalid doc_id {meta['doc_id']!r}")
    if meta["source_type"] not in SOURCE_TYPES:
        raise CorpusError(f"{path}: source_type must be one of {SOURCE_TYPES}")
    tenant = meta["tenant_id"]
    if meta["source_type"] in SHARED_TYPES and tenant != ALL_TENANTS:
        raise CorpusError(f"{path}: {meta['source_type']} documents apply to tenant_id: all")
    if meta["source_type"] == "contract" and not _TENANT.match(tenant):
        raise CorpusError(f"{path}: contracts need a tenant_id like bc-t0001, got {tenant!r}")
    date.fromisoformat(meta["effective_date"])
    return Document(
        doc_id=meta["doc_id"], title=meta["title"], source_type=meta["source_type"], tenant_id=tenant,
        effective_date=meta["effective_date"], path=path.relative_to(root).as_posix(),
        body="\n".join(lines[end + 1:]),
    )


def _split(body: str, limit: int) -> list[str]:
    """Split an over-long section on paragraph boundaries."""
    if len(body) <= limit:
        return [body]
    parts, current = [], ""
    for para in body.split("\n\n"):
        if current and len(current) + len(para) + 2 > limit:
            parts.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        parts.append(current)
    return parts


def chunk_document(doc: Document, max_chars: int = MAX_CHUNK_CHARS) -> list[Chunk]:
    sections: list[tuple[str, list[str]]] = []
    for line in doc.body.split("\n"):
        if line.startswith("## "):
            sections.append((line[3:].strip(), []))
        elif sections:
            sections[-1][1].append(line)
    if not sections:
        raise CorpusError(f"{doc.path}: no '## ' sections to chunk")

    chunks: list[Chunk] = []
    for number, (heading, body_lines) in enumerate(sections, start=1):
        clause = "general"
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
        if body_lines and (m := _CLAUSE.match(body_lines[0].strip())):
            clause = m.group(1)
            body_lines = body_lines[1:]
        body = "\n".join(body_lines).strip()
        if not body:
            raise CorpusError(f"{doc.path}: section {heading!r} is empty")
        parts = _split(body, max_chars)
        for part_no, part in enumerate(parts, start=1):
            key = f"{doc.doc_id}#{number}" + (f".{part_no}" if len(parts) > 1 else "")
            text = f"{doc.title}\n{heading}\n\n{part}"
            chunks.append(Chunk(
                key=key, doc_id=doc.doc_id, title=doc.title, heading=heading, text=text,
                source_type=doc.source_type, tenant_id=doc.tenant_id, clause_type=clause,
                effective_date=doc.effective_date, content_sha=hashlib.sha256(text.encode()).hexdigest(),
            ))
    return chunks


def load_corpus(root: Path) -> list[Chunk]:
    """All chunks under root, in a stable order. Fails on duplicate doc IDs."""
    root = Path(root)
    docs = [parse_document(p, root) for p in sorted(root.rglob("*.md")) if p.name != "README.md"]
    if not docs:
        raise CorpusError(f"{root}: no knowledge documents")
    seen: dict[str, str] = {}
    for d in docs:
        if d.doc_id in seen:
            raise CorpusError(f"duplicate doc_id {d.doc_id!r} in {seen[d.doc_id]} and {d.path}")
        seen[d.doc_id] = d.path
    return [c for d in docs for c in chunk_document(d)]
