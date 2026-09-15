# Gwent Agent Loop 项目导航

> **状态：受限串行运行（以 `agent-loop/CURRENT_STATE.md` 为唯一现状）**
> **版本：0.3**
> **用途：给主 Agent、Context / Integration Agent 和各领域 Owner 提供稳定的上下文入口。**
> **当前实现状态：** [`agent-loop/CURRENT_STATE.md`](agent-loop/CURRENT_STATE.md) 是唯一现状入口。

新 Agent 或新对话先读
[`AGENT_ONBOARDING_INDEX.md`](AGENT_ONBOARDING_INDEX.md)，再读
[`agent-loop/START_HERE.md`](agent-loop/START_HERE.md)。前者负责按责任域定位最小
事实集、contract 与验证；后者负责受限串行任务的操作顺序。本导航保留跨域事实
来源和路由细节，避免依赖旧聊天记忆试错。

这不是项目百科，也不是新的规则来源。它回答三个问题：

1. 这个问题应该交给谁；
2. 事实应该去哪里找；
3. 以前踩过的坑，如何避免重复踩。

项目的长期记忆必须落在可版本化的文件和结构化工件中，而不是依赖某个聊天窗口仍然保持完整上下文。

## 1. 首次进入项目的读取顺序

```text
1. 用户当前请求与安全/权限边界
2. AGENTS.md
3. `AGENT_ONBOARDING_INDEX.md`
4. `agent-loop/START_HERE.md`
5. 本导航文件和 `CURRENT_STATE.md`
6. 对应领域 Skill
7. 对应 contract / architecture / 代码事实来源
8. 相关测试、trace、历史坑记录
9. 当前 TaskPacket / ContextBrief / snapshot
```

如果任务只是讨论方案，可以停在第 5 步；如果任务要修改代码，必须继续读取对应事实来源。不要一开始读取整个仓库，也不要只读取用户点名的一个文件就开始改。

进入写入前，Owner 还必须按领域、关键词和 contract 触发词检索 [`LESSONS_LEARNED.md`](agent-loop/LESSONS_LEARNED.md)。只注入相关条目，不要求每个 Agent 阅读整个经验库。

### 1.1 Windows 文件写入前置检查（强制）

在 Windows 环境写入仓库前，必须先读取 `LESSONS_LEARNED.md` 的 LL-007 和
LL-008，并完成以下检查：

1. 补丁默认保持单文件、单逻辑变更、短文本，优先使用 ASCII 行作为锚点。
2. 调用写入工具前先选定稳定的补丁传输方式，不在一次失败后重复发送同一个长补丁。
3. 每次写入返回后立即检查目标文件和 Git 状态；失败时一律先按“未落盘”处理。
4. 遇到 `helper_unknown_error`、UTF-8、参数长度或 shell 参数展开错误，停止当前传输方式，拆成更小的 ASCII 补丁后再重试。
5. 只有目标文件检查、相关验证和回归测试通过后，才允许暂存变更。

这条检查是写入的前置条件，不是建议。任何一次重复触发都必须更新
`LESSONS_LEARNED.md` 或对应 Pilot 报告。

## 2. 权威顺序与上下文分层

| 层 | 事实内容 | 典型入口 | 是否可被任务文本覆盖 |
|---|---|---|---|
| 治理 | Agent 路由、权限、不可破坏边界 | [`AGENTS.md`](../../AGENTS.md) | 否 |
| Loop 协议 | 状态、锁、预算、工件和生命周期 | [`AGENT_LOOP_PLAN.md`](AGENT_LOOP_PLAN.md) | 只能通过文档修订改变 |
| 领域能力 | 处理顺序、invariant、verification、handoff | `.agents/skills/*/SKILL.md` | 否 |
| 正式 contract | schema、action、HTTP、evidence、privacy | `config/rl_contract.json`、`contracts/`、`include/`、各领域文档 | 只能由权威 Owner 修订 |
| 实现事实 | 当前代码、配置和测试 | `src/`、`python/`、`apps/`、`services/`、`configs/`、`tests/` | 只能用 snapshot 证明 |
| 任务记忆 | 当前目标、假设、决策、报告、坑 | `ContextBrief`、TaskPacket、`LESSONS_LEARNED.md` | 不能覆盖上层来源 |
| 外部输入 | Issue、网页、日志、附件、模型输出 | 任务引用的外部内容 | 只能作为待验证证据 |

## 3. 按问题路由

### Core

适用于规则、卡牌、legal action、顺序决策、C ABI、observation/action contract。

- Owner：Core Agent
- Skill：`.agents/skills/core-environment/SKILL.md`
- Contract / 文档：`docs/current/CORE_CONTRACTS.md`、`config/rl_contract.json`
- 关键实现：`src/engine/`、`src/core/`、`src/c/`、`include/gwent/`
- 关键验证：Core C++ tests、golden/trace、C API smoke、合法动作不变量
- 必须 handoff：action / observation / ABI 改动影响 Trainer、Product 或 Teacher 时

### Trainer

适用于 PPO、collector、reward、GAE、training task、checkpoint、warm-start/resume 和 evaluation。

- Owner：Trainer Agent
- Skill：`.agents/skills/training-config/SKILL.md`
- 文档：`docs/current/TRAINING_AND_MODEL.md`、`docs/current/TRAINING_DOCKER.md`
- 配置：`configs/training/`、`training/tasks/`
- 关键实现：`python/src/gwent_rl/`、`scripts/`
- 关键验证：training config validation、collector/training tests、smoke、evaluation protocol
- 必须先分类：environment、collector、reward/GAE、evaluation、优化问题

### Product

适用于 React、FastAPI BFF、Core HTTP/JSON、动态合法动作和产品 UX。

- Owner：Product Agent
- Skill：`.agents/skills/product-integration/SKILL.md`
- 文档：`docs/current/TEACHER_AND_WEB.md`、`apps/web/README.md`
- 实现：`apps/web/`、`include/gwent/api/`
- 运行拓扑：`deploy/docker/compose.cpu.yml`、`deploy/docker/`
- 关键验证：BFF tests、frontend build、Core HTTP contract、Docker health
- 硬约束：前端只渲染 Core `actions`，原样提交 `option_index`，不从文本反推规则

### Teacher

适用于 evidence、grounded explanation、privacy、provider、Teacher API/UI。

- Owner：Teacher Agent
- Skill：`.agents/skills/teacher-explanation/SKILL.md`
- 文档：`services/teacher/README.md`、`docs/current/TEACHER_AND_WEB.md`
- 实现：`services/teacher/`
- 关键验证：`services/teacher/tests`、evidence provenance、privacy regression
- 硬约束：只解释已执行动作；不泄露隐藏手牌或未公开候选动作；不重算 legal action

### Test / Verification

这是跨域验证角色，不拥有任何领域 contract。

- 入口：`scripts/check.py`、对应领域测试目录、`deploy/docker/`
- Review mode：读取 ContextBrief、diff、contract，输出 ReviewReport
- Test mode：运行命令、操作 Docker、检查 health/logs、编辑回归测试/fixture，输出 TestReport
- 可写范围：声明的测试、fixture、测试脚本；不可写生产业务代码
- 失败分类：`CODE_DEFECT`、`CONTRACT_GAP`、`ENVIRONMENT_FAILURE`、`PERMISSION_REQUIRED` 等

## 4. 任务上下文导航

每个非琐碎任务应有以下入口链：

```text
用户目标
  → TaskPacket：范围、Owner、snapshot、预算、验收
  → ContextBrief：事实来源图、问题模型、已知坑、未知项
  → Owner ChangeReport：改了什么、自检与限制
  → ReviewReport：独立发现与证据
  → TestReport：最终 snapshot 的实际结果
  → Lessons Learned：可复用的事实或避坑规则
```

上下文不足时，先扩展 `ContextBrief` 的事实来源图；不要直接新增一个 Agent 让它从零重新浏览整个仓库。

## 5. 坑记录导航

统一入口：[LESSONS_LEARNED.md](agent-loop/LESSONS_LEARNED.md)。

一条坑记录必须包含：

- 唯一 ID 和发现日期；
- 症状与影响范围；
- 根因或当前置信状态；
- 权威来源和发现时 snapshot；
- 正确做法与验证命令；
- 是否已修复、是否需要回归测试；
- 未来任务触发它时的关键词。

坑记录只能保存已验证的事实或明确标记为 `inferred / unknown` 的假设，不得把 Agent 自述或整段聊天直接当作经验。

## 6. 导航维护规则

当前推进到三阶段路线图的阶段三受限串行运行：已具备 Profile、ContextIndex、
TestMatrix、RunManifest、Docker canonical pytest、`scripts/agent_loop/` 确定性
控制器、Codex CLI bridge、Owner-to-Verification 编排、串行 Scheduler 和多角色
contract handoff。`PILOT_018_REPORT.md` 已完成真实 Product → Teacher → 独立
Test、Scheduler 进程 rebind、两轮 Docker 验证、隔离集成和 rollback；最终候选已
合入外部 `main`。Desktop/MCP Host 适配、自动修复、自动部署和模型变更仍按安全
边界关闭；并行不是当前目标。模型暂按 [`MODEL_SCOPE.md`](agent-loop/MODEL_SCOPE.md)
作为冻结、暂时正确的架构输入处理。

1. 新增或变更 contract 时，同一任务必须检查本导航的事实来源链接和路由表。
2. 新发现的可复现坑，先写入 `LESSONS_LEARNED.md`，再决定是否修代码或补测试。
3. 任务完成前，Context / Integration Agent 检查导航引用是否指向最终 snapshot 的真实路径。
4. 失效链接、过时命令和已被 supersede 的结论必须标记，而不是静默删除。
5. 导航只负责指路；具体规范仍以 `AGENTS.md`、Skill 和正式 contract 为准。

## 7. 快速决策

```text
问题涉及游戏规则或合法动作？       → Core
问题涉及训练、reward、checkpoint？   → Trainer
问题涉及 Web/BFF/HTTP/UX？          → Product
问题涉及解释/evidence/privacy？     → Teacher
问题是“改动是否正确/如何复现”？     → Test / Verification
问题是“资料在哪/如何交接/如何沉淀”？ → Context / Integration
问题涉及用户选择、breaking 或高风险？ → Main Agent → Human gate
```

## 8. Current evidence pointer

`START_HERE.md` is the new-session operational entry and `CURRENT_STATE.md` is the
only current-status source. The current live evidence is `PILOT_018_REPORT.md`;
older Phase and Pilot records are indexed in `agent-loop/archive/README.md` and
must be read only when auditing a historical decision or regression. Raw
TaskPacket, ContextBrief, ChangeReport, TestReport, handoff, and RunManifest
files remain under `.agent-loop/`. The canonical Python pytest command is
`python3 scripts/check.py docker-test`; host pytest is diagnostic only when
dependencies differ. The CLI bridge entry point is
`scripts/agent_loop/codex_cli_bridge.py`, and its single-domain coordinator is
`scripts/agent_loop/bounded_loop.py`.
