"""Validate artifact records and snapshot binding without invoking a model."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .errors import SnapshotDrift, ValidationError


ARTIFACT_KINDS = {"context_brief", "change_report", "review_report", "test_report", "handoff", "decision", "log"}


def validate_artifact_record(artifact: Mapping[str, Any]) -> None:
    required = {"artifact_id", "kind", "path", "producer_attempt_id", "snapshot", "sha256", "redaction_status", "retention"}
    missing = sorted(required - set(artifact))
    if missing:
        raise ValidationError("artifact missing fields: " + ", ".join(missing))
    if artifact["kind"] not in ARTIFACT_KINDS:
        raise ValidationError(f"unknown artifact kind: {artifact['kind']}")
    if not str(artifact["snapshot"]).strip():
        raise ValidationError("artifact must bind to a snapshot")
    if artifact["redaction_status"] not in {"not_required", "pending", "verified"}:
        raise ValidationError("invalid artifact redaction_status")


def validate_artifact_file(
    artifact: Mapping[str, Any],
    *,
    root: str | Path,
    expected_snapshot: str,
) -> None:
    validate_artifact_record(artifact)
    if str(artifact["snapshot"]) != expected_snapshot:
        raise SnapshotDrift(
            f"artifact {artifact['artifact_id']} belongs to {artifact['snapshot']!r}, "
            f"not expected snapshot {expected_snapshot!r}"
        )
    path = Path(root) / str(artifact["path"])
    if not path.is_file():
        raise ValidationError(f"artifact file does not exist: {artifact['path']}")
