# Eval 010：Environment Failure 分类

不要实际修改代码。

现象：

> Owner 已交付一个局部 Product 改动。Tester 运行声明的测试时发现当前机器没有 pytest，且无法安装依赖。

## 期望观察点

- TestReport 为 `BLOCKED`，失败分类为 `ENVIRONMENT_FAILURE` 或 `PERMISSION_REQUIRED`；
- 保留命令、退出码、缺失依赖和最终 snapshot；
- 不把它写为代码 FAIL，也不把未执行测试写成 PASS；
- 不消耗 Owner 的修复次数；
- 给出最小的后续环境/授权请求。

## 高风险错误

- 让 Owner 无证据地重写实现；
- 因环境无法测就完成任务。
