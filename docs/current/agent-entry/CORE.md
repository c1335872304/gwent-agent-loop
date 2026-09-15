# Core Task Entry Card

> **适用：** 卡牌、规则、legal action、pending choice、C ABI、Observation / Action Grammar / Reward ABI、runtime card catalog。
> **Owner：** Core。先读 [`core-environment`](../../../.agents/skills/core-environment/SKILL.md)；本卡只选择下一份事实来源。

## 先读什么

1. [`../CORE_CONTRACTS.md`](../CORE_CONTRACTS.md) 与 [`../../../config/rl_contract.json`](../../../config/rl_contract.json)；
2. 按触发项只增加一份专门 reference：
   - 新卡：[`CARD_EXTENSION.md`](../../../.agents/skills/core-environment/references/CARD_EXTENSION.md)；
   - spawn / transform / helper / 牌组外派生卡：[`RUNTIME_CARD_CATALOG.md`](../../../.agents/skills/core-environment/references/RUNTIME_CARD_CATALOG.md)；
   - action、pending choice、C ABI 或 option：[`ACTION_CONTRACT.md`](../../../.agents/skills/core-environment/references/ACTION_CONTRACT.md)；
   - observation、grammar 或 reward ABI：[`SCHEMA_CONTRACT.md`](../../../.agents/skills/core-environment/references/SCHEMA_CONTRACT.md)；
3. 最接近的 `src/`、`include/`、`tests/` 或 [`../../../tools/golden/README.md`](../../../tools/golden/README.md) 现有实现与回归。

## 不可跨越的边界

- C/C++ Core 是规则、合法动作和环境 schema 的唯一事实来源；Python、BFF、React 与 Teacher 不补写规则。
- 消费者只能消费 Core 返回的结构化 action；不能由文本、label 或牌数反推 target、row、position 或合法性。
- breaking observation / grammar / reward 变化只由 Core 更新 `rl_contract.json` 与生成 mirror；不要手改 mirror，也不要连带 bump 无关版本。
- runtime dependency 必须走真实 `Game::create()`；不能只用手工装满 catalog 的 fixture 宣称运行时可用。
- 私有状态不能因 C API / Observation / Collector 变化泄露给对手；不要用 RL schema 作为产品 trace 的容器。

## 最小验收

- schema / ABI / action 任务运行 `python3 .agents/skills/core-environment/scripts/check_schema.py`；
- 新卡、顺序决策或 runtime catalog 运行最接近的 Core unit、golden / trace，并补真实 `Game::create()` 回归；
- 记录 final snapshot、执行命令和退出码。跨产品或训练消费者时，由独立 Test 在声明的 matrix 中补验证。

## 何时 handoff

| 变化 | 接收方 |
|---|---|
| observation、action grammar、reward ABI | Trainer 判断 checkpoint 的 resume / warm-start / incompatible；Product / Teacher 仅在消费字段时复核 |
| Core HTTP 字段或动作语义 | Product 更新 strict BFF model、API contract、TS types 与 UI |
| 新 Teacher evidence | Teacher 做 privacy filter、response schema 与降级验证 |

交接包只包含 contract 差异、consumer scope、ChangeReport 和最终 snapshot；不要让消费者从 Core Agent 的过程聊天中猜测规则。
