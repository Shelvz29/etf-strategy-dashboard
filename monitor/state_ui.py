"""Explain only the selected strategy's own states and confirmed outputs."""
from html import escape

import pandas as pd
import streamlit as st

import core
import performance as perf
import strategy_states as states


def state_details(profile=None):
    profile = profile or core.active_strategy()
    cfg = core.baseline.Config(**profile["parameters"])
    release = {"annual_or_drawdown": f"跌破年线或距峰值回撤达到{core.percent(cfg.cash_drawdown)}",
               "annual_only": "跌破年线", "drawdown_only": f"距峰值回撤达到{core.percent(cfg.cash_drawdown)}"}[cfg.top_release]
    volume_basis = f"含当天的{cfg.volume_days}日" if cfg.volume_include_today else f"此前{cfg.volume_days}个交易日"
    recovery = ("连续收盘站上短线" if cfg.cooldown_mode == "consecutive_above20" else "连续位于年线下方")
    deep_lock = "或深跌进攻已锁定" if cfg.deep_latch else ""
    return {
        "TOP_DEFENSE": {
            "kind": "防御", "target": f"XSD 偏牛 {core.percent(cfg.bull_defense)} / 偏熊 {core.percent(cfg.bear_defense)}",
            "condition": "高位放量防御锁定中；此状态优先于其他七种状态。",
            "meaning": "高位出现放量阴线后，策略转向XSD防御，锁定解除前继续维持防御。",
            "detail": (f"新锁定需同时满足：XSD距锚定峰值不超过{core.percent(1-cfg.high_zone)}、"
                       f"阴线实体跌幅（开盘价−收盘价）/开盘价至少{core.percent(cfg.red_body)}、"
                       f"当日成交量至少为{volume_basis}平均成交量的{cfg.volume_multiple:g}倍。"
                       f"{release}时解除已有锁定；"
                       "QQQ偏牛/偏熊切换也会清除锁定，当天仍可能重新触发。"),
        },
        "PULLBACK_ATTACK": {
            "kind": "进攻", "target": f"SOXL {core.percent(cfg.attack)} / 现金 {core.percent(1-cfg.attack)}",
            "condition": f"XSD收盘价≥年线，距锚定峰值回撤≥{core.percent(cfg.cash_drawdown)}；偏牛、偏熊均适用。",
            "meaning": "XSD从峰值回落，但收盘价仍在年线上方；策略使用SOXL参与后续价格变化。",
            "detail": f"“回撤”指XSD价格从策略锚定峰值下跌，不是你的账户已经亏损。此分支不要求{cfg.short_days}日线恢复条件，也不保证反弹或买在最低点。",
        },
        "NORMAL_ATTACK": {
            "kind": "进攻", "target": f"SOXL {core.percent(cfg.attack)} / 现金 {core.percent(1-cfg.attack)}",
            "condition": f"XSD收盘价≥年线、距峰值回撤<{core.percent(cfg.cash_drawdown)}，且QQQ环境偏牛。",
            "meaning": "趋势与市场环境满足常态进攻条件，使用SOXL。",
            "detail": "即使没有明显回撤，也可能处于此状态。“常态进攻”和“回撤进攻”的目标标的及仓位相同，二者切换本身不会要求调仓。",
        },
        "NORMAL_DEFENSE": {
            "kind": "防御", "target": f"XSD {core.percent(cfg.bear_defense)} / 现金 {core.percent(1-cfg.bear_defense)}",
            "condition": f"XSD收盘价≥年线、距峰值回撤<{core.percent(cfg.cash_drawdown)}，且QQQ环境偏熊。",
            "meaning": "XSD仍在年线上方，但QQQ环境偏熊，使用较低比例的XSD持仓。",
            "detail": "此分支不使用SOXL。QQQ环境恢复偏牛后，会重新按同一天的XSD条件选择状态。",
        },
        "BREAK_CASH": {
            "kind": "现金", "target": "现金 100% / ETF 0%",
            "condition": f"XSD收盘价<年线，距峰值回撤<{core.percent(cfg.cash_drawdown)}。",
            "meaning": "价格跌破年线且尚未达到回撤进攻区间，目标为全部现金。",
            "detail": f"这里的现金指分配给本策略的资金不配置XSD或SOXL。此阈值不是账户亏损{core.percent(cfg.cash_drawdown)}自动止损规则。",
        },
        "DEEP_ATTACK": {
            "kind": "进攻", "target": f"SOXL {core.percent(cfg.attack)} / 现金 {core.percent(1-cfg.attack)}",
            "condition": f"XSD收盘价<年线且距峰值回撤≥{core.percent(cfg.cash_drawdown)}；达到深跌阈值（偏牛{core.percent(cfg.deep_bull)}／偏熊{core.percent(cfg.deep_bear)}）{deep_lock}。",
            "meaning": "跌幅进入深跌区间，策略直接选择SOXL进攻。",
            "detail": f"此分支优先于短线恢复条件，不要求先站回{cfg.short_days}日线。" + ("已启用深跌锁定，站回年线或QQQ环境切换时解除。" if cfg.deep_latch else "未启用深跌锁定，每天按最新确认收盘重新判断。") + "它不是账户最大回撤控制。",
        },
        "RECOVERY_ATTACK": {
            "kind": "进攻", "target": f"SOXL {core.percent(cfg.attack)} / 现金 {core.percent(1-cfg.attack)}",
            "condition": (f"XSD收盘价<年线；距峰值回撤≥{core.percent(cfg.cash_drawdown)}且未达深跌阈值、无深跌锁定；"
                          f"收盘价>{cfg.short_days}日线、该均线较前日上升，{recovery}偏牛≥{cfg.bull_cool}天/偏熊≥{cfg.bear_cool}天。"),
            "meaning": "长期趋势仍未恢复，但短线恢复条件成立，转向SOXL。",
            "detail": f"连续天数按已结束的美股交易日计算，包含当天；" + (f"跌回{cfg.short_days}日线" if cfg.cooldown_mode == "consecutive_above20" else "站回年线") + "或QQQ环境切换会重置计数。短线恢复不表示已经重新站上年线。",
        },
        "SPRING_DEFENSE": {
            "kind": "防御", "target": f"XSD 偏牛 {core.percent(cfg.bull_defense)} / 偏熊 {core.percent(cfg.bear_defense)}",
            "condition": f"XSD收盘价<年线；距峰值回撤≥{core.percent(cfg.cash_drawdown)}且未达深跌阈值、无深跌锁定；短线恢复条件尚未全部满足。",
            "meaning": "回撤已进入等待区间，暂用XSD防御，继续观察短线恢复。",
            "detail": f"偏牛使用XSD{core.percent(cfg.bull_defense)}和现金{core.percent(1-cfg.bull_defense)}，偏熊使用XSD{core.percent(cfg.bear_defense)}和现金{core.percent(1-cfg.bear_defense)}。XSD仍会涨跌，“防御”不代表本金保本。",
        },
    }


def strategy_context(bundle, cutoff, profile, snapshot=None):
    from strategy_ui import strategy_card_report
    if snapshot is not None and core.snapshot_strategy(snapshot)["fingerprint"] == profile["fingerprint"]:
        last = snapshot["last"]
    else:
        last = None
    rows = strategy_card_report(bundle, cutoff, profile)
    return last or rows.attrs["last_signal"], rows.attrs["state_codes"]


def render(snapshot, current=True):
    active = core.snapshot_strategy(snapshot)
    st.subheader("状态解释")
    st.caption("各策略使用自己的状态集合、名称和解释；数量不限于八种。说明随策略代码版本保存。")
    st.success(f"当前盯盘：{active['name']} · v{active['revision']} · "
               f"{core.state_name(snapshot['last']['state'], active)} · 信号日 {snapshot['last']['date']}")
    profiles = {"active": active}
    for profile in core.list_strategies():
        if profile["fingerprint"] != active["fingerprint"]:
            profiles[profile["id"]] = profile
    if st.session_state.get("state_explanation_profile") not in profiles:
        st.session_state["state_explanation_profile"] = "active"
    picked = st.pills("查看策略的状态", list(profiles), key="state_explanation_profile",
                      format_func=lambda key: ("当前启用 · " if key == "active" else "")
                      + f"{profiles[key]['name']} · v{profiles[key]['revision']}") or "active"
    profile = profiles[picked]
    _, bundle = perf.confirmed_inputs()
    cutoff = snapshot["last"]["date"]
    try:
        with st.spinner("正在读取该策略的状态与最新收盘结果…"):
            last, observed = strategy_context(bundle, cutoff, profile, snapshot)
    except (ValueError, RuntimeError, KeyError, TypeError) as exc:
        st.warning(f"状态试算暂不可用：{exc}")
        last = snapshot["last"] if picked == "active" else None
        observed = [row["state"] for row in snapshot["history"]] if picked == "active" else []
    rows = states.definitions(profile, observed)
    if last and last["state"] not in {row["code"] for row in rows}:
        rows.append({"code": last["state"], "name": core.state_name(last["state"], profile), "note": ""})
    st.markdown(f"### {escape(profile['name'])} · 状态说明")
    if last:
        qualifier = ("当前确认" if current else "缓存参考") if picked == "active" else "最新收盘试算（未启用）"
        st.info(f"{qualifier}：{core.state_name(last['state'], profile)} · {last['state']} · {last['date']}（美东）\n\n"
                f"目标：{last['symbol']} {core.percent(last['weight'])} · 现金 {core.percent(1-last['weight'])}")
        if note := next((row["note"] for row in rows if row["code"] == last["state"]), ""):
            st.write(note)
        else:
            st.caption("该状态尚未填写解释，可在策略编辑的状态框中补充。")
        st.write("本次代码返回的原因：" + (last.get("reason") or "未填写reason。"))
    st.caption(f"共 {len(rows)} 种状态。高亮表示该策略最近一次收盘触发的状态；其他策略的试算不切换盯盘。"
               "文字解释不参与信号判断，触发条件以generate_signals代码为准。")
    st.markdown("""<style>
    .explanation-grid {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;}
    .explanation-card {border:1px solid #dce5ec;border-radius:12px;padding:18px;background:#fff;color:#172b3a;overflow-wrap:anywhere;}
    .explanation-card.active {border:2px solid #087c68;padding:17px;background:#edf8f4;}
    .explanation-tag {font-size:12px;color:#607482;margin-bottom:8px;}
    .explanation-name {font-size:18px;font-weight:650;margin-bottom:5px;}
    .explanation-code {font-size:12px;color:#607482;margin-bottom:12px;}
    .explanation-note {font-size:14px;line-height:1.75;white-space:pre-wrap;}
    @media(max-width:750px) {.explanation-grid {grid-template-columns:1fr;}}
    </style>""", unsafe_allow_html=True)
    cards = []
    for row in rows:
        selected = bool(last and row["code"] == last["state"])
        tag = ("当前触发" if picked == "active" and current else "最近收盘触发") if selected else "状态定义"
        note = row["note"] or "尚未填写解释；触发判断以该策略代码为准。"
        cards.append(f'<div class="explanation-card{" active" if selected else ""}">'
                     f'<div class="explanation-tag">{escape(tag)}</div>'
                     f'<div class="explanation-name">{escape(row["name"])}</div>'
                     f'<div class="explanation-code">{escape(row["code"])}</div>'
                     f'<div class="explanation-note">{escape(note)}</div></div>')
    st.markdown('<div class="explanation-grid">' + ''.join(cards) + '</div>', unsafe_allow_html=True)
    if not rows:
        st.info("尚未声明或读取到状态。请在策略代码的STATE_LABELS、STATE_NOTES中声明，或在编辑器添加状态框。")
    st.caption("策略目标不代表你的实际持仓；最新状态采用已确认收盘日线，对应下一正常美股开盘执行。")


