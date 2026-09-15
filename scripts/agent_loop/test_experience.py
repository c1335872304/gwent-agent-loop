"""Regression tests for candidate-only detour analysis."""

from __future__ import annotations

import unittest
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from .errors import ValidationError
from .experience import (
    build_candidate_lessons,
    build_experience_manifest,
    analyze_path,
    validate_experience_manifest,
    write_experience_store,
)


def avoidable_trace() -> list[dict[str, object]]:
    return [
        {
            "seq": 1,
            "tool": "git",
            "operation": "apply_with_index",
            "target_scope": "docs/current",
            "status": "FAIL",
            "failure_class": "PROTOCOL_FAILURE",
            "error": "AGENTS.md does not match index",
            "preflight_available": True,
            "elapsed_seconds": 1.5,
        },
        {
            "seq": 2,
            "tool": "git",
            "operation": "explicit_path_apply",
            "target_scope": "docs/current",
            "status": "PASS",
            "fallback_of": 1,
            "elapsed_seconds": 2.0,
        },
    ]


class ExperienceExtractionTests(unittest.TestCase):
    def test_analyzer_identifies_avoidable_failure_and_verified_fallback(self) -> None:
        analysis = analyze_path(
            avoidable_trace(),
            task_id="TASK-1",
            task_revision=1,
            planned_actions=[{"operation": "explicit_path_apply"}],
            base_snapshot="git:base",
            final_snapshot="git:final",
        )

        self.assertEqual(analysis["schema"], "agent-loop.path-analysis.v1")
        self.assertEqual(analysis["counts"]["avoidable_detours"], 1)
        self.assertEqual(analysis["counts"]["successful_fallbacks"], 1)
        self.assertEqual(analysis["detours"][0]["resolution"]["resolved_by_seq"], 2)
        self.assertNotIn("AGENTS.md does not match index", str(analysis))

    def test_only_avoidable_detours_produce_candidate_lessons(self) -> None:
        analysis = analyze_path(
            avoidable_trace(),
            task_id="TASK-1",
            base_snapshot="git:base",
            final_snapshot="git:final",
        )
        lessons = build_candidate_lessons(
            analysis,
            domain="project",
            task_type="path_scoped_integration",
            source_refs=["trace.jsonl", "RunManifest.yaml", "TestReport.yaml"],
            changed_paths=["docs/current"],
            contract_versions={"agent-loop": "experience:v1"},
        )

        self.assertEqual(len(lessons), 1)
        self.assertEqual(lessons[0]["status"], "candidate")
        self.assertFalse(lessons[0]["privacy"]["contains_raw_conversation"])
        self.assertIn("git:apply_with_index", lessons[0]["avoidance"]["avoid"])
        self.assertIn("git:explicit_path_apply", lessons[0]["avoidance"]["prefer"])

    def test_necessary_exploration_is_recorded_but_not_promoted_to_candidate(self) -> None:
        trace = [
            {
                "seq": 1,
                "tool": "host",
                "operation": "lookup_session",
                "status": "FAIL",
                "failure_class": "EXTERNAL_DEPENDENCY",
                "error": "first lookup against an unknown host",
                "necessary_exploration": True,
            },
            {
                "seq": 2,
                "tool": "host",
                "operation": "create_session",
                "status": "PASS",
            },
        ]
        analysis = analyze_path(trace, task_id="TASK-2")
        lessons = build_candidate_lessons(
            analysis,
            domain="project",
            task_type="host_probe",
            source_refs=["trace.jsonl"],
        )

        self.assertEqual(analysis["detours"][0]["classification"], "necessary_exploration")
        self.assertEqual(lessons, [])

    def test_changed_preconditions_do_not_count_as_repeated_detour(self) -> None:
        trace = [
            {
                "seq": 1,
                "tool": "docker",
                "operation": "healthcheck",
                "status": "FAIL",
                "failure_class": "DOCKER_FAILURE",
                "error": "service not ready",
            },
            {
                "seq": 2,
                "tool": "docker",
                "operation": "healthcheck",
                "status": "PASS",
                "preconditions_changed": True,
            },
        ]
        analysis = analyze_path(trace, task_id="TASK-3")

        self.assertEqual(analysis["detours"][0]["classification"], "unclassified_failure")
        self.assertEqual(analysis["counts"]["avoidable_detours"], 0)

    def test_environment_and_scope_failures_require_explicit_successful_fallbacks(self) -> None:
        trace = [
            {
                "seq": 1,
                "tool": "pytest",
                "operation": "host_pytest",
                "status": "FAIL",
                "failure_class": "ENVIRONMENT_FAILURE",
                "error": "host dependency differs from pinned image",
                "preflight_available": True,
            },
            {
                "seq": 2,
                "tool": "git",
                "operation": "broad_patch",
                "target_scope": "repository",
                "status": "FAIL",
                "failure_class": "WRONG_FILE_SCOPE",
                "error": "patch includes unrelated paths",
                "preflight_available": True,
            },
            {
                "seq": 3,
                "tool": "docker",
                "operation": "docker_pytest",
                "target_scope": "service",
                "status": "PASS",
                "fallback_of": 1,
            },
            {
                "seq": 4,
                "tool": "git",
                "operation": "explicit_path_patch",
                "target_scope": "docs/current",
                "status": "PASS",
                "fallback_of": 2,
            },
        ]
        analysis = analyze_path(
            trace,
            task_id="TASK-ENV-SCOPE",
            base_snapshot="git:base",
            final_snapshot="git:final",
        )
        lessons = build_candidate_lessons(
            analysis,
            domain="project",
            task_type="verification",
            source_refs=["trace.jsonl"],
            contract_versions={"agent-loop": "experience:v1"},
        )

        self.assertEqual(analysis["counts"]["avoidable_detours"], 2)
        self.assertEqual(len(lessons), 2)
        self.assertEqual(
            {lesson["trigger"]["failure_class"] for lesson in lessons},
            {"ENVIRONMENT_FAILURE", "WRONG_FILE_SCOPE"},
        )

    def test_repeated_action_is_avoidable_but_unrelated_pass_is_not_a_fallback(self) -> None:
        trace = [
            {
                "seq": 1,
                "tool": "git",
                "operation": "apply_with_index",
                "status": "FAIL",
                "failure_class": "PROTOCOL_FAILURE",
                "error": "index mismatch",
            },
            {
                "seq": 2,
                "tool": "git",
                "operation": "apply_with_index",
                "status": "FAIL",
                "failure_class": "PROTOCOL_FAILURE",
                "error": "index mismatch again",
            },
            {"seq": 3, "tool": "git", "operation": "status", "status": "PASS"},
        ]
        analysis = analyze_path(trace, task_id="TASK-RETRY")

        self.assertTrue(analysis["detours"][0]["repeated_action"])
        self.assertEqual(analysis["detours"][0]["classification"], "avoidable_detour")
        self.assertEqual(analysis["detours"][0]["resolution"], {})

    def test_preflight_without_explicit_alternative_does_not_guess_a_fallback(self) -> None:
        trace = [
            {
                "seq": 1,
                "tool": "git",
                "operation": "apply_with_index",
                "status": "FAIL",
                "failure_class": "PROTOCOL_FAILURE",
                "error": "index mismatch",
                "preflight_available": True,
            },
            {"seq": 2, "tool": "git", "operation": "status", "status": "PASS"},
        ]
        analysis = analyze_path(trace, task_id="TASK-NO-GUESS")

        self.assertEqual(analysis["detours"][0]["classification"], "unclassified_failure")
        self.assertEqual(analysis["counts"]["successful_fallbacks"], 0)

    def test_missing_snapshot_or_contract_withholds_candidate(self) -> None:
        with_snapshot = analyze_path(
            avoidable_trace(), task_id="TASK-MISSING-CONTRACT", final_snapshot="git:final"
        )
        self.assertEqual(
            build_candidate_lessons(
                with_snapshot,
                domain="project",
                task_type="integration",
                source_refs=["trace.jsonl"],
            ),
            [],
        )
        with_contract = analyze_path(
            avoidable_trace(), task_id="TASK-MISSING-SNAPSHOT"
        )
        self.assertEqual(
            build_candidate_lessons(
                with_contract,
                domain="project",
                task_type="integration",
                source_refs=["trace.jsonl"],
                contract_versions={"agent-loop": "experience:v1"},
            ),
            [],
        )

    def test_documented_direct_cli_creates_candidate_only_store(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(__file__).resolve().parents[2]
            temp = Path(temp_dir)
            trace_path = temp / "trace.yaml"
            trace_path.write_text(yaml.safe_dump(avoidable_trace()), encoding="utf-8")
            output_dir = temp / "experience"
            result = subprocess.run(
                [
                    sys.executable,
                    str(root / "scripts/agent_loop/experience.py"),
                    "--trace",
                    str(trace_path),
                    "--task-id",
                    "TASK-CLI",
                    "--snapshot",
                    "git:final",
                    "--contract-version",
                    "agent-loop=experience:v1",
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = yaml.safe_load(
                (output_dir / "ExperienceManifest.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["status"], "candidate_only")
            self.assertFalse(manifest["injection"]["enabled"])
            self.assertEqual(len(manifest["candidate_lesson_ids"]), 1)

    def test_raw_conversation_fields_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValidationError, "prompt is not allowed"):
            analyze_path(
                [{"seq": 1, "tool": "codex", "operation": "open", "status": "PASS", "prompt": "secret"}],
                task_id="TASK-4",
            )

    def test_store_remains_candidate_only(self) -> None:
        analysis = analyze_path(
            avoidable_trace(),
            task_id="TASK-5",
            base_snapshot="git:base",
            final_snapshot="git:final",
        )
        lessons = build_candidate_lessons(
            analysis,
            domain="project",
            task_type="integration",
            source_refs=["trace.jsonl"],
            contract_versions={"agent-loop": "experience:v1"},
        )
        experience_manifest = build_experience_manifest(
            analysis,
            lessons,
            source_refs=["trace.jsonl"],
            contract_versions={"agent-loop": "experience:v1"},
        )
        validate_experience_manifest(experience_manifest)

        with TemporaryDirectory() as temp_dir:
            write_experience_store(temp_dir, experience_manifest, lessons)
            saved = yaml.safe_load(
                (Path(temp_dir) / "ExperienceManifest.yaml").read_text(encoding="utf-8")
            )
            self.assertFalse(saved["injection"]["enabled"])
            self.assertTrue((Path(temp_dir) / "candidate" / f"{lessons[0]['lesson_id']}.yaml").is_file())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
