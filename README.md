# AI-Powered-Beverage-Demand-Supply-Intelligence-Platform
Inspired by the digital transformation and regional supply-chain challenges of global FMCG and beverage companies.
For example, Asia Pacific Breweries Singapore (APBS), HEINEKEN’s wholly owned subsidiary, will progressively evolve to an import-based supply model over the next two years. **The products are imported from**
-Malaysia
-Vietnam
-China
-Other regional breweries

**The compay's lineup is**
-Beer
-Non-alcoholic beverages
-Other SKUs (6 SKU in total)

**Channles**: Retail/on-trade/distributor channels

# What it Does
As a role of Data & AI Business Partner in APBS, in this project.

Says how much of each SKU we should import, when we should replenish it, and how Commercial and Supply Chain teams can identify stockout or excess-inventory risks before they happen.

Power BI Dashboard for business people. Three views over all data.
| Commercial | Demand | Supply Chain |
|---|---|---|
| Revenue | Actual sales | Current inventory |
| Volume | Forecast sales | Days of inventory |
| Brand performance | Forecast error | Reorder point |
| Channel performance | Holiday impact | Import lead time |
| Promotion performance | Promotion impact | Stockout risk |
| Regional / outlet performance | Seasonality | Excess inventory risk |


# Quick Start

Prerequisites: Python 3.10+, MySQL 8.0.19+ running locally.

```powershell
# 1. Install dependencies
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -c "import requests; import mysql.connector; print('Imports OK')"
```

```sql
-- 2. In MySQL Workbench, run in order:
-- sql/00_create_database.sql
```

```powershell
# 3. Load Singapore public holidays into MySQL
.\.venv\Scripts\python.exe scripts\holiday_pipeline.py
```

```sql
-- 4. In MySQL Workbench, run in order:
-- Run: sql/01_verify_and_analyse.sql
-- row_count should match "Validated ... rows" from step 4
-- sql/02_build_dim_date.sql
-- sql/03_build_product_supply.sql
-- sql/04_create_transaction_tables.sql
```

```powershell
# 5. Generate and load the synthetic scenario
.\.venv\Scripts\python.exe scripts\generate_load_transactions.py
```

```sql
-- 6. In MySQL Workbench, verify:
-- sql/05_verify_transactions.sql
-- All failed_rows must be 0
```

# Data Modelling Concepts

# Before You Run it Wide
# How it Works
ARCHITECTURE.md - where the data comes from. 

https://www.kaggle.com/competitions/store-sales-time-series-forecasting/data
https://data.gov.sg/datasets/d_8ef23381f9417e4d4254ee8b4dcdb176/view

As well as synthetic enterprise data.
# Licence




# Step 4 — Synthetic Sales, Inventory and Purchase Orders

This module extends the Beverage Demand & Supply Decision Platform with reconciled business transactions. It supports the original questions: how much to import, when to replenish, and how to identify stockout or excess-inventory risks before they happen.

It creates a reproducible **synthetic** business scenario using your existing product, supply-policy and calendar tables. It is not APB transaction data and does not demonstrate measured APB benefits. Forecasting and replenishment recommendations are the next stage.

## 1. Prerequisites and installation

Complete and validate Steps 1–3 first. Your database should contain:

- `stg_public_holidays` and `dim_date` with validated Singapore calendar coverage.
- Six `dim_product` records with IDs 1–6 and codes `DEMO-BEV-001` through `DEMO-BEV-006`.
- Two suppliers, warehouse ID 1, and six `sku_supply_policy` records.
- Python 3.10+ and the existing `mysql-connector-python` dependency.
- MySQL 8.0.19+ (the observed local server is 8.0.46).

Extract this add-on and merge its `scripts`, `sql` and `docs` contents into the existing project directories. These files have new names; retain all earlier project files, README, requirements, and `.venv`. Put this guide in the project root.

| File | Purpose |
|---|---|
| `sql/04_create_transaction_tables.sql` | Create the new tables and three demo channels |
| `scripts/generate_load_transactions.py` | Read existing master data, generate/validate transactions, save CSVs, and load MySQL |
| `sql/05_verify_transactions.sql` | Reconcile tables and inspect the as-of inventory position |
| `docs/step4_model_contract.md` | Grains, assumptions, event timing, and data limitations |
| `docs/step4_validation.md` | Authoring checks and local MySQL acceptance criteria |

No new Python packages are required beyond the existing requirements.txt. Do not place the add-on in a separate nested project with a different `.venv`.

## 2. Create the tables — MySQL Workbench

Open `sql/04_create_transaction_tables.sql` in the existing MySQL connection. Select and execute the **entire file**. It selects `beverage_intelligence`, creates the tables and displays three channel records: retail, on_trade, and distributor.

New tables:

| Table | Grain |
|---|---|
| `dim_channel` | One customer channel |
| `dim_scenario` | One named synthetic scenario, including its cutoff, seed and assumptions |
| `fact_sales` | Scenario × date × SKU × warehouse × channel |
| `fact_inventory` | Scenario × date × SKU × warehouse |
| `fact_purchase_orders` | Scenario × purchase-order line |

This step does not populate the transaction tables. Python does that next. If the SQL reports an error, resolve it before proceeding. Existing calendar and master-data rows are not changed.

## 3. Generate and load — PowerShell in VS Code

Open a terminal in your existing project root. For the project location used so far:

```powershell
cd "C:\Users\kissg\Downloads\Beverage_Pipeline_Step1"
.\.venv\Scripts\python.exe scripts\generate_load_transactions.py
```

Enter your local MySQL password when prompted. Characters are not displayed while typing. The default connection is root at 127.0.0.1:3306. Use `--user`, `--host` and `--port` if your actual connection differs.

The program reads the master data already in MySQL; do not manually copy product parameters into Python. It verifies the six expected SKUs and three channels and checks that the date dimension covers historical dates and future expected arrivals.

The scenario is fixed at **end of day, 2026-09-30**. Historical sales and inventory run from **2024-01-01 through 2026-09-30**, inclusive: 1,004 days. It deliberately does not use today's date, so tomorrow's run does not silently change the scenario window.

Expected messages:

```text
Scenario: beverage_demo_v1 | SYNTHETIC | As of 2026-09-30
fact_sales: 18072 rows
fact_inventory: 6024 rows
fact_purchase_orders: 770 rows
DATA VALIDATION OK: stock balance, continuity, sales, receipts and PO rules.
```

A CSV-directory message follows. A successful database load ends with:

```text
TRANSACTION PIPELINE OK
Next: run sql/05_verify_transactions.sql in MySQL Workbench.
```

Sales rows = 1,004 days × 6 SKUs × 1 warehouse × 3 channels = **18,072**.
Inventory rows = 1,004 days × 6 SKUs × 1 warehouse = **6,024**.
The authoring run produced **770 PO lines and 20 open lines** with the original Step 3 parameters and the holiday snapshot already used in Step 1. The PO count is generated, not hard-coded. Different inputs, source revisions or runtime details can change it; compare the database count with your Python output. The generator version, Python version, input parameters, historical holiday dates and CSV hashes are recorded in the manifest.

### Generated files

Look under `data/processed/beverage_demo_v1/`:

- `fact_sales.csv`
- `fact_inventory.csv`
- `fact_purchase_orders.csv`
- `manifest.json`

The CSVs are written before the database refresh. Their existence alone does not prove that MySQL loading succeeded; check for `TRANSACTION PIPELINE OK`.

### Optional generation-only mode

```powershell
.\.venv\Scripts\python.exe scripts\generate_load_transactions.py --generate-only
```

This still **reads MySQL** for master data and the calendar, but does not write the transaction tables. It ends with `GENERATE OK`, not `TRANSACTION PIPELINE OK`.

## 4. Verify and inspect — MySQL Workbench

Open and execute the entire `sql/05_verify_transactions.sql` file. It returns five result sets. Workbench may initially show only the last result set; switch the tabs below the result grid to inspect the others.

1. **Scenario metadata:** one synthetic scenario, history start 2024-01-01, as-of date 2026-09-30, seed 20261004.
2. **Table counts:** 18,072 sales rows, 6,024 inventory rows, and a PO count matching Python.
3. **Eleven validation checks:** every `failed_rows` value must be **0**. Zero failures alone are insufficient if the expected transaction rows have not been loaded.
4. **Six-SKU snapshot:** current on-hand units, trailing 28-day average fulfilled sales, historical-sales-based days of supply, zero-stock days, open order units, next expected arrival, and lead time.
5. **Open purchase orders:** expected arrival dates after the cutoff, no actual receipt date, and zero received units.

The eleven checks cover stock balance, nonnegative inventory, day-to-day continuity, sales-to-inventory reconciliation, orphan sales, PO-to-inventory receipts, orphan receipts, sales revenue, order rules, future actual records, and incorrectly received open orders.

The fourth result set is a descriptive baseline. Its `trailing_days_of_supply` is closing stock divided by trailing average **fulfilled sales**. It is not forecast-based coverage. Stockouts can suppress sales and make this metric overstate coverage; inspect `zero_stock_days_last_28d`. No replenishment recommendation is made at this stage.

## 5. Reconciliation and event order

For every day, SKU and warehouse:

**Opening units + received units − sold units = closing units**

The next day's opening units must equal the previous day's closing units. Channel sales sum to the warehouse's sold units. Received purchase orders sum to the warehouse's received units on their actual receipt dates.

Within each simulated day, events occur in this order:

1. Begin with opening stock.
2. Receive orders due that morning.
3. Fulfill channel demand, capped by available stock.
4. Record closing stock.
5. On a review day, place new orders using information available through that day.

Open PO units are **not** on-hand units. Joining three sales-channel rows to an inventory row without first aggregating sales can triple-count stock; the supplied snapshot query aggregates each fact table before joining.

## 6. Repeatability and refresh behavior

With unchanged inputs and runtime, the fixed seed reproduces the same generated transactions. The input manifest makes those assumptions inspectable.

The loader replaces only records belonging to `scenario_id = 'beverage_demo_v1'` in the three fact tables and its scenario metadata. It does so in one transaction, using batches of 1,000 parameterized inserts. If a write or row-count check fails, the refresh is rolled back. It does not truncate tables or replace other scenarios, products, policies, dates or holiday records. Run one instance at a time.

Because this scenario is a reproducible demo, regenerate it after changing master assumptions only when you intend to replace its history. Do not change units per case on an existing SKU after loading transactions; create a distinct SKU for a different pack configuration. Future modules may add dependencies on the scenario, requiring their refresh logic to be coordinated.

## 7. Troubleshooting

| Symptom | Action |
|---|---|
| Script file cannot be found | Confirm you merged `scripts/generate_load_transactions.py` into the existing project and are in the project root |
| No module named mysql | Run the existing requirements installation using the same `.venv` Python interpreter |
| Table does not exist | Run the entire Step 4 schema SQL first, and confirm Steps 1–3 were completed in the same database |
| Expected six products/three channels | Check the Step 3 master data and Step 4 channel setup; the starter expects the documented IDs/codes |
| Date coverage is incomplete/unknown | Check dim_date and its holiday flags, including future arrival dates; do not fill unknown dates with a guessed holiday value |
| Access denied or connection refused | Check your existing MySQL username, password, service, host and port |
| PermissionError while writing CSV | Close the output CSV in Excel and rerun |
| DATA VALIDATION OK but no TRANSACTION PIPELINE OK | Inspect the following database error; generation passed, but loading has not been confirmed |
| Validation query reports nonzero failures | Send the check names, counts, and exact SQL errors; do not manually change totals to make them pass |

Do not send passwords. Share the exact command, error text and relevant result sets.

## 8. GitHub and the next stage

Commit the new scripts, SQL and documentation alongside the existing project. The existing `.gitignore` excludes `.venv`, raw/processed data and generated outputs. Do not blindly overwrite it or commit credentials.

After local acceptance passes, your project can accurately state that it generates and loads a reconciled synthetic sales/inventory/order scenario. It cannot yet claim proven forecasting improvements, optimized import quantities or measured cost savings.

Next, build and backtest a baseline demand forecast, then use dated receipts and projected daily stock to evaluate replenishment, shortage and overstock decisions. Preserve the original business scope: quantity, timing, stockout risk and excess-inventory risk. Supplier delays, expiry, partial receipts and constrained optimization remain later extensions.

# Step * Outcome - Beverage Demand & Supply Decision Platform.pbix
Commercial
- Revenue
- Volume
- Brand performance
- Channel performance
- Promotion performance
- Regional / outlet performance
Demand
- Actual sales
- Forecast sales
- Forecast error
- Holiday impact
- Promotion impact
- Seasonality
Supply Chain
- Current inventory
- Days of inventory
- Reorder point
- Import lead time
- Stockout risk
- Excess inventory risk









