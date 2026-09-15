"""Bounded single-domain Owner -> Test/Verification orchestration."""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .errors import ValidationError
from .execution import ExecutionRecord, RunnerExecution
from .handoff import HandoffEnvelope, build_handoff
from .launch import RunnerLaunchSpec
from .manifest import validate_run_manifest
from .report_validation import validate_test_report
from .retry_learning import summarize_retry_learning
from .runner import RunnerEvent
from .verification import VerificationPlan, build_verification_plan


class BoundedLoopError(ValidationError):
    """Raised when the bounded loop cannot produce an auditable result."""


@dataclass(frozen=True)
class BoundedLoopResult:
    owner_event: RunnerEvent
    owner_record: ExecutionRecord
    handoff: HandoffEnvelope
    verification_plan: VerificationPlan
    verifier_event: RunnerEvent
    verifier_record: ExecutionRecord
    test_report: Mapping[str, Any]
    manifest: Mapping[str, Any]


class SingleDomainLoop:
    """Run exactly one Owner and one independent Test/Verification attempt."""

    def __init__(
        self,
        *,
        owner_spec: RunnerLaunchSpec,
        owner_execution: RunnerExecution,
        test_profile: Mapping[str, Any],
        test_matrix: Mapping[str, Any],
        verification_attempt_id: str,
        command_ids: tuple[str, ...],
        docker_enabled: bool,
        verification_scope: tuple[str, ...],
        changed_paths: tuple[str, ...] = (),
        report_loader: Callable[[str], Mapping[str, Any] | str] | None = None,
        manifest_path: str | Path | None = None,
        human_approved: bool = False,
        max_wait_seconds: float = 180.0,
        poll_interval_seconds: float = 0.25,
        verifier_spec: RunnerLaunchSpec | None = None,
        verifier_execution: RunnerExecution | None = None,
        verifier_factory: Callable[[HandoffEnvelope, VerificationPlan], tuple[RunnerLaunchSpec, RunnerExecution]] | None = None,
    ) -> None:
        self.owner_spec = owner_spec
        self.verifier_spec = verifier_spec
        self.owner_execution = owner_execution
        self.verifier_execution = verifier_execution
        self.verifier_factory = verifier_factory
        self.test_profile = test_profile
        self.test_matrix = test_matrix
        self.verification_attempt_id = verification_attempt_id
        self.command_ids = command_ids
        self.docker_enabled = docker_enabled
        self.verification_scope = verification_scope
        self.changed_paths = changed_paths
        self.report_loader = report_loader
        self.manifest_path = Path(manifest_path) if manifest_path else None
        self.human_approved = human_approved
        self.max_wait_seconds = float(max_wait_seconds)
        self.poll_interval_seconds = float(poll_interval_seconds)
        if self.max_wait_seconds <= 0 or self.poll_interval_seconds <= 0:
            raise BoundedLoopError("loop wait bounds must be positive")

    def run(self) -> BoundedLoopResult:
        if self.owner_spec.request.role not in {"product", "core", "trainer", "teacher"}:
            raise BoundedLoopError("single-domain loop requires a domain Owner")
        if self.verifier_spec is not None and self.verifier_spec.request.role != "test-verification":
            raise BoundedLoopError("single-domain loop requires an independent Test/Verification spec")

        owner_event = self._complete(self.owner_execution, "Owner")
        owner_changes = self.changed_paths or tuple(self.owner_execution.record.changed_paths)
        handoff = build_handoff(
            self.owner_spec,
            self.owner_execution.record,
            to_role="test-verification",
            changed_paths=owner_changes,
            verification_scope=self.verification_scope,
        )
        plan = build_verification_plan(
            handoff,
            test_profile=self.test_profile,
            test_matrix=self.test_matrix,
            verification_attempt_id=self.verification_attempt_id,
            command_ids=self.command_ids,
            docker_enabled=self.docker_enabled,
        )
        if self.verifier_spec is None or self.verifier_execution is None:
            if self.verifier_factory is None:
                raise BoundedLoopError("a verifier spec or verifier factory is required")
            self.verifier_spec, self.verifier_execution = self.verifier_factory(handoff, plan)
        assert self.verifier_spec is not None
        assert self.verifier_execution is not None
        if self.verifier_spec.request.task_id != plan.task_id:
            raise BoundedLoopError("verifier TaskPacket identity does not match Owner handoff")
        if self.verifier_spec.request.task_revision != plan.task_revision:
            raise BoundedLoopError("verifier packet revision does not match Owner handoff")
        if self.verifier_spec.request.snapshot != plan.snapshot:
            raise BoundedLoopError("verifier must start at the Owner final snapshot")

        verifier_event = self._complete(self.verifier_execution, "Test/Verification")
        if not verifier_event.report_ref or self.report_loader is None:
            raise BoundedLoopError("Test/Verification must return a readable TestReport")
        test_report = self._load_report(verifier_event.report_ref)
        validate_test_report(test_report, plan=plan)
        if str(test_report.get("overall")) != "PASS":
            raise BoundedLoopError("first-stage loop stops unless TestReport overall is PASS")
        manifest = self._manifest(handoff, plan, test_report)
        if self.manifest_path:
            manifest = self._write_manifest(manifest, handoff)
        return BoundedLoopResult(
            owner_event=owner_event,
            owner_record=self.owner_execution.record,
            handoff=handoff,
            verification_plan=plan,
            verifier_event=verifier_event,
            verifier_record=self.verifier_execution.record,
            test_report=test_report,
            manifest=manifest,
        )

    def _complete(self, execution: RunnerExecution, label: str) -> RunnerEvent:
        if execution.record.status == "closed":
            if execution.last_event is None:
                raise BoundedLoopError(f"{label} Runner is closed without a final event")
            return execution.last_event
        event = execution.open()
        deadline = time.monotonic() + self.max_wait_seconds
        while time.monotonic() <= deadline:
            if event.status == "running":
                time.sleep(min(self.poll_interval_seconds, max(0.0, deadline - time.monotonic())))
                event = execution.wait()
                continue
            if event.status == "interrupted" and event.report_ref:
                return execution.close(event.report_ref)
            if event.status == "closed":
                return event
            raise BoundedLoopError(
                f"{label} Runner stopped in {event.status} without a report"
            )
        raise BoundedLoopError(f"{label} Runner exceeded the bounded wait time")

    def _load_report(self, report_ref: str) -> Mapping[str, Any]:
        raw = self.report_loader(report_ref)  # type: ignore[misc]
        if isinstance(raw, str):
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise BoundedLoopError("TestReport must be JSON at the host boundary") from exc
        else:
            value = raw
        if not isinstance(value, Mapping):
            raise BoundedLoopError("TestReport must be a mapping")
        return value

    def _manifest(
        self,
        handoff: HandoffEnvelope,
        plan: VerificationPlan,
        test_report: Mapping[str, Any],
    ) -> dict[str, Any]:
        execution = self.owner_spec.task_packet["execution"]
        final_snapshot = self.verifier_execution.record.final_snapshot or plan.snapshot
        input_tokens_used = (
            self.owner_execution.record.input_tokens
            + self.verifier_execution.record.input_tokens
        )
        output_tokens_used = (
            self.owner_execution.record.output_tokens
            + self.verifier_execution.record.output_tokens
        )
        elapsed_seconds_used = (
            self.owner_execution.record.elapsed_seconds
            + self.verifier_execution.record.elapsed_seconds
        )
        budget_limits = {
            "role_runs_used": int(execution["max_role_runs"]),
            "subtasks_used": int(execution["max_subtasks"]),
            "input_tokens_used": int(execution["max_model_input_tokens"]),
            "output_tokens_used": int(execution["max_model_output_tokens"]),
            "model_turns_used": int(execution["max_model_turns"]),
            "elapsed_minutes": int(execution["max_elapsed_minutes"]),
        }
        budget_used = {
            "role_runs_used": 2,
            "subtasks_used": 1,
            "input_tokens_used": input_tokens_used,
            "output_tokens_used": output_tokens_used,
            "model_turns_used": self.owner_execution.record.model_turns_used
            + self.verifier_execution.record.model_turns_used,
            "elapsed_minutes": int(math.ceil(elapsed_seconds_used / 60.0)),
        }
        exhausted_limits = [
            used
            for used, value in budget_used.items()
            if int(value) > int(budget_limits[used])
        ]
        manifest_status = "completed" if self.human_approved and not exhausted_limits else "human_required"
        artifacts = [
            self._artifact(
                self.owner_execution.record.report_ref,
                "change_report",
                self.owner_execution.record.identity.attempt_id,
                handoff.final_snapshot,
            ),
            self._artifact(
                self.verifier_execution.record.report_ref,
                "test_report",
                self.verifier_execution.record.identity.attempt_id,
                final_snapshot,
            ),
        ]
        role_runs = [
            self.owner_execution.record.to_manifest_role_run(),
            self.verifier_execution.record.to_manifest_role_run(),
        ]
        manifest = {
            "protocol_version": 1,
            "run_id": handoff.task_id,
            "task_id": handoff.task_id,
            "task_revision": handoff.task_revision,
            "runner": "codex",
            "status": manifest_status,
            "created_at": "",
            "updated_at": "",
            "workspace": {
                "base_snapshot_kind": "git_commit",
                "base_snapshot": handoff.snapshot,
                "final_snapshot": final_snapshot,
                "known_user_changes": [],
                "write_scope_refs": list(self.owner_spec.request.write_scope),
            },
            "budget": {
                "max_role_runs": budget_limits["role_runs_used"],
                "max_subtasks": budget_limits["subtasks_used"],
                "max_subtask_depth": int(execution["max_subtask_depth"]),
                "max_input_tokens": budget_limits["input_tokens_used"],
                "max_output_tokens": budget_limits["output_tokens_used"],
                "max_model_turns": budget_limits["model_turns_used"],
                "max_elapsed_minutes": budget_limits["elapsed_minutes"],
                **budget_used,
                "exhausted_limits": exhausted_limits,
                "elapsed_seconds_used": elapsed_seconds_used,
                "exhaustion_action": "transition_to_human_required_and_stop_new_runs",
            },
            "role_runs": role_runs,
            "artifacts": artifacts,
            "retry_learning": summarize_retry_learning(role_runs),
            "state_events": self._state_events(handoff.task_revision),
            "gates": self._gates(plan),
            "termination": {
                "completion_claim": "one Owner and one independent Test/Verification task passed",
                "final_report_ref": str(self.verifier_execution.record.report_ref or ""),
                "unresolved_blockers": (
                    []
                    if self.human_approved and not exhausted_limits
                    else (
                        ["budget exhausted: " + ", ".join(exhausted_limits)]
                        if exhausted_limits
                        else ["human gate approval required"]
                    )
                ),
                "recovery_point": "",
                "cleanup": "complete",
            },
        }
        validate_run_manifest(manifest)
        return manifest

    def _write_manifest(self, manifest: Mapping[str, Any], handoff: HandoffEnvelope) -> Mapping[str, Any]:
        assert self.manifest_path is not None
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        handoff_path = self.manifest_path.with_name(self.manifest_path.stem + ".handoff.json")
        handoff_path.write_text(json.dumps(handoff.to_payload(), indent=2) + "\n", encoding="utf-8")
        updated = json.loads(json.dumps(manifest))
        updated["artifacts"].append(
            self._artifact(str(handoff_path), "handoff", handoff.attempt_id, handoff.final_snapshot)
        )
        validate_run_manifest(updated)
        self.manifest_path.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
        return updated

    def _artifact(
        self,
        report_ref: str | None,
        kind: str,
        producer_attempt_id: str,
        snapshot: str,
    ) -> dict[str, Any]:
        ref = str(report_ref or "").strip()
        if not ref:
            raise BoundedLoopError(f"{kind} reference is missing")
        path = Path(ref)
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else hashlib.sha256(ref.encode()).hexdigest()
        return {
            "artifact_id": f"{producer_attempt_id}-{kind}",
            "kind": kind,
            "path": ref,
            "producer_attempt_id": producer_attempt_id,
            "snapshot": snapshot,
            "sha256": digest,
            "redaction_status": "not_required",
            "retention": "project_record",
        }

    @staticmethod
    def _state_events(task_revision: int) -> list[dict[str, Any]]:
        states = [
            ("RECEIVED", "TRIAGED"),
            ("TRIAGED", "CONTEXTUALIZED"),
            ("CONTEXTUALIZED", "PLANNED"),
            ("PLANNED", "ASSIGNED"),
            ("ASSIGNED", "IMPLEMENTING"),
            ("IMPLEMENTING", "REVIEWING"),
            ("REVIEWING", "TESTING"),
            ("TESTING", "COMPLETED"),
        ]
        return [
            {
                "event_seq": index,
                "event_id": f"loop-{index}",
                "at": "",
                "from_status": source,
                "to_status": target,
                "actor": "main",
                "reason": "bounded single-domain loop",
                "evidence_refs": [],
                "task_revision": task_revision,
            }
            for index, (source, target) in enumerate(states, start=1)
        ]

    def _gates(self, plan: VerificationPlan) -> list[dict[str, Any]]:
        gates = [
            {"gate_id": "scope", "kind": "scope", "status": "passed", "evidence_refs": [], "decided_by": "main", "decided_at": ""},
            {"gate_id": "contract", "kind": "contract", "status": "passed", "evidence_refs": [], "decided_by": "main", "decided_at": ""},
            {"gate_id": "test", "kind": "test", "status": "passed", "evidence_refs": [], "decided_by": "test-verification", "decided_at": ""},
        ]
        if plan.docker_enabled:
            gates.append({"gate_id": "docker", "kind": "docker", "status": "passed", "evidence_refs": [], "decided_by": "test-verification", "decided_at": ""})
        gates.append({
            "gate_id": "human",
            "kind": "human",
            "status": "passed" if self.human_approved else "pending",
            "evidence_refs": [],
            "decided_by": "user" if self.human_approved else "",
            "decided_at": "",
        })
        return gates
