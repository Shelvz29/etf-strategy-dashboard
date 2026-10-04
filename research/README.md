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
