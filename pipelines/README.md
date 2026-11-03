# pipelines/: ingest and transform

Stage 1 (ingest) and Stages 2–3 (transform, validate) of PLAN.md §6.2, as one command with one `run_id`.

```bash
cd simulator && uv run booncore-sim --out ../data/local/landing/booncore   # synthetic landing files
cd ../pipelines
uv sync
uv run mc-pipeline run --ingest-date 2026-11-03                            # ingest + dbt build
uv run pytest -q                                                           # 14 tests
```

| Step | Code | Output (under `data/local/`, git-ignored) |
| --- | --- | --- |
| Ingest: manifest reconcile (SHA-256, rows), `synthetic=true`, contract schema; quarantine on any failure | `mc_pipelines/ingest.py`, `contracts.py` | `bronze/<source>/ingest_date=…/`, `bronze/_manifests/`, `quarantine/` |
| Silver: token cost priced against the effective-dated catalog; invoices daily-ized exact to the cent | `transform/models/silver/` | `silver/*.parquet` |
| Gold: `fct_llm_usage_daily`, `fct_revenue_daily`, `fct_tenant_margin`, `agg_exec_kpis` | `transform/models/gold/` | `gold/*.parquet` |

dbt runs on DuckDB (`dbt-duckdb`); paths, the ingest date, and the simulated window are passed as dbt vars by `mc-pipeline`.

## M1 rules (revisit in M2)

- AI-feature revenue = the daily-ized AI add-on, attributed to **F1**, the only AI feature in M1. The multi-feature allocation rule is decided in M2-01 (it affects KPI-01).
- Cost-to-serve = LLM token cost only; shared-infrastructure allocation arrives in M2-02.
- KPIs computed: KPI-01 (AI gross margin), KPI-03 (LLM attribution coverage), KPI-04 (unprofitable tenants and their ARR). All rows carry `feature_scope = 'F1 only (M1)'`.
- With F1 alone, KPI-01 is about 98% (see the landing data contract's known limitations).

## AWS (env `dev`)

The same code runs as a container Lambda, `mc-dev-data-pipeline` (stack `mc-dev-data`, `infra/`): simulator → ingest → `dbt build` in `/tmp`, then upload to `s3://mc-dev-data-lake-<account>/{landing,bronze,silver,gold,quarantine}/`. No schedule yet (M1-08).

```bash
aws lambda invoke --function-name mc-dev-data-pipeline --cli-binary-format raw-in-base64-out \
  --payload '{}' --cli-read-timeout 900 out.json && cat out.json
```

- Image: `pipelines/Dockerfile` (build context: repo root). Dependencies come from the uv lockfiles and sit in their own layer, so code changes rebuild in seconds. Don't `docker image prune` during development: with the classic builder that deletes the build cache.
- **Lambda has no `/dev/shm`**, so POSIX semaphores fail. When `AWS_LAMBDA_FUNCTION_NAME` is set, `mc_pipelines.cli` swaps dbt's multiprocessing locks for thread locks and its `ThreadPool` for an executor-backed pool before importing dbt (`_make_dbt_lambda_safe`). A test reproduces Lambda on any machine by making semaphores fail, with a control test that fails without the patch.
- Cold starts of the ~1.6 GB image can exceed Lambda's 10-second init phase; Lambda then retries init inside the invocation (harmless for batch jobs).
