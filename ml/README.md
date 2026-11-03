# ml/: models and model registry

PLAN.md §6.2 Stage 4. M1-04 ships a **stub**: the seasonal-naive AI COGS forecaster, registered and promoted through the real registry. M3-01 replaces it with the trained forecaster and the ETS baseline (EV-02).

```bash
cd ml
uv sync
uv run pytest -q    # 10 tests (forecaster, promotion policy, file and DynamoDB registries)
```

The pipeline (`mc-pipeline run`, and the AWS Lambda) runs training after a successful dbt build.

| Piece | Code | Local | AWS (dev) |
| --- | --- | --- | --- |
| Forecaster | `mc_ml/cogs_forecast/seasonal_naive.py` | — | — |
| Train step | `mc_ml/train.py` | writes `data/local/models/` and `gold/fct_forecasts.parquet` | same, uploaded to `s3://mc-dev-data-lake-<account>/models/` and `gold/` |
| Registry index | `mc_ml/registry/` | `data/local/models/registry.json` (`FileRegistry`) | DynamoDB `mc-dev-state-core` (`DynamoRegistry`), items `MODEL#<name>` / `VERSION#<v>` and `ALIAS#champion` |

- **Seasonal naive:** each forecast day repeats the same weekday of the last observed week; P10/P90 scale it by the 10th/90th percentile of week-over-week ratios. Horizon 30 days.
- **Backtest:** rolling origin, one step ahead, last 28 days: WAPE and P10–P90 coverage, written to `backtest.json` and the model card.
- **Versions** are a hash of the training data and parameters (`sn-…`): re-training on the same data registers nothing new.
- **Promotion (Stage 4 policy):** the first version becomes `champion`; later versions only if their WAPE is no worse. In M1 the seasonal-naive model is itself the baseline.
- Artifacts per version: `model.json`, `backtest.json`, `model_card.md` (labeled synthetic).
