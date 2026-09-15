# Self-Evolution 方案讨论归档

> **性质：历史设计讨论，不是当前执行协议。**
> **整理日期：2026-09-15**
> 当前可执行版本见 [`../SELF_EVOLUTION_PLAN.md`](../SELF_EVOLUTION_PLAN.md)。新 Agent 默认不读取本文件。

## 1. 讨论来源与结论

本归档综合了外部 `SELF_EVOLUTION_PLAN.md` 和后续讨论。原始方案的方向是：从任务执行、
失败和验证结果中提取经验，用于改善 Context、Skill、Routing、Validation 和 Recovery，
而不是直接修改模型权重。

讨论后的核心修正是：普通 Lesson 不够，必须把“执行路径是否走了弯路”作为一等分析对象。
系统不仅要知道最终怎么成功，还要知道：

- 哪个工具在什么条件下失败；
- 失败是否可以提前避免；
- 是否重复执行了相同的无效动作；
- 最终使用了什么替代路径；
- 下次在什么相同条件下应直接采用替代路径。

## 2. 关键设计决策

### 2.1 不做自由自修改

Self-Evolution 不应让 Agent 直接修改 Scheduler、权限、Skill、contract、验证标准或模型。
Experience Layer 应作为现有串行控制面的受限挂钩，不新增 Manager Agent。

### 2.2 经验和权威事实分离

当前代码、contract、Skill、AGENTS 和 ContextIndex 永远高于经验。经验只能作为 advisory，
不能覆盖当前事实，也不能进入权威 `context_floor_refs`。

### 2.3 观察和推断分离

Agent 可能会错误判断根因。因此经验必须拆成：

```text
observed_facts
inference
recommendation
evidence
```

模型可以提出 inference，但不能把推断直接写成已确认事实。

### 2.4 工具失败必须条件化

不允许把一次失败归纳成“永远不要使用某工具”。规则必须绑定触发条件。例如：

```text
错误：git apply 失败，以后不使用 git apply。

正确：外部脏 worktree、存在无关用户改动、跨 worktree 集成时，
不要使用 broad cherry-pick 或 git apply --index；优先显式路径 patch、
逐路径 stage 和 git commit --only。
```

这是本项目实际遇到的典型弯路：第一次使用 `git apply --index` 失败，后来使用不带
`--index` 的显式路径补丁，再单独 stage/commit，最终成功且没有触碰无关 ZIP 删除项。

### 2.5 失败不能阻断基线 Loop

Experience 检索或提取失败时，基线任务仍应能够继续或按原有规则停止。经验层不能成为
主 Loop 的单点故障。

## 3. 经验分级讨论

```text
Candidate
  -> Confirmed Advisory
  -> Skill / Routing / Validation Proposal
  -> Promoted Rule
```

- Candidate：只保存，不影响行为；
- Confirmed：经证据和 Gate 后作为有限建议；
- Proposal：生成 diff，不直接改正式文件；
- Promoted：固定回归和人工批准后才进入正式规则；
- Harness Policy：影响调度、权限、并发、Docker、停止条件和合并时，必须人工批准。

Rejected 和 Deprecated 记录不能被普通检索选中，但不应直接删除，以便追踪错误经验和版本失效。

## 4. 讨论中的主要风险

### 4.1 上下文污染

直接把历史聊天、Trace 或所有 Lesson 塞进新 Context 会重复制造上下文污染。正确方式是：

```text
显式任务字段过滤
  -> snapshot / contract 兼容性过滤
  -> 证据强度排序
  -> 小数量、有限 Token 注入
```

默认不使用向量检索；显式 domain、task type、changed paths、contract 和 failure signature
更可解释，也更适合当前仓库的审计要求。

### 4.2 根因幻觉

“最后成功”不等于自动知道根因。必须保存失败 Trace、成功 Trace、测试结果和 snapshot，
并允许根因保持 `inferred` 或 `unknown`。

### 4.3 过度规避

如果规则没有 `when` 条件，Agent 可能在不相关任务中错误避开正确路径。所有 avoidance rule
都应包含 `avoid`、`prefer` 和 `preflight`，并通过 false avoidance 回归。

### 4.4 评估自欺

进化后的 Harness 不能修改自己的评估集、降低断言或用更多人工干预制造成功。Promotion 必须
对固定 Baseline/Evolved 任务集比较成功率、弯路率、负迁移、安全和回滚。

## 5. 建议的落地顺序

```text
E0  Schema / evidence / version / privacy
E1  Candidate-only PathAnalysis
E2  Shadow Retrieval
E3  Advisory Injection
E4  Regression + Promotion
E5  Skill / Routing / Validation Proposal
E6  可选模型训练
```

其中 E1 比普通的语义经验检索更重要。没有 PathAnalysis，系统无法区分“合理探索”和“可避免弯路”，
也无法证明下一次确实少走了一步。

## 6. 不纳入当前 MVP 的内容

- 不把完整对话历史作为长期记忆；
- 不直接自动改正式 Skill；
- 不自动修改 Scheduler 安全规则；
- 不自动扩大权限、并发、Docker allowlist 或预算；
- 不启动并行 Agent；
- 不修改或重训模型；
- 不通过新增 Manager Agent 解决经验管理问题。

本归档只保存设计推理和取舍。真正实施时，以当前 [`SELF_EVOLUTION_PLAN.md`](../SELF_EVOLUTION_PLAN.md)、
`AGENTS.md`、`CONTEXT_INDEX.yaml`、TaskPacket、ContextBrief 和 TestMatrix 为准。
