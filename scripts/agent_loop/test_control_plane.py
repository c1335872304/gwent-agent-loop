"""Focused deterministic tests for Phase 2 control-plane primitives."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from .budget import BudgetLedger, BudgetLimits
from .errors import BudgetExceeded, LockConflict, SnapshotDrift, StateTransitionError, ValidationError
from .locks import LockTable
from .snapshot import assert_file_hash_manifest_clean, build_file_hash_manifest, compare_file_hash_manifest
from .state_machine import apply_event, validate_transition
from .validate_packet import load_yaml, validate_context_index, validate_profile

ROOT = Path(__file__).resolve().parents[2]


class StateMachineTests(unittest.TestCase):
    def test_valid_event_and_idempotent_replay(self) -> None:
        state = {"state": "RECEIVED", "event_seq": 0, "event_ids": []}
        event = {
            "event_id": "e1",
            "event_seq": 1,
            "from_status": "RECEIVED",
            "to_status": "TRIAGED",
            "task_revision": 1,
        }
        advanced = apply_event(state, event, expected_task_revision=1)
        self.assertEqual(advanced["state"], "TRIAGED")
        replayed = apply_event(advanced, event, expected_task_revision=1)
        self.assertEqual(replayed["event_seq"], 1)
        self.assertTrue(replayed["idempotent_replay"])

    def test_illegal_transition_and_stale_sequence_are_rejected(self) -> None:
        with self.assertRaises(StateTransitionError):
            validate_transition("RECEIVED", "COMPLETED")
        with self.assertRaises(StateTransitionError):
            apply_event(
                {"state": "RECEIVED", "event_seq": 0, "event_ids": []},
                {"event_id": "e2", "event_seq": 2, "from_status": "RECEIVED", "to_status": "TRIAGED", "task_revision": 1},
                expected_task_revision=1,
            )


class BudgetAndLockTests(unittest.TestCase):
    def test_budget_is_task_wide_and_warns_at_eighty_percent(self) -> None:
        ledger = BudgetLedger(BudgetLimits(2, 1, 1, 100, 100, 4, 30))
        ledger.reserve(role_runs=1, input_tokens=80, output_tokens=10, model_turns=3, elapsed_minutes=1)
        self.assertIn("input_tokens", ledger.warnings())
        with self.assertRaises(BudgetExceeded):
            ledger.reserve(role_runs=2)

    def test_overlapping_path_lock_is_rejected(self) -> None:
        locks = LockTable()
        locks.acquire(lease_id="l1", task_id="t1", packet_revision=1, snapshot="s1", keys=["path:apps/web"])
        with self.assertRaises(LockConflict):
            locks.acquire(lease_id="l2", task_id="t2", packet_revision=1, snapshot="s1", keys=["path:apps/web/frontend"])
        locks.release("l1", task_id="t1")
        locks.acquire(lease_id="l2", task_id="t2", packet_revision=1, snapshot="s1", keys=["path:apps/web/frontend"])


class SnapshotTests(unittest.TestCase):
    def test_changed_and_added_files_are_visible(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "tracked.txt").write_text("one", encoding="utf-8")
            manifest = build_file_hash_manifest(root, ["tracked.txt"])
            (root / "tracked.txt").write_text("two", encoding="utf-8")
            manifest["scope_paths"] = ["."]
            (root / "new.txt").write_text("new", encoding="utf-8")
            comparison = compare_file_hash_manifest(root, manifest)
            self.assertEqual(comparison.changed, ("tracked.txt",))
            self.assertEqual(comparison.added, ("new.txt",))
            with self.assertRaises(SnapshotDrift):
                assert_file_hash_manifest_clean(root, manifest)


class PhaseOneAssetTests(unittest.TestCase):
    def test_all_profiles_and_context_index_are_valid(self) -> None:
        profiles = sorted((ROOT / "docs/current/agent-loop/profiles").glob("*.yaml"))
        self.assertEqual(len(profiles), 6)
        for path in profiles:
            validate_profile(load_yaml(path), root=ROOT)
        validate_context_index(load_yaml(ROOT / "docs/current/agent-loop/CONTEXT_INDEX.yaml"), root=ROOT)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
