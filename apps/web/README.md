# Web Product

`apps/web/` 是产品展示层：React 前端 + FastAPI BFF。

## Agent entry

- 一屏任务入口（HTTP、合法动作、验证、handoff）：[`PRODUCT.md`](../../docs/current/agent-entry/PRODUCT.md)；
- 本文只保留 Web 产品拓扑与实现边界；HTTP contract、Teacher 交接和验证选择统一由入口卡提供。

修改前先确定是否只涉及 UI/BFF，还是会改变 Core HTTP contract 或 Teacher evidence。
前者由 Product Owner 完成；后两者必须通过 Core 或 Teacher 的显式 contract handoff，
不要在前端从展示文本推导规则。

```text
React :5173
   │
   ▼
BFF :8010
  /       \
Core     Teacher
:8008     :8020
```

对局页包含：战场、手牌、合法动作、动态排内插入、AI 决策记录与 AI 教师面板。

边界：

- BFF 不加载 `.pt`，不 import RL 策略，不加载 C++ shared library；
- 前端不重建 legal actions；
- target / row / insert position 使用结构化字段；
- Teacher 只接收 live-safe evidence，服务失败不影响游戏。

Core HTTP 字段见 [`docs/CORE_API_CONTRACT.md`](docs/CORE_API_CONTRACT.md)，Teacher/Web 设计见 [`../../docs/current/TEACHER_AND_WEB.md`](../../docs/current/TEACHER_AND_WEB.md)。Python pytest 的最终 PASS/FAIL 证据使用 TaskPacket 声明的 Docker 测试环境；前端改动还要运行 `npm run build`。
