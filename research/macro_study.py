"""Predeclared external-factor overlays; current private strategy stays unchanged."""
import hashlib
import json
import math

import numpy as np
import pandas as pd

from cash_replacement import INITIAL,simulate,metrics,dump,core,perf
from deleveraging_rules import risk_features
from deleveraging_study import metric_range
from macro_data import OUT,CUTOFF,SOURCES
from macro_rules import features,apply_overlay,candidates,GROUPS,FACTORS
from qqq_transfer import transfer_source,risk_summary
import code_strategy as cs


def load_macro():
    inputs=[pd.read_csv(OUT/(s+'.csv'),index_col=0,parse_dates=True) for s in ('treasury','oil','policy')]
    for frame,columns in zip(inputs,[['yield2','yield10','real10'],['wti'],['target_upper']]):
        if frame.index.has_duplicates or not frame.index.is_monotonic_increasing or not np.isfinite(frame[columns]).all().all():
            raise ValueError('Incomplete or unordered macro observations; no silent forward filling of missing fields')
    cpi=pd.DataFrame(json.loads((OUT/'cpi_releases.json').read_text(encoding='utf-8')))
    cpi['release_date']=pd.to_datetime(cpi.release_date)
    cpi=cpi.set_index('release_date').sort_index()
    expected=set(pd.period_range('2015-01','2026-08',freq='M').astype(str))-{'2025-10'}
    if set(cpi.month)!=expected or cpi.month.duplicated().any() or not np.isfinite(cpi[['headline','core']]).all().all():
        raise ValueError('CPI archive incomplete; only the official October 2025 publication gap is allowed')
    return (*inputs,cpi)


def conditional_tests(f,frames):
    """Association, not causation. HAC accounts for overlapping forward returns."""
    rows=[]
    flags=[*FACTORS,*GROUPS]
    for symbol in ('SMH','QQQ'):
        price=frames[symbol].adj_close.reindex(f.index)
        past=price.pct_change(20);vol=price.pct_change().rolling(20).std()
        for horizon in (5,20,60):
            future=price.shift(-horizon)/price-1
            for flag in flags:
                data=pd.concat([future.rename('y'),f[flag].astype(float).rename('flag'),past.rename('past'),vol.rename('vol')],axis=1).loc['2017-01-03':].dropna()
                y=data.y.to_numpy();x=np.column_stack([np.ones(len(data)),data[['flag','past','vol']].to_numpy()])
                gram=np.linalg.pinv(x.T@x);beta=gram@x.T@y;u=y-x@beta;s=x*u[:,None]
                meat=s.T@s
                for lag in range(1,horizon+1):
                    cross=s[lag:].T@s[:-lag];meat+=(1-lag/(horizon+1))*(cross+cross.T)
                cov=gram@meat@gram;se=math.sqrt(max(0,float(cov[1,1])))
                z=beta[1]/se if se>0 else 0.;p=math.erfc(abs(z)/math.sqrt(2))
                yes=data.loc[data.flag==1,'y'];no=data.loc[data.flag==0,'y']
                rows.append({'asset':symbol,'horizon':horizon,'factor':flag,'risk_days':len(yes),'normal_days':len(no),
                    'mean_risk_return':float(yes.mean()),'mean_normal_return':float(no.mean()),
                    'controlled_difference':float(beta[1]),'ci_low':float(beta[1]-1.96*se),'ci_high':float(beta[1]+1.96*se),
                    'hac_p':p,'hac_lag':horizon,'control':'past20 return and realized20 volatility'})
    df=pd.DataFrame(rows)
    # One multiple-testing family per asset, including all factors and horizons.
    for symbol in ('SMH','QQQ'):
        loc=df.index[df.asset.eq(symbol)];ordered=loc[np.argsort(df.loc[loc,'hac_p'])]
        adjusted=df.loc[ordered,'hac_p'].to_numpy()*len(loc)/np.arange(1,len(loc)+1)
        df.loc[ordered,'bh_q']=np.minimum(1,np.minimum.accumulate(adjusted[::-1])[::-1])
    return df


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    for s in ('curves','etf_data'): (OUT/s).mkdir(exist_ok=True)
    definitions=candidates()
    dump(OUT/'design.json',{'cutoff':CUTOFF,'primary':'S2_H','groups':GROUPS,'factors':FACTORS,'candidates':definitions,
        'dates':'2017-01-03至2026-10-02','training':'2017—2021','validation':'2022—2024','later':'2025—2026',
        'selection':'各资产仅用2017—2021：最大回撤≤50%者取年化最高；无满足则取回撤最小；不包含固定仓位参照',
        'source':SOURCES,'cost_bps':10,'timing':'CPI归档当月同比从真实公告日收盘可用；国债/政策观测滞后2个NYSE交易日，油价滞后3日；次日开盘执行',
        'data_revision_limit':'CPI使用当次公告归档的未季调同比；其他宏观数据是当前下载历史而非完整逐日首次发布库，固定滞后不能消除更正/修订风险',
        'score':'利率、油价、货币政策、CPI四组各1票；同组相关指标只算1票；组之间仍可能相关。倒挂含紧缩，不另加利率组的一票',
        'scope':'默认只降低SOXL/TQQQ目标，保留防御ETF和原现金锁定；ALL才覆盖防御ETF；解除宏观限制后加仓仍要求原恢复条件',
        'policy_limit':'货币政策用历史联储目标上限；未将关税、财政政策新闻或主观情绪评分补造成完整历史',
        'stats':'前瞻5/20/60日复权收益的条件关联；控制过去20日收益/波动，Newey-West滞后=前瞻期，按资产对39项检验BH修正；不输入交易决策',
        'out_of_sample':False,'fit_note':'固定规则，但此前看过该市场历史，分段不是真正未知样本外；阈值±20%仅敏感性',
        'cash_interest':0,'limits':'不含税费、汇率和代币化证券价差；不能承诺最大回撤上限'})
    before=core.active_strategy()['fingerprint']
    source=next(p for p in core.list_strategies() if p['name']=='MACD＋4%急跌＋恢复确认策略')
    snap,bundle=perf.confirmed_inputs()
    if snap['last']['date']!=CUTOFF:raise ValueError('Study cutoff differs from confirmed ETF history')
    qprofile=core.make_strategy('QQQ/TQQQ宏观研究基础',code=transfer_source(source['code']))
    bundle=core.ensure_strategy_bundle(bundle,CUTOFF,source);bundle=core.ensure_strategy_bundle(bundle,CUTOFF,qprofile)
    frames=core.load_bundle(bundle,CUTOFF)
    for s in ('QQQ','TQQQ','SMH','SOXL'):frames[s].to_csv(OUT/'etf_data'/(s+'.csv'))
    base={'SMH':core.replay(frames,source,audit_code=True),'QQQ':cs.evaluate(qprofile['code'],core.strategy_frames(frames,qprofile),audit=True)}
    raw=load_macro();index=frames['QQQ'].index
    fcache={scale:features(index,frames['QQQ'].close,*raw,threshold_scale=scale) for scale in (.8,1.,1.2)}
    slow=features(index,frames['QQQ'].close,*raw,extra_lag=5)
    fcache[1.].to_csv(OUT/'macro_features.csv');slow.to_csv(OUT/'macro_features_lag5.csv')
    conditional_tests(fcache[1.],frames).to_csv(OUT/'factor_associations.csv',index=False)
    fcache[1.].loc['2017-01-03':,[*GROUPS]].astype(int).corr().to_csv(OUT/'group_correlations.csv')
    summary=[];periods=[];annual=[];segments=[];stress=[];lagged=[];audits=[];causal=[];allruns={};allgoals={}
    for market,sig in base.items():
        attack='SOXL' if market=='SMH' else 'TQQQ'
        local=frames if market=='SMH' else {'SMH':frames['QQQ'],'SOXL':frames['TQQQ'],'QQQ':frames['QQQ']}
        health=risk_features(local).risk_healthy
        for item in definitions:
            key=market+'_'+item['id'];rules=item['rules'];feat=fcache[rules.get('threshold_scale',1.)]
            goal=apply_overlay(sig,feat,health,attack,rules)
            if ((goal.weight-sig.weight)>1e-10).any() or not goal.loc[sig.symbol.eq('CASH'),'symbol'].eq('CASH').all():raise AssertionError('Overlay raised risk or released base cash')
            goal.to_csv(OUT/'curves'/(key+'_signals.csv'));nav=simulate(frames,goal)
            nav.to_csv(OUT/'curves'/(key+'.csv'));allruns[key]=nav;allgoals[key]=goal
            m=metrics(nav);m.pop('hedge_days',None)
            summary.append({'id':key,'market':market,'variant':item['id'],'name':item['name'],**m,**risk_summary(nav)})
            for period in perf.PERIODS:
                m=metrics(nav,period);m.pop('hedge_days',None);periods.append({'id':key,'period':period,**m})
            for year in range(2017,2027):annual.append({'id':key,'year':year,**metric_range(nav,f'{year}-01-01',f'{year}-12-31')})
            for label,start,end in [('前段2017—2021','2017-01-03','2021-12-31'),('中段2022—2024','2022-01-01','2024-12-31'),('后段2025—2026','2025-01-01',CUTOFF)]:
                segments.append({'id':key,'segment':label,**metric_range(nav,start,end)})
            for cost,lag in ((25,0),(50,0),(10,1)):
                trial=simulate(frames,goal,cost,lag);stress.append({'id':key,'cost_bps':cost,'extra_lag':lag,**metrics(trial)})
            delayed=apply_overlay(sig,slow,health,attack,rules)
            if rules.get('threshold_scale',1.)!=1.:delayed=apply_overlay(sig,features(index,frames['QQQ'].close,*raw,extra_lag=5,threshold_scale=rules['threshold_scale']),health,attack,rules)
            lagged.append({'id':key,'macro_extra_lag':5,**metrics(simulate(frames,delayed))})
            for end in ('2020-03-23','2022-10-14','2024-12-31'):
                cut=pd.Timestamp(end);small=index[index<=cut]
                cropped=tuple(d.loc[d.index<=cut] for d in raw)
                fresh=features(small,frames['QQQ'].close.loc[:cut],*cropped,threshold_scale=rules.get('threshold_scale',1.))
                check=apply_overlay(sig.loc[:cut],fresh,health.loc[:cut],attack,rules)
                pd.testing.assert_frame_equal(goal.loc[:cut],check)
                causal.append({'id':key,'end':end})
            if item['id'] in ('BASE','F75','RATES','CPI','S2_H','S23_ALL'):
                frozen,_=perf.engine.simulate(frames,goal,end=CUTOFF)
                np.testing.assert_allclose(nav.equity,frozen.equity,rtol=1e-10,atol=1e-7)
                audits.append({'id':key,'rows':len(nav)})
            print(key,round(summary[-1]['annualized_return']*100,2),round(summary[-1]['max_drawdown']*100,2),flush=True)
    # Choose within the early segment only. Full-history rankings are descriptive.
    selected={}
    for market in base:
        eligible=[r for r in segments if r['id'].startswith(market+'_') and r['segment']=='前段2017—2021' and not r['id'].split('_',1)[1].startswith('F')]
        constrained=[r for r in eligible if r['max_drawdown']<=.5]
        best=max(constrained,key=lambda r:r['annualized_return']) if constrained else min(eligible,key=lambda r:r['max_drawdown'])
        selected[market]=best['id']
    for row in summary:row['training_selected']=row['id']==selected[row['market']]
    for filename,rows in [('summary',summary),('periods',periods),('annual',annual),('segments',segments),('execution_stress',stress),('macro_lag_stress',lagged)]:pd.DataFrame(rows).to_csv(OUT/(filename+'.csv'),index=False)
    if core.active_strategy()['fingerprint']!=before:raise AssertionError('Active strategy changed')
    dump(OUT/'verification.json',{'frozen_audits':audits,'prefix_audits':causal,'selected':selected,'active_unchanged':True,
        'source_hash':source['code_hash'],'input_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (OUT/'cpi_releases.json',OUT/'treasury.csv',OUT/'oil.csv',OUT/'policy.csv')},
        'cpi_releases':len(raw[-1]),'variants_per_market':len(definitions),'strategy_imported':False})


if __name__=='__main__':main()
