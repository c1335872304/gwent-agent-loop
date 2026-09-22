"""Deterministic, bounded Scheduler for the Phase 3 Agent Loop.

The Scheduler owns task admission and lifecycle policy.  It does not know how
an Owner or Test/Verification task is executed; a backend is injected for
that platform boundary.  This keeps routing, queueing, pause/resume, budget
checks, and audit evidence testable without launching a model or a service.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Protocol

from .errors import BudgetExceeded, StateTransitionError, ValidationError
from .validate_packet import validate_task_packet

SchedulerTaskStatus = Literal[
    "queued",
    "running",
    "paused",
    "completed",
    "cancelled",
    "failed",
    "blocked",
    "human_required",
]
TERMINAL_TASK_STATUSES = frozenset(
    {"completed", "cancelled", "failed", "blocked", "human_required"}
)
BACKEND_STATUSES = frozenset(
    {"running", "completed", "failed", "blocked", "human_required"}
)
ROUTES = frozenset({"core", "trainer", "product", "teacher", "context-integration"})


class SchedulerError(ValidationError):
    """Raised when the Scheduler cannot safely accept or execute a task."""


class SchedulerStateError(StateTransitionError):
    """Raised when a Scheduler lifecycle operation is not allowed."""


@dataclass(frozen=True)
class SchedulerLimits:
    """Whole-scheduler hard limits, shared by all admitted tasks."""

    max_concurrency: int
    max_tasks: int
    max_input_tokens: int
    max_output_tokens: int
    max_model_turns: int
    max_elapsed_minutes: int

    def __post_init__(self) -> None:
        positive = {
            "max_concurrency": self.max_concurrency,
            "max_tasks": self.max_tasks,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "max_model_turns": self.max_model_turns,
            "max_elapsed_minutes": self.max_elapsed_minutes,
        }
        invalid = [name for name, value in positive.items() if int(value) <= 0]
        if invalid:
            raise SchedulerError("Scheduler limits must be positive: " + ", ".join(invalid))

    def to_dict(self) -> dict[str, int]:
        return {
            "max_concurrency": int(self.max_concurrency),
            "max_tasks": int(self.max_tasks),
            "max_input_tokens": int(self.max_input_tokens),
            "max_output_tokens": int(self.max_output_tokens),
            "max_model_turns": int(self.max_model_turns),
            "max_elapsed_minutes": int(self.max_elapsed_minutes),
        }


@dataclass(frozen=True)
class ExecutionBudget:
    """The maximum slice handed to one backend task."""

    max_input_tokens: int
    max_output_tokens: int
    max_model_turns: int
    max_elapsed_seconds: float

    def to_dict(self) -> dict[str, int | float]:
        return {
            "max_input_tokens": int(self.max_input_tokens),
            "max_output_tokens": int(self.max_output_tokens),
            "max_model_turns": int(self.max_model_turns),
            "max_elapsed_seconds": float(self.max_elapsed_seconds),
        }


@dataclass(frozen=True)
class ExecutionUpdate:
    """One backend poll result.

    Usage fields are deltas since the previous poll.  Making this explicit
    prevents concurrent tasks from double-counting cumulative host metrics.
    """

    status: str
    input_tokens_delta: int = 0
    output_tokens_delta: int = 0
    model_turns_delta: int = 0
    elapsed_seconds_delta: float = 0.0
    report_ref: str | None = None
    final_snapshot: str | None = None
    evidence_refs: tuple[str, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status not in BACKEND_STATUSES:
            raise SchedulerError(f"invalid backend status: {self.status!r}")
        values = {
            "input_tokens_delta": self.input_tokens_delta,
            "output_tokens_delta": self.output_tokens_delta,
            "model_turns_delta": self.model_turns_delta,
            "elapsed_seconds_delta": self.elapsed_seconds_delta,
        }
        if any(float(value) < 0 for value in values.values()):
            raise SchedulerError("backend usage deltas cannot be negative")
        if any(not str(ref).strip() for ref in self.evidence_refs):
            raise SchedulerError("backend evidence_refs cannot contain empty values")


@dataclass
class ScheduledTask:
    """Scheduler-owned projection for one TaskPacket."""

    task_id: str
    revision: int
    owner: str
    packet: Mapping[str, Any]
    sequence: int
    status: SchedulerTaskStatus = "queued"
    handle: str | None = None
    budget: ExecutionBudget | None = None
    resume_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    model_turns: int = 0
    elapsed_seconds: float = 0.0
    report_ref: str | None = None
    final_snapshot: str | None = None
    evidence_refs: tuple[str, ...] = ()
    reason: str | None = None
    started_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "revision": int(self.revision),
            "owner": self.owner,
            "packet": deepcopy(dict(self.packet)),
            "sequence": int(self.sequence),
            "status": self.status,
            "handle": self.handle,
            "budget": self.budget.to_dict() if self.budget else None,
            "resume_count": int(self.resume_count),
            "input_tokens": int(self.input_tokens),
            "output_tokens": int(self.output_tokens),
            "model_turns": int(self.model_turns),
            "elapsed_seconds": float(self.elapsed_seconds),
            "report_ref": self.report_ref,
            "final_snapshot": self.final_snapshot,
            "evidence_refs": list(self.evidence_refs),
            "reason": self.reason,
            "started_at": self.started_at,
        }


@dataclass(frozen=True)
class SchedulerEvent:
    """Append-only scheduling evidence."""

    event_seq: int
    event_id: str
    task_id: str
    from_status: str | None
    to_status: str
    actor: str
    reason: str
    at: str
    evidence_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_seq": int(self.event_seq),
            "event_id": self.event_id,
            "task_id": self.task_id,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "actor": self.actor,
            "reason": self.reason,
            "at": self.at,
            "evidence_refs": list(self.evidence_refs),
        }


class SchedulerBackend(Protocol):
    """Platform adapter used by the model-free Scheduler."""

    def start(self, task: ScheduledTask, budget: ExecutionBudget) -> str: ...

    def poll(self, task: ScheduledTask) -> ExecutionUpdate | Mapping[str, Any] | None: ...

    def pause(self, task: ScheduledTask, *, reason: str) -> None: ...

    def resume(self, task: ScheduledTask) -> None: ...

    def cancel(self, task: ScheduledTask, *, reason: str) -> None: ...


class RebindableSchedulerBackend(Protocol):
    """Optional restart boundary for a backend with durable Runner handles."""

    def rebind(self, task: ScheduledTask, handle: str) -> None: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


class Scheduler:
    """Main-driven FIFO Scheduler with bounded, auditable lifecycle policy.

    ``pump`` is intentionally non-blocking: the main control plane calls it
    periodically, the backend reports progress through ``poll``, and every
    state change is persisted when ``state_path`` is provided.  The Scheduler
    never retries a failed task, changes a contract, or starts work after a
    hard budget is exhausted.
    """

    def __init__(
        self,
        backend: SchedulerBackend,
        limits: SchedulerLimits,
        *,
        state_path: str | Path | None = None,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> None:
        self.backend = backend
        self.limits = limits
        self.state_path = Path(state_path) if state_path else None
        self._clock = monotonic_clock or time.monotonic
        self._tasks: dict[str, ScheduledTask] = {}
        self._queue: deque[str] = deque()
        self._events: list[SchedulerEvent] = []
        self._usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "model_turns": 0,
        }
        self._reserved = {
            "input_tokens": 0,
            "output_tokens": 0,
            "model_turns": 0,
        }
        self._started_monotonic: float | None = None
        self._started_at: str | None = None
        self._next_sequence = 1
        self._next_event_sequence = 1
        self._stopped = False
        self._budget_exhausted = False
        self._human_required = False

    @property
    def tasks(self) -> tuple[ScheduledTask, ...]:
        return tuple(deepcopy(task) for task in self._tasks.values())

    @property
    def events(self) -> tuple[SchedulerEvent, ...]:
        return tuple(self._events)

    @property
    def active_count(self) -> int:
        return sum(task.status == "running" for task in self._tasks.values())

    @property
    def occupied_count(self) -> int:
        """Count running and paused tasks so pause cannot reorder the FIFO."""
        return sum(task.status in {"running", "paused"} for task in self._tasks.values())

    @property
    def usage(self) -> Mapping[str, int]:
        return dict(self._usage)

    def get_task(self, task_id: str) -> ScheduledTask:
        try:
            return deepcopy(self._tasks[task_id])
        except KeyError as exc:
            raise SchedulerError(f"unknown scheduled task: {task_id}") from exc

    def submit(self, task_packet: Mapping[str, Any]) -> ScheduledTask:
        """Validate and enqueue one immutable TaskPacket for its declared owner."""
        validate_task_packet(task_packet)
        task_id = str(task_packet.get("task_id", "")).strip()
        owner = str(task_packet["ownership"]["primary_owner"]).strip()
        if owner not in ROUTES:
            raise SchedulerError(f"TaskPacket owner has no Scheduler route: {owner}")
        if self._stopped:
            raise SchedulerStateError("Scheduler has been stopped")
        if task_id in self._tasks:
            raise SchedulerError(f"task already submitted: {task_id}")
        if len(self._tasks) >= self.limits.max_tasks:
            raise BudgetExceeded("Scheduler max_tasks exhausted; no new task admitted")
        if self._budget_exhausted:
            raise BudgetExceeded("Scheduler budget exhausted; no new task admitted")
        if self._human_required:
            raise SchedulerStateError("Scheduler requires human recovery before new work")
        if self._started_monotonic is None:
            self._started_monotonic = self._clock()
            self._started_at = _now()
        task = ScheduledTask(
            task_id=task_id,
            revision=int(task_packet["revision"]),
            owner=owner,
            packet=deepcopy(dict(task_packet)),
            sequence=self._next_sequence,
        )
        self._next_sequence += 1
        self._tasks[task_id] = task
        self._queue.append(task_id)
        self._record(task, None, "queued", actor="scheduler", reason="admitted")
        self._persist()
        return deepcopy(task)

    @classmethod
    def restore(
        cls,
        path: str | Path,
        backend: SchedulerBackend,
        *,
        state_path: str | Path | None = None,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> "Scheduler":
        """Restore a persisted scheduler and rebind active backend handles.

        Restoration never calls ``start``.  A running or paused task must be
        attached to the exact backend handle recorded in the snapshot through
        the optional ``rebind(task, handle)`` hook.  If that hook is absent or
        rejects the handle, the task is made ``human_required`` and queued work
        is held.  This is deliberately fail-closed: a process restart must not
        duplicate a model run or lose its audit identity.
        """
        source = Path(path)
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SchedulerStateError(f"cannot read Scheduler snapshot: {source}") from exc
        if not isinstance(payload, Mapping):
            raise SchedulerStateError("Scheduler snapshot must be a mapping")
        if payload.get("protocol_version") != 1:
            raise SchedulerStateError("unsupported Scheduler snapshot protocol")
        raw_limits = payload.get("limits")
        if not isinstance(raw_limits, Mapping):
            raise SchedulerStateError("Scheduler snapshot limits must be a mapping")
        try:
            limits = SchedulerLimits(
                max_concurrency=int(raw_limits["max_concurrency"]),
                max_tasks=int(raw_limits["max_tasks"]),
                max_input_tokens=int(raw_limits["max_input_tokens"]),
                max_output_tokens=int(raw_limits["max_output_tokens"]),
                max_model_turns=int(raw_limits["max_model_turns"]),
                max_elapsed_minutes=int(raw_limits["max_elapsed_minutes"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchedulerStateError("Scheduler snapshot contains invalid limits") from exc
        scheduler = cls(
            backend,
            limits,
            state_path=state_path if state_path is not None else source,
            monotonic_clock=monotonic_clock,
        )
        scheduler._restore_payload(payload)
        scheduler._rebind_active_tasks()
        scheduler._persist()
        return scheduler

    def pump(self) -> tuple[SchedulerEvent, ...]:
        """Poll active work, enforce limits, and start FIFO queued work."""
        before = len(self._events)
        if self._stopped:
            return ()
        if self._human_required:
            self._persist()
            return ()
        self._enforce_elapsed_budget()
        for task in tuple(self._tasks.values()):
            if task.status == "running":
                self._poll_one(task)
        self._enforce_elapsed_budget()
        self._start_queued()
        self._persist()
        return tuple(self._events[before:])

    def pause(self, task_id: str, *, reason: str, actor: str = "scheduler") -> ScheduledTask:
        task = self._task(task_id)
        if task.status != "running":
            raise SchedulerStateError(f"cannot pause task in state {task.status}")
        if not str(reason).strip():
            raise SchedulerError("pause reason must not be empty")
        self.backend.pause(task, reason=str(reason))
        self._transition(task, "paused", actor=str(actor), reason=str(reason))
        self._persist()
        return deepcopy(task)

    def resume(self, task_id: str, *, actor: str = "scheduler") -> ScheduledTask:
        task = self._task(task_id)
        if task.status != "paused":
            raise SchedulerStateError(f"cannot resume task in state {task.status}")
        if self._elapsed_seconds() >= self.limits.max_elapsed_minutes * 60:
            self._budget_exhausted = True
            self._terminate(task, "human_required", "elapsed budget exhausted before resume", actor=str(actor))
            self._persist()
            return deepcopy(task)
        if self.occupied_count > self.limits.max_concurrency:
            raise SchedulerStateError("max_concurrency is full; resume remains queued by caller")
        if task.budget is None or self._task_budget_remaining(task) <= 0:
            self._terminate(task, "human_required", "task budget exhausted before resume", actor=str(actor))
            self._persist()
            return deepcopy(task)
        try:
            self.backend.resume(task)
        except Exception as exc:
            self._terminate(task, "human_required", f"resume failed; manual recovery required: {exc}", actor=str(actor))
            self._persist()
            return deepcopy(task)
        task.resume_count += 1
        self._transition(task, "running", actor=str(actor), reason="resumed")
        self._persist()
        return deepcopy(task)

    def end(
        self,
        task_id: str,
        *,
        reason: str = "operator ended task",
        status: SchedulerTaskStatus = "cancelled",
        actor: str = "scheduler",
    ) -> ScheduledTask:
        """End queued or active work; normal completion comes from ``pump``."""
        if status not in {"cancelled", "failed", "blocked", "human_required"}:
            raise SchedulerError("end status must be cancelled, failed, blocked, or human_required")
        task = self._task(task_id)
        if task.status in TERMINAL_TASK_STATUSES:
            raise SchedulerStateError(f"cannot end task in terminal state {task.status}")
        if task.status in {"running", "paused"}:
            try:
                self.backend.cancel(task, reason=str(reason))
            except Exception as exc:
                self._terminate(task, "human_required", f"cancel failed; manual recovery required: {exc}", actor=str(actor))
                self._persist()
                return deepcopy(task)
        self._terminate(task, status, str(reason), actor=str(actor))
        self._persist()
        return deepcopy(task)

    def cancel(
        self,
        task_id: str,
        *,
        reason: str = "operator cancelled task",
        actor: str = "scheduler",
    ) -> ScheduledTask:
        return self.end(task_id, reason=reason, status="cancelled", actor=actor)

    def stop(self, *, reason: str = "scheduler stopped") -> None:
        """Stop admitting work and end every queued/active task safely."""
        self._stopped = True
        for task in tuple(self._tasks.values()):
            if task.status in {"queued", "running", "paused"}:
                self.end(task.task_id, reason=reason)
        self._persist()

    def snapshot(self) -> dict[str, Any]:
        elapsed = self._elapsed_seconds()
        if self._stopped:
            scheduler_status = "stopped"
        elif self._budget_exhausted or self._human_required:
            scheduler_status = "human_required"
        elif self.active_count:
            scheduler_status = "running"
        elif any(task.status == "paused" for task in self._tasks.values()):
            scheduler_status = "paused"
        elif any(task.status == "queued" for task in self._tasks.values()):
            scheduler_status = "queued"
        elif self._tasks:
            scheduler_status = "completed"
        else:
            scheduler_status = "idle"
        return {
            "protocol_version": 1,
            "scheduler_status": scheduler_status,
            "started_at": self._started_at,
            "elapsed_seconds": elapsed,
            "limits": self.limits.to_dict(),
            "usage": {
                **self._usage,
                "elapsed_seconds": elapsed,
            },
            "reserved": dict(self._reserved),
            "queue": [task_id for task_id in self._queue if self._tasks[task_id].status == "queued"],
            "tasks": [task.to_dict() for task in self._tasks.values()],
            "events": [event.to_dict() for event in self._events],
        }

    def write_snapshot(self, path: str | Path | None = None) -> Path:
        target = Path(path) if path else self.state_path
        if target is None:
            raise SchedulerError("write_snapshot requires a path or configured state_path")
        _write_json_atomic(target, self.snapshot())
        return target

    def _task(self, task_id: str) -> ScheduledTask:
        try:
            return self._tasks[str(task_id)]
        except KeyError as exc:
            raise SchedulerError(f"unknown scheduled task: {task_id}") from exc

    def _restore_payload(self, payload: Mapping[str, Any]) -> None:
        raw_tasks = payload.get("tasks")
        raw_queue = payload.get("queue")
        raw_events = payload.get("events")
        if not isinstance(raw_tasks, list) or not isinstance(raw_queue, list) or not isinstance(raw_events, list):
            raise SchedulerStateError("Scheduler snapshot tasks, queue, and events must be lists")
        if len(raw_tasks) > self.limits.max_tasks:
            raise SchedulerStateError("Scheduler snapshot exceeds max_tasks")

        parsed_tasks: list[ScheduledTask] = []
        task_ids: set[str] = set()
        sequences: set[int] = set()
        for raw in raw_tasks:
            if not isinstance(raw, Mapping):
                raise SchedulerStateError("Scheduler snapshot task must be a mapping")
            try:
                task_id = str(raw["task_id"]).strip()
                revision = int(raw["revision"])
                owner = str(raw["owner"]).strip()
                packet = raw["packet"]
                sequence = int(raw["sequence"])
                status = str(raw["status"])
            except (KeyError, TypeError, ValueError) as exc:
                raise SchedulerStateError("Scheduler snapshot task identity is invalid") from exc
            if not task_id or task_id in task_ids or sequence < 1 or sequence in sequences:
                raise SchedulerStateError("Scheduler snapshot contains duplicate or invalid task identity")
            if owner not in ROUTES or status not in {
                "queued", "running", "paused", "completed", "cancelled", "failed", "blocked", "human_required"
            }:
                raise SchedulerStateError("Scheduler snapshot contains an invalid task route or status")
            if not isinstance(packet, Mapping):
                raise SchedulerStateError(f"Scheduler snapshot packet is invalid: {task_id}")
            try:
                validate_task_packet(packet)
            except Exception as exc:
                raise SchedulerStateError(f"Scheduler snapshot packet failed validation: {task_id}") from exc
            if str(packet.get("task_id")) != task_id or int(packet.get("revision", 0)) != revision:
                raise SchedulerStateError(f"Scheduler snapshot packet identity mismatch: {task_id}")
            if str(packet.get("ownership", {}).get("primary_owner")) != owner:
                raise SchedulerStateError(f"Scheduler snapshot owner mismatch: {task_id}")
            budget = self._restore_budget(raw.get("budget"), task_id)
            handle = str(raw["handle"]).strip() if raw.get("handle") else None
            if status in {"running", "paused"} and (not handle or budget is None):
                raise SchedulerStateError(f"active Scheduler task lacks handle or budget: {task_id}")
            try:
                evidence_refs = tuple(str(ref) for ref in raw.get("evidence_refs", ()))
                task = ScheduledTask(
                    task_id=task_id,
                    revision=revision,
                    owner=owner,
                    packet=deepcopy(dict(packet)),
                    sequence=sequence,
                    status=status,  # type: ignore[arg-type]
                    handle=handle,
                    budget=budget,
                    resume_count=max(0, int(raw.get("resume_count", 0))),
                    input_tokens=max(0, int(raw.get("input_tokens", 0))),
                    output_tokens=max(0, int(raw.get("output_tokens", 0))),
                    model_turns=max(0, int(raw.get("model_turns", 0))),
                    elapsed_seconds=max(0.0, float(raw.get("elapsed_seconds", 0.0))),
                    report_ref=str(raw["report_ref"]) if raw.get("report_ref") else None,
                    final_snapshot=str(raw["final_snapshot"]) if raw.get("final_snapshot") else None,
                    evidence_refs=evidence_refs,
                    reason=str(raw["reason"]) if raw.get("reason") else None,
                    started_at=str(raw["started_at"]) if raw.get("started_at") else None,
                )
            except (TypeError, ValueError) as exc:
                raise SchedulerStateError(f"Scheduler snapshot task metrics are invalid: {task_id}") from exc
            task_ids.add(task_id)
            sequences.add(sequence)
            parsed_tasks.append(task)

        for raw_id in raw_queue:
            task_id = str(raw_id)
            if task_id not in task_ids:
                raise SchedulerStateError(f"Scheduler snapshot queue references unknown task: {task_id}")
        if len(set(str(item) for item in raw_queue)) != len(raw_queue):
            raise SchedulerStateError("Scheduler snapshot queue contains duplicate task ids")
        if set(str(item) for item in raw_queue) - {task.task_id for task in parsed_tasks if task.status == "queued"}:
            raise SchedulerStateError("Scheduler snapshot queue contains a non-queued task")

        self._tasks = {task.task_id: task for task in sorted(parsed_tasks, key=lambda item: item.sequence)}
        self._queue = deque(str(item) for item in raw_queue)
        if set(self._queue) != {task.task_id for task in parsed_tasks if task.status == "queued"}:
            raise SchedulerStateError("Scheduler snapshot queue does not match queued tasks")

        parsed_events: list[SchedulerEvent] = []
        event_sequences: set[int] = set()
        for raw in raw_events:
            if not isinstance(raw, Mapping):
                raise SchedulerStateError("Scheduler snapshot event must be a mapping")
            try:
                event_seq = int(raw["event_seq"])
                event_id = str(raw["event_id"])
                task_id = str(raw["task_id"])
                to_status = str(raw["to_status"])
                actor = str(raw["actor"])
                reason = str(raw["reason"])
                at = str(raw["at"])
                from_status = str(raw["from_status"]) if raw.get("from_status") is not None else None
                evidence_refs = tuple(str(ref) for ref in raw.get("evidence_refs", ()))
            except (KeyError, TypeError, ValueError) as exc:
                raise SchedulerStateError("Scheduler snapshot event is invalid") from exc
            if event_seq < 1 or event_seq in event_sequences or task_id not in task_ids:
                raise SchedulerStateError("Scheduler snapshot event identity is invalid")
            if to_status not in {
                "queued", "running", "paused", "completed", "cancelled", "failed", "blocked", "human_required"
            }:
                raise SchedulerStateError("Scheduler snapshot event status is invalid")
            parsed_events.append(
                SchedulerEvent(
                    event_seq=event_seq,
                    event_id=event_id,
                    task_id=task_id,
                    from_status=from_status,
                    to_status=to_status,
                    actor=actor,
                    reason=reason,
                    at=at,
                    evidence_refs=evidence_refs,
                )
            )
            event_sequences.add(event_seq)
        self._events = sorted(parsed_events, key=lambda event: event.event_seq)

        self._usage = self._restore_counters(payload.get("usage"), "usage")
        self._reserved = self._restore_counters(payload.get("reserved"), "reserved")
        if any(value > getattr(self.limits, f"max_{name}") for name, value in self._usage.items()):
            raise SchedulerStateError("Scheduler snapshot usage exceeds hard limits")
        self._started_at = str(payload["started_at"]) if payload.get("started_at") else None
        try:
            elapsed = max(0.0, float(payload.get("elapsed_seconds", 0.0)))
        except (TypeError, ValueError) as exc:
            raise SchedulerStateError("Scheduler snapshot elapsed_seconds is invalid") from exc
        self._started_monotonic = self._clock() - elapsed if self._started_at or elapsed else None
        self._next_sequence = max((task.sequence for task in self._tasks.values()), default=0) + 1
        self._next_event_sequence = max([event.event_seq for event in self._events] or [0]) + 1
        scheduler_status = str(payload.get("scheduler_status", "idle"))
        if scheduler_status not in {"idle", "queued", "running", "paused", "completed", "human_required", "stopped"}:
            raise SchedulerStateError("Scheduler snapshot status is invalid")
        self._stopped = scheduler_status == "stopped"
        self._budget_exhausted = scheduler_status == "human_required" and any(
            "budget" in (task.reason or "").lower() or task.status == "human_required" and not task.handle
            for task in self._tasks.values()
        )
        self._human_required = scheduler_status == "human_required" or any(
            task.status == "human_required" for task in self._tasks.values()
        )

    @staticmethod
    def _restore_budget(raw: Any, task_id: str) -> ExecutionBudget | None:
        if raw is None:
            return None
        if not isinstance(raw, Mapping):
            raise SchedulerStateError(f"Scheduler snapshot budget is invalid: {task_id}")
        try:
            values = ExecutionBudget(
                max_input_tokens=int(raw["max_input_tokens"]),
                max_output_tokens=int(raw["max_output_tokens"]),
                max_model_turns=int(raw["max_model_turns"]),
                max_elapsed_seconds=float(raw["max_elapsed_seconds"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchedulerStateError(f"Scheduler snapshot budget is invalid: {task_id}") from exc
        if min(values.max_input_tokens, values.max_output_tokens, values.max_model_turns, values.max_elapsed_seconds) <= 0:
            raise SchedulerStateError(f"Scheduler snapshot budget must be positive: {task_id}")
        return values

    @staticmethod
    def _restore_counters(raw: Any, label: str) -> dict[str, int]:
        if not isinstance(raw, Mapping):
            raise SchedulerStateError(f"Scheduler snapshot {label} must be a mapping")
        values: dict[str, int] = {}
        for name in ("input_tokens", "output_tokens", "model_turns"):
            try:
                value = int(raw[name])
            except (KeyError, TypeError, ValueError) as exc:
                raise SchedulerStateError(f"Scheduler snapshot {label} is invalid") from exc
            if value < 0:
                raise SchedulerStateError(f"Scheduler snapshot {label} cannot be negative")
            values[name] = value
        return values

    def _rebind_active_tasks(self) -> None:
        rebind = getattr(self.backend, "rebind", None)
        for task in tuple(self._tasks.values()):
            if task.status not in {"running", "paused"}:
                continue
            error: Exception | None = None
            if not callable(rebind):
                error = SchedulerError("backend does not expose rebind(task, handle)")
            else:
                try:
                    rebind(task, str(task.handle))
                except Exception as exc:  # fail closed at the task boundary
                    error = exc
            if error is not None:
                self._release(task.budget)
                self._transition(
                    task,
                    "human_required",
                    actor="scheduler",
                    reason=f"Scheduler restore rebind failed; manual recovery required: {error}",
                )
                task.reason = f"Scheduler restore rebind failed; manual recovery required: {error}"
                self._human_required = True

    def _start_queued(self) -> None:
        while self._queue and self.occupied_count < self.limits.max_concurrency:
            if self._budget_exhausted or self._human_required:
                return
            task = self._tasks[self._queue.popleft()]
            if task.status != "queued":
                continue
            budget = self._allocate_budget(task)
            if budget is None:
                self._budget_exhausted = True
                self._terminate(task, "human_required", "scheduler budget exhausted before dispatch")
                for remaining_id in tuple(self._queue):
                    remaining = self._tasks[remaining_id]
                    if remaining.status == "queued":
                        self._terminate(remaining, "human_required", "scheduler budget exhausted before dispatch")
                self._queue.clear()
                return
            task.budget = budget
            self._reserve(budget)
            try:
                handle = str(self.backend.start(task, budget)).strip()
                if not handle:
                    raise SchedulerError("backend returned an empty task handle")
            except Exception as exc:
                self._release(budget)
                task.budget = None
                self._terminate(task, "failed", f"dispatch failed: {exc}")
                continue
            task.handle = handle
            task.started_at = _now()
            # Opening a model-backed Runner consumes its first model turn.
            # Token usage is reported by the backend later, but the turn must
            # be charged before any resume can be requested.
            task.model_turns += 1
            self._usage["model_turns"] += 1
            self._transition(task, "running", actor="scheduler", reason=f"routed to {task.owner}")

    def _poll_one(self, task: ScheduledTask) -> None:
        try:
            raw_update = self.backend.poll(task)
            if raw_update is None:
                return
            update = self._coerce_update(raw_update)
        except Exception as exc:
            self._terminate(task, "failed", f"backend poll failed: {exc}")
            return
        self._apply_usage(task, update)
        if task.status != "running":
            return
        if update.status == "running":
            if any(
                value
                for value in (
                    update.input_tokens_delta,
                    update.output_tokens_delta,
                    update.model_turns_delta,
                    update.elapsed_seconds_delta,
                )
            ):
                self._record(
                    task,
                    "running",
                    "running",
                    actor="backend",
                    reason="progress recorded",
                    evidence_refs=update.evidence_refs,
                )
            return
        if update.status == "completed" and not update.evidence_refs and not update.report_ref:
            self._terminate(task, "human_required", "completed update lacks evidence")
            return
        task.report_ref = update.report_ref or task.report_ref
        task.final_snapshot = update.final_snapshot or task.final_snapshot
        task.evidence_refs = tuple(dict.fromkeys((*task.evidence_refs, *update.evidence_refs)))
        self._terminate(task, update.status, update.reason or update.status, cancel_backend=False)

    def _apply_usage(self, task: ScheduledTask, update: ExecutionUpdate) -> None:
        projected = {
            "input_tokens": task.input_tokens + int(update.input_tokens_delta),
            "output_tokens": task.output_tokens + int(update.output_tokens_delta),
            "model_turns": task.model_turns + int(update.model_turns_delta),
            "elapsed_seconds": task.elapsed_seconds + float(update.elapsed_seconds_delta),
        }
        limits = task.budget
        exceeded: list[str] = []
        if limits is not None:
            if projected["input_tokens"] > limits.max_input_tokens:
                exceeded.append("task input tokens")
            if projected["output_tokens"] > limits.max_output_tokens:
                exceeded.append("task output tokens")
            if projected["model_turns"] > limits.max_model_turns:
                exceeded.append("task model turns")
            if projected["elapsed_seconds"] > limits.max_elapsed_seconds:
                exceeded.append("task elapsed time")
        global_projected = {
            "input_tokens": self._usage["input_tokens"] + int(update.input_tokens_delta),
            "output_tokens": self._usage["output_tokens"] + int(update.output_tokens_delta),
            "model_turns": self._usage["model_turns"] + int(update.model_turns_delta),
        }
        if global_projected["input_tokens"] > self.limits.max_input_tokens:
            exceeded.append("scheduler input tokens")
        if global_projected["output_tokens"] > self.limits.max_output_tokens:
            exceeded.append("scheduler output tokens")
        if global_projected["model_turns"] > self.limits.max_model_turns:
            exceeded.append("scheduler model turns")
        task.input_tokens = projected["input_tokens"]
        task.output_tokens = projected["output_tokens"]
        task.model_turns = projected["model_turns"]
        task.elapsed_seconds = projected["elapsed_seconds"]
        self._usage.update(global_projected)
        if exceeded:
            self._budget_exhausted = True
            self._terminate(
                task,
                "human_required",
                "usage exceeded hard limit: " + ", ".join(exceeded),
            )

    def _allocate_budget(self, task: ScheduledTask) -> ExecutionBudget | None:
        execution = task.packet["execution"]
        remaining = {
            name: int(getattr(self.limits, f"max_{name}")) - self._usage[name] - self._reserved[name]
            for name in ("input_tokens", "output_tokens", "model_turns")
        }
        values = {
            "input_tokens": min(int(execution["max_model_input_tokens"]), remaining["input_tokens"]),
            "output_tokens": min(int(execution["max_model_output_tokens"]), remaining["output_tokens"]),
            "model_turns": min(int(execution["max_model_turns"]), remaining["model_turns"]),
        }
        if any(value <= 0 for value in values.values()):
            return None
        remaining_seconds = self.limits.max_elapsed_minutes * 60 - self._elapsed_seconds()
        max_elapsed_seconds = min(int(execution["max_elapsed_minutes"]) * 60, remaining_seconds)
        if max_elapsed_seconds <= 0:
            return None
        return ExecutionBudget(
            max_input_tokens=values["input_tokens"],
            max_output_tokens=values["output_tokens"],
            max_model_turns=values["model_turns"],
            max_elapsed_seconds=float(max_elapsed_seconds),
        )

    def _task_budget_remaining(self, task: ScheduledTask) -> float:
        if task.budget is None:
            return 0.0
        return min(
            task.budget.max_input_tokens - task.input_tokens,
            task.budget.max_output_tokens - task.output_tokens,
            task.budget.max_model_turns - task.model_turns,
            task.budget.max_elapsed_seconds - task.elapsed_seconds,
        )

    def _reserve(self, budget: ExecutionBudget) -> None:
        self._reserved["input_tokens"] += budget.max_input_tokens
        self._reserved["output_tokens"] += budget.max_output_tokens
        self._reserved["model_turns"] += budget.max_model_turns

    def _release(self, budget: ExecutionBudget | None) -> None:
        if budget is None:
            return
        self._reserved["input_tokens"] = max(
            0, self._reserved["input_tokens"] - budget.max_input_tokens
        )
        self._reserved["output_tokens"] = max(
            0, self._reserved["output_tokens"] - budget.max_output_tokens
        )
        self._reserved["model_turns"] = max(
            0, self._reserved["model_turns"] - budget.max_model_turns
        )

    def _terminate(
        self,
        task: ScheduledTask,
        status: SchedulerTaskStatus,
        reason: str,
        *,
        cancel_backend: bool = True,
        actor: str = "scheduler",
    ) -> None:
        if task.status in TERMINAL_TASK_STATUSES:
            return
        if cancel_backend and task.status in {"running", "paused"}:
            try:
                self.backend.cancel(task, reason=reason)
            except Exception as exc:
                status = "human_required"
                reason = f"{reason}; backend cancellation failed: {exc}"
        self._release(task.budget)
        self._transition(task, status, actor=actor, reason=reason)
        task.reason = reason
        if status == "human_required":
            self._human_required = True
        task.handle = task.handle

    def _transition(
        self,
        task: ScheduledTask,
        target: SchedulerTaskStatus,
        *,
        actor: str,
        reason: str,
        evidence_refs: tuple[str, ...] = (),
    ) -> None:
        if target not in {
            "queued",
            "running",
            "paused",
            "completed",
            "cancelled",
            "failed",
            "blocked",
            "human_required",
        }:
            raise SchedulerStateError(f"unknown Scheduler target state: {target}")
        previous = task.status
        task.status = target
        self._record(task, previous, target, actor=actor, reason=reason, evidence_refs=evidence_refs)

    def _record(
        self,
        task: ScheduledTask,
        from_status: str | None,
        to_status: str,
        *,
        actor: str,
        reason: str,
        evidence_refs: tuple[str, ...] = (),
    ) -> None:
        event = SchedulerEvent(
            event_seq=self._next_event_sequence,
            event_id=f"scheduler-{self._next_event_sequence}",
            task_id=task.task_id,
            from_status=from_status,
            to_status=to_status,
            actor=actor,
            reason=str(reason),
            at=_now(),
            evidence_refs=tuple(evidence_refs),
        )
        self._next_event_sequence += 1
        self._events.append(event)

    def _enforce_elapsed_budget(self) -> None:
        if self._started_monotonic is None or self._budget_exhausted:
            return
        if self._elapsed_seconds() < self.limits.max_elapsed_minutes * 60:
            return
        self._budget_exhausted = True
        reason = "scheduler elapsed budget exhausted"
        for task in tuple(self._tasks.values()):
            if task.status in {"queued", "running", "paused"}:
                self._terminate(task, "human_required", reason)
        self._queue.clear()

    def _elapsed_seconds(self) -> float:
        if self._started_monotonic is None:
            return 0.0
        return max(0.0, float(self._clock() - self._started_monotonic))

    @staticmethod
    def _coerce_update(raw: ExecutionUpdate | Mapping[str, Any]) -> ExecutionUpdate:
        if isinstance(raw, ExecutionUpdate):
            return raw
        if not isinstance(raw, Mapping):
            raise SchedulerError("backend poll must return ExecutionUpdate, mapping, or None")
        return ExecutionUpdate(
            status=str(raw.get("status", "")),
            input_tokens_delta=int(raw.get("input_tokens_delta", raw.get("input_tokens", 0))),
            output_tokens_delta=int(raw.get("output_tokens_delta", raw.get("output_tokens", 0))),
            model_turns_delta=int(raw.get("model_turns_delta", raw.get("model_turns", 0))),
            elapsed_seconds_delta=float(
                raw.get("elapsed_seconds_delta", raw.get("elapsed_seconds", 0.0))
            ),
            report_ref=str(raw["report_ref"]) if raw.get("report_ref") else None,
            final_snapshot=str(raw["final_snapshot"]) if raw.get("final_snapshot") else None,
            evidence_refs=tuple(str(ref) for ref in raw.get("evidence_refs", ())),
            reason=str(raw["reason"]) if raw.get("reason") else None,
        )

    def _persist(self) -> None:
        if self.state_path:
            _write_json_atomic(self.state_path, self.snapshot())
