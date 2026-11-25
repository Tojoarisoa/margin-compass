"""ECR clean-up selection (owner decision 2026-11-26): never an image in use, the newest, or a recent one."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ops" / "ecr_cleanup.py"
spec = importlib.util.spec_from_file_location("ecr_cleanup", SCRIPT)
ecr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ecr)

NOW = datetime(2026, 11, 26, tzinfo=UTC)


def _img(digest, days_old):
    return {"imageDigest": digest, "imagePushedAt": (NOW - timedelta(days=days_old)).isoformat()}


def test_keeps_newest_in_use_and_recent_images():
    images = [_img(f"sha256:{i}", days) for i, days in enumerate([1, 2, 3, 4, 10, 20, 30, 40])]
    doomed = ecr.select_deletions(images, in_use={"sha256:6"}, now=NOW)
    assert [i["imageDigest"] for i in doomed] == ["sha256:5", "sha256:7"]


def test_nothing_to_delete_when_few_images():
    images = [_img("sha256:a", 100), _img("sha256:b", 200)]
    assert ecr.select_deletions(images, in_use=set(), now=NOW) == []


def test_an_old_image_in_use_is_never_deleted():
    images = [_img(f"sha256:{i}", 50 + i) for i in range(10)]
    doomed = ecr.select_deletions(images, in_use={"sha256:9"}, now=NOW)
    assert "sha256:9" not in {i["imageDigest"] for i in doomed} and len(doomed) == 5
