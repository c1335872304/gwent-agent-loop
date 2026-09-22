# Agent Loop 模块手册

> 本手册解释项目中八个主要模块的职责、连接方式和实际代码入口。
> 它是学习和定位文档，不是第二份规则文件。
>
> 稳定规则以根目录 AGENTS.md、对应 Skill 和正式 contract 为准；当前能力和现场结论以
> CURRENT_STATE.md 与最终 snapshot 为准；一次任务的实际范围、预算和验证以 TaskPacket、
> TestMatrix、TestReport 和 RunManifest 为准。

## 0. 先记住这八个模块

    1. 任务与上下文管理
    2. 责任域路由与 Skill
    3. Agent Loop
    4. 调度器 Scheduler
    5. Runner 执行层
    6. 宿主桥接
    7. 独立测试与证据
    8. 自进化

最简单的记忆方式：

    上下文模块管“带什么信息”
    路由模块管“交给谁”
    Loop 管“按什么业务顺序走”
    调度器管“什么时候执行”
    Runner 管“这次执行由谁承载”
    宿主桥接管“怎么连接 Codex”
    测试模块管“如何证明完成”
    自进化模块管“下次如何少走弯路”

## 1. 本手册怎么读

### 1.1 只想执行一个任务

先读：

1. [AGENT_ONBOARDING_INDEX.md](../AGENT_ONBOARDING_INDEX.md)；
2. [START_HERE.md](START_HERE.md)；
3. 本手册第 2、3、4、5 章；
4. 对应领域任务卡、Skill、contract 和最近回归。

### 1.2 想理解整个系统

    第 2 章 任务与上下文
      → 第 3 章 路由与 Skill
      → 第 4 章 Agent Loop
      → 第 5 章 调度器
      → 第 6 章 Runner 与宿主桥接
      → 第 7 章 测试与证据
      → 第 8 章 自进化

### 1.3 文档职责不能混淆

| 文档或模块 | 唯一职责 | 不负责什么 |
|---|---|---|
| AGENTS.md | 仓库级硬规则 | 不记录单次任务结果 |
| Skill | 专业 Agent 的工作方式和不变量 | 不保存运行状态 |
| TaskPacket / ContextBrief | 一次任务的范围和最小上下文 | 不代替领域 contract |
| Agent Loop | 业务阶段和交接顺序 | 不直接定义领域事实 |
| Scheduler | Runner 的生命周期和预算 | 不写业务代码、不代替测试 |
| Runner | 承载一次 Agent 执行 | 不决定任务目标 |
| Test Agent | 独立验证结果 | 不修改生产代码 |
| 自进化 | 分析弯路、形成候选经验 | 不未经验证改变规则 |
| 本手册 | 解释模块关系和使用方式 | 不复制所有权威规则 |

## 2. 总体架构

### 2.1 任务主线

    用户需求
      ↓
    TaskPacket
      ↓
    ContextBrief
      ↓
    责任域路由
      ↓
    一个领域 Owner
      ↓
    ChangeReport + 最终 snapshot
      ↓
    独立 Test Agent
      ↓
    TestReport
      ↓
    RunManifest
      ↓
    弯路分析与候选经验

### 2.2 八模块关系

    用户需求
        ↓
    任务与上下文管理
        ↓
    责任域路由与 Skill
        ↓
    Agent Loop
        ├── 一个领域 Owner
        │       ↓
        │   ChangeReport + 最终 snapshot
        │       ↓
        ├── 调度器 Scheduler
        │       ↓
        │   Runner 执行层
        │       ↓
        │   宿主桥接
        │       ↓
        │   Codex 宿主
        │
        ├── 独立 Test Agent
        │       ↓
        │   TestReport
        │       ↓
        │   RunManifest
        │
        └── 失败诊断 → 恢复策略 → 自进化
                                      ↓
                                候选经验
                                      ↓
                                后续上下文

### 2.3 三个平面

#### 控制平面

控制平面管理：

    任务身份
    上下文范围
    责任域
    状态
    预算
    Runner 引用
    恢复决策
    证据工件

它不执行 Gwent 对局，也不代替领域 Agent 定义游戏规则。

#### 运行时平面

运行时平面包括：

    Core 规则环境
    策略和训练运行时
    Web 前后端
    Teacher 运行时

它提供被修改或被验证的工程对象。

#### 经验治理平面

经验治理平面分析：

    执行事件
    失败签名
    重复尝试
    绕路记录
    候选 Lesson
    回归结果
    晋级决定

## 3. 模块一：任务与上下文管理

### 3.1 它解决什么问题

它解决的是：

> Agent 到底应该知道什么？

没有上下文管理时，新对话可能：

- 读取过时的历史文档；
- 从错误入口开始；
- 扫描整个仓库；
- 把别的领域规则带进当前任务；
- 不知道允许修改哪些文件；
- 不知道自己对应哪个 snapshot。

### 3.2 TaskPacket 是什么

TaskPacket 是一次任务的正式任务单，至少说明：

    task_id              任务唯一编号
    revision             任务版本
    owner                责任域 Owner
    requested_outcome    期望结果
    base_snapshot        代码起点
    allowed_write_paths  允许写入范围
    budget               token、回合、时间等上限
    verification         验收和测试要求

它回答：

> 这次任务要做什么、能改什么、从哪里开始、做到什么才算完成？

### 3.3 ContextBrief 是什么

ContextBrief 是给 Agent 的最小事实包，通常包含：

    fact_source_graph    事实来源图
    facts                已确认事实
    assumptions          当前假设
    unknowns             未知项
    included_context     实际装入的上下文
    excluded_context     明确排除的上下文
    lesson_refs          本任务相关经验

它回答：

> 为了完成这次任务，Agent 现在必须知道哪些信息？

### 3.4 上下文装配流程

    用户需求
      ↓
    确定任务类型和责任域
      ↓
    读取入口索引
      ↓
    读取对应任务卡和 Skill
      ↓
    读取 contract、相关实现和最近回归
      ↓
    排除历史、无关领域和冻结模型
      ↓
    生成 ContextBrief

### 3.5 当前项目的文件入口

- [CONTEXT_INDEX.yaml](CONTEXT_INDEX.yaml)：机器可检查的上下文策略；
- [TASK_PACKET_TEMPLATE.yaml](TASK_PACKET_TEMPLATE.yaml)：任务单模板；
- [CONTEXT_BRIEF_TEMPLATE.yaml](CONTEXT_BRIEF_TEMPLATE.yaml)：上下文模板；
- scripts/agent_loop/validate_packet.py：任务和上下文校验；
- scripts/agent_loop/launch.py：受限启动封装。

### 3.6 不属于它的事情

上下文模块不能：

    替 Owner 修改代码
    代替 contract 定义事实
    把历史报告当作当前状态
    自动扩大 allowed_write_paths
    因为未知就猜测结论

出现权威来源冲突、snapshot 不明确、隐私边界不明确或预算不明确时，应停止为
HUMAN_REQUIRED。

### 3.7 小例子

用户说：

> 修改网页上的教师提示卡，只允许修改前端展示。

上下文模块应装配：

    Product 任务卡
    Product Skill
    Core HTTP contract
    TeacherPanel 相关实现
    前端相关测试
    允许写入的前端路径

不应默认装配：

    Core C++ 全部代码
    Trainer checkpoint
    历史 Pilot 报告
    全仓库所有测试
    冻结模型文件

## 4. 模块二：责任域路由与 Skill

### 4.1 它解决什么问题

它解决的是：

> 这个任务应该由哪个专业 Agent 负责？

路由不是按文件语言机械判断，而是按事实来源判断。

### 4.2 四个领域 Owner

| Owner | 主要事实 |
|---|---|
| Core | 卡牌规则、合法动作、状态和环境 contract |
| Trainer | PPO、collector、reward、训练任务和模型来源 |
| Product | React、FastAPI BFF、Core HTTP 和交互 |
| Teacher | evidence、解释、隐私和 Teacher 接口 |

Test / Verification Agent 是验证角色，不是上述四个领域之一。

### 4.3 常见路由例子

    新增卡牌效果            → Core
    修改 action grammar     → Core
    修改 PPO reward         → Trainer
    修改训练任务配置         → Trainer
    修改 React 页面          → Product
    修改 FastAPI BFF         → Product
    修改教师解释证据         → Teacher
    修改隐藏信息过滤         → Teacher
    验证 Owner 最终提交       → Test / Verification

### 4.4 Skill 的作用

Skill 是专业 Agent 的可复用工作协议，包含：

    Trigger       什么时候使用
    Workflow      按什么顺序处理
    Invariant     什么绝不能破坏
    References    事实来源和脚本
    Verification  交付前给出什么证据
    Handoff       什么时候交给其他领域

Skill 不是项目百科，也不是一次任务的临时提示词。

### 4.5 交接规则

跨域变化必须带着：

    TaskPacket
    ContextBrief
    ChangeReport
    最终 snapshot
    contract 差异

下一个 Agent 只接收声明的结构化工件，不读取前一个 Agent 的完整对话过程。

### 4.6 当前项目的文件入口

- [agent-entry/README.md](../agent-entry/README.md)：领域任务卡总入口；
- [agent-entry/CORE.md](../agent-entry/CORE.md)；
- [agent-entry/TRAINER.md](../agent-entry/TRAINER.md)；
- [agent-entry/PRODUCT.md](../agent-entry/PRODUCT.md)；
- [agent-entry/TEACHER.md](../agent-entry/TEACHER.md)；
- .agents/skills/：四个可复用 Skill。

## 5. 模块三：Agent Loop

### 5.1 它是什么

Agent Loop 是任务的业务流程控制器。它规定一个任务从收到需求到完成验证，必须经过哪些阶段。

它关心的是：

    先做什么
    后做什么
    谁完成后才能交给谁
    什么时候必须停止
    哪些结果可以进入下一阶段

### 5.2 正常生命周期

    RECEIVED
      ↓
    TRIAGED
      ↓
    CONTEXTUALIZED
      ↓
    PLANNED
      ↓
    ASSIGNED
      ↓
    IMPLEMENTING
      ↓
    REVIEWING
      ↓
    TESTING
      ↓
    COMPLETED

### 5.3 状态含义

| 状态 | 含义 |
|---|---|
| RECEIVED | 已收到用户目标 |
| TRIAGED | 已确定责任域、风险和任务类型 |
| CONTEXTUALIZED | 已装配最小必要上下文 |
| PLANNED | 已确定范围、预算和验证方式 |
| ASSIGNED | 已确定一个领域 Owner |
| IMPLEMENTING | Owner 正在修改 |
| REVIEWING | Owner 正在自检并生成报告 |
| TESTING | 独立 Test Agent 正在验证 |
| COMPLETED | 结果和证据全部满足要求 |
| HUMAN_REQUIRED | 存在不能安全自动判断的问题 |
| STOP_NO_LEARNING | 重试没有新的学习增量 |

### 5.4 Owner → Test 串行闭环

    Owner 修改
      ↓
    ChangeReport
      ↓
    固定最终 snapshot
      ↓
    生成 Handoff
      ↓
    建立 VerificationPlan
      ↓
    Test Agent 从最终 snapshot 开始
      ↓
    TestReport

Test Agent 不看 Owner 的实现过程，只看最终结果和规定的证据。

### 5.5 主要代码入口

- scripts/agent_loop/bounded_loop.py：单领域 Owner → 独立 Test 的串行闭环；
- scripts/agent_loop/handoff.py：交接工件；
- scripts/agent_loop/verification.py：验证计划；
- scripts/agent_loop/recovery.py：失败后的恢复决策。

### 5.6 它不负责什么

Agent Loop 不负责：

    定义 Core 游戏规则
    直接执行 Codex 宿主调用
    代替 Scheduler 统计 Runner 生命周期
    代替 Test Agent 给出独立证据
    未经验证把 Lesson 变成正式规则

## 6. 模块四：调度器 Scheduler

### 6.1 它是什么

调度器是执行层的控制器，不是业务 Manager Agent。

它回答：

> 当前这个任务什么时候可以启动、暂停、恢复或结束？

### 6.2 当前项目的串行配置

项目的受限运行模式使用：

    max_concurrency = 1

这表示同一时间最多有一个 Runner 执行。

调度器内部可以保留等待中的任务，但这不是业务并行。真实业务流程仍然是：

    前一个阶段完成
      ↓
    生成后一个阶段
      ↓
    后一个阶段启动

### 6.3 调度器的主要动作

    submit()   接收并登记一个 TaskPacket
    pump()     检查进度、预算和是否可以启动
    pause()    暂停当前 Runner
    resume()   恢复当前 Runner
    restore()  从快照恢复调度器
    end()      结束任务并记录原因

### 6.4 pump() 做什么

每次调用 pump()，调度器会：

1. 检查自己是否已停止；
2. 检查是否进入 HUMAN_REQUIRED；
3. 检查总时间预算；
4. 轮询正在运行的任务；
5. 累计 token、模型回合和耗时；
6. 在有空闲执行槽且预算足够时启动任务；
7. 保存最新快照。

它是非阻塞的，主控制流程可以周期性调用它。

### 6.5 暂停和恢复

    running
      ↓ pause()
    paused
      ↓ resume()
    running

恢复的是原来的任务身份和原来的 Runner，不是复制一个新任务。

### 6.6 进程重启

    调度器进程停止
      ↓
    读取 Scheduler 快照
      ↓
    读取 task_id、revision、runner_ref
      ↓
    调用后端 rebind 原 Runner
      ↓
    成功：继续原任务
    失败：HUMAN_REQUIRED

restore() 不应该直接调用 start()，否则可能重复创建模型任务。

### 6.7 调度器的边界

调度器不负责：

    判断代码是否正确
    决定 Core / Product 的专业规则
    自动修复失败代码
    修改 contract
    替代 Test Agent
    判断 Lesson 是否应该晋级

### 6.8 当前项目的文件入口

- scripts/agent_loop/scheduler.py：任务状态、队列、预算和快照；
- scripts/agent_loop/scheduler_backend.py：调度器与 Runner 的连接；
- scripts/agent_loop/run_scheduler_canary.py：串行调度行为回归；
- scripts/agent_loop/run_stage3_live.py：现场流程中的调度接入示例。

### 6.9 当前实现的准确边界

当前代码中，Product 和 Teacher 在现场流程中通过 Scheduler 管理；Test 的串行验证由
主流程或 SingleDomainLoop 负责。在解释架构时，不应说 Scheduler 单独完成全部 Owner → Test
业务闭环。

## 7. 模块五：Runner 执行层

### 7.1 它是什么

Runner 是一次具体 Agent 执行的承载对象。

    Product Agent 这一种角色
      ↓ 一次实际执行
    Product Runner R-001

因此：

    Agent = 谁负责
    Runner = 这次执行由谁承载

### 7.2 Runner 的生命周期

    open()
      ↓
    running
      ↓
    wait()
      ↓
    interrupted / lost / closed
      ↓
    resume() 或 close()

### 7.3 RunnerRequest

启动 Runner 时必须绑定：

    task_id
    task_revision
    attempt_id
    role
    profile_revision
    snapshot
    write_scope
    max_turns

这样恢复时可以确认“这是同一个任务”，而不是相似任务。

### 7.4 RunnerEvent

Runner 返回统一事件，包含：

    runner_ref
    event
    status
    task_id
    task_revision
    attempt_id
    snapshot
    resume_count
    report_ref
    final_snapshot
    changed_paths
    input_tokens
    output_tokens
    elapsed_seconds

### 7.5 RunnerExecution 的作用

RunnerExecution 是 Runner 的安全包装层，负责：

    身份校验
    snapshot 校验
    write_scope 校验
    预算预留和释放
    执行日志
    恢复次数限制
    失败和 retry learning 记录

### 7.6 恢复与重试的区别

    恢复原 Runner：继续同一个任务
    重试新 attempt：重新执行一次新的尝试

恢复通常保留同一个 runner_ref；新的 attempt 应有新的身份和新的证据，不能覆盖旧记录。

### 7.7 当前项目的文件入口

- scripts/agent_loop/runner.py：Runner 生命周期协议；
- scripts/agent_loop/execution.py：身份、预算、日志和恢复保护；
- scripts/agent_loop/scheduler_backend.py：把 Runner 接入 Scheduler。

### 7.8 它不是什么

Runner 不是：

    一个新的专业 Agent
    一个 Manager Agent
    调度器
    自进化引擎
    自动修复器

它只是一次执行的可追踪载体。

## 8. 模块六：宿主桥接

### 8.1 它是什么

宿主桥接把项目内部的 Runner 调用转换成 Codex 宿主可以执行的调用。

    项目内部接口
      ↓
    ExternalRunnerAdapter
      ↓
    CodexHostTransport
      ↓
    Codex CLI 或其他宿主

### 8.2 基本操作

    open()    创建一次宿主任务
    wait()    查询任务进度
    rebind()  连接已经存在的任务
    resume()  恢复任务
    close()   关闭任务并保存报告

### 8.3 为什么要单独分层

分层后可以替换宿主，而不改业务控制逻辑：

    本地 Codex CLI
    测试替身
    其他执行服务
    未来的 Desktop/MCP 适配

调度器只依赖统一后端接口，不依赖某个宿主的具体通信方式。

### 8.4 恢复时的责任分工

    调度器：决定是否应该恢复
    宿主桥接：尝试找到原 runner_ref
    Runner 后端：检查返回身份
    调度器：根据结果继续或 HUMAN_REQUIRED

因此“有快照”不等于“必然能恢复”。还必须找到原 Runner，并确认 task_id、revision、snapshot
和 write_scope 一致。

### 8.5 宿主失败分类

至少要区分：

    任务不存在
    连接失败
    宿主拒绝
    身份不匹配
    Runner 超时
    权限不足
    返回格式错误

不能因为一次连接失败就无条件重新创建任务。

### 8.6 当前项目的文件入口

- scripts/agent_loop/external.py：外部 Runner 适配；
- scripts/agent_loop/codex_host_transport.py：宿主传输协议；
- scripts/agent_loop/codex_cli_bridge.py：本地 Codex CLI 桥接。

## 9. 模块七：独立测试与证据

### 9.1 为什么必须独立测试

Owner 的目标是完成修改，Test Agent 的目标是判断修改是否真的满足要求。两者职责不同。

Test Agent 不读取 Owner 的完整实现过程，只读取：

    最终 snapshot
    TaskPacket
    ContextBrief
    ChangeReport
    VerificationPlan

### 9.2 验证内容

    功能是否满足
    contract 是否一致
    changed paths 是否在范围内
    隐私是否满足
    测试命令是否真实执行
    退出码是否真实存在
    Docker health 是否通过
    失败分类是否准确
    cleanup 是否完成
    报告是否完整

### 9.3 验证流程

    Owner 完成
      ↓
    锁定最终 snapshot
      ↓
    构造 Handoff
      ↓
    生成 VerificationPlan
      ↓
    Test Agent 独立启动
      ↓
    执行允许的验证命令
      ↓
    生成 TestReport
      ↓
    严格校验 TestReport
      ↓
    生成 RunManifest

### 9.4 PASS 不是一句话

下面这些不能单独证明 PASS：

    Owner 说“我改好了”
    本地手工看起来正常
    Test Agent 说“应该没问题”
    命令没有退出码
    主机依赖和容器依赖不一致
    报告缺少 final snapshot

PASS 必须绑定可复现的命令、退出码、范围、snapshot 和证据。

### 9.5 Docker 的位置

Docker 不是默认动作。只有 TaskPacket 和 TestMatrix 明确声明服务依赖时，才启动 Docker，并记录：

    镜像或 Compose 文件
    服务启动结果
    health 检查
    测试命令
    日志位置
    cleanup 结果

主机上的 pytest 只能作为诊断；当项目规定容器为最终环境时，主机结果不能冒充最终 PASS。

### 9.6 当前项目的文件入口

- [TEST_AGENT.md](TEST_AGENT.md)：Test Agent 协议；
- [TEST_MATRIX.yaml](TEST_MATRIX.yaml)：允许的验证矩阵；
- scripts/agent_loop/verification.py：验证计划；
- scripts/agent_loop/report_validation.py：报告校验；
- scripts/agent_loop/bounded_loop.py：Owner → Test 闭环。

## 10. 模块八：自进化

### 10.1 它是什么

自进化不是“让模型无限尝试”，而是把执行经验变成经过验证的候选知识。

它回答：

> 这次为什么走弯路？下一次怎样避免重复走？

### 10.2 自进化输入

    Scheduler 事件
    Runner 事件
    ChangeReport
    TestReport
    失败分类
    重试记录
    token 和耗时

### 10.3 自进化流程

    执行失败
      ↓
    诊断失败原因
      ↓
    形成失败签名
      ↓
    记录 DetourRecord
      ↓
    提出 RetryLearningDelta
      ↓
    有限重试
      ↓
    成功后生成 Candidate Lesson
      ↓
    固定回归验证
      ↓
    人工批准或晋级

### 10.4 Retry Learning Gate

一次重试必须说明：

    failure_signature   上次失败的结构化签名
    changed             这次改变了什么
    preconditions       前置条件是什么
    new_action          这次采用的替代动作
    expected_effect     预期解决什么
    evidence            依据是什么

如果失败签名相同、前置条件没变、learning delta 没变，就不能继续消耗模型：

    STOP_NO_LEARNING

### 10.5 候选经验不是正式规则

成功一次只能得到：

    Candidate Lesson

它还不能自动覆盖当前 Skill 或 contract。只有经过独立回归、来源核对和规定的晋级闸门后，才可以进入后续任务上下文。

### 10.6 自进化的安全边界

自进化不能：

    覆盖用户目标
    覆盖当前 contract
    绕过权限检查
    把偶然成功当成普遍规律
    自动修改生产规则
    自动替换冻结模型

### 10.7 当前项目的文件入口

- scripts/agent_loop/retry_learning.py：重试学习门；
- scripts/agent_loop/recovery.py：恢复策略；
- [EXPERIENCE_PROTOCOL.md](EXPERIENCE_PROTOCOL.md)：经验协议；
- [LESSONS_LEARNED.md](LESSONS_LEARNED.md)：已记录经验；
- [SELF_EVOLUTION_PLAN.md](SELF_EVOLUTION_PLAN.md)：自进化阶段计划。

## 11. 一个完整的项目例子

任务：

> 修改 apps/web 的教师提示卡，只允许修改前端展示，并确认没有泄露隐藏信息。

### 11.1 创建任务

    task_id: GW-PRODUCT-001
    owner: product
    allowed_write_paths: apps/web/frontend/...
    base_snapshot: 某个 Git 提交
    verification: 前端构建 + Teacher 隐私检查

### 11.2 装配上下文

    Product 任务卡
    Product Skill
    Core HTTP contract
    TeacherPanel 相关代码
    Teacher 隐私 contract
    前端验证命令

### 11.3 启动 Owner

    Agent Loop：进入 ASSIGNED
    调度器：submit TaskPacket
    调度器：pump
    Runner：open
    Product Agent：进入 IMPLEMENTING

### 11.4 Owner 交付

Product Agent 输出：

    ChangeReport
    changed_paths
    最终 snapshot
    已运行的自检
    未解决问题

如果修改超出前端范围，不能继续进入测试，必须退回或进入 HUMAN_REQUIRED。

### 11.5 独立验证

    固定 Product 最终 snapshot
      ↓
    Test Agent 只读取最终结果
      ↓
    检查文件范围和 contract
      ↓
    运行前端构建
      ↓
    检查 Teacher 隐私边界
      ↓
    生成 TestReport

### 11.6 收口

只有以下内容齐全，才可以生成完成结论：

    ChangeReport
    TestReport
    最终 snapshot
    实际命令和退出码
    changed paths
    预算使用
    失败分类
    RunManifest

如果需要修改父工作树或合并到 main，还需要额外的 IntegrationManifest 和集成闸门。

## 12. 失败和恢复速查

| 现象 | 先查什么 | 正确出口 |
|---|---|---|
| 代码测试失败 | TestReport、失败命令和 changed paths | 诊断后 RETURN_TO_OWNER |
| 测试偶发失败 | 是否为 flaky，是否有新证据 | 有界 RETRY_TEST |
| Runner 进程丢失 | 快照、runner_ref、宿主注册表 | 成功则 RESUME_SAME_RUNNER |
| 找不到原 Runner | Host lookup/rebind 结果 | HUMAN_REQUIRED |
| Docker 无权限 | Docker 预检和权限证据 | PERMISSION_REQUIRED 或 HUMAN_REQUIRED |
| Python 依赖缺失 | 预检命令和环境 | ENVIRONMENT_FAILURE |
| contract 有冲突 | 权威来源和 revision | HUMAN_REQUIRED |
| 相同失败再次出现 | failure_signature 和 learning delta | STOP_NO_LEARNING |
| snapshot 发生漂移 | TaskPacket、Runner 和 Git 状态 | 停止，不继续执行 |
| Owner 修改越界 | ChangeReport 和 Git diff | 退回 Owner 或人工处理 |

## 13. 状态、调度器和 Runner 不要混淆

项目中有三组不同的状态。

### 13.1 Agent Loop 状态

表示业务任务进行到了哪一步：

    RECEIVED → TRIAGED → CONTEXTUALIZED → PLANNED → ASSIGNED
    → IMPLEMENTING → REVIEWING → TESTING → COMPLETED

### 13.2 调度器任务状态

表示调度器如何管理任务：

    queued
    running
    paused
    completed
    failed
    blocked
    human_required
    cancelled

### 13.3 Runner 状态

表示实际执行载体是否正常：

    running
    interrupted
    lost
    blocked
    closed

例如：

    Agent Loop：TESTING
    调度器：running
    Runner：running

这表示 Owner 已完成，Test Agent 正在通过 Runner 执行验证。

## 14. 新对话冷启动清单

新 Agent 不依赖聊天历史，按以下顺序开始：

    [ ] 读取 AGENTS.md
    [ ] 读取 AGENT_ONBOARDING_INDEX.md
    [ ] 读取 CONTEXT_INDEX.yaml 的 context_policy
    [ ] 读取 START_HERE.md
    [ ] 读取 CURRENT_STATE.md
    [ ] 确定责任域
    [ ] 读取对应任务卡和 Skill
    [ ] 读取相关 contract
    [ ] 创建或读取 TaskPacket
    [ ] 创建 ContextBrief
    [ ] 确认 base snapshot
    [ ] 确认 allowed_write_paths
    [ ] 确认验证命令和 Docker 需求
    [ ] 确认预算和停止条件
    [ ] 再开始执行

### 14.1 如果是恢复任务

额外检查：

    [ ] 找到 Scheduler 快照
    [ ] 找到 task_id 和 revision
    [ ] 找到 runner_ref
    [ ] 确认原 Runner 是否存在
    [ ] 确认宿主支持 rebind
    [ ] 确认 snapshot 没有漂移
    [ ] 确认预算和恢复次数仍然足够

## 15. 验证索引

验证命令必须由具体 TaskPacket、TestMatrix 和对应 Skill 决定。架构或 Loop 文档任务通常优先使用：

    python3 scripts/check.py architecture

Product、Teacher 和 Agent Loop 的 Python 测试，在声明服务依赖时使用：

    python3 scripts/check.py docker-test

主机测试可以帮助诊断依赖，但不能在规定容器为最终环境时替代容器证据。

所有最终结论都要记录：

    实际命令
    工作目录
    退出码
    snapshot
    测试结果
    失败分类
    证据路径

## 16. 最后的边界总结

    任务与上下文管理：准备最小必要信息
    责任域路由与 Skill：找到正确 Owner
    Agent Loop：推进业务阶段和交接
    调度器：控制 Runner 的时间和生命周期
    Runner：承载一次具体执行
    宿主桥接：连接真实 Codex 环境
    独立测试与证据：证明结果确实满足要求
    自进化：把经过验证的避坑经验带到未来任务

最终要记住：
> 上下文决定 Agent 看到什么，Loop 决定任务先做什么，调度器决定执行何时发生，Runner 承载一次执行，Test Agent 证明结果，自进化减少下一次重复犯错。
