# Runtime Runs

`runs/` 保存训练、评估和调试运行时输出，例如 checkpoint、`eval.jsonl` 和训练日志。

## Agent entry

- 训练任务路由：[`AGENT_ONBOARDING_INDEX.md`](../docs/current/AGENT_ONBOARDING_INDEX.md)；
- 必读 Skill：[`training-config`](../.agents/skills/training-config/SKILL.md)；
- 正式任务格式：[`training/README.md`](../training/README.md)；
- 需要长期引用的资产：[`artifacts/README.md`](../artifacts/README.md)。

`runs/` 是可再生成输出，不是稳定 contract、产品依赖或默认 Agent 上下文。需要恢复、
warm-start 或 promotion 时，只按明确 task/run id 读取，并把长期 source 固化到 `artifacts/`。

这些文件不是 C++ / Python 源码的一部分。当前正式策略由单独的最终模型槽 `models/v3/policy.pt` 表示。
