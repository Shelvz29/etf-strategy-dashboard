"""Read-only ETF monitor. The frozen research strategy is imported unchanged."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
import hashlib
import importlib.util
import json
import math
import os
import sqlite3
import subprocess
import sys
import tempfile
import uuid

import exchange_calendars as xc
import pandas as pd
import requests
import code_strategy

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
FROZEN = ROOT.parent / "backtests" / "2026-10-02-xsd-soxl"
DB = RUNTIME / "monitor.db"
TICKERS = ("QQQ", "XSD", "SOXL")
STRATEGY_NAME = "XSD和SOXL组合策略"
APP_NAME = "ETF策略编辑与回测看板"
DEFAULT_PRODUCTS = {
    "SOXL": {"name": "Direxion Daily Semiconductor Bull 3X ETF", "status": "已确认可买卖"},
    "XSD": {"name": "State Street SPDR S&P Semiconductor ETF", "status": "已确认可买卖"},
    "SMH": {"name": "", "status": "未确认"},
    "SOXX": {"name": "", "status": "未确认"},
    "QQQ": {"name": "", "status": "未确认"},
    "TQQQ": {"name": "", "status": "未确认"},
}
STATE_NAMES = {
    "TOP_DEFENSE": "高位放量防御", "PULLBACK_ATTACK": "回撤进攻",
    "NORMAL_ATTACK": "常态进攻", "NORMAL_DEFENSE": "熊市常态防御",
    "BREAK_CASH": "破年线离场", "DEEP_ATTACK": "深跌进攻",
    "RECOVERY_ATTACK": "短线恢复进攻", "SPRING_DEFENSE": "等待反弹防御",
}
spec = importlib.util.spec_from_file_location("original_xsd_strategy", FROZEN / "strategy.py")
baseline = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = baseline
spec.loader.exec_module(baseline)
STRATEGY_HASH = hashlib.sha256((FROZEN / "strategy.py").read_bytes()).hexdigest()


def now_utc():
    return datetime.now(timezone.utc)


def iso_now():
    return now_utc().isoformat()


def json_dump(obj):
    return json.dumps(obj, ensure_ascii=False, allow_nan=False)


def percent(value):
    return f"{value * 100:.2f}".rstrip("0").rstrip(".") + "%"


def init_db():
    RUNTIME.mkdir(exist_ok=True)
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("""CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY, created TEXT NOT NULL, kind TEXT NOT NULL,
            title TEXT NOT NULL, message TEXT NOT NULL, identity TEXT UNIQUE NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY, created TEXT NOT NULL, trade_date TEXT NOT NULL,
            reference TEXT NOT NULL, product TEXT NOT NULL, side TEXT NOT NULL,
            quantity REAL NOT NULL, price REAL NOT NULL, fee REAL NOT NULL,
            currency TEXT NOT NULL, notes TEXT NOT NULL)""")
        db.execute("INSERT OR IGNORE INTO kv VALUES (?, ?)", ("products", json_dump(DEFAULT_PRODUCTS)))
        db.execute("""CREATE TABLE IF NOT EXISTS strategy_profiles (
            id TEXT PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            revision INTEGER NOT NULL, payload TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS strategy_versions (
            id TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY (id, revision))""")
        default = default_strategy()
        db.execute("INSERT OR IGNORE INTO strategy_profiles VALUES (?,?,?,?)",
                   (default["id"], default["name"], 1, json_dump(default)))
        db.execute("INSERT OR IGNORE INTO strategy_versions VALUES (?,?,?)",
                   (default["id"], 1, json_dump(default)))
        db.execute("INSERT OR IGNORE INTO kv VALUES (?,?)", ("active_strategy", json_dump(default)))


@contextmanager
def connect():
    db = sqlite3.connect(DB, timeout=20)
    try:
        with db:
            yield db
    finally:
        db.close()


def get(key, default=None):
    with connect() as db:
        row = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def put(key, value):
    with connect() as db:
        db.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", (key, json_dump(value)))


def product_mappings():
    saved = get("products", {})
    return {symbol: dict(default, **saved.get(symbol, {}))
            for symbol, default in DEFAULT_PRODUCTS.items()}


class StrategyChanged(RuntimeError):
    """An active profile or price bundle changed while a calculation was running."""


def strategy_fingerprint(profile):
    identity = {key: profile[key] for key in ("id", "revision", "name", "parameters")}
    identity["engine"] = STRATEGY_HASH
    if profile.get("kind") == "python":
        identity.update(kind="python", code=profile["code"])
    return hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def default_strategy():
    profile = {"id": "default", "revision": 2, "name": STRATEGY_NAME,
               "parameters": dict(baseline.Config().to_dict(), attack=1.0), "description": "内置组合策略，进攻目标100%；冻结研究基线保持原样。",
               "engine_hash": STRATEGY_HASH, "created": None, "updated": None}
    profile["fingerprint"] = strategy_fingerprint(profile)
    return profile


def active_strategy():
    if not DB.exists():
        return default_strategy()
    return get("active_strategy") or default_strategy()


def snapshot_strategy(snapshot):
    return snapshot.get("strategy") or default_strategy()


def validate_parameters(parameters):
    defaults = baseline.Config().to_dict()
    if set(parameters) != set(defaults):
        raise ValueError("策略参数缺失或包含未知字段，请从现有策略复制。")
    result = dict(parameters)
    integers = {"annual_days": (2, 500), "short_days": (2, 500), "volume_days": (2, 500),
                "bull_cool": (1, 60), "bear_cool": (1, 60)}
    for key, (low, high) in integers.items():
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f"{key}须为{low}至{high}的整数。")
    macro = result["macro_annual_days"]
    if macro is not None and (isinstance(macro, bool) or not isinstance(macro, int) or not 2 <= macro <= 500):
        raise ValueError("QQQ年线周期须为2至500，或沿用XSD年线。")
    bounds = {"macro_buffer": (0, .2), "volume_multiple": (.1, 20), "red_body": (0, .5),
              "high_zone": (.5, 1), "cash_drawdown": (.001, .95), "deep_bull": (.001, .99),
              "deep_bear": (.001, .99), "bull_defense": (0, 1), "bear_defense": (0, 1), "attack": (0, 1)}
    for key, (low, high) in bounds.items():
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{key}超出允许范围。")
        result[key] = float(value)
    if result["short_days"] >= result["annual_days"]:
        raise ValueError("短线周期须小于XSD年线周期。")
    if not result["cash_drawdown"] < result["deep_bull"] <= result["deep_bear"]:
        raise ValueError("阈值须满足：回撤进攻 < 偏牛深跌 ≤ 偏熊深跌。")
    for key in ("deep_latch", "signal_adjusted", "volume_include_today", "macro_enabled"):
        if not isinstance(result[key], bool):
            raise ValueError(f"{key}须为开关值。")
    enums = {"top_release": ("annual_or_drawdown", "annual_only", "drawdown_only"),
             "cooldown_mode": ("consecutive_above20", "below_annual_days"), "peak_seed": ("high", "close")}
    for key, allowed in enums.items():
        if result[key] not in allowed:
            raise ValueError(f"{key}的选项无效。")
    return result


def state_name(code, profile=None):
    return (profile or {}).get("state_labels", {}).get(code, STATE_NAMES.get(code, code))


def strategy_code(profile):
    return code_strategy.template(profile, baseline)


def base_symbol(profile=None):
    return (profile or active_strategy()).get("base_symbol", "XSD")


def strategy_tickers(profile=None):
    return ("QQQ", "TQQQ") if base_symbol(profile) == "QQQ" else ("QQQ", base_symbol(profile), "SOXL")


def fetch_tickers(profile=None):
    return tuple(dict.fromkeys([*TICKERS, *strategy_tickers(profile)]))


def ensure_strategy_bundle(bundle, cutoff, profile):
    """Capture required extra prices without changing the confirmed monitor."""
    missing = tuple(dict.fromkeys(s for s in strategy_tickers(profile) if s not in bundle))
    if not missing:
        return bundle
    from performance import extra_prices
    frames, errors, _ = extra_prices(missing, cutoff)
    resolved = dict(bundle)
    for symbol in missing:
        if symbol not in frames:
            raise ValueError(f"{symbol}策略行情未就绪：{errors.get(symbol, '缺少完整日线')}")
        with connect() as db:
            row = db.execute("SELECT payload FROM comparison_prices WHERE symbol=?", (symbol,)).fetchone()
        if not row:
            raise ValueError(f"{symbol}历史行情尚未缓存。")
        resolved[symbol] = json.loads(row[0])
    return resolved


def strategy_frames(frames, profile):
    symbol = base_symbol(profile)
    if symbol == "XSD":
        return frames
    required = strategy_tickers(profile)
    if any(s not in frames for s in required):
        raise ValueError("策略需要" + "、".join(required) + "的完整日线。")
    # Trim only the differing history start, never discard a missing interior day.
    cutoff = str(frames[symbol].index[-1].date())
    validate_sessions({s: frames[s] for s in required}, cutoff)
    first = max(frames[s].index[0] for s in required)
    aligned = {s: frame.loc[first:] for s, frame in frames.items()}
    if any(not aligned[s].index.equals(aligned[symbol].index) for s in required):
        raise ValueError("策略所需标的的交易日期不一致。")
    return aligned


def make_strategy(name, parameters=None, description="", strategy_id=None, revision=1, *, code=None):
    name = name.strip()
    if not 1 <= len(name) <= 60 or any(ord(c) < 32 for c in name):
        raise ValueError("策略名称须为1至60个字符，且不能含换行。")
    if name.upper() in {"QQQ", "XSD", "SOXL", "TQQQ", "SMH", "VGT", "SOXX", "CASH"}:
        raise ValueError("策略名称不能与对比ETF名称相同。")
    if len(description) > 2000:
        raise ValueError("策略说明最多2000个字符。")
    metadata = code_strategy.check_source(code) if code is not None else {}
    parameters = metadata.get("PARAMETERS", parameters or baseline.Config().to_dict())
    profile = {"id": strategy_id or str(uuid.uuid4()), "revision": revision, "name": name,
               "parameters": validate_parameters(parameters), "description": description.strip(),
               "engine_hash": STRATEGY_HASH, "created": iso_now(), "updated": iso_now()}
    if code is not None:
        profile.update(kind="python", code=code, code_hash=code_strategy.code_hash(code),
                       base_symbol=metadata.get("BASE_SYMBOL", "XSD"),
                       state_labels=metadata.get("STATE_LABELS", {}), state_notes=metadata.get("STATE_NOTES", {}))
    profile["fingerprint"] = strategy_fingerprint(profile)
    return profile


def list_strategies():
    with connect() as db:
        rows = db.execute("SELECT payload FROM strategy_profiles ORDER BY CASE WHEN id='default' THEN 0 ELSE 1 END, rowid").fetchall()
    return [json.loads(row[0]) for row in rows]


def strategy_version(strategy_id, revision=None):
    with connect() as db:
        if revision is None:
            row = db.execute("SELECT payload FROM strategy_profiles WHERE id=?", (strategy_id,)).fetchone()
        else:
            row = db.execute("SELECT payload FROM strategy_versions WHERE id=? AND revision=?", (strategy_id, revision)).fetchone()
    if not row:
        raise ValueError("所选策略版本不存在。")
    return json.loads(row[0])


def strategy_history(strategy_id):
    with connect() as db:
        rows = db.execute("SELECT payload FROM strategy_versions WHERE id=? ORDER BY revision DESC", (strategy_id,)).fetchall()
    return [json.loads(row[0]) for row in rows]


def save_strategy(name, parameters=None, description="", strategy_id=None, expected_revision=None, *, code=None):
    if strategy_id == "default":
        raise ValueError("内置策略保留不覆盖，请另存为新策略。")
    if code is not None:
        # Validate the full code before any database writes; never hold a DB lock
        # while the child process is running.
        candidate = make_strategy(name, parameters, description, code=code)
        inputs, _ = captured_inputs()
        cutoff = inputs["snapshot"]["last"]["date"]
        frames = load_bundle(ensure_strategy_bundle(inputs["confirmed_bundle"], cutoff, candidate), cutoff)
        replay(frames, candidate, audit_code=True)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        old = None
        if strategy_id:
            row = db.execute("SELECT payload FROM strategy_profiles WHERE id=?", (strategy_id,)).fetchone()
            if not row:
                raise ValueError("策略已不存在。")
            old = json.loads(row[0])
            if expected_revision != old["revision"]:
                raise StrategyChanged("该策略已被更新，请重新选择最新版本后保存。")
        profile = make_strategy(name, parameters, description, strategy_id, old["revision"] + 1 if old else 1, code=code)
        if old:
            profile["created"] = old["created"]
        try:
            db.execute("INSERT INTO strategy_versions VALUES (?,?,?)", (profile["id"], profile["revision"], json_dump(profile)))
            db.execute("INSERT INTO strategy_profiles VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name, revision=excluded.revision, payload=excluded.payload",
                       (profile["id"], profile["name"], profile["revision"], json_dump(profile)))
        except sqlite3.IntegrityError as exc:
            raise ValueError("这个策略名称已存在，请使用其他名称。") from exc
    return profile


def captured_inputs():
    with connect() as db:
        rows = db.execute("SELECT key,value FROM kv WHERE key IN ('snapshot','confirmed_bundle','active_strategy')").fetchall()
    raw = dict(rows)
    return {key: json.loads(value) for key, value in raw.items()}, raw


def activate_strategy(strategy_id, revision=None):
    profile = strategy_version(strategy_id, revision)
    validate_parameters(profile["parameters"])
    for _ in range(3):
        inputs, raw = captured_inputs()
        previous = inputs["snapshot"]
        bundle = ensure_strategy_bundle(inputs["confirmed_bundle"], previous["last"]["date"], profile)
        frames = load_bundle(bundle, previous["last"]["date"])
        signals = replay(frames, profile, audit_code=True)
        snap = pack(frames, signals, previous["source"], previous.get("fetched"), previous.get("quotes"), profile)
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            live = dict(db.execute("SELECT key,value FROM kv WHERE key IN ('snapshot','confirmed_bundle','active_strategy')").fetchall())
            if live != raw:
                continue
            for key, value in (("active_strategy", profile), ("snapshot", snap), ("confirmed_bundle", bundle), ("preview", None)):
                db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, json_dump(value)))
        event("策略切换", f"已启用：{profile['name']} · v{profile['revision']}",
              "按已确认历史日线重新计算目标；不表示已执行买卖。", "activate:" + profile["fingerprint"] + ":" + iso_now())
        return snap
    raise StrategyChanged("行情正在更新，本次未切换策略，请稍后重试。")


def event(kind, title, message, identity):
    with connect() as db:
        cur = db.execute("INSERT OR IGNORE INTO events (created,kind,title,message,identity) VALUES (?,?,?,?,?)",
                         (iso_now(), kind, title, message, identity))
        return cur.rowcount == 1


def events(limit=100):
    with connect() as db:
        return pd.read_sql_query("SELECT created,kind,title,message FROM events ORDER BY id DESC LIMIT ?", db, params=(limit,))


def add_trade(trade_date, reference, product, side, quantity, price, fee, currency, notes):
    if reference not in ("XSD", "SMH", "SOXX", "SOXL", "QQQ", "TQQQ") or side not in ("买入", "卖出"):
        raise ValueError("请选择有效的参考标的和成交方向")
    if not product.strip():
        raise ValueError("请填写实际成交的币安产品名称")
    if any(not math.isfinite(v) for v in (quantity, price, fee)) or quantity <= 0 or price <= 0 or fee < 0:
        raise ValueError("数量、价格须大于零，费用须不小于零")
    if currency not in ("USDC", "USDT", "USD"):
        raise ValueError("未知结算币种")
    with connect() as db:
        db.execute("""INSERT INTO trades (created,trade_date,reference,product,side,quantity,price,fee,currency,notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                   (iso_now(), str(trade_date), reference, product.strip(), side, quantity, price, fee, currency, notes))


def trades():
    with connect() as db:
        return pd.read_sql_query("SELECT * FROM trades ORDER BY id DESC", db)


@lru_cache(maxsize=4)
def calendar(year):
    return xc.get_calendar("XNYS", start="2008-01-01", end=f"{year + 3}-12-31")


def market_clock(at=None):
    at = pd.Timestamp(at or now_utc())
    if at.tzinfo is None:
        raise ValueError("Clock must include its timezone")
    at = at.tz_convert("UTC")
    cal = calendar(at.year)
    # Exchange calendars account for US holidays, early closes and daylight saving.
    schedule = cal.schedule.loc[(at - pd.Timedelta(days=20)).date().isoformat():
                                (at + pd.Timedelta(days=20)).date().isoformat()]
    completed = schedule[schedule["close"] + pd.Timedelta(minutes=20) <= at]
    active = schedule[(schedule["open"] <= at) & (schedule["close"] > at)]
    next_open = schedule[schedule["open"] > at].iloc[0]["open"]
    session_date = at.tz_convert("America/New_York").date().isoformat()
    today = schedule.loc[session_date] if session_date in schedule.index else None
    waiting = today is not None and today["close"] <= at < today["close"] + pd.Timedelta(minutes=20)
    return {
        "expected_date": completed.index[-1].date().isoformat(),
        "is_open": not active.empty, "waiting_close": bool(waiting),
        "status": "美股交易中" if not active.empty else ("收盘数据确认中" if waiting else "美股休市 / 盘前"),
        "session_date": session_date,
        "next_open": next_open.isoformat(),
        "current_close": active.iloc[0]["close"].isoformat() if not active.empty else None,
        "now": at.isoformat(),
    }


def replay(frames, profile=None, *, audit_code=False):
    manifest = json.loads((ROOT / "strategy_manifest.json").read_text(encoding="utf-8"))
    if manifest["sha256"] != STRATEGY_HASH or manifest["parameters"] != baseline.Config().to_dict():
        raise ValueError("原策略文件或参数已改变；请核对版本后重新部署")
    profile = profile or active_strategy()
    frames = strategy_frames(frames, profile)
    cfg = baseline.Config(**validate_parameters(profile["parameters"]))
    if profile.get("kind") == "python":
        signals = code_strategy.evaluate(profile["code"], frames, audit=audit_code)
    else:
        signals = baseline.generate_signals(frames, start="2017-01-02", cfg=cfg)
    signals.attrs["strategy"] = profile
    return signals


def signal_row(index, row):
    result = json.loads(row.to_json())
    result["date"] = str(index.date())
    return result


def pack(frames, signals, source, fetched=None, quotes=None, profile=None):
    profile = profile or signals.attrs.get("strategy") or active_strategy()
    frames = strategy_frames(frames, profile)
    cfg = baseline.Config(**profile["parameters"])
    symbol = base_symbol(profile)
    x = frames[symbol]
    q = frames["QQQ"]
    xprice = x.adj_close if cfg.signal_adjusted else x.close
    qprice = q.adj_close if cfg.signal_adjusted else q.close
    chart = pd.DataFrame({"date": x.index.strftime("%Y-%m-%d"), symbol: xprice,
                          "年线": signals.xsd_annual.reindex(x.index).combine_first(xprice.rolling(cfg.annual_days).mean()),
                          "短线": signals.xsd_ma20.reindex(x.index).combine_first(xprice.rolling(cfg.short_days).mean()),
                          "QQQ": qprice, "QQQ年线": qprice.rolling(cfg.macro_annual_days or cfg.annual_days).mean(),
                          "策略锚定峰值": signals.anchored_peak.reindex(x.index)})
    chart = chart.tail(756).reset_index(drop=True)
    chart = json.loads(chart.to_json(orient="records"))
    history = [signal_row(idx, row) for idx, row in signals.tail(756).iterrows()]
    last = history[-1]
    previous = history[-2] if len(history) > 1 else None
    return {"source": source, "fetched": fetched, "last": last, "previous": previous,
            "history": history, "chart": chart, "quotes": quotes or {},
            "strategy_hash": STRATEGY_HASH, "strategy": profile, "generated": iso_now()}


def request_json(symbol, params):
    failures = []
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        try:
            response = requests.get(f"https://{host}/v8/finance/chart/{symbol}", params=params,
                                    headers={"User-Agent": "Mozilla/5.0"}, timeout=(8, 25))
            response.raise_for_status()
            payload = response.json()
            if payload["chart"].get("error") or not payload["chart"].get("result"):
                raise ValueError("行情接口未返回有效结果")
            if payload["chart"]["result"][0]["meta"]["symbol"] != symbol:
                raise ValueError("行情标的不匹配")
            return payload
        except (requests.RequestException, ValueError, KeyError) as exc:
            # Never persist request URLs, proxy addresses or credentials in error messages.
            failures.append(f"{host}: {type(exc).__name__}")
    raise RuntimeError(f"{symbol} 连接失败（{'；'.join(failures)}）")


def fetch_bundle(full=True, cutoff=None, profile=None):
    params = {}
    if full:
        cutoff = cutoff or market_clock()["expected_date"]
        # A stable completed-session boundary excludes unfinished bars and allows
        # the public provider to cache the same daily-history request.
        end = pd.Timestamp(cutoff, tz="UTC") + pd.Timedelta(days=1)
        # 2015 supplies more than 252 warm-up sessions before the unchanged 2017
        # replay start. Earlier data cannot affect the original peak seed or MAs.
        params.update(period1=1420070400, period2=int(end.timestamp()))
    else:
        params.update(range="5d")
    params.update(interval="1d", events="div,splits", includeAdjustedClose="true")
    symbols = fetch_tickers(profile)
    with ThreadPoolExecutor(max_workers=len(symbols)) as pool:
        values = list(pool.map(lambda sym: request_json(sym, params), symbols))
    return dict(zip(symbols, values))


def slice_payload(payload, cutoff):
    data = json.loads(json_dump(payload))
    r = data["chart"]["result"][0]
    dates = pd.to_datetime(r["timestamp"], unit="s", utc=True).tz_convert("America/New_York")
    keep = [i for i, date in enumerate(dates) if date.date().isoformat() <= cutoff]
    r["timestamp"] = [r["timestamp"][i] for i in keep]
    for key in ("quote", "adjclose"):
        for item in r["indicators"].get(key, []):
            for name, values in item.items():
                item[name] = [values[i] for i in keep]
    return data


def load_bundle(bundle, cutoff):
    # Staging directory is discarded only by tempfile's own scoped cleanup.
    with tempfile.TemporaryDirectory(prefix="staging-", dir=RUNTIME) as temp:
        for sym, payload in bundle.items():
            Path(temp, sym + ".json").write_text(json_dump(slice_payload(payload, cutoff)), encoding="utf-8")
        frames, _ = baseline.load_data(Path(temp))
    if any(s in bundle for s in ("SMH", "SOXX", "TQQQ")):
        from performance import parse_price
        for symbol in ("SMH", "SOXX", "TQQQ"):
            if symbol in bundle:
                frames[symbol] = parse_price(symbol, bundle[symbol], cutoff)
    return frames


def validate_sessions(frames, cutoff):
    cal = calendar(pd.Timestamp(cutoff).year)
    for sym, frame in frames.items():
        if frame.empty or str(frame.index[-1].date()) != cutoff:
            raise ValueError(f"{sym} 尚未提供 {cutoff} 完整日线，继续保留上次确认信号")
        expected = cal.sessions_in_range(frame.index[0], cutoff)
        if not frame.index.equals(expected):
            raise ValueError(f"{sym} 历史交易日不完整，暂停更新确认信号")


def quote_meta(bundle):
    quotes = {}
    for sym, payload in bundle.items():
        meta = payload["chart"]["result"][0]["meta"]
        quotes[sym] = {"price": meta.get("regularMarketPrice"), "time": meta.get("regularMarketTime"),
                       "delay_minutes": meta.get("exchangeDataDelayedBy"), "currency": meta.get("currency")}
    return quotes


def bootstrap():
    init_db()
    snap = get("snapshot")
    profile = active_strategy()
    if snap:
        if snap.get("strategy", {}).get("fingerprint") != profile["fingerprint"]:
            activate_strategy(profile["id"], profile["revision"])
        return
    clock = market_clock()
    if not all((FROZEN / "data" / f"{sym}.json").exists() for sym in TICKERS):
        bundle = fetch_bundle(True, cutoff=clock["expected_date"], profile=profile)
        frames = load_bundle(bundle, clock["expected_date"])
        validate_sessions(frames, clock["expected_date"])
        signals = replay(frames, profile)
        put("confirmed_bundle", bundle)
        put("snapshot", pack(frames, signals, "Yahoo 公开日线", iso_now(), quote_meta(bundle), profile))
        put("preview", None)
        return
    bundle = {sym: json.loads((FROZEN / "data" / f"{sym}.json").read_text(encoding="utf-8")) for sym in TICKERS}
    frames = load_bundle(bundle, clock["expected_date"])
    signals = replay(frames, profile)
    put("confirmed_bundle", bundle)
    put("snapshot", pack(frames, signals, "原回测冻结快照", profile=profile))
    put("preview", None)
    event("启动", f"已加载{STRATEGY_NAME}", "冻结快照仅供起始参考，后台正在检查最新完整日线。", "bootstrap:" + STRATEGY_HASH)


def target_changed(previous, current):
    return previous is not None and (previous["symbol"] != current["symbol"] or
                                    abs(previous["weight"] - current["weight"]) > 1e-9 or
                                    any(abs(previous.get(k, 0) - current.get(k, 0)) > 1e-9 for k in ("weight_QQQ", "weight_TQQQ")))


def target_text(row):
    if "weight_QQQ" in row:
        return " / ".join(f"{s} {percent(row['weight_' + s])}" for s in ("QQQ", "TQQQ") if row['weight_' + s] > 0) or "现金 100%"
    return f"{row['symbol']} {percent(row['weight'])}"


def notify(title, message):
    if os.name != "nt" or not get("desktop_notifications", True):
        return
    # Payload travels by file; no market or user text is evaluated as a command.
    fd, name = tempfile.mkstemp(prefix="notice-", suffix=".json", dir=RUNTIME)
    with os.fdopen(fd, "w", encoding="utf-8-sig") as file:
        json.dump({"title": title, "message": message}, file, ensure_ascii=False)
    try:
        with (RUNTIME / "notifications.log").open("ab") as log:
            return subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                     str(ROOT / "notify.ps1"), "-PayloadPath", name],
                                    creationflags=subprocess.CREATE_NO_WINDOW, stdout=log, stderr=log)
    except OSError as exc:
        event("提醒异常", "Windows提醒启动失败", type(exc).__name__, "notice-failure:" + iso_now())
        return None


def commit_confirmed(frames, bundle, fetched, profile=None):
    profile = profile or active_strategy()
    signals = replay(frames, profile)
    snap = pack(frames, signals, "Yahoo 公开日线", fetched, quote_meta(bundle), profile)
    prior = get("snapshot")
    old = prior["last"] if prior else None
    current = snap["last"]
    # One transaction keeps the replay inputs and displayed confirmed state together.
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        live = db.execute("SELECT value FROM kv WHERE key='active_strategy'").fetchone()
        if live and json.loads(live[0])["fingerprint"] != profile["fingerprint"]:
            raise StrategyChanged("计算期间策略已切换，正在使用新版本重新计算。")
        for key, value in (("snapshot", snap), ("confirmed_bundle", bundle), ("preview", None),
                           ("last_success", fetched), ("last_error", None)):
            db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, json_dump(value)))
    change = target_changed(old, current)
    if change:
        title = f"收盘目标变化：{target_text(current)}"
        message = (f"{profile['name']} · v{profile['revision']}：{current['date']} 美股收盘确认，{state_name(current['state'], profile)}。"
                   "请核对币安对应产品后手动处理；同一目标不要求每日调仓。")
        kind = "调仓提醒"
    elif old and old["date"] == current["date"]:
        return snap
    else:
        title = f"收盘已确认：{current['symbol']} {percent(current['weight'])}"
        message = f"{profile['name']} · v{profile['revision']}：{current['date']}，{state_name(current['state'], profile)}。目标未变，无新增调仓提醒。"
        kind = "收盘确认"
    identity = f"close:{profile['fingerprint']}:{current['date']}:{target_text(current)}"
    if event(kind, title, message, identity) and change:
        notify(title, message)
    return snap


def refresh_full(at=None):
    clock = market_clock(at)
    profile = active_strategy()
    bundle = fetch_bundle(True, cutoff=clock["expected_date"], profile=profile)
    frames = load_bundle(bundle, clock["expected_date"])
    validate_sessions(frames, clock["expected_date"])
    return commit_confirmed(frames, bundle, iso_now(), profile=profile)


def preview_from_bundle(bundle, at=None):
    clock = market_clock(at)
    if not clock["is_open"]:
        return None
    inputs, _ = captured_inputs()
    snapshot = inputs["snapshot"]
    profile = snapshot_strategy(snapshot)
    if any(symbol not in bundle for symbol in fetch_tickers(profile)):
        return None
    if profile["fingerprint"] != inputs.get("active_strategy", default_strategy())["fingerprint"]:
        return None
    if snapshot["last"]["date"] != clock["expected_date"]:
        return None
    session = clock["session_date"]
    confirmed = inputs["confirmed_bundle"]
    frames = load_bundle(confirmed, snapshot["last"]["date"])
    # Preview is calculated on fresh copies. It never commits peaks, locks or streaks.
    today = pd.Timestamp(session)
    for sym, payload in bundle.items():
        r = payload["chart"]["result"][0]
        quote_time = r["meta"].get("regularMarketTime")
        if not quote_time:
            return None
        quote_age = (pd.Timestamp(clock["now"]) - pd.Timestamp(quote_time, unit="s", tz="UTC")).total_seconds()
        if quote_age < -60 or quote_age > 1800:
            return None
        dates = pd.to_datetime(r["timestamp"], unit="s", utc=True).tz_convert("America/New_York")
        slots = [i for i, stamp in enumerate(dates) if str(stamp.date()) == session]
        if len(slots) != 1:
            return None
        i = slots[0]
        q = r["indicators"]["quote"][0]
        row = {name: q[name][i] for name in ("open", "high", "low", "close", "volume")}
        if any(v is None or not math.isfinite(v) for v in row.values()) or min(row[k] for k in ("open", "high", "low", "close")) <= 0:
            return None
        if row["high"] < max(row["open"], row["low"], row["close"]) or row["low"] > min(row["open"], row["close"], row["high"]):
            return None
        # A split or revision requires a full-history refresh, not mixing price scales.
        previous_slots = [j for j, stamp in enumerate(dates) if str(stamp.date()) == snapshot["last"]["date"]]
        if len(previous_slots) != 1 or abs(q["close"][previous_slots[0]] / frames[sym].close.iloc[-1] - 1) > 1e-5:
            return None
        adjusted = r["indicators"].get("adjclose", [{}])[0].get("adjclose", [])
        adj_today = adjusted[i] if len(adjusted) > i else None
        if profile["parameters"]["signal_adjusted"]:
            prior_adj = adjusted[previous_slots[0]] if len(adjusted) > previous_slots[0] else None
            if prior_adj is None or not math.isfinite(prior_adj) or abs(prior_adj / frames[sym].adjclose.iloc[-1] - 1) > 1e-5:
                return None
            if adj_today is None or not math.isfinite(adj_today) or adj_today <= 0:
                return None
        row["adjclose"] = adj_today if adj_today is not None and math.isfinite(adj_today) and adj_today > 0 else row["close"]
        factor = row["adjclose"] / row["close"]
        for name in ("open", "high", "low", "close"):
            row["adj_" + name] = row[name] * factor
        frames[sym] = pd.concat([frames[sym], pd.DataFrame([row], index=[today])])
    sig = replay(frames, profile)
    return {"last": signal_row(sig.index[-1], sig.iloc[-1]), "generated": iso_now(),
            "quotes": quote_meta(bundle), "strategy_fingerprint": profile["fingerprint"]}


def refresh_quotes():
    bundle = fetch_bundle(False)
    put("quotes", {"data": quote_meta(bundle), "fetched": iso_now()})
    preview = preview_from_bundle(bundle)
    with connect() as db:
        live = db.execute("SELECT value FROM kv WHERE key='active_strategy'").fetchone()
        if preview is None or (live and json.loads(live[0])["fingerprint"] == preview["strategy_fingerprint"]):
            db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", ("preview", json_dump(preview)))


def record_failure(exc):
    detail = str(exc)[:400]
    put("last_error", {"time": iso_now(), "message": detail})
    key = "error:" + now_utc().strftime("%Y-%m-%d-%H") + ":" + hashlib.sha256(detail.encode()).hexdigest()[:12]
    if event("数据异常", "行情未完成更新", detail + "；保留上次确认信号，请查看数据日期。", key):
        notify("行情未完成更新", "已保留上次确认信号，请打开看板查看数据日期和异常原因。")


def display_time(value, zone="Asia/Shanghai"):
    if not value:
        return "—"
    stamp = pd.to_datetime(value, unit="s", utc=True) if isinstance(value, (int, float)) else pd.Timestamp(value)
    return stamp.tz_convert(zone).strftime("%m-%d %H:%M:%S")
