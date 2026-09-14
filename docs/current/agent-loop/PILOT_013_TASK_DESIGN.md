# Pilot 013：Revision 3 干净 snapshot 复验

> **Revision：3**
>
> 本 revision 承接 Pilot 012 的隐私修复，并修复独立 Test 在干净
> snapshot 中发现的历史证据链接缺陷：被 `.gitignore` 忽略的本地运行工件
> 不再被写成仓库内 Markdown 链接。验证必须从本 revision 的 Git commit
> 启动，不得依赖执行主机残留的 `.agent-loop/` 文件。

## 复验范围

- Teacher Runtime 与 BFF 的公开响应继续删除顶层和嵌套 `prompt`；
- 前端 `TeacherResponse` 继续只声明浏览器公开字段；
- 历史 Pilot 005–008 报告不再引用干净 snapshot 中不存在的运行时文件；
- 不修改 Core action、游戏状态、模型或训练输出；
- Test Agent 不修改生产代码和测试断言，直接从最终 commit 执行验证。

## 独立 Test 命令

```text
git diff --check
python3 scripts/check.py architecture
python3 scripts/check.py docker-test
cd apps/web/frontend && npm run build
python3 -m pytest -q services/teacher/tests/test_api.py apps/web/backend/tests/test_teacher_preview_service.py
```

Docker pytest 仍按 Test Agent 和 TestMatrix 的 canonical 规则执行；如果宿主
没有 Docker 权限、Node 或 pytest，只能记录对应环境失败，不能把静态源码审查
升级为完整 PASS。
