"""Validated launch envelope for a future external Runner adapter."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping

from .errors import ValidationError
from .runner import RunnerRequest
from .validate_packet import validate_context_brief, validate_profile, validate_task_packet


def _require_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationError(f"RunnerLaunchSpec requires {label}")
    return text


def _validate_context_brief(
    context_brief: Mapping[str, Any],
    *,
    task_id: str,
    task_revision: int,
    snapshot: str,
) -> None:
    validate_context_brief(context_brief)
    if str(context_brief["task_id"]) != task_id:
        raise ValidationError("ContextBrief task_id does not match TaskPacket")
    context_revision = int(
        context_brief.get("packet_revision") or context_brief.get("revision") or 0
    )
    if context_revision != task_revision:
        raise ValidationError("ContextBrief packet revision does not match TaskPacket")
    context_snapshot = str(
        context_brief.get("context_snapshot") or context_brief.get("snapshot_id")
    )
    if context_snapshot != snapshot:
        raise ValidationError("ContextBrief snapshot does not match TaskPacket")


def _validate_write_scope(write_scope: tuple[str, ...], allowed: list[Any]) -> None:
    if not write_scope:
        raise ValidationError("RunnerLaunchSpec write_scope must not be empty")
    normalized_allowed = [str(path).strip("/") for path in allowed if str(path).strip()]
    for raw_path in write_scope:
        path = str(raw_path).strip("/")
        if path in {"declared test scope only", "task scope"}:
            continue
        if not any(path == parent or path.startswith(parent + "/") for parent in normalized_allowed):
            raise ValidationError(f"Runner write_scope exceeds TaskPacket scope: {raw_path}")


@dataclass(frozen=True)
class RunnerLaunchSpec:
    """Structured input passed to an external Runner adapter."""

    task_packet: Mapping[str, Any]
    context_brief: Mapping[str, Any]
    profile: Mapping[str, Any]
    request: RunnerRequest
    task_packet_ref: str
    context_brief_ref: str
    profile_ref: str
    max_input_tokens: int
    max_output_tokens: int
    max_elapsed_minutes: int
    subtask_depth: int

    def to_payload(self) -> dict[str, Any]:
        """Return structured input without any main-chat transcript."""
        return {
            "protocol_version": 1,
            "task_packet_ref": self.task_packet_ref,
            "context_brief_ref": self.context_brief_ref,
            "profile_ref": self.profile_ref,
            "request": {
                "task_id": self.request.task_id,
                "task_revision": self.request.task_revision,
                "attempt_id": self.request.attempt_id,
                "role": self.request.role,
                "profile_revision": self.request.profile_revision,
                "snapshot": self.request.snapshot,
                "write_scope": list(self.request.write_scope),
                "max_turns": self.request.max_turns,
            },
            "budgets": {
                "max_turns": self.request.max_turns,
                "max_input_tokens": self.max_input_tokens,
                "max_output_tokens": self.max_output_tokens,
                "max_elapsed_minutes": self.max_elapsed_minutes,
                "subtask_depth": self.subtask_depth,
            },
            "task_packet": copy.deepcopy(dict(self.task_packet)),
            "context_brief": copy.deepcopy(dict(self.context_brief)),
            "profile": copy.deepcopy(dict(self.profile)),
        }


def build_launch_spec(
    *,
    task_packet: Mapping[str, Any],
    context_brief: Mapping[str, Any],
    profile: Mapping[str, Any],
    task_packet_ref: str,
    context_brief_ref: str,
    profile_ref: str,
    attempt_id: str,
    write_scope: tuple[str, ...],
    max_turns: int,
    max_input_tokens: int,
    max_output_tokens: int,
    max_elapsed_minutes: int,
    subtask_depth: int = 1,
) -> RunnerLaunchSpec:
    """Validate and construct the only input shape an external Runner may receive."""
    validate_task_packet(task_packet)
    validate_profile(profile)

    task_id = _require_text(task_packet.get("task_id"), "TaskPacket task_id")
    task_revision = int(task_packet["revision"])
    snapshot = _require_text(task_packet["workspace"]["snapshot_ref"], "TaskPacket snapshot")
    role = _require_text(profile.get("agent_id"), "AgentProfile agent_id")
    execution = task_packet["execution"]
    if bool(execution.get("host_docker", False)):
        if role != "test-verification":
            raise ValidationError("host Docker access is restricted to test-verification")
        if not bool(profile.get("docker", {}).get("allowed", False)):
            raise ValidationError("host Docker access requires an allowed Test/Verification profile")
    _validate_context_brief(
        context_brief,
        task_id=task_id,
        task_revision=task_revision,
        snapshot=snapshot,
    )
    scope_paths = task_packet["scope"]["allowed_write_paths"]
    if role == "test-verification" and task_packet["scope"].get("allowed_test_write_paths"):
        scope_paths = task_packet["scope"]["allowed_test_write_paths"]
    _validate_write_scope(write_scope, list(scope_paths))

    if not attempt_id.strip() or not task_packet_ref.strip() or not context_brief_ref.strip() or not profile_ref.strip():
        raise ValidationError("RunnerLaunchSpec references and attempt_id must not be empty")
    if int(subtask_depth) < 0:
        raise ValidationError("RunnerLaunchSpec subtask_depth cannot be negative")

    profile_limits = profile["execution_limits"]
    limits = (
        ("max_turns", max_turns, "max_model_turns", execution["max_model_turns"]),
        ("max_input_tokens", max_input_tokens, "max_model_input_tokens", execution["max_model_input_tokens"]),
        ("max_output_tokens", max_output_tokens, "max_model_output_tokens", execution["max_model_output_tokens"]),
        ("max_elapsed_minutes", max_elapsed_minutes, "max_elapsed_minutes", execution["max_elapsed_minutes"]),
    )
    for label, value, packet_field, packet_limit in limits:
        if int(value) <= 0 or int(value) > int(packet_limit):
            raise ValidationError(f"RunnerLaunchSpec {label} exceeds TaskPacket budget")
    if int(max_input_tokens) > int(profile_limits["max_input_tokens"]):
        raise ValidationError("RunnerLaunchSpec input budget exceeds AgentProfile limit")
    if int(max_output_tokens) > int(profile_limits["max_output_tokens"]):
        raise ValidationError("RunnerLaunchSpec output budget exceeds AgentProfile limit")
    if int(max_elapsed_minutes) > int(profile_limits["max_elapsed_minutes"]):
        raise ValidationError("RunnerLaunchSpec elapsed budget exceeds AgentProfile limit")
    if int(subtask_depth) > int(execution["max_subtask_depth"]):
        raise ValidationError("RunnerLaunchSpec subtask depth exceeds TaskPacket limit")

    profile_revision = f"{profile['profile_id']}@{profile['profile_revision']}"
    request = RunnerRequest(
        task_id=task_id,
        task_revision=task_revision,
        attempt_id=attempt_id,
        role=role,
        profile_revision=profile_revision,
        snapshot=snapshot,
        write_scope=tuple(write_scope),
        max_turns=int(max_turns),
    )
    request.validate()
    return RunnerLaunchSpec(
        task_packet=copy.deepcopy(dict(task_packet)),
        context_brief=copy.deepcopy(dict(context_brief)),
        profile=copy.deepcopy(dict(profile)),
        request=request,
        task_packet_ref=task_packet_ref,
        context_brief_ref=context_brief_ref,
        profile_ref=profile_ref,
        max_input_tokens=int(max_input_tokens),
        max_output_tokens=int(max_output_tokens),
        max_elapsed_minutes=int(max_elapsed_minutes),
        subtask_depth=int(subtask_depth),
    )


def build_launch_spec_from_payload(payload: Mapping[str, Any]) -> RunnerLaunchSpec:
    """Re-validate the structured payload at the external transport boundary."""
    if not isinstance(payload, Mapping):
        raise ValidationError("Runner launch payload must be a mapping")
    if int(payload.get("protocol_version", 0)) != 1:
        raise ValidationError("unsupported Runner launch protocol version")
    refs = payload.get("refs") or payload
    request = payload.get("request")
    budgets = payload.get("budgets")
    if not isinstance(refs, Mapping) or not isinstance(request, Mapping) or not isinstance(budgets, Mapping):
        raise ValidationError("Runner launch payload requires refs, request and budgets")
    task_packet = payload.get("task_packet")
    context_brief = payload.get("context_brief")
    profile = payload.get("profile")
    if not isinstance(task_packet, Mapping) or not isinstance(context_brief, Mapping) or not isinstance(profile, Mapping):
        raise ValidationError("Runner launch payload requires structured task inputs")
    try:
        return build_launch_spec(
            task_packet=task_packet,
            context_brief=context_brief,
            profile=profile,
            task_packet_ref=str(refs["task_packet_ref"]),
            context_brief_ref=str(refs["context_brief_ref"]),
            profile_ref=str(refs["profile_ref"]),
            attempt_id=str(request["attempt_id"]),
            write_scope=tuple(str(path) for path in request["write_scope"]),
            max_turns=int(budgets["max_turns"]),
            max_input_tokens=int(budgets["max_input_tokens"]),
            max_output_tokens=int(budgets["max_output_tokens"]),
            max_elapsed_minutes=int(budgets["max_elapsed_minutes"]),
            subtask_depth=int(budgets.get("subtask_depth", 0)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError("Runner launch payload has invalid structured fields") from exc


def build_verification_launch_spec(
    owner_spec: RunnerLaunchSpec,
    handoff: Any,
    *,
    test_profile: Mapping[str, Any],
    attempt_id: str,
    task_packet_ref: str,
    context_brief_ref: str,
    profile_ref: str,
    write_scope: tuple[str, ...],
    max_turns: int,
    max_input_tokens: int,
    max_output_tokens: int,
    max_elapsed_minutes: int,
) -> RunnerLaunchSpec:
    """Build the independent verifier launch at the owner's final snapshot."""
    final_snapshot = str(getattr(handoff, "final_snapshot", "")).strip()
    if not final_snapshot:
        raise ValidationError("verification launch requires the owner's final snapshot")
    packet = copy.deepcopy(dict(owner_spec.task_packet))
    workspace = dict(packet.get("workspace", {}))
    workspace["snapshot_kind"] = "git_commit"
    workspace["snapshot_ref"] = final_snapshot
    packet["workspace"] = workspace
    context = copy.deepcopy(dict(owner_spec.context_brief))
    context["context_snapshot"] = final_snapshot
    return build_launch_spec(
        task_packet=packet,
        context_brief=context,
        profile=copy.deepcopy(dict(test_profile)),
        task_packet_ref=task_packet_ref,
        context_brief_ref=context_brief_ref,
        profile_ref=profile_ref,
        attempt_id=attempt_id,
        write_scope=write_scope,
        max_turns=max_turns,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        max_elapsed_minutes=max_elapsed_minutes,
        subtask_depth=0,
    )
