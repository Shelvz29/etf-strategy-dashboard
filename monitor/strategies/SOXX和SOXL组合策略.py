# SOXX和SOXL组合策略
# 将XSD的信号与防御角色完整替换为SOXX，原有参数保持不变。
# 修改 PARAMETERS 或下方 generate_signals 的判断逻辑，再点击应用代码。
# frames: QQQ / SOXX / SOXL 的日线 DataFrame；只能使用当日及之前的数据。
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
BASE_SYMBOL = 'SOXX'

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
STATE_LABELS = {'TOP_DEFENSE': '高位放量防御', 'PULLBACK_ATTACK': '回撤进攻', 'NORMAL_ATTACK': '常态进攻', 'NORMAL_DEFENSE': '熊市常态防御', 'BREAK_CASH': '破年线离场', 'DEEP_ATTACK': '深跌进攻', 'RECOVERY_ATTACK': '短线恢复进攻', 'SPRING_DEFENSE': '等待反弹防御'}
STATE_NOTES = {'TOP_DEFENSE': '高位放量防御锁定中；此状态优先于其他七种状态。 新锁定需同时满足：SOXX距锚定峰值不超过5%、阴线实体跌幅（开盘价−收盘价）/开盘价至少2%、当日成交量至少为此前60个交易日平均成交量的3.5倍。跌破年线或距峰值回撤达到15%时解除已有锁定；QQQ偏牛/偏熊切换也会清除锁定，当天仍可能重新触发。', 'PULLBACK_ATTACK': 'SOXX收盘价≥年线，距锚定峰值回撤≥15%；偏牛、偏熊均适用。 “回撤”指SOXX价格从策略锚定峰值下跌，不是你的账户已经亏损。此分支不要求20日线恢复条件，也不保证反弹或买在最低点。', 'NORMAL_ATTACK': 'SOXX收盘价≥年线、距峰值回撤<15%，且QQQ环境偏牛。 即使没有明显回撤，也可能处于此状态。“常态进攻”和“回撤进攻”的目标标的及仓位相同，二者切换本身不会要求调仓。', 'NORMAL_DEFENSE': 'SOXX收盘价≥年线、距峰值回撤<15%，且QQQ环境偏熊。 此分支不使用SOXL。QQQ环境恢复偏牛后，会重新按同一天的SOXX条件选择状态。', 'BREAK_CASH': 'SOXX收盘价<年线，距峰值回撤<15%。 这里的现金指分配给本策略的资金不配置SOXX或SOXL。此阈值不是账户亏损15%自动止损规则。', 'DEEP_ATTACK': 'SOXX收盘价<年线且距峰值回撤≥15%；达到深跌阈值（偏牛25%／偏熊30%）。 此分支优先于短线恢复条件，不要求先站回20日线。未启用深跌锁定，每天按最新确认收盘重新判断。它不是账户最大回撤控制。', 'RECOVERY_ATTACK': 'SOXX收盘价<年线；距峰值回撤≥15%且未达深跌阈值、无深跌锁定；收盘价>20日线、该均线较前日上升，连续收盘站上短线偏牛≥1天/偏熊≥2天。 连续天数按已结束的美股交易日计算，包含当天；跌回20日线或QQQ环境切换会重置计数。短线恢复不表示已经重新站上年线。', 'SPRING_DEFENSE': 'SOXX收盘价<年线；距峰值回撤≥15%且未达深跌阈值、无深跌锁定；短线恢复条件尚未全部满足。 偏牛使用SOXX90%和现金10%，偏熊使用SOXX50%和现金50%。SOXX仍会涨跌，“防御”不代表本金保本。'}


def generate_signals(frames, start="2017-01-02", cfg=Config(**PARAMETERS)):
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
