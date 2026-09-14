"""Build a bounded Codex project-task request.

The host application is responsible for calling the Codex task API.  This
module only validates project/snapshot identity and builds the request.  It
does not create a child task, read chat history, or choose a model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Mapping

from .errors import ValidationError
from .launch import RunnerLaunchSpec


class CodexBridgeError(ValidationError):
    """Raised when a Codex project-task request is unsafe to create."""


_SAFE_REF = re.compile(r"[A-Za-z0-9._/-]+")


def _require_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CodexBridgeError(f"{label} must not be empty")
    if "\n" in text or "\r" in text:
        raise CodexBridgeError(f"{label} must be single-line")
    return text


def _repo_ref(value: Any, label: str) -> str:
    ref = _require_text(value, label)
    if ref.startswith("-") or "\\" in ref or not _SAFE_REF.fullmatch(ref):
        raise CodexBridgeError(f"{label} is not a safe repository ref")
    if any(part == ".." for part in PurePosixPath(ref).parts):
        raise CodexBridgeError(f"{label} cannot contain parent traversal")
    return ref


def _relative_file_ref(value: Any, label: str) -> str:
    ref = _repo_ref(value, label)
    path = PurePosixPath(ref)
    if path.is_absolute() or not path.parts or any(part == ".." for part in path.parts):
        raise CodexBridgeError(f"{label} must be repository-relative")
    return ref


@dataclass(frozen=True)
class CodexThreadLaunch:
    """The complete host-side input for creating one project task."""

    project_id: str
    title: str
    prompt: str
    target: Mapping[str, Any]
    task_id: str
    task_revision: int
    attempt_id: str
    role: str
    profile_revision: str
    snapshot: str
    task_packet_ref: str
    context_brief_ref: str
    profile_ref: str
    write_scope: tuple[str, ...]
    max_turns: int
    max_input_tokens: int
    max_output_tokens: int
    max_elapsed_minutes: int
    subtask_depth: int
    structured_inputs: Mapping[str, Mapping[str, Any]]

    def to_payload(self) -> dict[str, Any]:
        """Return a create-task payload without transcript or model overrides."""
        return {
            "protocol_version": 1,
            "provider": "codex",
            "project_id": self.project_id,
            "target": dict(self.target),
            "title": self.title,
            "prompt": self.prompt,
            "task": {
                "task_id": self.task_id,
                "task_revision": self.task_revision,
                "attempt_id": self.attempt_id,
                "role": self.role,
                "profile_revision": self.profile_revision,
                "snapshot": self.snapshot,
                "write_scope": list(self.write_scope),
            },
            "refs": {
                "task_packet": self.task_packet_ref,
                "context_brief": self.context_brief_ref,
                "profile": self.profile_ref,
            },
            "budgets": {
                "max_turns": self.max_turns,
                "max_input_tokens": self.max_input_tokens,
                "max_output_tokens": self.max_output_tokens,
                "max_elapsed_minutes": self.max_elapsed_minutes,
                "subtask_depth": self.subtask_depth,
            },
            "spawn_policy": {"allow_child_tasks": False, "max_depth": 0},
            "structured_inputs": {
                name: dict(value) for name, value in self.structured_inputs.items()
            },
        }


@dataclass(frozen=True)
class CodexThreadHandle:
    """Stable identity returned by the host after creating a Codex task."""

    thread_id: str
    host_id: str | None = None

    @property
    def runner_ref(self) -> str:
        host = self.host_id or "local"
        return f"codex:{host}:{self.thread_id}"


def build_codex_thread_launch(
    spec: RunnerLaunchSpec,
    *,
    project_id: str,
    project_is_git: bool,
) -> CodexThreadLaunch:
    """Translate a validated LaunchSpec into a project-scoped Codex request.

    Real task creation requires a Git project and an explicit git snapshot.  A
    file-hash or arbitrary working-tree snapshot is rejected because the host
    task API cannot reproduce it safely in an isolated worktree.
    """
    project = _require_text(project_id, "project_id")
    if not project_is_git:
        raise CodexBridgeError("Codex child tasks require a Git project for isolation")

    workspace = spec.task_packet.get("workspace", {})
    if not isinstance(workspace, Mapping) or workspace.get("snapshot_kind") != "git_commit":
        raise CodexBridgeError("Codex child tasks require workspace.snapshot_kind=git_commit")
    snapshot = _repo_ref(spec.request.snapshot, "snapshot")

    task_packet_ref = _relative_file_ref(spec.task_packet_ref, "task_packet_ref")
    context_brief_ref = _relative_file_ref(spec.context_brief_ref, "context_brief_ref")
    profile_ref = _relative_file_ref(spec.profile_ref, "profile_ref")
    title = _require_text(
        spec.task_packet.get("title") or f"{spec.request.role} {spec.request.task_id}",
        "task title",
    )[:120]
    if not title:
        raise CodexBridgeError("task title must not be empty")

    instructions = [
        f"Act as the {spec.request.role} Agent for task {spec.request.task_id}.",
        f"Work only on attempt {spec.request.attempt_id} at snapshot {snapshot}.",
        "Read the structured task files before editing:",
        f"- TaskPacket: {task_packet_ref}",
        f"- ContextBrief: {context_brief_ref}",
        f"- AgentProfile: {profile_ref}",
        "Obey AGENTS.md, the declared write scope, and the relevant Skill.",
        "Do not read or request the parent chat transcript.",
        "Return only one JSON object as the final response; do not wrap it in Markdown.",
    ]
    if spec.request.role == "test-verification":
        instructions.extend(
            [
                "Do not create child tasks. Return a structured TestReport or blockage report.",
                "For a TestReport, use these exact top-level fields: task_id, packet_revision, tested_snapshot, tester, overall, results, environment, failures, manual_checks, changed_test_paths.",
                f"Set tested_snapshot exactly to {snapshot}; set tester exactly to test-verification.",
                "Each results item must use the exact full command string from TaskPacket.acceptance.verification_commands; never abbreviate it with ellipses and do not use a commands field.",
                "Each results item must include command, cwd, status, exit_code, and evidence_ref. For a non-Docker host run, environment.runner is host-diagnostic, missing_dependencies is [], and environment.docker.used is false.",
                "Use failures as a list (empty for PASS), manual_checks as a list, and changed_test_paths as a list. Do not substitute final_snapshot for tested_snapshot.",
            ]
        )
    else:
        instructions.append("Do not create child tasks. Return a structured ChangeReport or blockage report.")
    prompt = "\n".join(instructions)
    target = {
        "type": "project",
        "projectId": project,
        "environment": {
            "type": "worktree",
            "startingState": {"type": "branch", "branchName": snapshot},
        },
    }
    return CodexThreadLaunch(
        project_id=project,
        title=title,
        prompt=prompt,
        target=target,
        task_id=spec.request.task_id,
        task_revision=spec.request.task_revision,
        attempt_id=spec.request.attempt_id,
        role=spec.request.role,
        profile_revision=spec.request.profile_revision,
        snapshot=snapshot,
        task_packet_ref=task_packet_ref,
        context_brief_ref=context_brief_ref,
        profile_ref=profile_ref,
        write_scope=spec.request.write_scope,
        max_turns=spec.request.max_turns,
        max_input_tokens=spec.max_input_tokens,
        max_output_tokens=spec.max_output_tokens,
        max_elapsed_minutes=spec.max_elapsed_minutes,
        subtask_depth=spec.subtask_depth,
        structured_inputs={
            "task_packet": dict(spec.task_packet),
            "context_brief": dict(spec.context_brief),
            "profile": dict(spec.profile),
        },
    )


def parse_codex_thread_handle(payload: Mapping[str, Any]) -> CodexThreadHandle:
    """Parse the minimal create-task result returned by a host bridge."""
    if not isinstance(payload, Mapping):
        raise CodexBridgeError("Codex create-task response must be a mapping")
    thread_id = _require_text(
        payload.get("thread_id") or payload.get("threadId"), "thread_id"
    )
    host_value = payload.get("host_id") or payload.get("hostId")
    host_id = _require_text(host_value, "host_id") if host_value else None
    for value, label in ((thread_id, "thread_id"), (host_id, "host_id")):
        if value and ("\n" in value or "\r" in value or len(value) > 256):
            raise CodexBridgeError(f"{label} is invalid")
    return CodexThreadHandle(thread_id=thread_id, host_id=host_id)


def parse_codex_runner_ref(runner_ref: str) -> CodexThreadHandle:
    """Parse the durable ``codex:<host_id>:<thread_id>`` identity."""
    value = _require_text(runner_ref, "runner_ref")
    prefix, separator, remainder = value.partition(":")
    if prefix != "codex" or not separator:
        raise CodexBridgeError("runner_ref must use the codex:<host>:<thread> format")
    host_id, separator, thread_id = remainder.partition(":")
    if not separator or not host_id or not thread_id:
        raise CodexBridgeError("runner_ref must include host_id and thread_id")
    return parse_codex_thread_handle({"thread_id": thread_id, "host_id": host_id})
