"""Bounded execution records for the Agent Loop runner.

This module deliberately stays model-free. It binds every runner event to the
same task packet identity and writes a small recoverable record after each
accepted transition.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .runner import RunnerEvent, RunnerRequest, runner_event_dict


class ExecutionRecordError(ValueError):
    """Raised when a runner event cannot be safely recorded."""


def _safe_token(value: str, label: str) -> str:
    if not value or not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        raise ExecutionRecordError(f"invalid {label}")
    return value


@dataclass(frozen=True)
class ExecutionIdentity:
    task_id: str
    task_revision: int
    attempt_id: str
    role: str
    profile_revision: str
    snapshot: str
    write_scope: tuple[str, ...]

    @classmethod
    def from_request(cls, request: RunnerRequest) -> "ExecutionIdentity":
        return cls(
            task_id=request.task_id,
            task_revision=request.task_revision,
            attempt_id=request.attempt_id,
            role=request.role,
            profile_revision=request.profile_revision,
            snapshot=request.snapshot,
            write_scope=tuple(request.write_scope),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "attempt_id": self.attempt_id,
            "role": self.role,
            "profile_revision": self.profile_revision,
            "snapshot": self.snapshot,
            "write_scope": list(self.write_scope),
        }


@dataclass
class ExecutionRecord:
    """The bounded, serializable history of one runner attempt."""

    identity: ExecutionIdentity
    runner_ref: Optional[str] = None
    status: str = "new"
    resume_count: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    report_ref: Optional[str] = None
    last_reason: Optional[str] = None

    def accept(self, event: RunnerEvent, max_resumes: int) -> dict[str, Any]:
        if len(self.events) >= 32:
            raise ExecutionRecordError("runner event limit exceeded")

        expected = self.identity
        actual_scope = tuple(event.write_scope)
        if (
            event.task_id != expected.task_id
            or event.task_revision != expected.task_revision
            or event.attempt_id != expected.attempt_id
            or event.profile_revision != expected.profile_revision
            or event.snapshot != expected.snapshot
            or actual_scope != expected.write_scope
        ):
            raise ExecutionRecordError("runner event identity mismatch")

        if self.runner_ref is None:
            self.runner_ref = event.runner_ref
        elif self.runner_ref != event.runner_ref:
            raise ExecutionRecordError("runner reference mismatch")

        if event.resume_count > max_resumes:
            raise ExecutionRecordError("runner resume limit exceeded")
        if event.resume_count < self.resume_count:
            raise ExecutionRecordError("runner resume count moved backwards")

        payload = runner_event_dict(event)
        payload["record_seq"] = len(self.events) + 1
        self.events.append(payload)
        self.status = event.status
        self.resume_count = event.resume_count
        if event.reason:
            self.last_reason = event.reason
        if event.report_ref:
            self.report_ref = event.report_ref
        return payload

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "agent-loop.execution-record.v1",
            "identity": self.identity.as_dict(),
            "runner_ref": self.runner_ref,
            "status": self.status,
            "resume_count": self.resume_count,
            "events": list(self.events),
            "artifact_refs": list(self.artifact_refs),
            "report_ref": self.report_ref,
            "last_reason": self.last_reason,
        }

    def to_manifest_role_run(self) -> dict[str, Any]:
        """Project the record into the RunManifest role_runs shape."""
        status_map = {
            "new": "planned",
            "running": "running",
            "interrupted": "blocked",
            "lost": "lost",
            "blocked": "blocked",
            "closed": "closed",
        }
        artifact_refs = list(self.artifact_refs)
        if self.report_ref and self.report_ref not in artifact_refs:
            artifact_refs.append(self.report_ref)
        return {
            "attempt_id": self.identity.attempt_id,
            "role": self.identity.role,
            "profile_id": self.identity.role,
            "profile_revision": self.identity.profile_revision,
            "runner_ref": self.runner_ref or "",
            "started_at": "",
            "ended_at": "",
            "base_snapshot": self.identity.snapshot,
            "final_snapshot": "",
            "status": status_map.get(self.status, "failed"),
            "model": "",
            "reasoning": "",
            "prompt_revision": "",
            "skill_revisions": [],
            "input_tokens": 0,
            "output_tokens": 0,
            "turns": len(self.events),
            "changed_paths": [],
            "artifact_refs": artifact_refs,
            "verification_refs": [],
            "failure_class": "runner" if self.status == "lost" else "none",
            "stop_reason": self.last_reason or "",
        }


class ExecutionJournal:
    """Atomically stores one small JSON record for one runner attempt."""

    def __init__(self, path: Path):
        self.path = Path(path)

    @classmethod
    def for_task(
        cls, root: Path, task_id: str, attempt_id: str
    ) -> "ExecutionJournal":
        safe_task = _safe_token(task_id, "task_id")
        safe_attempt = _safe_token(attempt_id, "attempt_id")
        return cls(
            Path(root)
            / "tasks"
            / safe_task
            / "artifacts"
            / f"runner-{safe_attempt}.json"
        )

    @classmethod
    def for_task_store(
        cls, store: Any, task_id: str, attempt_id: str
    ) -> "ExecutionJournal":
        """Use the same artifact directory as a TaskStore."""
        return cls.for_task(Path(store.root).parent, task_id, attempt_id)

    def write(self, record: ExecutionRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(
            self.path.name + f".tmp-{len(record.events)}"
        )
        encoded = json.dumps(record.as_dict(), ensure_ascii=True, sort_keys=True)
        temp.write_text(encoded + "\n", encoding="utf-8")
        os.replace(temp, self.path)

    def read(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))


BudgetReserve = Callable[[RunnerRequest], Any]
BudgetRelease = Callable[[Any], None]


class RunnerExecution:
    """Guard a runner adapter with identity, budget, and recovery limits."""

    def __init__(
        self,
        adapter: Any,
        request: RunnerRequest,
        journal: Optional[ExecutionJournal] = None,
        budget_reserve: Optional[BudgetReserve] = None,
        budget_release: Optional[BudgetRelease] = None,
        max_resumes: int = 2,
    ):
        if max_resumes < 0:
            raise ExecutionRecordError("max_resumes must be non-negative")
        self.adapter = adapter
        self.request = request
        self.journal = journal
        self.budget_reserve = budget_reserve
        self.budget_release = budget_release
        self.max_resumes = max_resumes
        self.record = ExecutionRecord(ExecutionIdentity.from_request(request))
        self._budget_token: Any = None
        self._opened = False

    def open(self) -> RunnerEvent:
        if self._opened:
            raise ExecutionRecordError("runner execution already opened")
        if self.budget_reserve is not None:
            self._budget_token = self.budget_reserve(self.request)
        try:
            event = self.adapter.open(self.request)
            self._accept(event)
            self._opened = True
            return event
        except Exception:
            if self._budget_token is not None and self.budget_release is not None:
                self.budget_release(self._budget_token)
                self._budget_token = None
            raise

    def wait(self) -> RunnerEvent:
        self._require_open()
        return self._accept(self.adapter.wait(self._runner_ref()))

    def interrupt(self, reason: str) -> RunnerEvent:
        self._require_open()
        return self._accept(
            self.adapter.interrupt(self._runner_ref(), reason=reason)
        )

    def resume(self, artifact_refs: list[str]) -> RunnerEvent:
        self._require_open()
        if self.record.resume_count >= self.max_resumes:
            raise ExecutionRecordError("runner resume limit exceeded")
        if not artifact_refs:
            raise ExecutionRecordError("resume requires artifact references")
        event = self.adapter.resume(
            self._runner_ref(),
            artifact_refs=tuple(artifact_refs),
        )
        self.record.artifact_refs = list(dict.fromkeys(artifact_refs))
        return self._accept(event)

    def close(self, report_ref: str) -> RunnerEvent:
        self._require_open()
        if not report_ref:
            raise ExecutionRecordError("close requires a report reference")
        event = self.adapter.close(
            self._runner_ref(),
            report_ref=report_ref,
        )
        return self._accept(event)

    def _require_open(self) -> None:
        if not self._opened:
            raise ExecutionRecordError("runner execution is not open")
        if self.record.status == "closed":
            raise ExecutionRecordError("runner execution is closed")

    def _runner_ref(self) -> str:
        if not self.record.runner_ref:
            raise ExecutionRecordError("runner reference is unavailable")
        return self.record.runner_ref

    def _accept(self, event: RunnerEvent) -> RunnerEvent:
        self.record.accept(event, self.max_resumes)
        if self.journal is not None:
            self.journal.write(self.record)
        return event


def bind_task_execution(
    adapter: Any,
    store: Any,
    request: RunnerRequest,
    *,
    budget_reserve: Optional[BudgetReserve] = None,
    budget_release: Optional[BudgetRelease] = None,
    max_resumes: int = 2,
) -> RunnerExecution:
    """Bind a Runner attempt to an existing TaskStore packet revision."""
    request.validate()
    state = store.recover_state(request.task_id)
    packet_revision = int(state.get("packet_revision", 0))
    if packet_revision != request.task_revision:
        raise ExecutionRecordError(
            "TaskStore packet revision does not match RunnerRequest"
        )
    journal = ExecutionJournal.for_task_store(
        store, request.task_id, request.attempt_id
    )
    return RunnerExecution(
        adapter,
        request,
        journal=journal,
        budget_reserve=budget_reserve,
        budget_release=budget_release,
        max_resumes=max_resumes,
    )
