# Phase 1 状态：上下文资产化

> 状态：进行中（资产第一版已落地，确定性校验器尚未实现）
>
> 本记录是阶段实施状态，不替代 [`AGENT_LOOP_PHASE_PLAN.md`](../AGENT_LOOP_PHASE_PLAN.md) 的协议定义。
>
> 当前状态请以 [`CURRENT_STATE.md`](CURRENT_STATE.md) 为准；本文件中的“尚未实现”均是本阶段当时的历史记录。

## 已落地

1. [`AGENT_PROFILE_TEMPLATE.yaml`](AGENT_PROFILE_TEMPLATE.yaml)：统一角色能力、读写范围、Docker 权限、预算和停止条件的字段。
2. `profiles/` 下的四个领域 Owner 与 [`context-integration.yaml`](profiles/context-integration.yaml) 的第一版 Profile。
3. [`profiles/test-verification.yaml`](profiles/test-verification.yaml)：验证角色的 Profile；允许测试范围内编辑，不允许修改生产实现或降低断言标准。
4. [`CONTEXT_INDEX_TEMPLATE.yaml`](CONTEXT_INDEX_TEMPLATE.yaml)：事实索引模板，要求来源、snapshot、状态、owner、trigger terms 和坑记录引用。
5. [`CONTEXT_INDEX.yaml`](CONTEXT_INDEX.yaml)：基于当前未提交工作树的第一版事实索引，包含路由、Core legality、Teacher privacy、模型 provenance 和 Loop 预算五条高频事实。
6. [`RUN_MANIFEST_TEMPLATE.yaml`](RUN_MANIFEST_TEMPLATE.yaml)：一次任务的角色运行、预算、状态事件、工件、gate 和终止信息账本。

## 当前边界

- 当前 Git 仓库仍是 `main` 分支的未提交初始 baseline，因此索引 snapshot 使用 `working-tree-uncommitted; initial-baseline-pending`，不能当作永久 commit ID。
- 这些 YAML 是 Phase 1 的人工可读协议资产；Phase 2 才实现确定性 schema、状态、scope、snapshot 和 budget 校验器。
- 没有启动 Codex 子会话，也没有把完整聊天记录写入项目记忆。
- Profile 不等于提示词；ContextIndex 不等于聊天摘要；RunManifest 不等于最终汇报。

## 进入 Phase 2 前的剩余动作

1. 配置 Git identity 并创建初始 baseline commit。
2. 用 baseline commit 更新 `CONTEXT_INDEX.yaml` 的 `workspace_snapshot` 和所有 `verified_snapshot`。
3. 确认 Profile 的具体路径范围，尤其是 Trainer 的运行输出和 Product/Teacher 的 Docker compose 权限。
4. 实现 `scripts/agent_loop/` 下的确定性校验器，并为五个 Profile、ContextIndex、RunManifest 添加失败用例。

## 验收记录

| 检查 | 状态 | 说明 |
|---|---|---|
| 六个 Profile 文件存在 | pending | 由机械检查确认 |
| ContextIndex 引用的路径存在 | pending | 由机械检查确认 |
| YAML 可解析 | pending | 需要本机 YAML 解析器或 Phase 2 校验器 |
| Git 文件已进入暂存区 | pending | 初始 baseline 前复核 |
| 子 Agent 已按需启动 | not_started | Phase 5 之前禁止 |
