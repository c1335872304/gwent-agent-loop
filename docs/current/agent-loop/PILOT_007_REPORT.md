# Pilot 007：自动 worktree 复用与预算重校验

> 日期：2026-09-14
> 记录属性：历史试点记录；本文的外部 main 状态是执行当时的快照，不覆盖当前状态。
> 状态（当时）：预算门禁通过；隔离分支自动集成通过；外部 main 保持不动，service-backed 证据仍需专门任务；后续由 Pilot 008 覆盖服务证据。

## 自动化修复

真实闭环启动时，Git 因共享仓库已有同一 detached 基线 worktree 而拒绝创建
child。未删除或修改已有 `fbdb` worktree；在 `codex_cli_bridge.py` 中增加了
受限 fallback：仅当明确 commit 已被占用、child 使用独立目录且 Git 错误确实
是重复 worktree 时使用 `--force`，其他错误继续阻断。新增回归测试验证已有
worktree 内容不变。

## 隔离集成优化

针对外部 `/mnt/c/codes/gwent_v4` 的混合 staged/unstaged index，新增了无人值守
的隔离集成路径 `auto_integrate_isolated`。它先确认 parent snapshot、用户改动
清单和候选 changed paths 没有漂移或重叠，再创建独立分支和 worktree，只在该
隔离目录 cherry-pick 候选 commit，并校验最终 changed paths；失败时只清理本次
创建的分支/worktree。

本次真实执行结果：

- 分支：`agent-loop/GW-REAL-PRODUCT-001/integration-2`；
- worktree：`.agent-loop/integrations/GW-REAL-PRODUCT-001-integration-bwgqara0`；
- parent：`db697d147b48fb6cf3171df6843f4d18e9174160`，保持未修改；
- 隔离应用 snapshot：`227d71ed978aca33e37ee1ddee270fec11391fa8`；
- 声明的 Product changed path 校验：`PASS`；隔离 worktree：`clean`；
- 外部 main 的 181 个用户改动未被 stash、reset、覆盖或混合提交。

因此“完全信任”现在可以自动产出一个可审计的集成分支；只有要直接改变已有
脏 main 时，才保留人工 gate。

## 最终验证

- `python3 scripts/check.py architecture`：83 个 Agent Loop 测试、104 个
  Python 文件语法检查及项目 contract 检查均 `PASS`；
- `python3 scripts/check.py docker-test`：固定 Python 3.10 测试镜像下 `121
  passed`、2 个既有 deprecation warnings，容器使用 `--rm` 完成 cleanup；
- `stage2-external-main-integration-manifest.json`：schema validation `PASS`，
  `isolated_apply.status=applied`；隔离 worktree 状态 `clean`。

## 预算结果

按用户要求，当前 Product Owner、Test/Verification profile 和任务包的 input
上限统一为 `1,000,000`；任务包 output 上限为 `32,000`，Product profile
output 上限为 `32,000`，Test profile 保持 `12,000`。

真实 Owner `owner-019` 和独立 Test `verifier-020` 已关闭，Owner 完成一次
受控 loss/resume，Test 从 Owner 最终 snapshot 开始。实际指标如下：

| Attempt | input tokens | output tokens | elapsed | model turns | 状态 |
|---|---:|---:|---:|---:|---|
| `owner-019` | 803,319 | 16,817 | 258.731 s | 2 | closed |
| `verifier-020` | 141,600 | 4,234 | 102.584 s | 1 | closed |
| 合计 | 944,919 | 21,051 | 361.315 s | 3 | budget PASS |

第一次进程启动时仍持有旧的 `16,000` output 配置，因此旧 manifest 在收尾时
触发 `BUDGET_EXHAUSTED`；没有重跑 Owner，而是使用已关闭的 journal 和 PASS
TestReport，在新配置下重新生成 `stage2-budget-final-manifest.json`。该
manifest 的状态是 `human_required`（外部 main 集成尚未获批），预算、scope、
contract 和 TestReport 均通过。

## 当前边界

- Codex 阶段二工作树曾产生候选
  `e3e04b776104ab5b3c192631f48f21887a6a7c1f`；最终用于本次隔离应用的应用候选
  为 `1d2803e673c691d6f0d840dc3c181c15c9796998`，未覆盖已有应用结果；
- 外部 `/mnt/c/codes/gwent_v4` 仍有 181 个用户改动，目标 Product 文件干净，
  但直接写入混合 index 仍不能替用户处理；隔离分支已安全应用；
- 本次仍是静态 Product 任务，没有声明服务依赖，因此没有伪造 service-backed
  health/failure 证据。

## 证据

- [Final budget RunManifest](../../../.agent-loop/tasks/GW-REAL-PRODUCT-001/stage2-budget-final-manifest.json)
- [Owner journal](../../../.agent-loop/tasks/GW-REAL-PRODUCT-001/artifacts/runner-owner-019.json)
- [Test journal](../../../.agent-loop/tasks/GW-REAL-PRODUCT-001/artifacts/runner-verifier-020.json)
- [TestReport](../../../.agent-loop/host-artifacts/GW-REAL-PRODUCT-001/verifier-020.json)
- [External main IntegrationManifest](../../../.agent-loop/tasks/GW-REAL-PRODUCT-001/stage2-external-main-integration-manifest.json)
