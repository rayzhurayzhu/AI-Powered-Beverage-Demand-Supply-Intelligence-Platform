# Public holiday staging contract

Status: first external-data module; not the complete warehouse schema.

Source: Ministry of Manpower, Singapore Public Holidays (consolidated), data.gov.sg.
Dataset ID: `d_8ef23381f9417e4d4254ee8b4dcdb176`.
Accessed and successfully extracted: 2026-10-04 UTC.
Official coverage on that date: January 2020 to December 2027.
Observed extract: 104 rows, earliest holiday 2020-01-01, latest holiday 2027-12-25.

| Column | MySQL type | Meaning |
|---|---|---|
| country_code | CHAR(2) | SG; supplied by this single-country source contract |
| holiday_date | DATE | Singapore local calendar date, parsed from source date |
| holiday_name | VARCHAR(200) | Source holiday, whitespace normalized; observed dates retained |
| source_dataset_id | VARCHAR(50) | Official data.gov.sg dataset identifier |
| fetched_at_utc | DATETIME(6) | UTC extraction start; not source publication time |

Primary key: (country_code, holiday_date, holiday_name).
Table: `beverage_intelligence.stg_public_holidays`.
Source `day` is not stored because weekday can be derived from the date.
Source `_id` is retained in raw JSON and checked for unique pagination, not used as a business key.

Refresh: complete validated source snapshot replacement for this dataset/country only, in an InnoDB transaction. No TRUNCATE and no append-only loads. This handles source corrections and deletions. Run a single writer. Historical extracts live in timestamped raw directories, not in the SQL staging table.

Empty results, invalid required fields, repeated source IDs, changing source totals and incomplete pagination fail before database connection. API pagination is not a transactional source snapshot; an upstream edit that preserves total row count could still occur between pages. Raw snapshots support inspection. This small public calendar is appropriate for this portfolio implementation, not a general production ingestion framework.

Downstream contract: aggregate to one row per country/date or use EXISTS to form holiday features. Do not join sales directly to all holiday-name rows. Create a complete daily date dimension separately. Distinguish unknown calendar coverage from a known non-holiday. Keep publication/availability timing in mind in historical model evaluation: today's revised calendar is not necessarily the calendar known at every past forecast origin.

Use holiday flags as candidate features, not evidence of causal sales effects. Keep demand simulation assumptions explicit. No APB proprietary data or measured APB business outcomes are included.
