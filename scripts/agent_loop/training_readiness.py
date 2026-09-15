"""Fail-closed E6 training-readiness gate.

This module checks whether a self-evolution proposal is ready to be handed to
Trainer.  It never loads a checkpoint, starts training, installs a model, or
changes a training/config/model file.
"""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from typing import Any, Mapping

import yaml

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.agent_loop.errors import ValidationError
    from scripts.agent_loop.experience import load_document, reject_raw_context
else:
    from .errors import ValidationError
    from .experience import load_document, reject_raw_context


READINESS_SCHEMA = "agent-loop.e6-training-readiness.v1"
READINESS_STATUSES = {"blocked", "ready_for_trainer_review"}
VALIDATION_STATUSES = {"not_run", "passed", "failed"}


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


def _text_list(value: Any, label: str, *, required: bool = False) -> list[str]:
    result = [_text(item, f"{label}[]") for item in _list(value, label)]
    if required and not result:
        raise ValidationError(f"{label} must be non-empty")
    if len(set(result)) != len(result):
        raise ValidationError(f"{label} must contain unique values")
    return result


def _nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ValidationError(f"{label} must be a non-negative integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} must be a non-negative integer") from exc
    if result < 0:
        raise ValidationError(f"{label} must be a non-negative integer")
    return result


def _gate(gates: Mapping[str, Any], key: str) -> bool:
    gate = _mapping(gates.get(key), f"Readiness.gates.{key}")
    if gate.get("status") not in {"passed", "blocked", "failed"}:
        raise ValidationError(f"Readiness.gates.{key}.status is invalid")
    _text_list(gate.get("evidence_refs"), f"Readiness.gates.{key}.evidence_refs")
    return gate["status"] == "passed"


def validate_training_readiness(value: Mapping[str, Any]) -> None:
    readiness = _mapping(value, "TrainingReadiness")
    if readiness.get("schema") != READINESS_SCHEMA or int(readiness.get("schema_version", 0)) != 1:
        raise ValidationError("invalid E6 TrainingReadiness schema")
    _text(readiness.get("readiness_id"), "TrainingReadiness.readiness_id")
    if readiness.get("status") not in READINESS_STATUSES:
        raise ValidationError("TrainingReadiness.status is invalid")
    _text(readiness.get("objective"), "TrainingReadiness.objective")
    sources = _mapping(readiness.get("sources"), "TrainingReadiness.sources")
    for field in ("promotion_report_ref", "proposal_bundle_ref", "evaluation_ref"):
        _text(sources.get(field), f"TrainingReadiness.sources.{field}")
    if sources.get("promotion_report_status") not in {"approved", "not_ready", "rejected"}:
        raise ValidationError("TrainingReadiness.sources.promotion_report_status is invalid")
    contract = _mapping(readiness.get("contract"), "TrainingReadiness.contract")
    for field in ("observation_schema", "action_grammar", "reward_config"):
        value = _text(contract.get(field), f"TrainingReadiness.contract.{field}")
        if value.lower() in {"unknown", "current", "latest"}:
            raise ValidationError(f"TrainingReadiness.contract.{field} must be pinned")
    trainer_task = _mapping(readiness.get("trainer_task"), "TrainingReadiness.trainer_task")
    _text(trainer_task.get("ref"), "TrainingReadiness.trainer_task.ref")
    if trainer_task.get("owner") != "trainer":
        raise ValidationError("TrainingReadiness.trainer_task.owner must be trainer")
    if trainer_task.get("mode") not in {"scratch", "resume", "warm_start"}:
        raise ValidationError("TrainingReadiness.trainer_task.mode is invalid")
    validation = _mapping(readiness.get("trainer_validation"), "TrainingReadiness.trainer_validation")
    if validation.get("status") not in VALIDATION_STATUSES:
        raise ValidationError("TrainingReadiness.trainer_validation.status is invalid")
    _text_list(validation.get("evidence_refs"), "TrainingReadiness.trainer_validation.evidence_refs")
    if validation["status"] == "passed" and not validation.get("evidence_refs"):
        raise ValidationError("passed Trainer validation requires evidence_refs")
    evaluation = _mapping(readiness.get("evaluation"), "TrainingReadiness.evaluation")
    _nonnegative_int(evaluation.get("completed_games"), "TrainingReadiness.evaluation.completed_games")
    required_games = _nonnegative_int(evaluation.get("required_games"), "TrainingReadiness.evaluation.required_games")
    if required_games < 1:
        raise ValidationError("TrainingReadiness.evaluation.required_games must be positive")
    _nonnegative_int(evaluation.get("illegal_result_count"), "TrainingReadiness.evaluation.illegal_result_count")
    _text_list(evaluation.get("matchup_refs"), "TrainingReadiness.evaluation.matchup_refs", required=True)
    if evaluation["completed_games"] < evaluation["required_games"]:
        raise ValidationError("TrainingReadiness evaluation has incomplete games")
    if evaluation["illegal_result_count"] != 0:
        raise ValidationError("TrainingReadiness evaluation has illegal results")
    stability = _mapping(readiness.get("stability"), "TrainingReadiness.stability")
    if stability.get("status") not in {"stable", "unstable", "unknown"}:
        raise ValidationError("TrainingReadiness.stability.status is invalid")
    if _nonnegative_int(stability.get("independent_rounds"), "TrainingReadiness.stability.independent_rounds") < 2:
        raise ValidationError("TrainingReadiness requires two independent stability rounds")
    _text_list(stability.get("evidence_refs"), "TrainingReadiness.stability.evidence_refs", required=True)
    approvals = _mapping(readiness.get("approvals"), "TrainingReadiness.approvals")
    for field in ("formal_rules", "model_change"):
        approval = _mapping(approvals.get(field), f"TrainingReadiness.approvals.{field}")
        if approval.get("status") not in {"pending", "approved", "rejected"}:
            raise ValidationError(f"TrainingReadiness.approvals.{field}.status is invalid")
        if approval["status"] != "pending":
            _text(approval.get("decided_by"), f"TrainingReadiness.approvals.{field}.decided_by")
            _text(approval.get("evidence_ref"), f"TrainingReadiness.approvals.{field}.evidence_ref")
    permissions = _mapping(readiness.get("permissions"), "TrainingReadiness.permissions")
    for field in ("model_write_enabled", "model_promotion_enabled"):
        if permissions.get(field) is not False:
            raise ValidationError(f"TrainingReadiness.permissions.{field} must be false")
    if permissions.get("human_gate_required") is not True:
        raise ValidationError("E6 TrainingReadiness requires a human gate")
    evidence = _mapping(readiness.get("evidence"), "TrainingReadiness.evidence")
    _text_list(evidence.get("contract_refs"), "TrainingReadiness.evidence.contract_refs", required=True)
    gates = _mapping(readiness.get("gates"), "TrainingReadiness.gates")
    required_gates = {
        "context_stable",
        "experience_stable",
        "formal_rules_approved",
        "e4_regression_approved",
        "evaluation_complete",
        "contract_pinned",
        "trainer_task_validated",
        "model_gate",
    }
    if set(gates) != required_gates:
        raise ValidationError("TrainingReadiness gates must match the E6 gate set")
    for key in required_gates:
        _gate(gates, key)
    expected_status = "ready_for_trainer_review" if all(_gate(gates, key) for key in required_gates) else "blocked"
    if readiness["status"] != expected_status:
        raise ValidationError("TrainingReadiness.status does not match gate results")
    reject_raw_context(readiness, "TrainingReadiness")


def build_training_readiness(
    *,
    readiness_id: str,
    objective: str,
    sources: Mapping[str, Any],
    contract: Mapping[str, Any],
    trainer_task: Mapping[str, Any],
    trainer_validation: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    stability: Mapping[str, Any],
    approvals: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a readiness report; a report never starts the Trainer."""

    gates = {
        "context_stable": {"status": "passed" if stability.get("status") == "stable" and int(stability.get("independent_rounds", 0)) >= 2 else "blocked", "evidence_refs": list(stability.get("evidence_refs", []))},
        "experience_stable": {"status": "passed" if stability.get("status") == "stable" else "blocked", "evidence_refs": list(stability.get("evidence_refs", []))},
        "formal_rules_approved": {"status": "passed" if _mapping(approvals.get("formal_rules"), "approvals.formal_rules").get("status") == "approved" else "blocked", "evidence_refs": [str(_mapping(approvals.get("formal_rules"), "approvals.formal_rules").get("evidence_ref", ""))] if _mapping(approvals.get("formal_rules"), "approvals.formal_rules").get("evidence_ref") else []},
        "e4_regression_approved": {"status": "passed" if str(sources.get("promotion_report_status")) == "approved" else "blocked", "evidence_refs": [str(sources.get("promotion_report_ref", ""))]},
        "evaluation_complete": {"status": "passed" if int(evaluation.get("completed_games", 0)) >= int(evaluation.get("required_games", 0)) and int(evaluation.get("illegal_result_count", 1)) == 0 else "blocked", "evidence_refs": [str(sources.get("evaluation_ref", ""))]},
        "contract_pinned": {"status": "passed" if all(str(contract.get(field, "")).strip() for field in ("observation_schema", "action_grammar", "reward_config")) else "blocked", "evidence_refs": list(evidence.get("contract_refs", []))},
        "trainer_task_validated": {"status": "passed" if trainer_validation.get("status") == "passed" else "blocked", "evidence_refs": list(trainer_validation.get("evidence_refs", []))},
        "model_gate": {"status": "passed" if _mapping(approvals.get("model_change"), "approvals.model_change").get("status") == "approved" else "blocked", "evidence_refs": [str(_mapping(approvals.get("model_change"), "approvals.model_change").get("evidence_ref", ""))] if _mapping(approvals.get("model_change"), "approvals.model_change").get("evidence_ref") else []},
    }
    report = {
        "schema": READINESS_SCHEMA,
        "schema_version": 1,
        "readiness_id": _text(readiness_id, "readiness_id"),
        "status": "ready_for_trainer_review" if all(gate["status"] == "passed" for gate in gates.values()) else "blocked",
        "objective": _text(objective, "objective"),
        "sources": dict(sources),
        "contract": dict(contract),
        "trainer_task": dict(trainer_task),
        "trainer_validation": dict(trainer_validation),
        "evaluation": dict(evaluation),
        "stability": dict(stability),
        "approvals": copy.deepcopy(dict(approvals)),
        "permissions": {"model_write_enabled": False, "model_promotion_enabled": False, "human_gate_required": True},
        "gates": gates,
        "evidence": dict(evidence),
    }
    validate_training_readiness(report)
    return report


def _write_yaml(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(yaml.safe_dump(dict(value), allow_unicode=True, sort_keys=False), encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise ValidationError(f"cannot write TrainingReadiness {path}: {exc}") from exc


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Build a fail-closed E6 training readiness report")
    parser.add_argument("--input", required=True, help="TrainingReadiness YAML with evidence fields")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = load_document(args.input)
    validate_training_readiness(_mapping(report, "TrainingReadiness"))
    _write_yaml(Path(args.output), _mapping(report, "TrainingReadiness"))
    print(yaml.safe_dump({"status": report["status"], "output": args.output}, allow_unicode=True, sort_keys=False).strip())
    return 0


if __name__ == "__main__":  # pragma: no cover
    try:
        raise SystemExit(_cli())
    except ValidationError as exc:
        print(f"training readiness validation failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
