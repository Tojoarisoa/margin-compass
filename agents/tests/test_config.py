from decimal import Decimal
from pathlib import Path

from mc_agents.config import MODELS

ADR = Path(__file__).resolve().parents[2] / "docs" / "adr" / "003-llm-provider-and-models.md"


def _adr_rows() -> dict[str, list[str]]:
    rows = {}
    for line in ADR.read_text().splitlines():
        if line.startswith("| `"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            rows[cells[0]] = cells[1:]
    return rows


def test_prices_match_adr003_in_region_rows():
    rows = _adr_rows()
    for spec in MODELS.values():
        label = f"`{spec.model_id}`" + (" (in-region)" if spec.model_id.startswith("anthropic.") else "")
        input_, output, cache_read = rows[label][:3]
        assert (Decimal(input_), Decimal(output), Decimal(cache_read)) == (
            spec.input_per_m, spec.output_per_m, spec.cache_read_per_m), spec.key


def test_invocation_uses_us_inference_profiles():
    assert all(m.target.startswith("us.") for m in MODELS.values())
