# Experience Layer Protocol

> **当前实现：E0–E1 candidate-only、E2 shadow-only**
> **当前状态：** 分析已结束任务的执行路径并保存候选经验；E2 只做旁路检索和报告，E3 注入、E4 Promotion 均未启用。

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

## 7. 后续阶段边界

E3 才允许已确认经验以 advisory 形式进入 ContextBrief；
E4 才允许与 Baseline 做固定回归并提交 Promotion Proposal。任何影响 Harness Policy 的规则
仍然需要人工 Gate。
