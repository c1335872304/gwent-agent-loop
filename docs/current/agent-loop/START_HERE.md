# Agent Loop 新对话启动页

> 这是新 Agent / 新对话的第一份操作入口。它不替代治理、Skill、contract
> 或当前状态；它只告诉执行者先读什么、如何路由、何时停止，以及证据放在哪里。
>
> 当前状态只以 [`CURRENT_STATE.md`](CURRENT_STATE.md) 为准；本页的规则是
> 稳定操作约束，现场数字和试点结论不要复制到这里。
>
> 先用 [`../AGENT_ONBOARDING_INDEX.md`](../AGENT_ONBOARDING_INDEX.md) 识别责任域、
> 最小事实集和验证等级；本页只负责受限串行 Loop 的操作顺序与停止条件。

## 0. 一句话理解

本项目的默认 Loop 是**串行、单写者、有界、可恢复、证据优先**：

```text
用户目标
  -> TaskPacket / ContextBrief
  -> 一个领域 Owner
  -> 一个独立 Test / Verification
  -> TestReport / RunManifest
  -> 必要时隔离集成与 rollback
  -> 关闭并保留工件
```

不要把它理解成无限递归的 Manager，也不要把换一个会话当成“重新学习”。
新会话应读取仓库中的结构化上下文；原任务恢复则通过持久化的 task identity
和 `runner_ref` 执行 lookup/rebind。

## 1. 上下文装配

首次读取顺序、责任域路由、事实来源选择和状态语义的唯一入口是
[`../AGENT_ONBOARDING_INDEX.md`](../AGENT_ONBOARDING_INDEX.md)。本页不复制这些表，
只规定执行时必须带入的最小上下文：

- `TaskPacket`：范围、Owner、snapshot、预算、验收和写入边界；
- `ContextBrief`：`fact_source_graph`、事实账本、假设、未知项和相关 Lessons；
- 当前 snapshot：代码/配置事实必须绑定到可复现的 commit 或工作树清单；
- 对应领域任务卡 → Skill → contract → 最近实现/测试；
- 子任务只接收以上结构化工件，不接收父对话全文、全仓库扫描结果、历史归档或
  `docs/current/agent-loop/pilots/` 兼容夹具。

共享策略见 [`CONTEXT_INDEX.yaml`](CONTEXT_INDEX.yaml) 的 `context_policy`；ContextBrief
只记录本任务实际装入、排除和冲突的引用，不复制共享策略。出现冲突时按
`context_policy.authority_order` 处理，未解决冲突必须停止为 `HUMAN_REQUIRED`。

## 2. 默认执行模式

除非用户明确改变边界，否则保持以下设置：

- `max_concurrency=1`，一次只允许一个写入 Owner；
- 先 Owner，后独立 Test；Test 不读取 Owner 的实现过程，只看最终 snapshot；
- 子任务只接收 TaskPacket、ContextBrief、Profile 和仓库规则，不接收父对话全文；
- 使用本地 Codex CLI Host 时，任务在声明的 Git snapshot 和隔离 worktree 中执行；
- Docker 只有 TaskPacket/TestMatrix 明确声明时才启动，并且只清理本次拥有的资源；
- 不自动修复生产代码、不自动解决冲突、不自动放宽测试、不自动部署；
- 不加载、替换、重训或删除冻结的 `models/v3/policy.pt`；
- 任意权限、隐私、contract、snapshot、预算或宿主恢复不确定性都停止为
  `HUMAN_REQUIRED`。

“串行”是本项目的设计目标，不是临时退化方案；不需要为了看起来更智能而增加并行。

## 3. 修改任务的标准流程

### 3.1 创建最小任务上下文

非琐碎任务先创建不可变 TaskPacket，至少明确：

- `task_id`、`revision`、Owner 和责任域；
- `project_id`、Git `base_snapshot` 和 worktree 目标；
- `allowed_write_paths`、测试可写目录和禁止修改范围；
- 验收条件、TestMatrix、Docker 需求和 cleanup 责任；
- `max_attempts`、`max_resumes`、token、turn、时间和子任务上限；
- 输出要求：ChangeReport、Handoff/ReviewReport、TestReport、RunManifest。

需要探索事实时再创建 ContextBrief，列出来源、已知事实、假设、未知项和
触发的 Lessons；不要用一个新 Agent 代替上下文整理。

### 3.2 Owner 只做声明范围内的工作

Owner 必须：

1. 从精确 snapshot 开始；
2. 先读对应 Skill、contract 和相关 Lessons；
3. 做最小修改，不越过领域边界；
4. 运行该领域自检；
5. 生成 ChangeReport，写明 changed paths、snapshot、测试、限制和未知项。

Owner 不得把“测试绿了”当成独立验证，也不得修改 Test 标准来制造 PASS。

### 3.3 独立 Test / Verification

Test Agent 只从 Owner 最终 commit/snapshot 出发，独立检查：

- changed paths 是否在允许范围内；
- contract、隐私和文件范围是否满足；
- TestMatrix 中声明的命令、退出码、日志和 Docker health；
- 测试是否真实失败、环境失败、权限失败、协议失败或预算失败；
- TestReport 是否包含可复现证据、cleanup 和空的/明确的失败分类。

没有独立证据，不得写 PASS；不能运行时写清楚 `ENVIRONMENT_FAILURE` 或
`HUMAN_REQUIRED`，不要把主机上的半成功当作最终结论。

### 3.3a 重试必须产生学习增量

`RETRY_TEST` 和 `RETURN_TO_OWNER` 不是无条件的“再跑一次”。调用
`RunnerExecution.recover()` 前必须提供脱敏失败签名、改变项、前置检查和
成功替代动作组成的 `RetryLearningDelta`。同一失败签名、前置条件未变且
delta 未变时，控制面进入 `STOP_NO_LEARNING`；未经确认或晋级的 Lesson 不得
作为下一次任务上下文。成功的 retry 会自动写入 candidate-only Lesson，供
后续 E2/E3/E4 审核，不能在当前任务中直接提升为正式规则。

### 3.4 集成和关闭

只有最终 snapshot、changed paths、contract、TestReport 和预算都通过后，才生成
IntegrationManifest。脏 parent 的 disjoint candidate 可以自动产出隔离分支或
worktree，但直接修改 parent/main、解决冲突、删除用户改动仍需明确人工闸门。

关闭前必须保留：TaskPacket、ContextBrief、ChangeReport、Handoff、TestReport、
RunManifest、IntegrationManifest 和 rollback 证据。关闭会话不能删除这些工件。

## 4. 本地 Codex CLI 用法

本地 CLI 是当前已现场验证的 Host；Desktop/MCP 是可选的另一层适配，不要混用
两者的能力假设。

权威实现和顺序：

1. `scripts/agent_loop/codex_bridge.py` 构建 project-task 请求；
2. `scripts/agent_loop/codex_cli_bridge.py` 校验 project/snapshot，创建隔离
   worktree，启动 `codex exec --json`，映射 wait/resume/close；
3. Host registry 持久化 task identity、PID、worktree 和日志；
4. 新 Scheduler 进程使用原 `runner_ref` lookup/rebind，不能重复 create；
5. `bounded_loop.py` 串联一个 Owner 和一个独立 Test；
6. 所有事件先写 ExecutionJournal，再推进下一步；
7. 最终关闭前校验报告、预算和 changed paths。

操作细节以 [`CODEX_TRANSPORT.md`](CODEX_TRANSPORT.md) 为准。当前现场 canary 不使用旧
Pilot 启动器。`run_stage3_live.py` 固定的是历史 Pilot 011 的 task、snapshot 和预算，
只能在追溯该 Pilot 时查看帮助，不能作为当前任务入口。首次使用或参数不确定时先查看
当前 TaskPacket，不要凭聊天记忆发明参数：

```bash
python3 scripts/agent_loop/run_stage3_live.py --help
```

## 5. 验证命令速查

```bash
# Agent Loop / 架构任务的默认门禁，不加载 Trainer 模型
python3 scripts/check.py architecture

# TaskPacket/TestMatrix 明确需要 Docker 时的权威 Python pytest
python3 scripts/check.py docker-test

# 领域专项验证，按对应 Skill 选择，不要无条件全部运行
PYTHONPATH=. python3 -m pytest -q services/teacher/tests
PYTHONPATH=apps/web/backend python3 -m pytest -q apps/web/backend/tests
cd apps/web/frontend && npm run build
```

规则：`docker-test` 是 Product、Teacher 和 Agent Loop Python pytest 的最终环境；
主机 pytest 只能用于诊断环境差异。架构任务不要默认运行 `scripts/check.py quick`，
因为它会进入 Trainer/torch 检查。

## 6. 必须停止的情况

遇到下列任一情况，先持久化状态和原因，再停止；不要猜测、无限重试或自动修复：

- 没有可复现的 Git HEAD/snapshot，或 snapshot 已漂移；
- Owner 越过 `allowed_write_paths`，或 Test 想修改生产代码；
- Core/Product/Teacher/Trainer contract 所有权不清或出现 breaking 变更；
- 发现隐藏信息、prompt、未公开候选动作或其他 privacy 风险；
- Docker 权限、健康状态、资源所有权或 cleanup 无法证明；
- Host session 找不到、rebind 不确定、恢复点或责任链无法证明；
- token、turn、时间、attempt 或 resume 上限耗尽；
- parent 有无法归属的改动、Git 冲突或合并范围不明确。

失败分类优先于“继续试一次”：`CODE_DEFECT`、`CONTRACT_GAP`、
`ENVIRONMENT_FAILURE`、`DOCKER_FAILURE`、`PERMISSION_REQUIRED`、`PROTOCOL_FAILURE`、
`BUDGET_EXHAUSTED` 和 `HUMAN_REQUIRED` 不得互相伪装。

## 7. 本仓库的特殊文件边界

外部 `/mnt/c/codes/gwent_v4/main` 中的以下四个历史 ZIP 是不可读取的用户改动：

```text
packages/gwent_architecture_20260910_173340.zip
packages/gwent_architecture_20260910_181503.zip
release_assets/gwent-v3-models-update20.zip
release_assets/gwent-v3-update20-model.zip
```

不要读取、哈希、暂存、合并、删除或改变它们的内容；其他文件的合并也不能以
覆盖它们为代价。当前外部 `main` 若只显示这四个路径为 modified，应保留并报告，
不要用 reset、clean 或 stash 处理。

## 8. 新对话可直接使用的启动模板

新对话不需要依赖旧聊天。把下面信息写入任务上下文，或让 Agent 从仓库读取：

```text
请先读取 AGENTS.md、docs/current/AGENT_ONBOARDING_INDEX.md、
docs/current/agent-loop/CONTEXT_INDEX.yaml、docs/current/agent-loop/START_HERE.md
和 docs/current/agent-loop/CURRENT_STATE.md；
然后只读本任务对应的领域任务卡、Skill、contract、实现、测试与 Lessons。
不要扫描全仓库，不要读取模型或四个历史 ZIP。

目标：<一句话目标>
责任域：<core | trainer | product | teacher | loop>
允许写入：<精确文件/目录>
禁止写入：<文件/目录>
基线 snapshot：<Git ref/commit>
验证命令：<TestMatrix / Docker 命令>
预算：<attempt / resume / token / turn / time>
执行模式：串行，一个 Owner 后一个独立 Test；未知状态进入 HUMAN_REQUIRED。

完成时请交付：changed paths、最终 commit、ChangeReport、TestReport、
RunManifest、失败分类、实际命令和是否需要人工集成。
```

## 9. 文档维护

每次有实质性 Loop 变化时，先更新 `CURRENT_STATE.md`；入口、命令、路由或边界
变化时更新本页和导航。可复现且已验证的新坑写入 `LESSONS_LEARNED.md`；未经验证
的内容标记为 `inferred` 或 `unknown`。不要把一次聊天中的临时判断直接升级为事实。
