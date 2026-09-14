# Pilot 012：Teacher 浏览器隐私边界修复与独立验证

> **Revision：2**
>
> 本 revision 修复 Pilot 011 发现的 `PRIVACY-001`：高级 Teacher 响应把
> provider-neutral `prompt` 序列化到了浏览器响应。正式运行必须绑定到本
> revision 产生的干净 Git commit；不得复用 Pilot 011 的 Owner/Test run。

## Owner 变更

| 字段 | 设计值 |
|---|---|
| `task_id` | `GW-STAGE3-LIVE-012` |
| `primary_owner` | `teacher` |
| `required_skills` | `teacher-explanation`, `product-integration` |
| `allowed_write_paths` | `services/teacher/`, `apps/web/backend/app/clients/teacher.py`, `apps/web/backend/app/services/teacher_preview_service.py`, `apps/web/frontend/src/types/game.ts`, `services/teacher/tests/`, `apps/web/backend/tests/`, `docs/current/TEACHER_AND_WEB.md` |
| `forbidden_paths` | `src`, `include`, `python/src`, `models`, `runs`, `packages/*.zip` |
| `declared_contracts` | `gwent-teacher-response-v1` and `gwent-teacher-turn-response-v1` remain version-compatible; browser payload no longer includes `prompt` |

### 验收条件

1. `TeacherAgent` 内部可以继续生成 prompt，但 `/v1/explain` 和
   `/v1/explain-turn` 的公开 JSON 不包含 `prompt`。
2. 行动链的每个嵌套 step 也不包含 `prompt`。
3. BFF 对 Teacher 响应再做一次 fail-closed 过滤，避免兼容实现把内部字段
   带到 React。
4. 前端公开 `TeacherResponse` 类型不声明 `prompt`；不新增隐藏手牌、未公开
   候选动作或 provider 信息。
5. 不改变 Core action、`option_index`、游戏 state/revision 或 Teacher
   evidence 的事实来源。

## 独立 Test / Verification

Test Agent 只从 Owner 的最终 commit 启动，不读取 Owner 执行过程。必须执行：

- `git diff --check` 和 changed-path / contract 检查；
- `python3 scripts/check.py architecture`；
- canonical `python3 scripts/check.py docker-test`（若 Docker 权限或服务不可用，
  记录 `DOCKER_FAILURE` / `ENVIRONMENT_FAILURE`，不得改成 PASS）；
- `cd apps/web/frontend && npm run build`，宿主缺 Node 时分类记录；
- Teacher Runtime API、BFF preview 过滤和原有 Teacher 回归测试；
- 输出绑定 final snapshot、实际命令、退出码、failure class 和证据路径的
  TestReport。

本 revision 不需要 Core/BFF/Teacher 多服务 smoke，因此不启动 compose 服务；
canonical pytest 使用测试镜像时，只清理本次创建的临时容器和资源。

## 运行边界

```yaml
revision: 2
max_concurrency: 1
parallelism: forbidden
model_change: forbidden
max_role_runs: 1
max_model_input_tokens: 1000000
max_model_output_tokens: 32000
max_model_turns: 4
max_elapsed_minutes: 20
docker_compose: not_required
```
