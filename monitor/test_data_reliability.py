"""Connection recovery and product identity checks without live providers."""
import unittest
from unittest.mock import Mock, patch

import pandas as pd
import requests

import core
import market_factors
import performance
import product_catalog


class ReliabilityTests(unittest.TestCase):
    def response(self, symbol='QQQ'):
        response = Mock()
        response.json.return_value = {'chart': {'result': [{'meta': {'symbol': symbol}}]}}
        return response

    def test_recovers_after_both_hosts_fail_once(self):
        with patch.object(core.requests, 'get', side_effect=[requests.ReadTimeout(), requests.ConnectionError(), self.response()]) as get:
            result = core.request_json('QQQ', {'range': '1mo'})
        self.assertEqual(result['chart']['result'][0]['meta']['symbol'], 'QQQ')
        self.assertEqual(get.call_count, 3)
        self.assertIn('query2', get.call_args_list[0].args[0])
        self.assertIn('query1', get.call_args_list[1].args[0])

    def test_failure_is_bounded_and_redacts_private_details(self):
        with patch.object(core.requests, 'get', side_effect=requests.ReadTimeout('secret credential URL')) as get:
            with self.assertRaises(core.MarketDataUnavailable) as error:
                core.request_json('SMH', {})
        self.assertEqual(get.call_count, 4)
        self.assertIn('SMH 行情连接失败', str(error.exception))
        self.assertIn('ReadTimeout', str(error.exception))
        self.assertNotIn('secret', str(error.exception))

    def test_wrong_product_cannot_pass_as_valid(self):
        with patch.object(core.requests, 'get', return_value=self.response('SPY')) as get:
            with self.assertRaises(core.MarketDataUnavailable):
                core.request_json('SMH', {})
        self.assertEqual(get.call_count, 4)

    def test_blank_names_filled_without_overwriting_user_status(self):
        saved = {'SMH': {'name': '', 'status': '未确认'}, 'QQQ': {'name': '本人产品名称', 'status': '没有对应产品 / 暂不可交易'}}
        with patch.object(core, 'get', return_value=saved):
            result = core.product_mappings()
        self.assertEqual(result['SMH']['name'], 'VanEck Semiconductor ETF')
        self.assertEqual(result['SMH']['status'], '未确认')
        self.assertEqual(result['QQQ'], saved['QQQ'])
        self.assertIn('invesco.com', product_catalog.CATALOG['RSP'][1])

    def test_confirmed_price_reuse_preserves_provenance(self):
        at = pd.Timestamp('2026-10-05T02:00Z')
        snap = {'source': 'Yahoo 公开日线', 'last': {'date': '2026-10-02'}, 'fetched': '2026-10-02T22:00Z'}
        frame = pd.DataFrame({'adjclose': [100., 101.]}, index=pd.to_datetime(['2026-10-01', '2026-10-02']))
        with patch.object(performance, 'confirmed_inputs', return_value=(snap, {'SMH': {}})), patch.object(performance, 'parse_price', return_value=frame), patch.object(core, 'request_json') as request:
            result = market_factors.fetch_prices('SMH', at)
        request.assert_not_called()
        self.assertTrue(result['cache_reused'])
        self.assertEqual(result['price_fetched'], snap['fetched'])
        self.assertEqual(result['observations'][-1]['date'], '2026-10-02')

    def test_old_or_invalid_confirmed_data_cannot_replace_download(self):
        snap = {'source': 'Yahoo 公开日线', 'last': {'date': '2026-10-01'}, 'fetched': '2026-10-01T22:00Z'}
        with patch.object(performance, 'confirmed_inputs', return_value=(snap, {'SMH': {}})), patch.object(core, 'request_json', side_effect=RuntimeError('download required')) as fetch:
            with self.assertRaises(RuntimeError):
                market_factors.fetch_prices('SMH', pd.Timestamp('2026-10-05T02:00Z'))
        fetch.assert_called_once()
        snap['last']['date'] = '2026-10-02'
        with patch.object(performance, 'confirmed_inputs', return_value=(snap, {'SMH': {}})), patch.object(performance, 'parse_price', side_effect=ValueError('missing session')), patch.object(core, 'request_json', side_effect=RuntimeError('download required')) as fetch:
            with self.assertRaises(RuntimeError):
                market_factors.fetch_prices('SMH', pd.Timestamp('2026-10-05T02:00Z'))
        fetch.assert_called_once()


if __name__ == '__main__':
    unittest.main()
