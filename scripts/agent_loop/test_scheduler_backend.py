"""Regression tests for the RunnerExecution-backed Scheduler backend."""

from __future__ import annotations

from dataclasses import replace
import copy
import unittest

from .execution import RunnerExecution
from .runner import DeterministicRunner
from .scheduler import Scheduler, SchedulerLimits
from .scheduler_backend import MultiRoleRunnerExecutionBackend, RunnerExecutionBackend
from .test_launch import build, packet, profile


class LifecycleAdapter:
    def __init__(self) -> None:
        self.runner = DeterministicRunner()
        self.phase = "running"

    def open(self, request):
        return self.runner.open(request)

    def wait(self, runner_ref):
        event = self.runner.wait(runner_ref)
        if self.phase == "complete":
            return replace(
                event,
                status="interrupted",
                report_ref="artifacts/change-report.json",
                final_snapshot="snapshot-final",
            )
        return event

    def interrupt(self, runner_ref, *, reason):
        return self.runner.interrupt(runner_ref, reason=reason)

    def resume(self, runner_ref, *, artifact_refs):
        return self.runner.resume(runner_ref, artifact_refs=artifact_refs)

    def close(self, runner_ref, *, report_ref):
        return replace(
            self.runner.close(runner_ref, report_ref=report_ref),
            final_snapshot="snapshot-final",
        )


class SchedulerBackendTests(unittest.TestCase):
    def multi_role_spec(self, owner: str, task_id: str):
        task = copy.deepcopy(packet())
        task["task_id"] = task_id
        task["ownership"]["primary_owner"] = owner
        context = {
            "task_id": task_id,
            "packet_revision": 1,
            "context_snapshot": "snapshot-1",
            "context_floor_refs": [{"path": "AGENTS.md"}],
            "fact_source_graph": [{"path": "apps/web", "why": "target"}],
            "fact_ledger": [],
            "lessons": {"relevant_refs": []},
        }
        role_profile = copy.deepcopy(profile())
        role_profile["agent_id"] = owner
        role_profile["profile_id"] = f"{owner}-owner-v1"
        role_profile["authority"]["boundary"] = owner
        return build(
            task_packet=task,
            context_brief=context,
            profile=role_profile,
            task_packet_ref=f"tasks/{task_id}.yaml",
            context_brief_ref=f"context/{task_id}.yaml",
            profile_ref=f"profiles/{owner}.yaml",
            attempt_id=f"attempt-{task_id.lower()}",
        )

    def test_runner_lifecycle_maps_to_scheduler_update_and_evidence(self):
        adapter = LifecycleAdapter()
        spec = build()
        backend = RunnerExecutionBackend(
            lambda _task, _budget: RunnerExecution(adapter, spec.request),
            resume_artifact_factory=lambda _task: ("artifacts/pause.json",),
        )
        scheduler = Scheduler(
            backend,
            SchedulerLimits(
                max_concurrency=1,
                max_tasks=1,
                max_input_tokens=1000,
                max_output_tokens=800,
                max_model_turns=4,
                max_elapsed_minutes=5,
            ),
        )
        task = packet()
        scheduler.submit(task)
        scheduler.pump()
        scheduler.pause("TASK-1", reason="backend pause")
        scheduler.resume("TASK-1")
        adapter.phase = "complete"
        scheduler.pump()

        result = scheduler.get_task("TASK-1")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.report_ref, "artifacts/change-report.json")
        self.assertEqual(result.final_snapshot, "snapshot-final")
        self.assertEqual(result.evidence_refs, ("artifacts/change-report.json",))
        self.assertEqual(result.resume_count, 1)
        self.assertEqual(scheduler.usage["input_tokens"], 0)
        self.assertEqual(scheduler.usage["model_turns"], 2)
        self.assertEqual(
            [event.to_status for event in scheduler.events],
            ["queued", "running", "paused", "running", "completed"],
        )

    def test_missing_resume_artifact_factory_is_a_safe_failure(self):
        adapter = LifecycleAdapter()
        spec = build()
        backend = RunnerExecutionBackend(
            lambda _task, _budget: RunnerExecution(adapter, spec.request)
        )
        scheduler = Scheduler(
            backend,
            SchedulerLimits(1, 1, 1000, 800, 4, 5),
        )
        scheduler.submit(packet())
        scheduler.pump()
        scheduler.pause("TASK-1", reason="backend pause")
        result = scheduler.resume("TASK-1")
        self.assertEqual(result.status, "human_required")
        self.assertIn("artifact factory", result.reason)

    def test_multi_role_backend_routes_explicit_factories(self):
        product_spec = self.multi_role_spec("product", "PRODUCT-TASK")
        core_spec = self.multi_role_spec("core", "CORE-TASK")
        adapters = {"product": LifecycleAdapter(), "core": LifecycleAdapter()}
        specs = {"product": product_spec, "core": core_spec}
        created: list[str] = []

        def factory(task, _budget):
            created.append(task.owner)
            return RunnerExecution(adapters[task.owner], specs[task.owner].request)

        backend = MultiRoleRunnerExecutionBackend(
            {"product": factory, "core": factory},
            resume_artifact_factory=lambda _task: ("artifacts/resume.json",),
        )
        scheduler = Scheduler(backend, SchedulerLimits(1, 2, 1000, 800, 8, 5))
        scheduler.submit(product_spec.task_packet)
        scheduler.submit(core_spec.task_packet)
        scheduler.pump()
        self.assertEqual(created, ["product"])
        adapters["product"].phase = "complete"
        scheduler.pump()
        self.assertEqual(created, ["product", "core"])
        adapters["core"].phase = "complete"
        scheduler.pump()
        self.assertEqual(scheduler.get_task("PRODUCT-TASK").status, "completed")
        self.assertEqual(scheduler.get_task("CORE-TASK").status, "completed")
        self.assertEqual(
            [scheduler.get_task(task_id).owner for task_id in ("PRODUCT-TASK", "CORE-TASK")],
            ["product", "core"],
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
