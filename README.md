# ETF策略编辑与回测看板

本地运行的中文 ETF 策略看板：编辑 Python 策略、查看收盘信号、解释状态、比较历史收益与回撤，并记录手动执行。适合先研究、再自行核对和下单的个人用户。

**不接入交易账户，不提交订单，不需要券商或币安 API 密钥。** 日线来自 Yahoo 公开行情；界面显示美国 ETF 参考目标，不代表币安证券产品的实际成交报价。

## 功能

- 今日目标、参考行情、收盘确认和盘中预估；Windows 本机提醒。
- 矩形策略卡片：2017年至最新确认收盘、近1／2／3／5年的年化收益和最大回撤。
- Python 文本框编辑、预览、另存策略、保存版本、恢复版本、明确启用。
- 每个策略独立的状态名称、解释及当前触发状态。
- 输入本金，生成收益／回撤表格和每日资金图；同时比较多套策略和 TQQQ、QQQ、XSD、SMH、VGT、SOXX、SOXL。
- 单资产或 QQQ＋TQQQ 双资产目标；历史连续持仓与期初现金建仓两种口径。
- 产品对应关系、执行确认、手动成交台账和本地导出。

## 可导入策略

| 策略 | 使用ETF | 状态数 | 主要规则 |
|---|---|---:|---|
| XSD和SOXL组合策略（内置） | XSD／SOXL | 8 | 年线、短线、运行峰值回撤、放量防御、QQQ环境 |
| SMH和SOXL组合策略 | SMH／SOXL | 8 | 用SMH替换信号与防御标的 |
| SOXX和SOXL组合策略 | SOXX／SOXL | 8 | 用SOXX替换信号与防御标的 |
| MACD＋4%急跌避险策略 | SMH／SOXL／现金 | 11 | MACD柱线为负且SMH昨收至当日最低跌幅≥4%时锁定现金；等待5交易日，柱线非负且收盘≥EMA20后恢复基础目标 |
| QQQ和TQQQ双核策略 V22.1 | QQQ／TQQQ／现金 | 6 | MA200／MA20、运行峰值回撤、前60日均量2.0倍放量阴线、防御反转过滤；常态各45% |
| 纳指四季 V22.3 | QQQ／TQQQ／现金 | 8 | 放量阈值2.2倍；常态TQQQ90%；深跌进攻须MA20上升；正乖离MA200超过20%后降杠杆及现金解锁链 |

首次导入只保存策略，不改变当前启用策略。点击卡片只加载代码；要切换盯盘，请点击“启用选中已保存策略”。

## 安装与运行

需要 Python 3.12（64位）。Windows 可直接运行，无须 WSL。依赖版本固定在 `monitor/requirements.txt`。

```powershell
git clone https://github.com/Shelvz29/etf-strategy-dashboard.git
cd etf-strategy-dashboard
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r monitor/requirements.txt
.\.venv\Scripts\python.exe monitor/import_strategies.py
powershell -NoProfile -ExecutionPolicy Bypass -File monitor/start.ps1 -OpenBrowser
```

浏览器地址：<http://127.0.0.1:8501/>。之后可双击 `monitor/启动看板.vbs`，停止时双击 `monitor/停止看板.vbs`。关闭浏览器不会停止后台；电脑需开机、联网且保持唤醒。Windows 开机启动可选用 `monitor/install-startup.ps1`，取消用 `monitor/remove-startup.ps1`。

**公开仓库不附带本人的数据库、下载行情和大型回测报告。** 首次运行会下载2015年以来的日线，等待完整行情后计算2017年以来的信号。请求失败会报错，请恢复联网后重新运行；程序不会生成替代行情。缓存和账户记录保存在被 Git 忽略的 `monitor/runtime/`，不要上传这个目录。

Linux／WSL 可用两个终端分别运行后台和网页（无Windows弹窗）：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r monitor/requirements.txt
.venv/bin/python monitor/import_strategies.py
.venv/bin/python monitor/service.py
# 第二个终端
.venv/bin/python -m streamlit run monitor/app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
```

## 策略编辑接口

每份策略源文件位于 `monitor/strategies/`。复制代码到编辑框修改，可在保存前预览；保存版本和启用版本是独立操作。

- `BASE_SYMBOL`：XSD、SMH、SOXX或QQQ。
- `PARAMETERS`：兼容现有看板的参数字典；新增自定义参数可放在独立字典，例如 `RISK_RULES`、`STRATEGY_RULES`。
- `STATE_LABELS`／`STATE_NOTES`：状态代码到名称／解释的字典。
- `generate_signals(frames, start="2017-01-02")`：返回完整日期的日线信号表，包含首个交易日的前一日信号，只使用当天及以前的数据。
- 单资产信号用 `symbol`、`weight`；QQQ双资产还须返回 `weight_QQQ`、`weight_TQQQ`、`rebalance_band`，总仓位等于两者之和，双持仓时 `symbol="MIX"`。
- QQQ双资产可选返回布尔列 `rebalance_on_state_change`：省略时仍按状态切换调仓；设为 `False` 时只因目标仓位变化或再平衡阈值触发调仓，适合保留单资产策略移植前的执行方式。不能填写空值、数字或字符串。

运行器限制导入、常见文件／网络操作和运行时长，并检查截断历史是否改变旧信号。它不是操作系统安全沙箱，也不能证明代码完全没有未来数据问题；请只运行自己理解和信任的策略代码。

## moomoo导入版的口径

两份用户提供的原始文件完整保存在 `third_party/moomoo/`。日线适配版保留各自的状态条件、判断优先级、冷静期和目标权重。特别是V22.1的放量阈值为2.0，V22.3为2.2，按原代码而非概述推断。初始化峰值取首次信号日前252根日线的最高价（包含该信号日），随后只由更高收盘价更新，未使用未来全局最高点。

**导入版不是moomoo账户成交过程的完整复制。** 本项目用收盘确认、下一交易日开盘成交，双资产在同一开盘完成调仓；不复制未完成订单暂停、卖出后T+1资金结算等待及等待期间跳过信号、500美元最小调仓金额、整数股数量或账户可用现金限制。目标改变或双资产状态切换会调仓；V22.1常态时，前一收盘QQQ/TQQQ已投资市值偏离超过20%也会调仓。现金不计利息，无账户杠杆和做空。

因此，逐日核对通过指的是**没有账户成交暂停时的状态及目标权重**，不代表回测收益与moomoo实盘相同。QQQ/TQQQ均使用美国ETF行情；没有对应可交易产品时无法照搬执行。

## 回测约定

最早收益交易日为2017-01-03，结束日为最新完整且已确认的美股日线。策略卡片采用历史连续持仓、单边交易成本10基点（0.1%）；历史回测页允许修改成本。原半导体单资产执行引擎保持冻结，QQQ双资产使用单独的资金核算模块。

年化收益按实际日历天数计算；最大回撤按每日收盘账户净值计算，不包含盘中最差亏损。执行价格使用含分红调整的数据以模拟分红再投资，信号价格按策略代码；本金用于金额缩放，不包含实际汇率、税费、证券代币折溢价和额外费用。历史最优指标或信号阈值不能保证未来收益或最大回撤。

## 测试

不需要下载行情的公开测试，检查两个适配版与原代码在构造行情上的每日状态一致、双资产资金守恒、成本、信号延迟和截断历史：

```powershell
cd monitor
..\.venv\Scripts\python.exe -m unittest test_moomoo -v
```

完整回归套件为 `test_monitor test_performance test_strategies test_macd_risk test_moomoo`，使用原研究的冻结行情和MACD研究结果作为基准。这些下载行情不在公开仓库中；没有对应数据时不要把缺失数据错误视为策略失败。GitHub Actions运行可独立复现的构造行情测试；新源码另做编译检查。

## 目录与版本记录

```text
monitor/                       看板、后台、策略编辑、回测、测试
monitor/strategies/             可编辑的发行策略源码
monitor/import_strategies.py    首次导入；不覆盖已有用户版本
third_party/moomoo/             原始策略文件和授权说明
backtests/2026-10-02-xsd-soxl/   冻结的半导体策略与执行引擎
exports/build_project_package.py 本机离线项目包工具（需要本地研究数据）
CHANGELOG.md                    经用户确认发布的更新日志
AGENTS.md                       后续修改、Git记录和发布约定
```

每次开发修改按有意义的阶段保存为本地 Git 提交。**用户确认提交／发布后**才生成当次更新日志、发布标签并推送 GitHub；不会把每个开发中间版本都自动发布。网页内保存的私人策略版本保存在本机数据库，不自动上传仓库；要分享某个版本，请先导出代码并明确选择提交。

## 署名与许可证

项目自行编写的应用代码采用 [MIT](LICENSE)。`third_party/moomoo/` 两份原始策略、对应两份适配策略及其生成器遵循原作者标注的 **CC BY-NC 4.0**，保留署名、标明修改且限非商业使用；不能将这些部分改标为MIT。原作者为 ©2026 园园AI（aiyuan.ai）／财富种植园 [@wealthplantations](https://www.youtube.com/@wealthplantations)。详见 [第三方说明](third_party/moomoo/NOTICE.md) 和 [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)。本项目没有声称得到原作者背书。
