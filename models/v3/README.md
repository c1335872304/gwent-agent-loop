# V3 Policy Slot

`models/v3/policy.pt` 是本地产品运行时使用的最终 V3 policy 位置。

## Agent entry

- 路由与最小事实集：[`AGENT_ONBOARDING_INDEX.md`](../../docs/current/AGENT_ONBOARDING_INDEX.md)；
- 模型/训练 Owner：[`training-config`](../../.agents/skills/training-config/SKILL.md)；
- 当前冻结边界：[`MODEL_SCOPE.md`](../../docs/current/agent-loop/MODEL_SCOPE.md)；
- promotion、来源和兼容性：[`TRAINING_AND_MODEL.md`](../../docs/current/TRAINING_AND_MODEL.md)。

架构、Product、Teacher 和普通 Agent Loop 任务不得读取、哈希、重训、替换或删除该模型。
只有明确的 Trainer 模型结构、checkpoint、promotion 或 loader 验证任务才打开本目录；
验证时必须保留来源、hash 和 contract metadata，而不是只相信文件名。

一个 checkpoint 同时包含 Shared、Deck A Private 和 Deck B Private 参数。运行时由当前 deck id 选择对应私有分支。

该目录属于推理运行时资产位置；训练过程产生的中间 checkpoint 仍保留在各自的训练输出目录中。

## 当前架构阶段

当前 Agent Loop 和项目架构工作暂时把 `policy.pt` 视为正确且冻结的运行时输入，不读取、不重训、不替换模型。

范围和退出条件见 [`MODEL_SCOPE.md`](../../docs/current/agent-loop/MODEL_SCOPE.md)。Trainer 未来负责模型结构、contract、评估、promotion 和来源验证。
