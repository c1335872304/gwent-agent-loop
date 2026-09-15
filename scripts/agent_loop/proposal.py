"""Read-only E5 Skill, Routing, and Validation proposals.

E5 consumes independently evidenced Lessons and an approved E4
PromotionReport.  It emits review material only; no formal Skill, routing,
validator, scheduler, contract, model, or production file is edited.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.agent_loop.errors import ValidationError
    from scripts.agent_loop.experience import load_document, reject_raw_context, validate_lesson
    from scripts.agent_loop.regression import validate_promotion_report
else:
    from .errors import ValidationError
    from .experience import load_document, reject_raw_context, validate_lesson
    from .regression import validate_promotion_report


PROPOSAL_BUNDLE_SCHEMA = "agent-loop.e5-proposal-bundle.v1"
PROPOSAL_KINDS = ("skill_diff", "routing", "validation_plan")
PROPOSAL_STATUS = "draft_read_only"
DOMAIN_TARGETS = {
    "core": ".agents/skills/core-environment/SKILL.md",
    "trainer": ".agents/skills/training-config/SKILL.md",
    "product": ".agents/skills/product-integration/SKILL.md",
    "teacher": ".agents/skills/teacher-explanation/SKILL.md",
}


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{label} must be a mapping")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValidationError(f"{label} must be a list")
    return value


def _text(value: Any, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValidationError(f"{label} must not be empty")
    return result


def _text_list(value: Any, label: str, *, required: bool = False) -> list[str]:
    result = [_text(item, f"{label}[]") for item in _list(value, label)]
    if required and not result:
        raise ValidationError(f"{label} must be non-empty")
    if len(set(result)) != len(result):
        raise ValidationError(f"{label} must contain unique values")
    return result


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _lesson_refs(lessons: Sequence[Mapping[str, Any]]) -> tuple[list[str], list[str], list[str]]:
    lesson_ids: list[str] = []
    detour_ids: list[str] = []
    source_refs: list[str] = []
    snapshots: list[str] = []
    for index, lesson in enumerate(lessons):
        validate_lesson(lesson)
        if lesson["status"] not in {"confirmed", "promoted"}:
            raise ValidationError(f"lessons[{index}] must be confirmed or promoted")
        lesson_id = _text(lesson.get("lesson_id"), f"lessons[{index}].lesson_id")
        evidence = _mapping(lesson.get("evidence"), f"lessons[{index}].evidence")
        detour_id = _text(evidence.get("detour_id"), f"lessons[{index}].evidence.detour_id")
        snapshot = _text(evidence.get("snapshot"), f"lessons[{index}].evidence.snapshot")
        sources = _list(evidence.get("sources"), f"lessons[{index}].evidence.sources")
        refs = [_text(_mapping(source, "lesson evidence source").get("ref"), "lesson evidence source.ref") for source in sources]
        lesson_ids.append(lesson_id)
        detour_ids.append(detour_id)
        source_refs.extend(refs)
        snapshots.append(snapshot)
    if len(set(lesson_ids)) != len(lesson_ids):
        raise ValidationError("E5 lesson ids must be unique")
    if len(set(detour_ids)) != len(detour_ids):
        raise ValidationError("E5 requires distinct Detour evidence")
    if len(set(source_refs)) < 2 or len(set(snapshots)) < 2:
        raise ValidationError("E5 requires independent Lesson sources and snapshots")
    return lesson_ids, detour_ids, _unique(source_refs)


def _validate_inputs(
    promotion_report: Mapping[str, Any],
    lessons: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], list[str], list[str], list[str]]:
    reject_raw_context(promotion_report, "PromotionReport")
    validate_promotion_report(promotion_report)
    if promotion_report["eligibility"]["status"] != "approved":
        raise ValidationError("E5 requires an approved PromotionReport")
    if promotion_report["decision"]["status"] != "approved":
        raise ValidationError("E5 requires an explicit approved decision")
    if len(lessons) < 2:
        raise ValidationError("E5 requires at least two independent Lessons")
    clean_lessons: list[Mapping[str, Any]] = []
    for index, lesson in enumerate(lessons):
        item = _mapping(lesson, f"lessons[{index}]")
        reject_raw_context(item, f"lessons[{index}]")
        clean_lessons.append(item)
    lesson_ids, detour_ids, source_refs = _lesson_refs(clean_lessons)
    approved_ids = set(_text_list(
        _mapping(promotion_report["provenance"], "PromotionReport.provenance").get("advisory_lesson_ids"),
        "PromotionReport.provenance.advisory_lesson_ids",
    ))
    if not set(lesson_ids).issubset(approved_ids):
        raise ValidationError("E5 Lessons are not all covered by the approved PromotionReport")
    return promotion_report, lesson_ids, detour_ids, source_refs


def _conditions(lessons: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    conditions: list[dict[str, Any]] = []
    for lesson in lessons:
        trigger = _mapping(lesson["trigger"], "Lesson.trigger")
        conditions.append(
            {
                "lesson_id": str(lesson["lesson_id"]),
                "domain": str(lesson["domain"]),
                "task_type": str(lesson["task_type"]),
                "changed_paths": [str(value) for value in _list(trigger.get("changed_paths", []), "Lesson.trigger.changed_paths")],
                "failure_class": str(trigger.get("failure_class", "")),
                "preconditions": [str(value) for value in _list(trigger.get("preconditions", []), "Lesson.trigger.preconditions")],
            }
        )
    return conditions


def _avoidance_rules(lessons: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for lesson in lessons:
        avoidance = _mapping(lesson["avoidance"], "Lesson.avoidance")
        rules.append(
            {
                "lesson_id": str(lesson["lesson_id"]),
                "when": [str(value) for value in _list(avoidance["when"], "Lesson.avoidance.when")],
                "avoid": [str(value) for value in _list(avoidance["avoid"], "Lesson.avoidance.avoid")],
                "prefer": [str(value) for value in _list(avoidance["prefer"], "Lesson.avoidance.prefer")],
                "preflight": [str(value) for value in _list(avoidance["preflight"], "Lesson.avoidance.preflight")],
            }
        )
    return rules


def _targets(lessons: Sequence[Mapping[str, Any]], kind: str) -> list[str]:
    domains = _unique([str(lesson["domain"]) for lesson in lessons])
    if kind == "skill_diff":
        return _unique([DOMAIN_TARGETS.get(domain, f".agents/skills/{domain}/SKILL.md") for domain in domains])
    if kind == "routing":
        return ["AGENTS.md", "docs/current/agent-entry/<DOMAIN>.md"]
    return ["scripts/check.py", "docs/current/agent-loop/TEST_MATRIX.yaml"]


def _counterexamples(promotion_report: Mapping[str, Any]) -> list[dict[str, Any]]:
    provenance = _mapping(promotion_report["provenance"], "PromotionReport.provenance")
    by_kind = _mapping(provenance["cases_by_kind"], "PromotionReport.provenance.cases_by_kind")
    return [
        {
            "case_ids": list(by_kind["control"]),
            "condition": "advisory is irrelevant or absent",
            "required_behavior": "task success and avoidable-detour metrics must not regress",
        },
        {
            "case_ids": list(by_kind["safety"]),
            "condition": "advisory is prohibited or safety-sensitive",
            "required_behavior": "do not enable the rule; contract, scope and privacy must remain safe",
        },
    ]


def _proposal(
    kind: str,
    *,
    lessons: Sequence[Mapping[str, Any]],
    lesson_ids: Sequence[str],
    detour_ids: Sequence[str],
    source_refs: Sequence[str],
    promotion_report_ref: str,
    promotion_report: Mapping[str, Any],
) -> dict[str, Any]:
    conditions = _conditions(lessons)
    rules = _avoidance_rules(lessons)
    domains = _unique([str(lesson["domain"]) for lesson in lessons])
    common = {
        "proposal_id": f"E5-{kind}-" + "-".join(lesson_ids),
        "kind": kind,
        "status": PROPOSAL_STATUS,
        "read_only": True,
        "suggested_targets": _targets(lessons, kind),
        "source_lesson_ids": list(lesson_ids),
        "trigger_conditions": conditions,
        "avoidance_rules": rules,
        "counterexamples": _counterexamples(promotion_report),
        "regression_refs": [
            promotion_report_ref,
            *[f"{promotion_report_ref}#{case_id}" for case_id in _text_list(
                promotion_report["regression_set"]["case_ids"], "PromotionReport.regression_set.case_ids"
            )],
        ],
        "evidence_refs": _unique([promotion_report_ref, *source_refs, *detour_ids]),
        "review_required": True,
    }
    if kind == "skill_diff":
        common["change"] = {
            "operation": "add_bounded_preflight_guidance",
            "summary": "Add condition-bound preflight guidance while preserving each Skill's existing invariant section.",
            "preflight_items": _unique(
                [str(item) for lesson in lessons for item in _list(lesson["avoidance"]["preflight"], "Lesson.avoidance.preflight")]
            ),
            "invariants": [
                "Do not convert a conditional lesson into an unconditional prohibition.",
                "Do not change contract ownership, permissions, budgets, or stop conditions.",
            ],
        }
    elif kind == "routing":
        common["change"] = {
            "operation": "add_condition_to_existing_route",
            "summary": "Route only matching domain/task/precondition combinations to the current authoritative owner.",
            "domain_routes": [
                {"domain": domain, "owner": domain, "triggered_by": [condition for condition in conditions if condition["domain"] == domain]}
                for domain in domains
            ],
            "fallback": "context-integration then HUMAN_REQUIRED when authority is ambiguous",
        }
    else:
        common["change"] = {
            "operation": "add_regression_assertions",
            "summary": "Keep the fixed E4 regression set as a required check before any future rule adoption.",
            "commands": [
                "python3 scripts/check.py architecture",
                "python3 scripts/agent_loop/regression.py --regression-set <frozen-set> --output <PromotionReport>",
            ],
            "assertions": [
                "target avoidable detours decrease",
                "control and safety cases do not regress",
                "candidate lessons remain non-injectable",
                "human approval and rollback evidence remain required",
            ],
        }
    return common


def validate_proposal_bundle(value: Mapping[str, Any]) -> None:
    bundle = _mapping(value, "ProposalBundle")
    if bundle.get("schema") != PROPOSAL_BUNDLE_SCHEMA or int(bundle.get("schema_version", 0)) != 1:
        raise ValidationError("invalid E5 ProposalBundle schema")
    if bundle.get("status") != PROPOSAL_STATUS:
        raise ValidationError("E5 ProposalBundle must remain draft_read_only")
    _text(bundle.get("proposal_id"), "ProposalBundle.proposal_id")
    source = _mapping(bundle.get("source"), "ProposalBundle.source")
    _text(source.get("promotion_report_ref"), "ProposalBundle.source.promotion_report_ref")
    _text(source.get("promotion_report_snapshot"), "ProposalBundle.source.promotion_report_snapshot")
    _text_list(source.get("lesson_ids"), "ProposalBundle.source.lesson_ids", required=True)
    _text_list(source.get("detour_ids"), "ProposalBundle.source.detour_ids", required=True)
    _text_list(source.get("task_snapshots"), "ProposalBundle.source.task_snapshots", required=True)
    _text_list(source.get("regression_refs"), "ProposalBundle.source.regression_refs", required=True)
    proposals = _list(bundle.get("proposals"), "ProposalBundle.proposals")
    kinds = [str(_mapping(item, "ProposalBundle.proposals[]").get("kind")) for item in proposals]
    if len(proposals) != len(PROPOSAL_KINDS) or set(kinds) != set(PROPOSAL_KINDS):
        raise ValidationError("E5 ProposalBundle must contain Skill, Routing and Validation proposals")
    lesson_ids = set(str(item) for item in source["lesson_ids"])
    for index, raw_proposal in enumerate(proposals):
        proposal = _mapping(raw_proposal, f"ProposalBundle.proposals[{index}]")
        if proposal.get("status") != PROPOSAL_STATUS or proposal.get("read_only") is not True:
            raise ValidationError("E5 proposals must be read-only drafts")
        if proposal.get("kind") not in PROPOSAL_KINDS:
            raise ValidationError("E5 proposal kind is invalid")
        _text_list(proposal.get("suggested_targets"), "E5 suggested_targets", required=True)
        if not set(_text_list(proposal.get("source_lesson_ids"), "E5 source_lesson_ids", required=True)).issubset(lesson_ids):
            raise ValidationError("E5 proposal references unknown Lesson")
        for field in ("trigger_conditions", "avoidance_rules", "counterexamples", "regression_refs", "evidence_refs"):
            if not _list(proposal.get(field), f"E5 {field}"):
                raise ValidationError(f"E5 proposal requires {field}")
        _mapping(proposal.get("change"), "E5 proposal.change")
        if proposal.get("review_required") is not True:
            raise ValidationError("E5 proposals require review_required=true")
    boundaries = _mapping(bundle.get("boundaries"), "ProposalBundle.boundaries")
    for field in ("modifies_formal_files", "auto_merges", "auto_promotes"):
        if boundaries.get(field) is not False:
            raise ValidationError(f"E5 boundary {field} must be false")
    if boundaries.get("human_gate_required") is not True:
        raise ValidationError("E5 human gate is required")


def build_proposal_bundle(
    promotion_report: Mapping[str, Any],
    lessons: Sequence[Mapping[str, Any]],
    *,
    promotion_report_ref: str,
    proposal_id: str,
) -> dict[str, Any]:
    report, lesson_ids, detour_ids, source_refs = _validate_inputs(promotion_report, lessons)
    promotion_report_ref = _text(promotion_report_ref, "promotion_report_ref")
    proposal_id = _text(proposal_id, "proposal_id")
    snapshots = _unique([
        _text(_mapping(lesson["evidence"], "Lesson.evidence").get("snapshot"), "Lesson.evidence.snapshot")
        for lesson in lessons
    ])
    proposals = [
        _proposal(
            kind,
            lessons=lessons,
            lesson_ids=lesson_ids,
            detour_ids=detour_ids,
            source_refs=source_refs,
            promotion_report_ref=promotion_report_ref,
            promotion_report=report,
        )
        for kind in PROPOSAL_KINDS
    ]
    bundle = {
        "schema": PROPOSAL_BUNDLE_SCHEMA,
        "schema_version": 1,
        "proposal_id": proposal_id,
        "status": PROPOSAL_STATUS,
        "source": {
            "promotion_report_ref": promotion_report_ref,
            "promotion_report_snapshot": str(report["regression_set"]["snapshot"]),
            "lesson_ids": lesson_ids,
            "detour_ids": detour_ids,
            "task_snapshots": snapshots,
            "regression_refs": [promotion_report_ref, *[f"{promotion_report_ref}#{case_id}" for case_id in report["regression_set"]["case_ids"]]],
        },
        "proposals": proposals,
        "boundaries": {
            "modifies_formal_files": False,
            "auto_merges": False,
            "auto_promotes": False,
            "human_gate_required": True,
        },
    }
    reject_raw_context(bundle, "ProposalBundle")
    validate_proposal_bundle(bundle)
    return bundle


def _write_yaml(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(yaml.safe_dump(dict(value), allow_unicode=True, sort_keys=False), encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise ValidationError(f"cannot write ProposalBundle {path}: {exc}") from exc


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Create read-only E5 Skill/Routing/Validation proposals")
    parser.add_argument("--promotion-report", required=True)
    parser.add_argument("--lesson", action="append", required=True, help="confirmed/promoted Lesson; repeatable")
    parser.add_argument("--promotion-report-ref", required=True)
    parser.add_argument("--proposal-id", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = _mapping(load_document(args.promotion_report), "PromotionReport")
    lessons = [_mapping(load_document(path), f"Lesson:{path}") for path in args.lesson]
    bundle = build_proposal_bundle(
        report,
        lessons,
        promotion_report_ref=args.promotion_report_ref,
        proposal_id=args.proposal_id,
    )
    output = Path(args.output)
    _write_yaml(output, bundle)
    print(yaml.safe_dump({"status": bundle["status"], "proposals": list(PROPOSAL_KINDS), "output": str(output)}, allow_unicode=True, sort_keys=False).strip())
    return 0


if __name__ == "__main__":  # pragma: no cover
    try:
        raise SystemExit(_cli())
    except ValidationError as exc:
        print(f"proposal validation failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
