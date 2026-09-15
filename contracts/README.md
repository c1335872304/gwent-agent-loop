# Cross-layer Contracts

该目录记录跨层稳定边界。原则是：消费者依赖结构化 contract，而不是复制规则或解析展示文本。

## Agent entry

- 全仓库路由、handoff 和验证索引：[`AGENT_ONBOARDING_INDEX.md`](../docs/current/AGENT_ONBOARDING_INDEX.md)；
- Core schema/action owner：[`core-environment`](../.agents/skills/core-environment/SKILL.md)；
- Product HTTP consumer boundary：[`product-integration`](../.agents/skills/product-integration/SKILL.md)；
- Teacher evidence/privacy boundary：[`teacher-explanation`](../.agents/skills/teacher-explanation/SKILL.md)；
- 当前稳定事实：[`PROJECT_BASELINE.md`](../docs/current/PROJECT_BASELINE.md)。

先识别 contract 的 authoritative Owner，再识别所有消费者和版本/迁移影响。一个
contract change 不能由消费者单方面定义；结构化字段不足时要向事实 Owner 请求扩展，
不能用文本解析、宽松 schema 或静默兼容掩盖差异。

主要 contract：

- RL contract manifest：`config/rl_contract.json`；
- Core → Web：[`../apps/web/docs/CORE_API_CONTRACT.md`](../apps/web/docs/CORE_API_CONTRACT.md)；
- Strategy → Teacher：`python/src/gwent_rl/contracts/decision_packet.py`；
- Skill 内部约束：`.agents/skills/*/references/`。

各 contract 独立演进：Product API version 不等于 Observation Schema，也不等于 Action Grammar。
