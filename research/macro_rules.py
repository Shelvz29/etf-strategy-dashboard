"""Causal, group-balanced macro risk overlays for an existing recovery strategy."""
import numpy as np
import pandas as pd

GROUPS=('rates','oil','policy','cpi')
FACTORS={
 'rate_jump':'10年名义收益率20交易日上升≥50基点且高于60日均线',
 'real_jump':'10年实际收益率20交易日上升≥40基点',
 'curve_stress':'10年减2年收益率≤−50基点且63交易日政策利率上升≥50基点',
 'oil_spike':'正WTI油价20交易日涨≥15%或63交易日涨≥30%',
 'oil_crash':'WTI现价≤0或20交易日跌≥25%，且QQQ低于50日均线',
 'tightening':'联储目标区间上限63交易日上升≥50基点',
 'emergency_cut':'目标区间上限20交易日下降≥50基点，且QQQ低于50日均线',
 'cpi_heat':'当次公告总体同比≥3%且比3次公告前升≥0.3个百分点，或核心同比≥3%且升≥0.2个百分点',
 'cpi_jump':'当次公告总体同比比前次升≥0.2个百分点且核心同比≥3%，发布后5交易日'}


def available_daily(frame,index,lag):
    """Observation dates are not release dates: delay to future NYSE sessions."""
    if not isinstance(lag,int) or lag<1:raise ValueError('Daily macro lag must be positive')
    positions=index.searchsorted(frame.index,side='right')+lag-1
    keep=positions<len(index)
    out=frame.iloc[np.flatnonzero(keep)].copy()
    out['observed_date']=out.index
    out.index=index[positions[keep]]
    out=out.groupby(level=0).last().reindex(index).ffill()
    return out


def available_cpi(releases,index,extra_lag=0):
    if not isinstance(extra_lag,int) or extra_lag<0:raise ValueError('Invalid CPI lag')
    if releases.index.has_duplicates or not releases.index.is_monotonic_increasing:raise ValueError('Invalid CPI release ordering')
    positions=index.searchsorted(releases.index,side='left')+extra_lag
    keep=positions<len(index)
    c=releases[['headline','core']].copy()
    c['headline_accel3']=c.headline-c.headline.shift(3)
    c['core_accel3']=c.core-c.core.shift(3)
    c['headline_jump']=c.headline-c.headline.shift(1)
    c['release_date']=c.index
    c=c.iloc[np.flatnonzero(keep)];c.index=index[positions[keep]]
    c=c.groupby(level=0).last().reindex(index).ffill()
    c['release_age_sessions']=np.arange(len(index))-pd.Series(np.arange(len(index)),index=index).where(index.isin(index[positions[keep]])).ffill()
    return c


def features(index,qqq,treasury,oil,policy,cpi,extra_lag=0,threshold_scale=1.):
    if threshold_scale not in (.8,1.,1.2):raise ValueError('Unsupported fixed sensitivity')
    t=available_daily(treasury,index,2+extra_lag)
    o=available_daily(oil,index,3+extra_lag)
    p=available_daily(policy,index,2+extra_lag)
    c=available_cpi(cpi,index,extra_lag)
    q=qqq.reindex(index);bad=q.lt(q.rolling(50).mean())
    f=pd.DataFrame(index=index)
    f['nominal_change20']=t.yield10-t.yield10.shift(20)
    f['real_change20']=t.real10-t.real10.shift(20)
    f['curve']=t.yield10-t.yield2
    f['policy_change63']=p.target_upper-p.target_upper.shift(63)
    f['policy_change20']=p.target_upper-p.target_upper.shift(20)
    f['wti']=o.wti
    for window in (20,63):
        f[f'oil_return{window}']=(o.wti/o.wti.shift(window)-1).where(o.wti.gt(0)&o.wti.shift(window).gt(0))
    for key in ('headline','core','headline_accel3','core_accel3','headline_jump','release_age_sessions'):f[key]=c[key]
    f['rate_jump']=f.nominal_change20.ge(.5*threshold_scale)&t.yield10.gt(t.yield10.rolling(60).mean())
    f['real_jump']=f.real_change20.ge(.4*threshold_scale)
    f['curve_stress']=f.curve.le(-.5*threshold_scale)&f.policy_change63.ge(.5*threshold_scale)
    f['oil_spike']=f.oil_return20.ge(.15*threshold_scale)|f.oil_return63.ge(.30*threshold_scale)
    f['oil_crash']=(f.wti.le(0)|f.oil_return20.le(-.25*threshold_scale))&bad
    f['tightening']=f.policy_change63.ge(.5*threshold_scale)
    f['emergency_cut']=f.policy_change20.le(-.5*threshold_scale)&bad
    f['cpi_heat']=(f.headline.ge(3)&f.headline_accel3.ge(.3*threshold_scale-1e-10))|(f.core.ge(3)&f.core_accel3.ge(.2*threshold_scale-1e-10))
    f['cpi_jump']=f.headline_jump.ge(.2*threshold_scale-1e-10)&f.core.ge(3)&f.release_age_sessions.lt(5)
    # The curve flag explicitly contains tightening; do not count it as a
    # second independent vote alongside the policy group.
    f['rates']=f.rate_jump|f.real_jump
    f['oil']=f.oil_spike|f.oil_crash
    f['policy']=f.tightening|f.emergency_cut
    f['cpi']=f.cpi_heat|f.cpi_jump
    f['score']=f[list(GROUPS)].astype(int).sum(axis=1)
    for key,frame in [('treasury',t),('oil',o),('policy',p)]:
        f[key+'_observation_age']=(pd.Series(index,index=index)-frame.observed_date).dt.days
    f['cpi_release_age']=(pd.Series(index,index=index)-c.release_date).dt.days
    f.attrs['daily_age_limit']=15+2*extra_lag
    return f


def apply_overlay(signals,f,healthy,attack,rules):
    if not rules:return signals.copy()
    if attack not in ('SOXL','TQQQ'):raise ValueError('Invalid attack asset')
    f=f.reindex(signals.index);healthy=healthy.reindex(signals.index)
    required=[g for g in GROUPS]+['score','treasury_observation_age','oil_observation_age','policy_observation_age','cpi_release_age']
    if f[required].isna().any().any() or healthy.isna().any():raise ValueError('Missing macro history or recovery features')
    if f[[g+'_observation_age' for g in ('treasury','oil','policy')]].gt(f.attrs.get('daily_age_limit',15)).any().any() or f.cpi_release_age.gt(100).any():raise ValueError('Stale macro observations; no silent neutral substitution')
    cap=float(rules.get('cap',1.))
    if not 0<=cap<=1:raise ValueError('Invalid cap')
    out=signals.copy();previous_symbol='CASH';previous_weight=0.;entry_count=0;clear_count=0;active=False;restore=False
    for i,date in enumerate(signals.index):
        symbol=str(signals.symbol.iloc[i]);weight=float(signals.weight.iloc[i]);original=weight
        if rules.get('fixed'):
            desired=cap;code='MACRO_FIXED_CAP'
        else:
            group=rules.get('group')
            risk=bool(f[group].iloc[i]) if group else int(f.score.iloc[i])>=rules.get('entry_score',2)
            entry_count=entry_count+1 if risk else 0
            clear=not risk if group else int(f.score.iloc[i])<=rules.get('clear_score',1)
            clear_count=clear_count+1 if clear else 0
            if entry_count>=rules.get('entry_days',1):active=True
            if clear_count>=rules.get('clear_days',1):active=False
            desired=cap if active else 1.
            if active and rules.get('cash_score') is not None and int(f.score.iloc[i])>=rules['cash_score']:desired=0.
            code='MACRO_RISK_CASH' if desired==0 else 'MACRO_RISK_CAP'
        eligible=symbol==attack or (rules.get('scope')=='all' and symbol!='CASH')
        if eligible:
            weight=min(weight,desired)
            if weight<original-1e-10:restore=True
            if rules.get('restore_confirm',True) and not rules.get('fixed') and restore and symbol==attack:
                if bool(healthy.iloc[i]):restore=False
                else:
                    previous=previous_weight if previous_symbol==attack else 0.
                    if weight>previous+1e-10:weight=previous;code='MACRO_RESTORE_WAIT'
            if weight<original-1e-10:
                symbol=symbol if weight>0 else 'CASH'
                out.loc[date,['symbol','weight','state','reason']]=[symbol,weight,code,
                    f'基础={signals.state.iloc[i]}；宏观风险{int(f.score.iloc[i])}/4组；目标{symbol} {weight:.0%}，剩余现金。收盘确认、次日开盘。']
        previous_symbol=symbol;previous_weight=weight
    if 'weight_QQQ' in out:
        out['weight_QQQ']=np.where(out.symbol.eq('QQQ'),out.weight,0.)
        out['weight_TQQQ']=np.where(out.symbol.eq('TQQQ'),out.weight,0.)
    return out


def candidates():
    rows=[('BASE','恢复确认基准',{})]
    rows += [(f'F{cap}',f'固定进攻上限{cap}%',{'fixed':True,'cap':cap/100}) for cap in (90,75,50)]
    rows += [(g.upper(),f'单因素组：{g}，上限50%',{'group':g,'cap':.5}) for g in GROUPS]
    rows += [('CURVE','倒挂且紧缩，上限50%（单独参考）',{'group':'curve_stress','cap':.5})]
    rows += [('S2_75','两组风险，上限75%',{'entry_score':2,'cap':.75}),
        ('S2_50','两组风险，上限50%',{'entry_score':2,'cap':.5}),
        ('S2_25','两组风险，上限25%',{'entry_score':2,'cap':.25}),
        ('S3_50','三组风险，上限50%',{'entry_score':3,'clear_score':2,'cap':.5}),
        ('S23','两组50%／三组现金',{'entry_score':2,'cap':.5,'cash_score':3}),
        ('S2_H','两组50%＋2日触发／5日解除',{'entry_score':2,'cap':.5,'entry_days':2,'clear_days':5}),
        ('S23_H','两组50%／三组现金＋滞后解除',{'entry_score':2,'cap':.5,'cash_score':3,'entry_days':2,'clear_days':5}),
        ('S23_ALL','两组50%／三组现金，覆盖防御ETF',{'entry_score':2,'cap':.5,'cash_score':3,'scope':'all'}),
        ('S2_NORESTORE','两组50%，宏观解除即恢复',{'entry_score':2,'cap':.5,'restore_confirm':False}),
        ('S2_SOFT','两组50%，阈值降低20%',{'entry_score':2,'cap':.5,'threshold_scale':.8}),
        ('S2_HARD','两组50%，阈值提高20%',{'entry_score':2,'cap':.5,'threshold_scale':1.2})]
    return [{'id':key,'name':name,'rules':rules} for key,name,rules in rows]
