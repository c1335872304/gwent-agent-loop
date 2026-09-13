# V3 Policy Slot

`models/v3/policy.pt` 是本地产品运行时使用的最终 V3 policy 位置。

一个 checkpoint 同时包含 Shared、Deck A Private 和 Deck B Private 参数。运行时由当前 deck id 选择对应私有分支。

该目录属于推理运行时资产位置；训练过程产生的中间 checkpoint 仍保留在各自的训练输出目录中。

## 当前架构阶段

当前 Agent Loop 和项目架构工作暂时把 `policy.pt` 视为正确且冻结的运行时输入，不读取、不重训、不替换模型。

范围和退出条件见 [`MODEL_SCOPE.md`](../../docs/current/agent-loop/MODEL_SCOPE.md)。Trainer 未来负责模型结构、contract、评估、promotion 和来源验证。
