"""Durable, fail-closed control commands for a serial Scheduler.

This module deliberately sits *above* ``Scheduler`` and *below* any human
CLI, MCP tool, or UI.  It does not parse natural language, launch Codex, or
give an Owner/Test Runner permission to control itself.  Every mutating action
is identity-bound and idempotently journaled before its response is returned.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .errors import AgentLoopError, ValidationError
from .scheduler import Scheduler, ScheduledTask


CONTROL_ACTIONS = frozenset(
    {"inspect", "submit", "pause", "cancel", "prepare_resume", "resume", "events"}
)
CONTROL_ACTORS = frozenset({"user", "main_control"})
_SAFE_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


class ControlProtocolError(ValidationError):
    """Raised when an untrusted control request is incomplete or unsafe."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class ControlRequest:
    """One user-or-main-control request; never carries a raw parent transcript."""

    action: str
    task_id: str
    expected_revision: int | None
    expected_runner_ref: str | None
    actor: str
    reason: str
    idempotency_key: str
    payload: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ControlRequest":
        if not isinstance(value, Mapping):
            raise ControlProtocolError("control request must be a mapping")
        if int(value.get("protocol_version", 0)) != 1:
            raise ControlProtocolError("unsupported control request protocol")
        payload = value.get("payload", {})
        if not isinstance(payload, Mapping):
            raise ControlProtocolError("control request payload must be a mapping")
        try:
            request = cls(
                action=str(value["action"]).strip(),
                task_id=str(value["task_id"]).strip(),
                expected_revision=(int(value["expected_revision"]) if value.get("expected_revision") is not None else None),
                expected_runner_ref=(str(value["expected_runner_ref"]).strip() if value.get("expected_runner_ref") else None),
                actor=str(value["actor"]).strip(),
                reason=str(value.get("reason", "")).strip(),
                idempotency_key=str(value["idempotency_key"]).strip(),
                payload=dict(payload),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ControlProtocolError("control request fields are invalid") from exc
        request.validate()
        return request

    def validate(self) -> None:
        if self.action not in CONTROL_ACTIONS:
            raise ControlProtocolError(f"unsupported control action: {self.action!r}")
        if not _SAFE_TASK_ID.fullmatch(self.task_id):
            raise ControlProtocolError("control request has unsafe task_id")
        if self.expected_revision is not None and self.expected_revision < 1:
            raise ControlProtocolError("expected_revision must be positive")
        if self.actor not in CONTROL_ACTORS:
            raise ControlProtocolError("control actor must be user or main_control")
        try:
            uuid.UUID(self.idempotency_key)
        except (ValueError, AttributeError) as exc:
            raise ControlProtocolError("idempotency_key must be a UUID") from exc
        if self.action in {"pause", "cancel", "prepare_resume", "resume", "submit"} and not self.reason:
            raise ControlProtocolError(f"{self.action} requires a non-empty reason")
        if self.action in {"pause", "cancel", "prepare_resume", "resume"} and self.expected_revision is None:
            raise ControlProtocolError(f"{self.action} requires expected_revision")

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": 1,
            "action": self.action,
            "task_id": self.task_id,
            "expected_revision": self.expected_revision,
            "expected_runner_ref": self.expected_runner_ref,
            "actor": self.actor,
            "reason": self.reason,
            "idempotency_key": self.idempotency_key,
            "payload": dict(self.payload),
        }


class ControlJournal:
    """Append-only request/result journal with replay-safe idempotency keys."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.path = self.root / "control-events.ndjson"
        self.root.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._records: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            key = str(record.get("idempotency_key", ""))
            request = record.get("request")
            response = record.get("response")
            if not key or not isinstance(request, Mapping) or not isinstance(response, Mapping):
                raise ControlProtocolError("control journal contains an invalid record")
            previous = self._records.get(key)
            if previous is not None and _canonical(previous["request"]) != _canonical(request):
                raise ControlProtocolError("control journal contains conflicting idempotency key")
            self._records[key] = {"request": dict(request), "response": dict(response)}

    def replay(self, request: ControlRequest) -> dict[str, Any] | None:
        record = self._records.get(request.idempotency_key)
        if record is None:
            return None
        if _canonical(record["request"]) != _canonical(request.to_dict()):
            raise ControlProtocolError("idempotency_key was reused for a different request")
        response = dict(record["response"])
        response["idempotent_replay"] = True
        return response

    def append(self, request: ControlRequest, response: Mapping[str, Any]) -> None:
        if request.idempotency_key in self._records:
            raise ControlProtocolError("control journal key already exists")
        event = {
            "event_seq": len(self._records) + 1,
            "event_id": f"control-{request.idempotency_key}",
            "at": _now(),
            "idempotency_key": request.idempotency_key,
            "request": request.to_dict(),
            "response": dict(response),
        }
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        self._records[request.idempotency_key] = {
            "request": request.to_dict(),
            "response": dict(response),
        }

    def events(self, *, after_seq: int = 0) -> list[dict[str, Any]]:
        if after_seq < 0:
            raise ControlProtocolError("events after_seq cannot be negative")
        result: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                event = json.loads(line)
                if int(event["event_seq"]) > after_seq:
                    result.append(event)
        return result


class ResumeDirectiveStore:
    """Persist minimal supplemental facts without mutating an old TaskPacket."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def write(self, request: ControlRequest, task: ScheduledTask) -> str:
        raw_facts = request.payload.get("facts", [])
        if not isinstance(raw_facts, list) or not raw_facts:
            raise ControlProtocolError("prepare_resume requires a non-empty payload.facts list")
        if len(raw_facts) > 16 or any(not isinstance(item, Mapping) for item in raw_facts):
            raise ControlProtocolError("resume directive facts are invalid")
        facts: list[dict[str, str]] = []
        for raw in raw_facts:
            claim = str(raw.get("claim", "")).strip()
            source_ref = str(raw.get("source_ref", "")).strip()
            effect = str(raw.get("effect", "")).strip()
            if not claim or not source_ref or not effect:
                raise ControlProtocolError("each resume directive fact needs claim, source_ref and effect")
            if len(claim) > 600 or len(source_ref) > 300 or len(effect) > 300:
                raise ControlProtocolError("resume directive fact is too large")
            facts.append({"claim": claim, "source_ref": source_ref, "effect": effect})
        directive = {
            "schema": "agent-loop.resume-directive.v1",
            "task_id": task.task_id,
            "task_revision": task.revision,
            "runner_ref": task.handle,
            "actor": request.actor,
            "reason": request.reason,
            "facts": facts,
            "created_at": _now(),
            "idempotency_key": request.idempotency_key,
        }
        target = self.root / "resume-directives" / task.task_id / f"r{task.revision}-{request.idempotency_key}.json"
        _write_json_atomic(target, directive)
        return str(target)

    def latest_for(self, task: ScheduledTask) -> str | None:
        """Return the newest identity-matching directive after a service restart."""
        directory = self.root / "resume-directives" / task.task_id
        candidates = sorted(directory.glob(f"r{task.revision}-*.json"), key=lambda item: item.stat().st_mtime_ns, reverse=True)
        for candidate in candidates:
            try:
                value = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            try:
                revision_matches = int(value.get("task_revision", 0)) == task.revision
            except (TypeError, ValueError):
                revision_matches = False
            if (
                value.get("schema") == "agent-loop.resume-directive.v1"
                and value.get("task_id") == task.task_id
                and revision_matches
                and value.get("runner_ref") == task.handle
            ):
                return str(candidate)
        return None


SubmitHandler = Callable[[ControlRequest], Mapping[str, Any] | None]


class SchedulerControl:
    """Single-writer command facade for an injected, already-configured Scheduler."""

    def __init__(
        self,
        scheduler: Scheduler,
        *,
        state_root: str | Path,
        submit_handler: SubmitHandler | None = None,
    ) -> None:
        self.scheduler = scheduler
        root = Path(state_root).resolve()
        self.journal = ControlJournal(root)
        self.directives = ResumeDirectiveStore(root)
        self.submit_handler = submit_handler
        self._prepared: dict[str, str] = {}

    def dispatch(self, value: ControlRequest | Mapping[str, Any]) -> dict[str, Any]:
        request = value if isinstance(value, ControlRequest) else ControlRequest.from_mapping(value)
        replay = self.journal.replay(request)
        if replay is not None:
            return replay
        try:
            response = self._apply(request)
        except AgentLoopError as exc:
            response = self._blocked(request, str(exc))
        self.journal.append(request, response)
        return response

    def pump(self) -> tuple[dict[str, Any], ...]:
        return tuple(event.to_dict() for event in self.scheduler.pump())

    def _apply(self, request: ControlRequest) -> dict[str, Any]:
        if request.action == "events":
            after = int(request.payload.get("after_seq", 0))
            return {
                "status": "OK",
                "action": "events",
                "task_id": request.task_id,
                "control_events": self.journal.events(after_seq=after),
                "scheduler_events": [event.to_dict() for event in self.scheduler.events],
            }
        if request.action == "submit":
            if self.submit_handler is None:
                raise ControlProtocolError("submit is unavailable: no runtime submit handler is configured")
            extra = self.submit_handler(request)
            task = self.scheduler.get_task(request.task_id)
            return self._ok(request, task, extra=extra)

        task = self.scheduler.get_task(request.task_id)
        if request.action == "inspect":
            self._verify_identity(task, request, require_runner=False)
            return self._ok(request, task)
        self._verify_identity(task, request, require_runner=True)
        if request.action == "pause":
            task = self.scheduler.pause(task.task_id, reason=request.reason, actor=request.actor)
            return self._ok(request, task)
        if request.action == "cancel":
            task = self.scheduler.cancel(task.task_id, reason=request.reason, actor=request.actor)
            return self._ok(request, task)
        if request.action == "prepare_resume":
            if task.status != "paused":
                raise ControlProtocolError(f"prepare_resume requires paused task, got {task.status}")
            artifact_ref = self.directives.write(request, task)
            self._prepared[task.task_id] = artifact_ref
            return self._ok(request, task, extra={"resume_artifact_ref": artifact_ref})
        if request.action == "resume":
            if task.status != "paused":
                raise ControlProtocolError(f"resume requires paused task, got {task.status}")
            artifact_ref = self._prepared.get(task.task_id) or self.directives.latest_for(task)
            if not artifact_ref or not Path(artifact_ref).is_file():
                raise ControlProtocolError("resume requires a persisted prepare_resume directive")
            task = self.scheduler.resume(task.task_id, actor=request.actor)
            return self._ok(request, task, extra={"resume_artifact_ref": artifact_ref})
        raise ControlProtocolError(f"control action is not implemented: {request.action}")

    def _verify_identity(
        self,
        task: ScheduledTask,
        request: ControlRequest,
        *,
        require_runner: bool,
    ) -> None:
        if request.expected_revision is not None and request.expected_revision != task.revision:
            raise ControlProtocolError("expected_revision does not match the persisted task")
        if require_runner:
            if not task.handle:
                raise ControlProtocolError("active control requires a persisted runner_ref")
            if request.expected_runner_ref != task.handle:
                raise ControlProtocolError("expected_runner_ref does not match the persisted Runner")
        elif request.expected_runner_ref and request.expected_runner_ref != task.handle:
            raise ControlProtocolError("expected_runner_ref does not match the persisted Runner")

    def _ok(
        self,
        request: ControlRequest,
        task: ScheduledTask,
        *,
        extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = {
            "status": "OK",
            "action": request.action,
            "task_id": task.task_id,
            "task_revision": task.revision,
            "runner_ref": task.handle,
            "task_status": task.status,
            "scheduler_status": self.scheduler.snapshot()["scheduler_status"],
            "reason": task.reason,
        }
        if extra:
            response.update(dict(extra))
        return response

    def _blocked(self, request: ControlRequest, reason: str) -> dict[str, Any]:
        return {
            "status": "HUMAN_REQUIRED",
            "action": request.action,
            "task_id": request.task_id,
            "reason": reason,
            "scheduler_status": self.scheduler.snapshot()["scheduler_status"],
        }
