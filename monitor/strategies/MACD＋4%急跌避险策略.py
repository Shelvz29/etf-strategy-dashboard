# MACD＋4%急跌避险策略
# 已验证研究基线：MACD柱线<0且SMH昨收至最低跌幅≥4%。
# 收盘确认、次日开盘执行；不包含部分止盈或分批买回。
# 将XSD的信号与防御角色完整替换为SMH，原有参数保持不变。
# 修改 PARAMETERS 或下方 generate_signals 的判断逻辑，再点击应用代码。
# frames: QQQ / SMH / SOXL 的日线 DataFrame；只能使用当日及之前的数据。
# 返回以日期为索引的信号表；保留模板的输出字段。仓位为 0～1。
# xsd_close/xsd_annual/xsd_ma20 是兼容字段，保存当前信号标的的指标。
from dataclasses import dataclass, asdict
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
    attack: float = 1.0
    top_release: str = "annual_or_drawdown"
    deep_latch: bool = False
    cooldown_mode: str = "consecutive_above20"
    signal_adjusted: bool = False
    peak_seed: str = "high"
    volume_include_today: bool = False
    macro_enabled: bool = True

    def to_dict(self):
        return asdict(self)

# 信号与防御标的；QQQ用于环境判断，SOXL用于进攻。
BASE_SYMBOL = 'SMH'

# 参数也用于看板上的周期与价格口径标注。
PARAMETERS = {
    'annual_days': 252,
    'macro_annual_days': None,
    'short_days': 20,
    'macro_buffer': 0.01,
    'volume_multiple': 3.5,
    'volume_days': 60,
    'red_body': 0.02,
    'high_zone': 0.95,
    'cash_drawdown': 0.15,
    'deep_bull': 0.25,
    'deep_bear': 0.3,
    'bull_cool': 1,
    'bear_cool': 2,
    'bull_defense': 0.9,
    'bear_defense': 0.5,
    'attack': 1.0,
    'top_release': 'annual_or_drawdown',
    'deep_latch': False,
    'cooldown_mode': 'consecutive_above20',
    'signal_adjusted': False,
    'peak_seed': 'high',
    'volume_include_today': False,
    'macro_enabled': True,
}

# 可选：自定义状态名称和解释；解释须与修改后的代码一致。
STATE_LABELS = {'TOP_DEFENSE': '高位放量防御', 'PULLBACK_ATTACK': '回撤进攻', 'NORMAL_ATTACK': '常态进攻', 'NORMAL_DEFENSE': '熊市常态防御', 'BREAK_CASH': '破年线离场', 'DEEP_ATTACK': '深跌进攻', 'RECOVERY_ATTACK': '短线恢复进攻', 'SPRING_DEFENSE': '等待反弹防御', 'RISK_CASH_TRIGGER': 'MACD急跌触发避险', 'RISK_CASH_COOLDOWN': '现金避险等待', 'RISK_CASH_RECOVERY': '现金等待趋势恢复'}
STATE_NOTES = {'TOP_DEFENSE': '高位放量防御锁定中；此状态优先于其他七种状态。 新锁定需同时满足：SMH距锚定峰值不超过5%、阴线实体跌幅（开盘价−收盘价）/开盘价至少2%、当日成交量至少为此前60个交易日平均成交量的3.5倍。跌破年线或距峰值回撤达到15%时解除已有锁定；QQQ偏牛/偏熊切换也会清除锁定，当天仍可能重新触发。 基础状态继续独立计算；MACD急跌现金锁定生效时，实际目标由现金避险覆盖。', 'PULLBACK_ATTACK': 'SMH收盘价≥年线，距锚定峰值回撤≥15%；偏牛、偏熊均适用。 “回撤”指SMH价格从策略锚定峰值下跌，不是你的账户已经亏损。此分支不要求20日线恢复条件，也不保证反弹或买在最低点。 基础状态继续独立计算；MACD急跌现金锁定生效时，实际目标由现金避险覆盖。', 'NORMAL_ATTACK': 'SMH收盘价≥年线、距峰值回撤<15%，且QQQ环境偏牛。 即使没有明显回撤，也可能处于此状态。“常态进攻”和“回撤进攻”的目标标的及仓位相同，二者切换本身不会要求调仓。 基础状态继续独立计算；MACD急跌现金锁定生效时，实际目标由现金避险覆盖。', 'NORMAL_DEFENSE': 'SMH收盘价≥年线、距峰值回撤<15%，且QQQ环境偏熊。 此分支不使用SOXL。QQQ环境恢复偏牛后，会重新按同一天的SMH条件选择状态。 基础状态继续独立计算；MACD急跌现金锁定生效时，实际目标由现金避险覆盖。', 'BREAK_CASH': 'SMH收盘价<年线，距峰值回撤<15%。 这里的现金指分配给本策略的资金不配置SMH或SOXL。此阈值不是账户亏损15%自动止损规则。 基础状态继续独立计算；MACD急跌现金锁定生效时，实际目标由现金避险覆盖。', 'DEEP_ATTACK': 'SMH收盘价<年线且距峰值回撤≥15%；达到深跌阈值（偏牛25%／偏熊30%）。 此分支优先于短线恢复条件，不要求先站回20日线。未启用深跌锁定，每天按最新确认收盘重新判断。它不是账户最大回撤控制。 基础状态继续独立计算；MACD急跌现金锁定生效时，实际目标由现金避险覆盖。', 'RECOVERY_ATTACK': 'SMH收盘价<年线；距峰值回撤≥15%且未达深跌阈值、无深跌锁定；收盘价>20日线、该均线较前日上升，连续收盘站上短线偏牛≥1天/偏熊≥2天。 连续天数按已结束的美股交易日计算，包含当天；跌回20日线或QQQ环境切换会重置计数。短线恢复不表示已经重新站上年线。 基础状态继续独立计算；MACD急跌现金锁定生效时，实际目标由现金避险覆盖。', 'SPRING_DEFENSE': 'SMH收盘价<年线；距峰值回撤≥15%且未达深跌阈值、无深跌锁定；短线恢复条件尚未全部满足。 偏牛使用SMH90%和现金10%，偏熊使用SMH50%和现金50%。SMH仍会涨跌，“防御”不代表本金保本。 基础状态继续独立计算；MACD急跌现金锁定生效时，实际目标由现金避险覆盖。', 'RISK_CASH_TRIGGER': 'SMH MACD(12,26,9)柱线<0，且（昨日收盘−当日最低）/昨日收盘≥4%，两个条件同时成立。未锁定时仅在基础目标非现金时启动；已锁定期间再次触发会重置为5个交易日。收盘后确认，当天跌幅仍计入，下一交易日开盘目标为现金100%。此状态覆盖基础组合八种状态。', 'RISK_CASH_COOLDOWN': '已触发MACD且4%急跌避险，等待计数尚未归零，目标为现金100%。每个已结束交易日减1；重复触发重置5日。基础SMH/SOXL状态及峰值继续独立演算，切换基础状态或QQQ环境不会自行解除避险。', 'RISK_CASH_RECOVERY': '5交易日等待已结束，但SMH MACD柱线≥0与收盘≥EMA20的恢复条件未同时满足，继续现金100%。恢复且当天没有重复触发后，采用当天基础组合的SMH、SOXL或现金目标，不强制直接买SOXL，不重置基础峰值。'}


def generate_base_signals(frames, start="2017-01-02", cfg=Config(**PARAMETERS)):
    """按已确认收盘日生成目标，下一交易日开盘执行。"""
    x, q = frames[BASE_SYMBOL], frames["QQQ"]
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
            state, symbol, weight = "TOP_DEFENSE", BASE_SYMBOL, defense
            reason = "high_zone_volume_red_candle" if top_trigger else "top_lock"
        elif above_annual:
            if dd >= cfg.cash_drawdown:
                state, symbol, weight = "PULLBACK_ATTACK", "SOXL", cfg.attack
            elif bull:
                state, symbol, weight = "NORMAL_ATTACK", "SOXL", cfg.attack
            else:
                state, symbol, weight = "NORMAL_DEFENSE", BASE_SYMBOL, cfg.bear_defense
        elif dd < cfg.cash_drawdown:
            state, symbol, weight = "BREAK_CASH", "CASH", 0.
        elif dd >= deep or deep_locked:
            state, symbol, weight = "DEEP_ATTACK", "SOXL", cfg.attack
        elif rebound:
            state, symbol, weight = "RECOVERY_ATTACK", "SOXL", cfg.attack
        else:
            state, symbol, weight = "SPRING_DEFENSE", BASE_SYMBOL, defense
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


# 避险参数在这里编辑；PARAMETERS保留基础组合参数。
# 修改阈值或等待天数后，请同步修改下方对应状态解释。
RISK_RULES = {
    'macd_fast': 12,
    'macd_slow': 26,
    'macd_signal': 9,
    'drop_threshold': 0.04,
    'cooldown_days': 5,
    'recovery_ema': 20,
}


def apply_cash_risk(signals, hist, daily_drop, healthy, cooldown=5):
    """基础组合始终独立演算，现金锁定解除后采用当天基础目标。"""
    result = signals.copy()
    hist = hist.reindex(signals.index)
    daily_drop = daily_drop.reindex(signals.index)
    healthy = healthy.reindex(signals.index)
    locked, remaining = False, 0
    for i, date in enumerate(signals.index):
        risk = hist.iloc[i] < 0 and daily_drop.iloc[i] >= RISK_RULES['drop_threshold']
        triggered = False
        if locked:
            remaining = max(0, remaining - 1)
            if risk:
                remaining = cooldown
                triggered = True
            if remaining == 0 and bool(healthy.iloc[i]) and not risk:
                locked = False
        elif risk and signals.symbol.iloc[i] != 'CASH':
            locked, remaining, triggered = True, cooldown, True
        if locked:
            state = ('RISK_CASH_TRIGGER' if triggered else
                     'RISK_CASH_COOLDOWN' if remaining > 0 else
                     'RISK_CASH_RECOVERY')
            reason = (f"SMH MACD柱线={hist.iloc[i]:.6f}；昨收至最低跌幅={daily_drop.iloc[i]:.2%}；"
                      f"避险等待剩余{remaining}个交易日；基础目标为{signals.symbol.iloc[i]} "
                      f"{signals.weight.iloc[i]:.0%}，当前以现金覆盖。收盘确认，次日开盘执行。")
            result.loc[date, ['symbol', 'weight', 'state', 'reason']] = ['CASH', 0.0, state, reason]
    return result


def generate_signals(frames, start="2017-01-02", cfg=Config(**PARAMETERS)):
    """SMH和SOXL基础组合＋MACD且4%急跌避险，全部使用确认日线。"""
    risk = RISK_RULES
    for key in ('macd_fast', 'macd_slow', 'macd_signal', 'recovery_ema'):
        if not isinstance(risk[key], int) or isinstance(risk[key], bool) or risk[key] < 1:
            raise ValueError('MACD及EMA周期须为正整数')
    if risk['macd_fast'] >= risk['macd_slow']:
        raise ValueError('MACD快线周期须小于慢线周期')
    if not isinstance(risk['cooldown_days'], int) or isinstance(risk['cooldown_days'], bool) or risk['cooldown_days'] < 0:
        raise ValueError('等待交易日须为非负整数')
    if not 0 < risk['drop_threshold'] < 1:
        raise ValueError('急跌阈值须在0和1之间')
    signals = generate_base_signals(frames, start=start, cfg=cfg)
    x = frames[BASE_SYMBOL]
    close = x.close
    dif = (close.ewm(span=risk['macd_fast'], adjust=False).mean()
           - close.ewm(span=risk['macd_slow'], adjust=False).mean())
    hist = dif - dif.ewm(span=risk['macd_signal'], adjust=False).mean()
    daily_drop = (1 - x.low / close.shift(1)).clip(lower=0)
    healthy = (hist >= 0) & (close >= close.ewm(span=risk['recovery_ema'], adjust=False).mean())
    return apply_cash_risk(signals, hist, daily_drop, healthy, risk['cooldown_days'])
