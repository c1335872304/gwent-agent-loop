# 常见任务开场模板

> 复制一份模板后替换 `<...>`；模板只帮助构造 TaskPacket / ContextBrief，不授权扩大写入路径、Docker、模型或 contract 范围。开始前仍需读取 [`../../../AGENTS.md`](../../../AGENTS.md)、[`../agent-loop/START_HERE.md`](../agent-loop/START_HERE.md) 和对应领域卡。

## Product bug

```text
目标：修复 <apps/web 中可复现的 UI/BFF 问题>。
责任域：product；Owner：Product Agent。
事实来源：docs/current/agent-entry/PRODUCT.md；product-integration Skill；apps/web/docs/CORE_API_CONTRACT.md。
允许写入：apps/web/<精确文件或测试目录>。
禁止：复制 Core legal action、修改 HTTP contract 未经 handoff、加载模型/C++/RL、修改 Teacher 隐私规则。
验收：BFF 相关测试；前端改动运行 npm run build；Python pytest 的最终证据按 TaskPacket 使用 docker-test。
交接：若发现 Core field/action 或 Teacher evidence/privacy 缺口，停止 Product 修改，交给对应 Owner。
停止条件：snapshot、contract、Docker ownership 或隐私不确定时 HUMAN_REQUIRED。
```

## Core contract

```text
目标：修改 <legal action / pending choice / C ABI / Observation / Action Grammar / Reward ABI>。
责任域：core；Owner：Core Agent。
事实来源：docs/current/agent-entry/CORE.md；core-environment Skill；CORE_CONTRACTS.md；对应 contract reference。
允许写入：src/、include/、tests/ 中与 <精确范围> 直接相关的文件。
禁止：在 Python/BFF/React/Teacher 复制规则；手改生成 mirror；无关 contract 连带 bump；用 fixture 代替真实 Game::create() 回归。
验收：对应 Core unit/golden/trace；schema/ABI 任务运行 check_schema.py；runtime catalog 任务补真实 Game::create() integration regression。
交接：schema/action/reward 变化交 Trainer 判断 checkpoint 兼容性；HTTP 交 Product；evidence 交 Teacher。
停止条件：breaking contract、私有信息、catalog dependency 或 consumer scope 不确定时 HUMAN_REQUIRED。
```

## Training task

```text
目标：验证或运行 <算法 config / Training Task / smoke / evaluation / resume / warm-start / promotion>。
责任域：trainer；Owner：Trainer Agent。
事实来源：docs/current/agent-entry/TRAINER.md；training-config Skill；TRAINING_AND_MODEL.md；目标 task/config。
允许写入：configs/training/<...>、training/tasks/<...> 或声明的训练脚本/测试；运行输出只进 runs/，长期资产进 artifacts/。
禁止：用调参掩盖 Core/collector bug；strict=False、伪 metadata、静默裁剪；把 partial evaluation 当 promotion；直接覆盖 models/v3/policy.pt。
验收：validate_training.py --all；最小 smoke；按完整 episode 记录 matchup、illegal、completed games；需要时运行 check.py train。
交接：environment/schema/action 错误交 Core；模型安装/provenance 由 Trainer 留证并通知 Product；公开 metadata 交 Teacher。
停止条件：resume 身份、schema migration、预算、模型来源或 promotion 权限不确定时 HUMAN_REQUIRED。
```

## Teacher privacy

```text
目标：修复或扩展 <evidence / explanation / provider / /v1/explain / TeacherPanel / privacy>。
责任域：teacher；Owner：Teacher Agent。
事实来源：docs/current/agent-entry/TEACHER.md；teacher-explanation Skill；EVIDENCE_CONTRACT.md；PRIVACY_BOUNDARY.md。
允许写入：services/teacher/ 与声明的 Teacher 测试；若纯 UI，改由 Product Agent 负责。
禁止：生成/覆盖 option_index；重算 legal action；解释未执行动作；把隐藏手牌、未公开候选或内部 prompt 送到浏览器；让 Teacher/provider 失败阻断 gameplay。
验收：check_teacher.py；Teacher/BFF tests；证明 evidence provenance、privacy filter 和 deterministic fallback；TeacherPanel 改动补 frontend build，最终 Python 证据按 TaskPacket 使用 Docker。
交接：缺权威 game fact/trace 交 Core/Strategy；policy/value metadata 交 Core/Trainer；loading/error/UI 交 Product。
停止条件：隐私、evidence provenance、snapshot 或 provider 权限不确定时 HUMAN_REQUIRED。
```
