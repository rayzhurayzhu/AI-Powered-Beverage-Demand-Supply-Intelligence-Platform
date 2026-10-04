# Validation notes — 2026-10-04

Executed in the authoring environment:

- Installed and imported requests 2.34.2 and mysql-connector-python 26.7.0 on Python 3.12.
- Ran `python scripts/holiday_pipeline.py --extract-only` against the live government endpoint.
- Received 100 rows then 4 rows; API total 104.
- Saved both original JSON response payloads and an extraction manifest.
- Validated 104 rows; zero exact business-key duplicates removed.
- Wrote cleaned CSV; date range 2020-01-01 through 2027-12-25.
- Seven offline unittest cases passed: pagination, truncated extract rejection, exact duplicate removal, multiple names on one date, invalid/empty source rejection, mocked rollback, mocked successful load/export.

Not executed here: real MySQL Server integration. No MySQL Server is installed in this environment. The connector import and mock checks do not establish that local credentials, service configuration or live database transactions work.

Local acceptance:

1. Create beverage_intelligence using sql/00_create_database.sql.
2. Run the full pipeline against local MySQL 8.0+; enter password at prompt.
3. Check SQL count equals Python validated count, and inspect annual summary.
4. Run again and confirm the same source snapshot does not double row count.
5. Confirm outputs/holiday_summary.csv exists and matches SQL results.

Only after these checks should the local MySQL module be described as working end to end. Forecasting, inventory planning, Power BI, GenAI, deployment and user adoption have not yet been implemented by this starter.
