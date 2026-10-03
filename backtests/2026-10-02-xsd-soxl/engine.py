"""Long-only, self-financing backtest with delayed execution and exact fees.

Adjusted OHLC tracks a fractional-unit total-return account; dividend reinvestment
is implicit. Cash rate and tax are zero. Rebalance only when the target changes.
This is not a point-in-time physical-share/dividend settlement ledger.
"""
import numpy as np
import pandas as pd


def rebalance(equity, current_value, same_asset, weight, fee_rate):
    if not 0 <= weight <= 1 or not 0 <= fee_rate < 1:
        raise ValueError("Invalid target/fee")
    if same_asset:
        buying = weight * equity >= current_value
        if buying:
            after = (equity + fee_rate * current_value) / (1 + fee_rate * weight)
        else:
            after = (equity - fee_rate * current_value) / (1 - fee_rate * weight)
        turnover = abs(weight * after - current_value)
    else:
        after = (equity - fee_rate * current_value) / (1 + fee_rate * weight)
        turnover = current_value + weight * after
    fee = fee_rate * turnover
    if not np.isclose(equity - fee, after, atol=1e-7):
        raise AssertionError("Cash/fee conservation failure")
    return after, weight * after, fee, turnover


def simulate(frames, signals, start="2017-01-02", end="2026-10-01",
             cost_bps=10., initial=100_000., execution="next_open", extra_lag=0,
             daily_rebalance=False):
    if execution not in ("next_open", "next_close", "same_close_biased"):
        raise ValueError("Unknown execution")
    days = frames["SOXL"].index.intersection(signals.index)
    days = days[(days >= pd.Timestamp(start)) & (days <= pd.Timestamp(end))]
    # Signals are deliberately lagged before selecting the requested test window.
    lag = (0 if execution == "same_close_biased" else 1) + extra_lag
    actionable = signals.shift(lag).reindex(days)
    rate = cost_bps / 10_000
    cash, units, held, last_target = initial, 0., "CASH", None
    prior_close, historical_high = initial, initial
    rows, orders = [], []
    close_field = "adj_close"
    for date in days:
        sig = actionable.loc[date]
        if pd.isna(sig.symbol):
            symbol, w = "CASH", 0.
        else:
            symbol, w = str(sig.symbol), float(sig.weight)
        signal_date = signals.index[signals.index.get_loc(date) - lag] if not pd.isna(sig.symbol) else pd.NaT
        fill_field = "adj_open" if execution == "next_open" else close_field
        old_val = units * frames[held].loc[date, fill_field] if held != "CASH" else 0.
        before = cash + old_val
        # With close execution, the old asset is held during today's session.
        if execution != "next_open" and held != "CASH":
            session_high = cash + units * frames[held].loc[date, "adj_high"]
            session_low = cash + units * frames[held].loc[date, "adj_low"]
            session_open = cash + units * frames[held].loc[date, "adj_open"]
        else:
            session_high = session_low = session_open = before
        fees, turnover = 0., 0.
        target = (symbol, w)
        changed = last_target != target or daily_rebalance
        if changed:
            same = symbol == held
            after, new_val, fees, turnover = rebalance(before, old_val, same, w, rate)
            if same:
                delta = new_val - old_val
                if abs(delta) > 1e-8:
                    orders.append({"date": date, "signal_date": signal_date, "symbol": symbol,
                                   "side": "BUY" if delta > 0 else "SELL", "notional": abs(delta),
                                   "fee": abs(delta) * rate, "state": sig.get("state", "BENCHMARK")})
            else:
                if old_val > 0:
                    orders.append({"date": date, "signal_date": signal_date, "symbol": held,
                                   "side": "SELL", "notional": old_val, "fee": old_val * rate,
                                   "state": sig.get("state", "BENCHMARK")})
                if new_val > 0:
                    orders.append({"date": date, "signal_date": signal_date, "symbol": symbol,
                                   "side": "BUY", "notional": new_val, "fee": new_val * rate,
                                   "state": sig.get("state", "BENCHMARK")})
            held = symbol
            units = new_val / frames[held].loc[date, fill_field] if held != "CASH" else 0.
            cash = after - new_val
            last_target = target
        if cash < -1e-7 or units < -1e-7:
            raise AssertionError("Negative cash or short holding")
        if held != "CASH":
            equity = cash + units * frames[held].loc[date, close_field]
            if execution == "next_open":
                session_high = max(session_high, cash + units * frames[held].loc[date, "adj_high"])
                session_low = min(session_low, cash + units * frames[held].loc[date, "adj_low"])
                session_open = before
        else:
            equity = cash
        low = min(session_low, equity, before, before - fees)
        high = max(session_high, equity, before)
        certain_dd = low / max(historical_high, session_open) - 1
        possible_dd = low / max(historical_high, high) - 1
        historical_high = max(historical_high, high)
        actual_weight = 1 - cash / equity
        rows.append({
            "date": date, "equity": equity, "daily_return": equity / prior_close - 1,
            "cash": cash, "held": held, "asset_weight": actual_weight,
            "nominal_exposure": actual_weight * (3 if held == "SOXL" else 1),
            "regime": sig.get("regime", "N/A"), "state": sig.get("state", "N/A"),
            "signal_date": signal_date, "target_weight": w, "rebalance": changed,
            "fees": fees, "turnover": turnover, "open_equity": before,
            "session_high": high, "session_low": low,
            "intraday_dd_certain": certain_dd, "intraday_dd_possible": possible_dd,
        })
        prior_close = equity
    nav = pd.DataFrame(rows).set_index("date")
    trades = pd.DataFrame(orders, columns=["date", "signal_date", "symbol", "side", "notional", "fee", "state"])
    return nav, trades


def metrics(nav, trades=None, initial=100_000.):
    eq = nav.equity
    peak = np.maximum.accumulate(np.r_[initial, eq.to_numpy()])[1:]
    dd = eq.to_numpy() / peak - 1
    years = ((nav.index[-1] - nav.index[0]).days + 1) / 365.25
    returns = nav.daily_return.to_numpy()
    vol = np.std(returns, ddof=1) * np.sqrt(252)
    cagr = (eq.iloc[-1] / initial) ** (1 / years) - 1
    worst_i = int(np.argmin(dd))
    worst_date = nav.index[worst_i]
    before = eq.iloc[:worst_i + 1]
    peak_date = before.idxmax() if before.max() >= initial else nav.index[0]
    recovery = eq.loc[worst_date:]
    recovery = recovery[recovery >= peak[worst_i]]
    return {
        "start": str(nav.index[0].date()), "end": str(nav.index[-1].date()), "days": len(nav),
        "total_return": float(eq.iloc[-1] / initial - 1), "cagr": float(cagr),
        "final_equity": float(eq.iloc[-1]), "multiple": float(eq.iloc[-1] / initial),
        "max_drawdown_close": float(np.min(dd)), "annual_volatility": float(vol),
        "sharpe_rf0": float(np.mean(returns) * 252 / vol) if vol else 0.,
        "calmar": float(cagr / abs(np.min(dd))) if np.min(dd) < 0 else 0.,
        "intraday_dd_certain": float(nav.intraday_dd_certain.min()),
        "intraday_dd_possible": float(nav.intraday_dd_possible.min()),
        "max_dd_peak_date": str(peak_date.date()), "max_dd_trough_date": str(worst_date.date()),
        "max_dd_recovered_date": str(recovery.index[0].date()) if len(recovery) else None,
        "order_count": int(len(trades)) if trades is not None else None,
        "rebalance_days": int((nav.turnover > 1e-8).sum()),
        "annual_one_way_turnover": float((nav.turnover / nav.open_equity).sum() / years),
        "soxl_days_fraction": float((nav.held == "SOXL").mean()),
        "cash_days_fraction": float((nav.held == "CASH").mean()),
        "average_nominal_exposure": float(nav.nominal_exposure.mean()),
    }


def period_metrics(nav, start, end, initial=100_000.):
    cut = nav.loc[start:end].copy()
    if cut.empty:
        return {}
    before = nav.loc[nav.index < cut.index[0]]
    capital = float(before.equity.iloc[-1]) if len(before) else initial
    result = metrics(cut, initial=capital)
    return {"return": result["total_return"], "max_drawdown_close": result["max_drawdown_close"],
            "start": result["start"], "end": result["end"]}
