"""Codex host transport with strict Runner lifecycle mapping.

The bridge is injected by the host application.  This module owns the
project/snapshot request and maps normalized platform responses to the generic
ExternalRunnerAdapter contract.  It never calls the Codex app directly.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from .codex_bridge import (
    CodexThreadHandle,
    build_codex_thread_launch,
    parse_codex_thread_handle,
    parse_codex_runner_ref,
)
from .errors import ValidationError
from .launch import build_launch_spec_from_payload


class CodexHostTransportError(ValidationError):
    """Raised when a host response cannot be safely mapped to a Runner event."""


class CodexHostBridge(Protocol):
    """Small platform boundary implemented by the Codex host integration."""

    def create_task(self, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def rebind_task(
        self, handle: CodexThreadHandle, *, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...

    def wait_task(self, handle: CodexThreadHandle) -> Mapping[str, Any]: ...

    def interrupt_task(
        self, handle: CodexThreadHandle, *, reason: str
    ) -> Mapping[str, Any]: ...

    def resume_task(
        self, handle: CodexThreadHandle, *, artifact_refs: tuple[str, ...]
    ) -> Mapping[str, Any]: ...

    def close_task(
        self, handle: CodexThreadHandle, *, report_ref: str
    ) -> Mapping[str, Any]: ...


_STATUS_MAP = {
    "queued": "running",
    "starting": "running",
    "running": "running",
    "in_progress": "running",
    "interrupted": "interrupted",
    "paused": "interrupted",
    "cancelled": "interrupted",
    "canceled": "interrupted",
    "disconnected": "lost",
    "lost": "lost",
    "needs_attention": "blocked",
    "blocked": "blocked",
    "closed": "closed",
}


class CodexHostTransport:
    """Implement ExternalTransport over an injected Codex host bridge."""

    def __init__(
        self,
        *,
        project_id: str,
        project_is_git: bool,
        bridge: CodexHostBridge,
    ) -> None:
        self.project_id = project_id
        self.project_is_git = project_is_git
        self.bridge = bridge
        self._launch: Any = None
        self._handle: CodexThreadHandle | None = None
        self._status: str = "new"
        self._resume_count = 0

    def open(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if self._handle is not None:
            raise CodexHostTransportError("Codex host transport already opened")
        spec = build_launch_spec_from_payload(payload)
        launch = build_codex_thread_launch(
            spec,
            project_id=self.project_id,
            project_is_git=self.project_is_git,
        )
        handle = parse_codex_thread_handle(
            self.bridge.create_task(launch.to_payload())
        )
        self._launch = launch
        self._handle = handle
        self._status = "running"
        return self._event("opened", "running")

    def rebind(self, payload: Mapping[str, Any], runner_ref: str) -> Mapping[str, Any]:
        """Attach to an existing Host session without creating another task."""
        if self._handle is not None:
            raise CodexHostTransportError("Codex host transport already initialized")
        spec = build_launch_spec_from_payload(payload)
        launch = build_codex_thread_launch(
            spec,
            project_id=self.project_id,
            project_is_git=self.project_is_git,
        )
        try:
            handle = parse_codex_runner_ref(runner_ref)
        except Exception as exc:
            raise CodexHostTransportError(str(exc)) from exc
        rebind = getattr(self.bridge, "rebind_task", None)
        if rebind is None:
            raise CodexHostTransportError(
                "configured Host bridge does not support durable session rebind"
            )
        response = rebind(handle, payload=launch.to_payload())
        status, reason = self._status_from_response(response, closing=False)
        if status not in {"running", "interrupted", "lost", "blocked"}:
            raise CodexHostTransportError(
                f"cannot rebind Codex task in state {status}"
            )
        self._launch = launch
        self._handle = handle
        try:
            self._resume_count = int(response.get("resume_count", 0))
        except (AttributeError, TypeError, ValueError) as exc:
            raise CodexHostTransportError("rebound Host resume_count is invalid") from exc
        if self._resume_count < 0:
            raise CodexHostTransportError("rebound Host resume_count is invalid")
        self._status = status
        return self._event("rebound", status, reason=reason, response=response)

    def wait(self, runner_ref: str) -> Mapping[str, Any]:
        handle = self._require_ref(runner_ref)
        if self._status == "closed":
            raise CodexHostTransportError("cannot wait for a closed Codex task")
        response = self.bridge.wait_task(handle)
        status, reason = self._status_from_response(response, closing=False)
        self._status = status
        return self._event("waited", status, reason=reason, response=response)

    def inject_loss(self, runner_ref: str, *, reason: str) -> Mapping[str, Any]:
        """Expose the CLI bridge's explicit phase-two loss experiment hook."""
        handle = self._require_ref(runner_ref)
        injector = getattr(self.bridge, "inject_loss", None)
        if injector is None:
            raise CodexHostTransportError("configured host bridge does not support loss injection")
        response = injector(handle, reason=reason)
        status, response_reason = self._status_from_response(response, closing=False)
        if status != "lost":
            raise CodexHostTransportError("host loss injection did not produce lost status")
        self._status = status
        return self._event("lost", status, reason=response_reason, response=response)

    def interrupt(self, runner_ref: str, *, reason: str) -> Mapping[str, Any]:
        handle = self._require_ref(runner_ref)
        if self._status != "running":
            raise CodexHostTransportError(
                f"cannot interrupt Codex task in state {self._status}"
            )
        if not reason.strip():
            raise CodexHostTransportError("interrupt reason must not be empty")
        response = self.bridge.interrupt_task(handle, reason=reason)
        status, response_reason = self._status_from_response(response, closing=False)
        if status == "running":
            raise CodexHostTransportError("host did not interrupt Codex task")
        self._status = status
        return self._event(
            "interrupted",
            status,
            reason=response_reason or reason,
            response=response,
        )

    def resume(
        self, runner_ref: str, *, artifact_refs: tuple[str, ...]
    ) -> Mapping[str, Any]:
        handle = self._require_ref(runner_ref)
        if self._status not in {"interrupted", "lost"}:
            raise CodexHostTransportError(
                f"cannot resume Codex task in state {self._status}"
            )
        if not artifact_refs or any(not str(ref).strip() for ref in artifact_refs):
            raise CodexHostTransportError("resume requires non-empty artifact_refs")
        response = self.bridge.resume_task(handle, artifact_refs=artifact_refs)
        status, reason = self._status_from_response(response, closing=False)
        if status != "running":
            raise CodexHostTransportError("host did not resume Codex task")
        self._resume_count += 1
        self._status = status
        return self._event("resumed", status, reason=reason, response=response)

    def close(self, runner_ref: str, *, report_ref: str) -> Mapping[str, Any]:
        handle = self._require_ref(runner_ref)
        if self._status not in {"running", "interrupted"}:
            raise CodexHostTransportError(
                f"cannot close Codex task in state {self._status}"
            )
        if not report_ref.strip():
            raise CodexHostTransportError("close requires report_ref")
        response = self.bridge.close_task(handle, report_ref=report_ref)
        status, reason = self._status_from_response(response, closing=True)
        if status != "closed":
            raise CodexHostTransportError("host did not close Codex task")
        self._status = status
        return self._event(
            "closed", status, reason=reason, report_ref=report_ref, response=response
        )

    def _require_ref(self, runner_ref: str) -> CodexThreadHandle:
        if self._handle is None:
            raise CodexHostTransportError("Codex host transport is not open")
        if runner_ref != self._handle.runner_ref:
            raise CodexHostTransportError("Codex Runner reference mismatch")
        return self._handle

    @staticmethod
    def _status_from_response(
        response: Mapping[str, Any], *, closing: bool
    ) -> tuple[str, str | None]:
        if not isinstance(response, Mapping):
            raise CodexHostTransportError("Codex host response must be a mapping")
        raw_status = str(response.get("status") or "").strip().lower()
        if closing and raw_status == "completed":
            status = "closed"
        elif not closing and raw_status == "completed":
            # RunnerExecution performs the explicit close after the report exists.
            status = "interrupted"
        else:
            status = _STATUS_MAP.get(raw_status, "")
        if not status:
            raise CodexHostTransportError(
                f"unsupported Codex host status: {raw_status or 'missing'}"
            )
        reason = str(response.get("reason") or "").strip() or None
        if status in {"lost", "blocked"} and not reason:
            raise CodexHostTransportError(
                f"Codex host status {status} requires a reason"
            )
        return status, reason

    def _event(
        self,
        event: str,
        status: str,
        *,
        reason: str | None = None,
        report_ref: str | None = None,
        response: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._launch is None or self._handle is None:
            raise CodexHostTransportError("Codex task identity is not initialized")
        response_report = str((response or {}).get("report_ref") or "").strip()
        # A host may copy a transient child-worktree report into a stable
        # artifact store while closing. Prefer that returned path so callers
        # never receive a reference to a worktree that is about to be removed.
        final_report = response_report or report_ref or None
        if status == "closed" and not final_report:
            raise CodexHostTransportError("closed Codex task requires report_ref")
        raw_final_snapshot = (response or {}).get("final_snapshot")
        final_snapshot = (
            str(raw_final_snapshot).strip() if raw_final_snapshot is not None else None
        )
        if raw_final_snapshot is not None and not final_snapshot:
            raise CodexHostTransportError("final_snapshot must not be empty")
        raw_changed_paths = (response or {}).get("changed_paths", ())
        if not isinstance(raw_changed_paths, (list, tuple)):
            raise CodexHostTransportError("changed_paths must be a list")
        try:
            input_tokens = int((response or {}).get("input_tokens", 0))
            output_tokens = int((response or {}).get("output_tokens", 0))
            elapsed_seconds = float((response or {}).get("elapsed_seconds", 0.0))
        except (TypeError, ValueError) as exc:
            raise CodexHostTransportError("host metrics are invalid") from exc
        if input_tokens < 0 or output_tokens < 0 or elapsed_seconds < 0:
            raise CodexHostTransportError("host metrics must be non-negative")
        return {
            "runner_ref": self._handle.runner_ref,
            "event": event,
            "status": status,
            "task_id": self._launch.task_id,
            "task_revision": self._launch.task_revision,
            "attempt_id": self._launch.attempt_id,
            "profile_revision": self._launch.profile_revision,
            "snapshot": self._launch.snapshot,
            "write_scope": list(self._launch.write_scope),
            "resume_count": self._resume_count,
            "report_ref": final_report,
            "reason": reason,
            "final_snapshot": final_snapshot,
            "changed_paths": [str(path) for path in raw_changed_paths],
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "elapsed_seconds": elapsed_seconds,
        }
