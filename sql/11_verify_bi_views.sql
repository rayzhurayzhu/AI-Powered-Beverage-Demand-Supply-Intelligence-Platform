-- STEP 7B | Run the entire file. Five result sets.
USE beverage_intelligence;

-- RESULT 1: 11 table/view counts; expected values appear beside actual values.
SELECT 'ReportContext' AS table_name,COUNT(*) AS row_count,1 AS expected_count FROM vw_bi_context
UNION ALL SELECT 'DimDate',COUNT(*),2922 FROM vw_bi_dim_date
UNION ALL SELECT 'DimProduct',COUNT(*),6 FROM vw_bi_dim_product
UNION ALL SELECT 'DimChannel',COUNT(*),3 FROM vw_bi_dim_channel
UNION ALL SELECT 'DimWarehouse',COUNT(*),1 FROM vw_bi_dim_warehouse
UNION ALL SELECT 'DimStress',COUNT(*),4 FROM vw_bi_dim_stress
UNION ALL SELECT 'DimPlanPath',COUNT(*),2 FROM vw_bi_dim_plan_path
UNION ALL SELECT 'FactSales',COUNT(*),18072 FROM vw_bi_sales
UNION ALL SELECT 'FactForecast',COUNT(*),714 FROM vw_bi_forecast
UNION ALL SELECT 'FactDecision',COUNT(*),6 FROM vw_bi_decision
UNION ALL SELECT 'FactProjection',COUNT(*),4032 FROM vw_bi_projection;

-- RESULT 2: eight checks, ALL failed_rows = 0; counts above must also match.
SELECT 'sales_units_reconciliation' AS check_name,
 ABS((SELECT COALESCE(SUM(units_sold),0) FROM vw_bi_sales)-
     (SELECT COALESCE(SUM(units_sold),0) FROM fact_sales WHERE scenario_id='beverage_demo_v1')) AS failed_rows
UNION ALL SELECT 'sales_revenue_reconciliation',
 ABS((SELECT COALESCE(SUM(revenue_sgd),0) FROM vw_bi_sales)-
     (SELECT COALESCE(SUM(revenue_sgd),0) FROM fact_sales WHERE scenario_id='beverage_demo_v1'))
UNION ALL SELECT 'forecast_duplicate_grains',COUNT(*) FROM (
 SELECT product_id,warehouse_id,date_id FROM vw_bi_forecast GROUP BY product_id,warehouse_id,date_id HAVING COUNT(*)<>1) x
UNION ALL SELECT 'holdout_missing_actuals',COUNT(*) FROM vw_bi_forecast
 WHERE forecast_phase='holdout' AND (actual_units IS NULL OR zero_stock_flag IS NULL)
UNION ALL SELECT 'production_has_future_actuals',COUNT(*) FROM vw_bi_forecast
 WHERE forecast_phase='production' AND (actual_units IS NOT NULL OR zero_stock_flag IS NOT NULL)
UNION ALL SELECT 'decision_duplicate_grains',COUNT(*) FROM (
 SELECT product_id,warehouse_id FROM vw_bi_decision GROUP BY product_id,warehouse_id HAVING COUNT(*)<>1) x
UNION ALL SELECT 'decision_cost_reconciliation',
 ABS((SELECT COALESCE(SUM(estimated_purchase_cost_sgd),0) FROM vw_bi_decision)-
     (SELECT COALESCE(SUM(estimated_purchase_cost_sgd),0) FROM fact_replenishment_recommendation WHERE planning_run_id='planner_v1_20260930'))
UNION ALL SELECT 'projection_duplicate_grains',COUNT(*) FROM (
 SELECT product_id,warehouse_id,stress_name,plan_path,date_id FROM vw_bi_projection
 GROUP BY product_id,warehouse_id,stress_name,plan_path,date_id HAVING COUNT(*)<>1) x;

-- RESULT 3: the eight Executive Overview cards, all products, no slicer selection.
-- WAPE here is a RATIO: Power BI percentage formatting displays it as a percent.
SELECT
 (SELECT SUM(s.revenue_sgd) FROM vw_bi_sales s JOIN dim_date d ON d.date_id=s.date_id CROSS JOIN vw_bi_context c
  WHERE d.calendar_date BETWEEN DATE_SUB(c.as_of_date,INTERVAL 27 DAY) AND c.as_of_date) AS revenue_last_28d_sgd,
 (SELECT SUM(s.units_sold) FROM vw_bi_sales s JOIN dim_date d ON d.date_id=s.date_id CROSS JOIN vw_bi_context c
  WHERE d.calendar_date BETWEEN DATE_SUB(c.as_of_date,INTERVAL 27 DAY) AND c.as_of_date) AS units_last_28d,
 (SELECT SUM(ABS(forecast_units-actual_units))/NULLIF(SUM(actual_units),0) FROM vw_bi_forecast
  WHERE forecast_phase='holdout' AND zero_stock_flag=0) AS holdout_wape_ratio,
 SUM(stockout_14d_flag) AS stockout_risk_skus_14d,SUM(on_hand_units) AS on_hand_units,
 SUM(open_order_units) AS inbound_units,SUM(estimated_purchase_cost_sgd) AS proposed_purchase_sgd,
 SUM(excess_commitment_flag) AS excess_commitment_skus
FROM vw_bi_decision;

-- RESULT 4: 6 decision rows for the report's action table.
SELECT p.sku_code,d.model_display_name,d.first_shortage_date_existing,
       d.recommended_cases,d.recommended_units,d.proposed_order_date,d.proposed_arrival_date,
       d.estimated_purchase_cost_sgd,d.recommended_action
FROM vw_bi_decision d JOIN dim_product p ON p.product_id=d.product_id ORDER BY p.sku_code;

-- RESULT 5: temporal boundaries: historical holdout + production, not multiple overlapping runs.
SELECT f.forecast_phase,COUNT(*) AS row_count,MIN(d.calendar_date) AS first_day,MAX(d.calendar_date) AS last_day
FROM vw_bi_forecast f JOIN dim_date d ON d.date_id=f.date_id GROUP BY f.forecast_phase ORDER BY f.forecast_phase;
