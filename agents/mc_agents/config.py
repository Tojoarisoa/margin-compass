"""Models, prices, and per-question budgets (ADR-003, PLAN.md §8.3, §8.7, EV-10).

Prices are the us-east-1 on-demand **in-region** rates recorded in ADR-003 (AWS Price List API,
2026-11-04), in USD per 1M tokens. In-region is the higher of in-region and global, so caps computed
from it are conservative. A test keeps this table equal to the ADR.

Invocation uses the `us.` cross-region inference profiles: Bedrock rejects on-demand calls to the
in-region Claude Haiku 4.5 ID ("on-demand throughput isn't supported", 2026-11-04).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ModelSpec:
    key: str
    model_id: str
    label: str
    tier: str
    input_per_m: Decimal
    output_per_m: Decimal
    cache_read_per_m: Decimal
    invoke_id: str = ""  # what Converse is called with; an inference profile where on-demand needs one

    @property
    def target(self) -> str:
        return self.invoke_id or self.model_id


MODELS: dict[str, ModelSpec] = {
    "haiku-5-5": ModelSpec("haiku-5-5", "anthropic.claude-haiku-5-5", "Claude Haiku 5.5", "mid",
                           Decimal("0.11"), Decimal("0.55"), Decimal("0.011"), "us.anthropic.claude-haiku-5-5"),
    "haiku-4-5": ModelSpec("haiku-4-5", "anthropic.claude-haiku-4-5-20251001-v1:0", "Claude Haiku 4.5", "mid",
                           Decimal("1.10"), Decimal("5.50"), Decimal("0.11"), "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
    "nova-micro": ModelSpec("nova-micro", "amazon.nova-micro-v1:0", "Amazon Nova Micro", "small",
                            Decimal("0.035"), Decimal("0.14"), Decimal("0.00875"), "us.amazon.nova-micro-v1:0"),
}
DEFAULT_ANALYST_MODEL = "haiku-4-5"  # interim Mid default (owner, 2026-11-04): Haiku 5.5 not yet available to the account (ADR-003)

MAX_LLM_CALLS_PER_QUESTION = 8          # PLAN.md §8.3 / ADR-013 hard cap
MAX_USD_PER_QUESTION = Decimal("0.01")  # EV-10 target, enforced as a hard cap
MAX_OUTPUT_TOKENS_PER_CALL = 700        # per-request token ceiling (§8.7 lever 5)
MAX_INPUT_TOKENS_PER_CALL = 12_000
MAX_TOOL_ROUNDS = 3
MAX_REVISIONS = 1                       # verifier feedback rounds (PLAN.md allows ≤ 2; M1 uses 1)
