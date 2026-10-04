"""Predeclared price-only risk study on the existing MACD + 4% baseline."""
import hashlib
import inspect
import json

import numpy as np
import pandas as pd

from cash_replacement import ROOT, INITIAL, simulate, metrics, dump, core, perf
from deleveraging_rules import risk_features, apply_deleveraging, generate_risk_signals, RISK_LABELS

OUT=ROOT/'backtests'/'2026-10-04-smh-soxl-deleveraging'
CUTOFF='2026-10-02'
PRIMARY='C40'


def candidates():
    rows=[('BASE','MACD＋4%急跌基准',{}),('F50','固定SOXL上限50%',{'static_cap':.5}),
          ('F75','固定SOXL上限75%',{'static_cap':.75})]
    rows += [(f'V{v}',f'波动目标{v}%',{'vol_target':v/100}) for v in (30,40,50,60)]
    rows += [(f'T{v}',f'趋势恶化上限{v}%',{'trend_cap':v/100}) for v in (0,25,50)]
    rows += [('DEEP','深跌恢复确认',{'gate_deep':True}),('ENTRY','重新加仓确认',{'gate_reentry':True})]
    base={'vol_target':.4,'trend_cap':.25,'gate_deep':True,'gate_reentry':True}
    rows += [(f'C{v}',f'组合风控·波动目标{v}%',dict(base,vol_target=v/100)) for v in (30,40,50,60)]
    rows += [('VT40','波动40%＋趋势减仓',{'vol_target':.4,'trend_cap':.25}),
             ('VG40','波动40%＋恢复确认',{'vol_target':.4,'gate_deep':True,'gate_reentry':True}),
             ('TG25','趋势减仓＋恢复确认',{'trend_cap':.25,'gate_deep':True,'gate_reentry':True})]
    rows += [(f'C40_MA{v}',f'组合40%·趋势{v}日',dict(base,trend_days=v)) for v in (20,100)]
    rows += [(f'C40_RV{v}',f'组合40%·波动{v}日',dict(base,vol_days=v)) for v in (10,40)]
    rows += [(f'C40_WAIT{v}',f'组合40%·恢复{v}日',dict(base,recovery_days=v)) for v in (1,5)]
    initial=[{'id':key,'name':name,'rules':rule,'phase':1,
        'role':'主候选' if key==PRIMARY else '参考' if key.startswith(('BASE','F')) else '候选'} for key,name,rule in rows]
    extra=[{'id':f'F{v}G','name':f'恢复确认＋SOXL上限{v}%',
        'rules':{'static_cap':v/100,'gate_reentry':True},'role':'追加候选','phase':2} for v in (50,75,90)]
    return initial+extra


def metric_range(nav,start,end):
    cut=nav.loc[start:end]
    prior=nav.index[nav.index<cut.index[0]]
    anchor=prior[-1] if len(prior) else None
    capital=float(nav.equity.loc[anchor]) if anchor is not None else INITIAL
    win=perf.Window('指定区间',anchor,cut.index[0],cut.index[-1])
    m=perf.unit_result(cut.equity,capital,win,perf.CONTINUOUS)['metrics']
    r=np.diff(np.r_[capital,cut.equity])/np.r_[capital,cut.equity.to_numpy()[:-1]]
    vol=np.std(r,ddof=1)*np.sqrt(252)
    m.update(sharpe=float(np.mean(r)*252/vol) if vol else 0.,calmar=m['annualized_return']/m['max_drawdown'] if m['max_drawdown'] else 0.)
    return m


def extra_metrics(nav,signals):
    daily=nav.equity.pct_change()
    daily.iloc[0]=nav.equity.iloc[0]/INITIAL-1
    cutoff=daily.quantile(.05)
    underwater=nav.equity.to_numpy()<np.maximum.accumulate(np.r_[INITIAL,nav.equity])[1:]
    longest=current=0
    for u in underwater:current=current+1 if u else 0;longest=max(longest,current)
    actual_weight=1-nav.cash/nav.equity
    exposure=actual_weight*np.where(nav.held.eq('SOXL'),3.,np.where(nav.held.eq('SMH'),1.,0.))
    action=signals.shift(1).reindex(nav.index)
    return {'es95_daily':float(-daily[daily<=cutoff].mean()),'worst_day':float(-daily.min()),
            'longest_underwater_sessions':longest,'trade_days':int(nav.fees.gt(0).sum()),
            'mean_nominal_exposure':float(exposure.mean()),'cash_fraction':float(nav.held.eq('CASH').mean()),
            'soxl_fraction':float(nav.held.eq('SOXL').mean()),'preemptive_reduction_days':int(action.state.fillna('').str.startswith('DELEV_').sum())}


def export_code(profile,rules,name):
    # Preserve the private source only in the ignored research export directory.
    import ast
    source=profile['code']
    tree=ast.parse(source);lines=source.splitlines(keepends=True)
    labels=dict(profile.get('state_labels',{}));notes=dict(profile.get('state_notes',{}))
    labels.update(RISK_LABELS)
    explanation=(f"SOXL目标按风控配置 {rules} 缩减；波动率用复权日收益、趋势与MACD用基础策略同口径收盘价。"
                 "恢复要求SMH站上EMA20且EMA上升、MACD柱线非负、SMH20日波动不超过60日的1.1倍、连续站上天数达设定值。"
                 "新风控只修改基础SOXL目标，不改变SMH和原现金锁定；剩余现金不计利息；减仓权重按5个百分点向下取整。基础状态持续独立演算，收盘确认次日开盘执行。")
    for code in RISK_LABELS:notes[code]=explanation
    edits=[]
    for node in tree.body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
            key=node.targets[0].id
            if key in ('STATE_LABELS','STATE_NOTES'):
                edits.append((node.lineno-1,node.end_lineno,key+' = '+repr(labels if key=='STATE_LABELS' else notes)+'\n'))
    for begin,end,replacement in sorted(edits,reverse=True):lines[begin:end]=[replacement]
    source=''.join(lines)
    source+='\n\n# '+name+'：保留上述完整基础代码和MACD现金锁定。\n'
    source+='DELEVERAGING_RULES = '+repr(rules)+'\n'
    source+='\n\n'.join(inspect.getsource(fn) for fn in (risk_features,apply_deleveraging,generate_risk_signals))
    source+='\n\n_generate_macd_baseline = generate_signals\n\ndef generate_signals(frames, start="2017-01-02", cfg=Config(**PARAMETERS)):\n'
    source+='    baseline = _generate_macd_baseline(frames, start=start, cfg=cfg)\n    return generate_risk_signals(frames, baseline, DELEVERAGING_RULES)\n'
    return source


def main():
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'curves').mkdir(exist_ok=True);(OUT/'strategies').mkdir(exist_ok=True)
    active_before=core.active_strategy()['fingerprint']
    profile=next(p for p in core.list_strategies() if p['name']=='MACD＋4%急跌避险策略')
    snap,bundle=perf.confirmed_inputs()
    if snap['last']['date']!=CUTOFF:raise ValueError('冻结实验只接受截至2026-10-02的确认输入')
    frames=core.load_bundle(core.ensure_strategy_bundle(bundle,CUTOFF,profile),CUTOFF)
    signals=core.replay(frames,profile,audit_code=True)
    definitions=candidates()
    design={'cutoff':CUTOFF,'primary':PRIMARY,'candidates':definitions,'cost_bps':10,
        'training':'2017-01-03至2021-12-31','validation':'2022-01-01至2024-12-31','later_check':'2025-01-01至2026-10-02',
        'selection':'仅第一阶段候选，2017—2021年最大回撤≤50%者选年化最高；若无满足者则选训练回撤最小',
        'cash_interest':0,'execution':'当日收盘确认、下一交易日开盘；目标未变不配平',
        'scope':'只降低基础SOXL目标，不释放MACD现金锁定，不修改SMH目标；基础状态和峰值独立延续',
        'timing_note':'提前是相对后续更大跌幅，首次突然冲击仍可能承受；不声称预测去杠杆',
        'data_note':'波动率使用复权收益，趋势/EMA/MACD沿用基础信号的原始收盘口径；无新增外部数据',
        'independence_note':'第一阶段25个方案固定后执行；第二阶段3个恢复确认＋固定上限方案根据首轮整体结果追加。此前研究已查看这些历史，不是真正未知样本外；追加方案不参与第一阶段训练选型',
        'excluded':'FINRA/NFCI缺少当时发布版本；VIX、信用利差、市场广度未加入，避免缺失或时间戳错误',
        'source_hash':profile['code_hash']}
    dump(OUT/'design.json',design);dump(OUT/'private_source_profile.json',profile)
    signals.to_csv(OUT/'baseline_signals.csv')
    for s,f in frames.items():
        if s in ('SMH','SOXL','QQQ'):f.to_csv(OUT/(s+'.csv'))
    results=[];periods=[];segments=[];annual=[];stresses=[];audits=[];runs={};goals={}
    definitions += [{'id':s+'_HOLD','name':s+'买入持有','rules':{},'role':'买入持有','phase':0} for s in ('SMH','SOXL')]
    stress_ref={}
    for cost,lag in ((25,0),(50,0),(10,1)):
        stress_ref[(cost,lag)]=metrics(simulate(frames,signals,cost,lag))
    for item in definitions:
        key=item['id']
        if item['role']=='买入持有':
            new=signals.copy();new['symbol']=key.split('_')[0];new['weight']=1.;new['state']='HOLD'
        elif key=='BASE':new=signals.copy()
        else:new=generate_risk_signals(frames,signals,item['rules'])
        nav=simulate(frames,new);m=metrics(nav)
        results.append({**item,**m,**extra_metrics(nav,new)})
        runs[key]=nav;goals[key]=new
        nav.to_csv(OUT/'curves'/(key+'.csv'));new.to_csv(OUT/'curves'/(key+'_signals.csv'))
        for period in perf.PERIODS:periods.append({'id':key,'period':period,**metrics(nav,period)})
        for label,start,end in (('训练2017—2021','2017-01-03','2021-12-31'),
            ('验证2022—2024','2022-01-01','2024-12-31'),('后段2025—2026','2025-01-01',CUTOFF)):
            segments.append({'id':key,'segment':label,**metric_range(nav,start,end)})
        for year in range(2017,2027):annual.append({'id':key,'year':year,'partial':year==2026,**metric_range(nav,f'{year}-01-01',min(f'{year}-12-31',CUTOFF))})
        for cost,lag in ((25,0),(50,0),(10,1)):
            mm=metrics(simulate(frames,new,cost,lag));bm=stress_ref[(cost,lag)]
            stresses.append({'id':key,'cost_bps':cost,'extra_lag':lag,**mm,
                'cagr_change':mm['annualized_return']-bm['annualized_return'],
                'drawdown_change':mm['max_drawdown']-bm['max_drawdown']})
        if key in ('BASE','F50','V40','T25','DEEP','ENTRY','C40','C40_WAIT1','C40_RV40','F75G','F90G'):
            frozen,_=perf.engine.simulate(frames,new,start='2017-01-03',end=CUTOFF,cost_bps=10)
            for c in ('equity','fees','cash'):np.testing.assert_allclose(nav[c],frozen[c],rtol=1e-10,atol=1e-7)
            for length in (550,1300,1900,len(signals)-1):
                if key=='BASE':continue
                stop=signals.index[length-1]
                prefix=generate_risk_signals({s:f.loc[:stop] for s,f in frames.items()},signals.iloc[:length],item['rules'])
                pd.testing.assert_frame_equal(prefix,new.iloc[:length])
            audits.append(key)
        print('DONE',key,round(m['annualized_return']*100,2),round(m['max_drawdown']*100,2),flush=True)
    rankings=pd.DataFrame(results)
    segment_frame=pd.DataFrame(segments)
    train=segment_frame.loc[segment_frame.segment.eq('训练2017—2021')].merge(rankings[['id','role']],on='id')
    train=train.loc[train.role.isin(['候选','主候选'])]
    feasible=train.loc[train.max_drawdown.le(.5)]
    selected=(feasible.sort_values(['annualized_return','max_drawdown'],ascending=[False,True]) if len(feasible)
              else train.sort_values(['max_drawdown','annualized_return'],ascending=[True,False])).iloc[0]['id']
    rankings['training_selected']=rankings.id.eq(selected)
    base=rankings.loc[rankings.id.eq('BASE')].iloc[0]
    rankings['cagr_change']=rankings.annualized_return-base.annualized_return
    rankings['drawdown_change']=rankings.max_drawdown-base.max_drawdown
    rankings['both_better']=(rankings.cagr_change>0)&(rankings.drawdown_change<0)
    rankings.drop(columns=['rules']).to_csv(OUT/'results.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(periods).to_csv(OUT/'periods.csv',index=False,encoding='utf-8-sig')
    segment_frame.to_csv(OUT/'segments.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(annual).to_csv(OUT/'annual.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(stresses).to_csv(OUT/'execution_stress.csv',index=False,encoding='utf-8-sig')
    exported={}
    for key in dict.fromkeys((PRIMARY,selected,'ENTRY','F75G','F90G')):
        item=next(d for d in definitions if d['id']==key)
        name='SMH和SOXL提前减仓策略·'+item['name']
        code=export_code(profile,item['rules'],name)
        path=OUT/'strategies'/(name+'.py');path.write_text(code,encoding='utf-8')
        import code_strategy
        metadata=code_strategy.check_source(code)
        # Replay the same exported editable source through the dashboard worker.
        candidate_profile=dict(profile,code=code,name=name,code_hash=hashlib.sha256(code.encode()).hexdigest(),
            state_labels=metadata.get('STATE_LABELS',{}),state_notes=metadata.get('STATE_NOTES',{}))
        candidate_profile['fingerprint']=core.strategy_fingerprint(candidate_profile)
        actual=core.replay(frames,candidate_profile,audit_code=True)
        pd.testing.assert_frame_equal(actual[['symbol','weight','state']],goals[key][['symbol','weight','state']],check_dtype=False)
        exported[key]=str(path)
    assert core.active_strategy()['fingerprint']==active_before
    dump(OUT/'verification.json',{'primary':PRIMARY,'training_selected':selected,'candidate_count':len(candidates()),
        'all_curves':len(rankings),'independent_engine_checks':audits,'actual_prefix_checks':(len(audits)-1)*4,
        'exported_worker_checks':len(exported),'active_unchanged':True,'exported':exported,
        'input_hashes':{s:hashlib.sha256((OUT/(s+'.csv')).read_bytes()).hexdigest() for s in ('QQQ','SMH','SOXL')}})
    print('TRAINING_SELECTED',selected,flush=True)
    print(rankings.sort_values('calmar',ascending=False)[['id','annualized_return','max_drawdown','calmar','both_better']].head(12).to_string(index=False),flush=True)


if __name__=='__main__':main()
