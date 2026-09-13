"""Explicit Owner-to-Verification handoff contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import ValidationError
from .execution import ExecutionRecord
from .launch import RunnerLaunchSpec


_DOMAIN_ROLES = {"core", "trainer", "product", "teacher", "context-integration"}
_TARGET_ROLES = {"test-verification", "main"}


def _required(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationError(f"Handoff requires {label}")
    return text


def _safe_ref(value: str, label: str) -> str:
    text = _required(value, label)
    if "\x00" in text or len(text) > 240:
        raise ValidationError(f"invalid Handoff {label}")
    return text


def _within_scope(path: str, scope: tuple[str, ...]) -> bool:
    normalized = path.strip("/")
    return any(
        normalized == parent.strip("/")
        or normalized.startswith(parent.strip("/") + "/")
        for parent in scope
    )


@dataclass(frozen=True)
class HandoffEnvelope:
    task_id: str
    task_revision: int
    attempt_id: str
    from_role: str
    to_role: str
    snapshot: str
    task_packet_ref: str
    context_brief_ref: str
    artifact_refs: tuple[str, ...]
    changed_paths: tuple[str, ...]
    verification_scope: tuple[str, ...]
    reason: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "protocol_version": 1,
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "attempt_id": self.attempt_id,
            "from_role": self.from_role,
            "to_role": self.to_role,
            "snapshot": self.snapshot,
            "task_packet_ref": self.task_packet_ref,
            "context_brief_ref": self.context_brief_ref,
            "artifact_refs": list(self.artifact_refs),
            "changed_paths": list(self.changed_paths),
            "verification_scope": list(self.verification_scope),
            "reason": self.reason,
        }


def build_handoff(
    spec: RunnerLaunchSpec,
    record: ExecutionRecord,
    *,
    to_role: str,
    verification_scope: tuple[str, ...],
    changed_paths: tuple[str, ...] = (),
    reason: str = "owner report ready for independent verification",
) -> HandoffEnvelope:
    """Create a handoff only after the source Runner closed with a report."""
    identity = record.identity
    if identity.task_id != spec.request.task_id or identity.task_revision != spec.request.task_revision:
        raise ValidationError("Handoff execution identity does not match LaunchSpec")
    if identity.snapshot != spec.request.snapshot:
        raise ValidationError("Handoff snapshot does not match LaunchSpec")
    if record.status != "closed":
        raise ValidationError("Handoff requires a closed source Runner")
    if not record.report_ref:
        raise ValidationError("Handoff requires the source report reference")
    if identity.role not in _DOMAIN_ROLES:
        raise ValidationError("Handoff source must be a domain or context owner")
    if to_role not in _TARGET_ROLES or to_role == identity.role:
        raise ValidationError("Handoff target role is not allowed")
    if not verification_scope:
        raise ValidationError("Handoff verification_scope must not be empty")
    for path in changed_paths:
        if not _within_scope(str(path), spec.request.write_scope):
            raise ValidationError(f"Handoff changed path exceeds write scope: {path}")
    artifacts = list(dict.fromkeys((*record.artifact_refs, record.report_ref)))
    for ref in artifacts:
        _safe_ref(ref, "artifact_ref")
    for path in (*changed_paths, *verification_scope):
        _safe_ref(str(path), "path")
    _safe_ref(spec.task_packet_ref, "task_packet_ref")
    _safe_ref(spec.context_brief_ref, "context_brief_ref")
    _required(reason, "reason")
    return HandoffEnvelope(
        task_id=identity.task_id,
        task_revision=identity.task_revision,
        attempt_id=identity.attempt_id,
        from_role=identity.role,
        to_role=to_role,
        snapshot=identity.snapshot,
        task_packet_ref=spec.task_packet_ref,
        context_brief_ref=spec.context_brief_ref,
        artifact_refs=tuple(artifacts),
        changed_paths=tuple(changed_paths),
        verification_scope=tuple(verification_scope),
        reason=reason,
    )
