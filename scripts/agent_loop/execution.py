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

from .errors import ValidationError
from .runner import RunnerEvent, RunnerRequest, runner_event_dict
from .recovery import RecoveryDecision, decide_recovery
from .retry_learning import (
    RETRY_ACTIONS,
    RECOVERY_ONLY_ACTIONS,
    build_retry_experience,
    evaluate_retry_learning,
    normalise_savings,
    validate_failure_signature,
    validate_retry_learning_event,
)


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
    retry_learning: list[dict[str, Any]] = field(default_factory=list)
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
        learning_event: Mapping[str, Any] | None = None,
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
        if learning_event is not None:
            validate_retry_learning_event(learning_event)
            entry["retry_learning"] = dict(learning_event)
            self.retry_learning.append(dict(learning_event))
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
            "retry_learning": list(self.retry_learning),
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
        raw_retry_learning = payload.get("retry_learning", [])
        raw_changed = payload.get("changed_paths", [])
        if not all(isinstance(value, list) for value in (raw_events, raw_artifacts, raw_recovery, raw_retry_learning, raw_changed)):
            raise ExecutionRecordError("execution record lists are invalid")
        if len(raw_events) > 32 or any(not isinstance(event, Mapping) for event in raw_events):
            raise ExecutionRecordError("execution record events are invalid")
        if any(not isinstance(item, Mapping) for item in raw_recovery):
            raise ExecutionRecordError("execution record recovery decisions are invalid")
        if any(not isinstance(item, Mapping) for item in raw_retry_learning):
            raise ExecutionRecordError("execution record retry learning is invalid")
        for item in raw_retry_learning:
            try:
                validate_retry_learning_event(item)
            except ValidationError as exc:
                raise ExecutionRecordError("execution record retry learning is invalid") from exc
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
                retry_learning=[dict(item) for item in raw_retry_learning],
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
            "retry_learning": list(self.retry_learning),
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
        retry_learning_context: Mapping[str, Any] | None = None,
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
        self.retry_learning_context = dict(retry_learning_context or {})
        prior_retry_learning = self.retry_learning_context.get("prior_retry_learning", [])
        if prior_retry_learning:
            if not isinstance(prior_retry_learning, list):
                raise ExecutionRecordError("prior retry learning must be a list")
            existing_keys = {
                str(item.get("retry_id") or item.get("learning_delta_digest") or "")
                for item in self.record.retry_learning
                if isinstance(item, Mapping)
            }
            for item in prior_retry_learning:
                if not isinstance(item, Mapping):
                    raise ExecutionRecordError("prior retry learning event is invalid")
                try:
                    validate_retry_learning_event(item)
                except ValidationError as exc:
                    raise ExecutionRecordError("prior retry learning event is invalid") from exc
                key = str(item.get("retry_id") or item.get("learning_delta_digest") or "")
                if key and key in existing_keys:
                    continue
                self.record.retry_learning.append(dict(item))
                if key:
                    existing_keys.add(key)

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
        retry_learning_context: Mapping[str, Any] | None = None,
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
            retry_learning_context=retry_learning_context,
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
        failure_signature: str | None = None,
        failure_action: Mapping[str, Any] | None = None,
        preconditions: list[str] | None = None,
        preconditions_changed: bool = False,
        learning_delta: Mapping[str, Any] | None = None,
        lesson_ids_applied: list[str] | None = None,
        eligible_lesson_ids: list[str] | None = None,
        savings: Mapping[str, Any] | None = None,
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
        previous_learning = next(
            (
                item
                for item in reversed(self.record.retry_learning)
                if item.get("failure_signature")
            ),
            {},
        )
        learning_status = "not_retryable"
        safe_failure_signature = ""
        try:
            safe_failure_signature = validate_failure_signature(failure_signature)
        except ValidationError:
            pass
        safe_failure_action = {}
        if isinstance(failure_action, Mapping):
            safe_failure_action = {
                field: str(failure_action[field]).strip()
                for field in ("tool", "operation", "target_scope", "failure_class")
                if str(failure_action.get(field, "")).strip()
            }
        learning_event: dict[str, Any] = {
            "schema": "agent-loop.retry-learning.v1",
            "retry_id": f"{self.record.identity.attempt_id}-retry-{len(self.record.retry_learning) + 1}",
            "status": learning_status,
            "action": decision.action,
            "reason": decision.reason,
            "failure_class": failure_class or "unknown",
            "failure_signature": safe_failure_signature,
            "failure_action": safe_failure_action,
            "preconditions": list(preconditions or []),
            "preconditions_changed": bool(preconditions_changed),
            "learning_delta": None,
            "learning_delta_digest": "",
            "lesson_created": [],
            "lesson_applied": [],
            "savings": normalise_savings(savings),
            "failed_elapsed_seconds": self.record.elapsed_seconds,
            "failed_input_tokens": self.record.input_tokens,
            "failed_output_tokens": self.record.output_tokens,
            "failed_model_turns": self.record.model_turns_used,
        }
        if decision.action in RETRY_ACTIONS:
            if not isinstance(failure_action, Mapping):
                learning_gate_reason = "retry requires a structured failure_action"
                gate_allowed = False
                gate_digest = ""
            else:
                gate = evaluate_retry_learning(
                    action=decision.action,
                    failure_signature=str(failure_signature or ""),
                    learning_delta=learning_delta,
                    previous_failure_signature=previous_learning.get("failure_signature"),
                    previous_learning_delta_digest=previous_learning.get("learning_delta_digest"),
                    preconditions_changed=preconditions_changed,
                    lesson_ids_applied=lesson_ids_applied or [],
                    eligible_lesson_ids=eligible_lesson_ids or [],
                )
                learning_gate_reason = gate.reason
                gate_allowed = gate.allowed
                gate_digest = gate.delta_digest
            if not gate_allowed:
                decision = RecoveryDecision(
                    "STOP_NO_LEARNING",
                    learning_gate_reason,
                    False,
                    True,
                    True,
                )
                learning_status = "blocked_no_learning"
            else:
                learning_status = "retry_allowed"
                learning_event["learning_delta"] = dict(learning_delta or {})
                learning_event["learning_delta_digest"] = gate_digest
                learning_event["lesson_applied"] = [
                    str(item).strip()
                    for item in (lesson_ids_applied or [])
                    if str(item).strip()
                ]
        elif decision.action in RECOVERY_ONLY_ACTIONS:
            learning_status = "recovery_only"
        learning_event["status"] = learning_status
        learning_event["action"] = decision.action
        learning_event["reason"] = decision.reason
        validate_retry_learning_event(learning_event)
        self.record.record_recovery_decision(
            decision,
            failure_class=failure_class,
            remaining_budget=remaining_budget,
            learning_event=learning_event,
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
        event = self._accept(event)
        if event.status == "closed":
            self._finalize_retry_learning()
        return event

    def _finalize_retry_learning(self) -> None:
        """Create candidate-only Lessons after a successful retry fallback."""

        retry_events = [
            event
            for event in self.record.retry_learning
            if event.get("status") == "retry_allowed"
        ]
        if not retry_events:
            return
        for event in retry_events:
            # A cross-Runner retry may already carry counters from the failed
            # Runner.  Preserve those measured values instead of replacing
            # them with the new Runner's unrelated totals.
            if "retry_elapsed_seconds" not in event:
                event["retry_elapsed_seconds"] = max(
                    0.0,
                    self.record.elapsed_seconds
                    - float(event.get("failed_elapsed_seconds", 0.0) or 0.0),
                )
            if "retry_input_tokens" not in event:
                event["retry_input_tokens"] = max(
                    0,
                    self.record.input_tokens
                    - int(event.get("failed_input_tokens", 0) or 0),
                )
            if "retry_output_tokens" not in event:
                event["retry_output_tokens"] = max(
                    0,
                    self.record.output_tokens
                    - int(event.get("failed_output_tokens", 0) or 0),
                )
            if "retry_model_turns" not in event:
                event["retry_model_turns"] = max(
                    0,
                    self.record.model_turns_used
                    - int(event.get("failed_model_turns", 0) or 0),
                )

        context = dict(self.retry_learning_context)
        output_dir = context.get("output_dir")
        if output_dir is None and self.journal is not None:
            output_dir = (
                self.journal.path.parent.parent
                / "experience"
                / self.record.identity.attempt_id
            )
        if output_dir is None:
            for event in retry_events:
                event["lesson_creation_status"] = "unavailable"
                event["lesson_creation_reason"] = "no candidate output directory configured"
            self._persist_record()
            return

        source_refs = [str(ref) for ref in context.get("source_refs", []) if str(ref).strip()]
        if self.journal is not None:
            source_refs.append(str(self.journal.path))
        if self.record.report_ref:
            source_refs.append(str(self.record.report_ref))
        try:
            experience_manifest, lessons = build_retry_experience(
                retry_events,
                task_id=self.record.identity.task_id,
                task_revision=self.record.identity.task_revision,
                snapshot=self.record.final_snapshot or self.record.identity.snapshot,
                source_refs=list(dict.fromkeys(source_refs)),
                domain=str(context.get("domain", "loop")),
                task_type=str(context.get("task_type", "retry_recovery")),
                changed_paths=self.record.changed_paths,
                contract_versions=context.get(
                    "contract_versions", {"agent-loop": "retry-learning:v1"}
                ),
            )
            from .experience import write_experience_store

            write_experience_store(output_dir, experience_manifest, lessons)
            lesson_ids = [str(lesson["lesson_id"]) for lesson in lessons]
            for index, event in enumerate(retry_events):
                event["lesson_creation_status"] = "created"
                event["lesson_created"] = (
                    [lesson_ids[index]] if index < len(lesson_ids) else []
                )
                event["candidate_experience_ref"] = str(Path(output_dir) / "ExperienceManifest.yaml")
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            for event in retry_events:
                event["lesson_creation_status"] = "blocked"
                event["lesson_creation_reason"] = type(exc).__name__
        for event in retry_events:
            validate_retry_learning_event(event)
        self._persist_record()

    def _persist_record(self) -> None:
        if self.journal is not None:
            self.journal.write(self.record)

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
