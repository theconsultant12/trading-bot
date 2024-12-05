import unittest
from unittest.mock import patch, MagicMock
from mainV2 import *
from interactive import *

class TestTradingBot(unittest.TestCase):

    def test_get_parameter_value(self):
        with patch('boto3.client') as mock_client:
            mock_client.return_value.get_parameter.return_value = {'Parameter': {'Value': 'test_value'}}
            self.assertEqual(get_parameter_value('test_parameter'), 'test_value')

    def test_load_logs(self):
        with patch('os.path.abspath') as mock_abspath:
            mock_abspath.return_value = '/test/path'
            with patch('os.path.exists') as mock_exists:
                mock_exists.return_value = True
                with patch('open') as mock_open:
                    mock_open.return_value.__enter__.return_value.read.return_value = 'test_logs'
                    self.assertEqual(load_logs(['test_day']), 'test_logs')

    def test_load_recent_logs(self):
        with patch('os.path.abspath') as mock_abspath:
            mock_abspath.return_value = '/test/path'
            with patch('os.path.exists') as mock_exists:
                mock_exists.return_value = True
                with patch('open') as mock_open:
                    mock_open.return_value.__enter__.return_value.readlines.return_value = ['test_log']
                    self.assertEqual(load_recent_logs(1, 1), '[test_user] test_log')

    def test_get_date_range(self):
        self.assertEqual(get_date_range('today'), [])
        self.assertEqual(get_date_range('yesterday'), ['2022-01-01'])  # assuming today is 2022-01-02
        self.assertEqual(get_date_range('week'), ['2021-12-26', '2021-12-27', '2021-12-28', '2021-12-29', '2021-12-30', '2021-12-31', '2022-01-01'])

    def test_is_trading_time(self):
        with patch('datetime.datetime') as mock_datetime:
            mock_datetime.now.return_value = datetime(2022, 1, 1, 9, 30)
            self.assertTrue(is_trading_time())

    def test_is_closing_time(self):
        with patch('datetime.datetime') as mock_datetime:
            mock_datetime.now.return_value = datetime(2022, 1, 1, 15, 30)
            self.assertTrue(is_closing_time())

    def test_auto_start_trading(self):
        with patch('threading.Thread') as mock_thread:
            auto_start_trading(1)
            mock_thread.assert_called_once()

    def test_monitor_logs_for_errors(self):
        with patch('threading.Thread') as mock_thread:
            monitor_logs_for_errors(1)
            mock_thread.assert_called_once()

    def test_monitor_trading_hours(self):
        with patch('threading.Thread') as mock_thread:
            monitor_trading_hours(1)
            mock_thread.assert_called_once()

if __name__ == '__main__':
    unittest.main()

