# knowledge/: the retrieval corpus (synthetic)

> **Everything here is synthetic.** BoonCore Inc., its tenants, contracts, and policies are fictional
> (docs/booncore-spec.md). Nothing here is legal or medical advice. Values marked *(assumption)* are
> unverified simulator parameters.

These Markdown files are the source of truth for the RAG index (PLAN.md §6.2 Stage 5). `rag/` parses
them, chunks them by `##` section, embeds each chunk, and upserts it into the vector index.

| Folder | Corpus (PLAN.md §6.2) | `tenant_id` metadata |
| --- | --- | --- |
| `policies/` | 1. Pricing, fair-use, discount-authority, and compliance policies | `all` |
| `contracts/` | 2. Per-tenant contract clauses | the tenant, e.g. `bc-t0003` |

M1-05 shipped the fair-use policy and three contracts; M4-01 adds the discount-authority matrix and the compliance-constraint policy. Playbooks (`playbooks/`), schema cards (`schema/`) and metric cards (`metrics/`) are added too; all shared documents use `tenant_id: all`.

## File format

Each file starts with a front-matter block between `---` lines, with one `key: value` per line:

| Key | Required | Meaning |
| --- | --- | --- |
| `doc_id` | yes | Stable ID; part of every chunk key. Lowercase letters, digits, `-`. |
| `title` | yes | Human-readable title. |
| `source_type` | yes | `policy`, `contract`, `playbook`, `schema` or `metric`. |
| `tenant_id` | yes | `all` for policies; the tenant ID for contracts. |
| `effective_date` | yes | ISO date the document takes effect. |
| `synthetic` | yes | Must be `true`. |

Each `##` heading starts a chunk. The line after the heading may carry the clause type as an HTML
comment, e.g. `<!-- clause: unlimited_ai -->`; otherwise the clause type is `general`.

Contract values (ARR, AI add-on, discount, dates, unlimited AI) match the simulator's `m1` profile
with seed 42 (`simulator/booncore_sim/tenants.py`); a test keeps them in sync.
