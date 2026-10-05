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
        full = charts.indicators(bars, [5, 7], [9], 14, 20, kdj_params=(9, 3, 3))
        short = charts.indicators(bars.iloc[:40], [5, 7], [9], 14, 20, kdj_params=(9, 3, 3))
        assert_frame_equal(full.iloc[:40], short)
        assert_frame_equal(bars, before)
        fig = charts.figure(full, "TEST", "日K", 14)
        self.assertEqual(fig.data[0].type, "candlestick")
        self.assertEqual(len(fig.data[0].close), 60)
        self.assertEqual(fig.layout.yaxis3.range, (0, 100))

    def test_kdj_hand_calculation_flat_range_and_unbounded_j(self):
        bars = pd.DataFrame({'high': [10., 11., 12.], 'low': [0., 0., 0.], 'close': [5., 6., 9.]})
        result = charts.kdj(bars, 3, 3, 3)
        self.assertTrue(result.iloc[:2].isna().all().all())
        self.assertAlmostEqual(result.K.iloc[2], 58.33333333333333)
        self.assertAlmostEqual(result.D.iloc[2], 52.77777777777778)
        self.assertAlmostEqual(result.J.iloc[2], 69.44444444444443)
        flat = pd.DataFrame({'high': [10.] * 6, 'low': [10.] * 6, 'close': [10.] * 6})
        self.assertTrue(charts.kdj(flat, 3).iloc[2:].eq(50).all().all())
        bullish = pd.DataFrame({'high': [10.] * 6, 'low': [0.] * 6, 'close': [10.] * 6})
        self.assertGreater(charts.kdj(bullish, 3).J.iloc[-1], 100)
        for params in ((0, 3, 3), (9, 0, 3), (9, 3, 501)):
            with self.assertRaises(ValueError):
                charts.kdj(bars, *params)

    def test_kdj_separate_panel_with_or_without_rsi(self):
        bars = charts.candles(prices(pd.date_range('2026-01-01', periods=60)), '日K')
        data = charts.indicators(bars, rsi_length=14, kdj_params=(9, 3, 3))
        for rsi_length, row in ((None, 3), (14, 4)):
            fig = charts.figure(data, 'TEST', '日K', rsi_length=rsi_length, kdj_params=(9, 3, 3))
            axis = getattr(fig.layout, f'yaxis{row}')
            self.assertEqual(axis.title.text, 'KDJ')
            self.assertIsNone(axis.range)
            self.assertEqual([trace.name for trace in fig.data[-3:]], ['K', 'D', 'J'])

    def test_input_validation(self):
        self.assertEqual(charts.periods("5，7,20,7"), [5, 7, 20])
        for text in ("", "0", "501", "5.5", "5,,7", "5*2", "1,2,3,4,5,6,7"):
            with self.assertRaises(ValueError):
                charts.periods(text)

    def test_hover_previous_close_survives_display_crop(self):
        bars = charts.with_changes(charts.candles(prices(pd.date_range('2026-01-01', periods=4)), '日K'))
        cropped = bars.iloc[2:]
        self.assertAlmostEqual(cropped.change_pct.iloc[0], (13 / 12 - 1) * 100)
        tooltip = charts.figure(cropped, 'TEST', '日K').data[0].hovertext[0]
        self.assertIn('涨跌幅（较上一根收盘）：+8.33%', tooltip)
        self.assertIn('本根开收涨跌幅：+4.00%', tooltip)
        self.assertIn('无前收数据', charts.hover_labels(bars.iloc[:1], '日K')[0])
        weekly = charts.with_changes(charts.candles(prices(pd.bdate_range('2026-01-05', periods=10)), '周K'))
        self.assertAlmostEqual(weekly.change_pct.iloc[1], (20 / 15 - 1) * 100)

    def test_range_returns_holidays_bases_adjustment_and_invalid_dates(self):
        daily = prices(pd.to_datetime(['2026-01-02', '2026-01-05', '2026-01-06', '2026-01-07']))
        result = charts.range_return(daily, '2026-01-03', '2026-01-06')
        self.assertEqual(result['first'], pd.Timestamp('2026-01-05'))
        self.assertEqual(result['last'], pd.Timestamp('2026-01-06'))
        self.assertEqual(result['sessions'], 2)
        self.assertAlmostEqual(result['return'], 13 / 12 - 1)
        self.assertAlmostEqual(charts.range_return(daily, '2026-01-03', '2026-01-06', '首日开盘')['return'], 13 / 11.5 - 1)
        prior = charts.range_return(daily, '2026-01-03', '2026-01-06', '前一交易日收盘')
        self.assertAlmostEqual(prior['return'], 13 / 11 - 1)
        self.assertEqual(prior['baseline_date'], pd.Timestamp('2026-01-02'))
        self.assertEqual(charts.range_return(daily, '2026-01-05', '2026-01-05')['return'], 0.)
        adjusted = daily.copy()
        for field in ('open', 'high', 'low', 'close'):
            adjusted['adj_' + field] = adjusted[field] * np.array([.5, .6, .7, .8])
        self.assertAlmostEqual(charts.range_return(adjusted, '2026-01-03', '2026-01-06', adjusted=True)['return'], 13 * .7 / (12 * .6) - 1)
        for start, end, basis in (('2026-01-07', '2026-01-02', '首日收盘'), ('2026-01-03', '2026-01-04', '首日收盘'), ('2026-01-02', '2026-01-07', '前一交易日收盘')):
            with self.assertRaises(ValueError):
                charts.range_return(daily, start, end, basis)

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
            app.multiselect(key="tech_indicators").set_value(["MA", "EMA", "RSI", "BOLL", "KDJ"])
            app.run()
            self.assertEqual(app.number_input(key="tech_kdj_length").value, 9)
            app.number_input(key="tech_kdj_length").set_value(7)
            app.number_input(key="tech_kdj_k").set_value(2)
            app.text_input(key="tech_ma").set_value("5,7")
            app.number_input(key="tech_rsi").set_value(7)
            app.number_input(key="tech_boll").set_value(7)
            app.run()
            self.assertEqual(len(app.exception), 0)
            app.selectbox(key="tech_frequency").set_value("周K").run()
            self.assertEqual(len(app.exception), 0)
            app.selectbox(key="tech_window_周K").set_value("自选日期").run()
            app.date_input(key="tech_range_start_XSD_自选日期").set_value(pd.Timestamp('2026-01-03').date())
            app.date_input(key="tech_range_end_XSD_自选日期").set_value(pd.Timestamp('2026-01-06').date())
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any('所选区间涨跌幅' == m.label for m in app.metric))
            app.date_input(key="tech_range_end_XSD_自选日期").set_value(pd.Timestamp('2026-01-02').date()).run()
            self.assertTrue(any('开始日期不能晚于' in w.value for w in app.warning))
            app.selectbox(key="tech_frequency").set_value("年K").run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("历史K线根数不足" in x.value for x in app.info))
            self.assertTrue(any("尚未结束" in x.value for x in app.caption))
            app.text_input(key="tech_ma").set_value("5,,7").run()
            self.assertTrue(any("整数" in x.value for x in app.warning))


if __name__ == "__main__":
    unittest.main()
