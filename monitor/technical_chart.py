"""Read-only OHLC charts and indicators for confirmed strategy inputs."""
import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import core
import performance

PERIODS = {"日K": None, "周K": "W-FRI", "年K": "YE"}
WINDOWS = {"1个月": 1, "3个月": 3, "6个月": 6, "1年": 12, "3年": 36, "5年": 60, "全部历史": None}


def periods(text):
    """Accept several independent MA/EMA periods, never an expression."""
    parts = text.replace("，", ",").split(",")
    if not 1 <= len(parts) <= 6 or any(not p.strip().isdigit() for p in parts):
        raise ValueError("周期请填写1至6个整数，用逗号分隔，例如5,7,20。")
    values = list(dict.fromkeys(int(p.strip()) for p in parts))
    if any(not 1 <= n <= 500 for n in values):
        raise ValueError("MA／EMA周期须为1至500。")
    return values


def candles(frame, frequency, adjusted=False):
    if frequency not in PERIODS:
        raise ValueError("不支持的K线周期")
    prefix = "adj_" if adjusted else ""
    result = frame[[prefix + k for k in ("open", "high", "low", "close")]].copy()
    result.columns = ["open", "high", "low", "close"]
    result["volume"] = frame["volume"]
    if PERIODS[frequency]:
        result["last_session"] = result.index
        result = result.resample(PERIODS[frequency]).agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum", "last_session": "last"})
        result = result.dropna(subset=["open", "high", "low", "close"])
        # Actual last session avoids displaying a future Friday/December 31.
        result.index = pd.DatetimeIndex(result.pop("last_session"))
    return result


def rsi(close, length):
    """Wilder RSI, seeded by the first n changes, then recursive smoothing."""
    values = close.to_numpy(dtype=float)
    output = np.full(len(values), np.nan)
    if len(values) <= length:
        return pd.Series(output, index=close.index)
    changes = np.diff(values)
    gains = np.maximum(changes, 0)
    losses = np.maximum(-changes, 0)
    up, down = gains[:length].mean(), losses[:length].mean()
    def value():
        if up == 0 and down == 0:
            return 50.0
        return 100.0 if down == 0 else 100.0 - 100.0 / (1.0 + up / down)
    output[length] = value()
    for i in range(length + 1, len(values)):
        up = (up * (length - 1) + gains[i - 1]) / length
        down = (down * (length - 1) + losses[i - 1]) / length
        output[i] = value()
    return pd.Series(output, index=close.index)


def indicators(bars, ma=(), ema=(), rsi_length=None, boll_length=None, boll_width=2.0):
    result = bars.copy()
    for n in (*ma, *ema, *([rsi_length] if rsi_length else []), *([boll_length] if boll_length else [])):
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 500:
            raise ValueError("指标周期须为1至500的整数")
    if not np.isfinite(boll_width) or not 0.1 <= boll_width <= 10:
        raise ValueError("BOLL标准差倍数须为0.1至10")
    for n in ma:
        result[f"MA{n}"] = bars.close.rolling(n, min_periods=n).mean()
    for n in ema:
        result[f"EMA{n}"] = bars.close.ewm(span=n, adjust=False, min_periods=n).mean()
    if rsi_length:
        result[f"RSI{rsi_length}"] = rsi(bars.close, rsi_length)
    if boll_length:
        mid = bars.close.rolling(boll_length, min_periods=boll_length).mean()
        deviation = bars.close.rolling(boll_length, min_periods=boll_length).std(ddof=0)
        result["BOLL中轨"] = mid
        result["BOLL上轨"] = mid + boll_width * deviation
        result["BOLL下轨"] = mid - boll_width * deviation
    return result


@st.cache_data(max_entries=12, show_spinner=False)
def confirmed_frame(symbol, payload, cutoff):
    return performance.parse_price(symbol, json.loads(payload), cutoff)


def figure(data, symbol, frequency, rsi_length=None, lower=30, upper=70):
    has_rsi = rsi_length is not None
    fig = make_subplots(rows=3 if has_rsi else 2, cols=1, shared_xaxes=True,
                        vertical_spacing=.035, row_heights=[.64, .14, .22] if has_rsi else [.8, .2])
    dates = data.index.strftime("%Y-%m-%d").tolist()
    fig.add_trace(go.Candlestick(x=dates, open=data.open, high=data.high, low=data.low, close=data.close,
                  name=f"{symbol} {frequency}", increasing_line_color="#d64b4b", decreasing_line_color="#078571"), row=1, col=1)
    colors = ["#d68c20", "#2d76d2", "#9355bf", "#049d9d", "#e869ab", "#7f8130"]
    for i, name in enumerate(c for c in data if c.startswith(("MA", "EMA", "BOLL"))):
        fig.add_trace(go.Scatter(x=dates, y=data[name], name=name, mode="lines", connectgaps=False,
                      line=dict(width=1.5, color=colors[i % len(colors)], dash="dot" if name.startswith("BOLL") else "solid")), row=1, col=1)
    fig.add_trace(go.Bar(x=dates, y=data.volume, name="成交量", marker_color=np.where(data.close >= data.open, "#d64b4b", "#078571")), row=2, col=1)
    if has_rsi:
        fig.add_trace(go.Scatter(x=dates, y=data[f"RSI{rsi_length}"], name=f"RSI{rsi_length}", line_color="#9355bf"), row=3, col=1)
        for level in (lower, upper):
            fig.add_hline(y=level, line_dash="dot", line_color="#98a5ad", row=3, col=1)
        fig.update_yaxes(range=[0, 100], title_text="RSI", row=3, col=1)
    fig.update_yaxes(title_text="美元", row=1, col=1)
    fig.update_yaxes(title_text="成交量", row=2, col=1)
    # Category axis omits weekends/holidays without constructing range-break grids.
    fig.update_xaxes(type="category", nticks=10, showgrid=False, rangeslider_visible=False)
    fig.update_layout(height=700 if has_rsi else 550, margin=dict(l=0, r=10, t=40, b=10),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="white", hovermode="x unified",
                      legend=dict(orientation="h", y=1.12), uirevision=f"{symbol}-{frequency}")
    return fig


def render(profile):
    st.subheader("策略标的K线与技术指标")
    st.caption(f"{profile['name']} · 涉及信号与持仓标的；指标设置仅用于图表观察。")
    a, b, c = st.columns(3)
    tickers = core.strategy_tickers(profile)
    symbol = a.selectbox("K线标的", tickers, index=tickers.index(core.base_symbol(profile)), key="tech_symbol_" + profile["id"])
    frequency = b.selectbox("K线周期", list(PERIODS), key="tech_frequency")
    window = c.selectbox("K线显示范围", list(WINDOWS), index=6 if frequency == "年K" else 4 if frequency == "周K" else 3, key="tech_window_" + frequency)
    adjusted = st.radio("K线价格口径", ["拆股调整（不含分红）", "含分红复权"], horizontal=True, key="tech_adjusted") == "含分红复权"
    selected = st.multiselect("显示技术指标", ["MA", "EMA", "RSI", "BOLL"], default=["MA", "EMA"], key="tech_indicators")
    unit = {"日K": "交易日", "周K": "周", "年K": "年"}[frequency]
    st.caption(f"周期单位：{unit}，例如MA7表示7根{frequency}收盘价的平均值；先在全部可用历史上计算，再截取显示范围。")
    ma = ema = []
    rsi_length = boll_length = None
    width, lower, upper = 2.0, 30, 70
    with st.expander("技术指标参数", expanded=True):
        a, b = st.columns(2)
        ma_text = a.text_input("MA周期（逗号分隔）", "5,20,60", key="tech_ma", disabled="MA" not in selected)
        ema_text = b.text_input("EMA周期（逗号分隔）", "20", key="tech_ema", disabled="EMA" not in selected)
        if "RSI" in selected:
            a, b, c = st.columns(3)
            rsi_length = int(a.number_input("RSI周期", 2, 500, 14, key="tech_rsi"))
            lower = int(b.number_input("RSI下参考线", 0, 49, 30, key="tech_rsi_lower"))
            upper = int(c.number_input("RSI上参考线", 51, 100, 70, key="tech_rsi_upper"))
        if "BOLL" in selected:
            a, b = st.columns(2)
            boll_length = int(a.number_input("BOLL周期", 2, 500, 20, key="tech_boll"))
            width = b.number_input("BOLL标准差倍数", .1, 10.0, 2.0, .1, key="tech_boll_width")
    try:
        ma = periods(ma_text) if "MA" in selected else []
        ema = periods(ema_text) if "EMA" in selected else []
    except ValueError as exc:
        st.warning(str(exc)); return
    snap, bundle = performance.confirmed_inputs()
    if core.snapshot_strategy(snap)["fingerprint"] != profile["fingerprint"]:
        st.info("策略已更新，等待页面刷新后加载对应K线。"); return
    cutoff = snap["last"]["date"]
    if symbol not in bundle:
        st.info(f"{symbol}暂无已确认日线，请等待后台更新行情。"); return
    try:
        daily = confirmed_frame(symbol, core.json_dump(bundle[symbol]), cutoff)
        bars = candles(daily, frequency, adjusted)
        computed = indicators(bars, ma, ema, rsi_length, boll_length, width)
    except (ValueError, KeyError, TypeError) as exc:
        st.warning(f"{symbol}K线暂不可用：{exc}"); return
    unavailable = [name for name in computed.columns if name not in bars and computed[name].isna().all()]
    if unavailable:
        st.info("历史K线根数不足，暂无法计算：" + "、".join(unavailable) + "。可缩短指标周期。")
    if WINDOWS[window]:
        computed = computed.loc[computed.index >= computed.index[-1] - pd.DateOffset(months=WINDOWS[window])]
    st.plotly_chart(figure(computed, symbol, frequency, rsi_length, lower, upper), width="stretch", key="technical_kline")
    if frequency != "日K":
        end = bars.index[-1].to_period("Y-DEC" if frequency == "年K" else "W-FRI").end_time.normalize()
        next_session = core.calendar(pd.Timestamp(cutoff).year).next_session(cutoff)
        if next_session <= end:
            st.caption(f"最新{frequency}尚未结束，仅合成截至{cutoff}的已确认日线，会随新收盘数据变化。")
    st.caption(f"数据来源：{snap['source']} · 已确认至{cutoff}（美东） · 获取时间（北京）：{core.display_time(snap['fetched'])}。红涨绿跌；公开ETF日线，不是币安证券代币报价。")
    st.caption("MA为简单均线；EMA从最早可用收盘价递推，满周期后显示；RSI采用Wilder平滑，持平为50；BOLL使用总体标准差。图表参数不会改变策略、仓位或回测。")
