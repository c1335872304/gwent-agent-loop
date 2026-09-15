"""Regression tests for E3 bounded advisory ContextBrief injection."""

from __future__ import annotations

import copy
import unittest

from .errors import ValidationError
from .retrieval import shadow_retrieve, unavailable_shadow_report, validate_shadow_report
from .test_retrieval import confirmed_lesson, query
from .validate_packet import validate_context_brief
from .injection import inject_advisory, record_advisory_adoption


def context_brief() -> dict[str, object]:
    return {
        "task_id": "TASK-1",
        "packet_revision": 1,
        "context_snapshot": "git:current",
        "context_floor_refs": [{"path": "AGENTS.md", "role": "repository governance"}],
        "fact_source_graph": [{"path": "apps/web", "why": "task target"}],
        "fact_ledger": [{"fact": "current contract is product-http v1"}],
        "lessons": {"relevant_refs": []},
    }


class AdvisoryInjectionTests(unittest.TestCase):
    def test_injects_only_shadow_selected_lesson_into_dedicated_advisory(self) -> None:
        lesson = confirmed_lesson("LESSON-SELECTED")
        report = shadow_retrieve([lesson], query())
        base = context_brief()

        result = inject_advisory(
            base,
            report,
            [lesson],
            source_report_ref=".agent-loop/tasks/TASK-1/ShadowRetrieval.yaml",
        )

        self.assertEqual(result["context_floor_refs"], base["context_floor_refs"])
        self.assertEqual(result["fact_source_graph"], base["fact_source_graph"])
        self.assertEqual(result["advisory"]["status"], "applied")
        self.assertTrue(result["advisory"]["enabled"])
        self.assertEqual(result["advisory"]["items"][0]["lesson_id"], "LESSON-SELECTED")
        self.assertTrue(result["advisory"]["items"][0]["advisory_only"])
        self.assertNotIn("context_floor_refs", result["advisory"])
        validate_context_brief(result)

    def test_candidate_cannot_be_injected_even_if_report_is_tampered(self) -> None:
        lesson = confirmed_lesson("LESSON-CANDIDATE", status="candidate")
        report = shadow_retrieve([lesson], query())
        tampered = copy.deepcopy(report)
        tampered["selected"] = [{
            "lesson_id": "LESSON-CANDIDATE",
            "status": "candidate",
            "score": 1,
            "matched_fields": ["status"],
            "summary": "candidate",
            "estimated_tokens": 1,
        }]
        tampered["cost"]["selected_count"] = 1

        with self.assertRaisesRegex(ValidationError, "ineligible"):
            inject_advisory(context_brief(), tampered, [lesson], source_report_ref="report.yaml")

    def test_unavailable_shadow_retrieval_keeps_baseline_and_advisory_disabled(self) -> None:
        base = context_brief()
        result = inject_advisory(
            base,
            unavailable_shadow_report({}, "store unavailable"),
            [],
            source_report_ref="ShadowRetrieval.yaml",
        )

        self.assertEqual(result["advisory"]["status"], "unavailable")
        self.assertFalse(result["advisory"]["enabled"])
        self.assertEqual(result["advisory"]["items"], [])
        self.assertEqual(result["task_id"], base["task_id"])
        validate_context_brief(result)

    def test_item_limit_is_explicitly_reported_and_adoption_can_be_recorded(self) -> None:
        first = confirmed_lesson("LESSON-A")
        second = confirmed_lesson("LESSON-B")
        report = shadow_retrieve([first, second], query())
        result = inject_advisory(
            context_brief(),
            report,
            [first, second],
            source_report_ref="ShadowRetrieval.yaml",
            max_items=1,
        )

        self.assertEqual(len(result["advisory"]["items"]), 1)
        self.assertEqual(result["advisory"]["omitted"][0]["reason"], "item_limit")
        recorded = record_advisory_adoption(
            result,
            [result["advisory"]["items"][0]["lesson_id"]],
            evidence_ref="RunManifest.yaml#adoption",
        )
        self.assertEqual(recorded["advisory"]["adoption"]["status"], "recorded")
        self.assertEqual(len(recorded["advisory"]["adoption"]["not_adopted_lesson_ids"]), 0)
        validate_context_brief(recorded)

    def test_adoption_must_reference_an_injected_item(self) -> None:
        lesson = confirmed_lesson("LESSON-ONLY")
        result = inject_advisory(
            context_brief(),
            shadow_retrieve([lesson], query()),
            [lesson],
            source_report_ref="ShadowRetrieval.yaml",
        )

        with self.assertRaisesRegex(ValidationError, "not present"):
            record_advisory_adoption(result, ["LESSON-UNKNOWN"], evidence_ref="trace.jsonl")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
