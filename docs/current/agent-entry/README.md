# Domain Task Entry Cards

> **用途：** 给已经完成仓库总入口读取的新 Agent，一屏定位某个领域任务的最小事实集、不可跨越边界、验证与 handoff。
> **不是：** 新协议、第二份领域知识或实时状态。规则以对应 Skill / contract 为准；运行状态以 [`../agent-loop/CURRENT_STATE.md`](../agent-loop/CURRENT_STATE.md) 为准。

先读 [`../../../AGENTS.md`](../../../AGENTS.md) 和 [`../AGENT_ONBOARDING_INDEX.md`](../AGENT_ONBOARDING_INDEX.md)，再按责任域只打开一张卡：

| 任务责任域 | 入口卡 | 唯一工作流来源 |
|---|---|---|
| 规则、卡牌、legal action、C ABI、RL schema | [`CORE.md`](CORE.md) | [`core-environment`](../../../.agents/skills/core-environment/SKILL.md) |
| PPO、collector、Training Task、checkpoint、promotion | [`TRAINER.md`](TRAINER.md) | [`training-config`](../../../.agents/skills/training-config/SKILL.md) |
| React、FastAPI BFF、Core HTTP、UX | [`PRODUCT.md`](PRODUCT.md) | [`product-integration`](../../../.agents/skills/product-integration/SKILL.md) |
| Teacher evidence、隐私、provider、TeacherPanel | [`TEACHER.md`](TEACHER.md) | [`teacher-explanation`](../../../.agents/skills/teacher-explanation/SKILL.md) |

若任务涉及两个领域，先由最接近 authoritative fact 的 Owner 打开自己的卡并定义 contract 差异；另一个 Owner 只接收明确的 handoff、最终 snapshot 和消费者范围。不要同时把两张卡当作并行写入授权。
