"""Portable offline HTML and Chinese Markdown, with actual data coverage."""
import html
import json
import pandas as pd
from plotly.offline import get_plotlyjs
from six_factor_data import OUT
from six_factor_rules import FACTORS,LABELS

REPORT=OUT/'2026-10-05-六类风险分级与恢复确认策略回测.html'


def main():
    data={s:json.loads(pd.read_csv(OUT/(s+'.csv')).to_json(orient='records',force_ascii=False)) for s in
          ('summary','periods','annual','segments','execution_stress','publication_lag_stress','coverage','associations')}
    data['design']=json.loads((OUT/'design.json').read_text(encoding='utf-8'))
    data['audit']=json.loads((OUT/'verification.json').read_text(encoding='utf-8'))
    data['labels']=LABELS;data['curves']={}
    for row in data['summary']:
        nav=pd.read_csv(OUT/'curves'/(row['id']+'.csv'),index_col=0)
        data['dates']=nav.index.tolist();data['curves'][row['id']]=(nav.equity/100000).tolist()
    table=pd.read_csv(OUT/'summary.csv');base=table.loc[table.id.eq('BASE')].iloc[0]
    qualified=table.loc[table.max_drawdown.le(.5)&~table.id.isin(['F90','F75','F50','BASE','UNKNOWN50'])]
    winner=qualified.sort_values('annualized_return',ascending=False).iloc[0] if len(qualified) else None
    lines=['# 六类风险分级与恢复确认策略回测','',
        'SMH/SOXL，2017-01-03至2026-10-02，100%进攻基础版本，单边成本10基点，收盘信号次日开盘执行。',
        f'基准：年化{base.annualized_return:.2%}，最大回撤{base.max_drawdown:.2%}。',
        (f'完整历史回撤≤50%动态候选中的年化最高方案：{winner["name"]}，年化{winner.annualized_return:.2%}，回撤{winner.max_drawdown:.2%}。这是事后描述，不是未知样本外选型。' if winner is not None else '未找到全历史最大回撤≤50%的指标择时方案；不把固定减仓和缺失即减仓当作六因素择时成功。'),'',
        f'仅前段选出的方案：{data["audit"]["selected_by_early_period"]}；六类同时有历史值的交易日占比{data["audit"]["all_six_known_fraction"]:.2%}。',
        '盈利预测报告存在缺口；仅用同季度且45日内的已公布预测修正。缺失不标为正常，默认只按已知分数下界采取额外限制。另比较缺失上限50%、仅全数据日限制两个方案。',
        f'追加滚动前瞻EPS代理版本，六类共同覆盖{data["audit"]["proxy_all_six_known_fraction"]:.2%}。代理=上一交易日GSPC价格/报告PE，日期配对为假设，四舍五入与滚动预测窗口有误差，非同财政期间预测修正；不参与第一阶段选型。','',
        '|方案|年化收益|最大回撤|Sharpe|Sortino|Calmar|日损失ES95|','|---|---:|---:|---:|---:|---:|---:|']
    for _,r in table.sort_values('calmar',ascending=False).iterrows():
        lines.append(f'|{r["name"]}|{r.annualized_return:.2%}|{r.max_drawdown:.2%}|{r.sharpe:.2f}|{r.sortino:.2f}|{r.calmar:.2f}|{r.daily_es95:.2%}|')
    lines+=['','估值／盈利是S&P500环境代理，非半导体行业共识；宽度为RSP/SPY，集中为SMH/XSD结构分化，非真实持仓集中度。OFR当前历史含修订，未获得逐日首次发布库；首次发布前设为未知。',
        '原现金锁定保留。目标不变不每日配平，实际权重会漂移。当前策略未导入或更换，冻结代码不变，未推送GitHub。',
        '此前已经查看过该市场历史，固定阈值及分段测试不构成真正未知样本外。无法躲过信号触发当天下跌，不保证未来回撤≤50%。现金无息，不含税、汇率或代币化证券价差。']
    (OUT/'结果说明.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    payload=json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':')).replace('</','<\\/')
    REPORT.write_text(HTML.replace('__PLOTLY__',get_plotlyjs()).replace('__DATA__',payload),encoding='utf-8')
    print(REPORT)


HTML=r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>六类风险分级回测</title><style>
body{background:#f3f6fb;color:#20324a;font:15px/1.7 "Microsoft YaHei",sans-serif;margin:0}main{max-width:1450px;margin:30px auto;padding:0 24px}h1{font-size:27px}h2{font-size:21px;margin-top:0}.card{background:#fff;border:1px solid #dae2ec;border-radius:12px;padding:24px;margin:20px 0}.lead{background:#eaf3ff;border-left:5px solid #2470aa;padding:20px}.muted{color:#627187}.controls,.picks{display:flex;flex-wrap:wrap;gap:13px}.picks label{border:1px solid #dbe4ee;padding:7px;border-radius:5px}input,select{font:inherit;padding:5px}table{border-collapse:collapse;width:100%;white-space:nowrap;font-size:13px}th,td{text-align:right;border-bottom:1px solid #e0e6ef;padding:9px}th{background:#edf2f8}th:first-child,td:first-child{text-align:left}.scroll{overflow:auto}.charts{display:grid;grid-template-columns:1fr 1fr}.chart{height:480px}a{color:#25689c}pre{white-space:pre-wrap;word-break:break-word}@media(max-width:850px){.charts{grid-template-columns:1fr}.card{padding:15px}}</style><script>__PLOTLY__</script></head><body><main>
<h1>六类风险分级＋MACD急跌与恢复确认策略</h1><p class="muted">SMH／SOXL · 2017-01-03—2026-10-02 · 基础进攻仓100% · 首轮22个方案＋追加3个盈利代理方案</p><div class="lead" id="conclusion"></div>
<section class="card"><h2>指标、风险等级与数据边界</h2><div class="scroll"><table><tr><th>因素／量化指标</th><th>关注（1）</th><th>较高（2）</th><th>严重（3）</th><th>边界</th></tr>
<tr><td>估值：S&P500前瞻12月PE</td><td>≥22</td><td>≥25</td><td>≥28</td><td>真实日期FactSet归档，最长45日有效；市场代理</td></tr>
<tr><td>宽度：RSP/SPY复权比率63日变化</td><td>≤−3%</td><td>≤−6%</td><td>≤−9%</td><td>RSP低于MA200另加1级，上限3；非涨跌家数</td></tr>
<tr><td>盈利预期：当季EPS自季度开始修正</td><td>≤−2%</td><td>≤−5%</td><td>≤−10%</td><td>同一季度前瞻预测，窗口1—3月不等；45日有效</td></tr>
<tr><td>信用：OFR信用压力贡献／20日变化</td><td>≥0／≥0.5</td><td>≥1／≥1</td><td>≥2／≥2</td><td>两者取最高等级；非高收益债利差</td></tr>
<tr><td>流动性：OFR融资压力贡献／20日变化</td><td>≥0／≥0.3</td><td>≥0.5／≥0.6</td><td>≥1／≥1.2</td><td>融资压力代理，非央行净流动性</td></tr>
<tr><td>集中代理：SMH/XSD复权比率63日变化</td><td>≥8%</td><td>≥8%且SMH&lt;MA50</td><td>≥15%且SMH20日≤−10%</td><td>结构分化；非真实历史前十大权重</td></tr></table></div>
<p>未触发为正常（0）；数据缺失或过期为未知（灰色），保留NaN。信用／流动性取最高等级，宽度／集中代理取最高等级，再加估值和盈利等级，得到已知风险分数下界0—12，不把缺失数据改为正常，也不按已知因素数量放大分数。</p><p>追加3个滚动前瞻EPS代理方案：EPS代理=上一交易日GSPC收盘÷报告前瞻PE，比较约前30—44／90—104自然日的报告，任一窗口下降≥2%／5%／10%对应等级1／2／3。报告PE对应上一交易日价格是研究假设，PE取整和滚动预测窗口存在误差；这不是同财政期间分析师预测修正。追加方案在首轮结果后提出，单独标注且不参与第一阶段选型。</p>
<p>均衡方案：分数≥3／5／7／9时，SOXL目标上限75%／50%／25%／0%；进取方案为90%／75%／50%／25%；严格为50%／25%／0%／0%。单因素等级1／2／3对应75%／50%／25%。原现金锁定保留，风险解除后加仓仍要求恢复确认。只有“覆盖SMH”方案限制防御ETF。</p><p class="muted">阈值是固定研究假设。预测修正的1—3月窗口不等，不能当成固定1月修正率；只使用明确EPS估计修正，不将已实现EPS或盈利增长率修正混入。</p>
<div class="scroll" id="coverage"></div><p id="coverageNote"></p></section>
<section class="card"><h2>收益、回撤与每日资金曲线</h2><div class="controls"><label>区间 <select id="period"><option>全部历史</option><option>近5年</option><option>近3年</option><option>近2年</option><option>近1年</option></select></label><label>本金 <input id="capital" type="number" value="10000" min="1"></label><label>刻度 <select id="scale"><option value="log">对数</option><option value="linear">线性</option></select></label></div><p id="range"></p><div id="table" class="scroll"></div><p class="muted">按所选区间Calmar排序，仅作描述；固定仓位参照有助于区分择时与减少杠杆暴露。Sharpe按无风险利率0计算。近年沿用历史连续持仓，从前一交易日净值归一化。</p><div class="picks" id="picks"></div><div class="charts"><div id="equity" class="chart"></div><div id="drawdown" class="chart"></div></div></section>
<section class="card"><h2>阶段与成本敏感性（随勾选更新）</h2><div class="scroll" id="segments"></div><p>日损失和连续未创新高交易日：</p><div class="scroll" id="risk"></div><p>单边成本25／50基点、额外一天成交延迟：</p><div class="scroll" id="stress"></div><p>OFR与预测报告再延迟5交易日（ETF收盘指标不额外延迟）：</p><div class="scroll" id="lag"></div></section>
<section class="card"><h2>统计关联检查</h2><p>因变量为SMH未来20交易日复权收益；指标等级≥2为风险标志，控制过去20日收益与波动，Newey–West/HAC滞后20，并对6项做BH修正。缺失观察排除，各因素样本不同。负向且q&lt;0.05只说明样本关联，不证明因果，也不代表组合交易获利；少数危机事件、阈值探索和结构变化仍有影响。</p><div class="scroll" id="associations"></div></section>
<section class="card"><h2>可用时点与核对记录</h2><p>日线指标收盘确认，次日开盘成交，单边成本10基点，可买零股，复权OHLC隐含分红再投资。目标不变不每日配平，实际仓位会随价格漂移。FactSet使用真实日期归档，报告日期后的首个NYSE交易日收盘才视为可用；OFR观测延后2个NYSE交易日，2017-10-26前为未知。</p><p>OFR为当前下载历史，2022—2023部分历史曾修订，未获得逐日首次公布库。固定滞后和历史截断检查不能消除历史数据修订风险。此前已看过市场历史，2017—2021选型及2022—2024／2025以后检查不是真正未知样本外。阈值±20%、缺失处理、固定仓位和成本检查均单列，未按完整历史追调参数。</p><p>现金无息，不含税、汇率、代币化证券价差及交易时段差异。日线不能躲过触发当天已发生的下跌，不能保证未来最大回撤≤50%。当前看板策略未导入或更换，冻结引擎未修改，未推送GitHub。</p><p id="checks"></p><p>来源：<a href="https://insight.factset.com/topic/earnings">FactSet报告</a> · <a href="https://www.financialresearch.gov/financial-stress-index/">OFR压力指数</a> · <a href="https://www.financialresearch.gov/press-releases/files/FSI_factsheet.pdf">OFR历史修订说明</a></p><p><a href="summary.csv">全历史表</a> · <a href="periods.csv">近年表</a> · <a href="coverage.csv">覆盖明细</a> · <a href="forecast_archive.json">预测报告来源与哈希</a> · <a href="features.csv">逐日指标</a> · <a href="结果说明.md">文字说明</a></p><details><summary>完整实验约定与验证</summary><pre id="design"></pre></details></section></main><script>
const D=__DATA__,$=s=>document.getElementById(s),pct=x=>x==null?'未知':(100*x).toFixed(2)+'%',num=x=>x==null?'—':Number(x).toFixed(2),esc=x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function table(id,heads,rows){$(id).innerHTML='<table><tr>'+heads.map(h=>'<th>'+esc(h)+'</th>').join('')+'</tr>'+rows.map(r=>'<tr>'+r.map(v=>'<td>'+v+'</td>').join('')+'</tr>').join('')+'</table>'}
const base=D.summary.find(r=>r.id==='BASE'),main=D.summary.find(r=>r.id==='BALANCED'),selected=D.summary.find(r=>r.training_selected),under=D.summary.filter(r=>r.max_drawdown<=.5&&!['BASE','F90','F75','F50','UNKNOWN50'].includes(r.id)).sort((a,b)=>b.annualized_return-a.annualized_return),best=under[0];
$('conclusion').textContent=`全历史基准年化${pct(base.annualized_return)}／最大回撤${pct(base.max_drawdown)}；均衡六因素${pct(main.annualized_return)}／${pct(main.max_drawdown)}。${best?`事后回撤≤50%候选中年化最高：“${best.name}” ${pct(best.annualized_return)}／${pct(best.max_drawdown)}。`:'没有动态方案同时达到全历史回撤≤50%。'}只由2017—2021选出的方案为“${selected.name}”，全历史${pct(selected.annualized_return)}／${pct(selected.max_drawdown)}。`;
const years=Array.from({length:10},(_,i)=>2017+i);table('coverage',['因素',...years.map(y=>y===2026?'2026年内':y)],Object.keys(D.labels).map(f=>[D.labels[f],...years.map(y=>pct(D.coverage.find(r=>r.factor===f&&r.year===y).known_fraction))]));
$('coverageNote').textContent=`已核对${D.audit.forecast_reports}份PE快照、${D.audit.eps_reports}份EPS修正快照；六类同时有历史值的交易日占${pct(D.audit.all_six_known_fraction)}，滚动EPS代理版占${pct(D.audit.proxy_all_six_known_fraction)}。完整历史结果是可获得信息下的策略，并非六项指标每天都有值。缺失时不新增限制、仅完整数据日新增限制、缺失时上限50%分别对比。`;
$('checks').textContent=`${D.audit.frozen_curve_checks}条曲线与冻结引擎逐日核对；${D.audit.prefix_checks.length}次截断重算一致；6项便携规则测试通过。当前启用策略保持不变。`;
$('design').textContent=JSON.stringify({design:D.design,audit:D.audit},null,2);
for(const r of D.summary)$('picks').insertAdjacentHTML('beforeend',`<label><input type="checkbox" value="${r.id}" ${['BASE','BALANCED','CREDIT','F75',selected.id].includes(r.id)?'checked':''}>${esc(r.name)}</label>`);
table('associations',['因素','已知日数','较高风险日数','控制后20日差值','95%区间','BH q','解读'],D.associations.map(r=>[D.labels[r.factor],r.known_days,r.risk_days,pct(r.difference20),pct(r.ci_low)+'～'+pct(r.ci_high),num(r.bh_q),r.bh_q!=null&&r.bh_q<.05?(r.difference20<0?'负向关联':'正向关联'):'证据不足']));
function render(){const period=$('period').value,capital=Math.max(1,Number($('capital').value)||10000),ids=new Set([...$('picks').querySelectorAll('input:checked')].map(x=>x.value)),chosen=D.summary.filter(r=>ids.has(r.id)),rows=D.summary.map(r=>({...r,...D.periods.find(p=>p.id===r.id&&p.period===period)})).sort((a,b)=>b.calmar-a.calmar);$('range').textContent=`${rows[0].first_session}—${rows[0].end_session}，${rows[0].sessions}交易日。`;
table('table',['方案','年化','最大回撤','累计收益','Sharpe','Sortino','Calmar','年换手倍数','期末本金'],rows.map(r=>[esc(r.name)+(r.training_selected?'［前段选型］':''),pct(r.annualized_return),pct(r.max_drawdown),pct(r.total_return),num(r.sharpe),num(r.sortino),num(r.calmar),num(r.annual_turnover),(capital*r.multiple).toLocaleString('zh-CN',{maximumFractionDigits:0})]));
const eq=[],dd=[];for(const r of chosen){const p=D.periods.find(p=>p.id===r.id&&p.period===period),begin=D.dates.indexOf(p.first_session),end=D.dates.indexOf(p.end_session),raw=D.curves[r.id],anchor=p.baseline_close?raw[D.dates.indexOf(p.baseline_close)]:1,x=[p.baseline_close||'2016-12-30',...D.dates.slice(begin,end+1)],y=[1,...raw.slice(begin,end+1).map(v=>v/anchor)];let peak=1;const draw=y.map(v=>{peak=Math.max(peak,v);return 100*(v/peak-1)}),style={name:r.name,type:'scatter',mode:'lines',line:{width:r.id==='BASE'?3:1.5}};eq.push({...style,x,y:y.map(v=>v*capital)});dd.push({...style,x,y:draw})}
const layout={margin:{l:70,r:15,t:50,b:140},font:{family:'Microsoft YaHei',size:12},legend:{orientation:'h',y:-.25},hovermode:'x unified'};Plotly.react('equity',eq,{...layout,title:'每日资金曲线',yaxis:{type:$('scale').value}},{responsive:true,displaylogo:false});Plotly.react('drawdown',dd,{...layout,title:'日终回撤',yaxis:{ticksuffix:'%'}},{responsive:true,displaylogo:false});const name=id=>esc(D.summary.find(r=>r.id===id).name);
table('segments',['方案','阶段','年化','最大回撤'],D.segments.filter(r=>ids.has(r.id)).map(r=>[name(r.id),r.segment,pct(r.annualized_return),pct(r.max_drawdown)]));
table('risk',['方案','最差日损失','日损失ES95','连续未新高/交易日','现金日数','成交日数'],chosen.map(r=>[esc(r.name),pct(r.worst_day),pct(r.daily_es95),r.longest_underwater_days,r.cash_days,r.trade_days]));
table('stress',['方案','成本/基点','额外成交延迟/日','年化','最大回撤'],D.execution_stress.filter(r=>ids.has(r.id)).map(r=>[name(r.id),r.cost_bps,r.extra_lag,pct(r.annualized_return),pct(r.max_drawdown)]));
table('lag',['方案','指标额外滞后/日','年化','最大回撤'],D.publication_lag_stress.filter(r=>ids.has(r.id)).map(r=>[name(r.id),5,pct(r.annualized_return),pct(r.max_drawdown)]))}
for(const s of ['period','capital','scale','picks'])$(s).addEventListener('change',render);render();
</script></body></html>'''


if __name__=='__main__':main()
