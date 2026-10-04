-- STEP 4A | Run this entire file in MySQL Workbench, MySQL 8.0.19+.
-- Prerequisites: Steps 1-3 passed. No existing dimension/staging rows are changed.
-- All Step 4 business transactions are synthetic and scoped by scenario_id.
USE beverage_intelligence;

CREATE TABLE IF NOT EXISTS dim_channel (
    channel_id INT NOT NULL PRIMARY KEY,
    channel_code VARCHAR(30) NOT NULL UNIQUE,
    channel_name VARCHAR(80) NOT NULL,
    data_origin VARCHAR(20) NOT NULL DEFAULT 'synthetic'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

INSERT INTO dim_channel (channel_id, channel_code, channel_name, data_origin)
VALUES (1, 'retail', 'Retail customers', 'synthetic'),
       (2, 'on_trade', 'Bars and restaurants', 'synthetic'),
       (3, 'distributor', 'Distributor customers', 'synthetic')
ON DUPLICATE KEY UPDATE channel_id = dim_channel.channel_id;

CREATE TABLE IF NOT EXISTS dim_scenario (
    scenario_id VARCHAR(40) NOT NULL PRIMARY KEY,
    history_start DATE NOT NULL,
    as_of_date DATE NOT NULL,
    random_seed INT NOT NULL,
    data_origin VARCHAR(20) NOT NULL,
    assumptions_json JSON NOT NULL,
    generated_at_utc DATETIME(6) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- Grain: scenario x day x SKU x warehouse x channel.
-- Sales are warehouse outbound units, not consumer point-of-sale transactions.
CREATE TABLE IF NOT EXISTS fact_sales (
    scenario_id VARCHAR(40) NOT NULL,
    date_id INT NOT NULL,
    product_id INT NOT NULL,
    warehouse_id INT NOT NULL,
    channel_id INT NOT NULL,
    units_sold INT NOT NULL,
    unit_price_sgd DECIMAL(10,2) NOT NULL,
    revenue_sgd DECIMAL(14,2) NOT NULL,
    is_promotion TINYINT NOT NULL,
    PRIMARY KEY (scenario_id, date_id, product_id, warehouse_id, channel_id),
    CONSTRAINT fk_sales_scenario FOREIGN KEY (scenario_id) REFERENCES dim_scenario(scenario_id),
    CONSTRAINT fk_sales_date FOREIGN KEY (date_id) REFERENCES dim_date(date_id),
    CONSTRAINT fk_sales_product FOREIGN KEY (product_id) REFERENCES dim_product(product_id),
    CONSTRAINT fk_sales_warehouse FOREIGN KEY (warehouse_id) REFERENCES dim_warehouse(warehouse_id),
    CONSTRAINT fk_sales_channel FOREIGN KEY (channel_id) REFERENCES dim_channel(channel_id),
    CONSTRAINT chk_sales_units CHECK (units_sold >= 0),
    CONSTRAINT chk_sales_price CHECK (unit_price_sgd > 0),
    CONSTRAINT chk_sales_revenue CHECK (revenue_sgd = units_sold * unit_price_sgd),
    CONSTRAINT chk_sales_promotion CHECK (is_promotion IN (0,1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- Grain: scenario x day x SKU x warehouse. Do NOT repeat stock by channel.
-- Events: opening stock -> morning receipts -> outbound sales -> closing stock.
-- No returns, damage, transfers, backorders or partial receipts in this MVP.
CREATE TABLE IF NOT EXISTS fact_inventory (
    scenario_id VARCHAR(40) NOT NULL,
    date_id INT NOT NULL,
    product_id INT NOT NULL,
    warehouse_id INT NOT NULL,
    opening_units INT NOT NULL,
    received_units INT NOT NULL,
    sold_units INT NOT NULL,
    closing_units INT NOT NULL,
    zero_stock_flag TINYINT NOT NULL,
    PRIMARY KEY (scenario_id, date_id, product_id, warehouse_id),
    CONSTRAINT fk_inventory_scenario FOREIGN KEY (scenario_id) REFERENCES dim_scenario(scenario_id),
    CONSTRAINT fk_inventory_date FOREIGN KEY (date_id) REFERENCES dim_date(date_id),
    CONSTRAINT fk_inventory_product FOREIGN KEY (product_id) REFERENCES dim_product(product_id),
    CONSTRAINT fk_inventory_warehouse FOREIGN KEY (warehouse_id) REFERENCES dim_warehouse(warehouse_id),
    CONSTRAINT chk_inventory_nonnegative CHECK
        (opening_units >= 0 AND received_units >= 0 AND sold_units >= 0 AND closing_units >= 0),
    CONSTRAINT chk_inventory_balance CHECK
        (opening_units + received_units - sold_units = closing_units),
    CONSTRAINT chk_inventory_zero CHECK (zero_stock_flag = (closing_units = 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- Grain: one purchase-order line in one scenario; one complete receipt per line.
-- Open orders have future expected dates but NO invented actual receipt date.
CREATE TABLE IF NOT EXISTS fact_purchase_orders (
    scenario_id VARCHAR(40) NOT NULL,
    po_line_id VARCHAR(40) NOT NULL,
    product_id INT NOT NULL,
    warehouse_id INT NOT NULL,
    supplier_id INT NOT NULL,
    order_date_id INT NOT NULL,
    expected_arrival_date_id INT NOT NULL,
    actual_receipt_date_id INT NULL,
    quantity_cases INT NOT NULL,
    units_per_case_on_order INT NOT NULL,
    ordered_units INT NOT NULL,
    received_units INT NOT NULL,
    landed_cost_per_case_sgd DECIMAL(10,2) NOT NULL,
    order_status VARCHAR(12) NOT NULL,
    PRIMARY KEY (scenario_id, po_line_id),
    CONSTRAINT fk_po_scenario FOREIGN KEY (scenario_id) REFERENCES dim_scenario(scenario_id),
    CONSTRAINT fk_po_product FOREIGN KEY (product_id) REFERENCES dim_product(product_id),
    CONSTRAINT fk_po_warehouse FOREIGN KEY (warehouse_id) REFERENCES dim_warehouse(warehouse_id),
    CONSTRAINT fk_po_supplier FOREIGN KEY (supplier_id) REFERENCES dim_supplier(supplier_id),
    CONSTRAINT fk_po_order_date FOREIGN KEY (order_date_id) REFERENCES dim_date(date_id),
    CONSTRAINT fk_po_expected_date FOREIGN KEY (expected_arrival_date_id) REFERENCES dim_date(date_id),
    CONSTRAINT fk_po_actual_date FOREIGN KEY (actual_receipt_date_id) REFERENCES dim_date(date_id),
    CONSTRAINT chk_po_qty CHECK
        (quantity_cases > 0 AND units_per_case_on_order > 0
         AND ordered_units = quantity_cases * units_per_case_on_order),
    CONSTRAINT chk_po_dates CHECK
        (expected_arrival_date_id >= order_date_id
         AND (actual_receipt_date_id IS NULL OR actual_receipt_date_id >= order_date_id)),
    CONSTRAINT chk_po_cost CHECK (landed_cost_per_case_sgd > 0),
    CONSTRAINT chk_po_status CHECK
        ((order_status = 'open' AND actual_receipt_date_id IS NULL AND received_units = 0)
         OR (order_status = 'received' AND actual_receipt_date_id IS NOT NULL
             AND received_units = ordered_units))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

COMMIT;
SELECT channel_id, channel_code, channel_name FROM dim_channel ORDER BY channel_id;
-- Now run scripts/generate_load_transactions.py in PowerShell.
