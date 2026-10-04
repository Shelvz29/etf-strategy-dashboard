"""Additional observation factors; never write strategy signals or targets."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import io
import math
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import streamlit as st

import core
from macro_sources import request

OFR_PAGE='https://www.financialresearch.gov/financial-stress-index/'
OFR_CSV=OFR_PAGE+'data/fsi.csv'
FACTSET='https://insight.factset.com/topic/earnings'
SYMBOLS=('RSP','SPY','SMH','XSD','NVDA','AVGO','TSM','ASML','AMD')
LEADERS=SYMBOLS[4:]


def fetch_prices(symbol,at):
    cutoff=core.market_clock(at.to_pydatetime())['expected_date']
    end=pd.Timestamp(cutoff,tz='UTC')+pd.Timedelta(days=1)
    payload=core.request_json(symbol,dict(period1=int((end-pd.Timedelta(days=550)).timestamp()),
        period2=int(end.timestamp()),interval='1d',events='div,splits',includeAdjustedClose='true'))
    result=payload['chart']['result'][0]
    index=pd.to_datetime(result['timestamp'],unit='s',utc=True).tz_convert('America/New_York').tz_localize(None).normalize()
    prices=pd.Series(result['indicators']['adjclose'][0]['adjclose'],index=index).loc[:cutoff]
    expected=core.calendar(pd.Timestamp(cutoff).year).sessions_in_range(prices.index[0],cutoff)
    if len(prices)<220 or not prices.index.equals(expected) or not np.isfinite(prices).all() or prices.le(0).any():
        raise ValueError('观察行情缺少完整交易日或调整价格')
    return {'observations':[{'date':str(d.date()),'price':float(v)} for d,v in prices.items()],
        'source':f'https://finance.yahoo.com/quote/{symbol}/history/'}


def fetch_ofr(at):
    frame=pd.read_csv(io.StringIO(request(OFR_CSV,read_timeout=25).text))
    frame=frame.rename(columns={'Date':'date','Credit':'credit','Funding':'funding','OFR FSI':'fsi'})
    frame=frame[['date','credit','funding','fsi']].tail(500).sort_values('date')
    dates=pd.to_datetime(frame.date)
    today=at.tz_convert('America/New_York').tz_localize(None).normalize()
    if len(frame)<40 or dates.duplicated().any() or (dates>today).any() or not np.isfinite(frame[['credit','funding','fsi']]).all().all():
        raise ValueError('OFR压力数据不完整或日期无效')
    return {'observations':frame.to_dict('records'),'source':OFR_PAGE}


def refresh(force=False,at=None):
    at=pd.Timestamp(at or core.now_utc()).tz_convert('UTC');cache=core.get('factor_sources',{});jobs={}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for name in (*SYMBOLS,'OFR'):
            old=cache.get(name,{});stamp=old.get('last_attempt') or old.get('fetched')
            if stamp and (at-pd.Timestamp(stamp)).total_seconds()<(60 if force else 1800):continue
            jobs[pool.submit(fetch_ofr,at) if name=='OFR' else pool.submit(fetch_prices,name,at)]=name
        for job in as_completed(jobs):
            name=jobs[job];old=cache.get(name,{})
            try:
                record=job.result()
                if old.get('observations') and record['observations'][-1]['date']<old['observations'][-1]['date']:
                    raise ValueError('观察来源日期倒退')
                cache[name]={**record,'fetched':at.isoformat(),'last_attempt':at.isoformat(),'last_error':None}
            except Exception as exc:
                cache[name]={**old,'last_attempt':at.isoformat(),'last_error':f'{name}更新失败：{type(exc).__name__}'}
    core.put('factor_sources',cache)
    return cache


def save_manual(kind,values,date,source,scope,at=None):
    at=pd.Timestamp(at or core.now_utc()).tz_convert('UTC')
    stamp=pd.Timestamp(date);today=at.tz_convert('America/New_York').tz_localize(None).normalize()
    if stamp.tzinfo is not None or stamp!=stamp.normalize() or stamp>today:raise ValueError('数据日期不能晚于今天（美东）')
    parsed=urlparse(source.strip())
    if parsed.scheme not in ('http','https') or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError('请填写不含凭据的HTTP或HTTPS来源网址')
    if not scope.strip():raise ValueError('请填写数据覆盖范围／预测期间')
    bounds={'valuation':{'pe':(1,200)},'earnings':{'revision1':(-100,100),'revision3':(-100,100)}}
    if kind not in bounds or set(values)!=set(bounds[kind]):raise ValueError('录入字段不匹配')
    clean={}
    for key,(low,high) in bounds[kind].items():
        value=float(values[key])
        if not math.isfinite(value) or not low<=value<=high:raise ValueError('录入值超出合理范围')
        clean[key]=value
    core.put('factor_manual_'+kind,{'values':clean,'date':str(stamp.date()),'source':source.strip(),
        'scope':scope.strip(),'saved':at.isoformat()})


def assess(cache,manual,cutoff,treasury=None,at=None):
    at=pd.Timestamp(at or core.now_utc()).tz_convert('UTC');cutoff=pd.Timestamp(cutoff)
    rows=[]
    def add(name,level,value,rule,impact,date,source,limitations):
        rows.append(dict(name=name,level=level,value=value,rule=rule,impact=impact,date=date,
            source=source,limitations=limitations))
    def prices(symbol):
        record=cache.get(symbol,{})
        if not record.get('fetched') or (at-pd.Timestamp(record['fetched'])).total_seconds()>3*86400:raise ValueError('缓存过期或未获取')
        data=pd.DataFrame(record['observations']);index=pd.to_datetime(data.date)
        series=pd.Series(data.price.to_numpy(float),index=index).loc[:cutoff]
        if len(series)<200 or series.index[-1]!=cutoff or not np.isfinite(series).all() or series.le(0).any():raise ValueError('确认日行情不足')
        expected=core.calendar(cutoff.year).sessions_in_range(series.index[0],cutoff)
        if not series.index.equals(expected):raise ValueError('观察行情缺少交易日')
        return series
    def manual_record(kind):
        r=manual.get(kind,{})
        if not r or not 0<=(cutoff-pd.Timestamp(r['date'])).days<=35:raise ValueError('未录入、超过35天或晚于确认收盘')
        return r
    scope='';source=FACTSET;date='—'
    try:
        r=manual_record('valuation');pe=r['values']['pe'];scope=r['scope'];date=r['date'];source=r['source']
        # Treasury is the original panel's conservatively available value.
        yield10=(treasury or {}).get('yield10');spread=100/pe-yield10 if yield10 is not None else None
        level=2 if pe>=25 else 1 if pe>=22 else 0
        value=f'前瞻P/E {pe:.1f}倍'+(f'；盈利收益率−国债 {spread:+.2f}个百分点' if spread is not None else '；国债比较待核对')
    except (ValueError,KeyError,TypeError):level=None;value='等待前瞻P/E数据'
    add('估值风险',level,value,'前瞻P/E≥22倍关注，≥25倍升高；盈利收益率与10年国债差仅作参考',
        '高估值会放大利率上升或盈利失望造成的估值压缩，SOXL杠杆会放大价格影响。',date,source,
        '估值昂贵不等于即将下跌；不同指数不能混用。'+('覆盖：'+scope if scope else '需要填写指数范围和报告日期。'))
    try:
        rsp=prices('RSP');spy=prices('SPY');ratio=rsp/spy;rel=(ratio.iloc[-1]/ratio.iloc[-64]-1)*100
        below=bool(rsp.iloc[-1]<rsp.rolling(200).mean().iloc[-1]);level=int(rel<=-3)+int(below)
        value=f'RSP/SPY 63日 {rel:+.2f}%；RSP低于MA200：'+('是' if below else '否');date=str(cutoff.date())
    except (ValueError,KeyError,TypeError,IndexError):level=None;value='等待完整RSP/SPY日线';date='—'
    add('市场宽度',level,value,'等权／市值加权63日相对跌≥3%，或等权指数跌破MA200；一项关注，两项升高',
        '大盘上涨但普通成分股走弱，表明上涨参与面缩窄，半导体反弹可能更脆弱。',date,
        'https://www.invesco.com/us/en/financial-products/etfs/product-detail?productId=ETF-RSP',
        'ETF相对收益是参与度代理，不是全市场上涨家数或成分股均线占比。')
    scope='';source=FACTSET;date='—'
    try:
        r=manual_record('earnings');a=r['values']['revision1'];b=r['values']['revision3'];scope=r['scope'];source=r['source'];date=r['date']
        level=int(a<=-2)+int(b<=-5);value=f'盈利预测修订：1个月 {a:+.2f}%／3个月 {b:+.2f}%'
    except (ValueError,KeyError,TypeError):level=None;value='等待同一预测期间的EPS修订数据'
    add('盈利预期恶化',level,value,'同一预测期间、同一覆盖范围：1个月EPS下修≥2%，3个月下修≥5%；一项关注，两项升高',
        '盈利预期下修削弱高估值支撑；半导体需求、毛利率预期下降可能传导到SMH和SOXL。',date,source,
        '不能以历史已实现EPS代替预测，也不能比较滚动窗口变化不同的预测期间。'+('覆盖：'+scope if scope else '需从报告核对后录入。'))
    for field,name,threshold,impact in [('credit','信用风险',.5,'信用收缩会抬高企业融资成本，并削弱风险资产需求。'),
            ('funding','流动性风险',.3,'融资压力上升可能触发被动减仓和去杠杆，放大SOXL波动。')]:
        try:
            r=cache['OFR']
            if (at-pd.Timestamp(r['fetched'])).total_seconds()>3*86400:raise ValueError('缓存过期')
            frame=pd.DataFrame(r['observations']);frame.index=pd.to_datetime(frame.pop('date'))
            # OFR publishes two business days behind; use NYSE sessions conservatively.
            index=core.calendar(cutoff.year).sessions_in_range(frame.index[0],cutoff)
            from macro_ui import known
            aligned=known(frame,index,2);series=aligned[field];v=float(series.iloc[-1]);delta=float(series.iloc[-1]-series.iloc[-21])
            date=str(aligned.observed_date.iloc[-1].date())
            if not math.isfinite(v+delta) or (cutoff-pd.Timestamp(date)).days>10:raise ValueError('压力数据不足或过期')
            level=int(v>0)+int(delta>=threshold);value=f'OFR分项 {v:+.3f}；20交易日变化 {delta:+.3f}'
        except (ValueError,KeyError,TypeError,IndexError,AttributeError):level=None;value='等待OFR官方压力数据';date='—'
        add(name,level,value,f'OFR {field}贡献>0，或20交易日升≥{threshold:.1f}；一项关注，两项升高',impact,date,OFR_PAGE,
            'OFR系统性压力贡献，不是信用利差本身、资金总量或本券商流动性；官方约滞后2个工作日，数据可能修订。')
    try:
        smh=prices('SMH');xsd=prices('XSD');ratio=smh/xsd;gap=(ratio.iloc[-1]/ratio.iloc[-64]-1)*100
        changes=[(prices(s).iloc[-1]/prices(s).iloc[-21]-1)*100 for s in LEADERS]
        leaders=float(np.mean(changes));crowded=gap>=8;weak=leaders<=-8
        level=2 if crowded and weak else 1 if crowded else 0
        value=f'SMH/XSD 63日 {gap:+.2f}%；固定龙头篮子20日 {leaders:+.2f}%';date=str(cutoff.date())
    except (ValueError,KeyError,TypeError,IndexError):level=None;value='等待SMH/XSD与全部龙头日线';date='—'
    add('龙头集中风险',level,value,'SMH/XSD 63日相对涨≥8%关注；同时龙头等权篮子20日跌≥8%则升高',
        '涨势集中于少数龙头时，其转弱可能牵动半导体指数，SOXL承受更大净值冲击。',date,
        'https://www.vaneck.com/us/en/investments/semiconductor-etf-smh/',
        '这是龙头拥挤／转弱代理，不是基金前十持仓集中度；固定篮子NVDA、AVGO、TSM、ASML、AMD，非历史动态成员。')
    return rows


def render(cutoff,treasury=None):
    from macro_ui import card, CARD_STYLE
    st.subheader('扩展因素与影响评价')
    st.caption('六类因素独立观察：绿未触发、黄关注、橙升高、灰待核对。阈值是待检验的观察条件，不参与上方四组计票，也不调整策略仓位。')
    cache=core.get('factor_sources',{});manual={k:core.get('factor_manual_'+k,{}) for k in ('valuation','earnings')}
    rows=assess(cache,manual,cutoff,treasury)
    html=[]
    dependencies=[(),('RSP','SPY'),(),('OFR',),('OFR',),('SMH','XSD',*LEADERS)]
    for i,row in enumerate(rows):
        level=row['level'];tone='unknown' if level is None else ('clear','watch','triggered')[level]
        badge='待核对' if level is None else ('未触发','关注','风险升高')[level]
        meta='风险使用日期：'+row['date']
        kind={0:'valuation',2:'earnings'}.get(i)
        if kind and manual[kind]:meta+=' · 覆盖：'+manual[kind]['scope']
        if any(cache.get(name,{}).get('last_error') for name in dependencies[i]):meta+=' · 更新失败，沿用旧缓存'
        html.append(card(row['name'],row['value'],badge,tone,row['impact'],meta))
    st.markdown(CARD_STYLE+'<div class="macro-grid macro-detail">'+''.join(html)+'</div>',unsafe_allow_html=True)
    available=sum(r['level'] is not None for r in rows);triggered=sum(r['level'] is not None and r['level']>0 for r in rows)
    st.caption(f'可评价 {available}/6类，其中关注或升高 {triggered}类、待核对 {6-available}类。因素存在相关性，不相加为新的仓位评分。')
    with st.expander('扩展因素的计算条件、来源与实际限制'):
        for r in rows:
            st.markdown(f"**{r['name']}**：{r['rule']}");st.write(r['limitations'])
            st.link_button('查看来源 · '+r['name'],r['source'])
        for name,r in cache.items():
            st.caption(f"{name} · 最近获取（北京）：{core.display_time(r.get('fetched'))} · 最新观测：{r.get('observations',[{}])[-1].get('date','—')}")
            if r.get('last_error'):st.warning(r['last_error']+'；保留旧缓存，过期后待核对。')
        st.caption('行情为含分红调整价格，按确认收盘截断；获取时间不等于数据日期。两类手工数据超过35天或晚于确认收盘时不参与评价。此模块没有回测效果或预测准确率结论。')
    with st.expander('录入或更新估值、盈利预期数据'):
        st.caption('免费接口暂无可核实的一致前瞻数据；请从FactSet等报告核对，不填就保持灰色。更新行情会重算评价，但不会自动改写手工数据。')
        for kind,label in [('valuation','估值'),('earnings','盈利预期')]:
            r=manual[kind];v=r.get('values',{})
            with st.form('factor_manual_'+kind):
                st.write(label)
                date=st.date_input('报告／数据日期（美东）',value=pd.Timestamp(r['date']).date() if r else None,key=kind+'_date')
                scope=st.text_input('覆盖指数／行业及预测期间',value=r.get('scope',''),key=kind+'_scope')
                source=st.text_input('来源网址',value=r.get('source',FACTSET),key=kind+'_source')
                if kind=='valuation':values={'pe':st.number_input('前瞻12个月P/E（倍）',min_value=1.,max_value=200.,value=v.get('pe'),key='factor_pe')}
                else:values={key:st.number_input(text,min_value=-100.,max_value=100.,value=v.get(key),key='factor_'+key)
                    for key,text in [('revision1','同一预测期间EPS近1个月修订（%，下修填负数）'),('revision3','同一预测期间EPS近3个月修订（%）')]}
                if st.form_submit_button('保存'+label+'观察数据'):
                    try:
                        if date is None or any(x is None for x in values.values()):raise ValueError('请填写日期和全部数值')
                        save_manual(kind,values,date,source,scope);st.rerun()
                    except (ValueError,TypeError) as exc:st.error(str(exc))
