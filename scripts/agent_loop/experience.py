"""Deterministic E0-E1 experience extraction for the Agent Loop.

This module analyzes structured execution evidence only.  It never reads raw
conversation text, calls a model, injects context, or promotes a rule.  A
single failed action becomes an avoidance candidate only when its trigger and
successful fallback are sufficiently explicit to be audited later.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.agent_loop.errors import ValidationError
    from scripts.agent_loop.manifest import validate_run_manifest
    from scripts.agent_loop.report_validation import validate_test_report
else:
    from .errors import ValidationError
    from .manifest import validate_run_manifest
    from .report_validation import validate_test_report

try:
    import yaml
except ModuleNotFoundError as exc:  # pragma: no cover - environment-specific
    raise RuntimeError("experience extraction requires PyYAML") from exc


SCHEMA_VERSION = 1
PATH_ANALYSIS_SCHEMA = "agent-loop.path-analysis.v1"
DETOUR_SCHEMA = "agent-loop.detour.v1"
LESSON_SCHEMA = "agent-loop.lesson.v1"
EXPERIENCE_MANIFEST_SCHEMA = "agent-loop.experience-manifest.v1"

SUCCESS_STATUSES = {"pass", "passed", "success", "succeeded", "ok", "closed"}
FAILURE_STATUSES = {"fail", "failed", "error", "blocked", "inconclusive"}
RAW_CONTEXT_KEYS = {
    "conversation",
    "chat_history",
    "raw_transcript",
    "full_transcript",
    "prompt",
    "messages",
}
ALLOWED_DETOUR_CLASSES = {
    "avoidable_detour",
    "necessary_exploration",
    "unclassified_failure",
}
ALLOWED_LESSON_STATUSES = {"candidate", "confirmed", "promoted", "rejected", "deprecated"}


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{label} must be a mapping")
    return value


def _require_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationError(f"{label} must not be empty")
    return text


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValidationError(f"{label} must be a list")
    return value


def reject_raw_context(value: Any, path: str = "experience") -> None:
    """Reject fields that would turn an evidence record into chat memory."""

    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in RAW_CONTEXT_KEYS:
                raise ValidationError(f"{path}.{key} is not allowed in experience evidence")
            reject_raw_context(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_raw_context(child, f"{path}[{index}]")


def _redacted_hash(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"(?i)(token|cookie|password|secret|authorization)\s*[:=]\s*\S+", r"\1:<redacted>", text)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _status(event: Mapping[str, Any]) -> str:
    raw = str(event.get("status", event.get("result", ""))).strip().lower()
    if raw in SUCCESS_STATUSES:
        return "PASS"
    if raw in FAILURE_STATUSES:
        return "FAIL"
    if "exit_code" in event:
        try:
            return "PASS" if int(event["exit_code"]) == 0 else "FAIL"
        except (TypeError, ValueError):
            pass
    return "UNKNOWN"


def _action_key(event: Mapping[str, Any]) -> tuple[str, str, str]:
    tool = str(event.get("tool", event.get("tool_name", "unknown"))).strip() or "unknown"
    operation = str(event.get("operation", event.get("action", ""))).strip()
    command = str(event.get("command", "")).strip()
    if command:
        operation = operation or "command"
        operation = f"{operation}#sha256:{hashlib.sha256(command.encode('utf-8')).hexdigest()[:16]}"
    operation = operation or "unknown"
    target = str(event.get("target_scope", event.get("target", ""))).strip()
    return tool, operation, target


def _conditions(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        result: list[str] = []
        for key in sorted(value):
            if not value[key]:
                continue
            key_text = str(key)
            if re.search(r"(?i)(token|cookie|password|secret|authorization)", key_text):
                result.append(f"{key_text}=<redacted>")
            else:
                result.append(f"{key_text}={_redact_condition(str(value[key]))}")
        return result
    if isinstance(value, list):
        return [_redact_condition(str(item).strip()) for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [_redact_condition(text)] if text else []


def _redact_condition(text: str) -> str:
    return re.sub(
        r"(?i)(token|cookie|password|secret|authorization)\s*[:=]\s*\S+",
        r"\1:<redacted>",
        text,
    )


def _normalise_event(raw: Mapping[str, Any], index: int) -> dict[str, Any] | None:
    reject_raw_context(raw, f"trace[{index}]")
    tool, operation, target = _action_key(raw)
    if tool == "unknown" and operation == "unknown":
        return None
    try:
        sequence = int(raw.get("seq", raw.get("event_seq", index + 1)))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"trace[{index}].seq must be an integer") from exc
    if sequence < 1:
        raise ValidationError(f"trace[{index}].seq must be positive")

    status = _status(raw)
    try:
        elapsed = float(raw.get("elapsed_seconds", raw.get("duration_seconds", 0)) or 0)
        input_tokens = int(raw.get("input_tokens", 0) or 0)
        output_tokens = int(raw.get("output_tokens", 0) or 0)
        model_turns = int(raw.get("model_turns", raw.get("turns", 0)) or 0)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"trace[{index}] counters must be numeric") from exc
    if min(elapsed, input_tokens, output_tokens, model_turns) < 0:
        raise ValidationError(f"trace[{index}] counters must be non-negative")

    failure_class = str(raw.get("failure_class", raw.get("error_class", "none"))).strip() or "none"
    return {
        "seq": sequence,
        "tool": tool,
        "operation": operation,
        "target_scope": target,
        "action_key": f"{tool}:{operation}:{target}",
        "status": status,
        "failure_class": failure_class,
        "error_signature_hash": _redacted_hash(raw.get("error", raw.get("reason", ""))) if status == "FAIL" else "",
        "preflight_available": bool(raw.get("preflight_available", False)),
        "preconditions": _conditions(raw.get("preconditions", [])),
        "preflight_checks": _conditions(raw.get("preflight_checks", [])),
        "preconditions_changed": bool(raw.get("preconditions_changed", False)),
        "necessary_exploration": bool(raw.get("necessary_exploration", False)),
        "explicit_avoidable": raw.get("avoidable") if isinstance(raw.get("avoidable"), bool) else None,
        "fallback_of": raw.get("fallback_of"),
        "resolution_hint": str(raw.get("resolution_hint", "")).strip(),
        "elapsed_seconds": elapsed,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "model_turns": model_turns,
    }


def normalise_trace(trace: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(trace, Sequence) or isinstance(trace, (str, bytes)):
        raise ValidationError("execution trace must be a list")
    events: list[dict[str, Any]] = []
    ignored = 0
    for index, raw in enumerate(trace):
        item = _require_mapping(raw, f"trace[{index}]")
        event = _normalise_event(item, index)
        if event is None:
            ignored += 1
        else:
            events.append(event)
    sequences = [event["seq"] for event in events]
    if len(set(sequences)) != len(sequences):
        raise ValidationError("execution trace seq values must be unique")
    events.sort(key=lambda item: item["seq"])
    return events, ignored


def _find_fallback(events: list[dict[str, Any]], failed_index: int) -> dict[str, Any] | None:
    failed = events[failed_index]
    for candidate in events[failed_index + 1 :]:
        if candidate["status"] != "PASS" or candidate["action_key"] == failed["action_key"]:
            continue
        fallback_of = candidate.get("fallback_of")
        if str(fallback_of) in {str(failed["seq"]), str(failed_index)}:
            return candidate
        hint = failed["resolution_hint"].lower()
        candidate_label = f"{candidate['tool']}:{candidate['operation']}".lower()
        if hint and (hint == candidate["tool"].lower() or hint == candidate["operation"].lower() or hint in candidate_label):
            return candidate
    return None


def _has_repeated_action(events: list[dict[str, Any]], failed_index: int) -> bool:
    failed = events[failed_index]
    return any(
        candidate["action_key"] == failed["action_key"]
        and not candidate["preconditions_changed"]
        for candidate in events[failed_index + 1 :]
    )


def analyze_path(
    trace: Sequence[Mapping[str, Any]],
    *,
    task_id: str,
    task_revision: int = 1,
    planned_actions: Sequence[Mapping[str, Any]] | None = None,
    base_snapshot: str = "",
    final_snapshot: str = "",
) -> dict[str, Any]:
    """Produce PathAnalysis and DetourRecords without model inference."""

    task_id = _require_text(task_id, "task_id")
    if int(task_revision) < 1:
        raise ValidationError("task_revision must be positive")
    events, ignored = normalise_trace(trace)
    detours: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        if event["status"] != "FAIL":
            continue
        fallback = _find_fallback(events, index)
        repeated = _has_repeated_action(events, index)
        if event["explicit_avoidable"] is True:
            classification = "avoidable_detour"
        elif event["necessary_exploration"]:
            classification = "necessary_exploration"
        elif repeated or (event["preflight_available"] and fallback is not None):
            classification = "avoidable_detour"
        else:
            classification = "unclassified_failure"

        resolution: dict[str, Any] = {}
        if fallback is not None:
            resolution = {
                "resolved_by_seq": fallback["seq"],
                "tool": fallback["tool"],
                "operation": fallback["operation"],
                "target_scope": fallback["target_scope"],
                "verified_fallback": True,
            }
        detours.append(
            {
                "schema": DETOUR_SCHEMA,
                "detour_id": f"{task_id}-detour-{len(detours) + 1}",
                "task_id": task_id,
                "task_revision": int(task_revision),
                "failed_seq": event["seq"],
                "failed_action": {
                    "tool": event["tool"],
                    "operation": event["operation"],
                    "target_scope": event["target_scope"],
                    "failure_class": event["failure_class"],
                    "error_signature_hash": event["error_signature_hash"],
                },
                "classification": classification,
                "repeated_action": repeated,
                "trigger": {
                    "preflight_available": event["preflight_available"],
                    "preconditions": list(event["preconditions"]),
                    "preflight_checks": list(event["preflight_checks"]),
                    "preconditions_changed": event["preconditions_changed"],
                },
                "impact": {
                    "extra_attempts": 1,
                    "elapsed_seconds": event["elapsed_seconds"],
                    "input_tokens": event["input_tokens"],
                    "output_tokens": event["output_tokens"],
                    "model_turns": event["model_turns"],
                },
                "resolution": resolution,
            }
        )

    avoidable = [item for item in detours if item["classification"] == "avoidable_detour"]
    necessary = [item for item in detours if item["classification"] == "necessary_exploration"]
    successful_fallbacks = [item for item in detours if item["resolution"].get("verified_fallback")]
    planned_count = len(planned_actions) if planned_actions is not None else len(events)
    return {
        "schema": PATH_ANALYSIS_SCHEMA,
        "task_id": task_id,
        "task_revision": int(task_revision),
        "base_snapshot": str(base_snapshot or ""),
        "final_snapshot": str(final_snapshot or ""),
        "counts": {
            "planned_steps": planned_count,
            "actual_steps": len(events),
            "ignored_events": ignored,
            "failed_actions": len(detours),
            "avoidable_detours": len(avoidable),
            "necessary_explorations": len(necessary),
            "successful_fallbacks": len(successful_fallbacks),
            "repeated_actions": sum(bool(item["repeated_action"]) for item in detours),
            "extra_tool_calls": len(avoidable),
            "extra_model_turns": sum(int(item["impact"]["model_turns"]) for item in avoidable),
            "extra_elapsed_seconds": sum(float(item["impact"]["elapsed_seconds"]) for item in avoidable),
            "extra_input_tokens": sum(int(item["impact"]["input_tokens"]) for item in avoidable),
            "extra_output_tokens": sum(int(item["impact"]["output_tokens"]) for item in avoidable),
        },
        "detours": detours,
        "successful_path": [
            {
                "seq": event["seq"],
                "tool": event["tool"],
                "operation": event["operation"],
                "target_scope": event["target_scope"],
            }
            for event in events
            if event["status"] == "PASS"
        ],
    }


def build_candidate_lessons(
    path_analysis: Mapping[str, Any],
    *,
    domain: str,
    task_type: str,
    source_refs: Iterable[str],
    changed_paths: Sequence[str] = (),
    contract_versions: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Convert only explicit, avoidable Detours into non-injectable candidates."""

    analysis = _require_mapping(path_analysis, "path_analysis")
    if analysis.get("schema") != PATH_ANALYSIS_SCHEMA:
        raise ValidationError("unsupported PathAnalysis schema")
    source_refs = tuple(str(ref).strip() for ref in source_refs if str(ref).strip())
    if not source_refs:
        raise ValidationError("experience requires at least one evidence source")
    snapshot = str(analysis.get("final_snapshot") or analysis.get("base_snapshot") or "").strip()
    contract_versions = {
        str(key).strip(): str(value).strip()
        for key, value in (contract_versions or {}).items()
        if str(key).strip() and str(value).strip()
    }
    lessons: list[dict[str, Any]] = []
    for detour in _list(analysis.get("detours", []), "path_analysis.detours"):
        item = _require_mapping(detour, "detour")
        if item.get("classification") != "avoidable_detour":
            continue
        resolution = _require_mapping(item.get("resolution", {}), "detour.resolution")
        if not resolution.get("verified_fallback"):
            continue
        # A candidate without a reproducible snapshot or contract context is
        # withheld rather than allowed to become misleading long-term memory.
        if not snapshot or not contract_versions:
            continue
        failed = _require_mapping(item.get("failed_action", {}), "detour.failed_action")
        digest = hashlib.sha256(str(item["detour_id"]).encode("utf-8")).hexdigest()[:12]
        failed_label = f"{failed.get('tool')}:{failed.get('operation')}"
        preferred_label = f"{resolution.get('tool')}:{resolution.get('operation')}"
        detour_trigger = _require_mapping(item.get("trigger", {}), "detour.trigger")
        trigger_preconditions = list(detour_trigger.get("preconditions", []))
        lesson = {
            "schema": LESSON_SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "lesson_id": f"LESSON-{digest}",
            "status": "candidate",
            "domain": _require_text(domain, "domain"),
            "task_type": _require_text(task_type, "task_type"),
            "trigger": {
                "changed_paths": [str(path) for path in changed_paths],
                "failure_class": str(failed.get("failure_class", "unknown")),
                "preconditions": trigger_preconditions,
            },
            "observed_facts": [
                f"{failed_label} failed with {failed.get('failure_class', 'unknown')}",
                f"A verified fallback succeeded at sequence {resolution.get('resolved_by_seq')}",
            ],
            "inference": {
                "statement": f"{failed_label} was avoidable under the recorded trigger; prefer {preferred_label}.",
                "confidence": "medium",
            },
            "recommendation": [
                f"Before using {failed_label}, run the recorded preflight checks.",
                f"Under the same trigger, prefer {preferred_label}.",
            ],
            "avoidance": {
                "when": [
                    f"domain={domain}",
                    f"task_type={task_type}",
                    f"failure_class={failed.get('failure_class', 'unknown')}",
                    *trigger_preconditions,
                ],
                "avoid": [failed_label],
                "prefer": [preferred_label],
                "preflight": list(
                    detour_trigger.get("preflight_checks", [])
                ) or ["re-check the recorded trigger before acting"],
            },
            "evidence": {
                "detour_id": item["detour_id"],
                "sources": [
                    {"ref": ref, "snapshot": snapshot, "kind": "structured_artifact"}
                    for ref in source_refs
                ],
                "snapshot": snapshot,
            },
            "compatibility": {
                "contract_versions": contract_versions,
                "changed_paths": [str(path) for path in changed_paths],
                "invalidated_by": ["contract_version_changes", "path_scope_rewrite"],
            },
            "privacy": {
                "redacted": True,
                "contains_secrets": False,
                "contains_raw_conversation": False,
            },
            "relations": {"supersedes": [], "contradicts": []},
            "created_at": "",
            "last_verified_at": "",
        }
        validate_lesson(lesson)
        lessons.append(lesson)
    return lessons


def validate_path_analysis(value: Mapping[str, Any]) -> None:
    _require_mapping(value, "PathAnalysis")
    if value.get("schema") != PATH_ANALYSIS_SCHEMA:
        raise ValidationError("invalid PathAnalysis schema")
    _require_text(value.get("task_id"), "PathAnalysis.task_id")
    if int(value.get("task_revision", 0)) < 1:
        raise ValidationError("PathAnalysis.task_revision must be positive")
    counts = _require_mapping(value.get("counts"), "PathAnalysis.counts")
    for key in (
        "planned_steps",
        "actual_steps",
        "failed_actions",
        "avoidable_detours",
        "necessary_explorations",
        "successful_fallbacks",
        "repeated_actions",
    ):
        if int(counts.get(key, -1)) < 0:
            raise ValidationError(f"PathAnalysis.counts.{key} must be non-negative")
    detours = _list(value.get("detours"), "PathAnalysis.detours")
    for detour in detours:
        validate_detour(detour)


def validate_detour(value: Mapping[str, Any]) -> None:
    item = _require_mapping(value, "Detour")
    if item.get("schema") != DETOUR_SCHEMA:
        raise ValidationError("invalid Detour schema")
    _require_text(item.get("detour_id"), "Detour.detour_id")
    _require_text(item.get("task_id"), "Detour.task_id")
    if item.get("classification") not in ALLOWED_DETOUR_CLASSES:
        raise ValidationError("invalid Detour classification")
    failed = _require_mapping(item.get("failed_action"), "Detour.failed_action")
    for key in ("tool", "operation", "failure_class", "error_signature_hash"):
        _require_text(failed.get(key), f"Detour.failed_action.{key}")
    _require_mapping(item.get("trigger"), "Detour.trigger")
    _require_mapping(item.get("impact"), "Detour.impact")
    resolution = _require_mapping(item.get("resolution"), "Detour.resolution")
    if resolution.get("verified_fallback"):
        try:
            if int(resolution.get("resolved_by_seq", 0)) < 1:
                raise ValidationError("Detour.resolution.resolved_by_seq must be positive")
        except (TypeError, ValueError) as exc:
            raise ValidationError("Detour.resolution.resolved_by_seq must be positive") from exc
        for key in ("tool", "operation"):
            _require_text(resolution.get(key), f"Detour.resolution.{key}")


def validate_lesson(value: Mapping[str, Any]) -> None:
    item = _require_mapping(value, "Lesson")
    reject_raw_context(item)
    if item.get("schema") != LESSON_SCHEMA or int(item.get("schema_version", 0)) != SCHEMA_VERSION:
        raise ValidationError("invalid Lesson schema")
    for key in ("lesson_id", "domain", "task_type", "status"):
        _require_text(item.get(key), f"Lesson.{key}")
    if item["status"] not in ALLOWED_LESSON_STATUSES:
        raise ValidationError(f"invalid Lesson status: {item['status']}")
    if not isinstance(item.get("observed_facts"), list) or not item["observed_facts"]:
        raise ValidationError("Lesson.observed_facts must be non-empty")
    inference = _require_mapping(item.get("inference"), "Lesson.inference")
    _require_text(inference.get("statement"), "Lesson.inference.statement")
    if inference.get("confidence") not in {"low", "medium", "high"}:
        raise ValidationError("Lesson.inference.confidence is invalid")
    evidence = _require_mapping(item.get("evidence"), "Lesson.evidence")
    sources = _list(evidence.get("sources"), "Lesson.evidence.sources")
    if not sources:
        raise ValidationError("Lesson requires evidence sources")
    snapshot = _require_text(evidence.get("snapshot"), "Lesson.evidence.snapshot")
    for index, source in enumerate(sources):
        source = _require_mapping(source, f"Lesson.evidence.sources[{index}]")
        _require_text(source.get("ref"), f"Lesson.evidence.sources[{index}].ref")
        if _require_text(source.get("snapshot"), f"Lesson.evidence.sources[{index}].snapshot") != snapshot:
            raise ValidationError("Lesson evidence source snapshot mismatch")
    compatibility = _require_mapping(item.get("compatibility"), "Lesson.compatibility")
    versions = _require_mapping(compatibility.get("contract_versions"), "Lesson.compatibility.contract_versions")
    if not versions or any(not str(key).strip() or not str(version).strip() for key, version in versions.items()):
        raise ValidationError("Lesson requires contract versions")
    avoidance = _require_mapping(item.get("avoidance"), "Lesson.avoidance")
    for key in ("when", "avoid", "prefer", "preflight"):
        values = _list(avoidance.get(key), f"Lesson.avoidance.{key}")
        if key != "when" and not values:
            raise ValidationError(f"Lesson.avoidance.{key} must be non-empty")
    privacy = _require_mapping(item.get("privacy"), "Lesson.privacy")
    if privacy.get("redacted") is not True or privacy.get("contains_secrets") is not False:
        raise ValidationError("Lesson privacy gate failed")


def build_experience_manifest(
    path_analysis: Mapping[str, Any],
    lessons: Sequence[Mapping[str, Any]],
    *,
    source_refs: Iterable[str],
    contract_versions: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    validate_path_analysis(path_analysis)
    for lesson in lessons:
        validate_lesson(lesson)
    task_id = _require_text(path_analysis.get("task_id"), "ExperienceManifest.task_id")
    snapshot = str(path_analysis.get("final_snapshot") or path_analysis.get("base_snapshot") or "").strip()
    source_refs = tuple(str(ref).strip() for ref in source_refs if str(ref).strip())
    if not source_refs:
        raise ValidationError("experience requires at least one evidence source")
    versions = {
        str(key).strip(): str(value).strip()
        for key, value in (contract_versions or {}).items()
        if str(key).strip() and str(value).strip()
    }
    return {
        "schema": EXPERIENCE_MANIFEST_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "experience_id": f"{task_id}-experience-{path_analysis.get('task_revision')}",
        "task_id": task_id,
        "task_revision": int(path_analysis["task_revision"]),
        "status": "candidate_only",
        "injection": {
            "enabled": False,
            "reason": "E1 candidate-only; no automatic ContextBrief injection",
        },
        "sources": [
            {"ref": str(ref).strip(), "snapshot": snapshot, "kind": "structured_artifact"}
            for ref in source_refs
            if str(ref).strip()
        ],
        "compatibility": {"contract_versions": versions},
        "path_analysis": {
            "schema": PATH_ANALYSIS_SCHEMA,
            "counts": dict(_require_mapping(path_analysis["counts"], "PathAnalysis.counts")),
            "detour_ids": [str(item["detour_id"]) for item in path_analysis["detours"]],
        },
        "candidate_lesson_ids": [str(lesson["lesson_id"]) for lesson in lessons],
        "promotion": {
            "status": "not_started",
            "requires_independent_evidence": True,
            "human_gate_required": True,
        },
    }


def validate_experience_manifest(value: Mapping[str, Any]) -> None:
    item = _require_mapping(value, "ExperienceManifest")
    if item.get("schema") != EXPERIENCE_MANIFEST_SCHEMA or int(item.get("schema_version", 0)) != SCHEMA_VERSION:
        raise ValidationError("invalid ExperienceManifest schema")
    _require_text(item.get("experience_id"), "ExperienceManifest.experience_id")
    _require_text(item.get("task_id"), "ExperienceManifest.task_id")
    if item.get("status") != "candidate_only":
        raise ValidationError("ExperienceManifest must remain candidate_only in E1")
    injection = _require_mapping(item.get("injection"), "ExperienceManifest.injection")
    if injection.get("enabled") is not False:
        raise ValidationError("candidate-only ExperienceManifest cannot enable injection")
    sources = _list(item.get("sources"), "ExperienceManifest.sources")
    candidate_ids = _list(item.get("candidate_lesson_ids"), "ExperienceManifest.candidate_lesson_ids")
    if not sources:
        raise ValidationError("ExperienceManifest requires evidence sources")
    for index, source in enumerate(sources):
        source = _require_mapping(source, f"ExperienceManifest.sources[{index}]")
        _require_text(source.get("ref"), f"ExperienceManifest.sources[{index}].ref")
        if candidate_ids:
            _require_text(source.get("snapshot"), f"ExperienceManifest.sources[{index}].snapshot")
    if len({str(lesson_id) for lesson_id in candidate_ids}) != len(candidate_ids):
        raise ValidationError("ExperienceManifest candidate lesson ids must be unique")
    compatibility = _require_mapping(item.get("compatibility"), "ExperienceManifest.compatibility")
    versions = _require_mapping(compatibility.get("contract_versions"), "ExperienceManifest.compatibility.contract_versions")
    if candidate_ids and not versions:
        raise ValidationError("ExperienceManifest candidates require contract versions")


def load_document(path: str | Path) -> Any:
    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationError(f"cannot read experience input {target}: {exc}") from exc
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValidationError(f"invalid YAML in experience input {target}: {exc}") from exc


def load_trace_paths(paths: Sequence[str | Path]) -> list[Mapping[str, Any]]:
    trace: list[Mapping[str, Any]] = []
    for raw_path in paths:
        target = Path(raw_path)
        text = target.read_text(encoding="utf-8")
        try:
            document = yaml.safe_load(text)
        except yaml.YAMLError:
            document = None
        if document is None:
            for line_number, line in enumerate(text.splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValidationError(f"invalid trace JSONL {target}:{line_number}") from exc
                trace.append(_require_mapping(item, f"trace {target}:{line_number}"))
            continue
        if isinstance(document, Mapping):
            document = document.get("events", document.get("actions", document.get("trace", [document])))
        for index, item in enumerate(_list(document, f"trace {target}")):
            trace.append(_require_mapping(item, f"trace {target}[{index}]"))
    return trace


def write_experience_store(
    output_dir: str | Path,
    experience_manifest: Mapping[str, Any],
    lessons: Sequence[Mapping[str, Any]],
) -> None:
    """Write only candidate artifacts to an explicit, caller-owned directory."""

    validate_experience_manifest(experience_manifest)
    validated_lessons: list[Mapping[str, Any]] = []
    for lesson in lessons:
        validate_lesson(lesson)
        lesson_id = str(lesson["lesson_id"])
        if not re.fullmatch(r"LESSON-[A-Za-z0-9_-]+", lesson_id):
            raise ValidationError("invalid candidate lesson id")
        validated_lessons.append(lesson)
    manifest_ids = {str(lesson_id) for lesson_id in experience_manifest["candidate_lesson_ids"]}
    lesson_ids = {str(lesson["lesson_id"]) for lesson in validated_lessons}
    if manifest_ids != lesson_ids:
        raise ValidationError("ExperienceManifest candidate ids do not match lessons")

    def atomic_write(path: Path, content: str) -> None:
        temporary = path.with_name(f".{path.name}.tmp")
        try:
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise ValidationError(f"cannot write experience artifact {path}: {exc}") from exc

    target = Path(output_dir)
    candidate_dir = target / "candidate"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(
        target / "ExperienceManifest.yaml",
        yaml.safe_dump(dict(experience_manifest), allow_unicode=True, sort_keys=False),
    )
    for lesson in validated_lessons:
        lesson_id = str(lesson["lesson_id"])
        atomic_write(
            candidate_dir / f"{lesson_id}.yaml",
            yaml.safe_dump(dict(lesson), allow_unicode=True, sort_keys=False),
        )


def _parse_contract_versions(values: Sequence[str]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValidationError(f"--contract-version must use NAME=VERSION: {value}")
        name, version = (part.strip() for part in value.split("=", 1))
        if not name or not version:
            raise ValidationError(f"--contract-version must use NAME=VERSION: {value}")
        versions[name] = version
    return versions


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Analyze an Agent Loop trace into candidate experience artifacts")
    parser.add_argument("--trace", nargs="+", required=True, help="JSON/YAML or JSONL execution trace")
    parser.add_argument("--run-manifest", help="optional RunManifest YAML/JSON")
    parser.add_argument("--test-report", action="append", default=[], help="optional TestReport YAML/JSON")
    parser.add_argument("--change-report", action="append", default=[], help="optional ChangeReport YAML/JSON")
    parser.add_argument("--output-dir", required=True, help="candidate-only output directory")
    parser.add_argument("--task-id", help="task id when no RunManifest is provided")
    parser.add_argument("--snapshot", help="reproducible snapshot when no RunManifest is provided")
    parser.add_argument("--domain", default="project")
    parser.add_argument("--task-type", default="unknown")
    parser.add_argument(
        "--contract-version",
        action="append",
        default=[],
        metavar="NAME=VERSION",
        help="contract compatibility fact; repeat for multiple contracts",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    run_manifest: Mapping[str, Any] = {}
    if args.run_manifest:
        run_manifest = _require_mapping(load_document(args.run_manifest), "RunManifest")
        reject_raw_context(run_manifest, "RunManifest")
        validate_run_manifest(run_manifest)
    task_id = str(args.task_id or run_manifest.get("task_id", "")).strip()
    if not task_id:
        raise ValidationError("--task-id or RunManifest.task_id is required")
    task_revision = int(run_manifest.get("task_revision", 1))
    workspace = run_manifest.get("workspace", {})
    workspace = workspace if isinstance(workspace, Mapping) else {}
    supplied_snapshot = str(args.snapshot or "").strip()
    reports: list[Mapping[str, Any]] = []
    for path in [*args.test_report, *args.change_report]:
        report = _require_mapping(load_document(path), f"report {path}")
        reject_raw_context(report, f"report {path}")
        if path in args.test_report:
            validate_test_report(report)
        reports.append(report)
    contract_versions: dict[str, str] = {}
    manifest_versions = run_manifest.get("contract_versions", {})
    if isinstance(manifest_versions, Mapping):
        contract_versions.update({str(key): str(value) for key, value in manifest_versions.items()})
    for report in reports:
        report_versions = report.get("contract_versions", {})
        if isinstance(report_versions, Mapping):
            contract_versions.update({str(key): str(value) for key, value in report_versions.items()})
    contract_versions.update(_parse_contract_versions(args.contract_version))
    trace = load_trace_paths(args.trace)
    planned_actions = run_manifest.get("planned_actions")
    planned_actions = planned_actions if isinstance(planned_actions, list) else None
    changed_paths: list[str] = []
    for report in reports:
        for path in report.get("changed_paths", report.get("changed_test_paths", [])):
            if str(path).strip():
                changed_paths.append(str(path))
    for role_run in run_manifest.get("role_runs", []):
        if isinstance(role_run, Mapping):
            changed_paths.extend(str(path) for path in role_run.get("changed_paths", []) if str(path).strip())
    analysis = analyze_path(
        trace,
        task_id=task_id,
        task_revision=task_revision,
        planned_actions=planned_actions,
        base_snapshot=str(workspace.get("base_snapshot", "") or supplied_snapshot),
        final_snapshot=str(workspace.get("final_snapshot", "") or supplied_snapshot),
    )
    source_refs = [*args.trace]
    source_refs.extend(path for path in [args.run_manifest, *args.test_report, *args.change_report] if path)
    lessons = build_candidate_lessons(
        analysis,
        domain=args.domain,
        task_type=args.task_type,
        source_refs=source_refs,
        changed_paths=sorted(set(changed_paths)),
        contract_versions=contract_versions,
    )
    experience_manifest = build_experience_manifest(
        analysis,
        lessons,
        source_refs=source_refs,
        contract_versions=contract_versions,
    )
    write_experience_store(args.output_dir, experience_manifest, lessons)
    if not args.quiet:
        print(json.dumps({
            "task_id": task_id,
            "experience_manifest": str(Path(args.output_dir) / "ExperienceManifest.yaml"),
            "candidate_lessons": [lesson["lesson_id"] for lesson in lessons],
            "path_analysis": analysis["counts"],
            "injection_enabled": False,
        }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    try:
        raise SystemExit(_cli())
    except ValidationError as exc:
        print(f"experience validation failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
