"""Config-backed production assembly for the persistent local control service.

The control protocol deliberately knows nothing about Codex.  This module is
the explicit assembly point which gives it a Scheduler, a rebindable CLI Host
backend, durable journals, and a verified ResumeDirective materializer.
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Any, Mapping

from .codex_bridge import parse_codex_runner_ref
from .codex_cli_bridge import CodexCliBridge
from .codex_host_transport import CodexHostTransport
from .control_protocol import ControlProtocolError, ControlRequest, ResumeDirectiveStore, SchedulerControl
from .execution import ExecutionJournal, RunnerExecution
from .external import ExternalRunnerAdapter
from .launch import RunnerLaunchSpec, build_launch_spec, build_launch_spec_from_payload
from .scheduler import ExecutionBudget, Scheduler, SchedulerLimits, ScheduledTask
from .scheduler_backend import MultiRoleRunnerExecutionBackend


class ControlRuntimeError(ValueError):
    """Raised when a local runtime config is incomplete or unsafe."""


class ControlRuntime:
    """One durable Scheduler/CLI Host assembly declared by a JSON config file."""

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path).resolve()
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ControlRuntimeError(f"cannot read runtime config: {self.config_path}") from exc
        if not isinstance(raw, Mapping) or raw.get("schema") != "agent-loop.control-runtime.v1":
            raise ControlRuntimeError("runtime config schema must be agent-loop.control-runtime.v1")
        self.config = dict(raw)
        self.project_id = self._text(raw.get("project_id"), "project_id")
        self.project_root = Path(self._text(raw.get("project_root"), "project_root")).resolve()
        if not self.project_root.is_dir() or not (self.project_root / ".git").exists():
            raise ControlRuntimeError("project_root must be a Git worktree")
        self.state_root = Path(self._text(raw.get("state_root"), "state_root")).resolve()
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.state_root / "scheduler.json"
        raw_specs = raw.get("launch_specs")
        if not isinstance(raw_specs, Mapping) or not raw_specs:
            raise ControlRuntimeError("runtime config requires launch_specs")
        self.specs: dict[str, RunnerLaunchSpec] = {}
        for task_id, payload in raw_specs.items():
            if not isinstance(payload, Mapping):
                raise ControlRuntimeError("each launch_spec must be a mapping")
            spec = build_launch_spec_from_payload(payload)
            if str(task_id) != spec.request.task_id:
                raise ControlRuntimeError("launch_specs key must match TaskPacket task_id")
            self.specs[spec.request.task_id] = spec
        host = raw.get("host")
        if not isinstance(host, Mapping):
            raise ControlRuntimeError("runtime config requires host settings")
        command = host.get("codex_command") or [shutil.which("codex") or "codex"]
        if not isinstance(command, list) or not command or any(not str(item).strip() for item in command):
            raise ControlRuntimeError("host.codex_command must be a non-empty list")
        self.bridge = CodexCliBridge(
            {self.project_id: self.project_root},
            codex_command=tuple(str(item) for item in command),
            worktree_root=Path(self._text(host.get("worktree_root"), "host.worktree_root")),
            artifact_root=Path(self._text(host.get("artifact_root"), "host.artifact_root")),
            session_registry_root=Path(self._text(host.get("session_registry_root"), "host.session_registry_root")),
            resume_directive_root=self.state_root / "control",
            model=self._optional_text(host.get("model")),
            model_reasoning_effort=self._optional_text(
                host.get("model_reasoning_effort", host.get("reasoning_effort"))
            ),
            startup_timeout=float(host.get("startup_timeout", 45)),
            stop_timeout=float(host.get("stop_timeout", 15)),
        )
        self.backend = MultiRoleRunnerExecutionBackend(
            {role: self._new_execution for role in {spec.request.role for spec in self.specs.values()}},
            role_rebind_factories={role: self._rebind_execution for role in {spec.request.role for spec in self.specs.values()}},
            resume_artifact_factory=self._resume_artifacts,
        )
        if self.state_path.is_file():
            self.scheduler = Scheduler.restore(self.state_path, self.backend)
        else:
            self.scheduler = Scheduler(self.backend, self._limits(raw.get("scheduler_limits")), state_path=self.state_path)
            preload = raw.get("preload_task_ids", [])
            if not isinstance(preload, list):
                raise ControlRuntimeError("preload_task_ids must be a list")
            for task_id in preload:
                spec = self.specs.get(str(task_id))
                if spec is None:
                    raise ControlRuntimeError("preload_task_ids references an unknown launch spec")
                self.scheduler.submit(spec.task_packet)

    def control(self) -> SchedulerControl:
        return SchedulerControl(
            self.scheduler,
            state_root=self.state_root / "control",
            submit_handler=self._submit_declared_launch_spec,
        )

    def _submit_declared_launch_spec(self, request: ControlRequest) -> Mapping[str, Any]:
        source = self.specs.get(request.task_id)
        if source is None:
            raise ControlProtocolError("submit requires a task_id declared in runtime launch_specs")
        revision = int(source.task_packet["revision"])
        if request.expected_revision is not None and request.expected_revision != revision:
            raise ControlProtocolError("expected_revision does not match the declared TaskPacket")
        if request.expected_runner_ref:
            raise ControlProtocolError("submit must not include a runner_ref")
        payload = dict(request.payload)
        allowed = {"task_packet_ref"}
        unexpected = sorted(set(payload) - allowed)
        if unexpected:
            raise ControlProtocolError("submit payload contains unsupported fields: " + ", ".join(unexpected))
        if payload.get("task_packet_ref") and str(payload["task_packet_ref"]) != source.task_packet_ref:
            raise ControlProtocolError("submit task_packet_ref does not match the declared LaunchSpec")
        self.scheduler.submit(source.task_packet)
        return {
            "task_packet_ref": source.task_packet_ref,
            "context_brief_ref": source.context_brief_ref,
            "profile_ref": source.profile_ref,
        }

    def _new_execution(self, task: ScheduledTask, budget: ExecutionBudget) -> RunnerExecution:
        spec = self._spec(task, budget)
        transport = CodexHostTransport(project_id=self.project_id, project_is_git=True, bridge=self.bridge)
        journal = ExecutionJournal.for_task(self.state_root / "journals", task.task_id, spec.request.attempt_id)
        return RunnerExecution(ExternalRunnerAdapter(spec, transport), spec.request, journal=journal, max_resumes=1)

    def _rebind_execution(self, task: ScheduledTask, budget: ExecutionBudget, _handle: str) -> RunnerExecution:
        spec = self._spec(task, budget)
        transport = CodexHostTransport(project_id=self.project_id, project_is_git=True, bridge=self.bridge)
        journal = ExecutionJournal.for_task(self.state_root / "journals", task.task_id, spec.request.attempt_id)
        return RunnerExecution.rebind(ExternalRunnerAdapter(spec, transport), spec.request, journal.load(), journal=journal, max_resumes=1)

    def _resume_artifacts(self, task: ScheduledTask) -> tuple[str, ...]:
        source = ResumeDirectiveStore(self.state_root / "control").latest_for(task)
        if not source or not task.handle:
            raise ControlRuntimeError("resume requires a persisted matching ResumeDirective")
        return (self.bridge.materialize_resume_directive(parse_codex_runner_ref(task.handle), source),)

    def _spec(self, task: ScheduledTask, budget: ExecutionBudget) -> RunnerLaunchSpec:
        source = self.specs.get(task.task_id)
        if source is None:
            raise ControlRuntimeError("Scheduler task has no declared launch spec")
        return build_launch_spec(
            task_packet=source.task_packet, context_brief=source.context_brief, profile=source.profile,
            task_packet_ref=source.task_packet_ref, context_brief_ref=source.context_brief_ref, profile_ref=source.profile_ref,
            attempt_id=source.request.attempt_id, write_scope=source.request.write_scope,
            max_turns=budget.max_model_turns, max_input_tokens=budget.max_input_tokens,
            max_output_tokens=budget.max_output_tokens,
            max_elapsed_minutes=max(1, int(math.ceil(budget.max_elapsed_seconds / 60))), subtask_depth=source.subtask_depth,
        )

    @staticmethod
    def _limits(value: Any) -> SchedulerLimits:
        if not isinstance(value, Mapping):
            raise ControlRuntimeError("runtime config requires scheduler_limits")
        try:
            return SchedulerLimits(**{key: int(value[key]) for key in (
                "max_concurrency", "max_tasks", "max_input_tokens", "max_output_tokens", "max_model_turns", "max_elapsed_minutes"
            )})
        except (KeyError, TypeError, ValueError) as exc:
            raise ControlRuntimeError("scheduler_limits are invalid") from exc

    @staticmethod
    def _text(value: Any, label: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ControlRuntimeError(f"runtime config requires {label}")
        return text

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


def build_control(config_path: str | Path) -> SchedulerControl:
    """Factory used by the service entry point after config validation."""
    return ControlRuntime(config_path).control()
