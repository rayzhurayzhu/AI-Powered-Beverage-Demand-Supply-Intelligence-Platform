# Step 4 Model Contract

## Scope and provenance

- Scenario ID: `beverage_demo_v1`.
- All sales, prices, inventory, orders and business parameters are **synthetic**.
- Holiday flags come from the already-loaded public calendar; programmed demand responses are simulation assumptions, not empirical estimates of Singapore beverage behavior.
- History: 2024-01-01 through 2026-09-30; snapshot is end-of-day 2026-09-30.
- No future actual sales, actual receipts or future-placed orders are generated. Expected arrival dates after the cutoff remain valid planning information.
- Six SKUs, one warehouse, three outbound customer channels, one preferred supplier per SKU/warehouse.

## Grains and units

| Table | Grain | Quantity unit |
|---|---|---|
| fact_sales | Scenario × date × SKU × warehouse × channel | Individual cans/bottles |
| fact_inventory | Scenario × date × SKU × warehouse | Individual cans/bottles |
| fact_purchase_orders | Scenario × PO line | Whole cases and their individual-unit equivalent |

Quantities from different SKU sizes should not be labeled liters. To calculate physical beverage volume, multiply units by each product's unit_volume_ml and divide by 1000. Monetary values are SGD and synthetic warehouse selling prices/costs, not consumer retail benchmarks.

Order-time `units_per_case_on_order` and landed cost are snapshotted on each PO line. Product case sizes are immutable in this MVP. Received lines are fully received; open lines have zero receipts and NULL actual receipt dates. No partial receipt or split shipment model is implemented.

`dim_scenario.assumptions_json` captures the input master data, seed, generator version, historical calendar flags, runtime version and output hashes. Re-running the same scenario replaces its fact rows atomically and preserves other scenarios.

## Generation assumptions

- Base daily unit rates for SKUs 1–6: 100, 65, 80, 45, 130 and 75.
- Initial stock equals 45 times each base rate. This is an opening balance; no fictitious pre-history receipt is inserted.
- Channel demand shares are 50%, 30%, 20%, before seasonal, trend, weekend, holiday, promotion and random factors.
- A 10% sinusoidal seasonal component, a daily trend factor, and 15% random variation are explicitly programmed. Public holidays multiply requested demand by 1.20. The synthetic promotion schedule and a 1.25 demand multiplier are also programmed; none is a causal finding.
- Requested demand is capped by available stock and allocated proportionally using integer largest remainders. The latent requested demand is not persisted as a forecast input. No backorders are carried.
- Zero closing stock is stored as `zero_stock_flag`. It does not quantify lost demand or prove how long during the day a stockout lasted.
- Historical order reviews start at end of 2024-01-01 and recur at the policy interval. They use trailing seven-day fulfilled sales and inventory position. No future demand is used to place historical orders.
- Historical target factors for SKUs 1–6 are 0.75, 1.0, 1.0, 1.2, 1.7 and 0.9, deliberately creating differing supply behavior for demonstration. These are not an optimized recommendation.
- Orders respect minimum order cases and case multiples. Every order arrives in full on its expected date, based on fixed calendar-day lead time. Warehouse closure calendars and uncertain supplier delays are not yet modeled.
- No returns, spoilage, transfers, cancellations, shared freight constraints, storage-capacity constraints or expiry claims are included.

## Point-in-time and forecast boundaries

All current PO statuses describe the final scenario cutoff. For a historical backtest, reconstruct order/receipt availability from event dates rather than using final statuses or future actual receipt knowledge. The historical calendar comes from the current source snapshot and is not a full archive of past publication versions.

For a first uncensored baseline, explicitly handle or exclude demand observations affected by stock unavailability. Observed sales are not always unconstrained demand. Do not train or score on future targets, and do not treat known simulation coefficients as learned business effects.

The supplied 28-day sales rate and days-of-supply snapshot are descriptive. A stockout/excess decision must subsequently consider forecast uncertainty, dated inbound receipts and the planning horizon. Expiry risk needs batch/remaining-shelf-life information. This module does not yet solve those downstream decisions.
