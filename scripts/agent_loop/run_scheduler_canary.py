"""Run the low-risk, model-free Phase 3 serial Scheduler canary."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import defaultdict, deque
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.agent_loop.scheduler import ExecutionUpdate, Scheduler, SchedulerLimits
    from scripts.agent_loop.test_launch import packet
else:
    from .scheduler import ExecutionUpdate, Scheduler, SchedulerLimits
    from .test_launch import packet


class CanaryBackend:
    """Deterministic backend; no model, Docker, or production file is touched."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.paused: list[str] = []
        self.resumed: list[str] = []
        self.cancelled: list[str] = []
        self.updates: dict[str, deque[ExecutionUpdate]] = defaultdict(deque)

    def start(self, task, _budget):
        self.started.append(task.task_id)
        return f"canary:{task.task_id}"

    def poll(self, task):
        if self.updates[task.task_id]:
            return self.updates[task.task_id].popleft()
        return None

    def pause(self, task, *, reason):
        self.paused.append(task.task_id)

    def resume(self, task):
        self.resumed.append(task.task_id)

    def cancel(self, task, *, reason):
        self.cancelled.append(task.task_id)


def _task(task_id: str, owner: str) -> dict:
    value = copy.deepcopy(packet())
    value["task_id"] = task_id
    value["ownership"]["primary_owner"] = owner
    return value


def run(state_path: Path | None = None) -> dict:
    backend = CanaryBackend()
    scheduler = Scheduler(
        backend,
        SchedulerLimits(
            max_concurrency=1,
            max_tasks=2,
            max_input_tokens=2000,
            max_output_tokens=1600,
            max_model_turns=8,
            max_elapsed_minutes=5,
        ),
        state_path=state_path,
    )
    first = "GW-SCHEDULER-CANARY-001"
    second = "GW-SCHEDULER-CANARY-002"
    scheduler.submit(_task(first, "product"))
    scheduler.submit(_task(second, "core"))
    scheduler.pump()
    scheduler.pause(first, reason="serial canary pause")
    scheduler.pump()
    if backend.started != [first]:
        raise RuntimeError("paused task allowed FIFO successor to start")
    scheduler.resume(first)
    backend.updates[first].append(
        ExecutionUpdate(
            status="completed",
            input_tokens_delta=11,
            output_tokens_delta=7,
            model_turns_delta=0,
            elapsed_seconds_delta=0.2,
            report_ref="artifacts/scheduler-canary-001-report.json",
            evidence_refs=("evidence/scheduler-canary-001.json",),
        )
    )
    scheduler.pump()
    scheduler.pump()
    if backend.started != [first, second]:
        raise RuntimeError("FIFO successor did not start after first task completed")
    backend.updates[second].append(
        ExecutionUpdate(
            status="completed",
            input_tokens_delta=13,
            output_tokens_delta=5,
            model_turns_delta=0,
            elapsed_seconds_delta=0.2,
            report_ref="artifacts/scheduler-canary-002-report.json",
            evidence_refs=("evidence/scheduler-canary-002.json",),
        )
    )
    scheduler.pump()
    result = {
        "status": "PASS",
        "mode": "serial",
        "max_concurrency": 1,
        "started_order": backend.started,
        "paused": backend.paused,
        "resumed": backend.resumed,
        "task_statuses": {
            first: scheduler.get_task(first).status,
            second: scheduler.get_task(second).status,
        },
        "usage": dict(scheduler.usage),
        "event_count": len(scheduler.events),
        "state_path": str(state_path) if state_path else None,
    }
    if state_path:
        scheduler.write_snapshot()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=None)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.state), indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
