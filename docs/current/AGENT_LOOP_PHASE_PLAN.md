# Gwent Agent Loop 阶段实施计划

> **状态：历史阶段边界；实时状态以 `agent-loop/CURRENT_STATE.md` 为准**
> **版本：0.5**
> **配套规范：** [`AGENT_LOOP_PLAN.md`](AGENT_LOOP_PLAN.md)
> **项目导航：** [`AGENT_LOOP_NAVIGATION.md`](AGENT_LOOP_NAVIGATION.md)
> **原则：先把上下文和控制平面做成可验证的工程，再接入 Codex 子会话。**
>
> **当前实现状态：** 请先阅读 [`agent-loop/CURRENT_STATE.md`](agent-loop/CURRENT_STATE.md)；本文件保留 Phase 0–7 的阶段边界和退出条件，不重复维护实时状态。
> **三阶段路线图：** [`agent-loop/IDEAL_LOOP_3_STAGE_PLAN.md`](agent-loop/IDEAL_LOOP_3_STAGE_PLAN.md)

## 0. 这份计划解决什么问题

`AGENT_LOOP_PLAN.md` 规定不可破坏的协议；本文件规定落地顺序、阶段交付物、进入/退出条件、风险和回退方法。

目标不是尽快启动最多 Agent，而是逐步获得以下能力：

```text
项目事实可导航
  → 任务上下文可恢复
  → 状态和权限可验证
  → 测试与 Docker 证据可信
  → 子会话可按需启停
  → 跨领域任务可安全交接
```

任何阶段都不得为了展示“多 Agent”而跳过前置阶段。

## 1. 总体架构和建设顺序

```text
                    ┌──────────────────────────┐
                    │  Root/Main Agent         │
                    │  用户意图、状态、人工闸门 │
                    └────────────┬─────────────┘
                                 │
                ┌────────────────┴────────────────┐
                │                                 │
       Context / Integration              Deterministic Control Plane
       导航、ContextBrief、坑记录           状态、锁、预算、snapshot、事件
                │                                 │
                └────────────────┬────────────────┘
                                 │
              ┌──────────────────┴──────────────────┐
              │                                     │
      四个领域 Owner                         Test / Verification
 Core / Trainer / Product / Teacher          Review、Docker、测试证据
```

### 1.1 角色与启动策略

| 角色 | 定义是否长期存在 | 会话是否常驻 | 主要产物 |
|---|---:|---:|---|
| Main Agent | 是 | 根任务可长期存在 | TaskPacket、状态决策、最终汇总 |
| Core / Trainer / Product / Teacher | 是 | 否，按领域任务启动 | ChangeReport、代码和领域验证 |
| Context / Integration | 是 | 否，复杂任务按需启动 | ContextBrief、PlanReport、Handoff、Markdown |
| Test / Verification | 是 | 否，按需启动 | ReviewReport、TestReport、回归测试、Docker 证据 |
| Deterministic Scheduler | 是，作为工具/服务 | 不使用模型会话 | state、lock、budget、event |

角色定义、Skill、权限和路由可以长期保留；子会话完成后关闭，结构化工件继续保留。

### 1.2 关键依赖

```text
导航/坑记录
      ↓
AgentProfile + ContextIndex
      ↓
TaskPacket + ContextBrief + RunManifest
      ↓
状态机/锁/预算/snapshot 校验
      ↓
人工试点
      ↓
Codex Runner 适配器
      ↓
有限的跨域编排
```

## 2. 阶段总览

| 阶段 | 名称 | 目标 | 是否启动真实子 Agent |
|---|---|---|---:|
| Phase 0 | 规范与导航基线 | 统一角色、上下文、坑记录和报告协议 | 否 |
| Phase 1 | 上下文资产化 | 建立 AgentProfile、ContextIndex、RunManifest | 否 |
| Phase 2 | 确定性控制平面 | 实现状态、锁、预算、snapshot 和工件校验 | 否 |
| Phase 3 | 验证与环境平面 | 固化 Test/Verification、Docker 和测试修改边界 | 否 |
| Phase 4 | 人工闭环试点 | 用真实任务验证协议和上下文命中率 | 否，人工扮演角色 |
| Phase 5 | Codex Runner 适配 | 受控启动、等待、恢复、关闭子会话 | 是，低风险 |
| Phase 6 | 跨域编排 | 只为已验证的 contract handoff 增加自动化 | 是，受限 |
| Phase 7 | 运营与持续评估 | 观测、回退、成本和协议演进 | 是，按风险 |

阶段不能因为“代码已经能跑”就提前通过；必须满足退出条件和证据要求。

---

## 3. Phase 0：规范与导航基线

### 3.1 目标

让所有参与者知道：谁负责什么、上下文去哪里找、任务如何结束、哪些情况必须停下来问人。

### 3.2 已完成交付物

- [`AGENT_LOOP_PLAN.md`](AGENT_LOOP_PLAN.md)：基础规范、角色、状态机、预算、权限和 handoff；
- [`AGENT_LOOP_NAVIGATION.md`](AGENT_LOOP_NAVIGATION.md)：项目事实导航和路由；
- [`agent-loop/LESSONS_LEARNED.md`](agent-loop/LESSONS_LEARNED.md)：可验证的坑记录；
- [`agent-loop/CONTEXT_BRIEF_TEMPLATE.yaml`](agent-loop/CONTEXT_BRIEF_TEMPLATE.yaml)；
- TaskPacket、ChangeReport、ReviewReport、TestReport、HandoffReport 模板；
- `.agents/evals/tasks/007...018`：Agent Loop 正常流、故障流和上下文 grounding 评估案例；
- `.gitignore` 对 `.agent-loop/` 本机运行状态的忽略规则。

### 3.3 退出条件

- 四个领域 Owner 与现有 `AGENTS.md` 路由一致；
- Context / Integration 不被定义成新的 Manager Agent；
- Test / Verification 的生产代码只读、测试 scope 可写边界明确；
- 关键模板和导航链接通过机械核验；
- 维护者接受“先人工试点，后接 Runner”的顺序。

### 3.4 本阶段不做

- 不启动真实子 Agent；
- 不写后台调度器；
- 不修改 Core、Trainer、Product、Teacher 业务代码；
- 不把完整聊天历史作为项目记忆导入仓库。

---

## 4. Phase 1：上下文资产化

### 4.1 目标

把“项目上下文”从聊天记忆变成可引用、可验证、可恢复的文件资产。

### 4.2 交付物

当前已落地：`agent-loop/AGENT_PROFILE_TEMPLATE.yaml`、五个 Profile、`CONTEXT_INDEX.yaml`、`CONTEXT_INDEX_TEMPLATE.yaml`、`RUN_MANIFEST_TEMPLATE.yaml`，以及 Phase 1/2 状态记录。它们仍绑定初始 baseline 前的 working-tree snapshot，创建 Git baseline 后必须复核。

新增并冻结以下三个协议对象：

#### AgentProfile

记录一个角色的能力和边界：

```yaml
agent_id: "product"
role_type: "domain_owner"
owner_boundary: "apps/web and Core HTTP consumer"
required_skills: ["product-integration"]
read_roots: ["apps/web", "docs/current/TEACHER_AND_WEB.md"]
write_roots: ["apps/web"]
test_write_roots: ["apps/web/backend/tests", "apps/web/frontend"]
forbidden_roots: ["src/engine", "models", "runs"]
tools: ["read", "edit", "shell"]
docker:
  allowed: false
  compose_files: []
model_policy:
  model: "runner-defined"
  reasoning: "runner-defined"
prompt_revision: ""
skill_revisions: []
```

#### ContextIndex

记录项目事实之间的导航关系：

```yaml
index_version: 1
workspace_snapshot: ""
entries:
  - id: "core-action-source"
    domain: "core"
    claim: "Core actions are the legality source"
    source_refs: ["AGENTS.md", "config/rl_contract.json"]
    verified_at: ""
    verified_snapshot: ""
    status: "confirmed | inferred | superseded"
    trigger_terms: ["legal action", "option_index"]
    owner: "core"
lesson_refs: ["LL-001"]
```

#### RunManifest

记录一次任务实际发生了什么：

```yaml
run_id: "GW-YYYYMMDD-001"
task_id: ""
packet_revision: 1
runner: "manual | codex | ci"
base_snapshot: ""
final_snapshot: ""
role_runs:
  - role: "product"
    attempt_id: ""
    model: ""
    reasoning: ""
    profile_revision: ""
    input_tokens: 0
    output_tokens: 0
    status: "closed | lost | blocked"
artifacts: []
state_events: []
```

### 4.3 关键规则

- AgentProfile 是权限和能力声明，不是提示词百科；
- ContextIndex 的每条事实必须有来源、snapshot、验证时间和状态；
- RunManifest 记录真实执行，不允许由最终总结事后臆造；
- token 不可读时按请求上限记账；
- 角色配置变化必须产生新的 profile revision；
- 经验库条目必须通过人工或验证任务接受后才进入 `confirmed`。

### 4.4 退出条件

- 能为四个领域和 Test / Verification 创建合法 Profile；
- 能从关键词检索到相关 ContextIndex 和坑记录；
- 能用 RunManifest 恢复一次已关闭任务的责任链；
- 旧 snapshot 的事实不会静默覆盖新 revision；
- 有 schema 校验和至少一个过期上下文测试。

### 4.5 本阶段不做

- 不执行模型调用；
- 不自动读取整个仓库建立“全量向量记忆”；
- 不把未验证的 Agent 输出写入 confirmed 事实；
- 不引入数据库，先用可审计的文件格式。

---

## 5. Phase 2：确定性控制平面

### 5.1 目标

让没有模型参与时，系统也能拒绝非法状态、超范围写入、陈旧结果和无限循环。

### 5.2 交付物

第一版确定性控制器已落地于 `scripts/agent_loop/`：状态转换与事件幂等、任务级预算、路径/contract 锁冲突、跨进程锁文件、文件 hash snapshot 与 TaskPacket scope 绑定、Profile/ContextIndex/TaskPacket/RunManifest/Artifact 校验，以及 `.agent-loop/tasks/<task-id>/` 的本地状态和工件持久化。当前通过 21 个本地单元与负例测试，并已接入 `scripts/check.py quick`；统一 quick 已通过模型槽位和项目结构检查，但在 `training-config` 的 `validate_training.py --all` 处因当前 Python 环境缺少 `torch` 阻断。

建议新增纯确定性工具目录：

```text
scripts/agent_loop/
  validate_packet.py
  validate_artifact.py
  state_machine.py
  snapshot.py
  locks.py
  budget.py
  manifest.py
```

工具职责：

- TaskPacket / ContextBrief / AgentProfile / Report schema 校验；
- 合法状态转换和 `event_seq` 幂等；
- write scope、contract lock 和 snapshot drift 检查；
- role run、subtask depth、token、时间和失败重试预算；
- 工件内容摘要、引用完整性和脱敏检查；
- `BLOCKED`、`HUMAN_REQUIRED`、`CANCELLED`、`SUPERSEDED` 的安全转换；
- 生成可读的拒绝原因。

### 5.3 状态存储

第一版使用被 `.gitignore` 忽略的本地目录：

```text
.agent-loop/tasks/<task-id>/
  state.json
  events.ndjson
  artifacts/
  locks/
```

不使用数据库，不把控制状态放到 `runs/` 或训练 `artifacts/`。

### 5.4 退出条件

必须通过确定性测试：

- 非法状态转换被拒绝；
- 同一个事件重放不会重复写入；
- snapshot 漂移阻止完成；
- scope 重叠阻止第二个 Writer；
- 超过 token/轮次/时间预算自动熔断；
- Runner 丢失不会误标记完成；
- 报告缺字段不能进入下一阶段；
- 取消和恢复不会丢失旧工件。

### 5.5 本阶段不做

- 不自动创建 Codex 子会话；
- 不自动批准人工 gate；
- 不执行部署、模型 promotion、删除或破坏性迁移；
- 不解决所有业务测试问题。

---

## 6. Phase 3：验证与环境平面

### 6.1 目标

让 Test / Verification Agent 的测试、Docker 和测试文件修改具备可信边界。

### 6.2 交付物

当前已落地 [`agent-loop/TEST_MATRIX.yaml`](agent-loop/TEST_MATRIX.yaml)、[`agent-loop/TEST_MODIFICATION_POLICY.md`](agent-loop/TEST_MODIFICATION_POLICY.md) 和 TestMatrix 确定性校验。它们先固化测试范围、Docker allowlist、失败分类和人工 gate，尚未授权自动启动 Docker。

#### TestProfile

```yaml
agent_id: "test-verification"
role_type: "verification"
review_mode:
  read_roots: ["task scope", "ContextBrief", "contract refs"]
  write_roots: []
test_mode:
  test_write_roots: ["declared test scope"]
  production_write_roots: []
docker:
  compose_allowlist:
    - "deploy/docker/compose.cpu.yml"
  allowed_actions: ["up", "down", "ps", "health", "logs"]
  cleanup_required: true
  max_runtime_minutes: 30
```

#### 测试修改规则

- 新测试必须尽量先复现失败，再证明修复；
- 修改断言、skip、fixture 默认需要领域 Owner Review；
- 测试通过不能覆盖 contract 或 privacy finding；
- TestReport 必须绑定最终 snapshot；
- Docker 失败、依赖缺失和业务断言失败必须分类；
- 测试数据、容器、端口和临时文件必须隔离并清理。

#### 测试矩阵

建立领域到测试命令、Docker 服务和人工 gate 的映射，不让 Test Agent 自己猜测试范围。

### 6.3 退出条件

- TestProfile 能阻止生产代码写入；
- 测试修改能被列出并由领域 Owner 复核；
- Docker compose、health、logs、cleanup 有可复现流程；
- 有代码失败、环境失败、Docker 失败、权限失败和 flaky test 的评估案例；
- 至少一个测试能证明“错误实现 + 错误测试”不会被误判为 PASS。

---

## 7. Phase 4：人工闭环试点

### 7.1 目标

不接自动子会话，人工扮演 Main、Context、Owner、Verification，验证整个协议是否真的减少遗忘和返工。

当前状态：[Phase 4 状态记录](agent-loop/PHASE_4_STATUS.md)。Pilot 001 已完成协议演练，但不计入真实业务试点的退出条件：没有启动真实子会话、没有启动 Docker，也没有修改业务代码。

### 7.2 试点组合

至少选择：

1. 一个局部 Product 或 Teacher 低风险修改；
2. 一个环境阻塞或 Docker 失败案例；
3. 一个只读跨域 contract 规划案例；
4. 一个包含历史坑记录的任务；
5. 一个测试文件修改和回归验证案例。

排除：模型 promotion、生产部署、privacy 规则改写、breaking schema/action grammar 实施和不可逆数据操作。

### 7.3 观测指标

- 首次路由是否正确；
- ContextBrief 是否命中正确事实来源；
- 读取了多少无关文件；
- 是否发现并应用相关坑记录；
- Owner 一次完成率和返工次数；
- Review/Test 是否在最终 snapshot 上完成；
- token、模型轮次和重复调用；
- false PASS 数量；
- 人工 gate 和 BLOCKED 原因；
- 取消/恢复是否丢失上下文。

### 7.4 退出条件

- 3–5 个试点均能恢复任务；
- 没有用户改动丢失或未声明范围写入；
- 至少一个失败任务正确熔断；
- 至少一个历史坑被正确命中；
- 没有 false PASS；
- token 成本与返工减少之间有可解释关系；
- 参与者能看懂当前状态、下一步和需要的人工决策。

如果试点失败，回到 Phase 1/2 修协议，不直接增加 Agent 数量。

---

## 8. Phase 5：Codex Runner 适配

### 8.1 目标

只把已经验证的协议映射到 Codex 子会话，不让 Codex 的会话能力反过来定义项目规则。

### 8.2 最小 Runner 接口

```text
open(role, task_packet, context_brief, profile) -> runner_ref
send_input(runner_ref, structured_prompt) -> event
wait(runner_ref) -> event
resume(runner_ref, artifact_refs) -> runner_ref
interrupt(runner_ref) -> event
close(runner_ref) -> event
```

每次调用必须绑定：`task_id`、`revision`、`attempt_id`、`profile_revision`、`snapshot`、write scope 和剩余预算。

### 8.3 运行规则

- 简单任务只启动一个领域 Owner；
- Context / Integration 和 Test / Verification 按风险按需启动；
- 子会话不是长期记忆，关闭前必须写工件；
- Runner 丢失先 `BLOCKED`，确认工作树后才能恢复；
- 不把完整主对话转发给子会话；传 TaskPacket、ContextBrief 和必要的 source refs；
- 子 Agent 不得再递归派发 Agent；
- Runner 输出缺字段或不是结构化报告时，不能推进状态。

### 8.4 退出条件

- 可以启动、等待、打断、关闭和恢复一个低风险子任务；
- 会话关闭后能基于工件继续任务；
- Runner 崩溃不会重复写入或误标 PASS；
- 子会话数量和 token 永远受 RunManifest 约束；
- 人工可以随时停止整个 Loop。

---

## 9. Phase 6：有限跨域编排

### 9.1 目标

只自动化已经在 Phase 4/5 证明稳定的跨域 handoff，例如 Core action grammar → Trainer/Product consumer。

### 9.2 规则

- 权威 Owner 先定义 contract；
- Context / Integration 生成事实来源图和 HandoffReport；
- 每个依赖 Owner 只修改自己的边界；
- breaking change、privacy、模型 promotion 自动进入人工 gate；
- 同一 contract 不允许并行写入；
- 集成前重新生成最终 snapshot 和 IntegrationManifest；
- 任一 consumer 没有验证结论，主任务不能完成。

### 9.3 退出条件

- 跨域任务的责任和事实来源可追溯；
- contract 冲突能停在人工裁决，而不是自动猜；
- 局部成功和整体失败可以安全回退；
- 并行没有造成 token、锁或环境污染的不可解释增长。

---

## 10. Phase 7：运营、回退与持续评估

### 10.1 需要补齐的运营能力

- 结构化用户状态页或状态摘要；
- 任务运行、角色运行、token、时间和失败分类指标；
- Profile、Skill、Prompt、ContextIndex 的 revision 管理；
- lessons 的过期和 supersede 流程；
- 原始会话的保留/清理策略；
- 安全日志脱敏和访问范围；
- 一键禁用 Runner 的 kill switch；
- 失败任务重放和确定性评估。

### 10.2 回退策略

发生越权、false PASS、状态错乱、隐私风险、预算异常或 Docker 污染时：

1. 停止新的子会话；
2. 保留 RunManifest、snapshot 和现有工件；
3. 关闭 Runner 适配器；
4. 回到人工协议；
5. 修复确定性控制平面或 Skill；
6. 用评估案例复现后，才恢复自动化。

### 10.3 完成标准

Agent Loop 只有同时满足以下条件，才可以称为可用系统：

- 复杂任务能通过 ContextBrief 找到正确事实和改动边界；
- 专业 Owner 不越权；
- Test / Verification 不制造 false PASS；
- 状态、预算、snapshot 和锁可恢复；
- 子会话可按需开启、关闭和恢复；
- 跨域 handoff 可审计；
- 失败会熔断而非无限消耗；
- 用户知道系统在做什么、卡在哪里以及如何继续。

---

## 11. 近期执行顺序

下一步只做以下顺序，不提前接入 Codex 子会话：

1. 评审并确认本文与 [`AGENT_LOOP_PLAN.md`](AGENT_LOOP_PLAN.md) 没有冲突；
2. 创建 `AgentProfile`、`ContextIndex`、`RunManifest` 模板；
3. 创建确定性 schema / 状态 / snapshot / budget 校验工具；
4. 创建 TestProfile 和 Docker 测试矩阵；
5. 用人工完成 Phase 4 的首个 Context grounding 试点；
6. 复盘 token、错误路由、重复读取、测试质量和人工升级；
7. 只有试点退出条件满足后，才实现 Codex Runner。

## 12. 明确不做的事情

- 不为了“看起来像 Agent Loop”而永久打开七个对话；
- 不让 Manager Agent 无限递归派发；
- 不把完整聊天记录当项目知识库；
- 不把坑记录当作高于当前 contract 的规则；
- 不让 Test Agent 修改生产代码或降低测试标准；
- 不在没有 snapshot、权限和预算记录时启动子会话；
- 不在人工 gate 未批准时自动部署、发布、promotion 或执行破坏性操作。

## 13. Historical transition notes

This section records the 2026-09-13 transition from the initial baseline to the
Runner implementation. It is retained for auditability, but it is not a current
roadmap. For current work and remaining gaps, use
[`agent-loop/CURRENT_STATE.md`](agent-loop/CURRENT_STATE.md).

### 13.1 Completed foundation

- The logical role set is complete: Main, Core, Trainer, Product, Teacher, Context/Integration, and Test/Verification.
- The deterministic control plane is available: state, budget, locks, snapshots, persistence, packet validation, and artifact validation.
- The verification boundary is defined: TestMatrix, Docker allowlist, test modification policy, failure classes, and cleanup ownership.
- The architecture gate passes without loading the local model or requiring local torch.

### 13.2 Historical implementation sequence (superseded)

1. Completed the Phase 4 low-risk Product pilot as Pilot 002.
2. Confirmed final-snapshot validation, historical-lesson use, budget evidence, failure classification, and human gates for Pilot 002.
3. Implemented the model-free Runner lifecycle contract: open, wait, interrupt, resume, and close.
4. Implemented identity-bound execution records in `scripts/agent_loop/execution.py`, including bounded events, snapshot/write-scope checks, budget-before-open, resume limits, TaskStore packet-revision binding, and RunManifest role-run projection.
5. Implemented the validated external launch envelope in `scripts/agent_loop/launch.py` and the shared ContextBrief schema contract in `scripts/agent_loop/validate_packet.py`; they bind TaskPacket, ContextBrief, AgentProfile, scope, and nested budgets without forwarding raw conversation history.
6. Implemented the transport-only adapter boundary in `scripts/agent_loop/external.py`; malformed responses and runner reference drift are rejected before recording.
7. Implemented the Owner-to-Test/Verification handoff envelope in `scripts/agent_loop/handoff.py`; only a closed, scoped Owner report can enter independent verification.
8. Implemented `scripts/agent_loop/verification.py`; a handoff now resolves to allowlisted TestMatrix commands, Docker ownership, cleanup policy, and test-only write roots.
9. Implemented `scripts/agent_loop/report_validation.py`; TestReport cannot claim PASS without command, snapshot, failure, and Docker evidence.
10. Run one real Owner subtask followed by one independent Test/Verification subtask through an approved external transport.
11. Add bounded Docker execution only for allowlisted service tests; never use a global cleanup on a shared compose project.
12. Require two independent validation rounds before limited automatic repair.
13. Delay cross-domain orchestration, model operations, deployment, and promotion until the bounded loop is proven.

### 13.3 Historical completion gate (superseded)

The next stage is complete only when a low-risk task can be opened, paused, resumed, verified, and closed with preserved artifacts; a failure can stop at HUMAN_REQUIRED; no recursive subtask is created; no out-of-scope file is written; and the final report contains reproducible commands, snapshots, budget, and failure classification.

Do not add another Agent to compensate for a missing Runner, stale context, weak validation, or unclear ownership. Fix the control plane or the execution adapter instead.

### 13.4 Historical runner boundary (superseded)

At the 2026-09-13 baseline, the deterministic lifecycle contract was implemented
in `scripts/agent_loop/runner.py` and covered by negative tests. The execution,
launch, transport, handoff, verification, and report-validation layers were
then the boundary before a platform-specific external transport. This
transition note is superseded by [`CODEX_TRANSPORT.md`](agent-loop/CODEX_TRANSPORT.md)
and [`agent-loop/CURRENT_STATE.md`](agent-loop/CURRENT_STATE.md), which record the
later CLI bridge and bounded loop evidence.

### 13.5 Historical Pilot 002 boundary (superseded)

Pilot 002 was the first Product Owner to Test/Verification handoff. It passed
the checks available at that time but did not satisfy the real Codex child-session
requirement; that gap was later covered by Pilots 004–005.
