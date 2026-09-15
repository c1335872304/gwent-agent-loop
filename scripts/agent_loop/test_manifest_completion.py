"""Completion-gate tests for RunManifest."""

from __future__ import annotations

import unittest

from .errors import ValidationError
from .manifest import validate_run_manifest


def _manifest(status: str = "completed") -> dict:
    return {
        "protocol_version": 1,
        "run_id": "R1",
        "task_id": "T1",
        "task_revision": 1,
        "runner": "manual",
        "status": status,
        "workspace": {"base_snapshot": "s1", "final_snapshot": "s2"},
        "budget": {"max_role_runs": 1, "max_subtasks": 0, "max_input_tokens": 10, "max_output_tokens": 10, "max_model_turns": 1, "max_elapsed_minutes": 1, "role_runs_used": 1, "subtasks_used": 0, "input_tokens_used": 1, "output_tokens_used": 1, "model_turns_used": 1, "elapsed_minutes": 1},
        "role_runs": [{"attempt_id": "a1", "profile_id": "p1", "status": "closed"}],
        "artifacts": [],
        "state_events": [],
        "gates": [{"gate_id": "g1", "status": "passed"}],
        "termination": {"final_report_ref": "artifacts/final.json"},
    }


class ManifestCompletionTests(unittest.TestCase):
    def test_completed_manifest_requires_final_evidence(self) -> None:
        manifest = _manifest()
        validate_run_manifest(manifest)
        manifest["workspace"]["final_snapshot"] = ""
        with self.assertRaises(ValidationError):
            validate_run_manifest(manifest)

    def test_non_completed_manifest_can_wait_for_final_evidence(self) -> None:
        manifest = _manifest("running")
        manifest["workspace"]["final_snapshot"] = ""
        manifest["termination"] = {}
        validate_run_manifest(manifest)

    def test_blocked_manifest_preserves_declared_budget_overrun(self) -> None:
        manifest = _manifest("human_required")
        manifest["budget"]["role_runs_used"] = 2
        manifest["budget"]["exhausted_limits"] = ["role_runs_used"]
        validate_run_manifest(manifest)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
