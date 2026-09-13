"""Cross-instance tests for persistent Agent Loop locks."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from .errors import LockConflict
from .file_locks import PersistentLockTable


class PersistentLockTests(unittest.TestCase):
    def test_second_process_view_cannot_overlap_until_release(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            first = PersistentLockTable(Path(raw) / "locks")
            second = PersistentLockTable(Path(raw) / "locks")
            first.acquire(lease_id="l1", task_id="t1", packet_revision=1, snapshot="s1", keys=["path:apps/web"], now=100.0)
            with self.assertRaises(LockConflict):
                second.acquire(lease_id="l2", task_id="t2", packet_revision=1, snapshot="s1", keys=["path:apps/web/frontend"], now=101.0)
            first.release("l1", task_id="t1")
            second.acquire(lease_id="l2", task_id="t2", packet_revision=1, snapshot="s1", keys=["path:apps/web/frontend"], now=101.0)

    def test_expired_lease_requires_explicit_reclaim(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            table = PersistentLockTable(Path(raw) / "locks")
            table.acquire(lease_id="l1", task_id="t1", packet_revision=1, snapshot="s1", keys=["contract:core_http"], ttl_seconds=10, now=100.0)
            self.assertEqual(table.active(now=111.0), ())
            table.reclaim_expired("l1", now=111.0)
            self.assertEqual(table.active(now=111.0), ())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
