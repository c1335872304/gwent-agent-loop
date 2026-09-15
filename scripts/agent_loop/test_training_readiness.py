"""Regression tests for the fail-closed E6 training readiness gate."""

from __future__ import annotations

import copy
import unittest

from .errors import ValidationError
from .training_readiness import build_training_readiness, validate_training_readiness


def readiness_inputs() -> dict[str, object]:
    return {
        "readiness_id": "E6-READINESS-001",
        "objective": "Test one bounded context-advisory hypothesis.",
        "sources": {
            "promotion_report_ref": "e4/PromotionReport.yaml",
            "promotion_report_status": "approved",
            "proposal_bundle_ref": "e5/ProposalBundle.yaml",
            "evaluation_ref": "e6/evaluation.yaml",
        },
        "contract": {
            "observation_schema": "v13",
            "action_grammar": "v5",
            "reward_config": "v2",
        },
        "trainer_task": {
            "ref": "training/tasks/e6_smoke.yaml",
            "owner": "trainer",
            "mode": "scratch",
        },
        "trainer_validation": {"status": "passed", "evidence_refs": ["trainer/validate.log"]},
        "evaluation": {
            "completed_games": 100,
            "required_games": 100,
            "illegal_result_count": 0,
            "matchup_refs": ["e6/matchups.yaml"],
        },
        "stability": {"status": "stable", "independent_rounds": 2, "evidence_refs": ["e6/stability.yaml"]},
        "approvals": {
            "formal_rules": {"status": "approved", "decided_by": "human-review", "evidence_ref": "approval.md#rules"},
            "model_change": {"status": "approved", "decided_by": "human-review", "evidence_ref": "approval.md#model"},
        },
        "evidence": {"contract_refs": ["AGENTS.md#contract", "core/schema.json"]},
    }


class E6TrainingReadinessTests(unittest.TestCase):
    def test_complete_prerequisites_are_ready_for_trainer_review(self) -> None:
        report = build_training_readiness(**readiness_inputs())

        self.assertEqual(report["status"], "ready_for_trainer_review")
        self.assertFalse(report["permissions"]["model_write_enabled"])
        self.assertFalse(report["permissions"]["model_promotion_enabled"])
        self.assertTrue(all(gate["status"] == "passed" for gate in report["gates"].values()))
        validate_training_readiness(report)

    def test_missing_approval_and_validation_remain_blocked(self) -> None:
        values = readiness_inputs()
        values["approvals"]["formal_rules"]["status"] = "pending"
        values["approvals"]["model_change"]["status"] = "pending"
        values["trainer_validation"] = {"status": "not_run", "evidence_refs": []}
        report = build_training_readiness(**values)

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["gates"]["formal_rules_approved"]["status"], "blocked")
        self.assertEqual(report["gates"]["trainer_task_validated"]["status"], "blocked")

    def test_e6_never_enables_model_write_or_promotion(self) -> None:
        report = build_training_readiness(**readiness_inputs())
        tampered = copy.deepcopy(report)
        tampered["permissions"]["model_write_enabled"] = True

        with self.assertRaisesRegex(ValidationError, "model_write_enabled"):
            validate_training_readiness(tampered)

    def test_incomplete_or_illegal_evaluation_is_rejected(self) -> None:
        values = readiness_inputs()
        values["evaluation"]["completed_games"] = 99
        with self.assertRaisesRegex(ValidationError, "incomplete games"):
            build_training_readiness(**values)

        values = readiness_inputs()
        values["evaluation"]["illegal_result_count"] = 1
        with self.assertRaisesRegex(ValidationError, "illegal results"):
            build_training_readiness(**values)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
