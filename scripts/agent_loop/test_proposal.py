"""Regression tests for E5 read-only proposal generation."""

from __future__ import annotations

import copy
import unittest

from .errors import ValidationError
from .proposal import build_proposal_bundle, validate_proposal_bundle
from .regression import build_promotion_report
from .test_regression import case, passed_canary, regression_set
from .test_retrieval import confirmed_lesson


def approved_inputs() -> tuple[dict[str, object], list[dict[str, object]]]:
    first = confirmed_lesson("LESSON-001")
    second = confirmed_lesson("LESSON-002", snapshot="git:lesson-2")
    second["evidence"]["detour_id"] = "LESSON-002-detour"
    second["evidence"]["sources"][0]["ref"] = "trace-2.jsonl"
    data = regression_set(
        case("E5-TARGET-001", "target", expected="relevant", baseline_detours=1, evolved_detours=0, lesson_ids=["LESSON-001"], evolved_enabled=True),
        case("E5-TARGET-002", "target", expected="relevant", baseline_detours=2, evolved_detours=1, lesson_ids=["LESSON-002"], evolved_enabled=True),
        case("E5-CONTROL-001", "control"),
        case("E5-SAFETY-001", "safety", expected="prohibited"),
    )
    report = build_promotion_report(
        data,
        canary=passed_canary(),
        decision={"status": "approved", "decided_by": "human-review", "evidence_ref": "decision.md#E5"},
    )
    return report, [first, second]


class E5ProposalTests(unittest.TestCase):
    def test_generates_three_read_only_proposals_from_approved_evidence(self) -> None:
        report, lessons = approved_inputs()
        bundle = build_proposal_bundle(
            report,
            lessons,
            promotion_report_ref=".agent-loop/e4/PromotionReport.yaml",
            proposal_id="E5-PROPOSAL-001",
        )

        self.assertEqual(bundle["status"], "draft_read_only")
        self.assertEqual(
            {proposal["kind"] for proposal in bundle["proposals"]},
            {"skill_diff", "routing", "validation_plan"},
        )
        for proposal in bundle["proposals"]:
            self.assertTrue(proposal["read_only"])
            self.assertTrue(proposal["review_required"])
            self.assertEqual(proposal["source_lesson_ids"], ["LESSON-001", "LESSON-002"])
            self.assertTrue(proposal["counterexamples"])
        validate_proposal_bundle(bundle)

    def test_pending_promotion_report_cannot_create_proposal(self) -> None:
        report, lessons = approved_inputs()
        pending = copy.deepcopy(report)
        pending["eligibility"] = {"status": "ready_for_human_gate", "reason": "approval pending"}
        pending["decision"] = {"status": "pending", "decided_by": "", "evidence_ref": ""}
        pending["gates"][-1]["status"] = "FAIL"
        with self.assertRaisesRegex(ValidationError, "approved PromotionReport"):
            build_proposal_bundle(
                pending,
                lessons,
                promotion_report_ref="PromotionReport.yaml",
                proposal_id="E5-PROPOSAL-PENDING",
            )

    def test_candidate_lesson_cannot_be_promoted_by_e5(self) -> None:
        report, lessons = approved_inputs()
        candidate = copy.deepcopy(lessons[1])
        candidate["status"] = "candidate"
        with self.assertRaisesRegex(ValidationError, "confirmed or promoted"):
            build_proposal_bundle(
                report,
                [lessons[0], candidate],
                promotion_report_ref="PromotionReport.yaml",
                proposal_id="E5-PROPOSAL-CANDIDATE",
            )

    def test_duplicate_detour_evidence_is_not_independent(self) -> None:
        report, lessons = approved_inputs()
        duplicate = copy.deepcopy(lessons[1])
        duplicate["evidence"]["detour_id"] = lessons[0]["evidence"]["detour_id"]
        with self.assertRaisesRegex(ValidationError, "distinct Detour"):
            build_proposal_bundle(
                report,
                [lessons[0], duplicate],
                promotion_report_ref="PromotionReport.yaml",
                proposal_id="E5-PROPOSAL-DUPLICATE",
            )

    def test_proposal_bundle_rejects_raw_context(self) -> None:
        report, lessons = approved_inputs()
        report["prompt"] = "private conversation"
        with self.assertRaisesRegex(ValidationError, "not allowed in experience evidence"):
            build_proposal_bundle(
                report,
                lessons,
                promotion_report_ref="PromotionReport.yaml",
                proposal_id="E5-PROPOSAL-PRIVATE",
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
