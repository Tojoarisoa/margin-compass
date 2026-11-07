"""Churn / price-sensitivity model (PLAN.md §6.2 Stage 4, EV-11). numpy only."""

from .model import LogisticChurn, auc, brier, ev11_gate, reliability

__all__ = ["LogisticChurn", "auc", "brier", "ev11_gate", "reliability"]
