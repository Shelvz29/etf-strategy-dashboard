"""Display-only macro risk assessment. It never generates trading targets."""
import math
from html import escape
import numpy as np
import pandas as pd
import streamlit as st

import core
from macro_sources import SOURCES, save_release_date, CALENDAR

GROUP_NAMES={'rates':'利率风险','oil':'油价风险','policy':'货币政策风险','cpi':'通胀风险'}

CARD_STYLE='''<style>
.macro-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin:12px 0 18px}
.macro-card{border:1px solid var(--edge);border-left:6px solid var(--ink);border-radius:12px;padding:18px 20px;background:var(--bg);color:#20344d;min-width:0}
.macro-card.clear{--bg:#edf8f1;--ink:#23764c;--edge:#b5d9c3}
.macro-card.watch{--bg:#fff9e7;--ink:#8a6510;--edge:#e7d28e}
.macro-card.triggered{--bg:#fff0df;--ink:#a75312;--edge:#edc092}
.macro-card.high{--bg:#fff0ee;--ink:#b2352b;--edge:#e7aaa4}
.macro-card.severe{--bg:#fae6e9;--ink:#8f2338;--edge:#d79ca7}
.macro-card.unknown{--bg:#f0f3f7;--ink:#59687b;--edge:#c4cdd9}
.macro-top{display:flex;gap:10px;justify-content:space-between;align-items:start;font-weight:600}
.macro-badge{color:var(--ink);border:1px solid var(--edge);border-radius:5px;padding:3px 8px;font-size:13px;white-space:nowrap}
.macro-value{font-size:27px;line-height:1.35;font-weight:700;margin:12px 0 8px;overflow-wrap:anywhere}
.macro-meta{font-size:13px;color:#526275;margin-top:7px;line-height:1.55;overflow-wrap:anywhere}
.macro-level{margin:12px 0 14px}.macro-level .macro-value{font-size:24px}
.macro-detail .macro-value{font-size:17px}.macro-detail .macro-meta{font-size:13px}
.macro-legend{font-size:13px;color:#526275;margin:8px 0 14px;line-height:1.8}
@media(min-width:1150px){.macro-grid{grid-template-columns:repeat(4,minmax(0,1fr))}.macro-detail{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:520px){.macro-grid{grid-template-columns:1fr}}
</style>'''


def card(title,value,badge,tone,meta='',extra=''):
    return (f'<div class="macro-card {tone}"><div class="macro-top"><span>{escape(title)}</span>'
            f'<span class="macro-badge">{escape(badge)}</span></div><div class="macro-value">{escape(value)}</div>'
            f'<div class="macro-meta">{escape(meta)}</div><div class="macro-meta">{escape(extra)}</div></div>')


def risk_cards(panel,cache):
    cards=[]
    for name in SOURCES:
        value=panel['latest'].get(name,{})
        display={'rates':f"{value.get('yield10',0):.2f}%",'oil':f"${value.get('wti',0):.2f}",
            'policy':f"{value.get('target_upper',0):.2f}%",'cpi':f"{value.get('headline',0):.1f}% / {value.get('core',0):.1f}%"}[name] if value else '待获取'
        group=panel['groups'][name];tone='unknown' if group is None else 'triggered' if group else 'clear'
        badge='待核对' if group is None else '已触发' if group else '未触发'
        label={'rates':'10年名义国债收益率','oil':'WTI现货价格','policy':'联储目标区间上限','cpi':'总体／核心CPI同比'}[name]
        date=('统计月：' if name=='cpi' else '观测日：')+value.get('month' if name=='cpi' else 'date','—')
        if cache.get(name,{}).get('last_error'):date+=' · 更新失败，旧缓存'
        cards.append(card(GROUP_NAMES[name],display,badge,tone,label,date))
    low,high=panel['lower'],panel['upper'];score=str(low) if low==high else f'{low}—{high}'
    tones=['clear','watch','triggered','high','severe'];levels=['较低','需要关注','风险升高','高风险','多组高风险']
    if low!=high and low<3:tone='unknown';level='待核对'
    else:tone=tones[low];level=levels[low]+(' · 部分待核对' if low!=high else '')
    if low>=3:message='满足“三组风险”条件。此处仅展示研究条件，当前策略目标不因此调整。'
    elif high>=3:message='部分指标待核对，无法确认是否满足“三组风险”条件。'
    else:message='未满足“三组风险”条件。'
    overall=card('宏观风险等级',f'{level} · {score}/4组','按触发组数划分',tone,message,f"判定截至 {panel['as_of']} 已确认收盘")
    return '<div class="macro-grid">'+''.join(cards)+'</div><div class="macro-level">'+overall+'</div>'


def detail_cards(rows):
    cards=[]
    for row in rows:
        tone={'触发':'triggered','未触发':'clear'}.get(row['触发'],'unknown')
        cards.append(card(row['指标'],row['风险计算值'],row['触发'],tone,row['触发条件'],
            row['组别']+' · 风险使用日期：'+row['风险使用日期']))
    return '<div class="macro-grid macro-detail">'+''.join(cards)+'</div>'


def either(*flags):
    return True if any(x is True for x in flags) else None if any(x is None for x in flags) else False


def known(frame,index,lag):
    frame=frame.copy();frame['observed_date']=frame.index
    positions=index.searchsorted(frame.index,side='right')+lag-1;keep=positions<len(index)
    frame=frame.iloc[np.flatnonzero(keep)];frame.index=index[positions[keep]]
    return frame.groupby(level=0).last().reindex(index).ffill()


def qqq_prices(bundle,cutoff):
    result=bundle['QQQ']['chart']['result'][0]
    index=pd.to_datetime(result['timestamp'],unit='s',utc=True).tz_convert('America/New_York').tz_localize(None).normalize()
    series=pd.Series(result['indicators']['quote'][0]['close'],index=index).loc[:cutoff].tail(180)
    if series.index.has_duplicates or not series.index.is_monotonic_increasing or len(series)<80 or not np.isfinite(series).all() or series.le(0).any():
        raise ValueError('QQQ确认日线不足或含缺失值')
    expected=core.calendar(pd.Timestamp(cutoff).year).sessions_in_range(series.index[0],cutoff)
    if not series.index.equals(expected):raise ValueError('QQQ确认日线不完整')
    return series


def build_panel(cache,qqq,at=None):
    at=pd.Timestamp(at or core.now_utc()).tz_convert('UTC');cutoff=qqq.index[-1]
    rows=[];groups={};sources=[];latest={};values={};dates={};notes=[]
    valid={};aligned={}
    for name,(label,url) in SOURCES.items():
        record=cache.get(name,{})
        status='未获取';last=record.get('observations',[])
        if last:
            key='month' if name=='cpi' else 'date';latest[name]=last[-1]
            status='更新失败，保留旧值' if record.get('last_error') else '已获取'
            fresh=bool(record.get('fetched') and (at-pd.Timestamp(record['fetched'])).total_seconds()<=(7 if name=='cpi' else 3)*86400)
            if not fresh:status='缓存过期'
            valid[name]=fresh
            if name!='cpi':
                frame=pd.DataFrame(last);frame.index=pd.to_datetime(frame.pop('date'))
                a=known(frame,qqq.index,3 if name=='oil' else 2);aligned[name]=a
                date=a.observed_date.iloc[-1];dates[name]=str(date.date()) if pd.notna(date) else '不足'
                valid[name]=fresh and pd.notna(date) and (cutoff-date).days<=15
                if not valid[name] and fresh:status='风险口径数据不足或过期'
            sources.append({'来源':label,'最近观测':last[-1][key],'最近获取（北京）':core.display_time(record.get('fetched')),
                '状态':status,'官网':url})
        else:
            valid[name]=False
            sources.append({'来源':label,'最近观测':'—','最近获取（北京）':'—',
                '状态':record.get('last_error',{}).get('message','未获取'),'官网':url})
    def add(name,group,text,flag,rule,stamp):
        rows.append({'指标':name,'组别':GROUP_NAMES.get(group,'单独参考，不计票'),'风险计算值':text,
            '触发': '待核对／数据不足' if flag is None else '触发' if flag else '未触发','触发条件':rule,'风险使用日期':stamp})
    def number(value,suffix='',signed=False):
        return (f'{value:+.2f}' if signed else f'{value:.2f}')+suffix if pd.notna(value) and math.isfinite(value) else '不足'
    def flag(condition,group,*numbers):
        return bool(condition) if valid.get(group) and all(pd.notna(x) and math.isfinite(x) for x in numbers) else None
    t=aligned.get('rates');p=aligned.get('policy');o=aligned.get('oil')
    n20=real20=curve=p63=p20=or20=or63=np.nan
    rates1=rates2=policy1=policy2=oil1=oil2=curve_flag=None
    bad=bool(qqq.iloc[-1]<qqq.rolling(50).mean().iloc[-1])
    if t is not None:
        n20=(t.yield10-t.yield10.shift(20)).iloc[-1];real20=(t.real10-t.real10.shift(20)).iloc[-1]
        curve=(t.yield10-t.yield2).iloc[-1];ma=t.yield10.rolling(60).mean().iloc[-1]
        rates1=flag(n20>=.5 and t.yield10.iloc[-1]>ma,'rates',n20,ma)
        rates2=flag(real20>=.4,'rates',real20)
        values['rates']=dict(t.iloc[-1][['yield2','yield10','real10']])
    if p is not None:
        p63=(p.target_upper-p.target_upper.shift(63)).iloc[-1];p20=(p.target_upper-p.target_upper.shift(20)).iloc[-1]
        policy1=flag(p63>=.5,'policy',p63);policy2=flag(p20<=-.5 and bad,'policy',p20)
        values['policy']={'target_upper':p.target_upper.iloc[-1]}
    if o is not None:
        v=o.wti
        or20=(v/v.shift(20)-1).where(v.gt(0)&v.shift(20).gt(0)).iloc[-1]
        or63=(v/v.shift(63)-1).where(v.gt(0)&v.shift(63).gt(0)).iloc[-1]
        oil1=flag(or20>=.15 or or63>=.30,'oil',or20,or63) if v.iloc[-1]>0 else False if valid['oil'] else None
        oil2=flag((v.iloc[-1]<=0 or or20<=-.25) and bad,'oil',v.iloc[-1]) if v.iloc[-1]<=0 else flag(or20<=-.25 and bad,'oil',or20)
        values['oil']={'wti':v.iloc[-1]}
    if valid.get('rates') and valid.get('policy') and all(pd.notna(x) for x in (curve,p63)):
        curve_flag=bool(curve<=-.5 and p63>=.5)
    add('名义利率急升','rates',number(n20,'个百分点',True),rates1,'10年名义利率20日升≥0.50个百分点，且高于60日均线',dates.get('rates','—'))
    add('实际利率急升','rates',number(real20,'个百分点',True),rates2,'10年实际利率20日升≥0.40个百分点',dates.get('rates','—'))
    add('倒挂且紧缩','reference',number(curve,'个百分点',True),curve_flag,'10年−2年≤−0.50个百分点，且政策利率63日升≥0.50个百分点',dates.get('rates','—')+'／'+dates.get('policy','—'))
    add('油价快速上涨','oil','20日 '+number(or20*100,'%',True)+'；63日 '+number(or63*100,'%',True),oil1,'正油价20日涨≥15%或63日涨≥30%',dates.get('oil','—'))
    add('油价暴跌且股市走弱','oil','20日 '+number(or20*100,'%',True)+'；QQQ低于MA50：'+('是' if bad else '否'),oil2,'WTI≤0或20日跌≥25%，且QQQ低于50日均线',dates.get('oil','—'))
    add('政策紧缩','policy',number(p63,'个百分点',True),policy1,'联储目标利率上限63日升≥0.50个百分点',dates.get('policy','—'))
    add('紧急降息且股市走弱','policy',number(p20,'个百分点',True),policy2,'目标上限20日降≥0.50个百分点，且QQQ低于50日均线',dates.get('policy','—'))
    heat=jump=None;cpi_date='—';headline=core_yoy=h3=c3=hj=np.nan;release_age=None
    if valid.get('cpi'):
        record=cache['cpi'];c=pd.DataFrame(record['observations']).set_index('month').sort_index()
        release_dates=record.get('release_dates',{})
        # A known release after the confirmed close is visible as an observation,
        # but cannot enter the risk assessment for that earlier close.
        eligible=[m for m in c.index if m in release_dates and pd.Timestamp(release_dates[m])<=cutoff]
        latest_month=c.index[-1];latest_date=release_dates.get(latest_month)
        if latest_date and pd.Timestamp(latest_date)>cutoff:notes.append('最新CPI在确认收盘日之后公布，风险判定沿用此前已公告数据。')
        if not latest_date:notes.append('最新CPI公告日期未核实：显示同比值，但通胀组不计为已确认风险。')
        if latest_date and eligible:
            month=eligible[-1];c=c.loc[:month];cpi_date=release_dates[month]
            if len(c)>=4 and (cutoff-pd.Timestamp(cpi_date)).days<=100:
                headline=float(c.headline.iloc[-1]);core_yoy=float(c.core.iloc[-1])
                h3=headline-float(c.headline.iloc[-4]);c3=core_yoy-float(c.core.iloc[-4]);hj=headline-float(c.headline.iloc[-2])
                release_age=int((qqq.index>=pd.Timestamp(cpi_date)).sum())-1
                heat=bool((headline>=3 and h3>=.3-1e-10) or (core_yoy>=3 and c3>=.2-1e-10))
                jump=bool(hj>=.2-1e-10 and core_yoy>=3 and 0<=release_age<5)
                values['cpi']={'headline':headline,'core':core_yoy,'month':month}
    add('通胀升温','cpi','总体 '+number(headline,'%')+'／核心 '+number(core_yoy,'%')+'；较3次前 '+number(h3,'／',True)+number(c3,'个百分点',True),heat,
        '总体≥3%且比3次前升≥0.30个百分点；或核心≥3%且升≥0.20个百分点',cpi_date)
    add('CPI跳升','cpi',number(hj,'个百分点',True)+'；公告后交易日 '+(str(release_age) if release_age is not None else '未知'),jump,
        '总体同比比前次升≥0.20个百分点、核心≥3%，公告后首5交易日',cpi_date)
    groups={'rates':either(rates1,rates2),'oil':either(oil1,oil2),'policy':either(policy1,policy2),'cpi':either(heat,jump)}
    lower=sum(v is True for v in groups.values());upper=lower+sum(v is None for v in groups.values())
    return {'rows':rows,'groups':groups,'lower':lower,'upper':upper,'sources':sources,'latest':latest,
        'values':values,'notes':notes,'as_of':str(cutoff.date()),'qqq_below_ma50':bad}


def render():
    st.subheader('外部宏观指标与风险观察')
    cache=core.get('macro_sources',{})
    st.caption('随“更新行情”同步检查；后台也会定时获取。这里只展示指标，不修改当前策略目标。')
    if not cache:
        st.info('宏观指标尚未获取，请点击“更新行情”。')
        return
    try:
        snap=core.get('snapshot');qqq=qqq_prices(core.get('confirmed_bundle',{}),snap['last']['date'])
        panel=build_panel(cache,qqq)
    except (ValueError,KeyError,TypeError) as exc:
        st.warning('宏观风险判定暂不可用：'+str(exc));return
    st.markdown(CARD_STYLE+risk_cards(panel,cache),unsafe_allow_html=True)
    st.markdown('<div class="macro-legend">单组：🟩 未触发　🟧 已触发　⬜ 待核对<br>综合：0组绿色 · 1组黄色 · 2组橙色 · 3组红色 · 4组深红色；数据不足时灰色。等级仅表示宏观条件的触发组数。</div>',unsafe_allow_html=True)
    st.caption(f"风险判定截至 {panel['as_of']} 已确认收盘；国债／政策滞后2个NYSE交易日、油价滞后3日。上方最新值可能与下方指标卡片的保守风险计算值不同。四组各计一票，倒挂参考不重复计分。")
    for note in panel['notes']:st.warning(note)
    for name,record in cache.items():
        if record.get('last_error'):st.warning(record['last_error']['message']+'；继续显示上次成功值。')
    with st.expander('各指标的矩形卡片、计算值与触发条件'):
        st.markdown(detail_cards(panel['rows']),unsafe_allow_html=True)
    with st.expander('数据来源、获取时间和其他原始值'):
        st.dataframe(pd.DataFrame(panel['sources']),hide_index=True,width='stretch')
        rates=panel['latest'].get('rates',{})
        if rates:st.write(f"最新2年名义国债：{rates['yield2']:.2f}%；10年实际国债：{rates['real10']:.2f}%。")
        cpi=panel['latest'].get('cpi',{});month=cpi.get('month')
        if month and month not in cache.get('cpi',{}).get('release_dates',{}):
            st.markdown(f'本次CPI公告日期未获取。可在[BLS官方日历]({CALENDAR})核对后记录，用于恢复通胀风险判定。')
            with st.form('macro_release_date_'+month):
                release=st.date_input(f'{month} CPI实际公告日期（美东）',value=None)
                if st.form_submit_button('保存已核对的公告日期'):
                    try:
                        if release is None:raise ValueError('请先填写官网公告日期')
                        save_release_date(month,release);st.rerun()
                    except ValueError as exc:st.error(str(exc))
        st.caption('利率来自财政部平价收益率，油价为EIA现货；CPI按当前未季调指数计算同比，不是历史首次公告归档。公告日期缺失时不猜测跳升窗口；缺失、过期指标显示待核对。')
    return panel
