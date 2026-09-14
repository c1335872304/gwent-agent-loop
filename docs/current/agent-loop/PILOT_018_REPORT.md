# Pilot 018：本地 Host 理想串行 Loop 现场报告

> **状态：** PASS
> **运行 ID：** `GW-IDEAL-20260915-004`
> **TaskPacket revision：** 5
> **日期：** 2026-09-15

## 结论

本次低风险 Product canary 在本地 Codex CLI Host 上完成了完整的受限串行
责任链：

```text
Product Owner
  -> 新进程 Scheduler.restore / 原 runner_ref rebind
  -> Teacher contract/privacy review
  -> 独立 Test Agent + Docker Test 1
  -> 隔离 branch/worktree 集成
  -> 独立 Test Agent + Docker Test 2
  -> 隔离 rollback rehearsal
  -> RunManifest completed
```

RunManifest 的 7 个 gate 全部为 `passed`，4 个 role runs 全部为 `closed`。
父工作树没有被直接改写；集成结果保留在隔离分支中。

## Snapshot 与范围

| 项目 | 值 |
|---|---|
| base snapshot | `94f35e4d51d9a54b155bc9b0a334ed78ba740d2d` |
| Product candidate | `c95584faff0747027b9521188a3dcaa4a8c45384` |
| isolated applied snapshot | `207fe91f58f545f8614716905230b3db7b0cb35e` |
| isolated branch | `agent-loop/GW-IDEAL-20260915-004/integration-5` |
| changed paths | `apps/web/frontend/src/components/TeacherPanel.tsx` |
| candidate diff | 1 file, 3 insertions |
| parent state | clean and untouched |

Product 只在 `TurnAnswer` 成功展示区读取 typed
`response.schema_version` 与 `response.grounded_facts.length`；Teacher response
contract、API 请求、游戏规则和模型文件没有变化。

## 真实角色与预算

| role | attempt | input | output | model turns | elapsed |
|---|---|---:|---:|---:|---:|
| Product | `gw-ideal-20260915-004-product-1` | 238,436 | 3,177 | 1 | 4.1s |
| Teacher | `gw-ideal-20260915-004-teacher-1` | 189,538 | 5,204 | 1 | 113.8s |
| Test 1 | `gw-ideal-20260915-004-test-1` | 214,462 | 4,425 | 1 | 112.6s |
| Test 2 | `gw-ideal-20260915-004-test-2` | 330,804 | 4,848 | 1 | 133.8s |
| **合计** | **4 runs** | **973,240** | **17,654** | **4** | **364.3s** |

RunManifest 上限为 input 1,000,000、output 64,000、model turns 24、elapsed
90 分钟；本次均未超限。

## 独立 Docker Test 证据

两轮 Test Agent 都从各自声明的最终 snapshot 启动，并执行完全相同的
`python3 scripts/check.py docker-test`：

- `overall: PASS`；145 passed，2 warnings；
- `environment.runner: docker`；
- compose allowlist：`deploy/docker/compose.cpu.yml`；
- Docker health：`passed`；
- cleanup：`complete`；
- `changed_test_paths: []`；
- 两轮均无失败分类，TestReport validator 通过。

原始 RunManifest、IntegrationManifest、两个 TestReport、Teacher report 和
rollback 证据保存在被忽略的运行目录：
`.agent-loop/live-runs/GW-IDEAL-20260915-004/`。

## 恢复、集成与回滚

- Product 由第一个控制进程创建；bootstrap 持久化 Scheduler 后立即启动新
  进程。新进程通过同一 `runner_ref`
  `codex:local:01a0a0d3-8761-74b0-916a-6988bc3c0cd4` 完成 lookup/rebind，未重复
  create。
- IntegrationManifest 记录了 base、candidate、changed paths、空冲突、空用户
  改动和回滚 ref；隔离 branch/worktree cherry-pick 成功，`parent_untouched: true`。
- rollback rehearsal 在隔离 worktree 中执行 `git revert`，生成
  `78192ee65cb59005f1583b14b847deb1ab1e516f`，恢复 base tree，未触碰父工作树。
- 直接合入外部脏 `main` 仍不是本次操作的一部分，继续保留人工 gate。

## 校准记录

前两次试跑被正确拦截而没有伪造 PASS：一次是 Teacher packet 的 64k 输入上限，
另一次是过宽的 Teacher 工具扫描导致约 1.31m 输入。随后将 Teacher profile
输入上限对齐到 1,000,000，并把 Teacher 任务收窄为静态 contract/privacy review；
最终 Teacher 实际使用 189,538 input tokens，现场闭环通过。
