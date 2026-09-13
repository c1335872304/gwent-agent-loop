"""Validation for auditable TestReport results."""

from __future__ import annotations

from typing import Any, Mapping

from .errors import ValidationError


_OVERALL = {"PASS", "FAIL", "BLOCKED", "INCONCLUSIVE"}
_RESULT_STATUS = {"PASS", "FAIL", "NOT_RUN", "INCONCLUSIVE"}
_FAILURES = {
    "CODE_DEFECT",
    "CONTRACT_GAP",
    "ENVIRONMENT_FAILURE",
    "DOCKER_FAILURE",
    "PERMISSION_REQUIRED",
    "FLAKY_TEST",
    "PROTOCOL_FAILURE",
    "BUDGET_EXHAUSTED",
    "EXTERNAL_DEPENDENCY",
}


def _required_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationError(f"TestReport requires {label}")
    return text


def _within(path: str, roots: list[str]) -> bool:
    normalized = path.strip("/")
    for raw_root in roots:
        root = str(raw_root).strip("/")
        if root in {"declared test scope only", "task scope"}:
            return True
        if normalized == root or normalized.startswith(root + "/"):
            return True
    return False


def validate_test_report(
    report: Mapping[str, Any],
    *,
    plan: Any | None = None,
) -> None:
    """Reject false PASS and reports that cannot be reproduced."""
    required = {
        "task_id",
        "packet_revision",
        "tested_snapshot",
        "tester",
        "overall",
        "results",
        "environment",
        "failures",
        "manual_checks",
    }
    missing = sorted(required - set(report))
    if missing:
        raise ValidationError("TestReport missing fields: " + ", ".join(missing))
    task_id = _required_text(report["task_id"], "task_id")
    tested_snapshot = _required_text(report["tested_snapshot"], "tested_snapshot")
    tester = _required_text(report["tester"], "tester")
    if tester != "test-verification":
        raise ValidationError("TestReport tester must be test-verification")
    overall = str(report["overall"])
    if overall not in _OVERALL:
        raise ValidationError(f"invalid TestReport overall: {overall}")

    results = report["results"]
    if not isinstance(results, list) or not results:
        raise ValidationError("TestReport results must be a non-empty list")
    result_statuses: list[str] = []
    for index, raw_result in enumerate(results):
        if not isinstance(raw_result, Mapping):
            raise ValidationError(f"TestReport result {index} must be a mapping")
        for field in ("command", "cwd", "status", "evidence_ref"):
            _required_text(raw_result.get(field), f"results[{index}].{field}")
        status = str(raw_result["status"])
        if status not in _RESULT_STATUS:
            raise ValidationError(f"invalid TestReport result status: {status}")
        result_statuses.append(status)
        exit_code = raw_result.get("exit_code")
        if status == "PASS" and exit_code != 0:
            raise ValidationError("PASS result requires exit_code 0")
        if status == "FAIL" and (exit_code is None or int(exit_code) == 0):
            raise ValidationError("FAIL result requires a non-zero exit_code")

    environment = report["environment"]
    if not isinstance(environment, Mapping):
        raise ValidationError("TestReport.environment must be a mapping")
    runner = _required_text(environment.get("runner"), "environment.runner")
    missing_dependencies = environment.get("missing_dependencies", [])
    if not isinstance(missing_dependencies, list):
        raise ValidationError("TestReport missing_dependencies must be a list")

    failures = report["failures"]
    if not isinstance(failures, list):
        raise ValidationError("TestReport failures must be a list")
    for index, failure in enumerate(failures):
        if not isinstance(failure, Mapping):
            raise ValidationError(f"TestReport failure {index} must be a mapping")
        classification = str(failure.get("classification", ""))
        if classification not in _FAILURES:
            raise ValidationError(f"invalid TestReport failure class: {classification}")
        _required_text(failure.get("reproduction"), f"failures[{index}].reproduction")
        _required_text(failure.get("likely_owner"), f"failures[{index}].likely_owner")

    changed_test_paths = report.get("changed_test_paths", [])
    if not isinstance(changed_test_paths, list):
        raise ValidationError("TestReport changed_test_paths must be a list")

    docker = environment.get("docker", {})
    if not isinstance(docker, Mapping):
        raise ValidationError("TestReport.environment.docker must be a mapping")
    docker_used = bool(docker.get("used", False))
    if docker_used:
        if runner != "docker":
            raise ValidationError("Docker evidence requires environment.runner=docker")
        if not docker.get("compose_files"):
            raise ValidationError("Docker evidence requires compose_files")
        if str(docker.get("health", "")) != "passed":
            raise ValidationError("Docker evidence requires passed health")
        if str(docker.get("cleanup", "")) != "complete":
            raise ValidationError("Docker evidence requires complete cleanup")
        if not docker.get("evidence_refs"):
            raise ValidationError("Docker evidence requires evidence_refs")

    if overall == "PASS":
        if any(status != "PASS" for status in result_statuses):
            raise ValidationError("PASS TestReport cannot contain non-PASS results")
        if failures or missing_dependencies:
            raise ValidationError("PASS TestReport cannot contain failures or missing dependencies")
    if overall == "FAIL" and not failures and "FAIL" not in result_statuses:
        raise ValidationError("FAIL TestReport requires a failure result or classification")

    if plan is not None:
        if task_id != plan.task_id or int(report["packet_revision"]) != plan.task_revision:
            raise ValidationError("TestReport task identity does not match VerificationPlan")
        if tested_snapshot != plan.snapshot:
            raise ValidationError("TestReport snapshot does not match VerificationPlan")
        allowed_commands = {str(command["command"]) for command in plan.commands}
        actual_commands = {str(result["command"]) for result in results}
        if not actual_commands.issubset(allowed_commands):
            raise ValidationError("TestReport contains a command outside VerificationPlan")
        if allowed_commands - actual_commands:
            raise ValidationError("TestReport omitted a planned command")
        if plan.docker_enabled and not docker_used:
            raise ValidationError("VerificationPlan requires Docker evidence")
        if not plan.docker_enabled and docker_used:
            raise ValidationError("TestReport used Docker without VerificationPlan approval")
        for path in changed_test_paths:
            if not _within(str(path), list(plan.test_write_roots)):
                raise ValidationError(f"TestReport changed test path is out of scope: {path}")
