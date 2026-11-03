import dataclasses
import re
from decimal import Decimal

import numpy as np
import pytest

from mc_rag.corpus import CorpusError, load_corpus


def test_every_chunk_carries_tenant_and_clause_metadata(knowledge_dir):
    chunks = load_corpus(knowledge_dir)
    assert {c.doc_id for c in chunks} == {"policy-fair-use", "contract-bc-t0003", "contract-bc-t0009", "contract-bc-t0012"}
    for c in chunks:
        if c.source_type == "policy":
            assert c.tenant_id == "all"
        else:
            assert c.doc_id == f"contract-{c.tenant_id}"
        assert c.clause_type != "general", f"{c.key} has no clause marker"
        assert len(c.content_sha) == 64
        assert c.title in c.text and c.heading in c.text
        assert len(c.filterable_metadata()) <= 50


def test_keys_are_unique_and_stable(knowledge_dir):
    a, b = load_corpus(knowledge_dir), load_corpus(knowledge_dir)
    assert [c.key for c in a] == [c.key for c in b]
    assert [c.content_sha for c in a] == [c.content_sha for c in b]
    assert len({c.key for c in a}) == len(a)


def test_filterable_metadata_fits_s3_vectors_limit(knowledge_dir):
    # S3 Vectors: 2 KB filterable metadata per vector (VER-03).
    for c in load_corpus(knowledge_dir):
        assert len(str(c.filterable_metadata()).encode()) < 2048


def _write(tmp_path, front, body="## 1. A\n<!-- clause: x -->\n\nText.\n"):
    (tmp_path / "doc.md").write_text(f"---\n{front}\n---\n\n# T\n\n{body}")


BASE = "doc_id: contract-x\ntitle: T\nsource_type: contract\ntenant_id: bc-t0001\neffective_date: 2025-01-01\nsynthetic: true"


@pytest.mark.parametrize("front, message", [
    (BASE.replace("tenant_id: bc-t0001", "tenant_id: all"), "contracts need a tenant_id"),
    (BASE.replace("tenant_id: bc-t0001\n", ""), "missing front-matter keys"),
    (BASE.replace("synthetic: true", "synthetic: false"), "synthetic"),
    (BASE.replace("source_type: contract", "source_type: policy"), "policies apply to tenant_id: all"),
])
def test_malformed_documents_fail_closed(tmp_path, front, message):
    _write(tmp_path, front)
    with pytest.raises(CorpusError, match=message):
        load_corpus(tmp_path)


def test_long_sections_split_on_paragraphs(tmp_path):
    body = "## 1. Long\n<!-- clause: x -->\n\n" + "\n\n".join(["word " * 100] * 10)
    _write(tmp_path, BASE, body)
    chunks = load_corpus(tmp_path)
    assert [c.key for c in chunks][:2] == ["contract-x#1.1", "contract-x#1.2"]
    assert all(len(c.text) < 2_200 for c in chunks)


def test_contracts_match_the_simulated_tenants(knowledge_dir):
    """The contract library and the simulator describe the same tenants (m1 profile, seed 42)."""
    from booncore_sim.config import PROFILES
    from booncore_sim.tenants import generate_tenants

    cfg = dataclasses.replace(PROFILES["m1"], seed=42)
    tenants = {t.tenant_id: t for t in generate_tenants(cfg, np.random.default_rng(42))}
    contracts = [c for c in load_corpus(knowledge_dir) if c.source_type == "contract"]
    for tenant_id in {c.tenant_id for c in contracts}:
        t = tenants[tenant_id]
        text = "\n".join(c.text for c in contracts if c.tenant_id == tenant_id)
        clauses = {c.clause_type for c in contracts if c.tenant_id == tenant_id}
        assert f"Plan: {t.plan.capitalize()}." in text
        assert f"${t.arr_usd:,}" in text and f"${t.ai_addon_arr_usd:,}" in text
        assert f"discount of {int(t.discount_pct * 100)}%" in text
        assert f"from {t.contract_start.isoformat()} to {t.renewal_date.isoformat()}" in text
        assert ("unlimited_ai" in clauses) == t.unlimited_ai
        start = next(c.effective_date for c in contracts if c.tenant_id == tenant_id)
        assert start == t.contract_start.isoformat()
        assert re.search(r"\$\d", text) and Decimal(str(t.discount_pct)) <= Decimal("0.25")
