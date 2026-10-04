# Baseline forecasting methodology and limitations

## Grain and units

Training observations aggregate warehouse outbound sales across the three channels to one daily SKU/warehouse series. Forecasts are individual cans/bottles, not cases. Fractional expected quantities are retained to four decimal places; procurement rounding belongs in the decision engine, not in daily forecasts.

Run `baseline_v1_20260930` uses scenario `beverage_demo_v1`. It has 1,004 historical days, 2024-01-01 through 2026-09-30. Every expected day is required, including valid zero-sales days. Missing rows are rejected instead of interpreted as zero demand.

## Candidate definitions

- `mean_28`: mean of the last 28 adjusted training observations, constant over the horizon.
- `weekday_mean_56`: mean of the eight observations for each weekday in the last 56 adjusted training days, repeated by target weekday.
- `seasonal_naive_7`: last week's adjusted value for the matching weekday, repeated weekly across the horizon.

All candidates use the same causal preprocessing. These are not confidence intervals or probabilistic forecasts. They do not directly use holiday, promotion or weather covariates. The source contains such information, but a future model must demonstrate incremental value and respect feature availability before making driver claims.

## Censoring and imputation

The Step 4 stock balance constrains fulfilled sales. A zero closing balance is treated as a *potential* censoring signal. It may include exact sell-through without lost demand; in real data, an end-of-day balance may also miss intraday shortages.

For a flagged training day, average up to eight **earlier observed non-flagged** values with the same weekday. If none exist, average up to 28 earlier observed non-flagged values. If no earlier usable observations exist, stop. Imputed values are never added to the observed reference pool. No later observations, holdout actuals, future promotions, or generator latent demand enter the training adjustment. The approach is a heuristic and may use stale observations when prolonged shortages occur.

This is an estimated planning signal, not a measured unconstrained-demand series. Excluding flagged target days from an evaluation creates a conditional score that may be optimistic for shortage-prone products. Always report both scopes and excluded counts.

## Temporal evaluation

| Split | Forecast origin at end of day | Target period | Purpose |
|---|---|---|---|
| Validation 1 | 2026-05-13 | 2026-05-14–2026-06-17 | Model selection |
| Validation 2 | 2026-06-17 | 2026-06-18–2026-07-22 | Model selection |
| Validation 3 | 2026-07-22 | 2026-07-23–2026-08-26 | Model selection |
| Holdout | 2026-08-26 | 2026-08-27–2026-09-30 | Independent final evaluation |
| Production | 2026-09-30 | 2026-10-01–2026-12-23 | Future planning input |

At each origin, preprocessing and model estimates use only observations through that origin. Forecasts remain fixed for the entire 35-day window; they do not ingest actual values as the window progresses. Later folds can legitimately use earlier folds' now-observed history.

Select one candidate per SKU/warehouse using pooled validation WAPE on available-stock days. Do not average fold percentages. Ties favor candidate order: `mean_28`, then `weekday_mean_56`, then `seasonal_naive_7`. Require at least 14 available-stock days per validation fold and for the selected holdout. This is an evidence floor, not a statistical guarantee.

The holdout has no role in selection. After reporting its score, refit the selected method with all history through the production cutoff. If future development repeatedly tunes against this holdout, it stops being a fresh test; allocate a new evaluation period or use nested temporal validation.

Only 35-day forecasts are tested here. Extending output to 84 days supports planning but does not establish long-horizon accuracy. The backtest design must expand if future policies require a protection period longer than 35 days.

## Metrics

For scored observations with actual outbound quantity `y` and forecast `f`:

```text
MAE = sum(abs(f - y)) / scored_days
WAPE percent = 100 * sum(abs(f - y)) / sum(y)
Bias percent = 100 * sum(f - y) / sum(y)
```

Positive bias means overforecast. Zero denominator produces SQL NULL / Python None, not zero error. There is no per-day MAPE division by zero. WAPE is an error measure, not a universal accuracy percentage.

Each candidate/fold has `all_days` and `available_stock` scores. The latter excludes target dates with zero closing stock. Actuals are read from historical sales and never fabricated for the production horizon. The data-quality flags and forecast errors answer different questions.

## Reproducibility and audit

The run records its version, cutoff, policies, source-input SHA-256, generation timestamp and assumptions. CSVs also have hashes. Runtime and creation timestamp need not match across machines; identical model inputs should produce identical predictions and selection.

Rerunning this named run intentionally replaces it transactionally. Once later planner outputs depend on it, introduce a new run ID or coordinate the downstream rebuild instead of silently rewriting referenced results. The future planner should compare source fingerprints and policy snapshots before using a forecast.

## References

- Hyndman and Athanasopoulos, Forecasting: Principles and Practice, time series cross-validation: https://otexts.com/fpp3/tscv.html
- Forecast accuracy and held-out evaluation: https://otexts.com/fpp3/accuracy.html
- MySQL Connector/Python transaction API: https://dev.mysql.com/doc/connector-python/en/connector-python-api-mysqlconnection-start-transaction.html
- MySQL Connector/Python batch execution: https://dev.mysql.com/doc/connector-python/en/connector-python-api-mysqlcursor-executemany.html
