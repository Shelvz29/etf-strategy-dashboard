"""Episode boundaries must not count one underwater event more than once."""
import unittest
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from drawdown_review import episodes, context_index, macd, review_png, review_figure


class DrawdownReviewTests(unittest.TestCase):
    def curve(self, values):
        return pd.Series(values, index=pd.bdate_range("2020-01-01", periods=len(values)), dtype=float)

    def test_independent_episodes_and_latest_equal_peak(self):
        eq = self.curve([100, 100, 90, 70, 80, 100, 110, 99, 88, 111])
        rows = episodes(eq, 100)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['peak'], eq.index[1])
        self.assertEqual(rows[0]['trough'], eq.index[3])
        self.assertEqual(rows[0]['recovery'], eq.index[5])
        self.assertAlmostEqual(rows[0]['drawdown'], -.3)
        self.assertEqual(rows[0]['peak_to_trough_sessions'], 2)
        self.assertEqual(rows[0]['underwater_sessions'], 3)
        self.assertAlmostEqual(rows[1]['drawdown'], -.2)

    def test_entry_cost_and_unrecovered_event(self):
        eq = self.curve([99.9, 95, 80, 80, 90])
        row = episodes(eq, 100)[0]
        self.assertEqual(row['peak'], eq.index[0]-pd.Timedelta(seconds=1))
        self.assertEqual(row['trough'], eq.index[2])
        self.assertIsNone(row['recovery'])
        self.assertEqual(row['underwater_sessions'], 5)
        self.assertAlmostEqual(row['drawdown'], -.2)

    def test_reference_max_drawdown_and_no_mutation(self):
        eq = self.curve([100, 110, 100, 90, 110, 120, 80, 130, 110])
        copy = eq.copy()
        rows = episodes(eq, 100)
        expected = np.min(eq.to_numpy()/np.maximum.accumulate(np.r_[100, eq.to_numpy()])[1:]-1)
        self.assertAlmostEqual(rows[0]['drawdown'], expected)
        pd.testing.assert_series_equal(eq, copy)
        self.assertIsNone(rows[-1]['recovery'])
        self.assertEqual(episodes(self.curve([100,101,102]),100),[])

    def test_context_and_macd_warmup(self):
        eq = self.curve([100,110,100,90,95,110,120,125])
        row = episodes(eq,100)[0]
        self.assertTrue(context_index(eq.index,row,1).equals(eq.index[0:7]))
        f = macd(eq)
        pd.testing.assert_frame_equal(f.iloc[:5],macd(eq.iloc[:5]))

    def test_invalid_curve(self):
        for eq in (self.curve([]), self.curve([100,0]), self.curve([100,np.nan]),self.curve([100,90]).iloc[::-1]):
            with self.assertRaises(ValueError): episodes(eq,100)

    def test_render_prices_macd_holdings_and_account_dates(self):
        eq=self.curve([100,110,100,90,95,110,120,125])
        row=episodes(eq,100)[0]
        frame=pd.DataFrame({'open':eq-.5,'close':eq,'low':eq-1,'high':eq+1},index=eq.index)
        frames={'SMH':frame,'SOXL':frame*2}
        nav=pd.DataFrame({'equity':eq,'held':['SOXL']*4+['CASH']*2+['SMH']*2,
                          'asset_weight':[1]*4+[0]*2+[.5]*2},index=eq.index)
        fig=review_figure(frames,nav,row,'SMH',1)
        self.assertEqual(sum(t.type=='candlestick' for t in fig.data),2)
        histogram=next(t for t in fig.data if t.name=='MACD柱线')
        np.testing.assert_allclose(histogram.y,macd(frame.close)['hist'])
        account=next(t for t in fig.data if t.name=='策略净值')
        np.testing.assert_allclose(account.y,eq/110*100)
        self.assertEqual(len(fig.layout.shapes),16)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'chart.png'
            review_png(frames,nav,row,'SMH',1,path)
            from PIL import Image
            with Image.open(path) as im:self.assertEqual(im.size,(1920,1220))


if __name__ == "__main__":
    unittest.main()
