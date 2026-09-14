# Pilot 009：阶段三串行 Scheduler canary

> 记录属性：历史现场证据；当前状态以 [`CURRENT_STATE.md`](CURRENT_STATE.md) 为准。

> 日期：2026-09-14
> 状态：PASS（模型无关、无 Docker、无生产文件写入）

## 范围

本次只验证阶段三 P0 的控制平面，不启动 Codex、Docker 或任何业务服务。
Scheduler 使用注入的确定性 backend，提交两个合法 TaskPacket：

1. `GW-SCHEDULER-CANARY-001`，路由到 `product`；
2. `GW-SCHEDULER-CANARY-002`，路由到 `core`。

调度上限为 `max_concurrency=1`、`max_tasks=2`、input `2000`、output
`1600`、model turns `8`、elapsed `5` 分钟。

## 现场结果

- 两个 TaskPacket 均被接受并按 FIFO 排队；
- 第一个任务暂停时，第二个任务没有越过它启动；
- 第一个任务恢复并完成后，第二个任务才启动；
- 两个任务最终均为 `completed`，完成更新均带有 report/evidence 引用；
- 8 条 append-only Scheduler 事件连续记录 admission、route、pause、resume
  和 completion；
- 实际 usage：input `24`、output `12`、model turns `2`；
- `git diff --check` 和阶段三 Scheduler 回归测试通过；
- canary 未写入生产目录，状态快照仅写入临时文件。

## 结论

阶段三 P0 的串行路由、FIFO 排队、暂停/恢复/结束接口、并发硬上限、任务数
硬上限、token/turns/elapsed 硬上限和调度事件证据已具备可重复的模型无关实现。
真实 Codex backend、多角色 contract handoff、Scheduler 重启恢复和阶段三
多角色 canary 仍是后续工作，不能由本次 canary 推断已完成。
