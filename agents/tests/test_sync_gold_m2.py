"""sync_gold fetches M2 marts beside the M1 file and skips the ones S3 does not have yet."""

from pathlib import Path

from mc_agents import api


class _Missing(Exception):
    response = {"Error": {"Code": "404"}}


class FakeS3:
    def __init__(self, keys):
        self.keys = keys

    def head_object(self, Bucket, Key):
        if Key not in self.keys:
            raise _Missing()
        return {"ETag": "e1"}

    def download_file(self, Bucket, Key, path):
        Path(path).write_bytes(b"x")


def test_missing_m2_marts_skipped_and_present_ones_fetched(tmp_path, monkeypatch):
    names = api._m2_files()
    assert names, "registry should list M2 marts"
    present = {"gold/fct_tenant_margin.parquet", f"gold/{names[0]}"}
    monkeypatch.setattr(api, "_client", lambda n: FakeS3(present))
    api._gold_etags.clear()
    api.sync_gold("b", tmp_path)
    assert (tmp_path / "fct_tenant_margin.parquet").exists()
    assert (tmp_path / names[0]).exists()
    assert not any((tmp_path / n).exists() for n in names[1:])
