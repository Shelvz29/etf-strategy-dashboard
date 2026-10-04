"""Version persistence, activation isolation, cache identity and rule/UI consistency."""
from pathlib import Path
import copy
import json
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import core
import code_strategy as cs
import performance as perf
import state_ui


class StrategyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames, _ = core.baseline.load_data(core.FROZEN / "data")
        cls.bundle = {s: json.loads((core.FROZEN / "data" / f"{s}.json").read_text(encoding="utf-8")) for s in core.TICKERS}
        cls.default = core.default_strategy()
        cls.signals = core.replay(cls.frames, cls.default)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(core, "RUNTIME", Path(self.temp.name)), patch.object(core, "DB", Path(self.temp.name) / "test.db")]
        for item in self.patches:
            item.start()
        core.init_db()
        core.put("desktop_notifications", False)
        core.put("confirmed_bundle", self.bundle)
        core.put("snapshot", core.pack(self.frames, self.signals, "原回测冻结快照", profile=self.default))

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def custom(self, name="测试组合", **parameters):
        cfg = dict(self.default["parameters"], **parameters)
        return core.save_strategy(name, cfg)

    def test_draft_persistence_and_builtin_protection(self):
        before = core.get("snapshot")
        new = self.custom(attack=.6)
        self.assertEqual(core.strategy_version(new["id"]), new)
        self.assertEqual(core.get("snapshot"), before)
        self.assertEqual(core.active_strategy(), self.default)
        with self.assertRaises(ValueError):
            core.save_strategy("改写内置", new["parameters"], strategy_id="default", expected_revision=1)
        self.assertEqual(core.strategy_version("default"), self.default)

    def test_invalid_rules_names_and_duplicate_are_atomic(self):
        invalid = [{"attack": 1.2}, {"annual_days": True}, {"short_days": 252}, {"deep_bull": .10},
                   {"macro_buffer": float("nan")}, {"deep_latch": "yes"}, {"top_release": "exec"}, {"macro_annual_days": 1}]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.custom(**changes)
        with self.assertRaises(ValueError):
            self.custom(name="QQQ")
        self.custom()
        with self.assertRaises(ValueError):
            self.custom()
        self.assertEqual(len(core.list_strategies()), 2)
        self.assertEqual(len(core.strategy_history("default")), 1)

    def test_activation_updates_signal_history_and_backtest_name(self):
        custom = self.custom("自定义组合", attack=.6, annual_days=200, short_days=35)
        with patch.object(core, "notify") as notify:
            snap = core.activate_strategy(custom["id"])
            notify.assert_not_called()
        self.assertEqual(core.active_strategy()["fingerprint"], snap["strategy"]["fingerprint"])
        self.assertEqual(snap["strategy"]["name"], "自定义组合")
        frames, signals, _, _ = perf.datasets(self.bundle, "2026-10-01", [], profile=custom)
        full = perf.full_strategy(frames, signals)
        original = perf.full_strategy(self.frames, self.signals)
        self.assertFalse(np.allclose(full, original))
        result = perf.report(frames, signals, [], "近1年")
        self.assertEqual(list(result["results"]), [custom["name"]])
        self.assertEqual(snap["last"]["weight"], signals.iloc[-1].weight)
        self.assertEqual(len(core.trades()), 0)

    def test_save_new_revision_does_not_activate_and_can_restore(self):
        first = self.custom()
        core.activate_strategy(first["id"])
        second = core.save_strategy("已改名组合", dict(first["parameters"], attack=.4), strategy_id=first["id"], expected_revision=1)
        self.assertEqual(second["revision"], 2)
        self.assertEqual(core.active_strategy()["name"], first["name"])
        core.activate_strategy(first["id"], 2)
        self.assertEqual(core.get("snapshot")["strategy"]["name"], second["name"])
        core.activate_strategy(first["id"], 1)
        self.assertEqual(core.active_strategy(), first)
        self.assertEqual(core.strategy_version(first["id"]), second)
        with self.assertRaises(core.StrategyChanged):
            core.save_strategy("过期提交", first["parameters"], strategy_id=first["id"], expected_revision=1)

    def test_activation_failure_preserves_confirmed_snapshot(self):
        custom = self.custom()
        before = core.get("snapshot")
        with patch.object(core, "replay", side_effect=ValueError("预热行情不足")):
            with self.assertRaises(ValueError):
                core.activate_strategy(custom["id"])
        self.assertEqual(core.active_strategy(), self.default)
        self.assertEqual(core.get("snapshot"), before)

    def test_old_worker_cannot_overwrite_new_strategy(self):
        custom = self.custom(attack=.5)
        core.activate_strategy(custom["id"])
        before = core.get("snapshot")
        with self.assertRaises(core.StrategyChanged):
            core.commit_confirmed(self.frames, self.bundle, core.iso_now(), profile=self.default)
        self.assertEqual(core.get("snapshot"), before)

    def test_activation_retries_on_concurrent_input_change(self):
        custom = self.custom()
        pack = core.pack
        calls = []
        def interleave(*args, **kwargs):
            calls.append(1)
            result = pack(*args, **kwargs)
            if len(calls) == 1:
                concurrent = copy.deepcopy(core.get("snapshot"))
                concurrent["generated"] = core.iso_now()
                core.put("snapshot", concurrent)
            return result
        with patch.object(core, "pack", side_effect=interleave):
            result = core.activate_strategy(custom["id"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["strategy"], custom)

    def test_dynamic_state_explanation_and_name_only_cache_identity(self):
        custom = self.custom(annual_days=200, short_days=35, attack=.755, bull_defense=.8,
                             top_release="annual_only", cooldown_mode="below_annual_days", deep_latch=True)
        text = state_ui.state_details(custom)
        self.assertIn("35日线", text["RECOVERY_ATTACK"]["condition"])
        self.assertIn("连续位于年线下方", text["RECOVERY_ATTACK"]["condition"])
        self.assertIn("锁定", text["DEEP_ATTACK"]["condition"])
        self.assertIn("75.5%", text["NORMAL_ATTACK"]["target"])
        renamed = core.save_strategy("改名版本", custom["parameters"], strategy_id=custom["id"], expected_revision=1)
        self.assertNotEqual(custom["fingerprint"], renamed["fingerprint"])

    def test_maximum_periods_have_enough_live_warmup(self):
        custom = self.custom(annual_days=500, short_days=499, macro_annual_days=500, volume_days=500)
        online = {symbol: frame.loc["2015-01-01":] for symbol, frame in self.frames.items()}
        signals = core.replay(online, custom)
        self.assertEqual(len(signals), len(self.signals))
        self.assertFalse(signals.isna().any().any())

    def test_adjusted_preview_uses_provider_price_and_checks_revision(self):
        from test_monitor import MonitorTests
        helper = MonitorTests()
        helper.bundle = self.bundle
        intraday = helper.intraday_bundle()
        custom = self.custom(signal_adjusted=True)
        core.activate_strategy(custom["id"])
        r = intraday["XSD"]["chart"]["result"][0]
        prices = r["indicators"]["adjclose"][0]["adjclose"]
        prices[-1] *= .97
        preview = core.preview_from_bundle(intraday, "2026-10-02T15:00:00Z")
        self.assertAlmostEqual(preview["last"]["xsd_close"], prices[-1])
        prices[-2] *= .97
        self.assertIsNone(core.preview_from_bundle(intraday, "2026-10-02T15:00:00Z"))

    def test_editor_code_save_activate_rename_and_independent_calculator(self):
        from streamlit.testing.v1 import AppTest
        page = AppTest.from_string("import core, strategy_ui\nstrategy_ui.render(core.get('snapshot'))", default_timeout=30).run()
        [w for w in page.text_input if w.label == "策略名称"][0].set_value("页面自定义组合")
        code = [w for w in page.text_area if w.label == "策略代码（Python）"][0]
        code.set_value(code.value.replace("'attack': 1.0", "'attack': 0.7"))
        [b for b in page.button if b.label == "仅保存代码"][0].click().run()
        self.assertEqual(len(page.exception), 0)
        saved = core.list_strategies()[-1]
        self.assertEqual(saved["parameters"]["attack"], .7)
        self.assertEqual(core.active_strategy(), self.default)
        [b for b in page.button if b.label == "启用选中已保存策略"][0].click().run()
        self.assertEqual(len(page.exception), 0)
        self.assertEqual(core.active_strategy()["name"], "页面自定义组合")
        calculator = AppTest.from_string("import core, performance_ui\nperformance_ui.render(core.get('snapshot'))", default_timeout=30).run()
        self.assertEqual(len(calculator.exception), 0)
        self.assertEqual(calculator.session_state["performance_last_result"]["assets"][0], "页面自定义组合")
        [w for w in page.text_input if w.label == "策略名称"][0].set_value("页面改名组合")
        [b for b in page.button if b.label == "应用代码（保存并启用）"][0].click().run()
        self.assertEqual(len(page.exception), 0)
        self.assertEqual(core.active_strategy()["name"], "页面改名组合")
        calculator.run()
        self.assertEqual(len(calculator.exception), 0)
        self.assertEqual(calculator.session_state["performance_last_result"]["assets"][0], "页面改名组合")
        before = core.get("snapshot")
        [w for w in calculator.selectbox if w.label == "回测策略"][0].set_value(f"default:{self.default['revision']}")
        [b for b in calculator.button if b.label == "生成表格与图表"][0].click().run()
        self.assertEqual(len(calculator.exception), 0)
        self.assertEqual(calculator.session_state["performance_last_result"]["assets"][0], core.STRATEGY_NAME)
        self.assertEqual(core.get("snapshot"), before)
        shell = AppTest.from_file(str(core.ROOT / "app.py"), default_timeout=30).run()
        self.assertEqual(len(shell.exception), 0)
        self.assertEqual(shell.title[0].value, "页面改名组合")
        self.assertEqual(len(core.trades()), 0)

    def test_code_template_preserves_full_signal_and_performance_history(self):
        source = core.strategy_code(self.default)
        profile = core.make_strategy("完整代码复现", code=source)
        signals = core.replay(self.frames, profile, audit_code=True)
        pd.testing.assert_frame_equal(signals, self.signals, check_dtype=False)
        np.testing.assert_allclose(perf.full_strategy(self.frames, signals), perf.full_strategy(self.frames, self.signals), rtol=1e-12)

    def test_logic_change_executes_with_unchanged_parameters_and_custom_state(self):
        source = core.strategy_code(self.default).replace(
            '"NORMAL_ATTACK", "SOXL", cfg.attack', '"CUSTOM_HOLD", "XSD", 0.42')
        source = source.replace("STATE_LABELS = {}", "STATE_LABELS = {'CUSTOM_HOLD': '自定义低仓位'}").replace(
            "STATE_NOTES = {}", "STATE_NOTES = {'CUSTOM_HOLD': '偏牛且站上年线时持有42%的XSD。'}")
        saved = core.save_strategy("代码逻辑变化", code=source)
        self.assertEqual(saved["parameters"], self.default["parameters"])
        snap = core.activate_strategy(saved["id"])
        changed = core.replay(self.frames, saved)
        mask = self.signals.state == "NORMAL_ATTACK"
        self.assertTrue((changed.loc[mask, "symbol"] == "XSD").all())
        self.assertTrue((changed.loc[mask, "weight"] == .42).all())
        self.assertFalse(np.allclose(perf.full_strategy(self.frames, changed), perf.full_strategy(self.frames, self.signals)))
        self.assertEqual(core.state_name("CUSTOM_HOLD", saved), "自定义低仓位")
        core.commit_confirmed(self.frames, self.bundle, core.iso_now(), profile=saved)
        from streamlit.testing.v1 import AppTest
        page = AppTest.from_file(str(core.ROOT / "app.py"), default_timeout=30).run()
        self.assertEqual(len(page.exception), 0)
        states = AppTest.from_string("import core, state_ui\nstate_ui.render(core.get('snapshot'))", default_timeout=30).run()
        self.assertEqual(len(states.exception), 0)
        self.assertEqual(snap["strategy"]["kind"], "python")

    def test_code_errors_do_not_save_or_switch_active_strategy(self):
        source = core.strategy_code(self.default)
        before = core.get("snapshot")
        cases = [source + "\nif broken\n", source.replace('    x, q = frames', '    result = 1 / 0\n    x, q = frames'),
                 source.replace('cfg.attack', '1.5'), source.replace('cfg.attack', 'float("nan")'),
                 source.replace('return pd.DataFrame(rows).set_index("date")', 'return pd.DataFrame(rows).set_index("date").iloc[:-1]')]
        for code in cases:
            with self.subTest(code=cs.code_hash(code)), self.assertRaises(ValueError):
                core.save_strategy("不能保存", code=code)
            self.assertEqual(core.get("snapshot"), before)
            self.assertEqual(core.active_strategy(), self.default)
            self.assertEqual(len(core.list_strategies()), 1)
        with self.assertRaisesRegex(ValueError, "第.*行"):
            core.replay(self.frames, core.make_strategy("报错行号", code=cases[1]))

    def test_code_future_leak_is_rejected(self):
        source = core.strategy_code(self.default).replace('peak = float(np.max(seed[first_loc - 251:first_loc + 1]))', 'peak = float(np.max(c))')
        candidate = core.make_strategy("未来峰值", code=source)
        with self.assertRaisesRegex(ValueError, "历史信号发生变化"):
            core.replay(self.frames, candidate, audit_code=True)
        with self.assertRaises(ValueError):
            core.save_strategy(candidate["name"], code=source)
        self.assertEqual(core.active_strategy(), self.default)

    def test_code_import_io_restrictions_and_timeout(self):
        source = core.strategy_code(self.default)
        for suffix in ["\nimport os\n", "\nopen('file.txt', 'w')\n", "\npd.read_csv('file.csv')\n", "\nnp.ctypeslib.load_library('x', '.')\n"]:
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                cs.check_source(source + suffix)
        infinite = source.replace('    x, q = frames', '    while True:\n        pass\n    x, q = frames')
        with self.assertRaisesRegex(ValueError, "时间限制"):
            cs.evaluate(infinite, self.frames, timeout=2)
        self.assertEqual(core.active_strategy(), self.default)

    def test_code_revision_restore_and_fingerprint_tracks_logic(self):
        source = core.strategy_code(self.default)
        first = core.save_strategy("代码版本", code=source)
        changed_source = source.replace('"NORMAL_ATTACK", "SOXL", cfg.attack', '"NORMAL_ATTACK", "XSD", 0.4')
        second = core.save_strategy(first["name"], code=changed_source, strategy_id=first["id"], expected_revision=1)
        self.assertNotEqual(first["code_hash"], second["code_hash"])
        self.assertNotEqual(first["fingerprint"], second["fingerprint"])
        core.activate_strategy(first["id"], 1)
        self.assertEqual(core.active_strategy()["code"], source)
        core.activate_strategy(first["id"], 2)
        self.assertEqual(core.active_strategy()["code"], changed_source)

    def test_backtest_can_select_unactivated_saved_code_version(self):
        source = core.strategy_code(self.default).replace('"NORMAL_ATTACK", "SOXL", cfg.attack', '"NORMAL_ATTACK", "XSD", 0.4')
        saved = core.save_strategy("只回测代码", code=source)
        before = core.get("snapshot")
        from streamlit.testing.v1 import AppTest
        page = AppTest.from_string("import core, performance_ui\nperformance_ui.render(core.get('snapshot'))", default_timeout=30).run()
        [w for w in page.selectbox if w.label == "回测策略"][0].set_value(f"{saved['id']}:1")
        [b for b in page.button if b.label == "生成表格与图表"][0].click().run()
        self.assertEqual(len(page.exception), 0)
        self.assertEqual(page.session_state["performance_last_result"]["assets"][0], saved["name"])
        self.assertEqual(page.session_state["performance_last_result"]["fingerprint"], saved["fingerprint"])
        self.assertEqual(core.active_strategy(), self.default)
        self.assertEqual(core.get("snapshot"), before)

    def test_editor_rejects_bad_code_without_losing_draft(self):
        from streamlit.testing.v1 import AppTest
        page = AppTest.from_string("import core, strategy_ui\nstrategy_ui.render(core.get('snapshot'))", default_timeout=30).run()
        code = [w for w in page.text_area if w.label == "策略代码（Python）"][0]
        invalid = code.value + "\nif broken\n"
        code.set_value(invalid)
        [b for b in page.button if b.label == "应用代码（保存并启用）"][0].click().run()
        self.assertEqual(len(page.exception), 0)
        self.assertTrue(page.error)
        self.assertEqual([w for w in page.text_area if w.label == "策略代码（Python）"][0].value, invalid)
        self.assertEqual(core.active_strategy(), self.default)
        self.assertEqual(len(core.list_strategies()), 1)

    def test_card_metrics_match_backtest_for_original_and_replacement(self):
        import strategy_ui
        from export_strategies import replacement_code
        payload = self.cache_replacement("SMH")
        profiles = [self.default, core.make_strategy("SMH卡片", code=replacement_code("SMH"))]
        for profile in profiles:
            with self.subTest(base=core.base_symbol(profile)):
                frames = core.load_bundle({**self.bundle, "SMH": payload}, "2026-10-01")
                signals = core.replay(frames, profile)
                expected = perf.report(frames, signals, [], "全部历史")["periods"].set_index("period")
                actual = strategy_ui.strategy_card_report(self.bundle, "2026-10-01", profile).set_index("period")
                self.assertEqual(actual.index.tolist(), list(strategy_ui.CARD_PERIODS))
                np.testing.assert_allclose(actual[["annualized_return", "max_drawdown"]],
                                           expected.loc[actual.index, ["annualized_return", "max_drawdown"]], rtol=1e-12)
                self.assertEqual(actual.loc["全部历史", "first_session"], "2017-01-03")
                self.assertTrue((actual.end_session == "2026-10-01").all())

    def test_card_selection_loads_saved_code_without_activation(self):
        from streamlit.testing.v1 import AppTest
        custom = self.custom("卡片低仓位", attack=.6)
        before = core.get("snapshot")
        page = AppTest.from_string("import core, strategy_ui\nstrategy_ui.render(core.get('snapshot'))", default_timeout=30).run()
        self.assertFalse(any(w.label == "选择要编辑的策略" for w in page.selectbox))
        page.button(key="select_card:" + custom["id"]).click().run()
        self.assertEqual(len(page.exception), 0)
        self.assertEqual(page.session_state["editor_profile"], custom["id"])
        self.assertEqual([w for w in page.text_area if w.label == "策略代码（Python）"][0].value,
                         core.strategy_code(custom))
        self.assertEqual([w for w in page.text_input if w.label == "策略名称"][0].value, custom["name"])
        self.assertEqual(core.active_strategy(), self.default)
        self.assertEqual(core.get("snapshot"), before)
        self.assertEqual(len(core.trades()), 0)

    def test_card_cache_tracks_same_day_price_corrections_and_code_revisions(self):
        import strategy_ui
        source = core.strategy_code(self.default)
        profile = core.make_strategy("卡片缓存", code=source)
        first = strategy_ui.strategy_card_report(self.bundle, "2026-10-01", profile)
        corrected = copy.deepcopy(self.bundle)
        adj = corrected["SOXL"]["chart"]["result"][0]["indicators"]["adjclose"][0]["adjclose"]
        adj[-1] *= 1.1
        changed_price = strategy_ui.strategy_card_report(corrected, "2026-10-01", profile)
        self.assertFalse(np.allclose(first.annualized_return, changed_price.annualized_return))
        changed = core.make_strategy(profile["name"], code=source.replace('"NORMAL_ATTACK", "SOXL", cfg.attack',
                                                                       '"NORMAL_ATTACK", "XSD", 0.4'))
        changed_code = strategy_ui.strategy_card_report(self.bundle, "2026-10-01", changed)
        self.assertFalse(np.allclose(first.annualized_return, changed_code.annualized_return))
        with self.assertRaisesRegex(ValueError, "最新确认收盘日"):
            strategy_ui.strategy_card_report(self.bundle, "2026-10-02", profile)

    def test_card_calculation_failure_isolated_from_other_cards_and_editor(self):
        import strategy_ui
        from streamlit.testing.v1 import AppTest
        custom = self.custom("故障卡片")
        original = strategy_ui.strategy_card_report
        def isolated(bundle, cutoff, profile):
            if profile["id"] == custom["id"]:
                raise ValueError("测试行情不完整")
            return original(bundle, cutoff, profile)
        with patch.object(strategy_ui, "strategy_card_report", side_effect=isolated):
            page = AppTest.from_string("import core, strategy_ui\nstrategy_ui.render(core.get('snapshot'))", default_timeout=30).run()
            self.assertEqual(len(page.exception), 0)
            self.assertTrue(any("测试行情不完整" in item.value for item in page.warning))
            self.assertEqual(len([w for w in page.text_area if w.label == "策略代码（Python）"]), 1)
            self.assertEqual(len([item for item in page.markdown if 'class="strategy-card-metrics"' in item.value]), 1)
            page.button(key="select_card:" + custom["id"]).click().run()
            self.assertEqual(len(page.exception), 0)
            self.assertEqual(page.session_state["editor_profile"], custom["id"])
        self.assertEqual(core.active_strategy(), self.default)

    def two_state_code(self):
        source = core.strategy_code(self.default)
        source = source.replace("STATE_LABELS = {}", "STATE_LABELS = {'ON': '持有', 'OFF': '观望'}")
        source = source.replace("STATE_NOTES = {}", "STATE_NOTES = {'ON': '按代码持有进攻目标。', 'OFF': '按代码防御或等待。'}")
        return source.replace('return pd.DataFrame(rows).set_index("date")',
                              'result = pd.DataFrame(rows).set_index("date")\n'
                              '    result["state"] = np.where(result.symbol == "SOXL", "ON", "OFF")\n'
                              '    return result')

    def test_state_catalog_does_not_mix_in_builtin_eight_states(self):
        import strategy_states as states
        profile = core.make_strategy("两种状态", code=self.two_state_code())
        signals = core.replay(self.frames, profile, audit_code=True)
        rows = states.definitions(profile, signals.state.unique())
        self.assertEqual([row["code"] for row in rows], ["ON", "OFF"])
        observed = states.definitions(profile, ["ON", "OFF", "EARLY_ONLY"])
        self.assertEqual([row["code"] for row in observed], ["ON", "OFF", "EARLY_ONLY"])
        self.assertEqual(observed[-1]["note"], "")
        self.assertEqual(len(states.definitions(self.default)), 8)

    def test_state_metadata_edit_preserves_rule_code_unicode_and_comments(self):
        import ast
        import strategy_states as states
        source = core.strategy_code(self.default).replace("STATE_LABELS = {}", "中文变量 = 1; STATE_LABELS = {}  # 保留中文注释")
        updated = states.replace_metadata(source, {"ON": "持有"}, {"ON": "第一行\n第二行：'引号'和中文"})
        self.assertIn("中文变量 = 1; STATE_LABELS", updated)
        self.assertIn("# 保留中文注释", updated)
        self.assertEqual(cs.check_source(updated)["STATE_NOTES"]["ON"], "第一行\n第二行：'引号'和中文")
        fn = lambda text: next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == "generate_signals")
        self.assertEqual(ast.dump(fn(source)), ast.dump(fn(updated)))
        absent = source.replace("STATE_NOTES = {}", "")
        self.assertEqual(cs.check_source(states.replace_metadata(absent, {}, {"OFF": "等待"}))["STATE_NOTES"], {"OFF": "等待"})

    def test_state_editor_merges_changed_fields_without_overwriting_manual_code(self):
        import strategy_states as states
        profile = core.make_strategy("两状态编辑", code=self.two_state_code())
        defaults = states.definitions(profile, ["ON", "OFF"])
        direct = profile["code"].replace("按代码持有进攻目标。", "代码内的新解释。")
        merged = states.merge_editor_states(direct, defaults, defaults, profile)
        self.assertEqual(cs.check_source(merged)["STATE_NOTES"]["ON"], "代码内的新解释。")
        edited = copy.deepcopy(defaults)
        edited[0]["name"], edited[0]["note"] = "新的持有状态", "文本框的新解释。"
        edited[1]["remove"] = True
        merged = states.merge_editor_states(direct, defaults, edited, profile)
        metadata = cs.check_source(merged)
        self.assertEqual(metadata["STATE_LABELS"]["ON"], "新的持有状态")
        self.assertEqual(metadata["STATE_NOTES"]["ON"], "文本框的新解释。")
        self.assertNotIn("OFF", metadata["STATE_LABELS"])
        self.assertNotIn("OFF", metadata["STATE_NOTES"])
        signals = core.replay(self.frames, core.make_strategy("注释变更", code=merged), audit_code=True)
        self.assertIn("OFF", states.definitions(core.make_strategy("注释变更", code=merged), signals.state.unique())[-1]["code"])

    def test_state_editor_text_save_version_restore_and_current_highlight(self):
        from streamlit.testing.v1 import AppTest
        profile = core.save_strategy("两状态策略", code=self.two_state_code())
        before = core.get("snapshot")
        page = AppTest.from_string("import core, strategy_ui\nstrategy_ui.render(core.get('snapshot'))", default_timeout=30).run()
        page.button(key="select_card:" + profile["id"]).click().run()
        [w for w in page.text_input if w.label == "状态名称 · ON"][0].set_value("新的持有名称")
        [w for w in page.text_area if w.label == "状态解释 · ON"][0].set_value("收盘信号选择SOXL时显示此状态。")
        [w for w in page.button if w.label == "仅保存代码"][0].click().run()
        self.assertEqual(len(page.exception), 0)
        saved = core.strategy_version(profile["id"])
        self.assertEqual(saved["revision"], 2)
        self.assertEqual(saved["state_labels"]["ON"], "新的持有名称")
        self.assertEqual(saved["state_notes"]["ON"], "收盘信号选择SOXL时显示此状态。")
        self.assertEqual(core.get("snapshot"), before)
        snap = core.activate_strategy(profile["id"], 2)
        viewer = AppTest.from_string("import core, state_ui\nstate_ui.render(core.get('snapshot'))", default_timeout=30).run()
        self.assertEqual(len(viewer.exception), 0)
        cards = [item.value for item in viewer.markdown if '<div class="explanation-grid">' in item.value][0]
        self.assertEqual(cards.count('class="explanation-card'), 2)
        self.assertEqual(cards.count('explanation-card active'), 1)
        self.assertIn("新的持有名称", cards)
        self.assertNotIn("TOP_DEFENSE", cards)
        self.assertIn(snap["last"]["state"], cards)
        shell = AppTest.from_file(str(core.ROOT / "app.py"), default_timeout=30).run()
        self.assertIn("状态解释", [tab.label for tab in shell.tabs])
        self.assertNotIn("八种状态", [tab.label for tab in shell.tabs])
        core.activate_strategy(profile["id"], 1)
        self.assertEqual(core.active_strategy()["state_labels"]["ON"], "持有")
        self.assertEqual(len(core.trades()), 0)

    def test_state_editor_sync_add_and_preview_preserve_drafts_without_activation(self):
        from streamlit.testing.v1 import AppTest
        page = AppTest.from_string("import core, strategy_ui\nstrategy_ui.render(core.get('snapshot'))", default_timeout=30).run()
        [w for w in page.text_area if w.label == "策略代码（Python）"][0].set_value(self.two_state_code())
        [w for w in page.button if w.label == "从代码读取状态框"][0].click().run()
        self.assertEqual(len(page.exception), 0)
        self.assertEqual(len([w for w in page.text_area if w.label.startswith("状态解释 · ")]), 2)
        [w for w in page.text_input if w.label == "状态名称 · ON"][0].set_value("草稿持有")
        [w for w in page.text_input if w.label == "新状态标识"][0].set_value("WAIT")
        [w for w in page.button if w.label == "添加状态框"][0].click().run()
        self.assertEqual(len(page.exception), 0)
        self.assertEqual([w for w in page.text_input if w.label == "状态名称 · ON"][0].value, "草稿持有")
        [w for w in page.text_area if w.label == "状态解释 · WAIT"][0].set_value("未来可能触发的等待分支。")
        [w for w in page.button if w.label == "预览回测"][0].click().run()
        self.assertEqual(len(page.exception), 0)
        draft = page.session_state["editor_preview"]["profile"]
        self.assertEqual(draft["state_labels"]["ON"], "草稿持有")
        self.assertIn("WAIT", draft["state_labels"])
        self.assertEqual(draft["state_notes"]["WAIT"], "未来可能触发的等待分支。")
        self.assertEqual(core.active_strategy(), self.default)
        self.assertEqual(len(core.list_strategies()), 1)
        self.assertIn("草稿持有", [w for w in page.text_area if w.label == "策略代码（Python）"][0].value)

    def test_legacy_state_documentation_updates_parameter_thresholds(self):
        import strategy_states as states
        source = core.strategy_code(self.default).replace("'cash_drawdown': 0.15", "'cash_drawdown': 0.18")
        rows = states.definitions(self.default)
        updated = states.merge_editor_states(source, rows, rows, self.default)
        self.assertIn("18%", cs.check_source(updated)["STATE_NOTES"]["BREAK_CASH"])

    def replacement_payload(self, symbol, scale=1.7):
        payload = copy.deepcopy(self.bundle["XSD"])
        result = payload["chart"]["result"][0]
        result["meta"]["symbol"] = symbol
        quote = result["indicators"]["quote"][0]
        for key in ("open", "high", "low", "close"):
            quote[key] = [value * scale for value in quote[key]]
        adjusted = result["indicators"]["adjclose"][0]
        adjusted["adjclose"] = [value * scale for value in adjusted["adjclose"]]
        return payload

    def cache_replacement(self, symbol):
        payload = self.replacement_payload(symbol)
        perf.init_price_cache()
        with core.connect() as db:
            db.execute("INSERT INTO comparison_prices VALUES (?,?,?,?)", (symbol, "2026-10-01", core.iso_now(), core.json_dump(payload)))
        return payload

    def test_replacement_signal_input_and_defense_asset_are_both_replaced(self):
        from export_strategies import replacement_code
        for symbol in ("SMH", "SOXX"):
            with self.subTest(symbol=symbol):
                payload = self.cache_replacement(symbol)
                profile = core.make_strategy(symbol + "组合", code=replacement_code(symbol))
                with patch.object(core, "request_json", side_effect=AssertionError("must use cache")):
                    bundle = core.ensure_strategy_bundle(self.bundle, "2026-10-01", profile)
                    frames = core.load_bundle(bundle, "2026-10-01")
                    signals = core.replay(frames, profile, audit_code=True)
                self.assertEqual(profile["parameters"], self.default["parameters"])
                self.assertEqual(profile["base_symbol"], symbol)
                np.testing.assert_allclose(signals.xsd_close, self.signals.xsd_close * 1.7, rtol=1e-12)
                np.testing.assert_allclose(signals.peak_drawdown, self.signals.peak_drawdown, atol=1e-12)
                self.assertEqual(signals.state.tolist(), self.signals.state.tolist())
                self.assertEqual(signals.symbol.tolist(), self.signals.symbol.replace("XSD", symbol).tolist())
                snap = core.pack(frames, signals, "替换测试", profile=profile)
                self.assertIn(symbol, snap["chart"][-1])
                self.assertNotIn("XSD", snap["chart"][-1])
                self.assertIn(symbol, profile["state_notes"]["NORMAL_DEFENSE"])
                self.assertNotIn("XSD", profile["state_notes"]["NORMAL_DEFENSE"])
                # Scaled test prices have identical percentage returns; the
                # portfolio must therefore preserve the same economic result.
                np.testing.assert_allclose(perf.full_strategy(frames, signals), perf.full_strategy(self.frames, self.signals), rtol=1e-12)

    def test_replacement_activation_history_and_backtest_are_consistent(self):
        from export_strategies import replacement_code
        self.cache_replacement("SMH")
        profile = core.save_strategy("SMH切换", code=replacement_code("SMH"))
        snap = core.activate_strategy(profile["id"])
        self.assertIn("SMH", core.get("confirmed_bundle"))
        self.assertEqual(core.snapshot_strategy(snap)["base_symbol"], "SMH")
        from streamlit.testing.v1 import AppTest
        page = AppTest.from_file(str(core.ROOT / "app.py"), default_timeout=30).run()
        self.assertEqual(len(page.exception), 0)
        labels = [metric.label for metric in page.metric]
        self.assertTrue(any(label.startswith("SMH / 年线") for label in labels))
        self.assertFalse(any(label.startswith("XSD / 年线") for label in labels))
        frames, signals, errors, _ = perf.datasets(core.get("confirmed_bundle"), "2026-10-01", [], profile=profile)
        self.assertFalse(errors)
        result = perf.report(frames, signals, [], "近1年")
        self.assertEqual(list(result["results"]), [profile["name"]])
        self.assertEqual(core.get("snapshot"), snap)
        core.activate_strategy("default")
        self.assertEqual(core.get("snapshot")["strategy"]["id"], "default")

    def test_replacement_rejects_wrong_target_and_missing_market_data(self):
        from export_strategies import replacement_code
        profile = core.make_strategy("缺失SOXX", code=replacement_code("SOXX"))
        before = core.get("snapshot")
        with patch.object(core, "request_json", side_effect=RuntimeError("测试行情不可用")), self.assertRaises(ValueError):
            core.save_strategy(profile["name"], code=profile["code"])
        self.assertEqual(core.get("snapshot"), before)
        self.assertEqual(len(core.list_strategies()), 1)
        payload = self.cache_replacement("SOXX")
        frames = core.load_bundle({**self.bundle, "SOXX": payload}, "2026-10-01")
        wrong = profile["code"].replace('BASE_SYMBOL, defense', '"XSD", defense')
        with self.assertRaisesRegex(ValueError, "SOXX、SOXL、CASH"):
            core.replay(frames, core.make_strategy("错误防御标的", code=wrong))
        missing = dict(frames)
        missing["SOXX"] = frames["SOXX"].drop(frames["SOXX"].index[-2])
        with self.assertRaises(ValueError):
            core.replay(missing, profile)
        with self.assertRaises(ValueError):
            core.make_strategy("无效信号ETF", code=profile["code"].replace("BASE_SYMBOL = 'SOXX'", "BASE_SYMBOL = 'VGT'"))

    def test_replacement_intraday_preview_and_daily_fetch_use_new_base(self):
        from export_strategies import replacement_code
        from test_monitor import MonitorTests
        self.cache_replacement("SOXX")
        profile = core.save_strategy("SOXX盘中", code=replacement_code("SOXX"))
        core.activate_strategy(profile["id"])
        before, confirmed = core.get("snapshot"), core.get("confirmed_bundle")
        helper = MonitorTests()
        helper.bundle = confirmed
        intraday = helper.intraday_bundle()
        preview = core.preview_from_bundle(intraday, "2026-10-02T15:00:00Z")
        self.assertEqual(preview["last"]["date"], "2026-10-02")
        self.assertAlmostEqual(preview["last"]["xsd_close"], before["last"]["xsd_close"])
        self.assertEqual(core.get("snapshot"), before)
        self.assertEqual(core.get("confirmed_bundle"), confirmed)
        missing = dict(intraday)
        missing.pop("SOXX")
        self.assertIsNone(core.preview_from_bundle(missing, "2026-10-02T15:00:00Z"))
        with patch.object(core, "request_json", side_effect=lambda symbol, params: confirmed[symbol]) as fetch:
            fetched = core.fetch_bundle(True, "2026-10-01", profile=profile)
        self.assertEqual(set(fetched), {"QQQ", "XSD", "SOXL", "SOXX"})
        self.assertEqual(fetch.call_count, 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
