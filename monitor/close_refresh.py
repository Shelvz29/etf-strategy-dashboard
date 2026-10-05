"""Persistent post-close panel refresh; no scheduling of orders or strategies."""
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import pandas as pd
import streamlit as st

import core
import macro_sources
import market_factors

DELAY_MINUTES=20
RETRY_MINUTES=5
KEY='post_close_refresh'


def schedule(at=None):
    at=pd.Timestamp(at or core.now_utc())
    if at.tzinfo is None:raise ValueError('Time must be timezone aware')
    at=at.tz_convert('UTC');cal=core.calendar(at.year)
    rows=cal.schedule.loc[(at-pd.Timedelta(days=20)).date().isoformat():
                         (at+pd.Timedelta(days=20)).date().isoformat()]
    due=rows['close']+pd.Timedelta(minutes=DELAY_MINUTES)
    past=due.loc[due.le(at)];future=due.loc[due.gt(at)]
    return {'session':str(past.index[-1].date()),'due_at':past.iloc[-1].isoformat(),
            'next_at':future.iloc[0].isoformat(),'planned_at':at.isoformat(),
            'fingerprint':core.active_strategy()['fingerprint']}


def pending(at=None):
    plan=schedule(at);old=core.get(KEY,{})
    same=(old.get('session')==plan['session'] and old.get('fingerprint')==plan['fingerprint'])
    if same and old.get('status')=='complete':return None
    if same and old.get('retry_at') and pd.Timestamp(old['retry_at'])>pd.Timestamp(plan['planned_at']):return None
    return plan


def run(plan,logger):
    old=core.get(KEY,{})
    same=old.get('session')==plan['session'] and old.get('fingerprint')==plan['fingerprint']
    state={**plan,'status':'running','attempts':old.get('attempts',0)+1 if same else 1,
           'started':core.iso_now(),'parts':{},'errors':[]}
    if old.get('last_success'):state['last_success']=old['last_success']
    core.put(KEY,state)
    def stage(name,work):
        state['phase']=name;core.put(KEY,state)
        core.put('heartbeat',{'time':core.iso_now(),'pid':os.getpid(),'busy':True})
        try:
            # Slow public providers must not make a live worker look stopped.
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(work)
                while True:
                    try:errors=future.result(timeout=15);break
                    except TimeoutError:
                        if future.done():raise
                        core.put('heartbeat',{'time':core.iso_now(),'pid':os.getpid(),'busy':True})
            state['parts'][name]='部分失败' if errors else '完成';state['errors'].extend(errors)
        except Exception as exc:
            state['parts'][name]='失败';state['errors'].append(name+'：'+type(exc).__name__)
            logger.exception('Post-close %s failed',name)
        core.put(KEY,state)
    def daily():
        snap=core.refresh_full(at=pd.Timestamp(plan['planned_at']))
        if snap['last']['date']!=plan['session'] or snap['source']!='Yahoo 公开日线':raise ValueError('Daily close not confirmed')
        if core.active_strategy()['fingerprint']!=plan['fingerprint']:raise core.StrategyChanged('Strategy changed')
        core.put('validated_session',plan['session'])
        core.put('quotes',{'data':snap['quotes'],'fetched':core.iso_now()})
        return []
    def observations(fetch,names):
        cache=fetch(force=True)
        return [name+'：来源失败或缺失' for name in names if not cache.get(name) or cache[name].get('last_error')]
    stage('策略日线',daily)
    stage('宏观指标',lambda:observations(macro_sources.refresh,macro_sources.SOURCES))
    stage('六项参考指标',lambda:observations(market_factors.refresh,('RSP','SPY','SMH','XSD','OFR','FactSet')))
    if core.active_strategy()['fingerprint']!=plan['fingerprint']:
        state['errors'].append('策略已切换，需重新更新')
    state['finished']=core.iso_now();state.pop('phase',None)
    state['status']='retry' if state['errors'] else 'complete'
    state['retry_at']=(pd.Timestamp(state['finished'])+pd.Timedelta(minutes=RETRY_MINUTES)).isoformat() if state['errors'] else None
    if state['status']=='complete':
        state['completed']=state['finished']
        state['last_success']={'session':plan['session'],'time':state['finished']}
    elif old.get('last_success'):state['last_success']=old['last_success']
    core.put(KEY,state);logger.info('Post-close %s %s, attempt %s',plan['session'],state['status'],state['attempts'])
    return state


def render():
    plan=schedule();state=core.get(KEY,{})
    st.subheader('收盘后自动更新')
    st.caption(f'已开启 · 每个美股交易日收盘{DELAY_MINUTES}分钟后，自动检查策略日线、宏观数据和六项参考指标。下一次（北京）：{core.display_time(plan["next_at"])}。')
    labels={'running':'正在更新','retry':'部分失败，等待重试','complete':'已完成'}
    text=labels.get(state.get('status'),'等待首次更新')
    if state:
        text+=f' · 收盘日 {state["session"]}（美东） · 第{state.get("attempts",1)}次'
        if state.get('phase'):text+=' · '+state['phase']
        if state.get('finished'):text+=' · 最近检查（北京）'+core.display_time(state['finished'])
    st.info(text)
    if state.get('parts'):st.caption('本次检查：'+' · '.join(name+' '+value for name,value in state['parts'].items()))
    if state.get('last_success'):
        last=state['last_success'];st.caption(f'最近完整更新：{last["session"]}收盘 · {core.display_time(last["time"])}（北京）。完成表示来源检查成功，宏观／盈利报告仍可能有公布滞后。')
    if state.get('status')=='retry':st.warning(f'保留已确认数据；下次重试（北京）{core.display_time(state["retry_at"])}。'+'；'.join(state['errors']))
    st.caption('按交易日历处理夏令时、节假日和提前收盘；电脑需开机、联网且保持唤醒。后台恢复后补更新最近收盘日，页面每15秒显示最新结果；不提交订单。')
