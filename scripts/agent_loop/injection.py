"""E3 bounded advisory injection into a ContextBrief.

Only lessons selected by a valid E2 Shadow Retrieval report are eligible.  The
result is a new ContextBrief copy with a dedicated advisory section; authority
fields and task controls are never edited.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.agent_loop.errors import ValidationError
    from scripts.agent_loop.experience import load_document, reject_raw_context, validate_lesson
    from scripts.agent_loop.retrieval import load_lessons, validate_shadow_report
    from scripts.agent_loop.validate_packet import validate_context_brief
else:
    from .errors import ValidationError
    from .experience import load_document, reject_raw_context, validate_lesson
    from .retrieval import load_lessons, validate_shadow_report
    from .validate_packet import validate_context_brief


ADVISORY_STATUSES = {"empty", "applied", "unavailable", "blocked"}
ELIGIBLE_STATUSES = {"confirmed", "promoted"}
DEFAULT_MAX_ITEMS = 3
DEFAULT_MAX_TOKENS = 1500


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


def _estimated_tokens(value: Mapping[str, Any]) -> int:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return max(1, (len(encoded) + 3) // 4)


def _base_advisory(
    *,
    source_report_ref: str,
    max_items: int,
    max_tokens: int,
    status: str,
    enabled: bool,
    items: list[dict[str, Any]] | None = None,
    omitted: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    items = items or []
    return {
        "enabled": enabled,
        "status": status,
        "source_report_ref": source_report_ref,
        "items": items,
        "omitted": omitted or [],
        "limits": {
            "max_items": max_items,
            "max_tokens": max_tokens,
            "used_items": len(items),
            "used_tokens": sum(int(item["estimated_tokens"]) for item in items),
        },
        "adoption": {
            "status": "not_recorded",
            "adopted_lesson_ids": [],
            "not_adopted_lesson_ids": [],
            "evidence_ref": "",
        },
    }


def _assert_baseline_unchanged(before: Mapping[str, Any], after: Mapping[str, Any]) -> None:
    for key, value in before.items():
        if key == "advisory":
            continue
        if after.get(key) != value:
            raise ValidationError(f"advisory injection modified baseline field: {key}")


def _advisory_item(lesson: Mapping[str, Any], estimated_tokens: int) -> dict[str, Any]:
    avoidance = _mapping(lesson["avoidance"], "Lesson.avoidance")
    evidence = _mapping(lesson["evidence"], "Lesson.evidence")
    return {
        "lesson_id": str(lesson["lesson_id"]),
        "status": str(lesson["status"]),
        "advisory_only": True,
        "statement": str(lesson["inference"]["statement"]),
        "when": [str(item) for item in _list(avoidance["when"], "Lesson.avoidance.when")],
        "avoid": [str(item) for item in _list(avoidance["avoid"], "Lesson.avoidance.avoid")],
        "prefer": [str(item) for item in _list(avoidance["prefer"], "Lesson.avoidance.prefer")],
        "preflight": [str(item) for item in _list(avoidance["preflight"], "Lesson.avoidance.preflight")],
        "evidence_snapshot": _text(evidence["snapshot"], "Lesson.evidence.snapshot"),
        "source_refs": [
            _text(_mapping(source, "Lesson.evidence.source")["ref"], "Lesson.evidence.source.ref")
            for source in _list(evidence["sources"], "Lesson.evidence.sources")
        ],
        "estimated_tokens": estimated_tokens,
    }


def inject_advisory(
    context_brief: Mapping[str, Any],
    shadow_report: Mapping[str, Any],
    lessons: Sequence[Mapping[str, Any]],
    *,
    source_report_ref: str,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict[str, Any]:
    """Create a bounded advisory ContextBrief from E2 selected results."""

    base = copy.deepcopy(_mapping(context_brief, "ContextBrief"))
    reject_raw_context(base, "ContextBrief")
    validate_context_brief(base)
    validate_shadow_report(_mapping(shadow_report, "ShadowRetrieval"))
    source_report_ref = _text(source_report_ref, "source_report_ref")
    if max_items < 1 or max_tokens < 1:
        raise ValidationError("advisory limits must be positive")
    lesson_by_id: dict[str, Mapping[str, Any]] = {}
    for index, lesson in enumerate(lessons):
        validate_lesson(_mapping(lesson, f"lessons[{index}]"))
        lesson_id = str(lesson["lesson_id"])
        if lesson_id in lesson_by_id:
            raise ValidationError(f"duplicate lesson id: {lesson_id}")
        lesson_by_id[lesson_id] = lesson

    report_status = str(shadow_report["status"])
    if report_status == "unavailable":
        advisory = _base_advisory(
            source_report_ref=source_report_ref,
            max_items=max_items,
            max_tokens=max_tokens,
            status="unavailable",
            enabled=False,
        )
    else:
        items: list[dict[str, Any]] = []
        omitted: list[dict[str, str]] = []
        used_tokens = 0
        for selected in _list(shadow_report["selected"], "ShadowRetrieval.selected"):
            selected = _mapping(selected, "ShadowRetrieval.selected[]")
            lesson_id = _text(selected.get("lesson_id"), "selected.lesson_id")
            lesson = lesson_by_id.get(lesson_id)
            if lesson is None:
                raise ValidationError(f"selected lesson is not available for injection: {lesson_id}")
            if lesson["status"] not in ELIGIBLE_STATUSES or selected.get("status") != lesson["status"]:
                raise ValidationError(f"selected lesson is not eligible for advisory injection: {lesson_id}")
            item_without_estimate = {
                "lesson_id": lesson_id,
                "statement": str(_mapping(lesson["inference"], "Lesson.inference")["statement"]),
                "avoid": [str(value) for value in _list(_mapping(lesson["avoidance"], "Lesson.avoidance")["avoid"], "Lesson.avoidance.avoid")],
                "prefer": [str(value) for value in _list(_mapping(lesson["avoidance"], "Lesson.avoidance")["prefer"], "Lesson.avoidance.prefer")],
            }
            estimated_tokens = _estimated_tokens(item_without_estimate)
            item = _advisory_item(lesson, estimated_tokens)
            if len(items) >= max_items:
                omitted.append({"lesson_id": lesson_id, "reason": "item_limit"})
            elif used_tokens + estimated_tokens > max_tokens:
                omitted.append({"lesson_id": lesson_id, "reason": "token_limit"})
            else:
                items.append(item)
                used_tokens += estimated_tokens
        advisory = _base_advisory(
            source_report_ref=source_report_ref,
            max_items=max_items,
            max_tokens=max_tokens,
            status="applied" if items else "empty",
            enabled=bool(items),
            items=items,
            omitted=omitted,
        )

    result = copy.deepcopy(base)
    result["advisory"] = advisory
    _assert_baseline_unchanged(base, result)
    validate_context_brief(result)
    return result


def record_advisory_adoption(
    context_brief: Mapping[str, Any],
    adopted_lesson_ids: Sequence[str],
    *,
    evidence_ref: str,
) -> dict[str, Any]:
    """Record whether already-injected advisory items were used."""

    result = copy.deepcopy(_mapping(context_brief, "ContextBrief"))
    validate_context_brief(result)
    advisory = result.get("advisory")
    if not isinstance(advisory, Mapping):
        raise ValidationError("ContextBrief has no advisory to record")
    item_ids = {str(item["lesson_id"]) for item in _list(advisory["items"], "ContextBrief.advisory.items")}
    adopted = [str(lesson_id).strip() for lesson_id in adopted_lesson_ids if str(lesson_id).strip()]
    if not set(adopted).issubset(item_ids):
        raise ValidationError("adoption references a lesson not present in advisory")
    if len(set(adopted)) != len(adopted):
        raise ValidationError("adoption lesson ids must be unique")
    advisory = copy.deepcopy(advisory)
    advisory["adoption"] = {
        "status": "recorded",
        "adopted_lesson_ids": adopted,
        "not_adopted_lesson_ids": sorted(item_ids - set(adopted)),
        "evidence_ref": _text(evidence_ref, "adoption.evidence_ref"),
    }
    result["advisory"] = advisory
    validate_context_brief(result)
    return result


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Create a bounded E3 advisory ContextBrief")
    parser.add_argument("--context-brief", required=True, help="base ContextBrief YAML/JSON")
    parser.add_argument("--shadow-report", required=True, help="E2 ShadowRetrieval YAML/JSON")
    parser.add_argument("--lesson", action="append", required=True, help="Lesson YAML; repeatable")
    parser.add_argument("--source-report-ref", required=True)
    parser.add_argument("--output", required=True, help="augmented ContextBrief YAML")
    parser.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    args = parser.parse_args()
    context = _mapping(load_document(args.context_brief), "ContextBrief")
    report = _mapping(load_document(args.shadow_report), "ShadowRetrieval")
    result = inject_advisory(
        context,
        report,
        load_lessons(args.lesson),
        source_report_ref=args.source_report_ref,
        max_items=args.max_items,
        max_tokens=args.max_tokens,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(result, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(json.dumps({"status": result["advisory"]["status"], "items": len(result["advisory"]["items"]), "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    try:
        raise SystemExit(_cli())
    except ValidationError as exc:
        print(f"advisory validation failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
