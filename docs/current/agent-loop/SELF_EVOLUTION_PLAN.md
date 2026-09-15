# Agent Loop 自进化阶段计划

> **状态：E0–E4 已验证；E5 只读 ProposalBundle 和 E6 training-readiness 代码已实现，
> 但 E5 当前因独立 Lesson 数量不足而阻塞；训练尚未启用**
> **最后整理：2026-09-16**
> **读取范围：仅自进化任务默认读取；当前状态以 [`CURRENT_STATE.md`](CURRENT_STATE.md) 为准；
> 历史讨论见 [`archive/SELF_EVOLUTION_DISCUSSION_20260915.md`](archive/SELF_EVOLUTION_DISCUSSION_20260915.md)**

## 1. 目标与边界

Self-Evolution 的目标不是让 Agent 自由修改自己，也不是立即训练新的模型，而是让
Agent 从已完成任务的**执行路径、失败、回退和验证结果**中提取可验证经验，并在相同
前置条件下提前避开已经证明可以避免的弯路。

当前 Loop 的串行控制边界保持不变：

```text
TaskPacket
  -> ContextBrief
  -> 一个 Owner
  -> 独立 Test / Verification
  -> RunManifest / TestReport
  -> PathAnalysis
  -> Candidate Experience
```

Experience Layer 只挂在任务开始前和任务结束后，不新增 Manager Agent，不改变
Scheduler 的并发模型，不自动扩大权限，不自动修改生产代码、Skill、Routing、contract
或模型。

### 1.1 与三阶段 Loop 路线的关系

[`IDEAL_LOOP_3_STAGE_PLAN.md`](IDEAL_LOOP_3_STAGE_PLAN.md) 定义的是任务执行控制面：创建、
恢复、验证、集成和关闭；本文件的 `E0–E6` 定义的是任务完成后的经验治理面。两套路线
正交，不代表新增“阶段四”，也不能用 Self-Evolution 的 Proposal 绕过现有阶段退出条件。
当前阶段三的串行、预算、权限、Docker、snapshot 和人工 Gate 仍然优先。

## 2. 第一优先级：弯路分析

普通 Lesson 记录“应该注意什么”；Detour 记录“这次执行哪里绕远了，以及下次怎么避开”。
Detour 是本计划的核心对象。

### 2.1 什么算弯路

只有满足以下条件之一，才标记为 `avoidable_detour`：

- 在当时已经可见的上下文中，本可以通过前置检查避免；
- 同一个失败动作在条件未改变时重复执行；
- 使用了错误的环境、错误的文件范围或错误的 contract 入口；
- 已有成功替代路径，却没有在相同条件下优先使用；
- 最终解决方案明确证明了前一次动作是无效尝试。

第一次探索未知环境、首次发现新 contract 问题或必要的权限确认，不自动算作弯路，
但仍可记录为 `necessary_exploration`。

### 2.2 必须记录的路径事实

每次任务结束后生成 `PathAnalysis`，至少包含：

```yaml
path_analysis:
  planned_steps: 0
  actual_steps: 0
  failed_actions: 0
  repeated_actions: 0
  avoidable_detours: 0
  necessary_explorations: 0
  successful_fallbacks: 0
  extra_tool_calls: 0
  extra_model_turns: 0
  extra_elapsed_seconds: 0
```

每个 Detour 必须关联：

- 触发条件；
- 失败工具和规范化后的操作类型；
- 错误分类和错误签名；
- 失败前可见的事实；
- 最终成功的替代路径；
- 是否重复、是否可避免；
- 消耗的时间、工具调用和模型回合；
- 失败 Trace、成功 Trace、TestReport 和最终 snapshot。

### 2.3 工具失败不能被泛化成永久禁用

错误的经验是：

```text
git apply 失败，所以以后不要用 git apply。
```

正确的经验是：

```text
外部脏 worktree + 跨 worktree 集成时，git apply --index 可能因 index/worktree
身份不一致失败；相同条件下优先使用不带 --index 的显式路径补丁，再逐路径 stage
并使用 git commit --only。
```

所有 Avoidance Rule 都必须绑定 `when` 条件。没有触发条件的“永远不要”规则不得晋级。

## 3. 经验对象与状态机

### 3.1 Lesson 与 Detour 的关系

```text
Execution Trace
  -> PathAnalysis
  -> DetourRecord
  -> Candidate Lesson / Candidate Avoidance Rule
```

Lesson 可以总结一个稳定事实；Detour 专门描述一次低效执行路径。一个 Lesson 可以
引用多个 Detour，但不能反过来把一整段 Trace 直接塞进上下文。

### 3.2 最小 Detour Schema

```yaml
schema_version: 1
detour_id: DETOUR-0001
task_id: GW-...
phase: integration

trigger:
  domain: project
  task_type: path_scoped_integration
  environment: cross_worktree
  preconditions:
    - dirty_parent
    - unrelated_user_changes

failed_action:
  tool: git
  operation: apply_with_index
  error_class: WORKTREE_INDEX_MISMATCH
  error_signature_hash: sha256:...

classification: avoidable_detour
impact:
  extra_attempts: 1
  elapsed_seconds: 16
  model_turns: 0

resolution:
  operation: explicit_path_apply_then_commit_only
  why: verified_successful_fallback

avoidance:
  avoid:
    - broad_cherry_pick
    - git_apply_index_under_trigger
  prefer:
    - explicit_path_patch
    - staged_path_verification
    - commit_only
  preflight:
    - git_status_short
    - git_diff_cached_name_status

evidence:
  failed_trace: .agent-loop/.../trace.jsonl
  successful_trace: .agent-loop/.../trace.jsonl
  run_manifest: .agent-loop/.../RunManifest.yaml
  test_report: .agent-loop/.../TestReport.yaml
  snapshot: git:...

privacy:
  redacted: true
  contains_secrets: false

status: candidate
confidence: high
```

错误原文应脱敏并尽量保存签名，不保存 token、cookie、完整 prompt、隐藏信息或无关
用户路径。

### 3.3 状态流转

```text
candidate
  ├── confirmed       可作为有限 advisory 检索
  ├── rejected        不得检索
  └── deprecated      保留记录但不得默认检索

confirmed
  └── promoted        通过回归后才能成为 Skill / Routing / Validation Proposal
```

`candidate` 不影响 Agent 行为。`confirmed` 也只能作为非权威建议。影响 Scheduler、
权限、并发、Docker allowlist、停止条件或合并策略的规则必须经过人工 Gate。

## 4. 任务生命周期中的两个接入点

### 4.1 任务开始前：受限 Avoidance Retrieval

在加载当前权威上下文之后检索，不能在读取 contract 之前先读经验：

```text
AGENTS
  -> CONTEXT_INDEX
  -> START_HERE
  -> CURRENT_STATE
  -> Domain Card / Skill / Contract
  -> Avoidance Retrieval
  -> ContextBrief
```

检索硬过滤顺序：

1. `status` 必须允许当前用途；
2. domain、task_type 和 changed paths 匹配；
3. contract version、snapshot 和环境条件兼容；
4. 没有未解决的 contradicts 或过期标记；
5. 再按证据强度、最近验证时间和路径重叠度排序。

默认最多注入 3 条，建议上限 1500 tokens。经验应放在 ContextBrief 的 advisory 区域，
不能进入权威 `context_floor_refs`，不能改变 allowed paths、权限、并发、预算和停止条件。

检索失败时，继续使用基线 ContextBrief，并记录 `experience_retrieval: unavailable`；
经验层不能成为主 Loop 的单点故障。

### 4.2 任务结束后：PathAnalysis

RunManifest 关闭后才分析执行路径：

```text
RunManifest closed
  -> normalize Trace
  -> compare planned vs actual path
  -> classify failure / retry / fallback
  -> generate PathAnalysis
  -> generate Candidate Detour
```

确定性代码先提取工具、退出码、失败分类、重试和耗时；模型只能补充摘要、推断和
建议，并且必须标记 `inference`，不能把模型推测直接写成根因事实。

## 5. Promotion Gate

### Candidate → Confirmed

- 有完整 RunManifest、TestReport 或等价证据；
- 有可复现 snapshot 和 contract 版本；
- 失败与解决路径均可定位；
- 触发条件明确，不是无条件禁用工具；
- 已完成隐私过滤；
- 通过规则检查或人工审阅。

### Confirmed → Proposal

- 相似触发条件在至少两个独立任务中出现；
- 解决路径在独立任务中重复成功；
- 没有 contract、privacy、scope 或验证标准回归；
- 规则可以表达成简短的 preflight/checklist/diff。

### Proposal → Promoted Rule

- 在不可修改的固定回归集上与 Baseline 对比；
- 成功率不下降；
- contract violation、wrong-file-scope、privacy violation 和 false PASS 不增加；
- negative transfer 为零；
- 生成 PromotionReport；
- 人工批准并保留 rollback 路径。

## 6. 分阶段实施计划

### E0：协议和证据基础

目标：定义格式，不改变 Agent 行为。

交付：

- `PathAnalysis`、`DetourRecord`、`Lesson` schema；
- evidence、snapshot、contract version 和 privacy 字段；
- Candidate/Confirmed/Rejected/Deprecated 状态校验；
- 与 TaskPacket、ContextBrief、RunManifest、TestReport 的引用关系；
- `ExperienceManifest` 模板。

退出条件：缺少证据、snapshot、版本或隐私结论的记录无法通过校验。

### E1：Candidate-only 路径分析

目标：从真实任务报告中识别弯路，但不影响后续任务。

交付：

- Trace 标准化器；
- 失败、重复、错误环境、错误范围和成功回退识别；
- `PathAnalysis` 和 Candidate Detour 生成器；
- 已知失败动作与最终替代路径的对照报告。

退出条件：提取失败不影响主任务；所有候选经验可追溯到报告和 snapshot。

### E2：Shadow Retrieval

目标：验证“下一次会避开什么”，但暂时不注入给 Agent。

交付：

- 基于显式字段的检索器；
- selected/excluded 及原因记录；
- 过期、冲突、版本不兼容和错误状态过滤；
- 检索成本和候选命中率统计。

退出条件：检索结果可解释；检索不可用时基线任务仍正常运行。

### E3：Advisory Injection

目标：把已确认的 Avoidance Rule 以有限行动提醒注入 ContextBrief。

交付：

- advisory 专用 ContextBrief 区域；
- 数量和 Token 上限；
- 工具前 preflight 提醒；
- 记录经验是否被实际采用。

退出条件：经验不能覆盖当前 contract，也不能改变权限、预算、并发和停止条件。

### E4：固定回归与 Promotion

目标：证明经验真的减少弯路，而不是制造新的错误。

交付：

- Baseline/Evolved 双轨回归；
- PromotionReport；
- canary、批准、拒绝和 rollback；
- negative transfer 和 false avoidance 检查。

退出条件：没有安全回归，且已验证的已知弯路重复率下降。

### E5：Skill / Routing / Validation Proposal

目标：把重复的路径经验转成正式 Proposal。

交付：

- Skill diff Proposal；
- Routing Proposal；
- Validation Plan Proposal；
- 只读提案和人工合并流程。

退出条件：任何正式规则都能定位到多个独立 Detour 和固定回归证据。

### E6：可选模型训练

只有 Context、Experience、Skill、Routing 和评估长期稳定后，才考虑 SFT、偏好优化或
RL。模型训练不属于 MVP，也不能替代可审计的上下文治理。

## 7. 效率与安全指标

每轮至少记录：

```text
Avoidable Detour Count
Repeated Failed Action Count
Known-Rule Violation Count
Successful Fallback Rate
Time to Recovery
Extra Tool Calls
Extra Model Turns
Context Tokens
Task Success Rate
Contract Violation Rate
Wrong File Scope Rate
Privacy Violation Rate
Negative Transfer Rate
False Avoidance Rate
Human Intervention Rate
Rollback Success Rate
```

目标不是把所有失败都变成零，而是：

> 在相同前置条件下，不重复已经被证据证明可以避免的失败；在不同条件下，不误用旧规则。

## 8. E0–E6 实施边界与下一步

E0–E1 已实现为 `scripts/agent_loop/experience.py`：它只接收结构化 Trace 和可选的
RunManifest/TestReport/ChangeReport，生成 PathAnalysis、DetourRecord、Candidate Lesson
和 candidate-only ExperienceManifest。E2 已实现为 `scripts/agent_loop/retrieval.py`：它只对
显式字段做 Shadow Retrieval，记录 selected/excluded、排除原因和成本。当前实现不读取原始
对话、不调用模型，也不修改 Skill、Routing、Scheduler、contract、生产代码或模型。E3 已实现
为 `scripts/agent_loop/injection.py`：只把 E2 selected 的 confirmed/promoted 记录放入
ContextBrief 的独立 advisory 区域，并记录后续是否采用；`context_floor_refs` 和其他任务
控制字段保持不变。E4 已实现为 `scripts/agent_loop/regression.py`：它只接受冻结的
Baseline/Evolved 固定回归集，要求独立 Test/Verification 证据，统计弯路、成功率、安全
回归、negative transfer 和 false avoidance，并生成 PromotionReport。它不会自动修改
Skill、Routing、Scheduler、contract、生产代码或模型。

## 9. E5 Skill / Routing / Validation Proposal

E0–E4 的确定性分析、旁路检索、受限 advisory 和固定回归闸门已经完成。E5 已实现为
`scripts/agent_loop/proposal.py`，只接受 approved PromotionReport 与至少两个独立
Detour 来源，生成只读 ProposalBundle，不直接修改正式文件。

E6 已实现为 `scripts/agent_loop/training_readiness.py`：它只验证训练是否具备交给 Trainer
审查的前置条件，不读取 checkpoint、不启动训练、不安装模型，也不打开模型写入或 promotion。
缺少 E4 approved 回归、E5 正式规则批准、稳定性、contract、Trainer 校验或完整评估时，
状态保持 `blocked`。

> 基于多个独立 Detour 和已通过的 PromotionReport 生成只读 Skill/Routing/Validation
> Proposal；不得自动合并正式规则。

必须交付：

- 至少两个独立 Detour 证据和对应的 approved PromotionReport；
- Skill diff、Routing diff、Validation Plan 三份只读 Proposal；
- 每项 Proposal 的来源、触发条件、反例和回归引用；
- 人工批准、拒绝和回滚路径；
- 不新增 Agent、不引入并行、不改变当前串行安全边界。

E4 的 `approved` 只表示人工 Gate 已明确记录；没有固定回归、canary、rollback 或人工决定
时，PromotionReport 必须保持 `not_ready` 或 `ready_for_human_gate`，不能被解释为已晋级。

E6 的 `ready_for_trainer_review` 也不表示已经开始训练或完成模型 Promotion；真实训练必须
由单独的 Trainer Task 按 `training-config` Skill 执行，并另行经过人工 model gate。
