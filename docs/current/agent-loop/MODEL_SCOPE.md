# 模型范围声明

状态：Architecture-only baseline

## 当前决定

在 Agent Loop、项目导航、控制平面和产品架构阶段，暂时假设 `models/v3/policy.pt` 是正确且可用的冻结输入。

本阶段不审查模型权重，不加载模型，不重训模型，不迁移 checkpoint，也不替换或删除模型文件。模型文件不是当前架构任务的修改对象。

## 检查边界

当前 `python3 scripts/check.py architecture` 只确认：

- 产品代码指向规范路径 `models/v3/policy.pt`；
- 模型槽位和说明文档存在；
- 若本地有模型文件，只读取文件元数据确认它不是零字节文件。

architecture 检查不读取 29MB 模型内容，不计算哈希，不调用 PyTorch loader，也不据此判断模型结构或权重兼容性。全项目 `quick` 仍会进入 Trainer 校验，但架构任务不应调用它。

## 何时交给 Trainer

只有以下任务才进入 Trainer 范围：

- 安装、promotion 或替换产品模型；
- 验证 checkpoint 的 observation/action contract；
- 判断 resume、warm-start、migration 或 incompatible；
- 运行 PyTorch loader、完整评估或模型结构检查。

这些任务必须重新读取 `training-config` Skill，并提供独立的 TaskPacket、模型来源、contract 版本和验证证据。当前 Python 环境缺少 `torch` 时，应记录为 Trainer 环境阻塞，不应修改 Agent Loop 或伪造模型验证结果。

## 防止误用

- 不把模型二进制加入 ContextBrief 的正文上下文；只传递路径和本声明。
- 不因为 quick 没有加载模型，就把它描述成“模型已验证”。
- 不因为模型验证尚未执行，就阻塞与模型无关的 Core、Product、Teacher 或 Agent Loop 架构工作。
- 未来要改变这个假设，必须新增模型任务并由 Trainer Owner 明确解除本声明。

## 权威顺序

本声明只限定当前架构阶段的工作范围；模型训练和 promotion 仍以 `.agents/skills/training-config/SKILL.md`、`docs/current/TRAINING_AND_MODEL.md` 以及实际 Trainer 证据为准。
