"""Streamlit historical performance page; all results remain local."""
import hashlib
import time

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import core
import performance as perf

COLORS = {perf.STRATEGY: "#087c68", "TQQQ": "#d65d39", "QQQ": "#3e77b6", "XSD": "#c58d26",
          "SMH": "#8b61b4", "VGT": "#78888f", "SOXX": "#ae5085", "SOXL": "#d83f55"}


@st.cache_data(ttl=300, max_entries=16, show_spinner=False)
def cached_inputs(version, cutoff, selected, refresh_token, _bundle, _profile):
    return perf.datasets(_bundle, cutoff, selected, profile=_profile)


@st.cache_data(max_entries=24, show_spinner=False)
def cached_report(version, selected, period, mode, start, end, cost, refresh_token, comparison_versions,
                  _frames, _signals, _comparisons):
    result = perf.report(_frames, _signals, selected, period, mode, start, end, cost, comparisons=_comparisons)
    win = result["window"]
    # Keep custom module classes outside the cache boundary. Streamlit may reload
    # imported modules while an existing fragment still holds the previous class.
    result["window"] = {"label": win.label, "baseline": win.baseline, "first": win.first, "end": win.end}
    return result


def settings_defaults():
    return {"principal": 10000.0, "unit": "人民币", "selected": ["QQQ", "SOXL"], "strategy": "active",
            "period": "近5年", "mode": perf.CONTINUOUS, "cost": 10.0}


def comparison_options(profiles):
    return {"strategy:" + key: profile for key, profile in profiles.items() if key != "active"}


def comparison_label(profile):
    return f"{profile['name']} · v{profile['revision']}（策略）"


def chart_colors(names, main):
    palette = ("#713c9c", "#df6b26", "#2467a1", "#ad3e71", "#47906b", "#9b782c", "#617587", "#d14853")
    return {name: ("#087c68" if name == main else COLORS.get(name, palette[i % len(palette)]))
            for i, name in enumerate(names)}


def dataset_fingerprint(frames):
    digest = hashlib.sha256()
    for symbol, frame in sorted(frames.items()):
        digest.update(symbol.encode())
        digest.update(str(tuple(frame.columns)).encode())
        digest.update(pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes())
    return digest.hexdigest()


def render(snap):
    latest, bundle = perf.confirmed_inputs()
    active = core.snapshot_strategy(latest)
    profiles = {"active": active}
    for saved in core.list_strategies():
        for version in core.strategy_history(saved["id"]):
            profiles[f"{version['id']}:{version['revision']}"] = version
    comparison_profiles = comparison_options(profiles)
    comparison_choices = [*perf.BENCHMARKS, *comparison_profiles]
    cutoff = latest["last"]["date"]
    first, last = perf.FIRST_TRADE.date(), pd.Timestamp(cutoff).date()
    st.subheader("历史回测与ETF对比")
    st.caption(f"可回测范围：{first} 至 {last}（已确认美股收盘）。可选择已保存策略及其历史版本，对比ETF采用买入持有。")
    defaults = core.get("performance_settings", settings_defaults())
    defaults = {**settings_defaults(), **defaults}
    if defaults["strategy"] not in profiles:
        defaults["strategy"] = "active"
    defaults["selected"] = [key for key in defaults["selected"] if key in comparison_choices]
    with st.form("performance_form"):
        strategy_pick = st.selectbox("回测策略", list(profiles), index=list(profiles).index(defaults["strategy"]),
                                    format_func=lambda key: ("当前启用 · " if key == "active" else "") + f"{profiles[key]['name']} · v{profiles[key]['revision']}" + ("（内置）" if profiles[key]["id"] == "default" else ""))
        st.caption("选择回测策略并生成结果，只影响本页，不会切换当前盯盘策略。")
        a, b, c = st.columns([2, 1, 2])
        principal = a.number_input("起始本金", min_value=1.0, max_value=1_000_000_000_000.0,
                                   value=float(defaults["principal"]), step=1000.0, format="%.2f")
        units = ["人民币", "美元", "USDC", "USDT"]
        unit = b.selectbox("金额单位", units, index=units.index(defaults["unit"]))
        periods = [*perf.PERIODS, "自定义日期"]
        period = c.selectbox("查看年限", periods, index=periods.index(defaults["period"]))
        selected = st.multiselect("对比ETF与策略（可多选）", comparison_choices, default=defaults["selected"],
                                 format_func=lambda key: comparison_label(comparison_profiles[key]) if key in comparison_profiles else key,
                                 help="可同时勾选ETF和已保存策略的各版本。主策略始终显示；相同版本只显示一次。ETF买入持有，策略按各自代码运行。")
        a, b = st.columns([3, 2])
        modes = [perf.CONTINUOUS, perf.FRESH]
        mode = a.selectbox("起始持仓口径", modes, index=modes.index(defaults["mode"]))
        cost = b.number_input("单边交易成本（基点）", min_value=0.0, max_value=100.0,
                              value=float(defaults["cost"]), step=1.0, help="10基点 = 每次交易金额的0.1%。")
        default_start = max(first, min(last, pd.Timestamp(defaults.get("start", "2021-10-04")).date()))
        default_end = max(first, min(last, pd.Timestamp(defaults.get("end", cutoff)).date()))
        a, b = st.columns(2)
        start = a.date_input("自定义起始日期", default_start, min_value=first, max_value=last)
        end = b.date_input("自定义结束日期", default_end, min_value=first, max_value=last)
        st.caption("自定义日期仅在“查看年限”选择自定义日期时生效；近1／2／3／5年均截至最新确认日。")
        calculate = st.form_submit_button("生成表格与图表", type="primary", width="stretch")
    if calculate:
        if period == "自定义日期" and start > end:
            st.error("起始日期不能晚于结束日期。")
            return
        request = {"principal": principal, "unit": unit, "selected": selected, "period": period,
                   "mode": mode, "cost": cost, "start": str(start), "end": str(end), "strategy": strategy_pick}
        core.put("performance_settings", request)
        st.session_state["performance_request"] = request
    request = st.session_state.get("performance_request", defaults)
    request = {**settings_defaults(), **request}
    profile = profiles.get(request["strategy"], active)
    strategy_name = profile["name"]
    st.caption(f"本次回测策略：{strategy_name} · v{profile['revision']}；当前盯盘：{active['name']} · v{active['revision']}")
    selected = tuple(symbol for symbol in perf.BENCHMARKS if symbol in request["selected"])
    comparison_picks = {key: comparison_profiles[key] for key in request["selected"] if key in comparison_profiles
                        and comparison_profiles[key]["fingerprint"] != profile["fingerprint"]}
    if st.button("更新对比ETF日线", key="comparison_refresh"):
        with st.spinner("正在更新所选ETF的日线…"):
            _, refresh_errors, _ = perf.extra_prices(tuple(s for s in selected if s not in core.TICKERS), cutoff, force=True)
        st.session_state["performance_refresh_errors"] = refresh_errors
        st.session_state["performance_refresh"] = str(time.time_ns())
    refresh_token = st.session_state.get("performance_refresh", "")
    # Hash the captured inputs: replay caches also invalidate on same-date revisions.
    version = hashlib.sha256(core.json_dump(bundle).encode()).hexdigest() + profile["fingerprint"]
    comparisons, comparison_versions, comparison_errors = {}, [], []
    try:
        with st.spinner("正在读取日线并计算历史表现…"):
            frames, signals, errors, metadata = cached_inputs(version, cutoff, selected, refresh_token, bundle, profile)
            for key, other in comparison_picks.items():
                label = comparison_label(other)
                # Names may change between revisions; the immutable ID/version
                # identifies selections and the source fingerprint identifies cache entries.
                if label in comparisons or label == strategy_name or label in perf.BENCHMARKS:
                    label += f" [{other['id'][:8]}]"
                try:
                    other_version = hashlib.sha256(core.json_dump(bundle).encode()).hexdigest() + other["fingerprint"]
                    other_frames, other_signals, _, other_meta = cached_inputs(other_version, cutoff, (), refresh_token, bundle, other)
                    comparisons[label] = (other_frames, other_signals)
                    comparison_versions.append((key, other["fingerprint"], dataset_fingerprint(other_frames)))
                except (ValueError, KeyError, RuntimeError) as exc:
                    comparison_errors.append(f"{label}：{exc}；本次未纳入该策略，其余对比继续计算。")
            chosen_start = request.get("start", str(first))
            chosen_end = request.get("end", cutoff) if request["period"] == "自定义日期" else cutoff
            report_version = version + dataset_fingerprint(frames)
            result = cached_report(report_version, selected, request["period"], request["mode"], chosen_start,
                                   chosen_end, request["cost"], refresh_token, tuple(comparison_versions), frames, signals, comparisons)
    except (ValueError, KeyError, RuntimeError) as exc:
        st.error(f"本次回测未生成：{exc}")
        return
    errors = {**st.session_state.get("performance_refresh_errors", {}), **errors}
    for symbol, message in errors.items():
        st.warning(f"{symbol}：{message}" + ("。本次未纳入该ETF，其余标的继续计算。" if symbol not in frames else "。"))
    for message in comparison_errors + result["unavailable"]:
        st.caption(message)
    st.session_state["performance_last_result"] = {"period": request["period"], "principal": request["principal"],
                                                   "assets": list(result["results"]), "mode": request["mode"],
                                                   "strategy_id": profile["id"], "revision": profile["revision"], "fingerprint": profile["fingerprint"]}
    unit, principal = request["unit"], float(request["principal"])
    win = perf.Window(**result["window"])
    detail = result["results"][strategy_name]["metrics"]
    baseline = detail["baseline_close"]
    if request["mode"] == perf.CONTINUOUS:
        st.info("历史连续持仓：沿用2017年以来的策略持仓，将所选区间的期初账户金额折算为输入本金；与此前近年回测报告口径一致。")
    else:
        st.info("期初从现金建仓：在区间首个交易日，用前一交易日的已确认信号建仓并计入买入成本；策略的峰值和防御状态仍从2017年连续计算。")
    st.caption(f"当前结果：{request['period']} · {request['mode']} · 本金 {principal:,.2f} {unit} · 首个收益交易日 {win.first.date()} → {win.end.date()}" + (f" · 期初基准为 {baseline} 收盘" if baseline else " · 期初基准为开盘前本金"))
    st.caption(f"策略按收盘信号、次日正常美股开盘成交，相同目标不每日配平；对比ETF按100%买入持有。单边成本 {request['cost']/100:.2f}%，分红再投资；不计税费、现金利息和汇率变化。")
    if unit != "美元":
        st.caption(f"{unit}金额按固定换算展示美元资产收益，不包含实际换汇成本、汇率波动或币安证券代币的折溢价。")
    if detail["calendar_days"] < 365:
        st.warning("所选区间不足一年，年化收益仅为数学折算值。")
    if latest["source"] != "Yahoo 公开日线":
        st.warning(f"策略使用 {latest['source']}，数据截止 {cutoff}；此页是历史回测。")

    table = perf.money_table(result["results"], principal)
    main = table.iloc[0]
    cols = st.columns(4)
    cols[0].metric("策略年化收益", f"{main.annualized_return:.2%}")
    cols[1].metric("策略最大回撤 · 收盘", f"{main.max_drawdown:.2%}")
    cols[2].metric(f"策略期末资金 · {unit}", f"{main.ending_capital:,.2f}")
    cols[3].metric("策略累计收益", f"{main.total_return:.2%}")
    st.subheader("所选区间对比")
    display = table[["asset", "annualized_return", "max_drawdown", "total_return", "ending_capital", "profit"]].rename(
        columns={"asset": "标的", "annualized_return": "年化收益", "max_drawdown": "最大回撤", "total_return": "累计收益",
                 "ending_capital": f"期末资金（{unit}）", "profit": f"盈亏（{unit}）"})
    st.dataframe(display.style.format({"年化收益": "{:.2%}", "最大回撤": "{:.2%}", "累计收益": "{:.2%}",
                                      f"期末资金（{unit}）": "{:,.2f}", f"盈亏（{unit}）": "{:,.2f}"}),
                 hide_index=True, width="stretch")

    bars = make_subplots(rows=1, cols=2, subplot_titles=("年化收益（%）", "最大回撤（%）"))
    asset_colors = chart_colors(table.asset, strategy_name)
    colors = [asset_colors[name] for name in table.asset]
    for column, field in ((1, "annualized_return"), (2, "max_drawdown")):
        bars.add_trace(go.Bar(x=table.asset, y=table[field] * 100, marker_color=colors,
                              text=[f"{value:.1%}" for value in table[field]], textposition="outside",
                              hovertemplate="%{x}<br>%{y:.2f}%<extra></extra>"), row=1, col=column)
    bars.update_layout(height=330, showlegend=False, margin=dict(l=10, r=10, t=50, b=35),
                       paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="white")
    st.plotly_chart(bars, width="stretch", key="performance_bars")

    st.subheader("每日资金与回撤")
    log_scale = st.toggle("资金曲线使用对数坐标", value=False, key="performance_log")
    plots = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=.08, row_heights=[.65, .35])
    daily = pd.DataFrame()
    for name, item in result["results"].items():
        wealth = item["wealth"] * principal
        drawdown = item["drawdown"] * 100
        daily[name + "_资金"] = wealth
        daily[name + "_回撤"] = item["drawdown"]
        style = dict(color=asset_colors[name], width=3 if name == strategy_name else 1.5)
        plots.add_trace(go.Scatter(x=wealth.index, y=wealth, name=name, mode="lines", legendgroup=name,
                                   line=style, hovertemplate=f"{name}：%{{y:,.2f}} {unit}<extra></extra>"), row=1, col=1)
        plots.add_trace(go.Scatter(x=drawdown.index, y=drawdown, name=name, mode="lines", legendgroup=name,
                                   line=style, showlegend=False, hovertemplate=f"{name}回撤：%{{y:.2f}}%<extra></extra>"), row=2, col=1)
    plots.add_hline(y=principal, line_dash="dot", line_color="#9cacb6", row=1, col=1)
    plots.update_yaxes(title_text=f"资金（{unit}）", type="log" if log_scale else "linear", row=1, col=1)
    plots.update_yaxes(title_text="回撤（%）", range=[-100, 2], row=2, col=1)
    plots.update_layout(height=640, hovermode="x unified", margin=dict(l=5, r=15, t=60, b=20),
                        legend=dict(orientation="h", y=1.09), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="white",
                        uirevision=f"{profile['fingerprint']}:{request['period']}:{request['mode']}:{chosen_start}:{chosen_end}:{log_scale}:{principal}:{selected}:{comparison_versions}:{request['cost']}")
    st.plotly_chart(plots, width="stretch", key="performance_daily")
    st.caption("图表含期初本金点。回撤从本区间期初本金和区间内最高收盘资金计算；点击图例可隐藏或显示标的。")

    st.subheader("近1／2／3／5年与全部历史")
    metric = st.radio("汇总表指标", ["年化收益", "最大回撤", "期末资金"], horizontal=True, key="performance_matrix")
    field = {"年化收益": "annualized_return", "最大回撤": "max_drawdown", "期末资金": "multiple"}[metric]
    matrix = result["periods"].pivot(index="period", columns="asset", values=field)
    matrix = matrix.reindex([label for label in perf.PERIODS if label in matrix.index])
    matrix = matrix.reindex(columns=list(result["results"]))
    if metric == "期末资金":
        matrix = matrix * principal
    matrix.index.name = "年限"
    st.dataframe(matrix.style.format("{:,.2f}" if metric == "期末资金" else "{:.2%}"), width="stretch")
    st.caption("各年限均以相同本金计算；若选择自定义日期，汇总表各年限截至该自定义结束日期。")

    exports = st.columns(3)
    exports[0].download_button("导出所选区间汇总", display.to_csv(index=False).encode("utf-8-sig"), "回测区间汇总.csv", "text/csv", key="performance_summary_download")
    all_periods = result["periods"].copy()
    all_periods["ending_capital"] = all_periods.multiple * principal
    all_periods = all_periods.rename(columns={"period": "年限", "asset": "标的", "annualized_return": "年化收益率",
        "max_drawdown": "最大回撤", "total_return": "累计收益率", "multiple": "资金倍数", "first_session": "首个收益交易日",
        "end_session": "结束交易日", "baseline_close": "期初基准收盘日", "calendar_days": "日历天数", "sessions": "交易日数",
        "drawdown_trough": "最大回撤低点日期", "ending_capital": f"期末资金（{unit}）"})
    exports[1].download_button("导出全部年限指标", all_periods.to_csv(index=False).encode("utf-8-sig"), "各年限回测指标.csv", "text/csv", key="performance_period_download")
    exports[2].download_button("导出每日资金和回撤", daily.rename_axis("date").to_csv().encode("utf-8-sig"), "每日资金与回撤.csv", "text/csv", key="performance_daily_download")
    with st.expander("计算口径和行情来源"):
        st.write("年化收益按实际日历天数计算复合增长率。近年连续持仓口径采用周年日之前最近的收盘作为基准，保持与此前报告一致；首次建仓从第一个交易日开盘前本金起算。")
        st.write("最大回撤按每日收盘账户净值计算，不包含盘中最低价。比较的ETF采用含分红再投资的调整后价格；策略信号仍使用原代码的价格口径。")
        st.write("所有标的使用相同交易日和结束日期；缺失日线的ETF会明确提示并暂不纳入，不会填充缺失收益。")
        st.write("勾选的策略按各自已保存版本生成信号，与主策略使用相同本金、日期、建仓口径和交易成本；失败的策略会单独提示。比较策略不会切换盯盘，也不会触发下单。")
        st.caption(f"策略日线：{latest['source']} · 截止 {cutoff} · 确认更新（北京）{core.display_time(latest['fetched'])}。其余ETF：Yahoo公开历史行情，本机缓存。")
        st.caption("这些是美国ETF的历史回测；本金仅用于金额缩放，不代表已建仓，也不预测未来收益。币安实际证券产品的费用、折溢价和成交条件未额外建模。")
