"""Archive public dated forecast snapshots and daily risk observations.

Downloaded reports, extracts, and market data are private ignored research inputs.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import io
import json
import re

import numpy as np
import pandas as pd
import requests
from pypdf import PdfReader

from cash_replacement import ROOT, core, parse, dump

OUT = ROOT/'backtests'/'2026-10-05-six-factor-recovery'
CUTOFF = '2026-10-02'
OFR = 'https://www.financialresearch.gov/financial-stress-index/data/fsi.csv'
PDF_PATHS = (
    'https://insight.factset.com/hubfs/Resources%20Section/Research%20Desk/Earnings%20Insight/',
    'https://advantage.factset.com/hubfs/Website/Resources%20Section/Research%20Desk/Earnings%20Insight/',
    'https://insight.factset.com/hubfs/Website/Resources%20Section/Research%20Desk/Earnings%20Insight/',
    'https://go.factset.com/hubfs/Resources%20Section/Research%20Desk/Earnings%20Insight/',
)


def extract(text):
    """Accept explicit current-quarter revisions, never growth-rate revisions."""
    text = re.sub(r'\s+', ' ', text)
    pe = re.search(r'forward\s+12\s*.\s*month\s+P/E\s+ratio\s+(?:is|for the S&P 500 is)\s+(\d+\.\d+)', text, re.I)
    revision = re.search(
        r'On a per.share basis, estimated earnings for the (first|second|third|fourth) quarter '
        r'have (fallen|declined|decreased|increased|risen|grown) by (\d+(?:\.\d+)?)% since '
        r'(December 31|March 31|June 30|September 30)', text, re.I)
    out = {'pe':float(pe[1]) if pe else None, 'revision':None, 'quarter':None,
           'evidence':revision[0] if revision else None}
    if revision:
        quarter = ['first','second','third','fourth'].index(revision[1].lower())+1
        expected = ['December 31','March 31','June 30','September 30'][quarter-1]
        if revision[4].lower() != expected.lower():
            raise ValueError('Quarter and starting date disagree')
        sign = -1 if revision[2].lower() in ('fallen','declined','decreased') else 1
        out.update(revision=sign*float(revision[3]),quarter=quarter)
    if revision is None:
        alternative=re.search(r'The Q([1-4]) bottom.up EPS estimate\s*\([^)]{0,500}\)\s*'
            r'has (dropped|fallen|declined|decreased|increased|risen) by (\d+(?:\.\d+)?)%',text,re.I)
        if alternative:
            tail=text[alternative.end():alternative.end()+170]
            # Explicit quarter-start or current reporting-period wording only.
            quarter=int(alternative[1]);expected=['December 31','March 31','June 30','September 30'][quarter-1]
            if ('during this period' in tail.lower() or re.search('since '+expected,tail,re.I)):
                sign=1 if alternative[2].lower() in ('increased','risen') else -1
                out.update(revision=sign*float(alternative[3]),quarter=quarter,evidence=alternative[0]+tail)
    return out


def forecast(stamp):
    filename='EarningsInsight_'+stamp.strftime('%m%d%y')+'.pdf'
    path=OUT/'raw'/filename
    if path.exists():
        body=path.read_bytes(); url=json.loads((path.with_suffix('.source.json')).read_text())['url']
    else:
        errors=[]
        for prefix in PDF_PATHS:
            url=prefix+filename
            try:
                r=requests.get(url,timeout=(5,12),headers={'User-Agent':'Mozilla/5.0'})
                r.raise_for_status()
                if not r.content.startswith(b'%PDF'):raise ValueError('Not PDF')
                body=r.content;path.write_bytes(body);dump(path.with_suffix('.source.json'),{'url':url})
                break
            except (requests.RequestException,ValueError) as exc:errors.append(type(exc).__name__)
        else:return {'date':str(stamp.date()),'error':','.join(errors)}
    reader=PdfReader(io.BytesIO(body))
    text=' '.join(page.extract_text() or '' for page in reader.pages)
    flat=re.sub(r'\s+',' ',text)
    # The report itself must identify the requested publication date.
    date_pattern=stamp.strftime('%B')+r'\s+'+str(stamp.day)+r',?\s+'+str(stamp.year)
    front=re.sub(r'\s+',' ',reader.pages[0].extract_text() or '')
    if not re.search(date_pattern,front,re.I):return {'date':str(stamp.date()),'error':'Publication date not verified'}
    out=extract(text)
    if out['quarter'] is not None and out['quarter'] != (stamp.month-1)//3+1:
        out.update(revision=None,quarter=None,evidence=None)
    out.update(date=str(stamp.date()),source=url,sha256=hashlib.sha256(body).hexdigest())
    # Extracts remain in the ignored directory for an audit of accepted numbers.
    path.with_suffix('.txt').write_text(text,encoding='utf-8')
    return out


def main():
    for folder in ('raw','data'): (OUT/folder).mkdir(parents=True,exist_ok=True)
    body=requests.get(OFR,timeout=(8,30));body.raise_for_status()
    (OUT/'raw'/'fsi.csv').write_bytes(body.content)
    frame=pd.read_csv(io.BytesIO(body.content)).rename(columns={'Date':'date','Credit':'credit','Funding':'funding','OFR FSI':'fsi'})
    frame['date']=pd.to_datetime(frame.date)
    frame=frame.set_index('date').sort_index()[['credit','funding','fsi']].loc[:CUTOFF]
    if frame.index.has_duplicates or not np.isfinite(frame).all().all():raise ValueError('Invalid OFR series')
    frame.to_csv(OUT/'data'/'ofr.csv')
    def price(symbol):
        filename=symbol.replace('^','');path=OUT/'data'/(filename+'.json')
        if path.exists():payload=json.loads(path.read_text(encoding='utf-8'))
        else:
            payload=core.request_json(symbol,dict(period1=int(pd.Timestamp('2015-01-01',tz='UTC').timestamp()),
                period2=int(pd.Timestamp('2026-10-03',tz='UTC').timestamp()),interval='1d',events='div,splits',includeAdjustedClose='true'))
            dump(path,payload)
        f=parse(symbol,payload,CUTOFF);f.to_csv(OUT/'data'/(filename+'.csv'));return symbol,len(f)
    with ThreadPoolExecutor(max_workers=2) as pool:
        for result in pool.map(price,('RSP','SPY','^GSPC')):print('PRICE',result,flush=True)
    # Monthly snapshots selected by calendar, before inspecting performance.
    stamps=[]
    for period in pd.period_range('2016-01','2026-09',freq='M'):
        last=period.end_time.normalize();stamps.append(last-pd.Timedelta(days=(last.weekday()-4)%7))
    stamps.append(pd.Timestamp(CUTOFF))
    rows=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs={pool.submit(forecast,d):d for d in stamps}
        for job in as_completed(jobs):
            try:row=job.result()
            except Exception as exc:row={'date':str(jobs[job].date()),'error':type(exc).__name__}
            rows.append(row);print('REPORT',row['date'],row.get('pe'),row.get('revision'),row.get('error',''),flush=True)
    rows.sort(key=lambda r:r['date']);dump(OUT/'forecast_archive.json',rows)
    print('DONE',len(rows),'PE',sum(r.get('pe') is not None for r in rows),'EPS',sum(r.get('revision') is not None for r in rows),flush=True)


def supplement():
    """Calendar-based extra snapshots; no performance-dependent dates."""
    rows=json.loads((OUT/'forecast_archive.json').read_text(encoding='utf-8'))
    existing={r['date'] for r in rows if not r.get('error')}
    dates=set()
    for period in pd.period_range('2017-01','2026-09',freq='M'):
        last=period.end_time.normalize();friday=last-pd.Timedelta(days=(last.weekday()-4)%7)
        if str(friday.date()) not in existing:dates.add(friday-pd.Timedelta(days=7))
        first=period.start_time;dates.add(first+pd.Timedelta(days=(4-first.weekday())%7))
    dates={d for d in dates if str(d.date()) not in existing}
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs={pool.submit(forecast,d):d for d in dates}
        for job in as_completed(jobs):
            try:row=job.result()
            except Exception as exc:row={'date':str(jobs[job].date()),'error':type(exc).__name__}
            rows.append(row);print('EXTRA',row['date'],row.get('pe'),row.get('revision'),row.get('error',''),flush=True)
    merged={r['date']:r for r in rows};rows=sorted(merged.values(),key=lambda r:r['date'])
    dump(OUT/'forecast_archive.json',rows)
    print('ARCHIVE',len(rows),'PE',sum(r.get('pe') is not None for r in rows),'EPS',sum(r.get('revision') is not None for r in rows),flush=True)


if __name__=='__main__':
    import sys
    supplement() if '--supplement' in sys.argv else main()
