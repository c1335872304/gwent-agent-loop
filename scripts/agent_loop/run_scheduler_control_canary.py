"""Run a live Scheduler-control Owner -> Test canary.

The canary proves the main-control entry can submit and inspect one declared
Product task, deliver a post-start user supplement through ``loop_update``,
and resume the same Runner through the local Scheduler control service.  It
then launches an independent Test Agent from the Owner final snapshot and
writes a RunManifest.

It intentionally writes only a static marker in ``apps/web/frontend/index.html``
inside Codex-managed child worktrees.  The caller's parent worktree is not
modified by the Owner/Test tasks.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.agent_loop.codex_bridge import parse_codex_runner_ref
    from scripts.agent_loop.codex_host_transport import CodexHostTransport
    from scripts.agent_loop.control_runtime import ControlRuntime
    from scripts.agent_loop.control_service import (
        SchedulerControlService,
        create_capability_token,
        read_capability_token,
    )
    from scripts.agent_loop.execution import ExecutionJournal, RunnerExecution
    from scripts.agent_loop.external import ExternalRunnerAdapter
    from scripts.agent_loop.handoff import build_handoff
    from scripts.agent_loop.launch import build_launch_spec, build_verification_launch_spec
    from scripts.agent_loop.manifest import validate_run_manifest
    from scripts.agent_loop.report_validation import validate_test_report
    from scripts.agent_loop.retry_learning import summarize_retry_learning
    from scripts.agent_loop.runner import RunnerEvent
    from scripts.agent_loop.validate_packet import load_yaml
    from scripts.agent_loop.verification import build_verification_plan
else:
    from .codex_bridge import parse_codex_runner_ref
    from .codex_host_transport import CodexHostTransport
    from .control_runtime import ControlRuntime
    from .control_service import (
        SchedulerControlService,
        create_capability_token,
        read_capability_token,
    )
    from .execution import ExecutionJournal, RunnerExecution
    from .external import ExternalRunnerAdapter
    from .handoff import build_handoff
    from .launch import build_launch_spec, build_verification_launch_spec
    from .manifest import validate_run_manifest
    from .report_validation import validate_test_report
    from .retry_learning import summarize_retry_learning
    from .runner import RunnerEvent
    from .validate_packet import load_yaml
    from .verification import build_verification_plan


TASK_ID = "GW-SCHED-CTRL-001"
OWNER_ATTEMPT_ID = "owner-control-001"
TEST_ATTEMPT_ID = "test-control-001"
COMMAND_ID = "product-static-html-canary"
CANARY_MARKER = 'data-agent-loop-canary="GW-SCHED-CTRL-001"'
CANARY_ATTRIBUTE = "data-agent-loop-canary"
CANARY_SUPPLEMENT_VALUE = "from-main"


class McpControlClient:
    """Minimal stdio client used only to prove the registered control boundary.

    The Scheduler service remains the sole state writer.  This client speaks
    the public MCP adapter protocol, rather than importing the adapter and
    bypassing its JSON-RPC schema checks in the field canary.
    """

    def __init__(self, *, root: Path, socket_path: Path, token_file: Path) -> None:
        self._process = subprocess.Popen(
            [
                sys.executable,
                str(root / "scripts/agent_loop/control_mcp_server.py"),
                "--socket",
                str(socket_path),
                "--token-file",
                str(token_file),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._request_id = 0
        response = self._request(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "scheduler-control-canary", "version": "1"},
            },
        )
        if "error" in response:
            raise RuntimeError(f"MCP initialize failed: {response['error']}")
        tools = self._request("tools/list", {})
        names = {item.get("name") for item in tools.get("result", {}).get("tools", [])}
        expected = {
            "loop_inspect",
            "loop_submit",
            "loop_update",
            "loop_pause",
            "loop_prepare_resume",
            "loop_resume",
            "loop_cancel",
        }
        if names != expected:
            raise RuntimeError(f"MCP control tool catalog mismatch: {sorted(names)}")

    def close(self) -> None:
        if self._process.stdin is not None:
            self._process.stdin.close()
        try:
            self._process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._process.terminate()
            self._process.wait(timeout=3)

    def call(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        response = self._request("tools/call", {"name": name, "arguments": dict(arguments)})
        if "error" in response:
            raise RuntimeError(f"MCP {name} failed: {response['error']}")
        result = response.get("result", {})
        content = result.get("content", [])
        if not content or not isinstance(content[0], Mapping):
            raise RuntimeError(f"MCP {name} returned no control response")
        try:
            control_response = json.loads(str(content[0].get("text") or ""))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"MCP {name} returned invalid control JSON") from exc
        if result.get("isError") or control_response.get("status") != "OK":
            raise RuntimeError(f"MCP {name} rejected control action: {control_response}")
        return control_response

    def _request(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        if self._process.stdin is None or self._process.stdout is None:
            raise RuntimeError("MCP control client pipes are unavailable")
        self._request_id += 1
        self._process.stdin.write(
            json.dumps(
                {"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": dict(params)},
                ensure_ascii=True,
            )
            + "\n"
        )
        self._process.stdin.flush()
        line = self._process.stdout.readline()
        if not line:
            stderr = self._process.stderr.read() if self._process.stderr is not None else ""
            raise RuntimeError(f"MCP control server stopped before responding: {stderr.strip()}")
        response = json.loads(line)
        if not isinstance(response, Mapping):
            raise RuntimeError("MCP control server returned a non-object response")
        return dict(response)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _git_head(root: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _sha256(path: str | Path) -> str:
    target = Path(path)
    return hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else hashlib.sha256(str(path).encode()).hexdigest()


def _artifact(ref: str | None, *, kind: str, attempt_id: str, snapshot: str) -> dict[str, Any]:
    if not ref:
        raise RuntimeError(f"missing {kind} artifact ref")
    return {
        "artifact_id": f"{attempt_id}-{kind}",
        "kind": kind,
        "path": str(ref),
        "producer_attempt_id": attempt_id,
        "snapshot": snapshot,
        "sha256": _sha256(ref),
        "redaction_status": "not_required",
        "retention": "project_record",
    }


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
            "event_id": f"control-canary-{index}",
            "at": "",
            "from_status": source,
            "to_status": target,
            "actor": "main_control",
            "reason": "scheduler control canary",
            "evidence_refs": [],
            "task_revision": task_revision,
        }
        for index, (source, target) in enumerate(states, start=1)
    ]


def _load_product_command(test_matrix: Mapping[str, Any]) -> str:
    for domain in test_matrix["domains"]:
        if domain["domain"] != "product":
            continue
        for command in domain["commands"]:
            if command["id"] == COMMAND_ID:
                return str(command["command"])
    raise RuntimeError(f"TEST_MATRIX is missing {COMMAND_ID}")


def _packet(snapshot: str, *, task_root: str, verification_command: str) -> dict[str, Any]:
    return {
        "protocol_version": 1,
        "task_id": TASK_ID,
        "revision": 1,
        "title": "Scheduler control canary: static Product marker",
        "requested_outcome": (
            "In apps/web/frontend/index.html, add a static "
            f"{CANARY_ATTRIBUTE!r} attribute to the existing root div and change no other file. "
            "Its value will be supplied after the task starts; wait for that clarification."
        ),
        "non_goals": [
            "Do not change React source, backend code, Core contracts, Teacher behavior, package files, or tests.",
            "Do not run Docker or install dependencies.",
        ],
        "authority": {
            "user_request_ref": "current conversation: continue推进",
            "repo_rules": ["AGENTS.md"],
            "required_skills": ["product-integration"],
        },
        "ownership": {
            "primary_owner": "product",
            "consulted_owners": [],
            "handoff_required_before_completion": False,
        },
        "scope": {
            "allowed_write_paths": ["apps/web/frontend/index.html"],
            "allowed_test_write_paths": ["declared test scope only"],
            "forbidden_paths": [
                "apps/web/frontend/src",
                "apps/web/backend",
                "services/teacher",
                "src",
                "include",
                "models",
                "runs",
                "artifacts",
            ],
            "declared_contracts": [
                "Core HTTP contract: unchanged",
                "Teacher evidence/privacy contract: unchanged",
                "Product runtime behavior: unchanged",
            ],
        },
        "workspace": {
            "snapshot_kind": "git_commit",
            "snapshot_ref": snapshot,
            "known_user_changes": [],
        },
        "inputs": {
            "context_brief_ref": f"{task_root}/context-brief.json",
            "context_policy_ref": "docs/current/agent-loop/CONTEXT_INDEX.yaml#context_policy",
            "context_floor_refs": [
                "AGENTS.md",
                "docs/current/AGENT_ONBOARDING_INDEX.md",
                "docs/current/agent-loop/START_HERE.md",
                ".agents/skills/product-integration/SKILL.md",
            ],
            "canonical_files": [
                {"path": "apps/web/frontend/index.html", "reason": "only allowed production file"},
                {"path": ".agents/skills/product-integration/SKILL.md", "reason": "Product boundary"},
            ],
            "external_inputs": [],
        },
        "acceptance": {
            "behavioral": [
                f"`apps/web/frontend/index.html` root div contains `{CANARY_ATTRIBUTE}` with the value supplied after task start.",
                "No other path changes in the Owner final snapshot.",
            ],
            "verification_commands": [verification_command],
            "manual_checks": ["Check changed paths are exactly apps/web/frontend/index.html."],
        },
        "risks": [{"type": "operational", "mitigation": "static HTML-only marker can be reverted by discarding the child worktree"}],
        "execution": {
            "write_lock_keys": ["apps/web/frontend/index.html"],
            "max_owner_attempts": 2,
            "max_elapsed_minutes": 45,
            "max_parallel_readers": 1,
            "max_role_runs": 4,
            "max_subtasks": 1,
            "max_subtask_depth": 1,
            "max_model_input_tokens": 1000000,
            "max_model_output_tokens": 32000,
            "max_model_turns": 8,
        },
        "gates": ["independent TestReport PASS", "RunManifest validated"],
        "artifacts": {"task_root": task_root},
    }


def _context(snapshot: str) -> dict[str, Any]:
    return {
        "task_id": TASK_ID,
        "packet_revision": 1,
        "context_snapshot": snapshot,
        "prepared_by": "planner",
        "context_policy_ref": "docs/current/agent-loop/CONTEXT_INDEX.yaml#context_policy",
        "assembly": {
            "included_refs": [
                "AGENTS.md",
                "docs/current/agent-loop/START_HERE.md",
                ".agents/skills/product-integration/SKILL.md",
                "apps/web/frontend/index.html",
            ],
            "excluded_refs": ["raw conversation", "historical archives", "models/v3/policy.pt"],
            "authority_conflicts": [],
        },
        "problem_model": {
            "current_behavior": "Scheduler control entry lacks one live Owner/Test canary.",
            "expected_behavior": "Main control can submit an Owner, deliver a post-start clarification through loop_update, and run independent Test.",
            "user_visible_impact": "Proves control entry without modifying parent worktree.",
            "hypotheses": [
                {
                    "statement": "A static Product attribute is enough to exercise post-start update delivery and independent Test boundaries.",
                    "status": "inferred",
                    "evidence_ref": "docs/current/agent-loop/SCHEDULER_CONTROL_ENTRY_PLAN.md",
                }
            ],
        },
        "context_floor_refs": [
            {"path": "AGENTS.md", "role": "repository governance", "snapshot_or_version": snapshot},
            {"path": ".agents/skills/product-integration/SKILL.md", "role": "required skill", "snapshot_or_version": snapshot},
        ],
        "fact_source_graph": [
            {"path": "apps/web/frontend/index.html", "category": "production", "why_relevant": "only changed file", "read_status": "required"},
            {"path": "docs/current/agent-loop/TEST_MATRIX.yaml", "category": "test", "why_relevant": "verification command id", "read_status": "required"},
        ],
        "exploration": {"allowed_neighbor_roots": ["apps/web/frontend"], "search_terms": ["root div", "index.html"], "questions_to_resolve": []},
        "fact_ledger": [
            {"fact": "The task is static HTML-only and does not change contracts.", "status": "confirmed", "source_ref": "TaskPacket.scope.declared_contracts", "snapshot": snapshot}
        ],
        "excluded_leads": [{"lead": "Frontend npm build", "evidence": "Current WSL Node environment is not reliable for this control canary."}],
        "lessons": {"relevant_refs": [], "searched_trigger_terms": ["scheduler control", "product static canary"], "applied": [], "rejected_as_stale_or_irrelevant": []},
        "advisory": {
            "enabled": False,
            "status": "empty",
            "source_report_ref": "ShadowRetrieval.yaml",
            "items": [],
            "omitted": [],
            "limits": {"max_items": 3, "max_tokens": 1500, "used_items": 0, "used_tokens": 0},
            "adoption": {"status": "not_recorded", "adopted_lesson_ids": [], "not_adopted_lesson_ids": [], "evidence_ref": ""},
        },
        "contradictions_or_blockers": [],
    }


def _complete_execution(execution: RunnerExecution, *, label: str, timeout_seconds: float) -> Any:
    event = execution.open()
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() <= deadline:
        if event.status == "running":
            time.sleep(0.5)
            event = execution.wait()
            continue
        if event.status == "interrupted" and event.report_ref:
            return execution.close(event.report_ref)
        if event.status == "closed":
            return event
        raise RuntimeError(f"{label} stopped in {event.status}: {event.reason}")
    raise RuntimeError(f"{label} exceeded bounded wait")


def _manifest(
    *,
    task_id: str,
    revision: int,
    base_snapshot: str,
    final_snapshot: str,
    owner_record: Any,
    verifier_record: Any,
    test_report_ref: str,
    test_report: Mapping[str, Any],
    resume_directive_ref: str,
    state_events: list[dict[str, Any]],
    manifest_path: Path,
) -> dict[str, Any]:
    input_tokens = owner_record.input_tokens + verifier_record.input_tokens
    output_tokens = owner_record.output_tokens + verifier_record.output_tokens
    turns = owner_record.model_turns_used + verifier_record.model_turns_used
    elapsed_seconds = owner_record.elapsed_seconds + verifier_record.elapsed_seconds
    role_runs = [owner_record.to_manifest_role_run(), verifier_record.to_manifest_role_run()]
    manifest = {
        "protocol_version": 1,
        "run_id": task_id,
        "task_id": task_id,
        "task_revision": revision,
        "runner": "codex",
        "status": "completed",
        "created_at": _now(),
        "updated_at": _now(),
        "workspace": {
            "base_snapshot_kind": "git_commit",
            "base_snapshot": base_snapshot,
            "final_snapshot": final_snapshot,
            "known_user_changes": [],
            "write_scope_refs": ["apps/web/frontend/index.html"],
        },
        "budget": {
            "max_role_runs": 4,
            "max_subtasks": 1,
            "max_subtask_depth": 1,
            "max_input_tokens": 1000000,
            "max_output_tokens": 32000,
            "max_model_turns": 8,
            "max_elapsed_minutes": 45,
            "role_runs_used": 2,
            "subtasks_used": 1,
            "input_tokens_used": input_tokens,
            "output_tokens_used": output_tokens,
            "model_turns_used": turns,
            "elapsed_minutes": max(1, int((elapsed_seconds + 59) // 60)),
            "exhausted_limits": [],
            "elapsed_seconds_used": elapsed_seconds,
            "exhaustion_action": "transition_to_human_required_and_stop_new_runs",
        },
        "role_runs": role_runs,
        "artifacts": [
            _artifact(owner_record.report_ref, kind="change_report", attempt_id=OWNER_ATTEMPT_ID, snapshot=owner_record.final_snapshot or base_snapshot),
            _artifact(test_report_ref, kind="test_report", attempt_id=TEST_ATTEMPT_ID, snapshot=final_snapshot),
            _artifact(resume_directive_ref, kind="decision", attempt_id="main-control", snapshot=base_snapshot),
        ],
        "retry_learning": summarize_retry_learning(role_runs),
        "state_events": state_events,
        "gates": [
            {"gate_id": "control-submit", "kind": "control", "status": "passed", "evidence_refs": [], "decided_by": "main_control", "decided_at": _now()},
            {"gate_id": "control-pause-resume", "kind": "recovery", "status": "passed", "evidence_refs": [resume_directive_ref], "decided_by": "main_control", "decided_at": _now()},
            {"gate_id": "test", "kind": "test", "status": "passed", "evidence_refs": [test_report_ref], "decided_by": "test-verification", "decided_at": _now()},
        ],
        "termination": {
            "completion_claim": "Scheduler control Owner and independent Test canary passed",
            "final_report_ref": test_report_ref,
            "unresolved_blockers": [],
            "human_required_reason": "",
            "safe_to_integrate": False,
            "next_action": "record evidence; do not merge child worktree automatically",
        },
        "test_report_summary": {
            "overall": test_report.get("overall"),
            "results": test_report.get("results"),
        },
    }
    validate_run_manifest(manifest)
    _write_json(manifest_path, manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default="gwent_v4")
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument("--state-root", type=Path, default=None)
    parser.add_argument(
        "--resume-state-root",
        type=Path,
        default=None,
        help="Finish a durable canary whose Owner/Test runs already completed; never launches a new model task.",
    )
    parser.add_argument("--base-snapshot", default="")
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    return parser


def _latest_resume_artifact_ref(state_root: Path) -> str:
    events_path = state_root / "control" / "control-events.ndjson"
    if not events_path.is_file():
        return ""
    latest = ""
    for line in events_path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("request", {}).get("action") in {"prepare_resume", "resume"}:
            latest = str(event.get("response", {}).get("resume_artifact_ref") or latest)
    return latest


def _finish_existing_canary(*, root: Path, state_root: Path, project_id: str) -> dict[str, Any]:
    """Close and report a durable Test attempt without issuing a model prompt.

    A parent process may exit after the independent Test has completed but
    before it has copied the report and written the RunManifest.  Rebinding
    this attempt is deliberately separate from resuming an Owner: it performs
    only lifecycle/report closure against an already-completed Codex session.
    """
    runtime = ControlRuntime(state_root / "runtime.json")
    owner_spec = runtime.specs[TASK_ID]
    owner_journal = ExecutionJournal.for_task(state_root / "journals", TASK_ID, OWNER_ATTEMPT_ID)
    test_journal = ExecutionJournal.for_task(state_root / "journals", TASK_ID, TEST_ATTEMPT_ID)
    owner_record = owner_journal.load()
    test_record = test_journal.load()
    if owner_record.status != "closed" or not owner_record.final_snapshot:
        raise RuntimeError("cannot finish canary before the Owner has a closed final snapshot")
    if test_record.status not in {"running", "interrupted", "lost"}:
        raise RuntimeError(f"cannot finish Test attempt in terminal state {test_record.status}")

    task_root = str(owner_spec.task_packet["artifacts"]["task_root"])
    test_profile = json.loads((state_root / "inputs" / "test-profile.json").read_text(encoding="utf-8"))
    test_matrix = load_yaml(root / "docs/current/agent-loop/TEST_MATRIX.yaml")
    handoff = build_handoff(
        owner_spec,
        owner_record,
        to_role="test-verification",
        changed_paths=tuple(owner_record.changed_paths),
        verification_scope=("apps/web/frontend/index.html",),
        reason="Scheduler control canary Owner completed",
    )
    plan = build_verification_plan(
        handoff,
        test_profile=test_profile,
        test_matrix=test_matrix,
        verification_attempt_id=TEST_ATTEMPT_ID,
        command_ids=(COMMAND_ID,),
        docker_enabled=False,
    )
    test_spec = build_verification_launch_spec(
        owner_spec,
        handoff,
        test_profile=test_profile,
        attempt_id=TEST_ATTEMPT_ID,
        task_packet_ref=f"{task_root}/verification-task.json",
        context_brief_ref=f"{task_root}/verification-context.json",
        profile_ref=f"{task_root}/test-profile.json",
        write_scope=("declared test scope only",),
        max_turns=4,
        max_input_tokens=1000000,
        max_output_tokens=12000,
        max_elapsed_minutes=30,
        docker_enabled=False,
    )
    stable_report = state_root / "host-artifacts" / TASK_ID / f"{TEST_ATTEMPT_ID}.json"
    transient_report = Path(str(test_record.report_ref or ""))
    interrupted_worktree = transient_report.parent / "worktree"
    if stable_report.is_file() and transient_report.is_file() and not interrupted_worktree.exists():
        # A prior close had already copied the report and removed the worktree,
        # then its Git cleanup returned an error before the journal sync.  The
        # stable artifact plus absent worktree is an idempotent terminal proof;
        # recover the missing journal event without talking to the model or
        # recreating the worktree.
        recovered = RunnerEvent(
            runner_ref=str(test_record.runner_ref),
            event="closed_after_cleanup_recovery",
            status="closed",
            task_id=TASK_ID,
            task_revision=1,
            attempt_id=TEST_ATTEMPT_ID,
            profile_revision=test_record.identity.profile_revision,
            snapshot=test_record.identity.snapshot,
            write_scope=test_record.identity.write_scope,
            resume_count=test_record.resume_count,
            report_ref=str(stable_report),
            final_snapshot=test_record.identity.snapshot,
            changed_paths=(),
            input_tokens=test_record.input_tokens,
            output_tokens=test_record.output_tokens,
            elapsed_seconds=test_record.elapsed_seconds,
        )
        test_record.accept(recovered, max_resumes=0)
        test_journal.write(test_record)
        verifier_record = test_record
        verifier_report_ref = str(stable_report)
    else:
        transport = CodexHostTransport(project_id=project_id, project_is_git=True, bridge=runtime.bridge)
        verifier = RunnerExecution.rebind(
            ExternalRunnerAdapter(test_spec, transport),
            test_spec.request,
            test_record,
            journal=test_journal,
            max_resumes=0,
        )
        verifier_event = verifier.last_event
        persisted_report_ref = test_record.report_ref
        if verifier_event is None or verifier_event.status != "interrupted" or not persisted_report_ref:
            raise RuntimeError("completed Test attempt cannot be safely closed from its persisted report")
        # Rebind returns the live session state.  A finished CLI session does
        # not repeat its transient report path, so retain the journal ref.
        verifier_event = verifier.close(persisted_report_ref)
        verifier_record = verifier.record
        verifier_report_ref = str(verifier_event.report_ref or "")
    if not verifier_report_ref:
        raise RuntimeError("Test/Verification closed without a report")
    raw_report = runtime.bridge.read_report(verifier_report_ref)
    test_report = json.loads(raw_report) if isinstance(raw_report, str) else raw_report
    validate_test_report(test_report, plan=plan)
    if test_report.get("overall") != "PASS":
        raise RuntimeError(f"TestReport did not PASS: {test_report.get('overall')}")
    manifest_path = state_root / "run-manifest.json"
    manifest = _manifest(
        task_id=TASK_ID,
        revision=1,
        base_snapshot=owner_spec.request.snapshot,
        final_snapshot=verifier_record.final_snapshot or plan.snapshot,
        owner_record=owner_record,
        verifier_record=verifier_record,
        test_report_ref=verifier_report_ref,
        test_report=test_report,
        resume_directive_ref=_latest_resume_artifact_ref(state_root),
        state_events=_state_events(1),
        manifest_path=manifest_path,
    )
    report = {
        "status": "PASS",
        "task_id": TASK_ID,
        "base_snapshot": owner_spec.request.snapshot,
        "owner_final_snapshot": owner_record.final_snapshot,
        "test_final_snapshot": verifier_record.final_snapshot,
        "runner_ref": owner_record.runner_ref,
        "resume_artifact_ref": _latest_resume_artifact_ref(state_root),
        "owner_report": owner_record.report_ref,
        "test_report": verifier_report_ref,
        "manifest": str(manifest_path),
        "state_root": str(state_root),
        "budget": manifest["budget"],
    }
    _write_json(state_root / "control-canary-report.json", report)
    return report


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = args.project_root.resolve()
    if args.resume_state_root is not None:
        return _finish_existing_canary(
            root=root,
            state_root=args.resume_state_root.resolve(),
            project_id=args.project_id,
        )
    base_snapshot = args.base_snapshot.strip() or _git_head(root)
    run_id = f"{TASK_ID}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    state_root = (args.state_root or root / ".agent-loop" / "control-canary" / run_id).resolve()
    task_root = f".agent-loop/control-canary/{run_id}/inputs"
    inputs = state_root / "inputs"
    owner_profile = load_yaml(root / "docs/current/agent-loop/profiles/product.yaml")
    test_profile = load_yaml(root / "docs/current/agent-loop/profiles/test-verification.yaml")
    test_matrix = load_yaml(root / "docs/current/agent-loop/TEST_MATRIX.yaml")
    verification_command = _load_product_command(test_matrix)
    packet = _packet(base_snapshot, task_root=task_root, verification_command=verification_command)
    context = _context(base_snapshot)
    task_packet_ref = f"{task_root}/task-packet.json"
    context_ref = f"{task_root}/context-brief.json"
    owner_profile_ref = f"{task_root}/product-profile.json"
    test_profile_ref = f"{task_root}/test-profile.json"
    _write_json(inputs / "task-packet.json", packet)
    _write_json(inputs / "context-brief.json", context)
    _write_json(inputs / "product-profile.json", owner_profile)
    _write_json(inputs / "test-profile.json", test_profile)

    owner_spec = build_launch_spec(
        task_packet=packet,
        context_brief=context,
        profile=owner_profile,
        task_packet_ref=task_packet_ref,
        context_brief_ref=context_ref,
        profile_ref=owner_profile_ref,
        attempt_id=OWNER_ATTEMPT_ID,
        write_scope=("apps/web/frontend/index.html",),
        max_turns=6,
        max_input_tokens=1000000,
        max_output_tokens=32000,
        max_elapsed_minutes=45,
        subtask_depth=0,
    )
    runtime_config = {
        "schema": "agent-loop.control-runtime.v1",
        "project_id": args.project_id,
        "project_root": str(root),
        "state_root": str(state_root),
        "host": {
            "codex_command": ["codex"],
            "model": "gpt-5.6-luna",
            "model_reasoning_effort": "xhigh",
            "worktree_root": str(state_root / "worktrees"),
            "artifact_root": str(state_root / "host-artifacts"),
            "session_registry_root": str(state_root / "registry"),
        },
        "scheduler_limits": {
            "max_concurrency": 1,
            "max_tasks": 1,
            "max_input_tokens": 1000000,
            "max_output_tokens": 32000,
            "max_model_turns": 8,
            "max_elapsed_minutes": 45,
        },
        "launch_specs": {TASK_ID: owner_spec.to_payload()},
    }
    runtime_config_path = state_root / "runtime.json"
    _write_json(runtime_config_path, runtime_config)
    runtime = ControlRuntime(runtime_config_path)
    token_file = state_root / "token"
    if not token_file.exists():
        create_capability_token(token_file)
    token = read_capability_token(token_file)
    # Unix domain socket paths are short on Linux (commonly about 108 bytes).
    # Keep durable state in the run directory, but place the live socket under
    # /tmp so deeply nested Codex worktrees do not fail before the canary starts.
    socket_path = Path(tempfile.gettempdir()) / f"gwctrl-{uuid.uuid4().hex[:12]}.sock"
    service = SchedulerControlService(
        runtime.control(),
        socket_path=socket_path,
        capability_token=token,
        poll_interval_seconds=0.25,
    )
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    control_client: McpControlClient | None = None
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() <= deadline and not socket_path.exists():
            time.sleep(0.05)
        if not socket_path.exists():
            raise RuntimeError("Scheduler control socket did not start")
        control_client = McpControlClient(
            root=root,
            socket_path=socket_path,
            token_file=token_file,
        )
        submit = control_client.call(
            "loop_submit",
            {
                "task_id": TASK_ID,
                "reason": "start declared Scheduler control canary",
                "task_packet_ref": task_packet_ref,
            },
        )

        runner_ref = ""
        task_status = ""
        deadline = time.monotonic() + args.timeout_seconds
        while time.monotonic() <= deadline:
            inspected = control_client.call("loop_inspect", {"task_id": TASK_ID})
            task_status = str(inspected.get("task_status") or "")
            runner_ref = str(inspected.get("runner_ref") or "")
            if task_status == "running" and runner_ref:
                break
            if task_status in {"completed", "cancelled", "failed", "blocked", "human_required"}:
                raise RuntimeError(f"Owner reached {task_status} before pause: {inspected}")
            time.sleep(0.25)
        if not runner_ref:
            raise RuntimeError("Owner did not start before timeout")
        if not runtime.bridge.wait_for_resume_checkpoint(
            parse_codex_runner_ref(runner_ref),
            timeout_seconds=min(120.0, args.timeout_seconds),
        ):
            raise RuntimeError("Owner did not reach the Codex CLI resume checkpoint before timeout")

        update_result = control_client.call(
            "loop_update",
            {
                "task_id": TASK_ID,
                "reason": "deliver the canary's post-start clarification",
                "facts": [
                    {
                        "claim": f'Set `{CANARY_ATTRIBUTE}` to "{CANARY_SUPPLEMENT_VALUE}".',
                        "source_ref": "canary:user-supplement-after-owner-start",
                        "effect": "Supplies the unspecified attribute value; task goal, write scope, contracts, and budgets remain unchanged.",
                    }
                ],
            },
        )
        if not update_result.get("same_runner_resumed") or update_result.get("runner_ref") != runner_ref:
            raise RuntimeError(f"loop_update did not resume the same Runner: {update_result}")

        final_owner = {}
        while time.monotonic() <= deadline:
            final_owner = control_client.call("loop_inspect", {"task_id": TASK_ID})
            task_status = str(final_owner.get("task_status") or "")
            if task_status == "completed":
                break
            if task_status in {"cancelled", "failed", "blocked", "human_required"}:
                raise RuntimeError(f"Owner control task ended as {task_status}: {final_owner}")
            time.sleep(0.5)
        if task_status != "completed":
            raise RuntimeError("Owner did not complete before timeout")
    finally:
        if control_client is not None:
            control_client.close()
        service.request_stop()
        thread.join(timeout=3)
        try:
            socket_path.unlink()
        except FileNotFoundError:
            pass

    owner_record = ExecutionJournal.for_task(state_root / "journals", TASK_ID, OWNER_ATTEMPT_ID).load()
    changed_paths = tuple(owner_record.changed_paths or ["apps/web/frontend/index.html"])
    handoff = build_handoff(
        owner_spec,
        owner_record,
        to_role="test-verification",
        changed_paths=changed_paths,
        verification_scope=("apps/web/frontend/index.html",),
        reason="Scheduler control canary Owner completed",
    )
    plan = build_verification_plan(
        handoff,
        test_profile=test_profile,
        test_matrix=test_matrix,
        verification_attempt_id=TEST_ATTEMPT_ID,
        command_ids=(COMMAND_ID,),
        docker_enabled=False,
    )
    test_spec = build_verification_launch_spec(
        owner_spec,
        handoff,
        test_profile=test_profile,
        attempt_id=TEST_ATTEMPT_ID,
        task_packet_ref=f"{task_root}/verification-task.json",
        context_brief_ref=f"{task_root}/verification-context.json",
        profile_ref=test_profile_ref,
        write_scope=("declared test scope only",),
        max_turns=4,
        max_input_tokens=1000000,
        max_output_tokens=12000,
        max_elapsed_minutes=30,
        docker_enabled=False,
    )
    # The verifier receives only the final snapshot plus the minimum clarified
    # fact needed to check it.  The concrete value is deliberately absent from
    # the Owner's original TaskPacket and ContextBrief.
    verification_packet = copy.deepcopy(dict(test_spec.task_packet))
    verification_acceptance = dict(verification_packet.get("acceptance", {}))
    verification_acceptance["behavioral"] = [
        f"`apps/web/frontend/index.html` root div contains {CANARY_MARKER}.",
        "No other path changes in the Owner final snapshot.",
    ]
    verification_packet["acceptance"] = verification_acceptance
    verification_context = copy.deepcopy(dict(test_spec.context_brief))
    verification_facts = list(verification_context.get("fact_ledger", []))
    verification_facts.append(
        {
            "fact": f'Set `{CANARY_ATTRIBUTE}` to "{CANARY_SUPPLEMENT_VALUE}".',
            "status": "confirmed",
            "source_ref": "canary:user-supplement-after-owner-start",
            "snapshot": handoff.final_snapshot,
        }
    )
    verification_context["fact_ledger"] = verification_facts
    _write_json(inputs / "verification-task.json", verification_packet)
    _write_json(inputs / "verification-context.json", verification_context)
    test_spec = build_launch_spec(
        task_packet=verification_packet,
        context_brief=verification_context,
        profile=copy.deepcopy(dict(test_spec.profile)),
        task_packet_ref=test_spec.task_packet_ref,
        context_brief_ref=test_spec.context_brief_ref,
        profile_ref=test_spec.profile_ref,
        attempt_id=TEST_ATTEMPT_ID,
        write_scope=test_spec.request.write_scope,
        max_turns=test_spec.request.max_turns,
        max_input_tokens=test_spec.max_input_tokens,
        max_output_tokens=test_spec.max_output_tokens,
        max_elapsed_minutes=test_spec.max_elapsed_minutes,
        subtask_depth=test_spec.subtask_depth,
    )
    transport = CodexHostTransport(project_id=args.project_id, project_is_git=True, bridge=runtime.bridge)
    verifier = RunnerExecution(
        ExternalRunnerAdapter(test_spec, transport),
        test_spec.request,
        journal=ExecutionJournal.for_task(state_root / "journals", TASK_ID, TEST_ATTEMPT_ID),
        max_resumes=0,
    )
    verifier_event = _complete_execution(verifier, label="Test/Verification", timeout_seconds=args.timeout_seconds)
    if not verifier_event.report_ref:
        raise RuntimeError("Test/Verification closed without a report")
    raw_report = runtime.bridge.read_report(verifier_event.report_ref)
    test_report = json.loads(raw_report) if isinstance(raw_report, str) else raw_report
    validate_test_report(test_report, plan=plan)
    if test_report.get("overall") != "PASS":
        raise RuntimeError(f"TestReport did not PASS: {test_report.get('overall')}")
    manifest_path = state_root / "run-manifest.json"
    manifest = _manifest(
        task_id=TASK_ID,
        revision=1,
        base_snapshot=base_snapshot,
        final_snapshot=verifier.record.final_snapshot or plan.snapshot,
        owner_record=owner_record,
        verifier_record=verifier.record,
        test_report_ref=verifier_event.report_ref,
        test_report=test_report,
        resume_directive_ref=str(update_result.get("resume_artifact_ref") or ""),
        state_events=_state_events(1),
        manifest_path=manifest_path,
    )
    report = {
        "status": "PASS",
        "task_id": TASK_ID,
        "base_snapshot": base_snapshot,
        "owner_final_snapshot": owner_record.final_snapshot,
        "test_final_snapshot": verifier.record.final_snapshot,
        "runner_ref": runner_ref,
        "resume_artifact_ref": update_result.get("resume_artifact_ref"),
        "owner_report": owner_record.report_ref,
        "test_report": verifier_event.report_ref,
        "manifest": str(manifest_path),
        "state_root": str(state_root),
        "budget": manifest["budget"],
    }
    _write_json(state_root / "control-canary-report.json", report)
    return report


def main() -> int:
    try:
        print(json.dumps(run(build_parser().parse_args()), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
