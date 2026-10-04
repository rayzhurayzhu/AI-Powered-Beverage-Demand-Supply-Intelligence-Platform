"""Run: python -m unittest discover -s tests -p test_forecast_baselines.py -v"""
import copy
import sys
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import run_forecast_baselines as m


def history():
    days = (m.AS_OF - m.START).days + 1
    return [{'day': m.START + timedelta(days=i),
             'units': 100 + (m.START + timedelta(days=i)).weekday() * 10,
             'censored': 0, 'channel_count': 3,
             'inventory_sold': 100 + (m.START + timedelta(days=i)).weekday() * 10,
             'closing_units': 1000} for i in range(days)]


class ForecastTests(unittest.TestCase):
    def test_future_actuals_do_not_change_predictions(self):
        rows = history()
        origin = m.AS_OF - timedelta(days=35)
        changed = copy.deepcopy(rows)
        for r in changed:
            if r['day'] > origin:
                r['units'], r['censored'] = 999999, 1
        for model in m.MODELS:
            self.assertEqual(m.predict(rows, origin, model, 35), m.predict(changed, origin, model, 35))

    def test_weekly_signal_is_preserved(self):
        rows = history()
        for model in ('weekday_mean_56', 'seasonal_naive_7'):
            for day, forecast in m.predict(rows, m.AS_OF, model, 84):
                self.assertEqual(forecast, Decimal(100 + day.weekday() * 10))

    def test_censored_imputation_uses_only_prior_observations(self):
        rows = history()
        i = 70
        rows[i]['units'], rows[i]['censored'] = 0, 1
        # Later observed values must not change this historical imputation.
        original = dict(m.training_values(rows, m.AS_OF))[rows[i]['day']]
        for r in rows[i + 1:]:
            r['units'] = 99999
        after = dict(m.training_values(rows, m.AS_OF))[rows[i]['day']]
        self.assertEqual(original, after)
        self.assertEqual(original, Decimal(100 + rows[i]['day'].weekday() * 10))

    def test_metrics_and_bias_sign(self):
        pairs = [(100, Decimal(110), 0), (0, Decimal(50), 1)]
        available = m.metrics(pairs, True)
        self.assertEqual((available['scored_days'], available['excluded_days']), (1, 1))
        self.assertEqual(available['wape_pct'], Decimal(10))
        self.assertEqual(available['bias_pct'], Decimal(10))
        self.assertEqual(m.metrics(pairs, False)['wape_pct'], Decimal(60))
        self.assertIsNone(m.metrics([(0, Decimal(5), 0)], False)['wape_pct'])
        self.assertIsNone(m.metrics([(0, Decimal(5), 1)], True)['mae_units'])

    def test_holdout_cannot_select_model(self):
        evaluations = []
        for j, model in enumerate(m.MODELS):
            for _ in range(3):
                evaluations.append(dict(model_name=model, split_name='validation',
                    evaluation_scope='available_stock', scored_days=35,
                    actual_units=Decimal(100), absolute_error_units=Decimal(10 + 10 * j)))
            evaluations.append(dict(model_name=model, split_name='holdout',
                evaluation_scope='available_stock', scored_days=35,
                actual_units=Decimal(100), absolute_error_units=Decimal(9999 if j == 0 else 0)))
        self.assertEqual(m.choose_model(evaluations), ('mean_28', Decimal(10)))

    def test_build_counts_dates_and_repeatability(self):
        series = {(pid, 1): history() for pid in range(1, 7)}
        data = m.build_outputs(series)
        self.assertEqual({t: len(rows) for t, rows in data.items()},
            {'fact_forecast': 3024, 'forecast_evaluation': 144, 'forecast_model_selection': 6})
        prod = [r for r in data['fact_forecast'] if r['split_name'] == 'production']
        self.assertEqual(len(prod), 504)
        self.assertEqual(min(r['target_date_id'] for r in prod), 20261001)
        self.assertEqual(max(r['target_date_id'] for r in prod), 20261223)
        self.assertEqual(data, m.build_outputs(series))

    def test_missing_history_is_rejected(self):
        series = {(pid, 1): history() for pid in range(1, 7)}
        series[(1, 1)].pop(50)
        policies = [dict(product_id=pid, warehouse_id=1, lead_time_days=28,
                         review_period_days=7, max_cover_days=60) for pid in range(1, 7)]
        with self.assertRaisesRegex(ValueError, 'Missing/duplicate'):
            m.validate_inputs(series, policies)

    def test_failed_insert_rolls_back(self):
        connection = MagicMock()
        connection.cursor.return_value.executemany.side_effect = RuntimeError('simulated insert failure')
        data = {t: [{f: 0 for f in fields}] for t, fields in m.FIELDS.items()}
        with self.assertRaisesRegex(RuntimeError, 'simulated'):
            m.load(connection, data, {'input_sha256': 'a' * 64})
        connection.rollback.assert_called_once()
        # The only commit closes the input-read transaction; the refresh was not committed.
        self.assertEqual(connection.commit.call_count, 1)


if __name__ == '__main__':
    unittest.main()
