# Pilot 011：真实 Host 多角色现场任务设计

> **状态：DESIGN_READY，尚未执行**
>
> 本文件是任务设计，不是可直接启动的 TaskPacket。正式启动前必须把
> `workspace.snapshot_ref` 绑定到一个真实、可复现的 Git commit；禁止使用
> `current`、`latest` 或当前脏工作树作为运行基线。

## 为什么选这个任务

当前剩余风险不是游戏规则，而是：

- Scheduler 是否能把不同 Owner 路由到真实 Host-backed Runner；
- Scheduler 进程重启后，是否能按原 `runner_ref` 恢复，而不是重复创建模型任务；
- Product 把 Teacher 相关 contract 交给下游 Owner 后，能否在同一最终 snapshot
  上继续；
- 最终 Test Agent 是否仍然只验证 Owner 的最终结果。

因此选择一个只改一处 UI、无需改变 HTTP/游戏规则/模型的任务作为低风险
canary。它有明确可观察结果，也能触发 Product → Teacher 的跨域 consumer handoff。

## 主任务：Product Owner

| 字段 | 设计值 |
|---|---|
| `task_id` | `GW-STAGE3-LIVE-011` |
| `primary_owner` | `product` |
| `required_skills` | `product-integration` |
| `allowed_write_paths` | `apps/web/frontend/src/components/TeacherPanel.tsx` |
| `forbidden_paths` | `models`, `src`, `include`, `python/src`, `runs` |
| `declared_contracts` | `TeacherTurnResponse: unchanged`；`Core HTTP api_version: unchanged` |
| `handoff_required_before_completion` | `true`，交给 `teacher` 做 consumer contract review |

### 具体需求

在 `TeacherPanel.tsx` 的已有成功响应区域增加一行只读 provenance 信息：

- 展示现有 `response.schema_version`；
- 展示现有 `response.grounded_facts.length`；
- 只使用 TypeScript 已声明的结构化字段；
- 不展示 `response.prompt`，不新增隐藏信息；
- 不修改请求 URL、请求体、Core API 版本或 Teacher response schema；
- 保留现有错误、loading、stale response 和只读推演行为。

### Product 验收

1. 只修改 `apps/web/frontend/src/components/TeacherPanel.tsx`；
2. 成功响应显示 schema 版本和 grounded facts 数量；
3. `response` 为空、请求失败或 stale 时不崩溃，原有降级文案仍存在；
4. 不解析 `label`、`source`、`target` 或解释文本来推导规则；
5. Owner 输出 ChangeReport，并记录最终 commit、实际 changed paths 和自测命令。

## 跨域 handoff：Teacher Consumer Owner

Product 关闭后，Scheduler 生成 `ContractHandoffEnvelope`：

```yaml
from_role: product
to_role: teacher
contract_refs:
  - apps/web/frontend/src/types/game.ts
  - services/teacher/models.py
  - docs/current/TEACHER_AND_WEB.md
contract_version: teacher-turn-response-v1
consumer_scope:
  - services/teacher
changed_paths:
  - apps/web/frontend/src/components/TeacherPanel.tsx
```

随后创建第二个不可变 TaskPacket，`workspace.snapshot_ref` 必须等于
Product 的 `final_snapshot`，`primary_owner=teacher`，执行内容为只读
consumer review：确认新增显示只消费公开的 schema/evidence 计数，不泄露
prompt、隐藏手牌、未公开候选动作或 Teacher 内部 provider 信息。Teacher
输出 Review/ChangeReport；若无实现改动，`changed_paths` 明确写空列表。

## 独立 Test / Verification

Test Agent 只从 Teacher 最终 snapshot 验证，不读取 Owner 执行过程：

- 检查 Product 最终 changed paths 是否严格等于声明范围；
- 检查 Teacher consumer review 是否绑定正确的 Product final snapshot；
- 执行 Product frontend build（若宿主无 Node，则按 TestReport 分类为
  `ENVIRONMENT_FAILURE`，不能伪造 PASS）；
- 执行 canonical Agent Loop / Teacher Python tests；
- 验证 `prompt`、隐藏信息和原始聊天没有进入 UI 或报告；
- 生成 TestReport，列出命令、退出码、环境、snapshot、evidence refs 和
  failure class。

本任务不声明 Core/BFF/Teacher 服务集成，因此不启动 Docker；若现场任务
临时扩大为服务 smoke，必须先创建新 revision 并补充 TestMatrix 的 compose、
health、logs、failure、cleanup 证据。

## Scheduler / Host 故障注入顺序

1. 在 Product Runner 已经 `running` 且已有 `runner_ref` 后落盘 Scheduler snapshot；
2. 停止 Scheduler 控制进程，不停止由 Host 持有的 Codex session；
3. 启动新的 Scheduler 进程，读取 snapshot，调用每角色的
   `rebind(task, handle)`；
4. 断言 Product 不产生第二次 `start`，继续等待原 thread；
5. Product close 后生成上述 Product → Teacher contract handoff；
6. 串行启动 Teacher review，最后交给独立 Test Agent；
7. 任一 rebind 失败、thread 不可查回、snapshot 不一致或权限不明，立即
   `HUMAN_REQUIRED`，禁止自动重跑。

## 预算与运行边界

```yaml
max_concurrency: 1
max_role_runs: 3             # Product, Teacher, independent Test
max_model_input_tokens: 1000000
max_model_output_tokens: 32000
max_model_turns: 12
max_elapsed_minutes: 30
max_subtasks: 0
max_subtask_depth: 0
docker: not_required
model_change: forbidden
parallelism: forbidden
```

## 启动前剩余平台条件

当前代码已经提供本地 Host registry、独立 bridge 进程的
`runner_ref` lookup/rebind，以及不调用 `open` 的 `RunnerExecution` hydration
路径；独立进程回归已通过。Pilot 011 仍只有在现场 Host 提供以下条件后
才能从 DESIGN_READY 变为 RUNNABLE：

1. role-specific create/wait/close factory；
2. 将 durable `runner_ref` lookup/rebind 接入实际 Scheduler backend；
3. rebind 返回已 hydrate 的 `RunnerExecution`，且不调用 `open`；
4. Host 侧状态、报告和最终 snapshot 可被 RunManifest 引用；
5. 使用一个明确、干净的 candidate commit 作为 TaskPacket snapshot。

否则只能继续执行 Pilot 010 的模型无关 canary，不能声称真实多角色现场
PASS。
