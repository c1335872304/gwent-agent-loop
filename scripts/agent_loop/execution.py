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
from typing import Any, Callable, Mapping, Optional

from .runner import RunnerEvent, RunnerRequest, runner_event_dict
from .recovery import RecoveryDecision, decide_recovery


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

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ExecutionIdentity":
        if not isinstance(payload, Mapping):
            raise ExecutionRecordError("execution identity must be a mapping")
        raw_scope = payload.get("write_scope")
        if not isinstance(raw_scope, (list, tuple)):
            raise ExecutionRecordError("execution identity write_scope must be a list")
        try:
            identity = cls(
                task_id=_safe_token(str(payload["task_id"]), "task_id"),
                task_revision=int(payload["task_revision"]),
                attempt_id=_safe_token(str(payload["attempt_id"]), "attempt_id"),
                role=str(payload["role"]),
                profile_revision=str(payload["profile_revision"]),
                snapshot=str(payload["snapshot"]),
                write_scope=tuple(str(item) for item in raw_scope),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ExecutionRecordError("invalid execution identity") from exc
        if identity.task_revision < 1 or not identity.role.strip() or not identity.profile_revision.strip() or not identity.snapshot.strip():
            raise ExecutionRecordError("invalid execution identity")
        if not identity.write_scope or any(not item.strip() for item in identity.write_scope):
            raise ExecutionRecordError("execution identity write_scope must not be empty")
        return identity


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
    final_snapshot: Optional[str] = None
    changed_paths: list[str] = field(default_factory=list)
    recovery_decisions: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_seconds: float = 0.0

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
        repeated_poll = bool(
            self.events
            and event.event == "waited"
            and event.status == "running"
            and self.events[-1].get("event") == "waited"
            and self.events[-1].get("status") == "running"
        )
        if not repeated_poll:
            self.events.append(payload)
        self.status = event.status
        self.resume_count = event.resume_count
        if event.reason:
            self.last_reason = event.reason
        if event.report_ref:
            self.report_ref = event.report_ref
        if event.final_snapshot:
            if self.final_snapshot and self.final_snapshot != event.final_snapshot:
                raise ExecutionRecordError("runner final snapshot changed unexpectedly")
            self.final_snapshot = event.final_snapshot
        if event.changed_paths:
            self.changed_paths = list(dict.fromkeys(event.changed_paths))
        if event.input_tokens < self.input_tokens or event.output_tokens < self.output_tokens:
            raise ExecutionRecordError("runner token usage moved backwards")
        if event.elapsed_seconds < self.elapsed_seconds:
            raise ExecutionRecordError("runner elapsed time moved backwards")
        self.input_tokens = event.input_tokens
        self.output_tokens = event.output_tokens
        self.elapsed_seconds = event.elapsed_seconds
        return payload

    def record_recovery_decision(
        self,
        decision: RecoveryDecision,
        *,
        failure_class: str | None,
        remaining_budget: int,
    ) -> dict[str, Any]:
        """Persist a recovery decision before the caller executes it."""
        entry = {
            "decision_id": f"{self.identity.attempt_id}-recovery-{len(self.recovery_decisions) + 1}",
            "status": self.status,
            "failure_class": failure_class or "unknown",
            "action": decision.action,
            "reason": decision.reason,
            "consumes_model_call": decision.consumes_model_call,
            "terminal": decision.terminal,
            "requires_human": decision.requires_human,
            "resumes_used": self.resume_count,
            "remaining_budget": int(remaining_budget),
            "persisted_before_action": True,
        }
        self.recovery_decisions.append(entry)
        return entry

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
            "final_snapshot": self.final_snapshot,
            "changed_paths": list(self.changed_paths),
            "recovery_decisions": list(self.recovery_decisions),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "elapsed_seconds": self.elapsed_seconds,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ExecutionRecord":
        """Hydrate a journaled record for a process-restart rebind."""
        if not isinstance(payload, Mapping) or payload.get("schema") != "agent-loop.execution-record.v1":
            raise ExecutionRecordError("unsupported execution record schema")
        raw_events = payload.get("events", [])
        raw_artifacts = payload.get("artifact_refs", [])
        raw_recovery = payload.get("recovery_decisions", [])
        raw_changed = payload.get("changed_paths", [])
        if not all(isinstance(value, list) for value in (raw_events, raw_artifacts, raw_recovery, raw_changed)):
            raise ExecutionRecordError("execution record lists are invalid")
        if len(raw_events) > 32 or any(not isinstance(event, Mapping) for event in raw_events):
            raise ExecutionRecordError("execution record events are invalid")
        if any(not isinstance(item, Mapping) for item in raw_recovery):
            raise ExecutionRecordError("execution record recovery decisions are invalid")
        try:
            status = str(payload["status"])
            record = cls(
                identity=ExecutionIdentity.from_dict(payload["identity"]),
                runner_ref=(str(payload["runner_ref"]) if payload.get("runner_ref") else None),
                status=status,
                resume_count=int(payload.get("resume_count", 0)),
                events=[dict(event) for event in raw_events],
                artifact_refs=[str(item) for item in raw_artifacts],
                report_ref=(str(payload["report_ref"]) if payload.get("report_ref") else None),
                last_reason=(str(payload["last_reason"]) if payload.get("last_reason") else None),
                final_snapshot=(str(payload["final_snapshot"]) if payload.get("final_snapshot") else None),
                changed_paths=[str(item) for item in raw_changed],
                recovery_decisions=[dict(item) for item in raw_recovery],
                input_tokens=int(payload.get("input_tokens", 0)),
                output_tokens=int(payload.get("output_tokens", 0)),
                elapsed_seconds=float(payload.get("elapsed_seconds", 0.0)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ExecutionRecordError("invalid execution record") from exc
        if status not in {"new", "running", "interrupted", "lost", "blocked", "closed"}:
            raise ExecutionRecordError("invalid execution record status")
        if record.resume_count < 0 or record.input_tokens < 0 or record.output_tokens < 0 or record.elapsed_seconds < 0:
            raise ExecutionRecordError("execution record counters must be non-negative")
        if any(not item.strip() for item in record.artifact_refs + record.changed_paths):
            raise ExecutionRecordError("execution record paths cannot be empty")
        return record

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
            "final_snapshot": self.final_snapshot or "",
            "status": status_map.get(self.status, "failed"),
            "model": "",
            "reasoning": "",
            "prompt_revision": "",
            "skill_revisions": [],
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "turns": self.model_turns_used,
            "changed_paths": list(self.changed_paths),
            "artifact_refs": artifact_refs,
            "verification_refs": [],
            "failure_class": "runner" if self.status == "lost" else "none",
            "stop_reason": self.last_reason or "",
            "recovery_decisions": list(self.recovery_decisions),
            "elapsed_seconds": self.elapsed_seconds,
        }

    @property
    def model_turns_used(self) -> int:
        """Count model invocations, excluding lifecycle polling events."""
        return sum(event.get("event") in {"opened", "resumed"} for event in self.events)


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

    def load(self) -> ExecutionRecord:
        return ExecutionRecord.from_dict(self.read())


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
        record: ExecutionRecord | None = None,
    ):
        if max_resumes < 0:
            raise ExecutionRecordError("max_resumes must be non-negative")
        self.adapter = adapter
        self.request = request
        self.journal = journal
        self.budget_reserve = budget_reserve
        self.budget_release = budget_release
        self.max_resumes = max_resumes
        self.record = record or ExecutionRecord(ExecutionIdentity.from_request(request))
        if self.record.identity != ExecutionIdentity.from_request(request):
            raise ExecutionRecordError("hydrated execution identity does not match request")
        self._budget_token: Any = None
        self._opened = False
        self._last_event: RunnerEvent | None = None

    @classmethod
    def rebind(
        cls,
        adapter: Any,
        request: RunnerRequest,
        record: ExecutionRecord,
        *,
        journal: Optional[ExecutionJournal] = None,
        budget_release: Optional[BudgetRelease] = None,
        max_resumes: int = 2,
    ) -> "RunnerExecution":
        """Hydrate a journal and attach the same external Runner reference."""
        if not record.runner_ref:
            raise ExecutionRecordError("cannot rebind execution without runner_ref")
        if record.status not in {"running", "interrupted", "lost"}:
            raise ExecutionRecordError(
                f"cannot rebind execution in terminal state {record.status}"
            )
        request.validate()
        execution = cls(
            adapter,
            request,
            journal=journal,
            budget_release=budget_release,
            max_resumes=max_resumes,
            record=record,
        )
        event = adapter.rebind(record.runner_ref)
        execution._accept(event)
        execution._opened = True
        return execution

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

    def recover(
        self,
        *,
        artifact_refs: list[str],
        failure_class: str | None = "RUNNER_FAILURE",
        attempts_used: int = 0,
        max_attempts: int = 2,
        remaining_budget: int = 1,
        report_valid: bool = True,
        external_runner_available: bool = True,
    ) -> RecoveryDecision:
        """Apply the deterministic recovery policy to this execution.

        The decision is journaled before a resume can spend another model call.
        A policy decision that does not authorize resumption is returned to the
        caller, which must route terminal/human-required states itself.
        """
        decision = decide_recovery(
            status=self.record.status.upper(),
            failure_class=failure_class,
            attempts_used=attempts_used,
            max_attempts=max_attempts,
            resumes_used=self.record.resume_count,
            max_resumes=self.max_resumes,
            remaining_budget=remaining_budget,
            report_valid=report_valid,
            external_runner_available=external_runner_available,
        )
        self.record.record_recovery_decision(
            decision,
            failure_class=failure_class,
            remaining_budget=remaining_budget,
        )
        if self.journal is not None:
            self.journal.write(self.record)
        if decision.action == "RESUME_SAME_RUNNER":
            if not artifact_refs:
                raise ExecutionRecordError(
                    "recovery resume requires persisted artifact references"
                )
            self.resume(artifact_refs)
        return decision

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
        self._last_event = event
        if self.journal is not None:
            self.journal.write(self.record)
        return event

    @property
    def last_event(self) -> RunnerEvent | None:
        """Return the last accepted event for a resumed orchestration."""
        return self._last_event


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


def rebind_task_execution(
    adapter: Any,
    store: Any,
    request: RunnerRequest,
    *,
    budget_release: Optional[BudgetRelease] = None,
    max_resumes: int = 2,
) -> RunnerExecution:
    """Hydrate one persisted attempt and rebind it without opening a task."""
    request.validate()
    state = store.recover_state(request.task_id)
    if int(state.get("packet_revision", 0)) != request.task_revision:
        raise ExecutionRecordError(
            "TaskStore packet revision does not match RunnerRequest"
        )
    journal = ExecutionJournal.for_task_store(store, request.task_id, request.attempt_id)
    return RunnerExecution.rebind(
        adapter,
        request,
        journal.load(),
        journal=journal,
        budget_release=budget_release,
        max_resumes=max_resumes,
    )
