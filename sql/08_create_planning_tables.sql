-- STEP 6A | Run the whole file in MySQL Workbench. Requires Steps 1-5.
USE beverage_intelligence;

CREATE TABLE IF NOT EXISTS planning_run (
    planning_run_id VARCHAR(50) NOT NULL PRIMARY KEY,
    forecast_run_id VARCHAR(50) NOT NULL,
    as_of_date DATE NOT NULL,
    horizon_days INT NOT NULL,
    review_anchor_date DATE NOT NULL,
    code_version VARCHAR(30) NOT NULL,
    input_sha256 CHAR(64) NOT NULL,
    data_origin VARCHAR(20) NOT NULL,
    created_at_utc DATETIME(6) NOT NULL,
    assumptions_json JSON NOT NULL,
    CONSTRAINT fk_pr_forecast FOREIGN KEY (forecast_run_id) REFERENCES forecast_run(run_id),
    CONSTRAINT chk_pr_horizon CHECK (horizon_days > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- Grain: one proposed replenishment decision per run x SKU x warehouse.
-- Policy fields are snapshots. This table does NOT constitute purchase orders.
CREATE TABLE IF NOT EXISTS fact_replenishment_recommendation (
    planning_run_id VARCHAR(50) NOT NULL,
    product_id INT NOT NULL,
    warehouse_id INT NOT NULL,
    supplier_id INT NOT NULL,
    model_name VARCHAR(30) NOT NULL,
    on_hand_units INT NOT NULL,
    open_order_units INT NOT NULL,
    units_per_case INT NOT NULL,
    lead_time_days INT NOT NULL,
    review_period_days INT NOT NULL,
    min_order_cases INT NOT NULL,
    order_multiple_cases INT NOT NULL,
    safety_stock_days INT NOT NULL,
    max_cover_days INT NOT NULL,
    landed_cost_per_case_sgd DECIMAL(10,2) NOT NULL,
    scheduled_review_date DATE NOT NULL,
    planning_review_date DATE NOT NULL,
    next_review_date DATE NOT NULL,
    normal_arrival_date DATE NOT NULL,
    coverage_end_date DATE NOT NULL,
    safety_target_units DECIMAL(16,4) NOT NULL,
    net_required_units DECIMAL(16,4) NOT NULL,
    recommended_cases INT NOT NULL,
    recommended_units INT NOT NULL,
    estimated_purchase_cost_sgd DECIMAL(16,2) NOT NULL,
    proposed_order_date DATE NULL,
    proposed_arrival_date DATE NULL,
    first_shortage_date_existing DATE NULL,
    latest_normal_order_date DATE NULL,
    unmet_before_arrival_units DECIMAL(16,4) NOT NULL,
    unmet_14d_units DECIMAL(16,4) NOT NULL,
    stock_cover_days DECIMAL(10,4) NOT NULL,
    stock_cover_capped TINYINT NOT NULL,
    committed_excess_units DECIMAL(16,4) NOT NULL,
    action_code VARCHAR(24) NOT NULL,
    PRIMARY KEY (planning_run_id,product_id,warehouse_id),
    CONSTRAINT fk_rr_run FOREIGN KEY (planning_run_id) REFERENCES planning_run(planning_run_id),
    CONSTRAINT fk_rr_product FOREIGN KEY (product_id) REFERENCES dim_product(product_id),
    CONSTRAINT fk_rr_warehouse FOREIGN KEY (warehouse_id) REFERENCES dim_warehouse(warehouse_id),
    CONSTRAINT fk_rr_supplier FOREIGN KEY (supplier_id) REFERENCES dim_supplier(supplier_id),
    CONSTRAINT chk_rr_policy CHECK (units_per_case>0 AND lead_time_days>0 AND review_period_days>0
        AND min_order_cases>0 AND order_multiple_cases>0 AND safety_stock_days>=0 AND max_cover_days>0),
    CONSTRAINT chk_rr_quantities CHECK (on_hand_units>=0 AND open_order_units>=0
        AND safety_target_units>=0 AND net_required_units>=0 AND recommended_cases>=0
        AND recommended_units=recommended_cases*units_per_case),
    CONSTRAINT chk_rr_order CHECK (
        (recommended_cases=0 AND proposed_order_date IS NULL AND proposed_arrival_date IS NULL)
        OR (recommended_cases>=min_order_cases AND MOD(recommended_cases,order_multiple_cases)=0
            AND proposed_order_date IS NOT NULL AND proposed_arrival_date IS NOT NULL)),
    CONSTRAINT chk_rr_cost CHECK (landed_cost_per_case_sgd>0
        AND estimated_purchase_cost_sgd=recommended_cases*landed_cost_per_case_sgd),
    CONSTRAINT chk_rr_action CHECK (action_code IN
        ('EXPEDITE_REVIEW','ORDER_EARLY','ORDER_AT_REVIEW','REVIEW_EXCESS','MONITOR')),
    CONSTRAINT chk_rr_cover CHECK (stock_cover_days>=0 AND stock_cover_capped IN (0,1)
        AND unmet_before_arrival_units>=0 AND unmet_14d_units>=0 AND committed_excess_units>=0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- Grain: run x SKU x warehouse x stress scenario x plan path x future date.
-- Six SKUs x four stress scenarios x two paths x 84 days = 4,032 rows.
CREATE TABLE IF NOT EXISTS fact_inventory_projection (
    planning_run_id VARCHAR(50) NOT NULL,
    product_id INT NOT NULL,
    warehouse_id INT NOT NULL,
    stress_name VARCHAR(20) NOT NULL,
    plan_path VARCHAR(24) NOT NULL,
    projection_date DATE NOT NULL,
    opening_units DECIMAL(16,4) NOT NULL,
    existing_receipt_units DECIMAL(16,4) NOT NULL,
    recommended_receipt_units DECIMAL(16,4) NOT NULL,
    demand_units DECIMAL(16,4) NOT NULL,
    fulfilled_units DECIMAL(16,4) NOT NULL,
    unmet_units DECIMAL(16,4) NOT NULL,
    closing_units DECIMAL(16,4) NOT NULL,
    PRIMARY KEY (planning_run_id,product_id,warehouse_id,stress_name,plan_path,projection_date),
    CONSTRAINT fk_ip_run FOREIGN KEY (planning_run_id) REFERENCES planning_run(planning_run_id),
    CONSTRAINT fk_ip_product FOREIGN KEY (product_id) REFERENCES dim_product(product_id),
    CONSTRAINT fk_ip_warehouse FOREIGN KEY (warehouse_id) REFERENCES dim_warehouse(warehouse_id),
    CONSTRAINT fk_ip_date FOREIGN KEY (projection_date) REFERENCES dim_date(calendar_date),
    CONSTRAINT chk_ip_nonnegative CHECK (opening_units>=0 AND existing_receipt_units>=0
        AND recommended_receipt_units>=0 AND demand_units>=0 AND fulfilled_units>=0
        AND unmet_units>=0 AND closing_units>=0),
    CONSTRAINT chk_ip_balance CHECK (opening_units+existing_receipt_units+recommended_receipt_units-fulfilled_units=closing_units),
    CONSTRAINT chk_ip_demand CHECK (fulfilled_units+unmet_units=demand_units),
    CONSTRAINT chk_ip_path CHECK (plan_path IN ('existing_only','with_recommendation')),
    CONSTRAINT chk_ip_stress CHECK (stress_name IN ('base','demand_up_20','demand_down_20','arrival_delay_7'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- Grain: run x SKU x warehouse x stress scenario. Base decision is frozen.
CREATE TABLE IF NOT EXISTS replenishment_sensitivity (
    planning_run_id VARCHAR(50) NOT NULL,
    product_id INT NOT NULL,
    warehouse_id INT NOT NULL,
    stress_name VARCHAR(20) NOT NULL,
    demand_factor DECIMAL(5,2) NOT NULL,
    arrival_delay_days INT NOT NULL,
    first_shortage_existing DATE NULL,
    first_shortage_with_plan DATE NULL,
    unmet_14d_existing DECIMAL(16,4) NOT NULL,
    unmet_14d_with_plan DECIMAL(16,4) NOT NULL,
    unmet_cycle_existing DECIMAL(16,4) NOT NULL,
    unmet_cycle_with_plan DECIMAL(16,4) NOT NULL,
    unmet_84d_existing DECIMAL(16,4) NOT NULL,
    unmet_84d_with_plan DECIMAL(16,4) NOT NULL,
    closing_84d_existing DECIMAL(16,4) NOT NULL,
    closing_84d_with_plan DECIMAL(16,4) NOT NULL,
    committed_excess_existing DECIMAL(16,4) NOT NULL,
    committed_excess_with_plan DECIMAL(16,4) NOT NULL,
    PRIMARY KEY (planning_run_id,product_id,warehouse_id,stress_name),
    CONSTRAINT fk_rs_run FOREIGN KEY (planning_run_id) REFERENCES planning_run(planning_run_id),
    CONSTRAINT fk_rs_product FOREIGN KEY (product_id) REFERENCES dim_product(product_id),
    CONSTRAINT fk_rs_warehouse FOREIGN KEY (warehouse_id) REFERENCES dim_warehouse(warehouse_id),
    CONSTRAINT chk_rs_assumptions CHECK (demand_factor>0 AND arrival_delay_days>=0),
    CONSTRAINT chk_rs_unmet CHECK (unmet_14d_existing>=0 AND unmet_14d_with_plan>=0
        AND unmet_cycle_existing>=0 AND unmet_cycle_with_plan>=0 AND unmet_84d_existing>=0
        AND unmet_84d_with_plan>=0 AND closing_84d_existing>=0 AND closing_84d_with_plan>=0
        AND committed_excess_existing>=0 AND committed_excess_with_plan>=0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- Friendly labels leave technical model IDs unchanged.
-- Filter ONE planning_run_id; never sum across runs, stress scenarios or paths.
CREATE OR REPLACE VIEW vw_replenishment_decisions AS
SELECT r.planning_run_id,pr.as_of_date,p.sku_code,s.supplier_code,
       r.model_name,
       CASE r.model_name WHEN 'mean_28' THEN '28-Day Average'
         WHEN 'weekday_mean_56' THEN '8-Week Weekday Average'
         WHEN 'seasonal_naive_7' THEN 'Same Day Last Week' ELSE r.model_name END AS model_display_name,
       r.on_hand_units,r.open_order_units,r.stock_cover_days,r.stock_cover_capped,
       r.first_shortage_date_existing,r.latest_normal_order_date,
       r.scheduled_review_date,r.proposed_order_date,r.proposed_arrival_date,
       r.recommended_cases,r.recommended_units,r.estimated_purchase_cost_sgd,
       r.unmet_before_arrival_units,r.unmet_14d_units,r.committed_excess_units,
       r.action_code,
       CASE r.action_code WHEN 'EXPEDITE_REVIEW' THEN 'Review urgent supply options'
         WHEN 'ORDER_EARLY' THEN 'Bring the order review forward'
         WHEN 'ORDER_AT_REVIEW' THEN 'Order at scheduled review'
         WHEN 'REVIEW_EXCESS' THEN 'Review excess committed supply'
         ELSE 'Monitor at the next review' END AS recommended_action,
       r.coverage_end_date,pr.data_origin
FROM fact_replenishment_recommendation r
JOIN planning_run pr ON pr.planning_run_id=r.planning_run_id
JOIN dim_product p ON p.product_id=r.product_id
JOIN dim_supplier s ON s.supplier_id=r.supplier_id;

SELECT 'PLANNING TABLES READY' AS setup_status;
