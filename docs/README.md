# Documentation

本文档目录按“事实来源”和“使用场景”组织。当前源码的结论以基线和
contract 为准；方案/实施记录只用于解释为什么这样设计，不能覆盖当前代码。

## 新 Agent / 新对话

1. [`../AGENTS.md`](../AGENTS.md) — 治理、路由和不可跨越的边界；
2. [`current/AGENT_ONBOARDING_INDEX.md`](current/AGENT_ONBOARDING_INDEX.md) — 按任务定位 Owner、Skill、contract、目录和验证；
3. [`current/agent-loop/START_HERE.md`](current/agent-loop/START_HERE.md) — 受限串行任务的最小读取顺序和生命周期；
4. [`current/agent-loop/CURRENT_STATE.md`](current/agent-loop/CURRENT_STATE.md) — 唯一实时运行状态。
5. 已确定领域的实施任务再读 [`current/agent-entry/README.md`](current/agent-entry/README.md) — 只打开对应任务卡、Skill 和最小事实集。

## 当前事实来源

1. [`current/PROJECT_BASELINE.md`](current/PROJECT_BASELINE.md) — 当前架构、运行版本、模型资产和已验证链路；
2. [`current/ARCHITECTURE.md`](current/ARCHITECTURE.md) — Development Plane / Runtime Plane 和职责边界；
3. [`../apps/web/docs/CORE_API_CONTRACT.md`](../apps/web/docs/CORE_API_CONTRACT.md) — Core HTTP、`match_id/revision`、step、preview 和错误 contract；
4. [`current/CORE_CONTRACTS.md`](current/CORE_CONTRACTS.md) — C++ Core、legal action、RL 与跨层 contract 原则；
5. [`current/TEACHER_AND_WEB.md`](current/TEACHER_AND_WEB.md) — AI 决策过程、AI 教师、隐私和故障隔离；
6. [`current/TRAINING_AND_MODEL.md`](current/TRAINING_AND_MODEL.md) — 训练、模型槽位、checkpoint 和 promotion 边界。

## 日常操作

- [`current/LOCAL_DOCKER.md`](current/LOCAL_DOCKER.md) — 本地 Docker 启动、停止、配置和浏览器入口；
- [`current/DEVELOPMENT.md`](current/DEVELOPMENT.md) — C++、Python、Web、Teacher 的开发命令；
- [`current/PROJECT_TEST_PLAN.md`](current/PROJECT_TEST_PLAN.md) — 测试分层、当前结果和未覆盖项目；
- [`../apps/web/README.md`](../apps/web/README.md) — Web 产品边界和模块入口。

## 设计与实施记录

- [`current/archive/README.md`](current/archive/README.md) — 历史文档归档规则与索引；
- [`current/archive/design/LOGIC_OPTIMIZATION_PLAN.md`](current/archive/design/LOGIC_OPTIMIZATION_PLAN.md) — M0–M4 状态边界、revision、缓存和验收的历史记录；
- [`current/archive/design/AI_DECISION_AND_TEACHER_TURN_PLAN.md`](current/archive/design/AI_DECISION_AND_TEACHER_TURN_PLAN.md) — AI 决策过程与教师行动链的历史设计；
- [`current/archive/design/LOCAL_DOCKER_PLAN.md`](current/archive/design/LOCAL_DOCKER_PLAN.md) — Docker 架构与实施历史；
- [`current/archive/design/LOCAL_DOCKER_INSTALL_NOTES.md`](current/archive/design/LOCAL_DOCKER_INSTALL_NOTES.md) — Windows/Docker Desktop 安装坑和复现流程（历史复盘）。

上述记录中的“建议”“规划中”只表示历史阶段；若与基线或源码不一致，以基线、
详细 contract 和实际验证为准。更细的工程规则放在 `.agents/skills/*/`，协议级
细节放在对应模块的 contract 文件中。
