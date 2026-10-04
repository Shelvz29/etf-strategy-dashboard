"""Self-contained interactive research report for the fixed QQQ/TQQQ transfer."""
import json

import pandas as pd
from plotly.offline import get_plotlyjs

from qqq_transfer import OUT, REPORT, INITIAL


def main():
    data={key:json.loads(pd.read_csv(OUT/(key+'.csv')).to_json(orient='records',force_ascii=False))
          for key in ('summary','periods','annual','segments','stress')}
    data['design']=json.loads((OUT/'design.json').read_text(encoding='utf-8'))
    data['audit']=json.loads((OUT/'verification.json').read_text(encoding='utf-8'))
    data['curves']={}
    for row in data['summary']:
        nav=pd.read_csv(OUT/'curves'/(row['id']+'.csv'),index_col=0)
        data['dates']=nav.index.tolist()
        data['curves'][row['id']]=(nav.equity/INITIAL).tolist()
    # Explain the actual additional execution days, rather than only signal days.
    macd=pd.read_csv(OUT/'curves'/'MACD.csv',index_col=0)
    recovery=pd.read_csv(OUT/'curves'/'RECOVERY.csv',index_col=0)
    data['extra_cash_days']=int((macd.held.eq('TQQQ')&recovery.held.eq('CASH')).sum())
    data['risk_triggers']={key:int(pd.read_csv(OUT/'curves'/(key+'_signals.csv')).state.eq('RISK_CASH_TRIGGER').sum())
                           for key in ('MACD','SMH_REFERENCE')}
    payload=json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':')).replace('</','<\\/')
    REPORT.write_text(HTML.replace('__PLOTLY__',get_plotlyjs()).replace('__DATA__',payload),encoding='utf-8')
    print(REPORT)


HTML=r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>QQQ和TQQQ·MACD急跌与恢复确认回测</title>
<style>body{margin:0;background:#f3f6fb;color:#20334d;font:15px/1.65 "Microsoft YaHei",sans-serif}main{max-width:1400px;margin:32px auto;padding:0 20px}h1{font-size:28px;margin-bottom:6px}h2{font-size:20px;margin-top:0}.card{background:white;border:1px solid #dde5f0;border-radius:12px;margin:20px 0;padding:22px}.lead{background:#e9f1ff;border-left:5px solid #477cc2;padding:20px}.muted{color:#677991}.controls{display:flex;gap:20px;flex-wrap:wrap;align-items:end}input[type=number],select{padding:7px;font:inherit;border:1px solid #b8c6d9;border-radius:5px}.picks{display:flex;flex-wrap:wrap;gap:13px;margin:15px 0}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;white-space:nowrap;font-size:14px}th,td{padding:9px 12px;border-bottom:1px solid #e2e9f3;text-align:right}th{background:#edf3fc}th:first-child,td:first-child{text-align:left}.charts{display:grid;grid-template-columns:1fr 1fr;gap:12px}.chart{height:470px}details{margin:10px 0}summary{cursor:pointer}a{color:#3269a3}.fine{font-size:13px}@media(max-width:850px){.charts{grid-template-columns:1fr}.card{padding:15px}h1{font-size:23px}}</style><script>__PLOTLY__</script></head>
<body><main><h1>QQQ和TQQQ·MACD急跌与恢复确认回测</h1><p class="muted">研究日期2026-10-04 · 行情截至2026-10-02 · 参数原样移植 · 当前看板策略未更换</p>
<div class="lead" id="conclusion"></div>
<section class="card"><h2>移植后如何判断</h2><p>SMH替换为QQQ，SOXL替换为TQQQ。基础年线、20日线、锚定峰值、放量防御、仓位和状态优先级保留。QQQ同时承担信号、防御和宏观环境判断，原来半导体与纳指之间的跨资产关系随之改变。</p>
<p>急跌避险：QQQ MACD(12,26,9)柱线&lt;0，且当天最低价相对昨日收盘下跌≥4%。两个条件收盘确认后，下一交易日开盘撤至现金；等待5个交易日，重复触发重置等待期，MACD柱线≥0且收盘≥EMA20才解除锁定。该规则无法避开触发当天已经发生的跌幅。</p>
<p>恢复确认：从QQQ/现金转入TQQQ，或提高已有TQQQ目标仓位，需要QQQ连续3日收盘≥EMA20、EMA20高于3日前、MACD柱线≥0、QQQ复权日收益20日波动≤60日波动的1.1倍。同时满足才买入或加仓，已有TQQQ目标可保留或降低。原现金锁定和QQQ防御目标继续保留。</p>
<p class="muted fine">默认单边交易成本10基点（0.1%），次日开盘、复权OHLC、可买零股、现金无息。仅在目标标的或权重变化时交易；不因状态文字变化重新配平。全历史从现金建仓，短年限展示同一条历史持仓曲线在区间内的表现。</p></section>
<section class="card"><h2>收益与回撤</h2><div class="controls"><label>区间<br><select id="period"><option>全部历史</option><option>近5年</option><option>近3年</option><option>近2年</option><option>近1年</option></select></label><label>本金<br><input id="capital" type="number" value="10000" min="1"></label><label>资金图刻度<br><select id="scale"><option value="log">对数</option><option value="linear">线性</option></select></label></div>
<p id="range" class="muted"></p><div class="scroll" id="table"></div><div id="picks" class="picks"></div><div class="charts"><div id="equity" class="chart"></div><div id="drawdown" class="chart"></div></div><p class="muted fine">本金只缩放资金曲线，不改变年化或回撤；资金单位为等额ETF账户刻度，不计人民币汇率或代币化证券与ETF之间的价格差。回撤为日终净值相对区间历史高点的跌幅。</p></section>
<section class="card"><h2>代价与稳定性</h2><p id="diagnosis"></p><div class="scroll" id="segments"></div><p>以下为自然年收益，2026仅截至10月2日的累计收益，不是年化值。全历史回撤变小并不保证每一年亏损都减少。</p><div class="scroll" id="annual"></div><p>交易成本与额外延迟执行一天的敏感性（延迟后仍是按已有收盘信号在开盘成交）：</p><div class="scroll" id="stress"></div></section>
<section class="card"><h2>检查与使用范围</h2><p id="checks"></p><p>这是固定参数迁移检验，没有搜索或选择QQQ专用参数；此前已经查看过历史，分段检查不能视为真正未知的样本外证明。现有规则未在QQQ/TQQQ上同时提高收益和降低回撤，且恢复确认版全历史回撤仍高于约50%的目标。</p><p>不含税、汇率、买卖差价、流动性限制及现金利息，不代表币安产品实盘回报。行情、私人策略、导出代码和报告仅保存于本机。</p>
<p><a href="strategies/QQQ和TQQQ MACD＋4%急跌＋恢复确认.py" download>下载恢复确认版代码</a> · <a href="strategies/QQQ和TQQQ MACD＋4%急跌.py" download>下载MACD急跌版代码</a> · <a href="periods.csv" download>下载年限结果CSV</a></p><details><summary>实验规则及输入校验</summary><pre id="design"></pre></details></section></main>
<script>
const D=__DATA__;const $=id=>document.getElementById(id);const pct=x=>(x*100).toFixed(2)+'%';const num=x=>x.toFixed(2);const esc=x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const main=D.summary.find(r=>r.id==='RECOVERY'),base=D.summary.find(r=>r.id==='MACD');
$('conclusion').innerHTML=`<b>直接移植后，恢复确认降低回撤，同时减少收益。</b><br>全历史恢复确认版：年化 ${pct(main.annualized_return)}、最大回撤 ${pct(main.max_drawdown)}；MACD急跌版：${pct(base.annualized_return)}、${pct(base.max_drawdown)}。年化降低 ${(100*(base.annualized_return-main.annualized_return)).toFixed(2)} 个百分点，最大回撤降低 ${(100*(base.max_drawdown-main.max_drawdown)).toFixed(2)} 个百分点。`;
const recent=id=>D.periods.find(r=>r.id===id&&r.period==='近1年'),year2022=id=>D.annual.find(r=>r.id===id&&r.year===2022);
$('diagnosis').textContent=`恢复确认比MACD急跌版多持有现金 ${D.extra_cash_days} 个实际交易日，减少TQQQ参与。移植后的MACD急跌触发状态出现 ${D.risk_triggers.MACD} 日，SMH原版为 ${D.risk_triggers.SMH_REFERENCE} 日（含重复触发）；相同4%阈值在两种基础资产上触发频率不同。最近一年恢复确认年化 ${pct(recent('RECOVERY').annualized_return)}，MACD急跌版 ${pct(recent('MACD').annualized_return)}；2022年恢复确认收益 ${pct(year2022('RECOVERY').total_return)}，MACD版 ${pct(year2022('MACD').total_return)}，显示错过反弹和退出时机的代价。`;
$('checks').textContent=`${D.audit.ledger_audits.length} 组成本/延迟曲线与冻结单资产引擎逐日核对；其中15组QQQ/TQQQ曲线同时与看板投资组合引擎核对净值、现金、费用。3份QQQ移植代码及SMH参考均通过工作进程与截断重算审计。当前启用策略未改变，新策略未保存到看板策略列表。`;
$('design').textContent=JSON.stringify(D.design,null,2);
for(const row of D.summary)$('picks').insertAdjacentHTML('beforeend',`<label><input type="checkbox" value="${row.id}" ${['RECOVERY','MACD','QQQ_HOLD','TQQQ_HOLD'].includes(row.id)?'checked':''}>${esc(row.name)}</label>`);
function table(id,heads,rows){$(id).innerHTML='<table><thead><tr>'+heads.map(h=>'<th>'+h+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(v=>'<td>'+v+'</td>').join('')+'</tr>').join('')+'</tbody></table>'}
function render(){const period=$('period').value,capital=Math.max(1,Number($('capital').value)||10000),selected=new Set([...$('picks').querySelectorAll('input:checked')].map(i=>i.value));const rows=D.summary.map(r=>({...r,...D.periods.find(m=>m.id===r.id&&m.period===period)}));const first=rows[0];$('range').textContent=`${first.first_session} 至 ${first.end_session}，${first.sessions} 个交易日，历史连续持仓口径。`;
table('table',['策略','年化','最大回撤','累计收益','Sharpe（无风险利率0）','Calmar','期末本金'],rows.map(r=>[esc(r.name),pct(r.annualized_return),pct(r.max_drawdown),pct(r.total_return),num(r.sharpe),num(r.calmar),(r.multiple*capital).toLocaleString('zh-CN',{maximumFractionDigits:0})]));
const eq=[],dd=[];for(const r of rows){if(!selected.has(r.id))continue;const begin=D.dates.indexOf(r.first_session),end=D.dates.indexOf(r.end_session),raw=D.curves[r.id],anchor=r.baseline_close?raw[D.dates.indexOf(r.baseline_close)]:1,x=[r.baseline_close||'2016-12-30',...D.dates.slice(begin,end+1)],y=[1,...raw.slice(begin,end+1).map(v=>v/anchor)];let peak=1;const draw=y.map(v=>{peak=Math.max(peak,v);return 100*(v/peak-1)});const style={name:r.name,type:'scatter',mode:'lines',line:{width:r.id==='RECOVERY'?3:1.6}};eq.push({...style,x,y:y.map(v=>v*capital)});dd.push({...style,x,y:draw});}
const layout={margin:{l:65,r:15,t:50,b:100},paper_bgcolor:'white',plot_bgcolor:'white',font:{family:'Microsoft YaHei',size:12},legend:{orientation:'h',y:-.22},hovermode:'x unified',xaxis:{showgrid:false},yaxis:{gridcolor:'#edf1f7'}};Plotly.react('equity',eq,{...layout,title:'日线本金对比',yaxis:{...layout.yaxis,type:$('scale').value}},{responsive:true,displaylogo:false});Plotly.react('drawdown',dd,{...layout,title:'区间日终回撤',yaxis:{...layout.yaxis,ticksuffix:'%'}},{responsive:true,displaylogo:false});
table('segments',['策略','区间','年化','最大回撤'],D.segments.filter(r=>selected.has(r.id)).map(r=>[esc(D.summary.find(s=>s.id===r.id).name),r.segment,pct(r.annualized_return),pct(r.max_drawdown)]));const keys=D.summary.filter(r=>selected.has(r.id));table('annual',['年份',...keys.map(r=>esc(r.name))],Array.from({length:10},(_,i)=>2017+i).map(year=>[year===2026?'2026年内':year,...keys.map(k=>pct(D.annual.find(r=>r.year===year&&r.id===k.id).total_return))]));table('stress',['策略','单边成本/基点','额外延迟/交易日','全历史年化','最大回撤'],D.stress.filter(r=>selected.has(r.id)).map(r=>[esc(D.summary.find(s=>s.id===r.id).name),r.cost_bps,r.extra_lag,pct(r.annualized_return),pct(r.max_drawdown)]));}
for(const id of ['period','capital','scale','picks'])$(id).addEventListener('change',render);render();
</script></body></html>'''


if __name__=='__main__':main()
