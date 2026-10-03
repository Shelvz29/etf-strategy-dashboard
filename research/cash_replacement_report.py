"""Build an offline interactive report from the fixed cash-replacement study."""
import json
from pathlib import Path
import sys

import pandas as pd
from plotly.offline import get_plotlyjs

sys.path.insert(0,str(Path(__file__).resolve().parent))
from cash_replacement import OUT, ASSETS

REPORT=OUT/'2026-10-03-MACD急跌避险现金替代资产研究.html'


def records(frame):
    return json.loads(frame.to_json(orient='records',force_ascii=False))


def main():
    result=pd.read_csv(OUT/'results.csv')
    periods=pd.read_csv(OUT/'periods.csv')
    stress=pd.read_csv(OUT/'execution_stress.csv')
    conditional=pd.read_csv(OUT/'conditional_asset_returns.csv')
    audit=json.loads((OUT/'verification.json').read_text(encoding='utf-8'))
    curves={};dates={}
    for row in result.to_dict('records'):
        nav=pd.read_csv(OUT/(row['id']+'.csv'),index_col=0)
        dates[row['window']]=nav.index.tolist()
        curves[row['id']]=(nav.equity/100_000).round(10).tolist()
    data={'rows':records(result),'periods':records(periods),'stress':records(stress),
          'conditional':records(conditional),'dates':dates,'curves':curves,'assets':ASSETS,'audit':audit}
    document=HTML.replace('__PLOTLY__',get_plotlyjs()).replace('__DATA__',json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':')).replace('</','<\\/'))
    REPORT.write_text(document,encoding='utf-8')
    print(REPORT)


HTML=r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>MACD＋4%急跌避险：现金替代资产研究</title><style>
body{margin:0;background:#f3f6fb;color:#18283e;font:15px/1.65 "Microsoft YaHei",sans-serif}main{max-width:1450px;margin:28px auto;padding:0 22px}h1{font-size:29px;margin-bottom:8px}h2{font-size:21px;margin-top:0}.card{background:white;border:1px solid #dde5f0;border-radius:12px;padding:24px;margin:20px 0}.lead{background:#e8f0fc;border-left:5px solid #3473c8;padding:18px}.muted{color:#61728a}.controls{display:flex;gap:18px;flex-wrap:wrap;align-items:end}label{display:inline-block}select,input[type=number]{padding:9px;border:1px solid #acbdd3;border-radius:5px;font:inherit}.assets{display:flex;gap:12px;flex-wrap:wrap;margin-top:17px}.assets label{padding:5px 9px;background:#f2f6fc;border-radius:5px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.scroll{overflow:auto}table{border-collapse:collapse;white-space:nowrap;width:100%;font-size:14px}th,td{padding:9px 12px;text-align:right;border-bottom:1px solid #e2e8f0}th:first-child,td:first-child{text-align:left}th{background:#edf3fc;position:sticky;top:0}.good{color:#147355}.bad{color:#ad3d43}.baseline{background:#eef4ff}a{color:#225fa9}.chart{height:470px}.facts{display:flex;flex-wrap:wrap;gap:20px}.facts b{font-size:22px;display:block}.fine{font-size:13px}.note{border-left:4px solid #ecb251;padding:12px;background:#fff8e9}@media(max-width:850px){.grid{grid-template-columns:1fr}.card{padding:15px}h1{font-size:23px}}
</style><script>__PLOTLY__</script></head><body><main>
<h1>MACD＋4%急跌避险：现金替代资产研究</h1><p class="muted">截至 2026-10-02 的美股交易日线 · 固定规则比较 · 当前看板策略未改动</p>
<div class="lead"><b>长期结果没有出现“年化更高、最大回撤更低”的现金替代方案。</b><br>高股息与低波动股票略增长期收益，同时加大回撤；反向 ETF 与当前离场、再入场时机不匹配。近期 JEPQ 部分配置、SGOV 和少量黄金有局部改善，成本变化后优势不稳定。</div>
<section class="card"><h2>先区分资产的作用</h2><div class="scroll"><table><thead><tr><th>资产</th><th>作用</th><th>为何不能保证替代现金更好</th></tr></thead><tbody>
<tr><td>BIL、SGOV</td><td>超短期美国国债，管理闲置资金</td><td>短暂持有的利息可能抵不过反复买卖成本</td></tr>
<tr><td>SHY、IEF、TLT</td><td>不同期限的美国国债</td><td>期限越长利率风险越大；通胀与升息阶段可能股债同跌</td></tr>
<tr><td>GLD</td><td>黄金，与半导体风险来源不同</td><td>仍会波动，不能保证在每次股票急跌时上涨</td></tr>
<tr><td>SCHD、VYM、USMV</td><td>股息、股票分散或降低股票波动</td><td>仍然持有股票，系统性下跌时可能同步亏损</td></tr>
<tr><td>JEPI、JEPQ</td><td>股票与期权收入</td><td>高派息不等于保本，仍有股票下跌风险，历史较短</td></tr>
<tr><td>PSQ、SOXS、SQQQ</td><td>每日反向 −1 / −3 倍股票指数</td><td>急跌后再买可能遭遇反弹，复利结果不等于长期简单反向</td></tr>
</tbody></table></div><p class="fine muted">本研究测试的是离场后轮换到替代资产；没有同时持有 SOXL 与对冲资产。保护性看跌期权需要期权历史报价，未纳入本次日线回测。未核实上述产品在你的币安地区账户是否可交易或如何处理派息。</p></section>
<section class="card"><h2>选择比较口径</h2><div class="controls">
<label>历史起点<br><select id="window"><option>2017年以来</option><option>共同较短区间</option></select></label>
<label>替换范围<br><select id="scope"><option>仅MACD避险现金</option><option>策略全部现金</option></select></label>
<label>原空仓资金买入比例<br><select id="weight"><option value="1">100%</option><option value="0.5">50%</option><option value="0.25">25%</option></select></label>
<label>统计区间<br><select id="period"><option>全部历史</option><option>近1年</option><option>近2年</option><option>近3年</option><option>近5年</option></select></label>
<label>图表起始本金<br><input id="capital" type="number" min="1" value="10000" step="1000"></label>
<label>净值坐标<br><select id="scale"><option value="log">对数</option><option value="linear">线性</option></select></label>
</div><div class="assets" id="assets"></div><p class="muted" id="range"></p><div class="note">100% 是把原来要求空仓的资金全部转入替代资产；50% / 25% 时剩余现金不计利息。原来持有 SMH / SOXL 的信号和权重全部保留。“仅MACD避险现金”只替换 RISK_CASH 状态；“策略全部现金”还包含原规则的 BREAK_CASH。</div></section>
<section class="card"><h2>收益与回撤</h2><p class="fine muted">表格列出所选比例下全部可比较资产，勾选控制曲线。基准始终显示。每个区间重新按相同比例本金展示；近年曲线采用连续持仓历史，不在区间起点另行重新建仓。最大回撤为日终净值口径。</p><div id="table" class="scroll"></div><div class="grid"><div id="equity" class="chart"></div><div id="dd" class="chart"></div></div></section>
<section class="card"><h2>成本与成交延迟敏感性</h2><p class="fine muted">这里使用所选历史起点的完整区间，不随“近1/2/3/5年”切换。每行与相同成本、相同成交延迟的现金基准比较。“年化差”和“回撤差”单位为百分点；回撤差为负表示改善。</p><div id="stress" class="scroll"></div></section>
<section class="card"><h2>原避险信号之后，资产真的在对冲吗？</h2><p class="fine muted">以下用前一日空仓信号选取日线，计算当日复权收盘收益与 SMH 的相关性。这是资产行为诊断，未含进出场费用和隔夜成交差，不能当作实际交易利润。</p><div id="conditional" class="scroll"></div><p>2017 年以来，MACD 空仓段共有 40 次、实际替代持有 565 个交易日。SOXS 在这些日子与 SMH 的相关性约 −0.99，确实反向；但自身日均收益约 −0.48%。<b>负相关并不保证配合此策略的交易时点后有收益。</b></p></section>
<section class="card"><h2>怎样理解结果</h2><p>长期现金基准年化 66.65%，最大回撤 72.62%；黄金 100% 替换为 67.22% / 75.97%，SCHD 为 67.65% / 73.47%，SOXS 为 1.15% / 94.97%。替换资产不能修复原策略持有 SOXL 时的风险。</p><p>现金基准的最大回撤从 2021-12-07 的高点延伸至 2022-11-03 的低点，两个时点都持有 SOXL。想把整体回撤控制在约 50%，还需要另行研究 SOXL 仓位上限、再入场条件或波动率控制，单换避险资产在本实验中未达到目标。</p><p>共同较短区间从 2022-05-05 开始，从现金建仓，基础状态仍沿用此前历史。该段 JEPQ 50% 替换的年化 / 回撤为 99.50% / 69.42%，基准为 96.46% / 69.54%。提升是有限历史内的事后结果：成本升至单边 25 基点时回撤改善消失，升至 50 基点时年化与回撤均劣于相同成本的现金。</p><p>SGOV 在短区间的收益改善只有约 0.15 个百分点（100% 替换），25 基点成本时反而低于现金。若实际账户现金本就有利息，国债替代的相对优势还会进一步改变；本基准现金利息为零。</p></section>
<section class="card"><h2>数据、规则与验证</h2><ul>
<li>2017-01-03 至 2026-10-02：11 种已有完整历史的替代资产 × 2 个范围 × 3 个比例，另加现金，共 67 个方案。较短共同区间包含 14 种资产，另加现金，共 85 个方案；无上市前数据填补。</li>
<li>收盘后判断 MACD 与当日相对前收盘最大跌幅；下一交易日开盘执行。无法在已发生的急跌之前成交。原 MACD 12/26/9、4% 阈值、锁定和恢复规则保持不变。</li>
<li>每次买卖单边综合成本 10 基点（0.10%），目标变化才交易；另测 25 / 50 基点及额外延迟一个交易日。换仓的卖出和买入都收费。</li>
<li>使用 Yahoo 日线、复权 OHLC，含分红再投资与拆股；不是实物股息到账、税务或整数份额账本。未含税、汇率、币安代币价格偏离和资金结算限制。</li>
<li>年化按真实日历时长计算，最大回撤计入期初本金。夏普与索提诺按 252 交易日、无风险利率为零；Calmar = 年化 / 最大回撤。高年化来自历史杠杆敞口，不能视为未来收益预期。</li>
<li>完整日历、标的、币种、日线粒度校验；10 组实际历史曲线与冻结执行引擎逐日独立核对，并测试未来数据不改变过去成交、现金替换范围及费用资金守恒。</li>
<li>本研究固定比较资产与 25% / 50% / 100%，没有搜索触发参数；152 个方案的横向筛选存在多重比较。近年、成本与延迟检查不是独立样本外验证，不宣称统计显著性。</li>
</ul><p>完整数据与明细保存在本报告同目录：results.csv、periods.csv、execution_stress.csv、conditional_asset_returns.csv、baseline_signals.csv、verification.json。原始行情及结果不进入公开仓库；本次只记录研究工具的本地 Git 变更，未发布 GitHub 更新。</p>
<p class="fine">产品说明：<a href="https://www.ssga.com/us/en/intermediary/etfs/state-street-spdr-bloomberg-1-3-month-t-bill-etf-bil">BIL</a> · <a href="https://www.ishares.com/us/products/314116/ishares-0-3-month-treasury-bond-etf">SGOV</a> · <a href="https://www.ishares.com/us/products/239454/ishares-202026-treasury-bond-etf">TLT</a> · <a href="https://www.ssga.com/us/en/individual/etfs/spdr-gold-shares-gld">GLD</a> · <a href="https://www.schwabassetmanagement.com/products/schd">SCHD</a> · <a href="https://am.jpmorgan.com/content/dam/jpm-am-aem/americas/us/en/literature/fact-sheet/etfs/FS-JEPQ.PDF">JEPQ</a> · <a href="https://www.direxion.com/product/daily-semiconductor-bull-bear-3x-etfs">SOXS</a> · <a href="https://www.proshares.com/our-etfs/leveraged-and-inverse/psq">PSQ</a></p></section>
</main><script>const D=__DATA__;
const $=id=>document.getElementById(id),pct=v=>v==null?'—':(v*100).toFixed(2)+'%',num=v=>v==null?'—':Number(v).toFixed(2),pp=v=>(v>0?'+':'')+(v*100).toFixed(2),esc=v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
const defaults=new Set(['BIL','GLD','SCHD','SOXS','SGOV','JEPQ']);
for(const [s,g] of Object.entries(D.assets)){$('assets').insertAdjacentHTML('beforeend',`<label data-asset="${s}"><input type="checkbox" value="${s}" ${defaults.has(s)?'checked':''}> ${s} · ${g}</label>`)}
function table(id,heads,rows){$(id).innerHTML='<table><thead><tr>'+heads.map(h=>'<th>'+h+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map((v,i)=>'<td>'+v+'</td>').join('')+'</tr>').join('')+'</tbody></table>'}
function render(){const win=$('window').value,scope=$('scope').value,weight=Number($('weight').value),period=$('period').value,capital=Math.max(1,Number($('capital').value)||10000),selected=new Set([...$('assets').querySelectorAll('input:checked')].map(x=>x.value));
const candidates=D.rows.filter(r=>r.window===win&&(r.asset==='CASH'||(r.scope===scope&&r.weight===weight)));const available=new Set(candidates.map(r=>r.asset));
for(const label of $('assets').children){label.style.display=available.has(label.dataset.asset)?'':'none'}
const filtered=candidates.map(r=>{const p=D.periods.find(p=>p.id===r.id&&p.period===period);return p?{...r,...p}:null}).filter(Boolean);const base=filtered.find(r=>r.asset==='CASH');
if(!base){$('range').textContent='这个历史起点不足以覆盖所选区间，请选择较短年限。';for(const id of ['table','stress','conditional'])$(id).innerHTML='';Plotly.purge('equity');Plotly.purge('dd');return}
$('range').textContent=`${base.first_session} — ${base.end_session}，${base.sessions} 个交易日；${win==='共同较短区间'?'比较起点：2022-05-05。':'比较起点：2017-01-03。'} 本金按美元总收益比例缩放，未计算人民币汇率。`;
filtered.sort((a,b)=>a.asset==='CASH'?-1:b.asset==='CASH'?1:b.calmar-a.calmar);
table('table',['替代资产','年化收益','最大回撤','年化差 / pp','回撤差 / pp','Sharpe','Sortino','Calmar','期末本金','同时改善'],filtered.map(r=>[esc(r.asset+' · '+r.group),pct(r.annualized_return),pct(r.max_drawdown),pp(r.annualized_return-base.annualized_return),pp(r.max_drawdown-base.max_drawdown),num(r.sharpe),num(r.sortino),num(r.calmar),(r.multiple*capital).toLocaleString('zh-CN',{maximumFractionDigits:0}),r.asset==='CASH'?'基准':r.annualized_return>base.annualized_return&&r.max_drawdown<base.max_drawdown?'<span class="good">是</span>':'否']));
const eq=[],dd=[];for(const r of filtered){if(r.asset!=='CASH'&&!selected.has(r.asset))continue;const dates=D.dates[r.window],raw=D.curves[r.id];let begin=dates.indexOf(r.first_session),end=dates.indexOf(r.end_session),anchor=r.baseline_close?raw[dates.indexOf(r.baseline_close)]:1;const x=dates.slice(begin,end+1),y=raw.slice(begin,end+1).map(v=>v/anchor);let peak=1;const draw=y.map(v=>{peak=Math.max(peak,v);return (v/peak-1)*100});eq.push({x,y:y.map(v=>v*capital),type:'scatter',mode:'lines',name:r.asset,line:{width:r.asset==='CASH'?3:1.6},hovertemplate:'%{x}<br>%{y:,.0f}<extra>%{fullData.name}</extra>'});dd.push({x,y:draw,type:'scatter',mode:'lines',name:r.asset,line:{width:r.asset==='CASH'?3:1.6},hovertemplate:'%{x}<br>%{y:.2f}%<extra>%{fullData.name}</extra>'})}
const layout={margin:{l:64,r:16,t:50,b:70},paper_bgcolor:'white',plot_bgcolor:'white',legend:{orientation:'h',y:-.2},hovermode:'x unified',font:{family:'Microsoft YaHei',size:12},xaxis:{showgrid:false},yaxis:{gridcolor:'#edf1f8'}};
Plotly.react('equity',eq,{...layout,title:'日线本金对比',yaxis:{...layout.yaxis,type:$('scale').value}},{responsive:true,displaylogo:false});Plotly.react('dd',dd,{...layout,title:'日终历史回撤',yaxis:{...layout.yaxis,ticksuffix:'%'}},{responsive:true,displaylogo:false});
const keys=new Set(candidates.filter(r=>r.asset==='CASH'||selected.has(r.asset)).map(r=>r.id));
const S=D.stress.filter(r=>keys.has(r.id));table('stress',['资产','单边成本 / 基点','额外延迟 / 日','年化','回撤','年化差 / pp','回撤差 / pp'],S.map(r=>[r.id.split('_')[1],r.cost_bps,r.extra_lag,pct(r.annualized_return),pct(r.max_drawdown),pp(r.cagr_change),pp(r.drawdown_change)]));
const cscope=scope==='仅MACD避险现金'?'macd':'all';const C=D.conditional.filter(r=>r.window===win&&r.scope===cscope&&r.subset==='避险日');table('conditional',['资产','样本日','与SMH相关性','日均资产收益','上涨日比例','最差单日'],C.map(r=>[r.asset,r.days,num(r.correlation_smh),pct(r.mean_daily_return),pct(r.positive_fraction),pct(r.worst_day)]));
}
for(const id of ['window','scope','weight','period','capital','scale','assets'])$(id).addEventListener('change',render);render();
</script></body></html>'''


if __name__=='__main__':main()
