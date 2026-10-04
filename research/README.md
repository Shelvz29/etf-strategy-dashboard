# 现金替代资产研究

固定比较 MACD＋4%急跌避险策略的空仓资金转入国债、黄金、股息股票、期权收入 ETF 或反向 ETF 后的表现。研究工具不保存或启用新的策略，不改变当前看板配置，不自动下单。

本次实验冻结截至 2026-10-02。需要本机看板已完成该日行情确认，且策略列表中已保存名为 `MACD＋4%急跌避险策略` 的策略。输入来自本机数据库，数据库、私人策略代码、下载行情与回测报告均不提交公开仓库。研究工具只读取这些输入；使用其他截止日需要创建新的实验目录并更新报告说明。

在项目根目录执行（Windows）：

```powershell
.venv\Scripts\python.exe research\cash_replacement.py
.venv\Scripts\python.exe research\cash_replacement_report.py
.venv\Scripts\python.exe research\verify_cash_replacement.py
.venv\Scripts\python.exe -m unittest discover -s research -p test_cash_replacement.py -v
```

输出位于 `backtests/2026-10-03-smh-soxl-hedges/`，包括离线 HTML、全区间与分年限指标、费用和成交延迟敏感性、条件相关性、逐日净值、原始行情、输入代码哈希和验证记录。页面支持选择历史起点、替换范围、替换比例、本金和资产曲线；短历史资产仅从共同可交易起点比较，不补造上市前数据。`verify_cash_replacement.py` 还需要 Node.js，用于脚本语法及静态交互计算检查，不依赖浏览器预览。

执行信号在收盘确定，下一交易日开盘成交；基准现金无利息；复权 OHLC 隐含分红再投资；不含税、人民币汇率或代币化证券与 ETF 的价格差。替代资产只在原策略目标为现金时持有，原 SMH/SOXL 仓位权重与状态规则保留。部分配置剩余现金无利息，目标未变不每日配平。

单边成本 10 基点，并对所有方案检查 25/50 基点以及额外延迟一天。4 项便携测试验证现金替换范围、与冻结执行引擎的一致性、未来信息隔离和行情粒度/交易日完整性。实际历史另有 10 组逐日独立执行核对，报告的 675 个区间指标逐一核对本金锚点、年化与回撤。

跨资产筛选有多重比较问题。近年分段、成本与延迟敏感性不能替代独立样本外检验，工具不输出统计显著性结论或未来收益承诺。逆向 ETF 的负相关、国债利息或高派息也不保证配合当前交易时机后优于现金。

## SOXL 提前减仓与恢复确认实验

`deleveraging_study.py` 同样读取截至 2026-10-02 的本机确认输入和已有 MACD＋4% 策略，不下载新增数据。价格趋势、波动率、深跌恢复确认和重新加仓确认仅覆盖基础 SOXL 目标，不释放基础现金锁定、不修改 SMH 目标。仓位公式的上限约束施加在成交时；目标不变时实际权重可漂移。所有信号收盘确认、次日开盘成交。

第一阶段固定 25 项（含基准与固定仓位参照），第二阶段根据首轮观察追加 3 项恢复确认与固定上限组合；另有 SMH/SOXL 买入持有。使用 2017—2021 年在第一阶段候选中选型，检查 2022—2024 与 2025—2026。此前已查看这些历史，后半段仅是时间隔离检验，不是真正未知的样本外；追加方案也不参与第一阶段训练选型。

```powershell
.venv\Scripts\python.exe research\deleveraging_study.py
.venv\Scripts\python.exe research\deleveraging_report.py
.venv\Scripts\python.exe research\verify_deleveraging_report.py
.venv\Scripts\python.exe -m unittest discover -s research -p test_deleveraging.py -v
```

输出位于 `backtests/2026-10-04-smh-soxl-deleveraging/`。包含 30 项结果、近1/2/3/5年、自然年与分段指标、成本和成交延迟敏感性、逐日信号、离线交互报告。`strategies/` 中的完整可编辑代码保留私人基础策略，只保存在忽略目录；生成后通过看板工作进程和前缀审计，未保存到私人策略列表或启用，也未授权公开这些代码。

11 组完整曲线与冻结引擎逐日核对，40 组截断重算核对历史信号，5 份导出代码通过工作进程与其审计。5 项单元测试覆盖目标权重、原现金/SMH不变、深跌与加仓边界、禁用风控还原、未来数据隔离。报告验证器对 540 行年限/分段/年度指标独立核对本金、年化与回撤，另检查页面脚本语法和静态筛选计算；该检查不代表浏览器视觉预览。

## QQQ/TQQQ 固定参数移植检验

`qqq_transfer.py` 将本机已保存的 `MACD＋4%急跌＋恢复确认策略` 从 SMH/SOXL 移植到 QQQ/TQQQ，同时比较无MACD的基础组合、仅MACD急跌版、两只ETF买入持有与原SMH/SOXL恢复确认版。只替换标的，不搜索或调整参数，不保存新策略或更换当前启用策略。必须已有这两份私人源策略及截至2026-10-02的确认行情；可用 `--source-name`、`--macd-name` 指定本机保存名称。缓存缺少TQQQ时，使用看板原有行情接口补齐并验证完整日线，不能用填充收益替代。

```powershell
.venv\Scripts\python.exe research\qqq_transfer.py
.venv\Scripts\python.exe research\qqq_transfer_report.py
.venv\Scripts\python.exe research\verify_qqq_transfer.py
.venv\Scripts\python.exe -m unittest discover -s research -p test_qqq_transfer.py -v
```

输出位于 `backtests/2026-10-04-qqq-tqqq-recovery/`，包含近1/2/3/5年及全历史、分段、自然年、10/25/50基点成本和额外延迟一天的结果，以及本金和回撤日线交互图。完整导出策略代码、私人源代码及行情只保存在Git忽略目录，未授权公开。应用工具代码不包含这些私人策略。

移植后QQQ同时承担宏观判断、信号与防御标的的角色。恢复确认条件原样保留；4%急跌使用QQQ最低价相对前收且MACD柱线为负，收盘后才能确认，无法避免触发当天的损失。导出信号设置 `rebalance_on_state_change=False`，保留标的/目标权重变化才交易的原执行方式；已有moomoo策略仍按原有状态变化调仓。

24组全历史成本/延迟曲线与冻结执行引擎逐日核对，其中15组同时核对看板双资产引擎的净值、现金和费用。3份QQQ移植代码及SMH参照通过工作进程和截断重算；2项不依赖私人数据的测试核对标的映射、所有规则输出、两种成交引擎一致性和错误输入。验证器独立检查132行指标及页面5个年限、勾选、资金缩放的静态计算，不代表浏览器视觉预览。本研究没有真正未知的样本外，现金无息，不计税、汇率或代币化证券价差。

## 外部宏观因素与恢复确认实验

`macro_rules.py` 将财政部名义／实际收益率、EIA WTI现货、联储目标利率上限和BLS公告归档CPI量化为四组风险。默认每组最多一票，风险0—4分；倒挂且紧缩单独试验，不重复投票。叠加层只降低基础目标，不释放原现金锁定。除明确标注的ALL方案外，只覆盖进攻ETF；基础MACD及恢复确认保留。目标未变不每日配平，实际权重可能漂移。`macro_study.py` 在SMH／SOXL和QQQ／TQQQ各固定比较20项，包括单因素、风险分数、2日触发／5日解除、固定仓位参照及阈值±20%敏感性。

本研究需要已有私人 `MACD＋4%急跌＋恢复确认策略` 和截至2026-10-02的本机确认行情，不能在刚克隆且没有这些输入时直接运行完整研究。工具不包含私人基础策略，未修改冻结引擎或看板、未导入新策略、未更换当前启用策略。不需要私人数据的规则测试可单独运行。

安装研究的可选Excel读取依赖并获取公开数据：

```powershell
.venv\Scripts\python.exe -m pip install -r research\requirements.txt
.venv\Scripts\python.exe research\macro_data.py
```

`macro_data.py` 获取2015起的财政部XML、EIA XLS、NY Fed公开接口，原始文件和哈希写入Git忽略的 `backtests/2026-10-04-macro-recovery/`。它**不自动下载CPI归档**。另需将BLS各次公告的真实日期、统计月份、总体与核心未季调同比整理到该目录的 `cpi_releases.json`，例如：

```json
[{"release_date":"2023-07-12","month":"2023-06","headline":3.0,"core":4.8,
  "source":"https://www.bls.gov/news.release/archives/cpi_07122023.pdf"}]
```

完整输入必须覆盖2015-01至2026-08，共139次公告，保留官方未公布的2025-10缺口。使用[BLS新闻归档](https://www.bls.gov/bls/news-release/cpi.htm)而不是将月份固定平移到下月，取当次Table A同比列，不把当月环比或当前季调历史误用为首次公布值。HTML/PDF归档无法自动读取时须核对原表，不能补造。已有输入是本机研究数据，不随公共代码发布。核对工具使用BLS当前未季调指数检查录入，不覆盖归档数据，也不证明完整首次公布版本；2016年5、6月核心同比的历史更正差异保留并记录。

```powershell
.venv\Scripts\python.exe research\verify_macro_inputs.py
.venv\Scripts\python.exe research\macro_study.py
.venv\Scripts\python.exe research\macro_report.py
.venv\Scripts\python.exe research\verify_macro_report.py
.venv\Scripts\python.exe -m unittest discover -s research -p test_macro_rules.py -v
```

输出包括离线交互HTML、全历史与近1/2/3/5年、自然年、三个阶段、成本和成交延迟、宏观额外延迟5日、逐日信号、来源及输入哈希。页面支持两组资产、20方案勾选、本金、收益和回撤日线图，并展示Sharpe、Sortino、Calmar、日损失ES95等。12条实际曲线与冻结引擎逐日核对，120次历史截断重算核对信号。6项便携测试覆盖公告可用时点、宏观限制／恢复边界、原现金不变、滞后解除、数据过期和未来信息隔离。报告验证器需要Node.js；独立核对920行年限／年度／阶段／成本／宏观延迟指标，以及页面两组合五年限、资金缩放、勾选和三统计期的静态运算，不代表浏览器视觉预览。

统计关联检查包含每资产13指标×5/20/60交易日，共78项。控制过去20日收益与波动，Newey–West/HAC滞后等于前瞻期，每资产39项做BH修正；结果不参与交易决策，不将风险日数当独立危机事件数，不把关联当因果或收益增益。仅用2017—2021选择回撤≤50%中年化最高的非固定上限方案，再看后两个阶段；此前已经看过这些历史，因此不声称真正未知样本外。完整历史排序只作描述，未按本次结果追调阈值。

数据从观测日起国债／政策延后2个NYSE交易日，油价延后3日，CPI从真实公告日收盘可用，统一次日开盘成交。国债为财政部平价收益率，油价为现货；2020负油价不删除且不直接作普通百分比上涨信号。政策只量化货币政策，关税、财政和新闻情绪未构造历史评分。除CPI公告归档外，其余为当前下载历史，没有完整逐日首次公布库；滞后无法消除更正／修订风险。现金无息，不含税、汇率、代币化证券价差，策略无法规避触发当日跌幅或保证未来最大回撤。
