# Test / Verification Agent

> **当前边界：** 本文只定义独立 Test / Verification 的稳定职责、Docker 规则和报告格式；现场能力与限制只以 [`CURRENT_STATE.md`](CURRENT_STATE.md) 为准。Pilot 报告是历史证据，不能替代 TaskPacket、最终 snapshot 或 TestReport。

## Docker readiness note

The repository has a working Docker foundation, but it is not a universal all-tests runner. The canonical image covers the declared Python pytest scope, while Core C++ tests, frontend builds, and full Trainer validation retain their own commands. Current evidence and pinned-image results belong in [`CURRENT_STATE.md`](CURRENT_STATE.md) and the relevant TestReport rather than this stable role contract.

The agent must never run a global `docker compose down` on a shared project. It must record pre-existing containers, use `run --rm` or an isolated project name, and clean only resources created by the current attempt. Unknown ownership means `HUMAN_REQUIRED`.

## Canonical pytest environment

The pinned Docker test image is the canonical environment for Python pytest. It contains pytest, pytest-asyncio, PyYAML, tomli, project API dependencies, and CPU torch. Use `python3 scripts/check.py docker-test` to rebuild the image when its manifest changes and run the current working tree tests. The `python3` launcher is required on the WSL/Linux Host; the test image itself runs its pinned Python entrypoint.

Host pytest may be used only to diagnose host dependency problems. A host PASS or FAIL is not the authoritative Product, Teacher, or Agent Loop test result. The container is intentionally run with `--rm`; dependencies persist in the image, while container state does not.

The Test Agent itself starts in the Codex `workspace-write` sandbox. A task that
needs the canonical Docker command must explicitly set
`TaskPacket.execution.host_docker: true`; the Host Bridge then selects the
Docker-capable sandbox only for `test-verification`, after validating the
profile and the declared `docker-test` command. Ordinary Test tasks retain the
workspace sandbox, and the capability is persisted across Host rebind. This
does not grant Docker access if the Host process itself lacks the Docker socket
group; that condition is reported as `PERMISSION_REQUIRED`. When Docker is used,
the TestReport must use `environment.runner: docker` exactly, with plural
`compose_files`, `health: passed`, `cleanup: complete`, and non-empty
`evidence_refs`; `host-docker` is not a valid report runner value.

本地 Codex CLI Host 的独立 Test 任务、Docker capability handoff、有限恢复、
service-backed health/failure/cleanup，以及隔离集成后的第二轮 Docker 验证均已有
现场证据。最新完整串行多角色证据是 [`PILOT_018_REPORT.md`](PILOT_018_REPORT.md)；
Docker 的使用仍必须由当前 TaskPacket 声明，不能因历史 Pilot 自动扩大权限。

## 角色定位

Test / Verification Agent 是独立验证角色，不是第五个业务 Owner，也不是 Manager。四个领域 Agent 负责修改各自生产实现，Test / Verification Agent 负责复核结果、执行声明的测试、维护声明范围内的测试文件，并输出可审计证据。

实际路由配置位于 [`.codex/agents/test-verification.toml`](../../../.codex/agents/test-verification.toml)，能力边界位于 [`profiles/test-verification.yaml`](profiles/test-verification.yaml)。

## 输入和输出

输入必须包括：

- TaskPacket：任务范围、允许的测试写入目录、验收命令和预算；
- ContextBrief：事实来源、相关坑记录和拒绝使用的上下文；
- Owner ChangeReport：改动文件、contract 影响和自测结果；
- base/final snapshot；
- [`TEST_MATRIX.yaml`](TEST_MATRIX.yaml) 和 [`TEST_MODIFICATION_POLICY.md`](TEST_MODIFICATION_POLICY.md)。

输出必须是 TestReport 或 ReviewReport，并包含：

- 实际执行的命令和退出码；
- final snapshot；
- 通过、失败、未执行和不确定的检查；
- failure class；
- changed test paths；
- Docker 启动、health、日志和 cleanup 证据（仅在实际使用 Docker 时）；
- 需要 handoff 的领域 Owner 和下一步。

## 权限边界

允许：

- 读取仓库事实、contract、Skill、Owner 变更和测试结果；
- 在 TaskPacket 声明的 `test_write_roots` 内新增或修改测试；
- 按 TestMatrix allowlist 运行测试命令；
- 在明确授权且可清理时使用 Docker。

禁止：

- 修改 `src/`、`include/`、`python/src/`、产品实现、Teacher 实现、模型和训练输出；
- 改 schema、action grammar、HTTP、privacy 或 reward contract；
- 删除或削弱断言以制造 PASS；
- 把测试修改当成最终修复；
- 默认启动 Docker 或加载 `policy.pt`；
- 派生子 Agent。

## Docker 判定

| 情况 | Docker |
|---|---|
| Agent Loop / 文档 / schema / 单元测试 | 不需要 |
| Product/Teacher 纯 Python 或前端构建 | 按命令需要，默认不启动 |
| BFF/Core/Teacher 服务集成 | TaskPacket 明确后按 allowlist 启动 |
| Trainer 训练或 checkpoint 验证 | 由 Trainer Task 决定，不由 Test Agent 自行扩大范围 |

任何 Docker 运行都必须有 bounded timeout、health 证据、日志摘要、失败分类和 cleanup。cleanup 无法证明时状态只能是 `HUMAN_REQUIRED`。

## 生命周期

```text
Owner ChangeReport
      ↓
读取 TaskPacket / ContextBrief / TestMatrix / final snapshot
      ↓
执行声明的测试
      ├─ PASS → 写 TestReport → Owner/人工 Review gate
      ├─ CODE_DEFECT / CONTRACT_GAP → 交回领域 Owner
      ├─ ENVIRONMENT_FAILURE / DOCKER_FAILURE → 记录阻塞，不改业务代码
      └─ 权限、预算、范围或 cleanup 问题 → HUMAN_REQUIRED
```

本地 CLI 的真实 Host-backed rebind、独立进程恢复、串行多角色 handoff 和 Docker Test 已由 Pilot 018 验证。Desktop/MCP Host 是可选的后续适配器，不影响本地 CLI 受限串行路径。任何恢复失败、预算耗尽或权限不确定都必须进入 `HUMAN_REQUIRED`，不能通过新增 Agent 绕过；当前已完成能力和仍关闭的自动修复、并行、部署与模型变更以 [`CURRENT_STATE.md`](CURRENT_STATE.md) 为准。
