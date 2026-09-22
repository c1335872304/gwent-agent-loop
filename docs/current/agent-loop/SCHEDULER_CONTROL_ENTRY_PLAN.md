# 调度器控制入口实施计划

> **状态：阶段一、阶段二均已完成。真实 WSL 服务已启动，主控用户级 MCP 已注册，
> `GW-SCHED-CTRL-001` 已完成 Owner → pause → inspect → ResumeDirective → same-Runner
> resume → 独立 Test → RunManifest 闭环；阶段三仍为可选宿主升级。**
>
> 本文只规划“用户 / 主控如何安全操控已持久化的串行 Agent Loop”。它不改变
> 当前的领域路由、Skill、测试独立性、预算、恢复策略或自进化晋级规则。
> 当前真实能力仍以 [`CURRENT_STATE.md`](CURRENT_STATE.md) 为准。

## 1. 要解决的问题

现有控制面能够持久化 Scheduler、Runner 和 CLI Host session，也已经验证过
独立进程 `rebind`。但它没有一个长期运行、可由用户或新的主控对话调用的控制入口。
因此，下列用户意图尚不能可靠地映射为实际动作：

```text
“暂停 TASK-017”
“先检查原子任务是否还在运行”
“我补充了这个约束，按原任务继续”
“终止这次 Loop，不要再启动 Test”
```

目标不是让 Codex 自行决定流程，也不是截获 ChatGPT Desktop App 的原生“终止”按钮；
目标是建立一个**明确、持久、审计化的控制入口**，让主控只能通过受限动作操控原有
Scheduler。

## 2. 重要边界

### 2.1 不把 App 的停止按钮当作已存在的接口

目前没有证据表明 Desktop App 会把当前聊天的“终止”事件公开为可供本仓库订阅的
Scheduler 控制信号。因此 V1 不承诺：

```text
App 终止按钮 -> 自动暂停指定 Runner
```

App 中止主控对话后，子 CLI 任务可能仍在运行。重新进入同一或新的主控对话时，
主控必须先查询持久化状态，不能仅凭聊天记忆新建任务。

### 2.2 不让执行者控制自己

Owner / Test Codex 只能报告状态、产物和阻塞原因；它们不能直接调用 `pause`、
`resume`、`cancel`，不能扩大预算，也不能跳过独立 Test。控制入口仅面向：

- 明确授权的用户操作；
- 作为控制面入口的主控 Codex；
- Scheduler 自身的预算、协议或恢复判定。

### 2.3 不替换已验证的 CLI Host

V1 保留 `CodexCliBridge`，因为它已验证隔离 worktree、持久化 registry 和 rebind。
Codex SDK / App Server 是可选的第二个 Host Bridge canary，不是本计划的前置条件。
它只能替换宿主接入层，不能替换 TaskPacket、ContextBrief、Scheduler、Runner、
TestReport 或 RunManifest。

## 3. 目标体验

### 3.1 正常串行运行

```text
用户目标
  -> 主控创建不可变 TaskPacket / ContextBrief
  -> 控制入口 submit
  -> Scheduler 启动 Owner
  -> Owner 结束后由既有 Loop 进入独立 Test
  -> RunManifest / TestReport / 关闭
```

### 3.2 主控中断后补充信息

```text
主控对话中断
  -> 原 Runner 可能仍在运行
  -> 用户补充信息
  -> 新主控先执行 inspect(task_id)
  -> 读取 Scheduler 快照、runner_ref、状态和最后事件
  -> 分类补充信息
       ├─ 不影响目标/范围：生成 ResumeDirective artifact
       ├─ 改变目标、范围、contract 或验收：创建新 TaskPacket revision
       └─ 无法判断：HUMAN_REQUIRED
  -> pause / rebind / resume 原任务，或有依据地 supersede 原任务
```

**绝不允许**先启动一个新的 Owner 再去猜原任务是否存在。

### 3.3 用户主动停止

```text
用户明确请求暂停 / 取消
  -> 控制入口校验 task_id、revision、权限和当前状态
  -> Scheduler.pause() 或 Scheduler.cancel()
  -> Host Bridge interrupt / cleanup
  -> 追加 Scheduler 事件和 RunManifest 原因
  -> 返回可读状态
```

暂停是可恢复的中断；取消是不可自动恢复的终止。二者都必须提供原因和幂等键。

## 4. 目标架构

```text
用户或主控 Codex
       |
       | 显式动作：inspect / pause / cancel / prepare_resume / resume
       v
本地控制入口（CLI，后续可选 MCP 工具）
       |
       | 本地认证、幂等、revision / runner_ref 校验、审计
       v
长期运行的 Scheduler 服务
       |
       v
RunnerExecution -> CodexHostTransport -> CodexCliBridge -> Codex CLI -> Codex
       |
       v
.agent-loop/：Scheduler 快照、ExecutionJournal、Host registry、工件
```

控制入口只提交**命令**；Scheduler 仍是唯一的状态写入者。所有响应均来自持久化
事件和 Host 查询，不能从主控自然语言推断“应该已经完成”。

## 5. 需要新增的组件

| 组件 | 职责 | 不负责什么 |
|---|---|---|
| `ControlRequest` / `ControlResponse` | 定义受限动作、身份、期望 revision、原因、幂等键和返回状态 | 不承载完整聊天记录或业务需求 |
| Scheduler 服务进程 | 加载/恢复 Scheduler，周期性 `pump()`，独占写入状态 | 不解析用户自然语言、不定义领域事实 |
| 本地控制 API | 把经验证的命令交给 Scheduler 服务 | 不直连 CLI 子进程绕过 Scheduler |
| 人工 CLI 客户端 | 让用户先以可见命令查询、暂停、取消和恢复 | 不替代 App UI |
| ResumeDirective | 保存“补充信息如何影响原任务”的最小 artifact | 不修改原 TaskPacket 历史 |
| 可选 MCP 工具 | 让主控 Codex 调用同一控制 API | 不让 Owner/Test 自行调度 |
| 可选 SDK Host Bridge | 以官方 SDK/App Server 实现同一 `CodexHostBridge` 协议 | 不改变控制面协议 |

建议的 V1 本地接口仅使用 Unix domain socket（WSL）；Windows 原生支持放入后续平台
适配。禁止默认监听公网 TCP；若需要 TCP，必须是 loopback、随机能力令牌和明确
生命周期。

## 6. 控制协议

### 6.1 最小动作集

| 动作 | 前置条件 | 效果 | 幂等行为 |
|---|---|---|---|
| `inspect` | `task_id` | 返回持久化状态、最后事件、runner_ref 是否可 rebind | 纯读取 |
| `submit` | 新 TaskPacket 已验证 | 登记任务；不绕过 admission gate | 相同 idempotency key 只登记一次 |
| `pause` | `running`、身份匹配 | interrupt 原 Runner，状态转 `paused` | 已暂停时返回当前状态 |
| `cancel` | 非终态、身份匹配 | 终止并 cleanup，状态转 `cancelled` | 已取消时返回当前状态 |
| `prepare_resume` | `paused` / `lost` | 校验补充 artifact 与恢复上限；不启动模型 | 重复调用返回同一准备结果 |
| `resume` | 已准备、artifact 完整、预算可用 | rebind/`resume_task` 原 Runner | 不可因重放创建新 Runner |
| `events` | `task_id` | 返回追加事件流和游标 | 纯读取 |

每个写动作必须包含：

```yaml
task_id: "GW-..."
expected_revision: 3
expected_runner_ref: "..."       # 尚未启动时允许为空
actor: "user | main_control"
reason: "明确且可审计的原因"
idempotency_key: "UUID"
```

`expected_revision` 或 `expected_runner_ref` 不匹配时返回 `HUMAN_REQUIRED`，不得猜测
最新状态或选择另一个 Runner。

### 6.2 补充信息的分类

| 用户补充内容 | 可否恢复原任务 | 所需工件 |
|---|---|---|
| 澄清已有措辞，但不改范围、contract、验收 | 可以 | `ResumeDirective`，引用原 TaskPacket revision |
| 改变写入路径、验收、预算、Docker 权限、contract | 不直接恢复 | 新 TaskPacket revision；原任务 `superseded` 或人工闸门 |
| 发现隐私、安全、权限或 snapshot 不确定 | 不恢复 | `HUMAN_REQUIRED` 记录 |
| 原 Runner 已完成 | 不恢复 Owner | 创建后续 handoff/Test 或新任务，取决于最终 snapshot |

`ResumeDirective` 只包含用户补充的最小事实、来源、影响判断和需先读的 artifact；
禁止把整段父对话直接传给子 Codex。

## 7. 三阶段实施

### 阶段一：可人工控制的持久化基础

**目的：** 即使主控对话已经不存在，用户仍能可靠地查询、暂停、取消和恢复同一
Runner。这一阶段不接入 MCP、SDK 或 Desktop App。

1. 新建 `control_protocol.py`，定义请求、响应、错误分类和 JSON schema。
2. 将 Scheduler 的 `pause/resume/cancel/restore/inspect` 包装成单一服务接口；不允许
   客户端直接访问 `RunnerExecution` 或 `CodexCliBridge`。
3. 实现单实例 Scheduler 服务，使用锁防止双服务写同一 `.agent-loop/` 状态根。
4. 启动时执行 `Scheduler.restore()` 和 Host registry rebind；失败时保持
   `HUMAN_REQUIRED`，不自动 create。
5. 实现人用命令：
   `agent-loop-control inspect|submit|pause|cancel|prepare-resume|resume|events`。
6. 增加 `ResumeDirective` 模板和校验器；明确何时必须 bump TaskPacket revision。
7. 将控制动作追加到 ExecutionJournal / RunManifest，记录 actor、原因、幂等键、
   前后状态和 artifact refs；明确“服务关停不等于取消子 Runner”。

**阶段验收：** 协议单测覆盖 revision/runner_ref 漂移、重复幂等键、非法状态转换、
Owner/Test 越权控制和补充信息分类。终端用户可在主控对话不存在时查询、暂停、
重启服务、rebind 并恢复同一 Runner，且全过程不出现第二个 `create_task`。

**当前实现：** `control_protocol.py` 提供身份绑定的 `inspect`、`pause`、`cancel`、
`prepare_resume`、`resume`、`events` 命令、追加控制日志和恢复指令；
`control_service.py` 提供单实例 Unix socket 服务与私有能力令牌；
`agent_loop_control.py` 提供人工 CLI。`test_scheduler_control.py` 覆盖幂等重放、
版本/Runner 漂移、服务重启后的恢复指令、私有令牌和 Scheduler 审计 actor。当前
managed sandbox 仍禁止 Unix socket bind/connect；但同一 fake-backend socket smoke
已在真实本机权限下通过，证明服务入口本身可运行。真实 Owner → Test 的控制 canary
仍属于阶段二现场验收。

### 阶段二：主控对话接入与真实闭环

**目的：** 让新的主控 Codex 对话能够通过受限工具控制阶段一的服务，并用一次真实
Owner → Test 闭环证明“中断后补充信息”不会造成重复执行。

1. 将阶段一 API 包装为 MCP 工具或本地受限工具：`loop_inspect`、`loop_submit`、
   `loop_pause`、`loop_prepare_resume`、`loop_resume`、`loop_cancel`。
2. 工具描述强制要求主控先 `loop_inspect`；写动作必须带用户意图、任务身份和原因。
3. 只把控制工具授予主控；Owner/Test Profile 不加载它们。
4. 用户在新消息中说“继续/暂停”时，主控根据协议主动调用工具；不把 App 的原生
   “停止”当作回调。
5. 运行一个低风险 Product canary：

```text
submit Owner
  -> 主控中断
  -> 子 CLI 继续或被显式 pause
  -> 新主控 inspect
  -> 写入补充信息 artifact
  -> rebind / resume 原 thread
  -> Owner final snapshot
  -> 独立 Test（必要时 Docker）
  -> RunManifest 完整关闭
```

**现场实现：** 已新增零第三方依赖的
`scripts/agent_loop/control_mcp_server.py`，只公开 `loop_inspect`、`loop_submit`、
`loop_pause`、`loop_prepare_resume`、`loop_resume`、`loop_cancel` 六项动作。`loop_submit`
只提交 `runtime.json` 中已声明的 LaunchSpec，不能从自然语言上传或生成新
TaskPacket；所有写动作固定标为 `main_control` 并携带新幂等键。它必须作为**主控宿主的用户级 MCP 配置**单独注册，
不得写进项目 `.codex/config.toml`；否则子任务可能继承该配置。`CodexCliBridge` 已对
Owner/Test 子进程使用 `codex exec --ignore-user-config`，从而不加载用户级 MCP 控制工具。
Runner 运行时配置可显式声明 `host.model` 和 `host.model_reasoning_effort`；
低风险串行 canary 默认使用 `gpt-5.6-luna` 与 `xhigh`，命令形态为
`codex exec --ignore-user-config --model gpt-5.6-luna --config model_reasoning_effort="xhigh" ...`。
如果当前宿主模型目录或网络不可用，必须报告环境/宿主问题，不能静默回退到更贵模型并伪造同等证据。
恢复说明也不再把控制平面的绝对路径交给子任务：仅当其 schema、task、revision 和
runner_ref 都匹配时，才复制到原子任务自己的
`.agent-loop/resume-directives/...` 中并作为相对路径传给 `codex exec resume`。
`scripts/agent_loop/control_runtime.py` 现为正式的服务装配点：它从
`agent-loop.control-runtime.v1` JSON 配置加载已验证的 LaunchSpec、Scheduler 限额和
CLI Host 路径，启动时只会 restore/rebind 已持久化任务，或通过 `loop_submit` /
preload 提交配置中已声明的 TaskPacket；不会从自然语言生成任务，更不会在恢复时
调用 create。Runtime 已显式接入 `resume_artifact_factory`：恢复指令只有在 schema、
task、revision 和 runner_ref 都匹配后，才会被复制进原子任务 worktree 并传给
`codex exec resume`。服务启动使用：

```text
python3 scripts/agent_loop/agent_loop_control.py serve \
  --runtime-config /absolute/state/runtime.json \
  --socket /absolute/state/control.sock \
  --token-file /absolute/state/token
```

主控宿主完成服务启动后，配置示例为（路径和 token 必须是本机私有状态，不提交）：

```toml
[mcp_servers.agentLoopControl]
command = "python3"
args = ["/absolute/repo/scripts/agent_loop/control_mcp_server.py", "--socket", "/absolute/state/control.sock", "--token-file", "/absolute/state/token"]
enabled_tools = ["loop_inspect", "loop_submit", "loop_pause", "loop_prepare_resume", "loop_resume", "loop_cancel"]
default_tools_approval_mode = "prompt"
```

这与官方的本地 STDIO MCP 配置模型一致；Desktop、CLI 和 IDE 会共享同一宿主配置，
所以隔离 Owner/Test 的 `--ignore-user-config` 是实际安全边界，而非文档约定。

`GW-SCHED-CTRL-001` 已在真实 WSL 完成验收：控制服务通过私有 Unix socket 启动，
用户级 `agent-loop-control` MCP 注册指向同一服务；主控依次执行 submit、inspect、
pause、prepare-resume、resume 和 inspect。Owner 在 `turn.started` 后被暂停，避免了
CLI 尚未生成可恢复 rollout 时的错误；ResumeDirective 与同一 `runner_ref` 绑定，恢复
后 Owner 只提交 `apps/web/frontend/index.html`，独立 Test 从 Owner final snapshot 开始并
返回 `PASS`。完整 RunManifest、TestReport 和控制事件留在忽略的运行目录，摘要见
[`PILOT_019_REPORT.md`](PILOT_019_REPORT.md)。该 runtime 只承载其声明的 TaskPacket；
下一个任务必须使用新的状态根和 runtime 配置重启服务，不能把自然语言直接塞进旧服务。

**阶段验收：** 全新主控对话只读取 TaskPacket、ContextBrief 与 Scheduler 状态后，
能够正确查询原 Runner、避免重复创建、带 ResumeDirective 恢复，或在不确定时进入
`HUMAN_REQUIRED`。canary 必须记录连续事件序号、revision 归属、token/耗时、resume
次数、独立 Test snapshot，以及声明 Docker 时的 health/cleanup 和 rollback。

### 阶段三：宿主升级与界面适配（可选）

**目的：** 在阶段二已经稳定后，降低 CLI 子进程管理成本，并评估是否存在可验证的
Desktop 控制接线；这不是前两阶段的前置条件。

1. 新增 `CodexSdkBridge` 实现既有 `CodexHostBridge` 协议，与 CLI Bridge 并存。
2. 用同一低风险任务对照验证：

1. create、事件读取、interrupt、resume、close；
2. `thread_id <-> runner_ref` 的持久化身份映射；
3. 服务重启后的 lookup/rebind；
4. 隔离 worktree/snapshot、权限、日志和 cleanup；
5. Owner → 独立 Test 的完整证据链。

3. 只有在 OpenAI 提供可验证的 Desktop 事件接口时，才新增“App 动作 → 控制 API”
   适配；否则维持“用户/主控显式调用控制工具”的语义。

**阶段验收：** SDK Bridge 在 create、事件读取、interrupt、resume、close、
持久化身份映射和进程重启 rebind 上与 CLI canary 等价；否则 CLI Bridge 保持默认和
回退路径。官方文档说明 SDK 可程序化控制本地 Codex，而 App Server 面向需要认证、
历史、审批和事件的深度客户端集成；这证明 SDK 适合作为 Host 替代候选，但**不能证明
Desktop App 会转发其停止按钮事件**。

## 8. 所需前置条件

### 工程前置条件

- 一个由服务独占的、可写 `.agent-loop/` 状态根与锁；
- 已验证的 Git snapshot、TaskPacket、ContextBrief 和当前 CLI Host 配置；
- 本地 IPC 身份验证；不得把控制端口暴露到网络；
- 受版本控制的 ResumeDirective 模板/校验器，以及忽略的原始运行工件目录；
- 用于 P3 的低风险任务、明确允许写入路径和 TestMatrix；
- Docker 只在 P3 TaskPacket 声明服务依赖时启用。

### 人工决策前置条件

1. V1 是否只支持 WSL 本地 socket，还是同步支持 Windows 原生？建议先 WSL。
2. P2 是让主控调用 MCP 工具，还是先仅交付人用 CLI？建议先 CLI，再 MCP。
3. 是否接受“App 停止不自动暂停子任务”，而由新主控显式 `inspect` 决定？建议接受；
   这是目前可验证且不误杀子任务的语义。
4. 是否在阶段三投入 SDK Host canary？建议在阶段二真实闭环通过后再决定。

## 9. 安全与失败关闭规则

- 控制 API 只允许本机可信调用方；日志中不保存完整聊天、令牌或未脱敏模型输出；
- 不接受任意 shell 命令、任意路径或任意 `runner_ref`；所有路径由 TaskPacket /
  artifact registry 校验；
- 禁止 `resume` 绕过 TaskPacket revision、预算、恢复次数、snapshot 或 retry-learning
  gate；
- Host 查询失败、锁丢失、服务出现两个实例、事件序号不连续、身份不匹配或补充信息
  无法分类时，统一 `HUMAN_REQUIRED`；
- `cancel` 只清理由当前 Runner 所有的 worktree、容器和临时资源；禁止 broad cleanup；
- 控制入口不执行自动修复、自动合并、自动部署或自动放宽 Test。

## 10. 验收矩阵

| 场景 | 预期结果 |
|---|---|
| 主控对话存在，用户明确暂停 | 同一 Runner 被 interrupt，事件为 `running -> paused` |
| 主控对话中断，子任务仍运行 | 新主控 `inspect` 找到同一 runner_ref；不 create 新任务 |
| Scheduler 服务重启 | `restore + rebind` 成功，任务身份与 snapshot 不变 |
| 同一暂停请求重放 | 不重复 interrupt；返回已暂停状态 |
| 补充信息不改变任务语义 | ResumeDirective 被读取后恢复原 thread |
| 补充信息改变 contract 或验收 | 拒绝直接恢复，要求新 revision / 人工闸门 |
| 用户取消 | 原子任务终止、清理受控资源、不可自动 resume |
| Owner 试图调用控制工具 | 权限拒绝，记录协议失败 |
| SDK canary 不支持持久 rebind | 维持 CLI 默认路径，不宣称 SDK 已替换 |

## 11. 完成定义

只有同时满足以下条件，才可称“主控可安全操控持久化子任务”：

1. 人工 CLI 已能独立完成 inspect、pause、cancel、prepare-resume 和 resume；
2. 所有动作受 revision、runner_ref、状态、预算、锁和幂等键约束；
3. 中断主控后，新主控能从持久化状态恢复判断，且不重复 create；
4. 补充信息有不可变、可审计的 artifact 与分类规则；
5. Owner → 独立 Test 的真实串行 canary 通过并完成 RunManifest；
6. App 原生停止按钮仍明确标为“未接线”，除非未来有可验证的官方接口和现场证据；
7. 可选 SDK Host 只有在独立 canary 通过后才被标为可用。

## 12. 参考

- 本仓库现有宿主与恢复边界：[`CODEX_TRANSPORT.md`](CODEX_TRANSPORT.md)
- 现有 Scheduler / Runner 教学说明：[`MODULE_MANUAL.md`](MODULE_MANUAL.md)
- 现有启动与停止协议：[`START_HERE.md`](START_HERE.md)
- 官方 Codex SDK：<https://learn.chatgpt.com/docs/codex-sdk>
- 官方 Codex App Server：<https://learn.chatgpt.com/docs/app-server>
