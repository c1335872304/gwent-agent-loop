# Experience Layer Protocol

> **当前实现：E0–E1 candidate-only、E2 shadow-only、E3 bounded advisory、E4 fixed regression**
> **当前状态：** E4 只生成可审计 PromotionReport；实际晋级仍需要 canary、rollback 和明确人工 Gate。

本协议是 [`SELF_EVOLUTION_PLAN.md`](SELF_EVOLUTION_PLAN.md) 的运行时补充。它不新增 Agent，
不改变当前串行 Scheduler，不读取原始对话，也不让经验覆盖 AGENTS、Skill、contract、
TaskPacket 或当前 snapshot。

## 1. E0–E1 的输入和输出

输入必须是结构化工件：

- RunManifest：任务身份、snapshot、角色运行和恢复记录；
- TestReport：独立测试结果、失败分类、Docker/环境证据；
- ChangeReport：Owner 的 changed paths 和验证结果；
- Execution Trace：带序号的工具/动作事件；不得包含完整 prompt 或聊天记录。

输出：

```text
PathAnalysis
  -> DetourRecord（所有失败：avoidable / necessary / unclassified）
  -> Candidate Lesson（仅 verified fallback 的 avoidable detour）
  -> ExperienceManifest（candidate_only，injection=false）
  -> E2 Shadow Retrieval（selected/excluded report，仍不注入）
  -> E3 Advisory ContextBrief（仅 confirmed/promoted，受限且可回溯）
  -> E4 PromotionReport（Baseline/Evolved 固定回归，仍不自动晋级）
```

未被明确证明可避免的失败不会自动生成 Avoidance Rule。

## 2. Trace 事件最小格式

```yaml
seq: 1
tool: git
operation: apply_with_index
target_scope: docs/current
status: FAIL
failure_class: PROTOCOL_FAILURE
error: "仅用于生成脱敏 error_signature_hash"
preflight_available: true
preconditions:
  - dirty_parent
  - cross_worktree
preflight_checks:
  - git_status_short
  - inspect_parent_index
elapsed_seconds: 1.5
input_tokens: 0
output_tokens: 0
model_turns: 0
```

成功回退必须明确指向失败动作：

```yaml
seq: 2
tool: git
operation: explicit_path_apply
status: PASS
fallback_of: 1
```

`command` 可以作为输入，但输出只保留规范化操作和 digest，不保存可能包含秘密的原始命令。

## 3. 确定性分析规则

| 情况 | 分类 | 是否生成 Candidate Lesson |
|---|---|---|
| 同一动作在前置条件未改变时重复 | `avoidable_detour` | 只有存在成功回退时才生成 |
| `preflight_available` 且有显式成功替代路径（`fallback_of` 或匹配的 `resolution_hint`） | `avoidable_detour` | 是 |
| 首次探索未知环境，明确标记 `necessary_exploration` | `necessary_exploration` | 否 |
| 失败但无法证明可避免或没有成功回退 | `unclassified_failure` | 否 |
| 前置条件改变后重新执行同一动作 | 不自动判定 | 否 |

规则只基于可见的结构化事实，不自行猜测根因。模型总结若在未来加入，必须写入
`inference`，不能覆盖 `observed_facts`。

## 4. CLI

分析一个 JSON/YAML Trace 或 JSONL Trace：

```bash
python3 scripts/agent_loop/experience.py \
  --trace .agent-loop/tasks/<task>/trace.jsonl \
  --run-manifest .agent-loop/tasks/<task>/RunManifest.yaml \
  --test-report .agent-loop/tasks/<task>/TestReport.yaml \
  --change-report .agent-loop/tasks/<task>/ChangeReport.yaml \
  --domain product \
  --task-type api_contract_change \
  --contract-version product-http=v1 \
  --output-dir .agent-loop/tasks/<task>/experience
```

输出目录只允许写入：

```text
experience/
├── ExperienceManifest.yaml
└── candidate/
    └── LESSON-<digest>.yaml
```

当前 `ExperienceManifest` 强制 `injection.enabled=false`，Candidate 不会自动进入任何新的
ContextBrief。提取失败不改变主任务状态；报告中应保留失败原因。

E2 Shadow Retrieval 使用 `SHADOW_QUERY_TEMPLATE.yaml` 和 `retrieval.py`：

```bash
python3 scripts/agent_loop/retrieval.py \
  --lesson .agent-loop/experience/candidate/LESSON-<digest>.yaml \
  --query .agent-loop/tasks/<task>/ShadowQuery.yaml \
  --output .agent-loop/tasks/<task>/ShadowRetrieval.yaml
```

有多个 Lesson 时重复传入 `--lesson`；不要让 shell 通配符展开成未绑定参数。

报告只用于观察命中和排除，不会修改当前 ContextBrief；检索异常时记录 `unavailable` 并
继续使用基线上下文。

## 5. 安全和证据要求

- 所有输入先拒绝 `conversation`、`chat_history`、`raw_transcript`、`full_transcript`、
  `prompt` 和 `messages` 字段；
- error 只保存脱敏 hash 和 failure class；
- Lesson 必须引用 Trace、RunManifest、TestReport 或 ChangeReport；
- Lesson 必须绑定 snapshot；
- `candidate` 不能被检索为正式上下文；
- 当前阶段不修改 Skill、Routing、Scheduler、contract、权限、预算或模型；
- 测试失败、Docker 失败、权限失败和预算耗尽必须保留原分类，不能改写成“弯路”以外的成功。

## 6. E2 Shadow Retrieval

E2 的输入是显式 `ShadowQuery` 和候选/已确认 Lesson 文件。只有 `confirmed` 或 `promoted`
记录可以进入匹配池；`candidate`、rejected、deprecated、过期、冲突、contract 不兼容、快照
不兼容或缺少验证日期的记录必须进入 `excluded` 并带原因。检索使用 domain、task_type、
changed paths、failure class、preconditions、contract versions 和 snapshot policy 做确定性
匹配，默认最多 selected 3 条、1500 estimated tokens。

输出为 `SHADOW_RETRIEVAL_TEMPLATE.yaml` 形状的报告，必须记录匹配字段、排除原因、输入数量、
命中率、估算 Token 和 `model_calls=0`。检索不可用时输出 `status=unavailable`，并声明
`baseline.unchanged=true`；它不能阻断当前任务，也不能改变 ContextBrief。

## 7. E3 Advisory Injection

E3 必须通过 `injection.py` 创建新的 ContextBrief 副本，不能原地修改基线。输入必须包含
有效的 ContextBrief、完整的 E2 ShadowRetrieval 报告和 selected 对应的 Lesson 文件。只有
`confirmed` 或 `promoted` Lesson 可以生成 advisory item；每项必须保留 statement、when、
avoid、prefer、preflight、evidence snapshot 和 source refs。默认上限为 3 项、1500 estimated
tokens，超出的 selected 进入 `advisory.omitted` 并记录原因。

advisory 只能位于独立的 `ContextBrief.advisory` 区域，不能写入 `context_floor_refs`、事实
来源、权限、预算、并发或停止条件。初次生成时 adoption 为 `not_recorded`；任务结束后使用
`record_advisory_adoption` 绑定采用/未采用结果和证据引用。

显式执行注入：

```bash
python3 scripts/agent_loop/injection.py \
  --context-brief .agent-loop/tasks/<task>/ContextBrief.yaml \
  --shadow-report .agent-loop/tasks/<task>/ShadowRetrieval.yaml \
  --lesson .agent-loop/experience/confirmed/LESSON-<id>.yaml \
  --source-report-ref .agent-loop/tasks/<task>/ShadowRetrieval.yaml \
  --output .agent-loop/tasks/<task>/ContextBrief.advisory.yaml
```

多个 Lesson 时重复传入 `--lesson`。生成的新文件应作为后续 Owner 的显式 ContextBrief 输入，
不会自动替换原始 ContextBrief。

## 8. E4 Fixed Regression and PromotionReport

E4 的输入必须是 `REGRESSION_SET_TEMPLATE.yaml` 形状的冻结回归集。每个 case 都要有
独立的 Baseline 和 Evolved Test/Verification 证据，且两份 `report_ref` 不得相同。固定
回归集至少包含两个 `target`、一个 `control` 和一个 `safety` case；Baseline advisory
必须关闭，`prohibited` case 在 Evolved 中也必须关闭。

每个结果只记录结构化指标：任务是否成功、avoidable detours、额外工具调用/模型回合、
Context tokens、恢复耗时、contract/scope/privacy 违规、false avoidance、negative
transfer 和人工介入次数。原始对话、完整 prompt 和未脱敏日志不得进入回归集。

显式生成 PromotionReport：

```bash
python3 scripts/agent_loop/regression.py \
  --regression-set .agent-loop/e4/RegressionSet.yaml \
  --output .agent-loop/e4/PromotionReport.yaml \
  --canary-status passed \
  --canary-runner test-verification \
  --canary-snapshot git:<canary-snapshot> \
  --canary-evidence .agent-loop/e4/canary.log \
  --rollback-status ready \
  --rollback-method <explicit-reversible-method> \
  --rollback-evidence .agent-loop/e4/rollback-plan.md
```

闸门必须同时检查：已冻结回归集、独立证据、目标弯路减少、任务成功率不下降、安全指标
不回归、negative transfer 为零、false avoidance 为零、advisory 范围正确、canary 通过
和 rollback 就绪。即使这些闸门全部通过，报告也只能是 `ready_for_human_gate`；只有显式
记录 `decision.status=approved`、决定人和证据引用，才可标记 `approved`。`rejected` 和
`rolled_back` 必须保留原报告及相应证据。E4 不修改 Skill、Routing、Scheduler、contract、
生产代码或模型。

## 9. 后续阶段边界

E5 才允许形成 Skill、Routing 或 Validation Proposal。任何影响 Harness Policy 的规则仍然
需要人工 Gate；E6 模型训练仍然不是当前范围。
