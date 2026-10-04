"""Independent table arithmetic and static interactive-chart checks."""
import json
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from qqq_transfer import OUT, REPORT, INITIAL, simulate


def verify_row(row,nav):
    baseline=row['baseline_close']
    capital=INITIAL if pd.isna(baseline) else nav.loc[baseline,'equity']
    cut=nav.loc[row['first_session']:row['end_session'],'equity'].to_numpy()/capital
    peak=np.maximum.accumulate(np.r_[1.,cut])[1:]
    days=(pd.Timestamp(row['end_session'])-pd.Timestamp(baseline if pd.notna(baseline) else row['first_session'])).days+int(pd.isna(baseline))
    assert days==row['calendar_days']
    np.testing.assert_allclose([cut[-1],1-(cut/peak).min(),cut[-1]**(365.25/days)-1],
        [row['multiple'],row['max_drawdown'],row['annualized_return']],rtol=1e-10,atol=1e-12)


def main():
    count=0
    for filename in ('periods','annual','segments'):
        for row in pd.read_csv(OUT/(filename+'.csv')).to_dict('records'):
            verify_row(row,pd.read_csv(OUT/'curves'/(row['id']+'.csv'),index_col=0));count+=1
    frames={s:pd.read_csv(OUT/'data'/(s+'.csv'),index_col=0,parse_dates=True) for s in ('QQQ','TQQQ','SMH','SOXL')}
    for row in pd.read_csv(OUT/'stress.csv').to_dict('records'):
        sig=pd.read_csv(OUT/'curves'/(row['id']+'_signals.csv'),index_col=0,parse_dates=True)
        nav=simulate(frames,sig,row['cost_bps'],int(row['extra_lag']))
        nav.index=nav.index.strftime('%Y-%m-%d')
        verify_row(row,nav);count+=1
    html=REPORT.read_text(encoding='utf-8');scripts=re.findall(r'<script>(.*?)</script>',html,re.S)
    assert len(scripts)==2 and '__DATA__' not in html and '__PLOTLY__' not in html
    # A DOM stub checks actual page calculations. It is not a visual preview.
    prelude=r'''
const assert=require('node:assert/strict'),elements={},charts={};
for(const [id,value] of Object.entries({period:'全部历史',capital:'10000',scale:'log'}))elements[id]={value,addEventListener(){}};
for(const id of ['conclusion','diagnosis','checks','design','range','table','segments','annual','stress'])elements[id]={innerHTML:'',textContent:'',addEventListener(){}};
elements.picks={children:[],insertAdjacentHTML(position,html){this.children.push({value:html.match(/value="([^"]+)"/)[1],checked:html.includes('checked')})},querySelectorAll(){return this.children.filter(x=>x.checked)},addEventListener(){}};
const document={getElementById(id){return elements[id]}};
const Plotly={react(id,traces){for(const t of traces){assert.equal(t.x.length,t.y.length);assert.ok(t.y.every(Number.isFinite))}charts[id]=traces}};
'''
    ending=r'''
assert.equal(charts.equity.length,4);assert.ok(elements.conclusion.innerHTML.includes('29.86%'));
for(const period of ['全部历史','近1年','近2年','近3年','近5年']){elements.period.value=period;render();const r=D.periods.find(r=>r.id==='RECOVERY'&&r.period===period);assert.ok(elements.table.innerHTML.includes(pct(r.annualized_return)));assert.ok(Math.abs(charts.drawdown[0].y.reduce((a,b)=>Math.min(a,b),0)+100*r.max_drawdown)<1e-7);assert.ok(Math.abs(charts.equity[0].y.at(-1)/10000-r.multiple)<1e-7);assert.equal(charts.equity[0].x.at(-1),r.end_session)}
const previous=charts.equity[0].y.at(-1);elements.capital.value='20000';elements.scale.value='linear';render();assert.equal(charts.equity[0].y.at(-1),2*previous);
for(const x of elements.picks.children)x.checked=false;render();assert.equal(charts.equity.length,0);
elements.picks.children.find(x=>x.value==='SMH_REFERENCE').checked=true;render();assert.equal(charts.equity.length,1);
assert.ok(elements.diagnosis.textContent.includes('128'));console.log('Static table, 5 periods, capital scaling and selection checks passed');
'''
    with tempfile.TemporaryDirectory(prefix='qqq-transfer-report-') as folder:
        for i,code in enumerate(scripts):
            path=Path(folder)/f'script{i}.js';path.write_text(code,encoding='utf-8')
            subprocess.run(['node','--check',str(path)],check=True,capture_output=True)
        path=Path(folder)/'functional.js';path.write_text(prelude+scripts[1]+ending,encoding='utf-8')
        result=subprocess.run(['node',str(path)],check=True,capture_output=True,text=True)
        print(result.stdout.strip())
    receipt={'metric_rows':count,'script_syntax_checks':2,'chart_periods':5,'capital_scaling':True,
             'selection_checks':True,'visual_preview':'not performed; static calculations only'}
    (OUT/'report_verification.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False))


if __name__=='__main__':main()
