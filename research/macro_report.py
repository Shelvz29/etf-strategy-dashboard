"""Offline interactive report; macro inputs and private curves remain ignored."""
import json
import pandas as pd
from plotly.offline import get_plotlyjs
from macro_data import OUT
from macro_rules import FACTORS
from cash_replacement import INITIAL

REPORT=OUT/'2026-10-04-外部宏观因素与恢复确认策略回测.html'


def main():
    data={key:json.loads(pd.read_csv(OUT/(key+'.csv')).to_json(orient='records',force_ascii=False))
          for key in ('summary','periods','annual','segments','execution_stress','macro_lag_stress','factor_associations')}
    data.update({key:json.loads((OUT/(file+'.json')).read_text(encoding='utf-8'))
                 for key,file in [('design','design'),('audit','verification'),('cpi_audit','cpi_crosscheck')]})
    data['factors']=FACTORS
    for row in data['summary']:
        for key,name in [('rates','利率'),('oil','油价'),('policy','货币政策'),('cpi','通胀')]:
            row['name']=row['name'].replace('单因素组：'+key,name+'风险组')
    data['correlations']=json.loads(pd.read_csv(OUT/'group_correlations.csv',index_col=0).reset_index().to_json(orient='records'))
    data['curves']={}
    for row in data['summary']:
        nav=pd.read_csv(OUT/'curves'/(row['id']+'.csv'),index_col=0)
        data['dates']=nav.index.tolist();data['curves'][row['id']]=(nav.equity/INITIAL).tolist()
    payload=json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':')).replace('</','<\\/')
    REPORT.write_text(HTML.replace('__PLOTLY__',get_plotlyjs()).replace('__DATA__',payload),encoding='utf-8')
    print(REPORT)


HTML=r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>外部宏观因素与恢复确认策略回测</title>
<style>body{margin:0;background:#f3f6fa;color:#20344d;font:15px/1.7 "Microsoft YaHei",sans-serif}main{max-width:1450px;margin:32px auto;padding:0 20px}h1{font-size:28px;margin-bottom:4px}h2{font-size:21px;margin-top:0}.card{background:white;border:1px solid #dae3ed;border-radius:12px;margin:20px 0;padding:23px}.lead{background:#e8f2ff;border-left:5px solid #4082bc;padding:20px}.muted{color:#67768b}.fine{font-size:13px}.controls,.picks{display:flex;gap:16px;flex-wrap:wrap;align-items:end}.picks{margin:18px 0;gap:10px}.picks label{border:1px solid #d8e2ef;padding:7px 10px;border-radius:5px}input,select{font:inherit}input[type=number],select{padding:6px;border:1px solid #becbdc;border-radius:5px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px;white-space:nowrap}th,td{padding:9px 11px;border-bottom:1px solid #e3e9f1;text-align:right}th{background:#edf3fa}th:first-child,td:first-child{text-align:left}.charts{display:grid;grid-template-columns:1fr 1fr;gap:12px}.chart{height:480px}a{color:#2b6eab}summary{cursor:pointer}pre{white-space:pre-wrap;word-break:break-word}@media(max-width:850px){.charts{grid-template-columns:1fr}h1{font-size:23px}.card{padding:15px}}</style><script>__PLOTLY__</script></head><body><main>
<h1>外部宏观因素与恢复确认策略回测</h1><p class="muted">SMH／SOXL 与 QQQ／TQQQ · 2017-01-03 至 2026-10-02 · 每组20个固定方案 · 当前看板策略未更换</p>
<div class="lead">预设组合在QQQ／TQQQ上降低回撤，但后段收益减少；SMH／SOXL的三组风险规则有小幅改善，且对宏观时点敏感。完整历史排序用于描述，不能作为未来收益或回撤上限的保证。</div>
<section class="card"><h2>外部因素如何量化</h2><p>原MACD＋4%急跌＋恢复确认规则保留。叠加层只减小原目标：利率、油价、货币政策、通胀四组各计1票，同组指标取“或”，风险总分0—4。收益率倒挂同时包含紧缩，不重复计入利率组，而是另做单项试验。四组之间仍有相关性。</p><div class="scroll" id="factors"></div>
<p>预设主方案：风险分数连续2个交易日≥2时，进攻ETF目标上限50%；连续5日≤1才解除限制。解除后的进攻买入／加仓仍需原恢复确认。原防御ETF目标和现金锁定保留。三组风险上限50%版则在≥3分时降低目标，≤2分解除；两组50%／三组现金版在≥3分时目标归零。覆盖防御ETF版也限制SMH或QQQ，其他方案只限制SOXL或TQQQ。</p>
<p class="muted fine">上限指目标权重，并在目标变化时成交；目标不变不每日配平，实际持仓权重可随价格漂移。“宏观解除即恢复”只取消额外的宏观恢复等待，基础策略的恢复确认始终保留。政策指标仅包括联储目标利率，未补造关税、财政政策或新闻情绪的历史分数。</p></section>
<section class="card"><h2>全历史与近年对比</h2><div class="controls"><label>组合<br><select id="market"><option value="SMH">SMH／SOXL</option><option value="QQQ">QQQ／TQQQ</option></select></label><label>年限<br><select id="period"><option>全部历史</option><option>近5年</option><option>近3年</option><option>近2年</option><option>近1年</option></select></label><label>本金<br><input id="capital" type="number" value="10000" min="1"></label><label>资金图刻度<br><select id="scale"><option value="log">对数</option><option value="linear">线性</option></select></label></div><p id="range" class="muted"></p><p id="conclusion"></p>
<div class="scroll" id="table"></div><p class="muted fine">表格按所选年限Calmar（年化÷最大回撤）降序展示；排序不参与交易，也不重新选择训练方案。Sharpe无风险利率按0处理。固定上限参照用于区分宏观择时和少持有杠杆ETF。</p>
<div class="picks" id="picks"></div><div class="charts"><div class="chart" id="equity"></div><div class="chart" id="drawdown"></div></div><p class="muted fine">近年区间使用历史连续持仓，从区间前一交易日净值归一化；不是每个起点从空仓重新启动。本金缩放不改变收益率，单位为等额ETF资金，不含人民币汇率或代币化证券价差。回撤计入区间初始本金。</p></section>
<section class="card"><h2>阶段稳定性与实施代价</h2><p id="diagnosis"></p><div class="scroll" id="segments"></div><p>自然年累计收益，2026仅截至10月2日：</p><div class="scroll" id="annual"></div><p>额外评价指标（全历史）：日终单日最差跌幅、最差5%日收益的平均损失ES95、现金交易日数及成交日数。它们不能代替盘中风控或未来风险估计。</p><div class="scroll" id="risk"></div><p>交易成本／成交时间压力检查：</p><div class="scroll" id="stress"></div><p>所有宏观输入额外延迟5个NYSE交易日，保持交易成本10基点：</p><div class="scroll" id="macro_lag"></div></section>
<section class="card"><h2>指标关联的统计检查</h2><p>用基础ETF未来5、20、60个交易日的复权收益做关联检查，控制过去20日收益和20日波动。置信区间采用Newey–West/HAC，滞后等于未来期；每个资产39项检验做BH多重比较修正。BH q&lt;0.05且系数为负表示本样本中的较弱后续表现，不能证明因果或将差值当策略收益。</p><label>未来期 <select id="horizon"><option value="20">20交易日</option><option value="5">5交易日</option><option value="60">60交易日</option></select></label><div class="scroll" id="associations"></div>
<p>QQQ的利率急升和通胀升温主要在60日尺度出现负向关联，SMH未得到修正后显著证据。油价暴跌和紧急降息在QQQ的20日结果反而为正，样本主要集中在少数危机及反弹中。因此不能把“坏宏观消息”统一解释为卖出信号。风险日数不是独立事件数；HAC与BH仍无法充分处理极少危机、结构变化和所有探索偏差。</p><details><summary>四组风险标志的日度相关性</summary><div class="scroll" id="correlation"></div></details></section>
<section class="card"><h2>数据时点与检查范围</h2><div class="scroll"><table><thead><tr><th>数据</th><th>口径</th><th>可用时间处理</th><th>官方来源</th></tr></thead><tbody>
<tr><td>国债</td><td>财政部2年／10年名义、10年实际平价收益率</td><td>观测日起延后2个NYSE交易日</td><td><a href="https://home.treasury.gov/treasury-daily-interest-rate-xml-feed">Treasury XML</a></td></tr>
<tr><td>石油</td><td>EIA WTI现货价格，保留2020负价格</td><td>观测日起延后3个NYSE交易日</td><td><a href="https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&amp;s=RWTC&amp;f=D">EIA</a></td></tr>
<tr><td>政策</td><td>NY Fed历史联储目标区间上限</td><td>有效日起延后2个NYSE交易日</td><td><a href="https://www.newyorkfed.org/markets/reference-rates/effr">NY Fed</a></td></tr>
<tr><td>CPI</td><td>139次公告归档的总体／核心未季调同比</td><td>真实公告日收盘可用，再次日开盘交易</td><td><a href="https://www.bls.gov/bls/news-release/cpi.htm">BLS归档</a></td></tr></tbody></table></div>
<p>2025年10月CPI因停摆未公布，保留缺口，沿用最后已知公告值。与当前BLS未季调指数独立核对278个值，只有2016年5、6月核心同比有历史更正差异；保留当次归档值。这两期位于2017回测起点前。对照当前指数只能检查录入，不能证明所有数据首次公布版本完整。</p>
<p>国债、油价和政策为当前下载的历史，未取得完整的逐日首次公布数据库。2／3日滞后是保守假设，不能消除历史修订风险。公告日期精确处理不会让历史回测变成真正未知样本外。2017—2021按回撤≤50%时年化最高选型（排除固定上限），2022—2024与2025以后仅做时间隔离检查；此前已经看过该市场数据，未声称未知样本外。</p>
<p>收盘形成信号，次日开盘成交，单边10基点，可买零股，复权OHLC隐含分红再投资，现金无息。不含税、汇率、ETF与代币化证券的报价／交易时段差异。4%急跌在收盘确认，无法躲过当天已发生的下跌。数据过期或缺少时抛错，不当作中性信号。</p><p id="checks"></p>
<p><a href="summary.csv" download>全历史表格</a> · <a href="periods.csv" download>各年限表格</a> · <a href="segments.csv" download>分段表格</a> · <a href="factor_associations.csv" download>统计检查明细</a> · <a href="design.json" download>规则和实验约定</a></p><details><summary>完整规则与输入校验记录</summary><pre id="design"></pre></details></section></main>
<script>
const D=__DATA__, $=id=>document.getElementById(id), pct=x=>(100*x).toFixed(2)+'%',num=x=>Number(x).toFixed(2),esc=x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function table(id,heads,rows){$(id).innerHTML='<table><thead><tr>'+heads.map(h=>'<th>'+h+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(v=>'<td>'+v+'</td>').join('')+'</tr>').join('')+'</tbody></table>'}
const labels={rates:'利率',oil:'油价',policy:'货币政策',cpi:'通胀'};
const factorNames={rate_jump:'名义利率急升',real_jump:'实际利率急升',curve_stress:'倒挂且紧缩',oil_spike:'油价快速上涨',oil_crash:'油价暴跌且股市走弱',tightening:'政策紧缩',emergency_cut:'紧急降息且股市走弱',cpi_heat:'通胀升温',cpi_jump:'CPI跳升'};
table('factors',['指标','规则'],Object.entries(D.factors).map(([k,v])=>[factorNames[k],esc(v)]));
table('correlation',['组别',...Object.values(labels)],D.correlations.map(r=>[labels[r.index],...Object.keys(labels).map(g=>num(r[g]))]));
$('checks').textContent=`${D.audit.frozen_audits.length}条实际曲线与冻结引擎逐日核对；${D.audit.prefix_audits.length}次历史截断重算核对，无未来信息改变此前信号；6项规则测试通过。当前启用策略未改变，新研究未导入策略列表。报告仅保存在本机，未推送GitHub。`;
$('design').textContent=JSON.stringify({design:D.design,audit:D.audit,cpi:D.cpi_audit},null,2);
for(const r of D.summary.filter(r=>r.market==='SMH'))$('picks').insertAdjacentHTML('beforeend',`<label><input type="checkbox" value="${r.variant}" ${['BASE','F75','S2_H','S3_50','S2_NORESTORE'].includes(r.variant)?'checked':''}>${esc(r.name)}</label>`);
function render(){const market=$('market').value,period=$('period').value,capital=Math.max(1,Number($('capital').value)||10000),variants=new Set([...$('picks').querySelectorAll('input:checked')].map(x=>x.value));const full=D.summary.filter(r=>r.market===market),rows=full.map(r=>({...r,...D.periods.find(p=>p.id===r.id&&p.period===period)})).sort((a,b)=>b.calmar-a.calmar),chosen=full.filter(r=>variants.has(r.variant)),first=rows[0];
$('range').textContent=`${first.first_session} 至 ${first.end_session} · ${first.sessions}个交易日。`;
const b=full.find(r=>r.variant==='BASE'),m=full.find(r=>r.variant==='S2_H'),t=full.find(r=>r.training_selected);$('conclusion').textContent=`全历史基准年化${pct(b.annualized_return)}／最大回撤${pct(b.max_drawdown)}；预设主方案${pct(m.annualized_return)}／${pct(m.max_drawdown)}。仅由前段选出的方案为“${t.name}”，全历史${pct(t.annualized_return)}／${pct(t.max_drawdown)}。`;
table('table',['方案','年化','最大回撤','累计收益','Sharpe','Sortino','Calmar','年换手倍数','期末本金'],rows.map(r=>[esc(r.name)+(r.variant==='S2_H'?'［预设主方案］':'')+(r.training_selected?'［前段选型］':''),pct(r.annualized_return),pct(r.max_drawdown),pct(r.total_return),num(r.sharpe),num(r.sortino),num(r.calmar),num(r.annual_turnover),(capital*r.multiple).toLocaleString('zh-CN',{maximumFractionDigits:0})]));
const eq=[],dd=[];for(const r of chosen){const p=D.periods.find(p=>p.id===r.id&&p.period===period),begin=D.dates.indexOf(p.first_session),end=D.dates.indexOf(p.end_session),raw=D.curves[r.id],anchor=p.baseline_close?raw[D.dates.indexOf(p.baseline_close)]:1,x=[p.baseline_close||'2016-12-30',...D.dates.slice(begin,end+1)],y=[1,...raw.slice(begin,end+1).map(v=>v/anchor)];let peak=1;const draw=y.map(v=>{peak=Math.max(peak,v);return 100*(v/peak-1)}),style={name:r.name,type:'scatter',mode:'lines',line:{width:r.variant==='S2_H'?3:1.5}};eq.push({...style,x,y:y.map(v=>v*capital)});dd.push({...style,x,y:draw});}
const layout={margin:{l:70,r:15,t:50,b:125},paper_bgcolor:'white',plot_bgcolor:'white',font:{family:'Microsoft YaHei',size:12},legend:{orientation:'h',y:-.23},hovermode:'x unified',xaxis:{showgrid:false},yaxis:{gridcolor:'#edf1f5'}};Plotly.react('equity',eq,{...layout,title:'每日资金曲线',yaxis:{...layout.yaxis,type:$('scale').value}},{responsive:true,displaylogo:false});Plotly.react('drawdown',dd,{...layout,title:'区间日终回撤',yaxis:{...layout.yaxis,ticksuffix:'%'}},{responsive:true,displaylogo:false});
const selected=new Set(chosen.map(r=>r.id)),name=id=>esc(full.find(r=>r.id===id).name);table('segments',['方案','阶段','年化','最大回撤'],D.segments.filter(r=>selected.has(r.id)).map(r=>[name(r.id),r.segment,pct(r.annualized_return),pct(r.max_drawdown)]));
table('annual',['年份',...chosen.map(r=>esc(r.name))],Array.from({length:10},(_,i)=>2017+i).map(y=>[y===2026?'2026年内':y,...chosen.map(r=>pct(D.annual.find(a=>a.id===r.id&&a.year===y).total_return))]));
table('risk',['方案','最差日损失','日损失ES95','现金交易日','成交日'],chosen.map(r=>[esc(r.name),pct(r.worst_day),pct(r.daily_es95),r.cash_days,r.trade_days]));
table('stress',['方案','单边成本/基点','额外成交延迟/日','全历史年化','最大回撤'],D.execution_stress.filter(r=>selected.has(r.id)).map(r=>[name(r.id),r.cost_bps,r.extra_lag,pct(r.annualized_return),pct(r.max_drawdown)]));
table('macro_lag',['方案','宏观额外延迟/日','全历史年化','最大回撤'],D.macro_lag_stress.filter(r=>selected.has(r.id)).map(r=>[name(r.id),r.macro_extra_lag,pct(r.annualized_return),pct(r.max_drawdown)]));
$('diagnosis').textContent=market==='SMH'?'SMH／SOXL三组50%版全历史66.87%／50.70%，但它与基准在2017—2021及2025以后相同，改善主要来自中段；宏观再延迟5日后65.31%／54.29%，改善减弱。固定75%参照51.39%／44.26%能更明显降回撤，但减少收益。':'QQQ／TQQQ预设主方案主要改善2022—2024年：年化18.90%／回撤45.87%，基准11.93%／59.89%；2025以后年化7.04%，低于基准14.23%。宏观解除即恢复版虽全历史33.73%／46.29%，但宏观额外滞后5日变成28.71%／58.21%。';
const horizon=Number($('horizon').value);table('associations',['指标','风险日数','正常日数','风险期均值','正常期均值','控制后差值','HAC 95%区间','BH q','解读'],D.factor_associations.filter(r=>r.asset===market&&r.horizon===horizon).map(r=>[factorNames[r.factor]||labels[r.factor],r.risk_days,r.normal_days,pct(r.mean_risk_return),pct(r.mean_normal_return),pct(r.controlled_difference),pct(r.ci_low)+'～'+pct(r.ci_high),Number(r.bh_q).toFixed(4),r.bh_q<.05?(r.controlled_difference<0?'负向关联':'正向关联'):'证据不足']));}
for(const id of ['market','period','capital','scale','picks','horizon'])$(id).addEventListener('change',render);render();
</script></body></html>'''


if __name__=='__main__':main()
