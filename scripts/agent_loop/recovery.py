"""Deterministic recovery policy for the Agent Loop.

This module decides whether a failed step may continue.  It never launches a
model, a child task, or Docker.  The caller must execute the returned action.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RecoveryDecision:
    action: str
    reason: str
    consumes_model_call: bool
    terminal: bool
    requires_human: bool


def decide_recovery(
    *,
    status: str,
    failure_class: str | None = None,
    attempts_used: int = 0,
    max_attempts: int = 2,
    resumes_used: int = 0,
    max_resumes: int = 2,
    remaining_budget: int = 1,
    report_valid: bool = True,
    external_runner_available: bool = True,
) -> RecoveryDecision:
    """Return a bounded next action for a terminal or interrupted step."""

    if attempts_used < 0 or resumes_used < 0:
        raise ValueError("attempt counters must be non-negative")
    if max_attempts < 0 or max_resumes < 0:
        raise ValueError("recovery limits must be non-negative")

    if status == "PASS":
        return RecoveryDecision("COMPLETE", "verified pass", False, True, False)
    if status == "CANCELLED":
        return RecoveryDecision("STOP", "task was cancelled", False, True, False)
    if not report_valid:
        return RecoveryDecision(
            "WAIT_HUMAN",
            "test report is incomplete or inconsistent",
            False,
            True,
            True,
        )
    if remaining_budget <= 0:
        return RecoveryDecision(
            "STOP_BUDGET",
            "model-call budget is exhausted",
            False,
            True,
            True,
        )

    if status == "LOST":
        if not external_runner_available:
            return RecoveryDecision(
                "WAIT_HUMAN",
                "runner is lost and no approved transport is available",
                False,
                True,
                True,
            )
        if resumes_used >= max_resumes:
            return RecoveryDecision(
                "WAIT_HUMAN",
                "resume limit reached for the same runner",
                False,
                True,
                True,
            )
        return RecoveryDecision(
            "RESUME_SAME_RUNNER",
            "runner loss is recoverable within the resume limit",
            True,
            False,
            False,
        )

    if failure_class in {"ENVIRONMENT_FAILURE", "DOCKER_FAILURE"}:
        return RecoveryDecision(
            "WAIT_HUMAN",
            "environment failure must be repaired before another model call",
            False,
            True,
            True,
        )
    if failure_class in {"PERMISSION_REQUIRED", "EXTERNAL_DEPENDENCY"}:
        return RecoveryDecision(
            "WAIT_HUMAN",
            "external approval or dependency is required",
            False,
            True,
            True,
        )
    if failure_class == "PROTOCOL_FAILURE":
        return RecoveryDecision(
            "STOP",
            "control-plane protocol failure is not safe to retry automatically",
            False,
            True,
            False,
        )

    if attempts_used >= max_attempts:
        return RecoveryDecision(
            "WAIT_HUMAN",
            "attempt limit reached without a verified pass",
            False,
            True,
            True,
        )
    if failure_class == "FLAKY_TEST":
        return RecoveryDecision(
            "RETRY_TEST",
            "flaky test may be retried within the attempt limit",
            False,
            False,
            False,
        )
    return RecoveryDecision(
        "RETURN_TO_OWNER",
        "owner must address the reported failure within the attempt limit",
        True,
        False,
        False,
    )
