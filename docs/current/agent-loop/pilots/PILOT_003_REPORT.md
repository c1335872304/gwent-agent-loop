# Pilot 003：第一阶段单领域闭环记录

> 记录属性：历史阻塞记录；本文保留当时的 executor 故障证据，不代表当前实现状态。

状态：`BLOCKED`，不是业务代码失败。

## 目标

由 Product 子 Agent 完成一个低风险 Core HTTP contract 硬化，再由独立
Test/Verification Agent 在 Docker 中验证，保存 ChangeReport、TestReport 和
RunManifest。

## 已完成

- Product 子 Agent 只修改了：
  - `apps/web/backend/app/models/core_contract.py`
  - `apps/web/backend/tests/test_core_contract.py`
- `GameState.mode` 不再默认降级为 `manual_test`；缺失字段会被拒绝；
- Product contract 子集在宿主机通过：8 passed；
- Main 复核 diff，确认没有越过 Product 任务范围；
- Main 在 Docker canonical 环境通过：104 passed，2 个已有弃用警告；
- 结构化工件已保存：TaskPacket、ContextBrief、ChangeReport、TestReport、
  RunManifest。

## 未完成与阻塞

- 独立 Test/Verification 子 Agent 在读取文件和启动 Docker 前被 Windows
  executor `helper_unknown_error: setup refresh had errors` 阻断；
- 因此 TestReport 必须是 `BLOCKED`，不能改写成 `PASS`；
- 宿主机完整 backend 测试缺少 `pytest-asyncio`，只作为环境诊断；
- 仓库尚无 HEAD commit，Git 初始提交因未配置 author identity 被拒绝；
- 本次实际 Product 子任务使用了 file-hash manifest 记录，尚未证明从 Git
  worktree 启动的真实 Codex Host Transport。

## 结论

Pilot 003 证明了 Product 子 Agent 的受限修改和 Main 的 Docker 复核路径，
但没有满足第一阶段的完整退出条件。恢复点是：先解决 Git author identity
和独立 Test Agent executor，再从最终 snapshot 重新完成独立验证；不需要重新
设计角色，也不需要修改模型。
