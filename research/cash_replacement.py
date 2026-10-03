"""Fixed cash-replacement experiment; never edits/activates dashboard strategies."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import hashlib
import json
import sys
import time

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'monitor'))
import core
import performance as perf

OUT = ROOT/'backtests'/'2026-10-03-smh-soxl-hedges'
INITIAL = 100_000.
COST = 10.
ASSETS = {'BIL':'超短期国债','SHY':'短期国债','IEF':'中期国债','TLT':'长期国债',
          'GLD':'黄金','SCHD':'高股息股票','VYM':'高股息股票','USMV':'低波动股票',
          'PSQ':'纳指每日反向1倍','SOXS':'半导体每日反向3倍','SQQQ':'纳指每日反向3倍',
          'SGOV':'超短期国债','JEPI':'股票与期权收益','JEPQ':'纳指与期权收益'}
SCOPES = {'macd':'仅MACD避险现金','all':'策略全部现金'}
WEIGHTS = (.25,.50,1.)


def dump(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def parse(symbol,payload,cutoff):
    r=core.slice_payload(payload,cutoff)['chart']['result'][0]
    if r['meta']['symbol']!=symbol or r['meta'].get('currency','USD')!='USD':
        raise ValueError('行情标的或币种不一致')
    if r['meta'].get('dataGranularity')!='1d':
        raise ValueError('必须使用日线行情，拒绝月线替代')
    dates=pd.to_datetime(r['timestamp'],unit='s',utc=True).tz_convert('America/New_York').tz_localize(None).normalize()
    quote=r['indicators']['quote'][0]
    f=pd.DataFrame({c:quote[c] for c in ('open','high','low','close','volume')},index=dates)
    f['adjclose']=r['indicators']['adjclose'][0]['adjclose']
    if f.empty or f.index.has_duplicates or not f.index.is_monotonic_increasing or not np.isfinite(f.to_numpy(float)).all():
        raise ValueError('空行情、缺失数值或交易日期无效')
    if (f[['open','high','low','close','adjclose']]<=0).any().any() or (f.volume<0).any():
        raise ValueError('价格或成交量无效')
    if (f.high+1e-7<f[['open','close','low']].max(axis=1)).any() or (f.low-1e-7>f[['open','close','high']].min(axis=1)).any():
        raise ValueError('OHLC不一致')
    expected=core.calendar(pd.Timestamp(cutoff).year).sessions_in_range(f.index[0],cutoff)
    if not f.index.equals(expected):raise ValueError('交易日不完整，拒绝填充收益')
    for field in ('open','high','low','close'):f['adj_'+field]=f[field]*f.adjclose/f.close
    return f


def fetch(symbol,cutoff):
    folder=OUT/'data';folder.mkdir(exist_ok=True)
    path=folder/(symbol+'.json')
    if path.exists():payload=json.loads(path.read_text(encoding='utf-8'))
    else:
        # Ten years covers every execution since 2017; indicator warm-up uses
        # the separately confirmed SMH history rather than these hedge prices.
        last_error=None
        for attempt in range(8):
            host='query1' if attempt%2==0 else 'query2'
            try:
                response=requests.get(f'https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}',
                    params={'range':'10y','interval':'1d','events':'div,splits','includeAdjustedClose':'true'},
                    headers={'User-Agent':'Mozilla/5.0'},timeout=(5,12))
                response.raise_for_status()
                payload=response.json()
                parse(symbol,payload,cutoff)
                dump(path,payload)
                break
            except Exception as exc:
                last_error=exc
                time.sleep(.3)
        else:raise RuntimeError(f'8次请求未取得完整日线: {last_error}')
    frame=parse(symbol,payload,cutoff)
    frame.to_csv(folder/(symbol+'.csv'))
    return frame


def replace(signals,symbol,weight,scope):
    if not np.isfinite(weight) or not 0<=weight<=1:raise ValueError('替换权重必须在0至1之间')
    result=signals.copy()
    mask=signals.symbol.eq('CASH')
    if scope=='macd':mask &= signals.state.str.startswith('RISK_CASH_')
    elif scope!='all':raise ValueError('未知替换范围')
    result.loc[mask,['symbol','weight']]=[symbol,weight]
    return result


def simulate(frames,signals,cost=COST,extra_lag=0):
    """Array form of frozen engine, retaining its exact-fee identity."""
    if not np.isfinite(cost) or not 0<=cost<10000 or not isinstance(extra_lag,int) or extra_lag<0:
        raise ValueError('费用或执行延迟无效')
    dates=signals.index
    symbols=['CASH',*sorted(set(signals.symbol)-{'CASH'})]
    lookup={s:i for i,s in enumerate(symbols)}
    op=np.ones((len(dates),len(symbols)));cl=op.copy()
    for i,s in enumerate(symbols[1:],1):
        f=frames[s].reindex(dates)
        op[:,i]=f.adj_open.to_numpy();cl[:,i]=f.adj_close.to_numpy()
    if not np.isfinite(op).all() or not np.isfinite(cl).all():raise ValueError('缺少可执行行情')
    ids=signals.symbol.map(lookup).to_numpy(int);weights=signals.weight.to_numpy(float)
    rate=cost/10000.;cash=INITIAL;units=0.;held=0;prior=None
    eq=[];fees=[];helds=[];turnover=[];opening=[];cashvalues=[]
    for i in range(1,len(dates)):
        j=i-1-extra_lag
        want=int(ids[j]) if j>=0 else 0;weight=float(weights[j]) if j>=0 else 0.
        if not 0<=weight<=1:raise ValueError('权重无效')
        if want==0 and weight!=0:raise ValueError('现金目标的资产权重须为零')
        old=units*op[i,held] if held else 0.;before=cash+old;fee=turn=0.
        if (want,weight)!=prior:
            if want==held:
                after=(before+rate*old)/(1+rate*weight) if weight*before>=old else (before-rate*old)/(1-rate*weight)
                value=weight*after;turn=abs(value-old)
            else:
                after=(before-rate*old)/(1+rate*weight);value=weight*after;turn=old+value
            fee=turn*rate
            if abs(before-fee-after)>max(1e-7,before*1e-11):raise AssertionError('费用资金不守恒')
            cash=after-value;units=value/op[i,want] if want else 0.;held=want;prior=(want,weight)
        equity=cash+units*cl[i,held] if held else cash
        if cash < -1e-7 or equity<=0:raise AssertionError('融资或负净值')
        eq.append(equity);fees.append(fee);helds.append(symbols[held]);turnover.append(turn/before)
        opening.append(before);cashvalues.append(cash)
    return pd.DataFrame({'equity':eq,'fees':fees,'held':helds,'turnover':turnover,'open_equity':opening,'cash':cashvalues},index=dates[1:])


def metrics(nav,label='全部历史'):
    win=perf.window(nav.index,label)
    capital=float(nav.equity.loc[win.baseline]) if win.baseline is not None else INITIAL
    cut=nav.loc[win.first:win.end]
    result=perf.unit_result(cut.equity,capital,win,perf.CONTINUOUS)['metrics']
    returns=np.diff(np.r_[capital,cut.equity])/np.r_[capital,cut.equity.to_numpy()[:-1]]
    vol=np.std(returns,ddof=1)*np.sqrt(252)
    downside=np.sqrt(np.mean(np.minimum(returns,0)**2))*np.sqrt(252)
    years=result['calendar_days']/365.25
    result.update(sharpe=float(returns.mean()*252/vol) if vol else 0.,
                  sortino=float(returns.mean()*252/downside) if downside else 0.,
                  calmar=result['annualized_return']/result['max_drawdown'] if result['max_drawdown'] else 0.,
                  annual_turnover=float(cut.turnover.sum()/years),hedge_days=int((~cut.held.isin(['CASH','SMH','SOXL'])).sum()),
                  final_10000=result['multiple']*10000)
    return result


def attribution(frames,signals,scope,start):
    days=signals.index[signals.index>=pd.Timestamp(start)]
    mask=signals.symbol.eq('CASH')
    if scope=='macd':mask &= signals.state.str.startswith('RISK_CASH_')
    risk=mask.shift(1,fill_value=False).reindex(days)
    smh=frames['SMH'].adj_close.pct_change().reindex(days)
    output=[]
    for s in ASSETS:
        if s not in frames or frames[s].index[0]>days[0]:continue
        ret=frames[s].adj_close.pct_change().reindex(days)
        valid=smh.notna()&ret.notna()
        for subset,use in [('全区间',valid),('避险日',valid&risk),('SMH下跌日',valid&smh.lt(0))]:
            rr=ret[use]
            output.append({'asset':s,'group':ASSETS[s],'scope':scope,'subset':subset,'days':len(rr),
                'correlation_smh':float(rr.corr(smh[use])) if len(rr)>2 else None,
                'positive_fraction':float(rr.gt(0).mean()) if len(rr) else None,
                'mean_daily_return':float(rr.mean()) if len(rr) else None,
                'worst_day':float(rr.min()) if len(rr) else None})
    return output


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    active_before=core.active_strategy()['fingerprint']
    snap,bundle=perf.confirmed_inputs();cutoff=snap['last']['date']
    if cutoff!='2026-10-02':
        raise ValueError('本实验冻结截至2026-10-02；不同截止日须另建报告目录与更新报告说明')
    profile=next(p for p in core.list_strategies() if p['name']=='MACD＋4%急跌避险策略')
    design={'cutoff':cutoff,'cost_bps':COST,'assets':ASSETS,'weights':WEIGHTS,'scopes':SCOPES,
        'main_start':'2017-01-03','short_history_comparison':'共同最晚上市后的第二个交易日，从现金重建；基础信号从2017延续',
        'replacement_rule':'只替换原目标为CASH的信号，不改变进攻、防守目标和锁定解除条件',
        'cash_interest':0.,'dividends':'复权OHLC隐含再投资，禁止额外加股息率','signal_price':'原策略口径',
        'execution':'收盘信号次日开盘；目标不变不每日配平','fit':'固定资产及25/50/100%，没有搜索MACD/急跌阈值',
        'selection_note':'结果为事后筛选；分段/成本/延迟检查不构成独立样本外验证',
        'strategy_hash':profile['code_hash']}
    dump(OUT/'design.json',design);dump(OUT/'source_profile.json',profile)
    resolved=core.ensure_strategy_bundle(bundle,cutoff,profile)
    frames=core.load_bundle(resolved,cutoff)
    signals=core.replay(frames,profile,audit_code=True)
    signals.to_csv(OUT/'baseline_signals.csv')
    errors={}
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(fetch,s,cutoff):s for s in ASSETS}
        for job in as_completed(jobs):
            s=jobs[job]
            try:frames[s]=job.result();print('DATA',s,len(frames[s]),flush=True)
            except Exception as exc:errors[s]=str(exc);print('UNAVAILABLE',s,str(exc),flush=True)
    for s in ('SMH','SOXL','QQQ'):frames[s].to_csv(OUT/'data'/(s+'.csv'))
    dump(OUT/'data_errors.json',errors)
    long=[s for s in ASSETS if s in frames and frames[s].index[0]<=signals.index[0]]
    available=[s for s in ASSETS if s in frames]
    short=[s for s in available if s not in long]
    if not available:raise RuntimeError('所有替换资产数据缺失；保留诊断文件，不生成比较结论')
    common_first=max(frames[s].index[0] for s in available)
    common_trade=signals.index[signals.index>common_first][0]
    common_signal=signals.index[signals.index.get_loc(common_trade)-1]
    rows=[];periods=[];runs={};audits=[];stresses=[];correlations=[]
    windows=[('2017年以来',signals,long)]
    if short:windows.append(('共同较短区间',signals.loc[common_signal:],available))
    for window, sig, universe in windows:
        baseline=simulate(frames,sig)
        base_metric=metrics(baseline)
        # Frozen engine remains independent of the optimized research implementation.
        nav,_=perf.engine.simulate(frames,sig,start=str(sig.index[1].date()),end=cutoff,cost_bps=COST)
        np.testing.assert_allclose(nav.equity,baseline.equity,rtol=1e-10)
        tests=[('CASH','none',0.,sig)]
        tests += [(s,scope,w,replace(sig,s,w,scope)) for s in universe for scope in SCOPES for w in WEIGHTS]
        stress_refs={(cost,lag):metrics(simulate(frames,sig,cost=cost,extra_lag=lag))
                     for cost,lag in ((25.,0),(50.,0),(10.,1))}
        for s,scope,w,new_sig in tests:
            key=f'{window}_{s}_{scope}_{int(w*100)}'
            run=baseline if s=='CASH' else simulate(frames,new_sig)
            m=metrics(run)
            row={'id':key,'window':window,'asset':s,'group':ASSETS.get(s,'无息现金'),'scope':SCOPES.get(scope,'现金基准'),
                 'weight':w,**m,'cagr_change':m['annualized_return']-base_metric['annualized_return'],
                 'drawdown_change':m['max_drawdown']-base_metric['max_drawdown'],
                 'both_better':m['annualized_return']>base_metric['annualized_return'] and m['max_drawdown']<base_metric['max_drawdown']}
            rows.append(row);runs[key]=run
            run.to_csv(OUT/(key+'.csv'))
            for label in perf.PERIODS:
                try:periods.append({'id':key,'period':label,**metrics(run,label)})
                except ValueError:pass
            if w==1 and s in ('GLD','BIL','SOXS','SCHD') and scope=='macd':
                ref,_=perf.engine.simulate(frames,new_sig,start=str(sig.index[1].date()),end=cutoff,cost_bps=COST)
                np.testing.assert_allclose(ref.equity,run.equity,rtol=1e-10)
                audits.append(key)
        for scope in SCOPES:correlations.extend({'window':window,**r} for r in attribution(frames,sig,scope,sig.index[1]))
        # Stress all candidates on the same cost/lag settings (no winner-only reporting).
        for s,scope,w,new_sig in tests:
            key=f'{window}_{s}_{scope}_{int(w*100)}'
            for cost,lag in ((25.,0),(50.,0),(10.,1)):
                stress=simulate(frames,new_sig,cost=cost,extra_lag=lag)
                mm,bm=metrics(stress),stress_refs[(cost,lag)]
                stresses.append({'id':key,'cost_bps':cost,'extra_lag':lag,**mm,
                    'cagr_change':mm['annualized_return']-bm['annualized_return'],
                    'drawdown_change':mm['max_drawdown']-bm['max_drawdown']})
        print('WINDOW_DONE',window,len(tests),flush=True)
    ranking=pd.DataFrame(rows)
    ranking.to_csv(OUT/'results.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(periods).to_csv(OUT/'periods.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(stresses).to_csv(OUT/'execution_stress.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(correlations).to_csv(OUT/'conditional_asset_returns.csv',index=False,encoding='utf-8-sig')
    audit={'rows':len(ranking),'curves':len(runs),'independent_engine_checks':len(audits)+len(windows),
           'signals_unchanged':True,'active_unchanged':core.active_strategy()['fingerprint']==active_before,
           'common_start':str(common_trade.date()),'baseline':ranking.loc[ranking.asset.eq('CASH')].to_dict('records'),
           'data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (OUT/'data').glob('*.csv')}}
    assert audit['active_unchanged']
    dump(OUT/'verification.json',audit)
    print(ranking.loc[ranking.window.eq('2017年以来')].sort_values('calmar',ascending=False)[['asset','scope','weight','annualized_return','max_drawdown','calmar','both_better']].head(15).to_string(index=False),flush=True)


if __name__=='__main__':main()
