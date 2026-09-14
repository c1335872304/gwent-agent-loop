# Pilot 001：Agent Loop 协议演练报告

> 记录属性：历史协议演练；当前状态以 [`CURRENT_STATE.md`](../CURRENT_STATE.md) 为准。

## 结论

Pilot 001 通过。它验证了“Context/Integration 先形成边界明确的 ContextBrief，再交给 Test/Verification 做只读验证，最后生成 RunManifest”的最小闭环。

这不是整个项目通过，也不是 Phase 4 完成；本次没有开启真实 Codex 子任务，没有启动 Docker，没有修改业务代码。

## 范围

- TaskPacket：`PILOT_001_TASK_PACKET.yaml`
- ContextBrief：`PILOT_001_CONTEXT_BRIEF.yaml`
- RunManifest：`PILOT_001_RUN_MANIFEST.yaml`
- 允许写入：仅 `docs/current/agent-loop/pilots/`
- 基线快照：`file-hash-manifest:c86098912fce433728e0751f78dbaa0136f5b77e87afa693393b8543947b575e`

## 证据

| 检查 | 结果 |
|---|---|
| Agent Loop assets | PASS：6 个 Profile、ContextIndex、TestMatrix |
| 文档链接 | PASS |
| Agent Loop 单元测试 | PASS：19 tests |
| Docker 可用性探测 | PASS：仅读取 Server version，未启动容器 |
| 生产代码写入 | PASS：0 个 |
| 模型加载 | 未执行：当前 Python 环境缺少 `torch` |

## 发现并修复的问题

首次 preflight 暴露了两类真实 schema 问题：

1. 使用 `max_subtasks: 0` 时，验证器错误地把它当成必须为正的预算字段而拒绝。该问题已修复：`max_subtasks` 与 `max_subtask_depth` 现在允许为零，并由 Context/Integration 回归测试覆盖。
2. 初版 Pilot 文档只写了便于阅读的字段，没有完整映射正式 `TaskPacket` / `RunManifest` 契约；校验器拒绝了缺失的 protocol、ownership、workspace、budget、artifact 和 event 字段。现已按正式 schema 补齐，并重新验证通过。

这说明 Pilot 的价值不是把预先写好的 PASS 文件盖章，而是让执行记录必须真的通过机器契约。

## 边界判断

- `models/v3/policy.pt` 按 Trainer contract 视为运行时资产；没有伪造 provenance，也没有删除或替换它。
- 缺少 `torch` 属于 Trainer/环境阻塞，不属于本 Pilot 可越权处理的问题。
- Git 尚未提交；用户的 staged/working-tree 变更保持原样，Git identity/remote 仍需用户确认。
- 本次是单上下文手工演练，不等价于独立 Codex 子任务之间的真实隔离评审。

## 下一步

1. 选一个低风险 Product 或 Teacher 小改动，运行一次真实“Owner 修改 → Test/Verification 独立复核”的闭环。
2. 再验证 Docker compose 白名单、测试数据隔离和失败分类。
3. 通过两个真实试点后，才进入 Phase 4 的 Runner/跨进程执行器设计；不要先无限增加 Agent 数量。
