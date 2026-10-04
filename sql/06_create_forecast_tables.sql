-- STEP 5A: execute the entire file in MySQL Workbench (MySQL 8.0.19+).
USE beverage_intelligence;

CREATE TABLE IF NOT EXISTS forecast_run (
    run_id VARCHAR(50) NOT NULL PRIMARY KEY,
    scenario_id VARCHAR(40) NOT NULL,
    as_of_date DATE NOT NULL,
    horizon_days INT NOT NULL,
    backtest_days INT NOT NULL,
    code_version VARCHAR(30) NOT NULL,
    input_sha256 CHAR(64) NOT NULL,
    data_origin VARCHAR(20) NOT NULL,
    created_at_utc DATETIME(6) NOT NULL,
    assumptions_json JSON NOT NULL,
    CONSTRAINT fk_fr_scenario FOREIGN KEY (scenario_id) REFERENCES dim_scenario(scenario_id),
    CONSTRAINT chk_fr_horizons CHECK (horizon_days >= backtest_days AND backtest_days > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- Grain: run x SKU x warehouse x model x forecast origin x target date.
-- Only the selected model is written for production; all candidates for backtests.
-- Actuals stay in fact_sales; they are not copied into the production forecast.
CREATE TABLE IF NOT EXISTS fact_forecast (
    run_id VARCHAR(50) NOT NULL,
    product_id INT NOT NULL,
    warehouse_id INT NOT NULL,
    model_name VARCHAR(30) NOT NULL,
    origin_date DATE NOT NULL,
    target_date_id INT NOT NULL,
    split_name VARCHAR(12) NOT NULL,
    forecast_units DECIMAL(14,4) NOT NULL,
    PRIMARY KEY (run_id,product_id,warehouse_id,model_name,origin_date,target_date_id),
    CONSTRAINT fk_ff_run FOREIGN KEY (run_id) REFERENCES forecast_run(run_id),
    CONSTRAINT fk_ff_product FOREIGN KEY (product_id) REFERENCES dim_product(product_id),
    CONSTRAINT fk_ff_warehouse FOREIGN KEY (warehouse_id) REFERENCES dim_warehouse(warehouse_id),
    CONSTRAINT fk_ff_date FOREIGN KEY (target_date_id) REFERENCES dim_date(date_id),
    CONSTRAINT chk_ff_qty CHECK (forecast_units >= 0),
    CONSTRAINT chk_ff_split CHECK (split_name IN ('validation','holdout','production')),
    CONSTRAINT chk_ff_model CHECK (model_name IN ('mean_28','weekday_mean_56','seasonal_naive_7'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS forecast_evaluation (
    run_id VARCHAR(50) NOT NULL,
    product_id INT NOT NULL,
    warehouse_id INT NOT NULL,
    model_name VARCHAR(30) NOT NULL,
    origin_date DATE NOT NULL,
    split_name VARCHAR(12) NOT NULL,
    evaluation_scope VARCHAR(20) NOT NULL,
    scored_days INT NOT NULL,
    excluded_days INT NOT NULL,
    actual_units DECIMAL(16,4) NOT NULL,
    absolute_error_units DECIMAL(16,4) NOT NULL,
    signed_error_units DECIMAL(16,4) NOT NULL,
    mae_units DECIMAL(16,4) NULL,
    wape_pct DECIMAL(16,4) NULL,
    bias_pct DECIMAL(16,4) NULL,
    PRIMARY KEY (run_id,product_id,warehouse_id,model_name,origin_date,evaluation_scope),
    CONSTRAINT fk_fe_run FOREIGN KEY (run_id) REFERENCES forecast_run(run_id),
    CONSTRAINT fk_fe_product FOREIGN KEY (product_id) REFERENCES dim_product(product_id),
    CONSTRAINT fk_fe_warehouse FOREIGN KEY (warehouse_id) REFERENCES dim_warehouse(warehouse_id),
    CONSTRAINT chk_fe_days CHECK (scored_days >= 0 AND excluded_days >= 0),
    CONSTRAINT chk_fe_errors CHECK (actual_units >= 0 AND absolute_error_units >= 0),
    CONSTRAINT chk_fe_scope CHECK (evaluation_scope IN ('all_days','available_stock')),
    CONSTRAINT chk_fe_split CHECK (split_name IN ('validation','holdout'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS forecast_model_selection (
    run_id VARCHAR(50) NOT NULL,
    product_id INT NOT NULL,
    warehouse_id INT NOT NULL,
    model_name VARCHAR(30) NOT NULL,
    validation_wape_pct DECIMAL(16,4) NOT NULL,
    holdout_wape_pct DECIMAL(16,4) NOT NULL,
    holdout_bias_pct DECIMAL(16,4) NOT NULL,
    holdout_scored_days INT NOT NULL,
    holdout_excluded_days INT NOT NULL,
    training_imputed_days INT NOT NULL,
    PRIMARY KEY (run_id,product_id,warehouse_id),
    CONSTRAINT fk_fs_run FOREIGN KEY (run_id) REFERENCES forecast_run(run_id),
    CONSTRAINT fk_fs_product FOREIGN KEY (product_id) REFERENCES dim_product(product_id),
    CONSTRAINT fk_fs_warehouse FOREIGN KEY (warehouse_id) REFERENCES dim_warehouse(warehouse_id),
    CONSTRAINT chk_fs_wape CHECK (validation_wape_pct >= 0 AND holdout_wape_pct >= 0),
    CONSTRAINT chk_fs_days CHECK (holdout_scored_days >= 0 AND holdout_excluded_days >= 0
                                AND training_imputed_days >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- The planner will consume this view filtered to ONE explicit run_id.
-- Multiple runs must never be summed together. Quantities are individual units.
CREATE OR REPLACE VIEW vw_forecast_daily_production AS
SELECT f.run_id, r.scenario_id, r.as_of_date, f.product_id, p.sku_code,
       f.warehouse_id, d.calendar_date AS forecast_date, f.model_name,
       f.forecast_units, r.data_origin
FROM fact_forecast f
JOIN forecast_run r ON r.run_id=f.run_id
JOIN dim_product p ON p.product_id=f.product_id
JOIN dim_date d ON d.date_id=f.target_date_id
JOIN forecast_model_selection s ON s.run_id=f.run_id AND s.product_id=f.product_id
    AND s.warehouse_id=f.warehouse_id AND s.model_name=f.model_name
WHERE f.split_name='production';

SELECT 'FORECAST TABLES READY' AS setup_status;
