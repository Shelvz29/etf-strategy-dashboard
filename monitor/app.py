from datetime import date
import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import core
import performance_ui
import state_ui
import strategy_ui

core.bootstrap()
st.set_page_config(page_title=core.APP_NAME + " · " + core.active_strategy()["name"], page_icon="📈", layout="wide")

st.markdown("""<style>
.block-container {max-width:1400px;padding-top:1.6rem;padding-bottom:3rem;}
h1 {font-size:2.05rem!important;letter-spacing:-.035em;}
[data-testid="stMetric"] {background:white;padding:18px 20px;border-radius:14px;border:1px solid #e5eaf0;}
[data-testid="stMetricLabel"] {color:#607482;}
[data-testid="stMetricValue"] {font-size:1.75rem;}
[data-testid="stTabs"] button {font-size:1rem;}
</style>""", unsafe_allow_html=True)


def history_table(rows, profile=None):
    base = core.base_symbol(profile)
    data = pd.DataFrame(rows)
    data["state"] = data["state"].map(lambda code: core.state_name(code, profile))
    data["regime"] = data["regime"].map({"BULL": "偏牛", "BEAR": "偏熊"})
    data["weight"] = data["weight"].map(lambda x: f"{core.percent(x)}")
    data["peak_drawdown"] = data["peak_drawdown"].map(lambda x: f"{core.percent(x)}")
    data["top_locked"] = data["top_locked"].map({True: "锁定", False: "未锁定"})
    return data[["date", "symbol", "weight", "state", "regime", "xsd_close", "peak_drawdown", "top_locked"]].rename(
        columns={"date": "美股信号日", "symbol": "ETF目标", "weight": "目标仓位", "state": "状态",
                 "regime": "QQQ环境", "xsd_close": f"{base}收盘价", "peak_drawdown": f"{base}距锚定峰值", "top_locked": "高位防御"})


def chart(data, cfg, base="XSD"):
    df = pd.DataFrame(data)
    selected = st.select_slider("显示范围", options=["1个月", "3个月", "6个月", "1年", "3年"], value="6个月", key="chart_window")
    counts = {"1个月": 22, "3个月": 66, "6个月": 132, "1年": 252, "3年": 756}
    df = df.tail(counts[selected])
    fig = go.Figure()
    series = [(base, f"{base} 收盘", "#172b3a"), ("年线", f"{cfg.annual_days}日均线", "#dd9530"),
              ("短线", f"{cfg.short_days}日均线", "#087c68"), ("策略锚定峰值", "策略锚定峰值", "#91a0aa")]
    for name, label, color in series:
        fig.add_trace(go.Scatter(x=df.date, y=df[name], mode="lines", name=label,
                                line={"color": color, "width": 2 if name == base else 1.5,
                                      "dash": "dot" if name == "策略锚定峰值" else "solid"}))
    fig.update_layout(height=390, margin=dict(l=0, r=10, t=15, b=0), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="white", hovermode="x unified", legend=dict(orientation="h", y=1.12),
                      yaxis_title="美元 · 仅已确认日线", xaxis=dict(showgrid=False))
    st.plotly_chart(fig, width="stretch", key="xsd_chart")


def submit_refresh():
    core.put("refresh_request", str(time.time_ns()))
    st.toast("已请求更新行情，后台完成后会自动显示。")


@st.fragment(run_every="15s")
def dashboard():
    snap = core.get("snapshot")
    profile = core.snapshot_strategy(snap)
    base = core.base_symbol(profile)
    cfg = core.baseline.Config(**profile["parameters"])
    last = snap["last"]
    clock = core.market_clock()
    beat = core.get("heartbeat", {})
    alive = bool(beat and not beat.get("stopped") and
                 (pd.Timestamp.now(tz="UTC") - pd.Timestamp(beat["time"])).total_seconds() < 150)
    current = (last["date"] == clock["expected_date"] and snap["source"] == "Yahoo 公开日线"
               and profile["fingerprint"] == core.active_strategy()["fingerprint"])
    error = core.get("last_error")
    st.caption(f"{core.APP_NAME} · {profile['name']} · v{profile['revision']} · 收盘确认 · 手动下单 · 本地运行")
    left, right = st.columns([5, 1])
    with left:
        st.title(profile["name"])
        st.caption(f"{clock['status']}　·　后台{'更新中' if beat.get('busy') else ('运行中' if alive else '未运行')}　·　下一次美股开盘（北京）{core.display_time(clock['next_open'])}")
    with right:
        st.button("更新行情", on_click=submit_refresh, width="stretch", key="refresh")
    if not alive:
        st.error("后台监测未运行。请使用“启动看板”恢复后台；当前页面只显示已保存数据。")
    if current:
        st.success(f"收盘数据已确认：{last['date']}（美东）　·　最近成功更新：{core.display_time(snap['fetched'])}（北京）")
    else:
        st.warning(f"当前为缓存参考：{last['date']}（美东），应确认至 {clock['expected_date']}。缓存信号不代表今天可执行的最新目标。")
    if error:
        st.warning(f"最近一次行情异常（北京 {core.display_time(error['time'])}）：{error['message']}")

    tabs = st.tabs(["今日看板", "信号与提醒", "手动执行", "设置与说明", "历史回测", "状态解释", "策略编辑"],
                   key="main_tabs", on_change="rerun")
    with tabs[0]:
        cal = core.calendar(pd.Timestamp(last["date"]).year)
        next_session = cal.next_session(last["date"])
        execute_open = cal.session_open(next_session)
        cols = st.columns(4)
        cols[0].metric("收盘目标 · ETF参考", "现金" if last["symbol"] == "CASH" else last["symbol"])
        cols[1].metric("目标资金比例", f"{core.percent(last['weight'])}")
        cols[2].metric("策略状态", core.state_name(last["state"], profile))
        cols[3].metric("QQQ市场环境", "偏牛" if last["regime"] == "BULL" else "偏熊")
        st.caption(f"信号日 {last['date']}（美东）→ 对应执行开盘（北京）{core.display_time(execute_open.isoformat())}。相同目标不要求每天重新配平；现金比例 {core.percent(1-last['weight'])}。")
        st.caption("仓位比例以你分配给本策略的资金为基准。")
        mapping = core.product_mappings()
        product = mapping.get(last["symbol"], {})
        if last["symbol"] != "CASH" and product.get("status") != "已确认可买卖":
            st.info(f"{last['symbol']} 的币安产品对应关系尚未确认。请在“设置与说明”填写实际产品；没有对应产品时，本策略无法原样执行。")
        elif product.get("name"):
            st.caption(f"你的币安产品记录：{product['name']}。价格和交易时段请以币安页面为准。")

        quotes = core.get("quotes", {"data": snap.get("quotes", {})})
        qcols = st.columns(3)
        for col, sym in zip(qcols, core.strategy_tickers(profile)):
            quote = quotes.get("data", {}).get(sym, {})
            val = quote.get("price")
            col.metric(f"{sym} · 公开参考行情", f"${val:,.2f}" if val is not None else "待更新")
            stamp = quote.get("time")
            col.caption(f"行情时点（北京）：{core.display_time(stamp)}")
            if clock["is_open"] and stamp and (pd.Timestamp.now(tz="UTC").timestamp() - stamp) > 1800:
                col.caption("⚠️ 参考行情已超过30分钟未更新")
        st.caption("公开行情可能延迟，盘前、盘后和休市期间可能仍显示最近正常时段价格。此处不是币安成交报价。")
        preview = core.get("preview")
        if preview and clock["is_open"] and preview.get("strategy_fingerprint") == profile["fingerprint"]:
            age = (pd.Timestamp.now(tz="UTC") - pd.Timestamp(preview["generated"])).total_seconds()
            if age <= 600:
                p = preview["last"]
                st.info(f"盘中预估（未确认）：{p['symbol']} {core.percent(p['weight'])} · {core.state_name(p['state'], profile)}。日线尚未收盘，预估不产生调仓提醒。")
            else:
                st.warning("盘中预估已过期，请等待行情更新。收盘确认目标保持不变。")
        elif clock["is_open"]:
            st.caption("盘中预估尚未形成，正在等待三个标的的完整当日数据。")
        chart(snap["chart"], cfg, base)
        st.caption("信号价格口径：" + ("含分红调整后的价格。" if cfg.signal_adjusted else "拆股调整价格，不额外调整分红。"))
        cols = st.columns(4)
        cols[0].metric(f"{base} / 年线{cfg.annual_days}", f"${last['xsd_close']:.2f}", f"{last['xsd_close']/last['xsd_annual']-1:+.1%}")
        cols[1].metric(f"{base} / 短线{cfg.short_days}", f"${last['xsd_ma20']:.2f}", f"{last['xsd_close']/last['xsd_ma20']-1:+.1%}")
        cols[2].metric(f"{base}距锚定峰值", f"{core.percent(last['peak_drawdown'])}")
        cols[3].metric(f"成交量 / {'含当日' if cfg.volume_include_today else '前'}{cfg.volume_days}日均量", f"{last['volume_multiple']:.2f}倍")
        with st.expander("当前状态如何产生"):
            if profile.get("kind") == "python":
                st.write(profile.get("state_notes", {}).get(last["state"], "当前状态由已应用的策略代码决定。"))
                st.write("代码返回的原因：" + (last["reason"] or "未填写reason，请在策略代码中补充。"))
                st.caption("指标与状态以代码返回值为准；PARAMETERS用于周期和价格口径标注。")
            else:
                st.write(f"QQQ 收盘 ${last['qqq_close']:.2f}，{cfg.macro_annual_days or cfg.annual_days}日年线 ${last['qqq_annual']:.2f}；环境判断{'启用' if cfg.macro_enabled else '关闭（固定偏牛）'}，缓冲{core.percent(cfg.macro_buffer)}。XSD 锚定峰值 ${last['anchored_peak']:.2f}。")
                detail = state_ui.state_details(profile)[last["state"]]
                st.write(detail["condition"])
                st.write(detail["detail"])
                st.caption("这里显示已采用的近似定义；网站未公开的规则没有被还原。")

    with tabs[1]:
        st.subheader("收盘信号")
        table = history_table(list(reversed(snap["history"])), profile)
        st.dataframe(table, hide_index=True, width="stretch", height=430)
        csv = table.to_csv(index=False).encode("utf-8-sig")
        st.download_button("导出显示范围的收盘记录", csv, "收盘信号.csv", "text/csv", key="signal_csv")
        st.subheader("提醒记录")
        ev = core.events()
        if not ev.empty:
            ev["created"] = ev["created"].map(core.display_time)
        st.dataframe(ev.rename(columns={"created": "北京时间", "kind": "类型", "title": "标题", "message": "详情"}),
                     hide_index=True, width="stretch")
        st.caption("本机提醒只在确认目标变化或行情更新异常时触发，并保留记录。页面每15秒读取后台结果；后台在正常美股交易时段约每5分钟更新参考行情。")

    with tabs[2]:
        st.subheader("执行确认")
        ack = core.get("execution_ack")
        if ack:
            matches = (ack["symbol"] == last["symbol"] and abs(ack["weight"] - last["weight"]) < 1e-9
                       and ack.get("strategy_fingerprint", core.default_strategy()["fingerprint"]) == profile["fingerprint"])
            st.write(f"上次手动确认：{ack['date']} 信号 → {ack['symbol']} {core.percent(ack['weight'])}，记录时间（北京）{core.display_time(ack['time'])}。")
            (st.success if matches else st.warning)("已记录的目标与当前策略版本一致。" if matches else "当前目标或策略版本与上次确认不同，请核对实际持仓。")
        else:
            st.info("尚未记录执行确认；系统无法读取你的币安持仓。")
        if st.button("记录：我已核对并处理当前目标", key="ack", disabled=not current):
            core.put("execution_ack", {"date": last["date"], "symbol": last["symbol"], "weight": last["weight"], "time": core.iso_now(), "strategy_fingerprint": profile["fingerprint"], "strategy_name": profile["name"]})
            st.toast("执行确认已保存。这是你的手动记录，不代表系统核验了成交。")
            st.rerun()
        st.caption("此按钮仅登记你的确认，不会提交订单，也不会自动计算币安持仓。")
        st.subheader("手动成交台账")
        with st.form("trade", clear_on_submit=True):
            a, b, c = st.columns(3)
            trade_date = a.date_input("成交日期（北京）", date.today())
            reference = b.selectbox("策略参考ETF", ["SOXL", "XSD", "SMH", "SOXX"])
            side = c.selectbox("成交方向", ["买入", "卖出"])
            product_name = st.text_input("实际成交的币安产品名称", placeholder="填写页面显示的完整名称 / 交易对")
            a, b, c, d = st.columns(4)
            quantity = a.number_input("实际成交数量", min_value=0.0, step=0.001, format="%.6f")
            price = b.number_input("实际成交单价", min_value=0.0, step=0.01, format="%.6f")
            fee = c.number_input("费用（同币种）", min_value=0.0, step=0.01, format="%.6f")
            currency = d.selectbox("结算币种", ["USDC", "USDT", "USD"])
            notes = st.text_input("备注")
            if st.form_submit_button("保存成交记录"):
                try:
                    core.add_trade(trade_date, reference, product_name, side, quantity, price, fee, currency, notes)
                    st.toast("成交记录已保存到本机。")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        journal = core.trades()
        if not journal.empty:
            st.dataframe(journal.drop(columns=["id", "created"]).rename(columns={"trade_date": "日期", "reference": "ETF参考", "product": "实际产品", "side": "方向", "quantity": "数量", "price": "价格", "fee": "费用", "currency": "币种", "notes": "备注"}), hide_index=True, width="stretch")
            st.download_button("导出成交台账", journal.to_csv(index=False).encode("utf-8-sig"), "手动成交台账.csv", "text/csv", key="trade_csv")
        st.caption("只记录实际成交，不把证券代币视为ETF份额，也不把不同结算币种合并计算收益。")

    with tabs[3]:
        st.subheader("本机提醒")
        enabled = st.toggle("允许 Windows 桌面提醒", value=core.get("desktop_notifications", True), key="notifications")
        if enabled != core.get("desktop_notifications", True):
            core.put("desktop_notifications", enabled)
        if st.button("测试本机提醒", key="test_notice"):
            core.notify(core.APP_NAME + " 测试提醒", "本地监测程序已发送测试提醒。此消息不是交易信号。")
            core.event("测试", "测试本机提醒", "测试消息，不是交易信号。", "test:" + str(time.time_ns()))
            st.toast("测试提醒已发送；Windows 勿扰模式可能影响弹出显示。")
        st.caption("后台在登录 Windows 后启动；电脑需开机、联网且保持唤醒。关闭浏览器不会停止后台。未配置手机或外部消息渠道。")
        st.subheader("币安产品对应关系")
        st.caption("XSD和SOXL的默认名称及可买卖状态按你提供的信息设置；SMH、SOXX待你确认实际产品。你可在此修改并保存。")
        st.write("请依据你账户里的实际产品填写。没有对应产品、受地区限制或暂停交易时，无法原样执行ETF轮动。")
        products = core.product_mappings()
        with st.form("products"):
            values = {}
            for sym in ("SOXL", "XSD", "SMH", "SOXX"):
                prior = products.get(sym, {})
                a, b = st.columns([3, 2])
                name = a.text_input(f"{sym} 对应的币安产品完整名称", value=prior.get("name", ""))
                choices = ["未确认", "已确认可买卖", "没有对应产品 / 暂不可交易"]
                status = b.selectbox(f"{sym} 可交易状态", choices, index=choices.index(prior.get("status", "未确认")))
                values[sym] = {"name": name, "status": status}
            if st.form_submit_button("保存产品对应关系"):
                if any(x["status"] == "已确认可买卖" and not x["name"].strip() for x in values.values()):
                    st.error("标记可买卖前，请填写完整产品名称。")
                else:
                    core.put("products", values)
                    st.toast("产品对应关系已保存。")
                    st.rerun()
        st.subheader("采用的策略与执行约定")
        if profile.get("kind") == "python":
            st.write(f"{profile['name']} · v{profile['revision']}：采用你保存的Python代码，从2017年起点完整计算收盘信号。具体条件、指标及目标仓位以代码为准。")
        else:
            st.write(f"{profile['name']} · v{profile['revision']}：从2017年起点完整重放状态，{cfg.annual_days}日年线、{cfg.short_days}日短线、QQQ年线{core.percent(cfg.macro_buffer)}缓冲；SOXL进攻目标{core.percent(cfg.attack)}，XSD防御目标按偏牛{core.percent(cfg.bull_defense)}／偏熊{core.percent(cfg.bear_defense)}。")
        st.write("正常美股收盘20分钟后检查完整日线，并按次日正常美股开盘的原回测约定显示执行时间。盘中预估不改变收盘状态，证券代币的额外交易时段不改变信号日历。")
        if profile.get("kind") != "python" and profile["parameters"] == core.default_strategy()["parameters"]:
            st.info("这组内置参数既有回测的收盘最大回撤约83.6%，没有加入50%回撤控制。")
        else:
            st.info(f"策略已自定义。请在“历史回测”选择此版本查看实际计算的年化和回撤；{base}回撤阈值不是账户最大回撤限制。")
        st.write("本工具不连接币安账户、不需要API密钥、不自动下单。日线来源为Yahoo公开数据；对应证券代币的折溢价、费用及成交条件，以你实际产品为准。")
        with st.expander("数据与版本信息"):
            st.write(f"来源：{snap['source']}；重放起点：2017-01-02。在线日线从2015年开始用于预热，原冻结快照从2008年开始（SOXL从上市开始）。")
            st.code("策略指纹：" + snap["strategy_hash"][:16])
            st.code(f"当前版本：{profile['id']} · v{profile['revision']} · {profile['fingerprint'][:16]}")
            st.caption("原回测文件保持不变。更新的日线、信号状态、台账和提醒记录保存在 monitor/runtime；数据库可在停止程序后备份。")
        st.caption("参考：[原策略公开说明](https://aiyuan.ai/signals/guide/xsd-soxl) · [NYSE交易日历](https://www.nyse.com/trade/hours-calendars)")

    if tabs[4].open:
        with tabs[4]:
            performance_ui.render(snap)

    if tabs[5].open:
        with tabs[5]:
            state_ui.render(snap, current)

    if tabs[6].open:
        with tabs[6]:
            strategy_ui.render(snap)


dashboard()
