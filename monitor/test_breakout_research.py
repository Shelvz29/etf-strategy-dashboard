"""Cash lock boundaries, causality, underlying priority and delayed execution."""
import unittest

import numpy as np
import pandas as pd

import core
import performance
from breakout_research import apply_breakout, candidates, editor_code


class BreakoutTests(unittest.TestCase):
    def setUp(self):
        self.index=pd.bdate_range('2020-01-01',periods=10)
        c=pd.Series([100,100,100,99,97,100,102,100,103,100],index=self.index,dtype=float)
        p=pd.DataFrame({'open':c,'close':c,'high':c+1,'low':c-1,'volume':100},index=self.index)
        for field in ('open','close','high','low'):p['adj_'+field]=p[field]
        self.frames={'SMH':p,'SOXL':p.copy(),'QQQ':p.copy()}
        self.source=pd.DataFrame({'symbol':'SOXL','weight':1.,'state':'NORMAL_ATTACK','reason':''},index=self.index[2:])
        self.rules=dict(symbol='SMH',kind='channel',sell_days=2,buy_days=2,buffer=0.,sell_mode='close')

    def test_strict_boundary_lock_and_breakout(self):
        original=self.source.copy(deep=True)
        out=apply_breakout(self.source,self.frames,self.rules)
        self.assertEqual(out.symbol.iloc[1],'SOXL') # exactly lower at 99
        self.assertEqual(out.symbol.iloc[2],'CASH')
        self.assertEqual(out.state.iloc[2],'BREAKOUT_CASH_BREAK')
        self.assertEqual(out.symbol.iloc[3],'CASH') # exactly upper at 100
        self.assertEqual(out.symbol.iloc[4],'SOXL')
        self.assertTrue(out.breakout_released.iloc[4])
        pd.testing.assert_frame_equal(self.source,original)

    def test_underlying_cash_has_priority_and_initialization(self):
        source=self.source.copy()
        source.loc[self.index[6],['symbol','weight','state']]=['CASH',0.,'RISK_CASH_RECOVERY']
        out=apply_breakout(source,self.frames,self.rules)
        self.assertEqual(out.loc[self.index[6],'state'],'RISK_CASH_RECOVERY')
        self.assertEqual(out.loc[self.index[6],'symbol'],'CASH')
        self.assertTrue(out.loc[self.index[6],'breakout_released'])
        source.loc[:,['symbol','weight','state']]=['CASH',0.,'DELEV_RECOVERY_WAIT']
        cash=apply_breakout(source,self.frames,self.rules)
        self.assertFalse(cash.breakout_locked.any())
        self.assertTrue(cash.symbol.eq('CASH').all())

    def test_full_history_prefix_causality_and_excludes_current_extremes(self):
        full=apply_breakout(self.source,self.frames,self.rules)
        truncated={s:f.iloc[:6] for s,f in self.frames.items()}
        part=apply_breakout(self.source.iloc[:4],truncated,self.rules)
        pd.testing.assert_frame_equal(full.iloc[:4],part)
        changed={s:f.copy() for s,f in self.frames.items()}
        changed['SMH'].loc[self.index[4],'low']=1.
        changed['SMH'].loc[self.index[4],'high']=10000.
        alternative=apply_breakout(self.source,changed,self.rules)
        self.assertEqual(alternative.breakout_lower.iloc[2],full.breakout_lower.iloc[2])
        self.assertEqual(alternative.breakout_upper.iloc[2],full.breakout_upper.iloc[2])

    def test_low_touch_still_executes_next_open_at_actual_gap(self):
        out=apply_breakout(self.source,self.frames,self.rules)
        nav,trades=performance.engine.simulate(self.frames,out,start=str(self.index[3].date()),
            end=str(self.index[-1].date()),cost_bps=10.,initial=100000)
        self.assertEqual(nav.loc[self.index[4],'held'],'SOXL')
        self.assertEqual(nav.loc[self.index[5],'held'],'CASH')
        sale=trades[trades.side.eq('SELL')].iloc[0]
        self.assertEqual(sale.date,self.index[5])
        self.assertEqual(sale.signal_date,self.index[4])
        # Original source target buys at 99 on day3, exits at real day5 open=100.
        units=100000/(99*1.001)
        self.assertAlmostEqual(float(sale.notional),units*100,places=6)
        rules={**self.rules,'sell_mode':'low'}
        touch=apply_breakout(self.source,self.frames,rules)
        self.assertEqual(touch.symbol.iloc[1],'CASH')

    def test_buffer_and_ma_variants(self):
        for kind in ('channel','ma','ema'):
            out=apply_breakout(self.source,self.frames,{**self.rules,'kind':kind,'buffer':.01})
            self.assertTrue(np.isfinite(out.breakout_lower).all())
            self.assertTrue(out.loc[out.symbol.eq('CASH'),'weight'].eq(0).all())
        labels=[c['key'] for c in candidates()]
        self.assertEqual(len(labels),19)
        self.assertEqual(len(labels),len(set(labels)))

    def test_editor_copy_has_literal_states_and_no_private_source_in_module(self):
        profile=core.default_strategy()
        profile['code']=core.strategy_code(profile)
        profile['state_labels']={};profile['state_notes']={}
        candidate=core.make_strategy('测试突破',code=editor_code(profile,self.rules))
        self.assertEqual(candidate['state_labels']['BREAKOUT_CASH_BREAK'],'跌破位现金避险')
        self.assertIn('次日开盘',candidate['state_notes']['BREAKOUT_CASH_WAIT'])

    def test_invalid_rules_or_missing_warmup(self):
        for changes in ({'sell_days':1},{'buy_days':True},{'buffer':.2},{'kind':'bad'},{'sell_mode':'intraday'}):
            with self.assertRaises(ValueError):apply_breakout(self.source,self.frames,{**self.rules,**changes})
        with self.assertRaises(ValueError):apply_breakout(self.source,self.frames,{**self.rules,'sell_days':20})


if __name__=='__main__':unittest.main()
