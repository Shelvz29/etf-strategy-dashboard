"""Official live macro observations, independently cached from trading signals."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from html.parser import HTMLParser
import io
import json
import math
import xml.etree.ElementTree as ET

import pandas as pd
import requests

import core

SOURCES={
    'rates':('国债收益率','https://home.treasury.gov/treasury-daily-interest-rate-xml-feed'),
    'oil':('WTI现货','https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=RWTC&f=D'),
    'policy':('联储目标利率','https://www.newyorkfed.org/markets/reference-rates/effr'),
    'cpi':('CPI','https://www.bls.gov/bls/news-release/cpi.htm')}
API='https://api.bls.gov/publicAPI/v2/timeseries/data/'
CALENDAR='https://www.bls.gov/schedule/news_release/cpi.htm'


def request(url,body=None,read_timeout=12):
    response=(requests.get(url,timeout=(4,read_timeout)) if body is None else
              requests.post(url,json=body,timeout=(4,read_timeout)))
    response.raise_for_status()
    return response


def treasury(at,previous):
    jobs=[(year,real) for year in (at.year-1,at.year) for real in (False,True)]
    def one(job):
        year,real=job;kind='daily_treasury_real_yield_curve' if real else 'daily_treasury_yield_curve'
        url=f'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data={kind}&field_tdr_date_value={year}'
        root=ET.fromstring(request(url,read_timeout=25).content);rows=[]
        for prop in root.findall('.//{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}properties'):
            data={n.tag.split('}')[-1]:n.text for n in prop}
            row={'date':str(pd.Timestamp(data['NEW_DATE']).date())}
            keys={'real10':'TC_10YEAR'} if real else {'yield2':'BC_2YEAR','yield10':'BC_10YEAR'}
            for key,field in keys.items():row[key]=float(data[field])
            rows.append(row)
        # Current-year feed can legitimately be empty on January 1.
        return real,rows
    grouped={False:[],True:[]}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for real,rows in pool.map(one,jobs):grouped[real].extend(rows)
    left=pd.DataFrame(grouped[False]).set_index('date');right=pd.DataFrame(grouped[True]).set_index('date')
    frame=left.join(right,validate='one_to_one').sort_index()
    return {'observations':frame.reset_index().to_dict('records')}


def oil(at,previous):
    body=request('https://www.eia.gov/dnav/pet/hist_xls/RWTCd.xls').content
    frame=pd.read_excel(io.BytesIO(body),sheet_name='Data 1',skiprows=2,engine='xlrd')
    frame.columns=['date','wti'];frame['date']=pd.to_datetime(frame.date).dt.strftime('%Y-%m-%d')
    return {'observations':frame.loc[frame.date>=f'{at.year-1}-01-01'].to_dict('records')}


def policy(at,previous):
    url=f'https://markets.newyorkfed.org/api/rates/unsecured/effr/search.json?startDate={at.year-1}-01-01&endDate={at.date()}'
    rows=request(url).json()['refRates']
    return {'observations':[{'date':r['effectiveDate'],'target_upper':float(r['targetRateTo'])} for r in rows]}


class CalendarTable(HTMLParser):
    def __init__(self):
        super().__init__();self.rows=[];self.row=[];self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='tr':self.row=[]
        if tag=='td':self.cell=[]
    def handle_data(self,data):
        if self.cell is not None:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag=='td' and self.cell is not None:self.row.append(' '.join(''.join(self.cell).split()));self.cell=None
        if tag=='tr' and len(self.row)>=2:self.rows.append(self.row)


def release_calendar(text):
    parser=CalendarTable();parser.feed(text);dates={}
    for row in parser.rows:
        try:
            month=datetime.strptime(row[0],'%B %Y').strftime('%Y-%m')
            stamp=row[1].replace('.','').replace('Sept ','Sep ')
            released=datetime.strptime(stamp,'%b %d, %Y').date().isoformat()
            dates[month]=released
        except ValueError:continue
    if not dates:raise ValueError('CPI公告日历格式变化')
    return dates


def cpi(at,previous):
    body=request(API,{'seriesid':['CUUR0000SA0','CUUR0000SA0L1E'],
        'startyear':str(at.year-3),'endyear':str(at.year)}).json()
    if body.get('status')!='REQUEST_SUCCEEDED':raise ValueError('BLS API未返回有效数据或达到公开额度')
    levels={}
    names={'CUUR0000SA0':'headline','CUUR0000SA0L1E':'core'}
    for series in body['Results']['series']:
        name=names[series['seriesID']];levels[name]={}
        for row in series['data']:
            if row['period']=='M13' or row['value']=='-':continue
            month=row['year']+'-'+row['period'][1:];levels[name][month]=float(row['value'])
    months=sorted(set(levels['headline'])&set(levels['core']))
    rows=[]
    for month in months:
        prior=str(pd.Period(month,freq='M')-12)
        if all(prior in levels[key] for key in names.values()):
            rows.append({'month':month,**{key:round((levels[key][month]/levels[key][prior]-1)*100,1) for key in names.values()}})
    if len(rows)<4:raise ValueError('CPI共同历史不足')
    dates=dict(previous.get('release_dates',{}));calendar_error=None
    attempted=previous.get('calendar_attempt')
    if not attempted or (at-pd.Timestamp(attempted)).total_seconds()>=86400:
        attempted=at.isoformat()
        try:dates.update(release_calendar(request(CALENDAR).text))
        except Exception as exc:calendar_error=type(exc).__name__
    else:calendar_error=previous.get('calendar_error')
    return {'observations':rows,'release_dates':dates,'date_notes':previous.get('date_notes',{}),'calendar_attempt':attempted,'calendar_error':calendar_error,
        'method':'当前BLS未季调指数计算并四舍五入同比；公告日历缺失时不猜测跳升窗口'}


FETCHERS={'rates':treasury,'oil':oil,'policy':policy,'cpi':cpi}
FIELDS={'rates':['yield2','yield10','real10'],'oil':['wti'],'policy':['target_upper'],'cpi':['headline','core']}


def save_release_date(month,released,at=None):
    """User-verified date metadata only; do not overwrite observations or targets."""
    stamp=pd.Timestamp(released);today=pd.Timestamp(at or core.now_utc()).tz_convert('America/New_York').tz_localize(None).normalize()
    if stamp.tzinfo is not None or stamp!=stamp.normalize() or stamp>today or stamp<=pd.Period(month,freq='M').end_time.normalize():
        raise ValueError('公告日期需在统计月结束之后，且不能晚于今天（美东）')
    with core.connect() as db:
        raw=db.execute("SELECT value FROM kv WHERE key='macro_sources'").fetchone()
        cache=json.loads(raw[0]) if raw else {}
        record=cache.get('cpi',{})
        if month not in [r['month'] for r in record.get('observations',[])]:raise ValueError('该统计月尚无已获取的CPI数据')
        record.setdefault('release_dates',{})[month]=str(stamp.date())
        record.setdefault('date_notes',{})[month]='用户在BLS官网核对后记录'
        db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)",('macro_sources',core.json_dump(cache)))


def validate(name,record,at):
    rows=record['observations'];key='month' if name=='cpi' else 'date'
    rows=sorted(rows,key=lambda r:r[key]);dates=[r[key] for r in rows]
    if len(rows)<4 or len(set(dates))!=len(dates):raise ValueError('宏观历史为空或日期重复')
    for row in rows:
        if any(not math.isfinite(float(row[field])) for field in FIELDS[name]):raise ValueError('宏观数据含缺失值')
        if pd.Timestamp(row[key])>at.tz_convert('America/New_York').tz_localize(None):raise ValueError('宏观观测日期在未来')
    # Never replace a complete cache with an endpoint's partial old response.
    record['observations']=rows
    return record


def refresh(force=False,at=None):
    at=pd.Timestamp(at or core.now_utc()).tz_convert('UTC')
    cache=core.get('macro_sources',{});pending=[]
    for name in SOURCES:
        previous=cache.get(name,{});attempt=previous.get('last_attempt') or previous.get('fetched')
        age=(at-pd.Timestamp(attempt)).total_seconds() if attempt else float('inf')
        interval=3600 if name=='cpi' else 1800
        if age>=(60 if force else interval):pending.append(name)
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(FETCHERS[name],at,cache.get(name,{})):name for name in pending}
        for job in as_completed(jobs):
            name=jobs[job];previous=cache.get(name,{})
            try:
                record=validate(name,job.result(),at)
                key='month' if name=='cpi' else 'date'
                if previous.get('observations') and record['observations'][-1][key]<previous['observations'][-1][key]:raise ValueError('宏观接口返回日期倒退')
                cache[name]={**record,'fetched':at.isoformat(),'last_attempt':at.isoformat(),'last_error':None}
            except Exception as exc:
                cache[name]={**previous,'last_attempt':at.isoformat(),'last_error':{'time':at.isoformat(),'message':f'{SOURCES[name][0]}更新失败：{type(exc).__name__}'}}
    with core.connect() as db:
        raw=db.execute("SELECT value FROM kv WHERE key='macro_sources'").fetchone()
        live=json.loads(raw[0]) if raw else {}
        # Preserve a user-verified date saved while a network request was running.
        for month,note in live.get('cpi',{}).get('date_notes',{}).items():
            cache.setdefault('cpi',{}).setdefault('release_dates',{})[month]=live['cpi']['release_dates'][month]
            cache['cpi'].setdefault('date_notes',{})[month]=note
        db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)",('macro_sources',core.json_dump(cache)))
    core.put('macro_last_attempt',at.isoformat())
    return cache
