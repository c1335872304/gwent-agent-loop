# Agent Loop 历史归档

本目录保存阶段迁移记录、早期现场 Pilot 和任务设计。它们是审计材料，不是
当前状态、默认上下文或当前待办；新 Agent 不应在普通任务中批量读取本目录。

当前事实入口：

- [`../START_HERE.md`](../START_HERE.md)：新对话操作入口；
- [`../CURRENT_STATE.md`](../CURRENT_STATE.md)：唯一当前状态；
- [`../LESSONS_LEARNED.md`](../LESSONS_LEARNED.md)：已验证的可复用经验；
- [`../PILOT_018_REPORT.md`](../PILOT_018_REPORT.md)：当前本地 CLI Host 现场证据。

## 阶段记录

- [`AGENT_LOOP_PHASE_PLAN.md`](AGENT_LOOP_PHASE_PLAN.md)（旧版阶段计划）
- [`PHASE_1_STATUS.md`](phases/PHASE_1_STATUS.md)
- [`PHASE_2_STATUS.md`](phases/PHASE_2_STATUS.md)
- [`PHASE_3_STATUS.md`](phases/PHASE_3_STATUS.md)
- [`PHASE_4_STATUS.md`](phases/PHASE_4_STATUS.md)

## 早期 Pilot 与任务设计

- [`PILOT_004_REPORT.md`](pilots/PILOT_004_REPORT.md)
- [`PILOT_005_REPORT.md`](pilots/PILOT_005_REPORT.md)
- [`PILOT_006_REPORT.md`](pilots/PILOT_006_REPORT.md)
- [`PILOT_007_REPORT.md`](pilots/PILOT_007_REPORT.md)
- [`PILOT_008_REPORT.md`](pilots/PILOT_008_REPORT.md)
- [`PILOT_009_REPORT.md`](pilots/PILOT_009_REPORT.md)
- [`PILOT_010_REPORT.md`](pilots/PILOT_010_REPORT.md)
- [`PILOT_011_REPORT.md`](pilots/PILOT_011_REPORT.md)
- [`PILOT_012_TASK_DESIGN.md`](pilots/PILOT_012_TASK_DESIGN.md)
- [`PILOT_013_TASK_DESIGN.md`](pilots/PILOT_013_TASK_DESIGN.md)
- [`PILOT_014_TASK_DESIGN.md`](pilots/PILOT_014_TASK_DESIGN.md)
- [`SELF_EVOLUTION_DISCUSSION_20260915.md`](SELF_EVOLUTION_DISCUSSION_20260915.md)：自进化、弯路分析和经验 Promotion 的设计讨论归档；默认不读取。

更早的 Pilot 001–003 及其 YAML 工件保留在 [`../pilots/`](../pilots/)，因为它们
被确定性历史工件测试引用；它们同样只按需读取。

## 读取规则

只有在复核某次 Pilot、追查回归、解释历史决策或验证 Lessons 来源时，才打开
归档文件。历史报告中的“下一步”“未实现”“当前状态”和旧测试数字不能直接
覆盖 `CURRENT_STATE.md`；发现冲突时报告冲突并以当前权威来源为准。
