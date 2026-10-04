"""Independently check table arithmetic, archive dates, and page calculations."""
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
import pandas as pd
from pypdf import PdfReader
from cash_replacement import simulate
from verify_qqq_transfer import verify_row
from six_factor_data import OUT,extract
from six_factor_report import REPORT
from six_factor_rules import features,apply_overlay,candidates
from deleveraging_rules import risk_features


def main():
    curves={r['id']:pd.read_csv(OUT/'curves'/(r['id']+'.csv'),index_col=0) for r in pd.read_csv(OUT/'summary.csv').to_dict('records')}
    count=0
    for file in ('summary','periods','annual','segments'):
        for row in pd.read_csv(OUT/(file+'.csv')).to_dict('records'):
            verify_row(row,curves[row['id']]);count+=1
    frames={s:pd.read_csv(OUT/'data'/(s+'.csv'),index_col=0,parse_dates=True) for s in ('SMH','SOXL','QQQ','XSD','RSP','SPY','GSPC')}
    for row in pd.read_csv(OUT/'execution_stress.csv').to_dict('records'):
        sig=pd.read_csv(OUT/'curves'/(row['id']+'_signals.csv'),index_col=0,parse_dates=True)
        nav=simulate(frames,sig,row['cost_bps'],int(row['extra_lag']));nav.index=nav.index.strftime('%Y-%m-%d')
        verify_row(row,nav);count+=1
    records=json.loads((OUT/'forecast_archive.json').read_text(encoding='utf-8'))
    ofr=pd.read_csv(OUT/'data'/'ofr.csv',index_col=0,parse_dates=True)
    rules={r['id']:r['rules'] for r in candidates()};base=pd.read_csv(OUT/'curves'/'BASE_signals.csv',index_col=0,parse_dates=True)
    health=risk_features(frames).risk_healthy
    cache={s:features(frames['SMH'].index,frames,ofr,records,extra_lag=5,scale=s) for s in (.8,1.,1.2)}
    proxy=features(frames['SMH'].index,frames,ofr,records,extra_lag=5,earnings_proxy=True)
    for row in pd.read_csv(OUT/'publication_lag_stress.csv').to_dict('records'):
        rule=rules[row['id']];f=proxy if rule.get('earnings_proxy') else cache[rule.get('scale',1.)]
        sig=base if row['id']=='BASE' else apply_overlay(base,f,health,rule)
        nav=simulate(frames,sig);nav.index=nav.index.strftime('%Y-%m-%d');verify_row(row,nav);count+=1
    checked=0
    for row in records:
        if row.get('pe') is None and row.get('revision') is None:continue
        stamp=pd.Timestamp(row['date']);path=OUT/'raw'/('EarningsInsight_'+stamp.strftime('%m%d%y')+'.pdf')
        assert hashlib.sha256(path.read_bytes()).hexdigest()==row['sha256']
        front=re.sub(r'\s+',' ',PdfReader(path).pages[0].extract_text() or '')
        pattern=stamp.strftime('%B')+r'\s+'+str(stamp.day)+r',?\s+'+str(stamp.year)
        assert re.search(pattern,front,re.I),row['date']
        parsed=extract(path.with_suffix('.txt').read_text(encoding='utf-8'))
        assert parsed['pe']==row.get('pe')
        if row.get('revision') is not None:
            assert parsed['revision']==row['revision'] and row['quarter']==(stamp.month-1)//3+1
        checked+=1
    html=REPORT.read_text(encoding='utf-8');scripts=re.findall(r'<script>(.*?)</script>',html,re.S)
    assert len(scripts)==2 and '__DATA__' not in html and '__PLOTLY__' not in html
    prelude=r'''
const assert=require('node:assert/strict'),elements={},charts={};
for(const [id,value] of Object.entries({period:'全部历史',capital:'10000',scale:'log'}))elements[id]={value,addEventListener(){}};
for(const id of ['conclusion','coverage','coverageNote','checks','design','range','table','segments','risk','stress','lag','associations'])elements[id]={innerHTML:'',textContent:'',addEventListener(){}};
elements.picks={children:[],insertAdjacentHTML(position,html){this.children.push({value:html.match(/value="([^"]+)"/)[1],checked:html.includes('checked')})},querySelectorAll(){return this.children.filter(x=>x.checked)},addEventListener(){}};
const document={getElementById(id){return elements[id]}},Plotly={react(id,traces){for(const t of traces){assert.equal(t.x.length,t.y.length);assert.ok(t.y.every(Number.isFinite))}charts[id]=traces}};
'''
    ending=r'''
assert.equal(elements.picks.children.length,25);
for(const period of ['全部历史','近1年','近2年','近3年','近5年']){elements.period.value=period;render();const p=D.periods.find(r=>r.id==='BASE'&&r.period===period);assert.ok(elements.table.innerHTML.includes(pct(p.annualized_return)));assert.ok(Math.abs(Math.min(...charts.drawdown[0].y)+100*p.max_drawdown)<1e-7);assert.ok(Math.abs(charts.equity[0].y.at(-1)/10000-p.multiple)<1e-7);assert.equal(charts.equity[0].x.at(-1),p.end_session)}
const previous=charts.equity[0].y.at(-1);elements.capital.value='20000';elements.scale.value='linear';render();assert.equal(charts.equity[0].y.at(-1),2*previous);
for(const x of elements.picks.children)x.checked=false;render();assert.equal(charts.equity.length,0);elements.picks.children.find(x=>x.value==='PROXY_BALANCED').checked=true;render();assert.equal(charts.equity.length,1);console.log('25 options, five periods, capital scaling and selection passed');
'''
    with tempfile.TemporaryDirectory(prefix='six-factor-report-') as folder:
        for i,code in enumerate(scripts):
            path=Path(folder)/f'script{i}.js';path.write_text(code,encoding='utf-8')
            subprocess.run(['node','--check',str(path)],check=True,capture_output=True)
        path=Path(folder)/'functional.js';path.write_text(prelude+scripts[1]+ending,encoding='utf-8')
        result=subprocess.run(['node',str(path)],check=True,capture_output=True,text=True);print(result.stdout.strip())
    receipt={'metric_rows':count,'archive_reports_checked':checked,'script_syntax_checks':2,
             'periods':5,'selection_and_capital':True,
             'visual_preview':'not performed: browser policy blocks local file URLs; static checks passed'}
    (OUT/'report_verification.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False))


if __name__=='__main__':main()
