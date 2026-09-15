# Agent Loop 工件模板

## 文档职责

新 Agent 的读取顺序、路由和验证选择只看 [`../AGENT_ONBOARDING_INDEX.md`](../AGENT_ONBOARDING_INDEX.md)；
Loop 执行、停止和交付只看 [`START_HERE.md`](START_HERE.md)；当前能力和现场证据只看
[`CURRENT_STATE.md`](CURRENT_STATE.md)。本页只做模板目录，不复制上述协议。

项目导航：[AGENT_LOOP_NAVIGATION.md](../AGENT_LOOP_NAVIGATION.md)；三阶段路线图：[IDEAL_LOOP_3_STAGE_PLAN.md](IDEAL_LOOP_3_STAGE_PLAN.md)；模型范围：[MODEL_SCOPE.md](MODEL_SCOPE.md)；坑记录：[LESSONS_LEARNED.md](LESSONS_LEARNED.md)。领域任务卡和开场模板见 [`../agent-entry/README.md`](../agent-entry/README.md)。

历史 Phase/Pilot 报告只从 [`archive/README.md`](archive/README.md) 按需追溯，不进入默认上下文。
`pilots/` 是为早期确定性回归保留的兼容夹具，详见其
[`README.md`](pilots/README.md)；它同样不提供当前状态。

## 模板目录

按任务需要读取：`TASK_PACKET_TEMPLATE.yaml`、`CONTEXT_BRIEF_TEMPLATE.yaml`、
`CHANGE_REPORT_TEMPLATE.yaml`、`HANDOFF_REPORT_TEMPLATE.yaml`、
`REVIEW_REPORT_TEMPLATE.yaml`、`TEST_REPORT_TEMPLATE.yaml`、
`RUN_MANIFEST_TEMPLATE.yaml`、`INTEGRATION_MANIFEST_TEMPLATE.yaml` 和
`EXPERIENCE_MANIFEST_TEMPLATE.yaml`、`SHADOW_QUERY_TEMPLATE.yaml` 和
`SHADOW_RETRIEVAL_TEMPLATE.yaml`；E3 生成的 ContextBrief advisory 区域按
`CONTEXT_BRIEF_TEMPLATE.yaml` 的 `advisory` 字段校验。E4 固定回归使用
`REGRESSION_SET_TEMPLATE.yaml`，比较结果使用 `PROMOTION_REPORT_TEMPLATE.yaml`；E5
只读提案使用 `PROPOSAL_BUNDLE_TEMPLATE.yaml`；E6 训练前置审查使用
`TRAINING_READINESS_TEMPLATE.yaml`。

## 使用规则

1. 每个开始实施的任务先从 `TASK_PACKET_TEMPLATE.yaml` 创建不可变的 TaskPacket。
2. 非琐碎任务先从 `CONTEXT_BRIEF_TEMPLATE.yaml` 创建 ContextBrief，建立事实来源图和可扩展工作集。
3. 每次 Owner 实施或修复创建一个 ChangeReport；不要覆盖旧 attempt。
4. Reviewer、Tester 与跨边界 Owner 分别使用独立报告模板。
5. `.agent-loop/` 是本机控制状态和原始工件目录，已被忽略；需要提交的结论先脱敏并复制到这里或任务文档。
6. 模板中的占位符必须替换；缺失字段应明确写 `unknown`、`none` 或 `not_run`，不能静默删除。

这些模板不授权执行、部署、合并或扩大权限。上下文优先级和排除项以
[`CONTEXT_INDEX.yaml`](CONTEXT_INDEX.yaml) 的 `context_policy` 为准；领域语义仍以
根目录 `AGENTS.md`、对应 Skill 和正式 contract 为准。
