"""Portable release-time, overlay-boundary and future-isolation tests."""
import unittest

import numpy as np
import pandas as pd

from macro_rules import available_daily,available_cpi,features,apply_overlay,GROUPS


class MacroTests(unittest.TestCase):
    def case(self,n=10):
        index=pd.bdate_range('2017-01-03',periods=n)
        sig=pd.DataFrame({'symbol':'SOXL','weight':.99,'state':'ATTACK','reason':'base'},index=index)
        f=pd.DataFrame({**{g:False for g in GROUPS},'score':0,
            'treasury_observation_age':2,'oil_observation_age':3,'policy_observation_age':2,'cpi_release_age':20},index=index)
        return sig,f,pd.Series(True,index=index)

    def test_observation_not_available_until_lag(self):
        index=pd.bdate_range('2017-01-03',periods=5)
        observed=pd.DataFrame({'rate':[3.,4.]},index=index[[0,3]])
        out=available_daily(observed,index,2)
        self.assertTrue(pd.isna(out.rate.iloc[1]));self.assertEqual(out.rate.iloc[2],3.)
        self.assertEqual(out.rate.iloc[4],3.)
        with self.assertRaises(ValueError):available_daily(observed,index,0)

    def test_cpi_uses_release_date_and_does_not_backfill_gap(self):
        index=pd.bdate_range('2017-01-03',periods=8)
        releases=pd.DataFrame({'headline':[2.,3.],'core':[2.,2.5]},index=index[[2,6]])
        out=available_cpi(releases,index)
        self.assertTrue(pd.isna(out.headline.iloc[1]));self.assertEqual(out.headline.iloc[2],2.)
        self.assertEqual(out.headline.iloc[5],2.);self.assertEqual(out.headline.iloc[6],3.)
        slow=available_cpi(releases,index,1)
        self.assertTrue(pd.isna(slow.headline.iloc[2]));self.assertEqual(slow.headline.iloc[3],2.)

    def test_original_cash_defense_and_reentry_priority(self):
        sig,f,h=self.case(6)
        sig.iloc[2,sig.columns.get_loc('symbol')]='CASH';sig.iloc[2,sig.columns.get_loc('weight')]=0.
        sig.iloc[3,sig.columns.get_loc('symbol')]='SMH';sig.iloc[3,sig.columns.get_loc('weight')]=.9
        f.iloc[1,f.columns.get_loc('score')]=2;h.iloc[1:5]=False
        out=apply_overlay(sig,f,h,'SOXL',{'entry_score':2,'cap':.5})
        self.assertEqual(out.weight.iloc[1],.5)
        self.assertEqual(out.symbol.iloc[2],'CASH');self.assertEqual(out.weight.iloc[2],0.)
        self.assertEqual(out.symbol.iloc[3],'SMH');self.assertEqual(out.weight.iloc[3],.9)
        self.assertEqual(out.symbol.iloc[4],'CASH');self.assertEqual(out.state.iloc[4],'MACRO_RESTORE_WAIT')
        self.assertEqual(out.weight.iloc[5],.99)
        self.assertTrue(out.weight.le(sig.weight).all())

    def test_hysteresis_and_all_asset_scope(self):
        sig,f,h=self.case();f.loc[f.index[:3],'score']=3
        out=apply_overlay(sig,f,h,'SOXL',{'entry_score':2,'cap':.5,'cash_score':3,'entry_days':2,'clear_days':5})
        self.assertEqual(out.weight.iloc[0],.99);self.assertEqual(out.weight.iloc[1],0.)
        # Three-risk cash ends when the current score falls; the half-position
        # cap persists until five clear days have elapsed.
        self.assertEqual(out.weight.iloc[6],.5);self.assertEqual(out.weight.iloc[7],.99)
        sig['symbol']='SMH';sig['weight']=.9
        default=apply_overlay(sig,f,h,'SOXL',{'entry_score':2,'cap':.5,'cash_score':3})
        covered=apply_overlay(sig,f,h,'SOXL',{'entry_score':2,'cap':.5,'cash_score':3,'scope':'all'})
        self.assertEqual(default.weight.iloc[0],.9);self.assertEqual(covered.weight.iloc[0],0.)

    def test_missing_observation_and_invalid_cap_rejected(self):
        sig,f,h=self.case();f.loc[f.index[0],'cpi_release_age']=101
        with self.assertRaises(ValueError):apply_overlay(sig,f,h,'SOXL',{'cap':.5})
        sig,f,h=self.case()
        with self.assertRaises(ValueError):apply_overlay(sig,f,h,'SOXL',{'cap':1.2})
        f.loc[f.index[0],'score']=np.nan
        with self.assertRaises(ValueError):apply_overlay(sig,f,h,'SOXL',{'cap':.5})

    def test_future_isolation_and_negative_oil(self):
        idx=pd.bdate_range('2015-01-02',periods=180)
        q=pd.Series(np.linspace(200,100,180),index=idx)
        t=pd.DataFrame({'yield10':np.linspace(2,4,180),'yield2':2.,'yield3m':.2,'real10':np.linspace(0,2,180)},index=idx)
        o=pd.DataFrame({'wti':50.},index=idx);o.iloc[80,0]=-36.98
        p=pd.DataFrame({'target_upper':.5,'effr':.4},index=idx)
        c=pd.DataFrame({'headline':[2.,2.5,3.,3.5],'core':[2.,2.2,2.6,3.]},index=idx[[5,30,65,130]])
        full=features(idx,q,t,o,p,c)
        self.assertEqual(full.wti.iloc[83],-36.98);self.assertTrue(pd.isna(full.oil_return20.iloc[83]))
        self.assertTrue(full.oil_crash.iloc[83]);self.assertFalse(full.oil_spike.iloc[83])
        end=idx[100]
        small=features(idx[:101],q.loc[:end],t.loc[:end],o.loc[:end],p.loc[:end],c.loc[:end])
        pd.testing.assert_frame_equal(full.iloc[:101],small)


if __name__=='__main__':unittest.main()
