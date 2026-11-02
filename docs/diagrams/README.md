# Architecture diagrams

Diagrams are code. Each `*.py` script here renders the PNG with the same name, using the
[`diagrams`](https://pypi.org/project/diagrams/) library (MIT, pinned to 0.25.1) and the official
AWS Architecture Icons it bundles. AWS permits their use in architecture diagrams.

| Diagram | Used in |
| --- | --- |
| `overview.png` | ADR-002, PLAN.md §10.1 |
| `pipeline.png` | ADR-004 |
| `edge.png` | ADR-006, ADR-012 |
| `telemetry.png` | ADR-007, ADR-015 |
| `retrieval.png` | ADR-008 |
| `dashboard.png` | ADR-009 |
| `agent_state.png` | ADR-010, ADR-011 |

The agent graph (ADR-013) and BoonCore's lever constraints (ADR-017) are Mermaid diagrams written
inline in those ADRs, because they contain no AWS services. GitHub renders them natively.

## Regenerate

Requirements: [uv](https://docs.astral.sh/uv/) and Graphviz (`dot` on `PATH`).

```bash
# Graphviz, either way:
brew install graphviz                                      # may compile from source on Intel Macs
mamba create -p ./.gv-env -c conda-forge graphviz          # prebuilt; then: export PATH="$PWD/.gv-env/bin:$PATH"

docs/diagrams/render.sh
```

Change a diagram by editing its script, re-rendering, and committing both the script and the PNG.
Shared styling lives in `_style.py`.
