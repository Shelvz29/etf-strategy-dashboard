"""Portable checks for delayed execution and cash-only replacement."""
import copy
import unittest

import numpy as np
import pandas as pd

import cash_replacement as study


class CashReplacementTests(unittest.TestCase):
    def setUp(self):
        self.dates=study.core.calendar(2024).sessions_in_range('2024-01-02','2024-01-18')
        self.frames={}
        for i,symbol in enumerate(('SMH','SOXL','GLD')):
            opening=np.linspace(70+i*20,90+i*30,len(self.dates))
            closing=opening*(1+.025*np.sin(np.arange(len(opening))+i))
            self.frames[symbol]=pd.DataFrame({'adj_open':opening,'adj_close':closing,
                'adj_high':np.maximum(opening,closing)*1.01,'adj_low':np.minimum(opening,closing)*.99},index=self.dates)
        self.signals=pd.DataFrame({'symbol':['SMH','SMH','CASH','CASH','SOXL','SOXL','SOXL','CASH','CASH','SMH','SMH','SMH'],
            'weight':[.5,.5,0,0,.25,.5,.5,0,0,1,.5,.5],
            'state':['BASE','BASE','RISK_CASH_TRIGGER','RISK_CASH_RECOVERY','BASE','BASE','BASE',
                     'BREAK_CASH','RISK_CASH_TRIGGER','BASE','BASE','BASE']},index=self.dates)

    def test_only_cash_is_replaced_without_mutating_input(self):
        original=self.signals.copy(deep=True)
        for scope in study.SCOPES:
            candidate=study.replace(self.signals,'GLD',.5,scope)
            mask=self.signals.symbol.eq('CASH')
            if scope=='macd':mask &= self.signals.state.str.startswith('RISK_CASH_')
            pd.testing.assert_frame_equal(candidate.loc[~mask],original.loc[~mask])
            pd.testing.assert_series_equal(candidate.state,original.state)
            self.assertTrue(candidate.loc[mask,'symbol'].eq('GLD').all())
        pd.testing.assert_frame_equal(self.signals,original)

    def test_exact_ledger_matches_frozen_engine_including_delays(self):
        for scope in study.SCOPES:
            for weight in study.WEIGHTS:
                sig=study.replace(self.signals,'GLD',weight,scope)
                for cost,lag in ((0,0),(10,0),(50,1)):
                    actual=study.simulate(self.frames,sig,cost,lag)
                    expected,_=study.perf.engine.simulate(self.frames,sig,
                        start=str(sig.index[1].date()),end=str(sig.index[-1].date()),cost_bps=cost,extra_lag=lag)
                    for column in ('equity','fees','cash','open_equity'):
                        np.testing.assert_allclose(actual[column],expected[column],rtol=1e-12,atol=1e-7)
                    self.assertEqual(actual.held.tolist(),expected.held.tolist())

    def test_future_signal_and_prices_cannot_change_past_execution(self):
        original=study.simulate(self.frames,self.signals)
        changed=self.signals.copy()
        changed.iloc[8:,changed.columns.get_loc('symbol')]='GLD'
        changed.iloc[8:,changed.columns.get_loc('weight')]=1.
        frames={s:f.copy() for s,f in self.frames.items()}
        for f in frames.values():f.iloc[9:]*=4
        after=study.simulate(frames,changed)
        pd.testing.assert_frame_equal(original.iloc[:8],after.iloc[:8])

    def payload(self):
        dates=self.dates[:5]
        timestamps=(dates.tz_localize('America/New_York')+pd.Timedelta(hours=16)).tz_convert('UTC').as_unit('s').astype('int64').tolist()
        q={'open':[10.]*5,'high':[11.]*5,'low':[9.]*5,'close':[10.]*5,'volume':[100]*5}
        return {'chart':{'result':[{'meta':{'symbol':'GLD','currency':'USD','dataGranularity':'1d'},
            'timestamp':timestamps,'indicators':{'quote':[q],'adjclose':[{'adjclose':[9.]*5}]}}],'error':None}}

    def test_monthly_and_missing_sessions_are_rejected(self):
        payload=self.payload()
        parsed=study.parse('GLD',payload,'2024-01-08')
        self.assertEqual(len(parsed),5)
        self.assertAlmostEqual(parsed.adj_close.iloc[0],9.)
        monthly=copy.deepcopy(payload)
        monthly['chart']['result'][0]['meta']['dataGranularity']='1mo'
        with self.assertRaises(ValueError):study.parse('GLD',monthly,'2024-01-08')
        with self.assertRaises(ValueError):study.parse('GLD',payload,'2024-01-09')


if __name__=='__main__':unittest.main()
