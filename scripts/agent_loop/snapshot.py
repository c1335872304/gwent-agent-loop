"""Content-addressed workspace snapshot helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .errors import SnapshotDrift, ValidationError


@dataclass(frozen=True)
class SnapshotComparison:
    unchanged: tuple[str, ...]
    changed: tuple[str, ...]
    missing: tuple[str, ...]
    added: tuple[str, ...]

    @property
    def is_clean(self) -> bool:
        return not (self.changed or self.missing or self.added)


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _files_for(root: Path, paths: list[str] | tuple[str, ...]) -> list[Path]:
    found: list[Path] = []
    for raw in paths:
        target = (root / raw).resolve()
        target.relative_to(root.resolve())
        if target.is_file():
            found.append(target)
        elif target.is_dir():
            found.extend(path for path in target.rglob("*") if path.is_file())
        else:
            raise FileNotFoundError(raw)
    return sorted(set(found), key=lambda path: _relative(root, path))


def build_file_hash_manifest(root: str | Path, paths: list[str] | tuple[str, ...]) -> dict:
    root_path = Path(root).resolve()
    files: dict[str, dict[str, int | str]] = {}
    for path in _files_for(root_path, paths):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files[_relative(root_path, path)] = {"sha256": digest, "size": path.stat().st_size}
    payload = {"version": 1, "scope_paths": list(paths), "files": files}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["snapshot_id"] = "file-hash-manifest:" + hashlib.sha256(canonical).hexdigest()
    return payload


def validate_snapshot_scope(manifest: dict, allowed_write_paths: list[str] | tuple[str, ...]) -> None:
    """Ensure every declared snapshot scope is contained by TaskPacket scope."""
    declared = [str(path).strip("/") for path in manifest.get("scope_paths", []) if str(path).strip()]
    allowed = [str(path).strip("/") for path in allowed_write_paths if str(path).strip()]
    if not declared:
        raise ValidationError("snapshot must declare scope_paths")
    if not allowed:
        raise ValidationError("TaskPacket must declare allowed_write_paths before snapshot validation")
    outside = [
        path for path in declared
        if not any(path == parent or path.startswith(parent + "/") for parent in allowed)
    ]
    if outside:
        raise SnapshotDrift("snapshot scope exceeds TaskPacket allowed_write_paths: " + ", ".join(outside))


def compare_file_hash_manifest(root: str | Path, manifest: dict) -> SnapshotComparison:
    root_path = Path(root).resolve()
    expected = dict(manifest.get("files", {}))
    scope_paths = manifest.get("scope_paths", list(expected))
    actual_files = _files_for(root_path, list(scope_paths))
    actual: dict[str, dict[str, int | str]] = {}
    for path in actual_files:
        relative = _relative(root_path, path)
        actual[relative] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size}
    unchanged = sorted(path for path in expected.keys() & actual.keys() if expected[path] == actual[path])
    changed = sorted(path for path in expected.keys() & actual.keys() if expected[path] != actual[path])
    missing = sorted(set(expected) - set(actual))
    added = sorted(set(actual) - set(expected))
    return SnapshotComparison(tuple(unchanged), tuple(changed), tuple(missing), tuple(added))


def assert_file_hash_manifest_clean(root: str | Path, manifest: dict) -> None:
    comparison = compare_file_hash_manifest(root, manifest)
    if not comparison.is_clean:
        raise SnapshotDrift(
            "snapshot drift: "
            + json.dumps(
                {
                    "changed": comparison.changed,
                    "missing": comparison.missing,
                    "added": comparison.added,
                },
                ensure_ascii=False,
            )
        )
