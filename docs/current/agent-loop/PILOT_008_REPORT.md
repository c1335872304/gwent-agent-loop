# Pilot 008：Product service-backed Docker health/failure/cleanup

> 记录属性：历史现场证据；当前状态以 [`CURRENT_STATE.md`](CURRENT_STATE.md) 为准。

> 日期：2026-09-14
> 状态：PASS；服务健康、受控故障分类和 ownership-scoped cleanup 均有现场证据

## 任务包

本次使用独立的 service TaskPacket：
`GW-REAL-PRODUCT-001-SERVICE`，被测 snapshot 为
`227d71ed978aca33e37ee1ddee270fec11391fa8`。TaskPacket 明确声明：

- Product Compose 文件：`deploy/docker/compose.cpu.yml`；
- allowlist：`config`、`up`、`down`、`ps`、`health`、`logs`；
- 只使用隔离 Compose project，不使用共享 `gwent-local`；
- 不修改生产代码、contract 或测试；
- 必须记录 health、logs、故障分类和 cleanup。

## 执行结果

由 [run_service_pilot.py](../../../scripts/agent_loop/run_service_pilot.py) 自动
执行，project 为 `agent-loop-gw-real-product-001-service-v3`，Web 使用
`18081` 端口避免共享端口冲突；ownership guard 收紧后重新执行，证据 attempt
为 `service-verifier-022`。

健康阶段：

- `core`、`bff`、`web` 均达到 `healthy`；
- `/api/health` 返回 HTTP 200，`ok=true`、Core `schema_version=13`、`device=cpu`；
- Product shell 返回 `theme-color=#0f172a`；
- `/api/game/new` 返回 HTTP 200、有效 `match_id` 和 11 个 actions；
- Compose 状态和服务日志已采集。

故障阶段：

- 先对同一隔离 project 做 scoped `down`；
- 仅启动 BFF，不启动 Core；
- BFF healthcheck 最终为 `unhealthy`，`FailingStreak=6`；
- failure class 为 `DOCKER_FAILURE`，没有重试模型或修改 Product 代码；
- Compose 依赖阻止 Web 进入运行状态，日志保留了连接 Core 超时证据。

Cleanup 阶段：

- `docker compose ... down --remove-orphans` 返回 0；
- project 名下剩余 containers：空；
- project 名下剩余 networks：空；
- 未执行共享项目的 global `down`。

## TestReport

以下是执行主机上的历史运行时证据路径。`.agent-loop/` 被 Git 忽略，干净
snapshot 不携带这些文件，因此这里保留可审计路径文本而不创建失效链接：

- `.agent-loop/host-artifacts/GW-REAL-PRODUCT-001/service-verifier-022/TestReport.json`
- `.agent-loop/host-artifacts/GW-REAL-PRODUCT-001/service-verifier-022/service-pilot-evidence.json`
- `.agent-loop/runtime/GW-REAL-PRODUCT-001-SERVICE/task-packet.yaml`
- `.agent-loop/runtime/GW-REAL-PRODUCT-001-SERVICE/context-brief.yaml`

TestReport schema validation 为 `PASS`，changed test paths 为空。此次证据解决了
阶段二此前缺少的 service-backed Docker health/failure/cleanup 项。
