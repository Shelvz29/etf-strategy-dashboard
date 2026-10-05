"""Consecutive losses compound, flat resets, and re-entry is causally delayed."""
import unittest

import numpy as np
import pandas as pd

import core
import performance
from streak_research import apply_streak, candidates, dominance_flags, editor_code, holding_comparison, html_table, streak_features


class StreakResearchTests(unittest.TestCase):
    def setUp(self):
        self.index=pd.bdate_range('2020-01-01',periods=10)
        close=pd.Series([100,100,100,90,81,85,90,95,100,102],index=self.index,dtype=float)
        frame=pd.DataFrame({'open':close,'close':close,'high':close+1,'low':close-1,'volume':100.},index=self.index)
        for field in ('open','close','high','low'):frame['adj_'+field]=frame[field]
        self.frames={s:frame.copy() for s in ('SMH','SOXL','QQQ')}
        self.signals=pd.DataFrame({'symbol':'SOXL','weight':1.,'state':'NORMAL_ATTACK','reason':''},index=self.index[2:])
        self.rules=dict(symbol='SMH',recovery_symbol='SMH',mode='streak',threshold=.19,
                        ma_days=2,ma_kind='ma',window=3,recovery_kind='rising')

    def test_compound_not_sum_and_flat_or_up_reset(self):
        close=pd.Series([100,90,81,81,72.9,80],index=pd.bdate_range('2020-01-01',periods=6))
        f=streak_features(close)
        self.assertEqual(f.days.tolist(),[0,1,2,0,1,0])
        self.assertAlmostEqual(f['drop'].iloc[2],.19)
        self.assertEqual(f.start.iloc[2],close.index[1])
        self.assertAlmostEqual(f['drop'].iloc[4],.1)
        self.assertEqual(f['drop'].iloc[5],0.)

    def test_threshold_inclusive_two_down_days_and_ma_recovery(self):
        out=apply_streak(self.signals,self.frames,self.rules)
        self.assertEqual(out.symbol.iloc[1],'SOXL')
        self.assertEqual(out.symbol.iloc[2],'CASH')
        self.assertEqual(out.state.iloc[2],'STREAK_CASH_TRIGGER')
        self.assertEqual(out.symbol.iloc[3],'CASH')
        self.assertEqual(out.symbol.iloc[4],'SOXL')
        self.assertTrue(out.streak_released.iloc[4])
        looser=apply_streak(self.signals,self.frames,{**self.rules,'threshold':.05})
        self.assertEqual(looser.symbol.iloc[1],'SOXL') # single -10% isn't >=2-day run

    def test_prestart_loss_warmup_and_prefix_causality_no_mutation(self):
        original=self.signals.copy(deep=True)
        full=apply_streak(self.signals,self.frames,self.rules)
        cut=apply_streak(self.signals.iloc[:4],{s:f.iloc[:6] for s,f in self.frames.items()},self.rules)
        pd.testing.assert_frame_equal(full.iloc[:4],cut)
        late=apply_streak(self.signals.iloc[2:],self.frames,self.rules)
        self.assertEqual(late.streak_days.iloc[0],2)
        self.assertEqual(late.symbol.iloc[0],'CASH')
        pd.testing.assert_frame_equal(self.signals,original)

    def test_original_cash_priority_and_no_invisible_lock_initialization(self):
        source=self.signals.copy()
        source.loc[self.index[6],['symbol','weight','state']]=['CASH',0.,'RISK_CASH_RECOVERY']
        out=apply_streak(source,self.frames,self.rules)
        self.assertEqual(out.loc[self.index[6],'state'],'RISK_CASH_RECOVERY')
        self.assertEqual(out.loc[self.index[6],'symbol'],'CASH')
        self.assertTrue(out.loc[self.index[6],'streak_released'])
        source.loc[:,['symbol','weight','state']]=['CASH',0.,'DELEV_RECOVERY_WAIT']
        out=apply_streak(source,self.frames,self.rules)
        self.assertFalse(out.streak_locked.any())

    def test_actual_next_open_execution_not_loss_threshold_fill(self):
        source=apply_streak(self.signals,self.frames,self.rules)
        nav,trades=performance.engine.simulate(self.frames,source,start=str(self.index[3].date()),
            end=str(self.index[-1].date()),initial=100000,cost_bps=10)
        self.assertEqual(nav.loc[self.index[4],'held'],'SOXL')
        self.assertEqual(nav.loc[self.index[5],'held'],'CASH')
        self.assertEqual(nav.loc[self.index[6],'held'],'CASH')
        self.assertEqual(nav.loc[self.index[7],'held'],'SOXL')
        sale=trades[trades.side.eq('SELL')].iloc[0]
        self.assertEqual(sale.signal_date,self.index[4])
        self.assertAlmostEqual(sale.notional,100000/(90*1.001)*85,places=6)

    def test_rolling_window_includes_intervening_rebounds(self):
        frames={s:f.copy() for s,f in self.frames.items()}
        frames['SMH']['close']=pd.Series([100,100,100,90,95,85,90,95,100,102],index=self.index)
        source=self.signals.loc[self.index[5]:]
        strict=apply_streak(source,frames,{**self.rules,'threshold':.1})
        rolling=apply_streak(source,frames,{**self.rules,'mode':'window','threshold':.1,'window':3})
        self.assertEqual(strict.streak_days.iloc[0],1)
        self.assertEqual(strict.symbol.iloc[0],'SOXL')
        self.assertAlmostEqual(rolling.streak_drop.iloc[0],.15)
        self.assertEqual(rolling.symbol.iloc[0],'CASH')

    def test_rising_vs_strict_turn_and_exit_priority(self):
        frames={s:f.copy() for s,f in self.frames.items()}
        frames['SMH']['close']=pd.Series(np.arange(100.,110.),index=self.index)
        rule={**self.rules,'symbol':'SOXL','threshold':.1}
        rising=apply_streak(self.signals,frames,rule)
        turn=apply_streak(self.signals,frames,{**rule,'recovery_kind':'turn'})
        self.assertEqual(rising.symbol.iloc[2],'CASH') # MA is rising, risk wins today
        self.assertEqual(rising.symbol.iloc[3],'SOXL')
        self.assertEqual(turn.symbol.iloc[3],'CASH') # never turned from flat/down

    def test_grid_editor_source_and_boolean_formatting(self):
        grid=candidates()
        self.assertEqual(len(grid),45)
        self.assertEqual(len({c['key'] for c in grid}),45)
        profile=core.default_strategy();profile['code']=core.strategy_code(profile)
        candidate=core.make_strategy('测试连续跌幅',code=editor_code(profile,self.rules))
        self.assertEqual(candidate['state_labels']['STREAK_CASH_WAIT'],'现金等待均线向上')
        report=html_table([{'improved':False,'cagr':.12}],{'improved':'收益与回撤同时改善','cagr':'年化'})
        self.assertIn('<td>否</td>',report)
        self.assertIn('<td>12.00%</td>',report)

    def test_invalid_rules_and_missing_warmup(self):
        for override in ({'threshold':0},{'threshold':True},{'ma_days':True},{'ma_kind':'bad'},
                         {'window':1},{'mode':'bad'},{'recovery_kind':'tomorrow'}):
            with self.assertRaises(ValueError):apply_streak(self.signals,self.frames,{**self.rules,**override})
        with self.assertRaises(ValueError):apply_streak(self.signals,self.frames,{**self.rules,'ma_days':20})
        for values in ([100,0],[100,np.nan]):
            with self.assertRaises(ValueError):streak_features(pd.Series(values))

    def test_floating_point_equality_is_not_risk_improvement(self):
        baseline=pd.Series({'cagr':.65,'max_drawdown':.55})
        table=pd.DataFrame({'cagr':[.66,.66,.66],'max_drawdown':[.55,.55-1e-16,.54]})
        self.assertEqual(dominance_flags(table,baseline).tolist(),[False,False,True])

    def test_actual_extra_cash_sessions_are_not_original_cash_sessions(self):
        base=pd.DataFrame({'held':['SOXL','CASH','SMH']},index=self.index[:3])
        other=pd.DataFrame({'held':['CASH','CASH','SMH']},index=self.index[:3])
        r=holding_comparison({'baseline':base,'other':other},['other'],{'other':'测试'})[0]
        self.assertEqual(r['extra_cash_sessions'],1)
        self.assertEqual(r['different_holding_sessions'],1)
        self.assertEqual(r['extra_cash_dates'],str(self.index[0].date()))


if __name__=='__main__':unittest.main()
