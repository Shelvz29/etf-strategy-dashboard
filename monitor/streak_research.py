"""Consecutive-loss cash exits with causal moving-average recovery studies."""
from __future__ import annotations

import argparse
import html
import inspect
import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import core
import performance as perf
from breakout_research import period_metrics, replay_nav
from drawdown_review import episodes


def streak_features(close):
    """Reset on a flat/up day; compound losses from the close before the run."""
    if (len(close)<2 or not np.isfinite(close.to_numpy()).all() or (close<=0).any()
        or not close.index.is_monotonic_increasing or close.index.has_duplicates):
        raise ValueError('Invalid streak prices')
    days,drop,starts=[],[],[]
    previous=float(close.iloc[0]);anchor=previous;run_days=0;run_start=close.index[0]
    for date,value in close.items():
        if value<previous:
            if run_days==0:anchor=previous;run_start=date
            run_days+=1
            loss=1-float(value)/anchor
        else:
            run_days=0;loss=0.0;run_start=date
        days.append(run_days);drop.append(loss);starts.append(run_start)
        previous=float(value)
    return pd.DataFrame({'days':days,'drop':drop,'start':starts},index=close.index)


def apply_streak(signals,frames,rules):
    """Cash overrides asset targets; MA recovery never overrides underlying cash.

    Indicators use full warm-up history; all target changes execute next open.
    Initialization starts unlocked, while the loss-run feature is pre-warmed.
    'rising' accepts positive slope; 'turn' requires a nonpositive prior slope.
    Exit wins if both risk and recovery are true on a date.
    """
    symbol=rules['symbol'];recovery_symbol=rules.get('recovery_symbol','SMH')
    mode=rules['mode'];threshold=rules['threshold'];period=rules['ma_days']
    ma_kind=rules.get('ma_kind','ma');recovery_kind=rules.get('recovery_kind','rising')
    window=rules.get('window',3)
    if (symbol not in frames or recovery_symbol not in frames or mode not in ('streak','window')
        or isinstance(threshold,bool) or not np.isfinite(threshold) or not 0<threshold<.6
        or isinstance(period,bool) or not isinstance(period,int) or not 2<=period<=100
        or isinstance(window,bool) or not isinstance(window,int) or not 2<=window<=20
        or ma_kind not in ('ma','ema') or recovery_kind not in ('rising','turn')):
        raise ValueError('Invalid consecutive-loss rules')
    close=frames[symbol].close
    feature=streak_features(close)
    days=feature.days.reindex(signals.index)
    if mode=='streak':
        drop=feature['drop'].reindex(signals.index)
        risk=(days>=2)&(drop+1e-12>=threshold)
    else:
        drop=(1-close/close.shift(window)).clip(lower=0).reindex(signals.index)
        risk=drop+1e-12>=threshold
    recovery_close=frames[recovery_symbol].close
    if ma_kind=='ma':
        ma=recovery_close.rolling(period).mean()
    else:
        ma=recovery_close.ewm(span=period,adjust=False,min_periods=period).mean()
    slope=ma.diff()
    recovery=slope>0
    if recovery_kind=='turn':recovery=recovery&(slope.shift(1)<=0)
    if not np.isfinite(np.column_stack((drop,days,ma.reindex(signals.index),slope.reindex(signals.index)))).all():
        raise ValueError('Insufficient loss or recovery warm-up')
    recovery=recovery.reindex(signals.index)
    out=signals.copy(deep=True)
    out['streak_underlying_state']=signals.state
    out['streak_days']=days
    out['streak_drop']=drop
    out['streak_recovery_ma']=ma.reindex(signals.index)
    out['streak_recovery_slope']=slope.reindex(signals.index)
    out['streak_risk']=risk
    out['streak_locked']=False
    out['streak_released']=False
    locked=False
    for i,date in enumerate(signals.index):
        triggered=False
        if bool(risk.iloc[i]) and (locked or signals.symbol.iloc[i]!='CASH'):
            locked,triggered=True,True
        elif locked and bool(recovery.iloc[i]):
            locked=False
            out.loc[date,'streak_released']=True
        out.loc[date,'streak_locked']=locked
        if locked and signals.symbol.iloc[i]!='CASH':
            state='STREAK_CASH_TRIGGER' if triggered else 'STREAK_CASH_WAIT'
            reason=(f"{symbol}下跌口径={mode}；连续下跌{int(days.iloc[i])}日；累计跌幅={drop.iloc[i]:.2%}；"
                    f"阈值={threshold:.2%}；{recovery_symbol} {ma_kind.upper()}{period}斜率={slope.loc[date]:.6f}；"
                    "现金锁定，等待均线向上。原MACD/恢复确认现金优先；收盘确认、次日开盘执行。")
            out.loc[date,['symbol','weight','state','reason']]=['CASH',0.0,state,reason]
    return out


def candidates():
    """45 prespecified variants: exits and recovery are explicit and bounded."""
    items=[]
    def add(symbol,mode,threshold,ma_days,ma_kind='ma',window=3,recovery_kind='rising'):
        key=f'{symbol}_{mode}{window}_d{int(threshold*10000)}_{ma_kind}{ma_days}_{recovery_kind}'
        exit_name='连跌≥2日' if mode=='streak' else f'近{window}日累计'
        name=f'{symbol} {exit_name}跌{threshold:.0%}→SMH {ma_kind.upper()}{ma_days}上升'
        if recovery_kind=='turn':name+='（严格拐头）'
        rules=dict(symbol=symbol,recovery_symbol='SMH',mode=mode,threshold=threshold,ma_days=ma_days,
                   ma_kind=ma_kind,window=window,recovery_kind=recovery_kind)
        items.append(dict(key=key,name=name,rules=rules))
    for threshold in (.02,.04,.06,.08,.10):
        for period in (5,10,20):add('SMH','streak',threshold,period)
    for threshold in (.06,.12,.18,.24):
        for period in (10,20):add('SOXL','streak',threshold,period)
    for threshold in (.04,.06,.08):
        for period in (10,20):add('SMH','streak',threshold,period,'ema')
    for window in (3,5):
        for threshold in (.04,.06,.08):
            for period in (10,20):add('SMH','window',threshold,period,window=window)
    for threshold in (.04,.08):
        for period in (10,20):add('SMH','streak',threshold,period,recovery_kind='turn')
    return items


def soxl_candidates():
    """37 SOXL exit/recovery variants plus eight matched SMH recovery controls."""
    items=[]
    def add(mode,threshold,period,kind='ma',window=3,recovery_kind='rising',recovery_symbol='SOXL'):
        key=f'SOXL_{mode}{window}_d{int(threshold*10000)}_{kind}{period}_{recovery_kind}_recover{recovery_symbol}'
        loss='连跌≥2日' if mode=='streak' else f'近{window}日累计'
        name=f'SOXL {loss}跌{threshold:.0%}→{recovery_symbol} {kind.upper()}{period}上升'
        if recovery_kind=='turn':name+='（严格拐头）'
        family='SOXL双指标' if recovery_symbol=='SOXL' else 'SMH恢复对照'
        rules=dict(symbol='SOXL',recovery_symbol=recovery_symbol,mode=mode,threshold=threshold,
            ma_days=period,ma_kind=kind,window=window,recovery_kind=recovery_kind)
        items.append(dict(key=key,name=name,rules=rules,family=family))
    for threshold in (.06,.12,.18,.24,.30):
        for period in (5,10,20):add('streak',threshold,period)
    for threshold in (.12,.18,.24):
        for period in (10,20):add('streak',threshold,period,'ema')
    for window in (3,5):
        for threshold in (.12,.18,.24):
            for period in (10,20):add('window',threshold,period,window=window)
    for threshold in (.12,.24):
        for period in (10,20):add('streak',threshold,period,recovery_kind='turn')
    for threshold in (.06,.12,.18,.24):
        for period in (10,20):add('streak',threshold,period,recovery_symbol='SMH')
    return items


def recovery_pairs(table,configurations):
    """Same exit and MA settings; change only the recovery price symbol."""
    rows=[]
    configs={c['key']:c for c in configurations if c['rules'] is not None}
    metrics=table.set_index('key')
    for control in (c for c in configs.values() if c.get('family')=='SMH恢复对照'):
        paired={**control['rules'],'recovery_symbol':'SOXL'}
        primary=next(c for c in configs.values() if c['rules']==paired)
        left,right=metrics.loc[primary['key']],metrics.loc[control['key']]
        rows.append(dict(threshold=paired['threshold'],ma_days=paired['ma_days'],
            soxl_cagr=float(left.cagr),smh_cagr=float(right.cagr),
            soxl_drawdown=float(left.max_drawdown),smh_drawdown=float(right.max_drawdown),
            cagr_difference=float(left.cagr-right.cagr),drawdown_difference=float(left.max_drawdown-right.max_drawdown)))
    return rows


def editor_code(profile,rules):
    labels={**profile.get('state_labels',{}),'STREAK_CASH_TRIGGER':'累计连跌触发现金避险',
            'STREAK_CASH_WAIT':'现金等待均线向上'}
    loss=('至少连续2个收盘下跌交易日，自连续下跌前收盘累计，平盘或上涨重置'
          if rules['mode']=='streak' else f"近{rules['window']}个交易日收盘累计跌幅，中间允许反弹")
    recovery=("当天均线高于昨天" if rules['recovery_kind']=='rising'
              else "当天均线高于昨天，且昨天均线不高于前天（严格由非上升转上升）")
    note=(f"观察{rules['symbol']}：{loss}，达到{rules['threshold']:.1%}后覆盖为现金。"
          f"{rules['recovery_symbol']} {rules['ma_kind'].upper()}{rules['ma_days']}恢复定义：{recovery}。"
          "风险重复触发优先于恢复；已有原策略现金状态优先。解除只恢复原策略当天目标，"
          "仍须满足原MACD和恢复确认；不强制买入。所有指标按收盘确认，下一交易日开盘执行。")
    notes={**profile.get('state_notes',{}),'STREAK_CASH_TRIGGER':note,
           'STREAK_CASH_WAIT':note+'尚未解除新增锁定，继续现金。'}
    return (profile['code']+'\n\n# 连续跌幅＋均线恢复现金覆盖层；本机研究副本。\n'
            f'STREAK_RULES = {rules!r}\nSTATE_LABELS = {labels!r}\nSTATE_NOTES = {notes!r}\n\n'
            +inspect.getsource(streak_features)+'\n'+inspect.getsource(apply_streak)
            +'\n_streak_underlying = generate_signals\n\ndef generate_signals(frames, start="2017-01-02", cfg=Config(**PARAMETERS)):\n'
            +'    source = _streak_underlying(frames, start=start, cfg=cfg)\n'
            +'    return apply_streak(source, frames, STREAK_RULES)\n')


def stress_runs(frames,base_nav):
    records=[]
    for symbol in ('SMH','SOXL'):
        feature=streak_features(frames[symbol].close)
        for episode in episodes(base_nav.equity)[:5]:
            cut=feature.loc[episode['peak']:episode['trough']]
            cut=cut[cut.days.ge(2)]
            worst_date=cut['drop'].idxmax();row=cut.loc[worst_date]
            records.append(dict(symbol=symbol,peak=str(episode['peak'].date()),trough=str(episode['trough'].date()),
                run_start=str(row.start.date()),run_end=str(worst_date.date()),days=int(row.days),drop=float(row['drop'])))
    return records


def html_table(records,columns):
    table=pd.DataFrame(records)[list(columns)].rename(columns=columns)
    for name in table:
        if pd.api.types.is_bool_dtype(table[name]):table[name]=table[name].map({True:'是',False:'否'})
        elif any(s in name for s in ('年化','回撤','跌幅','现金占比','区间收益')):
            table[name]=table[name].map(lambda x:f'{x:.2%}')
    return table.to_html(index=False,escape=True,float_format=lambda x:f'{x:.2f}')


def dominance_flags(table,baseline):
    """Floating-point equality is not an improvement in drawdown or return."""
    return table.cagr.gt(baseline.cagr+1e-10)&table.max_drawdown.lt(baseline.max_drawdown-1e-10)


def holding_comparison(navs,chosen,names):
    baseline=navs['baseline']
    records=[]
    for key in chosen:
        nav=navs[key]
        if not nav.index.equals(baseline.index):raise ValueError('Comparison dates differ')
        extra=nav.held.eq('CASH')&baseline.held.ne('CASH')
        records.append(dict(key=key,name=names[key],extra_cash_sessions=int(extra.sum()),
            different_holding_sessions=int(nav.held.ne(baseline.held).sum()),
            extra_cash_dates=';'.join(nav.index[extra].strftime('%Y-%m-%d'))))
    return records


def run(study='mixed'):
    if study not in ('mixed','soxl'):raise ValueError('Unknown study')
    profile=core.active_strategy();fingerprint=profile['fingerprint']
    if profile.get('kind')!='python' or core.base_symbol(profile)!='SMH':
        raise ValueError('本研究需要当前本机SMH/SOXL Python策略')
    snapshot,bundle=perf.confirmed_inputs();cutoff=snapshot['last']['date']
    frames,underlying,_,_=perf.datasets(bundle,cutoff,[],profile=profile)
    output_root='streak_soxl_research' if study=='soxl' else 'streak_research'
    folder=core.RUNTIME/output_root/f"{profile['id']}-v{profile['revision']}-{cutoff}"
    folder.mkdir(parents=True,exist_ok=True)
    configurations=[dict(key='baseline',name=f"原策略 v{profile['revision']}",rules=None,family='原策略'),
                    *(soxl_candidates() if study=='soxl' else candidates())]
    navs,sources,rows,periods={},{},[],[]
    for i,config in enumerate(configurations):
        source=underlying if config['rules'] is None else apply_streak(underlying,frames,config['rules'])
        nav,trades,m=replay_nav(frames,source,cutoff)
        navs[config['key']],sources[config['key']]=nav,source
        nav.to_csv(folder/(config['key']+'-净值.csv'),encoding='utf-8-sig')
        trades.to_csv(folder/(config['key']+'-调仓.csv'),index=False,encoding='utf-8-sig')
        row=dict(key=config['key'],name=config['name'],family=config.get('family','研究候选'),
                 cagr=m['cagr'],max_drawdown=-m['max_drawdown_close'],
                 calmar=m['calmar'],sharpe=m['sharpe_rf0'],cash_fraction=m['cash_days_fraction'],
                 rebalance_days=m['rebalance_days'],risk_signal_days=int(source.get('streak_risk',pd.Series(dtype=bool)).sum()))
        for start,end,label,prefix in (('2017-01-03','2021-12-31','2017—2021','train'),
                ('2022-01-01','2024-12-31','2022—2024','check'),('2025-01-01',cutoff,'2025至今','recent')):
            metrics=period_metrics(nav,start,end,label)
            periods.append(dict(key=config['key'],name=config['name'],**metrics))
            row.update({prefix+'_'+k:v for k,v in metrics.items() if k!='period'})
        for label in perf.PERIODS:
            win=perf.window(nav.index,label)
            curve=nav.equity/100000
            capital=float(curve.loc[win.baseline]) if win.baseline is not None else 1.
            metrics=perf.unit_result(curve.loc[win.first:win.end],capital,win,perf.CONTINUOUS)['metrics']
            periods.append(dict(key=config['key'],name=config['name'],period=label,
                cagr=metrics['annualized_return'],max_drawdown=metrics['max_drawdown'],
                calmar=metrics['annualized_return']/metrics['max_drawdown']))
        rows.append(row)
        print(f"{i+1}/{len(configurations)} {config['name']} 年化{row['cagr']:.2%} 回撤{row['max_drawdown']:.2%}",flush=True)
    table=pd.DataFrame(rows);baseline=table[table.key.eq('baseline')].iloc[0]
    table['both_improved']=dominance_flags(table,baseline)
    alternatives=table[table.key.ne('baseline')&table.family.ne('SMH恢复对照')]
    bounded=alternatives[alternatives.train_max_drawdown.le(.50)]
    train_key=(bounded if len(bounded) else alternatives).sort_values('train_calmar',ascending=False).iloc[0].key
    full_key=alternatives.sort_values('calmar',ascending=False).iloc[0].key
    lowest_key=alternatives.sort_values(['max_drawdown','cagr'],ascending=[True,False]).iloc[0].key
    balanced_key=alternatives[alternatives.max_drawdown.le(alternatives.max_drawdown.min()+.01)].sort_values('cagr',ascending=False).iloc[0].key
    improved=alternatives[alternatives.both_improved]
    chosen=list(dict.fromkeys([train_key,full_key,lowest_key,balanced_key,
                              *improved.sort_values('calmar',ascending=False).key.head(1)]))
    export=[]
    for key in chosen:
        config=next(c for c in configurations if c['key']==key)
        code=editor_code(profile,config['rules'])
        candidate=core.make_strategy('恢复确认＋'+config['name'],code=code)
        replayed=core.replay(frames,candidate,audit_code=True)
        np.testing.assert_array_equal(replayed.symbol,sources[key].symbol)
        np.testing.assert_array_equal(replayed.state,sources[key].state)
        np.testing.assert_allclose(replayed.weight,sources[key].weight,rtol=0,atol=1e-12)
        filename=key+'-策略代码.py'
        (folder/filename).write_text(code,encoding='utf-8')
        export.append(dict(key=key,name=candidate['name'],file=filename))
    costs=[]
    for key in ['baseline',*chosen]:
        for bps in (5.,10.,25.):
            _,_,m=replay_nav(frames,sources[key],cutoff,bps)
            costs.append(dict(key=key,cost_bps=bps,cagr=m['cagr'],max_drawdown=-m['max_drawdown_close']))
    stress=[]
    for episode in episodes(navs['baseline'].equity)[:5]:
        start,end=episode['peak'],episode['trough']
        for key in ['baseline',*chosen]:
            cut=navs[key].equity.loc[start:end]
            values=cut.to_numpy()/cut.iloc[0]
            stress.append(dict(key=key,name=next(c['name'] for c in configurations if c['key']==key),
                start=str(start.date()),end=str(end.date()),return_=float(values[-1]-1),
                window_drawdown=float(-(values/np.maximum.accumulate(values)-1).min())))
    runs=stress_runs(frames,navs['baseline'])
    names={c['key']:c['name'] for c in configurations}
    holdings=holding_comparison(navs,chosen,names)
    pairs=recovery_pairs(table,configurations) if study=='soxl' else []
    if pairs:pd.DataFrame(pairs).to_csv(folder/'恢复标的对照.csv',index=False,encoding='utf-8-sig')
    table=table.sort_values('calmar',ascending=False)
    for filename,records in (('全部候选结果.csv',table),('分段与近年结果.csv',periods),
            ('交易成本敏感性.csv',costs),('五段压力区间.csv',stress),('五段连续跌幅.csv',runs),('新增现金日统计.csv',holdings)):
        pd.DataFrame(records).to_csv(folder/filename,index=False,encoding='utf-8-sig')
    metadata=dict(study=study,profile_name=profile['name'],revision=profile['revision'],fingerprint=fingerprint,
        cutoff=cutoff,source=snapshot['source'],fetched=snapshot['fetched'],configurations=configurations,
        train_choice=train_key,full_choice=full_key,lowest_choice=lowest_key,balanced_choice=balanced_key,exported=export,
        results=table.to_dict('records'),costs=costs,stress=stress,runs=runs,holdings=holdings,recovery_pairs=pairs)
    (folder/'结果.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    chart=make_subplots(rows=2,cols=1,shared_xaxes=True,vertical_spacing=.09,
                         subplot_titles=['初始1万元资金曲线 · 对数轴','账户日终回撤'])
    for i,key in enumerate(['baseline',*chosen]):
        nav=navs[key];curve=nav.equity/100000;x=curve.index.strftime('%Y-%m-%d')
        name=next(c['name'] for c in configurations if c['key']==key)
        color=('#3f63ba','#179e8f','#d99331','#9452b4','#bd4678','#59777c')[i]
        chart.add_trace(go.Scatter(x=x,y=curve*10000,name=name,line_color=color),row=1,col=1)
        peak=np.maximum.accumulate(np.r_[1.,curve.to_numpy()])[1:]
        chart.add_trace(go.Scatter(x=x,y=(curve.to_numpy()/peak-1)*100,name=name,
                                  showlegend=False,line_color=color),row=2,col=1)
    chart.update_yaxes(type='log',row=1,col=1)
    chart.update_layout(height=800,template='plotly_white',hovermode='x unified')
    scope=("本轮37组候选的新增卖出跌幅与恢复均线都使用SOXL，另外8组仅把恢复均线换回SMH作对照。"
           "原v2的SMH MACD、恢复确认和基础资产分配继续保留；这不是SOXL与现金独立策略。"
           if study=='soxl' else "恢复均线统一观察SMH。")
    note=(scope+"严格连跌：至少2个交易日收盘低于前收，累计跌幅=1−当前收盘/连跌开始前收盘；上涨或平盘立即重置。"
        "另比较近3/5日累计跌幅，允许中间小反弹，两者不混称。普通恢复版为当天均线高于昨天；"
        "严格拐头版还要求昨天均线不高于前天。新增层覆盖为现金，解除后仅恢复原策略当日目标，"
        "原MACD和恢复确认现金状态仍优先；同日下跌信号优先，不作盘中阈值成交。信号收盘确认、次日开盘执行，"
        "单边成本0.1%，现金利率0，价格已拆股调整，账户净值含分红调整；不含汇率、税和证券代币费用。"
        "45组预设候选；早期选择按2017—2021回撤≤50%且Calmar最高，全历史最佳与最小回撤是事后比较；"
        "回撤折中候选是在最小回撤加1个百分点以内选择年化最高者，两项同时改善候选按Calmar选择；"
        "收益与回撤变化小于1e-10不判定改善，避免把浮点误差当收益。"
        "本研究参照已知大跌，基础策略也已研究这些历史；时间分段不是独立样本外，结果不能称为统计显著或未来保证。"
        "当前策略未切换，代码只写入本机私有研究目录，未保存或启用新策略。")
    names={c['key']:c['name'] for c in configurations}
    pair_section=('<h2>同样SOXL卖出规则，仅改变恢复均线标的</h2>'+
        html_table(pairs,{'threshold':'累计跌幅阈值','ma_days':'MA周期','soxl_cagr':'SOXL恢复年化',
            'smh_cagr':'SMH恢复年化','soxl_drawdown':'SOXL恢复回撤','smh_drawdown':'SMH恢复回撤'}) if pairs else '')
    study_label='SOXL累计连跌与SOXL均线恢复研究' if study=='soxl' else '累计连跌与均线恢复研究'
    links=''.join(f'<li><a href="{html.escape(e["file"])}">{html.escape(e["name"])}</a></li>' for e in export)
    report=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>{study_label}</title>
<style>body{{max-width:1650px;margin:30px auto;padding:20px;font:16px system-ui;color:#20344b}}p{{line-height:1.8}}table{{border-collapse:collapse;font-size:14px;width:100%;margin-bottom:30px}}td,th{{padding:9px;border-bottom:1px solid #ddd;text-align:left}}th{{background:#eef3f9}}a{{color:#286bb0}}</style>
<h1>{html.escape(profile['name'])} · v{profile['revision']} · {study_label}</h1><p>2017-01-03—{cutoff}；当前100%进攻仓位版本。</p><p>{note}</p>
<h2>五段原策略大回撤中的最深连续下跌</h2>{html_table(runs,{'symbol':'观察标的','peak':'账户前高','trough':'账户谷底','run_start':'连跌首日','run_end':'连跌末日','days':'连跌交易日','drop':'累计跌幅'})}
<h2>全历史结果 · 按Calmar排序</h2>{html_table(table,{'family':'类型','name':'规则','cagr':'年化','max_drawdown':'最大回撤','calmar':'Calmar','sharpe':'Sharpe（现金利率0）','cash_fraction':'现金占比','rebalance_days':'调仓天数','both_improved':'收益与回撤同时改善'})}
{pair_section}
<p>早期选择：{html.escape(names[train_key])}；全历史Calmar最佳：{html.escape(names[full_key])}；全历史回撤最小：{html.escape(names[lowest_key])}；回撤折中：{html.escape(names[balanced_key])}。</p>
{chart.to_html(full_html=False,include_plotlyjs=True,config={'displaylogo':False})}
<h2>分段与近1/2/3/5年</h2>{html_table([p for p in periods if p['key'] in ['baseline',*chosen]],{'name':'规则','period':'区间','cagr':'年化','max_drawdown':'最大回撤','calmar':'Calmar'})}
<h2>费用敏感性</h2>{html_table(costs,{'key':'组合编号','cost_bps':'单边费用（基点）','cagr':'年化','max_drawdown':'最大回撤'})}
<h2>与原策略实际持仓差异</h2><p>新增现金日是新规则收盘持有现金、但原策略仍持有资产的日期；具体日期保存在新增现金日统计CSV。少数日期带来的微小收益差异不能证明稳健性。</p>{html_table(holdings,{'name':'规则','extra_cash_sessions':'新增现金交易日','different_holding_sessions':'持仓不同交易日'})}
<h2>原策略五段压力日期对照</h2><p>固定日期内的区间回撤，不等于各候选全历史最大回撤。</p>{html_table(stress,{'name':'规则','start':'区间起点','end':'区间终点','return_':'区间收益','window_drawdown':'区间最大回撤'})}
<h2>本机编辑器研究代码</h2><ul>{links}</ul></html>'''
    (folder/(study_label+'.html')).write_text(report,encoding='utf-8')
    if core.active_strategy()['fingerprint']!=fingerprint:raise ValueError('运行中原策略发生变化，须重新研究')
    print('REPORT '+str(folder),flush=True)
    print(table[['name','cagr','max_drawdown','calmar','both_improved']].head(12).to_string(index=False),flush=True)
    return folder,metadata


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='连跌现金与均线恢复研究；不启用、不下单，输出仅在私有runtime')
    parser.add_argument('--study',choices=('mixed','soxl'),default='mixed',help='soxl同时用SOXL跌幅和SOXL恢复均线')
    args=parser.parse_args()
    run(args.study)
