"""Run: python -m unittest discover -s tests -p test_bi_export.py -v"""
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import export_powerbi_snapshot as m


def dataset():
    return {
      'ReportContext':[{'as_of_date':date(2026,9,30)}],
      'DimDate':[{'date_id':20260902,'calendar_date':date(2026,9,2)},
                 {'date_id':20260903,'calendar_date':date(2026,9,3)},
                 {'date_id':20260930,'calendar_date':date(2026,9,30)}],
      'FactSales':[{'date_id':20260902,'revenue_sgd':Decimal(999),'units_sold':999},
                   {'date_id':20260903,'revenue_sgd':Decimal('10.20'),'units_sold':10},
                   {'date_id':20260930,'revenue_sgd':Decimal('20.30'),'units_sold':20}],
      'FactForecast':[
          {'forecast_phase':'holdout','zero_stock_flag':0,'actual_units':10,'forecast_units':Decimal(20)},
          {'forecast_phase':'holdout','zero_stock_flag':0,'actual_units':90,'forecast_units':Decimal(90)},
          {'forecast_phase':'holdout','zero_stock_flag':1,'actual_units':0,'forecast_units':Decimal(100)},
          {'forecast_phase':'production','zero_stock_flag':None,'actual_units':None,'forecast_units':Decimal(1000)}],
      'FactDecision':[{'stockout_14d_flag':1,'on_hand_units':10,'open_order_units':20,
                       'estimated_purchase_cost_sgd':Decimal('30.00'),'excess_commitment_flag':0}]}


class ReportTests(unittest.TestCase):
    def test_pooled_wape_not_mean_of_sku_percentages(self):
        values=m.calculate_kpis(dataset())
        self.assertEqual(values['holdout_wape_ratio'],Decimal('0.1'))
        self.assertNotEqual(values['holdout_wape_ratio'],Decimal('0.5'))

    def test_censored_and_future_rows_are_excluded_from_score(self):
        data=dataset()
        data['FactForecast'][2]['forecast_units']=Decimal(999999)
        data['FactForecast'][3]['forecast_units']=Decimal(999999)
        self.assertEqual(m.calculate_kpis(data)['holdout_wape_ratio'],Decimal('0.1'))

    def test_fixed_28_day_window_includes_both_boundaries(self):
        values=m.calculate_kpis(dataset())
        self.assertEqual(values['revenue_last_28d_sgd'],Decimal('30.50'))
        self.assertEqual(values['units_last_28d'],30)

    def test_zero_denominator_is_not_zero_error(self):
        data=dataset()
        for r in data['FactForecast']:
            if r['forecast_phase']=='holdout' and r['zero_stock_flag']==0:r['actual_units']=0
        self.assertIsNone(m.calculate_kpis(data)['holdout_wape_ratio'])

    def test_future_nulls_and_expected_decimal_units_survive_normalization(self):
        row=dict(date_id=20261001,product_id=1,warehouse_id=1,model_name='mean_28',
                 origin_date=date(2026,9,30),forecast_phase='production',
                 forecast_units=Decimal('125.0625'),actual_units=None,zero_stock_flag=None)
        actual=m.normalize([row],m.SCHEMAS['FactForecast'])[0]
        self.assertIsNone(actual['actual_units'])
        self.assertIsNone(actual['zero_stock_flag'])
        self.assertEqual(actual['forecast_units'],Decimal('125.0625'))

    def test_schema_drift_rejected(self):
        with self.assertRaisesRegex(ValueError,'schema changed'):
            m.normalize([{'unexpected_column':1}],m.SCHEMAS['DimProduct'])


if __name__=='__main__':
    unittest.main()
