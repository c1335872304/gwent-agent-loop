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
    final_snapshot: str
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
            "final_snapshot": self.final_snapshot,
            "task_packet_ref": self.task_packet_ref,
            "context_brief_ref": self.context_brief_ref,
            "artifact_refs": list(self.artifact_refs),
            "changed_paths": list(self.changed_paths),
            "verification_scope": list(self.verification_scope),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ContractHandoffEnvelope:
    """Closed-owner evidence passed to another domain consumer.

    A contract handoff is intentionally different from Owner-to-Test review:
    its target is another domain owner, and the payload carries the explicit
    contract references and consumer scope needed for that owner to continue.
    """

    task_id: str
    task_revision: int
    attempt_id: str
    from_role: str
    to_role: str
    snapshot: str
    final_snapshot: str
    task_packet_ref: str
    context_brief_ref: str
    artifact_refs: tuple[str, ...]
    changed_paths: tuple[str, ...]
    contract_refs: tuple[str, ...]
    contract_version: str
    consumer_scope: tuple[str, ...]
    reason: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "protocol_version": 1,
            "handoff_type": "cross-domain-contract",
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "attempt_id": self.attempt_id,
            "from_role": self.from_role,
            "to_role": self.to_role,
            "snapshot": self.snapshot,
            "final_snapshot": self.final_snapshot,
            "task_packet_ref": self.task_packet_ref,
            "context_brief_ref": self.context_brief_ref,
            "artifact_refs": list(self.artifact_refs),
            "changed_paths": list(self.changed_paths),
            "contract_refs": list(self.contract_refs),
            "contract_version": self.contract_version,
            "consumer_scope": list(self.consumer_scope),
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
    final_snapshot = record.final_snapshot or identity.snapshot
    _safe_ref(final_snapshot, "final_snapshot")
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
        final_snapshot=final_snapshot,
        task_packet_ref=spec.task_packet_ref,
        context_brief_ref=spec.context_brief_ref,
        artifact_refs=tuple(artifacts),
        changed_paths=tuple(changed_paths),
        verification_scope=tuple(verification_scope),
        reason=reason,
    )


def build_contract_handoff(
    spec: RunnerLaunchSpec,
    record: ExecutionRecord,
    *,
    to_role: str,
    contract_refs: tuple[str, ...],
    contract_version: str,
    consumer_scope: tuple[str, ...],
    changed_paths: tuple[str, ...] = (),
    reason: str = "closed owner contract is ready for the downstream domain",
) -> ContractHandoffEnvelope:
    """Create a scoped handoff between two distinct domain Owners."""
    identity = record.identity
    if identity.task_id != spec.request.task_id or identity.task_revision != spec.request.task_revision:
        raise ValidationError("Contract handoff execution identity does not match LaunchSpec")
    if identity.snapshot != spec.request.snapshot:
        raise ValidationError("Contract handoff snapshot does not match LaunchSpec")
    if record.status != "closed":
        raise ValidationError("Contract handoff requires a closed source Runner")
    if not record.report_ref:
        raise ValidationError("Contract handoff requires the source report reference")
    if identity.role not in _DOMAIN_ROLES:
        raise ValidationError("Contract handoff source must be a domain owner")
    if to_role not in _DOMAIN_ROLES or to_role == identity.role:
        raise ValidationError("Contract handoff target must be a different domain owner")
    if not contract_refs:
        raise ValidationError("Contract handoff requires contract_refs")
    if not consumer_scope:
        raise ValidationError("Contract handoff consumer_scope must not be empty")
    version = _required(contract_version, "contract_version")
    for ref in contract_refs:
        _safe_ref(str(ref), "contract_ref")
    for path in changed_paths:
        if not _within_scope(str(path), spec.request.write_scope):
            raise ValidationError(f"Contract handoff changed path exceeds write scope: {path}")
    for path in (*changed_paths, *consumer_scope):
        _safe_ref(str(path), "path")
    artifacts = list(dict.fromkeys((*record.artifact_refs, record.report_ref)))
    for ref in artifacts:
        _safe_ref(ref, "artifact_ref")
    final_snapshot = record.final_snapshot or identity.snapshot
    _safe_ref(final_snapshot, "final_snapshot")
    _safe_ref(spec.task_packet_ref, "task_packet_ref")
    _safe_ref(spec.context_brief_ref, "context_brief_ref")
    _required(reason, "reason")
    return ContractHandoffEnvelope(
        task_id=identity.task_id,
        task_revision=identity.task_revision,
        attempt_id=identity.attempt_id,
        from_role=identity.role,
        to_role=to_role,
        snapshot=identity.snapshot,
        final_snapshot=final_snapshot,
        task_packet_ref=spec.task_packet_ref,
        context_brief_ref=spec.context_brief_ref,
        artifact_refs=tuple(artifacts),
        changed_paths=tuple(changed_paths),
        contract_refs=tuple(dict.fromkeys(str(ref) for ref in contract_refs)),
        contract_version=version,
        consumer_scope=tuple(consumer_scope),
        reason=reason,
    )
