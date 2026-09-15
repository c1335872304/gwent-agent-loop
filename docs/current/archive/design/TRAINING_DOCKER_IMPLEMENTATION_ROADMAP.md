# 训练 Docker 原始实施路线图

> **记录属性：** 历史实施记录，不是当前训练能力、服务器状态或当前待办列表。
> 当前操作规则见 [`../../TRAINING_DOCKER.md`](../../TRAINING_DOCKER.md)；当前训练结果
> 必须来自 Training Task、RunManifest / `runs` 证据和对应的最终 snapshot。

## M0：训练 Docker contract

- 确认 CPU/GPU 镜像版本；
- 确认 Core builder 工具链；
- 确认容器内项目根目录、动态库路径和输出目录；
- 确认历史 retired task 的宿主机绝对路径不作为 Docker 任务运行；
- 确认不加入 SSH。

## M1：训练镜像

- 编写 `Dockerfile.train`；
- 编译并复制 `libgwent_core.so`；
- 安装锁定的 Python、PyTorch 和训练依赖；
- 设置非 root、工作目录和 `PYTHONPATH`。

## M2：CPU Compose 与 smoke

- 编写 CPU Compose；
- 用 `training/tasks/smoke.yaml` 执行 `plan`；
- 执行小规模 smoke；
- 检查 checkpoint、日志、评估和 `runs/` 输出。

历史记录曾以 8 个环境、2 个 collector 线程和 16 局 CPU smoke 验证 M0–M2；这些数字
只描述当时的运行，不得作为新的 PASS。当前执行必须重新记录 task、镜像、snapshot、
输出路径和 RunManifest。

## M3：GPU Compose 与服务器验证

- 编写 GPU Compose；
- 验证 `torch.cuda.is_available()`；
- 验证 C++ Core 动态库和 Collector；
- 先用小规模任务验证，再切换正式任务。

## M4：正式训练操作

- 服务器上执行正式 task；
- 512 并行只在服务器资源确认后启用；
- 记录镜像 tag、源码版本、Core ABI、schema、grammar 和 task；
- 训练结果经过 evaluation/promotion 后再安装到 `models/v3/`。

