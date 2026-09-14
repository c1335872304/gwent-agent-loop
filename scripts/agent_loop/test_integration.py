"""Phase two IntegrationManifest and human-gate tests."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from .integration import (
    IntegrationManifestError,
    approve_integration,
    auto_integrate_isolated,
    build_integration_manifest,
    manifest_digest,
    record_applied_snapshot,
    validate_integration_manifest,
    write_integration_manifest,
)


def _git(root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=check,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class IntegrationManifestTests(unittest.TestCase):
    def _repo(self) -> tuple[Path, str, str]:
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        self.addCleanup(temp.cleanup)
        (root / "allowed.txt").write_text("base\n", encoding="utf-8")
        (root / "unrelated.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        _git(root, "config", "user.name", "Test")
        _git(root, "config", "user.email", "test@example.com")
        _git(root, "add", "allowed.txt", "unrelated.txt")
        _git(root, "commit", "-qm", "base")
        base = _git(root, "rev-parse", "HEAD")
        (root / "allowed.txt").write_text("candidate\n", encoding="utf-8")
        _git(root, "add", "allowed.txt")
        _git(root, "commit", "-qm", "candidate")
        candidate = _git(root, "rev-parse", "HEAD")
        return root, base, candidate

    def test_clean_candidate_is_ready_and_digest_is_stable(self) -> None:
        root, base, candidate = self._repo()
        manifest = build_integration_manifest(
            root,
            task_id="GW-INTEGRATION-001",
            task_revision=1,
            base_snapshot=base,
            candidate_snapshot=candidate,
            allowed_write_paths=("allowed.txt",),
            attempts=(
                {
                    "attempt_id": "owner-1",
                    "role": "product",
                    "base_snapshot": base,
                    "final_snapshot": candidate,
                    "changed_paths": ["allowed.txt"],
                    "status": "closed",
                },
                {
                    "attempt_id": "verifier-1",
                    "role": "test-verification",
                    "base_snapshot": candidate,
                    "final_snapshot": candidate,
                    "changed_paths": [],
                    "status": "closed",
                },
            ),
        )
        self.assertEqual(manifest["status"], "ready")
        self.assertEqual(manifest["changed_paths"], ["allowed.txt"])
        self.assertEqual(manifest["known_user_changes"], [])
        self.assertEqual(manifest_digest(manifest), manifest_digest(json.loads(json.dumps(manifest))))
        validate_integration_manifest(manifest)

    def test_dirty_parent_stops_at_human_gate(self) -> None:
        root, base, candidate = self._repo()
        (root / "user-note.txt").write_text("keep me\n", encoding="utf-8")
        manifest = build_integration_manifest(
            root,
            task_id="GW-INTEGRATION-002",
            task_revision=1,
            base_snapshot=base,
            candidate_snapshot=candidate,
            allowed_write_paths=("allowed.txt",),
        )
        self.assertEqual(manifest["status"], "human_required")
        self.assertEqual(manifest["human_gate"]["approved"], False)
        self.assertEqual(manifest["known_user_changes"], ["user-note.txt"])

    def test_out_of_scope_candidate_is_blocked(self) -> None:
        root, base, _candidate = self._repo()
        (root / "unrelated.txt").write_text("outside\n", encoding="utf-8")
        _git(root, "add", "unrelated.txt")
        _git(root, "commit", "-qm", "out-of-scope")
        candidate = _git(root, "rev-parse", "HEAD")
        manifest = build_integration_manifest(
            root,
            task_id="GW-INTEGRATION-003",
            task_revision=1,
            base_snapshot=base,
            candidate_snapshot=candidate,
            allowed_write_paths=("allowed.txt",),
        )
        self.assertEqual(manifest["status"], "blocked")
        self.assertEqual(manifest["scope_violations"], ["unrelated.txt"])
        validate_integration_manifest(manifest)

    def test_manifest_write_is_atomic_and_validated(self) -> None:
        root, base, candidate = self._repo()
        manifest = build_integration_manifest(
            root,
            task_id="GW-INTEGRATION-004",
            task_revision=1,
            base_snapshot=base,
            candidate_snapshot=candidate,
            allowed_write_paths=("allowed.txt",),
        )
        destination = root / ".agent-loop" / "integration.json"
        self.assertEqual(write_integration_manifest(destination, manifest), str(destination))
        self.assertEqual(json.loads(destination.read_text(encoding="utf-8"))["status"], "ready")
        with self.assertRaises(IntegrationManifestError):
            validate_integration_manifest({"schema": "wrong"})

    def test_approval_and_apply_are_explicit_manifest_transitions(self) -> None:
        root, base, candidate = self._repo()
        manifest = build_integration_manifest(
            root,
            task_id="GW-INTEGRATION-005",
            task_revision=1,
            base_snapshot=base,
            candidate_snapshot=candidate,
            allowed_write_paths=("allowed.txt",),
        )
        approved = approve_integration(manifest, approver="human-reviewer")
        self.assertEqual(approved["status"], "approved")
        self.assertTrue(approved["human_gate"]["approved"])
        applied = record_applied_snapshot(approved, applied_snapshot=candidate)
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(applied["apply"]["applied_snapshot"], candidate)

        dirty = dict(manifest)
        dirty["status"] = "human_required"
        with self.assertRaises(IntegrationManifestError):
            approve_integration(dirty, approver="human-reviewer")

    def test_disjoint_dirty_parent_requires_explicit_opt_in(self) -> None:
        root, base, candidate = self._repo()
        (root / "user-note.txt").write_text("keep me\n", encoding="utf-8")
        manifest = build_integration_manifest(
            root,
            task_id="GW-INTEGRATION-006",
            task_revision=1,
            base_snapshot=base,
            candidate_snapshot=candidate,
            allowed_write_paths=("allowed.txt",),
        )
        approved = approve_integration(
            manifest,
            approver="human-reviewer",
            allow_disjoint_user_changes=True,
        )
        self.assertEqual(approved["status"], "approved")
        self.assertTrue(approved["human_gate"]["approved"])

        (root / "allowed.txt").write_text("overlap\n", encoding="utf-8")
        overlapping = build_integration_manifest(
            root,
            task_id="GW-INTEGRATION-007",
            task_revision=1,
            base_snapshot=base,
            candidate_snapshot=candidate,
            allowed_write_paths=("allowed.txt",),
        )
        with self.assertRaises(IntegrationManifestError):
            approve_integration(
                overlapping,
                approver="human-reviewer",
                allow_disjoint_user_changes=True,
            )

    def test_isolated_auto_integration_preserves_dirty_parent(self) -> None:
        root, base, candidate = self._repo()
        _git(root, "checkout", "-q", base)
        (root / "user-note.txt").write_text("keep me\n", encoding="utf-8")
        manifest = build_integration_manifest(
            root,
            task_id="GW-INTEGRATION-008",
            task_revision=1,
            base_snapshot=base,
            candidate_snapshot=candidate,
            allowed_write_paths=("allowed.txt",),
        )
        integration_root = tempfile.TemporaryDirectory()
        self.addCleanup(integration_root.cleanup)
        updated = auto_integrate_isolated(
            manifest,
            worktree_root=Path(integration_root.name),
        )
        self.assertEqual(updated["status"], "human_required")
        isolated = updated["isolated_apply"]
        self.assertEqual(isolated["status"], "applied")
        self.assertTrue(isolated["parent_untouched"])
        self.assertEqual(_git(root, "rev-parse", "HEAD"), base)
        self.assertEqual(_git(root, "status", "--porcelain"), "?? user-note.txt")
        worktree = Path(isolated["worktree"])
        self.assertEqual(
            (worktree / "allowed.txt").read_text(encoding="utf-8"),
            "candidate\n",
        )
        self.assertNotEqual(isolated["applied_snapshot"], base)
        _git(root, "worktree", "remove", "--force", str(worktree))
        _git(root, "branch", "-D", isolated["branch"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
