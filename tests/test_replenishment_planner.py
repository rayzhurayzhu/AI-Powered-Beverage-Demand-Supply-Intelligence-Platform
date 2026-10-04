"""Run from project root: python -m unittest discover -s tests -p test_replenishment_planner.py -v"""
import copy
import sys
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_replenishment_planner as m


def policy(pid=1):
    return dict(product_id=pid,warehouse_id=1,supplier_id=1,model_name='mean_28',
        units_per_case=10,lead_time_days=10,review_period_days=7,min_order_cases=2,
        order_multiple_cases=1,safety_stock_days=2,max_cover_days=60,
        landed_cost_per_case_sgd=Decimal('12.00'))


def demand(value=100):
    return {m.AS_OF+timedelta(days=i):Decimal(value) for i in range(1,85)}


class PlannerTests(unittest.TestCase):
    def test_review_schedule_and_exception_anchor(self):
        self.assertEqual(m.next_review(m.AS_OF,m.fc.START,7).isoformat(),'2026-10-05')
        self.assertEqual(m.next_review(m.AS_OF,m.AS_OF,7),m.AS_OF)
        self.assertEqual(m.next_review(m.AS_OF,m.AS_OF,7,True),m.AS_OF+timedelta(days=7))

    def test_zero_need_does_not_trigger_moq(self):
        self.assertEqual(m.round_cases(Decimal(0),24,20,10),0)
        self.assertEqual(m.round_cases(Decimal(-5),24,20,10),0)

    def test_case_rounding_and_minimum(self):
        self.assertEqual(m.round_cases(Decimal(25),12,10,4),12)
        self.assertEqual(m.round_cases(Decimal(481),24,20,10),30)
        self.assertEqual(m.round_cases(Decimal('0.0001'),24,20,10),20)

    def test_late_receipt_does_not_fix_earlier_lost_demand(self):
        d=demand()
        arrival=m.AS_OF+timedelta(days=10)
        rows=m.project(500,d,{arrival:Decimal(1000)})
        self.assertEqual(m.first_shortage(rows),m.AS_OF+timedelta(days=6))
        self.assertEqual(m.unmet_through(rows,arrival-timedelta(days=1)),Decimal(400))
        self.assertEqual(rows[9]['opening_units'],0)
        self.assertEqual(rows[9]['closing_units'],Decimal(900))
        self.assertEqual(rows[9]['unmet_units'],0)  # No 400-unit fictitious backlog.

    def test_arrival_morning_is_usable_same_day(self):
        rows=m.project(0,demand(),{m.AS_OF+timedelta(days=1):Decimal(100)})
        self.assertEqual(rows[0]['unmet_units'],0)
        self.assertEqual(rows[0]['closing_units'],0)
        self.assertNotEqual(m.first_shortage(rows),rows[0]['projection_date'])

    def test_urgent_gap_and_order_quantity_are_separate(self):
        p=policy(); p['safety_stock_days']=0
        r=m.plan_sku(p,500,demand(),{},anchor=m.AS_OF)
        self.assertEqual(r['action_code'],'EXPEDITE_REVIEW')
        self.assertEqual(r['unmet_before_arrival_units'],Decimal(400))
        self.assertEqual(r['net_required_units'],Decimal(700))
        self.assertEqual(r['recommended_cases'],70)
        self.assertLess(r['latest_normal_order_date'],m.AS_OF)

    def test_early_order_avoids_waiting_until_scheduled_review(self):
        r=m.plan_sku(policy(),1200,demand(),{},anchor=m.AS_OF-timedelta(days=2))
        self.assertEqual(r['action_code'],'ORDER_EARLY')
        self.assertEqual(r['scheduled_review_date'],m.AS_OF+timedelta(days=5))
        self.assertEqual(r['proposed_order_date'],m.AS_OF)
        self.assertEqual(r['net_required_units'],Decimal(400))
        self.assertEqual(r['unmet_before_arrival_units'],0)

    def test_scheduled_review_is_preserved_when_feasible(self):
        r=m.plan_sku(policy(),2000,demand(),{},anchor=m.AS_OF-timedelta(days=2))
        self.assertEqual(r['action_code'],'ORDER_AT_REVIEW')
        self.assertEqual(r['proposed_order_date'],m.AS_OF+timedelta(days=5))
        self.assertEqual(r['net_required_units'],Decimal(300))

    def test_receipt_after_coverage_window_does_not_offset_order(self):
        p=policy()
        plain=m.plan_sku(p,500,demand(),{},anchor=m.AS_OF)
        later=m.plan_sku(p,500,demand(),{m.AS_OF+timedelta(days=20):Decimal(9999)},anchor=m.AS_OF)
        self.assertEqual(plain['net_required_units'],later['net_required_units'])

    def test_prefix_gap_counts_even_if_later_receipt_is_large(self):
        d=demand(); arrival=m.AS_OF+timedelta(days=10)
        receipt={m.AS_OF+timedelta(days=12):Decimal(5000)}
        base=m.project(900,d,receipt)
        net,safety=m.order_requirement(900,d,receipt,base,arrival,m.AS_OF+timedelta(days=16),0)
        self.assertEqual(net,Decimal(200))
        self.assertEqual(safety,0)

    def test_excess_committed_supply_and_zero_order(self):
        r=m.plan_sku(policy(),10000,demand(),{},anchor=m.AS_OF)
        self.assertEqual(r['recommended_cases'],0)
        self.assertIsNone(r['proposed_order_date'])
        self.assertEqual(r['committed_excess_units'],Decimal(4000))
        self.assertEqual(r['action_code'],'REVIEW_EXCESS')
        self.assertEqual((r['stock_cover_days'],r['stock_cover_capped']),(Decimal(84),1))

    def test_overdue_eta_fails_closed(self):
        with self.assertRaisesRegex(ValueError,'Overdue'):
            m.plan_sku(policy(),500,demand(),{m.AS_OF:Decimal(100)},anchor=m.AS_OF)

    def test_stock_cover_fraction(self):
        self.assertEqual(m.physical_cover(250,demand()),(Decimal('2.5'),0))
        self.assertEqual(m.physical_cover(0,demand()),(Decimal(0),0))

    def test_full_shape_and_frozen_stress_plan(self):
        context={'review_anchor':m.AS_OF,'policies':[policy(i) for i in range(1,7)],
            'stocks':[dict(product_id=i,warehouse_id=1,closing_units=500) for i in range(1,7)],
            'open_orders':[],'production_forecasts':[
                dict(product_id=i,warehouse_id=1,target_date_id=m.fc.key(day),forecast_units=qty)
                for i in range(1,7) for day,qty in demand().items()]}
        data=m.build_outputs(context)
        self.assertEqual([len(v) for v in data.values()],[6,4032,24])
        self.assertEqual(data,m.build_outputs(copy.deepcopy(context)))
        rec=data['fact_replenishment_recommendation'][0]
        for stress in m.STRESSES:
            rows=[r for r in data['fact_inventory_projection'] if r['product_id']==1
                  and r['stress_name']==stress and r['plan_path']=='with_recommendation']
            self.assertEqual(sum(r['recommended_receipt_units'] for r in rows),rec['recommended_units'])
            day=next(r['projection_date'] for r in rows if r['recommended_receipt_units']>0)
            self.assertEqual(day,rec['proposed_arrival_date']+timedelta(days=m.STRESSES[stress][1]))

    def test_stale_forecast_inputs_rejected(self):
        run=dict(run_id=m.fc.RUN_ID,as_of_date=m.AS_OF,scenario_id=m.fc.SCENARIO,
                 code_version=m.fc.VERSION,horizon_days=m.HORIZON,data_origin='synthetic',input_sha256='stale')
        with self.assertRaisesRegex(ValueError,'stale'):
            m.verify_forecast_source({},[],run,[],[])

    def test_failed_database_write_rolls_back(self):
        con=MagicMock()
        con.cursor.return_value.executemany.side_effect=RuntimeError('simulated insert failure')
        data={t:[{f:0 for f in fields}] for t,fields in m.FIELDS.items()}
        with self.assertRaisesRegex(RuntimeError,'simulated'):
            m.load(con,data,{'input_sha256':'a'*64})
        con.rollback.assert_called_once()
        self.assertEqual(con.commit.call_count,1)


if __name__=='__main__':
    unittest.main()
