# Phase 3 状态：验证与环境平面

> 状态：准备中（TestProfile、Context/Integration Profile、测试矩阵、修改闸门和矩阵校验已落地；尚未启动 Docker 试点）
>
> 当前状态请以 [`CURRENT_STATE.md`](CURRENT_STATE.md) 为准；本文件记录 Phase 3 当时的状态。

## 已落地

- [`profiles/test-verification.yaml`](profiles/test-verification.yaml)：Test / Verification 的读写和 Docker 能力边界；
- [`profiles/context-integration.yaml`](profiles/context-integration.yaml)：上下文/文档整合边界，不写生产代码；
- [`TEST_MATRIX.yaml`](TEST_MATRIX.yaml)：Core、Trainer、Product、Teacher 的测试命令、测试写入范围、compose allowlist 和人工 gate；
- [`TEST_MODIFICATION_POLICY.md`](TEST_MODIFICATION_POLICY.md)：测试编辑、断言保护、失败分类和 Docker cleanup 规则。
- `scripts/agent_loop/validate_packet.py`：TestMatrix 的路径、命令、领域和 Docker allowlist 校验。

## 当前不做

The canonical Python pytest container runner is implemented for the declared suite. Docker service-level health, ownership, isolation and cleanup still require a bounded pilot. Do not treat the Python test image as proof that Core C++, frontend runtime, or Trainer checks are all containerized.

- 不启动真实 Docker 服务；
- 不自动修改生产代码；
- 不把 Test Agent 变成领域 Owner；
- 不把 Test / Verification Profile 误称为已经实现的自动测试 Agent/Runner；
- 不把架构阶段的 Trainer/torch 环境阻塞误称为 Agent Loop 失败。

## 测试与 Docker 边界

当前阶段的测试角色已经完成职责、权限和矩阵定义，但还没有独立子会话执行器。架构任务默认使用本地确定性检查；只有实际任务的 TaskPacket 引用了 Product、Teacher 或 Trainer 服务依赖，Test / Verification 才按 `TEST_MATRIX.yaml` 的 compose 白名单启动 Docker，并记录 health、logs、失败分类和 cleanup。

## 进入人工试点前

1. 使用一个低风险 Product 或 Teacher 任务进行人工 Review → Test 闭环；
2. 记录 Docker 成功、依赖缺失、业务失败和 cleanup 四类证据；
3. 确认测试修改确实由领域 Owner 复核，而不是 Test Agent 自证；
4. 再决定是否进入 Phase 4 人工闭环试点。
