# Step 5 validation record

## Authoring checks completed

- Eight executable Python unit tests passed: future-data isolation, weekly signal, causal imputation, known metric examples and zero denominators, holdout-independent model selection, repeatable output and dates, missing-history rejection, and rollback on a simulated insert failure.
- The full Step 4 authoring CSV dataset (18,072 sales rows and 6,024 inventory rows) passed Step 5 input validation and generated 3,024 forecast rows, 144 evaluation rows, and 6 model selections.
- The production portion contains 504 rows: 6 SKUs times 84 consecutive dates from 2026-10-01 to 2026-12-23.
- The five SQL verification result sets were exercised against an in-memory SQLite copy with explicit dialect adaptations for MySQL date expressions, decimal division, null-safe comparisons and table/view syntax. All ten checks returned zero and the result sizes were 5, 10, 6, 6 and 12 rows.
- This was **not** a live MySQL execution. The user must run SQL 06, the Python script and SQL 07 against the local MySQL server to validate actual connector, DDL, decimal and transaction behavior.

## Reference model results

These results come from the unchanged Step 4 authoring dataset. A changed holiday snapshot, source data, generator or policy can change results. The script calculates results; the values below are not hard-coded into the model.

| SKU | Selected model | Validation WAPE % | Holdout WAPE % | Holdout bias % | Excluded holdout days |
|---|---|---:|---:|---:|---:|
| DEMO-BEV-001 | weekday_mean_56 | 10.6471 | 13.4819 | 12.7806 | 2 |
| DEMO-BEV-002 | weekday_mean_56 | 9.2026 | 12.5781 | 10.4748 | 0 |
| DEMO-BEV-003 | weekday_mean_56 | 11.5164 | 11.4570 | 1.2476 | 0 |
| DEMO-BEV-004 | weekday_mean_56 | 10.4203 | 10.0528 | 6.9135 | 0 |
| DEMO-BEV-005 | weekday_mean_56 | 10.0518 | 12.6397 | 10.9588 | 0 |
| DEMO-BEV-006 | weekday_mean_56 | 11.3448 | 9.2197 | 4.3562 | 0 |

These are available-stock scores. Result 5 also exposes all-days scores. Positive bias indicates overforecast; it warrants attention before buying more stock. SKU 001 has 144 potentially censored training days over the full history, so its demand estimate requires particular caution. It is not evidence that 144 days of actual lost sales occurred.

All six SKUs happened to select the same candidate. Selection is still calculated independently by SKU and can change with inputs. Passing tests does not prove that this baseline is ready for real commercial decisions, that holiday effects are causal, or that a replenishment policy has delivered savings.

## User acceptance for this step

1. `FORECAST PIPELINE OK` appears after successful MySQL load.
2. SQL Result 1 equals 1 / 3024 / 144 / 6 / 504.
3. All ten integrity checks in Result 2 equal zero.
4. Result 3 contains six model selections with finite errors and explicit excluded-day counts.
5. Result 4 contains six complete 84-day forecasts and each SKU's own protection period.
6. Result 5 contains twelve holdout rows, with both evaluation scopes visible.

No arbitrary low error threshold is used to fake an acceptance gate. Data/software correctness is checked first; model quality is reviewed separately and compared with challengers later.
