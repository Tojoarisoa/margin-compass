from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelVersion:
    model_name: str
    version: str
    artifact_uri: str
    card_uri: str
    metrics: dict
    trained_on: dict  # e.g. {"window_start": ..., "window_end": ..., "data_sha256": ...}
    run_id: str
    baselines: list[str] = field(default_factory=list)


class Registry(ABC):
    @abstractmethod
    def get_version(self, model_name: str, version: str) -> ModelVersion | None: ...

    @abstractmethod
    def register(self, mv: ModelVersion) -> bool:
        """Store a version. Returns False (and changes nothing) if it already exists."""

    @abstractmethod
    def get_alias(self, model_name: str, alias: str) -> str | None: ...

    @abstractmethod
    def set_alias(self, model_name: str, alias: str, version: str) -> None: ...


def should_promote(challenger: ModelVersion, champion: ModelVersion | None, metric: str = "wape") -> bool:
    """Stage 4 policy: promote only if the challenger beats (or ties) the champion on `metric`
    (lower is better). With no champion yet, the first version is promoted. Baselines: in M1 the
    seasonal-naive model *is* the baseline; M3-01 adds ETS and requires beating both (EV-02)."""
    if champion is None:
        return True
    new, old = challenger.metrics.get(metric), champion.metrics.get(metric)
    if new is None:
        return False
    return old is None or new <= old
