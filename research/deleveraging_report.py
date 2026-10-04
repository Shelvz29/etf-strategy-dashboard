"""Offline, interactive report for the fixed two-stage SOXL risk experiment."""
import json
from pathlib import Path

import pandas as pd
from plotly.offline import get_plotlyjs

from deleveraging_study import OUT, PRIMARY

REPORT=OUT/'2026-10-04-SMH和SOXL提前减仓与恢复确认策略回测.html'


def records(frame):return json.loads(frame.to_json(orient='records',force_ascii=False))


def main():
    rows=pd.read_csv(OUT/'results.csv')
    design=json.loads((OUT/'design.json').read_text(encoding='utf-8'))
    audit=json.loads((OUT/'verification.json').read_text(encoding='utf-8'))
    curves={};dates=[]
    for key in rows.id:
        nav=pd.read_csv(OUT/'curves'/(key+'.csv'),index_col=0)
        dates=nav.index.tolist();curves[key]=(nav.equity/100_000).round(10).tolist()
    data={'rows':records(rows),'periods':records(pd.read_csv(OUT/'periods.csv')),
        'segments':records(pd.read_csv(OUT/'segments.csv')),'annual':records(pd.read_csv(OUT/'annual.csv')),
        'stress':records(pd.read_csv(OUT/'execution_stress.csv')),'design':design,'audit':audit,
        'dates':dates,'curves':curves}
    payload=json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':')).replace('</','<\\/')
    REPORT.write_text(HTML.replace('__PLOTLY__',get_plotlyjs()).replace('__DATA__',payload),encoding='utf-8')
    print(REPORT)


HTML=r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SMH和SOXL提前减仓与恢复确认策略回测</title>
<style>body{background:#f4f7fc;color:#18304c;font:15px/1.65 "Microsoft YaHei",sans-serif;margin:0}main{max-width:1460px;margin:30px auto;padding:0 22px}h1{font-size:28px;margin-bottom:5px}h2{font-size:20px;margin:0 0 12px}.card{background:white;border:1px solid #dce5ef;border-radius:12px;padding:23px;margin:19px 0}.muted{color:#667891}.lead{background:#e9f2ff;border-left:5px solid #3b75bc;padding:18px}.warn{background:#fff8e9;border-left:4px solid #e5b454;padding:13px}.controls{display:flex;gap:18px;flex-wrap:wrap;align-items:end}input[type=number],select{font:inherit;padding:8px;border:1px solid #adbed1;border-radius:5px}.picks{display:flex;flex-wrap:wrap;gap:9px;margin:15px 0}.picks label{padding:5px 9px;background:#f0f5fc;border-radius:5px}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;white-space:nowrap;font-size:14px}td,th{padding:9px 11px;text-align:right;border-bottom:1px solid #e4eaf2}td:first-child,th:first-child{text-align:left}th{background:#edf3fc}.base{background:#f0f5fd}.good{color:#09754c}.bad{color:#b93d3d}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.chart{height:480px}.fine{font-size:13px}a{color:#2767a8}details{margin:12px 0}summary{cursor:pointer;color:#2767a8}@media(max-width:850px){.grid{grid-template-columns:1fr}.card{padding:15px}h1{font-size:23px}}</style><script>__PLOTLY__</script></head>
<body><main><h1>SMH和SOXL提前减仓与恢复确认策略回测</h1><p class="muted">研究日期 2026-10-04 · 行情截至 2026-10-02 · 收盘判断、次日开盘成交 · 当前看板策略未更换</p>
<div class="lead" id="summary"></div>
<section class="card"><h2>新策略怎样运行</h2><p>保留现有 SMH/SOXL 基础状态、峰值和 MACD＋4% 急跌现金锁定。在基础目标为 SOXL 时额外限制风险；原来要求现金时继续现金，原来要求 SMH 时保留该目标。剩余资金持有无息现金。</p>
<div class="scroll"><table><thead><tr><th>模块</th><th>判断与行为</th></tr></thead><tbody>
<tr><td>波动率减仓</td><td>SOXL复权日收益的20日标准差×√252；目标仓位≤目标波动率/该波动率，且不超过基础仓位。</td></tr>
<tr><td>趋势恶化减仓</td><td>SMH收盘低于50日均线且均线较5日前下降；或SMH与QQQ都在50日线下、QQQ均线下降。主方案SOXL上限25%。</td></tr>
<tr><td>深跌恢复确认</td><td>基础为DEEP_ATTACK但恢复条件未满足时，继续现金，不因价格已跌很多直接抄底。</td></tr>
<tr><td>重新加仓确认</td><td>由其他资产/现金转入SOXL，或提高现有SOXL目标仓位，均需恢复确认；已有目标可保留或降低。</td></tr>
<tr><td>恢复条件</td><td>SMH收盘≥EMA20，EMA20高于3日前，MACD(12,26,9)柱线≥0，20日波动≤60日波动的1.1倍，连续站上EMA20达3日。</td></tr>
<tr><td>降低频繁调仓</td><td>受限制目标按5个百分点向下取整；原99%目标未被限制时保持99%。目标未变不每日配平，实际权重会随价格漂移。</td></tr>
</tbody></table></div><p class="fine muted">主方案 C40 同时使用以上模块，波动率目标40%。另测试单模块、不同波动目标及附近周期。第二阶段根据首轮观察追加“恢复确认＋固定SOXL上限”50/75/90%，不将其冒充首轮事前方案。</p>
<div class="warn">这些规则是风险管理代理，不直接观测或证明美股正在去杠杆。“提前”指在后续更大跌幅之前减仓，首次突然下跌和次日跳空仍可能承受。动态仓位公式也不能保证未来波动率或最大回撤等于目标值。</div></section>
<section class="card"><h2>收益与风险比较</h2><div class="controls"><label>统计区间<br><select id="period"><option>全部历史</option><option>近1年</option><option>近2年</option><option>近3年</option><option>近5年</option><option>训练2017—2021</option><option>验证2022—2024</option><option>后段2025—2026</option></select></label><label>图表本金<br><input id="capital" type="number" value="10000" min="1" step="1000"></label><label>排序<br><select id="sort"><option value="calmar">Calmar 高到低</option><option value="annualized_return">年化高到低</option><option value="max_drawdown">回撤低到高</option></select></label><label>净值坐标<br><select id="scale"><option value="log">对数</option><option value="linear">线性</option></select></label></div><div class="picks" id="picks"></div><p id="range" class="muted"></p><p class="fine muted">表格显示全部30个方案，勾选控制图表。BASE 始终显示；第一阶段25项（含现有策略基准及固定仓位参照）、第二阶段3项、买入持有2项。近年及分段为连续历史持仓，区间本金重标定，未重新初始化状态。人民币汇率未计入。</p><div class="scroll" id="table"></div><div class="grid"><div id="equity" class="chart"></div><div id="drawdown" class="chart"></div></div></section>
<section class="card"><h2>时间分段与训练选择</h2><p id="selection"></p><div class="scroll" id="segments"></div><p class="warn">训练选择仅用2017—2021年数据，在第一阶段候选中选择回撤≤50%且年化最高的方案，随后检查2022—2024与2025—2026。已有研究看过这些历史，且第二阶段由首轮结果启发，因此这里只能称时间隔离检验，不能称真正未知的样本外实盘验证。图表期内回撤会在区间起点重新计峰，不等同于跨区间延续的账户回撤。</p></section>
<section class="card"><h2>逐年收益</h2><p class="fine muted">展示所勾选方案的自然年收益；2026为截至10月2日的年内收益，不是全年预测。2017按1月3日开盘建仓。</p><div class="scroll" id="annual"></div></section>
<section class="card"><h2>成本与成交延迟</h2><p class="fine muted">这里均为2017年以来完整区间，不随上方统计区间切换。单边成本25/50基点，或10基点但额外延迟一个交易日；差值与同样成本、延迟下的BASE比较。回撤差为负表示改善。</p><div class="scroll" id="stress"></div></section>
<section class="card"><h2>额外风险与执行指标</h2><p class="fine muted">以下均为完整区间，显示所勾选方案；“交易日数”指当天有费用的日数，换仓买卖两笔仍计为一天。ES95显示最差5%交易日的平均损失。</p><div class="scroll" id="risk"></div></section>
<section class="card"><h2>规则与策略代码</h2><div id="rules"></div><p>本报告同目录的 strategies 文件夹包含完整可编辑策略代码，可复制到看板策略编辑框保存为新策略；本次没有写入私人策略列表或更换启用策略。新状态包括波动率减仓、趋势恶化减仓、深跌等待恢复、等待恢复加仓和固定仓位限制，代码内附状态说明。</p></section>
<section class="card"><h2>如何判断是否值得采用</h2><p>若固定减仓已取得类似结果，复杂指标未必值得增加。重点比较长期回撤是否满足约50%的目标、2022等困难年份是否改善、恢复阶段是否错失大量收益，以及交易成本升高后结论是否保留。不能把全部历史排序第一或最近一年高收益视为未来保证。</p><p>Calmar=年化/最大回撤；夏普按252个交易日、无风险利率0计算。日亏损ES95是最差5%日收益的平均亏损。平均名义敞口把SOXL按3倍、SMH按1倍计算，只是敞口近似。最长未创新高为日终净值低于历史最高的连续交易日，未含期末尚未恢复的额外未来时间。</p></section>
<section class="card"><h2>口径与验证</h2><ul><li>2017-01-03至2026-10-02，同一组已确认QQQ/SMH/SOXL日线。复权OHLC表示分红再投资与拆股后的总收益账户，不是实物份额与股息到账账本。</li><li>标准单边综合交易成本0.10%，买卖均收费；不含税、汇率、整数份额、代币化证券与ETF价格偏离、结算及可交易性差异。</li><li>趋势、EMA、MACD沿用原始收盘口径，波动率使用复权日收益。信号只使用当日及之前信息；收盘信号下一交易日开盘执行。</li><li>未新增VIX、信用利差、FINRA、NFCI或市场广度数据。缺少当时发布版本与完整成分股时，使用这些数据可能引入发布时间或幸存者偏差。</li><li id="checks"></li><li>完整参数、输入哈希、逐日信号和净值、分段、逐年与成本数据均保存在同目录。详细结果和私人导出代码不进入公开仓库；本次不生成发布更新日志、不推送GitHub。</li></ul></section>
</main><script>const D=__DATA__;
const $=id=>document.getElementById(id),pct=v=>v==null?'—':(v*100).toFixed(2)+'%',num=v=>v==null?'—':Number(v).toFixed(2),pp=v=>(v>0?'+':'')+(v*100).toFixed(2),esc=v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
const defaults=new Set(['ENTRY','F75G','F90G','C40','SMH_HOLD']);for(const r of D.rows){if(r.id==='BASE')continue;$('picks').insertAdjacentHTML('beforeend',`<label><input type="checkbox" value="${r.id}" ${defaults.has(r.id)?'checked':''}> ${esc(r.name)}</label>`)}
const baseline=D.rows.find(r=>r.id==='BASE'),primary=D.rows.find(r=>r.id===D.audit.primary),entry=D.rows.find(r=>r.id==='ENTRY'),best50=D.rows.filter(r=>r.role!=='买入持有'&&r.max_drawdown<=.5).sort((a,b)=>b.annualized_return-a.annualized_return)[0];
$('summary').innerHTML=`<b>降低回撤有效，但没有固定承诺同时提高年化。</b><br>基准 ${pct(baseline.annualized_return)} / ${pct(baseline.max_drawdown)}；主组合 C40 ${pct(primary.annualized_return)} / ${pct(primary.max_drawdown)}；单独恢复确认 ${pct(entry.annualized_return)} / ${pct(entry.max_drawdown)}。全历史回撤≤50%方案中，年化最高的是 ${esc(best50.name)}：${pct(best50.annualized_return)} / ${pct(best50.max_drawdown)}。这是事后比较，不代表统计显著或未来最优。`;
$('selection').textContent=`第一阶段训练规则选出 ${D.rows.find(r=>r.id===D.audit.training_selected).name}（${D.audit.training_selected}）。以下与预先指定主方案、基准及所勾选候选共同比较；无需只看“获胜者”。`;
$('checks').textContent=`${D.audit.independent_engine_checks.length}组实际历史曲线与冻结执行引擎逐日核对；${D.audit.actual_prefix_checks}组截断重算核对过去信号；${D.audit.exported_worker_checks}份完整导出代码通过看板子进程及其前缀审计。另有5项单元测试覆盖减仓、现金锁定、恢复边界和未来数据隔离。`;
$('rules').innerHTML=D.design.candidates.filter(r=>r.id!=='BASE').map(r=>`<details><summary>${esc(r.id+' · '+r.name)}（第${r.phase}阶段）</summary><pre>${esc(JSON.stringify(r.rules,null,2))}</pre></details>`).join('');
function table(id,heads,rows){$(id).innerHTML='<table><thead><tr>'+heads.map(h=>'<th>'+h+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(v=>'<td>'+v+'</td>').join('')+'</tr>').join('')+'</tbody></table>'}
function render(){const period=$('period').value,capital=Math.max(1,Number($('capital').value)||10000),sort=$('sort').value,selected=new Set(['BASE']);
for(const input of $('picks').querySelectorAll('input:checked'))selected.add(input.value);
const segmented=period.includes('—'),source=segmented?D.segments:D.periods;let rows=D.rows.map(r=>{const m=source.find(m=>m.id===r.id&&(segmented?m.segment===period:m.period===period));return {...r,...m}});const base=rows.find(r=>r.id==='BASE');
rows.sort((a,b)=>a.id==='BASE'?-1:b.id==='BASE'?1:sort==='max_drawdown'?a[sort]-b[sort]:b[sort]-a[sort]);
$('range').textContent=`${base.first_session} — ${base.end_session}，${base.sessions} 个交易日。排序用于查看历史结果，未参与第一阶段训练选择。`;
table('table',['策略','年化','最大回撤','年化差/pp','回撤差/pp','Sharpe','Calmar','期末本金','阶段/身份'],rows.map(r=>[esc(r.id+' · '+r.name),pct(r.annualized_return),pct(r.max_drawdown),pp(r.annualized_return-base.annualized_return),pp(r.max_drawdown-base.max_drawdown),num(r.sharpe),num(r.calmar),(r.multiple*capital).toLocaleString('zh-CN',{maximumFractionDigits:0}),r.training_selected?'第一阶段训练选择':r.role==='买入持有'?'买入持有':r.phase===2?'第二阶段追加':r.role]));
const eq=[],dd=[];for(const r of rows){if(!selected.has(r.id))continue;const begin=D.dates.indexOf(r.first_session),end=D.dates.indexOf(r.end_session),raw=D.curves[r.id],anchor=r.baseline_close?raw[D.dates.indexOf(r.baseline_close)]:1,x=D.dates.slice(begin,end+1),y=raw.slice(begin,end+1).map(v=>v/anchor);let peak=1;const draw=y.map(v=>{peak=Math.max(peak,v);return (v/peak-1)*100});const name=r.id;eq.push({x,y:y.map(v=>v*capital),name,type:'scatter',mode:'lines',line:{width:r.id==='BASE'?3:1.6},hovertemplate:'%{x}<br>%{y:,.0f}<extra>%{fullData.name}</extra>'});dd.push({x,y:draw,name,type:'scatter',mode:'lines',line:{width:r.id==='BASE'?3:1.6},hovertemplate:'%{x}<br>%{y:.2f}%<extra>%{fullData.name}</extra>'})}
const layout={margin:{l:65,r:15,t:50,b:65},paper_bgcolor:'white',plot_bgcolor:'white',font:{family:'Microsoft YaHei',size:12},legend:{orientation:'h',y:-.2},hovermode:'x unified',xaxis:{showgrid:false},yaxis:{gridcolor:'#edf2f8'}};
Plotly.react('equity',eq,{...layout,title:'日线本金对比',yaxis:{...layout.yaxis,type:$('scale').value}},{responsive:true,displaylogo:false});Plotly.react('drawdown',dd,{...layout,title:'日终最大回撤过程',yaxis:{...layout.yaxis,ticksuffix:'%'}},{responsive:true,displaylogo:false});
const keep=new Set([...selected,D.audit.training_selected]);table('segments',['策略','区间','年化','最大回撤','Calmar'],D.segments.filter(r=>keep.has(r.id)).map(r=>[r.id,r.segment,pct(r.annualized_return),pct(r.max_drawdown),num(r.calmar)]));
const keys=D.rows.filter(r=>selected.has(r.id)).map(r=>r.id);table('annual',['年份',...keys],Array.from({length:10},(_,i)=>2017+i).map(year=>[year===2026?'2026年内':year,...keys.map(id=>pct(D.annual.find(r=>r.id===id&&r.year===year).total_return))]));
table('stress',['策略','单边成本/基点','额外延迟/日','年化','最大回撤','年化差/pp','回撤差/pp'],D.stress.filter(r=>keep.has(r.id)).map(r=>[r.id,r.cost_bps,r.extra_lag,pct(r.annualized_return),pct(r.max_drawdown),pp(r.cagr_change),pp(r.drawdown_change)]));
table('risk',['策略','最差日亏损','日亏损ES95','最长未创新高/交易日','发生交易的日数','平均名义敞口','现金日比例','SOXL日比例'],D.rows.filter(r=>selected.has(r.id)).map(r=>[r.id,pct(r.worst_day),pct(r.es95_daily),r.longest_underwater_sessions,r.trade_days,num(r.mean_nominal_exposure)+'倍',pct(r.cash_fraction),pct(r.soxl_fraction)]));
}
for(const id of ['period','capital','sort','scale','picks'])$(id).addEventListener('change',render);render();
</script></body></html>'''


if __name__=='__main__':main()
