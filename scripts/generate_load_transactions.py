"""Step 4: reproducible SYNTHETIC beverage sales, inventory and purchase orders.

Requires existing Steps 1-3 and sql/04_create_transaction_tables.sql.
Uses only the previously installed mysql-connector-python plus Python stdlib.
Run one instance at a time. Never interpret this demo as real APB performance.
"""
import argparse
import csv
import hashlib
import json
import math
import random
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from getpass import getpass
from pathlib import Path

import mysql.connector

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = 'beverage_demo_v1'
START = date(2024, 1, 1)
AS_OF = date(2026, 9, 30)
SEED = 20261004
DAYS = (AS_OF - START).days + 1
BASE_UNITS = {1: 100, 2: 65, 3: 80, 4: 45, 5: 130, 6: 75}
PRICE_CENTS = {1: 260, 2: 340, 3: 300, 4: 240, 5: 90, 6: 180}
# Deliberately varied historical behavior to exercise shortage/overstock cases.
# These are assumptions of the data generator, not a proposed optimal policy.
ORDER_FACTORS = {1: 0.75, 2: 1.0, 3: 1.0, 4: 1.2, 5: 1.7, 6: 0.9}

FIELDS = {
    'fact_sales': ['scenario_id', 'date_id', 'product_id', 'warehouse_id',
                   'channel_id', 'units_sold', 'unit_price_sgd', 'revenue_sgd', 'is_promotion'],
    'fact_inventory': ['scenario_id', 'date_id', 'product_id', 'warehouse_id',
                       'opening_units', 'received_units', 'sold_units', 'closing_units',
                       'zero_stock_flag'],
    'fact_purchase_orders': ['scenario_id', 'po_line_id', 'product_id', 'warehouse_id',
                            'supplier_id', 'order_date_id', 'expected_arrival_date_id',
                            'actual_receipt_date_id', 'quantity_cases',
                            'units_per_case_on_order', 'ordered_units', 'received_units',
                            'landed_cost_per_case_sgd', 'order_status'],
}


def date_key(day):
    return day.year * 10000 + day.month * 100 + day.day


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_inputs(connection):
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute('''
            SELECT p.sku_code, p.units_per_case,
                   p.data_origin AS product_origin, sp.*
            FROM dim_product AS p JOIN sku_supply_policy AS sp
              ON p.product_id = sp.product_id
            WHERE sp.warehouse_id = 1 ORDER BY p.product_id
        ''')
        policies = cursor.fetchall()
        require([p['product_id'] for p in policies] == list(range(1, 7)),
                'Expected the six Step 3 products and one policy each for warehouse 1.')
        for p in policies:
            require(p['sku_code'] == f"DEMO-BEV-{p['product_id']:03d}",
                    'Product IDs do not match the Step 3 demo SKUs.')
            require(p['product_origin'] == p['data_origin'] == 'synthetic',
                    'This generator only accepts synthetic demo master data.')
            for field in ['units_per_case', 'lead_time_days', 'review_period_days',
                          'min_order_cases', 'order_multiple_cases']:
                require(p[field] > 0, f'Invalid policy field: {field}')
        cursor.execute('SELECT channel_id, channel_code FROM dim_channel ORDER BY channel_id')
        channels = [(r['channel_id'], r['channel_code']) for r in cursor.fetchall()]
        require(channels == [(1, 'retail'), (2, 'on_trade'), (3, 'distributor')],
                'Run sql/04_create_transaction_tables.sql; expected three demo channels.')
        end = AS_OF + timedelta(days=max(p['lead_time_days'] for p in policies))
        cursor.execute('''SELECT date_id, calendar_date, is_sg_public_holiday
                          FROM dim_date WHERE calendar_date BETWEEN %s AND %s
                          ORDER BY calendar_date''', (START, end))
        calendar = cursor.fetchall()
        expected = [START + timedelta(days=i) for i in range((end - START).days + 1)]
        require([r['calendar_date'] for r in calendar] == expected,
                'dim_date must cover the history and future arrival dates without gaps.')
        require(all(r['date_id'] == date_key(r['calendar_date']) for r in calendar),
                'Date keys are inconsistent.')
        require(all(r['is_sg_public_holiday'] in (0, 1) for r in calendar
                    if r['calendar_date'] <= AS_OF), 'Historical holiday coverage is unknown.')
        return policies, {r['calendar_date']: r['is_sg_public_holiday'] for r in calendar}
    finally:
        cursor.close()


def allocate_stock(requested, available):
    """Proportional allocation with largest remainders; preserves integer units."""
    total = sum(requested)
    if total <= available:
        return requested[:]
    quantities = [available * q // total for q in requested]
    order = sorted(range(len(requested)),
                   key=lambda i: (-(available * requested[i] % total), i))
    for i in order[:available - sum(quantities)]:
        quantities[i] += 1
    return quantities


def generate(policies, holidays):
    data = {table: [] for table in FIELDS}
    for p in policies:
        pid = p['product_id']
        rng = random.Random(SEED + pid)
        stock = BASE_UNITS[pid] * 45  # Explicit initial stock; no pre-history PO invented.
        pending = []
        history = []
        sequence = 0
        for offset in range(DAYS):
            day = START + timedelta(days=offset)
            key = date_key(day)
            opening = stock
            receipts = 0
            for po in pending:
                if po['order_status'] == 'open' and po['expected_arrival_date_id'] == key:
                    po['order_status'] = 'received'
                    po['actual_receipt_date_id'] = key
                    po['received_units'] = po['ordered_units']
                    receipts += po['ordered_units']
            stock += receipts
            promo = int(day.day in (10, 11, 12) and (day.month + pid) % 3 == 0)
            season = 1 + 0.10 * math.sin(2 * math.pi * (day.timetuple().tm_yday - 1) / 365.25)
            trend = 1 + 0.00015 * offset
            holiday = 1.20 if holidays[day] else 1.0
            requested = []
            for channel, share in [(1, 0.5), (2, 0.3), (3, 0.2)]:
                weekend = (1.35 if channel == 2 else 1.10) if day.weekday() >= 5 else 1.0
                demand = BASE_UNITS[pid] * share * season * trend * holiday * weekend
                demand *= 1.25 if promo else 1.0
                demand *= max(0.20, rng.gauss(1.0, 0.15))
                requested.append(max(0, round(demand)))
            fulfilled = allocate_stock(requested, stock)
            sold = sum(fulfilled)
            stock -= sold
            history.append(sold)
            # Latent requested demand is deliberately NOT a model input/table column.
            for channel, units in enumerate(fulfilled, start=1):
                price_cents = PRICE_CENTS[pid]
                if channel == 3:
                    price_cents = (price_cents * 95 + 50) // 100
                if promo:
                    price_cents = (price_cents * 90 + 50) // 100
                price = Decimal(price_cents) / Decimal(100)
                data['fact_sales'].append(dict(
                    scenario_id=SCENARIO, date_id=key, product_id=pid, warehouse_id=1,
                    channel_id=channel, units_sold=units, unit_price_sgd=price,
                    revenue_sgd=price * units, is_promotion=promo))
            data['fact_inventory'].append(dict(
                scenario_id=SCENARIO, date_id=key, product_id=pid, warehouse_id=1,
                opening_units=opening, received_units=receipts, sold_units=sold,
                closing_units=stock, zero_stock_flag=int(stock == 0)))

            # Orders are placed at END OF DAY, every review interval from START.
            # Only observed sales to this day enter the historical ordering heuristic.
            if offset % p['review_period_days'] == 0:
                rate = sum(history[-7:]) / len(history[-7:])
                target = math.ceil(rate * (p['lead_time_days'] + p['review_period_days']
                                           + p['safety_stock_days']) * ORDER_FACTORS[pid])
                on_order = sum(po['ordered_units'] for po in pending if po['order_status'] == 'open')
                net = target - stock - on_order
                if net > 0:
                    cases_needed = (net + p['units_per_case'] - 1) // p['units_per_case']
                    minimum = max(cases_needed, p['min_order_cases'])
                    multiple = p['order_multiple_cases']
                    cases = ((minimum + multiple - 1) // multiple) * multiple
                    sequence += 1
                    po = dict(
                        scenario_id=SCENARIO, po_line_id=f'DEMO-{pid:02d}-{sequence:05d}',
                        product_id=pid, warehouse_id=1, supplier_id=p['supplier_id'],
                        order_date_id=key,
                        expected_arrival_date_id=date_key(day + timedelta(days=p['lead_time_days'])),
                        actual_receipt_date_id=None, quantity_cases=cases,
                        units_per_case_on_order=p['units_per_case'],
                        ordered_units=cases * p['units_per_case'], received_units=0,
                        landed_cost_per_case_sgd=p['landed_cost_per_case_sgd'], order_status='open')
                    pending.append(po)
                    data['fact_purchase_orders'].append(po)
    return data


def validate(data, policies):
    sales = data['fact_sales']
    inventory = data['fact_inventory']
    orders = data['fact_purchase_orders']
    require(len(sales) == DAYS * 6 * 3, 'Unexpected sales row count.')
    require(len(inventory) == DAYS * 6, 'Unexpected inventory row count.')
    key = lambda r: (r['date_id'], r['product_id'], r['warehouse_id'])
    require(len({(*key(r), r['channel_id']) for r in sales}) == len(sales), 'Duplicate sales grain.')
    require(len({key(r) for r in inventory}) == len(inventory), 'Duplicate inventory grain.')
    require(len({r['po_line_id'] for r in orders}) == len(orders), 'Duplicate PO line IDs.')
    policies = {p['product_id']: p for p in policies}
    totals = Counter()
    receipts = Counter()
    for r in sales:
        require(r['units_sold'] >= 0 and r['revenue_sgd'] == r['units_sold'] * r['unit_price_sgd'],
                'Sales revenue or quantity mismatch.')
        require(date_key(START) <= r['date_id'] <= date_key(AS_OF), 'Sales outside history.')
        totals[key(r)] += r['units_sold']
    for po in orders:
        p = policies[po['product_id']]
        require(po['quantity_cases'] >= p['min_order_cases']
                and po['quantity_cases'] % p['order_multiple_cases'] == 0, 'PO violates MOQ/multiple.')
        require(po['ordered_units'] == po['quantity_cases'] * p['units_per_case'], 'PO units mismatch.')
        require(po['supplier_id'] == p['supplier_id'], 'PO supplier mismatch.')
        require(date_key(START) <= po['order_date_id'] <= date_key(AS_OF), 'Future order created.')
        order_day = date.fromisoformat(str(po['order_date_id'])[:4] + '-'
                                     + str(po['order_date_id'])[4:6] + '-'
                                     + str(po['order_date_id'])[6:])
        require(po['expected_arrival_date_id'] == date_key(order_day + timedelta(days=p['lead_time_days'])),
                'PO lead-time mismatch.')
        if po['order_status'] == 'received':
            require(po['actual_receipt_date_id'] == po['expected_arrival_date_id'] <= date_key(AS_OF),
                    'Invalid actual receipt date.')
            require(po['received_units'] == po['ordered_units'], 'Receipt quantity mismatch.')
            receipts[(po['actual_receipt_date_id'], po['product_id'], po['warehouse_id'])] += po['received_units']
        else:
            require(po['order_status'] == 'open' and po['actual_receipt_date_id'] is None
                    and po['received_units'] == 0 and po['expected_arrival_date_id'] > date_key(AS_OF),
                    'Open order incorrectly recognized as received.')
    previous = {}
    for r in sorted(inventory, key=key):
        pw = (r['product_id'], r['warehouse_id'])
        require(r['opening_units'] == previous.get(pw, BASE_UNITS[r['product_id']] * 45),
                'Inventory continuity mismatch.')
        require(r['opening_units'] + r['received_units'] - r['sold_units'] == r['closing_units'] >= 0,
                'Inventory balance mismatch.')
        require(r['sold_units'] == totals[key(r)], 'Sales-to-inventory mismatch.')
        require(r['received_units'] == receipts[key(r)], 'PO-to-inventory mismatch.')
        require(r['zero_stock_flag'] == int(r['closing_units'] == 0), 'Zero-stock flag mismatch.')
        previous[pw] = r['closing_units']
    require(set(receipts) <= {key(r) for r in inventory}, 'Orphan receipt date.')
    return {table: len(rows) for table, rows in data.items()}


def save_files(data, policies, holidays, counts):
    directory = ROOT / 'data' / 'processed' / SCENARIO
    directory.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for table, fields in FIELDS.items():
        path = directory / f'{table}.csv'
        with path.open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(data[table])
        hashes[table] = hashlib.sha256(path.read_bytes()).hexdigest()
    assumptions = {
        'scenario_id': SCENARIO, 'generator_version': '1.0', 'data_origin': 'synthetic',
        'history_start': START.isoformat(), 'as_of_date': AS_OF.isoformat(), 'seed': SEED,
        'base_daily_units': BASE_UNITS, 'base_price_cents_sgd': PRICE_CENTS,
        'historical_order_factors': ORDER_FACTORS, 'initial_stock_days_of_base_units': 45,
        'notes': 'Sales capped by availability; zero stock is a censoring signal, not measured lost demand. '
                 'Synthetic holiday/promotion effects are programmed assumptions, not empirical causal findings. '
                 'Orders use trailing 7-day fulfilled sales; fixed calendar lead times; no backorders, '
                 'returns, damage, partial receipts, transfers or cancellations. Prices are warehouse sales prices. '
                 'Order reviews anchored at end of 2024-01-01, then every configured review interval. '
                 'No future sales/actual receipts are generated after the fixed as-of date.',
        'master_inputs': policies,
        'historical_holiday_dates': [d.isoformat() for d, flag in sorted(holidays.items()) if flag == 1 and d <= AS_OF],
        'rows': counts, 'csv_sha256': hashes,
        'python_version': sys.version.split()[0],
    }
    (directory / 'manifest.json').write_text(json.dumps(assumptions, indent=2, default=str), encoding='utf-8')
    print(f'CSV files and input manifest: {directory}')
    return assumptions


def load(connection, data, assumptions):
    connection.commit()  # Close the read-input transaction before starting a refresh.
    cursor = connection.cursor()
    try:
        connection.start_transaction()
        # This refresh affects this named synthetic scenario only; no TRUNCATE.
        for table in FIELDS:
            cursor.execute(f'DELETE FROM {table} WHERE scenario_id = %s', (SCENARIO,))
        cursor.execute('DELETE FROM dim_scenario WHERE scenario_id = %s', (SCENARIO,))
        cursor.execute('''INSERT INTO dim_scenario
            (scenario_id, history_start, as_of_date, random_seed, data_origin,
             assumptions_json, generated_at_utc) VALUES (%s,%s,%s,%s,%s,%s,%s)''',
            (SCENARIO, START, AS_OF, SEED, 'synthetic', json.dumps(assumptions, default=str),
             datetime.now(timezone.utc).replace(tzinfo=None)))
        for table, fields in FIELDS.items():
            # Identifiers come only from the constant FIELDS allowlist.
            statement = f"INSERT INTO {table} ({', '.join(fields)}) VALUES ({', '.join(['%s'] * len(fields))})"
            rows = [tuple(row[f] for f in fields) for row in data[table]]
            for offset in range(0, len(rows), 1000):
                cursor.executemany(statement, rows[offset:offset + 1000])
            cursor.execute(f'SELECT COUNT(*) FROM {table} WHERE scenario_id = %s', (SCENARIO,))
            require(cursor.fetchone()[0] == len(rows), f'Database count mismatch: {table}')
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=3306)
    parser.add_argument('--user', default='root')
    parser.add_argument('--generate-only', action='store_true',
                        help='Read existing MySQL inputs and generate/validate CSVs without writing facts')
    args = parser.parse_args()
    connection = mysql.connector.connect(host=args.host, port=args.port, user=args.user,
        password=getpass(f'MySQL password for {args.user}: '), database='beverage_intelligence',
        charset='utf8mb4', connection_timeout=10, autocommit=False)
    try:
        policies, holidays = read_inputs(connection)
        data = generate(policies, holidays)
        counts = validate(data, policies)
        print(f'Scenario: {SCENARIO} | SYNTHETIC | As of {AS_OF}')
        for table, count in counts.items():
            print(f'{table}: {count} rows')
        print('DATA VALIDATION OK: stock balance, continuity, sales, receipts and PO rules.')
        assumptions = save_files(data, policies, holidays, counts)
        if args.generate_only:
            print('GENERATE OK. No fact tables were written.')
            return
        load(connection, data, assumptions)
        print('TRANSACTION PIPELINE OK')
        print('Next: run sql/05_verify_transactions.sql in MySQL Workbench.')
    finally:
        connection.close()


if __name__ == '__main__':
    try:
        main()
    except (mysql.connector.Error, ValueError, OSError) as error:
        print(f'ERROR [{type(error).__name__}]: {error}', file=sys.stderr)
        sys.exit(1)
