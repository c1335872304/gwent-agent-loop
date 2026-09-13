# Eval 018：ContextBrief 与正确改动点

不要实际修改代码。请为以下需求建立 ContextBrief 和实施前计划。

需求：

> Web 对局界面展示了一个前端自行计算出的“可行动作”，偶尔与 Core 返回的 actions 不一致。目标是让界面只展示并提交 Core 的合法动作，而不是复刻规则。

## 期望观察点

- 路由 Product Owner 并要求 `$product-integration`；
- ContextBrief 的 context floor 至少包含 `AGENTS.md`、Product Skill、Core HTTP/JSON contract、相关 BFF/前端文件和现有测试；
- 将“Core actions 是唯一合法性来源”记录为带来源的 confirmed fact；
- Owner 可以从 Product 入口受控探索到相关 UI、BFF adapter 和测试，而不是只接受一句摘要；
- 若发现 Core 字段不足，使用 HandoffReport 给 Core，而非让前端解析 label/source/target 文本反推规则；
- 计划必须说明最终应修改的边界、非目标和验收命令。

## 高风险错误

- 把“上下文压缩”理解为只给 Agent 一个文件名；
- 只读前端代码，未读 Product contract/Skill；
- 让多个 Agent 各自重新浏览整个仓库，导致 token 重复消耗。
