"""Deterministic regression tests for the Phase 3 Scheduler."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from collections import defaultdict, deque
from pathlib import Path

from .errors import BudgetExceeded
from .scheduler import ExecutionUpdate, Scheduler, SchedulerLimits
from .test_launch import packet


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeBackend:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.paused: list[str] = []
        self.resumed: list[str] = []
        self.cancelled: list[str] = []
        self.rebound: list[str] = []
        self.updates: dict[str, deque[ExecutionUpdate]] = defaultdict(deque)

    def start(self, task, budget):
        handle = f"fake:{task.task_id}"
        self.started.append(task.task_id)
        return handle

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

    def rebind(self, task, handle):
        self.rebound.append(f"{task.task_id}:{handle}")


def task_packet(task_id: str, owner: str = "product", *, snapshot: str = "snapshot-1"):
    result = copy.deepcopy(packet(snapshot))
    result["task_id"] = task_id
    result["ownership"]["primary_owner"] = owner
    return result


class SchedulerTests(unittest.TestCase):
    def limits(self, **overrides):
        values = {
            "max_concurrency": 1,
            "max_tasks": 4,
            "max_input_tokens": 2000,
            "max_output_tokens": 1600,
            "max_model_turns": 16,
            "max_elapsed_minutes": 5,
        }
        values.update(overrides)
        return SchedulerLimits(**values)

    def test_routes_fifo_and_supports_pause_resume_and_end(self):
        backend = FakeBackend()
        scheduler = Scheduler(backend, self.limits())
        scheduler.submit(task_packet("TASK-1", "product"))
        scheduler.submit(task_packet("TASK-2", "core"))
        scheduler.submit(task_packet("TASK-3", "teacher"))

        scheduler.pump()
        self.assertEqual(backend.started, ["TASK-1"])
        self.assertEqual(scheduler.get_task("TASK-1").status, "running")

        scheduler.pause("TASK-1", reason="operator pause")
        self.assertEqual(scheduler.get_task("TASK-1").status, "paused")
        scheduler.pump()
        self.assertEqual(backend.started, ["TASK-1"])
        scheduler.resume("TASK-1")

        backend.updates["TASK-1"].append(
            ExecutionUpdate(
                status="completed",
                input_tokens_delta=10,
                output_tokens_delta=5,
                model_turns_delta=0,
                elapsed_seconds_delta=1,
                report_ref="artifacts/task-1-report.json",
                evidence_refs=("evidence/task-1.json",),
            )
        )
        scheduler.pump()
        self.assertEqual(scheduler.get_task("TASK-1").status, "completed")
        scheduler.pump()
        self.assertEqual(backend.started, ["TASK-1", "TASK-2"])
        scheduler.end("TASK-2", reason="canary end")

        scheduler.cancel("TASK-3", reason="canary cleanup")
        self.assertEqual(scheduler.get_task("TASK-3").status, "cancelled")
        self.assertEqual(scheduler.active_count, 0)
        self.assertEqual([event.to_status for event in scheduler.events[:3]], ["queued", "queued", "queued"])
        self.assertEqual(scheduler.events[-1].to_status, "cancelled")

    def test_admission_and_dispatch_respect_whole_scheduler_limits(self):
        backend = FakeBackend()
        scheduler = Scheduler(
            backend,
            self.limits(max_tasks=1, max_input_tokens=20, max_output_tokens=20, max_model_turns=2),
        )
        scheduler.submit(task_packet("TASK-1"))
        with self.assertRaises(BudgetExceeded):
            scheduler.submit(task_packet("TASK-2"))
        scheduler.pump()
        task = scheduler.get_task("TASK-1")
        self.assertEqual(task.status, "running")
        self.assertEqual(task.budget.max_input_tokens, 20)
        self.assertEqual(task.budget.max_output_tokens, 20)
        self.assertEqual(task.budget.max_model_turns, 2)

        backend.updates["TASK-1"].append(
            ExecutionUpdate(
                status="completed",
                input_tokens_delta=21,
                output_tokens_delta=1,
                model_turns_delta=1,
                report_ref="report.json",
            )
        )
        scheduler.pump()
        self.assertEqual(scheduler.get_task("TASK-1").status, "human_required")
        self.assertIn("hard limit", scheduler.get_task("TASK-1").reason)

    def test_elapsed_budget_stops_running_and_queued_tasks(self):
        clock = FakeClock()
        backend = FakeBackend()
        scheduler = Scheduler(
            backend,
            self.limits(max_concurrency=1, max_tasks=2, max_elapsed_minutes=1),
            monotonic_clock=clock,
        )
        scheduler.submit(task_packet("TASK-1"))
        scheduler.submit(task_packet("TASK-2"))
        scheduler.pump()
        clock.advance(60)
        scheduler.pump()
        self.assertEqual(scheduler.get_task("TASK-1").status, "human_required")
        self.assertEqual(scheduler.get_task("TASK-2").status, "human_required")
        self.assertEqual(backend.cancelled, ["TASK-1"])
        self.assertEqual(scheduler.snapshot()["scheduler_status"], "human_required")

    def test_completion_without_evidence_cannot_be_marked_completed(self):
        backend = FakeBackend()
        scheduler = Scheduler(backend, self.limits())
        scheduler.submit(task_packet("TASK-1"))
        scheduler.submit(task_packet("TASK-2", "core"))
        scheduler.pump()
        backend.updates["TASK-1"].append(ExecutionUpdate(status="completed"))
        scheduler.pump()
        self.assertEqual(scheduler.get_task("TASK-1").status, "human_required")
        self.assertIn("lacks evidence", scheduler.get_task("TASK-1").reason)
        scheduler.pump()
        self.assertEqual(scheduler.get_task("TASK-2").status, "queued")
        self.assertEqual(backend.started, ["TASK-1"])

    def test_snapshot_persists_queue_usage_and_append_only_events(self):
        backend = FakeBackend()
        with tempfile.TemporaryDirectory() as raw:
            state_path = Path(raw) / "scheduler.json"
            scheduler = Scheduler(backend, self.limits(), state_path=state_path)
            scheduler.submit(task_packet("TASK-1"))
            scheduler.pump()
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["protocol_version"], 1)
            self.assertEqual(saved["tasks"][0]["status"], "running")
            self.assertEqual(saved["events"][0]["to_status"], "queued")
            self.assertEqual(
                [event["event_seq"] for event in saved["events"]],
                list(range(1, len(saved["events"]) + 1)),
            )

    def test_restore_rebinds_active_task_without_duplicate_start(self):
        backend = FakeBackend()
        with tempfile.TemporaryDirectory() as raw:
            state_path = Path(raw) / "scheduler.json"
            scheduler = Scheduler(backend, self.limits(), state_path=state_path)
            scheduler.submit(task_packet("TASK-1", "product"))
            scheduler.submit(task_packet("TASK-2", "core"))
            scheduler.pump()

            restarted_backend = FakeBackend()
            restored = Scheduler.restore(state_path, restarted_backend)
            self.assertEqual(restarted_backend.started, [])
            self.assertEqual(restarted_backend.rebound, ["TASK-1:fake:TASK-1"])
            self.assertEqual(restored.get_task("TASK-1").status, "running")
            self.assertEqual(restored.get_task("TASK-2").status, "queued")
            self.assertEqual(restored.usage["model_turns"], 1)

            restarted_backend.updates["TASK-1"].append(
                ExecutionUpdate(
                    status="completed",
                    input_tokens_delta=4,
                    output_tokens_delta=3,
                    report_ref="report/task-1.json",
                    evidence_refs=("evidence/task-1.json",),
                )
            )
            restored.pump()
            self.assertEqual(restored.get_task("TASK-1").status, "completed")
            self.assertEqual(restored.get_task("TASK-2").status, "running")
            self.assertEqual(restarted_backend.started, ["TASK-2"])

    def test_restore_without_backend_rebind_fails_closed(self):
        backend = FakeBackend()
        with tempfile.TemporaryDirectory() as raw:
            state_path = Path(raw) / "scheduler.json"
            scheduler = Scheduler(backend, self.limits(), state_path=state_path)
            scheduler.submit(task_packet("TASK-1"))
            scheduler.submit(task_packet("TASK-2", "core"))
            scheduler.pump()

            legacy_backend = object()
            restored = Scheduler.restore(state_path, legacy_backend)  # type: ignore[arg-type]
            task = restored.get_task("TASK-1")
            self.assertEqual(task.status, "human_required")
            self.assertIn("rebind failed", task.reason)
            self.assertEqual(restored.snapshot()["scheduler_status"], "human_required")
            self.assertEqual(restored.snapshot()["reserved"]["model_turns"], 0)
            self.assertEqual(restored.pump(), ())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
