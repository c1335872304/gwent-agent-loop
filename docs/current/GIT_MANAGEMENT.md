# Gwent Git 版本管理规范

> **状态：Proposed**  
> **版本：0.1**  
> **适用范围：本地开发、Agent Loop、测试、跨域 contract 变更和未来远程协作**

## 0. 当前仓库状态

最后核验：2026-09-13。

```text
本地 Git 仓库：已初始化
默认分支：main
远程仓库：未配置
首次提交：待配置作者身份后创建
Git LFS：当前环境不可用
```

首次初始化时已按现有 `.gitignore` 暂存项目文件。当前规则会排除缓存、`node_modules`、`.agent-loop/`、训练运行输出和 checkpoint；`models/v3/policy.pt` 以及 `release_assets/` 中的发布资产目前会被纳入候选提交。它们是大文件，未来配置远程仓库前必须重新确认存储策略。

本文件是管理规范，不替代 Git 的实际状态。任何状态结论必须以命令输出为准。

## 1. Git 在本项目中的作用

Git 不只是保存代码，还为 Agent Loop 提供三个确定性锚点：

1. **snapshot**：TaskPacket、ContextBrief、RunManifest 必须能引用一个可复现的基线；
2. **diff**：Reviewer 和 Test / Verification 必须知道本次到底改了什么；
3. **回退**：发现错误、越权或 false PASS 时，能定位 attempt 并恢复到已知状态。

Git 不负责保存完整聊天历史、隐藏推理、临时 Docker 状态或训练运行目录。长期上下文保存在导航、contract、坑记录和任务工件中。

## 2. 文件归属策略

### 2.1 应当提交

- `src/`、`include/`、`python/`、`apps/`、`services/`、`tools/` 中的源代码；
- `tests/`、领域测试、golden/trace 和有意维护的 fixtures；
- `configs/`、`training/tasks/`、`config/` 等正式配置和 contract；
- `.agents/`、`.codex/` 中的项目级 Agent 路由、Skill 和 eval；
- `docs/`、`AGENTS.md`、README、设计和迁移说明；
- Dockerfile、Compose、脚本和开发环境说明；
- 明确标记为公开、可复现发布输入的资产。

### 2.2 默认不应提交

- `.agent-loop/` 的本机状态、原始子会话和未脱敏日志；
- `runs/` 下的训练输出、checkpoint、metrics 和临时评估结果；
- `artifacts/` 中未 pinned 的运行资产；
- Python/Node/CMake 缓存、IDE 状态、虚拟环境和 `node_modules/`；
- `.env`、token、cookie、私钥、生产配置和个人机器路径；
- Docker 容器状态、临时数据库和本地导出文件。

### 2.3 模型和发布资产

当前规则对模型资产采用区分策略：

| 类型 | 当前策略 | 说明 |
|---|---|---|
| `models/v3/policy.pt` | 当前允许提交 | 项目文档将其定义为公开产品推理槽位；单文件约 28 MB。 |
| `models/**/installed.json` | 默认忽略 | provenance 应由安装流程或受控记录生成。 |
| `artifacts/checkpoints/*` | 默认忽略二进制 | 训练 checkpoint 不属于产品 runtime。 |
| `runs/*` | 默认忽略 | 保留 `runs/README.md` 的目录契约。 |
| `release_assets/*.zip` | 当前未被忽略 | 约 20 MB 的发布包，配置远程前需决定使用 Git、Release 附件或对象存储。 |

没有 Git LFS 时，不要继续向仓库添加更大的 checkpoint、embedding 或构建包。未来若需要远程协作，应在远程策略确定后再启用 LFS 或 Release 存储，避免把大文件历史永久写入普通 Git。

## 3. 首次基线提交

首次提交是“当前工作区基线”，不是对所有运行结果已经验证的声明。配置作者身份后按顺序执行：

```powershell
git config user.name "你的姓名"
git config user.email "你的邮箱"

git status --short
git diff --cached --stat
git diff --cached --name-only
git diff --cached --check

git commit -m "chore: establish project baseline"
git status --short
```

提交前必须检查：

- 没有 `.env`、密钥、个人临时文件；
- 没有 `node_modules/`、Python cache、训练 checkpoint；
- 大文件属于已确认的公开资产；
- 新增文档和 `.gitignore` 规则已在 staged diff 中；
- `git diff --cached --check` 没有 whitespace error；
- 当前目录没有与用户无关的未声明改动。

没有配置作者身份时，可以保持“已初始化、已暂存、未提交”，不得伪造作者邮箱。

## 4. 日常工作流

### 4.1 开始任务

```powershell
git status --short
git branch --show-current
git log -1 --oneline
```

确认用户已有改动后，再创建 TaskPacket 和 ContextBrief。用户改动与任务 scope 重叠时先进入 `HUMAN_REQUIRED`，不得 reset、checkout 或覆盖。

### 4.2 分支命名

未来有远程协作时，推荐：

```text
feat/core-<topic>
fix/product-<topic>
fix/teacher-<topic>
train/<topic>
test/<topic>
docs/agent-loop-<topic>
chore/<topic>
```

当前没有远程仓库且没有 Git 历史时，可以先在 `main` 建立初始基线；进入正式开发后，跨域或高风险任务 SHOULD 使用独立分支或独立 worktree。

### 4.3 修改和暂存

每次修改后先看 diff，再暂存：

```powershell
git diff
git diff -- <path>
git status --short
git add <声明过的路径>
git diff --cached --check
```

不建议在 Agent Loop 中无条件使用 `git add -A`，因为它可能把用户临时文件、未声明生成物或测试输出一起加入。只有首次基线或明确审查过范围时才允许全量暂存。

### 4.4 提交边界

一次提交应表达一个可解释的变更单元：

- 领域代码与对应测试可以同提交，但测试不能被隐藏在无关重构中；
- contract 变更必须在提交说明或关联文档中写明影响的 consumers；
- Context / Integration 文档提交不能伪装成业务代码修复；
- Test / Verification 产生的测试变更必须经过领域 Owner 或 Review mode 确认；
- 训练输出、临时日志和本机状态不进入提交。

推荐提交格式：

```text
<type>(<scope>): <short outcome>

Task: GW-YYYYMMDD-001
Contracts: unchanged | changed: <name>
Verification: <command/result>
```

常用 `type`：`feat`、`fix`、`test`、`docs`、`refactor`、`train`、`chore`。

## 5. Agent Loop 与 Git 的协作

### 5.1 TaskPacket 必须记录

```yaml
workspace:
  snapshot_kind: "git_commit | git_worktree | file_hash_manifest"
  snapshot_ref: ""
  branch: ""
  user_changes: []

git:
  base_commit: ""
  expected_changed_paths: []
  commit_required: false
  integration_owner: "main | domain_owner | human"
```

如果当前工作区没有可用 Git，必须降级为 `file_hash_manifest` 和单写者；不能假装拥有 worktree 隔离或可回滚 commit。

### 5.2 Agent 权限

| 角色 | 读 Git | 写代码 | 写测试 | 创建 commit | 处理冲突 |
|---|---:|---:|---:|---:|---:|
| Main Agent | 是 | 否，除非明确兼任 Owner | 否 | 按用户授权 | 负责停下并升级 |
| 领域 Owner | 是 | 仅声明 scope | 可写对应测试 | 可建议，不自动提交 | 不得静默覆盖 |
| Context / Integration | 是 | 否 | 否 | 仅文档任务且明确授权 | 记录冲突 |
| Test / Verification | 是 | 否 | 仅声明 test scope | 否 | 只报告 |
| Human | 是 | 按授权 | 按授权 | 最终决定 | 最终裁决 |

“能运行 Git 命令”不等于“有权修改任何文件”。写入权仍由 TaskPacket scope、锁和仓库规则共同决定。

### 5.3 每个 attempt 的 Git 证据

Owner、Review、Test 的工件应绑定：

- `base_snapshot`；
- `end_snapshot`；
- branch/worktree；
- changed files；
- staged 与 unstaged 是否存在；
- 相关 commit（如果已提交）；
- 测试执行时的实际 snapshot；
- 是否发现用户改动或 snapshot drift。

Review/Test 不得把不同 snapshot 的结果拼成一个 PASS。

## 6. 跨领域 contract 变更

Core、Trainer、Product、Teacher 共享 contract 时：

1. 权威 Owner 在独立分支或锁定 scope 中先定义 contract；
2. Context / Integration 记录 HandoffReport 和 consumer 列表；
3. 依赖 Owner 在自己的 scope 分别修改和测试；
4. Test / Verification 检查各 consumer 的最终 diff 和 snapshot；
5. Main Agent 或 Human 决定集成顺序和是否需要人工 gate；
6. 集成后重新生成 `IntegrationManifest`，不能沿用旧分支的测试 PASS。

Breaking schema、action grammar、HTTP、privacy、模型 promotion 一律不能仅靠 Git merge 就视为完成。

## 7. 回退、冲突和恢复

### 7.1 安全回退

回退前必须先确认精确目标、保留用户改动和记录当前 snapshot。禁止在未获授权时使用：

```text
git reset --hard
git checkout -- <path>
git clean -fd
```

这些操作可能删除用户工作。优先使用新分支、worktree、补丁或人工确认后的可恢复操作。

### 7.2 冲突处理

- 冲突涉及业务语义或 contract：交给权威领域 Owner；
- 冲突只涉及 Markdown/导航：Context / Integration 处理，但必须保留来源；
- 冲突涉及用户未提交改动：`HUMAN_REQUIRED`；
- 冲突无法在当前环境安全隔离：`BLOCKED`，不强行合并。

### 7.3 Runner 丢失

子会话失联时：

1. 保留最后已知 commit、工作树摘要、锁和 RunManifest；
2. 不启动第二个 Writer；
3. 检查是否有未知文件或半完成写入；
4. 确认安全后，使用新 attempt 恢复同一责任链；
5. 旧会话关闭，但旧工件不能删除。

## 8. Windows、换行和敏感信息

当前项目在 Windows 工作区，首次暂存时可能出现 `LF will be replaced by CRLF` 警告。它不是业务失败，但正式协作前应决定是否增加 `.gitattributes`，统一文本文件策略，避免无意义全文件 diff。

提交前必须检查：

```powershell
git diff --cached --check
git status --short --ignored
```

不得提交：

- `.env` 和 token；
- Docker registry 凭据；
- 本机绝对路径和个人临时截图；
- 完整 Agent 私密对话和隐藏推理；
- 未脱敏测试日志。

## 9. 远程仓库准备

当前不配置远程。未来配置前必须确认：

1. 仓库可见性和访问权限；
2. `policy.pt` 与 release zip 是否应该进入 Git、Release 附件或对象存储；
3. 是否安装并配置 Git LFS；
4. `.env`、密钥和训练数据是否已经清理；
5. 首次推送是否需要人工 Review；
6. 分支保护、PR 检查和回滚方式。

远程配置属于外部状态变更，不由 Agent Loop 自动决定。

## 10. Git 管理验收清单

### 初始基线

- [ ] `.git` 已初始化；
- [ ] 作者身份已配置；
- [ ] `.gitignore` 已审查；
- [ ] staged 文件列表已审查；
- [ ] 大文件策略已确认；
- [ ] `git diff --cached --check` 通过；
- [ ] 初始 commit 已创建；
- [ ] `git status --short` 干净或剩余项已解释。

### 每个 Agent 任务

- [ ] TaskPacket 有 branch/worktree/snapshot；
- [ ] 写入 scope 与 Git diff 一致；
- [ ] 用户既有改动未被覆盖；
- [ ] Context / Integration 更新了必要导航和坑记录；
- [ ] Test / Verification 在最终 snapshot 上运行；
- [ ] commit 或未提交状态已记录；
- [ ] 没有临时产物、密钥或大文件误入；
- [ ] 失败时保存 RunManifest 和回退信息。

## 11. 当前下一步

1. 用户提供本地 Git `user.name` 和 `user.email`；
2. 审查当前已暂存的 445 个文件和三个大文件；
3. 创建 `chore: establish project baseline` 初始 commit；
4. 决定是否补 `.gitattributes`；
5. 决定 `release_assets/` 和 `policy.pt` 的长期远程存储策略；
6. 再为 Agent Loop 的 Phase 1 引入分支、snapshot 和 RunManifest 约束。
