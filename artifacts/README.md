# Model Artifacts

`artifacts/` 保存需要被训练或迁移流程精确引用的 pinned 模型资产；普通训练输出仍写入 `runs/`。

## Agent entry

- 训练任务路由：[`AGENT_ONBOARDING_INDEX.md`](../docs/current/AGENT_ONBOARDING_INDEX.md)；
- 必读 Skill：[`training-config`](../.agents/skills/training-config/SKILL.md)；
- compatibility、warm-start 和 promotion：[`TRAINING_AND_MODEL.md`](../docs/current/TRAINING_AND_MODEL.md)；
- 可再生成运行输出：[`runs/README.md`](../runs/README.md)；
- 产品最终模型槽：[`models/v3/README.md`](../models/v3/README.md)。

这里存放可复现引用的长期资产，不是临时实验目录；变更前先确认 source/target contract，
并记录 hash、来源和 migration 决策。

原则：

- `artifacts/checkpoints/registry.yaml` 是 checkpoint 资产索引；
- warm-start source 应固定路径、SHA-256 与 source contract metadata；
- 文件名不是身份，hash 才是稳定身份边界；
- checkpoint compatibility 必须显式验证，不能把不同 contract 的模型静默 resume。

产品最终模型使用 `models/v3/policy.pt`，不依赖本目录中的训练资产。
