# Trainer Task Entry Card

> **适用：** PPO、collector、reward、Training Task、checkpoint、resume、warm-start、evaluation、promotion。
> **Owner：** Trainer。先读 [`training-config`](../../../.agents/skills/training-config/SKILL.md)；本卡不定义 Core 规则或 schema 语义。

## 先读什么

1. [`../TRAINING_AND_MODEL.md`](../TRAINING_AND_MODEL.md) 与 [`../../../training/README.md`](../../../training/README.md)；
2. [`TRAINING_CONFIG.md`](../../../.agents/skills/training-config/references/TRAINING_CONFIG.md)，再定位最接近的 `configs/training/*.yaml` 或 `training/tasks/*.yaml`；
3. 涉及 environment schema、legal action 或 grammar 时，再读 [`CORE.md`](CORE.md) 与 [`../../../config/rl_contract.json`](../../../config/rl_contract.json)；
4. 涉及容器、GPU 或服务器运行时，再读 [`../TRAINING_DOCKER.md`](../TRAINING_DOCKER.md)；只在模型 / promotion 任务中打开 [`../../../models/v3/README.md`](../../../models/v3/README.md)。

## 不可跨越的边界

- `configs/training/` 是算法 / 实验参数；`training/tasks/` 是一次正式运行的预算、初始化、runtime、checkpoint、evaluation 和 resume 声明，不能混用。
- Trainer 消费 Core contract，不反向修改游戏规则、legal action 或 schema；schema / grammar 变化必须由 Core 定义。
- 不用 learning rate、reward、`strict=False`、伪 metadata 或静默裁剪掩盖 environment、collector 或 checkpoint incompatibility。
- checkpoint 必须明确区分 resume、warm-start / migration 与 incompatible；partial evaluation 不是 promotion 证据。
- `runs/` 是可再生成运行输出，`artifacts/` 是长期 pinned 资产，产品模型只通过受控安装进入 `models/v3/`；训练服务器不是 Web runtime。

## 最小验收

- 先用 `python3 scripts/validate_training.py --all` 验证任务定义，再以最小 smoke 验证运行路径；
- evaluation 按完整 episode 记录 matchup、swap-sides、illegal results 和 completed games；
- resume / warm-start / promotion 记录 source、target contract metadata、预算、final checkpoint 与验证证据；
- 训练范围需要时运行 `python3 scripts/check.py train`；不要用 `architecture` PASS 代替 training validation。

## 何时 handoff

| 发现 | 接收方 |
|---|---|
| Core rule、legal action、collector 输入或 schema 本身错误 | Core；先修 capability / contract，再讨论优化 |
| Product 模型槽位、运行时 provenance 或安装问题 | Product 只消费受控模型；Trainer 负责 promotion / install evidence |
| Teacher 需要公开 policy/value metadata | Core / Trainer 确认结构化字段和公开边界，再交 Teacher 解释 |

任何模型替换、promotion、服务器训练、成本或 resume 身份不确定都必须写入 TaskPacket 并走人工 gate；不得用本地临时文件替代可审计资产。
