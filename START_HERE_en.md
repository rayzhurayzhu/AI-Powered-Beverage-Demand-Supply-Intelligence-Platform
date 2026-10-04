# Beverage Demand & Supply Intelligence — Working Pipeline

Goal: retrieve public holidays from a Singapore government API, save the raw JSON, validate and organize the data with Python, load it into MySQL, and then query and export the results using SQL. Once this runs successfully, you will have a reusable external-data ingestion module. Forecasting, inventory recommendations, and AI question answering come in later stages.

This tutorial uses Windows + PowerShell + MySQL. It requires Python 3.10 or later (3.12 recommended) and MySQL Server 8.0 or later. The MySQL service must already be installed and running. MySQL Workbench is only a client; installing the Python driver does not install MySQL Server.

## 0. Understanding the errors you encountered

- `NameError: name 'requests' is not defined`: `import requests` has not been executed in the current Python file or notebook session.
- `ModuleNotFoundError: No module named 'requests'`: requests is not installed in the Python environment running your code.
- `NameError: name 'url' is not defined`: the url variable has not been assigned a value before it is used.
- The `...` in `requests.get(...)` is not a URL. In the earlier explanation, it was only a placeholder, not a complete runnable program.

Installation and importing are separate steps: installation makes a package available in the environment, while import makes it available to the current program. Do not name your files `requests.py`, `mysql.py`, or `json.py`, because these names will shadow the packages or modules you need to import.

## 1. Add the files to your existing project

Keep the README.md you have already written. Place the following contents from the archive in the same project root directory:

| File | Purpose |
|---|---|
| requirements.txt | Install the two third-party dependencies |
| scripts/holiday_pipeline.py | Complete runnable Python program |
| sql/00_create_database.sql | Create the project database for the first time |
| sql/01_verify_and_analyse.sql | Validate and analyze the data in MySQL |
| START_HERE_en.md | This guide |
| docs/data_contract.md | Field definitions and the interface for the next database stage |
| docs/validation_notes.md | Checks already completed and checks still required locally |
| tests/test_holiday_pipeline.py | Optional offline logic tests |
| .gitignore | Prevent environment files, password files, and generated outputs from being committed |

If you already have a requirements.txt or .gitignore with the same name, merge the new entries into it; do not overwrite the original file directly. Raw JSON, cleaned CSV files, and analytical outputs are generated automatically at runtime. You do not need to create their directories manually.

VS Code → File → Open Folder → select your project folder → Terminal → New Terminal. Run all commands marked PowerShell below in this terminal. First use `Get-Location` to check your location, then use `Get-ChildItem` to confirm that you can see `requirements.txt` and `scripts`.

Do not run PowerShell commands at the `mysql>` prompt or Python's `>>>` prompt. If you have entered Python's interactive mode, run `exit()` first to return to PowerShell.

## 2. Install the dependencies (PowerShell)

Run these commands in order:

```powershell
py --version
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -c "import requests; import mysql.connector; print('Imports OK')"
```

The final command should display `Imports OK`. If `py` is not recognized but `python --version` reports Python 3.10 or later, replace `py` with `python` in the first two commands. If neither is recognized, install Python first and reopen VS Code. If you already have a working `.venv`, you can skip the environment-creation step.

This tutorial specifies the Python executable inside `.venv` directly, so there is no need to activate the environment or change PowerShell's execution policy. Use this same interpreter for every subsequent run. Avoid using a standalone `pip install` when you are unsure which Python environment it belongs to.

## 3. Understand the complete requests.get example (optional exercise)

The following is a complete API exercise, with no missing variables or imports. Save it as `scripts/api_smoke_test.py` and run it:

```python
import json
import requests

url = "https://data.gov.sg/api/action/datastore_search"
params = {
    "resource_id": "d_8ef23381f9417e4d4254ee8b4dcdb176",
    "limit": 5,
    "offset": 0,
}

response = requests.get(url, params=params, timeout=30)
response.raise_for_status()
payload = response.json()

if payload.get("success") is not True:
    raise RuntimeError(f"API returned an error: {payload}")

records = payload["result"]["records"]
print("HTTP status:", response.status_code)
print("Total source rows:", payload["result"]["total"])
print(json.dumps(records, ensure_ascii=False, indent=2))
```

```powershell
.\.venv\Scripts\python.exe scripts\api_smoke_test.py
```

This only previews the first 5 rows. The complete program handles pagination. The dataset page lists the fields `date`, `day`, and `holiday`; the API also includes `_id`.

| Expression | What it does |
|---|---|
| requests.get(...) | Sends an HTTP GET request and returns an HTTP response object |
| response.raise_for_status() | Stops on an HTTP error so that an error page is not treated as data |
| response.json() | Parses the JSON response into Python dict/list objects |
| payload["result"]["records"] | Extracts the list of business records from the response wrapper |
| json.dumps(...) | Serializes Python objects into JSON text for display or storage |

An HTTP 200 response does not guarantee that the API operation succeeded, so the program also checks `success`. JSON is a data exchange format, not a database; `response.json()` does not automatically write anything to SQL.

## 4. Run API → JSON → Python (PowerShell)

Run the complete script provided in the package:

```powershell
.\.venv\Scripts\python.exe scripts\holiday_pipeline.py --extract-only
```

This mode does not connect to MySQL. It:

1. Calls the official API and retrieves data page by page, sorted by `_id`, with up to 100 records per page.
2. Saves each original response under `data/raw/<run timestamp>/`.
3. Checks the number of retrieved rows against the API's reported total and checks for duplicate `_id` values across pages.
4. Validates date formats and holiday names, removing only identical country/date/name combinations.
5. Generates `data/processed/sg_public_holidays.csv`.

Actual execution log from 2026-10-04:

```text
Fetched 100/104 records
Fetched 104/104 records
Validated 104 rows; removed 0 exact duplicates
Date range: 2020-01-01 to 2027-12-25
EXTRACT OK. Next: create the database, then run without --extract-only.
```

The program also prints file paths and the first 5 rows. The value 104 is the actual number of rows retrieved in this run, not a permanently hard-coded answer. It may change when the official source is updated; the program validates against the API's reported total.

The last holiday date, 2027-12-25, does not mean that the dataset only covers dates through December 25. The official page states coverage through December 2027. Coverage boundaries and the date of the last event are different concepts.

If this step fails, resolve the error before proceeding to the sales model. The raw JSON files contain responses that were successfully received. A failed run may leave an incomplete run directory; a directory without manifest.json does not represent a complete extraction.

## 5. Create the database (MySQL Workbench or mysql>)

Open your existing local MySQL connection, create a new SQL query tab, and run:

```sql
CREATE DATABASE IF NOT EXISTS beverage_intelligence
  CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
USE beverage_intelligence;
SELECT DATABASE() AS selected_database, VERSION() AS mysql_version;
```

Alternatively, open `sql/00_create_database.sql` and run the entire file. You should see the database name `beverage_intelligence` and the server version.

It is normal for the holiday table not to exist yet: Python will create `stg_public_holidays` in the next step. If you use the MySQL command-line client, you can run `mysql -u root -p` in a separate PowerShell window. If `mysql` is not on your PATH, simply use your installed MySQL Workbench; there is no need to change this tutorial for that reason.

## 6. Run the complete pipeline (back in PowerShell)

```powershell
.\.venv\Scripts\python.exe scripts\holiday_pipeline.py
```

The program fetches and cleans the data again, then prompts:

```text
MySQL password for root:
```

Enter your local MySQL password and press Enter. It is normal for no characters to appear as you type. This is not your GitHub password, and it is not written into the script.

Default connection settings: host=`127.0.0.1`, port=`3306`, user=`root`, database=`beverage_intelligence`. These defaults follow your local learning setup. If you already use a dedicated MySQL account or a different port, specify them as arguments. For example, if the username really is beverage_user and the port really is 3307:

```powershell
.\.venv\Scripts\python.exe scripts\holiday_pipeline.py --user beverage_user --port 3307
```

This command does not create that user. The account must have CREATE, SELECT, INSERT, and DELETE permissions in the project database. Do not send your password to anyone to run this script.

The program creates the holiday staging table, then refreshes this source's SG holiday data within a single transaction. If the row-count check fails or a SQL operation fails, the data refresh is rolled back. Table creation is a separate step, so a failed run may leave an empty table; this is expected.

On repeated runs, the program first deletes **this source's SG snapshot in this staging table**, then inserts the new snapshot. This prevents corrected or removed holidays from remaining in the table. The table is not an append-only log; do not manually maintain other SG sources in it. Raw JSON is saved separately for every run. Run only one instance at a time.

On success, you should see:

```text
Committed 104 rows to beverage_intelligence.stg_public_holidays
calendar_year | holiday_records | holiday_dates
```

The annual summary, output CSV path, and `PIPELINE OK` follow. The value 104 may change when the source is updated. The final output is `outputs/holiday_summary.csv`, which you can open in Excel.

Note: if you have already seen `Committed` and the CSV export then fails, the data may already be in the database. For example, if Excel is holding the output file open, close it and rerun the script; you do not need to delete the database and start over.

## 7. Validate and analyze with SQL (MySQL)

Open `sql/01_verify_and_analyse.sql` and run all queries. At minimum, confirm that:

- `row_count` equals the number of validated rows printed by Python.
- The first 10 rows contain country, date, holiday name, and extraction time.
- Annual `holiday_records` and `holiday_dates` results are returned successfully.
- Running the full script again does not double the row count when the source is unchanged.

Two different holidays can fall on the same date. `COUNT(*)` counts holiday records, while `COUNT(DISTINCT holiday_date)` counts holiday dates. Do not treat them as the same measure.

The analytics at this stage cover calendar coverage and holiday distribution. They cannot yet answer "How much do holidays increase beer sales?" because we do not have sales data yet. Differences in sales before and after holidays also cannot automatically be described as causal effects.

## 8. Connect this module to the next database stage

The `stg` prefix in the current table name means staging: a layer of organized source data. It is not a complete date dimension, because it contains holidays but not ordinary working days.

Next, define the business scenario, data sources, and table grains before designing:

- `dim_date`: one row per day, covering the complete date sequence.
- `dim_product`: one row per SKU; units such as individual bottles and full cases must be clearly defined.
- `dim_location`: store/warehouse identities and types, to be split later if business requirements call for it.
- `fact_sales`: first establish a grain such as day × SKU × sales location.
- `fact_inventory`: an inventory snapshot at day × SKU × warehouse grain.
- `fact_forecast`: retain the forecast generation date, forecast target date, and SKU/location to support proper backtesting.

The holiday data will supply Singapore calendar flags. First aggregate holidays to one row per country and date, or use EXISTS, before flagging sales dates. Do not JOIN the sales table directly to unaggregated holiday rows, because multiple holidays on the same date could duplicate sales quantities.

Dates outside the holiday source's coverage should be treated as unknown, not automatically flagged as non-holidays. Public holidays are also not necessarily non-working days for every supplier, store, and warehouse; separate business calendars will be needed later.

The data scenario needs a correction: Kaggle Store Sales contains real retail data from Ecuador. We cannot simply attach Singapore dates and weather to explain its real demand. For a Singapore beverage scenario, we can construct sales, inventory, and lead-time data explicitly labeled synthetic. If we choose Kaggle's real data instead, we should use its actual country and historical time period. Simulated data cannot support claims of real APB business benefits.

## 9. Build the platform in stages

| Stage | Deliverable | Completion criteria |
|---|---|---|
| 1 — current | Holiday API → MySQL → SQL analysis | PIPELINE OK, correct row counts, no accumulation on repeated runs |
| 2 | Business problem, data dictionary, database design | Clear grain, primary/foreign keys, units, and sources for every table |
| 3 | Sales, inventory, and lead-time ingestion | Aligned dates and SKUs; reconcilable inventory and sales definitions |
| 4 | Baseline forecasting and replenishment rules | Time-based backtesting and comparison with simple baselines; account for in-transit stock and arrival dates |
| 5 | Power BI | Business metrics traceable to SQL, with exceptions and recommendations displayed |
| 6 | AI query assistant | Uses controlled queries to cite computed results and explains limitations when data is missing |
| 7 | Business case, UAT, demonstration | Distinguishes simulated benefits from measured metrics; includes acceptance tests and a complete user walkthrough |

First build a minimum demonstrable version of one scenario, then expand to weather, more complex models, and cloud deployment. This package only implements the code needed for stage 1; later features should not be described as completed.

## 10. Add the project to GitHub

If this is already a cloned GitHub repository and a remote is configured, run the following from the project root:

```powershell
git status
git add .gitignore requirements.txt scripts/holiday_pipeline.py sql/00_create_database.sql sql/01_verify_and_analyse.sql START_HERE_en.md docs tests
git diff --cached --stat
git commit -m "Add Singapore holiday API to MySQL pipeline"
git push
```

Inspect the staged contents first to confirm that no passwords, `.venv`, or unrelated files are included. If `git push` reports that no upstream or remote is configured, send me the error so we can handle it according to the existing branch; do not guess the repository URL. If the repository has not been cloned, there is no need to resolve Git setup before completing this stage. Get it working locally first, then upload it.

Suggested README update, to use after local MySQL acceptance checks pass:

> Implemented a paginated Singapore public-holiday API pipeline with raw JSON snapshots, Python validation, transactional MySQL staging refreshes, and SQL calendar summaries. Demand forecasting, inventory planning and an AI assistant are planned next.

If you have only completed --extract-only, describe API extraction and validation only; do not claim that the MySQL pipeline has been completed.

## 11. Troubleshooting

| Error or symptom | What to do |
|---|---|
| requests is not defined | Add import requests at the top of the current script; run the entire file, not just a selected line |
| No module named requests/mysql | Install using `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`, then run with that same interpreter |
| py is not recognized | Try python --version; if neither command works, install Python and reopen the terminal |
| can't open file | Check the current directory and filename, including whether the file was accidentally saved as `.py.txt` |
| MySQL 1045 Access denied | Check your username and local MySQL password; do not post your password |
| MySQL 1049 Unknown database | Run the database-creation SQL on the same MySQL server first |
| MySQL 2003 / 10061 | Check the MySQL Server service, host, and port, and whether Workbench can connect |
| MySQL 1142 permission denied | Use an existing account with permission to create tables and read/write in the project database |
| HTTP 429 | Requests are being rate-limited; the script performs a limited number of retries. Do not repeatedly rerun it immediately |
| HTTP 403/404/5xx | Check whether the official dataset page is available and inspect the error message; do not load an empty response into the database |
| SSLError / timeout | Check the network, proxy, and system clock; do not resolve this by disabling TLS verification |
| Pagination/schema validation error | The API structure or data may have changed; send the error text and manifest/field names for inspection |
| PermissionError while exporting CSV | Close the output file if it is open in Excel, then rerun |
| MySQL password input is not visible | getpass does not echo characters by default; enter the password normally and press Enter |

If a local run fails, send the command you ran, the complete traceback, and the Python version. Do not send passwords.

## 12. Sources and validation boundaries

Date checked: 2026-10-04.

- Data source: [MOM — Singapore Public Holidays (consolidated)](https://data.gov.sg/datasets/d_8ef23381f9417e4d4254ee8b4dcdb176/view). The source page specifies 2020–2027 coverage, 104 rows, and the Singapore Open Data Licence. Retain the source and access date when citing the data.
- [Official pagination API documentation](https://guide.data.gov.sg/developer-guide/dataset-apis/search-and-filter-within-dataset). API parameters are resource_id, limit, offset, and sort.
- [Official API overview](https://guide.data.gov.sg/developer-guide/api-overview). This example can be tested without an API key, as verified by the actual anonymous requests in this run.
- [Official MySQL Connector/Python connection documentation](https://dev.mysql.com/doc/connector-python/en/connector-python-example-connecting.html).

The external API extraction, saving of two JSON pages, cleaning of 104 rows, and 7 offline logic checks have actually been completed. The authoring environment has no MySQL Server, so no claim is made that a real MySQL integration test passed there. Actual SQL execution, account permissions, connectivity, and transaction behavior must be checked on your local machine using the steps above. The offline tests use mocked connections; they are not equivalent to real database tests.

The appendices below contain the complete file contents. In normal use, simply run the scripts in the package; there is no need to copy them again from the appendices.


## Appendix A: Complete Python program

File:`scripts/holiday_pipeline.py`

```python
"""Singapore holiday API -> JSON -> validated Python rows -> MySQL -> CSV.

Python 3.10+; local MySQL 8.0+. Run from a terminal, not a SQL editor.
Run only one instance at a time. This is a learning/local portfolio pipeline.
"""

import argparse
import csv
import json
import sys
from datetime import date, datetime, timezone
from getpass import getpass
from pathlib import Path

import mysql.connector
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[1]
API_URL = "https://data.gov.sg/api/action/datastore_search"
DATASET_ID = "d_8ef23381f9417e4d4254ee8b4dcdb176"
DATABASE = "beverage_intelligence"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS stg_public_holidays (
    country_code CHAR(2) NOT NULL,
    holiday_date DATE NOT NULL,
    holiday_name VARCHAR(200) NOT NULL,
    source_dataset_id VARCHAR(50) NOT NULL,
    fetched_at_utc DATETIME(6) NOT NULL,
    PRIMARY KEY (country_code, holiday_date, holiday_name),
    INDEX idx_holiday_source (source_dataset_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
"""

SUMMARY_SQL = """
SELECT YEAR(holiday_date) AS calendar_year,
       COUNT(*) AS holiday_records,
       COUNT(DISTINCT holiday_date) AS holiday_dates
FROM stg_public_holidays
WHERE country_code = %s AND source_dataset_id = %s
GROUP BY YEAR(holiday_date)
ORDER BY calendar_year
"""


def fetch_holidays():
    """Fetch all pages; keep original response payloads for inspection."""
    fetched_at = datetime.now(timezone.utc)
    run_dir = ROOT / "data" / "raw" / fetched_at.strftime("%Y%m%dT%H%M%S_%fZ")
    run_dir.mkdir(parents=True, exist_ok=False)
    records = []
    offset = 0
    expected_total = None
    retry = Retry(total=3, backoff_factor=1,
                  status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET"], respect_retry_after_header=True)

    with requests.Session() as session:
        session.mount("https://", HTTPAdapter(max_retries=retry))
        while True:
            response = session.get(
                API_URL,
                params={"resource_id": DATASET_ID, "limit": 100,
                        "offset": offset, "sort": "_id asc"},
                timeout=(10, 30),
            )
            response.raise_for_status()
            payload = response.json()
            (run_dir / f"page_{offset:06d}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if not isinstance(payload, dict) or payload.get("success") is not True:
                raise ValueError("API returned success=false or an unexpected structure.")
            result = payload.get("result")
            if not isinstance(result, dict):
                raise ValueError("API response is missing the result object.")
            batch = result.get("records")
            total = result.get("total")
            if not isinstance(batch, list) or type(total) is not int or total <= 0:
                raise ValueError("Missing records/total or an empty source dataset.")
            if expected_total is None:
                expected_total = total
            if total != expected_total:
                raise ValueError("Source row count changed during pagination. Run again.")
            if not batch:
                raise ValueError("Pagination ended before all source rows were received.")
            records.extend(batch)
            offset += len(batch)
            print(f"Fetched {offset}/{total} records")
            if offset == total:
                break
            if offset > total:
                raise ValueError("Received more rows than the API total.")

    ids = [row.get("_id") for row in records if isinstance(row, dict)]
    if len(ids) != len(records) or any(x is None for x in ids):
        raise ValueError("Source rows are missing their _id values.")
    if len(set(ids)) != len(ids):
        raise ValueError("Repeated source row IDs across pages; rerun the extract.")
    (run_dir / "manifest.json").write_text(json.dumps({
        "api_url": API_URL, "dataset_id": DATASET_ID,
        "fetched_at_utc": fetched_at.isoformat(), "source_rows": len(records),
    }, indent=2), encoding="utf-8")
    print(f"Raw JSON: {run_dir}")
    return records, fetched_at


def clean_holidays(records, fetched_at):
    """Grain: one country, one date, one named holiday (not just one date)."""
    cleaned = {}
    for record in records:
        row = {str(k).strip().lower(): v for k, v in record.items()}
        if not isinstance(row.get("date"), str) or not isinstance(row.get("holiday"), str):
            raise ValueError("Every source row must have text date and holiday fields.")
        day = date.fromisoformat(row["date"].strip())
        name = " ".join(row["holiday"].split())
        if not name or len(name) > 200:
            raise ValueError("Holiday name is empty or exceeds 200 characters.")
        key = ("SG", day, name)
        cleaned[key] = (*key, DATASET_ID, fetched_at.replace(tzinfo=None))
    if not cleaned:
        raise ValueError("No validated rows; refusing to refresh the database.")
    rows = [cleaned[key] for key in sorted(cleaned)]
    path = ROOT / "data" / "processed" / "sg_public_holidays.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["country_code", "holiday_date", "holiday_name",
                         "source_dataset_id", "fetched_at_utc"])
        writer.writerows(rows)
    print(f"Validated {len(rows)} rows; removed {len(records) - len(rows)} exact duplicates")
    print(f"Date range: {rows[0][1]} to {rows[-1][1]}")
    print(f"Clean CSV: {path}")
    for row in rows[:5]:
        print(row[:3])
    return rows


def load_and_analyse(rows, host, port, user):
    password = getpass(f"MySQL password for {user}: ")
    connection = mysql.connector.connect(
        host=host, port=port, user=user, password=password,
        database=DATABASE, charset="utf8mb4", connection_timeout=10,
        autocommit=False,
    )
    cursor = connection.cursor()
    try:
        cursor.execute(CREATE_TABLE_SQL)
        connection.commit()  # DDL is outside the data-refresh transaction.
        connection.start_transaction()
        try:
            # Replace only this source's SG staging snapshot, atomically.
            cursor.execute(
                "DELETE FROM stg_public_holidays "
                "WHERE country_code = %s AND source_dataset_id = %s",
                ("SG", DATASET_ID),
            )
            cursor.executemany(
                "INSERT INTO stg_public_holidays "
                "(country_code, holiday_date, holiday_name, "
                "source_dataset_id, fetched_at_utc) VALUES (%s, %s, %s, %s, %s)",
                rows,
            )
            cursor.execute(
                "SELECT COUNT(*) FROM stg_public_holidays "
                "WHERE country_code = %s AND source_dataset_id = %s",
                ("SG", DATASET_ID),
            )
            if cursor.fetchone()[0] != len(rows):
                raise ValueError("Database row-count validation failed.")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        print(f"Committed {len(rows)} rows to {DATABASE}.stg_public_holidays")

        cursor.execute(SUMMARY_SQL, ("SG", DATASET_ID))
        summary = cursor.fetchall()
        output = ROOT / "outputs" / "holiday_summary.csv"
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([column[0] for column in cursor.description])
            writer.writerows(summary)
        print("calendar_year | holiday_records | holiday_dates")
        for year, record_count, date_count in summary:
            print(f"{year} | {record_count} | {date_count}")
        print(f"Analysis CSV: {output}")
    finally:
        cursor.close()
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract-only", action="store_true",
                        help="Fetch and clean data without connecting to MySQL")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--user", default="root")
    args = parser.parse_args()
    records, fetched_at = fetch_holidays()
    rows = clean_holidays(records, fetched_at)
    if args.extract_only:
        print("EXTRACT OK. Next: create the database, then run without --extract-only.")
        return
    load_and_analyse(rows, args.host, args.port, args.user)
    print("PIPELINE OK")


if __name__ == "__main__":
    try:
        main()
    except (requests.RequestException, mysql.connector.Error, ValueError, OSError) as exc:
        print(f"ERROR [{type(exc).__name__}]: {exc}", file=sys.stderr)
        sys.exit(1)
```


## Appendix B: Complete dependency list

File:`requirements.txt`

```text
requests==2.34.2
mysql-connector-python==26.7.0
```


## Appendix C: Complete database-creation SQL

File:`sql/00_create_database.sql`

```sql
-- Run in MySQL Workbench or at the mysql> prompt, not in PowerShell.
CREATE DATABASE IF NOT EXISTS beverage_intelligence
  CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
USE beverage_intelligence;
SELECT DATABASE() AS selected_database, VERSION() AS mysql_version;
```


## Appendix D: Complete validation and analysis SQL

File:`sql/01_verify_and_analyse.sql`

```sql
USE beverage_intelligence;

-- Preview the source staging table.
SELECT country_code, holiday_date, holiday_name, fetched_at_utc
FROM stg_public_holidays
ORDER BY holiday_date, holiday_name
LIMIT 10;

-- Compare row_count with the Python 'Validated ... rows' message.
SELECT COUNT(*) AS row_count,
       MIN(holiday_date) AS earliest_holiday,
       MAX(holiday_date) AS latest_holiday
FROM stg_public_holidays
WHERE country_code = 'SG'
  AND source_dataset_id = 'd_8ef23381f9417e4d4254ee8b4dcdb176';

-- Calendar exploration: these are NOT sales or demand results.
SELECT YEAR(holiday_date) AS calendar_year,
       COUNT(*) AS holiday_records,
       COUNT(DISTINCT holiday_date) AS holiday_dates
FROM stg_public_holidays
WHERE country_code = 'SG'
GROUP BY YEAR(holiday_date)
ORDER BY calendar_year;

-- Count holiday dates in each month of the planning year.
SELECT MONTH(holiday_date) AS calendar_month,
       COUNT(DISTINCT holiday_date) AS holiday_dates
FROM stg_public_holidays
WHERE country_code = 'SG'
  AND holiday_date >= '2026-01-01' AND holiday_date < '2027-01-01'
GROUP BY MONTH(holiday_date)
ORDER BY calendar_month;

-- Multiple holidays on a date are valid, not necessarily duplicates.
SELECT holiday_date, COUNT(*) AS names_on_date
FROM stg_public_holidays
WHERE country_code = 'SG'
GROUP BY holiday_date
HAVING COUNT(*) > 1;
```
