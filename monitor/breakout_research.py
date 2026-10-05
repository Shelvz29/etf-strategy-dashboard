"""Bounded, causal cash-overlay study; all user-specific outputs stay private."""
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
from drawdown_review import episodes


def apply_breakout(signals, frames, rules):
    """Cash lock after a break; a breakout only restores the underlying target.

    Donchian bounds exclude today's high/low. MA/EMA use today's confirmed close.
    Even a low-touch signal executes next open, never at the touched threshold.
    Underlying cash states retain priority and are never forced into an asset.
    """
    symbol = rules['symbol']
    kind = rules['kind']
    sell_days, buy_days = rules['sell_days'], rules['buy_days']
    buffer = rules.get('buffer', 0.0)
    sell_mode = rules.get('sell_mode', 'close')
    if (symbol not in frames or kind not in ('channel', 'ma', 'ema')
        or any(isinstance(v, bool) or not isinstance(v, int) or not 2 <= v <= 252 for v in (sell_days,buy_days))
        or not np.isfinite(buffer) or not 0 <= buffer <= .05
        or sell_mode not in ('close','low')):
        raise ValueError('Invalid breakout rules')
    prices = frames[symbol]
    if kind == 'channel':
        lower = prices.low.rolling(sell_days).min().shift(1)
        upper = prices.high.rolling(buy_days).max().shift(1)
    elif kind == 'ma':
        lower = prices.close.rolling(sell_days).mean()
        upper = prices.close.rolling(buy_days).mean()
    else:
        lower = prices.close.ewm(span=sell_days,adjust=False,min_periods=sell_days).mean()
        upper = prices.close.ewm(span=buy_days,adjust=False,min_periods=buy_days).mean()
    lower,upper = lower.reindex(signals.index)*(1-buffer),upper.reindex(signals.index)*(1+buffer)
    close = prices.close.reindex(signals.index)
    sell_price = prices[sell_mode].reindex(signals.index)
    if not np.isfinite(np.column_stack((lower,upper,close,sell_price))).all():
        raise ValueError('Insufficient breakout warm-up or missing prices')
    out = signals.copy(deep=True)
    out['breakout_underlying_state'] = signals.state
    out['breakout_lower'] = lower
    out['breakout_upper'] = upper
    out['breakout_locked'] = False
    out['breakout_released'] = False
    locked = False
    for i,date in enumerate(signals.index):
        broken = bool(sell_price.iloc[i] < lower.iloc[i])
        breakout = bool(close.iloc[i] > upper.iloc[i])
        triggered = False
        if broken and (locked or signals.symbol.iloc[i] != 'CASH'):
            locked,triggered = True,True
        elif locked and breakout:
            locked = False
            out.loc[date,'breakout_released'] = True
        out.loc[date,'breakout_locked'] = locked
        # Preserve existing MACD/recovery cash states instead of relabeling them.
        if locked and signals.symbol.iloc[i] != 'CASH':
            state = 'BREAKOUT_CASH_BREAK' if triggered else 'BREAKOUT_CASH_WAIT'
            reason = (f"{symbol}跌破位={lower.iloc[i]:.6f}；突破位={upper.iloc[i]:.6f}；"
                      f"当前现金锁定；基础目标={signals.symbol.iloc[i]} {signals.weight.iloc[i]:.0%}。"
                      "收盘确认，次日开盘执行；突破只能恢复基础目标，不能覆盖基础现金状态。")
            out.loc[date,['symbol','weight','state','reason']] = ['CASH',0.0,state,reason]
    return out


def candidates():
    """Fixed small grid, no thresholds generated from the observed best result."""
    result=[]
    def add(symbol,kind,sell,buy,buffer=0.0,sell_mode='close'):
        key=f'{symbol}_{kind}_s{sell}_b{buy}_buf{int(buffer*10000)}_{sell_mode}'
        style={'channel':'前期低点/高点','ma':'MA','ema':'EMA'}[kind]
        name=f'{symbol} {style} 卖{sell}/买{buy}'
        if buffer:name+=f' 缓冲{buffer:.0%}'
        if sell_mode=='low':name+=' 最低价触及'
        result.append(dict(key=key,name=name,rules=dict(symbol=symbol,kind=kind,sell_days=sell,
                            buy_days=buy,buffer=buffer,sell_mode=sell_mode)))
    for sell,buy in ((5,10),(10,20),(20,20),(20,55),(55,55)):
        for buffer in (0.0,.01):add('SMH','channel',sell,buy,buffer)
    for sell,buy in ((10,20),(20,55)):add('SOXL','channel',sell,buy)
    for period in (20,50,100):add('SMH','ma',period,period)
    for period in (20,50):add('SMH','ema',period,period)
    add('SMH','ema',20,20,.01)
    add('SMH','channel',10,20,sell_mode='low')
    return result


def replay_nav(frames,signals,cutoff,cost_bps=10.0):
    nav,trades=perf.engine.simulate(frames,signals,start='2017-01-03',end=cutoff,
        initial=100000,cost_bps=cost_bps,execution='next_open',daily_rebalance=False)
    return nav,trades,perf.engine.metrics(nav,trades)


def period_metrics(nav,start,end,label):
    curve=nav.equity/100000
    win=perf.window(curve.index,'自选',start,end)
    capital=float(curve.loc[win.baseline]) if win.baseline is not None else 1.0
    m=perf.unit_result(curve.loc[win.first:win.end],capital,win,perf.CONTINUOUS)['metrics']
    return dict(period=label,cagr=m['annualized_return'],max_drawdown=m['max_drawdown'],
                calmar=m['annualized_return']/m['max_drawdown'] if m['max_drawdown']>0 else 0)


def editor_code(profile,rules):
    """A local editor-compatible copy; no source is written into tracked files."""
    labels={**profile.get('state_labels',{}),'BREAKOUT_CASH_BREAK':'跌破位现金避险',
            'BREAKOUT_CASH_WAIT':'现金等待突破位'}
    kind={'channel':'此前交易日最低/最高价（不含当日）','ma':'简单均线','ema':'指数均线'}[rules['kind']]
    note=(f"观察{rules['symbol']}；{kind}卖出周期{rules['sell_days']}、买入周期{rules['buy_days']}，"
          f"上下缓冲{rules['buffer']:.1%}。卖出比较{'当日最低价' if rules['sell_mode']=='low' else '收盘价'}，"
          "严格低于下边界后现金锁定，收盘严格高于上边界解除。触及或相等不触发。"
          "突破仅恢复原策略目标，原MACD/恢复确认现金优先；收盘确认、次日开盘执行，不假设阈值成交。")
    notes={**profile.get('state_notes',{}),'BREAKOUT_CASH_BREAK':note,
           'BREAKOUT_CASH_WAIT':note+'仍未突破，继续现金；基础策略始终独立演算。'}
    return (profile['code']+'\n\n# 跌破/突破现金覆盖层；研究副本，不替换原版本。\n'
            f'BREAKOUT_RULES = {rules!r}\nSTATE_LABELS = {labels!r}\nSTATE_NOTES = {notes!r}\n\n'
            +inspect.getsource(apply_breakout)
            +'\n_breakout_underlying = generate_signals\n\ndef generate_signals(frames, start="2017-01-02", cfg=Config(**PARAMETERS)):\n'
            +'    source = _breakout_underlying(frames, start=start, cfg=cfg)\n'
            +'    return apply_breakout(source, frames, BREAKOUT_RULES)\n')


def run():
    profile=core.active_strategy()
    if profile.get('kind')!='python' or core.base_symbol(profile)!='SMH':
        raise ValueError('当前研究须以本机SMH/SOXL Python策略为基础')
    fingerprint=profile['fingerprint']
    snap,bundle=perf.confirmed_inputs();cutoff=snap['last']['date']
    frames,signals,_,_=perf.datasets(bundle,cutoff,[],profile=profile)
    folder=core.RUNTIME/'breakout_research'/f"{profile['id']}-v{profile['revision']}-{cutoff}"
    folder.mkdir(parents=True,exist_ok=True)
    configs=[dict(key='baseline',name='原v2',rules=None),*candidates()]
    navs,sources,rows,periods={},{},[],[]
    for i,c in enumerate(configs):
        source=signals if c['rules'] is None else apply_breakout(signals,frames,c['rules'])
        nav,trades,m=replay_nav(frames,source,cutoff)
        navs[c['key']],sources[c['key']]=nav,source
        nav.to_csv(folder/(c['key']+'-净值.csv'),encoding='utf-8-sig')
        trades.to_csv(folder/(c['key']+'-调仓.csv'),index=False,encoding='utf-8-sig')
        row=dict(key=c['key'],name=c['name'],cagr=m['cagr'],max_drawdown=-m['max_drawdown_close'],
                 sharpe=m['sharpe_rf0'],calmar=m['calmar'],cash_fraction=m['cash_days_fraction'],
                 rebalance_days=m['rebalance_days'],turnover=m['annual_one_way_turnover'])
        for start,end,label in (('2017-01-03','2021-12-31','2017—2021'),
                                ('2022-01-01','2024-12-31','2022—2024'),('2025-01-01',cutoff,'2025至今')):
            p=period_metrics(nav,start,end,label)
            periods.append(dict(key=c['key'],name=c['name'],**p))
            prefix={'2017—2021':'train','2022—2024':'check','2025至今':'recent'}[label]
            row.update({prefix+'_'+k:v for k,v in p.items() if k!='period'})
        for label in perf.PERIODS:
            win=perf.window(nav.index,label)
            curve=nav.equity/100000
            capital=float(curve.loc[win.baseline]) if win.baseline is not None else 1.0
            m=perf.unit_result(curve.loc[win.first:win.end],capital,win,perf.CONTINUOUS)['metrics']
            periods.append(dict(key=c['key'],name=c['name'],period=label,cagr=m['annualized_return'],
                                max_drawdown=m['max_drawdown'],calmar=m['annualized_return']/m['max_drawdown']))
        rows.append(row)
        print(f"{i+1}/{len(configs)} {c['name']}: 年化{row['cagr']:.2%} 回撤{row['max_drawdown']:.2%}",flush=True)
    table=pd.DataFrame(rows)
    alternatives=table[table.key.ne('baseline')]
    bounded=alternatives[alternatives.train_max_drawdown.le(.50)]
    train_choice=(bounded if len(bounded) else alternatives).sort_values('train_calmar',ascending=False).iloc[0].key
    full_choice=alternatives.sort_values('calmar',ascending=False).iloc[0].key
    base=table[table.key.eq('baseline')].iloc[0]
    table['both_improved']=table.cagr.gt(base.cagr)&table.max_drawdown.lt(base.max_drawdown)
    winners=table[table.both_improved]
    chosen=list(dict.fromkeys([train_choice,full_choice,*winners.sort_values('cagr',ascending=False).key.head(1)]))
    exported=[]
    for key in chosen:
        c=next(c for c in configs if c['key']==key)
        code=editor_code(profile,c['rules'])
        candidate=core.make_strategy('恢复确认＋'+c['name'],code=code)
        actual=core.replay(frames,candidate,audit_code=True)
        np.testing.assert_array_equal(actual.symbol,sources[key].symbol)
        np.testing.assert_allclose(actual.weight,sources[key].weight,rtol=0,atol=1e-12)
        (folder/(key+'-策略代码.py')).write_text(code,encoding='utf-8')
        exported.append(dict(key=key,name=candidate['name'],file=key+'-策略代码.py',audit='prefix causality and all targets match'))
    costs=[]
    for key in ['baseline',*chosen]:
        for bps in (5.,10.,25.):
            _,_,m=replay_nav(frames,sources[key],cutoff,bps)
            costs.append(dict(key=key,cost_bps=bps,cagr=m['cagr'],max_drawdown=-m['max_drawdown_close']))
    # Evaluate every overlay over the same original-v2 peak-to-trough stress dates.
    stress=[]
    for episode in episodes(navs['baseline'].equity)[:5]:
        start,end=episode['peak'],episode['trough']
        for key in ['baseline',*chosen]:
            cut=navs[key].equity.loc[start:end]
            values=cut.to_numpy()/float(cut.iloc[0])
            stress.append(dict(key=key,start=str(start.date()),end=str(end.date()),
                              return_=float(values[-1]-1),window_drawdown=float(-(values/np.maximum.accumulate(values)-1).min())))
    table=table.sort_values('calmar',ascending=False)
    table.to_csv(folder/'全部候选结果.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(periods).to_csv(folder/'分段与近年结果.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(costs).to_csv(folder/'交易成本敏感性.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(stress).to_csv(folder/'原v2五段压力区间.csv',index=False,encoding='utf-8-sig')
    metadata=dict(profile_name=profile['name'],revision=profile['revision'],fingerprint=fingerprint,
        cutoff=cutoff,source=snap['source'],fetched=snap['fetched'],configurations=configs,
        train_choice=train_choice,full_choice=full_choice,exported=exported,results=table.to_dict('records'),
        costs=costs,stress=stress)
    (folder/'结果.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    chart=make_subplots(rows=2,cols=1,shared_xaxes=True,vertical_spacing=.09,
                        subplot_titles=['资金曲线 · 初始资金1万元 · 对数轴','账户回撤'])
    for i,key in enumerate(['baseline',*chosen]):
        curve=navs[key].equity/100000
        name=next(c['name'] for c in configs if c['key']==key)
        color=('#3f63ba','#179e8f','#d99331','#9452b4')[i]
        dates=curve.index.strftime('%Y-%m-%d')
        chart.add_trace(go.Scatter(x=dates,y=curve*10000,name=name,line_color=color),row=1,col=1)
        peak=np.maximum.accumulate(np.r_[1.,curve.to_numpy()])[1:]
        chart.add_trace(go.Scatter(x=dates,y=(curve.to_numpy()/peak-1)*100,name=name,showlegend=False,line_color=color),row=2,col=1)
    chart.update_yaxes(type='log',row=1,col=1)
    chart.update_layout(height=850,template='plotly_white',hovermode='x unified')
    def tab(data,cols):
        t=pd.DataFrame(data)[list(cols)].rename(columns=cols)
        for column in t:
            if pd.api.types.is_bool_dtype(t[column]):
                t[column]=t[column].map({True:'是',False:'否'})
            elif any(word in column for word in ('年化','回撤','现金占比','区间收益')):
                t[column]=t[column].map(lambda v:f'{v:.2%}')
        return t.to_html(index=False,escape=True,float_format=lambda v:f'{v:.2f}')
    explanation=("跌破/突破层只覆盖为现金，不反向做空。原v2独立演算；突破后采用当日原v2目标，"
        "原MACD避险与恢复确认仍可要求现金。近期通道=此前N个交易日的最低/最高价，不含当日；"
        "严格跌破才卖，严格突破才解除；均线含当天已确认收盘。最低价触及版本仍在次日开盘卖，"
        "并非盘中止损。费用单边0.1%，现金收益0，不含税、汇率和证券代币费用。"
        "19个预设组合，不进行无限参数搜索。按2017—2021回撤≤50%的候选中Calmar最高选择分段候选；"
        "全历史Calmar最高仅为事后描述。2022—2024和2025至今用于时间分段检查，"
        "但基础v2本身已使用这些历史进行研究，因此不能称为真正独立样本外测试或统计显著证据。"
        "近年收益按连续持仓口径计算。当前启用策略未更换，代码文件仅供本机编辑器试用。")
    links=''.join(f'<li><a href="{html.escape(c["file"])}">{html.escape(c["name"])}</a></li>' for c in exported)
    report=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>跌破位现金与突破买回研究</title>
<style>body{{max-width:1650px;margin:30px auto;padding:20px;font:16px system-ui;color:#20344b}}p{{line-height:1.8}}table{{border-collapse:collapse;font-size:14px;width:100%;margin-bottom:30px}}td,th{{padding:9px;border-bottom:1px solid #ddd;text-align:left}}th{{background:#eef3f9}}a{{color:#286bb0}}</style>
<h1>MACD＋4%急跌＋恢复确认 v2 · 跌破/突破现金覆盖研究</h1><p>2017-01-03—{cutoff}，基于本机当前100%进攻版本。</p><p>{explanation}</p>
<h2>全历史结果 · 按Calmar排序</h2>{tab(table,{'name':'规则','cagr':'年化','max_drawdown':'最大回撤','calmar':'Calmar','sharpe':'Sharpe（现金利率0）','cash_fraction':'现金占比','rebalance_days':'调仓天数','both_improved':'收益与回撤同时改善'})}
<p>分段选择：{html.escape(next(c['name'] for c in configs if c['key']==train_choice))}。全历史Calmar最高：{html.escape(next(c['name'] for c in configs if c['key']==full_choice))}。</p>
{chart.to_html(full_html=False,include_plotlyjs=True,config={'displaylogo':False})}
<h2>分段与近1/2/3/5年检查</h2>{tab([p for p in periods if p['key'] in ['baseline',*chosen]],{'name':'规则','period':'区间','cagr':'年化','max_drawdown':'最大回撤','calmar':'Calmar'})}
<h2>费用敏感性</h2>{tab(costs,{'key':'组合编号','cost_bps':'单边成本（基点）','cagr':'年化','max_drawdown':'最大回撤'})}
<h2>原v2五段压力日期对比</h2><p>这是固定日期内的净值变化与区间回撤，不代表各新策略的全历史最大回撤。</p>{tab(stress,{'key':'组合编号','start':'起点','end':'终点','return_':'区间收益','window_drawdown':'区间最大回撤'})}
<h2>本机可编辑策略代码</h2><ul>{links}</ul></html>'''
    (folder/'跌破突破策略研究.html').write_text(report,encoding='utf-8')
    if core.active_strategy()['fingerprint']!=fingerprint:raise ValueError('运行中启用版本发生变化，请重新研究')
    print('REPORT '+str(folder),flush=True)
    print(table[['name','cagr','max_drawdown','calmar','both_improved']].to_string(index=False),flush=True)
    return folder,metadata


if __name__=='__main__':
    argparse.ArgumentParser(description='研究当前本机SMH/SOXL策略的跌破/突破现金规则，不启用、不下单').parse_args()
    run()
