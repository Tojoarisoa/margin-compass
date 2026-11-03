from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from .base import ModelVersion, Registry


class FileRegistry(Registry):
    """Local registry: one JSON index file (local-first development and tests)."""

    def __init__(self, index_path: Path) -> None:
        self.path = Path(index_path)

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {"models": {}}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        os.replace(tmp, self.path)  # atomic on the same filesystem

    def get_version(self, model_name: str, version: str) -> ModelVersion | None:
        entry = self._load()["models"].get(model_name, {}).get("versions", {}).get(version)
        return ModelVersion(**entry) if entry else None

    def register(self, mv: ModelVersion) -> bool:
        data = self._load()
        versions = data["models"].setdefault(mv.model_name, {"versions": {}, "aliases": {}})["versions"]
        if mv.version in versions:
            return False
        versions[mv.version] = asdict(mv)
        self._save(data)
        return True

    def get_alias(self, model_name: str, alias: str) -> str | None:
        return self._load()["models"].get(model_name, {}).get("aliases", {}).get(alias)

    def set_alias(self, model_name: str, alias: str, version: str) -> None:
        data = self._load()
        model = data["models"].setdefault(model_name, {"versions": {}, "aliases": {}})
        if version not in model["versions"]:
            raise KeyError(f"{model_name} has no version {version}")
        model["aliases"][alias] = version
        self._save(data)
