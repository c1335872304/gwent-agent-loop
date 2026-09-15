# Training Tasks

`configs/training/` 描述算法参数，`training/tasks/` 描述一次可执行训练任务的生命周期。

## Agent entry

- 一屏任务入口（任务类型、资产边界、验证、handoff）：[`TRAINER.md`](../docs/current/agent-entry/TRAINER.md)；
- 本文只保留 Training Task 的生命周期和运行接口事实；任务分类、Skill、资产和验证选择统一由入口卡提供。

先判断任务是算法 config、正式 Training Task、resume、warm-start、evaluation 还是
promotion。环境 schema/action grammar 由 Core 定义；Trainer 只判断兼容性与迁移策略，
不能通过调参掩盖 Core 或 collector 缺陷。

```text
Training Task
  ├─ config
  ├─ initialization / resume policy
  ├─ game budget
  ├─ runtime
  ├─ checkpoint / eval
  └─ compatibility metadata
       │
       ▼
Python Orchestrator
       │
       ▼
gwent_rl.train_ppo
```

关键原则：

- warm-start 与 resume 不混用；
- source checkpoint 的 schema/grammar metadata 必须显式；
- 训练异常先排查 environment / collector / reward / GAE，再调优化参数；
- 正式产品只使用封盘 checkpoint，不依赖训练目录。

当前训练与 V3 设计见 [`../docs/current/TRAINING_AND_MODEL.md`](../docs/current/TRAINING_AND_MODEL.md)。正式任务先用 `validate_training.py` 验证定义并完成 smoke；不要把服务器训练环境或 `runs/` 当作产品 Web 的运行时依赖。
