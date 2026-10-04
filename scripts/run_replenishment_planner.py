"""Step 6: dated inventory risk and one-cycle replenishment recommendations.

SYNTHETIC demonstration. No purchase orders are created or submitted.
Requires Step 5's run_forecast_baselines.py in the same scripts folder.
Uses Python stdlib and the existing mysql-connector-python installation.
"""
import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING
from getpass import getpass
from pathlib import Path

import mysql.connector
import run_forecast_baselines as fc

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = 'planner_v1_20260930'
VERSION = 'planner_v1'
AS_OF = fc.AS_OF
HORIZON = fc.HORIZON
ZERO = Decimal(0)
ONE_DAY = timedelta(days=1)
# Illustrative stress assumptions, NOT confidence intervals or probabilities.
STRESSES = {'base': (Decimal('1.0'), 0), 'demand_up_20': (Decimal('1.2'), 0),
            'demand_down_20': (Decimal('0.8'), 0), 'arrival_delay_7': (Decimal('1.0'), 7)}
PATHS = ('existing_only', 'with_recommendation')
FIELDS = {
 'fact_replenishment_recommendation': [
    'planning_run_id','product_id','warehouse_id','supplier_id','model_name',
    'on_hand_units','open_order_units','units_per_case','lead_time_days','review_period_days',
    'min_order_cases','order_multiple_cases','safety_stock_days','max_cover_days',
    'landed_cost_per_case_sgd','scheduled_review_date','planning_review_date','next_review_date',
    'normal_arrival_date','coverage_end_date','safety_target_units','net_required_units',
    'recommended_cases','recommended_units','estimated_purchase_cost_sgd',
    'proposed_order_date','proposed_arrival_date','first_shortage_date_existing',
    'latest_normal_order_date','unmet_before_arrival_units','unmet_14d_units',
    'stock_cover_days','stock_cover_capped','committed_excess_units','action_code'],
 'fact_inventory_projection': [
    'planning_run_id','product_id','warehouse_id','stress_name','plan_path','projection_date',
    'opening_units','existing_receipt_units','recommended_receipt_units','demand_units',
    'fulfilled_units','unmet_units','closing_units'],
 'replenishment_sensitivity': [
    'planning_run_id','product_id','warehouse_id','stress_name','demand_factor','arrival_delay_days',
    'first_shortage_existing','first_shortage_with_plan','unmet_14d_existing','unmet_14d_with_plan',
    'unmet_cycle_existing','unmet_cycle_with_plan','unmet_84d_existing','unmet_84d_with_plan',
    'closing_84d_existing','closing_84d_with_plan','committed_excess_existing','committed_excess_with_plan']}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def q(value):
    return fc.quant(value)


def digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode('utf-8')).hexdigest()


def next_review(day, anchor, interval, strictly_after=False):
    require(interval > 0 and anchor <= day, 'Invalid review schedule.')
    wait = (-(day - anchor).days) % interval
    if strictly_after and wait == 0:
        wait = interval
    return day + timedelta(days=wait)


def round_cases(net_units, units_per_case, minimum, multiple):
    require(units_per_case > 0 and minimum > 0 and multiple > 0, 'Invalid case policy.')
    if net_units <= 0:
        return 0
    cases = int((net_units / Decimal(units_per_case)).to_integral_value(rounding=ROUND_CEILING))
    return ((max(cases, minimum) + multiple - 1) // multiple) * multiple


def project(stock, demand, receipts, proposed_date=None, proposed_units=ZERO):
    """Morning receipts, demand, closing stock. Unmet demand is LOST, not backlogged."""
    rows = []
    balance = Decimal(stock)
    for day, need in sorted(demand.items()):
        opening = balance
        existing = Decimal(receipts.get(day, ZERO))
        recommended = Decimal(proposed_units) if day == proposed_date else ZERO
        available = opening + existing + recommended
        fulfilled = min(available, need)
        balance = available - fulfilled
        rows.append(dict(projection_date=day, opening_units=q(opening),
            existing_receipt_units=q(existing), recommended_receipt_units=q(recommended),
            demand_units=q(need), fulfilled_units=q(fulfilled), unmet_units=q(need - fulfilled),
            closing_units=q(balance)))
    return rows


def first_shortage(rows):
    return next((r['projection_date'] for r in rows if r['unmet_units'] > 0), None)


def unmet_through(rows, last_day):
    return q(sum((r['unmet_units'] for r in rows if r['projection_date'] <= last_day), ZERO))


def physical_cover(stock, demand):
    """Stock-only cover, fraction of the next forecast day; excludes all inbound POs."""
    remaining = Decimal(stock)
    days = ZERO
    for _, need in sorted(demand.items()):
        if need > remaining:
            return q(days + remaining / need), 0
        remaining -= need
        days += 1
    return q(days), int(remaining > 0 or all(v == 0 for v in demand.values()))


def committed_excess(stock, demand, receipts, as_of, cover_days, proposed_date=None, proposed_units=ZERO):
    """Quantity screen: stock + receipts within cover window - forecast within it.

    This includes committed inbound stock. It is not physical-stock cover, expiry
    loss, or proof of waste; timing risk is reported separately by daily projection.
    """
    end = as_of + timedelta(days=cover_days)
    need = sum((v for d, v in demand.items() if d <= end), ZERO)
    incoming = sum((Decimal(v) for d, v in receipts.items() if as_of < d <= end), ZERO)
    if proposed_date is not None and as_of < proposed_date <= end:
        incoming += proposed_units
    return q(max(ZERO, Decimal(stock) + incoming - need))


def order_requirement(stock, demand, receipts, baseline, arrival, coverage_end, safety_days):
    """Minimum continuous units to avoid shortage from arrival through cycle end,
    AND leave the specified demand-based safety buffer at cycle end.
    Shortages before arrival are excluded from the order quantity (no backorders).
    """
    require(arrival in demand and coverage_end in demand, 'Planning cycle exceeds forecast coverage.')
    safety_dates = [coverage_end + timedelta(days=i) for i in range(1, safety_days + 1)]
    require(all(d in demand for d in safety_dates), 'Forecast does not cover the safety buffer.')
    before = [r for r in baseline if r['projection_date'] < arrival]
    balance = before[-1]['closing_units'] if before else Decimal(stock)
    needed = ZERO
    for day in sorted(d for d in demand if arrival <= d <= coverage_end):
        balance += Decimal(receipts.get(day, ZERO)) - demand[day]
        needed = max(needed, -balance)
    safety = sum((demand[d] for d in safety_dates), ZERO)
    return q(max(ZERO, needed, safety - balance)), q(safety)


def plan_sku(policy, stock, demand, receipts, as_of=AS_OF, anchor=fc.START):
    require(bool(demand), 'No forecast dates.')
    expected = [as_of + timedelta(days=i) for i in range(1, len(demand) + 1)]
    require(sorted(demand) == expected and all(v.is_finite() and v >= 0 for v in demand.values()),
            'Forecast must be contiguous, finite and nonnegative.')
    require(stock >= 0, 'Physical stock must be nonnegative.')
    require(all(d > as_of and Decimal(v) >= 0 for d, v in receipts.items()),
            'Overdue/invalid inbound order: confirm a future ETA before planning.')
    require(0 < policy['max_cover_days'] <= len(demand), 'Invalid max-cover window.')
    lead, review = policy['lead_time_days'], policy['review_period_days']
    require(lead > 0 and review > 0 and policy['safety_stock_days'] >= 0, 'Invalid supply timing.')
    baseline = project(stock, demand, receipts)
    first = first_shortage(baseline)
    scheduled = next_review(as_of, anchor, review)
    scheduled_arrival = scheduled + timedelta(days=lead)
    # An earlier review is an explicit exception; it does not imply faster transport.
    chosen = as_of if first is not None and first < scheduled_arrival else scheduled
    following = next_review(chosen, anchor, review, strictly_after=True)
    arrival = chosen + timedelta(days=lead)
    cycle_end = following + timedelta(days=lead) - ONE_DAY
    net, safety = order_requirement(stock, demand, receipts, baseline, arrival, cycle_end,
                                    policy['safety_stock_days'])
    cases = round_cases(net, policy['units_per_case'], policy['min_order_cases'], policy['order_multiple_cases'])
    units = cases * policy['units_per_case']
    shortage_before = unmet_through(baseline, arrival - ONE_DAY)
    excess = committed_excess(stock, demand, receipts, as_of, policy['max_cover_days'])
    if shortage_before > 0:
        action = 'EXPEDITE_REVIEW'
    elif cases > 0 and chosen < scheduled:
        action = 'ORDER_EARLY'
    elif cases > 0:
        action = 'ORDER_AT_REVIEW'
    elif excess > 0:
        action = 'REVIEW_EXCESS'
    else:
        action = 'MONITOR'
    cover, capped = physical_cover(stock, demand)
    result = dict(planning_run_id=RUN_ID, product_id=policy['product_id'],
        warehouse_id=policy['warehouse_id'], supplier_id=policy['supplier_id'],
        model_name=policy['model_name'], on_hand_units=int(stock),
        open_order_units=int(sum(receipts.values(), ZERO)),
        **{k: policy[k] for k in ['units_per_case','lead_time_days','review_period_days',
            'min_order_cases','order_multiple_cases','safety_stock_days','max_cover_days','landed_cost_per_case_sgd']},
        scheduled_review_date=scheduled, planning_review_date=chosen, next_review_date=following,
        normal_arrival_date=arrival, coverage_end_date=cycle_end, safety_target_units=safety,
        net_required_units=net, recommended_cases=cases, recommended_units=units,
        estimated_purchase_cost_sgd=(Decimal(cases) * Decimal(policy['landed_cost_per_case_sgd'])).quantize(Decimal('0.01')),
        proposed_order_date=chosen if cases else None, proposed_arrival_date=arrival if cases else None,
        first_shortage_date_existing=first,
        latest_normal_order_date=first - timedelta(days=lead) if first is not None else None,
        unmet_before_arrival_units=shortage_before,
        unmet_14d_units=unmet_through(baseline, as_of + timedelta(days=14)),
        stock_cover_days=cover, stock_cover_capped=capped, committed_excess_units=excess,
        action_code=action)
    return result


def verify_forecast_source(series, policies, run, production, selections):
    require(run['run_id'] == fc.RUN_ID and run['as_of_date'] == AS_OF
            and run['scenario_id'] == fc.SCENARIO and run['code_version'] == fc.VERSION
            and run['horizon_days'] == HORIZON and run['data_origin'] == 'synthetic',
            'Unexpected forecast run or incompatible Step 5 version.')
    require(run['input_sha256'] == fc.input_fingerprint(series, policies),
            'Historical inputs or forecast policies changed. Forecast is stale; rebuild dependencies first.')
    # Recompute the tiny baseline job to reject manually edited forecast/selection rows.
    expected = fc.build_outputs(series)
    wanted = {(r['product_id'], r['warehouse_id'], r['target_date_id']):
              (r['model_name'], r['forecast_units']) for r in expected['fact_forecast'] if r['split_name']=='production'}
    actual = {(r['product_id'], r['warehouse_id'], r['target_date_id']):
              (r['model_name'], r['forecast_units']) for r in production}
    require(len(production) == len(wanted) and actual == wanted,
            'Stored production forecasts do not match the verified Step 5 inputs/version.')
    selected = {(r['product_id'],r['warehouse_id']):r['model_name'] for r in selections}
    require(len(selections)==6 and selected == {(r['product_id'],r['warehouse_id']):r['model_name']
            for r in expected['forecast_model_selection']}, 'Selected-model mismatch.')


def read_inputs(connection):
    # One coherent input snapshot. Run no source/forecast refresh concurrently.
    connection.start_transaction(isolation_level='REPEATABLE READ', consistent_snapshot=True, readonly=True)
    series, forecast_policies = fc.read_inputs(connection)
    runs = fc.get_rows(connection, 'SELECT * FROM forecast_run WHERE run_id=%s', (fc.RUN_ID,))
    require(len(runs)==1, 'Step 5 forecast run is missing.')
    production = fc.get_rows(connection, '''SELECT * FROM fact_forecast
        WHERE run_id=%s AND split_name='production' ORDER BY product_id,warehouse_id,target_date_id''', (fc.RUN_ID,))
    selections = fc.get_rows(connection, 'SELECT * FROM forecast_model_selection WHERE run_id=%s ORDER BY product_id', (fc.RUN_ID,))
    verify_forecast_source(series, forecast_policies, runs[0], production, selections)
    policies = fc.get_rows(connection, '''SELECT sp.*,p.sku_code,p.units_per_case
        FROM sku_supply_policy sp JOIN dim_product p ON p.product_id=sp.product_id
        WHERE sp.warehouse_id=1 ORDER BY sp.product_id''')
    selected = {(s['product_id'],s['warehouse_id']):s['model_name'] for s in selections}
    for p in policies:
        p['model_name'] = selected[(p['product_id'],p['warehouse_id'])]
        require(p['data_origin']=='synthetic' and p['landed_cost_per_case_sgd'] > 0,
                'Expected synthetic policies with positive landed costs.')
    stocks = fc.get_rows(connection, '''SELECT product_id,warehouse_id,closing_units
        FROM fact_inventory WHERE scenario_id=%s AND date_id=%s ORDER BY product_id,warehouse_id''',
        (fc.SCENARIO,fc.key(AS_OF)))
    orders = fc.get_rows(connection, '''SELECT po.*,
        od.calendar_date AS order_date,ed.calendar_date AS expected_arrival_date
        FROM fact_purchase_orders po JOIN dim_date od ON od.date_id=po.order_date_id
        JOIN dim_date ed ON ed.date_id=po.expected_arrival_date_id
        WHERE po.scenario_id=%s AND po.order_status='open'
        ORDER BY po.product_id,po.warehouse_id,ed.calendar_date,po.po_line_id''', (fc.SCENARIO,))
    for po in orders:
        require(po['order_date'] <= AS_OF and po['expected_arrival_date'] > AS_OF,
                f"PO {po['po_line_id']} has a future order date or overdue ETA; confirm the ETA before planning.")
        require(po['actual_receipt_date_id'] is None and po['received_units']==0 and po['ordered_units']>0,
                'Open order status/receipt mismatch.')
        p = next((p for p in policies if (p['product_id'],p['warehouse_id']) == (po['product_id'],po['warehouse_id'])), None)
        require(p is not None and po['supplier_id']==p['supplier_id']
                and po['units_per_case_on_order']==p['units_per_case']
                and po['ordered_units']==po['quantity_cases']*po['units_per_case_on_order'],
                'Open PO does not match the one-supplier demo policy/pack conversion.')
    context = {'forecast_run_id':fc.RUN_ID,'forecast_input_sha256':runs[0]['input_sha256'],
               'review_anchor':fc.START,'policies':policies,'stocks':stocks,'open_orders':orders,
               'production_forecasts':production,'selections':selections}
    return context


def build_outputs(context):
    data = {table:[] for table in FIELDS}
    stock_map = {(s['product_id'],s['warehouse_id']):s['closing_units'] for s in context['stocks']}
    require(len(context['policies'])==6 and set(stock_map)=={(i,1) for i in range(1,7)}, 'Expected six SKU stocks/policies.')
    for p in context['policies']:
        pid,wid = p['product_id'],p['warehouse_id']
        forecasts = [f for f in context['production_forecasts'] if (f['product_id'],f['warehouse_id'])==(pid,wid)]
        demand = {datetime.strptime(str(f['target_date_id']),'%Y%m%d').date():Decimal(f['forecast_units']) for f in forecasts}
        require(len(forecasts)==HORIZON and len(demand)==HORIZON, 'Expected 84 forecasts per SKU.')
        receipts = defaultdict(lambda:ZERO)
        for po in context['open_orders']:
            if (po['product_id'],po['warehouse_id'])==(pid,wid):
                receipts[po['expected_arrival_date']] += Decimal(po['ordered_units'])
        stock = stock_map[(pid,wid)]
        recommendation = plan_sku(p,stock,demand,receipts,anchor=context['review_anchor'])
        data['fact_replenishment_recommendation'].append(recommendation)
        for stress,(factor,delay) in STRESSES.items():
            stressed_demand = {d:q(v*factor) for d,v in demand.items()}
            stressed_receipts = {d+timedelta(days=delay):v for d,v in receipts.items()}
            proposed_date = recommendation['proposed_arrival_date']
            if proposed_date is not None:
                proposed_date += timedelta(days=delay)
            both = {}
            for path in PATHS:
                units = Decimal(recommendation['recommended_units']) if path=='with_recommendation' else ZERO
                rows = project(stock,stressed_demand,stressed_receipts,proposed_date,units)
                both[path] = rows
                for r in rows:
                    data['fact_inventory_projection'].append(dict(planning_run_id=RUN_ID,product_id=pid,
                        warehouse_id=wid,stress_name=stress,plan_path=path,**r))
            base,with_plan = both['existing_only'],both['with_recommendation']
            data['replenishment_sensitivity'].append(dict(planning_run_id=RUN_ID,product_id=pid,warehouse_id=wid,
                stress_name=stress,demand_factor=factor,arrival_delay_days=delay,
                first_shortage_existing=first_shortage(base),first_shortage_with_plan=first_shortage(with_plan),
                unmet_14d_existing=unmet_through(base,AS_OF+timedelta(days=14)),
                unmet_14d_with_plan=unmet_through(with_plan,AS_OF+timedelta(days=14)),
                unmet_cycle_existing=unmet_through(base,recommendation['coverage_end_date']),
                unmet_cycle_with_plan=unmet_through(with_plan,recommendation['coverage_end_date']),
                unmet_84d_existing=unmet_through(base,AS_OF+timedelta(days=HORIZON)),
                unmet_84d_with_plan=unmet_through(with_plan,AS_OF+timedelta(days=HORIZON)),
                closing_84d_existing=base[-1]['closing_units'],closing_84d_with_plan=with_plan[-1]['closing_units'],
                committed_excess_existing=committed_excess(stock,stressed_demand,stressed_receipts,AS_OF,p['max_cover_days']),
                committed_excess_with_plan=committed_excess(stock,stressed_demand,stressed_receipts,AS_OF,p['max_cover_days'],
                    proposed_date,Decimal(recommendation['recommended_units']))))
    validate_outputs(data)
    return data


def validate_outputs(data):
    require({t:len(v) for t,v in data.items()}=={'fact_replenishment_recommendation':6,
        'fact_inventory_projection':4032,'replenishment_sensitivity':24}, 'Planner output counts differ.')
    tracks=defaultdict(list)
    for r in data['fact_inventory_projection']:
        require(all(r[f]>=0 for f in ['opening_units','existing_receipt_units','recommended_receipt_units',
                                     'demand_units','fulfilled_units','unmet_units','closing_units']), 'Negative projection.')
        require(r['opening_units']+r['existing_receipt_units']+r['recommended_receipt_units']-r['fulfilled_units']==r['closing_units'],
                'Projection stock balance error.')
        require(r['fulfilled_units']+r['unmet_units']==r['demand_units'], 'Demand balance error.')
        tracks[(r['product_id'],r['warehouse_id'],r['stress_name'],r['plan_path'])].append(r)
    require(len(tracks)==48, 'Missing/duplicate projection track.')
    for rows in tracks.values():
        require([r['projection_date'] for r in rows]==[AS_OF+timedelta(days=i) for i in range(1,HORIZON+1)], 'Projection date gap.')
        require(all(a['closing_units']==b['opening_units'] for a,b in zip(rows,rows[1:])), 'Projection continuity error.')
    for r in data['fact_replenishment_recommendation']:
        require(r['recommended_cases']==round_cases(r['net_required_units'],r['units_per_case'],r['min_order_cases'],r['order_multiple_cases']),
                'MOQ/multiple rounding error.')
        require(r['recommended_units']==r['recommended_cases']*r['units_per_case'], 'Case conversion error.')
        rows=tracks[(r['product_id'],r['warehouse_id'],'base','with_recommendation')]
        window=[p for p in rows if r['normal_arrival_date']<=p['projection_date']<=r['coverage_end_date']]
        require(all(p['unmet_units']==0 for p in window), 'Base recommendation leaves an avoidable cycle shortage.')
        require(window[-1]['closing_units']>=r['safety_target_units'], 'Safety target not met at cycle end.')
        require(unmet_through(rows,r['normal_arrival_date']-ONE_DAY)==r['unmet_before_arrival_units'],
                'Recommendation changed shortages before its arrival.')
    for r in data['replenishment_sensitivity']:
        require(r['unmet_84d_with_plan']<=r['unmet_84d_existing'], 'Adding nonnegative supply increased unmet demand.')


def save_files(data,context):
    directory=ROOT/'data'/'processed'/RUN_ID
    directory.mkdir(parents=True,exist_ok=True)
    hashes={}
    for table,fields in FIELDS.items():
        path=directory/f'{table}.csv'
        with path.open('w',encoding='utf-8',newline='') as handle:
            writer=csv.DictWriter(handle,fieldnames=fields)
            writer.writeheader(); writer.writerows(data[table])
        hashes[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    manifest={'planning_run_id':RUN_ID,'forecast_run_id':fc.RUN_ID,'scenario_id':fc.SCENARIO,
        'as_of_date':AS_OF,'horizon_days':HORIZON,'code_version':VERSION,'data_origin':'synthetic',
        'input_sha256':digest(context),'input_snapshot':context,'csv_sha256':hashes,
        'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'stress_assumptions':STRESSES,'python_version':sys.version.split()[0],
        'notes':'One proposed order per SKU, not an 84-day rolling ordering policy. Base plan frozen in stress tests. '
                'No backorders; shortages before arrival remain unmet. No PO writes. Lead times are calendar days. '
                '20% demand changes and 7-day delays are illustrative, not confidence bounds. '
                'Committed excess includes dated existing/proposed inbound within the max-cover window; '
                'it is a quantity screen, not observed physical overstock, expiry loss or measured savings.'}
    (directory/'manifest.json').write_text(json.dumps(manifest,indent=2,default=str),encoding='utf-8')
    print(f'CSV files and manifest: {directory}')
    return manifest


def load(connection,data,manifest):
    connection.commit()  # End input snapshot; do not refresh inputs concurrently.
    cursor=connection.cursor()
    try:
        connection.start_transaction()
        for table in FIELDS:
            cursor.execute(f'DELETE FROM {table} WHERE planning_run_id=%s',(RUN_ID,))
        cursor.execute('DELETE FROM planning_run WHERE planning_run_id=%s',(RUN_ID,))
        cursor.execute('''INSERT INTO planning_run
          (planning_run_id,forecast_run_id,as_of_date,horizon_days,review_anchor_date,
           code_version,input_sha256,data_origin,created_at_utc,assumptions_json)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
          (RUN_ID,fc.RUN_ID,AS_OF,HORIZON,fc.START,VERSION,manifest['input_sha256'],'synthetic',
           datetime.now(timezone.utc).replace(tzinfo=None),json.dumps(manifest,default=str)))
        for table,fields in FIELDS.items():
            statement=f"INSERT INTO {table} ({', '.join(fields)}) VALUES ({', '.join(['%s']*len(fields))})"
            rows=[tuple(r[f] for f in fields) for r in data[table]]
            for start in range(0,len(rows),1000): cursor.executemany(statement,rows[start:start+1000])
            cursor.execute(f'SELECT COUNT(*) FROM {table} WHERE planning_run_id=%s',(RUN_ID,))
            require(cursor.fetchone()[0]==len(rows),f'Database count mismatch: {table}')
        connection.commit()
    except Exception:
        connection.rollback(); raise
    finally:
        cursor.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=3306)
    parser.add_argument('--user',default='root')
    parser.add_argument('--generate-only',action='store_true',help='Read MySQL, save CSVs, skip planner database load')
    args=parser.parse_args()
    connection=mysql.connector.connect(host=args.host,port=args.port,user=args.user,
        password=getpass(f'MySQL password for {args.user}: '),database='beverage_intelligence',
        charset='utf8mb4',connection_timeout=10,autocommit=False)
    try:
        context=read_inputs(connection)
        data=build_outputs(context)
        print(f'Scenario: {fc.SCENARIO} | SYNTHETIC | As of {AS_OF}')
        for table,rows in data.items(): print(f'{table}: {len(rows)} rows')
        print('PLANNER VALIDATION OK')
        print('SKU | action | cases | proposed order | proposed arrival | first shortage with existing POs')
        for r in data['fact_replenishment_recommendation']:
            print(f"{r['product_id']} | {r['action_code']} | {r['recommended_cases']} | "
                f"{r['proposed_order_date']} | {r['proposed_arrival_date']} | {r['first_shortage_date_existing']}")
        manifest=save_files(data,context)
        if args.generate_only:
            print('GENERATE OK. Database planner tables were not changed.'); return
        load(connection,data,manifest)
        print('REPLENISHMENT PIPELINE OK')
        print('Next: run sql/09_verify_replenishment.sql in MySQL Workbench.')
    finally:
        connection.close()


if __name__=='__main__':
    try:
        main()
    except (mysql.connector.Error,ValueError,OSError) as error:
        print(f'ERROR [{type(error).__name__}]: {error}',file=sys.stderr)
        sys.exit(1)
