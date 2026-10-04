# Step 6 UAT cases and traceability

These acceptance examples connect software behavior to business decisions. Executable counterparts are in `tests/test_replenishment_planner.py`. Passing them establishes consistency with the declared policy, not proof of an optimal policy or realized business impact.

| ID | Business requirement | Given / When | Expected result |
|---|---|---|---|
| UAT-01 | Do not count late supply as available now | Stock 500; demand 100/day; 1,000 units arrive on day 10 | First shortage day 6; 400 unmet units on days 6–9; day 10 closing stock 900. No fictitious backlog. |
| UAT-02 | Use arrivals on their usable date | Zero opening stock; 100 units arrive in the morning; demand 100 | Demand fulfilled; zero unmet; closing zero. Exact sell-through alone is not a shortage. |
| UAT-03 | Separate urgent gap from normal-order quantity | Stock 500; demand 100/day; lead 10; review today then every 7 days; no safety buffer | Urgent review; 400 units unmet before arrival; order need 700 units for days 10–16. Do not add the earlier lost demand to the order. |
| UAT-04 | Bring review forward when useful | Stock 1,200; demand 100/day; next review day 5; lead 10; safety 2 days | First existing-only shortage day 13 is before scheduled arrival day 15. Review today; arrival day 10; coverage through day 14; net need 400 units. |
| UAT-05 | Retain regular review when feasible | Same as UAT-04 but stock 2,000 | Review day 5; arrival day 15; coverage through day 21; net need 300 units. |
| UAT-06 | Respect timing within the coverage window | No stock before day 10; demand 100/day; 5,000 existing units arrive day 12; coverage ends day 16; no buffer | Need 200 new units on day 10 to bridge days 10–11 despite abundant later supply. |
| UAT-07 | Ignore receipts outside the decision window for order sizing | Add a large PO arriving after coverage end | Current net order need is unchanged. Later supply may independently create an excess alert. |
| UAT-08 | Apply MOQ only to positive need | Net need zero or negative | Zero cases; no proposed order/arrival dates. |
| UAT-09 | Respect both MOQ and order multiple | Net need 25 units; 12/case; MOQ 10 cases; multiple 4 | 12 cases = 144 units. |
| UAT-10 | Convert units to valid cases | Net need 481 units; 24/case; MOQ 20; multiple 10 | 30 cases = 720 units. |
| UAT-11 | Expose excessive committed supply | Stock 10,000; demand 100/day; no POs; max cover 60 days | 4,000 units above 60-day demand; no order; review excess. |
| UAT-12 | Avoid assuming overdue stock is available | An open PO has ETA on/before the cutoff | Stop with an explicit ETA exception. Require a credible future ETA. |
| UAT-13 | Stress the same decision | Compare base, demand +/-20% and arrival +7 days | Same proposed cases/order date; delayed scenario moves arrivals by seven days; no hidden reoptimization. |
| UAT-14 | Reject stale analytical inputs | Historical input/policy fingerprint differs from the stored forecast | Stop before loading recommendations. |
| UAT-15 | Preserve prior valid output on write failure | Simulated database insert failure | Roll back the planner refresh; do not commit partial new output. |
| UAT-16 | Explain cover honestly | Physical stock exceeds all 84 days of forecast demand | Display 84 with `stock_cover_capped=1`, meaning cover is at least the available horizon; do not invent a longer precise cover. |

## Data-layer acceptance

- Expected rows: 1 planning run; 6 recommendations; 4,032 daily projections; 24 scenario summaries.
- The 17 SQL integrity checks return zero failures.
- Source sales, physical inventory, existing PO lines and forecast records are not modified by the planner.
- Every recommendation has a forecast reference, policy snapshot, supplier, quantities, costs and action code.
- Every projection satisfies exact Decimal stock conservation, demand fulfillment and daily continuity in Python.
- The base order prevents additional shortages from its normal arrival through cycle end and leaves the specified cycle-end buffer. Earlier shortages remain explicit.

## Business review after execution

The learner acts as the demo Supply Chain Planner. Review SKU 001's early gap, the case-rounding effect for SKUs 002/003/006, SKU 004's zero-order outcome, and SKU 005's committed-supply excess. Confirm that no normal import is described as resolving demand that occurs before its arrival.

Record local execution results separately from this authoring checklist. A UAT sign-off is not implied merely by providing the checklist.
