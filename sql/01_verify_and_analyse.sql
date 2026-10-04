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
