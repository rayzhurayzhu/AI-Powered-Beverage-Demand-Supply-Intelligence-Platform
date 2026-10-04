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
