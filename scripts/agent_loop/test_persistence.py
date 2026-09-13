"""Persistence tests for restart and idempotency semantics."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from .errors import ValidationError
from .persistence import TaskStore


class PersistenceTests(unittest.TestCase):
    def test_event_survives_reopen_and_replay_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            store = TaskStore(Path(raw) / "tasks")
            store.initialize("T1", packet_revision=1)
            event = {"event_id": "e1", "event_seq": 1, "from_status": "RECEIVED", "to_status": "TRIAGED", "task_revision": 1}
            first = store.append_event("T1", event)
            self.assertEqual(first["state"], "TRIAGED")
            reopened = TaskStore(Path(raw) / "tasks")
            self.assertEqual(reopened.read_state("T1")["state"], "TRIAGED")
            replay = reopened.append_event("T1", event)
            self.assertTrue(replay["idempotent_replay"])
            self.assertEqual(reopened._event_log("T1").read_text(encoding="utf-8").splitlines().__len__(), 1)

    def test_task_and_artifact_names_are_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            store = TaskStore(Path(raw) / "tasks")
            with self.assertRaises(ValidationError):
                store.initialize("../escape", packet_revision=1)
            store.initialize("T2", packet_revision=1)
            ref = store.write_artifact("T2", "change-report", {"ok": True})
            self.assertTrue(ref.endswith("artifacts/change-report.json"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
