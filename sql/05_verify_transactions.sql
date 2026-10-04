-- STEP 4C | Run the whole file after TRANSACTION PIPELINE OK.
USE beverage_intelligence;

-- RESULT 1: scenario metadata. Fixed end-of-day as-of date, NOT today's date.
SELECT scenario_id, history_start, as_of_date, random_seed, data_origin
FROM dim_scenario WHERE scenario_id = 'beverage_demo_v1';

-- RESULT 2: expected sales 18072, inventory 6024; PO count must match Python.
SELECT 'fact_sales' AS table_name, COUNT(*) AS row_count
FROM fact_sales WHERE scenario_id = 'beverage_demo_v1'
UNION ALL SELECT 'fact_inventory', COUNT(*)
FROM fact_inventory WHERE scenario_id = 'beverage_demo_v1'
UNION ALL SELECT 'fact_purchase_orders', COUNT(*)
FROM fact_purchase_orders WHERE scenario_id = 'beverage_demo_v1';

-- RESULT 3: all failed_rows should be 0; row counts above must ALSO be correct.
WITH
s AS (
    SELECT date_id, product_id, warehouse_id, SUM(units_sold) AS units_sold,
           COUNT(*) AS channel_rows
    FROM fact_sales WHERE scenario_id = 'beverage_demo_v1'
    GROUP BY date_id, product_id, warehouse_id
),
i AS (SELECT * FROM fact_inventory WHERE scenario_id = 'beverage_demo_v1'),
po AS (SELECT * FROM fact_purchase_orders WHERE scenario_id = 'beverage_demo_v1'),
receipts AS (
    SELECT actual_receipt_date_id AS date_id, product_id, warehouse_id,
           SUM(received_units) AS units_received
    FROM po WHERE order_status = 'received'
    GROUP BY actual_receipt_date_id, product_id, warehouse_id
),
continuity AS (
    SELECT i.*, LAG(closing_units) OVER (
        PARTITION BY product_id, warehouse_id ORDER BY date_id) AS prior_closing
    FROM i
)
SELECT 'inventory_balance_errors' AS check_name, COUNT(*) AS failed_rows
FROM i WHERE opening_units + received_units - sold_units <> closing_units
UNION ALL
SELECT 'negative_inventory_rows', COUNT(*) FROM i
WHERE opening_units < 0 OR received_units < 0 OR sold_units < 0 OR closing_units < 0
UNION ALL
SELECT 'inventory_continuity_errors', COUNT(*) FROM continuity
WHERE prior_closing IS NOT NULL AND opening_units <> prior_closing
UNION ALL
SELECT 'sales_inventory_mismatches', COUNT(*)
FROM i LEFT JOIN s USING (date_id, product_id, warehouse_id)
WHERE i.sold_units <> COALESCE(s.units_sold, 0) OR COALESCE(s.channel_rows, 0) <> 3
UNION ALL
SELECT 'sales_without_inventory', COUNT(*)
FROM s LEFT JOIN i USING (date_id, product_id, warehouse_id) WHERE i.date_id IS NULL
UNION ALL
SELECT 'receipt_inventory_mismatches', COUNT(*)
FROM i LEFT JOIN receipts AS r USING (date_id, product_id, warehouse_id)
WHERE i.received_units <> COALESCE(r.units_received, 0)
UNION ALL
SELECT 'receipts_without_inventory', COUNT(*)
FROM receipts AS r LEFT JOIN i USING (date_id, product_id, warehouse_id) WHERE i.date_id IS NULL
UNION ALL
SELECT 'sales_revenue_errors', COUNT(*) FROM fact_sales
WHERE scenario_id = 'beverage_demo_v1' AND revenue_sgd <> ROUND(units_sold * unit_price_sgd, 2)
UNION ALL
SELECT 'po_rule_errors', COUNT(*)
FROM po JOIN sku_supply_policy AS p USING (product_id, warehouse_id)
JOIN dim_product AS pr USING (product_id)
JOIN dim_date AS od ON od.date_id = po.order_date_id
JOIN dim_date AS ed ON ed.date_id = po.expected_arrival_date_id
WHERE po.quantity_cases < p.min_order_cases
   OR MOD(po.quantity_cases, p.order_multiple_cases) <> 0
   OR po.ordered_units <> po.quantity_cases * pr.units_per_case
   OR po.units_per_case_on_order <> pr.units_per_case
   OR po.supplier_id <> p.supplier_id
   OR DATEDIFF(ed.calendar_date, od.calendar_date) <> p.lead_time_days
UNION ALL
SELECT 'future_actual_rows',
    (SELECT COUNT(*) FROM fact_sales WHERE scenario_id = 'beverage_demo_v1' AND date_id > 20260930)
  + (SELECT COUNT(*) FROM i WHERE date_id > 20260930)
  + (SELECT COUNT(*) FROM po WHERE order_date_id > 20260930 OR actual_receipt_date_id > 20260930)
UNION ALL
SELECT 'open_orders_incorrectly_received', COUNT(*) FROM po
WHERE order_status = 'open' AND (actual_receipt_date_id IS NOT NULL
      OR received_units <> 0 OR expected_arrival_date_id <= 20260930);

-- RESULT 4: six rows. Aggregate each fact to SKU/warehouse before joining.
-- This is a descriptive baseline, NOT a demand forecast or order recommendation.
-- Closing stock / trailing average fulfilled sales is biased when sales were censored.
WITH
recent_sales AS (
    SELECT s.product_id, s.warehouse_id, SUM(s.units_sold) / 28.0 AS avg_daily_sales
    FROM fact_sales AS s
    JOIN dim_date AS d ON d.date_id = s.date_id
    JOIN dim_scenario AS sc ON sc.scenario_id = s.scenario_id
    WHERE s.scenario_id = 'beverage_demo_v1'
      AND d.calendar_date BETWEEN DATE_SUB(sc.as_of_date, INTERVAL 27 DAY) AND sc.as_of_date
    GROUP BY s.product_id, s.warehouse_id
),
recent_inventory AS (
    SELECT i.product_id, i.warehouse_id, SUM(i.zero_stock_flag) AS zero_stock_days
    FROM fact_inventory AS i
    JOIN dim_date AS d ON d.date_id = i.date_id
    JOIN dim_scenario AS sc ON sc.scenario_id = i.scenario_id
    WHERE i.scenario_id = 'beverage_demo_v1'
      AND d.calendar_date BETWEEN DATE_SUB(sc.as_of_date, INTERVAL 27 DAY) AND sc.as_of_date
    GROUP BY i.product_id, i.warehouse_id
),
inbound AS (
    SELECT po.product_id, po.warehouse_id,
           SUM(po.ordered_units - po.received_units) AS open_order_units,
           MIN(d.calendar_date) AS next_expected_arrival
    FROM fact_purchase_orders AS po
    JOIN dim_date AS d ON d.date_id = po.expected_arrival_date_id
    WHERE po.scenario_id = 'beverage_demo_v1' AND po.order_status = 'open'
    GROUP BY po.product_id, po.warehouse_id
)
SELECT p.sku_code, i.closing_units AS on_hand_units,
       ROUND(s.avg_daily_sales, 2) AS avg_daily_sales_last_28d,
       ROUND(i.closing_units / NULLIF(s.avg_daily_sales, 0), 1) AS trailing_days_of_supply,
       ri.zero_stock_days AS zero_stock_days_last_28d,
       COALESCE(b.open_order_units, 0) AS open_order_units,
       b.next_expected_arrival,
       sp.lead_time_days,
       sc.as_of_date,
       sc.data_origin
FROM fact_inventory AS i
JOIN dim_scenario AS sc ON sc.scenario_id = i.scenario_id
JOIN dim_date AS d ON d.date_id = i.date_id AND d.calendar_date = sc.as_of_date
JOIN dim_product AS p ON p.product_id = i.product_id
JOIN sku_supply_policy AS sp ON sp.product_id = i.product_id AND sp.warehouse_id = i.warehouse_id
LEFT JOIN recent_sales AS s ON s.product_id = i.product_id AND s.warehouse_id = i.warehouse_id
LEFT JOIN recent_inventory AS ri ON ri.product_id = i.product_id AND ri.warehouse_id = i.warehouse_id
LEFT JOIN inbound AS b ON b.product_id = i.product_id AND b.warehouse_id = i.warehouse_id
WHERE i.scenario_id = 'beverage_demo_v1'
ORDER BY p.sku_code;

-- RESULT 5: actual receipt dates remain NULL for these open orders.
SELECT po.po_line_id, p.sku_code, od.calendar_date AS order_date,
       ed.calendar_date AS expected_arrival_date,
       ad.calendar_date AS actual_receipt_date,
       po.quantity_cases, po.ordered_units, po.received_units, po.order_status
FROM fact_purchase_orders AS po
JOIN dim_product AS p ON p.product_id = po.product_id
JOIN dim_date AS od ON od.date_id = po.order_date_id
JOIN dim_date AS ed ON ed.date_id = po.expected_arrival_date_id
LEFT JOIN dim_date AS ad ON ad.date_id = po.actual_receipt_date_id
WHERE po.scenario_id = 'beverage_demo_v1' AND po.order_status = 'open'
ORDER BY expected_arrival_date, p.sku_code;
