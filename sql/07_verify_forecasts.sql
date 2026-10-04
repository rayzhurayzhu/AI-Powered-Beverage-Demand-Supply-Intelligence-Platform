-- STEP 5C: run this entire file AFTER the Python script.
USE beverage_intelligence;
SET @forecast_run = 'baseline_v1_20260930';

-- RESULT 1: 1 / 3024 / 144 / 6 / 504, respectively.
SELECT 'forecast_run' AS table_name, COUNT(*) AS row_count
FROM forecast_run WHERE run_id=@forecast_run
UNION ALL SELECT 'fact_forecast', COUNT(*) FROM fact_forecast WHERE run_id=@forecast_run
UNION ALL SELECT 'forecast_evaluation', COUNT(*) FROM forecast_evaluation WHERE run_id=@forecast_run
UNION ALL SELECT 'forecast_model_selection', COUNT(*) FROM forecast_model_selection WHERE run_id=@forecast_run
UNION ALL SELECT 'production_forecast_rows', COUNT(*) FROM fact_forecast
WHERE run_id=@forecast_run AND split_name='production';

-- RESULT 2: ten checks, ALL failed_rows = 0 (also require the counts above).
WITH run_info AS (
    SELECT * FROM forecast_run WHERE run_id=@forecast_run
), f AS (
    SELECT ff.*, d.calendar_date AS target_date
    FROM fact_forecast ff JOIN dim_date d ON d.date_id=ff.target_date_id
    WHERE ff.run_id=@forecast_run
), prod AS (
    SELECT product_id,warehouse_id,COUNT(*) AS n, MIN(target_date) AS first_day,
           MAX(target_date) AS last_day, COUNT(DISTINCT target_date) AS distinct_days
    FROM f WHERE split_name='production' GROUP BY product_id,warehouse_id
), folds AS (
    SELECT product_id,warehouse_id,model_name,origin_date,split_name,
           COUNT(*) AS n, MIN(target_date) AS first_day, MAX(target_date) AS last_day
    FROM f WHERE split_name<>'production'
    GROUP BY product_id,warehouse_id,model_name,origin_date,split_name
), scores AS (
    SELECT product_id,warehouse_id,model_name,
           SUM(absolute_error_units)/NULLIF(SUM(actual_units),0)*100 AS validation_wape
    FROM forecast_evaluation WHERE run_id=@forecast_run AND split_name='validation'
      AND evaluation_scope='available_stock' GROUP BY product_id,warehouse_id,model_name
)
SELECT 'invalid_forecast_dates' AS check_name, COUNT(*) AS failed_rows FROM f
CROSS JOIN run_info r WHERE f.target_date<=f.origin_date
 OR (f.split_name='production' AND (f.origin_date<>r.as_of_date OR f.target_date<=r.as_of_date))
 OR (f.split_name<>'production' AND f.target_date>r.as_of_date)
UNION ALL SELECT 'negative_forecasts', COUNT(*) FROM f WHERE forecast_units<0
UNION ALL SELECT 'production_coverage_errors', COUNT(*) FROM prod CROSS JOIN run_info r
WHERE n<>r.horizon_days OR distinct_days<>r.horizon_days
 OR first_day<>DATE_ADD(r.as_of_date,INTERVAL 1 DAY)
 OR last_day<>DATE_ADD(r.as_of_date,INTERVAL r.horizon_days DAY)
UNION ALL SELECT 'backtest_coverage_errors', COUNT(*) FROM folds CROSS JOIN run_info r
WHERE n<>r.backtest_days OR first_day<>DATE_ADD(origin_date,INTERVAL 1 DAY)
 OR last_day<>DATE_ADD(origin_date,INTERVAL r.backtest_days DAY)
 OR (split_name='holdout' AND last_day<>r.as_of_date)
 OR (split_name='validation' AND last_day>DATE_SUB(r.as_of_date,INTERVAL r.backtest_days DAY))
UNION ALL SELECT 'selected_model_mismatches', COUNT(*) FROM f
LEFT JOIN forecast_model_selection s ON s.run_id=f.run_id AND s.product_id=f.product_id
 AND s.warehouse_id=f.warehouse_id
WHERE f.split_name='production' AND (s.model_name IS NULL OR s.model_name<>f.model_name)
UNION ALL SELECT 'metric_day_count_errors', COUNT(*) FROM forecast_evaluation e CROSS JOIN run_info r
WHERE e.run_id=@forecast_run AND (scored_days+excluded_days<>r.backtest_days
 OR (evaluation_scope='all_days' AND excluded_days<>0)
 OR (evaluation_scope='available_stock' AND scored_days<14))
UNION ALL SELECT 'metric_arithmetic_errors', COUNT(*) FROM forecast_evaluation e
WHERE e.run_id=@forecast_run AND (
 NOT (e.mae_units <=> ROUND(e.absolute_error_units/NULLIF(e.scored_days,0),4))
 OR NOT (e.wape_pct <=> ROUND(100*e.absolute_error_units/NULLIF(e.actual_units,0),4))
 OR NOT (e.bias_pct <=> ROUND(100*e.signed_error_units/NULLIF(e.actual_units,0),4)))
UNION ALL SELECT 'selection_score_errors', COUNT(*) FROM forecast_model_selection s
LEFT JOIN scores c ON c.product_id=s.product_id AND c.warehouse_id=s.warehouse_id AND c.model_name=s.model_name
WHERE s.run_id=@forecast_run AND (c.validation_wape IS NULL OR ABS(s.validation_wape_pct-c.validation_wape)>0.0001)
UNION ALL SELECT 'non_minimum_validation_selection', COUNT(*) FROM forecast_model_selection s
JOIN scores chosen ON chosen.product_id=s.product_id AND chosen.warehouse_id=s.warehouse_id AND chosen.model_name=s.model_name
JOIN scores candidate ON candidate.product_id=s.product_id AND candidate.warehouse_id=s.warehouse_id
WHERE s.run_id=@forecast_run AND candidate.validation_wape < chosen.validation_wape - 0.00000001
UNION ALL SELECT 'policy_horizon_errors', COUNT(*) FROM sku_supply_policy p CROSS JOIN run_info r
WHERE p.warehouse_id=1 AND (p.lead_time_days+p.review_period_days>r.backtest_days
 OR p.max_cover_days>r.horizon_days);

-- RESULT 3: six SKU model choices. WAPE is a percentage, not accuracy = 100-WAPE.
-- These displayed errors EXCLUDE zero-stock days. See Result 5 for both scopes.
SELECT p.sku_code, s.model_name, s.validation_wape_pct, s.holdout_wape_pct,
       s.holdout_bias_pct, s.holdout_scored_days, s.holdout_excluded_days,
       s.training_imputed_days
FROM forecast_model_selection s JOIN dim_product p ON p.product_id=s.product_id
WHERE s.run_id=@forecast_run ORDER BY p.sku_code;

-- RESULT 4: six planning summaries. 84 days = 2026-10-01 through 2026-12-23.
SELECT f.sku_code, f.model_name, MIN(f.forecast_date) AS forecast_start,
       MAX(f.forecast_date) AS forecast_end, COUNT(*) AS forecast_days,
       ROUND(SUM(CASE WHEN f.forecast_date<=DATE_ADD(f.as_of_date,INTERVAL 14 DAY)
                      THEN f.forecast_units ELSE 0 END),2) AS forecast_units_14d,
       p.lead_time_days+p.review_period_days AS protection_days,
       ROUND(SUM(CASE WHEN DATEDIFF(f.forecast_date,f.as_of_date)<=p.lead_time_days+p.review_period_days
                      THEN f.forecast_units ELSE 0 END),2) AS forecast_units_protection_period,
       ROUND(SUM(f.forecast_units),2) AS forecast_units_84d
FROM vw_forecast_daily_production f JOIN sku_supply_policy p
 ON p.product_id=f.product_id AND p.warehouse_id=f.warehouse_id
WHERE f.run_id=@forecast_run GROUP BY f.sku_code,f.model_name,p.lead_time_days,p.review_period_days
ORDER BY f.sku_code;

-- RESULT 5: 12 rows: selected-model holdout scores, two evaluation scopes per SKU.
SELECT p.sku_code,e.model_name,e.evaluation_scope,e.scored_days,e.excluded_days,
       e.mae_units,e.wape_pct,e.bias_pct
FROM forecast_evaluation e JOIN forecast_model_selection s
 ON s.run_id=e.run_id AND s.product_id=e.product_id AND s.warehouse_id=e.warehouse_id AND s.model_name=e.model_name
JOIN dim_product p ON p.product_id=e.product_id
WHERE e.run_id=@forecast_run AND e.split_name='holdout'
ORDER BY p.sku_code,e.evaluation_scope;
