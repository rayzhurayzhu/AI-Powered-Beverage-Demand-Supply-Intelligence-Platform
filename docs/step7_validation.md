# Step 7 validation record and report acceptance

## Completed during authoring

- Six Python tests passed: pooled WAPE versus mean-of-percentages, excluded/future observations, inclusive 28-day boundaries, zero denominator, nullable future actuals with decimal forecasts, and reporting schema drift.
- The complete existing synthetic Step 4/5/6 fixture was used to exercise all eleven reporting views and the full CSV publication process.
- SQL logic was executed in SQLite with explicit MySQL dialect adaptations for date functions and view syntax. Decimal revenue comparison used a small tolerance in SQLite; the delivered MySQL SQL retains exact decimal reconciliation.
- SQL result-set sizes: **11, 8, 1, 6, 2**. All eight adapted checks returned zero. All view row counts matched their expected values.
- Independently computed Python KPI values matched the adapted SQL KPI query.
- All eleven CSV headers, row counts and export IDs were checked after writing. Power Query reference files exist for every table.
- DAX table/column references were checked against the exported schemas. This does **not** constitute execution of DAX or Power Query.
- No live MySQL server or Power BI Desktop engine was used in the authoring environment. Native SQL, connector behavior, Power Query evaluation, DAX filter behavior and visual rendering remain user-side acceptance steps.

## Expected scope and counts

| Table | Rows |
|---|---:|
| ReportContext | 1 |
| DimDate | 2922 |
| DimProduct | 6 |
| DimChannel | 3 |
| DimWarehouse | 1 |
| DimStress | 4 |
| DimPlanPath | 2 |
| FactSales | 18072 |
| FactForecast | 714 |
| FactDecision | 6 |
| FactProjection | 4032 |

Forecast rows contain 210 selected-model holdout predictions and 504 production predictions. Dates do not overlap between phases. Candidate forecasts are deliberately excluded from the BI forecast total.

## Expected unfiltered cards

| Card | Value |
|---|---:|
| Revenue last 28 days SGD | 32470.91 |
| Units last 28 days | 15098 |
| Holdout WAPE ratio | 0.1181533857673867 |
| Stockout-risk SKUs, 14 days | 1 |
| Physical stock units | 10314 |
| Existing inbound units | 13440 |
| Proposed normal purchase SGD | 4650.00 |
| Excess-commitment SKUs | 1 |

Display WAPE as 11.82%. The holdout has 210 SKU-days, with 2 zero-stock SKU-days excluded from the available-stock score. This is not an average of six SKU error percentages.

## User acceptance checklist

1. Execute SQL 10 and SQL 11 in MySQL; verify all counts and eight checks.
2. Run the Python exporter and require `POWER BI EXPORT OK`.
3. Load eleven tables in Desktop with no conversion errors. Keep pDataRoot and BeverageBundle unloaded.
4. Create the fourteen specified single-direction relationships; no fact-to-fact or many-to-many links.
5. Mark DimDate using calendar_date; sort year_month by year_month_sort.
6. Clear product/brand filters and reconcile all eight first-page cards with SQL and expected_kpis.json.
7. Filter to SKU 001: first shortage is 2026-10-04, proposed order is 40 cases / 960 units, purchase SGD 1440, normal arrival 2026-10-21, and urgent review remains visible.
8. Filter to SKU 005: zero recommended cases, blank proposed dates, and excess commitment review.
9. On Supply Chain, explicitly select one stress and one path. The projection must respond to them; base recommendation quantities must stay fixed. Removing or making either selection ambiguous should blank the projection measures.
10. On Forecast & Insights, future actuals remain blank, holdout excludes two flagged SKU-days in the unfiltered available-stock score, and the all-days score is visible separately.
11. Re-export unchanged source data, wait for success, then refresh Desktop. KPI values should remain unchanged while the export timestamp/version folder advances.
12. Save the PBIX and screenshots. Record actual local results; this checklist is not a pre-signed UAT approval.
