# Beverage Demand & Supply Decision Platform — delivery contract

## Business problem and intended decisions

How much of each SKU should we import, when should we replenish it, and how can Commercial and Supply Chain teams identify stockout or excess-inventory risks before they happen?

The product must connect evidence to a planner's action. A demand forecast alone does not solve this problem. For every SKU/warehouse, the final decision record must explain:

1. The demand estimate over the relevant lead time and review interval.
2. Usable stock now and dated expected inbound units.
3. The first projected shortage date and any estimated unmet units.
4. Recommended import cases and units, subject to MOQ and order multiples.
5. A proposed order/review date, expected usable arrival, and whether normal replenishment is too late.
6. Excess-stock exceptions, assumptions, forecast quality, and a accountable human decision owner.

Recommendations support a planner; this portfolio does not automatically submit real purchase orders.

## Scope decisions relative to the original concept

| Original idea | Implemented or revised scope | Reason |
|---|---|---|
| Public retail sales plus Singapore holidays | Synthetic Singapore sales/stock/POs plus real Singapore holiday API | The previously mentioned Kaggle Store Sales data is Ecuadorian retail; relabeling it as Singapore beverage SKU demand would be misleading. |
| Generic SQL database / PostgreSQL example | MySQL throughout | Matches the already working local environment. No database migration is needed. |
| Product, store and supplier dimensions | Product, channel, warehouse, supplier and SKU/warehouse supply policy | The current facts describe warehouse outbound transactions. There is no observed outlet geography to support regional claims. |
| One inventory field including in-transit stock | Daily physical stock plus separately dated purchase-order lines | Avoids double counting physical stock and inbound stock; late arrivals cannot repair earlier shortages. |
| Forecast a fixed 14 or 28 days | 84-day planning output; 35-day validated comparison | The current longest protection period is 28 days of lead time plus a 7-day review. Fourteen days is only an urgency filter. |
| Single forecast/error table | Versioned origins, target dates, candidate scores and selections | Forecast errors require knowing when the forecast was made; production actuals do not exist yet. |
| Inventory days < lead time = high risk | Daily stock projection using forecast and dated receipts | A cover ratio alone ignores receipt timing and varying daily demand. |
| Holiday/promotion 'impact' | Descriptive association first; causal claims require a separate design | The demo generator deliberately encodes such effects; this is not empirical evidence of causality. |
| Many ML algorithms immediately | Tested baselines, then a justified challenger | Complexity must improve out-of-sample evidence or decision quality. |
| Copilot explains any region or driver | Copilot answers only questions supported by implemented data/tools | No invented West-region insights, causal drivers, or future promotion assumptions. |

## Delivery stages and acceptance gates

| Stage | Current status | Business output and acceptance gate |
|---|---|---|
| 1. External integration | Passed by user | REST API → raw JSON → Python → MySQL; reproducible source data and validation. |
| 2. Calendar and master data | Passed by user | Consistent dates, 6 SKUs, 2 suppliers, 1 warehouse, unit/case conversion and supply policies. |
| 3. Transaction evidence | Passed by user | 18,072 sales rows; 6,024 daily inventory rows; 770 PO lines in the confirmed scenario; all 11 integrity checks pass. |
| 4. Forecast benchmark (Step 5) | Delivered; local execution pending | Three candidates, temporal validation, separate holdout, selected model per SKU, 504 future daily predictions. SQL and forecast review must pass. |
| 5. Replenishment and risk engine | Next | Daily stock and unmet-demand projection, import cases, review/order date, expected arrival, urgency and excess-stock flags. Hand-calculated scenarios and reconciliation required. |
| 6. Model/decision improvement | Planned | Compare a calendar/promotion-aware challenger if a reliable future promotion plan exists; sensitivity to demand and lead time. Retain baseline unless evidence supports change. |
| 7. Commercial and Power BI layer | Planned | Four pages: executive, commercial, supply chain, forecast/insights; governed measures, run/date filters and drill-through. Reconcile cards to SQL. |
| 8. Grounded AI copilot | Planned | Read-only functions return authoritative numbers and provenance; assistant summarizes evidence and states missing data. Verify answers against SQL. |
| 9. Business case, UAT and handover | Planned | Scenario-based value estimates, measurable success metrics, UAT sign-off checklist, adoption/training plan, reproducible GitHub instructions and demo. |

## Decision-engine requirements for the next stage

- Anchor every calculation to the scenario's end-of-day cutoff, not the computer clock.
- Start with physical closing stock. Add each open PO only on its expected usable arrival date. Past-due open orders become exceptions rather than silently disappearing.
- Model events consistently: opening stock, morning receipts, daily forecast consumption, closing stock.
- Track unmet forecast demand separately from nonnegative physical stock. Do not silently carry lost sales as backorders; the MVP assumes no backorders.
- Test shortage before a new normal order can arrive. Raising order quantity cannot fix that earlier shortage. Offer expedite/transfer/commercial review as human options, not invented confirmed supply.
- Respect the review schedule inherited from the synthetic scenario, or explicitly document a new policy. Distinguish 'review now because of an exception' from a scheduled review date.
- Compute a time-phased net need, then convert positive need into cases and apply MOQ and order multiples. Zero or negative need means zero recommended cases.
- Do not offset near-term need with receipts that arrive after the coverage period. Show before/after recommendation projections.
- Show purchase spend from case quantities and landed case cost. Do not label purchase spend as inventory carrying cost or realized savings.
- Use the maximum-cover policy to flag surplus, not as an automatic order cap. MOQ can cause surplus. Expiry risk remains out of scope until batch expiry data exists.
- Include at least base/high/low demand and delayed-arrival scenarios before claiming robustness. No service-level guarantee follows from a fixed seven-day buffer.
- Block stale decisions when source/forecast/policy versions do not match. Keep a run ID, cutoff, input fingerprint, model version and policy snapshot with the output.

## BI scope and metric ownership

Commercial owns revenue, outbound volume, brand/category/channel mix and promotion-period comparisons. There is no outlet/region detail in this MVP, so those slicers are omitted. Promotion lift is descriptive until a valid counterfactual design exists.

Supply Chain owns stock, dated inbound supply, projected shortage, import cases, order timing and excess-stock exceptions. Forecast owners monitor WAPE, MAE, bias, excluded-day counts and the gap between fulfilled sales and unknown true demand.

The dashboard must never sum forecasts from multiple origins, candidates or run IDs. Inventory is not additive over dates or channels. Display the synthetic-data label and business cutoff clearly.

## Grounded AI contract

Planned functions include `get_sku_risk`, `get_replenishment_recommendation`, `get_forecast_evaluation`, and `get_commercial_summary`. They return units, dates, selected run, assumptions and supporting rows. The language model summarizes these results; it does not invent numbers, execute unrestricted SQL, or claim causal explanations unsupported by the model.

A suitable answer might explain that projected demand before the next usable arrival exceeds available supply and cite the specific forecast, stock and PO rows. It must not say that holidays caused an 18% increase unless the analytical layer has actually estimated and validated that claim.

## Business case and success metrics

Original illustrative values such as 8 hours/week, 7% stockout and 25% MAPE are assumptions, not measured baselines. Do not present them as achieved results.

Separate three types of evidence:

- **Measured in the project:** pipeline runtime, reproducible data checks, held-out forecast errors, SQL/BI reconciliation, UAT pass rate, copilot numeric accuracy.
- **Simulated operational outcomes:** unmet demand, average stock units/value, purchase quantities, carrying cost under explicit rates, and review-policy scenarios.
- **Hypothetical adoption benefits:** manual time saved and staffing impact, with stated inputs and sensitivity ranges.

For any simulated policy comparison, use the same demand path and supply assumptions for both policies. Observed historical sales are censored and are insufficient to establish true lost-sales reduction. A later separate evaluation harness may hold synthetic latent demand for scoring only; it must not expose that future truth to the forecast or planner.

Revenue protected is not profit. Value estimates should use contribution margin when available and avoid counting the same benefit twice. Document implementation/operating costs and keep currency and unit conversions consistent.

## Portfolio completion definition

A fresh user can follow the English guide from API extraction to verified SQL outputs, generate forecasts and planner recommendations, open the BI report, inspect a grounded AI answer, and reproduce the synthetic scenario. GitHub includes an honest data statement, architecture/data model, business requirements, user stories, UAT cases, business case, adoption plan, dependency versions, setup instructions, screenshots and a short demo narrative. No real-company impact or enterprise-production readiness is claimed without evidence.
