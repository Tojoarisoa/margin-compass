import json

from mc_pipelines.publish import publish_finops


def test_publish_finops_writes_awaiting_status_without_export(tmp_path, monkeypatch):
    monkeypatch.delenv("MC_FINOPS_FOCUS_GLOB", raising=False)
    assert publish_finops(tmp_path, "r1") == ["publish/latest/finops.json"]
    body = json.loads((tmp_path / "publish" / "latest" / "finops.json").read_text())
    assert body["status"] == "awaiting_first_export" and body["run_id"] == "r1"
