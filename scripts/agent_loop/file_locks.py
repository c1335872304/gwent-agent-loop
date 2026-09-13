"""Cross-process lock files for Agent Loop path and contract ownership."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import LockConflict, ValidationError
from .locks import _overlaps

_SAFE_LEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


@dataclass(frozen=True)
class FileLease:
    lease_id: str
    task_id: str
    packet_revision: int
    snapshot: str
    keys: tuple[str, ...]
    expires_at: float


class PersistentLockTable:
    """Use atomic file creation plus a short table mutex for local processes."""

    def __init__(self, root: str | Path = ".agent-loop/locks") -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._mutex = self.root / ".table.mutex"

    def _lease_path(self, lease_id: str) -> Path:
        if not _SAFE_LEASE_ID.fullmatch(lease_id):
            raise ValidationError(f"unsafe lease_id: {lease_id!r}")
        return self.root / f"{lease_id}.json"

    def _acquire_mutex(self, timeout_seconds: float = 1.0) -> None:
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                with self._mutex.open("x", encoding="ascii") as handle:
                    handle.write(str(os.getpid()))
                return
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise LockConflict("persistent lock table mutex is busy")
                time.sleep(0.02)

    def _release_mutex(self) -> None:
        try:
            self._mutex.unlink()
        except FileNotFoundError:
            pass

    def _read(self, path: Path) -> FileLease:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return FileLease(
            lease_id=str(raw["lease_id"]),
            task_id=str(raw["task_id"]),
            packet_revision=int(raw["packet_revision"]),
            snapshot=str(raw["snapshot"]),
            keys=tuple(sorted(set(str(key) for key in raw["keys"]))),
            expires_at=float(raw["expires_at"]),
        )

    def active(self, *, now: float | None = None) -> tuple[FileLease, ...]:
        timestamp = time.time() if now is None else now
        leases: list[FileLease] = []
        for path in sorted(self.root.glob("*.json")):
            lease = self._read(path)
            if lease.expires_at > timestamp:
                leases.append(lease)
        return tuple(leases)

    def acquire(
        self,
        *,
        lease_id: str,
        task_id: str,
        packet_revision: int,
        snapshot: str,
        keys: list[str] | tuple[str, ...],
        ttl_seconds: float = 900.0,
        now: float | None = None,
    ) -> FileLease:
        if ttl_seconds <= 0:
            raise LockConflict("persistent lock ttl must be positive")
        normalized = tuple(sorted(set(str(key).strip() for key in keys if str(key).strip())))
        if not normalized:
            raise LockConflict("cannot acquire an empty persistent lock set")
        timestamp = time.time() if now is None else now
        self._acquire_mutex()
        try:
            target = self._lease_path(lease_id)
            if target.exists():
                existing = self._read(target)
                if existing.task_id == task_id and existing.keys == normalized:
                    return existing
                raise LockConflict(f"lease id already exists: {lease_id}")
            for existing in self.active(now=timestamp):
                if any(requested == held or _overlaps(requested, held) for requested in normalized for held in existing.keys):
                    raise LockConflict(
                        f"persistent lock overlap with {existing.lease_id!r} owned by {existing.task_id!r}"
                    )
            lease = FileLease(lease_id, task_id, packet_revision, snapshot, normalized, timestamp + ttl_seconds)
            with target.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(lease.__dict__, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
            return lease
        finally:
            self._release_mutex()

    def release(self, lease_id: str, *, task_id: str) -> None:
        self._acquire_mutex()
        try:
            target = self._lease_path(lease_id)
            if not target.exists():
                return
            lease = self._read(target)
            if lease.task_id != task_id:
                raise LockConflict(f"only {lease.task_id!r} may release lease {lease_id!r}")
            target.unlink()
        finally:
            self._release_mutex()

    def reclaim_expired(self, lease_id: str, *, now: float | None = None) -> None:
        timestamp = time.time() if now is None else now
        self._acquire_mutex()
        try:
            target = self._lease_path(lease_id)
            if not target.exists():
                return
            lease = self._read(target)
            if lease.expires_at > timestamp:
                raise LockConflict(f"lease {lease_id!r} has not expired")
            target.unlink()
        finally:
            self._release_mutex()
