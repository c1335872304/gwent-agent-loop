"""Regression tests for the fail-closed Retry Learning Gate."""

from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from .execution import ExecutionJournal, RunnerExecution
from .errors import ValidationError
from .retry_learning import (
    build_failure_signature,
    build_retry_experience,
    evaluate_retry_learning,
    learning_delta_digest,
    summarize_retry_learning,
    _trace_for_retry_records,
    validate_retry_learning_summary,
)
from .runner import DeterministicRunner, RunnerRequest


def _failure_signature() -> str:
    return build_failure_signature(
        failure_class="CODE_DEFECT",
        action_key="git:broad_patch:docs/current",
        error_signature="index mismatch",
    )


def _learning_delta(signature: str, *, marker: str = "preflight-v1") -> dict[str, object]:
    return {
        "schema": "agent-loop.retry-learning.v1",
        "kind": "preflight_change",
        "summary": "run the narrow scope preflight before the retry",
        "failure_signature": signature,
        "changed_refs": [f"retry-policy/{marker}"],
        "preflight_checks": ["git_status_short", "inspect_declared_scope"],
        "new_context_refs": [f"docs/current/agent-loop/{marker}.md"],
        "preconditions_changed": False,
        "fallback_action": {
            "tool": "git",
            "operation": "explicit_path_patch",
            "target_scope": "docs/current",
        },
    }


def _request() -> RunnerRequest:
    return RunnerRequest(
        task_id="retry-learning-task",
        task_revision=1,
        attempt_id="retry-learning-attempt",
        role="product",
        profile_revision="product-v1",
        snapshot="snapshot-1",
        write_scope=("apps/web/frontend/src/components/TeacherPanel.tsx",),
        max_turns=3,
    )


class RetryLearningGateTests(unittest.TestCase):
    def test_missing_delta_blocks_model_retry(self) -> None:
        decision = evaluate_retry_learning(
            action="RETURN_TO_OWNER",
            failure_signature=_failure_signature(),
            learning_delta=None,
        )
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.requires_human)
        self.assertIn("structured learning_delta", decision.reason)

    def test_same_failure_and_same_delta_is_blocked(self) -> None:
        signature = _failure_signature()
        delta = _learning_delta(signature)
        first = evaluate_retry_learning(
            action="RETURN_TO_OWNER",
            failure_signature=signature,
            learning_delta=delta,
        )
        repeated = evaluate_retry_learning(
            action="RETURN_TO_OWNER",
            failure_signature=signature,
            learning_delta=delta,
            previous_failure_signature=signature,
            previous_learning_delta_digest=learning_delta_digest(delta),
        )
        self.assertTrue(first.allowed)
        self.assertFalse(repeated.allowed)
        self.assertIn("same failure signature", repeated.reason)

    def test_changed_delta_allows_a_bounded_retry(self) -> None:
        signature = _failure_signature()
        first_delta = _learning_delta(signature, marker="preflight-v1")
        second_delta = _learning_delta(signature, marker="preflight-v2")
        decision = evaluate_retry_learning(
            action="RETURN_TO_OWNER",
            failure_signature=signature,
            learning_delta=second_delta,
            previous_failure_signature=signature,
            previous_learning_delta_digest=learning_delta_digest(first_delta),
        )
        self.assertTrue(decision.allowed)
        self.assertFalse(decision.requires_human)

    def test_precondition_change_is_preserved_in_candidate_trace(self) -> None:
        signature = _failure_signature()
        delta = _learning_delta(signature)
        delta["preconditions_changed"] = True
        records = [
            {
                "status": "retry_allowed",
                "failure_signature": signature,
                "failure_action": {
                    "tool": "git",
                    "operation": "broad_patch",
                    "target_scope": "docs/current",
                    "failure_class": "CODE_DEFECT",
                },
                "preconditions": ["clean_scope"],
                "preconditions_changed": True,
                "learning_delta": delta,
                "failed_elapsed_seconds": 2.0,
                "retry_elapsed_seconds": 1.0,
            }
        ]
        trace = _trace_for_retry_records(records)
        self.assertTrue(trace[0]["preconditions_changed"])
        with TemporaryDirectory() as temp_dir:
            manifest, _ = build_retry_experience(
                records,
                task_id="trace-task",
                task_revision=1,
                snapshot="snapshot-1",
                source_refs=[str(Path(temp_dir) / "journal.json")],
            )
        self.assertEqual(manifest["status"], "candidate_only")

    def test_manifest_summary_rejects_event_count_drift(self) -> None:
        signature = _failure_signature()
        delta = _learning_delta(signature)
        event = {
            "schema": "agent-loop.retry-learning.v1",
            "retry_id": "retry-1",
            "status": "retry_allowed",
            "action": "RETURN_TO_OWNER",
            "reason": "changed",
            "failure_class": "CODE_DEFECT",
            "failure_signature": signature,
            "failure_action": {
                "tool": "git",
                "operation": "patch",
                "target_scope": "docs/current",
                "failure_class": "CODE_DEFECT",
            },
            "preconditions_changed": False,
            "learning_delta": delta,
            "learning_delta_digest": learning_delta_digest(delta),
            "lesson_created": [],
            "lesson_applied": [],
            "savings": {
                "status": "unavailable",
                "elapsed_seconds": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "reason": "not measured",
            },
        }
        summary = summarize_retry_learning([{"retry_learning": [event]}])
        summary["retry_count"] = 0
        with self.assertRaises(ValidationError):
            validate_retry_learning_summary(summary)

    def test_unapproved_lesson_cannot_be_applied_on_retry(self) -> None:
        signature = _failure_signature()
        decision = evaluate_retry_learning(
            action="RETRY_TEST",
            failure_signature=signature,
            learning_delta=_learning_delta(signature),
            lesson_ids_applied=["LESSON-CANDIDATE"],
            eligible_lesson_ids=[],
        )
        self.assertFalse(decision.allowed)
        self.assertIn("not confirmed/promoted", decision.reason)

    def test_same_runner_recovery_is_not_forced_to_invent_a_lesson(self) -> None:
        decision = evaluate_retry_learning(
            action="RESUME_SAME_RUNNER",
            failure_signature="",
            learning_delta=None,
        )
        self.assertTrue(decision.allowed)
        self.assertFalse(decision.learning_required)

    def test_execution_gate_journals_block_and_allows_changed_retry(self) -> None:
        signature = _failure_signature()
        request = _request()
        with TemporaryDirectory() as temp_dir:
            journal = ExecutionJournal.for_task(Path(temp_dir), request.task_id, request.attempt_id)
            runner = DeterministicRunner()
            execution = RunnerExecution(runner, request, journal=journal, max_resumes=2)
            execution.open()
            execution.interrupt("first failure")
            blocked = execution.recover(
                artifact_refs=["failure.json"],
                failure_class="CODE_DEFECT",
                failure_signature=signature,
                failure_action={
                    "tool": "git",
                    "operation": "broad_patch",
                    "target_scope": "docs/current",
                    "failure_class": "CODE_DEFECT",
                },
                remaining_budget=3,
            )
            self.assertEqual(blocked.action, "STOP_NO_LEARNING")
            self.assertEqual(execution.record.resume_count, 0)

            # A new attempt must be explicit; the blocked decision itself does
            # not mutate the runner into a retryable state.
            self.assertEqual(journal.read()["retry_learning"][0]["status"], "blocked_no_learning")

    def test_successful_retry_writes_candidate_only_lesson_and_manifest_summary(self) -> None:
        signature = _failure_signature()
        request = _request()
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            journal = ExecutionJournal.for_task(root, request.task_id, request.attempt_id)
            runner = DeterministicRunner()
            execution = RunnerExecution(runner, request, journal=journal, max_resumes=1)
            execution.open()
            execution.interrupt("recoverable code failure")
            delta = _learning_delta(signature)
            decision = execution.recover(
                artifact_refs=["failure.json"],
                failure_class="CODE_DEFECT",
                failure_signature=signature,
                failure_action={
                    "tool": "git",
                    "operation": "broad_patch",
                    "target_scope": "docs/current",
                    "failure_class": "CODE_DEFECT",
                },
                learning_delta=delta,
                remaining_budget=3,
            )
            self.assertEqual(decision.action, "RETURN_TO_OWNER")
            execution.close("test-report.json")

            saved = journal.read()
            event = saved["retry_learning"][0]
            self.assertEqual(event["lesson_creation_status"], "created")
            self.assertEqual(len(event["lesson_created"]), 1)
            experience_dir = root / "tasks" / request.task_id / "experience" / request.attempt_id
            self.assertTrue(experience_dir.is_dir())
            self.assertTrue(
                list((experience_dir / "candidate").glob("LESSON-*.yaml"))
            )
            summary = summarize_retry_learning([execution.record.to_manifest_role_run()])
            self.assertEqual(summary["retry_count"], 1)
            self.assertEqual(summary["savings"]["status"], "unavailable")

    def test_successful_new_runner_can_finalize_prior_retry_learning(self) -> None:
        signature = _failure_signature()
        request = _request()
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_journal = ExecutionJournal.for_task(root, request.task_id, request.attempt_id)
            first = RunnerExecution(DeterministicRunner(), request, journal=first_journal)
            first.open()
            first.interrupt("owner must correct the failure")
            first.recover(
                artifact_refs=["failure.json"],
                failure_class="CODE_DEFECT",
                failure_signature=signature,
                failure_action={
                    "tool": "git",
                    "operation": "broad_patch",
                    "target_scope": "docs/current",
                    "failure_class": "CODE_DEFECT",
                },
                learning_delta=_learning_delta(signature),
                remaining_budget=3,
            )

            next_request = replace(request, attempt_id="retry-learning-attempt-2")
            next_journal = ExecutionJournal.for_task(root, next_request.task_id, next_request.attempt_id)
            next_execution = RunnerExecution(
                DeterministicRunner(),
                next_request,
                journal=next_journal,
                retry_learning_context={"prior_retry_learning": first.record.retry_learning},
            )
            next_execution.open()
            next_execution.close("test-report-2.json")

            event = next_journal.read()["retry_learning"][0]
            self.assertEqual(event["lesson_creation_status"], "created")
            self.assertTrue(
                list(
                    (
                        root
                        / "tasks"
                        / request.task_id
                        / "experience"
                        / next_request.attempt_id
                        / "candidate"
                    ).glob("LESSON-*.yaml")
                )
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
