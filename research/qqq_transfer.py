"""Fixed-parameter private-strategy transfer; no save, activation or publication."""
import argparse
import hashlib
import json

import numpy as np
import pandas as pd

from cash_replacement import ROOT, INITIAL, core, perf, simulate, metrics, dump
from deleveraging_study import metric_range
import code_strategy as cs
import portfolio

OUT = ROOT / 'backtests' / '2026-10-04-qqq-tqqq-recovery'
CUTOFF = '2026-10-02'
REPORT = OUT / '2026-10-04-QQQ和TQQQ·MACD急跌与恢复确认回测.html'
NAMES = {'FOUNDATION':'QQQ/TQQQ基础组合', 'MACD':'QQQ/TQQQ MACD＋4%急跌',
         'RECOVERY':'QQQ/TQQQ MACD＋4%急跌＋恢复确认', 'QQQ_HOLD':'QQQ买入持有',
         'TQQQ_HOLD':'TQQQ买入持有', 'SMH_REFERENCE':'SMH/SOXL 恢复确认参照'}


def transfer_source(code, entry_point='generate_signals'):
    if cs.check_source(code).get('BASE_SYMBOL') != 'SMH':
        raise ValueError('此移植只接受SMH基础策略。')
    # Both textual explanations and instrument literals use the same mapping.
    result = code.replace('SOXL', 'TQQQ').replace('SMH', 'QQQ')
    result += f'\n\n_generate_transfer_original = {entry_point}\n'
    result += '''
def generate_signals(frames, start="2017-01-02", cfg=Config(**PARAMETERS)):
    out = _generate_transfer_original(frames, start=start, cfg=cfg).copy()
    out['weight_QQQ'] = np.where(out.symbol.eq('QQQ'), out.weight, 0.)
    out['weight_TQQQ'] = np.where(out.symbol.eq('TQQQ'), out.weight, 0.)
    out['rebalance_band'] = 0.
    # Preserve single-target semantics: a state-only change creates no order.
    out['rebalance_on_state_change'] = False
    return out
'''
    cs.check_source(result)
    return result


def risk_summary(nav):
    r=nav.equity.pct_change();r.iloc[0]=nav.equity.iloc[0]/INITIAL-1
    return {'trade_days':int(nav.fees.gt(0).sum()), 'cash_days':int(nav.held.eq('CASH').sum()),
            'cash_fraction':float(nav.held.eq('CASH').mean()),
            'attack_fraction':float(nav.held.isin(['TQQQ','SOXL']).mean()),
            'worst_day':float(-r.min()), 'daily_es95':float(-r[r<=r.quantile(.05)].mean())}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-name',default='MACD＋4%急跌＋恢复确认策略')
    parser.add_argument('--macd-name',default='MACD＋4%急跌避险策略')
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    for folder in ('curves','strategies','data'): (OUT/folder).mkdir(exist_ok=True)
    before=core.active_strategy()['fingerprint']
    profiles=core.list_strategies()
    source=next(p for p in profiles if p['name']==args.source_name)
    macd=next(p for p in profiles if p['name']==args.macd_name)
    snapshot,bundle=perf.confirmed_inputs()
    if snapshot['last']['date'] != CUTOFF: raise ValueError('本次研究冻结2026-10-02确认输入。')
    codes={'RECOVERY':transfer_source(source['code']), 'MACD':transfer_source(macd['code']),
           'FOUNDATION':transfer_source(macd['code'],'generate_base_signals')}
    qprofile=core.make_strategy(NAMES['RECOVERY'],code=codes['RECOVERY'])
    bundle=core.ensure_strategy_bundle(bundle,CUTOFF,source)
    bundle=core.ensure_strategy_bundle(bundle,CUTOFF,qprofile)
    frames=core.load_bundle(bundle,CUTOFF)
    qframes=core.strategy_frames(frames,qprofile)
    sframes=core.strategy_frames(frames,source)
    for s in ('QQQ','TQQQ','SMH','SOXL'):frames[s].to_csv(OUT/'data'/(s+'.csv'))
    dump(OUT/'private_source_profiles.json',{'recovery':source,'macd':macd})
    dump(OUT/'design.json',{'cutoff':CUTOFF,'start':'2017-01-03','cost_bps':10,
        'mapping':{'SMH':'QQQ','SOXL':'TQQQ'},'changed_parameters':{},
        'execution':'收盘确认、次日开盘；标的或目标仓位变化才交易；不按状态名称或每日配平',
        'macro_role':'QQQ同时作为信号、防御标的和宏观环境判断标的，原SMH与QQQ的跨资产关系不再存在',
        'signal_price':'沿用原策略原始OHLC；波动率使用复权收益；执行用复权OHLC',
        'recovery':'QQQ连续3天收盘≥EMA20；EMA20高于3日前；MACD柱线≥0；20日波动≤60日波动1.1倍',
        'acute_drop':'QQQ MACD柱线<0且最低价相对前收跌≥4%；收盘确认，无法避开当天已发生的跌幅',
        'cash_interest':0,'no_optimization':True,'out_of_sample':False,
        'limitations':'固定参数迁移研究，已见过历史；不是独立未知样本外，不含税费、汇率、代币化证券价差和额外现金利息',
        'source_hashes':{p['name']:p['code_hash'] for p in (source,macd)}})
    signals={};runs={};audits=[]
    for key,code in codes.items():
        signals[key]=cs.evaluate(code,qframes,audit=True)
        if key!='FOUNDATION':(OUT/'strategies'/(NAMES[key].replace('/','和')+'.py')).write_text(code,encoding='utf-8')
    signals['SMH_REFERENCE']=core.replay(sframes,source,audit_code=True)
    for symbol in ('QQQ','TQQQ'):
        sig=signals['RECOVERY'].copy();sig['symbol']=symbol;sig['weight']=1.;sig['state']='HOLD'
        sig['weight_QQQ']=1. if symbol=='QQQ' else 0.
        sig['weight_TQQQ']=1. if symbol=='TQQQ' else 0.
        signals[symbol+'_HOLD']=sig
    summary=[];periods=[];annual=[];segments=[];stress=[]
    for key,sig in signals.items():
        f=sframes if key=='SMH_REFERENCE' else qframes
        sig.to_csv(OUT/'curves'/(key+'_signals.csv'))
        nav=simulate(f,sig);runs[key]=nav;nav.to_csv(OUT/'curves'/(key+'.csv'))
        for cost,lag in ((10,0),(25,0),(50,0),(10,1)):
            trial=nav if (cost,lag)==(10,0) else simulate(f,sig,cost,lag)
            ref,_=perf.engine.simulate(f,sig,end=CUTOFF,cost_bps=cost,extra_lag=lag)
            np.testing.assert_allclose(trial.equity,ref.equity,rtol=1e-10,atol=1e-7)
            audits.append({'id':key,'cost':cost,'lag':lag,'frozen_rows':len(ref)})
            if key!='SMH_REFERENCE' and lag==0:
                dual,_=portfolio.simulate(f,sig,end=CUTOFF,cost_bps=cost,initial=INITIAL)
                np.testing.assert_allclose(trial[['equity','fees','cash']],dual[['equity','fees','cash']],rtol=1e-10,atol=1e-7)
                audits[-1]['portfolio_rows']=len(dual)
            stress.append({'id':key,'cost_bps':cost,'extra_lag':lag,**metrics(trial)})
        m=metrics(nav);m.pop('hedge_days',None)
        summary.append({'id':key,'name':NAMES[key],**m,**risk_summary(nav)})
        for period in perf.PERIODS:
            m=metrics(nav,period);m.pop('hedge_days',None)
            periods.append({'id':key,'period':period,**m})
        for year in range(2017,2027):
            annual.append({'id':key,'year':year,**metric_range(nav,f'{year}-01-01',f'{year}-12-31')})
        for label,start,end in [('前段2017—2021','2017-01-03','2021-12-31'),
            ('中段2022—2024','2022-01-01','2024-12-31'),('后段2025—2026','2025-01-01',CUTOFF)]:
            segments.append({'id':key,'segment':label,**metric_range(nav,start,end)})
        print(key,round(summary[-1]['annualized_return']*100,2),round(summary[-1]['max_drawdown']*100,2),flush=True)
    for filename,rows in [('summary',summary),('periods',periods),('annual',annual),('segments',segments),('stress',stress)]:
        pd.DataFrame(rows).to_csv(OUT/(filename+'.csv'),index=False)
    if core.active_strategy()['fingerprint']!=before:raise AssertionError('当前策略发生变化')
    dump(OUT/'verification.json',{'ledger_audits':audits,'worker_prefix_audited':list(codes)+['SMH_REFERENCE'],
        'active_unchanged':True,'strategy_saved':False,'export_hashes':{k:cs.code_hash(v) for k,v in codes.items()},
        'data_hashes':{s:hashlib.sha256((OUT/'data'/(s+'.csv')).read_bytes()).hexdigest() for s in ('QQQ','TQQQ','SMH','SOXL')}})


if __name__=='__main__':main()
