"""The saved editor strategy must reproduce the researched overlay and ledger."""
from pathlib import Path
import importlib.util
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
import core
import code_strategy as cs
import performance as perf
import strategy_states

PROJECT=Path(__file__).resolve().parent.parent
CODE=PROJECT/'monitor'/'strategies'/'MACD＋4%急跌避险策略.py'
NAME='MACD＋4%急跌避险策略'


class MacdRiskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code=CODE.read_text(encoding='utf-8')
        cls.profile=core.make_strategy(NAME,code=cls.code)
        data=PROJECT/'backtests'/'2026-10-03-smh-soxl-risk'/'data'
        cls.frames={s:pd.read_csv(data/(s+'.csv'),index_col=0,parse_dates=True) for s in ('SMH','SOXL','QQQ')}
        cls.actual=core.replay(cls.frames,cls.profile,audit_code=True)
        cls.expected=pd.read_csv(PROJECT/'backtests'/'2026-10-03-smh-soxl-combinations'/'signals_macd_drop4.csv',index_col=0,parse_dates=True)
        spec=importlib.util.spec_from_file_location('standalone_macd_risk',CODE)
        cls.module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=cls.module;spec.loader.exec_module(cls.module)

    def synthetic(self,n=12):
        dates=pd.bdate_range('2020-01-01',periods=n)
        base=pd.DataFrame({'symbol':'SOXL','weight':.99,'state':'NORMAL_ATTACK','reason':''},index=dates)
        hist=pd.Series(1.,index=dates);drop=pd.Series(0.,index=dates);healthy=pd.Series(True,index=dates)
        return base,hist,drop,healthy

    def test_every_historical_target_matches_research(self):
        np.testing.assert_array_equal(self.actual.symbol,self.expected.symbol)
        np.testing.assert_allclose(self.actual.weight,self.expected.weight.mask(self.expected.weight.eq(.99),1.))
        mask=self.expected.state.eq('EXPERIMENT_MACD_DROP4')
        self.assertTrue(self.actual.loc[mask,'state'].str.startswith('RISK_CASH_').all())
        # A locked day whose underlying target is already CASH has unchanged
        # position but now explicitly explains the still-active risk lock.
        unlocked=~self.actual.state.str.startswith('RISK_CASH_')
        np.testing.assert_array_equal(self.actual.loc[unlocked,'state'],self.expected.loc[unlocked,'state'])

    def test_every_equity_row_matches_prior_backtest(self):
        # Keep the immutable 99% research ledger audit separate from new targets.
        legacy=self.actual.copy();legacy['weight']=legacy.weight.mask(legacy.symbol.eq('SOXL')&legacy.weight.eq(1.),.99)
        nav,_=perf.engine.simulate(self.frames,legacy,start='2017-01-03',end='2026-10-02',cost_bps=15.)
        expected=pd.read_csv(PROJECT/'backtests'/'2026-10-03-smh-soxl-combinations'/'curve_macd_drop4.csv',index_col=0)
        np.testing.assert_allclose(nav.equity,expected.equity,rtol=1e-11)

    def test_requires_both_negative_macd_and_four_percent_drop(self):
        base,hist,drop,healthy=self.synthetic()
        drop.iloc[0]=.05;hist.iloc[1]=-1;drop.iloc[1]=.039
        hist.iloc[2]=-1;drop.iloc[2]=.04;healthy.iloc[2]=False
        out=self.module.apply_cash_risk(base,hist,drop,healthy)
        self.assertEqual(out.symbol.iloc[:2].tolist(),['SOXL','SOXL'])
        self.assertEqual(out.state.iloc[2],'RISK_CASH_TRIGGER')
        self.assertTrue(out.symbol.iloc[2:7].eq('CASH').all())
        self.assertEqual(out.symbol.iloc[7],'SOXL')

    def test_repeat_trigger_restarts_wait_and_recovery_restores_today_base(self):
        base,hist,drop,healthy=self.synthetic(15)
        hist.iloc[[1,4]]=-1;drop.iloc[[1,4]]=.05;healthy.iloc[[1,4]]=False
        healthy.iloc[9:11]=False
        base.loc[base.index[11]:,['symbol','weight','state']]=['SMH',.5,'NORMAL_DEFENSE']
        out=self.module.apply_cash_risk(base,hist,drop,healthy)
        self.assertEqual(out.state.iloc[4],'RISK_CASH_TRIGGER')
        self.assertEqual(out.state.iloc[9],'RISK_CASH_RECOVERY')
        self.assertTrue(out.symbol.iloc[1:11].eq('CASH').all())
        self.assertEqual(out.symbol.iloc[11],'SMH')
        self.assertEqual(out.weight.iloc[11],.5)

    def test_underlying_cash_does_not_start_an_unnecessary_lock(self):
        base,hist,drop,healthy=self.synthetic()
        base.loc[base.index[0],['symbol','weight','state']]=['CASH',0.,'BREAK_CASH']
        hist.iloc[0]=-1;drop.iloc[0]=.06;healthy.iloc[0]=False
        out=self.module.apply_cash_risk(base,hist,drop,healthy)
        self.assertEqual(out.state.iloc[0],'BREAK_CASH')
        self.assertEqual(out.symbol.iloc[1],'SOXL')

    def test_custom_states_explain_all_outputs(self):
        states=strategy_states.definitions(self.profile,self.actual.state.unique())
        self.assertEqual(len(states),11)
        self.assertEqual(set(self.actual.state)-{x['code'] for x in states},set())
        self.assertTrue(all(x['note'] for x in states))
        self.assertEqual(cs.check_source(self.code)['BASE_SYMBOL'],'SMH')

    def test_save_adds_version_without_changing_active_snapshot(self):
        snap,bundle=perf.confirmed_inputs()
        resolved=core.ensure_strategy_bundle(bundle,snap['last']['date'],self.profile)
        with tempfile.TemporaryDirectory() as work:
            with patch.object(core,'DB',Path(work)/'monitor.db'),patch.object(core,'RUNTIME',Path(work)):
                core.init_db()
                # The default snapshot needs XSD; preserve the actual bundle and
                # use the existing confirmed snapshot as a read-only fixture.
                core.put('snapshot',snap);core.put('confirmed_bundle',resolved)
                before=core.get('snapshot');active=core.active_strategy()
                saved=core.save_strategy(NAME,code=self.code)
                self.assertEqual(saved['revision'],1)
                self.assertEqual(core.get('snapshot'),before)
                self.assertEqual(core.active_strategy()['fingerprint'],active['fingerprint'])
                self.assertEqual(core.strategy_version(saved['id'])['code_hash'],cs.code_hash(self.code))
                self.assertEqual(len(core.strategy_history(saved['id'])),1)


if __name__=='__main__':unittest.main()
