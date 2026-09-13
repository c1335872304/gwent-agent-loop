"""Deterministic tests for the model-free Runner lifecycle contract."""

from __future__ import annotations

import unittest

from .errors import StateTransitionError, ValidationError
from .runner import DeterministicRunner, RunnerRequest, runner_event_dict


def request() -> RunnerRequest:
    return RunnerRequest(
        task_id="GW-RUNNER-001",
        task_revision=1,
        attempt_id="GW-RUNNER-001-OWNER-001",
        role="product",
        profile_revision="product-v1",
        snapshot="file-hash-manifest:base",
        write_scope=("apps/web/**",),
        max_turns=3,
    )


class RunnerLifecycleTests(unittest.TestCase):
    def test_open_wait_interrupt_resume_close_preserves_identity(self) -> None:
        runner = DeterministicRunner()
        opened = runner.open(request())
        self.assertEqual(opened.status, "running")
        self.assertEqual(runner.wait(opened.runner_ref).snapshot, "file-hash-manifest:base")

        interrupted = runner.interrupt(opened.runner_ref, reason="human gate")
        self.assertEqual(interrupted.status, "interrupted")
        resumed = runner.resume(opened.runner_ref, artifact_refs=("artifacts/context.json",))
        self.assertEqual(resumed.status, "running")
        self.assertEqual(resumed.resume_count, 1)
        self.assertEqual(resumed.attempt_id, opened.attempt_id)

        closed = runner.close(opened.runner_ref, report_ref="artifacts/change-report.json")
        self.assertEqual(closed.status, "closed")
        self.assertEqual(closed.report_ref, "artifacts/change-report.json")
        payload = runner_event_dict(closed)
        self.assertEqual(payload["write_scope"], ["apps/web/**"])

    def test_lost_runner_requires_evidence_before_resume(self) -> None:
        runner = DeterministicRunner()
        opened = runner.open(request())
        lost = runner.mark_lost(opened.runner_ref, reason="runner process exited")
        self.assertEqual(lost.status, "lost")
        with self.assertRaises(ValidationError):
            runner.resume(opened.runner_ref, artifact_refs=())
        resumed = runner.resume(opened.runner_ref, artifact_refs=("artifacts/loss.json",))
        self.assertEqual(resumed.status, "running")

    def test_terminal_runner_cannot_resume_or_reopen_attempt(self) -> None:
        runner = DeterministicRunner()
        opened = runner.open(request())
        runner.close(opened.runner_ref, report_ref="artifacts/report.json")
        with self.assertRaises(StateTransitionError):
            runner.resume(opened.runner_ref, artifact_refs=("artifacts/report.json",))
        with self.assertRaises(ValidationError):
            runner.open(request())

    def test_request_requires_scope_and_snapshot(self) -> None:
        invalid = RunnerRequest(
            task_id="GW-RUNNER-001",
            task_revision=1,
            attempt_id="attempt",
            role="product",
            profile_revision="product-v1",
            snapshot="",
            write_scope=(),
            max_turns=1,
        )
        with self.assertRaises(ValidationError):
            DeterministicRunner().open(invalid)


if __name__ == "__main__":
    unittest.main()
