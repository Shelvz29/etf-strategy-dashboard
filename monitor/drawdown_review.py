"""Read-only review of independent underwater episodes for a local strategy.

Generated strategy results stay in ignored runtime; strategy source is never exported.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from PIL import Image, ImageDraw, ImageFont

import core
import performance


def episodes(equity, initial=100000.0):
    """Non-overlapping ATH-to-recovery episodes, including entry fees/open tails.

    Use the latest equal peak before a fall; the first equal recovery closes it.
    Include pre-entry capital so entry fees cannot disappear from drawdown.
    """
    if (equity.empty or not isinstance(equity.index, pd.DatetimeIndex)
            or equity.index.has_duplicates or not equity.index.is_monotonic_increasing
            or not np.isfinite(equity.to_numpy()).all() or (equity <= 0).any()
            or not np.isfinite(initial) or initial <= 0):
        raise ValueError("净值必须为按日期递增的正数，初始资金必须为正数")
    peak, peak_date = float(initial), equity.index[0] - pd.Timedelta(seconds=1)
    active, rows = None, []
    for date, value in equity.items():
        if value >= peak:
            if active is not None:
                active["recovery"] = date
                rows.append(active)
                active = None
            peak, peak_date = float(value), date
        else:
            loss = float(value / peak - 1)
            if active is None:
                active = dict(peak=peak_date, start=date, trough=date,
                              drawdown=loss, peak_equity=peak, recovery=None)
            elif loss < active["drawdown"]:
                active.update(trough=date, drawdown=loss)
    if active is not None:
        rows.append(active)
    for row in rows:
        row["peak_to_trough_sessions"] = int(((equity.index > row["peak"]) &
                                                (equity.index <= row["trough"])).sum())
        row["underwater_sessions"] = int(((equity.index > row["peak"]) &
            (equity.index < row["recovery"] if row["recovery"] is not None else True)).sum())
    return sorted(rows, key=lambda row: row["drawdown"])


def context_index(index, episode, padding=20):
    left = max(0, index.searchsorted(episode["peak"]) - padding)
    right = min(len(index), index.searchsorted(episode["recovery"] or index[-1], side="right") + padding)
    return index[left:right]


def macd(close):
    dif = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    dea = dif.ewm(span=9, adjust=False).mean()
    return pd.DataFrame({"DIF": dif, "DEA": dea, "hist": dif - dea,
                         "EMA20": close.ewm(span=20, adjust=False).mean()})


def review_figure(frames, nav, episode, base, rank):
    dates = context_index(nav.index, episode)
    x = dates.strftime("%Y-%m-%d").tolist()
    fig = make_subplots(rows=5, cols=1, shared_xaxes=True, vertical_spacing=.045,
        row_heights=[.27, .27, .15, .2, .11],
        subplot_titles=[f"{base} 日K · 信号价格", "SOXL 日K · 交易标的价格",
                        f"{base} MACD(12,26,9) · 柱线=DIF−DEA", "策略净值 · 回撤前高点=100", "实际收盘资产仓位"])
    for row, symbol in ((1, base), (2, "SOXL")):
        f = frames[symbol].loc[dates]
        fig.add_trace(go.Candlestick(x=x, open=f.open, high=f.high, low=f.low, close=f.close,
            increasing_line_color="#cf394b", decreasing_line_color="#078571", name=symbol), row=row, col=1)
        ema = frames[symbol].close.ewm(span=20, adjust=False).mean().loc[dates]
        fig.add_trace(go.Scatter(x=x, y=ema, name=f"{symbol} EMA20", line=dict(color="#bd861c", width=1)), row=row, col=1)
    m = macd(frames[base].close).loc[dates]
    fig.add_trace(go.Bar(x=x, y=m['hist'], name="MACD柱线", marker_color=np.where(m['hist'] >= 0, "#bd861c", "#2a719c")), row=3, col=1)
    for name, color in (("DIF", "#5860b0"), ("DEA", "#bd861c")):
        fig.add_trace(go.Scatter(x=x, y=m[name], name=name, line_color=color), row=3, col=1)
    fig.add_trace(go.Scatter(x=x, y=nav.equity.loc[dates] / episode["peak_equity"] * 100,
        name="策略净值", line=dict(color="#3659aa", width=2)), row=4, col=1)
    fig.add_hline(y=100, line_dash="dot", row=4, col=1)
    for symbol, color in (("SOXL", "#cf394b"), (base, "#26a092"), ("CASH", "#9da8b5")):
        weight = (1-nav.asset_weight if symbol == "CASH" else nav.asset_weight.where(nav.held == symbol, 0))
        fig.add_trace(go.Scatter(x=x, y=weight.loc[dates]*100, name="现金" if symbol == "CASH" else symbol+"仓位",
            stackgroup="held", mode="lines", line=dict(width=0, color=color)), row=5, col=1)
    markers = (("peak", "净值前高", "#b8840c"), ("trough", "回撤谷底", "#cf394b"), ("recovery", "净值恢复", "#078571"))
    for key, label, color in markers:
        date = episode[key]
        if date is not None:
            value = str(date.date())
            fig.add_vline(x=value, line_color=color, line_dash="dash", line_width=1)
            fig.add_annotation(x=value, y=1.045, yref="paper", xref="x", text=label+" "+value,
                               showarrow=False, font_color=color)
    fig.update_xaxes(type="category", nticks=10, rangeslider_visible=False)
    fig.update_yaxes(title_text="美元", row=1, col=1)
    fig.update_yaxes(title_text="美元", row=2, col=1)
    fig.update_yaxes(title_text="净值", row=4, col=1)
    fig.update_yaxes(title_text="%", range=[0, 100], row=5, col=1)
    fig.update_layout(height=1150, template="plotly_white", hovermode="x unified",
        title=f"第{rank}段 · 最大回撤 {episode['drawdown']:.2%}", margin=dict(t=115), showlegend=True)
    return fig


def review_png(frames, nav, episode, base, rank, path):
    """Portable PNG rendering without a browser/Chrome export dependency."""
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    font = ImageFont.truetype(str(font_path), 21) if font_path.exists() else ImageFont.load_default(size=21)
    small = ImageFont.truetype(str(font_path), 17) if font_path.exists() else ImageFont.load_default(size=17)
    dates = context_index(nav.index, episode)
    n = len(dates)
    image = Image.new("RGB", (1920, 1220), "#f4f7fb")
    d = ImageDraw.Draw(image)
    d.text((42, 20), f"第{rank}段独立回撤  |  {episode['drawdown']:.2%}  |  {base} / SOXL 日K", fill="#162d46", font=font)
    recover = str(episode['recovery'].date()) if episode['recovery'] is not None else "截至末日未恢复"
    d.text((42, 58), f"净值前高 {episode['peak'].date()}  →  谷底 {episode['trough'].date()}  →  恢复 {recover}", fill="#435970", font=small)
    d.text((42, 88), "日期为策略账户节点，不是ETF价格顶底；红涨绿跌；信号收盘确认、次日开盘执行。", fill="#435970", font=small)
    left, right = 110, 1880
    xx = lambda i: left + (i+.5)*(right-left)/n
    panels = [(150, 410), (455, 715), (760, 890), (935, 1075), (1120, 1170)]
    def panel(top, bottom, title, low, high):
        d.rectangle((left, top, right, bottom), fill="white")
        d.text((left, top-30), title, fill="#162d46", font=small)
        if high == low: high = low + 1
        pad = (high-low)*.07
        low, high = low-pad, high+pad
        yy = lambda v: bottom - (v-low)/(high-low)*(bottom-top)
        for value in np.linspace(low, high, 5):
            y = yy(value)
            d.line((left, y, right, y), fill="#e3e9f0")
            d.text((12, y-10), f"{value:.1f}", fill="#63778b", font=small)
        for i in np.unique(np.linspace(0,n-1,7).astype(int)):
            label=str(dates[i].date())
            label_width=d.textlength(label,font=small)
            label_x=min(right-label_width,max(left,xx(i)-label_width/2))
            d.text((label_x,bottom+4),label,fill="#63778b",font=small)
        return yy
    for row, symbol in enumerate((base, "SOXL")):
        f = frames[symbol].loc[dates]
        top,bottom = panels[row]
        yy = panel(top,bottom,symbol+" 日K / EMA20 · 美元",float(f.low.min()),float(f.high.max()))
        width = max(1, min(10,(right-left)/n*.6))
        for i, candle in enumerate(f.itertuples()):
            color = "#cf394b" if candle.close >= candle.open else "#078571"
            d.line((xx(i),yy(candle.low),xx(i),yy(candle.high)),fill=color,width=1)
            y1,y2 = sorted((yy(candle.open),yy(candle.close)))
            d.rectangle((xx(i)-width/2,y1,xx(i)+width/2,max(y1+1,y2)),fill=color)
        ema = frames[symbol].close.ewm(span=20,adjust=False).mean().loc[dates]
        d.line([(xx(i),yy(v)) for i,v in enumerate(ema)],fill="#bd861c",width=2)
    m = macd(frames[base].close).loc[dates]
    yy = panel(*panels[2],f"{base} MACD(12,26,9) · DIF紫 / DEA金 / 柱线=DIF−DEA",float(m[['DIF','DEA','hist']].min().min()),float(m[['DIF','DEA','hist']].max().max()))
    for i,v in enumerate(m['hist']):
        d.line((xx(i),yy(0),xx(i),yy(v)),fill="#bd861c" if v>=0 else "#2a719c",width=max(1,int((right-left)/n*.5)))
    for name,color in (("DIF","#5860b0"),("DEA","#bd861c")):
        d.line([(xx(i),yy(v)) for i,v in enumerate(m[name])],fill=color,width=2)
    values = nav.equity.loc[dates]/episode['peak_equity']*100
    yy = panel(*panels[3],"策略净值 · 本段回撤前高=100",float(values.min()),max(100,float(values.max())))
    d.line((left,yy(100),right,yy(100)),fill="#a9b7c8",width=1)
    d.line([(xx(i),yy(v)) for i,v in enumerate(values)],fill="#3659aa",width=3)
    top,bottom = panels[4]
    d.text((left,top-30),"实际收盘仓位 · 红SOXL / 绿"+base+" / 灰现金（颜色比例表示仓位）",fill="#162d46",font=small)
    held=nav.loc[dates]
    for i,row in enumerate(held.itertuples()):
        x1=left+i*(right-left)/n;x2=left+(i+1)*(right-left)/n
        d.rectangle((x1,top,x2,bottom),fill="#b9c3cf")
        w=float(row.asset_weight)
        if w>0: d.rectangle((x1,bottom-w*(bottom-top),x2,bottom),fill="#cf394b" if row.held=="SOXL" else "#26a092")
    for key,color in (("peak","#b8840c"),("trough","#cf394b"),("recovery","#078571")):
        date=episode[key]
        if date is not None and date in dates:
            x=xx(dates.get_loc(date))
            for top,bottom in panels:
                for y in range(top,bottom,10):d.line((x,y,x,min(y+5,bottom)),fill=color,width=2)
    d.text((42,1190),f"图示交易日 {dates[0].date()}—{dates[-1].date()}；OHLC已拆股调整、未作分红复权；策略净值采用分红调整价格。",fill="#435970",font=small)
    image.save(path)


def generate(profile, count=5, cost_bps=10.0):
    snap,bundle=performance.confirmed_inputs()
    cutoff=snap['last']['date']
    frames,signals,_,_=performance.datasets(bundle,cutoff,[],profile=profile)
    if "weight_QQQ" in signals:
        raise ValueError("当前回撤K线研究面向半导体单资产策略")
    nav,trades=performance.engine.simulate(frames,signals,start="2017-01-03",end=cutoff,
        initial=100000,cost_bps=cost_bps,execution="next_open",daily_rebalance=False)
    rows=episodes(nav.equity)[:count]
    metrics=performance.engine.metrics(nav,trades)
    if rows and not np.isclose(rows[0]['drawdown'],metrics['max_drawdown_close'],atol=1e-12):
        raise AssertionError("独立回撤排名与执行引擎最大回撤不一致")
    base=core.base_symbol(profile)
    folder=core.RUNTIME/"drawdown_reviews"/f"{profile['id']}-v{profile['revision']}-{cutoff}"
    folder.mkdir(parents=True,exist_ok=True)
    serial=[{k:str(v.date()) if isinstance(v,pd.Timestamp) else v for k,v in row.items()} for row in rows]
    pd.DataFrame(serial).to_csv(folder/"回撤排名.csv",index=False,encoding="utf-8-sig")
    nav.to_csv(folder/"净值与实际仓位.csv",encoding="utf-8-sig")
    trades.to_csv(folder/"回测调仓.csv",index=False,encoding="utf-8-sig")
    metadata=dict(name=profile['name'],revision=profile['revision'],fingerprint=profile['fingerprint'],
                  cutoff=cutoff,fetched=snap['fetched'],source=snap['source'],cost_bps=cost_bps,
                  metrics=metrics,episodes=serial)
    (folder/"结果.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
    headers=("排名","最大回撤","净值前高","回撤谷底","恢复前高","高点至谷底交易日")
    table="<table><thead><tr>"+"".join(f"<th>{v}</th>" for v in headers)+"</tr></thead><tbody>"
    for i,r in enumerate(serial,1):
        values=(i,f"{r['drawdown']:.2%}",r['peak'],r['trough'],r['recovery'] or "未恢复",r['peak_to_trough_sessions'])
        table+="<tr>"+"".join(f"<td>{v}</td>" for v in values)+"</tr>"
    table+="</tbody></table>"
    charts=[]
    for i,row in enumerate(rows,1):
        review_png(frames,nav,row,base,i,folder/f"第{i}段回撤日K.png")
        fig=review_figure(frames,nav,row,base,i)
        charts.append(fig.to_html(full_html=False,include_plotlyjs=True if i==1 else False,
                                 config={"responsive":True,"displaylogo":False}))
    title=f"{profile['name']} · v{profile['revision']} · 最大独立回撤与K线"
    note=(f"2017-01-03至{cutoff}；收盘信号、次日开盘成交；单边交易成本{cost_bps/100:.2f}%；"
          f"年化{metrics['cagr']:.2%}，日终最大回撤{metrics['max_drawdown_close']:.2%}。"
          "按净值历史高点至重新达到前高划分独立事件，每段只取最深谷底；未恢复的事件也纳入排名。"
          "K线前后各增加20个交易日作背景。MACD与EMA20先在全历史计算，再截取；图中MACD为观察参考。"
          "日K已拆股调整、未作分红复权；账户净值采用分红调整成交价。日期标记属于策略净值，"
          "不代表ETF价格顶底。现金收益为0；不含汇率、税、币安产品折溢价及额外费用；日终回撤不等于盘中回撤。")
    document=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>body{{max-width:1500px;margin:30px auto;font:16px system-ui;color:#20344b;padding:0 24px}}p{{line-height:1.8}}table{{border-collapse:collapse;width:100%;margin:20px 0}}td,th{{padding:12px;border-bottom:1px solid #ddd;text-align:left}}th{{background:#eef3f9}}</style>
<h1>{html.escape(title)}</h1><p>{html.escape(note)}</p>{table}{''.join(charts)}</html>'''
    (folder/"回撤与K线.html").write_text(document,encoding="utf-8")
    return folder,metadata


if __name__=="__main__":
    parser=argparse.ArgumentParser(description="只读生成本机策略的最大独立回撤和K线，输出保存在私有runtime")
    parser.add_argument("--strategy-id",help="默认为当前启用策略")
    parser.add_argument("--revision",type=int)
    parser.add_argument("--count",type=int,default=5)
    args=parser.parse_args()
    if not 1<=args.count<=20:parser.error("count须在1至20之间")
    profile=core.strategy_version(args.strategy_id,args.revision) if args.strategy_id else core.active_strategy()
    folder,metadata=generate(profile,args.count)
    print(json.dumps(dict(folder=str(folder),metrics=metadata['metrics'],episodes=metadata['episodes']),ensure_ascii=False,indent=2))
