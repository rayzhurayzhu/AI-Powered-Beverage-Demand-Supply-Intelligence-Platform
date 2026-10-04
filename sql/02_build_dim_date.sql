-- Beverage Demand & Supply Decision Platform | Step 2
-- Run this WHOLE file in MySQL Workbench (MySQL Server 8.0+).
-- Prerequisite: Step 1 has successfully loaded stg_public_holidays.
-- Date grain: exactly one row per calendar date.
-- Current planning calendar: 2020-01-01 through 2027-12-31 (2922 days).
-- SG coverage is based on the source's documented coverage, NOT MAX(holiday_date).
-- Existing staging data is read only. Rerunning refreshes existing date attributes.
-- Run in a fresh query tab, with no other uncommitted work on this connection.

USE beverage_intelligence;

CREATE TABLE IF NOT EXISTS dim_date (
    date_id INT NOT NULL COMMENT 'YYYYMMDD key; use calendar_date for date arithmetic',
    calendar_date DATE NOT NULL,
    calendar_year SMALLINT NOT NULL,
    calendar_quarter TINYINT NOT NULL,
    calendar_month TINYINT NOT NULL,
    day_of_month TINYINT NOT NULL,
    day_of_week TINYINT NOT NULL COMMENT '1=Monday through 7=Sunday',
    is_weekend TINYINT NOT NULL COMMENT '1=Saturday/Sunday; not a warehouse-closure flag',
    is_sg_public_holiday TINYINT NULL COMMENT '1=yes, 0=no, NULL=coverage unknown',
    sg_holiday_count SMALLINT NULL COMMENT 'Named holidays on this date; NULL=unknown',
    PRIMARY KEY (date_id),
    UNIQUE KEY uq_dim_date_calendar_date (calendar_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- Build a small sequence without changing recursion or SQL safety settings.
-- The INSERT is a single InnoDB statement; source data is not modified.
INSERT INTO dim_date (
    date_id, calendar_date, calendar_year, calendar_quarter,
    calendar_month, day_of_month, day_of_week, is_weekend,
    is_sg_public_holiday, sg_holiday_count
)
WITH
digits AS (
    SELECT 0 AS n UNION ALL SELECT 1 UNION ALL SELECT 2
    UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5
    UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8
    UNION ALL SELECT 9
),
numbers AS (
    SELECT a.n + 10 * b.n + 100 * c.n + 1000 * d.n AS n
    FROM digits AS a
    CROSS JOIN digits AS b
    CROSS JOIN digits AS c
    CROSS JOIN digits AS d
),
calendar_dates AS (
    SELECT DATE_ADD(CAST('2020-01-01' AS DATE), INTERVAL n DAY) AS calendar_date
    FROM numbers
    WHERE n <= DATEDIFF('2027-12-31', '2020-01-01')
),
holiday_by_date AS (
    SELECT holiday_date, COUNT(*) AS holiday_count
    FROM stg_public_holidays
    WHERE country_code = 'SG'
      AND source_dataset_id = 'd_8ef23381f9417e4d4254ee8b4dcdb176'
    GROUP BY holiday_date
),
source_status AS (
    SELECT COUNT(*) AS source_dates FROM holiday_by_date
),
incoming AS (
    SELECT
        YEAR(c.calendar_date) * 10000
          + MONTH(c.calendar_date) * 100
          + DAYOFMONTH(c.calendar_date) AS new_date_id,
        c.calendar_date AS new_calendar_date,
        YEAR(c.calendar_date) AS new_calendar_year,
        QUARTER(c.calendar_date) AS new_calendar_quarter,
        MONTH(c.calendar_date) AS new_calendar_month,
        DAYOFMONTH(c.calendar_date) AS new_day_of_month,
        WEEKDAY(c.calendar_date) + 1 AS new_day_of_week,
        CASE WHEN WEEKDAY(c.calendar_date) >= 5 THEN 1 ELSE 0 END AS new_is_weekend,
        CASE
            WHEN s.source_dates = 0 THEN NULL
            WHEN c.calendar_date < '2020-01-01'
              OR c.calendar_date > '2027-12-31' THEN NULL
            WHEN h.holiday_date IS NOT NULL THEN 1
            ELSE 0
        END AS new_is_sg_public_holiday,
        CASE
            WHEN s.source_dates = 0 THEN NULL
            WHEN c.calendar_date < '2020-01-01'
              OR c.calendar_date > '2027-12-31' THEN NULL
            ELSE COALESCE(h.holiday_count, 0)
        END AS new_sg_holiday_count
    FROM calendar_dates AS c
    LEFT JOIN holiday_by_date AS h ON c.calendar_date = h.holiday_date
    CROSS JOIN source_status AS s
)
SELECT
    new_date_id, new_calendar_date, new_calendar_year, new_calendar_quarter,
    new_calendar_month, new_day_of_month, new_day_of_week, new_is_weekend,
    new_is_sg_public_holiday, new_sg_holiday_count
FROM incoming
ON DUPLICATE KEY UPDATE
    calendar_date = new_calendar_date,
    calendar_year = new_calendar_year,
    calendar_quarter = new_calendar_quarter,
    calendar_month = new_calendar_month,
    day_of_month = new_day_of_month,
    day_of_week = new_day_of_week,
    is_weekend = new_is_weekend,
    is_sg_public_holiday = new_is_sg_public_holiday,
    sg_holiday_count = new_sg_holiday_count;

COMMIT;

-- CHECK 1. Expected currently: 2922 rows, 2922 distinct dates,
-- 2020-01-01 to 2027-12-31, 104 holiday dates, 0 unknown dates.
SELECT
    COUNT(*) AS total_dates,
    COUNT(DISTINCT calendar_date) AS unique_dates,
    MIN(calendar_date) AS start_date,
    MAX(calendar_date) AS end_date,
    SUM(is_sg_public_holiday = 1) AS sg_holiday_dates,
    SUM(is_sg_public_holiday IS NULL) AS unknown_holiday_dates,
    DATEDIFF(MAX(calendar_date), MIN(calendar_date)) + 1 - COUNT(*) AS missing_dates
FROM dim_date;

-- CHECK 2. Leap years 2020/2024 should have 366 calendar days.
-- Other years have 365. SG holiday counts should match Step 1's DISTINCT dates.
SELECT calendar_year, COUNT(*) AS calendar_days,
       SUM(is_sg_public_holiday = 1) AS sg_holiday_dates
FROM dim_date
GROUP BY calendar_year
ORDER BY calendar_year;

-- CHECK 3. Expected mismatched_dates: 0 (including missing or extra flags).
SELECT COUNT(*) AS mismatched_dates
FROM dim_date AS d
LEFT JOIN (
    SELECT holiday_date, COUNT(*) AS holiday_count
    FROM stg_public_holidays
    WHERE country_code = 'SG'
      AND source_dataset_id = 'd_8ef23381f9417e4d4254ee8b4dcdb176'
    GROUP BY holiday_date
) AS h ON d.calendar_date = h.holiday_date
WHERE NOT (d.is_sg_public_holiday <=> IF(h.holiday_date IS NULL, 0, 1))
   OR NOT (d.sg_holiday_count <=> COALESCE(h.holiday_count, 0));

-- CHECK 4. Leap day, holiday and ordinary date examples.
SELECT * FROM dim_date
WHERE calendar_date IN ('2024-02-29', '2026-01-01', '2026-01-02', '2026-01-03')
ORDER BY calendar_date;

-- Sources checked 2026-10-04:
-- https://dev.mysql.com/doc/refman/8.0/en/with.html
-- https://dev.mysql.com/doc/refman/8.0/en/insert-on-duplicate.html
-- https://dev.mysql.com/doc/refman/8.0/en/date-and-time-functions.html
-- https://data.gov.sg/datasets/d_8ef23381f9417e4d4254ee8b4dcdb176/view
-- Validation: date-range and source reconciliation checked independently in Python.
-- No MySQL Server is available in the authoring environment; run CHECK 1-4 locally.
-- After a successful Step 1 refresh, rerun this file to refresh the SG flags.
-- To extend beyond 2027, extend calendar_dates only; update holiday coverage
-- bounds only after verifying a newly published and successfully loaded source.
-- Neither weekends nor public holidays imply a specific warehouse/supplier is closed.
