"""Check reported arithmetic and static interaction without browser execution."""
import json
import re
import subprocess
import tempfile
from pathlib import Path
import pandas as pd

from macro_data import OUT
from macro_report import REPORT
from macro_study import load_macro
from macro_rules import features,apply_overlay,candidates
from deleveraging_rules import risk_features
from cash_replacement import simulate
from verify_qqq_transfer import verify_row


def main():
    curves={row['id']:pd.read_csv(OUT/'curves'/(row['id']+'.csv'),index_col=0)
            for row in pd.read_csv(OUT/'summary.csv').to_dict('records')}
    count=0
    for file in ('summary','periods','annual','segments'):
        for row in pd.read_csv(OUT/(file+'.csv')).to_dict('records'):
            verify_row(row,curves[row['id']]);count+=1
    frames={s:pd.read_csv(OUT/'etf_data'/(s+'.csv'),index_col=0,parse_dates=True) for s in ('SMH','SOXL','QQQ','TQQQ')}
    for row in pd.read_csv(OUT/'execution_stress.csv').to_dict('records'):
        goal=pd.read_csv(OUT/'curves'/(row['id']+'_signals.csv'),index_col=0,parse_dates=True)
        nav=simulate(frames,goal,row['cost_bps'],int(row['extra_lag']));nav.index=nav.index.strftime('%Y-%m-%d')
        verify_row(row,nav);count+=1
    raw=load_macro();rules={r['id']:r['rules'] for r in candidates()};index=frames['QQQ'].index
    delayed={s:features(index,frames['QQQ'].close,*raw,extra_lag=5,threshold_scale=s) for s in (.8,1.,1.2)}
    for row in pd.read_csv(OUT/'macro_lag_stress.csv').to_dict('records'):
        market,variant=row['id'].split('_',1);base=pd.read_csv(OUT/'curves'/(market+'_BASE_signals.csv'),index_col=0,parse_dates=True)
        local=frames if market=='SMH' else {'SMH':frames['QQQ'],'SOXL':frames['TQQQ'],'QQQ':frames['QQQ']}
        health=risk_features(local).risk_healthy;rule=rules[variant]
        goal=apply_overlay(base,delayed[rule.get('threshold_scale',1.)],health,'SOXL' if market=='SMH' else 'TQQQ',rule)
        nav=simulate(frames,goal);nav.index=nav.index.strftime('%Y-%m-%d');verify_row(row,nav);count+=1
    html=REPORT.read_text(encoding='utf-8');scripts=re.findall(r'<script>(.*?)</script>',html,re.S)
    assert len(scripts)==2 and '__DATA__' not in html and '__PLOTLY__' not in html
    prelude=r'''
const assert=require('node:assert/strict'),elements={},charts={};
for(const [id,value] of Object.entries({market:'SMH',period:'全部历史',capital:'10000',scale:'log',horizon:'20'}))elements[id]={value,addEventListener(){}};
for(const id of ['factors','correlation','checks','design','range','conclusion','table','segments','annual','risk','stress','macro_lag','diagnosis','associations'])elements[id]={innerHTML:'',textContent:'',addEventListener(){}};
elements.picks={children:[],insertAdjacentHTML(position,html){this.children.push({value:html.match(/value="([^"]+)"/)[1],checked:html.includes('checked')})},querySelectorAll(){return this.children.filter(x=>x.checked)},addEventListener(){}};
const document={getElementById(id){return elements[id]}},Plotly={react(id,traces){for(const t of traces){assert.equal(t.x.length,t.y.length);assert.ok(t.y.every(Number.isFinite))}charts[id]=traces}};
'''
    ending=r'''
assert.equal(elements.picks.children.length,20);assert.equal(charts.equity.length,5);
for(const market of ['SMH','QQQ'])for(const period of ['全部历史','近1年','近2年','近3年','近5年']){elements.market.value=market;elements.period.value=period;render();const p=D.periods.find(r=>r.id===market+'_BASE'&&r.period===period);assert.ok(elements.table.innerHTML.includes(pct(p.annualized_return)));assert.ok(Math.abs(Math.min(...charts.drawdown[0].y)+100*p.max_drawdown)<1e-7);assert.ok(Math.abs(charts.equity[0].y.at(-1)/10000-p.multiple)<1e-7);assert.equal(charts.equity[0].x.at(-1),p.end_session);assert.equal((elements.table.innerHTML.match(/<tbody>/g)||[]).length,1);assert.equal((elements.table.innerHTML.match(/<tr>/g)||[]).length,21)}
const previous=charts.equity[0].y.at(-1);elements.capital.value='20000';elements.scale.value='linear';render();assert.equal(charts.equity[0].y.at(-1),2*previous);
for(const horizon of ['5','20','60']){elements.horizon.value=horizon;render();assert.equal((elements.associations.innerHTML.match(/<tr>/g)||[]).length,14)}
for(const x of elements.picks.children)x.checked=false;render();assert.equal(charts.equity.length,0);elements.picks.children.find(x=>x.value==='S23_ALL').checked=true;render();assert.equal(charts.equity.length,1);assert.equal(charts.equity[0].name,D.summary.find(r=>r.id==='QQQ_S23_ALL').name);console.log('Two markets, five periods, selection, capital and three statistical horizons passed');
'''
    with tempfile.TemporaryDirectory(prefix='macro-report-') as folder:
        for i,code in enumerate(scripts):
            path=Path(folder)/f'script{i}.js';path.write_text(code,encoding='utf-8')
            subprocess.run(['node','--check',str(path)],check=True,capture_output=True)
        path=Path(folder)/'functional.js';path.write_text(prelude+scripts[1]+ending,encoding='utf-8')
        result=subprocess.run(['node',str(path)],check=True,capture_output=True,text=True);print(result.stdout.strip())
    receipt={'metric_rows':count,'script_syntax_checks':2,'markets':2,'periods':5,'statistical_horizons':3,
        'capital_scaling':True,'selection_checks':True,'visual_preview':'not performed; static calculations only'}
    (OUT/'report_verification.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False))


if __name__=='__main__':main()
