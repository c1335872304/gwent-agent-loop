"""RunManifest validation and budget projection checks."""

from __future__ import annotations

from typing import Any, Mapping

from .errors import ValidationError
from .retry_learning import validate_retry_learning_event, validate_retry_learning_summary
from .validate_artifact import validate_artifact_record

RUN_STATUSES = {"created", "running", "blocked", "human_required", "completed", "cancelled", "failed", "superseded"}
ROLE_RUN_STATUSES = {"planned", "running", "closed", "lost", "blocked", "failed"}


def validate_run_manifest(manifest: Mapping[str, Any]) -> None:
    required = {"protocol_version", "run_id", "task_id", "task_revision", "runner", "status", "workspace", "budget", "role_runs", "artifacts", "state_events", "gates", "termination"}
    missing = sorted(required - set(manifest))
    if missing:
        raise ValidationError("RunManifest missing fields: " + ", ".join(missing))
    if manifest["protocol_version"] != 1 or manifest["status"] not in RUN_STATUSES:
        raise ValidationError("RunManifest protocol_version or status is invalid")
    workspace = manifest["workspace"]
    if not isinstance(workspace, Mapping) or not str(workspace.get("base_snapshot", "")).strip():
        raise ValidationError("RunManifest requires a reproducible base_snapshot")
    budget = manifest["budget"]
    if not isinstance(budget, Mapping):
        raise ValidationError("RunManifest.budget must be a mapping")
    pairs = (
        ("role_runs_used", "max_role_runs"),
        ("subtasks_used", "max_subtasks"),
        ("input_tokens_used", "max_input_tokens"),
        ("output_tokens_used", "max_output_tokens"),
        ("model_turns_used", "max_model_turns"),
        ("elapsed_minutes", "max_elapsed_minutes"),
    )
    for used, limit in pairs:
        if int(budget.get(used, -1)) < 0 or int(budget.get(limit, 0)) < 0:
            raise ValidationError(f"RunManifest budget values must be non-negative: {used}/{limit}")
        if int(budget[used]) > int(budget[limit]):
            exhausted = budget.get("exhausted_limits", [])
            if manifest["status"] not in {"blocked", "human_required"} or used not in exhausted:
                raise ValidationError(f"RunManifest budget exhausted: {used} > {limit}")

    exhausted_limits = budget.get("exhausted_limits", [])
    if not isinstance(exhausted_limits, list) or len(set(str(item) for item in exhausted_limits)) != len(exhausted_limits):
        raise ValidationError("RunManifest budget.exhausted_limits must be a list of unique fields")

    role_runs = manifest["role_runs"]
    if not isinstance(role_runs, list):
        raise ValidationError("RunManifest.role_runs must be a list")
    for role_run in role_runs:
        if not isinstance(role_run, Mapping):
            raise ValidationError("each role run must be a mapping")
        if role_run.get("status") not in ROLE_RUN_STATUSES:
            raise ValidationError(f"invalid role run status: {role_run.get('status')}")
        if not str(role_run.get("attempt_id", "")).strip() or not str(role_run.get("profile_id", "")).strip():
            raise ValidationError("role run requires attempt_id and profile_id")
        retry_learning = role_run.get("retry_learning", [])
        if not isinstance(retry_learning, list):
            raise ValidationError("role run retry_learning must be a list")
        for event in retry_learning:
            if not isinstance(event, Mapping):
                raise ValidationError("role run retry_learning events must be mappings")
            validate_retry_learning_event(event)

    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, list):
        raise ValidationError("RunManifest.artifacts must be a list")
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            raise ValidationError("each artifact must be a mapping")
        validate_artifact_record(artifact)

    if "retry_learning" in manifest:
        validate_retry_learning_summary(manifest["retry_learning"])

    events = manifest["state_events"]
    if not isinstance(events, list):
        raise ValidationError("RunManifest.state_events must be a list")
    sequences = [int(event.get("event_seq", -1)) for event in events]
    if sequences != list(range(1, len(sequences) + 1)):
        raise ValidationError("RunManifest state_events must have contiguous event_seq starting at 1")

    if manifest["status"] == "completed":
        if not str(workspace.get("final_snapshot", "")).strip():
            raise ValidationError("completed RunManifest requires workspace.final_snapshot")
        termination = manifest["termination"]
        if not isinstance(termination, Mapping) or not str(termination.get("final_report_ref", "")).strip():
            raise ValidationError("completed RunManifest requires termination.final_report_ref")
        gates = manifest["gates"]
        if not isinstance(gates, list) or any(not isinstance(gate, Mapping) for gate in gates):
            raise ValidationError("RunManifest.gates must be a list of mappings")
        if any(gate.get("status") != "passed" for gate in gates):
            raise ValidationError("completed RunManifest requires every gate to be passed")
        if any(role_run.get("status") != "closed" for role_run in role_runs):
            raise ValidationError("completed RunManifest cannot contain open, lost, blocked, or failed role runs")
