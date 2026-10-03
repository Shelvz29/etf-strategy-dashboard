"""Verify exported chart anchors/metrics and syntax without a browser."""
import json
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from cash_replacement import OUT, INITIAL
from cash_replacement_report import REPORT


def main():
    rows=pd.read_csv(OUT/'results.csv')
    periods=pd.read_csv(OUT/'periods.csv')
    for row in periods.to_dict('records'):
        nav=pd.read_csv(OUT/(row['id']+'.csv'),index_col=0)
        anchor=INITIAL if pd.isna(row['baseline_close']) else nav.loc[row['baseline_close'],'equity']
        curve=nav.loc[row['first_session']:row['end_session'],'equity'].to_numpy()/anchor
        np.testing.assert_allclose(curve[-1],row['multiple'],rtol=1e-12)
        np.testing.assert_allclose(curve[-1]**(365.25/row['calendar_days'])-1,row['annualized_return'],rtol=1e-12)
        peak=np.maximum.accumulate(np.r_[1.,curve])[1:]
        np.testing.assert_allclose(1-(curve/peak).min(),row['max_drawdown'],rtol=1e-12)
    html=REPORT.read_text(encoding='utf-8')
    scripts=re.findall(r'<script>(.*?)</script>',html,re.S)
    assert len(scripts)==2 and '__DATA__' not in html and '__PLOTLY__' not in html
    with tempfile.TemporaryDirectory(prefix='hedge-report-check-') as folder:
        for i,script in enumerate(scripts):
            path=Path(folder)/f'script{i}.js'
            path.write_text(script,encoding='utf-8')
            subprocess.run(['node','--check',str(path)],check=True,capture_output=True)
        # Execute the report's filtering/math with small plain JS objects. This
        # is a static functional check, not a browser or native-app preview.
        prelude=r'''
const assert=require('node:assert/strict');
const elements={};const charts={};
for(const [id,value] of Object.entries({window:'2017年以来',scope:'仅MACD避险现金',weight:'1',period:'全部历史',capital:'10000',scale:'log'}))elements[id]={value,addEventListener(){}};
for(const id of ['range','table','stress','conditional'])elements[id]={innerHTML:'',addEventListener(){}};
elements.assets={children:[],insertAdjacentHTML(position,html){const s=html.match(/data-asset="([^"]+)"/)[1];const checkbox={value:s,checked:html.includes('checked')};this.children.push({dataset:{asset:s},style:{},checkbox})},querySelectorAll(){return this.children.filter(x=>x.checkbox.checked).map(x=>x.checkbox)},addEventListener(){}};
const document={getElementById(id){return elements[id]}};
const Plotly={react(id,traces,layout){for(const t of traces){assert.equal(t.x.length,t.y.length);assert.ok(t.y.every(Number.isFinite))}charts[id]=traces},purge(id){delete charts[id]}};
'''
        ending=r'''
assert.ok(elements.table.innerHTML.includes('66.65%'));
assert.equal(charts.equity.length,5);
elements.window.value='共同较短区间';elements.weight.value='.5';render();
assert.ok(elements.table.innerHTML.includes('99.50%'));
assert.ok(elements.range.textContent.includes('2022-05-05'));
elements.period.value='近5年';render();assert.equal(elements.table.innerHTML,'');
elements.window.value='2017年以来';elements.period.value='近1年';render();
assert.ok(elements.table.innerHTML.includes('464.29%'));
for(const t of charts.dd)assert.ok(t.y.every(v=>v<=1e-9));
elements.scope.value='策略全部现金';elements.weight.value='.25';render();
console.log('Report filtering, chart arrays and period anchors passed');
'''
        path=Path(folder)/'functional.js'
        path.write_text(prelude+scripts[1]+ending,encoding='utf-8')
        result=subprocess.run(['node',str(path)],check=True,capture_output=True,text=True)
        print(result.stdout.strip())
    audit={'curves':len(rows),'period_metrics':len(periods),'javascript_syntax_checks':len(scripts),
           'static_filter_checks':5,'browser_preview':'blocked by file URL policy; not performed'}
    (OUT/'report_verification.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(audit,ensure_ascii=False))


if __name__=='__main__':main()
