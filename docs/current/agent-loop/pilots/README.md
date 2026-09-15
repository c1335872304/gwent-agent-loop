# 早期 Pilot 兼容工件

> **属性：历史兼容夹具，不是当前状态，也不是新 Agent 的默认上下文。**

本目录仅保留 Pilot 001–003 的原始 TaskPacket、ContextBrief、报告和
RunManifest。`scripts/agent_loop/test_pilot_artifacts.py` 会对其中的固定路径做
确定性回归，因此暂不移动或删除这些文件。

新任务不得从本目录推断当前能力、当前测试数量、下一步或阻塞原因。当前现场证据
以 [`../PILOT_018_REPORT.md`](../PILOT_018_REPORT.md) 和
[`../CURRENT_STATE.md`](../CURRENT_STATE.md) 为准；其他历史试点从
[`../archive/README.md`](../archive/README.md) 按需追溯。

如果未来要迁移这些夹具，必须同时更新回归测试、所有工件内部引用和归档索引，
并在一次完整架构门禁后再提交。
