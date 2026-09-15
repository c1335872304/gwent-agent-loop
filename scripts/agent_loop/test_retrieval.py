"""Regression tests for E2 shadow-only experience retrieval."""

from __future__ import annotations

import copy
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from .errors import ValidationError
from .retrieval import (
    shadow_retrieve,
    unavailable_shadow_report,
    validate_shadow_report,
    validate_shadow_query,
)


def confirmed_lesson(
    lesson_id: str,
    *,
    status: str = "confirmed",
    domain: str = "product",
    task_type: str = "api_contract_change",
    changed_paths: list[str] | None = None,
    contract_version: str = "v1",
    snapshot: str = "git:lesson",
    snapshot_policy: str = "contract_bound",
    last_verified_at: str = "2026-09-01",
    contradicts: list[str] | None = None,
) -> dict[str, object]:
    changed_paths = changed_paths or ["apps/web"]
    return {
        "schema": "agent-loop.lesson.v1",
        "schema_version": 1,
        "lesson_id": lesson_id,
        "status": status,
        "domain": domain,
        "task_type": task_type,
        "trigger": {
            "changed_paths": changed_paths,
            "failure_class": "ENVIRONMENT_FAILURE",
            "preconditions": ["host_dependencies_differ"],
        },
        "observed_facts": ["host test failed", "pinned environment passed"],
        "inference": {
            "statement": "Use the pinned verification environment under this trigger.",
            "confidence": "high",
        },
        "recommendation": ["Run the pinned verification environment first."],
        "avoidance": {
            "when": ["domain=product", "task_type=api_contract_change"],
            "avoid": ["pytest:host_pytest"],
            "prefer": ["docker:docker_pytest"],
            "preflight": ["check pinned test image"],
        },
        "evidence": {
            "detour_id": f"{lesson_id}-detour",
            "sources": [{"ref": "trace.jsonl", "snapshot": snapshot, "kind": "structured_artifact"}],
            "snapshot": snapshot,
        },
        "compatibility": {
            "contract_versions": {"product-http": contract_version},
            "changed_paths": changed_paths,
            "snapshot_policy": snapshot_policy,
            "invalidated_by": ["contract_version_changes"],
        },
        "privacy": {
            "redacted": True,
            "contains_secrets": False,
            "contains_raw_conversation": False,
        },
        "relations": {"supersedes": [], "contradicts": contradicts or []},
        "created_at": "2026-09-01",
        "last_verified_at": last_verified_at,
    }


def query(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "schema": "agent-loop.shadow-query.v1",
        "query_id": "TASK-1-shadow-1",
        "domain": "product",
        "task_type": "api_contract_change",
        "changed_paths": ["apps/web/frontend"],
        "failure_class": "ENVIRONMENT_FAILURE",
        "failed_action": "pytest:host_pytest",
        "preconditions": ["host_dependencies_differ"],
        "contract_versions": {"product-http": "v1"},
        "current_snapshot": "git:current",
        "as_of": "2026-09-15",
        "max_age_days": 180,
        "max_results": 3,
        "max_tokens": 1500,
        "conflicting_lesson_ids": [],
    }
    result.update(overrides)
    return result


class ShadowRetrievalTests(unittest.TestCase):
    def test_selects_confirmed_match_and_excludes_candidate(self) -> None:
        matching = confirmed_lesson("LESSON-MATCH")
        candidate = copy.deepcopy(matching)
        candidate["lesson_id"] = "LESSON-CANDIDATE"
        candidate["status"] = "candidate"

        report = shadow_retrieve([candidate, matching], query())

        self.assertEqual([item["lesson_id"] for item in report["selected"]], ["LESSON-MATCH"])
        self.assertIn(
            "candidate_not_eligible",
            {item["reason"] for item in report["excluded"]},
        )
        validate_shadow_report(report)
        self.assertFalse(report["baseline"]["injection_enabled"])

    def test_stale_conflicting_and_incompatible_lessons_are_excluded(self) -> None:
        stale = confirmed_lesson("LESSON-STALE", last_verified_at="2025-01-01")
        conflict = confirmed_lesson("LESSON-CONFLICT", contradicts=["OTHER"])
        incompatible = confirmed_lesson("LESSON-V2", contract_version="v2")

        report = shadow_retrieve([stale, conflict, incompatible], query())
        reasons = {item["lesson_id"]: item["reason"] for item in report["excluded"]}

        self.assertEqual(report["selected"], [])
        self.assertEqual(reasons["LESSON-STALE"], "stale")
        self.assertEqual(reasons["LESSON-CONFLICT"], "declared_conflict")
        self.assertEqual(reasons["LESSON-V2"], "contract_incompatible")

    def test_domain_path_failure_and_snapshot_mismatches_are_excluded(self) -> None:
        wrong_domain = confirmed_lesson("LESSON-DOMAIN", domain="teacher")
        wrong_path = confirmed_lesson("LESSON-PATH", changed_paths=["services/teacher"])
        exact_only = confirmed_lesson("LESSON-SNAPSHOT", snapshot_policy="exact")

        report = shadow_retrieve([wrong_domain, wrong_path, exact_only], query())
        reasons = {item["lesson_id"]: item["reason"] for item in report["excluded"]}

        self.assertEqual(reasons["LESSON-DOMAIN"], "domain_mismatch")
        self.assertEqual(reasons["LESSON-PATH"], "changed_path_mismatch")
        self.assertEqual(reasons["LESSON-SNAPSHOT"], "snapshot_mismatch")

    def test_result_limit_and_cost_are_reported_without_model_calls(self) -> None:
        first = confirmed_lesson("LESSON-A")
        second = confirmed_lesson("LESSON-B")
        report = shadow_retrieve([first, second], query(max_results=1))

        self.assertEqual(len(report["selected"]), 1)
        self.assertEqual(report["cost"]["model_calls"], 0)
        self.assertEqual(report["cost"]["selected_count"], 1)
        self.assertIn("result_limit", {item["reason"] for item in report["excluded"]})
        self.assertEqual(report["baseline"]["unchanged"], True)

    def test_invalid_query_and_unavailable_retrieval_fail_safe_to_baseline(self) -> None:
        with self.assertRaisesRegex(ValidationError, "raw_transcript"):
            validate_shadow_query({**query(), "raw_transcript": "private"})
        report = unavailable_shadow_report({"prompt": "private"}, "store unavailable")

        validate_shadow_report(report)
        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["query"], {})
        self.assertEqual(report["baseline"]["fallback"], "use_current_context_baseline")

    def test_documented_direct_cli_writes_shadow_report(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(__file__).resolve().parents[2]
            temp = Path(temp_dir)
            lesson_path = temp / "lesson.yaml"
            query_path = temp / "query.yaml"
            output_path = temp / "ShadowRetrieval.yaml"
            lesson_path.write_text(yaml.safe_dump(confirmed_lesson("LESSON-CLI")), encoding="utf-8")
            query_path.write_text(yaml.safe_dump(query()), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(root / "scripts/agent_loop/retrieval.py"),
                    "--lesson",
                    str(lesson_path),
                    "--query",
                    str(query_path),
                    "--output",
                    str(output_path),
                ],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = yaml.safe_load(output_path.read_text(encoding="utf-8"))
            validate_shadow_report(report)
            self.assertEqual(report["status"], "completed")
            self.assertEqual([item["lesson_id"] for item in report["selected"]], ["LESSON-CLI"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
