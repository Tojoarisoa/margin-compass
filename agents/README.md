# agents/: Margin Compass agents

PLAN.md §8, ADR-003, ADR-010 (LangGraph, pinned), ADR-013, ADR-014. **M1-06** ships the one-node
**Cost-to-Serve Analyst (AG-03)** and a five-question replay evaluation. All data is synthetic.

```bash
cd agents
uv sync
uv run pytest -q                       # scripted model, no network: graph, tools, verifier, budget, replay
uv run mc-agents eval                  # replay evals/m1_06 fixtures ($0, no network)
uv run mc-agents eval --mode record    # live Bedrock: re-record fixtures (< $0.01 for the set)
uv run mc-agents ask "What was bc-t0003's AI gross margin in September 2025?"   # live
```

Gold defaults to `../data/local/gold`; run `mc-pipeline run` first.

## Graph

```text
START -> analyst (LLM, Mid tier) --toolUse--> tools (deterministic) --> analyst
                     \--text--> verify (deterministic ledger check) --pass--> END
                                         \--fail, 1 revision--> analyst; still failing -> withheld
```

| Piece | Code | Rule |
| --- | --- | --- |
| Tools | `mc_agents/tools/metrics.py` | `tenant_margin`, `tenant_ranking`, `portfolio_margin` over gold Parquet; read-only, validated, row-limited; all arithmetic in Decimal, money half-up to the cent |
| Ledger + verifier | `mc_agents/ledger.py` | every $, %, decimal, or separated figure in the answer must equal a tool value; at least one `[E#]` citation |
| Budget | `mc_agents/budget.py` | checked before each call: ≤ 8 calls, ≤ $0.01 per question (EV-10), 700 output / 12,000 input tokens per call |
| Provider | `mc_agents/llm.py` | Bedrock Converse via `us.` inference profiles; replay fixtures keyed by request hash (drift fails) |
| Cost line | `mc_agents/analyst.py` | computed from token usage × ADR-003 in-region prices, never by the model |
| Telemetry | `mc_agents/llm.py` | OTel GenAI attribute names, token counts, cost; **no prompt or answer content** |

## Replay evaluation (`evals/m1_06/`)

Five questions with the expected tool call and the figures the answer must contain. Scores per
question: `tool` (EV-07), `grounded` (EV-08), `correct`, `budget` (EV-10). Fixtures live in
`evals/m1_06/fixtures/<model>/` and are re-recorded when the prompt, tool schemas, graph, or model change.
