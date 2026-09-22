# Gwent Agent Loop 架构手册规划

## 使用说明：手册定位

### 1.1 手册目的

本手册用于帮助新加入的开发者、Agent 和面试者，在不依赖历史聊天记录的情况下，理解 Gwent 项目的 Agent Loop、上下文治理、流程控制、独立验证和自进化机制。

### 1.2 手册解决的问题

- 项目为什么需要 Agent Loop；
- 主 Codex、领域 Agent 和 Test Agent 分别负责什么；
- 一个任务如何被接收、执行、验证、恢复和关闭；
- 上下文如何选择、装载、排除和绑定快照；
- 失败如何分类，为什么不能盲目重试；
- 执行弯路如何沉淀为候选经验；
- 哪些经验可以进入后续任务，哪些变化必须经过人工批准。

### 1.3 手册边界

本手册是解释层，不取代权威规则文件：

- 当前状态以 `docs/current/agent-loop/CURRENT_STATE.md` 为准；
- 新对话入口以 `AGENT_ONBOARDING_INDEX.md`、`CONTEXT_INDEX.yaml` 和 `START_HERE.md` 为准；
- 领域实施规则以对应 Skill 和 contract 为准；
- 本手册不重复维护试点数字、临时命令和历史状态；
- 正文中所有“当前已实现”“待实现”和“已关闭能力”必须能回指事实来源。

### 1.4 每章统一写法

每章正文统一包含：

1. 本章解决什么问题；
2. 核心概念；
3. 当前项目中的对应文件；
4. 实际执行流程；
5. 一个具体例子；
6. 常见错误和历史弯路；
7. 最小验证命令；
8. 当前限制和交接条件。

---

## 第 0 章：先看懂整个项目

### 0.1 一句话理解项目

知识点：

- Gwent Runtime 负责游戏运行；
- Agent Loop 负责工程任务运行；
- 自进化负责分析工程执行过程；
- 游戏模型的决策与 Coding Agent 的工程行为不是同一个系统。

### 0.2 三层平面

知识点：

- 运行时平面：Core、Strategy、Web、Teacher Runtime；
- 控制平面：TaskPacket、上下文、调度、Runner、验证和证据；
- 经验治理平面：执行记录、弯路分析、候选经验和晋级闸门。

### 0.3 一次任务的最短路径

知识点：

```text
用户目标
→ 任务包
→ 上下文简报
→ 一个领域 Owner
→ 独立 Test Agent
→ 诊断与失败分类
→ 恢复策略
→ 证据清单
→ 弯路分析
```

### 0.4 新读者的阅读路线

知识点：

- 只想执行任务：先读本章、第 3 章和第 6 章；
- 想理解 Agent 协作：再读第 4、5、7、9 章；
- 想理解恢复和自进化：重点读第 8、10、12 章；
- 想准备面试：完整阅读第 0、3、4、6、8、9、10、13 章。

### 0.5 本章输出

读者应能用三分钟说明：项目分为哪些平面、一次任务如何流动、为什么需要独立验证和上下文治理。

---

## 第 1 章：项目分层与 Agent Loop 的位置

### 1.1 项目目录总览

知识点：

- `src/`、`include/`：C++ Core 和规则实现；
- `python/`、`configs/`、`training/`：训练和评估；
- `apps/web/`：产品前端和 BFF；
- `services/teacher/`：运行时 Teacher；
- `.agents/`：Skill、参考资料和 Agent 评测；
- `.codex/agents/`：Coding Agent 和 Test Agent 配置；
- `scripts/agent_loop/`：控制面、状态机、执行、恢复和证据实现；
- `docs/current/agent-loop/`：当前架构协议、模板和验证说明。

### 1.2 运行时与开发时的区别

知识点：

- Runtime 处理对局、策略、解释和产品请求；
- Agent Loop 处理代码修改和验证任务；
- Transformer/PPO 不等于 Coding Agent；
- Teacher Runtime 不等于 Teacher Coding Agent。

### 1.3 Agent Loop 在项目中的位置

知识点：

- Loop 不直接定义游戏规则；
- Loop 通过 Skill、contract 和验证约束领域 Agent；
- Loop 为 Core、Trainer、Product、Teacher 提供统一执行框架；
- Test Agent 只验证结果，不拥有业务事实。

### 1.4 本章应配图

知识点：

- 项目三层平面图；
- Runtime 数据流；
- Agent Loop 控制流；
- 控制平面如何维护运行时平面。

### 1.5 本章输出

读者应能准确指出某个文件属于运行时、领域实现、控制面还是经验治理，不再按“Python/C++/前端”机械判断职责。

---

## 第 2 章：控制平面与运行时平面

### 2.1 什么是控制平面

知识点：

- 控制平面不执行游戏业务；
- 控制平面管理任务、责任、状态、预算和证据；
- 控制平面决定任务能否继续；
- 控制平面不能绕过领域 contract。

### 2.2 什么是运行时平面

知识点：

- Core 提供规则和合法动作；
- Strategy 从合法动作中选择；
- Web 负责交互和 API；
- Teacher Runtime 根据结构化证据生成解释。

### 2.3 两个平面的边界

知识点：

- 控制平面可以维护运行时代码，但不代替运行时做决策；
- 运行时失败不能自动改变控制平面的规则；
- 模型文件默认冻结，架构任务不自动加载或重训模型；
- 领域变化必须通过 contract 和验证结果交接。

### 2.4 主 Codex 的位置

知识点：

- 主 Codex 是编排入口；
- 主 Codex 负责理解目标、路由责任域、装配上下文和推进生命周期；
- 主 Codex 不替 Core、Trainer、Product 或 Teacher 定义领域事实；
- 主 Codex 不是拥有额外业务权限的 Manager Agent。

### 2.5 本章输出

读者应能解释：为什么调度器可以控制任务生命周期，却不能替领域 Agent 决定规则、训练策略或教师解释内容。

---

## 第 3 章：Agent Loop 生命周期和状态机

### 3.1 正常状态链

知识点：

```text
RECEIVED
→ TRIAGED
→ CONTEXTUALIZED
→ PLANNED
→ ASSIGNED
→ IMPLEMENTING
→ REVIEWING
→ TESTING
→ COMPLETED
```

### 3.2 每个状态的含义

知识点：

- `RECEIVED`：收到任务；
- `TRIAGED`：判断责任域、风险和任务类型；
- `CONTEXTUALIZED`：装载最小必要上下文；
- `PLANNED`：确认范围、验收条件、预算和验证命令；
- `ASSIGNED`：确定一个领域 Owner；
- `IMPLEMENTING`：Owner 实施修改；
- `REVIEWING`：Owner 自检并准备交接；
- `TESTING`：独立 Test Agent 验证最终快照；
- `COMPLETED`：验证通过并完成证据收口。

### 3.3 异常状态

知识点：

- `BLOCKED`：等待外部条件；
- `HUMAN_REQUIRED`：需要人工判断权限、环境、预算、隐私或 contract；
- `CANCELLED`：任务被取消；
- `SUPERSEDED`：任务被新 revision 替代；
- `COMPLETED`、`CANCELLED`、`SUPERSEDED` 不允许继续转移。

### 3.4 合法与非法转换

知识点：

- 状态机只允许显式声明的转换；
- `REVIEWING`、`TESTING` 可以有限回到 `TRIAGED`；
- 不能从终止状态重新开始；
- 事件必须匹配当前状态、事件序号和任务 revision；
- 重放同一事件必须幂等，不得重复推进。

### 3.5 状态机与恢复策略的区别

知识点：

- 状态机记录任务处于哪个生命周期阶段；
- 恢复策略决定失败后的下一步动作；
- `RETRY_TEST`、`RETURN_TO_OWNER`、`RESUME_SAME_RUNNER` 是恢复决策，不是状态；
- 是否允许重试还要经过重试学习门。

### 3.6 本章输出

读者应能画出正常状态链，并说明失败后为什么不能直接跳回任意状态。

---

## 第 4 章：主 Codex、领域 Agent 与 Test Agent

### 4.1 角色总览

知识点：

```text
主 Codex：编排和控制
Core Agent：规则事实
Trainer Agent：训练事实
Product Agent：产品事实
Teacher Agent：解释事实
Test Agent：独立验证
```

### 4.2 主 Codex 的职责

知识点：

- 解析用户目标；
- 判断责任域；
- 生成或校验 TaskPacket；
- 装配 ContextBrief；
- 推进状态和恢复流程；
- 收集报告和生成 RunManifest；
- 不越权修改领域 contract。

### 4.3 Core Agent

知识点：

- 规则、卡牌效果和合法动作；
- Observation、Action Grammar、C ABI；
- Core 是规则和合法性的唯一事实来源；
- 不在 Python、TypeScript 或 Teacher 中复制规则；
- contract 或 evidence 字段变化时交接给相关领域。

### 4.4 Trainer Agent

知识点：

- PPO、采样、奖励、训练任务和模型 provenance；
- 区分算法配置和正式训练任务；
- 判断 resume、warm-start 和 schema migration；
- 不把临时运行输出当成正式模型；
- 不替代 Core 定义规则。

### 4.5 Product Agent

知识点：

- React、FastAPI BFF、Core HTTP contract 和用户交互；
- 前端只渲染 Core 提供的合法动作；
- 不加载 C++ shared library、训练逻辑或 checkpoint；
- contract 不足时请求上游提供结构化字段；
- 不从文本标签反推业务规则。

### 4.6 Teacher Agent

知识点：

- 结构化 evidence、解释输出、隐私过滤和 Teacher API；
- 只能解释 Strategy 已经执行或暴露的动作；
- 不重算 legal action，不改变 `option_index`；
- 不泄露隐藏手牌和未公开候选动作；
- 缺少事实证据时交回 Core、Strategy 或 Product。

### 4.7 Test Agent

知识点：

- 从 Owner 最终 commit 或 snapshot 开始；
- 不读取 Owner 的实现过程；
- 验证功能、contract、文件范围和证据；
- 不修改生产代码；
- Docker 只在 TaskPacket 和 TestMatrix 声明时使用；
- 输出 TestReport 和 ReviewReport。

### 4.8 为什么不增加独立 Manager Agent

知识点：

- 主 Codex 已经承担编排职责；
- 额外 Manager 容易形成第二套路由和第二套规则；
- 领域事实应由最接近事实来源的 Agent 维护；
- 调度器只控制生命周期，不定义业务事实。

### 4.9 本章输出

读者应能针对一项修改，判断谁是 Owner、谁提供事实、谁负责验证，以及什么时候必须 handoff。

---

## 第 5 章：Skill、事实来源和责任边界

### 5.1 Skill 是什么

知识点：

- Skill 是可复用的工程知识和约束集合；
- Skill 不是一次性提示词；
- Skill 不等于工具，也不等于 Agent；
- Skill 规定触发条件、流程、不变量、验证和交接。

### 5.2 Skill 的六个组成部分

知识点：

- Trigger：什么时候使用；
- Workflow：按什么顺序处理；
- Invariant：不能破坏什么；
- References / scripts：事实和检查工具；
- Verification：必须提供哪些证据；
- Handoff：什么时候交给其他领域。

### 5.3 Agent 与 Skill 的关系

知识点：

```text
Agent：执行一次任务
Skill：约束如何正确执行
Contract：约束模块如何协作
Test Agent：独立判断结果是否满足要求
```

### 5.4 四个领域 Skill

知识点：

- Core Environment Skill：规则、动作、观察和 C ABI；
- Training Config Skill：训练配置、任务、resume 和模型检查；
- Product Integration Skill：React、FastAPI、HTTP contract 和 UX；
- Teacher Explanation Skill：证据、解释、隐私和 Teacher API。

### 5.5 事实来源的优先级

知识点：

- 当前 contract 高于旧文档和临时经验；
- 当前 TaskPacket 的范围高于泛化建议；
- 结构化事实高于模型猜测；
- 当前 snapshot 高于旧运行记录；
- 未知状态不能通过经验强行推断。

### 5.6 本章输出

读者应能解释：为什么 Skill 不是百科全书，以及重复规则应该放进 Skill、入口卡还是架构手册。

---

## 第 6 章：TaskPacket、ContextBrief 与上下文治理

### 6.1 为什么需要任务包

知识点：

- 明确唯一目标；
- 固定责任域和 Owner；
- 固定允许修改的文件范围；
- 固定验收条件、预算和测试矩阵；
- 固定 snapshot、revision 和证据要求。

### 6.2 TaskPacket 的核心字段

知识点：

- `task_id`、`task_revision`；
- `goal` 和 `acceptance_criteria`；
- `owner_role` 和 `verifier_role`；
- `allowed_paths` 和 `test_write_roots`；
- `base_snapshot`、`final_snapshot`；
- `budget`、`retry_policy` 和 `test_matrix`；
- `privacy`、`docker`、`integration` 和 `termination`。

### 6.3 ContextBrief 的作用

知识点：

- 把 TaskPacket 转换成执行者真正需要的上下文；
- 记录事实来源、假设、限制和最近回归；
- 记录实际装入的上下文；
- 记录明确排除的历史、模型和无关领域；
- 不把整个仓库和全部聊天记录装入任务。

### 6.4 上下文装配顺序

知识点：

```text
入口索引
→ 当前状态
→ 责任域任务卡
→ 对应 Skill
→ 相关 contract
→ 最近固定回归
→ TaskPacket / ContextBrief
→ 最小源码范围
```

### 6.5 上下文排除规则

知识点：

- 不默认读取历史试点全文；
- 不默认加载模型和 checkpoint；
- 不默认进入 Trainer/torch 检查；
- 不读取无关领域的 Skill；
- 不把候选经验当成权威规则；
- 不使用旧聊天记忆替代当前文档。

### 6.6 上下文一致性和状态漂移

知识点：

- 每个任务绑定 revision；
- 每份上下文绑定 snapshot；
- 状态文档中的当前数字必须有来源；
- 旧状态必须进入归档区；
- 冲突来源必须停止为 `HUMAN_REQUIRED`。

### 6.7 新 Agent 冷启动流程

知识点：

1. 找到 `AGENT_ONBOARDING_INDEX.md`；
2. 读取 `CONTEXT_INDEX.yaml` 的策略；
3. 读取 `START_HERE.md`；
4. 根据责任域读取入口卡；
5. 读取对应 Skill 和 contract；
6. 确认最小验证命令；
7. 再开始执行，不先全仓库扫描。

### 6.8 本章输出

读者应能为一次任务写出最小 TaskPacket 和 ContextBrief，并解释每一份上下文为什么被装入或排除。

---

## 第 7 章：Contract、Snapshot 与 Artifact

### 7.1 Schema 与 Contract 的区别

知识点：

- Schema 描述数据长什么样；
- Contract 描述模块如何协作；
- Schema 变化不一定等于业务语义变化；
- breaking change 必须明确版本和影响范围。

### 7.2 Contract 体系

知识点：

- Environment Contract；
- Action Contract；
- Observation Contract；
- Core HTTP Contract；
- Teacher Evidence Contract；
- Agent Loop Task / Handoff Contract；
- Test Matrix 和报告 Contract。

### 7.3 Contract 变更流程

知识点：

- 确定 authoritative owner；
- 判断是否 breaking；
- 更新唯一版本来源；
- 同步消费者和适配器；
- 运行针对性验证；
- 通过 handoff 交给受影响领域。

### 7.4 Snapshot 的作用

知识点：

- 绑定 Owner 的起始代码；
- 绑定 Owner 的最终提交；
- 绑定 Test Agent 的验证输入；
- 防止测试验证了另一份代码；
- 支持集成、回滚和事后审计。

### 7.5 Artifact 类型

知识点：

- `TaskPacket`：任务边界；
- `ContextBrief`：上下文边界；
- `ChangeReport`：Owner 交付内容；
- `TestReport`：独立验证结论；
- `ReviewReport`：验证审阅结果；
- `RunManifest`：一次运行的总证据；
- `IntegrationManifest`：隔离集成和回滚证据；
- `DecisionPacket`：运行时决策和 Teacher 所需证据。

### 7.6 证据链

知识点：

```text
任务范围
→ 修改快照
→ 变更报告
→ 独立测试
→ 测试报告
→ 集成记录
→ 运行清单
```

### 7.7 本章输出

读者应能说明一项结论由哪份 Artifact 支持，以及为什么没有 snapshot 绑定就不能认为验证有效。

---

## 第 8 章：Runner、Scheduler、恢复和预算

### 8.1 Runner 是什么

知识点：

- Runner 是一次 Agent 执行的运行载体；
- 负责创建、等待、恢复、关闭和记录运行；
- Runner 不决定领域业务；
- Runner 产生状态、日志、耗时和模型消耗证据。

### 8.2 Scheduler 是什么

知识点：

- Scheduler 串联任务生命周期；
- 默认 `max_concurrency=1`；
- 同一时刻只有一个写入 Owner；
- Scheduler 不定义领域事实；
- Scheduler 不能替代 Test Agent。

### 8.3 Codex Host Bridge

知识点：

- 将控制面任务连接到实际 Codex 执行进程；
- 维护 Runner 标识、进程信息和工作树；
- 支持 wait、close、lookup 和 rebind；
- 进程重启后恢复同一责任链；
- 当前能力和可选宿主适配必须以当前状态文档为准。

### 8.4 有界执行

知识点：

- 模型调用上限；
- 总 token 上限；
- 时间上限；
- Runner 恢复次数上限；
- Owner/Test 尝试次数上限；
- Docker 使用范围和 cleanup 要求。

### 8.5 恢复策略

知识点：

```text
PASS                  → COMPLETE
代码缺陷               → RETURN_TO_OWNER
偶发测试失败           → RETRY_TEST
Runner 丢失            → RESUME_SAME_RUNNER
Docker/环境失败        → HUMAN_REQUIRED
权限/外部依赖          → HUMAN_REQUIRED
协议失败               → STOP
预算或次数耗尽         → 停止并请求人工
```

### 8.6 诊断、恢复策略和学习门

知识点：

- 诊断负责根据可见证据分类失败；
- 恢复策略负责决定当前流程下一步；
- Retry Learning Gate 负责判断重试是否有新的学习增量；
- 三者是独立模块；
- Runner 恢复是同一责任链恢复，不等于产生新经验。

### 8.7 失败分类

知识点：

- 代码缺陷；
- 测试失败；
- flaky；
- contract 失败；
- 环境失败；
- Docker 失败；
- 权限失败；
- 外部依赖失败；
- 协议失败；
- 预算失败；
- 上下文或快照失败。

### 8.8 本章输出

读者应能判断一次失败是否可以自动恢复、是否消耗模型、是否需要人工，以及为什么不能无限重试。

---

## 第 9 章：Verification、证据和集成闸门

### 9.1 为什么 Owner 不能自我确认

知识点：

- Owner 了解自己的实现过程，容易忽略未覆盖问题；
- 独立 Test Agent 能减少确认偏差；
- Test Agent 从最终 snapshot 开始；
- 没有证据的“看起来正确”不能成为 PASS。

### 9.2 Test Agent 的输入

知识点：

- Owner 最终 snapshot；
- changed paths；
- 任务验收条件；
- contract 版本；
- TestMatrix；
- Docker allowlist；
- 报告和证据格式。

### 9.3 Test Agent 的验证范围

知识点：

- 功能行为；
- contract 一致性；
- 文件范围；
- 隐私边界；
- 测试命令和退出码；
- Docker health；
- 失败分类；
- cleanup；
- token、耗时和恢复次数。

### 9.4 测试环境等级

知识点：

- Docker 是 Product、Teacher 和 Agent Loop Python 测试的权威环境；
- 宿主机测试只能诊断环境差异；
- Docker 只有 TaskPacket 和 TestMatrix 声明需要时才启动；
- Docker 运行后必须有 health 和 cleanup 证据；
- 缺少环境证据不能伪造 PASS。

### 9.5 报告校验

知识点：

- 报告字段完整；
- 状态枚举合法；
- snapshot 与任务一致；
- changed paths 在允许范围内；
- 结果与证据相互一致；
- 失败必须分类；
- 缺失或互相矛盾时进入 `HUMAN_REQUIRED`。

### 9.6 集成闸门

知识点：

- 先验证 Owner 和 Test 证据；
- 再确认 contract、范围和预算；
- 在隔离分支或工作树中集成；
- 记录 IntegrationManifest；
- 集成失败时保留 rollback 证据；
- 父工作树直接修改仍是独立人工闸门。

### 9.7 本章输出

读者应能解释“测试通过”和“任务可以交付”的区别，并能列出一份合格 TestReport 必须包含的证据。

---

## 第 10 章：Retry Learning 与自进化

### 10.1 工程意义上的自进化

知识点：

- 自进化首先改进执行过程，而不是自由修改自身；
- 目标是减少重复弯路、缩短耗时、降低模型消耗；
- 经验必须来源于可审计的执行记录；
- 自进化不能绕过 contract、权限、预算和验证。

### 10.2 从失败到经验

知识点：

```text
执行记录
→ 诊断与失败分类
→ 弯路分析
→ DetourRecord
→ Retry Learning Gate
→ Candidate Lesson
→ 固定回归
→ 人工批准
→ 只读改进提案
```

### 10.3 重试学习门

知识点：

- 重试必须带失败签名；
- 必须说明 changed refs；
- 必须提供新的 preflight checks；
- 必须说明 fallback action；
- 必须说明前置条件是否改变；
- 同一失败且 delta 不变时进入 `STOP_NO_LEARNING`；
- 未确认的经验不能直接注入下一次上下文。

### 10.4 候选经验

知识点：

- 成功 fallback 只能生成 candidate-only Lesson；
- 候选经验记录来源、snapshot 和 detour_id；
- 候选经验不能覆盖当前 contract；
- 候选经验不能改变停止条件和允许路径；
- 没有回归证据就不能晋级。

### 10.5 经验检索和上下文注入

知识点：

- 只有与当前任务触发条件匹配的经验才可候选检索；
- 失败类型、工具、操作和目标范围必须可比对；
- 经验进入 ContextBrief 的 advisory 区域；
- 经验不能替代权威事实；
- 检索失败不能阻塞普通任务，但来源冲突必须停止。

### 10.6 E0--E6 晋级边界

知识点：

- E0：记录和规范化执行事实；
- E1：分析弯路和失败模式；
- E2：生成候选经验；
- E3：验证经验可复用性；
- E4：固定回归、基线、演化版本和反例；
- E5：人工批准后生成只读改进提案；
- E6：训练或更大范围变更前的准备检查；
- 晋级阶段不能自动替代人工批准。

### 10.7 自进化的禁止事项

知识点：

- 不自动修改生产代码；
- 不自动修改 Skill 和路由；
- 不自动替换模型；
- 不自动重训；
- 不把一次偶然成功当作通用规律；
- 不把零成本或零耗时当作已节省；
- 不在证据缺失时声称完成学习。

### 10.8 本章输出

读者应能解释：一次重试怎样转化为候选经验，以及为什么候选经验不能立即改变下一次任务。

---

## 第 11 章：一个完整任务案例

### 11.1 案例选择

建议使用低风险的 Product UI 或 API 任务，避免引入模型训练和复杂 Core 规则变化。

### 11.2 任务准备

知识点：

- 写出 Goal；
- 指定 Product Owner；
- 指定独立 Test Agent；
- 固定 allowed paths；
- 固定验收条件；
- 声明测试环境和 Docker 要求；
- 固定预算、超时和停止条件。

### 11.3 上下文装配

知识点：

- 读取 Product 入口卡；
- 读取 Product Skill；
- 读取相关 HTTP contract；
- 读取最近回归；
- 明确排除 Core 规则、Trainer 模型和历史试点。

### 11.4 Owner 阶段

知识点：

- 创建或绑定隔离工作树；
- 只修改允许文件；
- 执行最小自检；
- 生成 ChangeReport；
- 固定最终 snapshot。

### 11.5 Test 阶段

知识点：

- Test Agent 不查看 Owner 的过程；
- 从最终 snapshot 启动；
- 执行指定测试；
- 检查功能、contract、范围和证据；
- 生成 TestReport。

### 11.6 失败分支

知识点：

- 代码失败：返回 Owner；
- flaky：有限重测；
- Docker 失败：停止并请求人工；
- 相同失败无新 delta：停止；
- Runner 丢失：恢复同一个 Runner；
- 报告不完整：不能完成任务。

### 11.7 集成与关闭

知识点：

- 判断是否需要集成；
- 在隔离环境生成 IntegrationManifest；
- 必要时保留 rollback 证据；
- 生成 RunManifest；
- 记录终止原因、耗时、token 和恢复次数；
- 任务关闭后再进行弯路分析。

### 11.8 本章输出

读者应能从用户需求开始，完整讲述一次任务如何经过所有状态、Artifact 和安全闸门。

---

## 第 12 章：常见弯路、错误做法和改进经验

### 12.1 命令和环境弯路

知识点：

- 不使用不存在的 `python`，统一确认 `python3`；
- 不把宿主机 pytest 结果当作 Docker 权威结果；
- 不在 Docker 权限失败后盲目重复模型调用；
- 不在 Node、pytest 或依赖缺失时反复猜命令；
- 先执行环境预检，再启动正式任务。

### 12.2 入口和上下文弯路

知识点：

- 不从历史 Pilot 入口判断当前能力；
- 不重复读取多个互相冲突的启动文档；
- 不把当前状态、历史证据和未来计划混在一起；
- 不依赖旧聊天记忆；
- 不进行无范围的全仓库扫描。

### 12.3 Git 和工作树弯路

知识点：

- 修改前确认工作目录、分支和快照；
- 不在脏的 main 上自动提交；
- 不把隔离工作树当作 Windows 主目录；
- 不复制 `.git` 指针文件；
- 不在没有冲突策略时大范围覆盖 main；
- 同步前检查 staged、unstaged 和 untracked 文件。

### 12.4 重试弯路

知识点：

- “再试一次”不是诊断；
- 相同失败必须停止；
- 每次模型重试必须说明 learning delta；
- Runner 恢复与经验学习不能混淆；
- 环境失败不能通过增加模型预算解决。

### 12.5 证据弯路

知识点：

- 没有最终 snapshot 不能声称验证完成；
- 没有 Docker health 和 cleanup 不能声称服务测试 PASS；
- 报告字段不一致时不能人工推断为 PASS；
- 没有反事实基线不能声称节省了 token 或时间；
- 没有人工批准不能声称经验已晋级。

### 12.6 Lesson 的写法

知识点：

- 记录观察事实，不把推测写成根因；
- 给出触发条件；
- 给出失败签名；
- 给出成功替代路径；
- 给出适用范围和反例；
- 给出证据引用和可复现实验。

### 12.7 本章输出

读者应能把一次失败拆成：环境问题、流程问题、工具问题、上下文问题、代码问题或证据问题，并知道下一次如何避免重复。

---

## 第 13 章：架构权衡、当前状态和未来边界

### 13.1 为什么选择串行

知识点：

- 一个写入 Owner，降低冲突；
- 一个独立 Test，保证责任清晰；
- 上下文和快照更容易绑定；
- 恢复路径更容易审计；
- 不以并行数量换取不可控复杂度。

### 13.2 Multi-Agent 的收益

知识点：

- 责任域清晰；
- 事实来源单一；
- 上下文更小；
- contract 交接可追踪；
- Test Agent 可以独立验证。

### 13.3 Multi-Agent 的成本

知识点：

- 需要维护更多入口和 Skill；
- 跨边界任务需要 handoff；
- contract 变化需要同步；
- 上下文装配本身需要治理；
- 调度、恢复和证据记录增加工程成本。

### 13.4 自动化与人工控制的边界

知识点：

- 可以自动执行：有限调度、状态推进、报告校验、同 Runner 恢复和候选经验记录；
- 默认不能自动执行：冲突解决、父 main 合并、权限批准、生产部署、模型替换、正式训练和 Skill 晋级；
- 不确定性统一进入 `HUMAN_REQUIRED`。

### 13.5 当前已实现、部分验证和关闭能力

知识点：

- 已实现的控制面模块；
- 已通过自动回归的部分；
- 已有本地现场证据的部分；
- 仍依赖宿主适配或人工闸门的部分；
- 明确关闭的自动修复、自动训练和生产变更能力。

### 13.6 未来扩展边界

知识点：

- 更完整的独立宿主适配；
- 更稳定的跨进程 session lookup/rebind；
- 更丰富的诊断证据归一化；
- 更强的经验去重和反例验证；
- 更完整的集成和回滚状态表达；
- 所有扩展都必须保持串行、有界、可审计和 fail-closed。

### 13.7 本章输出

读者应能同时回答“这个架构为什么这样设计”和“它现在具体做到哪一步”，避免把设计目标误说成现场能力。

---

## 附录 A：文件索引

### A.1 Agent 配置

知识点：

- `.codex/agents/core.toml`；
- `.codex/agents/trainer.toml`；
- `.codex/agents/product.toml`；
- `.codex/agents/teacher.toml`；
- `.codex/agents/test-verification.toml`。

### A.2 Skill

知识点：

- `.agents/skills/core-environment/SKILL.md`；
- `.agents/skills/training-config/SKILL.md`；
- `.agents/skills/product-integration/SKILL.md`；
- `.agents/skills/teacher-explanation/SKILL.md`。

### A.3 Loop 核心实现

知识点：

- `scripts/agent_loop/state_machine.py`；
- `scripts/agent_loop/bounded_loop.py`；
- `scripts/agent_loop/scheduler.py`；
- `scripts/agent_loop/scheduler_backend.py`；
- `scripts/agent_loop/execution.py`；
- `scripts/agent_loop/recovery.py`；
- `scripts/agent_loop/retry_learning.py`；
- `scripts/agent_loop/verification.py`；
- `scripts/agent_loop/integration.py`；
- `scripts/agent_loop/manifest.py`。

### A.4 上下文和协议

知识点：

- `docs/current/AGENT_ONBOARDING_INDEX.md`；
- `docs/current/agent-loop/CONTEXT_INDEX.yaml`；
- `docs/current/agent-loop/START_HERE.md`；
- `docs/current/agent-loop/TASK_PACKET_TEMPLATE.yaml`；
- `docs/current/agent-loop/CONTEXT_BRIEF_TEMPLATE.yaml`；
- `docs/current/agent-loop/RECOVERY_POLICY.md`；
- `docs/current/agent-loop/EXPERIENCE_PROTOCOL.md`。

### A.5 证据和状态

知识点：

- `docs/current/agent-loop/CURRENT_STATE.md`；
- `docs/current/agent-loop/TEST_AGENT.md`；
- `docs/current/agent-loop/TEST_MATRIX.yaml`；
- `docs/current/agent-loop/RUN_MANIFEST_TEMPLATE.yaml`；
- `docs/current/agent-loop/INTEGRATION_MANIFEST_TEMPLATE.yaml`；
- `docs/current/agent-loop/SELF_EVOLUTION_PLAN.md`。

---

## 附录 B：命令索引

### B.1 架构门禁

```bash
python3 scripts/check.py architecture
```

### B.2 Agent Loop 回归

```bash
python3 scripts/agent_loop/check.py
```

### B.3 Docker 权威测试

```bash
python3 scripts/check.py docker-test
```

### B.4 领域验证

```bash
PYTHONPATH=. python3 -m pytest -q services/teacher/tests
PYTHONPATH=apps/web/backend python3 -m pytest -q apps/web/backend/tests
cd apps/web/frontend && npm ci && npm run build
```

### B.5 命令使用原则

知识点：

- 先确认任务范围，再选命令；
- 架构任务优先使用 architecture 门禁；
- 宿主 pytest 只用于诊断；
- Docker 测试才可作为声明范围内的权威证据；
- 命令、退出码和环境必须写入报告。

---

## 附录 C：术语表

### C.1 核心术语

知识点：

- Agent：执行任务的模型角色；
- Agent Loop：受控的任务生命周期；
- Skill：领域知识、流程和约束；
- Contract：模块之间的协作协议；
- Schema：结构化数据格式；
- Context：任务执行所需的上下文；
- Snapshot：可复现的代码状态；
- Artifact：任务过程中的结构化交付物；
- Verification：独立验证；
- Evidence：支持结论的可审计事实；
- Self-evolution：基于执行证据改进后续流程。

### C.2 恢复术语

知识点：

- `RETURN_TO_OWNER`：返回 Owner 修复；
- `RETRY_TEST`：重新执行测试；
- `RESUME_SAME_RUNNER`：恢复同一 Runner；
- `HUMAN_REQUIRED`：需要人工处理；
- `STOP_NO_LEARNING`：没有新学习，停止重试。

### C.3 经验术语

知识点：

- DetourRecord：执行弯路记录；
- Candidate Lesson：候选经验；
- learning delta：本次重试相对于上次的新变化；
- baseline：固定回归中的原始基线；
- evolved：应用候选改进后的版本；
- negative transfer：经验应用后对其他任务产生的负面影响。

---

## 附录 D：架构图清单

### D.1 总体架构图

应展示：

- 运行时平面；
- 控制平面；
- 经验治理平面；
- 三者之间的维护和证据关系。

### D.2 Agent Loop 生命周期图

应展示：

- 正常状态链；
- 诊断；
- 恢复策略；
- 重试学习门；
- 独立验证和完成条件。

### D.3 Agent 责任域图

应展示：

- 主 Codex 的编排位置；
- Core、Trainer、Product、Teacher 四选一；
- 独立 Test Agent；
- contract 和 handoff 边界。

### D.4 上下文装配图

应展示：

- 入口索引；
- 任务卡；
- Skill；
- contract；
- 最近回归；
- 装入和排除规则；
- snapshot 和 revision 绑定。

### D.5 Artifact 流转图

应展示：

```text
TaskPacket
→ ContextBrief
→ ChangeReport
→ TestReport
→ IntegrationManifest
→ RunManifest
→ PathAnalysis
→ Candidate Lesson
```

### D.6 自进化图

应展示：

- 执行记录；
- 弯路分析；
- 候选经验；
- 固定回归；
- 人工批准；
- 只读提案；
- 后续上下文的 advisory 注入。

---

## 附录 E：手册完成标准

手册正文完成前必须满足：

- 每章都有明确目标、子章节和知识点；
- 每个核心概念都能回指当前代码或权威文档；
- 不把历史状态写成当前能力；
- 不把设计目标写成现场验证结果；
- 状态机、恢复策略、学习门三个模块没有混写；
- 上下文装载和排除规则可以被新 Agent 执行；
- 至少包含一个从任务创建到关闭的完整案例；
- 至少包含一章历史弯路和改进经验；
- 架构图、文件索引和命令索引相互一致；
- 通过 `python3 scripts/check.py architecture`。
