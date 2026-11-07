// Engineering lever replay v1 (calc-spec/README.md, ADR-016). Integer arithmetic only; matches
// agents/mc_agents/tools/levers.py on every vector in calc-spec/vectors/levers_v1.json (EV-12). Synthetic inputs only.
import { roundDiv } from "./pricing.ts";

export const SAFETY_RECALL_FLOOR_BPS = 9900; // KPI-08b

export interface LeverInput {
  cost_cents: number;
  route_bps: number;
  cheap_cost_ratio_bps: number;
  cache_hit_bps: number;
  quality_bps: number;
  quality_drop_bps: number;
  guardrail_bps: number;
  recall_bps: number;
  recall_drop_bps: number;
}

export interface LeverResult {
  routed_base_cents: number;
  routed_new_cents: number;
  cache_saved_cents: number;
  new_cost_cents: number;
  savings_cents: number;
  quality_loss_bps: number;
  quality_after_bps: number;
  recall_after_bps: number;
  quality_ok: boolean;
  recall_ok: boolean;
  allowed: boolean;
  applied_savings_cents: number;
}

const CAPPED: (keyof LeverInput)[] = ["route_bps", "cache_hit_bps", "quality_bps", "recall_bps", "quality_drop_bps", "recall_drop_bps"];

export function replayLever(lv: LeverInput): LeverResult {
  for (const f of Object.keys(lv) as (keyof LeverInput)[]) {
    if (!Number.isSafeInteger(lv[f]) || lv[f] < 0) throw new Error(`${f} must be a non-negative integer`);
  }
  for (const f of CAPPED) if (lv[f] > 10000) throw new Error(`${f} must be at most 10000`);
  const cost = lv.cost_cents;
  const routedBase = roundDiv(cost * lv.route_bps, 10000);
  const routedNew = roundDiv(routedBase * lv.cheap_cost_ratio_bps, 10000);
  const kept = cost - routedBase;
  const cacheSaved = roundDiv((kept + routedNew) * lv.cache_hit_bps, 10000);
  const newCost = kept + routedNew - cacheSaved;
  const savings = cost - newCost;
  const qualityLoss = roundDiv(lv.quality_drop_bps * lv.route_bps, 10000);
  const recallLoss = roundDiv(lv.recall_drop_bps * lv.route_bps, 10000);
  const recallAfter = Math.max(0, lv.recall_bps - recallLoss);
  const qualityOk = qualityLoss <= lv.guardrail_bps;
  const recallOk = recallAfter >= SAFETY_RECALL_FLOOR_BPS;
  const allowed = qualityOk && recallOk;
  return {
    routed_base_cents: routedBase, routed_new_cents: routedNew, cache_saved_cents: cacheSaved,
    new_cost_cents: newCost, savings_cents: savings, quality_loss_bps: qualityLoss,
    quality_after_bps: Math.max(0, lv.quality_bps - qualityLoss), recall_after_bps: recallAfter,
    quality_ok: qualityOk, recall_ok: recallOk, allowed, applied_savings_cents: allowed ? savings : 0,
  };
}
