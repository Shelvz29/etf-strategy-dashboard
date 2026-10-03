"""Generate editable daily adapters; originals are retained with attribution."""
# Adapted from ©2026 园园AI (aiyuan.ai) / 财富种植园 @wealthplantations.
# CC BY-NC 4.0: https://creativecommons.org/licenses/by-nc/4.0/
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
import core

BODY = '''
def generate_signals(frames, start="2017-01-02"):
    q = frames["QQQ"]
    close = q.close
    ma200 = close.rolling(PARAMETERS["annual_days"]).mean()
    ma20 = close.rolling(PARAMETERS["short_days"]).mean()
    prev20 = ma20.shift(1)
    volmean = q.volume.shift(1).rolling(PARAMETERS["volume_days"]).mean()
    first_trade = frames["TQQQ"].index.intersection(q.index)
    first_trade = first_trade[first_trade >= pd.Timestamp(start)][0]
    first = q.index.get_loc(first_trade) - 1
    if first < 252 or ma200.iloc[first] <= 0 or ma20.iloc[first] <= 0:
        raise ValueError("QQQ需要至少252个交易日的预热行情。")
    ath = float(q.high.iloc[first-251:first+1].max())
    state, risk_days = "INIT", 0
    rows = []
    for i in range(first, len(q)):
        date = q.index[i]
        p, long, short, previous = float(close.iloc[i]), float(ma200.iloc[i]), float(ma20.iloc[i]), float(prev20.iloc[i])
        ath = max(ath, p)
        dd = p / ath - 1
        rising, falling = short > previous, short < previous
        above_long, above_short, below_short = p > long, p > short, p < short
        vm = float(q.volume.iloc[i] / volmean.iloc[i]) if volmean.iloc[i] > 0 else 0.
        top = p >= ath * PARAMETERS["high_zone"] and vm > PARAMETERS["volume_multiple"] and p < q.open.iloc[i]
        risk_off = ("BEAR_CASH", "ZONE_BATTLE_DEFEND", "TOP_ESCAPE")
        risk_days = risk_days + 1 if state in risk_off else 0
        handled = False
        next_state = state
        if STRATEGY_RULES["hi_enabled"] and state == "HI":
            if not above_long:
                pass
            elif below_short and falling:
                next_state, handled = "HI_CASH", True
            else:
                next_state, handled = "HI", True
        elif STRATEGY_RULES["hi_enabled"] and state == "HI_CASH":
            if not above_long:
                pass
            elif above_short:
                next_state, handled = "NORMAL", True
            else:
                next_state, handled = "HI_CASH", True
        if not handled:
            if STRATEGY_RULES["hi_enabled"] and p > long * (1 + STRATEGY_RULES["hi_deviation"]):
                next_state = "HI"
            elif top:
                next_state = "TOP_ESCAPE"
            elif p < long:
                if dd <= -STRATEGY_RULES["deep_drawdown"]:
                    next_state = "ZONE_DESPAIR_TQQQ" if not STRATEGY_RULES["deep_requires_rising"] or rising else "ZONE_BATTLE_DEFEND"
                elif dd <= -STRATEGY_RULES["battle_drawdown"]:
                    next_state = "ZONE_BATTLE_ATTACK" if above_short else "ZONE_BATTLE_DEFEND"
                else:
                    next_state = "BEAR_CASH"
            else:
                next_state = "ZONE_BATTLE_ATTACK" if dd < -STRATEGY_RULES["battle_drawdown"] else "NORMAL"
        blocked = state in risk_off and next_state in ("ZONE_BATTLE_ATTACK", "NORMAL") and (risk_days < STRATEGY_RULES["min_risk_off_days"] or not rising)
        if blocked:
            next_state = state
        wq, wt = 0., 0.
        if next_state in ("ZONE_DESPAIR_TQQQ", "ZONE_BATTLE_ATTACK"):
            wt = .99
        elif next_state in ("ZONE_BATTLE_DEFEND", "TOP_ESCAPE"):
            wq = .90
        elif next_state == "HI":
            wq = 1.
        elif next_state == "NORMAL":
            wq, wt = STRATEGY_RULES["normal_qqq"], STRATEGY_RULES["normal_tqqq"]
        symbol = "MIX" if wq > 0 and wt > 0 else "QQQ" if wq > 0 else "TQQQ" if wt > 0 else "CASH"
        band = STRATEGY_RULES["normal_drift_band"] if next_state == "NORMAL" and wq > 0 and wt > 0 else 0.
        regime = "BULL" if p >= long else "BEAR"
        prior_regime = rows[-1]["regime"] if rows else regime
        rows.append(dict(date=date, regime=regime, regime_switch=regime != prior_regime,
            state=next_state, symbol=symbol, weight=wq+wt, weight_QQQ=wq, weight_TQQQ=wt, rebalance_band=band,
            reason=f"QQQ距运行峰值{dd:.2%}；MA20{'上升' if rising else '未上升'}；防御等待{risk_days}日；{'反转过滤保持状态；' if blocked else ''}收盘确认、次日开盘执行。",
            xsd_close=p, xsd_annual=long, xsd_ma20=short, qqq_close=p, qqq_annual=long,
            anchored_peak=ath, peak_drawdown=max(0., -dd), volume_multiple=vm,
            top_trigger=bool(top), top_locked=next_state in ("HI", "HI_CASH")))
        state = next_state
    return pd.DataFrame(rows).set_index("date")
'''

def main():
    labels = {'NORMAL':'常态双核配置','ZONE_DESPAIR_TQQQ':'深跌TQQQ进攻',
              'ZONE_BATTLE_ATTACK':'拉锯进攻','ZONE_BATTLE_DEFEND':'拉锯防御',
              'BEAR_CASH':'破年线现金等待','TOP_ESCAPE':'高位放量防御'}
    notes = {
        'NORMAL':'未触发高位放量防御；QQQ不低于MA200且距运行峰值回撤不超过10%。目标QQQ45%、TQQQ45%、现金10%；双资产市值偏离超过20%时再平衡。防御返回本状态还需至少2个已结束交易日且MA20上升。',
        'ZONE_DESPAIR_TQQQ':'QQQ低于MA200且距运行峰值回撤至少30%；目标TQQQ99%、现金1%。V22.1不要求MA20上升。',
        'ZONE_BATTLE_ATTACK':'QQQ低于MA200、距峰值回撤10%至30%且收盘高于MA20；或QQQ不低于MA200但回撤严格大于10%。目标TQQQ99%、现金1%。从防御状态返回还需等待2交易日且MA20上升。',
        'ZONE_BATTLE_DEFEND':'QQQ低于MA200、距峰值回撤10%至30%但未站上MA20；或恢复进攻被反转过滤。目标QQQ90%、现金10%。',
        'BEAR_CASH':'QQQ低于MA200且距峰值回撤小于10%，目标现金100%。恢复进攻/常态需至少2交易日且MA20上升。',
        'TOP_ESCAPE':'QQQ收盘不低于运行峰值95%，当日成交量严格超过前60日均量2.0倍且收盘低于开盘；目标QQQ90%、现金10%。原条件仅要求阴线，没有最小实体跌幅。恢复进攻/常态需至少2交易日且MA20上升。',
    }
    variants=[('QQQ和TQQQ双核策略 V22.1','qqq-tqqq-v22.1-moomoo.txt',False),
              ('纳指四季 V22.3','nazhi-siji-v22.3-moomoo.txt',True)]
    for name, original, seasonal in variants:
        rules={'hi_enabled':seasonal,'hi_deviation':.20,'deep_requires_rising':seasonal,
               'deep_drawdown':.30,'battle_drawdown':.10,'min_risk_off_days':2,
               'normal_qqq':0. if seasonal else .45,'normal_tqqq':.90 if seasonal else .45,'normal_drift_band':.20}
        names, explanations=dict(labels),dict(notes)
        if seasonal:
            names.update(NORMAL='常态TQQQ进攻',HI='乖离降杠杆',HI_CASH='逃顶后现金等待')
            explanations.update(
                TOP_ESCAPE=notes['TOP_ESCAPE'].replace('2.0倍','2.2倍'),
                NORMAL='目标TQQQ90%、现金10%。首次QQQ正乖离MA200严格超过20%时转HI；HI_CASH重新站上MA20且仍高于MA200时也可返回NORMAL，当日不重复触发HI。',
                ZONE_DESPAIR_TQQQ='QQQ低于MA200且距峰值回撤至少30%，还须MA20严格上升才持有TQQQ99%；否则QQQ90%防御。深跌进入不受2日反转等待限制。',
                ZONE_BATTLE_DEFEND=notes['ZONE_BATTLE_DEFEND']+'V22.3深跌达到30%但MA20未上升时也使用本状态。',
                HI='首次QQQ收盘严格高于MA200的120%，目标QQQ100%。锁定后不依靠乖离回落退出；仍高于MA200时，收盘跌破MA20且MA20向下转HI_CASH，否则保持HI；不高于MA200时返回基础判断。此锁定链优先于放量阴线。',
                HI_CASH='HI后QQQ跌破MA20且该均线向下，目标现金100%。仍高于MA200且收盘严格高于MA20时恢复NORMAL；不高于MA200时回到基础状态判断；否则继续现金。')
        params=core.baseline.Config().to_dict()
        params.update(annual_days=200,macro_annual_days=200,short_days=20,volume_days=60,volume_multiple=2.2 if seasonal else 2.0,high_zone=.95,macro_buffer=0.,bull_cool=2,bear_cool=2)
        header=f'# {name} · 本地日线适配版\n# 原作者：© 2026 园园AI (aiyuan.ai)，财富种植园 @wealthplantations\n# https://www.youtube.com/@wealthplantations\n# 原文件：third_party/moomoo/{original}\n# License: CC BY-NC 4.0 https://creativecommons.org/licenses/by-nc/4.0/\n# 修改说明：从moomoo API改为DataFrame；保留每日状态条件和目标权重。\n# 不含账户订单暂停、T+1结算等待、500美元门槛和整数股限制；按次日开盘模拟。\n# 不代表原作者认可本项目。\nimport numpy as np\nimport pandas as pd\n\nBASE_SYMBOL = "QQQ"\n'
        code=header+'PARAMETERS = '+repr(params)+'\nSTRATEGY_RULES = '+repr(rules)+'\nSTATE_LABELS = '+repr(names)+'\nSTATE_NOTES = '+repr(explanations)+'\n'+BODY
        (ROOT/(name+'.py')).write_text(code,encoding='utf-8')
        print(name)

if __name__=='__main__':main()
