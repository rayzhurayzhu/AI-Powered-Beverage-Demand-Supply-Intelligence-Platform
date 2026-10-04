"""Offline checks. Fixtures below are test inputs, never business data."""
import importlib.util
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'holiday_pipeline.py'
spec = importlib.util.spec_from_file_location('holiday_pipeline', SCRIPT)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = patch.object(pipeline, 'ROOT', Path(self.temp.name))
        root.start()
        self.addCleanup(root.stop)
        self.when = datetime(2026, 10, 4, tzinfo=timezone.utc)
        self.fixture = [{'date': '2026-01-01', 'holiday': 'Test Holiday'}]

    def test_same_date_different_holidays_are_preserved(self):
        rows = pipeline.clean_holidays(self.fixture + [
            {'date': '2026-01-01', 'holiday': 'Second Test Holiday'}
        ], self.when)
        self.assertEqual(len(rows), 2)

    def test_exact_duplicate_is_removed(self):
        rows = pipeline.clean_holidays(self.fixture * 2, self.when)
        self.assertEqual(len(rows), 1)

    def test_invalid_date_and_empty_source_fail(self):
        for records in [[], [{'date': '2026-02-30', 'holiday': 'Test'}]]:
            with self.assertRaises(ValueError):
                pipeline.clean_holidays(records, self.when)

    def test_two_pages_are_read(self):
        first = {'_id': 1, **self.fixture[0]}
        second = {'_id': 2, 'date': '2026-01-02', 'holiday': 'Test 2'}
        responses = []
        for record in [first, second]:
            response = MagicMock()
            response.json.return_value = {
                'success': True, 'result': {'records': [record], 'total': 2}
            }
            responses.append(response)
        with patch.object(pipeline.requests, 'Session') as factory:
            session = factory.return_value.__enter__.return_value
            session.get.side_effect = responses
            rows, _ = pipeline.fetch_holidays()
        self.assertEqual(len(rows), 2)
        offsets = [call.kwargs['params']['offset'] for call in session.get.call_args_list]
        self.assertEqual(offsets, [0, 1])

    def test_incomplete_pagination_fails(self):
        response = MagicMock()
        response.json.return_value = {
            'success': True, 'result': {'records': [], 'total': 2}
        }
        with patch.object(pipeline.requests, 'Session') as factory:
            factory.return_value.__enter__.return_value.get.return_value = response
            with self.assertRaises(ValueError):
                pipeline.fetch_holidays()

    def test_insert_failure_rolls_back_refresh(self):
        rows = pipeline.clean_holidays(self.fixture, self.when)
        connection = MagicMock()
        cursor = connection.cursor.return_value
        cursor.executemany.side_effect = pipeline.mysql.connector.Error('Test failure')
        with patch.object(pipeline, 'getpass', return_value='test'), \
             patch.object(pipeline.mysql.connector, 'connect', return_value=connection):
            with self.assertRaises(pipeline.mysql.connector.Error):
                pipeline.load_and_analyse(rows, '127.0.0.1', 3306, 'test')
        connection.rollback.assert_called_once()
        # Only the schema setup commit occurred, not a data refresh commit.
        self.assertEqual(connection.commit.call_count, 1)
        connection.close.assert_called_once()

    def test_success_checks_count_and_exports_sql_result(self):
        rows = pipeline.clean_holidays(self.fixture, self.when)
        connection = MagicMock()
        cursor = connection.cursor.return_value
        cursor.fetchone.return_value = (1,)
        cursor.fetchall.return_value = [(2026, 1, 1)]
        cursor.description = [('calendar_year',), ('holiday_records',), ('holiday_dates',)]
        with patch.object(pipeline, 'getpass', return_value='test'), \
             patch.object(pipeline.mysql.connector, 'connect', return_value=connection):
            pipeline.load_and_analyse(rows, '127.0.0.1', 3306, 'test')
        self.assertEqual(connection.commit.call_count, 2)
        connection.rollback.assert_not_called()
        self.assertTrue((pipeline.ROOT / 'outputs' / 'holiday_summary.csv').exists())


if __name__ == '__main__':
    unittest.main()
