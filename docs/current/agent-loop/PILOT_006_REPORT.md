# Pilot 006：阶段二集成、Docker 与预算审计

> 日期：2026-09-14
> 记录属性：历史试点记录；本文的外部 main 和预算结论是执行当时的快照，不覆盖当前状态。
> 状态：集成与验证通过；预算上限审计阻断阶段二最终退出

## 已完成

候选 Product commit `23ede8a596cde25b14af69a19ca00ee9f6c1c35c` 已在用户
明确要求“逐步完成”后通过 disjoint-user-changes 人工闸门，集成后的阶段二
Codex 工作树 snapshot 为 `1d2803e673c691d6f0d840dc3c181c15c9796998`。
集成只改变 `apps/web/frontend/index.html`，该工作树原有 33 个改动路径均保留。

集成后，独立 Test Agent `verifier-008` 从新 snapshot 开始验证，结果为
`overall: PASS`，RunManifest 为 `completed`，scope、contract、test 和 human
四个 gate 均通过，临时 worktree 已清理。

## Docker 证据

按 `python3 scripts/check.py docker-test` 执行 canonical Docker test：

1. 首次构建因 `Dockerfile.test` 缺少 `git` 导致 9 个 bridge/integration 测试
   发生环境错误；其余 110 个测试通过；
2. 镜像补充 `git` 后，首次重建遇到 Debian `libexpat1` 的瞬时 HTTP 502；
3. 有界重试成功，最终 `119 passed, 2 warnings`；容器使用 `--rm`，没有遗留
   测试容器。

这证明 canonical Docker 测试环境和 cleanup 路径可用。本次 Product 任务是
静态 HTML 检查，没有声明 Core/BFF/Teacher 服务依赖，因此未启动服务栈，也
没有伪造 service health 证据。

## Rollback 演练

没有在当前阶段二 Codex 工作树回退已集成的 Product 改动；那会撤销用户已确认的结果。
在 applied snapshot `1d2803e673c691d6f0d840dc3c181c15c9796998` 的隔离 clone
中加入不相关的未提交文件 `user-preserved.txt`，执行真实
`git revert --no-edit 1d2803e673c691d6f0d840dc3c181c15c9796998`，得到回退
commit `52971b4ccb04bddd8a3d7eaaa45237dd37c5fc1b`。验证结果：

- `apps/web/frontend/index.html` 的 tree 与 parent snapshot
  `db697d147b48fb6cf3171df6843f4d18e9174160` 完全一致；
- `user-preserved.txt` 仍存在且保持未提交状态；
- 当前源工作树仍为 `1d2803e673c691d6f0d840dc3c181c15c9796998`，未被演练改变。

因此 rollback 的隔离可恢复路径已通过；父工作树是否实际回退仍必须经过新的
人工决定。

## 外部 main 集成闸门

另对登记的外部 checkout `/mnt/c/codes/gwent_v4` 生成了
`stage2-external-main-integration-manifest.json`。它的目标文件干净，候选
与该 checkout 的 181 个用户改动无路径重叠、无 three-tree conflict，但用户
改动同时包含 5 个 staged、176 个 unstaged 和 1 个 untracked 项。直接
cherry-pick 被 Git 安全拒绝，未产生提交或覆盖；没有使用 stash、reset、
强制 ref 更新或混合用户 index。该外部 main 集成因此保持 `HUMAN_REQUIRED`，
需要用户先决定如何处理其现有 index/worktree 后再继续。

## 真实指标与预算结果

指标链路已接通并在真实 CLI Runner 上采集到：

| Attempt | input tokens | output tokens | elapsed | model turns | 状态 |
|---|---:|---:|---:|---:|---|
| `owner-013` | 427,745 | 11,623 | 177.917 s | 2 | closed |
| `verifier-014` | 114,535 | 3,268 | 83.443 s | 1 | closed |

但这次指标审计使用的 TaskPacket 上限是 input `12,000`、output `6,000`。
系统在生成 RunManifest 时正确判定 `BUDGET_EXHAUSTED` 并停止；没有把超预算
的结果标成 PASS。该结果同时证明 token、耗时、model turns 和停止原因已经
进入 ExecutionJournal，但阶段二的“无超预算”退出条件尚未满足。

## 阶段二当前结论

阶段二的恢复、Codex 工作树集成、集成后二次独立验证、canonical Docker 测试和隔离
rollback 演练均已完成。最终退出仍被预算审计阻断，且本次 Product 任务没有
声明服务依赖，因而没有 service-backed health/failure 证据。后续必须由人工
决定合理的输入/输出预算与上下文计费口径，再重新跑一次同等证据链；不能直接
把上限调大来掩盖当前上下文开销，也不能把 `BUDGET_EXHAUSTED` 改写成成功。

## 证据索引

以下是执行主机上的历史运行时证据路径。`.agent-loop/` 被 Git 忽略，干净
snapshot 不携带这些文件，因此这里保留可审计路径文本而不创建失效链接：

- `.agent-loop/tasks/GW-REAL-PRODUCT-001/stage2-integration-manifest.json`
- `.agent-loop/tasks/GW-REAL-PRODUCT-001/stage2-external-main-integration-manifest.json`
- `.agent-loop/tasks/GW-REAL-PRODUCT-001/stage2-post-integration-run-manifest.json`
- `.agent-loop/host-artifacts/GW-REAL-PRODUCT-001/verifier-008.json`
- `.agent-loop/tasks/GW-REAL-PRODUCT-001/artifacts/runner-owner-013.json`
- `.agent-loop/tasks/GW-REAL-PRODUCT-001/artifacts/runner-verifier-014.json`
- `.agent-loop/host-artifacts/GW-REAL-PRODUCT-001/verifier-014.json`
