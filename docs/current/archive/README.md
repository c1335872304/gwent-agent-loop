# 当前文档历史归档

本目录保存已经完成、被新基线取代或仅用于追溯的设计/实施记录。它们保留
审计价值，但不是新 Agent 的默认上下文；日常任务应从
[`../PROJECT_BASELINE.md`](../PROJECT_BASELINE.md)、对应 contract 和当前操作文档开始。

## 归档内容

- [`design/AI_DECISION_AND_TEACHER_TURN_PLAN.md`](design/AI_DECISION_AND_TEACHER_TURN_PLAN.md)：AI 决策与 Teacher 行动链的原始设计和实施演进；
- [`design/LOCAL_DOCKER_PLAN.md`](design/LOCAL_DOCKER_PLAN.md)：本地 Docker 方案的设计与实施历史；
- [`design/LOCAL_DOCKER_INSTALL_NOTES.md`](design/LOCAL_DOCKER_INSTALL_NOTES.md)：Windows/Docker Desktop 安装与故障排查复盘；
- [`design/LOGIC_OPTIMIZATION_PLAN.md`](design/LOGIC_OPTIMIZATION_PLAN.md)：`match_id/revision`、action-chain、preview isolation 与产品验收的历史实施记录；
- [`design/PROJECT_TEST_PLAN_20260911_SNAPSHOT.md`](design/PROJECT_TEST_PLAN_20260911_SNAPSHOT.md)：2026-09-11 产品验收快照和 M4 自动验收记录；
- [`design/AGENT_LOOP_PLAN_ORIGINAL_ROADMAP.md`](design/AGENT_LOOP_PLAN_ORIGINAL_ROADMAP.md)：Agent Loop 原始 Phase 0–4 推演、评估清单和最初落地清单；
- [`design/TRAINING_DOCKER_IMPLEMENTATION_ROADMAP.md`](design/TRAINING_DOCKER_IMPLEMENTATION_ROADMAP.md)：训练 Docker M0–M4 原始实施路线和历史 smoke 记录；
- [`../agent-loop/archive/README.md`](../agent-loop/archive/README.md)：Agent Loop 阶段和 Pilot 历史归档索引。

## 使用规则

只有在追查历史决策、复核回归或补充证据时才读取归档文件。归档内容中的
“当前”“下一步”“尚未完成”和旧测试数字均不覆盖当前基线；冲突时以
`PROJECT_BASELINE.md`、`CURRENT_STATE.md`、正式 contract 和实际验证为准。
