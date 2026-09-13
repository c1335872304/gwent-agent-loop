"""Snapshot-to-TaskPacket write-scope tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from .errors import SnapshotDrift, ValidationError
from .snapshot import build_file_hash_manifest, validate_snapshot_scope


class SnapshotScopeTests(unittest.TestCase):
    def test_snapshot_scope_must_be_inside_allowed_write_scope(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "apps").mkdir()
            (root / "apps" / "web").mkdir()
            (root / "apps" / "web" / "x.txt").write_text("x", encoding="utf-8")
            manifest = build_file_hash_manifest(root, ["apps/web"])
            validate_snapshot_scope(manifest, ["apps"])
            with self.assertRaises(SnapshotDrift):
                validate_snapshot_scope(manifest, ["services"])

    def test_snapshot_scope_cannot_be_empty(self) -> None:
        with self.assertRaises(ValidationError):
            validate_snapshot_scope({}, ["apps"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
