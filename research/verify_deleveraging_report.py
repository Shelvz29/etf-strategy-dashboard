"""Exported-metric, script-syntax and static chart/filter checks."""
import json
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from deleveraging_study import OUT, INITIAL
from deleveraging_report import REPORT


def main():
    count=0
    for file in ('periods.csv','segments.csv','annual.csv'):
        for row in pd.read_csv(OUT/file).to_dict('records'):
            nav=pd.read_csv(OUT/'curves'/(row['id']+'.csv'),index_col=0)
            anchor=INITIAL if pd.isna(row['baseline_close']) else nav.loc[row['baseline_close'],'equity']
            curve=nav.loc[row['first_session']:row['end_session'],'equity'].to_numpy()/anchor
            peak=np.maximum.accumulate(np.r_[1.,curve])[1:]
            np.testing.assert_allclose([curve[-1],1-(curve/peak).min(),curve[-1]**(365.25/row['calendar_days'])-1],
                [row['multiple'],row['max_drawdown'],row['annualized_return']],rtol=1e-10,atol=1e-12)
            count+=1
    html=REPORT.read_text(encoding='utf-8')
    scripts=re.findall(r'<script>(.*?)</script>',html,re.S)
    assert len(scripts)==2 and '__DATA__' not in html and '__PLOTLY__' not in html
    prelude=r'''
const assert=require('node:assert/strict');const elements={},charts={};
for(const [id,value] of Object.entries({period:'全部历史',capital:'10000',sort:'calmar',scale:'log'}))elements[id]={value,addEventListener(){}};
for(const id of ['summary','selection','checks','rules','range','table','segments','annual','stress','risk'])elements[id]={innerHTML:'',textContent:'',addEventListener(){}};
elements.picks={children:[],insertAdjacentHTML(position,html){const key=html.match(/value="([^"]+)"/)[1];this.children.push({value:key,checked:html.includes('checked')})},querySelectorAll(){return this.children.filter(x=>x.checked)},addEventListener(){}};
const document={getElementById(id){return elements[id]}};
const Plotly={react(id,traces){for(const t of traces){assert.equal(t.x.length,t.y.length);assert.ok(t.y.every(Number.isFinite))}charts[id]=traces}};
'''
    ending=r'''
assert.equal(charts.equity.length,6);assert.ok(elements.table.innerHTML.includes('60.19%'));
assert.ok(elements.summary.innerHTML.includes('44.26%'));
elements.period.value='近1年';render();assert.ok(elements.table.innerHTML.includes('464.29%'));
assert.ok(elements.range.textContent.includes('2025-10-03'));
for(const t of charts.drawdown)assert.ok(t.y.every(v=>v<=1e-9));
elements.period.value='验证2022—2024';render();assert.ok(elements.table.innerHTML.includes('-15.08%'));
elements.period.value='后段2025—2026';elements.sort.value='max_drawdown';elements.capital.value='20000';render();
assert.ok(elements.range.textContent.includes('2025-01-02'));
for(const x of elements.picks.children)x.checked=false;render();assert.equal(charts.equity.length,1);
console.log('Static chart arrays, filters, selections and table anchors passed');
'''
    with tempfile.TemporaryDirectory(prefix='deleveraging-report-check-') as folder:
        for i,script in enumerate(scripts):
            path=Path(folder)/f'script{i}.js';path.write_text(script,encoding='utf-8')
            subprocess.run(['node','--check',str(path)],check=True,capture_output=True)
        path=Path(folder)/'functional.js';path.write_text(prelude+scripts[1]+ending,encoding='utf-8')
        check=subprocess.run(['node',str(path)],check=True,capture_output=True,text=True)
        print(check.stdout.strip())
    result={'metric_rows':count,'script_syntax_checks':2,'static_filter_cases':5,
            'browser_visual_preview':'not performed; earlier local file URL policy restriction'}
    (OUT/'report_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
