# Agent Onboarding Index

> 目标：让一个没有聊天历史的新 Agent 在十分钟内找到正确 Owner、最小事实集、
> 修改边界和验证命令。它是**索引**，不是第二份协议或项目百科；实时结论始终以
> [`agent-loop/CURRENT_STATE.md`](agent-loop/CURRENT_STATE.md) 和最终 snapshot 为准。

## 0. 文档职责（单向引用）

| 文档 | 唯一职责 | 不负责什么 |
|---|---|---|
| 本页 | 首次读取顺序、责任域路由、事实来源和验证等级 | 不重复 Loop 生命周期细节 |
| [`agent-loop/START_HERE.md`](agent-loop/START_HERE.md) | 串行 Loop 的执行、停止和交付协议 | 不重新定义路由或首次读取顺序 |
| [`AGENT_LOOP_NAVIGATION.md`](AGENT_LOOP_NAVIGATION.md) | Context / handoff / Lessons 的维护附录 | 不作为默认入口，不重复领域路由 |
| [`agent-loop/CONTEXT_INDEX.yaml`](agent-loop/CONTEXT_INDEX.yaml) | 机器可检查的入口卡、权威顺序、排除项和停止条件 | 不承载聊天摘要或单次任务结论 |
| 领域任务卡 → Skill → contract | 领域事实、invariant 和最小验证 | 不由导航文档复制业务规则 |

如果多个文档同时描述同一事实，保留上表中职责更靠前的来源；其他文档只保留链接和用途说明。

## 1. 先选入口，不要全仓库扫描

| 你现在要做什么 | 第一入口 | 然后读取 |
|---|---|---|
| 任何研发或 Agent Loop 任务 | [`../../AGENTS.md`](../../AGENTS.md) | 本页 → [`agent-loop/START_HERE.md`](agent-loop/START_HERE.md) → 当前状态 |
| 只想确认目前具备什么能力 | [`agent-loop/CURRENT_STATE.md`](agent-loop/CURRENT_STATE.md) | [`agent-loop/IDEAL_LOOP_3_STAGE_PLAN.md`](agent-loop/IDEAL_LOOP_3_STAGE_PLAN.md) |
| 启动或恢复一次受限串行 Loop | [`agent-loop/START_HERE.md`](agent-loop/START_HERE.md) | [`agent-loop/CODEX_TRANSPORT.md`](agent-loop/CODEX_TRANSPORT.md) → TaskPacket/ContextBrief |
| 查项目运行时架构或稳定事实 | [`PROJECT_BASELINE.md`](PROJECT_BASELINE.md) | [`ARCHITECTURE.md`](ARCHITECTURE.md) → 对应 contract |
| 寻找尚未在本页列出的当前文档 | [`../README.md`](../README.md) | 当前事实来源 / 日常操作 / 历史归档 |
| 本地启动、Docker 或手工验收 | [`LOCAL_DOCKER.md`](LOCAL_DOCKER.md) | [`DEVELOPMENT.md`](DEVELOPMENT.md) → [`PROJECT_TEST_PLAN.md`](PROJECT_TEST_PLAN.md) |
| 已确定的 Core / Trainer / Product / Teacher 实施任务 | [`agent-entry/README.md`](agent-entry/README.md) | 只打开对应领域卡 → Skill → 该卡列出的 contract 与最近回归 |
| 脏工作树、分支、隔离集成或 rollback | [`GIT_MANAGEMENT.md`](GIT_MANAGEMENT.md) | 当前 TaskPacket/snapshot → [`agent-loop/START_HERE.md`](agent-loop/START_HERE.md) |
| 复核旧决策、Pilot 或实施过程 | [`archive/README.md`](archive/README.md) | [`agent-loop/archive/README.md`](agent-loop/archive/README.md)；只按需读取 |
| 自进化、弯路分析、经验检索或 Promotion | [`agent-loop/SELF_EVOLUTION_PLAN.md`](agent-loop/SELF_EVOLUTION_PLAN.md) | `RunManifest`、`TestReport`、`PathAnalysis` 和按需读取讨论归档 |

### 最小读取顺序

1. 用户目标、权限、允许写入路径和外部影响边界；
2. [`../../AGENTS.md`](../../AGENTS.md)；
3. [`agent-loop/CONTEXT_INDEX.yaml`](agent-loop/CONTEXT_INDEX.yaml) 的 `context_policy`；
4. [`agent-loop/START_HERE.md`](agent-loop/START_HERE.md)；
5. [`agent-loop/CURRENT_STATE.md`](agent-loop/CURRENT_STATE.md)；
6. 已确定领域时，先打开对应任务卡，再读该卡指定的 Skill 和 contract；
7. 仅打开本任务相关实现、测试、Lessons 和当前工件。

不要把历史报告、整个 Git 日志、模型文件或旧对话当作默认上下文。发生事实冲突时，
按 [`CONTEXT_INDEX.yaml`](agent-loop/CONTEXT_INDEX.yaml) 的 `context_policy.authority_order`
裁决；本页只解释入口和用途，不复制第二份优先级列表。

### 文档状态与命令语义

| 标记 | 唯一用途 | 不应承担的用途 |
|---|---|---|
| `CURRENT_STATE.md` | Agent Loop 当前能力、现场证据和仍关闭的能力 | 领域 contract、单次任务验收或历史实施细节 |
| `PROJECT_BASELINE.md` | 当前项目架构、运行时/模型基线 | Loop 实时状态、完整测试报告 |
| Skill / contract | 稳定 workflow、invariant、authoritative schema / HTTP / evidence 语义 | 记录会过期的通过数、Pilot 或临时状态 |
| TaskPacket / TestMatrix / TestReport | 一次任务的命令、final snapshot、Docker 权限和 PASS/FAIL | 覆盖上层 contract 或变成长期项目事实 |
| `archive/` | 已完成计划、Pilot、旧验收和决策追溯 | 新 Agent 的默认读取路径 |

入口卡只选择验证等级；实际命令、Docker scope 和最终 PASS/FAIL 以本次 TaskPacket / TestMatrix / TestReport 为准。没有 TaskPacket 的日常任务从对应 Skill 与 [`DEVELOPMENT.md`](DEVELOPMENT.md) 选择最小验证，不能把历史通过数复制为新证据。

## 2. 路由索引：谁负责、读什么、交付什么

| 领域/触发词 | Owner 与必读 Skill | 最小事实入口 | 最小验证 | 何时交接 |
|---|---|---|---|---|
| 卡牌、规则、legal action、pending choice、C ABI、observation/action schema | Core；[`CORE.md`](agent-entry/CORE.md) → [`core-environment`](../../.agents/skills/core-environment/SKILL.md) | 卡片列出的 contract、`src/`、`include/` | 卡片选择 `check_schema.py`、C++/golden/trace | HTTP、schema 或 evidence 消费者会受影响 |
| PPO、collector、reward、Training Task、resume、warm-start、promotion | Trainer；[`TRAINER.md`](agent-entry/TRAINER.md) → [`training-config`](../../.agents/skills/training-config/SKILL.md) | 卡片列出的模型 / task / Core contract | 卡片选择 validation、smoke、evaluation | Core schema/action grammar 或产品模型槽位变更 |
| React、FastAPI BFF、Core HTTP、UX、动态合法动作 | Product；[`PRODUCT.md`](agent-entry/PRODUCT.md) → [`product-integration`](../../.agents/skills/product-integration/SKILL.md) | 卡片列出的 HTTP contract、`apps/web/` | 卡片选择 BFF、frontend、Docker 验证 | HTTP contract 变更或 Teacher evidence/隐私受影响 |
| Teacher explanation、evidence、privacy、provider、TeacherPanel | Teacher；[`TEACHER.md`](agent-entry/TEACHER.md) → [`teacher-explanation`](../../.agents/skills/teacher-explanation/SKILL.md) | 卡片列出的 evidence / privacy / Product contract | 卡片选择 Teacher、BFF、frontend、Docker 验证 | 缺少 authoritative evidence 时交给 Core；纯 UI 交给 Product |
| 测试、复现、diff/contract 审查、Docker health、证据报告 | Test / Verification；[`TEST_AGENT.md`](agent-loop/TEST_AGENT.md) | 当前 TaskPacket、TestMatrix、最终 snapshot、diff | 声明的命令、日志、health、cleanup、TestReport | 发现生产缺陷或 contract gap 时退回对应 Owner |
| 资料定位、交接、状态沉淀、工件组织 | Context / Integration；本页 → [`AGENT_LOOP_NAVIGATION.md`](AGENT_LOOP_NAVIGATION.md) | ContextBrief、HandoffReport、当前状态、Lessons | 引用可解析、snapshot 一致、交接范围完整 | 不替代任何领域 Owner 定义业务 contract |

Owner 不能因为文件扩展名跨越边界：Core 的 Python golden/trace 仍归 Core；
`tools/server/` 的训练/评估通常归 Trainer；Product 只消费 Core HTTP，不加载 RL 或
C++ shared library；Teacher 解释已执行 evidence，不能决定动作。

## 3. 目录与事实来源地图

| 目录/文件 | 是什么 | 默认 Owner | 何时打开 |
|---|---|---|---|
| `src/`、`include/`、`tests/` | C++ 游戏规则、状态机、C API 和单元测试 | Core | 规则、卡牌、legal action、ABI、clone/trace |
| [`config/rl_contract.json`](../../config/rl_contract.json) | Observation、Action Grammar、Reward ABI 的唯一版本源 | Core | schema/grammar/reward 兼容性问题 |
| `python/src/gwent_rl/`、`python/tests/` | RL runtime、collector、训练/评估测试 | Trainer | 训练、collector、checkpoint、评估 |
| `configs/training/`、[`training/tasks/`](../../training/tasks/) | 算法参数与正式训练任务 | Trainer | 新训练、warm-start、resume、promotion |
| [`apps/web/`](../../apps/web/) | React 前端与 FastAPI BFF | Product | UI、BFF、Core HTTP、Teacher 面板 |
| [`apps/web/docs/CORE_API_CONTRACT.md`](../../apps/web/docs/CORE_API_CONTRACT.md) | Core → Product 的 versioned HTTP/JSON contract | Core 定义，Product 消费 | HTTP 字段、`match_id/revision`、`option_index` |
| [`services/teacher/`](../../services/teacher/) | grounded explanation runtime、privacy filter、provider | Teacher | evidence、解释、隐私、Teacher API |
| [`contracts/README.md`](../../contracts/README.md) | 跨层 contract 总入口 | 对应事实 Owner | 先判断变更是否跨层 |
| [`deploy/docker/`](../../deploy/docker/) | 本地产品、测试与训练 Compose/Dockerfile | Product/Trainer/Test | TaskPacket/TestMatrix 声明服务依赖时 |
| [`data/cards/README.md`](../../data/cards/README.md)、[`data/decks/README.md`](../../data/decks/README.md) | reference/supported cards 与 deck composition manifests | Core | 新卡、卡牌绑定、deck id 或 codegen 数据变更 |
| [`tools/golden/README.md`](../../tools/golden/README.md) | C++/Python trace、legal surface 对拍工具 | Core | 顺序规则、pending choice、跨实现回归 |
| [`models/v3/README.md`](../../models/v3/README.md) | 冻结产品模型槽位与 provenance | Trainer | 只在模型、promotion、loader 任务中读取 |
| [`runs/README.md`](../../runs/README.md)、[`artifacts/README.md`](../../artifacts/README.md) | 可再生成训练输出与长期 pinned 资产 | Trainer | 训练、恢复、模型来源审计 |
| [`scripts/agent_loop/`](../../scripts/agent_loop/) | TaskPacket、执行、恢复、Scheduler、集成控制面 | Context / Integration | 运行或维护受限串行 Loop |
| [`.codex/agents/`](../../.codex/agents/) | 各角色可执行配置 | Loop runtime | 核对角色配置或 Test Agent 能力时 |
| [`.agents/evals/README.md`](../../.agents/evals/README.md) | Coding Agent 路由/证据/边界评估 | Context / Integration | 评估 Agent 行为；不是默认生产任务 |
| `.agent-loop/` | 本机运行状态、原始工件和 child worktree | Loop runtime | 仅按 task id/snapshot 读取；不提交为文档事实 |

## 4. Contract handoff 索引

| 变化 | authoritative Owner | 必须同步/复核的消费者 | 不允许的捷径 |
|---|---|---|---|
| Observation、Action Grammar、Reward ABI | Core | Trainer 判断 checkpoint 兼容性；Product/Teacher 若消费字段则复核 | 在 Python/TS 复制规则或手改生成 mirror |
| Core HTTP 字段或语义 | Core | Product：BFF strict model → API 文档 → TS types → UI | 从 `label/source/target` 文本解析规则 |
| Teacher 新 evidence | Core/Strategy 暴露结构化事实 | Teacher privacy filter → response schema → BFF/UI | Teacher 反推规则、重算 legal actions 或泄露隐藏信息 |
| checkpoint 或产品模型槽位 | Trainer | Core contract 兼容性、产品 provenance | 从 `runs/` 直接作为产品运行时依赖 |
| 测试标准或 fixture | Test 可在声明范围内编辑 | 领域 Owner/人工 gate 复核 | 修改生产代码或降低断言制造 PASS |

跨域任务仍是**串行 handoff**：前一个 Owner 给出最终 snapshot、ChangeReport 和明确
contract 差异；下一个 Owner 只接收声明的事实和工件，不读取前一个 Agent 的全过程。

## 5. 验证索引：先选与风险匹配的门禁

| 任务 | 必跑或优先跑 | 说明 |
|---|---|---|
| 文档、Agent Loop、索引、控制面 | `python3 scripts/check.py architecture` | 不进入 Trainer/torch；验证链接、Agent assets、Loop tests、关键 contract |
| Product/Teacher/Agent Loop Python 测试 | `python3 scripts/check.py docker-test` | Docker 是最终 PASS/FAIL 环境；host pytest 仅用于诊断依赖差异 |
| Product 代码 | BFF tests + `cd apps/web/frontend && npm run build` | Contract 变更还要检查 Core HTTP 文档、Pydantic 和 TS types |
| Teacher 代码 | `check_teacher.py` + Teacher/BFF tests | 还要证明 privacy 与 Teacher failure 不阻断 gameplay |
| Core/schema 代码 | `check_schema.py` + 对应 C++/golden/trace | 修改 runtime spawn/transform 时补真实 `Game::create()` 回归 |
| Training task/config | `validate_training.py --all` + smoke | 不把 `architecture` PASS 当作训练定义 PASS |
| 全项目回归 | `quick` / `test` / `full` / `train` | 只有任务范围和环境允许时使用；它们会进入 Trainer 依赖 |

所有 PASS 都需要对应的最终 snapshot、命令、退出码和失败分类。Docker 仅在 TaskPacket 和
TestMatrix 明确声明时启动，并且只清理本次拥有的资源。

## 6. 受限串行 Loop 索引

当前默认流程是：

```text
TaskPacket / ContextBrief
  -> 单一领域 Owner
  -> ChangeReport + final snapshot
  -> 独立 Test / Verification
  -> TestReport + RunManifest
  -> 必要时隔离 integration / rollback
  -> close
```

- 运行协议与模板：[`agent-loop/README.md`](agent-loop/README.md)；
- 当前能力和限制：[`agent-loop/CURRENT_STATE.md`](agent-loop/CURRENT_STATE.md)；
- 本地 Codex CLI Host create/wait/rebind/close：[`agent-loop/CODEX_TRANSPORT.md`](agent-loop/CODEX_TRANSPORT.md)；
- 测试角色、Docker 和失败分类：[`agent-loop/TEST_AGENT.md`](agent-loop/TEST_AGENT.md)；
- 恢复上限与停止条件：[`agent-loop/RECOVERY_POLICY.md`](agent-loop/RECOVERY_POLICY.md)；
- 可复用坑：[`agent-loop/LESSONS_LEARNED.md`](agent-loop/LESSONS_LEARNED.md)；
- 历史现场证据：[`agent-loop/archive/README.md`](agent-loop/archive/README.md)。

默认 `max_concurrency=1`。未知 snapshot、超出写入范围、隐私/contract 不确定、Docker
ownership 不清、Host 无法 rebind 或任一预算耗尽时，停止为 `HUMAN_REQUIRED`；不要自动修复、
自动解决冲突或扩大权限。

### 写入与环境护栏

- Windows 写入前必须读 [`AGENT_LOOP_NAVIGATION.md`](AGENT_LOOP_NAVIGATION.md) 的 1.1 节和
  [`LESSONS_LEARNED.md`](agent-loop/LESSONS_LEARNED.md) 的 LL-007/LL-008；每次短补丁后立即
  检查目标文件和 Git 状态。
- 直接改脏 parent/main、解决冲突、删除用户改动或扩大 Docker/外部权限，都不是默认动作；
  先按 [`GIT_MANAGEMENT.md`](GIT_MANAGEMENT.md) 和 TaskPacket 停在人工闸门。
- `models/v3/policy.pt` 在当前架构阶段冻结；非 Trainer 任务不读取、不哈希、不替换它。
- 外部 `/mnt/c/codes/gwent_v4` 的两个历史 ZIP 是不可读取的用户改动；不得读取、哈希、
  暂存、合并、删除或以它们为代价执行 reset/clean/stash。完整边界见
  [`agent-loop/START_HERE.md`](agent-loop/START_HERE.md)。

## 7. 工件与状态索引

| 工件 | 作用 | 何时创建/读取 |
|---|---|---|
| TaskPacket | 不可变任务范围、Owner、snapshot、预算、TestMatrix | 非琐碎任务开始前 |
| ContextBrief | 最小事实图、假设、未知项、相关 Lessons | 需要探索或跨域 handoff 时 |
| ChangeReport | Owner 的 changed paths、自检、限制 | 每个实施/修复 attempt 后 |
| Handoff/ReviewReport | 跨域消费差异或独立审查结果 | contract handoff 或 review 时 |
| TestReport | 独立 Test 的命令、证据、分类、cleanup | Test 从最终 snapshot 开始后 |
| RunManifest | 角色运行、预算、状态、工件和终止原因 | Loop 生命周期内持续写入 |
| IntegrationManifest | 隔离集成、最终 commit 和 rollback 证据 | Test PASS 且需要集成时 |

模板位于 [`agent-loop/README.md`](agent-loop/README.md)。原始运行工件在 `.agent-loop/`，
已提交结论必须脱敏、可链接且绑定 snapshot。

## 8. 新 Agent 的可复制任务开场

```text
先读 AGENTS.md、docs/current/AGENT_ONBOARDING_INDEX.md、
docs/current/agent-loop/CONTEXT_INDEX.yaml、docs/current/agent-loop/START_HERE.md
和 CURRENT_STATE.md；然后只读本任务对应的
Skill、contract、实现、测试与 Lessons。不要扫描全仓库、读取模型或历史归档。

目标：<一句话>
责任域：<core | trainer | product | teacher | test | loop>
允许写入：<精确目录或文件>
基线：<commit/snapshot>
验收：<命令、contract、Docker 需求>
停止条件：<权限、预算、隐私、snapshot 或 handoff 不确定时 HUMAN_REQUIRED>
```

## 9. 索引维护规则

| 发生什么变化 | 必须更新 |
|---|---|
| 路由、Skill、默认 Loop、Host 能力或停止条件变化 | `AGENTS.md`、本页、`START_HERE.md`、必要时 `CURRENT_STATE.md` |
| 当前架构、运行时能力、可验证现场证据变化 | `PROJECT_BASELINE.md` / `CURRENT_STATE.md` |
| 跨层 contract 变化 | 对应领域文档、contract、Skill reference、消费者入口与测试 |
| 日常启动或测试命令变化 | `LOCAL_DOCKER.md` / `DEVELOPMENT.md` / `PROJECT_TEST_PLAN.md` |
| 已验证、会重复发生的坑 | `LESSONS_LEARNED.md`，附来源、snapshot、关键词和验证 |
| 已完成的计划、Pilot 或实施记录 | 移入 `archive/`，在当前文档中只保留简短、可链接的历史指针 |

本页每次变更后至少运行 `python3 scripts/check.py architecture`。新增入口前先确认它
不会让新 Agent 重复读取同一事实、绕过 Skill 或把历史材料误当当前状态。
