"""Model-free Runner lifecycle contract for the Agent Loop.

This module deliberately does not launch Codex, Docker, or a model.  It makes
the lifecycle and safety checks executable before an external runner adapter
is connected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping, Protocol

from .errors import StateTransitionError, ValidationError

RunnerStatus = Literal["running", "interrupted", "lost", "blocked", "closed"]


@dataclass(frozen=True)
class RunnerRequest:
    task_id: str
    task_revision: int
    attempt_id: str
    role: str
    profile_revision: str
    snapshot: str
    write_scope: tuple[str, ...]
    max_turns: int

    def validate(self) -> None:
        required = {
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "role": self.role,
            "profile_revision": self.profile_revision,
            "snapshot": self.snapshot,
        }
        missing = sorted(name for name, value in required.items() if not str(value).strip())
        if missing:
            raise ValidationError("RunnerRequest missing fields: " + ", ".join(missing))
        if self.task_revision < 1:
            raise ValidationError("RunnerRequest.task_revision must be positive")
        if not self.write_scope:
            raise ValidationError("RunnerRequest.write_scope must not be empty")
        if self.max_turns < 1:
            raise ValidationError("RunnerRequest.max_turns must be positive")


@dataclass(frozen=True)
class RunnerEvent:
    runner_ref: str
    event: str
    status: RunnerStatus
    task_id: str
    task_revision: int
    attempt_id: str
    profile_revision: str
    snapshot: str
    write_scope: tuple[str, ...]
    resume_count: int
    report_ref: str | None = None
    reason: str | None = None


class RunnerAdapter(Protocol):
    def open(self, request: RunnerRequest) -> RunnerEvent: ...

    def wait(self, runner_ref: str) -> RunnerEvent: ...

    def interrupt(self, runner_ref: str, *, reason: str) -> RunnerEvent: ...

    def resume(self, runner_ref: str, *, artifact_refs: tuple[str, ...]) -> RunnerEvent: ...

    def close(self, runner_ref: str, *, report_ref: str) -> RunnerEvent: ...


@dataclass
class _Session:
    runner_ref: str
    request: RunnerRequest
    status: RunnerStatus
    resume_count: int = 0
    report_ref: str | None = None
    reason: str | None = None


class DeterministicRunner:
    """In-memory lifecycle adapter used for protocol tests and dry runs."""

    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}

    def open(self, request: RunnerRequest) -> RunnerEvent:
        request.validate()
        if request.attempt_id in {session.request.attempt_id for session in self._sessions.values()}:
            raise ValidationError(f"Runner attempt already exists: {request.attempt_id}")
        runner_ref = f"deterministic:{request.task_id}:{request.attempt_id}"
        self._sessions[runner_ref] = _Session(
            runner_ref=runner_ref,
            request=request,
            status="running",
        )
        return self._event(self._sessions[runner_ref], "opened")

    def wait(self, runner_ref: str) -> RunnerEvent:
        session = self._session(runner_ref)
        return self._event(session, "waited")

    def interrupt(self, runner_ref: str, *, reason: str) -> RunnerEvent:
        session = self._session(runner_ref)
        if session.status != "running":
            raise StateTransitionError(f"cannot interrupt Runner in state {session.status}")
        if not reason.strip():
            raise ValidationError("interrupt reason must not be empty")
        session.status = "interrupted"
        session.reason = reason
        return self._event(session, "interrupted")

    def resume(self, runner_ref: str, *, artifact_refs: tuple[str, ...]) -> RunnerEvent:
        session = self._session(runner_ref)
        if session.status not in {"interrupted", "lost"}:
            raise StateTransitionError(f"cannot resume Runner in state {session.status}")
        if not artifact_refs or any(not str(ref).strip() for ref in artifact_refs):
            raise ValidationError("resume requires non-empty artifact_refs")
        session.status = "running"
        session.resume_count += 1
        session.reason = None
        return self._event(session, "resumed")

    def close(self, runner_ref: str, *, report_ref: str) -> RunnerEvent:
        session = self._session(runner_ref)
        if session.status not in {"running", "interrupted"}:
            raise StateTransitionError(f"cannot close Runner in state {session.status}")
        if not report_ref.strip():
            raise ValidationError("close requires report_ref")
        session.status = "closed"
        session.report_ref = report_ref
        return self._event(session, "closed")

    def mark_lost(self, runner_ref: str, *, reason: str) -> RunnerEvent:
        """Test-only failure injection; recovery must use resume with evidence."""
        session = self._session(runner_ref)
        if session.status != "running":
            raise StateTransitionError(f"cannot lose Runner in state {session.status}")
        if not reason.strip():
            raise ValidationError("loss reason must not be empty")
        session.status = "lost"
        session.reason = reason
        return self._event(session, "lost")

    def _session(self, runner_ref: str) -> _Session:
        try:
            return self._sessions[runner_ref]
        except KeyError as exc:
            raise ValidationError(f"unknown runner_ref: {runner_ref}") from exc

    @staticmethod
    def _event(session: _Session, event: str) -> RunnerEvent:
        request = session.request
        return RunnerEvent(
            runner_ref=session.runner_ref,
            event=event,
            status=session.status,
            task_id=request.task_id,
            task_revision=request.task_revision,
            attempt_id=request.attempt_id,
            profile_revision=request.profile_revision,
            snapshot=request.snapshot,
            write_scope=request.write_scope,
            resume_count=session.resume_count,
            report_ref=session.report_ref,
            reason=session.reason,
        )


def runner_event_dict(event: RunnerEvent) -> Mapping[str, object]:
    """Return a JSON-friendly event payload for RunManifest adapters."""
    return {
        "runner_ref": event.runner_ref,
        "event": event.event,
        "status": event.status,
        "task_id": event.task_id,
        "task_revision": event.task_revision,
        "attempt_id": event.attempt_id,
        "profile_revision": event.profile_revision,
        "snapshot": event.snapshot,
        "write_scope": list(event.write_scope),
        "resume_count": event.resume_count,
        "report_ref": event.report_ref,
        "reason": event.reason,
    }
