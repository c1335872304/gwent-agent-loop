# Test / Verification 修改闸门

Test / Verification 可以验证、复现和补充测试，但不拥有任何生产 contract。

## 可以写入

- TaskPacket 明确声明的 `test_write_roots`；
- 回归测试、fixture、测试脚本和测试配置；
- 隔离的临时目录；
- TestReport、ReviewReport 和环境证据。

## 默认禁止

- 生产实现、领域 contract、schema、API、privacy filter 和模型文件；
- 删除或弱化 assertion；
- 新增 `skip`、放宽 fixture、改变错误码语义来制造 PASS；
- 修改 Docker compose 的生产服务定义；
- 在没有 cleanup 证据时留下容器、端口、临时卷或日志。

## 测试修改流程

1. 先记录最终被测 snapshot 和复现命令；
2. 新回归测试优先证明修复前会失败，再证明修复后通过；
3. 修改 assertion、skip、fixture 或测试配置时，必须交给领域 Owner 复核测试语义；
4. TestReport 列出所有 changed test paths、命令、退出码、环境失败和 Docker 清理结果；
5. 领域 Owner、Review 和 Test 必须绑定同一个最终 snapshot；
6. 任何生产代码写入请求转为 `HUMAN_REQUIRED`，不能由 Test Agent 自行越权。

## Docker 规则

- 只能使用 [`TEST_MATRIX.yaml`](TEST_MATRIX.yaml) 和 TaskPacket allowlist 中的 compose 文件；
- `config`、`up`、`down`、`ps`、health 和 logs 是默认允许动作；
- 端口、容器名、数据卷和临时目录必须按 task 隔离；
- 服务启动失败分类为 `DOCKER_FAILURE` 或 `ENVIRONMENT_FAILURE`，不能伪装成业务测试失败；
- 任务结束必须记录 cleanup：`complete`、`incomplete` 或 `not_required`。
