"""Public macro observations; archive inputs and research output stay private."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import io
import json
from pathlib import Path
import time
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import requests

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'backtests'/'2026-10-04-macro-recovery'
CUTOFF='2026-10-02'
SOURCES={
 'treasury':'https://home.treasury.gov/treasury-daily-interest-rate-xml-feed',
 'oil':'https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=RWTC&f=D',
 'policy':'https://www.newyorkfed.org/markets/reference-rates/effr',
 'cpi':'https://www.bls.gov/bls/news-release/cpi.htm'}


def download(url,path):
    if path.exists():return path.read_bytes()
    error=None
    for attempt in range(3):
        try:
            r=requests.get(url,timeout=(8,30),headers={'User-Agent':'Mozilla/5.0'})
            r.raise_for_status();path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(r.content)
            return r.content
        except requests.RequestException as exc:
            error=exc
            if getattr(getattr(exc,'response',None),'status_code',None) in (401,403):break
            time.sleep(.5)
    raise RuntimeError(f'Public data download failed: {url}: {error}')


def treasury(year,real=False):
    kind='daily_treasury_real_yield_curve' if real else 'daily_treasury_yield_curve'
    url=f'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data={kind}&field_tdr_date_value={year}'
    body=download(url,OUT/'raw'/(kind+str(year)+'.xml'))
    ns={'m':'http://schemas.microsoft.com/ado/2007/08/dataservices/metadata'}
    rows=[]
    for prop in ET.fromstring(body).findall('.//m:properties',ns):
        data={n.tag.split('}')[-1]:n.text for n in prop}
        row={'date':pd.Timestamp(data['NEW_DATE']).normalize()}
        keys={'real10':'TC_10YEAR'} if real else {'yield2':'BC_2YEAR','yield10':'BC_10YEAR','yield3m':'BC_3MONTH'}
        for target,key in keys.items():row[target]=float(data[key]) if data.get(key) is not None else np.nan
        rows.append(row)
    frame=pd.DataFrame(rows).set_index('date').sort_index()
    if frame.empty or frame.index.has_duplicates:raise ValueError('Invalid treasury XML')
    return frame


def fetch_all():
    OUT.mkdir(parents=True,exist_ok=True)
    frames={False:[],True:[]}
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(treasury,year,real):(year,real) for year in range(2015,2027) for real in (False,True)}
        for job in as_completed(jobs):
            year,real=jobs[job];frames[real].append(job.result());print('TREASURY',year,'real' if real else 'nominal',flush=True)
    yields=pd.concat(frames[False]).sort_index().join(pd.concat(frames[True]).sort_index())
    yields=yields.loc['2015-01-01':CUTOFF]
    yields.to_csv(OUT/'treasury.csv')
    oilbody=download('https://www.eia.gov/dnav/pet/hist_xls/RWTCd.xls',OUT/'raw'/'RWTCd.xls')
    oil=pd.read_excel(io.BytesIO(oilbody),sheet_name='Data 1',skiprows=2,engine='xlrd')
    oil.columns=['date','wti'];oil['date']=pd.to_datetime(oil.date)
    oil=oil.set_index('date').sort_index().loc['2015-01-01':CUTOFF]
    if oil.index.has_duplicates or not np.isfinite(oil.wti).all():raise ValueError('Invalid EIA oil data')
    # Negative spot prices in April 2020 are real; do not remove or log them.
    oil.to_csv(OUT/'oil.csv')
    body=download(f'https://markets.newyorkfed.org/api/rates/unsecured/effr/search.json?startDate=2015-01-01&endDate={CUTOFF}',OUT/'raw'/'nyfed_effr.json')
    policy=pd.DataFrame(json.loads(body)['refRates'])
    policy['date']=pd.to_datetime(policy.effectiveDate)
    policy=policy.set_index('date').sort_index()[['percentRate','targetRateTo']].rename(columns={'percentRate':'effr','targetRateTo':'target_upper'})
    if policy.index.has_duplicates or policy.loc['2016-01-01':].isna().any().any():raise ValueError('Invalid policy history')
    policy.to_csv(OUT/'policy.csv')
    receipts={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (OUT/'raw').iterdir() if p.is_file()}
    (OUT/'download_verification.json').write_text(json.dumps({'sources':SOURCES,'hashes':receipts,
        'ranges':{k:[str(f.index[0].date()),str(f.index[-1].date()),len(f)] for k,f in [('treasury',yields),('oil',oil),('policy',policy)]}},indent=2),encoding='utf-8')
    print('DATA',len(yields),len(oil),len(policy),flush=True)


if __name__=='__main__':fetch_all()
