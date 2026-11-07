"""Engineering lever replay v1 (calc-spec/README.md, ADR-016). Integer arithmetic only. Synthetic inputs only."""

from __future__ import annotations

from typing import Any

from mc_agents.tools.pricing import round_div

SAFETY_RECALL_FLOOR_BPS = 9900  # KPI-08b: a lever that drops safety-event recall below 99% is rejected.

_FIELDS = (
    "cost_cents", "route_bps", "cheap_cost_ratio_bps", "cache_hit_bps", "quality_bps", "quality_drop_bps",
    "guardrail_bps", "recall_bps", "recall_drop_bps",
)


def replay_lever(lv: dict[str, Any]) -> dict[str, int | bool]:
    """Replay one feature-month of traffic under a routing + caching lever.

    `route_bps` of traffic moves to a cheaper tier costing `cheap_cost_ratio_bps` of the baseline per call;
    `cache_hit_bps` of the remaining spend is avoided. Quality and safety recall fall in proportion to the routed
    share (`quality_drop_bps`, `recall_drop_bps` at 100% routing). The lever is rejected when quality drops more
    than `guardrail_bps` or recall falls below the floor.
    """
    for f in _FIELDS:
        v = lv[f]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise ValueError(f"{f} must be a non-negative integer")
    for f in ("route_bps", "cache_hit_bps", "quality_bps", "recall_bps", "quality_drop_bps", "recall_drop_bps"):
        if lv[f] > 10000:
            raise ValueError(f"{f} must be at most 10000")
    cost = lv["cost_cents"]
    routed_base = round_div(cost * lv["route_bps"], 10000)
    routed_new = round_div(routed_base * lv["cheap_cost_ratio_bps"], 10000)
    kept = cost - routed_base
    cache_saved = round_div((kept + routed_new) * lv["cache_hit_bps"], 10000)
    new_cost = kept + routed_new - cache_saved
    savings = cost - new_cost
    quality_loss = round_div(lv["quality_drop_bps"] * lv["route_bps"], 10000)
    recall_loss = round_div(lv["recall_drop_bps"] * lv["route_bps"], 10000)
    recall_after = max(0, lv["recall_bps"] - recall_loss)
    quality_ok = quality_loss <= lv["guardrail_bps"]
    recall_ok = recall_after >= SAFETY_RECALL_FLOOR_BPS
    allowed = quality_ok and recall_ok
    return {
        "routed_base_cents": routed_base, "routed_new_cents": routed_new, "cache_saved_cents": cache_saved,
        "new_cost_cents": new_cost, "savings_cents": savings, "quality_loss_bps": quality_loss,
        "quality_after_bps": max(0, lv["quality_bps"] - quality_loss), "recall_after_bps": recall_after,
        "quality_ok": quality_ok, "recall_ok": recall_ok, "allowed": allowed,
        "applied_savings_cents": savings if allowed else 0,
    }
