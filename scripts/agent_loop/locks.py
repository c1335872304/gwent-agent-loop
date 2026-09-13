"""Deterministic in-process write/contract lock table."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import LockConflict


@dataclass(frozen=True)
class LockLease:
    lease_id: str
    task_id: str
    packet_revision: int
    snapshot: str
    keys: tuple[str, ...]


def _overlaps(left: str, right: str) -> bool:
    if left == right:
        return True
    if left.startswith("path:") and right.startswith("path:"):
        lpath = left[5:].rstrip("/") + "/"
        rpath = right[5:].rstrip("/") + "/"
        return lpath.startswith(rpath) or rpath.startswith(lpath)
    return False


class LockTable:
    def __init__(self) -> None:
        self._leases: dict[str, LockLease] = {}

    def acquire(
        self,
        *,
        lease_id: str,
        task_id: str,
        packet_revision: int,
        snapshot: str,
        keys: list[str] | tuple[str, ...],
    ) -> LockLease:
        normalized = tuple(sorted(set(str(key).strip() for key in keys if str(key).strip())))
        if not normalized:
            raise LockConflict("cannot acquire an empty lock set")
        existing = self._leases.get(lease_id)
        if existing is not None:
            if existing.task_id == task_id and existing.keys == normalized:
                return existing
            raise LockConflict(f"lease id already belongs to another lock: {lease_id}")
        for current in self._leases.values():
            conflict = next(
                (requested for requested in normalized for held in current.keys if _overlaps(requested, held)),
                None,
            )
            if conflict is not None:
                raise LockConflict(
                    f"lock overlap: requested {conflict!r} conflicts with "
                    f"lease {current.lease_id!r} owned by {current.task_id!r}"
                )
        lease = LockLease(lease_id, task_id, packet_revision, snapshot, normalized)
        self._leases[lease_id] = lease
        return lease

    def release(self, lease_id: str, *, task_id: str) -> None:
        lease = self._leases.get(lease_id)
        if lease is None:
            return
        if lease.task_id != task_id:
            raise LockConflict(f"only {lease.task_id!r} may release lease {lease_id!r}")
        del self._leases[lease_id]

    def active(self) -> tuple[LockLease, ...]:
        return tuple(self._leases.values())
