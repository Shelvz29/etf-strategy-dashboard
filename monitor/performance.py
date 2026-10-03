"""Historical comparisons using the unchanged original portfolio engine."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import importlib.util
import json
import math
import sys

import numpy as np
import pandas as pd

import core

BENCHMARKS = ("TQQQ", "QQQ", "XSD", "SMH", "VGT", "SOXX", "SOXL")
STRATEGY = core.STRATEGY_NAME
CONTINUOUS = "历史连续持仓"
FRESH = "期初从现金建仓"
PERIODS = ("近1年", "近2年", "近3年", "近5年", "全部历史")
FIRST_TRADE = pd.Timestamp("2017-01-03")
spec = importlib.util.spec_from_file_location("original_portfolio_engine", core.FROZEN / "engine.py")
engine = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = engine
spec.loader.exec_module(engine)


def confirmed_inputs():
    # One SQL statement reads a consistent replay-input/snapshot pair.
    with core.connect() as db:
        rows = db.execute("SELECT key,value FROM kv WHERE key IN ('snapshot','confirmed_bundle')").fetchall()
    values = {key: json.loads(value) for key, value in rows}
    return values["snapshot"], values["confirmed_bundle"]


def init_price_cache():
    with core.connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS comparison_prices (
            symbol TEXT PRIMARY KEY, through_date TEXT NOT NULL,
            fetched TEXT NOT NULL, payload TEXT NOT NULL)""")


def parse_price(symbol, payload, cutoff):
    r = core.slice_payload(payload, cutoff)["chart"]["result"][0]
    if r["meta"].get("symbol") != symbol:
        raise ValueError(f"{symbol} 返回标的不匹配")
    if r["meta"].get("dataGranularity", "1d") != "1d":
        raise ValueError(f"{symbol} 返回的不是日线")
    if r["meta"].get("currency", "USD") != "USD":
        raise ValueError(f"{symbol} 行情币种不是美元")
    dates = pd.to_datetime(r["timestamp"], unit="s", utc=True).tz_convert("America/New_York").tz_localize(None).normalize()
    quote = r["indicators"]["quote"][0]
    frame = pd.DataFrame({key: quote[key] for key in ("open", "high", "low", "close", "volume")}, index=dates)
    frame["adjclose"] = r["indicators"]["adjclose"][0]["adjclose"]
    prices = frame[["open", "high", "low", "close", "adjclose"]]
    if frame.empty or frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError(f"{symbol} 日线为空或日期重复")
    if not np.isfinite(frame.to_numpy(dtype=float)).all() or (prices <= 0).any().any() or (frame.volume < 0).any():
        raise ValueError(f"{symbol} 日线含缺失或无效价格")
    if (frame.high + 1e-7 < frame[["open", "low", "close"]].max(axis=1)).any() or (frame.low - 1e-7 > frame[["open", "high", "close"]].min(axis=1)).any():
        raise ValueError(f"{symbol} 日线高低价无效")
    factor = frame.adjclose / frame.close
    for field in ("open", "high", "low", "close"):
        frame["adj_" + field] = frame[field] * factor
    if str(frame.index[-1].date()) != cutoff:
        raise ValueError(f"{symbol} 未覆盖至 {cutoff}")
    expected = core.calendar(pd.Timestamp(cutoff).year).sessions_in_range(frame.index[0], cutoff)
    if not frame.index.equals(expected) or frame.index[0] > FIRST_TRADE:
        raise ValueError(f"{symbol} 交易日不完整，暂不纳入对比")
    return frame


def extra_prices(symbols, cutoff, force=False):
    """Keep each successful download even if a different ETF is unavailable."""
    init_price_cache()
    frames, errors, pending, metadata = {}, {}, [], {}
    cached = {}
    with core.connect() as db:
        for symbol in symbols:
            row = db.execute("SELECT through_date,fetched,payload FROM comparison_prices WHERE symbol=?", (symbol,)).fetchone()
            if row and row[0] >= cutoff:
                try:
                    frame = parse_price(symbol, json.loads(row[2]), cutoff)
                    cached[symbol] = (frame, row[1])
                except (ValueError, KeyError, TypeError):
                    pass
            if symbol in cached and not force:
                frames[symbol], metadata[symbol] = cached[symbol]
            else:
                pending.append(symbol)
    end = pd.Timestamp(cutoff, tz="UTC") + pd.Timedelta(days=1)
    params = {"period1": 1420070400, "period2": int(end.timestamp()), "interval": "1d",
              "events": "div,splits", "includeAdjustedClose": "true"}

    def download(symbol):
        payload = core.request_json(symbol, params)
        return payload, parse_price(symbol, payload, cutoff)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(download, symbol): symbol for symbol in pending}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                payload, frame = future.result()
                fetched = core.iso_now()
                with core.connect() as db:
                    db.execute("INSERT OR REPLACE INTO comparison_prices VALUES (?,?,?,?)",
                               (symbol, cutoff, fetched, core.json_dump(payload)))
                frames[symbol], metadata[symbol] = frame, fetched
            except Exception as exc:
                errors[symbol] = str(exc)[:350]
                if symbol in cached:
                    frames[symbol], metadata[symbol] = cached[symbol]
                    errors[symbol] += "；本次使用仍覆盖所需日期的缓存日线"
    return frames, errors, metadata


def datasets(bundle, cutoff, selected, force=False, profile=None):
    selected = tuple(symbol for symbol in BENCHMARKS if symbol in selected)
    profile = profile or core.active_strategy()
    bundle = core.ensure_strategy_bundle(bundle, cutoff, profile)
    frames = core.load_bundle(bundle, cutoff)
    core.validate_sessions(frames, cutoff)
    signals = core.replay(frames, profile, audit_code=True)
    extras = tuple(symbol for symbol in selected if symbol not in frames)
    extra, errors, metadata = extra_prices(extras, cutoff, force)
    frames.update(extra)
    return frames, signals, errors, metadata


@dataclass(frozen=True)
class Window:
    label: str
    baseline: pd.Timestamp | None
    first: pd.Timestamp
    end: pd.Timestamp


def window(index, label, start=None, end=None):
    end = pd.Timestamp(end or index[-1])
    eligible = index[(index >= FIRST_TRADE) & (index <= end)]
    if eligible.empty:
        raise ValueError("所选范围内没有可回测的交易日")
    end = eligible[-1]
    if label.startswith("近"):
        years = int(label[1:-1])
        anchor = end - pd.DateOffset(years=years)
        prior = eligible[eligible <= anchor]
        if prior.empty:
            raise ValueError(f"历史长度不足{years}年")
        baseline = prior[-1]
        cut = eligible[eligible > baseline]
    elif label == "全部历史":
        baseline, cut = None, eligible
    else:
        start = pd.Timestamp(start)
        if start < FIRST_TRADE or start > end:
            raise ValueError("起始日期须在2017-01-03与结束日期之间")
        cut = eligible[eligible >= start]
        prior = eligible[eligible < start]
        baseline = prior[-1] if len(prior) else None
    if cut.empty:
        raise ValueError("所选范围内没有交易日")
    return Window(label, baseline, cut[0], end)


def full_strategy(frames, signals, cost_bps=10.0):
    nav, _ = engine.simulate(frames, signals, start=str(FIRST_TRADE.date()),
                             end=str(signals.index[-1].date()), cost_bps=cost_bps,
                             initial=100_000.0, execution="next_open", daily_rebalance=False)
    return nav.equity / 100_000.0


def buy_hold(frame, first, end, cost_bps=10.0):
    cut = frame.loc[first:end]
    if cut.empty:
        raise ValueError("对比ETF没有所选区间的日线")
    return cut.adj_close / (float(cut.adj_open.iloc[0]) * (1 + cost_bps / 10_000))


def unit_result(curve, initial, win, mode):
    curve = curve / initial
    # Drawdown always starts at initial capital, even if entry-day costs cause a loss.
    wealth = np.r_[1.0, curve.to_numpy(dtype=float)]
    dd = wealth / np.maximum.accumulate(wealth) - 1
    if mode == CONTINUOUS and win.baseline is not None:
        elapsed = (win.end - win.baseline).days
        anchor = win.baseline
    else:
        elapsed = (win.end - win.first).days + 1
        # This point represents pre-entry capital; daily observations begin at first.
        anchor = win.first - pd.Timedelta(seconds=1)
    plotted = pd.concat([pd.Series([1.0], index=[anchor]), curve])
    plotted.index.name = "date"
    drawdown = pd.Series(dd, index=plotted.index, name="drawdown")
    total = float(wealth[-1] - 1)
    metric = {"annualized_return": float(wealth[-1] ** (365.25 / elapsed) - 1),
              "max_drawdown": float(-dd.min()), "total_return": total,
              "multiple": float(wealth[-1]), "first_session": str(win.first.date()),
              "end_session": str(win.end.date()), "baseline_close": str(win.baseline.date()) if win.baseline is not None and mode == CONTINUOUS else None,
              "calendar_days": elapsed, "sessions": len(curve),
              "drawdown_trough": str(plotted.index[int(np.argmin(dd))].date())}
    return {"wealth": plotted, "drawdown": drawdown, "metrics": metric}


def compare_window(frames, signals, full, selected, win, mode=CONTINUOUS, cost_bps=10.0):
    if mode not in (CONTINUOUS, FRESH) or not 0 <= cost_bps <= 100:
        raise ValueError("未知回测口径或交易成本无效")
    if mode == CONTINUOUS:
        capital = float(full.loc[win.baseline]) if win.baseline is not None else 1.0
        cut = full.loc[win.first:win.end]
    else:
        nav, _ = engine.simulate(frames, signals, start=str(win.first.date()), end=str(win.end.date()),
                                 cost_bps=cost_bps, initial=100_000.0, execution="next_open", daily_rebalance=False)
        cut, capital = nav.equity / 100_000.0, 1.0
    name = signals.attrs.get("strategy", {}).get("name", STRATEGY)
    results = {name: unit_result(cut, capital, win, mode)}
    for symbol in selected:
        if symbol not in frames:
            continue
        if mode == CONTINUOUS:
            history = buy_hold(frames[symbol], full.index[0], win.end, cost_bps)
            capital = float(history.loc[win.baseline]) if win.baseline is not None else 1.0
            cut = history.loc[win.first:win.end]
        else:
            cut, capital = buy_hold(frames[symbol], win.first, win.end, cost_bps), 1.0
        if not cut.index.equals(full.loc[win.first:win.end].index):
            raise ValueError(f"{symbol} 与策略交易日期不一致，暂停该对比")
        results[symbol] = unit_result(cut, capital, win, mode)
    return results


def report(frames, signals, selected, period, mode=CONTINUOUS, start=None, end=None, cost_bps=10.0,
           comparisons=None):
    full = full_strategy(frames, signals, cost_bps)
    chosen = window(full.index, period, start, end)
    results = compare_window(frames, signals, full, selected, chosen, mode, cost_bps)
    rows, unavailable = [], []
    for label in PERIODS:
        try:
            win = window(full.index, label, end=chosen.end)
            items = results if win == chosen else compare_window(frames, signals, full, selected, win, mode, cost_bps)
            rows.extend({"period": label, "asset": asset, **data["metrics"]} for asset, data in items.items())
        except ValueError as exc:
            unavailable.append(str(exc))
    # A comparison strategy executes its own signals, with exactly the same
    # calendar, capital convention and transaction costs as the main strategy.
    for name, (other_frames, other_signals) in (comparisons or {}).items():
        try:
            if name in results:
                raise ValueError("对比名称重复")
            other_full = full_strategy(other_frames, other_signals, cost_bps)
            if not other_full.index.equals(full.index):
                raise ValueError("与主策略交易日期不一致")
            item = compare_window(other_frames, other_signals, other_full, [], chosen, mode, cost_bps)
            comparison_rows = []
            for label in PERIODS:
                try:
                    win = window(full.index, label, end=chosen.end)
                except ValueError:
                    continue
                data = item if win == chosen else compare_window(other_frames, other_signals, other_full, [], win, mode, cost_bps)
                comparison_rows.append({"period": label, "asset": name, **next(iter(data.values()))["metrics"]})
            results[name] = next(iter(item.values()))
            rows.extend(comparison_rows)
        except (ValueError, KeyError, RuntimeError) as exc:
            unavailable.append(f"{name}：{exc}；本次未纳入该策略，其余对比继续计算。")
    return {"results": results, "periods": pd.DataFrame(rows), "window": chosen, "unavailable": unavailable}


def money_table(results, principal):
    if not math.isfinite(principal) or principal <= 0:
        raise ValueError("本金须为大于零的有限数值")
    return pd.DataFrame([{"asset": asset, **data["metrics"],
                          "ending_capital": principal * data["metrics"]["multiple"],
                          "profit": principal * data["metrics"]["total_return"]}
                         for asset, data in results.items()])
