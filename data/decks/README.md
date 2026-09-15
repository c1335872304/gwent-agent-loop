# Deck Manifests

Deck manifests are lightweight compositions over the supported card library.
They reference card ids from `data/cards/supported_cards.json` and do not own
card text, static card identity, effect ids, or rules.

## Agent entry

- Core 任务路由：[`AGENT_ONBOARDING_INDEX.md`](../../docs/current/AGENT_ONBOARDING_INDEX.md)；
- 必读 Skill：[`core-environment`](../../.agents/skills/core-environment/SKILL.md)；
- 卡牌静态数据与 supported/reference 边界：[`data/cards/README.md`](../cards/README.md)；
- 跨层规则与 schema：[`CORE_CONTRACTS.md`](../../docs/current/CORE_CONTRACTS.md)。

牌组只表达 composition，不定义卡牌身份、effect 或规则。任何新 id 先由 Core 支持并
完成相应测试，再写入 deck manifest；训练侧只消费已声明的 deck id，不反向定义卡牌规则。

`deck_a.json` remains the default training/development deck. `deck_b.json` is
the supported White Frost tournament deck. The RL environment and collector
select them independently for player 0 and player 1 with deck ids A/B; Python
training configs use `collector.player0_deck` and `collector.player1_deck`.
Adding another deck should not require duplicating card definitions or effect
handlers.

Every deck manifest must declare `"card_set": "supported_cards"`. Its leader,
stratagem, and every main-deck card id must exist in
`data/cards/supported_cards.json`. Reference-only ids from
`data/cards/reference/all_cards.json` are deliberately invalid here: a card
must first receive Core behavior and tests before a runtime deck can use it.

Run `python tools/codegen/validate_card_data.py` after adding or changing any
deck manifest.
