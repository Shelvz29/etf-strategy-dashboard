"""Save the standalone strategy into the dashboard, without activating it."""
from pathlib import Path
import json
import sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent))
import core
import code_strategy as cs
import performance as perf

NAME='MACD＋4%急跌避险策略'

def main():
    code=(ROOT/(NAME+'.py')).read_text(encoding='utf-8')
    candidate=core.make_strategy(NAME,code=code)
    active_before=core.active_strategy()
    snap,bundle=perf.confirmed_inputs();cutoff=snap['last']['date']
    resolved=core.ensure_strategy_bundle(bundle,cutoff,candidate)
    frames=core.load_bundle(resolved,cutoff)
    signals=core.replay(frames,candidate,audit_code=True)
    # Check the actual monitor inputs, not just the isolated research fixture.
    expected=ROOT.parent.parent/'backtests'/'2026-10-03-smh-soxl-combinations'/'signals_macd_drop4.csv'
    expected_equity=expected.with_name('curve_macd_drop4.csv')
    matched=None
    if expected.exists() and cutoff=='2026-10-02':
        reference=pd.read_csv(expected,index_col=0,parse_dates=True)
        np.testing.assert_array_equal(reference.symbol,signals.symbol)
        np.testing.assert_allclose(reference.weight,signals.weight,rtol=1e-12)
        nav,_=perf.engine.simulate(frames,signals,start='2017-01-03',end=cutoff,cost_bps=15.)
        np.testing.assert_allclose(nav.equity,pd.read_csv(expected_equity,index_col=0).equity,rtol=1e-10)
        matched=len(signals)
    existing=next((x for x in core.list_strategies() if x['name']==NAME),None)
    if existing:
        if existing.get('code_hash')!=cs.code_hash(code):
            raise ValueError('已有同名策略包含不同代码；保留它，请通过策略编辑另存或保存新版本。')
        saved=existing
    else:
        saved=core.save_strategy(NAME,description='SMH和SOXL组合叠加MACD(12,26,9)柱线<0且SMH昨收至最低急跌≥4%的现金避险。等待5交易日，MACD柱线≥0且SMH收盘≥EMA20后恢复当天基础目标。收盘确认、次日开盘执行；不包含部分止盈或分批买回。',code=code)
    assert core.active_strategy()['fingerprint']==active_before['fingerprint']
    report=perf.report(frames,signals,[],'全部历史',cost_bps=10.)
    periods=report['periods'].astype(object).where(pd.notna(report['periods']),None)
    verification={'strategy_id':saved['id'],'revision':saved['revision'],'name':NAME,
                  'code_sha256':saved['code_hash'],'registered':True,'activated':False,
                  'verified_at_utc':core.iso_now(),'cutoff':cutoff,'research_rows_matched':matched,
                  'states':saved['state_labels'],'latest_signal':core.signal_row(signals.index[-1],signals.iloc[-1]),
                  'card_cost_bps':10.,'periods':periods.to_dict('records'),
                  'active_strategy_unchanged':True,'active_strategy':active_before['name']}
    # Dates in the report may be pandas scalars; the UI uses formatted strings.
    (ROOT/(NAME+'-验证.json')).write_text(json.dumps(verification,ensure_ascii=False,indent=2,default=str,allow_nan=False),encoding='utf-8')
    print(json.dumps({'saved_id':saved['id'],'revision':saved['revision'],'research_rows_matched':matched,
         'state_count':len(saved['state_labels']),'active_unchanged':True,'latest_state':signals.state.iloc[-1]},ensure_ascii=True))


if __name__=='__main__':main()
