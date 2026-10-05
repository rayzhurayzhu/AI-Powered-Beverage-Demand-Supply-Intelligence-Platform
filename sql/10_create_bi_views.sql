-- STEP 7A | Reporting contract for ONE explicit scenario/forecast/planning run.
-- These views do not write or join raw facts to other raw facts without aggregation.
USE beverage_intelligence;

CREATE OR REPLACE VIEW vw_bi_context AS
SELECT pr.planning_run_id,fr.run_id AS forecast_run_id,fr.scenario_id,pr.as_of_date,
       ds.history_start,DATE_ADD(pr.as_of_date,INTERVAL 1 DAY) AS forecast_start,
       DATE_ADD(pr.as_of_date,INTERVAL pr.horizon_days DAY) AS forecast_end,
       pr.horizon_days,fr.backtest_days,pr.data_origin
FROM planning_run pr JOIN forecast_run fr ON fr.run_id=pr.forecast_run_id
JOIN dim_scenario ds ON ds.scenario_id=fr.scenario_id
WHERE pr.planning_run_id='planner_v1_20260930' AND fr.run_id='baseline_v1_20260930'
  AND ds.scenario_id='beverage_demo_v1' AND pr.as_of_date=fr.as_of_date
  AND pr.as_of_date=ds.as_of_date;

CREATE OR REPLACE VIEW vw_bi_dim_date AS
SELECT date_id,calendar_date,calendar_year,calendar_quarter,calendar_month,
       CONCAT(calendar_year,'-',LPAD(calendar_month,2,'0')) AS year_month,
       calendar_year*100+calendar_month AS year_month_sort,day_of_month,day_of_week,
       is_weekend,is_sg_public_holiday
FROM dim_date;

CREATE OR REPLACE VIEW vw_bi_dim_product AS
SELECT product_id,sku_code,product_name,brand_name,category,container_type,unit_volume_ml,units_per_case
FROM dim_product WHERE product_id BETWEEN 1 AND 6;

CREATE OR REPLACE VIEW vw_bi_dim_channel AS
SELECT channel_id,channel_code,channel_name FROM dim_channel;

CREATE OR REPLACE VIEW vw_bi_dim_warehouse AS
SELECT warehouse_id,warehouse_code,warehouse_name,country_code FROM dim_warehouse WHERE warehouse_id=1;

CREATE OR REPLACE VIEW vw_bi_dim_stress AS
SELECT 'base' AS stress_name,'Base demand' AS stress_label,1 AS sort_order
UNION ALL SELECT 'demand_up_20','Demand +20%',2
UNION ALL SELECT 'demand_down_20','Demand -20%',3
UNION ALL SELECT 'arrival_delay_7','Arrivals +7 days',4;

CREATE OR REPLACE VIEW vw_bi_dim_plan_path AS
SELECT 'existing_only' AS plan_path,'Existing stock and POs only' AS plan_label,1 AS sort_order
UNION ALL SELECT 'with_recommendation','Including one proposed order',2;

CREATE OR REPLACE VIEW vw_bi_sales AS
SELECT s.date_id,s.product_id,s.warehouse_id,s.channel_id,s.units_sold,s.revenue_sgd,
       CAST(s.units_sold*p.unit_volume_ml/1000.0 AS DECIMAL(16,4)) AS volume_litres,s.is_promotion
FROM fact_sales s JOIN vw_bi_context c ON c.scenario_id=s.scenario_id
JOIN dim_product p ON p.product_id=s.product_id;

-- Grain: chosen model x target date x SKU x warehouse. Only ONE origin per phase.
-- Selected holdout: 210 rows. Production: 504 rows. No other model candidates.
-- Actuals stay NULL in production. Available-stock WAPE excludes zero-stock targets.
CREATE OR REPLACE VIEW vw_bi_forecast AS
SELECT f.target_date_id AS date_id,f.product_id,f.warehouse_id,f.model_name,f.origin_date,
       f.split_name AS forecast_phase,f.forecast_units,
       CASE WHEN f.split_name='holdout' THEN a.actual_units ELSE NULL END AS actual_units,
       CASE WHEN f.split_name='holdout' THEN i.zero_stock_flag ELSE NULL END AS zero_stock_flag
FROM fact_forecast f JOIN vw_bi_context c ON c.forecast_run_id=f.run_id
JOIN forecast_model_selection s ON s.run_id=f.run_id AND s.product_id=f.product_id
 AND s.warehouse_id=f.warehouse_id AND s.model_name=f.model_name
LEFT JOIN (SELECT date_id,product_id,warehouse_id,SUM(units_sold) AS actual_units
           FROM vw_bi_sales GROUP BY date_id,product_id,warehouse_id) a
 ON a.date_id=f.target_date_id AND a.product_id=f.product_id AND a.warehouse_id=f.warehouse_id
LEFT JOIN fact_inventory i ON i.scenario_id=c.scenario_id AND i.date_id=f.target_date_id
 AND i.product_id=f.product_id AND i.warehouse_id=f.warehouse_id
WHERE f.split_name IN ('holdout','production');

-- This is an AS-OF snapshot. Deliberately do not relate it to the history date slicer.
CREATE OR REPLACE VIEW vw_bi_decision AS
SELECT r.product_id,r.warehouse_id,r.supplier_id,s.supplier_code,r.model_name,
       CASE r.model_name WHEN 'mean_28' THEN '28-Day Average'
         WHEN 'weekday_mean_56' THEN '8-Week Weekday Average'
         WHEN 'seasonal_naive_7' THEN 'Same Day Last Week' ELSE r.model_name END AS model_display_name,
       r.on_hand_units,r.open_order_units,r.stock_cover_days,r.stock_cover_capped,
       r.first_shortage_date_existing,r.latest_normal_order_date,r.scheduled_review_date,
       r.proposed_order_date,r.proposed_arrival_date,r.coverage_end_date,
       r.recommended_cases,r.recommended_units,r.estimated_purchase_cost_sgd,
       r.unmet_before_arrival_units,r.unmet_14d_units,r.committed_excess_units,
       r.action_code,
       CASE r.action_code WHEN 'EXPEDITE_REVIEW' THEN 'Review urgent supply options'
         WHEN 'ORDER_EARLY' THEN 'Bring the order review forward'
         WHEN 'ORDER_AT_REVIEW' THEN 'Order at scheduled review'
         WHEN 'REVIEW_EXCESS' THEN 'Review excess committed supply'
         ELSE 'Monitor at the next review' END AS recommended_action,
       r.lead_time_days,r.review_period_days,r.safety_stock_days,
       r.max_cover_days,r.units_per_case,r.min_order_cases,r.order_multiple_cases,
       r.net_required_units,r.safety_target_units,r.landed_cost_per_case_sgd,
       CASE WHEN r.unmet_14d_units>0 THEN 1 ELSE 0 END AS stockout_14d_flag,
       CASE WHEN r.unmet_before_arrival_units>0 THEN 1 ELSE 0 END AS urgent_supply_flag,
       CASE WHEN r.committed_excess_units>0 THEN 1 ELSE 0 END AS excess_commitment_flag,
       ms.validation_wape_pct,ms.holdout_wape_pct,ms.holdout_bias_pct,
       ms.holdout_scored_days,ms.holdout_excluded_days,ms.training_imputed_days
FROM fact_replenishment_recommendation r JOIN vw_bi_context c ON c.planning_run_id=r.planning_run_id
JOIN dim_supplier s ON s.supplier_id=r.supplier_id
JOIN forecast_model_selection ms ON ms.run_id=c.forecast_run_id AND ms.product_id=r.product_id AND ms.warehouse_id=r.warehouse_id;

CREATE OR REPLACE VIEW vw_bi_projection AS
SELECT d.date_id,p.product_id,p.warehouse_id,p.stress_name,p.plan_path,
       p.opening_units,p.existing_receipt_units,p.recommended_receipt_units,
       p.demand_units,p.fulfilled_units,p.unmet_units,p.closing_units
FROM fact_inventory_projection p JOIN vw_bi_context c ON c.planning_run_id=p.planning_run_id
JOIN dim_date d ON d.calendar_date=p.projection_date;

SELECT 'BI VIEWS READY' AS setup_status;
