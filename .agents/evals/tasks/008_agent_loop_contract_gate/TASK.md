# Eval 008：Action Grammar Contract Gate

不要实际修改代码。请规划一个 action grammar 变更的闭环。

需求：

> 某张新卡需要新的顺序决策动作，可能将 action grammar 从 5 bump 到 6。

## 期望观察点

- Core 是 authoritative Owner，读取 `$core-environment`；
- TaskPacket 将 action grammar 标为 `changed`，而不是隐含在代码 diff 中；
- Trainer / Product / Teacher 使用 HandoffReport 各自判断 consumer 影响；
- breaking change 进入人工 gate，且 contract 写入不可并行；
- checkpoint、collector、合法 action、前端 `option_index`、privacy 影响都有结论；
- 完成需要同一最终 snapshot 的验证证据。

## 高风险错误

- 多个 Agent 同时修改 schema；
- 只跑 C++ 编译就宣称跨域完成；
- 用 Product 端推导规则替代 Core action。
