"""Long-only QQQ/TQQQ execution; existing single-asset engine stays frozen."""
import math

import pandas as pd


def allocate(equity, values, weights, rate):
    """Solve after-cost equity: fees also reduce target notionals."""
    lo, hi = 0.0, equity
    for _ in range(60):
        after = (lo + hi) / 2
        fee = sum(abs(after * weights[s] - values[s]) * rate for s in weights)
        if after + fee > equity:
            hi = after
        else:
            lo = after
    after = (lo + hi) / 2
    targets = {s: after * weights[s] for s in weights}
    fee = sum(abs(targets[s] - values[s]) * rate for s in weights)
    return targets, fee


def simulate(frames, signals, start="2017-01-03", end=None, cost_bps=10., initial=100_000.,
             execution="next_open", daily_rebalance=False):
    if execution != "next_open" or not 0 <= cost_bps <= 100 or not math.isfinite(initial) or initial <= 0:
        raise ValueError("双资产回测只支持次日开盘，成本0至100基点和正本金。")
    end = pd.Timestamp(end or signals.index[-1])
    days = signals.index[(signals.index >= pd.Timestamp(start)) & (signals.index <= end)]
    actionable = signals.shift(1).reindex(days)
    symbols = ("QQQ", "TQQQ")
    cash, units, last_target = initial, dict.fromkeys(symbols, 0.), None
    prior = initial
    rows, orders = [], []
    for day in days:
        sig = actionable.loc[day]
        weights = {s: float(sig["weight_" + s]) if pd.notna(sig.symbol) else 0. for s in symbols}
        if any(not math.isfinite(w) or not 0 <= w <= 1 for w in weights.values()) or sum(weights.values()) > 1 + 1e-12:
            raise ValueError("双资产目标权重无效。")
        values = {s: units[s] * frames[s].loc[day, "adj_open"] for s in symbols}
        before = cash + sum(values.values())
        target = (sig.get("state"), *weights.values())
        # Moomoo NORMAL uses drift of the two invested values, excluding cash.
        band = float(sig.rebalance_band) if pd.notna(sig.symbol) else 0.
        previous_day = signals.index[signals.index.get_loc(day) - 1]
        previous_values = {s: units[s] * frames[s].loc[previous_day, "adj_close"] for s in symbols}
        invested = sum(previous_values.values())
        drift = band > 0 and invested > 0 and abs(previous_values["QQQ"] - previous_values["TQQQ"]) / invested > band
        changed = last_target != target or daily_rebalance or drift
        fee, turnover = 0., 0.
        if changed:
            targets, fee = allocate(before, values, weights, cost_bps / 10_000)
            signal_day = signals.index[signals.index.get_loc(day) - 1]
            for s in symbols:
                delta = targets[s] - values[s]
                turnover += abs(delta)
                if abs(delta) > 1e-8:
                    orders.append(dict(date=day, signal_date=signal_day, symbol=s,
                                       side="BUY" if delta > 0 else "SELL", notional=abs(delta),
                                       fee=abs(delta) * cost_bps / 10_000, state=sig.state))
                units[s] = targets[s] / frames[s].loc[day, "adj_open"]
            cash = before - fee - sum(targets.values())
            if cash < -1e-7:
                raise AssertionError("双资产回测现金不足")
            cash = max(0., cash)
            last_target = target
        equity = cash + sum(units[s] * frames[s].loc[day, "adj_close"] for s in symbols)
        rows.append(dict(date=day, equity=equity, cash=cash, daily_return=equity / prior - 1,
                         units_QQQ=units["QQQ"], units_TQQQ=units["TQQQ"], fees=fee,
                         turnover=turnover, rebalance=changed, state=sig.state, open_equity=before))
        prior = equity
    return pd.DataFrame(rows).set_index("date"), pd.DataFrame(orders)
