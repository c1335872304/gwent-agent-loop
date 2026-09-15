"""Deterministic E2 shadow retrieval for confirmed experience.

The retriever is deliberately advisory-free: it selects and excludes records
for an auditable report, but never edits a ContextBrief or changes task
execution.  Matching is explicit and fail-closed when evidence is missing.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.agent_loop.errors import ValidationError
    from scripts.agent_loop.experience import load_document, reject_raw_context, validate_lesson
else:
    from .errors import ValidationError
    from .experience import load_document, reject_raw_context, validate_lesson


SHADOW_RETRIEVAL_SCHEMA = "agent-loop.shadow-retrieval.v1"
SHADOW_QUERY_SCHEMA = "agent-loop.shadow-query.v1"
ELIGIBLE_STATUSES = {"confirmed", "promoted"}
DEFAULT_MAX_RESULTS = 3
DEFAULT_MAX_TOKENS = 1500
DEFAULT_MAX_AGE_DAYS = 180


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{label} must be a mapping")
    return value


def _text(value: Any, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValidationError(f"{label} must not be empty")
    return result


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValidationError(f"{label} must be a list")
    return value


def _text_list(value: Any, label: str) -> list[str]:
    return [_text(item, f"{label}[]") for item in _list(value, label)]


def _normalise_path(value: str) -> str:
    return value.strip().replace("\\", "/").strip("/")


def _paths_overlap(left: Sequence[str], right: Sequence[str]) -> bool:
    normal_left = [_normalise_path(path) for path in left if _normalise_path(path)]
    normal_right = [_normalise_path(path) for path in right if _normalise_path(path)]
    return any(
        a == b or a.startswith(b + "/") or b.startswith(a + "/")
        for a in normal_left
        for b in normal_right
    )


def _parse_date(value: Any, label: str) -> date:
    text = _text(value, label)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise ValidationError(f"{label} must be an ISO date or datetime") from exc


def _query_defaults(query: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(query)
    if result.get("schema") != SHADOW_QUERY_SCHEMA:
        raise ValidationError("invalid ShadowQuery schema")
    result["query_id"] = _text(result.get("query_id"), "ShadowQuery.query_id")
    result.setdefault("changed_paths", [])
    result.setdefault("preconditions", [])
    result.setdefault("conflicting_lesson_ids", [])
    result.setdefault("failure_class", "")
    result.setdefault("failed_action", "")
    result.setdefault("max_results", DEFAULT_MAX_RESULTS)
    result.setdefault("max_tokens", DEFAULT_MAX_TOKENS)
    result.setdefault("max_age_days", DEFAULT_MAX_AGE_DAYS)
    result["domain"] = _text(result.get("domain"), "ShadowQuery.domain")
    result["task_type"] = _text(result.get("task_type"), "ShadowQuery.task_type")
    result["current_snapshot"] = _text(result.get("current_snapshot"), "ShadowQuery.current_snapshot")
    _parse_date(result.get("as_of"), "ShadowQuery.as_of")
    changed_paths = _text_list(result["changed_paths"], "ShadowQuery.changed_paths")
    preconditions = _text_list(result["preconditions"], "ShadowQuery.preconditions")
    conflicting_ids = _text_list(result["conflicting_lesson_ids"], "ShadowQuery.conflicting_lesson_ids")
    contract_versions = _mapping(result.get("contract_versions"), "ShadowQuery.contract_versions")
    if not contract_versions or any(not str(key).strip() or not str(value).strip() for key, value in contract_versions.items()):
        raise ValidationError("ShadowQuery requires contract versions")
    try:
        max_results = int(result["max_results"])
        max_tokens = int(result["max_tokens"])
        max_age_days = int(result["max_age_days"])
    except (TypeError, ValueError) as exc:
        raise ValidationError("ShadowQuery limits must be integers") from exc
    if min(max_results, max_tokens, max_age_days) < 1:
        raise ValidationError("ShadowQuery limits must be positive")
    result.update(
        {
            "changed_paths": changed_paths,
            "preconditions": preconditions,
            "conflicting_lesson_ids": conflicting_ids,
            "contract_versions": {
                str(key).strip(): str(value).strip() for key, value in contract_versions.items()
            },
            "max_results": max_results,
            "max_tokens": max_tokens,
            "max_age_days": max_age_days,
        }
    )
    return result


def validate_shadow_query(value: Mapping[str, Any]) -> None:
    query = _mapping(value, "ShadowQuery")
    reject_raw_context(query, "ShadowQuery")
    _query_defaults(query)


def _estimated_tokens(value: Any) -> int:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return max(1, (len(encoded) + 3) // 4)


def _excluded(lesson_id: str, status: str, reason: str, **details: Any) -> dict[str, Any]:
    return {
        "lesson_id": lesson_id,
        "status": status,
        "reason": reason,
        "details": {key: value for key, value in details.items() if value not in (None, "", [], {})},
    }


def _selected(lesson: Mapping[str, Any], score: int, matched_fields: list[str], estimated_tokens: int) -> dict[str, Any]:
    return {
        "lesson_id": str(lesson["lesson_id"]),
        "status": str(lesson["status"]),
        "score": score,
        "matched_fields": matched_fields,
        "summary": str(lesson["inference"]["statement"]),
        "estimated_tokens": estimated_tokens,
    }


def shadow_retrieve(lessons: Sequence[Mapping[str, Any]], query: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deterministic selected/excluded report without injecting anything."""

    raw_query = _mapping(query, "ShadowQuery")
    reject_raw_context(raw_query, "ShadowQuery")
    query = _query_defaults(raw_query)
    as_of = _parse_date(query["as_of"], "ShadowQuery.as_of")
    selected_pool: list[tuple[Mapping[str, Any], int, list[str], int]] = []
    excluded: list[dict[str, Any]] = []
    invalid_count = 0
    declared_conflict_ids: set[str] = set()
    for raw_lesson in lessons:
        if not isinstance(raw_lesson, Mapping):
            continue
        lesson_id = str(raw_lesson.get("lesson_id", "")).strip()
        relations = raw_lesson.get("relations")
        if lesson_id and isinstance(relations, Mapping) and isinstance(relations.get("contradicts"), list):
            if relations["contradicts"]:
                declared_conflict_ids.add(lesson_id)
                declared_conflict_ids.update(str(item).strip() for item in relations["contradicts"] if str(item).strip())

    for index, raw_lesson in enumerate(lessons):
        lesson_id = str(raw_lesson.get("lesson_id", f"lesson-{index + 1}")) if isinstance(raw_lesson, Mapping) else f"lesson-{index + 1}"
        if not isinstance(raw_lesson, Mapping):
            invalid_count += 1
            excluded.append(_excluded(lesson_id, "unknown", "invalid_lesson"))
            continue
        try:
            reject_raw_context(raw_lesson, f"lesson[{index}]")
            validate_lesson(raw_lesson)
        except ValidationError as exc:
            invalid_count += 1
            excluded.append(_excluded(lesson_id, str(raw_lesson.get("status", "unknown")), "invalid_lesson", validation=str(exc)))
            continue

        status = str(raw_lesson["status"])
        if status == "candidate":
            excluded.append(_excluded(lesson_id, status, "candidate_not_eligible"))
            continue
        if status not in ELIGIBLE_STATUSES:
            excluded.append(_excluded(lesson_id, status, f"status_not_eligible:{status}"))
            continue
        if lesson_id in set(query["conflicting_lesson_ids"]):
            excluded.append(_excluded(lesson_id, status, "query_conflict"))
            continue

        relations = _mapping(raw_lesson.get("relations"), f"lesson[{index}].relations")
        if lesson_id in declared_conflict_ids or _text_list(relations.get("contradicts", []), f"lesson[{index}].relations.contradicts"):
            excluded.append(_excluded(lesson_id, status, "declared_conflict"))
            continue

        if raw_lesson["domain"] != query["domain"]:
            excluded.append(_excluded(lesson_id, status, "domain_mismatch"))
            continue
        if raw_lesson["task_type"] != query["task_type"]:
            excluded.append(_excluded(lesson_id, status, "task_type_mismatch"))
            continue

        trigger = _mapping(raw_lesson.get("trigger"), f"lesson[{index}].trigger")
        lesson_paths = _text_list(trigger.get("changed_paths", []), f"lesson[{index}].trigger.changed_paths")
        if query["changed_paths"] and (not lesson_paths or not _paths_overlap(query["changed_paths"], lesson_paths)):
            excluded.append(_excluded(lesson_id, status, "changed_path_mismatch"))
            continue
        query_failure = str(query.get("failure_class", "")).strip()
        if query_failure and str(trigger.get("failure_class", "")) != query_failure:
            excluded.append(_excluded(lesson_id, status, "failure_class_mismatch"))
            continue
        lesson_preconditions = set(_text_list(trigger.get("preconditions", []), f"lesson[{index}].trigger.preconditions"))
        if query["preconditions"] and not set(query["preconditions"]).issubset(lesson_preconditions):
            excluded.append(_excluded(lesson_id, status, "precondition_mismatch"))
            continue

        compatibility = _mapping(raw_lesson.get("compatibility"), f"lesson[{index}].compatibility")
        lesson_versions = _mapping(compatibility.get("contract_versions"), f"lesson[{index}].compatibility.contract_versions")
        if set(str(key) for key in lesson_versions) != set(query["contract_versions"]) or any(
            str(lesson_versions.get(key, "")) != str(value)
            for key, value in query["contract_versions"].items()
        ):
            excluded.append(_excluded(lesson_id, status, "contract_incompatible"))
            continue

        evidence = _mapping(raw_lesson.get("evidence"), f"lesson[{index}].evidence")
        lesson_snapshot = str(evidence.get("snapshot", "")).strip()
        if not lesson_snapshot:
            excluded.append(_excluded(lesson_id, status, "snapshot_missing"))
            continue
        snapshot_policy = str(compatibility.get("snapshot_policy", "exact")).strip()
        if lesson_snapshot != query["current_snapshot"] and snapshot_policy != "contract_bound":
            excluded.append(_excluded(lesson_id, status, "snapshot_mismatch"))
            continue

        last_verified = str(raw_lesson.get("last_verified_at", "")).strip()
        if not last_verified:
            excluded.append(_excluded(lesson_id, status, "verification_date_missing"))
            continue
        verified_date = _parse_date(last_verified, f"lesson[{index}].last_verified_at")
        age_days = (as_of - verified_date).days
        if age_days < 0:
            excluded.append(_excluded(lesson_id, status, "verification_date_in_future"))
            continue
        if age_days > query["max_age_days"]:
            excluded.append(_excluded(lesson_id, status, "stale", age_days=age_days))
            continue
        expires = str(raw_lesson.get("expires_at", "")).strip()
        if expires and as_of > _parse_date(expires, f"lesson[{index}].expires_at"):
            excluded.append(_excluded(lesson_id, status, "expired"))
            continue

        avoidance = _mapping(raw_lesson.get("avoidance"), f"lesson[{index}].avoidance")
        failed_action = str(query.get("failed_action", "")).strip()
        if failed_action and failed_action not in {str(item) for item in _text_list(avoidance.get("avoid", []), f"lesson[{index}].avoidance.avoid")}:
            excluded.append(_excluded(lesson_id, status, "failed_action_mismatch"))
            continue

        matched_fields = ["status", "domain", "task_type", "contract_versions", "snapshot", "verification_freshness"]
        score = 4 + 4 + 3 + 3 + 1
        if query["changed_paths"]:
            score += 3
            matched_fields.append("changed_paths")
        if query_failure:
            score += 2
            matched_fields.append("failure_class")
        if query["preconditions"]:
            score += 1
            matched_fields.append("preconditions")
        if failed_action:
            score += 1
            matched_fields.append("failed_action")
        selected_pool.append((raw_lesson, score, matched_fields, _estimated_tokens(raw_lesson["inference"])))

    selected_pool.sort(key=lambda item: (-item[1], str(item[0]["lesson_id"])))
    selected: list[dict[str, Any]] = []
    selected_tokens = 0
    for lesson, score, matched_fields, estimated_tokens in selected_pool:
        if len(selected) >= query["max_results"]:
            excluded.append(_excluded(str(lesson["lesson_id"]), str(lesson["status"]), "result_limit"))
            continue
        if selected_tokens + estimated_tokens > query["max_tokens"]:
            excluded.append(_excluded(str(lesson["lesson_id"]), str(lesson["status"]), "token_limit", estimated_tokens=estimated_tokens))
            continue
        selected.append(_selected(lesson, score, matched_fields, estimated_tokens))
        selected_tokens += estimated_tokens

    eligible_count = len(selected_pool)
    report = {
        "schema": SHADOW_RETRIEVAL_SCHEMA,
        "status": "completed",
        "query": query,
        "selected": selected,
        "excluded": excluded,
        "cost": {
            "input_lessons": len(lessons),
            "invalid_lessons": invalid_count,
            "eligible_matches": eligible_count,
            "selected_count": len(selected),
            "excluded_count": len(excluded),
            "selected_estimated_tokens": selected_tokens,
            "candidate_hit_rate": (len(selected) / eligible_count) if eligible_count else 0.0,
            "input_match_rate": (len(selected) / len(lessons)) if lessons else 0.0,
            "model_calls": 0,
            "context_injection": False,
        },
        "baseline": {
            "unchanged": True,
            "injection_enabled": False,
            "fallback": "use_current_context_baseline",
        },
    }
    validate_shadow_report(report)
    return report


def unavailable_shadow_report(query: Mapping[str, Any], reason: str) -> dict[str, Any]:
    """Build a safe report when retrieval cannot run; the task baseline remains usable."""

    safe_query: Mapping[str, Any]
    try:
        reject_raw_context(query, "ShadowQuery")
        safe_query = dict(query)
    except ValidationError:
        safe_query = {}
    return {
        "schema": SHADOW_RETRIEVAL_SCHEMA,
        "status": "unavailable",
        "query": safe_query,
        "selected": [],
        "excluded": [],
        "cost": {
            "input_lessons": 0,
            "invalid_lessons": 0,
            "eligible_matches": 0,
            "selected_count": 0,
            "excluded_count": 0,
            "selected_estimated_tokens": 0,
            "candidate_hit_rate": 0.0,
            "input_match_rate": 0.0,
            "model_calls": 0,
            "context_injection": False,
        },
        "baseline": {
            "unchanged": True,
            "injection_enabled": False,
            "fallback": "use_current_context_baseline",
        },
        "unavailable_reason": str(reason)[:240],
    }


def validate_shadow_report(value: Mapping[str, Any]) -> None:
    item = _mapping(value, "ShadowRetrieval")
    reject_raw_context(item, "ShadowRetrieval")
    if item.get("schema") != SHADOW_RETRIEVAL_SCHEMA:
        raise ValidationError("invalid ShadowRetrieval schema")
    status = str(item.get("status", ""))
    if status not in {"completed", "unavailable"}:
        raise ValidationError("invalid ShadowRetrieval status")
    selected = _list(item.get("selected"), "ShadowRetrieval.selected")
    excluded = _list(item.get("excluded"), "ShadowRetrieval.excluded")
    selected_ids: list[str] = []
    for index, result in enumerate(selected):
        result = _mapping(result, f"ShadowRetrieval.selected[{index}]")
        lesson_id = _text(result.get("lesson_id"), f"ShadowRetrieval.selected[{index}].lesson_id")
        if lesson_id in selected_ids:
            raise ValidationError("ShadowRetrieval selected lesson ids must be unique")
        selected_ids.append(lesson_id)
        if result.get("status") not in ELIGIBLE_STATUSES:
            raise ValidationError("ShadowRetrieval selected an ineligible lesson")
        if not isinstance(result.get("matched_fields"), list) or not result["matched_fields"]:
            raise ValidationError("ShadowRetrieval selected result requires matched_fields")
        _text(result.get("summary"), f"ShadowRetrieval.selected[{index}].summary")
        try:
            if int(result.get("estimated_tokens", 0)) < 1:
                raise ValidationError("ShadowRetrieval selected token estimate must be positive")
        except (TypeError, ValueError) as exc:
            raise ValidationError("ShadowRetrieval selected token estimate must be positive") from exc
    for index, result in enumerate(excluded):
        result = _mapping(result, f"ShadowRetrieval.excluded[{index}]")
        _text(result.get("lesson_id"), f"ShadowRetrieval.excluded[{index}].lesson_id")
        _text(result.get("reason"), f"ShadowRetrieval.excluded[{index}].reason")
    cost = _mapping(item.get("cost"), "ShadowRetrieval.cost")
    for key in (
        "input_lessons",
        "invalid_lessons",
        "eligible_matches",
        "selected_count",
        "excluded_count",
        "selected_estimated_tokens",
        "model_calls",
    ):
        try:
            if int(cost.get(key, -1)) < 0:
                raise ValidationError(f"ShadowRetrieval.cost.{key} must be non-negative")
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"ShadowRetrieval.cost.{key} must be non-negative") from exc
    if cost.get("context_injection") is not False:
        raise ValidationError("ShadowRetrieval cannot enable context injection")
    baseline = _mapping(item.get("baseline"), "ShadowRetrieval.baseline")
    if baseline.get("unchanged") is not True or baseline.get("injection_enabled") is not False:
        raise ValidationError("ShadowRetrieval baseline must remain unchanged")
    if status == "completed":
        validate_shadow_query(_mapping(item.get("query"), "ShadowRetrieval.query"))
        if int(cost["selected_count"]) != len(selected):
            raise ValidationError("ShadowRetrieval selected count mismatch")
    elif selected:
        raise ValidationError("unavailable ShadowRetrieval cannot select lessons")


def load_lessons(paths: Sequence[str | Path]) -> list[Mapping[str, Any]]:
    lessons: list[Mapping[str, Any]] = []
    for raw_path in paths:
        document = load_document(raw_path)
        if isinstance(document, Mapping) and isinstance(document.get("lessons"), list):
            items = document["lessons"]
        else:
            items = [document]
        for index, item in enumerate(_list(items, f"lessons {raw_path}")):
            lessons.append(_mapping(item, f"lesson {raw_path}[{index}]"))
    return lessons


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Run E2 deterministic shadow retrieval")
    parser.add_argument("--lesson", action="append", required=True, help="confirmed/candidate Lesson YAML; repeatable")
    parser.add_argument("--query", required=True, help="ShadowQuery YAML/JSON")
    parser.add_argument("--output", required=True, help="ShadowRetrieval report YAML")
    args = parser.parse_args()
    try:
        query = _mapping(load_document(args.query), "ShadowQuery")
        report = shadow_retrieve(load_lessons(args.lesson), query)
    except (OSError, ValidationError) as exc:
        query = load_document(args.query)
        report = unavailable_shadow_report(query if isinstance(query, Mapping) else {}, str(exc))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(report, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(json.dumps({"status": report["status"], "selected": len(report["selected"]), "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
