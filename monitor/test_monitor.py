"""Financial-state, market-calendar, persistence and UI smoke checks."""
from datetime import datetime, timezone
from pathlib import Path
import copy
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from pandas.testing import assert_frame_equal

import core


class MonitorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames, _ = core.baseline.load_data(core.FROZEN / "data")
        cls.bundle = {sym: json.loads((core.FROZEN / "data" / f"{sym}.json").read_text(encoding="utf-8")) for sym in core.TICKERS}
        cls.signals = core.replay(cls.frames, core.default_strategy())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime_patch = patch.object(core, "RUNTIME", Path(self.temp.name))
        self.db_patch = patch.object(core, "DB", Path(self.temp.name) / "test.db")
        self.runtime_patch.start()
        self.db_patch.start()
        core.init_db()
        core.put("desktop_notifications", False)
        core.put("confirmed_bundle", self.bundle)
        core.put("snapshot", core.pack(self.frames, self.signals, "原回测冻结快照"))

    def tearDown(self):
        self.db_patch.stop()
        self.runtime_patch.stop()
        self.temp.cleanup()

    def test_full_original_history_parity(self):
        original = pd.read_csv(core.FROZEN / "signals.csv", parse_dates=["signal_date"], index_col="signal_date")
        original.index.name = "date"
        original.index = original.index.as_unit("s")
        original["reason"] = original["reason"].fillna("")
        legacy=core.make_strategy('冻结99%参考',core.baseline.Config().to_dict())
        assert_frame_equal(core.replay(self.frames,legacy),original,check_freq=False,check_exact=False,atol=1e-10,rtol=1e-12)
        original['weight']=original.weight.mask(original.weight.eq(.99),1.)
        assert_frame_equal(self.signals, original, check_freq=False, check_exact=False, atol=1e-10, rtol=1e-12)
        # The live feed's 2015 warm-up must produce the identical 2017-onward
        # state sequence, including the anchored peak and all path-dependent locks.
        online = core.replay({sym: frame.loc["2015-01-01":] for sym, frame in self.frames.items()}, core.default_strategy())
        assert_frame_equal(online, original, check_freq=False, check_exact=False, atol=1e-10, rtol=1e-12)

    def test_frozen_source_and_data_unchanged(self):
        hashes = json.loads((core.ROOT / "frozen_file_hashes.json").read_text(encoding="utf-8"))
        for path, sha in hashes.items():
            self.assertEqual(hashlib.sha256((core.FROZEN / path).read_bytes()).hexdigest(), sha)

    def test_close_grace_period(self):
        before = core.market_clock("2026-10-02T19:59:00+00:00")
        waiting = core.market_clock("2026-10-02T20:19:00+00:00")
        after = core.market_clock("2026-10-02T20:20:00+00:00")
        self.assertTrue(before["is_open"])
        self.assertEqual(before["expected_date"], "2026-10-01")
        self.assertTrue(waiting["waiting_close"])
        self.assertEqual(after["expected_date"], "2026-10-02")

    def test_weekend_holiday_and_daylight_saving(self):
        weekend = core.market_clock("2026-10-03T12:00:00+00:00")
        self.assertFalse(weekend["is_open"])
        self.assertEqual(weekend["next_open"], "2026-10-05T13:30:00+00:00")
        holiday = core.market_clock("2026-11-26T16:00:00+00:00")
        self.assertFalse(holiday["is_open"])
        self.assertEqual(holiday["next_open"], "2026-11-27T14:30:00+00:00")
        self.assertEqual(core.calendar(2026).session_close("2026-11-27").isoformat(), "2026-11-27T18:00:00+00:00")

    def intraday_bundle(self):
        bundle = copy.deepcopy(self.bundle)
        timestamp = int(pd.Timestamp("2026-10-02T13:30:00Z").timestamp())
        for sym, payload in bundle.items():
            r = payload["chart"]["result"][0]
            r["timestamp"].append(timestamp)
            q = r["indicators"]["quote"][0]
            for key, values in q.items():
                values.append(values[-1])
            adj = r["indicators"]["adjclose"][0]["adjclose"]
            adj.append(adj[-1])
            r["meta"]["regularMarketTime"] = int(pd.Timestamp("2026-10-02T15:00:00Z").timestamp())
        return bundle

    def test_intraday_isolation_and_close_filter(self):
        before = core.get("snapshot")
        confirmed = core.get("confirmed_bundle")
        bundle = self.intraday_bundle()
        result = core.preview_from_bundle(bundle, "2026-10-02T15:00:00Z")
        self.assertEqual(result["last"]["date"], "2026-10-02")
        self.assertEqual(core.get("snapshot"), before)
        self.assertEqual(core.get("confirmed_bundle"), confirmed)
        frames = core.load_bundle(bundle, "2026-10-01")
        self.assertEqual(str(frames["XSD"].index[-1].date()), "2026-10-01")

    def test_invalid_or_stale_intraday_not_executable(self):
        bundle = self.intraday_bundle()
        bundle["XSD"]["chart"]["result"][0]["indicators"]["quote"][0]["close"][-1] = None
        self.assertIsNone(core.preview_from_bundle(bundle, "2026-10-02T15:00:00Z"))
        bundle = self.intraday_bundle()
        self.assertIsNone(core.preview_from_bundle(bundle, "2026-10-02T15:31:00Z"))
        self.assertIsNone(core.preview_from_bundle(bundle, "2026-10-03T15:00:00Z"))

    def test_missing_session_and_provider_failure_preserve_confirmation(self):
        before = core.get("snapshot")
        frames = dict(self.frames)
        frames["SOXL"] = frames["SOXL"].iloc[:-1]
        with self.assertRaises(ValueError):
            core.validate_sessions(frames, "2026-10-01")
        with patch.object(core, "fetch_bundle", side_effect=RuntimeError("测试连接失败")):
            with self.assertRaises(RuntimeError):
                core.refresh_full()
        self.assertEqual(before, core.get("snapshot"))

    def test_target_changes_only_and_alert_deduplication(self):
        original = core.get("snapshot")["last"]
        alternate = dict(original, state="DEEP_ATTACK")
        self.assertFalse(core.target_changed(original, alternate))
        changed = self.signals.copy()
        changed.loc[changed.index[-1], "symbol"] = "XSD"
        changed.loc[changed.index[-1], "weight"] = .9
        changed.loc[changed.index[-1], "state"] = "TOP_DEFENSE"
        with patch.object(core, "replay", return_value=changed), patch.object(core, "notify") as notify:
            core.commit_confirmed(self.frames, self.bundle, core.iso_now())
            core.commit_confirmed(self.frames, self.bundle, core.iso_now())
            self.assertEqual(notify.call_count, 1)
        self.assertEqual(len(core.events()), 1)

    def test_persistent_trade_and_validation(self):
        with self.assertRaises(ValueError):
            core.add_trade("2026-10-02", "SOXL", "", "买入", 1, 100, 0, "USDC", "")
        core.add_trade("2026-10-02", "SOXL", "仅测试台账", "买入", 1, 100, 0, "USDC", "测试数据仅存在临时数据库")
        self.assertEqual(len(core.trades()), 1)
        self.assertEqual(core.trades().iloc[0].currency, "USDC")
        self.assertTrue(core.event("测试", "测试", "测试", "dedup-test"))
        self.assertFalse(core.event("测试", "测试", "测试", "dedup-test"))

    def test_streamlit_initial_page_and_invalid_form(self):
        from streamlit.testing.v1 import AppTest
        with patch.object(core, "notify"):
            page = AppTest.from_file(str(core.ROOT / "app.py"), default_timeout=30).run()
            self.assertEqual(len(page.exception), 0)
            save = [button for button in page.button if button.label == "保存成交记录"][0]
            save.click().run()
            self.assertEqual(len(page.exception), 0)
            self.assertEqual(len(core.trades()), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
