# Teacher Task Entry Card

> **适用：** grounded explanation、evidence、privacy、provider、`/v1/explain`、BFF Teacher contract、`TeacherPanel`。
> **Owner：** Teacher。先读 [`teacher-explanation`](../../../.agents/skills/teacher-explanation/SKILL.md)；本卡不定义游戏决策或网页交互规则。

## 先读什么

1. [`../TEACHER_AND_WEB.md`](../TEACHER_AND_WEB.md)、[`../../../services/teacher/README.md`](../../../services/teacher/README.md)；
2. [`EVIDENCE_CONTRACT.md`](../../../.agents/skills/teacher-explanation/references/EVIDENCE_CONTRACT.md) 和 [`PRIVACY_BOUNDARY.md`](../../../.agents/skills/teacher-explanation/references/PRIVACY_BOUNDARY.md)；
3. 涉及 BFF、Core HTTP 或 React 时，再读 [`PRODUCT.md`](PRODUCT.md) 与 [`../../../apps/web/docs/CORE_API_CONTRACT.md`](../../../apps/web/docs/CORE_API_CONTRACT.md)；
4. 最接近的 evidence builder、privacy filter、response schema、provider / fallback 与回归测试。

## 不可跨越的边界

- Teacher 只把已执行的真实 AI action 或 Core clone 已执行的 branch action 翻译为解释；不持有或 step Core handle。
- 不产生、覆盖或重新计算 `option_index` / legal actions；不把语言流畅当作 evidence。
- 浏览器不能收到 AI 隐藏手牌、未公开候选动作或经 alternatives 间接泄露的私有信息。
- provider 只改变措辞；evidence extraction、privacy filter、response schema 和 deterministic fallback 必须 provider-neutral。
- Teacher / preview 失败只能降级解释面板；不能让真实 gameplay step 失败，也不能通过截断 trace 掩盖 clone 污染。

## 最小验收

- `python .agents/skills/teacher-explanation/scripts/check_teacher.py`；
- 诊断测试：`PYTHONPATH=. pytest -q services/teacher/tests` 与 `PYTHONPATH=apps/web/backend pytest -q apps/web/backend/tests/test_teacher_api.py`；
- 改动 `TeacherPanel` 时运行 `cd apps/web/frontend && npm run build`；
- Python pytest 的最终 PASS/FAIL 仍以 TaskPacket 声明的 Docker 测试和 final snapshot 为准；同时证明隐私过滤与“Teacher failure 不阻断 gameplay”。

## 何时 handoff

| 缺口 | 接收方 |
|---|---|
| 解释所需的权威游戏事实、执行 action 或结构化 trace 不存在 | Core / Strategy 定义并输出 structured evidence |
| policy / value metadata 不存在或语义不明 | Trainer 与 Core 确认来源和可公开范围 |
| 纯展示、loading、error UX 或 BFF 消费问题 | Product；Teacher 不跨界修改产品交互 |

若 privacy、snapshot、evidence provenance 或 provider 权限不确定，停在 `HUMAN_REQUIRED`；禁止扩大浏览器可见数据作为修复。
