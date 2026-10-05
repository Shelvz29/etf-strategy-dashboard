"""Portable chart checks with synthetic inputs, never live trading data."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
from streamlit.testing.v1 import AppTest

import core
import technical_chart as charts


def prices(dates):
    close = np.arange(1., len(dates) + 1.) + 10
    frame = pd.DataFrame({"open": close - .5, "high": close + 1, "low": close - 1,
                          "close": close, "volume": np.arange(1., len(dates) + 1.) * 100}, index=pd.DatetimeIndex(dates))
    for field in ("open", "high", "low", "close"):
        frame["adj_" + field] = frame[field] * .5
    return frame


class TechnicalChartTests(unittest.TestCase):
    def test_weekly_holiday_partial_bar_and_actual_date(self):
        source = prices(pd.to_datetime(["2026-11-23", "2026-11-24", "2026-11-25", "2026-11-27", "2026-11-30", "2026-12-01"]))
        bars = charts.candles(source, "周K")
        self.assertEqual(bars.index.strftime("%Y-%m-%d").tolist(), ["2026-11-27", "2026-12-01"])
        self.assertEqual(bars.iloc[0].open, source.iloc[0].open)
        self.assertEqual(bars.iloc[0].close, source.iloc[3].close)
        self.assertEqual(bars.iloc[0].high, source.iloc[:4].high.max())
        self.assertEqual(bars.iloc[0].low, source.iloc[:4].low.min())
        self.assertEqual(bars.volume.sum(), source.volume.sum())
        # Midweek data must not be labelled as a future Friday.
        self.assertEqual(bars.index[-1], source.index[-1])

    def test_annual_boundary_and_uniform_adjustment(self):
        source = prices(pd.to_datetime(["2025-12-30", "2025-12-31", "2026-01-02", "2026-01-05"]))
        raw = charts.candles(source, "年K")
        adjusted = charts.candles(source, "年K", True)
        self.assertEqual(raw.index.strftime("%Y-%m-%d").tolist(), ["2025-12-31", "2026-01-05"])
        assert_frame_equal(adjusted[["open", "high", "low", "close"]], raw[["open", "high", "low", "close"]] * .5)
        self.assertTrue(adjusted.volume.equals(raw.volume))
        self.assertEqual(raw.iloc[1].open, source.iloc[2].open)

    def test_known_ma_ema_boll_and_insufficient_history(self):
        source = prices(pd.date_range("2026-01-01", periods=10))
        data = charts.indicators(charts.candles(source, "日K"), [3, 20], [3], boll_length=3)
        self.assertEqual(data.MA3.iloc[2], 12.)
        self.assertEqual(data.EMA3.iloc[2], 12.25)
        self.assertAlmostEqual(data["BOLL上轨"].iloc[2], 12 + 2 * np.sqrt(2 / 3))
        self.assertTrue(data.MA20.isna().all())
        self.assertTrue(data.MA3.iloc[:2].isna().all())
        self.assertTrue(data.EMA3.iloc[:2].isna().all())

    def test_wilder_rsi_known_value_and_zero_gain_loss(self):
        close = pd.Series([44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00])
        output = charts.rsi(close, 14)
        self.assertAlmostEqual(output.iloc[14], 70.46413502109705)
        self.assertAlmostEqual(output.iloc[15], 66.24961855355505)
        self.assertTrue(output.iloc[:14].isna().all())
        self.assertEqual(charts.rsi(pd.Series([1.] * 10), 3).iloc[-1], 50.)
        self.assertEqual(charts.rsi(pd.Series(np.arange(10.)), 3).iloc[-1], 100.)
        self.assertEqual(charts.rsi(pd.Series(-np.arange(10.)), 3).iloc[-1], 0.)

    def test_indicators_no_future_fill_or_input_mutation(self):
        bars = charts.candles(prices(pd.date_range("2026-01-01", periods=60)), "日K")
        before = bars.copy(deep=True)
        full = charts.indicators(bars, [5, 7], [9], 14, 20)
        short = charts.indicators(bars.iloc[:40], [5, 7], [9], 14, 20)
        assert_frame_equal(full.iloc[:40], short)
        assert_frame_equal(bars, before)
        fig = charts.figure(full, "TEST", "日K", 14)
        self.assertEqual(fig.data[0].type, "candlestick")
        self.assertEqual(len(fig.data[0].close), 60)
        self.assertEqual(fig.layout.yaxis3.range, (0, 100))

    def test_input_validation(self):
        self.assertEqual(charts.periods("5，7,20,7"), [5, 7, 20])
        for text in ("", "0", "501", "5.5", "5,,7", "5*2", "1,2,3,4,5,6,7"):
            with self.assertRaises(ValueError):
                charts.periods(text)

    def test_widget_changes_and_yearly_insufficient_history(self):
        profile = core.default_strategy()
        daily = prices(pd.bdate_range("2024-01-02", "2026-10-02"))
        snap = {"strategy": profile, "source": "测试输入", "last": {"date": "2026-10-02"}, "fetched": "2026-10-02T21:00:00Z"}
        bundle = {s: {} for s in core.strategy_tickers(profile)}
        app = AppTest.from_string("import technical_chart, core\ntechnical_chart.render(core.default_strategy())")
        with patch.object(charts.performance, "confirmed_inputs", return_value=(snap, bundle)), patch.object(charts, "confirmed_frame", return_value=daily):
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.selectbox(key="tech_symbol_default").options, ["QQQ", "XSD", "SOXL"])
            app.multiselect(key="tech_indicators").set_value(["MA", "EMA", "RSI", "BOLL"])
            app.run()
            app.text_input(key="tech_ma").set_value("5,7")
            app.number_input(key="tech_rsi").set_value(7)
            app.number_input(key="tech_boll").set_value(7)
            app.run()
            self.assertEqual(len(app.exception), 0)
            app.selectbox(key="tech_frequency").set_value("周K").run()
            self.assertEqual(len(app.exception), 0)
            app.selectbox(key="tech_frequency").set_value("年K").run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("历史K线根数不足" in x.value for x in app.info))
            self.assertTrue(any("尚未结束" in x.value for x in app.caption))
            app.text_input(key="tech_ma").set_value("5,,7").run()
            self.assertTrue(any("整数" in x.value for x in app.warning))


if __name__ == "__main__":
    unittest.main()
