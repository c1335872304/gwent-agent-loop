# Agent Loop 工件模板

## 新对话入口

新 Agent 或新对话先读 [`../AGENT_ONBOARDING_INDEX.md`](../AGENT_ONBOARDING_INDEX.md)
定位责任域和最小事实集，再读 [`START_HERE.md`](START_HERE.md)。本目录集中说明
受限串行模式、本地 Codex CLI、Docker 验证、停止条件和交付物；不要依赖旧聊天
记录或临时记忆重新摸索。

这些模板是 [`AGENT_LOOP_PLAN.md`](../AGENT_LOOP_PLAN.md) 的可提交、人工可读部分。

项目导航：[AGENT_LOOP_NAVIGATION.md](../AGENT_LOOP_NAVIGATION.md)；三阶段路线图：[IDEAL_LOOP_3_STAGE_PLAN.md](IDEAL_LOOP_3_STAGE_PLAN.md)；模型范围：[MODEL_SCOPE.md](MODEL_SCOPE.md)；坑记录：[LESSONS_LEARNED.md](LESSONS_LEARNED.md)。领域任务卡和开场模板见 [`../agent-entry/README.md`](../agent-entry/README.md)。

当前唯一现状入口：[`CURRENT_STATE.md`](CURRENT_STATE.md)。本目录中的 Phase 状态和 Pilot 报告保留历史证据，不覆盖当前状态。

## 当前默认上下文

新对话只需要按 [`START_HERE.md`](START_HERE.md) 操作。当前运行状态、已验证
能力和最新现场结论看 [`CURRENT_STATE.md`](CURRENT_STATE.md)；本地 CLI Host 的
生命周期看 [`CODEX_TRANSPORT.md`](CODEX_TRANSPORT.md)；Test/Docker 边界看
[`TEST_AGENT.md`](TEST_AGENT.md)；可复用坑看 [`LESSONS_LEARNED.md`](LESSONS_LEARNED.md)。

`PILOT_018_REPORT.md` 是当前现场证据。其他 Phase/Pilot 报告已移到
[`archive/README.md`](archive/README.md)，默认不读取；它们只用于复核历史证据、
追查回归或解释旧决策。

模板按需读取：`TASK_PACKET_TEMPLATE.yaml`、`CONTEXT_BRIEF_TEMPLATE.yaml`、
`CHANGE_REPORT_TEMPLATE.yaml`、`HANDOFF_REPORT_TEMPLATE.yaml`、
`REVIEW_REPORT_TEMPLATE.yaml`、`TEST_REPORT_TEMPLATE.yaml`、
`RUN_MANIFEST_TEMPLATE.yaml` 和 `INTEGRATION_MANIFEST_TEMPLATE.yaml`。

## 使用规则

1. 每个开始实施的任务先从 `TASK_PACKET_TEMPLATE.yaml` 创建不可变的 TaskPacket。
2. 非琐碎任务先从 `CONTEXT_BRIEF_TEMPLATE.yaml` 创建 ContextBrief，建立事实来源图和可扩展工作集。
3. 每次 Owner 实施或修复创建一个 ChangeReport；不要覆盖旧 attempt。
4. Reviewer、Tester 与跨边界 Owner 分别使用独立报告模板。
5. `.agent-loop/` 是本机控制状态和原始工件目录，已被忽略；需要提交的结论先脱敏并复制到这里或任务文档。
6. 模板中的占位符必须替换；缺失字段应明确写 `unknown`、`none` 或 `not_run`，不能静默删除。

这些模板不授权执行、部署、合并或扩大权限。实际权威顺序仍以根目录 `AGENTS.md`、领域 Skill 和 TaskPacket 为准。
