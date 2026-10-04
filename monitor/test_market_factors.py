"""Portable checks for observation factors and their data boundaries."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import core
import market_factors as factors


class FactorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.db=patch.object(core,'DB',self.root/'monitor.db');self.runtime=patch.object(core,'RUNTIME',self.root)
        self.db.start();self.runtime.start();core.init_db()
        self.at=pd.Timestamp('2026-10-04T04:00:00Z');self.cutoff='2026-10-02'
        self.index=core.calendar(2026).sessions_in_range('2025-06-01',self.cutoff)
        self.cache={}
        for symbol in factors.SYMBOLS:
            self.cache[symbol]={'fetched':self.at.isoformat(),'observations':[
                {'date':str(d.date()),'price':100.} for d in self.index],'last_error':None}
        self.cache['OFR']={'fetched':self.at.isoformat(),'observations':[
            {'date':str(d.date()),'credit':-1.,'funding':-.5,'fsi':-2.} for d in self.index],'last_error':None}

    def tearDown(self):
        self.db.stop();self.runtime.stop();self.temp.cleanup()

    def assess(self,manual=None):
        return factors.assess(self.cache,manual or {},self.cutoff,{'yield10':4.},self.at)

    def test_baseline_missing_fundamentals_are_unknown(self):
        rows=self.assess()
        self.assertEqual([r['level'] for r in rows],[None,0,None,0,0,0])
        self.assertTrue(all(r['impact'] and r['rule'] and r['limitations'] for r in rows))

    def test_thresholds_and_linked_concentration(self):
        self.cache['RSP']['observations'][-1]['price']=96.
        self.cache['SMH']['observations'][-1]['price']=109.
        for symbol in factors.LEADERS:self.cache[symbol]['observations'][-1]['price']=91.
        # Last two days are not yet eligible for conservative OFR assessment.
        for row in self.cache['OFR']['observations'][-3:]:row.update(credit=1.,funding=.5)
        manual={'valuation':{'date':self.cutoff,'values':{'pe':25.},'scope':'S&P500','source':factors.FACTSET},
            'earnings':{'date':self.cutoff,'values':{'revision1':-2.,'revision3':-5.},'scope':'S&P500 FY2027','source':factors.FACTSET}}
        self.assertEqual([r['level'] for r in self.assess(manual)],[2,2,2,2,2,2])

    def test_cutoff_rejects_future_manual_and_ignores_future_price(self):
        before=self.assess()
        self.cache['RSP']['observations'].append({'date':'2026-10-05','price':1.})
        self.cache['OFR']['observations'].append({'date':'2026-10-05','credit':100.,'funding':100.,'fsi':100.})
        manual={'valuation':{'date':'2026-10-05','values':{'pe':30.},'scope':'S&P500','source':factors.FACTSET}}
        self.assertEqual(before,self.assess(manual))

    def test_missing_sessions_and_stale_cache_do_not_signal_clear(self):
        self.cache['RSP']['observations'].pop(-15)
        self.cache['OFR']['fetched']='2026-09-01T00:00:00Z'
        self.cache['AMD']['observations'].pop()
        rows=self.assess();self.assertIsNone(rows[1]['level']);self.assertIsNone(rows[3]['level'])
        self.assertIsNone(rows[4]['level']);self.assertIsNone(rows[5]['level'])

    def test_refresh_preserves_failed_source_and_targets(self):
        core.put('factor_sources',self.cache);before=core.active_strategy()['fingerprint']
        def fetch(symbol,at):
            if symbol=='RSP':raise ConnectionError('private URL secret')
            return copy.deepcopy(self.cache[symbol])
        with patch.object(factors,'fetch_prices',side_effect=fetch),patch.object(factors,'fetch_ofr',return_value=self.cache['OFR']):
            new=factors.refresh(force=True,at=self.at+pd.Timedelta(minutes=2))
        self.assertEqual(new['RSP']['observations'],self.cache['RSP']['observations'])
        self.assertEqual(new['RSP']['fetched'],self.cache['RSP']['fetched'])
        self.assertIn('ConnectionError',new['RSP']['last_error']);self.assertNotIn('secret',new['RSP']['last_error'])
        with patch.object(factors,'fetch_prices') as fetch,patch.object(factors,'fetch_ofr') as ofr:
            factors.refresh(force=True,at=self.at+pd.Timedelta(minutes=2,seconds=30));fetch.assert_not_called();ofr.assert_not_called()
        self.assertEqual(before,core.active_strategy()['fingerprint']);self.assertIsNone(core.get('snapshot'))

    def test_manual_validation_persistence_and_expiry(self):
        before=core.active_strategy()['fingerprint']
        for date,url,scope,value in [('2026-10-05',factors.FACTSET,'S&P500',25.),
                (self.cutoff,'javascript:alert(1)','S&P500',25.),(self.cutoff,factors.FACTSET,'',25.),
                (self.cutoff,factors.FACTSET,'S&P500',float('nan'))]:
            with self.assertRaises(ValueError):factors.save_manual('valuation',{'pe':value},date,url,scope,self.at)
        factors.save_manual('valuation',{'pe':22.},self.cutoff,factors.FACTSET,'S&P500',self.at)
        record=core.get('factor_manual_valuation');self.assertEqual(self.assess({'valuation':record})[0]['level'],1)
        record['date']='2026-08-01';self.assertIsNone(self.assess({'valuation':record})[0]['level'])
        self.assertEqual(before,core.active_strategy()['fingerprint'])

    def test_ofr_publication_lag(self):
        for row in self.cache['OFR']['observations'][-2:]:row.update(credit=100.,funding=100.)
        rows=self.assess();self.assertEqual(rows[3]['level'],0);self.assertEqual(rows[4]['level'],0)
        self.assertEqual(rows[3]['date'],'2026-09-30')

    def test_independent_service_refresh_after_macro_failure(self):
        import service
        core.put('snapshot',{'last':{'date':self.cutoff},'source':'Yahoo 公开日线'})
        with patch('sys.argv',['service','--once']),patch.object(core,'bootstrap'),patch.object(core,'record_failure'),patch.object(core,'refresh_full',side_effect=RuntimeError('unavailable')),patch.object(service.macro_sources,'refresh',side_effect=RuntimeError('unavailable')),patch.object(factors,'refresh',return_value={}) as refresh:
            service.main()
        refresh.assert_called_once_with(force=True)

    def test_streamlit_cards_manual_save_and_html_escaping(self):
        from streamlit.testing.v1 import AppTest
        self.cache['RSP']['last_error']='RSP更新失败：ConnectionError'
        core.put('factor_sources',self.cache);before=core.active_strategy()['fingerprint']
        app="import market_factors\nmarket_factors.render('2026-10-02')"
        with patch.object(core,'now_utc',return_value=self.at.to_pydatetime()):
            page=AppTest.from_string(app).run();self.assertEqual(len(page.exception),0)
            self.assertEqual(len(page.date_input),2);self.assertEqual(len(page.number_input),3)
            page.date_input[0].set_value(pd.Timestamp(self.cutoff).date())
            page.text_input[0].set_value('<script>bad</script>');page.number_input[0].set_value(25.)
            page.button[0].click().run();self.assertEqual(len(page.exception),0)
        self.assertEqual(core.get('factor_manual_valuation')['values']['pe'],25.)
        markup=''.join(r.value for r in page.markdown if 'macro-card' in r.value)
        self.assertIn('macro-card',markup);self.assertNotIn('<script>bad</script>',markup)
        self.assertIn('更新失败，沿用旧缓存',markup);self.assertIn('&lt;script&gt;bad&lt;/script&gt;',markup)
        from macro_ui import card
        self.assertIn('&lt;script&gt;bad&lt;/script&gt;',card('title','value','badge','clear',extra='<script>bad</script>'))
        self.assertEqual(before,core.active_strategy()['fingerprint'])


if __name__=='__main__':unittest.main()
