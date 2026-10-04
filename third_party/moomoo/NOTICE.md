# 原始moomoo策略与适配说明

原作者：©2026 园园AI（aiyuan.ai），财富种植园 @wealthplantations。

- `qqq-tqqq-v22.1-moomoo.txt`：QQQ/TQQQ 双核量化策略 V22.1。
- `nazhi-siji-v22.3-moomoo.txt`：纳指四季 QQQ/TQQQ 量化策略 V22.3。

文件由本项目用户提供，按字节完整保存，未改动原代码或原署名。原文件声明的许可证为 [Creative Commons Attribution-NonCommercial 4.0 International（CC BY-NC 4.0）](https://creativecommons.org/licenses/by-nc/4.0/)。

原资料链接：[YouTube](https://www.youtube.com/@wealthplantations)、[AI助手](https://aiyuan.ai)、[纳指四季](https://aiyuan.ai/strategy/nazhi-siji)、[领取策略](https://aiyuan.ai/gift)、[会员网站](https://wealthplantations.com)。原文件中的其他联系信息仍保留在原文件中。

修改内容：从moomoo专用账户API转换为DataFrame日线信号；添加本地看板元数据、状态解释与QQQ/TQQQ目标权重；移除交易账户执行和消息API。对应适配文件及`monitor/strategies/prepare_moomoo.py`保留CC BY-NC 4.0标注。具体账户执行差异见项目README的“moomoo导入版的口径”。

分享与改编须保留适当署名、许可证链接、修改说明，且仅用于非商业用途；本项目MIT许可证不改变这些部分的授权。原作者没有为本项目或回测结果提供认可或背书。

2026-10-05用户要求本地看板将99%目标改为100%。发行适配代码只覆盖此仓位档位，原状态触发条件和其他仓位档位保留；两份第三方原文件仍按原字节保存。构造行情测试逐日核对状态，并明确只允许原99%目标变为100%，不再宣称这些目标权重与原文件完全相同。
