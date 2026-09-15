# Teacher Runtime

`services/teacher/` 是只读解释服务。它把 Strategy 已执行动作和公开 evidence 转换成教学文本，不参与动作选择、legal action 或 PPO。

## Agent entry

- 一屏任务入口（evidence、privacy、验证、handoff）：[`TEACHER.md`](../../docs/current/agent-entry/TEACHER.md)；
- 全仓库路由与 handoff：[`AGENT_ONBOARDING_INDEX.md`](../../docs/current/AGENT_ONBOARDING_INDEX.md)；
- 必读 Skill：[`teacher-explanation`](../../.agents/skills/teacher-explanation/SKILL.md)；
- evidence 结构：[`EVIDENCE_CONTRACT.md`](../../.agents/skills/teacher-explanation/references/EVIDENCE_CONTRACT.md)；
- 隐私边界：[`PRIVACY_BOUNDARY.md`](../../.agents/skills/teacher-explanation/references/PRIVACY_BOUNDARY.md)；
- 产品集成和降级行为：[`TEACHER_AND_WEB.md`](../../docs/current/TEACHER_AND_WEB.md)。

缺少结构化事实时，先交给 Core/Strategy 扩展 contract；纯展示、loading 或 error UX
交给 Product。不要让 Teacher 通过重算动作、解析 label 或读取隐藏信息补齐 evidence。

能力：

- DecisionPacket / TraceDecision 输入；
- Beginner / Intermediate / Advanced 三档解释；
- probability / value 与本地 card/rule evidence；
- deterministic fallback；
- 可替换语言 Provider；
- HTTP API；
- 人机对局隐藏信息保护。

详细边界见 [`../../docs/current/TEACHER_AND_WEB.md`](../../docs/current/TEACHER_AND_WEB.md)。最小验证为 Teacher check、`services/teacher/tests` 与相关 BFF Teacher API 测试；修改 `TeacherPanel` 时另运行前端 build。
