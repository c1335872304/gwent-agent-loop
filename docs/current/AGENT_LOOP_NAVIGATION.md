# Gwent Agent Loop 项目导航

> **状态：受限串行运行（以 `agent-loop/CURRENT_STATE.md` 为唯一现状）**
> **版本：0.3**
> **用途：给主 Agent、Context / Integration Agent 和各领域 Owner 提供稳定的上下文入口。**
> **当前实现状态：** [`agent-loop/CURRENT_STATE.md`](agent-loop/CURRENT_STATE.md) 是唯一现状入口。

新 Agent 或新对话的默认入口、读取顺序、责任域路由和验证选择只看
[`AGENT_ONBOARDING_INDEX.md`](AGENT_ONBOARDING_INDEX.md)。执行协议只看
[`agent-loop/START_HERE.md`](agent-loop/START_HERE.md)。本导航是 Context / handoff /
Lessons 的维护附录，不再复制入口表、领域路由或当前状态。

这不是项目百科，也不是新的规则来源。它只回答两个问题：上下文如何交接、已验证的
坑如何沉淀。责任域和事实来源请回到 Onboarding Index；业务语义请回到 Skill / contract。

项目的长期记忆必须落在可版本化的文件和结构化工件中，而不是依赖某个聊天窗口仍然保持完整上下文。

## 1. 使用边界

首次读取顺序、责任域路由、事实来源选择、状态语义和验证等级统一由
[`AGENT_ONBOARDING_INDEX.md`](AGENT_ONBOARDING_INDEX.md) 维护。本导航不提供第二份
路由表。执行顺序、停止条件和交付物统一由 [`agent-loop/START_HERE.md`](agent-loop/START_HERE.md)
维护。本页只补充 Context / handoff / Lessons 的维护规则。

进入写入前，Owner 按领域、关键词和 contract 触发词检索
[`LESSONS_LEARNED.md`](agent-loop/LESSONS_LEARNED.md)；只注入相关条目，不要求阅读
整个经验库。

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

## 2. 上下文与交接附录

机器可检查的权威顺序、必读底座、默认排除项、交接字段和停止条件只定义在
[`agent-loop/CONTEXT_INDEX.yaml`](agent-loop/CONTEXT_INDEX.yaml) 的 `context_policy`。
本页只说明如何使用它：

- `ContextBrief` 记录本任务实际读取的 `included_refs`、主动排除的 `excluded_refs` 和
  未解决的 `authority_conflicts`；
- `TaskPacket` 冻结范围、Owner、snapshot、预算和验收，不能被聊天文本静默覆盖；
- handoff 只传递 TaskPacket、ContextBrief、ChangeReport、final snapshot 和 contract diff；
- 新 Agent 不读取父对话全文、整仓库扫描结果或历史归档作为默认上下文。

如果来源冲突，先按 `context_policy.authority_order` 找权威来源；无法裁决就记录冲突并
停止为 `HUMAN_REQUIRED`，不要用“最新看到的文本”覆盖正式 contract。

## 3. 领域导航

Core、Trainer、Product、Teacher 和 Test / Verification 的触发词、Owner、Skill、事实来源
与最小验证统一见 [`AGENT_ONBOARDING_INDEX.md`](AGENT_ONBOARDING_INDEX.md)。领域卡是任务
入口，Skill 是 workflow/invariant，contract 是语义来源；本导航不重复这些业务规则。

跨域任务必须由最接近事实来源的 Owner 主导，通过 contract handoff 串行交接；Context /
Integration 只整理上下文和工件，不定义领域 contract，也不替代 Owner。

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

当前能力、现场证据、关闭的能力和路线阶段只读取
[`agent-loop/CURRENT_STATE.md`](agent-loop/CURRENT_STATE.md)；理想路线只读取
[`agent-loop/IDEAL_LOOP_3_STAGE_PLAN.md`](agent-loop/IDEAL_LOOP_3_STAGE_PLAN.md)。本页不
复制 Pilot 数字、Host 能力或“当前下一步”，避免历史结论漂移成当前事实。

1. 新增或变更 contract 时，同一任务必须检查本页的上下文链接和维护规则。
2. 新发现的可复现坑，先写入 `LESSONS_LEARNED.md`，再决定是否修代码或补测试。
3. 任务完成前，Context / Integration Agent 检查导航引用是否指向最终 snapshot 的真实路径。
4. 失效链接、过时命令和已被 supersede 的结论必须标记，而不是静默删除。
5. 导航只负责指路；具体规范仍以 `AGENTS.md`、Skill 和正式 contract 为准。

## 7. 快速决策

责任域和最小验证统一见 [`AGENT_ONBOARDING_INDEX.md`](AGENT_ONBOARDING_INDEX.md)；
若问题是资料定位、交接、状态沉淀或工件组织，再使用本页第 2、4、5 节。

## 8. Current evidence pointer

`START_HERE.md` 是执行协议入口，`CURRENT_STATE.md` 是唯一现状和现场证据入口；需要追溯
历史时，沿 CURRENT_STATE 的链接进入 `agent-loop/archive/README.md`。原始 TaskPacket、
ContextBrief、ChangeReport、TestReport、handoff 和 RunManifest 留在 `.agent-loop/`，不
进入默认上下文。命令选择回到 Onboarding Index；CLI 实现细节见
`agent-loop/CODEX_TRANSPORT.md`。
