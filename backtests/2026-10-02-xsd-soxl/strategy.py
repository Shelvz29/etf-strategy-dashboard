"""Auditable approximation of AIYuan XSD/SOXL V26.5, not its private code.

Only the parameters explicitly shown in the public guide are treated as known.
Ambiguous conditions are Config fields and are tested in run_backtest.py.
Signals use data available at the close; execution is in a separate module.
"""
from dataclasses import dataclass, asdict
from pathlib import Path
import json

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Config:
    annual_days: int = 252  # Guide says annual line, without specifying its length.
    macro_annual_days: int | None = None  # None uses the same length for both ETFs.
    short_days: int = 20
    macro_buffer: float = .01
    volume_multiple: float = 3.5
    volume_days: int = 60
    red_body: float = .02  # Unpublished definition of a "long bearish candle".
    high_zone: float = .95
    cash_drawdown: float = .15
    deep_bull: float = .25
    deep_bear: float = .30
    bull_cool: int = 1
    bear_cool: int = 2
    bull_defense: float = .90
    bear_defense: float = .50
    attack: float = .99
    top_release: str = "annual_or_drawdown"
    deep_latch: bool = False
    cooldown_mode: str = "consecutive_above20"
    signal_adjusted: bool = False
    peak_seed: str = "high"
    volume_include_today: bool = False
    macro_enabled: bool = True

    def to_dict(self):
        return asdict(self)


def load_data(root: Path):
    frames, audit = {}, {}
    for symbol in ("QQQ", "XSD", "SOXL"):
        j = json.loads((root / f"{symbol}.json").read_text(encoding="utf-8"))
        r = j["chart"]["result"][0]
        q = r["indicators"]["quote"][0]
        dates = pd.to_datetime(r["timestamp"], unit="s", utc=True).tz_convert(
            r["meta"]["exchangeTimezoneName"]
        ).tz_localize(None).normalize()
        f = pd.DataFrame({k: q[k] for k in ("open", "high", "low", "close", "volume")}, index=dates)
        f["adjclose"] = r["indicators"]["adjclose"][0]["adjclose"]
        if f.index.has_duplicates or not f.index.is_monotonic_increasing:
            raise ValueError(f"{symbol}: duplicate/non-monotone dates")
        if f.isna().any().any() or (f[["open", "high", "low", "close", "adjclose"]] <= 0).any().any():
            raise ValueError(f"{symbol}: missing/non-positive observations")
        if (f.high + 1e-7 < f[["open", "close", "low"]].max(axis=1)).any():
            raise ValueError(f"{symbol}: invalid high")
        if (f.low - 1e-7 > f[["open", "close", "high"]].min(axis=1)).any():
            raise ValueError(f"{symbol}: invalid low")
        factor = f.adjclose / f.close
        for field in ("open", "high", "low", "close"):
            f[f"adj_{field}"] = f[field] * factor
        frames[symbol] = f
        ret = f.adjclose.pct_change()
        audit[symbol] = {
            "rows": len(f), "first": str(f.index[0].date()), "last": str(f.index[-1].date()),
            "last_close": float(f.close.iloc[-1]), "null_cells": int(f.isna().sum().sum()),
            "zero_volume_days": int((f.volume == 0).sum()),
            "largest_abs_total_return": float(ret.abs().max()),
            "largest_abs_return_date": str(ret.abs().idxmax().date()),
            "dividends": len(r.get("events", {}).get("dividends", {})),
            "splits": r.get("events", {}).get("splits", {}),
        }
    shared = frames["XSD"].index.intersection(frames["QQQ"].index)
    if len(shared) != len(frames["XSD"]) or len(shared) != len(frames["QQQ"]):
        raise ValueError("QQQ/XSD calendar mismatch; do not silently discard observations")
    if not frames["SOXL"].index.isin(shared).all():
        raise ValueError("SOXL calendar mismatch")
    audit["qqq_xsd_dates_equal"] = True
    audit["soxl_missing_after_inception"] = [str(x.date()) for x in shared[shared >= frames["SOXL"].index[0]].difference(frames["SOXL"].index)]
    if audit["soxl_missing_after_inception"]:
        raise ValueError("SOXL has missing post-inception sessions")
    return frames, audit


def generate_signals(frames, start="2017-01-02", cfg=Config()):
    """Initialize one close before the first executable session.

    Peak starts with previous 252 highs (including first signal day), then only
    rises with new closing highs. Macro switch resets the lock/latch; not peak.
    The guide lists six state headings. NORMAL_DEFENSE and RECOVERY_ATTACK are
    our descriptive labels, not a claim to have recovered its original states.
    """
    x, q = frames["XSD"], frames["QQQ"]
    tradable = frames["SOXL"].index.intersection(x.index)
    first_trade = tradable[tradable >= pd.Timestamp(start)][0]
    first_loc = x.index.get_loc(first_trade) - 1
    macro_days = cfg.macro_annual_days or cfg.annual_days
    if first_loc < max(252, cfg.annual_days, macro_days, cfg.volume_days):
        raise ValueError("Insufficient warm-up")
    prefix = "adj_" if cfg.signal_adjusted else ""
    c, o, h = (x[f"{prefix}{name}"].to_numpy() for name in ("close", "open", "high"))
    qc = q[f"{prefix}close"].to_numpy()
    ma = pd.Series(c).rolling(cfg.annual_days).mean().to_numpy()
    qm = pd.Series(qc).rolling(macro_days).mean().to_numpy()
    short = pd.Series(c).rolling(cfg.short_days).mean().to_numpy()
    vol = x.volume.to_numpy()
    vma = x.volume.rolling(cfg.volume_days).mean()
    if not cfg.volume_include_today:
        vma = vma.shift(1)
    vma = vma.to_numpy()
    seed = h if cfg.peak_seed == "high" else c
    peak = float(np.max(seed[first_loc - 251:first_loc + 1]))
    bull = bool(qc[first_loc] >= qm[first_loc])
    top_locked = deep_locked = False
    above20_streak = below_annual_days = 0
    rows = []
    for i in range(first_loc, len(x)):
        old_bull = bull
        if not cfg.macro_enabled:
            bull = True
        elif qc[i] > qm[i] * (1 + cfg.macro_buffer):
            bull = True
        elif qc[i] < qm[i] * (1 - cfg.macro_buffer):
            bull = False
        switched = i > first_loc and old_bull != bull
        if switched:
            top_locked = deep_locked = False
            above20_streak = below_annual_days = 0
        peak = max(peak, float(c[i]))
        dd = 1 - c[i] / peak
        above_annual = c[i] >= ma[i]
        above20_streak = above20_streak + 1 if c[i] > short[i] else 0
        below_annual_days = 0 if above_annual else below_annual_days + 1
        cool = cfg.bull_cool if bull else cfg.bear_cool
        cooled = (above20_streak >= cool if cfg.cooldown_mode == "consecutive_above20"
                  else below_annual_days >= cool)
        rebound = c[i] > short[i] and short[i] > short[i - 1] and cooled
        defense = cfg.bull_defense if bull else cfg.bear_defense
        deep = cfg.deep_bull if bull else cfg.deep_bear
        if top_locked:
            release = ((not above_annual) or dd >= cfg.cash_drawdown)
            if cfg.top_release == "annual_only":
                release = not above_annual
            elif cfg.top_release == "drawdown_only":
                release = dd >= cfg.cash_drawdown
            if release:
                top_locked = False
        top_trigger = (c[i] >= peak * cfg.high_zone
                       and (o[i] - c[i]) / o[i] >= cfg.red_body
                       and vol[i] >= vma[i] * cfg.volume_multiple)
        if top_trigger:
            top_locked = True
        if above_annual:
            deep_locked = False
        if not above_annual and dd >= deep:
            deep_locked = cfg.deep_latch
        reason = ""
        if top_locked:
            state, symbol, weight = "TOP_DEFENSE", "XSD", defense
            reason = "high_zone_volume_red_candle" if top_trigger else "top_lock"
        elif above_annual:
            if dd >= cfg.cash_drawdown:
                state, symbol, weight = "PULLBACK_ATTACK", "SOXL", cfg.attack
            elif bull:
                state, symbol, weight = "NORMAL_ATTACK", "SOXL", cfg.attack
            else:
                state, symbol, weight = "NORMAL_DEFENSE", "XSD", cfg.bear_defense
        elif dd < cfg.cash_drawdown:
            state, symbol, weight = "BREAK_CASH", "CASH", 0.
        elif dd >= deep or deep_locked:
            state, symbol, weight = "DEEP_ATTACK", "SOXL", cfg.attack
        elif rebound:
            state, symbol, weight = "RECOVERY_ATTACK", "SOXL", cfg.attack
        else:
            state, symbol, weight = "SPRING_DEFENSE", "XSD", defense
            reason = "cooldown_or_shortline"
        rows.append({
            "date": x.index[i], "regime": "BULL" if bull else "BEAR", "regime_switch": switched,
            "state": state, "symbol": symbol, "weight": weight, "reason": reason,
            "xsd_close": c[i], "xsd_annual": ma[i], "xsd_ma20": short[i],
            "qqq_close": qc[i], "qqq_annual": qm[i], "anchored_peak": peak,
            "peak_drawdown": dd, "volume_multiple": vol[i] / vma[i],
            "top_trigger": top_trigger, "top_locked": top_locked,
        })
    return pd.DataFrame(rows).set_index("date")
