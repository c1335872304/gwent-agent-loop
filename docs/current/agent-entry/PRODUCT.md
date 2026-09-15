# Product Task Entry Card

> **适用：** `apps/web/` React、FastAPI BFF、Core HTTP/JSON、动态合法动作、产品 UX。
> **Owner：** Product。先读 [`product-integration`](../../../.agents/skills/product-integration/SKILL.md)；本卡不重新定义 HTTP 或游戏规则。

## 先读什么

1. [`../../../apps/web/README.md`](../../../apps/web/README.md) 与 [`../../../apps/web/docs/CORE_API_CONTRACT.md`](../../../apps/web/docs/CORE_API_CONTRACT.md)；
2. 涉及 Teacher panel、preview 或解释时，再读 [`../TEACHER_AND_WEB.md`](../TEACHER_AND_WEB.md) 与 Teacher card；
3. 当前端点、Pydantic model、TypeScript type、组件和最近的 BFF / frontend tests；
4. 需要服务测试时，只按 TaskPacket / TestMatrix 读取 [`../agent-loop/TEST_AGENT.md`](../agent-loop/TEST_AGENT.md) 和 Docker allowlist。

## 不可跨越的边界

- Core HTTP 返回的 `actions` 是唯一合法性来源；前端只渲染它们，并原样提交同一 state 的 `option_index`、`match_id` 与 `revision`。
- `stale_state` 是刷新 state 的协议结果，不是规则引擎故障；每次 step 后丢弃旧 action index。
- 只消费结构化 action fields；禁止解析 `label`、`source` 或 `target` 文本来推断规则。
- BFF 不 import RL、不加载 C++ shared library 或 checkpoint；训练服务器不是产品运行时依赖。
- Teacher 是旁路：预演、解释、provider 或 panel 失败不得阻断 `/game/step`；不要把 branch action 写进真实 AI 动作历史。

## 最小验收

- 先检查 Core HTTP contract、Pydantic model、TS type 和 UI 是否同步；breaking change 必须明确 `api_version` 处理；
- BFF 诊断：`PYTHONPATH=apps/web/backend pytest -q apps/web/backend/tests` 与 `python -m compileall -q apps/web/backend/app`；
- 前端改动：`cd apps/web/frontend && npm run build`；
- Product / Teacher Python pytest 的最终 PASS/FAIL 使用 TaskPacket 声明的 `python3 scripts/check.py docker-test`，host pytest 只用于诊断。

## 何时 handoff

| 发现 | 接收方 |
|---|---|
| 缺失、错误或不稳定的 legal action / match state / authoritative HTTP field | Core 定义并交付结构化 contract |
| Teacher evidence、隐私、response schema 或 provider 问题 | Teacher 处理 grounded evidence 与 privacy；Product 仅处理 BFF / UI 消费 |
| 训练、模型加载、checkpoint 或推理策略问题 | Trainer；Product 不以 runtime workaround 掩盖模型或 collector 问题 |

交接时锁定最终 snapshot 与 changed paths；独立 Test 只从 Owner 的最终结果开始验证，不读取实现过程。
