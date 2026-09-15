# 理想 Agent Loop 三阶段路线图

> **当前版本：** 0.1
> **当前所在：** 阶段三本地 Codex CLI Host 多角色串行 canary 已通过；经明确授权后已合入外部 `main`
> **权威现状：** [`CURRENT_STATE.md`](CURRENT_STATE.md)

这份文档把原来的 Phase 0–7 压缩成三个可验收的工程阶段。以后推进只
围绕这三个阶段，不再为了“看起来更智能”不断新增 Agent、循环或管理层。

## 总目标

```text
结构化上下文
  -> 一个 Owner 子任务
  -> 一个独立 Test/Verification 子任务
  -> 有证据的 PASS/FAIL/BLOCKED
  -> 有界恢复
  -> Git 集成与最终快照
  -> 可审计关闭
```

理想 Loop 不是所有 Agent 永久在线，也不是无限自动修复。它是由 Main
控制、专业 Agent 按需启动、Test Agent 独立验证、所有状态和证据可恢复的
受限自动化系统。

## 三阶段总览

| 阶段 | 目标 | Agent 范围 | 自动化范围 |
|---|---|---|---|
| 一 | 证明单领域真实闭环 | Main + 一个领域 Owner + Test/Verification | 只自动传递和记录，不自动修复 |
| 二 | 证明闭环可恢复、可集成 | 阶段一角色；Context 按需加入 | 有界恢复、Git 集成，失败进人工闸门 |
| 三 | 进入受限多 Agent 运营 | 四领域 Owner 按需路由，Context/Test 独立 | 受限调度、跨 contract handoff、持续评估 |

阶段必须顺序完成。任何阶段退出条件未满足，都只能修复当前阶段，不能
通过增加 Agent 或放宽验证标准来“跳过”。

---

## 阶段一：单领域真实闭环

### 目标

证明系统可以在一个真实项目任务中完成：创建子任务、传递结构化上下文、
修改代码、独立测试、返回报告、保存证据并关闭会话。

### 固定试验范围

- 选择低风险 Product 任务；
- 使用已有 Git 项目和明确 snapshot；
- 只启动一个 Product Owner；
- 完成后只启动一个独立 Test/Verification Agent；
- Test Agent 使用已声明的 Docker pytest 命令；
- `max_subtasks: 1`，不允许递归派生；
- 不启动 Core、Trainer、Teacher 并行任务；
- 不修改模型，不要求宿主机安装 Torch。

### 必须交付

1. 平台 Host Transport：`create / wait / interrupt / resume / close`；
2. Codex 返回值到 `RunnerEvent` 的严格映射；
3. 子任务在当前项目中从指定 Git snapshot 创建隔离 worktree；
4. 只通过 TaskPacket、ContextBrief、AgentProfile 文件引用传递上下文；
5. Owner 的 ChangeReport 和 Test Agent 的 TestReport；
6. 每个事件写入 ExecutionJournal，并投影到 RunManifest；
7. 子任务结束后关闭会话，保留结构化工件。

### 退出条件

- 真实 Product 子任务被创建在正确项目和正确 snapshot；
- 子任务没有收到父对话全文，也没有递归创建子任务；
- Owner 只修改声明的 write scope；
- Test Agent 在最终 snapshot 上独立运行声明命令；
- Docker health、命令、退出码、日志引用和 cleanup 都有证据；
- PASS、FAIL、BLOCKED 都能被 TestReport 闸门正确区分；
- RunManifest 能恢复任务责任链；
- 未发生超预算、越权写入或静默失败。

### 阶段一禁止事项

- 不做自动修 bug；
- 不做自动重试；
- 不做跨领域编排；
- 不删除子任务记录；
- 不把一次成功当成系统已经稳定。

---

## 阶段二：可恢复与可集成闭环

### 目标

证明阶段一不是一次性演示，而是可以在失败、Runner 丢失、测试修改、Git
冲突和用户已有改动存在时安全停止或恢复。

### 必须交付

- Host Transport 的状态、超时、取消和断线映射；
- Recovery Policy 与 ExecutionJournal 的真实连接；
- Runner 丢失的一次受控恢复，且不超过 `max_resumes`；
- 代码缺陷、Docker 故障、权限问题、协议错误和预算耗尽的不同恢复路径；
- `IntegrationManifest`：base snapshot、每次 attempt、changed paths、
  冲突、最终 snapshot 和回滚方式；
- worktree 到主工作树的人工确认集成闸门；对脏 parent 的 disjoint candidate
  可自动产出隔离分支/worktree，但不自动改写 parent；
- Test Agent 修改测试后的 Owner/Review 二次检查；
- 实际模型调用、token、耗时、停止原因和预算消耗记录；
- ContextIndex 的 snapshot 新鲜度和 superseded 检查；
- 已验证的新坑进入 Lessons Learned，未经验证的内容保持 unknown/inferred。

### 退出条件

- 至少完成两轮独立验证，而不是只重复同一个 Agent 的自检；
- 人为注入 Runner 丢失时，系统能有限恢复或正确进入人工闸门；
- Docker 故障不会触发无意义的模型重试；
- 测试失败不会被改成“通过”；
- Git 冲突、snapshot drift 和用户已有改动都能被识别并保留；
- 任意失败后都能回答：当前状态、已经消耗的额度、下一步和恢复点；
- 没有无限循环、隐式递归或证据缺失的 PASS。

### 阶段二允许的自动化

只允许自动执行“确定且有边界”的动作：记录事件、验证 schema、运行
allowlist 命令、有限恢复和生成下一步建议。修改生产代码、解决冲突、放宽
测试标准、改变 contract 和继续未知状态，必须进入人工闸门。

---

## 阶段三：受限多 Agent 运营闭环

### 目标

在前两阶段证据成立后，才把四个领域 Owner、Context/Integration 和
Test/Verification 组合成可重复的多 Agent 工作流。

### 必须交付

1. Main 驱动的确定性 Scheduler：按 TaskPacket 路由、排队、暂停和结束；
2. Context/Integration 按需生成最小 ContextBrief，而不是复制全仓库或全聊天；
3. 四个领域 Owner 只处理自己的事实边界和 Skill；
4. Test/Verification 与领域 Owner 使用独立会话和独立证据；
5. 跨领域任务通过 contract handoff，禁止按语言或目录机械拆分；
6. 并发、子任务数量、总 token 和总时间都有硬上限；
7. Agent Evals 覆盖正确路由、上下文 grounding、越权、snapshot drift、
   false PASS、预算和停止条件；
8. 提供取消、恢复、审计、关闭/归档和工件保留策略；
9. 对 breaking contract、隐私、模型、部署和生产写入设置人工 gate；
10. 用小流量、低风险任务做 canary，持续记录成功率、误判率、成本和回退。

### 退出条件

- 常规任务可以按需启动角色，不需要永久常驻专业 Agent；
- 多角色任务有明确 owner、handoff、验证和 integration 顺序；
- 一个 Agent 失败不会污染其他责任链；
- 所有自动重试都能由 RunManifest 解释并受到预算约束；
- 评估集没有 false PASS，未知状态会停止；
- 用户可以从任意暂停点恢复，而不会依赖原始聊天窗口仍在上下文中；
- 关闭子任务不会删除报告、快照、TestReport 或 Lessons Learned。

### 阶段三仍然不是

- 无限制自治开发；
- 自动决定 breaking contract；
- 自动替换模型或 checkpoint；
- 自动处理无法证明所有权的 Docker 资源；
- 用更多 Agent 掩盖 ContextBrief、contract 或测试证据缺失。

---

## 当前推进位置与下一步

当前已通过阶段一最小现场试点、阶段二受控恢复与隔离集成试点，以及阶段三
本地 Codex CLI Host-backed 多角色串行 canary。`PILOT_018_REPORT.md` 记录了
revision-5 的真实 Product Owner、新 Scheduler 进程 restore/rebind、Teacher
contract/privacy review、两轮独立 Docker Test、隔离 branch/worktree 集成、
rollback 和完整 RunManifest。真实 token/elapsed 指标、Docker health/failure/
cleanup 证据和 changed-path/contract gate 均已收口；经明确授权的最终候选已
合入外部 `main`。外部 Desktop/MCP Host 适配、并行编排、自动修复和生产写入
仍不在当前受限运行模式内。

阶段三 P0 的串行 Scheduler 已实现并由 `archive/pilots/PILOT_009_REPORT.md` 验证：
`max_concurrency=1` 下按 owner 路由、FIFO 排队，暂停任务继续占用调度槽，
并对任务数、tokens、turns 和 elapsed 设置硬上限。

阶段三控制面和本地真实 Host 现场验证均已完成：Scheduler 已接入显式 per-role
Runner backend，补齐 snapshot restore/rebind、跨角色 contract handoff，并由
`archive/pilots/PILOT_010_REPORT.md` 和 `PILOT_018_REPORT.md` 分别记录模型无关 canary 与真实
Product → Teacher → Test canary。最终候选已在明确授权后合入外部 `main`；四个
历史 ZIP 仍保留为未提交、不可读取的用户改动。自进化 E4 已生成机器回归报告，
但 target-001 的最终 RunManifest 仍需补齐，尚未进入 E5。后续只处理可选 Host 适配和单独
门禁，不改变当前串行安全边界。

## 维护规则

- 当前状态只写入 [`CURRENT_STATE.md`](CURRENT_STATE.md)；
- 本路线图只写三阶段目标和退出条件，不记录每次试验的即时数字；
- Pilot 报告记录事实，不能反向改变路线图的退出条件；
- 每次阶段推进都必须有 RunManifest、ChangeReport、TestReport 和验证命令；
- 任何失败先记录 Lessons Learned，再决定是否修改协议或代码。
