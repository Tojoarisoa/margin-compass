# Margin Compass

**AI cost-to-serve and gross-margin intelligence for B2B SaaS companies that ship AI features.**

Generative-AI features turned software's near-zero marginal cost into a real per-interaction inference cost. Yet most SaaS companies still can't answer three questions:

- Which customers and features make money after AI costs?
- Why did AI margin drop this month?
- What happens to margin and churn if we change pricing?

Margin Compass joins three sources: **LLM usage telemetry** (OpenTelemetry GenAI conventions), **cloud billing** (FOCUS), and **subscription revenue**. From them it computes daily cost-to-serve and margin per tenant × feature × model. A **LangGraph multi-agent system** then investigates margin leaks, simulates pricing and engineering options, checks them against contracts and policy, and proposes actions for humans to approve. Each proposal carries both its margin impact and its quality impact.

```text
Ingest ➔ Transform ➔ Validate ➔ Train ➔ Embed ➔ Evaluate ➔ Monitor / Deploy
```

| | |
| --- | --- |
| **Customer** | B2B SaaS (≈ $10M–$200M ARR) with generative-AI features in production |
| **Pain points** | Cost-to-serve blindness, late margin leaks, hidden unprofitable tenants, pricing by guesswork, unmanaged cost vs quality, unforecastable AI COGS |
| **Standout features** | Per-tenant margin waterfall, Pricing Simulator (churn-risk-adjusted), Cost–Quality Lab, contract-aware agents |
| **Architecture** | Serverless AWS (Lambda, Step Functions, S3, DynamoDB, S3 Vectors, Bedrock, CloudFront), DuckDB + dbt |
| **Agents** | LangGraph supervisor + 5 specialists, deterministic verifier, role-based human approval, durable checkpoints |
| **Proof of value** | Closed loop: approved actions change future simulated usage and revenue; recovered margin is measured against a forecast baseline |

## Start here

- **[PLAN.md](PLAN.md):** the master plan. §2 covers the problem and customer, §3 the positioning, §17 the roadmap.
- **[AGENTS.md](AGENTS.md):** rules and workflow for AI coding agents contributing to this repo.

## Disclaimer

The customer ("BoonCore Inc.") and its data are **synthetic**, generated with labeled ground truth for evaluation. The only real data is this platform's own AWS bill and its own agent telemetry. BoonCore is a fictional technical-support platform for medical device and imaging companies: nothing in this project is medical advice or a validated medical system, and no real patient data is used.
