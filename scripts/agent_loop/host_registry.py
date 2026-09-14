"""Durable Host-owned registry for external Agent Loop sessions.

The Scheduler is allowed to restart; the Host session is not recreated as a
side effect of that restart.  This small JSON registry is the local reference
implementation of that boundary.  A production Host may replace it with a
database or service, but it must preserve the same identity and fail-closed
semantics.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class HostRegistryError(ValueError):
    """Raised when a durable Host session record is unsafe or invalid."""


_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
_SCHEMA = "agent-loop.host-session.v1"


def _text(value: Any, label: str, *, token: bool = False) -> str:
    result = str(value or "").strip()
    if not result or "\x00" in result or "\n" in result or "\r" in result:
        raise HostRegistryError(f"{label} must be a non-empty single-line value")
    if token and not _SAFE_TOKEN.fullmatch(result):
        raise HostRegistryError(f"invalid {label}")
    return result


def _non_negative_int(value: Any, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise HostRegistryError(f"invalid {label}") from exc
    if result < 0:
        raise HostRegistryError(f"{label} must be non-negative")
    return result


def _non_negative_float(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise HostRegistryError(f"invalid {label}") from exc
    if result < 0:
        raise HostRegistryError(f"{label} must be non-negative")
    return result


@dataclass(frozen=True)
class HostSessionRecord:
    """All information required to find and verify one Host session."""

    runner_ref: str
    thread_id: str
    host_id: str
    project_id: str
    task_id: str
    task_revision: int
    attempt_id: str
    role: str
    profile_revision: str
    snapshot: str
    write_scope: tuple[str, ...]
    session_dir: str
    worktree: str
    output_path: str
    stderr_path: str
    stdout_path: str
    pid: int | None
    status: str
    resume_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_seconds: float = 0.0
    report_ref: str | None = None
    final_snapshot: str | None = None
    changed_paths: tuple[str, ...] = ()
    reason: str | None = None
    updated_at: str = ""
    sandbox_mode: str = "workspace-write"

    def __post_init__(self) -> None:
        for value, label in (
            (self.runner_ref, "runner_ref"),
            (self.thread_id, "thread_id"),
            (self.host_id, "host_id"),
            (self.project_id, "project_id"),
            (self.task_id, "task_id"),
            (self.attempt_id, "attempt_id"),
            (self.role, "role"),
            (self.profile_revision, "profile_revision"),
            (self.snapshot, "snapshot"),
            (self.session_dir, "session_dir"),
            (self.worktree, "worktree"),
            (self.output_path, "output_path"),
            (self.stderr_path, "stderr_path"),
            (self.stdout_path, "stdout_path"),
            (self.status, "status"),
        ):
            _text(value, label)
        if self.task_revision < 1:
            raise HostRegistryError("task_revision must be positive")
        if not self.write_scope or any(not str(item).strip() for item in self.write_scope):
            raise HostRegistryError("write_scope must not be empty")
        if self.pid is not None and int(self.pid) <= 0:
            raise HostRegistryError("pid must be positive when present")
        _non_negative_int(self.resume_count, "resume_count")
        _non_negative_int(self.input_tokens, "input_tokens")
        _non_negative_int(self.output_tokens, "output_tokens")
        _non_negative_float(self.elapsed_seconds, "elapsed_seconds")
        if self.sandbox_mode not in {"workspace-write", "danger-full-access"}:
            raise HostRegistryError("unsupported sandbox_mode")
        if any(not str(path).strip() for path in self.changed_paths):
            raise HostRegistryError("changed_paths cannot contain empty values")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": _SCHEMA,
            "runner_ref": self.runner_ref,
            "thread_id": self.thread_id,
            "host_id": self.host_id,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "attempt_id": self.attempt_id,
            "role": self.role,
            "profile_revision": self.profile_revision,
            "snapshot": self.snapshot,
            "write_scope": list(self.write_scope),
            "session_dir": self.session_dir,
            "worktree": self.worktree,
            "output_path": self.output_path,
            "stderr_path": self.stderr_path,
            "stdout_path": self.stdout_path,
            "pid": self.pid,
            "status": self.status,
            "resume_count": self.resume_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "elapsed_seconds": self.elapsed_seconds,
            "report_ref": self.report_ref,
            "final_snapshot": self.final_snapshot,
            "changed_paths": list(self.changed_paths),
            "reason": self.reason,
            "sandbox_mode": self.sandbox_mode,
            "updated_at": self.updated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "HostSessionRecord":
        if not isinstance(payload, Mapping) or payload.get("schema") != _SCHEMA:
            raise HostRegistryError("unsupported Host session record schema")
        raw_scope = payload.get("write_scope")
        raw_changed = payload.get("changed_paths", ())
        if not isinstance(raw_scope, (list, tuple)) or not isinstance(raw_changed, (list, tuple)):
            raise HostRegistryError("Host session paths must be lists")
        pid = payload.get("pid")
        if pid is not None:
            pid = _non_negative_int(pid, "pid")
        optional = {}
        for name in ("report_ref", "final_snapshot", "reason"):
            value = payload.get(name)
            optional[name] = str(value) if value is not None else None
        return cls(
            runner_ref=_text(payload.get("runner_ref"), "runner_ref"),
            thread_id=_text(payload.get("thread_id"), "thread_id"),
            host_id=_text(payload.get("host_id"), "host_id"),
            project_id=_text(payload.get("project_id"), "project_id"),
            task_id=_text(payload.get("task_id"), "task_id"),
            task_revision=_non_negative_int(payload.get("task_revision"), "task_revision"),
            attempt_id=_text(payload.get("attempt_id"), "attempt_id"),
            role=_text(payload.get("role"), "role"),
            profile_revision=_text(payload.get("profile_revision"), "profile_revision"),
            snapshot=_text(payload.get("snapshot"), "snapshot"),
            write_scope=tuple(_text(item, "write_scope item") for item in raw_scope),
            session_dir=_text(payload.get("session_dir"), "session_dir"),
            worktree=_text(payload.get("worktree"), "worktree"),
            output_path=_text(payload.get("output_path"), "output_path"),
            stderr_path=_text(payload.get("stderr_path"), "stderr_path"),
            stdout_path=_text(payload.get("stdout_path"), "stdout_path"),
            pid=pid,
            status=_text(payload.get("status"), "status"),
            resume_count=_non_negative_int(payload.get("resume_count", 0), "resume_count"),
            input_tokens=_non_negative_int(payload.get("input_tokens", 0), "input_tokens"),
            output_tokens=_non_negative_int(payload.get("output_tokens", 0), "output_tokens"),
            elapsed_seconds=_non_negative_float(payload.get("elapsed_seconds", 0.0), "elapsed_seconds"),
            report_ref=optional["report_ref"],
            final_snapshot=optional["final_snapshot"],
            changed_paths=tuple(_text(item, "changed_paths item") for item in raw_changed),
            reason=optional["reason"],
            updated_at=_text(payload.get("updated_at"), "updated_at"),
            sandbox_mode=str(payload.get("sandbox_mode") or "workspace-write"),
        )


class HostSessionRegistry:
    """Atomically persist and retrieve Host session records by runner_ref."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key(runner_ref: str) -> str:
        return hashlib.sha256(runner_ref.encode("utf-8")).hexdigest()

    def _path(self, runner_ref: str) -> Path:
        _text(runner_ref, "runner_ref")
        return self.root / f"{self._key(runner_ref)}.json"

    def put(self, record: HostSessionRecord) -> HostSessionRecord:
        if not record.updated_at:
            record = replace(
                record,
                updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
        target = self._path(record.runner_ref)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(record.as_dict(), handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(temp_name, target)
        except BaseException:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise
        return record

    def get(self, runner_ref: str) -> HostSessionRecord | None:
        target = self._path(runner_ref)
        if not target.is_file():
            return None
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HostRegistryError(f"cannot read Host session record: {target}") from exc
        record = HostSessionRecord.from_dict(payload)
        if record.runner_ref != runner_ref:
            raise HostRegistryError("Host session registry key/reference mismatch")
        return record

    def require(self, runner_ref: str) -> HostSessionRecord:
        record = self.get(runner_ref)
        if record is None:
            raise HostRegistryError(f"unknown Host runner_ref: {runner_ref}")
        return record
