"""Regression checks for the first recorded Agent Loop pilot."""

from __future__ import annotations

import unittest
from pathlib import Path

from .manifest import validate_run_manifest
from .validate_packet import load_yaml, validate_task_packet


ROOT = Path(__file__).resolve().parents[2]
PILOT_DIR = ROOT / "docs" / "current" / "agent-loop" / "pilots"


class PilotArtifactTests(unittest.TestCase):
    def test_recorded_packet_and_manifest_match_protocol(self) -> None:
        validate_task_packet(load_yaml(PILOT_DIR / "PILOT_001_TASK_PACKET.yaml"))
        validate_run_manifest(load_yaml(PILOT_DIR / "PILOT_001_RUN_MANIFEST.yaml"))

    def test_report_preserves_pilot_boundary(self) -> None:
        report = (PILOT_DIR / "PILOT_001_REPORT.md").read_text(encoding="utf-8")
        self.assertIn("Pilot 001", report)
        self.assertIn("Phase 4", report)
        self.assertIn("Codex", report)

    def test_blocked_pilot_preserves_verification_boundary(self) -> None:
        validate_task_packet(load_yaml(PILOT_DIR / "PILOT_003_TASK_PACKET.yaml"))
        manifest = load_yaml(PILOT_DIR / "PILOT_003_RUN_MANIFEST.yaml")
        validate_run_manifest(manifest)
        report = load_yaml(PILOT_DIR / "PILOT_003_TEST_REPORT.yaml")
        self.assertEqual(manifest["status"], "blocked")
        self.assertEqual(report["overall"], "BLOCKED")
        self.assertEqual(report["failures"][0]["classification"], "ENVIRONMENT_FAILURE")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
