# Pilot 011：真实 Host 多角色现场报告

> **状态：HUMAN_REQUIRED（2026-09-14）**

本次现场从 candidate commit
`53fabec954b549f1cdce46720c3461470230ed6e` 启动，按串行路线执行真实
Product → Teacher。完整运行文件位于
`.agent-loop/live-runs/GW-STAGE3-LIVE-011/`；其中
`PILOT_011_RUN_MANIFEST.json` 已通过结构校验，状态为 `human_required`。

## 结果

| 环节 | 结果 | 证据 |
|---|---|---|
| Product create | 通过 | `runner_ref=codex:local:01a0a047-af5b-7b32-b34f-bcab61ba3f74` |
| Scheduler 独立进程重启/rebind | 通过 | 原 `runner_ref` 被重新绑定，没有第二次 create/start |
| Product scope/commit | 通过 | `apps/web/frontend/src/components/TeacherPanel.tsx`；final snapshot `e1d7d6793ca1f651eedf5e2e34828a4e885c5d5` |
| Product → Teacher contract handoff | 通过 | `product-teacher-handoff.json`；`teacher-turn-response-v1` |
| Teacher consumer review | 阻断 | 发现 `PRIVACY-001`：高级预览响应仍将 `prompt` 序列化进浏览器响应 |
| Independent Test | 未启动 | 上游 Teacher privacy/budget gate 未通过，按协议停止 |
| Docker | 未运行 | 本任务未声明 service-backed 依赖 |

## 预算与环境

Product 实际使用 `236,351` input / `5,071` output；Teacher 实际使用
`512,884` input / `10,581` output。Teacher 超出其 64k TaskPacket input
上限，Scheduler 转为 `HUMAN_REQUIRED`；这不是自动重试条件。Product 自测
报告还记录了宿主缺少 `pytest`，以及 Node/WSL 1 不可用，因此没有伪造
backend test 或 frontend build PASS。

## 结论与下一步

真实 Host create、隔离执行、Scheduler restart/rebind、Product close 和
跨域 handoff 已被现场证明；完整 Product → Teacher → Test PASS 尚未证明。
下一次运行必须先新建 revision，修复浏览器响应的 prompt privacy filter，
再重新执行独立 Test。不得把本次 Product commit 直接合入主线，也不得复用
本次已消耗的 role run。
