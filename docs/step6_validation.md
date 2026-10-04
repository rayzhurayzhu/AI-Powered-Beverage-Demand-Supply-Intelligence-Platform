# Step 6 validation record

## Checks completed during authoring

- All **16 executable Python tests** passed. They cover review timing, early-review exceptions, zero-need MOQ behavior, case rounding, usable-date receipts, pre-arrival shortages, lost-sales handling, prefix deficits, late POs, excess quantity, overdue exceptions, cover limits, frozen stress plans, stale forecast rejection and failed-write rollback.
- The full unchanged Step 4 transaction fixture and Step 5 forecast fixture passed source verification and generated **6 recommendations, 4,032 daily projections and 24 sensitivity rows**.
- Exact stock/demand balances and continuity were checked using Python Decimal arithmetic.
- The five SQL result sets were exercised in an in-memory SQLite harness with dialect adaptations for MySQL dates, null-safe comparisons, decimal division and view syntax. SQLite uses floating point for DECIMAL, so its harness omitted the MySQL decimal CHECK constraints and used a small tolerance for floating-point balance comparisons. The production MySQL SQL retains exact DECIMAL constraints/comparisons. All **17 adapted query checks** returned zero.
- Result-set row counts were **4, 17, 6, 24 and 28**.
- This is **not a live MySQL test**. The user's SQL 08 / Python / SQL 09 execution is still required to validate the actual MySQL schema, connector, decimal behavior and transaction integration.

## Reference decisions

| SKU | Cases | Units | Purchase cost SGD | Action |
|---|---:|---:|---:|---|
| DEMO-BEV-001 | 40 | 960 | 1,440.00 | EXPEDITE_REVIEW |
| DEMO-BEV-002 | 20 | 480 | 960.00 | ORDER_AT_REVIEW |
| DEMO-BEV-003 | 30 | 720 | 1,200.00 | ORDER_AT_REVIEW |
| DEMO-BEV-004 | 0 | 0 | 0.00 | MONITOR |
| DEMO-BEV-005 | 0 | 0 | 0.00 | REVIEW_EXCESS |
| DEMO-BEV-006 | 70 | 840 | 1,050.00 | ORDER_AT_REVIEW |

Total proposed normal-order purchase cost is **SGD 4,650.00**, using synthetic landed costs. This total does not price additional expedite/transfer actions, and is not a savings or ROI estimate.

The net needs before case constraints are 915.2500, 192.2500, 455.2500, 0, 0 and 796.3750 units. Case sizes differ: SKU 006 has 12 units/case; the others have 24. The proposed case quantities are calculated from these needs and the seeded policies, not hard-coded by SKU.

With existing supply only, SKU 001 first has unmet forecast demand on 2026-10-04. A new normal order from the cutoff arrives on 2026-10-21, so the earlier 21.1875 expected units remain unmet unless a separate feasible intervention is arranged. SKU 005's 961.8750-unit excess refers to committed supply relative to 60-day demand, including POs within the window; it is not current physical-stock cover.

These are reference outputs for the unchanged synthetic source and model. They do not establish realized business value. A later rolling-policy comparison must use fair shared demand/supply assumptions and distinguish forecast uncertainty from observed data.

## Local acceptance to record

1. `PLANNING TABLES READY` after SQL 08.
2. `REPLENISHMENT PIPELINE OK` after Python commits.
3. SQL 09 Result 1: 1 / 6 / 4032 / 24.
4. SQL 09 Result 2: all 17 checks zero.
5. Result 3: six readable business decisions with valid units, dates, case rounding and labels.
6. Results 4 and 5: inspect stressed outcomes and the pre-arrival gap; do not expect stockout risk to be zero merely because integrity tests pass.
