"""RunnerExecution-backed adapter for the Phase 3 Scheduler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from .execution import RunnerExecution
from .scheduler import ExecutionBudget, ExecutionUpdate, ScheduledTask
from .scheduler import SchedulerError, SchedulerBackend


class RunnerExecutionBackendError(SchedulerError):
    """Raised when a RunnerExecution cannot satisfy Scheduler semantics."""


ExecutionFactory = Callable[[ScheduledTask, ExecutionBudget], RunnerExecution]
RebindExecutionFactory = Callable[[ScheduledTask, ExecutionBudget, str], RunnerExecution]
ResumeArtifactFactory = Callable[[ScheduledTask], tuple[str, ...]]


@dataclass
class _Binding:
    execution: RunnerExecution
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_seconds: float = 0.0
    model_turns: int = 1


class RunnerExecutionBackend(SchedulerBackend):
    """Translate one ``RunnerExecution`` per scheduled task.

    ``execution_factory`` is the only platform-specific seam.  A factory can
    construct an ``ExternalRunnerAdapter`` over ``CodexHostTransport`` and
    the concrete ``CodexCliBridge``; this class remains independent from the
    Codex CLI and is therefore deterministic in unit tests.
    """

    def __init__(
        self,
        execution_factory: ExecutionFactory,
        *,
        resume_artifact_factory: ResumeArtifactFactory | None = None,
        rebind_factory: RebindExecutionFactory | None = None,
    ) -> None:
        self.execution_factory = execution_factory
        self.resume_artifact_factory = resume_artifact_factory
        self.rebind_factory = rebind_factory
        self._bindings: dict[str, _Binding] = {}

    def start(self, task: ScheduledTask, budget: ExecutionBudget) -> str:
        if task.task_id in self._bindings:
            raise RunnerExecutionBackendError(f"task already has a Runner binding: {task.task_id}")
        execution = self.execution_factory(task, budget)
        if not isinstance(execution, RunnerExecution):
            raise RunnerExecutionBackendError("execution_factory must return RunnerExecution")
        self._validate_identity(task, execution)
        event = execution.open()
        if event.status != "running":
            raise RunnerExecutionBackendError(
                f"RunnerExecution opened in unexpected state: {event.status}"
            )
        if not event.runner_ref:
            raise RunnerExecutionBackendError("RunnerExecution opened without runner_ref")
        self._bindings[task.task_id] = _Binding(execution=execution)
        return event.runner_ref

    def rebind(self, task: ScheduledTask, handle: str) -> None:
        """Attach a persisted task to an already-open Runner handle.

        The factory must hydrate an existing host session and return an
        already-open ``RunnerExecution``.  It must not call ``open`` or create
        a new model task; otherwise restart recovery could duplicate work.
        """
        if task.task_id in self._bindings:
            raise RunnerExecutionBackendError(f"task already has a Runner binding: {task.task_id}")
        if self.rebind_factory is None:
            raise RunnerExecutionBackendError("rebind requires a persisted Runner binding factory")
        if task.budget is None or not handle.strip():
            raise RunnerExecutionBackendError("rebind requires task budget and handle")
        execution = self.rebind_factory(task, task.budget, handle)
        if not isinstance(execution, RunnerExecution):
            raise RunnerExecutionBackendError("rebind_factory must return RunnerExecution")
        self._validate_identity(task, execution)
        if execution.record.runner_ref != handle:
            raise RunnerExecutionBackendError("rebound Runner reference does not match Scheduler handle")
        if execution.record.status not in {"running", "interrupted"}:
            raise RunnerExecutionBackendError(
                f"rebound Runner is not active: {execution.record.status}"
            )
        self._bindings[task.task_id] = _Binding(
            execution=execution,
            input_tokens=execution.record.input_tokens,
            output_tokens=execution.record.output_tokens,
            elapsed_seconds=execution.record.elapsed_seconds,
            model_turns=execution.record.model_turns_used,
        )

    def poll(self, task: ScheduledTask) -> ExecutionUpdate:
        binding = self._binding(task)
        event = binding.execution.wait()
        status = event.status
        report_ref = event.report_ref
        reason = event.reason
        if status == "interrupted" and report_ref:
            event = binding.execution.close(report_ref)
            status = "completed"
            report_ref = event.report_ref or report_ref
        elif status == "interrupted":
            # An out-of-band interruption cannot be assumed to be a Scheduler
            # pause; stop and escalate rather than silently continue.
            status = "human_required"
            reason = reason or "Runner interrupted outside Scheduler control"
        elif status == "lost":
            status = "human_required"
            reason = reason or "Runner lost; explicit recovery decision required"
        elif status == "closed":
            status = "completed"
        elif status not in {"running", "blocked"}:
            raise RunnerExecutionBackendError(f"unsupported RunnerExecution status: {status}")

        input_delta = self._delta(
            current=event.input_tokens,
            previous=binding.input_tokens,
            label="input_tokens",
        )
        output_delta = self._delta(
            current=event.output_tokens,
            previous=binding.output_tokens,
            label="output_tokens",
        )
        elapsed_delta = self._delta_float(
            current=event.elapsed_seconds,
            previous=binding.elapsed_seconds,
            label="elapsed_seconds",
        )
        current_turns = binding.execution.record.model_turns_used
        turns_delta = self._delta(
            current=current_turns,
            previous=binding.model_turns,
            label="model_turns",
        )
        binding.input_tokens = event.input_tokens
        binding.output_tokens = event.output_tokens
        binding.elapsed_seconds = event.elapsed_seconds
        binding.model_turns = current_turns
        evidence_refs = (report_ref,) if report_ref else ()
        return ExecutionUpdate(
            status=status,
            input_tokens_delta=input_delta,
            output_tokens_delta=output_delta,
            model_turns_delta=turns_delta,
            elapsed_seconds_delta=elapsed_delta,
            report_ref=report_ref,
            final_snapshot=event.final_snapshot,
            evidence_refs=evidence_refs,
            reason=reason,
        )

    def pause(self, task: ScheduledTask, *, reason: str) -> None:
        binding = self._binding(task)
        event = binding.execution.interrupt(reason)
        if event.status != "interrupted":
            raise RunnerExecutionBackendError(
                f"RunnerExecution did not pause cleanly: {event.status}"
            )

    def resume(self, task: ScheduledTask) -> None:
        if self.resume_artifact_factory is None:
            raise RunnerExecutionBackendError(
                "resume requires a persisted artifact factory"
            )
        refs = self.resume_artifact_factory(task)
        if not refs or any(not str(ref).strip() for ref in refs):
            raise RunnerExecutionBackendError("resume artifact factory returned no references")
        binding = self._binding(task)
        event = binding.execution.resume(list(refs))
        if event.status != "running":
            raise RunnerExecutionBackendError(
                f"RunnerExecution did not resume cleanly: {event.status}"
            )

    def cancel(self, task: ScheduledTask, *, reason: str) -> None:
        binding = self._binding(task)
        if binding.execution.record.status == "running":
            event = binding.execution.interrupt(reason)
            if event.status not in {"interrupted", "lost", "blocked"}:
                raise RunnerExecutionBackendError(
                    f"RunnerExecution did not cancel cleanly: {event.status}"
                )

    def _binding(self, task: ScheduledTask) -> _Binding:
        try:
            return self._bindings[task.task_id]
        except KeyError as exc:
            raise RunnerExecutionBackendError(
                f"no Runner binding for scheduled task: {task.task_id}"
            ) from exc

    @staticmethod
    def _validate_identity(task: ScheduledTask, execution: RunnerExecution) -> None:
        request = execution.request
        if (
            request.task_id != task.task_id
            or request.task_revision != task.revision
            or request.role != task.owner
            or request.snapshot != str(task.packet["workspace"]["snapshot_ref"])
        ):
            raise RunnerExecutionBackendError("RunnerExecution identity does not match TaskPacket")

    @staticmethod
    def _delta(*, current: int, previous: int, label: str) -> int:
        if current < previous:
            raise RunnerExecutionBackendError(f"Runner {label} moved backwards")
        return int(current - previous)

    @staticmethod
    def _delta_float(*, current: float, previous: float, label: str) -> float:
        if current < previous:
            raise RunnerExecutionBackendError(f"Runner {label} moved backwards")
        return float(current - previous)


RoleExecutionFactories = Mapping[str, ExecutionFactory]
RoleRebindExecutionFactories = Mapping[str, RebindExecutionFactory]


class MultiRoleRunnerExecutionBackend(RunnerExecutionBackend):
    """Route each Scheduler owner to its explicitly registered Runner factory.

    A role factory may use the concrete local ``CodexCliBridge`` through the
    Host transport, while tests can inject deterministic Runner adapters.  No
    role silently falls back to another domain.
    """

    def __init__(
        self,
        role_factories: RoleExecutionFactories,
        *,
        role_rebind_factories: RoleRebindExecutionFactories | None = None,
        resume_artifact_factory: ResumeArtifactFactory | None = None,
    ) -> None:
        if not role_factories:
            raise RunnerExecutionBackendError("multi-role backend requires role factories")
        self.role_factories = dict(role_factories)
        self.role_rebind_factories = dict(role_rebind_factories or {})
        super().__init__(
            self._create_for_role,
            resume_artifact_factory=resume_artifact_factory,
            rebind_factory=self._rebind_for_role,
        )

    def _create_for_role(self, task: ScheduledTask, budget: ExecutionBudget) -> RunnerExecution:
        try:
            factory = self.role_factories[task.owner]
        except KeyError as exc:
            raise RunnerExecutionBackendError(
                f"no Runner factory registered for Scheduler owner: {task.owner}"
            ) from exc
        return factory(task, budget)

    def _rebind_for_role(
        self, task: ScheduledTask, budget: ExecutionBudget, handle: str
    ) -> RunnerExecution:
        try:
            factory = self.role_rebind_factories[task.owner]
        except KeyError as exc:
            raise RunnerExecutionBackendError(
                f"no Runner rebind factory registered for Scheduler owner: {task.owner}"
            ) from exc
        return factory(task, budget, handle)
