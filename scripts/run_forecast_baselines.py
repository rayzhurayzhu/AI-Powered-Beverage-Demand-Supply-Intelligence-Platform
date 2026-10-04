"""Step 5: point-in-time forecasting baselines for SYNTHETIC beverage data.
Run after SQL 06. No new dependencies: Python stdlib + mysql-connector-python.
Forecasts are planning estimates, not recovered true demand or purchase orders.
"""
import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from getpass import getpass
from pathlib import Path

import mysql.connector

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = 'beverage_demo_v1'
AS_OF = date(2026, 9, 30)
START = date(2024, 1, 1)
RUN_ID = 'baseline_v1_20260930'
VERSION = 'baseline_v1'
HORIZON = 84
BACKTEST_DAYS = 35
MODELS = ('mean_28', 'weekday_mean_56', 'seasonal_naive_7')
QUANTUM = Decimal('0.0001')
FIELDS = {
    'fact_forecast': ['run_id', 'product_id', 'warehouse_id', 'model_name',
                      'origin_date', 'target_date_id', 'split_name', 'forecast_units'],
    'forecast_evaluation': ['run_id', 'product_id', 'warehouse_id', 'model_name',
                            'origin_date', 'split_name', 'evaluation_scope', 'scored_days',
                            'excluded_days', 'actual_units', 'absolute_error_units',
                            'signed_error_units', 'mae_units', 'wape_pct', 'bias_pct'],
    'forecast_model_selection': ['run_id', 'product_id', 'warehouse_id', 'model_name',
                                 'validation_wape_pct', 'holdout_wape_pct',
                                 'holdout_bias_pct', 'holdout_scored_days',
                                 'holdout_excluded_days', 'training_imputed_days'],
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def key(day):
    return day.year * 10000 + day.month * 100 + day.day


def quant(value):
    return Decimal(str(value)).quantize(QUANTUM, rounding=ROUND_HALF_UP)


def average(values):
    require(bool(values), 'Cannot average an empty training sample.')
    return sum(values, Decimal(0)) / Decimal(len(values))


def get_rows(connection, sql, params=()):
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(sql, params)
        return cursor.fetchall()
    finally:
        cursor.close()


def validate_inputs(series, policies):
    expected = [START + timedelta(days=i) for i in range((AS_OF - START).days + 1)]
    require(set(series) == {(p, 1) for p in range(1, 7)}, 'Expected six demo SKU/warehouse series.')
    require({(p['product_id'], p['warehouse_id']) for p in policies} == set(series),
            'Supply policies and historical series do not match.')
    for sku, rows in series.items():
        require([r['day'] for r in rows] == expected, f'Missing/duplicate historical dates: {sku}')
        for r in rows:
            require(r['units'] >= 0 and r['censored'] in (0, 1), f'Invalid history: {sku}')
            require(r['channel_count'] == 3 and r['units'] == r['inventory_sold'],
                    f'Sales/inventory mismatch: {sku} {r["day"]}')
            require(r['closing_units'] >= 0 and r['censored'] == int(r['closing_units'] == 0),
                    f'Invalid zero-stock flag: {sku} {r["day"]}')
    for p in policies:
        require(p['lead_time_days'] > 0 and p['review_period_days'] > 0,
                'Lead time and review interval must be positive.')
        require(p['lead_time_days'] + p['review_period_days'] <= BACKTEST_DAYS,
                'Policy protection period exceeds 35 days: revise backtest design first.')
        require(p['max_cover_days'] <= HORIZON, 'Increase production horizon for max-cover policy.')


def read_inputs(connection):
    scenario = get_rows(connection, 'SELECT * FROM dim_scenario WHERE scenario_id=%s', (SCENARIO,))
    require(len(scenario) == 1, 'Run Step 4 first: scenario not found.')
    require(scenario[0]['history_start'] == START and scenario[0]['as_of_date'] == AS_OF
            and scenario[0]['data_origin'] == 'synthetic', 'Unexpected scenario dates or data origin.')
    policies = get_rows(connection, '''SELECT product_id, warehouse_id, lead_time_days,
        review_period_days, max_cover_days FROM sku_supply_policy WHERE warehouse_id=1
        ORDER BY product_id''')
    rows = get_rows(connection, '''
        SELECT d.calendar_date AS day, i.product_id, i.warehouse_id,
               s.units, s.channel_count, i.sold_units AS inventory_sold,
               i.closing_units, i.zero_stock_flag AS censored
        FROM fact_inventory i JOIN dim_date d ON d.date_id=i.date_id
        LEFT JOIN (
          SELECT scenario_id,date_id,product_id,warehouse_id,
                 SUM(units_sold) AS units, COUNT(*) AS channel_count
          FROM fact_sales WHERE scenario_id=%s
          GROUP BY scenario_id,date_id,product_id,warehouse_id
        ) s ON s.scenario_id=i.scenario_id AND s.date_id=i.date_id
           AND s.product_id=i.product_id AND s.warehouse_id=i.warehouse_id
        WHERE i.scenario_id=%s ORDER BY i.product_id,i.warehouse_id,d.calendar_date
    ''', (SCENARIO, SCENARIO))
    series = defaultdict(list)
    for r in rows:
        require(r['units'] is not None, 'Inventory date has no sales rows. Recheck Step 4.')
        series[(r['product_id'], r['warehouse_id'])].append({
            'day': r['day'], 'units': int(r['units']), 'censored': int(r['censored']),
            'channel_count': int(r['channel_count']), 'inventory_sold': int(r['inventory_sold']),
            'closing_units': int(r['closing_units'])})
    validate_inputs(series, policies)
    calendar = get_rows(connection, '''SELECT date_id,calendar_date FROM dim_date
        WHERE calendar_date BETWEEN %s AND %s ORDER BY calendar_date''',
        (START, AS_OF + timedelta(days=HORIZON)))
    expected = [START + timedelta(days=i) for i in range((AS_OF - START).days + HORIZON + 1)]
    require([r['calendar_date'] for r in calendar] == expected
            and all(r['date_id'] == key(r['calendar_date']) for r in calendar),
            'dim_date must cover history and the full 84-day forecast horizon.')
    return dict(series), policies


def training_values(rows, origin):
    """Causal imputation: past observed nonzero-stock days only; no future actuals.

    An end-of-day zero balance is a conservative censoring flag. It does not
    establish that demand was lost. Imputation is a heuristic, not ground truth.
    """
    clean, observed = [], []
    for r in rows:
        if r['day'] > origin:
            break
        if r['censored']:
            same = [Decimal(x['units']) for x in observed
                    if x['day'].weekday() == r['day'].weekday()][-8:]
            fallback = [Decimal(x['units']) for x in observed[-28:]]
            require(bool(same or fallback), 'No prior available-stock observations for imputation.')
            value = average(same or fallback)
        else:
            value = Decimal(r['units'])
            observed.append(r)
        clean.append((r['day'], value))
    require(len(clean) >= 56 and clean[-1][0] == origin, 'Insufficient contiguous training history.')
    return clean


def predict(rows, origin, model, horizon):
    train = training_values(rows, origin)
    if model == 'mean_28':
        means = {w: average([v for _, v in train[-28:]]) for w in range(7)}
    elif model == 'weekday_mean_56':
        means = {w: average([v for d, v in train[-56:] if d.weekday() == w]) for w in range(7)}
    elif model == 'seasonal_naive_7':
        means = {d.weekday(): v for d, v in train[-7:]}
    else:
        raise ValueError(f'Unknown model: {model}')
    return [(origin + timedelta(days=i), quant(means[(origin + timedelta(days=i)).weekday()]))
            for i in range(1, horizon + 1)]


def metrics(pairs, exclude_censored):
    sample = [(actual, predicted) for actual, predicted, censored in pairs
              if not (exclude_censored and censored)]
    n = len(sample)
    actual = sum((Decimal(a) for a, _ in sample), Decimal(0))
    absolute = sum((abs(p - Decimal(a)) for a, p in sample), Decimal(0))
    signed = sum((p - Decimal(a) for a, p in sample), Decimal(0))
    return {'scored_days': n, 'excluded_days': len(pairs) - n, 'actual_units': quant(actual),
            'absolute_error_units': quant(absolute), 'signed_error_units': quant(signed),
            'mae_units': quant(absolute / n) if n else None,
            'wape_pct': quant(100 * absolute / actual) if actual > 0 else None,
            'bias_pct': quant(100 * signed / actual) if actual > 0 else None}


def choose_model(evaluations):
    scores = {}
    for model in MODELS:
        rows = [r for r in evaluations if r['model_name'] == model
                and r['split_name'] == 'validation' and r['evaluation_scope'] == 'available_stock']
        require(len(rows) == 3 and all(r['scored_days'] >= 14 for r in rows),
                'Each validation fold needs at least 14 available-stock days.')
        denominator = sum(r['actual_units'] for r in rows)
        require(denominator > 0, 'Validation sales denominator is zero.')
        scores[model] = sum(r['absolute_error_units'] for r in rows) / denominator
    # Pooled absolute error / pooled actual sales, not an average of percentages.
    winner = min(MODELS, key=lambda m: (scores[m], MODELS.index(m)))
    return winner, quant(100 * scores[winner])


def build_outputs(series):
    data = {table: [] for table in FIELDS}
    folds = [('validation', AS_OF - timedelta(days=offset)) for offset in (140, 105, 70)]
    folds.append(('holdout', AS_OF - timedelta(days=35)))
    for (pid, wid), rows in sorted(series.items()):
        actuals = {r['day']: r for r in rows}
        evaluations = []
        for split, origin in folds:
            for model in MODELS:
                predictions = predict(rows, origin, model, BACKTEST_DAYS)
                pairs = []
                for day, qty in predictions:
                    data['fact_forecast'].append(dict(run_id=RUN_ID, product_id=pid, warehouse_id=wid,
                        model_name=model, origin_date=origin, target_date_id=key(day),
                        split_name=split, forecast_units=qty))
                    pairs.append((actuals[day]['units'], qty, actuals[day]['censored']))
                for scope in ('all_days', 'available_stock'):
                    evaluations.append(dict(run_id=RUN_ID, product_id=pid, warehouse_id=wid,
                        model_name=model, origin_date=origin, split_name=split,
                        evaluation_scope=scope, **metrics(pairs, scope == 'available_stock')))
        winner, validation_wape = choose_model(evaluations)
        holdout = next(r for r in evaluations if r['model_name'] == winner
                       and r['split_name'] == 'holdout' and r['evaluation_scope'] == 'available_stock')
        require(holdout['scored_days'] >= 14 and holdout['wape_pct'] is not None,
                f'Insufficient holdout evidence for SKU {pid}.')
        data['forecast_evaluation'].extend(evaluations)
        data['forecast_model_selection'].append(dict(run_id=RUN_ID, product_id=pid, warehouse_id=wid,
            model_name=winner, validation_wape_pct=validation_wape,
            holdout_wape_pct=holdout['wape_pct'], holdout_bias_pct=holdout['bias_pct'],
            holdout_scored_days=holdout['scored_days'], holdout_excluded_days=holdout['excluded_days'],
            training_imputed_days=sum(r['censored'] for r in rows)))
        for day, qty in predict(rows, AS_OF, winner, HORIZON):
            data['fact_forecast'].append(dict(run_id=RUN_ID, product_id=pid, warehouse_id=wid,
                model_name=winner, origin_date=AS_OF, target_date_id=key(day),
                split_name='production', forecast_units=qty))
    validate_outputs(data, len(series))
    return data


def validate_outputs(data, sku_count):
    require(len(data['fact_forecast']) == sku_count * (3 * 4 * 35 + HORIZON), 'Forecast count mismatch.')
    require(len(data['forecast_evaluation']) == sku_count * 3 * 4 * 2, 'Evaluation count mismatch.')
    require(len(data['forecast_model_selection']) == sku_count, 'Selection count mismatch.')
    grains = set()
    for row in data['fact_forecast']:
        grain = tuple(row[f] for f in FIELDS['fact_forecast'][:-2])
        require(grain not in grains, 'Duplicate forecast grain.')
        grains.add(grain)
        require(row['forecast_units'].is_finite() and row['forecast_units'] >= 0, 'Invalid forecast.')
        require(row['target_date_id'] > key(row['origin_date']), 'Target is not after origin.')
        require((row['target_date_id'] > key(AS_OF)) == (row['split_name'] == 'production'),
                'Historical/production date boundary violation.')
    for s in data['forecast_model_selection']:
        rows = [r for r in data['fact_forecast'] if r['product_id'] == s['product_id']
                and r['warehouse_id'] == s['warehouse_id'] and r['split_name'] == 'production']
        require(len(rows) == HORIZON and all(r['model_name'] == s['model_name'] for r in rows),
                'Production forecast does not match the selected model.')


def input_fingerprint(series, policies):
    payload = {'series': [{'product_id': p, 'warehouse_id': w, 'rows': rows}
                          for (p, w), rows in sorted(series.items())], 'policies': policies}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode('utf-8')).hexdigest()


def save_files(data, series, policies):
    directory = ROOT / 'data' / 'processed' / RUN_ID
    directory.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for table, fields in FIELDS.items():
        path = directory / f'{table}.csv'
        with path.open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(data[table])
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {'run_id': RUN_ID, 'scenario_id': SCENARIO, 'code_version': VERSION,
        'as_of_date': AS_OF.isoformat(), 'horizon_days': HORIZON, 'backtest_days': BACKTEST_DAYS,
        'models': MODELS, 'data_origin': 'synthetic', 'python_version': sys.version.split()[0],
        'input_sha256': input_fingerprint(series, policies), 'policy_snapshot': policies,
        'csv_sha256': hashes, 'row_counts': {t: len(v) for t, v in data.items()},
        'selection': 'Lowest pooled validation WAPE on available-stock days; never holdout error.',
        'bias_convention': '100 * sum(forecast - actual) / sum(actual); positive = overforecast.',
        'censoring': 'Closing stock zero => flag; causal historical-only imputation in training. '
                     'Available-stock scoring excludes flagged days; all-days scoring is also retained. '
                     'Neither is a direct measure of lost or unconstrained demand.',
        'limitations': 'No causal holiday/promotion attribution, prediction intervals, future '
                       'promotion calendar, weather features or order recommendations in this step. '
                       'Backtest validates 35-day forecasts; days 36-84 are unvalidated extensions.'}
    (directory / 'manifest.json').write_text(json.dumps(manifest, indent=2, default=str), encoding='utf-8')
    print(f'CSV files and manifest: {directory}')
    return manifest


def load(connection, data, manifest):
    connection.commit()
    cursor = connection.cursor()
    try:
        connection.start_transaction()
        # Only this run is refreshed. Run one process at a time.
        for table in FIELDS:
            cursor.execute(f'DELETE FROM {table} WHERE run_id=%s', (RUN_ID,))
        cursor.execute('DELETE FROM forecast_run WHERE run_id=%s', (RUN_ID,))
        cursor.execute('''INSERT INTO forecast_run
            (run_id,scenario_id,as_of_date,horizon_days,backtest_days,code_version,
             input_sha256,data_origin,created_at_utc,assumptions_json)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (RUN_ID, SCENARIO, AS_OF, HORIZON, BACKTEST_DAYS, VERSION, manifest['input_sha256'],
             'synthetic', datetime.now(timezone.utc).replace(tzinfo=None), json.dumps(manifest, default=str)))
        for table, fields in FIELDS.items():
            statement = f"INSERT INTO {table} ({', '.join(fields)}) VALUES ({', '.join(['%s'] * len(fields))})"
            rows = [tuple(r[f] for f in fields) for r in data[table]]
            for start in range(0, len(rows), 1000):
                cursor.executemany(statement, rows[start:start + 1000])
            cursor.execute(f'SELECT COUNT(*) FROM {table} WHERE run_id=%s', (RUN_ID,))
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
    parser.add_argument('--generate-only', action='store_true', help='Read MySQL, write CSVs, skip database load')
    args = parser.parse_args()
    connection = mysql.connector.connect(host=args.host, port=args.port, user=args.user,
        password=getpass(f'MySQL password for {args.user}: '), database='beverage_intelligence',
        charset='utf8mb4', connection_timeout=10, autocommit=False)
    try:
        series, policies = read_inputs(connection)
        data = build_outputs(series)
        print(f'Scenario: {SCENARIO} | SYNTHETIC | As of {AS_OF}')
        for table, rows in data.items():
            print(f'{table}: {len(rows)} rows')
        print('FORECAST VALIDATION OK')
        print('SKU | selected model | validation WAPE % | holdout WAPE % | excluded holdout days')
        for r in data['forecast_model_selection']:
            print(f"{r['product_id']} | {r['model_name']} | {r['validation_wape_pct']} | "
                  f"{r['holdout_wape_pct']} | {r['holdout_excluded_days']}")
        manifest = save_files(data, series, policies)
        if args.generate_only:
            print('GENERATE OK. Database forecasts were not changed.')
            return
        load(connection, data, manifest)
        print('FORECAST PIPELINE OK')
        print('Next: run sql/07_verify_forecasts.sql in MySQL Workbench.')
    finally:
        connection.close()


if __name__ == '__main__':
    try:
        main()
    except (mysql.connector.Error, ValueError, OSError) as error:
        print(f'ERROR [{type(error).__name__}]: {error}', file=sys.stderr)
        sys.exit(1)
