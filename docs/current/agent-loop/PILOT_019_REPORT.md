# Pilot 019：主控调度器控制入口现场报告

> **状态：** PASS
> **任务：** `GW-SCHED-CTRL-001` revision 1
> **日期：** 2026-09-22

## 结论

真实 WSL 控制服务和主控 MCP 入口已完成低风险串行闭环：

```text
主控 MCP submit
  -> Product Owner
  -> pause（等待 turn.started 后）
  -> 新主控 inspect
  -> ResumeDirective
  -> 同一 runner_ref resume
  -> Owner final snapshot
  -> 独立 Test Agent
  -> TestReport PASS + RunManifest completed
```

控制工具只注册在用户级主控配置；Owner/Test 子进程使用
`codex exec --ignore-user-config`，不会获得暂停、恢复或取消权限。

## 证据摘要

| 项目 | 结果 |
|---|---|
| base snapshot | `026bc04854a4ad88937dcd7556dd5fe5d4619929` |
| Owner runner | `codex:local:01a0c971-8a90-7d72-8393-386978d32ef8` |
| Owner resume | 1 次，同一 runner_ref |
| Owner final snapshot | `e10de462f475a8fd14b15875d4c26d86bba3a46e` |
| Owner changed paths | 仅 `apps/web/frontend/index.html` |
| Test 起点 / final snapshot | `e10de462f475a8fd14b15875d4c26d86bba3a46e` |
| Test 结果 | `overall: PASS`，零 Test 写入 |
| Docker | 未声明服务依赖，未启动 |
| 总预算 | input 621,296；output 11,269；3 turns；177.4 秒；无超限 |

原始控制事件、ResumeDirective、两个报告和 RunManifest 保存在本机忽略目录：
`.agent-loop/control-canary/GW-SCHED-CTRL-001-20260922T140735Z/`。

## 现场发现与修复

首次 pause 若仅等待 `thread.started`，CLI 会拒绝恢复（`no rollout found`）。
桥接器现将 `turn.started` 作为唯一可恢复检查点，未达到该点时 fail-closed。
此外，只读 Test 的空 changed-path 允许关档；若它产生文件改动，仍必须声明具体
test write root，否则关闭失败。两项均有确定性回归，见 LL-017 和
`scripts/agent_loop/test_codex_cli_bridge.py`。

本次 Test 已完成后遇到 Git 嵌套 worktree 清理返回非零的边缘路径。稳定 TestReport
已复制且 worktree 已移除，恢复收口只补写终态 journal，不重复调用模型；桥接器现在
会把“目录已删除但 Git 返回 stale metadata”视为已清理并 prune 元数据。
