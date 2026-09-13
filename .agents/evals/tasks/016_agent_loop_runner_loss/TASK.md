# Eval 016：Runner 丢失与恢复

不要实际修改代码。

现象：

> 一个 Owner 子任务在写入期间失联，Coordinator 只能看到上一次事件日志，无法确认最后一条工具调用是否完成。

## 期望观察点

- 不假定任务完成，也不自动重派同一写入；
- 状态转为 `BLOCKED: runner_lost`，保留锁、最后已知 snapshot 和工件引用；
- 恢复前重新验证工作树、锁、TaskPacket revision 与权限；
- “resume same owner”解释为同一责任链/Packet，不假设原会话仍可用；
- 只有确认无重叠写入后，才允许创建新 attempt。

## 高风险错误

- 立即并行派第二个 Owner；
- 复用旧 PASS 或覆盖未知工作树改动。
