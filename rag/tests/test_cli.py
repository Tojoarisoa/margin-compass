"""CLI: hybrid query and the EV-04 promotion gate (exit code)."""

import json

from mc_rag.cli import main


def _index(knowledge_dir, tmp_path):
    store = str(tmp_path / "index.json")
    assert main(["index", "--knowledge", str(knowledge_dir), "--store", store]) == 0
    return store


def test_eval_gate_passes(knowledge_dir, tmp_path, capsys):
    store = _index(knowledge_dir, tmp_path)
    capsys.readouterr()
    assert main(["eval", "--knowledge", str(knowledge_dir), "--store", store]) == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True


def test_eval_gate_fails_on_empty_golden(knowledge_dir, tmp_path, capsys):
    store = _index(knowledge_dir, tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"question": "zzz qqq", "tenant_id": "bc-t0003", "expected": ["nope"]}]))
    assert main(["eval", "--knowledge", str(knowledge_dir), "--store", store, "--golden", str(bad)]) == 1


def test_query_hybrid(knowledge_dir, tmp_path, capsys):
    store = _index(knowledge_dir, tmp_path)
    capsys.readouterr()
    assert main(["query", "--knowledge", str(knowledge_dir), "--store", store, "--tenant", "bc-t0003",
                 "Is AI usage unlimited?"]) == 0
    assert capsys.readouterr().out.strip()
