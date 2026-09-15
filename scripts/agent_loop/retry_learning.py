"""Fail-closed learning gates for bounded Agent Loop retries.

The retry gate is deliberately deterministic and model-free.  A retry that
would spend another model call must carry a structured learning delta.  The
delta is recorded in the execution journal, and a successful fallback can be
turned into a candidate-only Lesson without ever injecting it automatically.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .errors import ValidationError


SCHEMA = "agent-loop.retry-learning.v1"
FAILURE_SIGNATURE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
RETRY_ACTIONS = {"RETURN_TO_OWNER", "RETRY_TEST"}
RECOVERY_ONLY_ACTIONS = {"RESUME_SAME_RUNNER"}
LEARNING_KINDS = {
    "environment_fix",
    "fallback_change",
    "packet_change",
    "preflight_change",
    "prompt_change",
    "protocol_fix",
    "test_scope_change",
}
RAW_CONTEXT_KEYS = {
    "conversation",
    "chat_history",
    "raw_transcript",
    "full_transcript",
    "prompt",
    "messages",
}


@dataclass(frozen=True)
class RetryLearningDecision:
    """The result of checking whether a retry contains new information."""

    allowed: bool
    reason: str
    requires_human: bool
    learning_required: bool
    delta_digest: str = ""


def _text(value: Any, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValidationError(f"{label} must not be empty")
    return result


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValidationError(f"{label} must be a list")
    return value


def _reject_raw_context(value: Any, path: str = "retry_learning") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in RAW_CONTEXT_KEYS:
                raise ValidationError(f"{path}.{key} is not allowed")
            _reject_raw_context(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_raw_context(child, f"{path}[{index}]")


def validate_failure_signature(value: Any, label: str = "failure_signature") -> str:
    signature = _text(value, label)
    if not FAILURE_SIGNATURE_RE.fullmatch(signature):
        raise ValidationError(f"{label} must be a redacted sha256 signature")
    return signature


def build_failure_signature(
    *, failure_class: str, action_key: str, error_signature: str
) -> str:
    """Hash failure identity without persisting a raw error or transcript."""

    canonical = json.dumps(
        {
            "action_key": _text(action_key, "action_key"),
            "error_signature": _text(error_signature, "error_signature"),
            "failure_class": _text(failure_class, "failure_class"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_learning_delta(value: Mapping[str, Any]) -> None:
    """Validate the small, non-chat payload required before a retry."""

    if not isinstance(value, Mapping) or value.get("schema") != SCHEMA:
        raise ValidationError("invalid RetryLearningDelta schema")
    _reject_raw_context(value)
    kind = _text(value.get("kind"), "learning_delta.kind")
    if kind not in LEARNING_KINDS:
        raise ValidationError(f"unsupported learning_delta.kind: {kind}")
    _text(value.get("summary"), "learning_delta.summary")
    validate_failure_signature(value.get("failure_signature"), "learning_delta.failure_signature")
    changed_refs = _list(value.get("changed_refs"), "learning_delta.changed_refs")
    if not changed_refs or any(not str(item).strip() for item in changed_refs):
        raise ValidationError("learning_delta.changed_refs must be non-empty")
    preflight_checks = _list(value.get("preflight_checks"), "learning_delta.preflight_checks")
    if not preflight_checks or any(not str(item).strip() for item in preflight_checks):
        raise ValidationError("learning_delta.preflight_checks must be non-empty")
    new_context_refs = _list(value.get("new_context_refs", []), "learning_delta.new_context_refs")
    if any(not str(item).strip() for item in new_context_refs):
        raise ValidationError("learning_delta.new_context_refs contains an empty ref")
    if not isinstance(value.get("preconditions_changed"), bool):
        raise ValidationError("learning_delta.preconditions_changed must be boolean")
    fallback = value.get("fallback_action")
    if not isinstance(fallback, Mapping):
        raise ValidationError("learning_delta.fallback_action must be a mapping")
    for field in ("tool", "operation", "target_scope"):
        _text(fallback.get(field), f"learning_delta.fallback_action.{field}")


def normalise_savings(value: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return measured savings or an explicit no-counterfactual record."""

    if value is None:
        return {
            "status": "unavailable",
            "elapsed_seconds": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "reason": "counterfactual baseline not supplied; no savings claimed",
        }
    if not isinstance(value, Mapping) or value.get("status") not in {"measured", "unavailable"}:
        raise ValidationError("savings status must be measured or unavailable")
    reason = _text(value.get("reason"), "savings.reason")
    try:
        elapsed = float(value.get("elapsed_seconds", 0.0) or 0.0)
        input_tokens = int(value.get("input_tokens", 0) or 0)
        output_tokens = int(value.get("output_tokens", 0) or 0)
    except (TypeError, ValueError) as exc:
        raise ValidationError("savings counters must be numeric") from exc
    if min(elapsed, input_tokens, output_tokens) < 0:
        raise ValidationError("savings counters must be non-negative")
    if value.get("status") == "unavailable" and any((elapsed, input_tokens, output_tokens)):
        raise ValidationError("unavailable savings must have zero counters")
    return {
        "status": str(value["status"]),
        "elapsed_seconds": elapsed,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reason": reason,
    }


def validate_retry_learning_event(value: Mapping[str, Any]) -> None:
    """Validate one journal/manifest retry-learning event."""

    if not isinstance(value, Mapping) or value.get("schema") != SCHEMA:
        raise ValidationError("invalid RetryLearningEvent schema")
    status = _text(value.get("status"), "retry_learning.status")
    if status not in {"retry_allowed", "blocked_no_learning", "recovery_only", "not_retryable"}:
        raise ValidationError("invalid retry_learning.status")
    for field in ("action", "reason", "failure_class"):
        _text(value.get(field), f"retry_learning.{field}")
    for field in ("lesson_created", "lesson_applied"):
        values = _list(value.get(field), f"retry_learning.{field}")
        if any(not str(item).strip() for item in values):
            raise ValidationError(f"retry_learning.{field} contains an empty id")
    normalise_savings(value.get("savings"))
    if status == "retry_allowed":
        validate_failure_signature(value.get("failure_signature"), "retry_learning.failure_signature")
        failure = value.get("failure_action")
        if not isinstance(failure, Mapping):
            raise ValidationError("retry_learning.failure_action must be a mapping")
        for field in ("tool", "operation", "target_scope", "failure_class"):
            _text(failure.get(field), f"retry_learning.failure_action.{field}")
        delta = value.get("learning_delta")
        if not isinstance(delta, Mapping):
            raise ValidationError("retry_learning.learning_delta is required")
        validate_learning_delta(delta)
        if bool(value.get("preconditions_changed", False)) != bool(
            delta["preconditions_changed"]
        ):
            raise ValidationError(
                "retry_learning.preconditions_changed does not match learning_delta"
            )
        digest = learning_delta_digest(delta)
        if str(value.get("learning_delta_digest", "")) != digest:
            raise ValidationError("retry_learning.learning_delta_digest mismatch")
    elif value.get("learning_delta") is not None:
        validate_learning_delta(value["learning_delta"])


def learning_delta_digest(value: Mapping[str, Any]) -> str:
    validate_learning_delta(value)
    canonical = json.dumps(dict(value), sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def evaluate_retry_learning(
    *,
    action: str,
    failure_signature: str,
    learning_delta: Mapping[str, Any] | None,
    previous_failure_signature: str | None = None,
    previous_learning_delta_digest: str | None = None,
    preconditions_changed: bool = False,
    lesson_ids_applied: Sequence[str] = (),
    eligible_lesson_ids: Sequence[str] = (),
) -> RetryLearningDecision:
    """Allow a retry only when it carries a new, auditable learning delta."""

    action = _text(action, "action")
    if action in RECOVERY_ONLY_ACTIONS:
        return RetryLearningDecision(
            allowed=True,
            reason="same-runner recovery is not a new logical retry",
            requires_human=False,
            learning_required=False,
        )
    if action not in RETRY_ACTIONS:
        return RetryLearningDecision(
            allowed=True,
            reason="retry learning gate is not applicable to this terminal action",
            requires_human=False,
            learning_required=False,
        )

    try:
        signature = validate_failure_signature(failure_signature)
    except ValidationError as exc:
        return RetryLearningDecision(False, str(exc), True, True)
    if learning_delta is None:
        return RetryLearningDecision(
            False,
            "retry requires a structured learning_delta",
            True,
            True,
        )
    try:
        validate_learning_delta(learning_delta)
        digest = learning_delta_digest(learning_delta)
    except ValidationError as exc:
        return RetryLearningDecision(False, str(exc), True, True)
    if str(learning_delta["failure_signature"]) != signature:
        return RetryLearningDecision(
            False,
            "learning_delta failure_signature does not match the failed action",
            True,
            True,
            digest,
        )
    if bool(learning_delta["preconditions_changed"]) != bool(preconditions_changed):
        return RetryLearningDecision(
            False,
            "learning_delta preconditions_changed does not match the retry record",
            True,
            True,
            digest,
        )

    applied = {str(item).strip() for item in lesson_ids_applied if str(item).strip()}
    eligible = {str(item).strip() for item in eligible_lesson_ids if str(item).strip()}
    if not applied.issubset(eligible):
        return RetryLearningDecision(
            False,
            "retry references a Lesson that is not confirmed/promoted for injection",
            True,
            True,
            digest,
        )

    previous_signature = str(previous_failure_signature or "").strip()
    previous_digest = str(previous_learning_delta_digest or "").strip()
    if previous_signature == signature and not preconditions_changed:
        if not previous_digest or previous_digest == digest:
            return RetryLearningDecision(
                False,
                "same failure signature and unchanged preconditions require a new learning delta",
                True,
                True,
                digest,
            )
    return RetryLearningDecision(
        True,
        "retry carries a new auditable learning delta",
        False,
        True,
        digest,
    )


def _trace_for_retry_records(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    sequence = 1
    for record in records:
        if record.get("status") != "retry_allowed":
            continue
        delta = record.get("learning_delta")
        failure = record.get("failure_action")
        if not isinstance(delta, Mapping) or not isinstance(failure, Mapping):
            continue
        validate_learning_delta(delta)
        for field in ("tool", "operation", "target_scope", "failure_class"):
            _text(failure.get(field), f"failure_action.{field}")
        trace.append(
            {
                "seq": sequence,
                "tool": failure["tool"],
                "operation": failure["operation"],
                "target_scope": failure["target_scope"],
                "status": "FAIL",
                "failure_class": failure["failure_class"],
                "error": record["failure_signature"],
                "preflight_available": True,
                "preconditions": list(record.get("preconditions", [])),
                "preflight_checks": list(delta["preflight_checks"]),
                "preconditions_changed": bool(record.get("preconditions_changed", False)),
                "elapsed_seconds": float(record.get("failed_elapsed_seconds", 0.0) or 0.0),
                "input_tokens": int(record.get("failed_input_tokens", 0) or 0),
                "output_tokens": int(record.get("failed_output_tokens", 0) or 0),
                "model_turns": int(record.get("failed_model_turns", 0) or 0),
            }
        )
        failed_sequence = sequence
        sequence += 1
        fallback = delta["fallback_action"]
        trace.append(
            {
                "seq": sequence,
                "tool": fallback["tool"],
                "operation": fallback["operation"],
                "target_scope": fallback["target_scope"],
                "status": "PASS",
                "fallback_of": failed_sequence,
                "preconditions_changed": bool(record.get("preconditions_changed", False)),
                "elapsed_seconds": float(record.get("retry_elapsed_seconds", 0.0) or 0.0),
                "input_tokens": int(record.get("retry_input_tokens", 0) or 0),
                "output_tokens": int(record.get("retry_output_tokens", 0) or 0),
                "model_turns": int(record.get("retry_model_turns", 0) or 0),
            }
        )
        sequence += 1
    return trace


def build_retry_experience(
    records: Sequence[Mapping[str, Any]],
    *,
    task_id: str,
    task_revision: int,
    snapshot: str,
    source_refs: Iterable[str],
    domain: str = "loop",
    task_type: str = "retry_recovery",
    changed_paths: Sequence[str] = (),
    contract_versions: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build candidate-only experience from successful retry fallbacks."""

    from .experience import (
        analyze_path,
        build_candidate_lessons,
        build_experience_manifest,
    )

    trace = _trace_for_retry_records(records)
    if not trace:
        raise ValidationError("successful retry records are required for candidate experience")
    refs = [str(ref).strip() for ref in source_refs if str(ref).strip()]
    if not refs:
        raise ValidationError("retry experience requires source_refs")
    versions = dict(contract_versions or {"agent-loop": "retry-learning:v1"})
    analysis = analyze_path(
        trace,
        task_id=_text(task_id, "task_id"),
        task_revision=int(task_revision),
        base_snapshot=_text(snapshot, "snapshot"),
        final_snapshot=_text(snapshot, "snapshot"),
    )
    lessons = build_candidate_lessons(
        analysis,
        domain=_text(domain, "domain"),
        task_type=_text(task_type, "task_type"),
        source_refs=refs,
        changed_paths=changed_paths,
        contract_versions=versions,
    )
    return build_experience_manifest(
        analysis,
        lessons,
        source_refs=refs,
        contract_versions=versions,
    ), lessons


def summarize_retry_learning(role_runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Project per-role retry records into the RunManifest learning section."""

    events: list[dict[str, Any]] = []
    for role_run in role_runs:
        raw = role_run.get("retry_learning", [])
        if not isinstance(raw, list):
            continue
        events.extend(dict(item) for item in raw if isinstance(item, Mapping))
    created = sorted(
        {
            str(lesson_id)
            for event in events
            for lesson_id in event.get("lesson_created", [])
            if str(lesson_id).strip()
        }
    )
    applied = sorted(
        {
            str(lesson_id)
            for event in events
            for lesson_id in event.get("lesson_applied", [])
            if str(lesson_id).strip()
        }
    )
    deltas = [
        dict(event["learning_delta"])
        for event in events
        if isinstance(event.get("learning_delta"), Mapping)
    ]
    measured = [
        event.get("savings", {})
        for event in events
        if isinstance(event.get("savings"), Mapping)
        and event.get("savings", {}).get("status") == "measured"
    ]
    return {
        "schema": SCHEMA,
        "retry_count": sum(event.get("status") == "retry_allowed" for event in events),
        "lesson_created": created,
        "lesson_applied": applied,
        "learning_delta": deltas,
        "savings": {
            "status": "measured" if measured else "unavailable",
            "elapsed_seconds": sum(float(item.get("elapsed_seconds", 0.0) or 0.0) for item in measured),
            "input_tokens": sum(int(item.get("input_tokens", 0) or 0) for item in measured),
            "output_tokens": sum(int(item.get("output_tokens", 0) or 0) for item in measured),
            "reason": "counterfactual baseline supplied"
            if measured
            else "counterfactual baseline not supplied; no savings claimed",
        },
        "events": events,
    }


def validate_retry_learning_summary(value: Mapping[str, Any]) -> None:
    if not isinstance(value, Mapping) or value.get("schema") != SCHEMA:
        raise ValidationError("invalid RunManifest retry_learning schema")
    if int(value.get("retry_count", -1)) < 0:
        raise ValidationError("retry_learning.retry_count must be non-negative")
    for field in ("lesson_created", "lesson_applied", "learning_delta", "events"):
        if not isinstance(value.get(field), list):
            raise ValidationError(f"retry_learning.{field} must be a list")
    for field in ("lesson_created", "lesson_applied"):
        if any(not str(item).strip() for item in value[field]):
            raise ValidationError(f"retry_learning.{field} contains an empty id")
    for delta in value["learning_delta"]:
        if not isinstance(delta, Mapping):
            raise ValidationError("retry_learning.learning_delta items must be mappings")
        validate_learning_delta(delta)
    for event in value["events"]:
        if not isinstance(event, Mapping):
            raise ValidationError("retry_learning.events items must be mappings")
        validate_retry_learning_event(event)
        delta = event.get("learning_delta")
        if isinstance(delta, Mapping) and delta not in value["learning_delta"]:
            raise ValidationError("retry_learning.learning_delta is missing an event delta")
    retry_count = sum(event.get("status") == "retry_allowed" for event in value["events"])
    if int(value.get("retry_count", -1)) != retry_count:
        raise ValidationError("retry_learning.retry_count does not match events")
    savings = value.get("savings")
    normalise_savings(savings)
