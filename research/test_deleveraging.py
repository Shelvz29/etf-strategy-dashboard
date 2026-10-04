"""Boundary and no-lookahead checks for research overlays."""
import unittest
import numpy as np
import pandas as pd

from deleveraging_rules import apply_deleveraging, risk_features


class DeleveragingTests(unittest.TestCase):
    def setUp(self):
        self.days=pd.date_range('2024-01-02',periods=6,freq='B')
        self.signals=pd.DataFrame({'symbol':['SOXL','SOXL','CASH','SMH','SOXL','SOXL'],
            'weight':[.99,.99,0,.9,.99,.99],'state':['NORMAL_ATTACK','DEEP_ATTACK','RISK_CASH_TRIGGER','SPRING_DEFENSE','NORMAL_ATTACK','NORMAL_ATTACK'],
            'reason':['']*6},index=self.days)
        self.features=pd.DataFrame({'risk_soxl_vol':[.8]*6,'risk_smh_vol_ratio':[1.]*6,
            'risk_macd_hist':[.1]*6,'risk_trend_bad':[False]*6,'risk_healthy':[True]*6,
            'risk_above_ema_streak':[3]*6},index=self.days)

    def test_volatility_limit_and_quantization(self):
        result=apply_deleveraging(self.signals,self.features,{'vol_target':.4})
        self.assertEqual(result.weight.iloc[0],.5)
        features=self.features.copy();features['risk_soxl_vol']=.9
        result=apply_deleveraging(self.signals,features,{'vol_target':.4})
        self.assertAlmostEqual(result.weight.iloc[0],.4)
        self.assertTrue(result.loc[result.symbol.eq('SOXL'),'weight'].le(.4/.9).all())

    def test_existing_cash_lock_and_smh_targets_are_untouched(self):
        original=self.signals.copy(deep=True)
        result=apply_deleveraging(self.signals,self.features,{'vol_target':.3,'trend_cap':0,'gate_deep':True,'gate_reentry':True})
        pd.testing.assert_frame_equal(result.loc[self.days[2:4],self.signals.columns],original.loc[self.days[2:4]])
        pd.testing.assert_frame_equal(self.signals,original)

    def test_deep_gate_and_reentry_and_increase_boundary(self):
        features=self.features.copy();features.loc[self.days[1:],'risk_healthy']=False
        result=apply_deleveraging(self.signals,features,{'gate_deep':True,'gate_reentry':True})
        self.assertEqual(result.symbol.iloc[0],'SOXL')
        self.assertEqual(result.symbol.iloc[1],'CASH')
        self.assertEqual(result.symbol.iloc[4],'CASH')
        features.loc[self.days[5],'risk_healthy']=True
        result=apply_deleveraging(self.signals,features,{'gate_deep':True,'gate_reentry':True})
        self.assertEqual(result.symbol.iloc[5],'SOXL')
        self.assertEqual(result.weight.iloc[5],.99)
        sig=self.signals.iloc[:2].copy();sig['state']='NORMAL_ATTACK'
        feat=self.features.iloc[:2].copy();feat['risk_soxl_vol']=[1.,.5];feat['risk_healthy']=[True,False]
        result=apply_deleveraging(sig,feat,{'vol_target':.4,'gate_reentry':True})
        np.testing.assert_allclose(result.weight,[.4,.4])

    def test_trend_cash_cap_and_disabled_overlay(self):
        feat=self.features.copy();feat['risk_trend_bad']=True
        result=apply_deleveraging(self.signals,feat,{'trend_cap':0})
        self.assertTrue(result.loc[self.signals.symbol.eq('SOXL'),'symbol'].eq('CASH').all())
        plain=apply_deleveraging(self.signals,self.features,{})
        pd.testing.assert_frame_equal(plain[self.signals.columns],self.signals)

    def test_features_do_not_use_future_prices(self):
        dates=pd.date_range('2023-01-02',periods=200,freq='B')
        frames={}
        for i,s in enumerate(('SMH','QQQ','SOXL')):
            values=100*np.exp(np.cumsum(.002+np.sin(np.arange(len(dates))+i)*.01))
            frames[s]=pd.DataFrame({'close':values,'adj_close':values},index=dates)
        full=risk_features(frames)
        early=risk_features({s:f.iloc[:150] for s,f in frames.items()})
        pd.testing.assert_frame_equal(full.iloc[:150],early)
        changed={s:f.copy() for s,f in frames.items()}
        for f in changed.values():f.iloc[150:]*=10
        pd.testing.assert_frame_equal(full.iloc[:150],risk_features(changed).iloc[:150])


if __name__=='__main__':unittest.main()
