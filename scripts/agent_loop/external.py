"""Transport adapter boundary for a future external Runner."""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from .errors import ValidationError
from .launch import RunnerLaunchSpec
from .runner import RunnerEvent, RunnerRequest, RunnerStatus


class ExternalRunnerError(ValidationError):
    """Raised when an external transport returns an unsafe Runner response."""


class ExternalTransport(Protocol):
    def open(self, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def rebind(self, payload: Mapping[str, Any], runner_ref: str) -> Mapping[str, Any]: ...

    def wait(self, runner_ref: str) -> Mapping[str, Any]: ...

    def interrupt(self, runner_ref: str, *, reason: str) -> Mapping[str, Any]: ...

    def resume(
        self, runner_ref: str, *, artifact_refs: tuple[str, ...]
    ) -> Mapping[str, Any]: ...

    def close(self, runner_ref: str, *, report_ref: str) -> Mapping[str, Any]: ...


def _event_from_payload(payload: Mapping[str, Any]) -> RunnerEvent:
    required = {
        "runner_ref",
        "event",
        "status",
        "task_id",
        "task_revision",
        "attempt_id",
        "profile_revision",
        "snapshot",
        "write_scope",
        "resume_count",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise ExternalRunnerError(
            "external Runner response missing fields: " + ", ".join(missing)
        )
    status = str(payload["status"])
    if status not in {"running", "interrupted", "lost", "blocked", "closed"}:
        raise ExternalRunnerError(f"invalid external Runner status: {status}")
    scope = payload["write_scope"]
    if not isinstance(scope, (list, tuple)) or not scope:
        raise ExternalRunnerError("external Runner response has invalid write_scope")
    try:
        task_revision = int(payload["task_revision"])
        resume_count = int(payload["resume_count"])
    except (TypeError, ValueError) as exc:
        raise ExternalRunnerError("external Runner numeric fields are invalid") from exc
    if task_revision < 1 or resume_count < 0:
        raise ExternalRunnerError("external Runner numeric fields are out of range")
    raw_changed_paths = payload.get("changed_paths", ())
    if not isinstance(raw_changed_paths, (list, tuple)):
        raise ExternalRunnerError("external Runner response has invalid changed_paths")
    changed_paths = tuple(str(path) for path in raw_changed_paths)
    final_snapshot = payload.get("final_snapshot")
    if final_snapshot is not None and not str(final_snapshot).strip():
        raise ExternalRunnerError("external Runner response has invalid final_snapshot")
    try:
        input_tokens = int(payload.get("input_tokens", 0))
        output_tokens = int(payload.get("output_tokens", 0))
        elapsed_seconds = float(payload.get("elapsed_seconds", 0.0))
    except (TypeError, ValueError) as exc:
        raise ExternalRunnerError("external Runner metrics are invalid") from exc
    if input_tokens < 0 or output_tokens < 0 or elapsed_seconds < 0:
        raise ExternalRunnerError("external Runner metrics must be non-negative")
    return RunnerEvent(
        runner_ref=str(payload["runner_ref"]),
        event=str(payload["event"]),
        status=status,  # type: ignore[arg-type]
        task_id=str(payload["task_id"]),
        task_revision=task_revision,
        attempt_id=str(payload["attempt_id"]),
        profile_revision=str(payload["profile_revision"]),
        snapshot=str(payload["snapshot"]),
        write_scope=tuple(str(item) for item in scope),
        resume_count=resume_count,
        report_ref=(str(payload["report_ref"]) if payload.get("report_ref") else None),
        reason=(str(payload["reason"]) if payload.get("reason") else None),
        final_snapshot=str(final_snapshot) if final_snapshot is not None else None,
        changed_paths=changed_paths,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        elapsed_seconds=elapsed_seconds,
    )


class ExternalRunnerAdapter:
    """Map a validated launch spec onto an external transport.

    The transport may be a Codex bridge, a service process, or a test double.
    This class does not know how a child session is created and never creates
    one by itself.
    """

    def __init__(self, spec: RunnerLaunchSpec, transport: ExternalTransport):
        self.spec = spec
        self.transport = transport
        self._runner_ref: str | None = None
        self._closed = False

    def open(self, request: RunnerRequest) -> RunnerEvent:
        if self._runner_ref is not None:
            raise ExternalRunnerError("external Runner adapter already opened")
        if request != self.spec.request:
            raise ExternalRunnerError("RunnerRequest does not match LaunchSpec")
        event = self._decode(self.transport.open(self.spec.to_payload()))
        self._runner_ref = event.runner_ref
        return event

    def rebind(self, runner_ref: str) -> RunnerEvent:
        """Attach to the existing transport session; never call ``open``."""
        if self._runner_ref is not None:
            raise ExternalRunnerError("external Runner adapter already initialized")
        event = self._decode(self.transport.rebind(self.spec.to_payload(), runner_ref))
        if event.runner_ref != runner_ref:
            raise ExternalRunnerError("external Runner rebind reference mismatch")
        self._runner_ref = event.runner_ref
        return event

    def wait(self, runner_ref: str) -> RunnerEvent:
        self._require_ref(runner_ref)
        return self._decode(self.transport.wait(runner_ref))

    def interrupt(self, runner_ref: str, *, reason: str) -> RunnerEvent:
        self._require_ref(runner_ref)
        return self._decode(self.transport.interrupt(runner_ref, reason=reason))

    def resume(
        self, runner_ref: str, *, artifact_refs: tuple[str, ...]
    ) -> RunnerEvent:
        self._require_ref(runner_ref)
        return self._decode(
            self.transport.resume(runner_ref, artifact_refs=artifact_refs)
        )

    def close(self, runner_ref: str, *, report_ref: str) -> RunnerEvent:
        self._require_ref(runner_ref)
        event = self._decode(
            self.transport.close(runner_ref, report_ref=report_ref)
        )
        self._closed = True
        return event

    def _require_ref(self, runner_ref: str) -> None:
        if self._closed:
            raise ExternalRunnerError("external Runner adapter is closed")
        if self._runner_ref is None:
            raise ExternalRunnerError("external Runner adapter is not open")
        if runner_ref != self._runner_ref:
            raise ExternalRunnerError("external Runner reference mismatch")

    def _decode(self, payload: Mapping[str, Any]) -> RunnerEvent:
        if not isinstance(payload, Mapping):
            raise ExternalRunnerError("external Runner response must be a mapping")
        event = _event_from_payload(payload)
        if self._runner_ref is not None and event.runner_ref != self._runner_ref:
            raise ExternalRunnerError("external Runner response reference mismatch")
        return event
