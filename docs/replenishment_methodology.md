# Replenishment methodology — deterministic one-cycle planner

## Intended use and assumptions

This is an auditable planning heuristic for the synthetic portfolio scenario. It is not a stochastic optimizer, a guaranteed service-level policy, an autonomous ordering system or a forecast of real company demand. One SKU/warehouse has one preferred supplier. Constraints are calendar-day lead time, review interval, case size, MOQ, order multiple, safety days and maximum cover. Shared containers, warehouse capacity, cash budgets, supplier capacity, expiry and partial receipts are out of scope.

The cutoff is end of 2026-09-30. Demand is the selected Step 5 daily forecast. Existing POs were placed no later than the cutoff, have zero received quantities, and have future expected usable arrival dates. The planner never learns future actual sales or receipt outcomes.

## Daily stock conservation

For each day, in this order:

```text
available = opening physical stock + existing morning receipts + proposed morning receipt
fulfilled = min(available, forecast demand)
unmet = forecast demand - fulfilled
closing physical stock = available - fulfilled
next day's opening = today's closing
```

All quantities are nonnegative. An exact zero closing balance is not itself a shortage: a shortage requires positive unmet forecast demand. Unmet units are lost for this model; they do not become backorders. Fractional units reflect expected quantities, not fractional cans physically sold. Purchase orders are rounded to integer cases.

## Review and order dates

The historical review anchor is 2024-01-01. Reviews occur at the end of each date separated from that anchor by a multiple of `review_period_days`. With seven-day reviews, the next review on or after the cutoff is 2026-10-05.

1. Project existing stock and dated existing POs with no additional order.
2. Find the first day with positive unmet demand in the 84-day window.
3. If this is before the normal arrival of an order placed at the next scheduled review, bring the proposed review forward to the cutoff. This is an exception review, not a reduced transport lead time.
4. Otherwise retain the scheduled review date.
5. Identify the first regular review strictly after that chosen review.
6. Normal arrival = chosen review date + lead time.
7. Coverage end = following regular review date + lead time - one day.

An exception order can therefore cover fewer than seven days before the next regular order could arrive. This preserves the existing review schedule. The proposed order is considered at end of day; its arrival is usable at the start of the arrival date, consistent with the synthetic transaction generator's date convention.

`latest_normal_order_date` equals the first projected shortage date minus lead time, if a shortage exists. It is a theoretical deadline under the existing-only projection and fixed lead-time assumption. A past date means a new normal order at the cutoff is already too late. It is not a recommendation to backdate an order.

## Time-phased net quantity

Let `B` be the existing-only projected closing stock immediately before the candidate arrival. This balance already respects historical-in-the-projection lost sales before arrival; those losses are not backlogged.

For each day from candidate arrival through coverage end, compute a virtual balance without the proposed order:

```text
virtual balance = B + cumulative existing receipts - cumulative forecast demand
```

Do not floor this virtual balance at zero during this calculation: the largest deficit identifies how many new units must arrive at the candidate arrival to prevent any intervening shortage. A receipt on a later date cannot offset an earlier deficit.

The end-of-cycle safety target equals the sum of forecast demand over the `safety_stock_days` immediately following coverage end. This is a day-based buffer heuristic, not a quantified probability of service.

```text
net required units = max(
    0,
    largest daily deficit during the coverage window,
    safety target - virtual balance at coverage end
)
```

Only dated receipts through the relevant day enter the calculation. A receipt after coverage end cannot reduce this order. To retain a simple day-based safety target, receipts after coverage end are not netted against the buffer target; this assumption can be revisited as the policy evolves.

## Case and cost conversion

```text
If net required units <= 0:
    recommended cases = 0
Otherwise:
    raw cases = ceiling(net required units / units per case)
    recommended cases = ceiling(max(raw cases, MOQ cases) / order multiple cases)
                        * order multiple cases
recommended units = recommended cases * units per case
estimated purchase cost = recommended cases * landed cost per case
```

The last quantity is a proposed purchase cost in SGD, not a carrying cost, profitability estimate or savings result. MOQ/multiples can make an order larger than the unconstrained net need. The maximum-cover threshold is an alert, not an order cap.

## Risk and excess indicators

- **First shortage with existing POs:** earliest forecast date with positive unmet units under no new orders. A far-future shortage is not necessarily today's urgent exception.
- **Unmet before normal arrival:** sums unmet demand strictly before the candidate normal arrival. A positive value triggers urgent review even if a normal import quantity is also recommended.
- **14-day unmet demand:** near-term urgency indicator; it does not replace the full lead/review calculation.
- **Physical stock cover:** consume current physical stock along future daily forecasts, excluding all inbound orders. Return a fractional day at depletion. If cover exceeds the 84-day forecast window, return 84 with `stock_cover_capped=1`; the true cover is not known from this horizon.
- **Excess committed supply:** `max(0, current stock + existing POs arriving within the max-cover window - forecast demand in that window)`. In the with-plan stress path, add the proposed order only if it arrives within the window. This includes the pipeline and is not equivalent to physical-stock days of supply. It does not measure spoilage, excess cost or guaranteed lost sales.

A single priority action is chosen: urgent supply review; otherwise early ordering; otherwise scheduled ordering; otherwise excess review; otherwise monitor. Separate numeric risk columns preserve simultaneous exceptions.

## Sensitivity and evaluation boundaries

Stress scenarios use base demand, demand +20%, demand -20%, and all arrivals delayed seven days. Factors are assumptions, not uncertainty quantiles. Base order cases and order date are frozen. The delay shifts existing and proposed usable arrival dates equally. A receipt shifted beyond the horizon remains in the input snapshot but contributes no within-horizon supply.

The two paths differ only by this one proposed order. This makes the scenario comparison interpretable, but it is not a comparison of full 84-day replenishment policies. There are no subsequent hypothetical orders. The cycle metric uses the same base cycle-end date in every stress scenario so a delayed order can correctly expose unmet demand inside that window.

Step 5 evaluated 35-day forecasts. A delayed review date plus lead time, a review interval and safety days can require predictions beyond day 35. Those portions are available in the 84-day output but their longer-horizon accuracy has not yet been validated.

A later business-case simulation must evaluate repeated decisions under the same demand and lead-time realizations for both policies. Do not use current projections as realized improvement claims, and do not use censored historical sales as verified true lost demand.

## Data contracts, freshness and lineage

The input reader verifies the Step 5 history/policy fingerprint, recomputes the small baseline forecast, and checks stored production values and selected models. It then snapshots current physical balances, all open POs, full current supply policies and forecast records. A planning run stores its own input SHA-256, code version/hash, forecast-run reference and creation timestamp.

Inputs are read in one MySQL repeatable-read consistent snapshot. Run a single pipeline writer; no source/forecast refresh should occur during planning. Recommendations persist their policy values so later policy edits do not reinterpret an old decision. Results are valid for their recorded input snapshot, not automatically for live changed data.

Rerunning the named planner run replaces its outputs transactionally. Once another layer stores foreign-key dependencies on it, use versioned runs or coordinate rebuilding descendants. The older Step 4/5 parent-delete refreshes are blocked by these dependencies; never bypass foreign keys. A full scheduled-refresh orchestration is a later deliverable.

## References for implementation mechanics

- MySQL Connector/Python consistent snapshots and transaction modes: https://dev.mysql.com/doc/connector-python/en/connector-python-api-mysqlconnection-start-transaction.html
- Python Decimal arithmetic and ceiling rounding: https://docs.python.org/3/library/decimal.html

The specific inventory policy above is the explicit design of this demonstration; it is not claimed to be an externally certified optimal policy.
