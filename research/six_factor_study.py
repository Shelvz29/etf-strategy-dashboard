"""Fixed six-factor experiment against the local 100% recovery strategy."""
import hashlib
import json
import math

import numpy as np
import pandas as pd
from cash_replacement import simulate,metrics,dump,core,perf
from deleveraging_study import metric_range
from deleveraging_rules import risk_features
from qqq_transfer import risk_summary
from six_factor_data import OUT,CUTOFF,OFR
from six_factor_rules import features,apply_overlay,candidates,FACTORS


def associations(f,price):
    """20-day association, HAC lag 20 and BH correction, not a trading input."""
    rows=[];future=price.shift(-20)/price-1
    for factor in FACTORS:
        data=pd.DataFrame({'y':future,'risk':f[factor].ge(2).where(f[factor].notna()),
            'past':price.pct_change(20),'vol':price.pct_change().rolling(20).std()}).loc['2017-01-03':].dropna().astype(float)
        if data.risk.nunique()<2:
            rows.append({'factor':factor,'known_days':len(data),'risk_days':int(data.risk.sum()),'hac_p':None});continue
        x=np.column_stack([np.ones(len(data)),data[['risk','past','vol']].to_numpy()]);y=data.y.to_numpy()
        inv=np.linalg.pinv(x.T@x);beta=inv@x.T@y;s=x*(y-x@beta)[:,None];meat=s.T@s
        for lag in range(1,21):
            cross=s[lag:].T@s[:-lag];meat+=(1-lag/21)*(cross+cross.T)
        se=math.sqrt(max(0,(inv@meat@inv)[1,1]));z=beta[1]/se if se else 0.
        rows.append({'factor':factor,'known_days':len(data),'risk_days':int(data.risk.sum()),
            'difference20':float(beta[1]),'ci_low':float(beta[1]-1.96*se),'ci_high':float(beta[1]+1.96*se),
            'hac_p':math.erfc(abs(z)/math.sqrt(2))})
    df=pd.DataFrame(rows);valid=df.index[df.hac_p.notna()];order=valid[np.argsort(df.loc[valid,'hac_p'])]
    p=df.loc[order,'hac_p'].to_numpy()*len(FACTORS)/np.arange(1,len(valid)+1)
    df.loc[order,'bh_q']=np.minimum(1,np.minimum.accumulate(p[::-1])[::-1])
    return df


def main():
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'curves').mkdir(exist_ok=True)
    before=core.active_strategy()['fingerprint'];source=next(s for s in core.list_strategies() if s['name']=='MACD＋4%急跌＋恢复确认策略')
    definitions=candidates()
    design={'cutoff':CUTOFF,'base_name':source['name'],'base_hash':source['code_hash'],
        'variants':definitions,'cost_bps':10,'selection':'仅2017—2021，回撤≤50%者年化最高，排除固定仓位和缺失处理敏感性；此前见过历史，不是真正未知样本外',
        'timing':'每日收盘确认，下一NYSE交易日开盘执行；OFR观测延迟2交易日，FactSet报告日期后首个交易日收盘可用（再次日开盘）',
        'unknown':'NaN独立保留，不标为正常；默认风险分数为已知分组风险下界，不重新放大缺失因素；COMPLETE与UNKNOWN50敏感性单列',
        'deduplication':'宽度与集中代理取最大等级；信用与流动性取最大等级；估值和盈利各一组，共0—12分',
        'caps':'均衡总分≥3/5/7/9：进攻上限75/50/25/0%；单因素等级1/2/3：75/50/25%；只减SOXL，ALL才同时减SMH',
        'thresholds':{'valuation':[22,25,28],'earnings_revision_pct':[-2,-5,-10],
            'breadth_relative63':[-.03,-.06,-.09],'breadth_extra':'RSP低于MA200加1级，上限3',
            'credit_value':[0,1,2],'credit_change20':[.5,1,2],
            'funding_value':[0,.5,1],'funding_change20':[.3,.6,1.2],
            'concentration':'SMH/XSD相对63日≥8%级1；同时SMH<MA50级2；相对≥15%且SMH20日≤−10%级3'},
        'coverage_limit':'估值和盈利来自不定期可下载报告，有缺口，最长45自然日；盈利只保留同一季度的前瞻修正。不是完整每日共识数据库',
        'sources':{'ofr':OFR,'factset':'https://insight.factset.com/topic/earnings','etf':'Yahoo Finance daily adjusted OHLC'},
        'revision_limit':'FactSet使用真实日期归档；OFR为当前历史，2022—2023部分历史曾修订，不是逐日首次发布版本；2017-10-26前设未知',
        'concentration_limit':'SMH/XSD相对表现衡量市值加权与等权结构分化，非真实持仓集中度；不使用今天龙头名单回填历史',
        'scope_limit':'S&P500估值／盈利代表全市场环境，非半导体行业预测；宽度为等权相对表现而非逐股涨跌家数',
        'proxy_stage':'查看首轮22方案后追加3个EPS代理试验，不参与前段选型；约前30—44/90—104自然日比较，阈值−2/−5/−10%，两窗口取最高等级',
        'proxy_limit':'假定周五报告PE对应上一交易日GSPC收盘，EPS代理=GSPC价格/报告前瞻PE；PE四舍五入、日期配对及滚动预测窗口带来误差；非同财政期预测修正',
        'limits':'阈值是固定研究假设；无保证50%回撤上限；现金无息，税、汇率、代币化价差未计；日线不能避免触发当天下跌',
        'cash_interest':0,'out_of_sample':False,'strategy_imported':False}
    dump(OUT/'design.json',design)
    snap,bundle=perf.confirmed_inputs()
    if snap['last']['date']!=CUTOFF:raise ValueError('Need the frozen confirmed cutoff')
    bundle=core.ensure_strategy_bundle(bundle,CUTOFF,source);frames=core.load_bundle(bundle,CUTOFF)
    for s in ('RSP','SPY','GSPC'):frames[s]=pd.read_csv(OUT/'data'/(s+'.csv'),index_col=0,parse_dates=True)
    for s in ('SMH','SOXL','QQQ','XSD'):frames[s].to_csv(OUT/'data'/(s+'.csv'))
    base=core.replay(frames,source,audit_code=True)
    if not np.isclose(base.loc[base.symbol.eq('SOXL'),'weight'].max(),1.):raise AssertionError('Base is not 100% revision')
    index=frames['SMH'].index;ofr=pd.read_csv(OUT/'data'/'ofr.csv',index_col=0,parse_dates=True)
    records=json.loads((OUT/'forecast_archive.json').read_text(encoding='utf-8'))
    cache={s:features(index,frames,ofr,records,scale=s) for s in (.8,1.,1.2)}
    slow={s:features(index,frames,ofr,records,extra_lag=5,scale=s) for s in (.8,1.,1.2)}
    proxy=features(index,frames,ofr,records,earnings_proxy=True)
    proxy_slow=features(index,frames,ofr,records,extra_lag=5,earnings_proxy=True)
    proxy.to_csv(OUT/'features_proxy.csv')
    f=cache[1.];f.to_csv(OUT/'features.csv');slow[1.].to_csv(OUT/'features_lag5.csv')
    coverage=[]
    for factor in FACTORS:
        for year in range(2017,2027):
            cut=f.loc[f'{year}-01-01':f'{year}-12-31',factor]
            coverage.append({'factor':factor,'year':year,'days':len(cut),'known_days':int(cut.notna().sum()),
                'known_fraction':float(cut.notna().mean()),'grade1':int(cut.eq(1).sum()),'grade2':int(cut.eq(2).sum()),'grade3':int(cut.eq(3).sum())})
    pd.DataFrame(coverage).to_csv(OUT/'coverage.csv',index=False)
    associations(f,frames['SMH'].adj_close).to_csv(OUT/'associations.csv',index=False)
    f.loc['2017-01-03':,list(FACTORS)].corr().to_csv(OUT/'correlations.csv')
    healthy=risk_features(frames).risk_healthy
    summary=[];periods=[];segments=[];annual=[];stress=[];lagged=[];checks=[]
    for item in definitions:
        key=item['id'];rules=item['rules'];feat=proxy if rules.get('earnings_proxy') else cache[rules.get('scale',1.)]
        goal=base.copy() if key=='BASE' else apply_overlay(base,feat,healthy,rules)
        if (goal.weight>base.weight+1e-10).any() or not goal.loc[base.symbol.eq('CASH'),'symbol'].eq('CASH').all():raise AssertionError('Raised base risk')
        if key!='ALL' and not goal.loc[base.symbol.eq('SMH'),['symbol','weight']].equals(base.loc[base.symbol.eq('SMH'),['symbol','weight']]):raise AssertionError('Changed defense target')
        goal.to_csv(OUT/'curves'/(key+'_signals.csv'));nav=simulate(frames,goal);nav.to_csv(OUT/'curves'/(key+'.csv'))
        m=metrics(nav);m.pop('hedge_days',None)
        dd=np.r_[100000.,nav.equity.to_numpy()];underwater=dd<np.maximum.accumulate(dd)-1e-7
        longest=0;streak=0
        for yes in underwater:streak=streak+1 if yes else 0;longest=max(longest,streak)
        summary.append({'id':key,'name':item['name'],**m,**risk_summary(nav),'longest_underwater_days':longest})
        for period in perf.PERIODS:periods.append({'id':key,'period':period,**metrics(nav,period)})
        for label,start,end in [('前段2017—2021','2017-01-03','2021-12-31'),('中段2022—2024','2022-01-01','2024-12-31'),('后段2025—2026','2025-01-01',CUTOFF),('OFR发布后2018起','2018-01-01',CUTOFF)]:
            segments.append({'id':key,'segment':label,**metric_range(nav,start,end)})
        for year in range(2017,2027):annual.append({'id':key,'year':year,**metric_range(nav,f'{year}-01-01',f'{year}-12-31')})
        for cost,lag in ((25,0),(50,0),(10,1)):
            stress.append({'id':key,'cost_bps':cost,'extra_lag':lag,**metrics(simulate(frames,goal,cost,lag))})
        delayed_feat=proxy_slow if rules.get('earnings_proxy') else slow[rules.get('scale',1.)]
        delayed=base.copy() if key=='BASE' else apply_overlay(base,delayed_feat,healthy,rules)
        lagged.append({'id':key,**metrics(simulate(frames,delayed))})
        for end in ('2020-03-23','2022-10-14','2024-12-31'):
            cut=pd.Timestamp(end);small=index[index<=cut]
            fresh=features(small,{s:x.loc[:cut] for s,x in frames.items()},ofr.loc[:cut],records,scale=rules.get('scale',1.),earnings_proxy=rules.get('earnings_proxy',False))
            check=base.loc[:cut].copy() if key=='BASE' else apply_overlay(base.loc[:cut],fresh,healthy.loc[:cut],rules)
            pd.testing.assert_frame_equal(goal.loc[:cut],check);checks.append({'id':key,'prefix':end})
        if key in ('BASE','BALANCED','CREDIT','ALL','HYST','UNKNOWN50'):
            frozen,_=perf.engine.simulate(frames,goal,end=CUTOFF)
            np.testing.assert_allclose(nav.equity,frozen.equity,rtol=1e-10,atol=1e-7)
        print(key,round(m['annualized_return']*100,2),round(m['max_drawdown']*100,2),flush=True)
    excluded={'BASE','F90','F75','F50','UNKNOWN50','COMPLETE','SOFT','HARD'}
    early=[r for r in segments if r['segment']=='前段2017—2021' and r['id'] not in excluded and not r['id'].startswith('PROXY_')]
    eligible=[r for r in early if r['max_drawdown']<=.5]
    selected=max(eligible,key=lambda r:r['annualized_return']) if eligible else min(early,key=lambda r:r['max_drawdown'])
    for row in summary:row['training_selected']=row['id']==selected['id']
    for filename,rows in [('summary',summary),('periods',periods),('segments',segments),('annual',annual),('execution_stress',stress),('publication_lag_stress',lagged)]:
        pd.DataFrame(rows).to_csv(OUT/(filename+'.csv'),index=False)
    if core.active_strategy()['fingerprint']!=before:raise AssertionError('Changed active strategy')
    dump(OUT/'verification.json',{'variants':len(definitions),'prefix_checks':checks,'frozen_curve_checks':6,
        'selected_by_early_period':selected['id'],'active_unchanged':True,'base_hash':source['code_hash'],
        'all_six_known_fraction':float(f.loc['2017-01-03':].known_count.eq(6).mean()),
        'proxy_all_six_known_fraction':float(proxy.loc['2017-01-03':].known_count.eq(6).mean()),
        'forecast_reports':sum(r.get('pe') is not None for r in records),'eps_reports':sum(r.get('revision') is not None for r in records),
        'input_hashes':{str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [OUT/'forecast_archive.json',*(OUT/'data').glob('*.csv')]}})


if __name__=='__main__':main()
