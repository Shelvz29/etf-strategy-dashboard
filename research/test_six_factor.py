import unittest
import numpy as np
import pandas as pd
from six_factor_data import extract
from six_factor_rules import grade,archive_daily,apply_overlay,proxy_records,FACTORS


class SixFactorTests(unittest.TestCase):
    def test_forecasts_not_growth_or_actual(self):
        text='The forward 12 -month P/E ratio for the S&P 500 is 22.4. On a per-share basis, estimated earnings for the third quarter have fallen by 5.4% since June 30.'
        self.assertEqual(extract(text)['pe'],22.4)
        self.assertEqual(extract(text)['revision'],-5.4)
        self.assertIsNone(extract('Actual earnings fell by 5.4%. Estimated earnings growth declined to 5.4% from 7%.')['revision'])
        self.assertEqual(extract('The Q2 bottom-up EPS estimate (an aggregation for all companies in the index) has dropped by 2.6% during this period.')['revision'],-2.6)

    def test_grade_boundaries_unknown(self):
        s=pd.Series([np.nan,21.9,22.,25.,28.])
        pd.testing.assert_series_equal(grade(s,[22.,25.,28.]),pd.Series([np.nan,0.,1.,2.,3.]))
        self.assertEqual(grade(pd.Series([-5.]),[-2.,-5.,-10.],True).iloc[0],2.)

    def test_release_and_expiry(self):
        ix=pd.bdate_range('2022-03-01','2022-05-31')
        rows=[{'date':'2022-03-04','revision':-5.,'quarter':1}]
        f=archive_daily(rows,ix,'revision')
        self.assertTrue(pd.isna(f.loc['2022-03-04','revision']))
        self.assertEqual(f.loc['2022-03-07','revision'],-5.)
        self.assertTrue(pd.isna(f.loc['2022-04-01','revision']))
        pe=archive_daily([{'date':'2022-03-04','pe':25.}],ix,'pe')
        self.assertTrue(pd.isna(pe.iloc[-1].pe))

    def test_caps_and_original_cash_recovery(self):
        ix=pd.bdate_range('2022-01-03',periods=6)
        sig=pd.DataFrame({'symbol':['SOXL','SOXL','CASH','SOXL','SOXL','SMH'],'weight':[1.,1.,0.,1.,1.,.5],
                          'state':'base','reason':'base'},index=ix)
        f=pd.DataFrame(0.,index=ix,columns=[*FACTORS,'structure','finance','score_lower_bound','known_count'])
        f['known_count']=6;f.loc[ix[:2],['structure','finance']]=[3.,2.]
        healthy=pd.Series([True,True,False,False,True,True],index=ix)
        out=apply_overlay(sig,f,healthy,{})
        self.assertEqual(out.weight.iloc[0],.5)
        self.assertEqual(out.symbol.iloc[2],'CASH')
        self.assertEqual(out.weight.iloc[3],0.)
        self.assertEqual(out.weight.iloc[4],1.)
        self.assertEqual(out.symbol.iloc[5],'SMH')
        self.assertTrue(out.weight.le(sig.weight).all())
        pd.testing.assert_frame_equal(out.iloc[:4],apply_overlay(sig.iloc[:4],f.iloc[:4],healthy.iloc[:4],{}))

    def test_unknown_is_explicit_and_sensitivity(self):
        ix=pd.bdate_range('2022-01-03',periods=2)
        sig=pd.DataFrame({'symbol':'SOXL','weight':1.,'state':'base','reason':'base'},index=ix)
        f=pd.DataFrame(np.nan,index=ix,columns=FACTORS)
        f['structure']=0.;f['finance']=0.;f['known_count']=4;f['score_lower_bound']=0.
        healthy=pd.Series(True,index=ix)
        self.assertTrue(apply_overlay(sig,f,healthy,{}).weight.eq(1.).all())
        self.assertTrue(apply_overlay(sig,f,healthy,{'unknown_cap':.5}).weight.eq(.5).all())

    def test_rolling_proxy_uses_prior_close_and_past_report(self):
        ix=pd.bdate_range('2022-01-01','2022-04-30');price=pd.Series(4000.,index=ix)
        rows=[{'date':'2022-01-07','pe':20.},{'date':'2022-02-11','pe':22.},
              {'date':'2022-03-18','pe':25.}]
        price.loc['2022-02-11']=8000.  # Friday is not used by the Friday report.
        a=proxy_records(rows,price)
        self.assertAlmostEqual(a[1]['proxy_revision30'],100*(20/22-1))
        self.assertEqual(a[:2],proxy_records(rows[:2],price.loc[:'2022-02-11']))


if __name__=='__main__':unittest.main()
