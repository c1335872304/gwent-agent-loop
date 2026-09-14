# Phase 2 状态：确定性控制平面

> 状态：已结束（历史记录；确定性控制平面已落地）
>
> 当前状态请以 [`CURRENT_STATE.md`](CURRENT_STATE.md) 为准；本文件记录 Phase 2 当时的状态，文中的“下一步”不再作为当前待办。

## 已落地

- [`scripts/agent_loop/state_machine.py`](../../../scripts/agent_loop/state_machine.py)：显式状态转换、事件序号、任务 revision 和事件重放幂等；
- [`scripts/agent_loop/budget.py`](../../../scripts/agent_loop/budget.py)：任务级角色运行、子任务、输入/输出 token、轮次和时间预算；达到 80% 可预警，超限拒绝 reservation；
- [`scripts/agent_loop/locks.py`](../../../scripts/agent_loop/locks.py)：路径层级锁和 contract 锁冲突检测；
- [`scripts/agent_loop/snapshot.py`](../../../scripts/agent_loop/snapshot.py)：文件 hash snapshot、内容变化/缺失/声明 scope 内新增文件检测，以及与 TaskPacket write scope 的包含关系校验；
- [`scripts/agent_loop/validate_packet.py`](../../../scripts/agent_loop/validate_packet.py)：AgentProfile、ContextIndex、TaskPacket 的确定性校验；
- [`scripts/agent_loop/validate_artifact.py`](../../../scripts/agent_loop/validate_artifact.py)：工件类型、snapshot 绑定和文件存在性校验；
- [`scripts/agent_loop/manifest.py`](../../../scripts/agent_loop/manifest.py)：RunManifest 的状态、预算、角色运行、工件和事件序列校验；
- [`scripts/agent_loop/check.py`](../../../scripts/agent_loop/check.py)：当前六个 Profile、ContextIndex 和 TestMatrix 的单命令检查；
- [`scripts/agent_loop/persistence.py`](../../../scripts/agent_loop/persistence.py)：`.agent-loop/tasks/<task-id>/` 下的 state、事件日志和 JSON 工件持久化，支持重启恢复与事件幂等；
- [`scripts/agent_loop/file_locks.py`](../../../scripts/agent_loop/file_locks.py)：基于原子文件创建的跨进程锁、TTL 和显式过期 reclaim；
- `scripts/agent_loop/test_*.py`：21 个确定性单元/负例测试。

## 当前验证

```text
python scripts/agent_loop/check.py                         PASS
python -m unittest -q scripts.agent_loop.*                         PASS (21 tests)
python scripts/check.py quick                         BLOCKED at training-config validation: Python environment lacks `torch`
python -m compileall -q scripts/agent_loop                    PASS
```

## 尚未完成的控制面能力

1. `python scripts/check.py architecture` 已按 [`MODEL_SCOPE.md`](MODEL_SCOPE.md) 接受冻结模型槽位，不读取模型内容；全项目 `quick` 才会进入 Trainer 环境并需要 `torch`。
2. `scripts/check.py quick` 已纳入 21 个控制平面测试；安装环境仍需实际同步 `PyYAML>=6.0` dev 依赖。

## Phase 2 下一步（历史记录）

控制平面已进入人工闭环试点；在 Trainer 环境补齐前，不执行需要加载 PyTorch checkpoint 的训练验证，也不把它误判为 Agent Loop 协议失败。
