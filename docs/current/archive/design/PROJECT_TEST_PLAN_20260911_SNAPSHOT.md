# 项目测试计划：2026-09-11 产品验收快照

> **记录属性：** 历史验收快照，不是当前测试结果、当前 Docker 状态或 Agent Loop 现场证据。
> 新任务应先读取 [`../../PROJECT_TEST_PLAN.md`](../../PROJECT_TEST_PLAN.md)、
> [`../../PROJECT_BASELINE.md`](../../PROJECT_BASELINE.md)、对应领域 Skill、TaskPacket
> 和 [`../../agent-loop/CURRENT_STATE.md`](../../agent-loop/CURRENT_STATE.md)。
> 本文只用于复核当时的产品验收结论。

## 当时的验收目标

本次快照验收以下完整链路：

```text
C++ Core / C ABI
       ↓
Python RL / Collector / checkpoint inference
       ↓
Core HTTP adapter
       ↓
FastAPI BFF
       ↓
React Web / Teacher panel
       ↓
CPU Docker Compose runtime
```

当时的证明目标是：

1. Core 规则、合法动作、C ABI 和 RL schema 没有回归；
2. 已下载的最优模型可以在 CPU Docker 中加载并完成推理；
3. BFF 严格转发 Core contract，前端只提交最新的 `option_index` 及同一状态的 `match_id/revision`；
4. Teacher 只解释已执行的真实动作或 Core clone 中已执行的单个根行动及其必要选择，不泄露 AI 隐藏手牌，也不阻断游戏；
5. Docker 中的 Core → BFF → Web → 浏览器访问链路可以稳定工作。

## 当时的结果

快照结论为“非训练产品链路基本通过，浏览器手动验收待执行”：

- Core 非训练 CTest：**36/36 通过**；另行执行了小规模训练 smoke；
- Core card data/schema 检查：通过；Teacher 静态检查：通过；
- Docker 内 BFF 测试：**17 passed**；Core HTTP adapter 测试：**12 passed**；Teacher 测试：**7 passed**；
- 前端 `npm run build`：通过；
- 当时源码重建的 Core/BFF/Web Compose：healthy；CPU `human_vs_ai` 推理、BFF HTTP、`ability_text`、隐藏手牌边界、版本化预演和 `409 stale_state`：通过；
- Teacher profile health 和 `/api/teacher/explain`：通过；
- 本地训练 smoke：collector 使用 1 个环境、2 个回合通过；PPO/replay smoke 使用 4 个环境、1 次 update 通过，`illegal=0`、`mismatches=0`；
- 浏览器实际点击验收尚未执行；正式训练和训练全量测试按要求暂缓。

## M4 自动验收记录

- 连续 Teacher 预演、真实《盖尔》及其排/位置/牌选择、领袖目标选择均通过；
- 旧 revision 返回 `409 stale_state`，新局返回新 `match_id/revision=0`；
- 停止 Teacher 后真实 `/step` 仍成功；
- human-vs-AI 隐藏手牌边界和卡牌 `ability_text` 通过；
- 仅剩浏览器手工点击与视觉确认，不能由 API smoke 代替。

## 当时的测试环境与范围

测试环境固定为按需构建的 Docker `test` profile：依赖写入
`deploy/docker/requirements.test.txt`，镜像由 `deploy/docker/Dockerfile.test` 构建，测试时挂载当时的工作树。
生产镜像刻意不包含 pytest；测试容器退出后可删除，测试依赖镜像由 Docker layer cache 复用。

该次验收排除正式训练：不执行 `python/tests` 全量、训练任务验证、长时间 PPO 训练和服务器训练，
只执行本地 1 环境 collector smoke 及 4 环境/1 次 update 的最小 PPO/replay smoke；其余训练相关项目标记为“暂缓”。

当时遵循的边界是：Core 是规则和合法动作事实来源，Trainer 负责训练/模型兼容，Product 负责转发和展示，
Teacher 只解释结构化 evidence。

