"""Editable source code, previews, saved versions and activation."""
import hashlib
import html

import pandas as pd
import streamlit as st

import core
import performance as perf
import strategy_states as states


CARD_PERIODS = ("全部历史", "近1年", "近2年", "近3年", "近5年")


@st.cache_data(max_entries=48, show_spinner=False)
def card_report(version, cutoff, _bundle, _profile):
    """Cache by saved code AND resolved quotes, including the replacement ETF."""
    frames = core.load_bundle(_bundle, cutoff)
    signals = core.replay(frames, _profile, audit_code=True)
    if str(signals.index[-1].date()) != cutoff:
        raise ValueError("策略日线尚未覆盖最新确认收盘日")
    result = perf.report(frames, signals, [], "全部历史", cost_bps=10.0)
    rows = result["periods"].set_index("period").reindex(CARD_PERIODS)
    first = rows.loc["全部历史", "first_session"]
    if pd.Timestamp(first) > perf.FIRST_TRADE:
        raise ValueError(f"行情历史从{first}开始，尚未覆盖2017年起的完整区间")
    rows = rows.reset_index()
    rows.attrs["state_codes"] = signals.state.drop_duplicates().tolist()
    rows.attrs["last_signal"] = core.signal_row(signals.index[-1], signals.iloc[-1])
    return rows


def strategy_card_report(bundle, cutoff, profile):
    resolved = core.ensure_strategy_bundle(bundle, cutoff, profile)
    # Only the actual input instruments matter; extra comparison ETFs should not
    # invalidate unrelated cards. Hash payloads before the cache boundary so that
    # a same-day corrected price, code revision or name change is reflected.
    required = tuple(dict.fromkeys([*core.TICKERS, *core.strategy_tickers(profile)]))
    resolved = {symbol: resolved[symbol] for symbol in required}
    version = hashlib.sha256(core.json_dump(resolved).encode()).hexdigest() + profile["fingerprint"]
    return card_report(version, cutoff, resolved, profile)


def pick_editor_strategy(strategy_id):
    st.session_state["editor_profile"] = strategy_id


def render_strategy_cards(profiles, active):
    latest, bundle = perf.confirmed_inputs()
    cutoff = latest["last"]["date"]
    selected = st.session_state["editor_profile"]
    selected_key = "strategy_card_" + hashlib.sha256(selected.encode()).hexdigest()[:16]
    st.markdown("""<style>
    [class*="st-key-strategy_card_"] {position:relative;background:var(--secondary-background-color,#fff);}
    [class*="st-key-strategy_card_"] > [data-testid="stElementContainer"] {position:static!important;}
    [class*="st-key-strategy_card_"] [data-testid="stButton"],
    [class*="st-key-strategy_card_"] button {position:static!important;}
    [class*="st-key-strategy_card_"] button {border:0;background:transparent;color:inherit;
        text-align:left;justify-content:flex-start;padding:0;min-height:44px;font-weight:650;box-shadow:none!important;}
    [class*="st-key-strategy_card_"] button p {text-align:left;}
    [class*="st-key-strategy_card_"] button::after {content:"";position:absolute;
        inset:0;z-index:1;cursor:pointer;border:2px solid transparent;border-radius:12px;}
    [class*="st-key-strategy_card_"] button:hover::after {border-color:#50a58d;}
    [class*="st-key-strategy_card_"] button:focus-visible::after {outline:3px solid #50a58d;outline-offset:3px;}
    .strategy-card-metrics {width:100%;border-collapse:collapse;font-size:14px;}
    .strategy-card-metrics th,.strategy-card-metrics td {padding:7px 3px;text-align:right;
        border-bottom:1px solid rgba(128,128,128,.18);font-variant-numeric:tabular-nums;}
    .strategy-card-metrics th:first-child,.strategy-card-metrics td:first-child {text-align:left;}
    .strategy-card-metrics tr:last-child td {border-bottom:0;}
    </style>""" + f"<style>.st-key-{selected_key} button::after {{border-color:#087c68;}}"
                  f".st-key-{selected_key} {{background:rgba(8,124,104,.06);}}</style>", unsafe_allow_html=True)
    st.markdown("**选择要编辑的策略**")
    st.caption(f"点击矩形卡片加载代码，不会启用策略。数据截至 {cutoff}（最新确认美股收盘）。"
               "2017-01-01起的首个交易日为2017-01-03；下表为年化收益与最大回撤。")
    st.caption("统一口径：历史连续持仓 · 收盘信号、下一交易日开盘执行 · 单边成本0.1%。"
               "近1／2／3／5年均截至同一确认日；回撤显示损失幅度。卡片预览已保存代码，编辑草稿请使用下方“预览回测”。")
    for offset in range(0, len(profiles), 3):
        columns = st.columns(3)
        for column, profile in zip(columns, profiles[offset:offset + 3]):
            key = "strategy_card_" + hashlib.sha256(profile["id"].encode()).hexdigest()[:16]
            with column, st.container(border=True, key=key):
                chosen = profile["id"] == selected
                st.button(f"{'✓ ' if chosen else ''}{profile['name']} · v{profile['revision']}",
                          key="select_card:" + profile["id"], width="stretch",
                          on_click=pick_editor_strategy, args=(profile["id"],))
                badges = ["已选中" if chosen else "点击选择"]
                if profile["fingerprint"] == active["fingerprint"]:
                    badges.append("当前启用")
                if profile["id"] == "default":
                    badges.append("内置")
                st.caption(" · ".join(badges))
                try:
                    rows = strategy_card_report(bundle, cutoff, profile)
                    cells = []
                    for row in rows.to_dict("records"):
                        label = "2017年至今" if row["period"] == "全部历史" else row["period"]
                        values = ["—" if pd.isna(row[field]) else f"{row[field]:.2%}"
                                  for field in ("annualized_return", "max_drawdown")]
                        cells.append(f"<tr><td>{html.escape(label)}</td><td>{values[0]}</td><td>{values[1]}</td></tr>")
                    st.markdown('<table class="strategy-card-metrics"><thead><tr><th>区间</th>'
                                '<th>年化收益</th><th>最大回撤</th></tr></thead><tbody>'
                                + "".join(cells) + '</tbody></table>', unsafe_allow_html=True)
                except (ValueError, RuntimeError, KeyError, TypeError) as exc:
                    st.warning(f"历史表现暂不可计算：{exc}")
    return selected


@st.cache_data(max_entries=16, show_spinner=False)
def preview_report(version, cost, _bundle, _snapshot, _profile):
    cutoff = _snapshot["last"]["date"]
    frames = core.load_bundle(core.ensure_strategy_bundle(_bundle, cutoff, _profile), cutoff)
    signals = core.replay(frames, _profile, audit_code=True)
    result = perf.report(frames, signals, [], "全部历史", cost_bps=cost)
    result["periods"].attrs["state_codes"] = signals.state.drop_duplicates().tolist()
    return result["periods"], core.signal_row(signals.index[-1], signals.iloc[-1])


def state_field_key(prefix, code, field):
    return prefix + "state:" + hashlib.sha256(code.encode()).hexdigest()[:16] + ":" + field


def load_state_fields(prefix, rows):
    st.session_state[prefix + "state_defaults"] = rows
    for row in rows:
        for field in ("name", "note"):
            st.session_state[state_field_key(prefix, row["code"], field)] = row[field]
        st.session_state[state_field_key(prefix, row["code"], "remove")] = False


def sync_state_fields(prefix):
    try:
        rows = states.source_definitions(st.session_state[prefix + "code"])
        load_state_fields(prefix, rows)
        st.session_state[prefix + "state_message"] = "已从当前代码读取状态框。未保存，未启用。"
    except (ValueError, SyntaxError) as exc:
        st.session_state[prefix + "state_message"] = f"未读取：{exc}。状态框和代码草稿已保留。"


def add_state_field(prefix):
    code = st.session_state[prefix + "new_state"].strip()
    rows = st.session_state[prefix + "state_defaults"]
    if not 1 <= len(code) <= 80 or any(ord(c) < 32 for c in code):
        st.session_state[prefix + "state_message"] = "新状态标识须为1至80个字符，不含换行。"
    elif code in {row["code"] for row in rows}:
        st.session_state[prefix + "state_message"] = f"{code}的状态框已存在。"
    elif len(rows) >= 40:
        st.session_state[prefix + "state_message"] = "每种策略最多维护40种状态说明。"
    else:
        # Preserve all existing drafts; initialize only the newly added box.
        row = {"code": code, "name": code, "note": "", "new": True}
        st.session_state[prefix + "state_defaults"] = [*rows, row]
        st.session_state[state_field_key(prefix, code, "name")] = code
        st.session_state[state_field_key(prefix, code, "note")] = ""
        st.session_state[state_field_key(prefix, code, "remove")] = False
        st.session_state[prefix + "new_state"] = ""
        st.session_state[prefix + "state_message"] = f"已添加{code}状态框。需要在代码中返回该状态才会触发。"


def render_state_fields(prefix, rows, last=None):
    st.subheader("状态名称与解释")
    st.caption("每个矩形框对应一个状态。标识须与代码返回的state一致；编辑名称和解释不会改变触发条件或仓位。"
               "如果直接修改了代码中的状态，先点击“从代码读取状态框”。读取会以代码内的名称和解释覆盖状态框草稿。")
    a, b, c = st.columns([2, 2, 1])
    a.form_submit_button("从代码读取状态框", on_click=sync_state_fields, args=(prefix,), width="stretch")
    b.text_input("新状态标识", placeholder="例如 MACD_CASH", max_chars=80, key=prefix + "new_state")
    c.form_submit_button("添加状态框", on_click=add_state_field, args=(prefix,), width="stretch")
    if message := st.session_state.pop(prefix + "state_message", None):
        st.info(message)
    edited = []
    for offset in range(0, len(rows), 2):
        columns = st.columns(2)
        for column, row in zip(columns, rows[offset:offset + 2]):
            code = row["code"]
            with column, st.container(border=True):
                st.caption("状态标识：" + code)
                if last and code == last["state"]:
                    st.info("该策略最新保存版本触发的状态 · " + last["date"])
                label = st.text_input("状态名称 · " + code, max_chars=80, key=state_field_key(prefix, code, "name"))
                note = st.text_area("状态解释 · " + code, height=160, max_chars=2000,
                                    placeholder="填写触发条件、含义及需要注意的情况…", key=state_field_key(prefix, code, "note"))
                remove = st.checkbox("移除此状态说明 · " + code, key=state_field_key(prefix, code, "remove"))
                edited.append({"code": code, "name": label, "note": note, "remove": remove})
    st.caption("名称和解释与策略代码一起预览、保存或应用；状态数量和含义由各策略独立维护。"
               "移除说明只删除名称和解释，代码仍返回该状态时，状态解释页会继续显示它。")
    return edited


def render(snapshot):
    profiles = core.list_strategies()
    by_id = {p["id"]: p for p in profiles}
    active = core.active_strategy()
    st.subheader("策略代码编辑")
    st.caption("直接编辑Python代码。应用后，盯盘信号、页面名称和回测图例使用新策略；原内置策略仍可随时切回。")
    st.success(f"当前启用：{active['name']} · v{active['revision']}")
    if "pending_editor_pick" in st.session_state:
        st.session_state["editor_profile"] = st.session_state.pop("pending_editor_pick")
    if st.session_state.get("editor_profile") not in by_id:
        st.session_state["editor_profile"] = active["id"]
    with st.spinner("正在加载策略卡片的历史表现…"):
        selected = render_strategy_cards(profiles, active)
    profile = by_id[selected]
    if message := st.session_state.pop("editor_notice", None):
        st.info(message)
    a, b = st.columns([2, 1])
    if a.button("启用选中已保存策略", disabled=active["fingerprint"] == profile["fingerprint"], width="stretch", key="activate_selected"):
        try:
            with st.spinner("正在校验并重新计算已保存策略…"):
                core.activate_strategy(selected, profile["revision"])
            st.session_state["editor_notice"] = f"已启用 {profile['name']} · v{profile['revision']}。"
            st.rerun()
        except (ValueError, RuntimeError) as exc:
            st.error(f"未启用：{exc}。当前策略保持原样。")
    source = core.strategy_code(profile)
    b.download_button("导出策略代码", source.encode("utf-8"), f"strategy-{selected[:8]}-v{profile['revision']}.py", "text/x-python", width="stretch")
    with st.expander("代码怎么写"):
        st.write("可直接修改下方完整代码中的条件、指标和仓位。PARAMETERS用于模板参数及看板周期标注；主要逻辑在generate_signals函数中。")
        st.write("BASE_SYMBOL可设为XSD、SMH或SOXX。输入frames包含QQQ、信号标的和SOXL的日线，日期索引为美东交易日；列为open、high、low、close、volume、adjclose及adj_open/high/low/close。")
        st.write("请保留generate_signals(frames, start='2017-01-02')入口和模板返回表的全部字段；symbol支持BASE_SYMBOL所指定的ETF、SOXL、CASH，weight为0～1，CASH须为0。xsd_close/xsd_annual/xsd_ma20为兼容字段，保存当前信号标的指标。可在STATE_LABELS、STATE_NOTES填写状态名称和解释。")
        st.write("支持numpy、pandas、math、dataclasses。每次计算在独立进程中运行，限时30秒；读写文件和联网操作不属于策略接口。只应用自己信任的代码，这些限制不是系统级安全沙箱。")
        st.caption("预览、保存和启用会校验信号，并在多个截断日期检查历史结果是否变化；该检查能发现常见未来数据错误，但不能证明所有代码都无未来引用。")
    prefix = f"strategy-code-edit:{selected}:{profile['revision']}:"
    last = None
    if pending := st.session_state.pop(prefix + "pending_state_code", None):
        st.session_state[prefix + "code"] = pending["code"]
        load_state_fields(prefix, states.definitions(pending["profile"], pending["observed"]))
    if prefix + "state_defaults" not in st.session_state:
        try:
            latest, bundle = perf.confirmed_inputs()
            report = strategy_card_report(bundle, latest["last"]["date"], profile)
            observed = report.attrs["state_codes"]
        except (ValueError, RuntimeError, KeyError, TypeError):
            observed = []
        load_state_fields(prefix, states.definitions(profile, observed))
    try:
        latest, bundle = perf.confirmed_inputs()
        last = strategy_card_report(bundle, latest["last"]["date"], profile).attrs["last_signal"]
    except (ValueError, RuntimeError, KeyError, TypeError):
        pass
    st.markdown('<style>[class*="st-key-source_code_"] textarea {font-family:Consolas,"Courier New",monospace;font-size:13px;line-height:1.55;tab-size:4;}</style>', unsafe_allow_html=True)
    with st.form(prefix + "form"):
        name = st.text_input("策略名称", profile["name"] + "副本" if selected == "default" else profile["name"], max_chars=60, key=prefix + "name")
        description = st.text_input("策略说明", profile.get("description", ""), max_chars=2000, key=prefix + "description")
        with st.container(key="source_code_" + hashlib.sha256(prefix.encode()).hexdigest()[:16]):
            code = st.text_area("策略代码（Python）", value=None if prefix + "code" in st.session_state else source,
                                height=640, max_chars=200_000, key=prefix + "code",
                                help="在此直接输入或粘贴完整策略代码。修改后点击应用代码，保存并切换当前策略。")
        defaults = st.session_state[prefix + "state_defaults"]
        edited_states = render_state_fields(prefix, defaults, last)
        copy_new = st.checkbox("另存为新策略", value=selected == "default", disabled=selected == "default", key=prefix + "copy")
        st.caption("应用代码会先检查、保存，再切换盯盘；仅保存代码可在历史回测中选择它。编辑内置策略时自动另存副本。")
        a, b, c = st.columns(3)
        apply = a.form_submit_button("应用代码（保存并启用）", type="primary", width="stretch")
        preview = b.form_submit_button("预览回测", width="stretch")
        save = c.form_submit_button("仅保存代码", width="stretch")
    if apply or preview or save:
        try:
            code = states.merge_editor_states(code, defaults, edited_states, profile)
            candidate = core.make_strategy(name, profile["parameters"], description, code=code)
            if preview:
                inputs, _ = core.captured_inputs()
                version = hashlib.sha256(core.json_dump(inputs["confirmed_bundle"]).encode()).hexdigest() + candidate["fingerprint"]
                with st.spinner("正在检查代码并预览历史表现…"):
                    rows, last = preview_report(version, 10.0, inputs["confirmed_bundle"], inputs["snapshot"], candidate)
                st.session_state["editor_preview"] = {"profile": candidate, "rows": rows, "last": last, "selected": selected}
                st.session_state[prefix + "pending_state_code"] = {"code": code, "profile": candidate,
                                                                  "observed": rows.attrs["state_codes"]}
                st.rerun()
            else:
                with st.spinner("正在检查并保存策略代码…"):
                    saved = core.save_strategy(name, profile["parameters"], description,
                                               None if copy_new else selected,
                                               None if copy_new else profile["revision"], code=code)
                st.session_state["pending_editor_pick"] = saved["id"]
                st.session_state.pop("editor_preview", None)
                st.session_state["editor_notice"] = f"已保存：{saved['name']} · v{saved['revision']}。可到历史回测中选择；当前盯盘策略保持原样。"
                if apply:
                    try:
                        with st.spinner("正在应用策略并更新盯盘信号…"):
                            core.activate_strategy(saved["id"], saved["revision"])
                        st.session_state["editor_notice"] = f"已保存并启用：{saved['name']} · v{saved['revision']}。"
                    except (ValueError, RuntimeError) as exc:
                        st.session_state["editor_notice"] = f"代码已保存，但未启用：{exc}。当前策略保持原样。"
                st.rerun()
        except (ValueError, RuntimeError, TypeError) as exc:
            st.error(f"未完成：{exc}。当前策略保持原样。")
    result = st.session_state.get("editor_preview")
    if result and result["selected"] == selected:
        draft = result["profile"]
        st.subheader("代码回测预览")
        st.caption(f"{draft['name']} · 上次提交代码的预览 · 截至 {result['last']['date']} · 单边成本0.1% · 历史连续持仓")
        last = result["last"]
        st.write(f"最新收盘目标：{last['symbol']} {core.percent(last['weight'])} · {core.state_name(last['state'], draft)}")
        table = result["rows"][["period", "annualized_return", "max_drawdown", "total_return"]].rename(
            columns={"period": "年限", "annualized_return": "年化收益", "max_drawdown": "最大回撤", "total_return": "累计收益"})
        table = table.set_index("年限").reindex(perf.PERIODS).reset_index()
        st.dataframe(table.style.format({"年化收益": "{:.2%}", "最大回撤": "{:.2%}", "累计收益": "{:.2%}"}), hide_index=True, width="stretch")
        st.caption("预览不会更改当前策略。保存后，历史回测可独立选择此策略查看每日资金曲线和ETF对比。")
    with st.expander("已保存版本与恢复"):
        versions = core.strategy_history(selected)
        st.dataframe(pd.DataFrame([{"版本": p["revision"], "名称": p["name"], "保存时间（北京）": core.display_time(p["updated"]) if p["updated"] else "内置版本"} for p in versions]), hide_index=True, width="stretch")
        old = st.selectbox("选择要恢复启用的版本", [p["revision"] for p in versions], key="restore_version:" + selected)
        if st.button("启用此历史版本", key="restore_strategy:" + selected):
            try:
                core.activate_strategy(selected, old)
                st.session_state["editor_notice"] = f"已启用历史版本v{old}；最新编辑版本仍保留。"
                st.rerun()
            except (ValueError, RuntimeError) as exc:
                st.error(f"未恢复：{exc}")
