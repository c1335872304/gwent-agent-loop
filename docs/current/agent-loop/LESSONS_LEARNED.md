# Agent Loop 坑记录与经验库

> 这不是指令文件，也不是完整项目百科。每条记录必须有来源、snapshot 和验证状态；未验证内容不得被自动当作事实。

## 记录格式

```yaml
id: "LL-YYYYMMDD-001"
status: "confirmed | inferred | superseded"
discovered_at: "YYYY-MM-DD"
task_id: "GW-..."
scope: "core | trainer | product | teacher | loop | environment"
symptom: ""
impact: ""
root_cause: ""
evidence:
  - ref: "path:line or artifact"
    snapshot: ""
correct_practice: ""
verification: []
regression_test: "none | path"
trigger_terms: []
```

## 已确认的高价值经验

### LL-001：Core actions 是合法性的唯一来源

```yaml
id: "LL-001"
status: "confirmed"
scope: "product"
symptom: "前端或 Teacher 根据 label/source/target 文本自行推导可行动作。"
impact: "可能与 Core 合法动作不一致，造成错误提交或解释越界。"
root_cause: "把展示文本误当作规则 contract。"
evidence:
  - ref: "AGENTS.md: Product Agent"
correct_practice: "只消费 Core 返回的 actions，原样提交 option_index；metadata 不足时请求 contract 变更。"
verification:
  - "Product BFF/前端 contract tests"
regression_test: "required"
trigger_terms: ["legal action", "option_index", "label", "source", "target"]
```

### LL-002：Teacher 不能通过流畅解释弥补缺少 evidence

```yaml
id: "LL-002"
status: "confirmed"
scope: "teacher"
symptom: "解释文本听起来合理，但没有 Strategy 已执行动作的结构化证据。"
impact: "可能编造原因或泄露隐藏手牌/未公开候选动作。"
root_cause: "把语言质量当成 grounding 和 privacy 验证。"
evidence:
  - ref: "AGENTS.md: Teacher Coding Agent"
correct_practice: "只解释结构化 evidence；经过 privacy filter；不重算 legal action。"
verification:
  - "PYTHONPATH=. pytest -q services/teacher/tests"
regression_test: "services/teacher/tests"
trigger_terms: ["evidence", "grounding", "hidden hand", "privacy"]
```

### LL-003：模型二进制存在不等于运行时安装元数据完整

```yaml
id: "LL-003"
status: "confirmed"
scope: "environment"
symptom: "models/v3/policy.pt 存在，但 installed.json 或 provenance 元数据缺失。"
impact: "source check、runtime readiness 和模型来源可能被混为一谈。"
root_cause: "把仓库中的公开推理资产和完整运行时安装状态当成同一件事。"
evidence:
  - ref: "models/v3/README.md"
  - ref: "scripts/check.py"
correct_practice: "验证时分别报告 source asset、runtime metadata 和服务 readiness；不能用其中一个冒充另两个。"
verification:
  - "python scripts/check.py quick"
regression_test: "pending: split source/runtime checks"
trigger_terms: ["policy.pt", "installed.json", "checkpoint", "readiness"]
```

### LL-004：Agent Loop 不是无限递归的 Manager 链

```yaml
id: "LL-004"
status: "confirmed"
scope: "loop"
symptom: "Planner、Reviewer 或 Tester 继续派生新的 Agent，重复读取相同上下文。"
impact: "token 失控、责任不清、结果无法审计。"
root_cause: "把角色定义误解为可无限递归的管理层。"
evidence:
  - ref: "docs/current/AGENT_LOOP_PLAN.md: 2.2, 11.1a"
correct_practice: "Main Agent 控制状态；子任务深度默认 1；Context / Integration 和 Test / Verification 按需开启。"
verification:
  - "Agent Loop budget and runner-loss evals"
regression_test: ".agents/evals/tasks/017_agent_loop_token_budget/TASK.md"
trigger_terms: ["recursive manager", "spawn", "subagent", "token budget"]
```

### LL-005：架构阶段不要把全项目 quick 当作默认验证

```yaml
id: "LL-005"
status: "confirmed"
discovered_at: "2026-09-13"
task_id: "GW-PILOT-001"
scope: "loop | trainer | environment"
symptom: "执行 scripts/check.py quick 时，流程进入 training-config/validate_training.py 并因本机缺少 torch 停止。"
impact: "与模型和训练无关的架构工作被误认为必须加载模型或安装 Trainer 依赖，浪费时间和上下文。"
root_cause: "quick 是全项目门禁，不是架构专用门禁；Test/Verification Agent 也尚未实现为自动 Runner。"
evidence:
  - ref: "AGENTS.md: 当前架构阶段边界"
  - ref: "docs/current/agent-loop/MODEL_SCOPE.md"
  - ref: "scripts/check.py: check_local_model_slot / quick"
correct_practice: "架构任务运行 scripts/check.py architecture、Agent Loop、文档、语法、contract 和本地确定性测试；只有 TaskPacket 明确进入 Trainer 或服务集成时，才运行全项目 quick、torch 检查或启动 Docker。"
verification:
  - "python scripts/agent_loop/check.py"
  - "python -m unittest -q scripts.agent_loop.*"
  - "python -c \"import scripts.check as check; check.check_docs()\""
regression_test: "docs/current/agent-loop/MODEL_SCOPE.md"
trigger_terms: ["architecture", "agent loop", "quick", "torch", "docker", "test agent"]
```

## 新增记录前的检查

### LL-006: Docker cleanup must be ownership-scoped

```yaml
id: "LL-006"
status: "confirmed"
discovered_at: "2026-09-13"
task_id: "GW-PILOT-001"
scope: "loop | environment"
symptom: "A global docker compose down on a shared project stopped and removed pre-existing gwent-local services."
impact: "Test cleanup can interrupt services outside the task scope."
root_cause: "The compose project lifecycle was treated as the temporary test container lifecycle."
evidence:
  - ref: "docker compose -f deploy/docker/compose.cpu.yml ps"
  - ref: "docs/current/agent-loop/TEST_AGENT.md"
correct_practice: "Record pre-existing resources; prefer docker compose run --rm or an isolated project name; clean only resources created by the current attempt."
verification:
  - "Docker test service: 37 tests passed"
  - "gwent-local core/bff/web restored healthy after scoped recovery"
regression_test: "pending: ownership-scoped Docker runner"
trigger_terms: ["docker", "compose down", "cleanup", "shared project", "container ownership"]
```

### LL-007: Windows patch arguments can fail before applying

```yaml
id: "LL-007"
status: "confirmed"
discovered_at: "2026-09-13"
task_id: "GW-PILOT-001"
scope: "loop | environment"
symptom: "The Windows apply-patch helper rejected a non-ASCII or large PATCH argument with a UTF-8 error, and the patch was not applied."
impact: "The assistant may assume a file changed, causing stale docs, missing config, or false verification."
root_cause: "The patch was transported through a Windows process argument path with fragile encoding or size behavior."
evidence:
  - ref: "codex.exe --codex-run-as-apply-patch output: requires a UTF-8 PATCH argument"
  - ref: "docs/current/agent-loop/TEST_AGENT.md"
correct_practice: "After any patch transport error, inspect the target file and git status; never assume a write happened. Verify the wrapper passes both the apply-patch flag and exactly one PATCH argument. Retry as small ASCII-only patches through the official apply-patch entrypoint, then rerun the relevant validator or tests and stage only after verification."
verification:
  - "architecture check passed after split ASCII-only patch retry"
  - "docs link check passed"
regression_test: "pending: patch transport smoke check"
trigger_terms: ["apply_patch", "UTF-8 PATCH", "Windows", "encoding", "not applied", "stale patch"]
```

### LL-008: Keep Windows patch operations small and independently verifiable

```yaml
id: "LL-008"
status: "confirmed"
discovered_at: "2026-09-13"
task_id: "GW-PILOT-001"
scope: "loop | environment"
symptom: "A large patch was chosen to reduce tool calls and keep multiple changes together, but Windows argument transport made the write fragile."
impact: "A failed batch write can leave several intended changes absent while creating uncertainty about what actually reached disk."
root_cause: "The workflow optimized for call count and apparent atomicity without accounting for Windows process-argument encoding and size constraints."
correct_practice: "Default to one file and one logical change per patch. Prefer ASCII anchors, split non-ASCII or long patches, inspect the target and git status after every apply, and validate before staging. Keep context large for reasoning but keep write operations small."
verification:
  - "architecture check passed after the split patch workflow"
  - "docs link check passed"
regression_test: "pending: patch transport smoke check"
trigger_terms: ["small patch", "single logical change", "ASCII anchor", "Windows argument", "independent verification"]
```

### LL-009: Host pytest failures are not authoritative when Docker is the test environment

```yaml
id: "LL-009"
status: "confirmed"
discovered_at: "2026-09-13"
task_id: "GW-PILOT-002"
scope: "loop | product | teacher | environment"
symptom: "Host pytest reported async test failures because pytest-asyncio was not installed, while the pinned Docker test image passed the same Python/API/Teacher suites."
impact: "A host dependency mismatch can be misclassified as a code defect and can cause unnecessary local package or torch installation."
root_cause: "The host interpreter and the repository test image were treated as equivalent environments even though only the image pins the required pytest plugins and runtime dependencies."
evidence:
  - ref: "python -m pytest -q apps/web/backend/tests: 13 passed, 4 async plugin failures on host"
  - ref: "python3 scripts/check.py docker-test: 62 passed in the pinned test image"
  - ref: "deploy/docker/requirements.test.txt"
correct_practice: "Use python3 scripts/check.py docker-test as authoritative Python pytest evidence for Product, Teacher, and Agent Loop scopes. Use host pytest only to diagnose environment differences, and classify its result as ENVIRONMENT_FAILURE when plugins or runtime dependencies are missing."
verification:
  - "Docker test image rebuild completed"
  - "62 tests passed, 2 dependency warnings"
regression_test: "python3 scripts/check.py docker-test"
trigger_terms: ["pytest", "pytest-asyncio", "host environment", "docker-test", "environment failure"]
```

### LL-010: Git identity and HEAD are preconditions for an exact snapshot loop

```yaml
id: "LL-010"
status: "confirmed"
discovered_at: "2026-09-14"
task_id: "GW-PILOT-003"
scope: "loop | environment"
symptom: "The repository had no HEAD and the initial commit was rejected with Author identity unknown."
impact: "An immutable git_commit snapshot and a real worktree-backed host task cannot be proven."
root_cause: "Git user.name and user.email were not configured for this repository or its global scope."
evidence:
  - ref: "git rev-parse --verify HEAD: no HEAD"
  - ref: "git commit: Author identity unknown"
  - ref: "docs/current/agent-loop/pilots/PILOT_003_REPORT.md"
correct_practice: "Before a real Git-backed loop, check HEAD and local user.name/email. Ask the user before configuring identity; never silently invent identity. Use file-hash manifests only as diagnostic evidence and mark the pilot blocked for exact Git snapshot requirements."
verification:
  - "git rev-parse --verify HEAD"
  - "git config user.name"
  - "git config user.email"
regression_test: "docs/current/agent-loop/CURRENT_STATE.md"
trigger_terms: ["git baseline", "HEAD", "author identity", "worktree", "snapshot"]

### LL-011: A remembered lesson is ineffective without an enforced preflight

```yaml
id: "LL-011"
status: "confirmed"
discovered_at: "2026-09-14"
task_id: "GW-PILOT-003"
scope: "loop | environment"
symptom: "LL-007 and LL-008 already existed, but the next edit still entered a fragile Windows patch transport path before the lesson was applied as a precondition."
impact: "The same failure class recurred and consumed time despite an existing long-term record."
root_cause: "The lesson was navigable reference material, not a mandatory write gate checked before execution."
evidence:
  - ref: "docs/current/agent-loop/AGENT_LOOP_NAVIGATION.md section 1.1"
  - ref: "AGENTS.md Windows file-write preflight"
  - ref: "scripts/agent_loop/check.py Windows write preflight markers"
correct_practice: "Promote repeated operational lessons into the repository entry instructions and a deterministic architecture check. The Agent must complete the preflight before constructing a patch, not only record the failure afterward."
verification:
  - "python scripts/check.py architecture"
  - "read AGENTS.md before repository writes"
regression_test: "scripts/agent_loop/check.py"
trigger_terms: ["remembered lesson", "preflight", "repeat failure", "write gate"]
```

### LL-012: A single-domain loop reserves one subtask for the independent verifier

```yaml
id: "LL-012"
status: "confirmed"
discovered_at: "2026-09-15"
task_id: "E4-TARGET-001"
scope: "loop"
symptom: "The Owner and independent Test Agent both closed successfully, but the RunManifest was rejected because max_subtasks was configured as 0."
impact: "A real completed responsibility chain lost its final manifest solely because the budget omitted the required verifier subtask."
root_cause: "max_subtasks was interpreted as Owner recursion instead of the total number of child tasks created by the loop."
evidence:
  - ref: ".agent-loop/tasks/E4-TARGET-001/artifacts/runner-e4-t001-baseline-test-r2.json"
  - ref: "scripts/agent_loop/bounded_loop.py"
    snapshot: "ea117826d569f0a5a370512e6c3adff362f746a8"
correct_practice: "For the serial Owner -> independent Test shape, set max_subtasks=1 and max_subtask_depth=0; reserve recursion separately from the verifier count."
verification:
  - "TaskPacket validation passed with max_subtasks=1"
  - "Independent Docker Test closed with 198 passed tests"
regression_test: "scripts/agent_loop/test_bounded_loop.py"
trigger_terms: ["max_subtasks", "independent verifier", "RunManifest budget", "serial loop"]
```

### LL-013: The bounded wait must derive from the declared task time budget

```yaml
id: "LL-013"
status: "confirmed"
discovered_at: "2026-09-15"
task_id: "E4-TARGET-001"
scope: "loop | environment"
symptom: "The Owner returned a valid ChangeReport, but the runner timed out at its fixed 180-second wait before the close phase completed."
impact: "The loop could waste a real model run and leave no final handoff even though the child task had already finished its work."
root_cause: "The orchestration wait bound was shorter than the TaskPacket max_elapsed_minutes and was not derived from the declared budget."
evidence:
  - ref: ".agent-loop/tasks/E4-TARGET-001/artifacts/runner-e4-t001-baseline-owner.json"
  - ref: "scripts/agent_loop/run_bounded_loop.py"
    snapshot: "ea117826d569f0a5a370512e6c3adff362f746a8"
correct_practice: "Default max_wait_seconds to TaskPacket execution.max_elapsed_minutes*60; use an explicit smaller bound only for a deliberate canary."
verification:
  - "The rerun closed Owner and independent Test and recorded final snapshots"
  - "Unit test for the derived wait bound passed"
regression_test: "scripts/agent_loop/test_bounded_loop.py"
trigger_terms: ["max_wait_seconds", "bounded wait", "runner timeout", "TaskPacket elapsed budget"]
```

### LL-014: A serial task budget must cover both role outputs

```yaml
id: "LL-014"
status: "confirmed"
discovered_at: "2026-09-15"
task_id: "E4-TARGET-002"
scope: "loop"
symptom: "Owner and independent Test both closed, but the task-level RunManifest exceeded max_model_output_tokens=8000 even though neither role exceeded its own profile limit."
impact: "A valid independent Docker Test result was incorrectly left at human_required because the aggregate budget did not cover the serial Owner plus verifier outputs."
root_cause: "The TaskPacket output limit was treated as a per-role allowance while RunManifest accounts for the whole serial responsibility chain."
evidence:
  - ref: ".agent-loop/tasks/E4-TARGET-002/run-manifest-baseline.json"
  - ref: ".agent-loop/tasks/E4-TARGET-002/run-manifest-baseline-r2.json"
    snapshot: "d39cf8f066591f44bc4dc9405fd7b0a9a1234037"
correct_practice: "Set the task-level output budget to cover the declared serial role chain, keep each profile limit intact, and record exhausted_limits when a run still exceeds the aggregate budget."
verification:
  - "The corrected 32000-token packet completed Baseline and Evolved RunManifest validation"
  - "scripts/agent_loop/test_manifest_completion.py passed"
regression_test: "scripts/agent_loop/test_manifest_completion.py"
trigger_terms: ["max_model_output_tokens", "aggregate budget", "serial Owner Test", "exhausted_limits"]
```

1. 先确认它不是已有 Skill、contract 或导航条目的重复内容；
2. 保存最小可验证症状，不复制整段聊天或敏感日志；
3. 记录来源和 snapshot；
4. 能补回归测试就补测试，不能补时写明原因；
5. 如果事实已改变，不删除旧记录，标记为 `superseded` 并链接新记录。
