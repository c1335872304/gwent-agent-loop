# Agent Loop 工件模板

这些模板是 [`AGENT_LOOP_PLAN.md`](../AGENT_LOOP_PLAN.md) 的可提交、人工可读部分。

项目导航：[AGENT_LOOP_NAVIGATION.md](../AGENT_LOOP_NAVIGATION.md)；阶段计划：[AGENT_LOOP_PHASE_PLAN.md](../AGENT_LOOP_PHASE_PLAN.md)；模型范围：[MODEL_SCOPE.md](MODEL_SCOPE.md)；坑记录：[LESSONS_LEARNED.md](LESSONS_LEARNED.md)。

当前唯一现状入口：[`CURRENT_STATE.md`](CURRENT_STATE.md)。本目录中的 Phase 状态和 Pilot 报告保留历史证据，不覆盖当前状态。

三阶段路线图：[`IDEAL_LOOP_3_STAGE_PLAN.md`](IDEAL_LOOP_3_STAGE_PLAN.md)。

当前实现状态：

- Phase 1 资产：`AGENT_PROFILE_TEMPLATE.yaml`、`profiles/`、`CONTEXT_INDEX.yaml`、`RUN_MANIFEST_TEMPLATE.yaml`；
- Phase 2 第一版：`scripts/agent_loop/` 的状态机、预算、锁、snapshot、校验和本地持久化；
- Phase 3 准备：`TEST_MATRIX.yaml`、`TEST_MODIFICATION_POLICY.md` 和 TestMatrix 校验；
- Test / Verification Agent: `TEST_AGENT.md` and `.codex/agents/test-verification.toml` are implemented; the concrete Codex CLI cross-session transport is available;
- Recovery policy: `RECOVERY_POLICY.md`, `recovery.py`, and `RunnerExecution.recover()` are connected; Pilot 005 proves one live bounded same-runner loss/resume;
- Pilot 005: `PILOT_005_REPORT.md` records the live recovery chain and the parent integration gate as it stood at that time; later integration evidence is in Pilots 006–007;
- Pilot 006: `PILOT_006_REPORT.md` records the applied integration, post-integration verification, canonical Docker result, rollback rehearsal, and initial budget audit;
- Pilot 007: `PILOT_007_REPORT.md` records the isolated unattended integration path, recalibrated budget audit, and final canonical verification;
- Pilot 008: `PILOT_008_REPORT.md` records the service-backed Docker health, controlled failure classification, and ownership-scoped cleanup evidence;
- Phase 2 integration gate: `INTEGRATION_MANIFEST_TEMPLATE.yaml`, `integration.py`, and its deterministic tests provide read-only planning, explicit approval, disjoint isolated auto-integration, and applied-snapshot recording; direct mutation of a dirty parent remains human-gated;
- Phase 3 P0 Scheduler: `scheduler.py` and `test_scheduler.py` provide serial FIFO routing, pause/resume/end, hard concurrency/task/token/time limits and append-only scheduling evidence; `PILOT_009_REPORT.md` records the canary;
- Phase 3 Runner backend: `scheduler_backend.py` and `test_scheduler_backend.py` bind `RunnerExecution` to the Scheduler, preserve cumulative metrics as deltas, count model turns, and require persisted resume artifacts;
- Phase 3 multi-role control plane: `MultiRoleRunnerExecutionBackend`, strict Scheduler restore/rebind and `ContractHandoffEnvelope` are covered by `PILOT_010_REPORT.md`; the canary is model-free and the live Host rebind remains a separate gate;
- Live multi-role canary design: `PILOT_011_TASK_DESIGN.md` defines the bounded Product → Teacher → Test task, restart injection point, budget and fail-closed conditions;
- Codex transport boundary: `CODEX_TRANSPORT.md`, `scripts/agent_loop/codex_bridge.py`, `scripts/agent_loop/codex_cli_bridge.py`, and `scripts/agent_loop/bounded_loop.py` are implemented; the Desktop MCP adapter remains injectable;
- Phase 4 试点：已完成一次无业务代码写入的 Pilot 001，证据位于 `pilots/`；
- 阶段记录：[PHASE_1_STATUS.md](PHASE_1_STATUS.md)、[PHASE_2_STATUS.md](PHASE_2_STATUS.md)、[PHASE_3_STATUS.md](PHASE_3_STATUS.md)、[PHASE_4_STATUS.md](PHASE_4_STATUS.md)。

## 使用规则

1. 每个开始实施的任务先从 `TASK_PACKET_TEMPLATE.yaml` 创建不可变的 TaskPacket。
2. 非琐碎任务先从 `CONTEXT_BRIEF_TEMPLATE.yaml` 创建 ContextBrief，建立事实来源图和可扩展工作集。
3. 每次 Owner 实施或修复创建一个 ChangeReport；不要覆盖旧 attempt。
4. Reviewer、Tester 与跨边界 Owner 分别使用独立报告模板。
5. `.agent-loop/` 是本机控制状态和原始工件目录，已被忽略；需要提交的结论先脱敏并复制到这里或任务文档。
6. 模板中的占位符必须替换；缺失字段应明确写 `unknown`、`none` 或 `not_run`，不能静默删除。

这些模板不授权执行、部署、合并或扩大权限。实际权威顺序仍以根目录 `AGENTS.md`、领域 Skill 和 TaskPacket 为准。
