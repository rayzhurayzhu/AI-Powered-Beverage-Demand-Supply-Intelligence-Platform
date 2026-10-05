"""Step 7: validated, versioned CSV snapshots for Power BI Desktop.

Reads the explicit Step 6 run. Does not write database facts or submit orders.
Requires the Step 5 and Step 6 scripts in this same scripts directory.
"""
import argparse
import csv
import hashlib
import json
import os
import sys
import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from getpass import getpass
from pathlib import Path

import mysql.connector
import run_replenishment_planner as planner

ROOT=Path(__file__).resolve().parents[1]
VERSION='bi_v1'
# Schema drives both Python validation and the Power Query type conversion.
def schema(text):
    return dict(item.split(':') for item in text.split())

SCHEMAS={
'ReportContext':schema('planning_run_id:text forecast_run_id:text scenario_id:text as_of_date:date history_start:date forecast_start:date forecast_end:date horizon_days:int backtest_days:int data_origin:text'),
'DimDate':schema('date_id:int calendar_date:date calendar_year:int calendar_quarter:int calendar_month:int year_month:text year_month_sort:int day_of_month:int day_of_week:int is_weekend:int is_sg_public_holiday:int'),
'DimProduct':schema('product_id:int sku_code:text product_name:text brand_name:text category:text container_type:text unit_volume_ml:int units_per_case:int'),
'DimChannel':schema('channel_id:int channel_code:text channel_name:text'),
'DimWarehouse':schema('warehouse_id:int warehouse_code:text warehouse_name:text country_code:text'),
'DimStress':schema('stress_name:text stress_label:text sort_order:int'),
'DimPlanPath':schema('plan_path:text plan_label:text sort_order:int'),
'FactSales':schema('date_id:int product_id:int warehouse_id:int channel_id:int units_sold:int revenue_sgd:decimal volume_litres:decimal is_promotion:int'),
'FactForecast':schema('date_id:int product_id:int warehouse_id:int model_name:text origin_date:date forecast_phase:text forecast_units:decimal actual_units:int zero_stock_flag:int'),
'FactDecision':schema('product_id:int warehouse_id:int supplier_id:int supplier_code:text model_name:text model_display_name:text on_hand_units:int open_order_units:int stock_cover_days:decimal stock_cover_capped:int first_shortage_date_existing:date latest_normal_order_date:date scheduled_review_date:date proposed_order_date:date proposed_arrival_date:date coverage_end_date:date recommended_cases:int recommended_units:int estimated_purchase_cost_sgd:decimal unmet_before_arrival_units:decimal unmet_14d_units:decimal committed_excess_units:decimal action_code:text recommended_action:text lead_time_days:int review_period_days:int safety_stock_days:int max_cover_days:int units_per_case:int min_order_cases:int order_multiple_cases:int net_required_units:decimal safety_target_units:decimal landed_cost_per_case_sgd:decimal stockout_14d_flag:int urgent_supply_flag:int excess_commitment_flag:int validation_wape_pct:decimal holdout_wape_pct:decimal holdout_bias_pct:decimal holdout_scored_days:int holdout_excluded_days:int training_imputed_days:int'),
'FactProjection':schema('date_id:int product_id:int warehouse_id:int stress_name:text plan_path:text opening_units:decimal existing_receipt_units:decimal recommended_receipt_units:decimal demand_units:decimal fulfilled_units:decimal unmet_units:decimal closing_units:decimal')}
VIEWS=dict(zip(SCHEMAS,('vw_bi_context','vw_bi_dim_date','vw_bi_dim_product','vw_bi_dim_channel',
    'vw_bi_dim_warehouse','vw_bi_dim_stress','vw_bi_dim_plan_path','vw_bi_sales',
    'vw_bi_forecast','vw_bi_decision','vw_bi_projection')))
COUNTS=dict(zip(SCHEMAS,(1,2922,6,3,1,4,2,18072,714,6,4032)))
GRAINS={
'ReportContext':['planning_run_id'],'DimDate':['date_id'],'DimProduct':['product_id'],
'DimChannel':['channel_id'],'DimWarehouse':['warehouse_id'],'DimStress':['stress_name'],
'DimPlanPath':['plan_path'],'FactSales':['date_id','product_id','warehouse_id','channel_id'],
'FactForecast':['date_id','product_id','warehouse_id'],'FactDecision':['product_id','warehouse_id'],
'FactProjection':['date_id','product_id','warehouse_id','stress_name','plan_path']}
require=planner.require
ZERO=Decimal(0)


def normalize(rows,fields):
    result=[]
    for row in rows:
        require(set(row)==set(fields),'Reporting view schema changed: rerun SQL 10 or reconcile versions.')
        clean={}
        for field,kind in fields.items():
            value=row[field]
            if value is None: clean[field]=None
            elif kind=='int':
                require(Decimal(str(value))==Decimal(int(value)),f'Noninteger value in {field}')
                clean[field]=int(value)
            elif kind=='decimal':
                value=Decimal(str(value)); require(value.is_finite(),f'Invalid number in {field}')
                clean[field]=planner.q(value)
            elif kind=='date':
                require(isinstance(value,date) and not isinstance(value,datetime),f'Expected date: {field}')
                clean[field]=value
            else: clean[field]=str(value)
        result.append(clean)
    return result


def read_dataset(connection):
    context=planner.read_inputs(connection)  # Includes a consistent snapshot and Step 5 verification.
    runs=planner.fc.get_rows(connection,'SELECT * FROM planning_run WHERE planning_run_id=%s',(planner.RUN_ID,))
    require(len(runs)==1,'Run Step 6 before exporting the report.')
    run=runs[0]
    require(run['forecast_run_id']==planner.fc.RUN_ID and run['as_of_date']==planner.AS_OF
            and run['code_version']==planner.VERSION and run['input_sha256']==planner.digest(context),
            'Planning inputs changed or run version is stale. Resolve the dependency before exporting.')
    # Verify saved planner values, not just its header fingerprint.
    expected=planner.build_outputs(context)
    for table,fields in planner.FIELDS.items():
        actual=planner.fc.get_rows(connection,f"SELECT {', '.join(fields)} FROM {table} WHERE planning_run_id=%s",(planner.RUN_ID,))
        require(Counter(tuple(r[f] for f in fields) for r in actual)==
                Counter(tuple(r[f] for f in fields) for r in expected[table]),
                f'Saved planning output differs from its verified inputs: {table}')
    dataset={}
    for name,view in VIEWS.items():
        # Identifiers are fixed allowlist entries, never user inputs.
        rows=planner.fc.get_rows(connection,f"SELECT * FROM {view} ORDER BY {', '.join(GRAINS[name])}")
        dataset[name]=normalize(rows,SCHEMAS[name])
    validate_dataset(dataset)
    return dataset,run['input_sha256']


def validate_dataset(data):
    require(set(data)==set(SCHEMAS),'Missing report table.')
    for table,rows in data.items():
        require(len(rows)==COUNTS[table],f'{table}: expected {COUNTS[table]} rows, got {len(rows)}.')
        grains=[tuple(r[k] for k in GRAINS[table]) for r in rows]
        require(len(set(grains))==len(grains) and all(None not in g for g in grains),f'Duplicate/null key: {table}')
    c=data['ReportContext'][0]
    require(c['planning_run_id']==planner.RUN_ID and c['forecast_run_id']==planner.fc.RUN_ID
            and c['scenario_id']==planner.fc.SCENARIO and c['as_of_date']==planner.AS_OF
            and c['data_origin']=='synthetic','Unexpected report scope.')
    dates={r['date_id']:r['calendar_date'] for r in data['DimDate']}
    require(len(set(dates.values()))==len(dates),'Duplicate calendar dates.')
    require(sorted(dates.values())==[date(2020,1,1)+timedelta(days=i) for i in range(2922)],'Calendar gap/range error.')
    for name in ('FactSales','FactForecast','FactDecision','FactProjection'):
        for field,dim in [('product_id','DimProduct'),('warehouse_id','DimWarehouse'),('date_id','DimDate'),
                          ('channel_id','DimChannel'),('stress_name','DimStress'),('plan_path','DimPlanPath')]:
            if field not in SCHEMAS[name]: continue
            keys={r[field] for r in data[dim]}
            require(all(r[field] in keys for r in data[name]),f'Orphan key: {name}.{field}')
    actual={}
    for r in data['FactSales']:
        require(c['history_start']<=dates[r['date_id']]<=c['as_of_date'],'Sales outside historical window.')
        k=(r['date_id'],r['product_id'],r['warehouse_id'])
        actual[k]=actual.get(k,0)+r['units_sold']
    for r in data['FactForecast']:
        require(r['forecast_units']>=0,'Negative forecast.')
        if r['forecast_phase']=='production':
            require(r['actual_units'] is None and r['zero_stock_flag'] is None,'Future actuals must be NULL.')
            require(c['forecast_start']<=dates[r['date_id']]<=c['forecast_end'],'Production date boundary error.')
        else:
            require(r['forecast_phase']=='holdout' and r['zero_stock_flag'] in (0,1),'Invalid evaluation flag.')
            require(r['actual_units']==actual[(r['date_id'],r['product_id'],r['warehouse_id'])], 'Holdout actual differs from sales.')
            require(c['as_of_date']-timedelta(days=34)<=dates[r['date_id']]<=c['as_of_date'],'Holdout date boundary error.')
    for r in data['FactDecision']:
        require(r['stockout_14d_flag']==int(r['unmet_14d_units']>0),'Stockout flag mismatch.')
        require(r['excess_commitment_flag']==int(r['committed_excess_units']>0),'Excess flag mismatch.')


def calculate_kpis(data):
    as_of=data['ReportContext'][0]['as_of_date']
    dates={r['date_id']:r['calendar_date'] for r in data['DimDate']}
    sales=[r for r in data['FactSales'] if as_of-timedelta(days=27)<=dates[r['date_id']]<=as_of]
    scored=[r for r in data['FactForecast'] if r['forecast_phase']=='holdout' and r['zero_stock_flag']==0]
    actual=sum((Decimal(r['actual_units']) for r in scored),ZERO)
    absolute=sum((abs(r['forecast_units']-r['actual_units']) for r in scored),ZERO)
    decision=data['FactDecision']
    return {
      'revenue_last_28d_sgd':sum((r['revenue_sgd'] for r in sales),ZERO).quantize(Decimal('0.01')),
      'units_last_28d':sum(r['units_sold'] for r in sales),
      'holdout_wape_ratio':absolute/actual if actual else None,
      'stockout_risk_skus_14d':sum(r['stockout_14d_flag'] for r in decision),
      'on_hand_units':sum(r['on_hand_units'] for r in decision),
      'inbound_units':sum(r['open_order_units'] for r in decision),
      'proposed_purchase_sgd':sum((r['estimated_purchase_cost_sgd'] for r in decision),ZERO).quantize(Decimal('0.01')),
      'excess_commitment_skus':sum(r['excess_commitment_flag'] for r in decision)}


def publish_snapshot(data,source_hash,root=None):
    validate_dataset(data)
    root=Path(root) if root is not None else ROOT/'data'/'powerbi'
    root.mkdir(parents=True,exist_ok=True)
    export_id=datetime.now(timezone.utc).strftime('export_%Y%m%dT%H%M%SZ_')+uuid.uuid4().hex[:8]
    folder=root/export_id
    folder.mkdir()
    entries={}
    for name,rows in data.items():
        path=folder/f'{name}.csv'
        fields=['export_id',*SCHEMAS[name]]
        with path.open('w',encoding='utf-8-sig',newline='') as handle:
            writer=csv.DictWriter(handle,fieldnames=fields)
            writer.writeheader()
            writer.writerows(dict(export_id=export_id,**r) for r in rows)
        entries[name]={'file':path.name,'rows':len(rows),'columns':SCHEMAS[name],
                       'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    kpis=calculate_kpis(data)
    manifest={'export_id':export_id,'folder':export_id,'code_version':VERSION,
        'created_at_utc':datetime.now(timezone.utc).isoformat(),'planning_input_sha256':source_hash,
        'context':data['ReportContext'][0],'tables':entries,'expected_kpis':kpis,
        'notes':'One fixed synthetic scenario. FactDecision is an as-of snapshot; do not relate it to DimDate. '
                'Forecast contains selected holdout + production only. Filter ONE stress and plan path for projections. '
                'KPI WAPE is a ratio; use percentage formatting, not another multiplication by 100.'}
    manifest_text=json.dumps(manifest,indent=2,default=str)
    (folder/'manifest.json').write_text(manifest_text,encoding='utf-8')
    (folder/'expected_kpis.json').write_text(json.dumps(kpis,indent=2,default=str),encoding='utf-8')
    # Validate every written CSV before making this export discoverable.
    for name,entry in entries.items():
        with (folder/entry['file']).open(encoding='utf-8-sig',newline='') as handle:
            reader=csv.DictReader(handle)
            require(reader.fieldnames==['export_id',*SCHEMAS[name]],f'CSV header mismatch: {name}')
            saved=list(reader)
            require(len(saved)==entry['rows'] and all(r['export_id']==export_id for r in saved),f'CSV write mismatch: {name}')
    # Immutable export directories; only the small latest pointer changes atomically.
    temp=root/f'.latest_{uuid.uuid4().hex}.json'
    temp.write_text(manifest_text,encoding='utf-8')
    os.replace(temp,root/'latest_export.json')
    return folder,kpis


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default='127.0.0.1'); parser.add_argument('--port',type=int,default=3306)
    parser.add_argument('--user',default='root')
    args=parser.parse_args()
    connection=mysql.connector.connect(host=args.host,port=args.port,user=args.user,
        password=getpass(f'MySQL password for {args.user}: '),database='beverage_intelligence',
        charset='utf8mb4',connection_timeout=10,autocommit=False)
    try:
        data,source_hash=read_dataset(connection)
        connection.commit()  # Close the read-only snapshot; no database data was changed.
        folder,kpis=publish_snapshot(data,source_hash)
        for name,rows in data.items(): print(f'{name}: {len(rows)} rows')
        print('BI EXPORT VALIDATION OK')
        print(f'Export folder: {folder}')
        print(f'Power BI pDataRoot: {folder.parent}')
        print('Executive Overview reference values:')
        for name,value in kpis.items(): print(f'{name}: {value}')
        print('POWER BI EXPORT OK')
        print('Next: follow powerbi/BUILD_REPORT.md in Power BI Desktop.')
    finally:
        connection.close()


if __name__=='__main__':
    try:
        main()
    except (mysql.connector.Error,ValueError,OSError) as error:
        print(f'ERROR [{type(error).__name__}]: {error}',file=sys.stderr)
        sys.exit(1)
