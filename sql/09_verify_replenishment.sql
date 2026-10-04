-- STEP 6C | Execute the whole file after run_replenishment_planner.py.
USE beverage_intelligence;
SET @planning_run = 'planner_v1_20260930';

-- RESULT 1: expected 1 / 6 / 4032 / 24.
SELECT 'planning_run' AS table_name,COUNT(*) AS row_count FROM planning_run WHERE planning_run_id=@planning_run
UNION ALL SELECT 'fact_replenishment_recommendation',COUNT(*) FROM fact_replenishment_recommendation WHERE planning_run_id=@planning_run
UNION ALL SELECT 'fact_inventory_projection',COUNT(*) FROM fact_inventory_projection WHERE planning_run_id=@planning_run
UNION ALL SELECT 'replenishment_sensitivity',COUNT(*) FROM replenishment_sensitivity WHERE planning_run_id=@planning_run;

-- RESULT 2: 17 checks, ALL failed_rows = 0. Also require correct Result 1 counts.
WITH run_info AS (
 SELECT pr.*,fr.scenario_id FROM planning_run pr JOIN forecast_run fr ON fr.run_id=pr.forecast_run_id
 WHERE pr.planning_run_id=@planning_run
), rec AS (
 SELECT * FROM fact_replenishment_recommendation WHERE planning_run_id=@planning_run
), proj AS (
 SELECT p.*,LAG(p.closing_units) OVER (PARTITION BY p.product_id,p.warehouse_id,p.stress_name,p.plan_path
                                     ORDER BY p.projection_date) AS previous_close
 FROM fact_inventory_projection p WHERE p.planning_run_id=@planning_run
), summary_rows AS (
 SELECT p.product_id,p.warehouse_id,p.stress_name,p.plan_path,COUNT(*) AS n,
        MIN(p.projection_date) AS first_day,MAX(p.projection_date) AS last_day,
        MIN(CASE WHEN p.unmet_units>0 THEN p.projection_date END) AS first_shortage,
        SUM(CASE WHEN p.projection_date<=DATE_ADD(ri.as_of_date,INTERVAL 14 DAY) THEN p.unmet_units ELSE 0 END) AS unmet_14,
        SUM(CASE WHEN p.projection_date<=r.coverage_end_date THEN p.unmet_units ELSE 0 END) AS unmet_cycle,
        SUM(p.unmet_units) AS unmet_84,
        MAX(CASE WHEN p.projection_date=DATE_ADD(ri.as_of_date,INTERVAL ri.horizon_days DAY) THEN p.closing_units END) AS closing_84,
        GREATEST(0,r.on_hand_units+SUM(CASE WHEN DATEDIFF(p.projection_date,ri.as_of_date)<=r.max_cover_days
          THEN p.existing_receipt_units+p.recommended_receipt_units-p.demand_units ELSE 0 END)) AS committed_excess
 FROM proj p JOIN rec r ON r.product_id=p.product_id AND r.warehouse_id=p.warehouse_id CROSS JOIN run_info ri
 GROUP BY p.product_id,p.warehouse_id,p.stress_name,p.plan_path,r.on_hand_units
), po_receipts AS (
 SELECT po.product_id,po.warehouse_id,d.calendar_date AS eta,SUM(po.ordered_units) AS units
 FROM fact_purchase_orders po JOIN dim_date d ON d.date_id=po.expected_arrival_date_id
 JOIN run_info ri ON ri.scenario_id=po.scenario_id WHERE po.order_status='open'
 GROUP BY po.product_id,po.warehouse_id,d.calendar_date
)
SELECT 'negative_projection_values' AS check_name,COUNT(*) AS failed_rows FROM proj
 WHERE LEAST(opening_units,existing_receipt_units,recommended_receipt_units,demand_units,fulfilled_units,unmet_units,closing_units)<0
UNION ALL SELECT 'stock_balance_errors',COUNT(*) FROM proj
 WHERE opening_units+existing_receipt_units+recommended_receipt_units-fulfilled_units<>closing_units
UNION ALL SELECT 'demand_balance_errors',COUNT(*) FROM proj
 WHERE fulfilled_units+unmet_units<>demand_units
 OR fulfilled_units<>LEAST(demand_units,opening_units+existing_receipt_units+recommended_receipt_units)
UNION ALL SELECT 'stock_continuity_errors',COUNT(*) FROM proj p JOIN rec r ON r.product_id=p.product_id AND r.warehouse_id=p.warehouse_id
 WHERE p.opening_units<>COALESCE(p.previous_close,r.on_hand_units)
UNION ALL SELECT 'projection_coverage_errors',COUNT(*) FROM summary_rows s CROSS JOIN run_info ri
 WHERE s.n<>ri.horizon_days OR s.first_day<>DATE_ADD(ri.as_of_date,INTERVAL 1 DAY)
 OR s.last_day<>DATE_ADD(ri.as_of_date,INTERVAL ri.horizon_days DAY)
UNION ALL SELECT 'case_rounding_errors',COUNT(*) FROM rec
 WHERE recommended_units<>recommended_cases*units_per_case OR recommended_cases<>
 CASE WHEN net_required_units<=0 THEN 0
 ELSE CEILING(GREATEST(CEILING(net_required_units/units_per_case),min_order_cases)/order_multiple_cases)*order_multiple_cases END
UNION ALL SELECT 'purchase_cost_errors',COUNT(*) FROM rec
 WHERE estimated_purchase_cost_sgd<>recommended_cases*landed_cost_per_case_sgd
UNION ALL SELECT 'order_schedule_errors',COUNT(*) FROM rec r CROSS JOIN run_info ri
 WHERE r.scheduled_review_date<ri.as_of_date OR DATEDIFF(r.scheduled_review_date,ri.as_of_date)>=r.review_period_days
 OR MOD(DATEDIFF(r.scheduled_review_date,ri.review_anchor_date),r.review_period_days)<>0
 OR r.next_review_date<=r.planning_review_date OR DATEDIFF(r.next_review_date,r.planning_review_date)>r.review_period_days
 OR MOD(DATEDIFF(r.next_review_date,ri.review_anchor_date),r.review_period_days)<>0
 OR r.normal_arrival_date<>DATE_ADD(r.planning_review_date,INTERVAL r.lead_time_days DAY)
 OR r.coverage_end_date<>DATE_SUB(DATE_ADD(r.next_review_date,INTERVAL r.lead_time_days DAY),INTERVAL 1 DAY)
 OR r.planning_review_date<>CASE WHEN r.first_shortage_date_existing<DATE_ADD(r.scheduled_review_date,INTERVAL r.lead_time_days DAY)
                               THEN ri.as_of_date ELSE r.scheduled_review_date END
 OR (r.recommended_cases=0 AND (r.proposed_order_date IS NOT NULL OR r.proposed_arrival_date IS NOT NULL))
 OR (r.recommended_cases>0 AND (NOT(r.proposed_order_date<=>r.planning_review_date) OR NOT(r.proposed_arrival_date<=>r.normal_arrival_date)))
UNION ALL SELECT 'avoidable_base_cycle_shortages',COUNT(*) FROM proj p JOIN rec r ON r.product_id=p.product_id AND r.warehouse_id=p.warehouse_id
 WHERE p.stress_name='base' AND p.plan_path='with_recommendation'
 AND p.projection_date BETWEEN r.normal_arrival_date AND r.coverage_end_date AND p.unmet_units>0
UNION ALL SELECT 'cycle_safety_buffer_errors',COUNT(*) FROM proj p JOIN rec r ON r.product_id=p.product_id AND r.warehouse_id=p.warehouse_id
 WHERE p.stress_name='base' AND p.plan_path='with_recommendation'
 AND p.projection_date=r.coverage_end_date AND p.closing_units<r.safety_target_units
UNION ALL SELECT 'pre_arrival_shortages_changed',COUNT(*) FROM proj p
 JOIN proj b ON b.product_id=p.product_id AND b.warehouse_id=p.warehouse_id AND b.stress_name=p.stress_name
 AND b.projection_date=p.projection_date AND b.plan_path='existing_only'
 JOIN rec r ON r.product_id=p.product_id AND r.warehouse_id=p.warehouse_id
 WHERE p.stress_name='base' AND p.plan_path='with_recommendation'
 AND p.projection_date<r.normal_arrival_date AND p.unmet_units<>b.unmet_units
UNION ALL SELECT 'forecast_demand_mismatches',COUNT(*) FROM proj p CROSS JOIN run_info ri
 JOIN dim_date d ON d.calendar_date=p.projection_date
 LEFT JOIN fact_forecast f ON f.run_id=ri.forecast_run_id AND f.product_id=p.product_id AND f.warehouse_id=p.warehouse_id
 AND f.target_date_id=d.date_id AND f.split_name='production'
 WHERE f.forecast_units IS NULL OR p.demand_units<>ROUND(f.forecast_units*
 CASE p.stress_name WHEN 'demand_up_20' THEN 1.2 WHEN 'demand_down_20' THEN 0.8 ELSE 1 END,4)
UNION ALL SELECT 'existing_receipt_mismatches',COUNT(*) FROM proj p
 LEFT JOIN po_receipts po ON po.product_id=p.product_id AND po.warehouse_id=p.warehouse_id
 AND p.projection_date=DATE_ADD(po.eta,INTERVAL (CASE WHEN p.stress_name='arrival_delay_7' THEN 7 ELSE 0 END) DAY)
 WHERE p.existing_receipt_units<>COALESCE(po.units,0)
UNION ALL SELECT 'recommended_receipt_mismatches',COUNT(*) FROM proj p JOIN rec r ON r.product_id=p.product_id AND r.warehouse_id=p.warehouse_id
 WHERE p.recommended_receipt_units<>CASE WHEN p.plan_path='with_recommendation'
 AND p.projection_date=DATE_ADD(r.proposed_arrival_date,INTERVAL (CASE WHEN p.stress_name='arrival_delay_7' THEN 7 ELSE 0 END) DAY)
 THEN r.recommended_units ELSE 0 END
UNION ALL SELECT 'sensitivity_summary_errors',COUNT(*) FROM replenishment_sensitivity s
 JOIN summary_rows b ON b.product_id=s.product_id AND b.warehouse_id=s.warehouse_id AND b.stress_name=s.stress_name AND b.plan_path='existing_only'
 JOIN summary_rows a ON a.product_id=s.product_id AND a.warehouse_id=s.warehouse_id AND a.stress_name=s.stress_name AND a.plan_path='with_recommendation'
 WHERE s.planning_run_id=@planning_run AND (
 NOT(s.first_shortage_existing<=>b.first_shortage) OR NOT(s.first_shortage_with_plan<=>a.first_shortage)
 OR s.unmet_14d_existing<>b.unmet_14 OR s.unmet_14d_with_plan<>a.unmet_14
 OR s.unmet_cycle_existing<>b.unmet_cycle OR s.unmet_cycle_with_plan<>a.unmet_cycle
 OR s.unmet_84d_existing<>b.unmet_84 OR s.unmet_84d_with_plan<>a.unmet_84
 OR s.closing_84d_existing<>b.closing_84 OR s.closing_84d_with_plan<>a.closing_84
 OR s.committed_excess_existing<>b.committed_excess OR s.committed_excess_with_plan<>a.committed_excess)
UNION ALL SELECT 'action_label_errors',COUNT(*) FROM rec
 WHERE action_code<>CASE WHEN unmet_before_arrival_units>0 THEN 'EXPEDITE_REVIEW'
 WHEN recommended_cases>0 AND planning_review_date<scheduled_review_date THEN 'ORDER_EARLY'
 WHEN recommended_cases>0 THEN 'ORDER_AT_REVIEW' WHEN committed_excess_units>0 THEN 'REVIEW_EXCESS' ELSE 'MONITOR' END
UNION ALL SELECT 'decision_summary_errors',COUNT(*) FROM rec r
 JOIN summary_rows b ON b.product_id=r.product_id AND b.warehouse_id=r.warehouse_id AND b.stress_name='base' AND b.plan_path='existing_only'
 WHERE NOT(r.first_shortage_date_existing<=>b.first_shortage) OR r.unmet_14d_units<>b.unmet_14 OR r.committed_excess_units<>b.committed_excess
 OR NOT(r.latest_normal_order_date<=>DATE_SUB(r.first_shortage_date_existing,INTERVAL r.lead_time_days DAY));

-- RESULT 3: six business decisions. Cases and units are different columns.
SELECT sku_code,model_display_name,on_hand_units,open_order_units,stock_cover_days,
       first_shortage_date_existing,scheduled_review_date,proposed_order_date,proposed_arrival_date,
       recommended_cases,recommended_units,estimated_purchase_cost_sgd,
       unmet_before_arrival_units,committed_excess_units,action_code,recommended_action
FROM vw_replenishment_decisions WHERE planning_run_id=@planning_run ORDER BY sku_code;

-- RESULT 4: 24 sensitivity rows. Base order date/quantity stay fixed in all scenarios.
-- unmet_cycle includes shortages BEFORE arrival; those are not solved by ordinary imports.
SELECT p.sku_code,s.stress_name,s.first_shortage_existing,s.first_shortage_with_plan,
       s.unmet_14d_existing,s.unmet_14d_with_plan,s.unmet_cycle_existing,s.unmet_cycle_with_plan,
       s.committed_excess_existing,s.committed_excess_with_plan
FROM replenishment_sensitivity s JOIN dim_product p ON p.product_id=s.product_id
WHERE s.planning_run_id=@planning_run ORDER BY p.sku_code,s.stress_name;

-- RESULT 5: SKU 001, first 14 dates, both paths: 28 rows.
-- This is a short demonstration of why an order arriving later cannot remove earlier shortages.
SELECT p.sku_code,x.projection_date,x.plan_path,x.opening_units,x.existing_receipt_units,
       x.recommended_receipt_units,x.demand_units,x.fulfilled_units,x.unmet_units,x.closing_units
FROM fact_inventory_projection x JOIN dim_product p ON p.product_id=x.product_id
JOIN planning_run r ON r.planning_run_id=x.planning_run_id
WHERE x.planning_run_id=@planning_run AND x.product_id=1 AND x.stress_name='base'
 AND x.projection_date<=DATE_ADD(r.as_of_date,INTERVAL 14 DAY)
ORDER BY x.projection_date,x.plan_path;
