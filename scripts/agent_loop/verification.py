"""Deterministic Test/Verification plan derived from an Owner handoff."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping

from .errors import ValidationError
from .handoff import HandoffEnvelope
from .validate_packet import validate_profile, validate_test_matrix


_DOMAINS = {"core", "trainer", "product", "teacher"}


@dataclass(frozen=True)
class VerificationPlan:
    task_id: str
    task_revision: int
    verification_attempt_id: str
    source_attempt_id: str
    domain: str
    snapshot: str
    changed_paths: tuple[str, ...]
    verification_scope: tuple[str, ...]
    command_ids: tuple[str, ...]
    commands: tuple[Mapping[str, Any], ...]
    test_write_roots: tuple[str, ...]
    docker_enabled: bool
    docker_compose_files: tuple[str, ...]
    docker_allowed_actions: tuple[str, ...]
    cleanup_required: bool
    max_runtime_minutes: int
    artifact_refs: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "protocol_version": 1,
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "verification_attempt_id": self.verification_attempt_id,
            "source_attempt_id": self.source_attempt_id,
            "domain": self.domain,
            "snapshot": self.snapshot,
            "changed_paths": list(self.changed_paths),
            "verification_scope": list(self.verification_scope),
            "command_ids": list(self.command_ids),
            "commands": [copy.deepcopy(dict(command)) for command in self.commands],
            "test_write_roots": list(self.test_write_roots),
            "docker": {
                "enabled": self.docker_enabled,
                "compose_files": list(self.docker_compose_files),
                "allowed_actions": list(self.docker_allowed_actions),
                "cleanup_required": self.cleanup_required,
                "max_runtime_minutes": self.max_runtime_minutes,
            },
            "artifact_refs": list(self.artifact_refs),
        }


def build_verification_plan(
    handoff: HandoffEnvelope,
    *,
    test_profile: Mapping[str, Any],
    test_matrix: Mapping[str, Any],
    verification_attempt_id: str,
    command_ids: tuple[str, ...],
    docker_enabled: bool = False,
) -> VerificationPlan:
    """Build a bounded test plan without running commands or Docker."""
    if handoff.to_role != "test-verification":
        raise ValidationError("VerificationPlan requires a Test/Verification handoff")
    if handoff.from_role not in _DOMAINS:
        raise ValidationError("VerificationPlan source must map to a TestMatrix domain")
    if not verification_attempt_id.strip():
        raise ValidationError("VerificationPlan attempt id must not be empty")
    if not command_ids:
        raise ValidationError("VerificationPlan requires at least one command")

    validate_profile(test_profile)
    if test_profile.get("agent_id") != "test-verification":
        raise ValidationError("VerificationPlan requires the test-verification profile")
    if bool(test_profile["capabilities"]["can_modify_production_code"]):
        raise ValidationError("Test/Verification profile cannot write production code")
    validate_test_matrix(test_matrix)

    domain = next(
        (item for item in test_matrix["domains"] if item["domain"] == handoff.from_role),
        None,
    )
    if domain is None:
        raise ValidationError("Handoff source has no matching TestMatrix domain")
    command_map = {str(command["id"]): command for command in domain["commands"]}
    unknown = sorted(set(command_ids) - set(command_map))
    if unknown:
        raise ValidationError("VerificationPlan command is not in TestMatrix: " + ", ".join(unknown))

    profile_docker = test_profile["docker"]
    domain_docker = domain["docker"]
    if docker_enabled:
        if not profile_docker["allowed"] or not profile_docker["cleanup_required"]:
            raise ValidationError("Test/Verification Docker policy is not ready")
        if int(profile_docker["max_runtime_minutes"]) <= 0:
            raise ValidationError("Test/Verification Docker runtime must be positive")
        missing_compose = sorted(
            set(domain_docker["compose_files"]) - set(profile_docker["compose_files"])
        )
        if missing_compose:
            raise ValidationError(
                "Test/Verification profile does not allow domain compose files: "
                + ", ".join(missing_compose)
            )
        docker_files = tuple(str(item) for item in domain_docker["compose_files"])
        docker_actions = tuple(str(item) for item in domain_docker["allowed_actions"])
        max_runtime = min(
            int(profile_docker["max_runtime_minutes"]),
            int(test_matrix["default_docker"]["max_runtime_minutes"]),
        )
    else:
        docker_files = ()
        docker_actions = ()
        max_runtime = 0

    return VerificationPlan(
        task_id=handoff.task_id,
        task_revision=handoff.task_revision,
        verification_attempt_id=verification_attempt_id,
        source_attempt_id=handoff.attempt_id,
        domain=handoff.from_role,
        snapshot=handoff.final_snapshot,
        changed_paths=handoff.changed_paths,
        verification_scope=handoff.verification_scope,
        command_ids=tuple(command_ids),
        commands=tuple(copy.deepcopy(dict(command_map[item])) for item in command_ids),
        test_write_roots=tuple(str(item) for item in test_profile["capabilities"]["test_write_roots"]),
        docker_enabled=docker_enabled,
        docker_compose_files=docker_files,
        docker_allowed_actions=docker_actions,
        cleanup_required=bool(profile_docker["cleanup_required"]) if docker_enabled else False,
        max_runtime_minutes=max_runtime,
        artifact_refs=handoff.artifact_refs,
    )
