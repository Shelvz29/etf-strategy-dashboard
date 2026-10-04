"""Generate the editor-compatible strategy from the frozen research base."""
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parent.parent
sys.path.insert(0,str(ROOT.parent))
import strategy_states

OVERLAY='''

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
'''


def main():
    frozen=PROJECT/'backtests'/'2026-10-03-smh-soxl-risk'/'source_profile.json'
    profile=json.loads(frozen.read_text(encoding='utf-8'))
    source=profile['code'].replace('# SMH和SOXL组合策略',
        '# MACD＋4%急跌避险策略\n# 已验证研究基线：MACD柱线<0且SMH昨收至最低跌幅≥4%。\n# 收盘确认、次日开盘执行；不包含部分止盈或分批买回。',1)
    source=source.replace('def generate_signals(', 'def generate_base_signals(',1)+OVERLAY
    labels=dict(profile['state_labels']);notes=dict(profile['state_notes'])
    notes={code:text+' 基础状态继续独立计算；MACD急跌现金锁定生效时，实际目标由现金避险覆盖。' for code,text in notes.items()}
    labels.update({'RISK_CASH_TRIGGER':'MACD急跌触发避险',
                   'RISK_CASH_COOLDOWN':'现金避险等待',
                   'RISK_CASH_RECOVERY':'现金等待趋势恢复'})
    notes.update({
        'RISK_CASH_TRIGGER':'SMH MACD(12,26,9)柱线<0，且（昨日收盘−当日最低）/昨日收盘≥4%，两个条件同时成立。未锁定时仅在基础目标非现金时启动；已锁定期间再次触发会重置为5个交易日。收盘后确认，当天跌幅仍计入，下一交易日开盘目标为现金100%。此状态覆盖基础组合八种状态。',
        'RISK_CASH_COOLDOWN':'已触发MACD且4%急跌避险，等待计数尚未归零，目标为现金100%。每个已结束交易日减1；重复触发重置5日。基础SMH/SOXL状态及峰值继续独立演算，切换基础状态或QQQ环境不会自行解除避险。',
        'RISK_CASH_RECOVERY':'5交易日等待已结束，但SMH MACD柱线≥0与收盘≥EMA20的恢复条件未同时满足，继续现金100%。恢复且当天没有重复触发后，采用当天基础组合的SMH、SOXL或现金目标，不强制直接买SOXL，不重置基础峰值。',
    })
    source=strategy_states.replace_metadata(source,labels,notes)
    from full_allocation import upgrade_source
    source=upgrade_source(source)
    target=ROOT/'MACD＋4%急跌避险策略.py'
    target.write_text(source,encoding='utf-8')
    print(str(target))


if __name__=='__main__':main()
