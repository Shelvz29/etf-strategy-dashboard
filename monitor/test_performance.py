"""Regression checks for portfolio windows, adjusted prices and the calculator."""
from pathlib import Path
import copy
import json
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from pandas.testing import assert_series_equal

import core
import performance as perf


class PerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames, _ = core.baseline.load_data(core.FROZEN / "data")
        cls.signals = core.replay(cls.frames, core.default_strategy())
        cls.full = perf.full_strategy(cls.frames, cls.signals)
        cls.bundle = {sym: json.loads((core.FROZEN / "data" / f"{sym}.json").read_text(encoding="utf-8")) for sym in core.TICKERS}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(core, "RUNTIME", Path(self.temp.name)),
                        patch.object(core, "DB", Path(self.temp.name) / "test.db")]
        for item in self.patches:
            item.start()
        core.init_db()
        core.put("confirmed_bundle", self.bundle)
        core.put("snapshot", core.pack(self.frames, self.signals, "原回测冻结快照"))
        core.put("desktop_notifications", False)

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_original_nav_and_trailing_report_regression(self):
        original = pd.read_csv(core.FROZEN / "equity.csv", parse_dates=["date"], index_col="date")
        legacy=core.make_strategy(core.STRATEGY_NAME,core.baseline.Config().to_dict())
        legacy_signals=core.replay(self.frames,legacy);legacy_full=perf.full_strategy(self.frames,legacy_signals)
        np.testing.assert_allclose(legacy_full.to_numpy(), original.equity.to_numpy() / 100000, rtol=1e-12)
        prior = pd.read_csv(core.FROZEN / "2026-10-02-XSD-SOXL-近年回测.csv")
        for _, row in prior.iterrows():
            win = perf.window(legacy_full.index, f"近{int(row.window_years)}年")
            result = perf.compare_window(self.frames, legacy_signals, legacy_full, [], win)[perf.STRATEGY]
            metric = result["metrics"]
            self.assertAlmostEqual(metric["annualized_return"], row.annualized_return, places=10)
            self.assertAlmostEqual(metric["max_drawdown"], -row.max_drawdown_close, places=10)
            self.assertEqual(metric["baseline_close"], row.baseline_close_date)
            self.assertEqual(result["wealth"].iloc[0], 1.0)
        win = perf.window(self.full.index, "全部历史")
        whole = perf.compare_window(self.frames, self.signals, self.full, [], win)[perf.STRATEGY]
        expected = self.full.iloc[-1] ** (365.25 / ((self.full.index[-1] - self.full.index[0]).days + 1)) - 1
        self.assertAlmostEqual(whole["metrics"]["annualized_return"], expected, places=11)

    def test_principal_scaling_and_invalid_values(self):
        win = perf.window(self.full.index, "近1年")
        results = perf.compare_window(self.frames, self.signals, self.full, ["QQQ", "SOXL"], win)
        small, large = perf.money_table(results, 10000), perf.money_table(results, 20000)
        np.testing.assert_allclose(large.ending_capital, small.ending_capital * 2)
        np.testing.assert_allclose(large.profit, small.profit * 2)
        np.testing.assert_allclose(large.annualized_return, small.annualized_return)
        np.testing.assert_allclose(large.max_drawdown, small.max_drawdown)
        for capital in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                perf.money_table(results, capital)

    def test_cash_start_includes_entry_cost_and_previous_close_signal(self):
        win = perf.window(self.full.index, "自定义日期", "2026-09-01", "2026-10-01")
        result = perf.compare_window(self.frames, self.signals, self.full, ["QQQ"], win, perf.FRESH, 10)
        benchmark = result["QQQ"]["wealth"]
        f = self.frames["QQQ"]
        expected = f.loc[win.first, "adj_close"] / (f.loc[win.first, "adj_open"] * 1.001)
        self.assertAlmostEqual(benchmark.iloc[1], expected, places=12)
        nav, _ = perf.engine.simulate(self.frames, self.signals, str(win.first.date()), str(win.end.date()), initial=100000)
        np.testing.assert_allclose(result[perf.STRATEGY]["wealth"].iloc[1:], nav.equity / 100000, rtol=1e-12)
        previous = self.signals.index[self.signals.index.get_loc(win.first) - 1]
        self.assertEqual(nav.signal_date.iloc[0], previous)
        self.assertIsNone(result[perf.STRATEGY]["metrics"]["baseline_close"])

    def test_split_and_dividend_adjustment_not_raw_price_return(self):
        index = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"])
        # Raw prices halve on a split; total-return prices remain flat.
        frame = pd.DataFrame({"open": [100, 50, 50], "close": [100, 50, 49],
                              "adj_open": [50, 50, 50], "adj_close": [50, 50, 50]}, index=index)
        curve = perf.buy_hold(frame, index[0], index[-1], 0)
        np.testing.assert_allclose(curve, [1, 1, 1])

    def test_drawdown_includes_initial_capital(self):
        idx = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"])
        win = perf.Window("测试", None, idx[0], idx[-1])
        result = perf.unit_result(pd.Series([.9, .8, .85], index=idx), 1, win, perf.FRESH)
        self.assertAlmostEqual(result["metrics"]["max_drawdown"], .2)
        self.assertAlmostEqual(result["metrics"]["total_return"], -.15)

    def test_custom_weekend_and_history_limits(self):
        win = perf.window(self.full.index, "自定义日期", "2026-09-26", "2026-10-01")
        self.assertEqual(str(win.first.date()), "2026-09-28")
        for a, b in (("2026-09-26", "2026-09-27"), ("2016-12-30", "2017-01-06"), ("2026-10-01", "2026-09-01")):
            with self.assertRaises(ValueError):
                perf.window(self.full.index, "自定义日期", a, b)
        with self.assertRaises(ValueError):
            perf.window(self.full.index, "近5年", end="2019-12-31")

    def test_future_changes_do_not_change_earlier_window(self):
        win = perf.window(self.full.index, "自定义日期", "2026-09-01", "2026-09-15")
        before = perf.compare_window(self.frames, self.signals, self.full, ["QQQ"], win, perf.FRESH)
        changed = {sym: frame.copy(deep=True) for sym, frame in self.frames.items()}
        for frame in changed.values():
            price_cols = [key for key in frame.columns if key != "volume"]
            frame.loc[frame.index > win.end, price_cols] *= 1.7
        future_signals = core.replay(changed)
        after = perf.compare_window(changed, future_signals, perf.full_strategy(changed, future_signals), ["QQQ"], win, perf.FRESH)
        for name in before:
            assert_series_equal(before[name]["wealth"], after[name]["wealth"])

    def test_missing_and_monthly_quotes_rejected(self):
        broken = copy.deepcopy(self.bundle["QQQ"])
        r = broken["chart"]["result"][0]
        r["timestamp"].pop(-2)
        for kind in ("quote", "adjclose"):
            for item in r["indicators"][kind]:
                for values in item.values():
                    values.pop(-2)
        with self.assertRaises(ValueError):
            perf.parse_price("QQQ", broken, "2026-10-01")
        monthly = copy.deepcopy(self.bundle["QQQ"])
        monthly["chart"]["result"][0]["meta"]["dataGranularity"] = "1mo"
        with self.assertRaises(ValueError):
            perf.parse_price("QQQ", monthly, "2026-10-01")

    def test_failed_comparison_does_not_change_monitor_state(self):
        before = core.get("snapshot")
        with patch.object(core, "request_json", side_effect=RuntimeError("测试ETF接口失败")):
            frames, errors, _ = perf.extra_prices(["TQQQ"], "2026-10-01")
        self.assertNotIn("TQQQ", frames)
        self.assertIn("TQQQ", errors)
        self.assertEqual(core.get("snapshot"), before)

    def test_page_principal_and_comparison_selection(self):
        from streamlit.testing.v1 import AppTest
        # AppTest's current widget serializer does not preserve tracked tab state
        # on unrelated widget submissions. Exercise the calculator directly;
        # tracked-tab navigation is verified separately in the actual browser.
        page = AppTest.from_string("import core, performance_ui\nperformance_ui.render(core.get('snapshot'))", default_timeout=30).run()
        self.assertEqual(len(page.exception), 0)
        current = [metric for metric in page.metric if metric.label.startswith("策略期末资金")][0].value
        [widget for widget in page.number_input if widget.label == "起始本金"][0].set_value(20000)
        [widget for widget in page.multiselect if widget.label == "对比ETF与策略（可多选）"][0].set_value([])
        [button for button in page.button if button.label == "生成表格与图表"][0].click()
        page.run()
        self.assertEqual(len(page.exception), 0)
        new = [metric for metric in page.metric if metric.label.startswith("策略期末资金")][0].value
        self.assertAlmostEqual(float(new.replace(",", "")), 2 * float(current.replace(",", "")), places=1)
        self.assertEqual(page.session_state["performance_last_result"]["assets"], [perf.STRATEGY])
        self.assertEqual(len(core.trades()), 0)

    def test_multiple_strategies_match_independent_backtests_and_all_periods(self):
        candidates = [core.save_strategy("稳健组合", dict(core.default_strategy()["parameters"], attack=.4)),
                      core.save_strategy("进取组合", dict(core.default_strategy()["parameters"], attack=.8))]
        comparisons = {f"{p['name']} · v{p['revision']}（策略）": (self.frames, core.replay(self.frames, p)) for p in candidates}
        before = core.get("snapshot")
        for mode in (perf.CONTINUOUS, perf.FRESH):
            combined = perf.report(self.frames, self.signals, ["QQQ"], "近3年", mode, cost_bps=17, comparisons=comparisons)
            self.assertEqual(list(combined["results"]), [perf.STRATEGY, "QQQ", *comparisons])
            for label, (frames, signals) in comparisons.items():
                independent = perf.report(frames, signals, [], "近3年", mode, cost_bps=17)
                own_name = signals.attrs["strategy"]["name"]
                assert_series_equal(combined["results"][label]["wealth"], independent["results"][own_name]["wealth"])
                assert_series_equal(combined["results"][label]["drawdown"], independent["results"][own_name]["drawdown"])
                self.assertEqual(combined["results"][label]["metrics"], independent["results"][own_name]["metrics"])
                np.testing.assert_allclose(combined["periods"].query('asset == @label').annualized_return,
                                           independent["periods"].annualized_return)
        self.assertEqual(core.get("snapshot"), before)
        self.assertEqual(core.active_strategy()["id"], "default")
        self.assertEqual(len(core.trades()), 0)

    def test_comparison_calendar_failure_does_not_hide_valid_results(self):
        comparisons = {"有效策略": (self.frames, self.signals),
                       "缺少末日策略": (self.frames, self.signals.iloc[:-1])}
        combined = perf.report(self.frames, self.signals, ["QQQ"], "近1年", comparisons=comparisons)
        self.assertEqual(list(combined["results"]), [perf.STRATEGY, "QQQ", "有效策略"])
        self.assertNotIn("缺少末日策略", set(combined["periods"].asset))
        self.assertTrue(any("缺少末日策略" in item and "日期" in item for item in combined["unavailable"]))

    def test_cache_identity_includes_comparison_base_prices_and_adjustments(self):
        import performance_ui as ui
        original = ui.dataset_fingerprint(self.frames)
        changed = {**self.frames, "SMH": self.frames["XSD"].copy()}
        base = ui.dataset_fingerprint(changed)
        self.assertNotEqual(base, original)
        changed['SMH'].iloc[-1, changed['SMH'].columns.get_loc('adj_close')] *= 1.01
        self.assertNotEqual(ui.dataset_fingerprint(changed), base)
        self.assertEqual(ui.dataset_fingerprint(dict(reversed(list(self.frames.items())))), original)

    def test_page_compares_code_strategy_revisions_and_preserves_monitor(self):
        import code_strategy as cs
        import performance_ui as ui
        from streamlit.testing.v1 import AppTest
        code = cs.template(core.default_strategy(), core.baseline).replace("'attack': 1.0", "'attack': 0.4")
        first = core.save_strategy("代码组合", code=code)
        second = core.save_strategy("代码组合", code=code.replace("'attack': 0.4", "'attack': 0.8"),
                                    strategy_id=first['id'], expected_revision=1)
        before = core.get("snapshot")
        keys = [f"strategy:{p['id']}:{p['revision']}" for p in (first, second)]
        page = AppTest.from_string("import core, performance_ui\nperformance_ui.render(core.get('snapshot'))", default_timeout=30).run()
        choices = [widget for widget in page.multiselect if widget.label == "对比ETF与策略（可多选）"][0]
        for p in (first, second):
            self.assertIn(ui.comparison_label(p), choices.options)
        default_key=f"strategy:default:{core.default_strategy()['revision']}"
        choices.set_value(["QQQ", *keys, default_key])
        [button for button in page.button if button.label == "生成表格与图表"][0].click()
        page.run()
        self.assertEqual(len(page.exception), 0)
        self.assertEqual(page.session_state['performance_last_result']['assets'],
                         [perf.STRATEGY, 'QQQ', ui.comparison_label(first), ui.comparison_label(second)])
        self.assertEqual(core.get('performance_settings')['selected'], ["QQQ", *keys, default_key])
        # Switching the main backtest keeps the other version as a comparison;
        # the same version selected twice must never duplicate rows or curves.
        [widget for widget in page.selectbox if widget.label == "回测策略"][0].set_value(f"{first['id']}:1")
        [button for button in page.button if button.label == "生成表格与图表"][0].click()
        page.run()
        self.assertEqual(len(page.exception), 0)
        assets = page.session_state['performance_last_result']['assets']
        self.assertEqual(assets[0], first['name'])
        self.assertNotIn(ui.comparison_label(first), assets)
        self.assertIn(ui.comparison_label(second), assets)
        self.assertEqual(core.get("snapshot"), before)
        self.assertEqual(core.active_strategy()["id"], "default")
        self.assertEqual(len(core.trades()), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
