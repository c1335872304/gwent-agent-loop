# Pilot 010：阶段三多角色 Scheduler canary

> **状态：PASS（2026-09-14）**
>
> 这是控制平面的模型无关 canary。它不启动 Codex、不加载模型、不启动
> Docker，也不写入业务代码；真实 Host 的 role factory 与 durable rebind
> factory 仍需单独做低风险现场试点。

## 目的

按串行路线验证阶段三剩余控制面：

1. Scheduler 按 TaskPacket 的 `primary_owner` 路由到明确的 `product` / `core`
   Runner factory；
2. 第一个任务运行期间落盘 Scheduler snapshot，模拟进程重启；
3. 重启后的 Scheduler 只通过原 handle `rebind`，不重复调用 `start`；
4. Product 任务完成后才启动 Core 任务，保持 `max_concurrency=1`；
5. 关闭的 Product Owner 通过显式 contract refs、版本和 consumer scope
   生成跨域 handoff。

## 执行与结果

执行命令：

```text
PYTHONPATH=. python3 scripts/agent_loop/run_stage3_canary.py
```

结果摘要：

| 检查项 | 结果 |
|---|---|
| Scheduler 模式 | serial，`max_concurrency=1` |
| Owner 路由顺序 | `product → core` |
| 重启 checkpoint | `scheduler_status=running` |
| 原 Runner 重绑定 | `STAGE3-PRODUCT-001`，无重复 `start` |
| 两个任务最终状态 | `completed / completed` |
| 跨域 handoff | `product → core`，`product-http:v1` |
| 模型调用 | `0` |
| Docker | `not_run` |
| Scheduler 事件 | `6` |

## 代码与边界

- `scheduler.py` 新增严格 snapshot restore；活动任务没有可验证的
  `rebind(task, handle)` 时进入 `human_required`，并暂停后续排队任务；
- `scheduler_backend.py` 新增 `RunnerExecutionBackend.rebind` 和
  `MultiRoleRunnerExecutionBackend`；每个 Owner 必须提供自己的 factory，
  不允许跨域 fallback；
- `handoff.py` 新增 `ContractHandoffEnvelope`，只允许已关闭的领域 Owner
  向另一个领域 Owner 传递 contract；Test Agent 仍走原有独立验证 handoff；
- `test_scheduler.py`、`test_scheduler_backend.py`、`test_handoff.py` 和
  `test_stage3_canary.py` 覆盖正常恢复、fail-closed、角色路由和 contract
  字段约束。

## 未由本次 canary 证明的事项

本次没有消费模型，也没有证明 Codex Host 在独立进程重启后能查回真实
thread/session。生产接入必须提供能按持久化 `runner_ref` 恢复既有
`RunnerExecution` 的 rebind factory；如果平台只允许重新创建任务，控制面
必须保持 `human_required`，不能自动重跑。
