# Pilot 005：阶段二受控恢复与集成闸门

> 日期：2026-09-14
> 记录属性：历史试点记录；集成闸门的后续结果以 Pilot 006–007 和 `CURRENT_STATE.md` 为准。
> 状态：恢复与独立验证通过；父工作树人工集成闸门待处理

## 结论

本次试点完成了一次真实 Codex CLI Product Owner → 独立 Test / Verification
闭环，并在 Owner 首次 rollout 已持久化后注入一次 Runner 丢失。系统记录了
`LOST`，在执行恢复决策后只对同一 Runner、同一责任链执行了一次有界
`RESUME_SAME_RUNNER`，随后 Owner 关闭，Test Agent 从 Owner 最终 commit
独立开始验证。恢复次数为 1，未发生递归派生或第二次 Owner 创建。

试点没有自动修改父工作树。因为父工作树包含 33 个已存在的用户改动路径，
IntegrationManifest 正确停在 `human_required`；候选 commit 没有冲突，也没有
未经批准的 merge、stash、reset 或 rollback。

## 试点范围

- Task：`GW-REAL-PRODUCT-001`；低风险 Product 静态 UI 改动；
- base snapshot：`db697d147b48fb6cf3171df6843f4d18e9174160`；
- Owner：`owner-006`，只允许修改 `apps/web/frontend/index.html`；
- Test Agent：`verifier-007`，只允许在
  `apps/web/backend/tests` 写测试；本次未修改测试；
- final / candidate snapshot：
  `23ede8a596cde25b14af69a19ca00ee9f6c1c35c`；
- 实际候选改动：`apps/web/frontend/index.html` 一项。

## 恢复证据

Owner ExecutionJournal 的事件顺序为：

```text
opened(running)
  -> waited(interrupted)
  -> injected loss(lost)
  -> resumed(running, resume_count=1)
  -> waited(interrupted)
  -> closed(closed, resume_count=1)
```

恢复记录包含：`failure_class=RUNNER_FAILURE`、
`action=RESUME_SAME_RUNNER`、`persisted_before_action=true`、
`remaining_budget=1`。这证明恢复决策先写入 ExecutionJournal，再调用有界
resume。

另一次 `owner-005` 试验在首个 rollout 尚未持久化时立即注入丢失，Codex 返回
`no rollout found`，系统没有伪造恢复成功；该结果确立了“只能从已持久化的
rollout 恢复”的现场边界。

## 独立验证证据

`verifier-007` 没有重新执行 Owner，也没有读取 Owner 的实现过程；它从
`23ede8a596cde25b14af69a19ca00ee9f6c1c35c` 启动独立 Test Agent，执行声明的
静态 HTML contract 检查，结果为 `overall: PASS`。验证确认：

- `theme-color` 元标签恰好一处且值为 `#0f172a`；
- React `root` 和 `/src/main.tsx` 入口仍存在；
- commit diff 只有声明的 UI 文件；
- Core API contract 和 frontend request 文件未改变。

本任务是依赖无关的静态 UI 检查，TaskPacket 没有声明服务依赖，因此本次不
启动 Docker。Docker/service-backed Product 任务仍需另一次现场证据。

## 集成闸门

只读 IntegrationManifest 已生成，结果如下：

- `candidate_snapshot` 与 Owner/Test 最终 snapshot 一致；
- `changed_paths` 在 allowlist 内；
- `conflicts=[]`；
- `human_gate.required=true`、`approved=false`、`status=pending`；
- `apply.status=not_applied`；
- rollback 参考为 base snapshot，尚未执行。

当前 RunManifest 的 `status=human_required`，原因是父工作树存在用户改动。
因此阶段二尚未完成父工作树集成、可恢复 rollback 和集成后的第二轮独立
验证。

## 证据索引

- [Stage 2 RunManifest](../../../.agent-loop/tasks/GW-REAL-PRODUCT-001/stage2-run-manifest.json)
- [IntegrationManifest](../../../.agent-loop/tasks/GW-REAL-PRODUCT-001/stage2-integration-manifest.json)
- [Owner ExecutionJournal](../../../.agent-loop/tasks/GW-REAL-PRODUCT-001/artifacts/runner-owner-006.json)
- [Owner ChangeReport](../../../.agent-loop/host-artifacts/GW-REAL-PRODUCT-001/owner-006.json)
- [Independent TestReport](../../../.agent-loop/host-artifacts/GW-REAL-PRODUCT-001/verifier-007.json)
