# Pilot 014：Revision 4 最终独立复验

> **Revision：4**
>
> 本 revision 只承接 Pilot 013 的两项已验证修复：Teacher 浏览器响应隐私
> 过滤，以及 clean snapshot 下历史运行证据链接的文档修复。其余变化是对
> BFF 回归测试的 gather 结果解包修正，确保测试真正断言缓存返回的响应对象。

## 最终验收

- Runtime `/v1/explain` 与 `/v1/explain-turn` 的公开 JSON 不包含
  `prompt`；行动链步骤也不包含；
- BFF `TeacherClient` 和 preview service 对兼容实现 fail-closed 过滤；
- 前端公开类型不声明 `prompt`；
- clean snapshot 的 architecture gate 不依赖被忽略的 `.agent-loop/` 工件；
- Test Agent 从最终 commit 独立执行声明命令，不能修改生产代码或测试断言。

## 独立 Test 命令

```text
git diff --check
python3 scripts/check.py architecture
python3 scripts/check.py docker-test
cd apps/web/frontend && npm run build
python3 -m pytest -q services/teacher/tests/test_api.py apps/web/backend/tests/test_teacher_preview_service.py
```

Docker 测试使用项目的 `run --rm` canonical 流程；Node/前端构建如仍受 WSL
环境限制，必须保留为环境阻塞，不能影响或伪造 Python/Docker 结果。
