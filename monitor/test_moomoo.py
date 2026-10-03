"""Original daily decisions vs adapters, multi-asset accounting and metadata."""
from pathlib import Path
from types import SimpleNamespace, MethodType
import unittest

import numpy as np
import pandas as pd

import code_strategy as cs
import core
import portfolio
import strategy_runner

ROOT = Path(__file__).resolve().parent
VARIANTS = [('QQQ和TQQQ双核策略 V22.1', 'qqq-tqqq-v22.1-moomoo.txt'),
            ('纳指四季 V22.3', 'nazhi-siji-v22.3-moomoo.txt')]


def synthetic():
    idx = pd.bdate_range('2015-01-02', periods=1600)
    # Repeated booms, deep declines, recoveries and high-volume down candles.
    cycle = np.array([100,110,150,200,155,90,65,80,125,180,225,175,120,150,220,300])
    close = np.interp(np.arange(1600), np.arange(16)*100, cycle)
    close *= 1 + .02*np.sin(np.arange(1600)/9)
    q = pd.DataFrame({'open':close*1.001,'high':close*1.01,'low':close*.99,'close':close,
                      'volume':np.where(np.arange(1600)%63==0,5e6,1e6),'adjclose':close}, index=idx)
    for f in ('open','high','low','close'):q['adj_'+f] = q[f]
    return {'QQQ':q,'TQQQ':q.copy()}


def original_daily(filename, q):
    """Run supplied state machine with market mocks; broker process is replaced."""
    pointer = [0]
    def bar(field):
        return lambda symbol, bar_type, select, session_type: float(q[field].iloc[pointer[0] - select + 1])
    def ma(symbol, period, bar_type, data_type, select, session_type):
        end=pointer[0]-select+1
        return float(q.close.iloc[end-period+1:end+1].mean())
    ns = dict(StrategyBase=object, Contract=lambda x:x, Currency=SimpleNamespace(USD='USD'),
              BarType=SimpleNamespace(D1='D1'),THType=SimpleNamespace(RTH='RTH'),
              DataType=SimpleNamespace(CLOSE='CLOSE'),ma=ma, print=lambda *a:None, alert=lambda **k:None)
    for field in ('open','high','low','close','volume'):ns['bar_'+field]=bar(field)
    exec(compile((ROOT.parent/'third_party'/'moomoo'/filename).read_text(encoding='utf-8-sig'),filename,'exec'),ns)
    obj=ns['Strategy']();obj.global_variables();obj.has_open_orders=lambda:False
    first=q.index.get_loc(q.index[q.index>=pd.Timestamp('2017-01-02')][0])-1
    pointer[0]=first;obj._init_ath_price()
    output=[]
    def record(self,state,wq,wt,*args):
        self.state_label=state
        output.append((q.index[pointer[0]],state,wq,wt))
    obj.process_trading=MethodType(record,obj)
    for i in range(first,len(q)):
        pointer[0]=i;obj.handle_data()
    return pd.DataFrame(output,columns=['date','state','weight_QQQ','weight_TQQQ']).set_index('date')


class ImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames=synthetic()
        cls.codes={name:(ROOT/'strategies'/(name+'.py')).read_text(encoding='utf-8') for name,_ in VARIANTS}

    def test_original_state_machines_daily_equivalence(self):
        for name, filename in VARIANTS:
            with self.subTest(name=name):
                actual=strategy_runner.calculate(self.codes[name],self.frames)
                ref=original_daily(filename,self.frames['QQQ'])
                pd.testing.assert_frame_equal(actual[ref.columns],ref,check_dtype=False,check_freq=False)
                self.assertGreaterEqual(actual.state.nunique(),5)

    def test_worker_causality_and_two_asset_weights(self):
        for name,_ in VARIANTS:
            sig=cs.evaluate(self.codes[name],self.frames,audit=True)
            self.assertTrue(np.allclose(sig.weight_QQQ+sig.weight_TQQQ,sig.weight))
            self.assertTrue((sig.weight<=1).all())

    def test_own_states_and_author_credit(self):
        for name,filename in VARIANTS:
            profile=core.make_strategy(name,code=self.codes[name])
            self.assertEqual(profile['base_symbol'],'QQQ')
            self.assertEqual(len(profile['state_labels']),8 if '22.3' in name else 6)
            self.assertEqual(set(profile['state_labels']),set(profile['state_notes']))
            self.assertIn('CC BY-NC 4.0',profile['code'])
            self.assertIn(filename,profile['code'])
            self.assertEqual(profile['parameters']['volume_multiple'],2.2 if '22.3' in name else 2.0)

    def test_bad_sum_and_symbol_rejected(self):
        sig=strategy_runner.calculate(self.codes[VARIANTS[0][0]],self.frames)
        bad=sig.copy();bad.loc[bad.index[0],'weight_QQQ']=.1
        with self.assertRaises(ValueError):cs.validate_signals(bad,self.frames,'2017-01-02','QQQ')
        bad=sig.copy();bad.loc[bad.index[0],'symbol']='SOXL'
        with self.assertRaises(ValueError):cs.validate_signals(bad,self.frames,'2017-01-02','QQQ')

    def test_target_split_changes_alert_and_ack(self):
        previous={'symbol':'MIX','weight':.9,'weight_QQQ':.45,'weight_TQQQ':.45}
        current={**previous,'weight_QQQ':.3,'weight_TQQQ':.6}
        self.assertTrue(core.target_changed(previous,current))
        self.assertFalse(core.target_changed(previous,previous))
        self.assertIn('QQQ 45%',core.target_text(previous))
        self.assertEqual(core.strategy_tickers({'base_symbol':'QQQ'}),('QQQ','TQQQ'))

class PortfolioTests(unittest.TestCase):
    def case(self):
        idx=pd.bdate_range('2017-01-02',periods=5)
        q=pd.DataFrame({'adj_open':[10.]*5,'adj_close':[10.,10.,20.,20.,20.]},index=idx)
        t=pd.DataFrame({'adj_open':[10.]*5,'adj_close':[10.]*5},index=idx)
        sig=pd.DataFrame({'symbol':['MIX']*5,'weight_QQQ':[.45]*5,'weight_TQQQ':[.45]*5,
                          'weight':[.9]*5,'rebalance_band':[0.]*5,'state':['NORMAL']*5},index=idx)
        return {'QQQ':q,'TQQQ':t},sig

    def test_simultaneous_holding_and_no_daily_rebalance(self):
        frames,sig=self.case()
        nav,orders=portfolio.simulate(frames,sig,start='2017-01-03',initial=1000.,cost_bps=0)
        self.assertAlmostEqual(nav.equity.iloc[0],1000.)
        self.assertAlmostEqual(nav.equity.iloc[1],1450.)
        self.assertEqual(len(orders),2)
        self.assertTrue((orders.signal_date<orders.date).all())
        self.assertEqual(int(nav.rebalance.sum()),1)

    def test_change_sells_both_legs_and_ledger_conserves_cash(self):
        frames,sig=self.case();sig.loc[sig.index[1]:,['weight_QQQ','weight_TQQQ','weight']]=0.
        sig.loc[sig.index[1]:,'symbol']='CASH'
        nav,orders=portfolio.simulate(frames,sig,start='2017-01-03',initial=1000.,cost_bps=10)
        self.assertEqual(set(orders.side),{'BUY','SELL'})
        self.assertTrue((nav.cash>=0).all())
        self.assertAlmostEqual(nav.equity.iloc[-1]+orders.fee.sum(),1000.,places=9)
        self.assertAlmostEqual(orders.fee.sum(),nav.fees.sum(),places=9)

    def test_normal_drift_rebalance(self):
        frames,sig=self.case();sig['rebalance_band']=.20
        frames['QQQ']['adj_open']=[10.,10.,10.,20.,20.]
        nav,orders=portfolio.simulate(frames,sig,start='2017-01-03',initial=1000.,cost_bps=0)
        self.assertEqual(int(nav.rebalance.sum()),2)
        self.assertGreater(len(orders),2)

    def test_previous_day_signal_only(self):
        frames,sig=self.case();sig.loc[sig.index[-1],['weight_QQQ','weight_TQQQ']]=[1.,0.]
        nav,_=portfolio.simulate(frames,sig,start='2017-01-03',initial=1000.,cost_bps=0)
        self.assertAlmostEqual(nav.units_TQQQ.iloc[-1],45.)


if __name__=='__main__':unittest.main()
