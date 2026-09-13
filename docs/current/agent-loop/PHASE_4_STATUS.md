# Phase 4 状态：真实闭环试点

状态：进行中（Pilot 002 已完成，尚未满足 Phase 4 退出条件）

当前实时状态请以 [`CURRENT_STATE.md`](CURRENT_STATE.md) 为准；本文件保留 Phase 4 和 Pilot 002 的历史证据。

## 已完成

- 完成一次不修改业务代码的协议演练：Context/Integration → Test/Verification。
- 生成 TaskPacket、ContextBrief、RunManifest 和报告，包含快照、角色运行、预算、门禁和未解决阻塞。
- 发现并修复 `max_subtasks: 0` 被验证器错误拒绝的问题，并加入回归测试。
- 确认 Docker 可用，但本次没有启动服务或创建容器。
- 完成一次低风险 Product 真实改动试点，并由 Docker pytest 和架构门禁复核。

详见：[Pilot 001 任务包](./pilots/PILOT_001_TASK_PACKET.yaml)、[上下文简报](./pilots/PILOT_001_CONTEXT_BRIEF.yaml)、[运行清单](./pilots/PILOT_001_RUN_MANIFEST.yaml)、[报告](./pilots/PILOT_001_REPORT.md)。

## 尚未完成

- 尚未开启真实 Codex 子任务，因此还没有验证独立上下文和跨任务 handoff。
- 尚未验证 Docker compose 白名单、测试数据隔离、容器清理和服务失败分类。
- 尚未处理 Trainer 本地模型加载阻塞：当前环境缺少 `torch`；这保留给 Trainer/环境边界处理。
- 尚未满足“真实业务改动至少通过两轮独立验证”的 Phase 4 退出条件。

## 下一阶段

实现并验证一个真实外部 Runner 适配器；仍限制在单一领域 Owner，Test/Verification 独立复核，并记录冲突、失败分类、预算和最终快照。若出现越权或不确定性，立即停在人工闸门，不扩大任务范围。

## Current implementation boundary

The role model is complete: Main, four domain Owners, Context/Integration, and Test/Verification. The project does not need another Manager, Planner, Reviewer, or QA role. Planner is a Context/Integration mode; Reviewer and Tester are Test/Verification modes.

The runtime loop is not complete yet. The real platform bridge is still missing: opening a bounded subtask, passing structured context, collecting a report, resuming the same responsibility chain, and closing the session without losing evidence. The generic adapter, Codex project-task request builder, and injected Host Transport lifecycle mapping are implemented, but they do not call the host API.

The model-free lifecycle contract is implemented in `scripts/agent_loop/runner.py`. The identity-bound execution record layer is implemented in `scripts/agent_loop/execution.py`; it binds an existing TaskStore packet revision, persists bounded events, projects role runs for RunManifest, and enforces snapshot/write-scope identity, budget-before-open, and a resume limit. The shared ContextBrief contract is implemented in `scripts/agent_loop/validate_packet.py`; the validated launch envelope is implemented in `scripts/agent_loop/launch.py`; the transport-only response adapter is implemented in `scripts/agent_loop/external.py`; the Owner-to-Verification handoff is implemented in `scripts/agent_loop/handoff.py`; the allowlisted verification plan is implemented in `scripts/agent_loop/verification.py`; the TestReport evidence gate is implemented in `scripts/agent_loop/report_validation.py`; bounded recovery decisions are implemented in `scripts/agent_loop/recovery.py`; and the Codex project-task request builder is implemented in `scripts/agent_loop/codex_bridge.py`. Together they reject mismatched TaskPacket, ContextBrief, AgentProfile, scope, budget, raw transcript input, malformed responses, runner reference drift, open-source handoffs, out-of-scope changes, non-allowlisted test commands, false PASS reports, unbounded retries, and non-reproducible child-task snapshots. These layers do not launch Codex, Docker, or a model; the host API transport remains the next implementation boundary.

## Next implementation sequence

1. Connect a platform-specific host bridge to the existing open, wait, interrupt, resume, and close operations.
2. Run one real Owner subtask, then one independent Test/Verification subtask; do not allow recursive spawning.
3. Add bounded Docker execution only for a TaskMatrix allowlisted service test, with health, logs, ownership-scoped cleanup, and HUMAN_REQUIRED on unknown ownership.
4. Require two successful independent validation rounds before considering the loop ready for limited automation.

## Stop conditions

Stop and return to a human gate when the Runner loses the session, the final snapshot is unknown, the write scope overlaps, the budget is exhausted, Docker ownership is unclear, a report is incomplete, or a test change may weaken an assertion. Do not add agents to recover from these conditions.

## Pilot 002 result

Pilot 002 completed a real low-risk Product change: after a fresh snapshot load, `GamePage` clears pending actions, selected card state, and the acted-turn marker. The Product diff is limited to one frontend file and leaves Core actions, HTTP contracts, Teacher behavior, models, and Trainer code unchanged.

Evidence:

- frontend production build passed;
- canonical Docker pytest passed 66 tests;
- architecture gate passed with 29 Agent Loop tests;
- host async pytest failure was classified as ENVIRONMENT_FAILURE because the host lacks pytest-asyncio;
- TaskPacket, ContextBrief, ChangeReport, TestReport, RunManifest, and final report are stored under `pilots/PILOT_002_*`.

Phase 4 remains in progress: this is a manual Owner to Test/Verification pilot with a deterministic execution-record layer, not proof of a real Codex child session, automatic resume, or bounded automatic repair.
