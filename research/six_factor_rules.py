"""Past-only graded research overlays; not a live trading integration."""
import numpy as np
import pandas as pd
from macro_rules import available_daily

FACTORS=('valuation','breadth','earnings','credit','liquidity','concentration')
LABELS=dict(zip(FACTORS,('估值','市场宽度','盈利预测修正','信用','流动性','龙头集中代理')))


def grade(values, thresholds, reverse=False):
    a=values.astype(float)
    result=pd.Series(0.,index=a.index)
    for level,threshold in enumerate(thresholds,1):
        result.loc[a.le(threshold) if reverse else a.ge(threshold)]=level
    result.loc[a.isna()]=np.nan
    return result


def archive_daily(records,index,field,extra_lag=0):
    good=[r for r in records if r.get(field) is not None and pd.Timestamp(r['date'])<=index[-1]]
    raw=pd.DataFrame(good)
    if raw.empty:return pd.DataFrame({field:np.nan,'age':np.nan},index=index)
    raw.index=pd.DatetimeIndex(pd.to_datetime(raw.date))
    raw=raw.sort_index()
    if raw.index.has_duplicates:raise ValueError('Duplicate release dates')
    pos=index.searchsorted(raw.index,side='right')+extra_lag
    use=pos<len(index);raw=raw.loc[use].copy();raw['released']=raw.index
    raw.index=index[pos[use]]
    out=raw.groupby(level=0).last().reindex(index).ffill()
    out['age']=(pd.Series(index,index=index)-out.released).dt.days
    out.loc[out.age.gt(45),field]=np.nan
    if field=='revision':
        # Do not keep a forecast of a completed quarter as a current forecast.
        out.loc[out.quarter.ne((index.month-1)//3+1),field]=np.nan
    return out


def proxy_records(records,index_price):
    """Rounded forward-P/E implies a rolling EPS proxy, not fixed-year revisions.

    Friday reports conventionally use the prior trading-day close; this date
    pairing is an assumption, so output is explicitly a reconstructed proxy.
    """
    rows=[]
    for r in records:
        if r.get('pe') is None:continue
        date=pd.Timestamp(r['date']);pos=index_price.index.searchsorted(date,side='left')-1
        if pos<0:continue
        rows.append({'date':r['date'],'proxy_eps':float(index_price.iloc[pos])/float(r['pe'])})
    rows.sort(key=lambda r:r['date'])
    dates=pd.DatetimeIndex(pd.to_datetime([r['date'] for r in rows]))
    for i,r in enumerate(rows):
        for days in (30,90):
            target=dates[i]-pd.Timedelta(days=days);j=dates.searchsorted(target,side='right')-1
            r['proxy_revision'+str(days)]=None
            if j>=0 and (target-dates[j]).days<=14:
                r['proxy_revision'+str(days)]=100*(r['proxy_eps']/rows[j]['proxy_eps']-1)
    return rows


def features(index,frames,ofr,records,extra_lag=0,scale=1.,earnings_proxy=False):
    if scale<=0 or extra_lag<0:raise ValueError('Invalid lag or threshold scale')
    out=pd.DataFrame(index=index)
    prices={s:frames[s].adj_close.reindex(index) for s in ('RSP','SPY','SMH','XSD')}
    if any(p.isna().any() for p in prices.values()):raise ValueError('Missing ETF sessions')
    rel=prices['RSP']/prices['SPY'];out['breadth_relative63']=rel.pct_change(63)
    out['rsp_below200']=prices['RSP'].lt(prices['RSP'].rolling(200).mean())
    out['breadth']=np.minimum(3,grade(out.breadth_relative63,[-.03*scale,-.06*scale,-.09*scale],True)+out.rsp_below200.astype(int))
    out.loc[prices['RSP'].rolling(200).mean().isna(),'breadth']=np.nan
    rel=prices['SMH']/prices['XSD'];out['concentration_relative63']=rel.pct_change(63)
    out['smh_return20']=prices['SMH'].pct_change(20)
    weak=prices['SMH'].lt(prices['SMH'].rolling(50).mean())
    out['concentration']=0.
    out.loc[out.concentration_relative63.ge(.08*scale),'concentration']=1.
    out.loc[out.concentration_relative63.ge(.08*scale)&weak,'concentration']=2.
    out.loc[out.concentration_relative63.ge(.15*scale)&out.smh_return20.le(-.10*scale),'concentration']=3.
    out.loc[out.concentration_relative63.isna(),'concentration']=np.nan
    stress=available_daily(ofr,index,2+extra_lag)
    age=(pd.Series(index,index=index)-stress.observed_date).dt.days
    for name,field,changes,levels in [('credit','credit',[.5,1.,2.],[0.,1.,2.]),
                                    ('liquidity','funding',[.3,.6,1.2],[0.,.5,1.])]:
        v=stress[field];d=v-v.shift(20)
        out[name+'_value']=v;out[name+'_delta20']=d
        out[name]=np.maximum(grade(v,[x*scale for x in levels]),grade(d,[x*scale for x in changes]))
        # The index was first published in October 2017; backfilled history is
        # not presumed public earlier. Conservative daily publication lag.
        out.loc[(index<pd.Timestamp('2017-10-26'))|age.gt(10)|age.isna(),name]=np.nan
    pe=archive_daily(records,index,'pe',extra_lag)
    eps=archive_daily(records,index,'revision',extra_lag)
    out['forward_pe']=pe.pe;out['pe_age']=pe.age
    out['eps_revision_pct']=eps.revision;out['eps_age']=eps.age
    out['valuation']=grade(out.forward_pe,[22.*scale,25.*scale,28.*scale])
    out['earnings']=grade(out.eps_revision_pct,[-2.*scale,-5.*scale,-10.*scale],True)
    if earnings_proxy:
        estimates=proxy_records(records,frames['GSPC'].close.loc[:index[-1]])
        one=archive_daily(estimates,index,'proxy_revision30',extra_lag)
        three=archive_daily(estimates,index,'proxy_revision90',extra_lag)
        out['proxy_revision30']=one.proxy_revision30;out['proxy_revision90']=three.proxy_revision90
        out['earnings']=np.fmax(grade(one.proxy_revision30,[-2*scale,-5*scale,-10*scale],True),
                               grade(three.proxy_revision90,[-2*scale,-5*scale,-10*scale],True))
    out['known_count']=out[list(FACTORS)].notna().sum(axis=1)
    # Reduce redundant votes: market structure and financial stress each max,
    # plus valuation and forecasts. Unknown groups remain unknown.
    out['structure']=out[['breadth','concentration']].max(axis=1,skipna=True)
    out['finance']=out[['credit','liquidity']].max(axis=1,skipna=True)
    groups=out[['valuation','earnings','structure','finance']]
    out['score_lower_bound']=groups.sum(axis=1,min_count=1)
    return out


def candidates():
    rows=[('BASE','恢复确认基准（100%进攻）',{})]
    rows += [(f'F{x}',f'固定进攻上限{x}%',{'fixed':x/100}) for x in (90,75,50)]
    rows += [(s.upper(),LABELS[s]+'单因素分级',{'factor':s}) for s in FACTORS]
    rows += [('BALANCED','六因素分级：均衡',{}),
             ('AGGRESSIVE','六因素分级：进取',{'caps':[.9,.75,.5,.25]}),
             ('STRICT','六因素分级：严格',{'caps':[.5,.25,0.,0.]}),
             ('HYST','均衡＋2日减仓／5日恢复',{'entry_days':2,'clear_days':5}),
             ('ALL','均衡，覆盖SMH防御仓',{'all_assets':True}),
             ('CORE','仅宽度／集中代理／信用／流动性',{'core_only':True}),
             ('NO_VAL','均衡，去掉估值',{'exclude':'valuation'}),
             ('NO_EPS','均衡，去掉盈利预测',{'exclude':'earnings'}),
             ('COMPLETE','均衡，仅六因素均有值时新增限制',{'complete_only':True}),
             ('UNKNOWN50','均衡，任一缺失进攻上限50%',{'unknown_cap':.5}),
             ('SOFT','均衡，风险阈值降低20%',{'scale':.8}),
             ('HARD','均衡，风险阈值提高20%',{'scale':1.2})]
    rows += [('PROXY_EPS','滚动前瞻EPS代理单因素（追加）',{'factor':'earnings','earnings_proxy':True}),
             ('PROXY_BALANCED','六因素均衡＋滚动EPS代理（追加）',{'earnings_proxy':True}),
             ('PROXY_HYST','六因素滞后解除＋滚动EPS代理（追加）',{'earnings_proxy':True,'entry_days':2,'clear_days':5})]
    return [{'id':key,'name':name,'rules':rules} for key,name,rules in rows]


def apply_overlay(signals,f,healthy,rules):
    out=signals.copy();f=f.reindex(out.index);healthy=healthy.reindex(out.index)
    if healthy.isna().any():raise ValueError('Missing recovery status')
    if 'weight_QQQ' in signals:raise ValueError('This study supports SMH/SOXL single-asset targets only')
    previous_symbol='CASH';previous_weight=0.;active_cap=1.;pending=0;clear=0;restore=False
    for i,date in enumerate(out.index):
        row=f.iloc[i];symbol=str(signals.symbol.iloc[i]);weight=float(signals.weight.iloc[i]);original=weight
        if rules.get('fixed') is not None:desired=float(rules['fixed'])
        else:
            factor=rules.get('factor')
            if factor:
                level=row[factor];desired=1. if pd.isna(level) else [1.,.75,.5,.25][int(level)]
            else:
                groups=[row['structure'],row['finance']]
                if not rules.get('core_only'):
                    groups += [row[s] for s in ('valuation','earnings') if rules.get('exclude')!=s]
                score=sum(x for x in groups if pd.notna(x))
                caps=rules.get('caps',[.75,.5,.25,0.])
                desired=1.
                for threshold,cap in zip((3,5,7,9),caps):
                    if score>=threshold:desired=float(cap)
            missing=(pd.isna(row[factor]) if factor else row.known_count<6)
            if rules.get('complete_only') and missing:desired=1.
            if missing and rules.get('unknown_cap') is not None:desired=min(desired,rules['unknown_cap'])
        if not 0<=desired<=1:raise ValueError('Invalid target cap')
        if desired<active_cap:
            pending+=1;clear=0
            if pending>=rules.get('entry_days',1):active_cap=desired;pending=0
        elif desired>active_cap:
            clear+=1;pending=0
            if clear>=rules.get('clear_days',1):active_cap=desired;clear=0
        else:pending=clear=0
        eligible=symbol=='SOXL' or (rules.get('all_assets') and symbol=='SMH')
        code='FACTOR_CAP'
        if eligible:
            weight=min(weight,active_cap)
            if weight<original-1e-10:restore=True
            if restore and symbol=='SOXL' and rules.get('fixed') is None:
                if bool(healthy.iloc[i]):
                    if weight>=original-1e-10:restore=False
                else:
                    prior=previous_weight if previous_symbol=='SOXL' else 0.
                    if weight>prior:weight=prior;code='FACTOR_RECOVERY_WAIT'
            if weight<original-1e-10:
                symbol=symbol if weight>0 else 'CASH'
                out.loc[date,['symbol','weight','state','reason']]=[symbol,weight,code,
                    f'基础={signals.state.iloc[i]}；已知因素={int(row.known_count)}/6；风险下界={row.score_lower_bound:g}/12；目标{symbol} {weight:.0%}；次日开盘执行。']
        previous_symbol=symbol;previous_weight=weight
    return out
