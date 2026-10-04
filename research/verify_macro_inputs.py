"""Cross-check archived CPI YoY against current unadjusted BLS indexes.

This checks transcription, not real-time vintages; mismatches are reported and
never used to overwrite the release archive.
"""
import json
import numpy as np
import pandas as pd

from macro_data import OUT, download


def main():
    levels={}
    for name,series in [('headline','CUUR0000SA0'),('core','CUUR0000SA0L1E')]:
        rows=[]
        for start,end in [(2014,2023),(2024,2026)]:
            url=f'https://api.bls.gov/publicAPI/v2/timeseries/data/{series}?startyear={start}&endyear={end}'
            body=json.loads(download(url,OUT/'raw'/f'bls_{series}_{start}_{end}.json'))
            if body['status']!='REQUEST_SUCCEEDED':raise ValueError(body.get('message'))
            for r in body['Results']['series'][0]['data']:
                if r['period']=='M13' or r['value']=='-':continue
                rows.append((r['year']+'-'+r['period'][1:],float(r['value'])))
        levels[name]=dict(rows)
    archive=json.loads((OUT/'cpi_releases.json').read_text(encoding='utf-8'))
    comparisons=[]
    for r in archive:
        month=pd.Period(r['month'],freq='M');prior=str(month-12)
        for name in levels:
            values=levels[name]
            if r['month'] not in values or prior not in values:raise ValueError('Missing BLS comparison month')
            current=(values[r['month']]/values[prior]-1)*100
            # Archived publications round YoY to one decimal point.
            comparisons.append({'month':r['month'],'release_date':r['release_date'],'series':name,
                'archive_yoy':r[name],'current_index_yoy':current,
                'matches_rounding':bool(abs(current-r[name])<=.051)})
    df=pd.DataFrame(comparisons);df.to_csv(OUT/'cpi_crosscheck.csv',index=False)
    mismatches=df.loc[~df.matches_rounding].to_dict('records')
    if not np.isfinite(df[['archive_yoy','current_index_yoy']]).all().all():raise ValueError('Nonfinite CPI comparison')
    receipt={'comparisons':len(df),'mismatches':mismatches,
        'note':'Current unadjusted indexes only check transcription. Revisions/corrections can differ from original announcements; archives are not overwritten.'}
    (OUT/'cpi_crosscheck.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False))
    if any(r['month']>='2017-01' for r in mismatches):raise AssertionError('Review post-2017 CPI transcription or corrections before interpreting results')


if __name__=='__main__':main()
