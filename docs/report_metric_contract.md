# Report metric contract

## Grains and relationships

| Table | Grain | Important behavior |
|---|---|---|
| ReportContext | One selected export scope | Disconnected metadata; identifies scenario and cutoff. |
| DimDate | Calendar date | One date key; contiguous 2020–2027 calendar. |
| DimProduct | Beverage SKU | Brand/category/pack attributes; common filter for all four facts. |
| DimChannel | Sales channel | Filters FactSales only. |
| DimWarehouse | Warehouse | Common filter; one warehouse in this MVP. |
| DimStress | Stress assumption | Filters projections only. |
| DimPlanPath | Existing-only or proposed-order path | Filters projections only. |
| FactSales | Date × SKU × warehouse × channel | Outbound fulfilled sales and revenue. |
| FactForecast | Target date × SKU × warehouse | Selected holdout or production model; one run and origin per phase. |
| FactDecision | SKU × warehouse, at cutoff | One-cycle base recommendation and current physical/inbound supply. |
| FactProjection | Date × SKU × warehouse × stress × path | Expected physical stock and unmet demand under explicit assumptions. |

Dimension filters flow one way into facts. Never relate facts directly. The as-of FactDecision snapshot has no DimDate relationship. ReportContext is disconnected. Candidate models and extra run IDs are filtered out before import.

## KPI ownership and aggregation

| Metric | Definition and period | Owner / use |
|---|---|---|
| Revenue last 28 days | Sum warehouse outbound revenue, cutoff-27 through cutoff | Commercial; fixed recent performance. |
| Outbound units last 28 days | Sum fulfilled units over the same inclusive window | Commercial; not verified unconstrained demand. |
| Holdout WAPE | Sum absolute forecast errors / sum actual units on eligible holdout SKU-days | Forecast owner; lower is better, not 100-WAPE accuracy. |
| Holdout bias | Sum(forecast-actual) / sum(actual) | Forecast owner; positive overforecast, negative underforecast. |
| Physical stock | Sum cutoff on-hand units across selected SKUs/warehouses | Supply Chain; never sum over dates. |
| Existing inbound | Sum open-order units at cutoff | Supply Chain; not yet physical stock; arrivals must remain dated in projections. |
| Proposed normal imports | Cases × snapshotted landed case cost | Planner; proposed purchase spend, not realized benefit. |
| Stockout-risk SKUs, next 14 days | Distinct SKUs with positive base existing-only unmet demand in 14 days | Planner; urgency indicator, not historical stockout rate. |
| Excess-commitment SKUs | Distinct SKUs with positive committed excess quantity | Planner; quantity screen including timely inbound, not expiry loss. |
| Projected closing units | Last visible forecast date's closing units, one stress and one path | Planner; on a daily chart, that day's physical closing balance. |
| Projected unmet units | Sum unmet expected demand across selected forecast dates, one stress/path | Planner; expected shortfall, not observed lost-sales revenue. |

Aggregate WAPE is weighted by actual quantities through pooling, not by averaging SKU percentages. The zero-stock exclusion applies to the target day; the all-days score is retained for transparency. Excluded counts across products are SKU-days, not distinct calendar days.

## Filter contract

- Product/brand and warehouse: filter commercial, forecast, decisions and projection facts.
- Date: filters sales, forecast lines and projections. Fixed last-28-day and whole-holdout measures deliberately override it; labels state their periods.
- Channel: filters commercial sales only. A channel forecast or channel stock allocation has not been modeled.
- Stress/path: filter projections only. The base recommendation is frozen in sensitivity analysis.
- Maximum stock cover, dates and SKU error percentages: do not sum them.

## Honest analytics scope

Promotion/non-promotion charts are descriptive comparisons, not causal uplift. Holidays exist in the date dimension, but the current forecasting baselines do not estimate a separate causal holiday driver. No weather model, outlet/region analysis, batch expiry or verified lost demand exists yet. A future copilot must follow the same metric definitions and cite its analytical inputs.

## Refresh and lineage

The exporter recomputes/checks the forecast and planner against their source inputs before reading reporting views. It checks grains, counts, foreign keys and temporal boundaries. CSVs have an export ID; the manifest has schema, hashes, planning input fingerprint and KPI benchmarks. Power Query enforces schema, counts and a consistent batch ID; it does not recompute the SHA-256 hashes. Treat generated export files as immutable.

The latest pointer is published only after a complete export. Power BI refresh must occur after export finishes. This is a single-writer local pipeline; a concurrent enterprise refresh/serving architecture is not claimed.
