import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.agent_loop.execution import (
    ExecutionJournal,
    ExecutionRecordError,
    RunnerExecution,
    bind_task_execution,
)
from scripts.agent_loop.persistence import TaskStore
from scripts.agent_loop.runner import DeterministicRunner, RunnerRequest


def make_request() -> RunnerRequest:
    return RunnerRequest(
        task_id="pilot-002",
        task_revision=1,
        attempt_id="attempt-1",
        role="product",
        profile_revision="product-v1",
        snapshot="snap-001",
        write_scope=("apps/web/frontend/src/pages/GamePage.tsx",),
        max_turns=3,
    )


class TestRunnerExecution(unittest.TestCase):
    def test_execution_binds_identity_and_persists_each_transition(self):
        request = make_request()
        with TemporaryDirectory() as temp_dir:
            journal = ExecutionJournal.for_task(
                Path(temp_dir), request.task_id, request.attempt_id
            )
            execution = RunnerExecution(
                DeterministicRunner(), request, journal=journal, max_resumes=2
            )

            execution.open()
            execution.wait()
            execution.interrupt("needs verification")
            execution.resume(["change-report.yaml"])
            execution.close("test-report.yaml")

            saved = journal.read()
            self.assertEqual(saved["schema"], "agent-loop.execution-record.v1")
            self.assertEqual(saved["identity"]["snapshot"], "snap-001")
            self.assertEqual(
                saved["identity"]["write_scope"], list(request.write_scope)
            )
            self.assertEqual(saved["status"], "closed")
            self.assertEqual(len(saved["events"]), 5)
            self.assertEqual(saved["artifact_refs"], ["change-report.yaml"])
            self.assertEqual(saved["report_ref"], "test-report.yaml")
            role_run = execution.record.to_manifest_role_run()
            self.assertEqual(role_run["status"], "closed")
            self.assertEqual(role_run["base_snapshot"], "snap-001")
            self.assertEqual(role_run["profile_id"], "product")
            self.assertEqual(role_run["artifact_refs"], [
                "change-report.yaml",
                "test-report.yaml",
            ])

    def test_task_store_binding_checks_packet_revision(self):
        request = make_request()
        with TemporaryDirectory() as temp_dir:
            store = TaskStore(Path(temp_dir) / "tasks")
            store.initialize(request.task_id, packet_revision=1)
            execution = bind_task_execution(
                DeterministicRunner(), store, request
            )
            execution.open()
            self.assertTrue(execution.journal.path.is_file())

            wrong_revision = replace(request, task_revision=2)
            with self.assertRaisesRegex(ExecutionRecordError, "packet revision"):
                bind_task_execution(DeterministicRunner(), store, wrong_revision)

    def test_execution_rejects_event_from_a_different_snapshot(self):
        class WrongSnapshotAdapter:
            def __init__(self):
                self.inner = DeterministicRunner()

            def open(self, request):
                return replace(self.inner.open(request), snapshot="other-snapshot")

        execution = RunnerExecution(WrongSnapshotAdapter(), make_request())
        with self.assertRaisesRegex(ExecutionRecordError, "identity mismatch"):
            execution.open()

    def test_budget_failure_happens_before_runner_open(self):
        class CountingRunner(DeterministicRunner):
            def __init__(self):
                super().__init__()
                self.open_calls = 0

            def open(self, request):
                self.open_calls += 1
                return super().open(request)

        runner = CountingRunner()

        def reject(_request):
            raise ExecutionRecordError("budget exhausted")

        execution = RunnerExecution(runner, make_request(), budget_reserve=reject)
        with self.assertRaisesRegex(ExecutionRecordError, "budget exhausted"):
            execution.open()
        self.assertEqual(runner.open_calls, 0)

    def test_resume_limit_is_bounded(self):
        request = make_request()
        execution = RunnerExecution(DeterministicRunner(), request, max_resumes=1)
        execution.open()
        execution.interrupt("first stop")
        execution.resume(["first-report.yaml"])
        with self.assertRaisesRegex(ExecutionRecordError, "resume limit"):
            execution.resume(["second-report.yaml"])

    def test_repeated_running_polls_do_not_exhaust_lifecycle_event_budget(self):
        execution = RunnerExecution(DeterministicRunner(), make_request())
        execution.open()
        for _ in range(64):
            execution.wait()
        self.assertEqual(len(execution.record.events), 2)
        self.assertEqual(execution.record.events[-1]["status"], "running")

    def test_recovery_decision_is_journaled_before_bounded_resume(self):
        request = make_request()
        with TemporaryDirectory() as temp_dir:
            journal = ExecutionJournal.for_task(
                Path(temp_dir), request.task_id, request.attempt_id
            )
            runner = DeterministicRunner()
            execution = RunnerExecution(runner, request, journal=journal, max_resumes=1)
            opened = execution.open()
            lost = runner.mark_lost(opened.runner_ref, reason="injected runner loss")
            execution._accept(lost)

            decision = execution.recover(
                artifact_refs=["runner-loss.json"],
                failure_class="RUNNER_FAILURE",
                remaining_budget=3,
            )

            self.assertEqual(decision.action, "RESUME_SAME_RUNNER")
            self.assertEqual(execution.record.resume_count, 1)
            saved = journal.read()
            self.assertEqual(saved["recovery_decisions"][0]["action"], "RESUME_SAME_RUNNER")
            self.assertTrue(saved["recovery_decisions"][0]["persisted_before_action"])
            self.assertEqual(saved["events"][-1]["event"], "resumed")


if __name__ == "__main__":
    unittest.main()
