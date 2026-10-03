"""Tests of causality, execution and accounting; not fitted return assertions."""
import unittest
from pathlib import Path
from dataclasses import replace
import numpy as np
import pandas as pd
from strategy import Config, load_data, generate_signals
from engine import simulate, rebalance


class AccountingTests(unittest.TestCase):
    def test_fee_conservation_buy_sell_switch(self):
        for current in (0., 25_000., 90_000.):
            for weight in (0., .5, .99, 1.):
                for same in (True, False):
                    after, target, fee, volume = rebalance(100_000., current, same, weight, .001)
                    self.assertAlmostEqual(after + fee, 100_000., places=7)
                    self.assertAlmostEqual(fee, volume * .001, places=7)
                    self.assertAlmostEqual(target / after, weight)
                    self.assertGreaterEqual(after - target, 0.)

    def test_invalid_financing_target_rejected(self):
        with self.assertRaises(ValueError):
            rebalance(100., 0., True, 1.1, .001)

    def test_constant_price_once_only_fee(self):
        dates = pd.bdate_range("2020-01-01", periods=8)
        f = pd.DataFrame({"adj_open": 10., "adj_close": 10., "adj_high": 10., "adj_low": 10.}, index=dates)
        s = pd.DataFrame({"symbol": "SOXL", "weight": .99}, index=dates)
        n, t = simulate({"SOXL": f}, s, start=str(dates[1].date()), end=str(dates[-1].date()))
        self.assertEqual(len(t), 1)
        np.testing.assert_allclose(n.equity, 100_000 / (1 + .001 * .99))

    def test_next_open_cannot_receive_previous_overnight_gain(self):
        dates = pd.bdate_range("2020-01-01", periods=4)
        p = [10., 20., 20., 20.]
        f = pd.DataFrame({k: p for k in ("adj_open", "adj_close", "adj_high", "adj_low")}, index=dates)
        s = pd.DataFrame({"symbol": "SOXL", "weight": 1.}, index=dates)
        n, t = simulate({"SOXL": f}, s, start=str(dates[1].date()), end=str(dates[-1].date()), cost_bps=0.)
        np.testing.assert_allclose(n.equity, 100_000.)
        self.assertTrue((t.signal_date < t.date).all())

    def test_held_asset_receives_overnight_and_session_return(self):
        dates = pd.bdate_range("2020-01-01", periods=4)
        o, c = [10., 10., 20., 30.], [10., 15., 30., 40.]
        f = pd.DataFrame({"adj_open": o, "adj_close": c, "adj_high": c, "adj_low": o}, index=dates)
        s = pd.DataFrame({"symbol": "SOXL", "weight": 1.}, index=dates)
        n, _ = simulate({"SOXL": f}, s, start=str(dates[1].date()), end=str(dates[-1].date()), cost_bps=0.)
        np.testing.assert_allclose(n.equity, [150_000., 300_000., 400_000.])

    def test_rebalance_is_on_target_change_not_daily_drift(self):
        dates = pd.bdate_range("2020-01-01", periods=4)
        p = [10., 10., 20., 40.]
        f = pd.DataFrame({k: p for k in ("adj_open", "adj_close", "adj_high", "adj_low")}, index=dates)
        s = pd.DataFrame({"symbol": "SOXL", "weight": .5}, index=dates)
        n, t = simulate({"SOXL": f}, s, start=str(dates[1].date()), end=str(dates[-1].date()), cost_bps=0.)
        self.assertEqual(len(t), 1)
        self.assertAlmostEqual(n.asset_weight.iloc[-1], .8)


class RealDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames, cls.audit = load_data(Path(__file__).parent / "data")
        cls.signals = generate_signals(cls.frames)

    def test_future_data_changes_do_not_change_past_signals(self):
        cutoff = pd.Timestamp("2020-12-31")
        altered = {k: v.copy() for k, v in self.frames.items()}
        for f in altered.values():
            fields = [k for k in f.columns if k != "volume"]
            f.loc[f.index > cutoff, fields] *= 8
            f.loc[f.index > cutoff, "volume"] *= 20
        new = generate_signals(altered)
        pd.testing.assert_frame_equal(new.loc[:cutoff], self.signals.loc[:cutoff])

    def test_truncating_future_data_keeps_signal_prefix(self):
        cutoff = pd.Timestamp("2021-12-31")
        truncated = {k: v.loc[:cutoff] for k, v in self.frames.items()}
        pd.testing.assert_frame_equal(generate_signals(truncated), self.signals.loc[:cutoff])

    def test_all_main_orders_follow_signal_dates(self):
        n, t = simulate(self.frames, self.signals)
        self.assertTrue((t.signal_date < t.date).all())
        self.assertGreaterEqual(n.cash.min(), 0.)
        self.assertTrue((n.equity > 0).all())

    def test_peak_never_rolls_down(self):
        self.assertTrue((self.signals.anchored_peak.diff().dropna() >= 0).all())

    def test_macro_buffer_holds_previous_regime(self):
        s = self.signals
        ratio = s.qqq_close / s.qqq_annual
        for i in range(1, len(s)):
            if .99 <= ratio.iloc[i] <= 1.01:
                self.assertEqual(s.regime.iloc[i], s.regime.iloc[i - 1])

    def test_macro_switch_resets_prior_top_lock(self):
        s = self.signals
        rows = s[s.regime_switch & ~s.top_trigger]
        self.assertFalse(rows.top_locked.any())

    def test_seed_uses_only_previous_252_observations(self):
        first = self.signals.index[0]
        seed = self.frames["XSD"].loc[:first].tail(252).high.max()
        self.assertAlmostEqual(self.signals.anchored_peak.iloc[0], seed)


class StateMachineTests(unittest.TestCase):
    def fixture(self):
        dates = pd.bdate_range("2014-01-01", periods=280)
        def frame(price):
            f = pd.DataFrame({k: float(price) for k in ("open", "high", "low", "close")}, index=dates)
            f["volume"] = 100.
            for field in ("open", "high", "low", "close"):
                f[f"adj_{field}"] = f[field]
            return f
        return dates, {"QQQ": frame(100), "XSD": frame(100), "SOXL": frame(10)}

    def test_top_lock_blocks_high_level_reentry(self):
        dates, f = self.fixture()
        f["XSD"].loc[dates[269], ["close", "low"]] = 97.
        f["XSD"].loc[dates[269], "volume"] = 400.
        s = generate_signals(f, str(dates[270].date()))
        self.assertTrue(s.top_trigger.iloc[0])
        self.assertEqual(s.state.iloc[1], "TOP_DEFENSE")
        self.assertEqual(s.symbol.iloc[1], "XSD")

    def test_deep_attack_has_priority_over_falling_short_ma(self):
        dates, f = self.fixture()
        f["QQQ"].loc[dates[269]:, ["open", "high", "low", "close"]] = 80.
        f["XSD"].loc[dates[269]:, ["open", "high", "low", "close"]] = 69.
        s = generate_signals(f, str(dates[270].date()))
        self.assertEqual(s.regime.iloc[0], "BEAR")
        self.assertEqual(s.state.iloc[0], "DEEP_ATTACK")
        self.assertEqual(s.symbol.iloc[0], "SOXL")

    def test_shallow_annual_break_is_cash(self):
        dates, f = self.fixture()
        f["XSD"].loc[dates[269]:, ["open", "high", "low", "close"]] = 90.
        s = generate_signals(f, str(dates[270].date()))
        self.assertEqual(s.state.iloc[0], "BREAK_CASH")
        self.assertEqual(s.weight.iloc[0], 0.)


if __name__ == "__main__":
    unittest.main(verbosity=2)
