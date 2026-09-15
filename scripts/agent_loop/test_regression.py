"""Regression tests for E4 fixed comparison and promotion gates."""

from __future__ import annotations

import copy
import unittest

from .errors import ValidationError
from .regression import build_promotion_report, validate_promotion_report, validate_regression_set


def evidence(ref: str) -> dict[str, object]:
    return {
        "report_ref": ref,
        "snapshot": f"git:{ref}",
        "tester": "test-verification",
        "independent": True,
        "evidence_refs": [f"{ref}#evidence"],
    }


def outcome(ref: str, *, success: bool = True, detours: int = 0, **overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "task_success": success,
        "avoidable_detours": detours,
        "extra_tool_calls": detours,
        "extra_model_turns": detours,
        "context_tokens": 250,
        "time_to_recovery_seconds": detours * 5,
        "contract_violations": 0,
        "wrong_file_scope": 0,
        "privacy_violations": 0,
        "false_avoidance_events": 0,
        "negative_transfer_events": 0,
        "human_interventions": 0,
        "evidence": evidence(ref),
    }
    result.update(overrides)
    return result


def case(case_id: str, kind: str, *, expected: str = "irrelevant", baseline_detours: int = 0, evolved_detours: int = 0, evolved_success: bool = True, lesson_ids: list[str] | None = None, evolved_enabled: bool = False, **evolved_overrides: object) -> dict[str, object]:
    return {
        "case_id": case_id,
        "kind": kind,
        "advisory": {
            "expected": expected,
            "baseline_enabled": False,
            "evolved_enabled": evolved_enabled,
            "lesson_ids": lesson_ids or [],
            "adoption": "adopted" if evolved_enabled else "not_applicable",
            "evidence_refs": [f"{case_id}#advisory"],
        },
        "baseline": outcome(f"{case_id}-baseline", detours=baseline_detours),
        "evolved": outcome(f"{case_id}-evolved", success=evolved_success, detours=evolved_detours, **evolved_overrides),
    }


def regression_set(*cases: dict[str, object]) -> dict[str, object]:
    return {
        "schema": "agent-loop.e4-regression-set.v1",
        "schema_version": 1,
        "regression_set_id": "E4-SET-001",
        "frozen": True,
        "snapshot": "git:fixed-fixtures",
        "source_refs": ["fixtures/e4/index.yaml"],
        "contract_versions": {"agent-loop": "v1"},
        "minimum_cases": {"target": 2, "control": 1, "safety": 1},
        "cases": list(cases),
    }


def passed_canary() -> dict[str, object]:
    return {
        "status": "passed",
        "runner": "test-verification",
        "snapshot": "git:canary",
        "evidence_refs": ["canary/run.log"],
        "rollback": {
            "status": "ready",
            "method": "restore fixed ContextBrief revision",
            "evidence_refs": ["canary/rollback-plan.md"],
        },
    }


class E4RegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = regression_set(
            case("E4-TARGET-001", "target", expected="relevant", baseline_detours=1, evolved_detours=0, lesson_ids=["LESSON-001"], evolved_enabled=True),
            case("E4-TARGET-002", "target", expected="relevant", baseline_detours=2, evolved_detours=1, lesson_ids=["LESSON-001"], evolved_enabled=True),
            case("E4-CONTROL-001", "control"),
            case("E4-SAFETY-001", "safety", expected="prohibited"),
        )

    def test_ready_report_requires_canary_and_waits_for_human_gate(self) -> None:
        report = build_promotion_report(self.data, canary=passed_canary())

        self.assertEqual(report["eligibility"]["status"], "ready_for_human_gate")
        self.assertEqual(report["metrics"]["by_kind"]["target"]["baseline"]["avoidable_detours_total"], 3)
        self.assertEqual(report["metrics"]["by_kind"]["target"]["evolved"]["avoidable_detours_total"], 1)
        self.assertEqual(
            {
                gate["id"]
                for gate in report["gates"]
                if gate["status"] == "FAIL" and gate["id"] != "human_approval"
            },
            set(),
        )
        self.assertEqual(report["gates"][-1]["id"], "human_approval")
        self.assertEqual(report["gates"][-1]["status"], "FAIL")
        validate_promotion_report(report)

    def test_explicit_approval_is_required_for_approved_status(self) -> None:
        report = build_promotion_report(
            self.data,
            canary=passed_canary(),
            decision={"status": "approved", "decided_by": "human-review", "evidence_ref": "decision.md#E4"},
        )

        self.assertEqual(report["eligibility"]["status"], "approved")
        self.assertEqual(report["gates"][-1]["status"], "PASS")

    def test_missing_detour_reduction_blocks_promotion(self) -> None:
        blocked = copy.deepcopy(self.data)
        blocked["cases"][0]["evolved"]["avoidable_detours"] = 1
        blocked["cases"][1]["evolved"]["avoidable_detours"] = 2
        report = build_promotion_report(blocked, canary=passed_canary())

        self.assertEqual(report["eligibility"]["status"], "not_ready")
        gate = next(gate for gate in report["gates"] if gate["id"] == "known_detours_reduced")
        self.assertEqual(gate["status"], "FAIL")

    def test_control_regression_and_false_avoidance_block_promotion(self) -> None:
        blocked = copy.deepcopy(self.data)
        control = blocked["cases"][2]
        control["advisory"]["evolved_enabled"] = True
        control["advisory"]["lesson_ids"] = ["LESSON-001"]
        control["evolved"]["task_success"] = False
        control["evolved"]["false_avoidance_events"] = 1
        report = build_promotion_report(blocked, canary=passed_canary())

        self.assertEqual(report["eligibility"]["status"], "not_ready")
        statuses = {gate["id"]: gate["status"] for gate in report["gates"]}
        self.assertEqual(statuses["negative_transfer_zero"], "FAIL")
        self.assertEqual(statuses["false_avoidance_zero"], "FAIL")
        self.assertTrue(report["derived_findings"]["negative_transfer"])

    def test_candidate_or_prohibited_advisory_cannot_enter_fixed_set_as_enabled(self) -> None:
        invalid = copy.deepcopy(self.data)
        invalid["cases"][3]["advisory"]["evolved_enabled"] = True
        invalid["cases"][3]["advisory"]["lesson_ids"] = ["LESSON-CANDIDATE"]
        with self.assertRaisesRegex(ValidationError, "prohibited advisory"):
            validate_regression_set(invalid)

    def test_canary_is_required_before_report_is_ready(self) -> None:
        report = build_promotion_report(self.data)

        self.assertEqual(report["eligibility"]["status"], "not_ready")
        status = {gate["id"]: gate["status"] for gate in report["gates"]}
        self.assertEqual(status["canary_passed"], "FAIL")
        self.assertEqual(status["rollback_ready"], "PASS")

    def test_approval_cannot_override_failed_canary(self) -> None:
        with self.assertRaisesRegex(ValidationError, "passed canary"):
            build_promotion_report(
                self.data,
                decision={"status": "approved", "decided_by": "human-review", "evidence_ref": "decision.md#E4"},
            )

    def test_rollback_decision_requires_executed_rollback_evidence(self) -> None:
        canary = passed_canary()
        canary["rollback"]["status"] = "executed"
        canary["rollback"]["evidence_refs"] = ["canary/rollback.log"]
        report = build_promotion_report(
            self.data,
            canary=canary,
            decision={"status": "rolled_back", "decided_by": "human-review", "evidence_ref": "decision.md#rollback"},
        )

        self.assertEqual(report["eligibility"]["status"], "rolled_back")
        validate_promotion_report(report)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
