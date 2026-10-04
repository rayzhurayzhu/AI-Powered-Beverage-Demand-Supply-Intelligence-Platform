-- Beverage Demand & Supply Decision Platform | Step 3
-- MySQL 8.0.19+; the user's observed server is MySQL 8.0.46.
-- Run the complete file in MySQL Workbench. Stop and inspect any SQL errors.
-- ALL products, brands, suppliers, warehouses, costs and parameters below
-- are SYNTHETIC portfolio assumptions, not APB data or market benchmarks.
-- No changes are made to dim_date or stg_public_holidays.
-- Reruns seed missing records; existing rows are preserved, not reset.

USE beverage_intelligence;

-- Grain: one SKU. One base unit means one individual can or bottle.
-- Different pack sizes must have different SKUs; do not change historical
-- units_per_case after transaction data has been loaded.
CREATE TABLE IF NOT EXISTS dim_product (
    product_id INT NOT NULL,
    sku_code VARCHAR(30) NOT NULL,
    product_name VARCHAR(120) NOT NULL,
    brand_name VARCHAR(60) NOT NULL,
    category VARCHAR(40) NOT NULL,
    container_type VARCHAR(10) NOT NULL,
    unit_volume_ml INT NOT NULL,
    units_per_case INT NOT NULL,
    data_origin VARCHAR(20) NOT NULL DEFAULT 'synthetic',
    PRIMARY KEY (product_id),
    UNIQUE KEY uq_product_sku (sku_code),
    CONSTRAINT chk_product_container CHECK (container_type IN ('can', 'bottle')),
    CONSTRAINT chk_product_volume CHECK (unit_volume_ml > 0),
    CONSTRAINT chk_product_case_size CHECK (units_per_case > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- Grain: one supplier. Country is the demo dispatch/source country.
CREATE TABLE IF NOT EXISTS dim_supplier (
    supplier_id INT NOT NULL,
    supplier_code VARCHAR(30) NOT NULL,
    supplier_name VARCHAR(120) NOT NULL,
    source_country_code CHAR(2) NOT NULL,
    data_origin VARCHAR(20) NOT NULL DEFAULT 'synthetic',
    PRIMARY KEY (supplier_id),
    UNIQUE KEY uq_supplier_code (supplier_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- Grain: one receiving warehouse. This MVP pools channel demand here.
CREATE TABLE IF NOT EXISTS dim_warehouse (
    warehouse_id INT NOT NULL,
    warehouse_code VARCHAR(30) NOT NULL,
    warehouse_name VARCHAR(120) NOT NULL,
    country_code CHAR(2) NOT NULL,
    data_origin VARCHAR(20) NOT NULL DEFAULT 'synthetic',
    PRIMARY KEY (warehouse_id),
    UNIQUE KEY uq_warehouse_code (warehouse_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- Grain: one SKU x destination warehouse, with ONE preferred supplier.
-- This is current planning configuration, not a sales fact or purchase order.
-- Lead time = elapsed CALENDAR days from order placement until stock is usable
-- at the destination. The demo assumes a fixed lead time and no closure delays.
-- Review interval is a cadence, not an order-date schedule/anchor.
-- Safety-stock days are an initial heuristic, not a proven service-level guarantee.
-- Max cover is a configurable overstock alert threshold, not a hard stock cap.
-- Cost is a synthetic fixed landed cost per case, denominated in SGD.
CREATE TABLE IF NOT EXISTS sku_supply_policy (
    product_id INT NOT NULL,
    warehouse_id INT NOT NULL,
    supplier_id INT NOT NULL,
    lead_time_days INT NOT NULL,
    review_period_days INT NOT NULL,
    min_order_cases INT NOT NULL,
    order_multiple_cases INT NOT NULL,
    safety_stock_days INT NOT NULL,
    max_cover_days INT NOT NULL,
    landed_cost_per_case_sgd DECIMAL(10,2) NOT NULL,
    data_origin VARCHAR(20) NOT NULL DEFAULT 'synthetic',
    PRIMARY KEY (product_id, warehouse_id),
    CONSTRAINT fk_policy_product FOREIGN KEY (product_id)
        REFERENCES dim_product (product_id),
    CONSTRAINT fk_policy_warehouse FOREIGN KEY (warehouse_id)
        REFERENCES dim_warehouse (warehouse_id),
    CONSTRAINT fk_policy_supplier FOREIGN KEY (supplier_id)
        REFERENCES dim_supplier (supplier_id),
    CONSTRAINT chk_policy_lead_time CHECK (lead_time_days > 0),
    CONSTRAINT chk_policy_review CHECK (review_period_days > 0),
    CONSTRAINT chk_policy_moq CHECK (min_order_cases > 0),
    CONSTRAINT chk_policy_multiple CHECK (order_multiple_cases > 0),
    CONSTRAINT chk_policy_safety CHECK (safety_stock_days >= 0),
    CONSTRAINT chk_policy_cover CHECK (max_cover_days > 0),
    CONSTRAINT chk_policy_cost CHECK (landed_cost_per_case_sgd > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- Synthetic seed data. Duplicate-key no-ops preserve future manual edits.
INSERT INTO dim_product (
    product_id, sku_code, product_name, brand_name, category,
    container_type, unit_volume_ml, units_per_case, data_origin
) VALUES
    (1, 'DEMO-BEV-001', 'Demo Harbour Lager 330ml Can', 'Demo Harbour',
     'beer', 'can', 330, 24, 'synthetic'),
    (2, 'DEMO-BEV-002', 'Demo Harbour Lager 500ml Can', 'Demo Harbour',
     'beer', 'can', 500, 24, 'synthetic'),
    (3, 'DEMO-BEV-003', 'Demo Orchard Lager 330ml Bottle', 'Demo Orchard',
     'beer', 'bottle', 330, 24, 'synthetic'),
    (4, 'DEMO-BEV-004', 'Demo Harbour Alcohol-Free 330ml Can', 'Demo Harbour',
     'alcohol_free_beer', 'can', 330, 24, 'synthetic'),
    (5, 'DEMO-BEV-005', 'Demo Orchard Sparkling Water 330ml Can', 'Demo Orchard',
     'sparkling_water', 'can', 330, 24, 'synthetic'),
    (6, 'DEMO-BEV-006', 'Demo Orchard Iced Tea 500ml Bottle', 'Demo Orchard',
     'iced_tea', 'bottle', 500, 12, 'synthetic')
ON DUPLICATE KEY UPDATE product_id = dim_product.product_id;

INSERT INTO dim_supplier (
    supplier_id, supplier_code, supplier_name, source_country_code, data_origin
) VALUES
    (1, 'DEMO-SUP-MY', 'Demo Malaysia Beverage Supplier', 'MY', 'synthetic'),
    (2, 'DEMO-SUP-VN', 'Demo Vietnam Beverage Supplier', 'VN', 'synthetic')
ON DUPLICATE KEY UPDATE supplier_id = dim_supplier.supplier_id;

INSERT INTO dim_warehouse (
    warehouse_id, warehouse_code, warehouse_name, country_code, data_origin
) VALUES
    (1, 'DEMO-SG-DC01', 'Demo Singapore Distribution Centre', 'SG', 'synthetic')
ON DUPLICATE KEY UPDATE warehouse_id = dim_warehouse.warehouse_id;

INSERT INTO sku_supply_policy (
    product_id, warehouse_id, supplier_id, lead_time_days, review_period_days,
    min_order_cases, order_multiple_cases, safety_stock_days, max_cover_days,
    landed_cost_per_case_sgd, data_origin
) VALUES
    (1, 1, 1, 21, 7, 20, 10, 7, 60, 36.00, 'synthetic'),
    (2, 1, 1, 21, 7, 20, 10, 7, 60, 48.00, 'synthetic'),
    (3, 1, 2, 28, 7, 30, 10, 7, 60, 40.00, 'synthetic'),
    (4, 1, 1, 21, 7, 10,  5, 7, 60, 30.00, 'synthetic'),
    (5, 1, 2, 28, 7, 20, 10, 7, 60, 12.00, 'synthetic'),
    (6, 1, 2, 28, 7, 20, 10, 7, 60, 15.00, 'synthetic')
ON DUPLICATE KEY UPDATE product_id = sku_supply_policy.product_id;

COMMIT;

-- CHECK 1: expected counts in the initial demo = 6, 2, 1, 6.
SELECT 'dim_product' AS table_name, COUNT(*) AS row_count FROM dim_product
UNION ALL
SELECT 'dim_supplier', COUNT(*) FROM dim_supplier
UNION ALL
SELECT 'dim_warehouse', COUNT(*) FROM dim_warehouse
UNION ALL
SELECT 'sku_supply_policy', COUNT(*) FROM sku_supply_policy;

-- CHECK 2: one understandable commercial/supply row per SKU (6 rows).
SELECT
    p.sku_code,
    p.units_per_case,
    s.supplier_code,
    s.source_country_code,
    w.warehouse_code,
    sp.lead_time_days,
    sp.review_period_days,
    sp.min_order_cases,
    sp.order_multiple_cases,
    sp.min_order_cases * p.units_per_case AS min_order_units,
    sp.order_multiple_cases * p.units_per_case AS order_multiple_units,
    sp.safety_stock_days,
    sp.max_cover_days,
    sp.landed_cost_per_case_sgd,
    sp.data_origin
FROM sku_supply_policy AS sp
JOIN dim_product AS p ON p.product_id = sp.product_id
JOIN dim_supplier AS s ON s.supplier_id = sp.supplier_id
JOIN dim_warehouse AS w ON w.warehouse_id = sp.warehouse_id
ORDER BY p.sku_code, w.warehouse_code;

-- CHECK 3: expected invalid_reference_rows = 0.
SELECT COUNT(*) AS invalid_reference_rows
FROM sku_supply_policy AS sp
LEFT JOIN dim_product AS p ON p.product_id = sp.product_id
LEFT JOIN dim_supplier AS s ON s.supplier_id = sp.supplier_id
LEFT JOIN dim_warehouse AS w ON w.warehouse_id = sp.warehouse_id
WHERE p.product_id IS NULL OR s.supplier_id IS NULL OR w.warehouse_id IS NULL;

-- CHECK 4: expected products_without_policy = 0 for this one-warehouse MVP.
SELECT COUNT(*) AS products_without_policy
FROM dim_product AS p
LEFT JOIN sku_supply_policy AS sp
    ON sp.product_id = p.product_id AND sp.warehouse_id = 1
WHERE sp.product_id IS NULL;

-- CHECK 5: expected policy_review_flags = 0 for these demo assumptions.
-- This is a policy-consistency screen, not a measure of forecast quality.
SELECT COUNT(*) AS policy_review_flags
FROM sku_supply_policy
WHERE MOD(min_order_cases, order_multiple_cases) <> 0
   OR max_cover_days < lead_time_days + review_period_days + safety_stock_days;

-- CHECK 6: expected non_synthetic_rows = 0. These are NOT company facts.
SELECT
    (SELECT COUNT(*) FROM dim_product WHERE data_origin <> 'synthetic')
  + (SELECT COUNT(*) FROM dim_supplier WHERE data_origin <> 'synthetic')
  + (SELECT COUNT(*) FROM dim_warehouse WHERE data_origin <> 'synthetic')
  + (SELECT COUNT(*) FROM sku_supply_policy WHERE data_origin <> 'synthetic')
    AS non_synthetic_rows;

-- MODEL CONTRACT FOR NEXT STEPS
-- Sales/forecast/inventory quantities: integer individual units of each SKU.
-- Purchase orders: whole cases, with quantity converted to individual units.
-- Example: DEMO-BEV-001 has 24 units/case; 20 cases = 480 individual units.
-- If replenishment is needed, round the greater of the net requirement and
-- MOQ up to a valid order multiple. A nonpositive net requirement means no order.
-- Do not apply MOQ merely because a SKU appears in a planning report.
-- Future demand forecasts must span lead time + review interval at minimum.
-- Calculate risks on daily projected stock including dated inbound receipts.
-- Historical sales will be warehouse outbound sales by day x SKU x channel;
-- inventory is a day x SKU x warehouse snapshot, not repeated by channel.
-- Raw sales can be constrained by stockouts; sales are not always true demand.
-- Lead times/costs are fixed assumptions in this MVP, not historical estimates.
-- The max-cover threshold supports overstock alerts, not expiry detection.
-- Expiry analysis requires batch-level expiry/remaining shelf-life data later.
-- Actual PO dates/status/receipts belong in transaction tables, not this policy.
-- Multiple suppliers, shared freight/MOQ, capacity limits, business calendars,
-- and effective-dated policy history are later extensions, not implemented here.
-- Validation: seed relationships and unit conversions checked independently.
-- Real MySQL execution must be verified using CHECK 1-6 on the local server.
-- MySQL reference: https://dev.mysql.com/doc/refman/8.0/en/create-table-foreign-keys.html
-- MySQL reference: https://dev.mysql.com/doc/refman/8.0/en/create-table-check-constraints.html
