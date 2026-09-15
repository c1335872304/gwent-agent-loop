"""Regression tests for the architecture bundle's context boundary."""

from __future__ import annotations

import unittest

from scripts.package_architecture_bundle import (
    CONTEXT_ENTRYPOINTS,
    archive_member_is_safe,
    collect_files,
    git_snapshot,
    is_historical_doc,
    manifest,
    relative,
)


class ArchitectureBundleTests(unittest.TestCase):
    def test_default_bundle_contains_current_context_and_excludes_history(self) -> None:
        files, _ = collect_files(include_tests=False, max_file_size=10 * 1024 * 1024)
        names = {relative(path) for path in files}

        self.assertTrue(set(CONTEXT_ENTRYPOINTS).issubset(names))
        self.assertFalse(any(is_historical_doc(path) for path in files))

    def test_history_requires_explicit_opt_in(self) -> None:
        current, _ = collect_files(include_tests=False, max_file_size=10 * 1024 * 1024)
        with_history, _ = collect_files(
            include_tests=False,
            max_file_size=10 * 1024 * 1024,
            include_history=True,
        )

        self.assertGreater(len(with_history), len(current))
        self.assertTrue(any(is_historical_doc(path) for path in with_history))

    def test_manifest_records_context_mode_and_git_provenance(self) -> None:
        text = manifest(
            [],
            [],
            1024,
            include_history=False,
            include_tests=False,
            snapshot={
                "head": "abc123",
                "branch": "codex/test",
                "worktree": "clean",
                "changed_paths": "0",
            },
        )

        self.assertIn("Git HEAD：abc123", text)
        self.assertIn("文档模式：current context only", text)
        self.assertIn("--include-history", text)
        self.assertIn("AGENT_ONBOARDING_INDEX.md", text)

    def test_git_snapshot_has_explicit_worktree_state(self) -> None:
        snapshot = git_snapshot()

        self.assertIn(snapshot["worktree"], {"clean", "dirty", "unavailable"})
        self.assertIn("head", snapshot)
        self.assertIn("changed_paths", snapshot)

    def test_archive_safety_rejects_compressed_and_traversal_members(self) -> None:
        self.assertFalse(archive_member_is_safe("gwent_v3_architecture/packages/a.zip"))
        self.assertFalse(archive_member_is_safe("gwent_v3_architecture/../secret.txt"))
        self.assertTrue(archive_member_is_safe("gwent_v3_architecture/docs/current/README.md"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
