# E4：固定回归与 PromotionReport 现场报告

> **日期：** 2026-09-15  
> **机器报告：** `ready_for_human_gate`  
> **正式晋级：** 未发生；未执行 E5 Proposal 应用或模型训练

## 执行范围

本轮只验证 `LL-009`：在 Product 的 Python 验证场景中，host pytest 只能作为
诊断，Docker canonical test 才是最终证据。调度保持串行，每个 case 为一个
Baseline Owner → 独立 Test Agent 链，Test Agent 不读取 Owner 对话。

固定集位于被忽略的运行目录 `.agent-loop/e4/RegressionSet.yaml`，包含 2 个
target、1 个 control、1 个 safety。四个 case 的 TestReport 均来自独立
`test-verification` 运行；Docker 报告均记录 health、退出结果和 cleanup。

## 结果

| 指标 | Baseline | Evolved |
|---|---:|---:|
| target avoidable detours | 2 | 0 |
| task success rate | 100% | 100% |
| contract / scope / privacy violations | 0 | 0 |
| negative transfer | 0 | 0 |
| false avoidance | 0 | 0 |
| advisory context tokens | 0 | 140/case |

真实 target 运行均执行了 `python3 scripts/check.py docker-test`；每个 TestReport
均为 PASS，当前两类 UI case 的结果是 198 tests passed，Docker health passed，
cleanup complete。

## 证据边界

- `E4-TARGET-002` 的 Baseline/Evolved 均在修正后的 32,000 aggregate output
  budget 下产生了完整 RunManifest；真实 input 分别为 648,700 和 918,432。
- `E4-TARGET-001` 的 TestReport、Owner/Test ExecutionRecord 和 Docker 证据均已
  保存，但它们是在旧的 128,000 task input budget 下运行；Evolved 总 input 为
  1,033,238，因此当时没有形成可通过预算校验的最终 RunManifest。这个缺口没有
  被 PromotionReport schema 自动隐藏，需在正式批准前补齐或明确拒绝该报告。
- control 使用两次独立 service-backed Docker Test（health、受控缺 Core 故障、
  ownership-scoped cleanup）；safety 使用 Pilot 018 集成前后的两次独立 Docker
  Test。它们是历史现场证据，未被伪装成新的模型运行。
- 生成器 CLI 曾丢弃 rollback 参数，已修复；修复后 rollback gate 使用 Pilot 018
  的隔离 worktree revert 证据并通过。

## Gate 结论

机器 PromotionReport 的 11 个 gate 中，除 `human_approval` 外均通过；报告状态为
`ready_for_human_gate`。但由于 T001 的 RunManifest 缺口，当前不能把它解释为
“E4 已正式完成”，也不能直接生成 approved PromotionReport。

下一步必须先补齐 T001 的同预算 Baseline/Evolved RunManifest，或由人工明确将
该 case 标记为不合格并重新冻结回归集；之后才可以人工决定是否批准 E4，批准后
再生成只读 E5 Proposal。E6 Trainer 校验和 smoke training 目前保持关闭。
