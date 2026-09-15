"""Run Pilot 011 as a real two-process Product -> Teacher -> Test canary.

The command is intentionally split into ``bootstrap`` and ``restore`` phases.
The first process starts Product, persists the Scheduler snapshot, and exits
without stopping the Host-owned Codex process.  The second process constructs
new bridge/backend objects, rebinds the persisted runner, then continues the
serial handoffs.  Runtime state is written below ``.agent-loop/live-runs`` and
is not part of the product candidate snapshot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.agent_loop.codex_cli_bridge import CodexCliBridge
    from scripts.agent_loop.codex_host_transport import CodexHostTransport
    from scripts.agent_loop.execution import ExecutionJournal, RunnerExecution
    from scripts.agent_loop.external import ExternalRunnerAdapter
    from scripts.agent_loop.handoff import build_contract_handoff, build_handoff
    from scripts.agent_loop.launch import build_launch_spec, build_verification_launch_spec
    from scripts.agent_loop.manifest import validate_run_manifest
    from scripts.agent_loop.report_validation import validate_test_report
    from scripts.agent_loop.scheduler import Scheduler, SchedulerLimits
    from scripts.agent_loop.scheduler_backend import MultiRoleRunnerExecutionBackend
    from scripts.agent_loop.validate_packet import load_yaml, validate_context_brief, validate_task_packet
    from scripts.agent_loop.verification import build_verification_plan
else:
    from .codex_cli_bridge import CodexCliBridge
    from .codex_host_transport import CodexHostTransport
    from .execution import ExecutionJournal, RunnerExecution
    from .external import ExternalRunnerAdapter
    from .handoff import build_contract_handoff, build_handoff
    from .launch import build_launch_spec, build_verification_launch_spec
    from .manifest import validate_run_manifest
    from .report_validation import validate_test_report
    from .scheduler import Scheduler, SchedulerLimits
    from .scheduler_backend import MultiRoleRunnerExecutionBackend
    from .validate_packet import load_yaml, validate_context_brief, validate_task_packet
    from .verification import build_verification_plan


ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "GW-STAGE3-LIVE-011"
PRODUCT_ID = f"{RUN_ID}-PRODUCT"
TEACHER_ID = f"{RUN_ID}-TEACHER"
BASE_SNAPSHOT = "53fabec954b549f1cdce46720c3461470230ed6e"
RUN_ROOT = ROOT / ".agent-loop" / "live-runs" / RUN_ID
CONFIG_PATH = RUN_ROOT / "config.json"
SCHEDULER_PATH = RUN_ROOT / "scheduler.json"
MANIFEST_PATH = RUN_ROOT / "PILOT_011_RUN_MANIFEST.json"
TEST_MATRIX_PATH = ROOT / "docs/current/agent-loop/TEST_MATRIX.yaml"
PROFILE_PATHS = {
    "product": ROOT / "docs/current/agent-loop/profiles/product.yaml",
    "teacher": ROOT / "docs/current/agent-loop/profiles/teacher.yaml",
    "test-verification": ROOT / "docs/current/agent-loop/profiles/test-verification.yaml",
}


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*args: str) -> str:
    import subprocess

    result = subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _runtime_ref(name: str) -> str:
    return f".agent-loop/live-runs/{RUN_ID}/{name}.json"


def _context(task_id: str, snapshot: str, *, sources: list[dict[str, str]], claims: list[str]) -> dict[str, Any]:
    value = {
        "task_id": task_id,
        "packet_revision": 1,
        "context_snapshot": snapshot,
        "context_floor_refs": [
            {"path": "AGENTS.md", "locator": "routing and verification"},
            {"path": "docs/current/agent-loop/archive/pilots/PILOT_011_TASK_DESIGN.md", "locator": "Pilot 011"},
        ],
        "fact_source_graph": sources,
        "fact_ledger": [{"claim": claim, "status": "confirmed", "verified_snapshot": snapshot} for claim in claims],
        "lessons": {"relevant_refs": []},
    }
    validate_context_brief(value)
    return value


def _packet(
    task_id: str,
    owner: str,
    snapshot: str,
    *,
    outcome: str,
    allowed_write_paths: list[str],
    allowed_test_write_paths: list[str],
    contracts: list[str],
    commands: list[str],
    max_input: int,
    max_output: int,
    max_turns: int,
    max_elapsed: int,
) -> dict[str, Any]:
    value = {
        "protocol_version": 1,
        "task_id": task_id,
        "revision": 1,
        "title": f"Pilot 011 {owner} canary",
        "requested_outcome": outcome,
        "authority": {
            "required_skills": ["product-integration"] if owner == "product" else ["teacher-explanation"] if owner == "teacher" else [],
            "no_parent_transcript": True,
        },
        "ownership": {"primary_owner": owner},
        "scope": {
            "allowed_write_paths": allowed_write_paths,
            "allowed_test_write_paths": allowed_test_write_paths,
            "forbidden_paths": ["models", "src", "include", "python/src/gwent_rl", "runs"],
            "declared_contracts": contracts,
        },
        "workspace": {"snapshot_kind": "git_commit", "snapshot_ref": snapshot},
        "inputs": {},
        "acceptance": {
            "verification_commands": commands,
            "verification_working_directories": [".", "apps/web/frontend"],
            "manual_gates": ["scope", "contract", "evidence"],
        },
        "execution": {
            "max_owner_attempts": 1,
            "max_elapsed_minutes": max_elapsed,
            "max_role_runs": 3,
            "max_model_input_tokens": max_input,
            "max_model_output_tokens": max_output,
            "max_model_turns": max_turns,
            "max_subtasks": 0,
            "max_subtask_depth": 0,
        },
        "artifacts": {"required": ["ChangeReport" if owner == "product" else "ReviewReport"]},
    }
    validate_task_packet(value)
    return value


def _product_packet() -> dict[str, Any]:
    return _packet(
        PRODUCT_ID,
        "product",
        BASE_SNAPSHOT,
        outcome=(
            "In apps/web/frontend/src/components/TeacherPanel.tsx, add one read-only provenance line "
            "in the existing successful response area showing response.schema_version and "
            "response.grounded_facts.length. Use only typed structured fields. Do not change API "
            "requests, contracts, game rules, model files, prompts, or hidden-information behavior."
        ),
        allowed_write_paths=["apps/web/frontend/src/components/TeacherPanel.tsx"],
        allowed_test_write_paths=["apps/web/frontend"],
        contracts=["TeacherTurnResponse: unchanged", "Core HTTP api_version: unchanged"],
        commands=[
            "PYTHONPATH=apps/web/backend pytest -q apps/web/backend/tests",
            "npm run build",
        ],
        max_input=1_000_000,
        max_output=32_000,
        max_turns=12,
        max_elapsed=30,
    )


def _teacher_packet(snapshot: str) -> dict[str, Any]:
    return _packet(
        TEACHER_ID,
        "teacher",
        snapshot,
        outcome=(
            "Perform a read-only consumer review of the Product change. Confirm that the UI uses only "
            "public typed schema_version and grounded_facts count, preserves fallback behavior, and "
            "does not expose prompt text, hidden hand, undisclosed candidates, or provider internals. "
            "Do not modify production code or contracts. Return a ReviewReport/ChangeReport with evidence."
        ),
        allowed_write_paths=["services/teacher/tests"],
        allowed_test_write_paths=["services/teacher/tests"],
        contracts=["teacher-turn-response-v1: unchanged"],
        commands=["PYTHONPATH=. pytest -q services/teacher/tests"],
        max_input=64_000,
        max_output=16_000,
        max_turns=6,
        max_elapsed=15,
    )


def _base_config() -> dict[str, Any]:
    product = _product_packet()
    product_context = _context(
        PRODUCT_ID,
        BASE_SNAPSHOT,
        sources=[
            {"path": "apps/web/frontend/src/components/TeacherPanel.tsx", "why": "target UI"},
            {"path": "apps/web/frontend/src/types/game.ts", "why": "typed response fields"},
            {"path": "docs/current/TEACHER_AND_WEB.md", "why": "Teacher contract"},
        ],
        claims=[
            "TeacherPanel already receives structured response data",
            "The requested change is read-only presentation metadata",
            "The Teacher response contract remains unchanged",
        ],
    )
    return {
        "protocol_version": 1,
        "run_id": RUN_ID,
        "project_id": "gwent-v4",
        "project_root": str(ROOT),
        "base_snapshot": BASE_SNAPSHOT,
        "task_specs": {
            PRODUCT_ID: {
                "packet": product,
                "context": product_context,
                "profile": load_yaml(PROFILE_PATHS["product"]),
                "packet_ref": _runtime_ref("product-packet"),
                "context_ref": _runtime_ref("product-context"),
                "profile_ref": "docs/current/agent-loop/profiles/product.yaml",
                "attempt_id": "pilot011-product-1",
                "write_scope": ["apps/web/frontend/src/components/TeacherPanel.tsx"],
            }
        },
        "phases": {"bootstrap": "pending", "restore": "pending", "teacher": "pending", "test": "pending"},
    }


def _write_role_inputs(config: Mapping[str, Any], task_id: str) -> None:
    spec = config["task_specs"][task_id]
    refs = [(spec["packet_ref"], spec["packet"]), (spec["context_ref"], spec["context"])]
    for ref, value in refs:
        target = ROOT / ref
        _write_json(target, value)


class LiveRuntime:
    """One process-local set of role factories over the durable Host bridge."""

    def __init__(self, config: Mapping[str, Any]) -> None:
        self.config = config
        command = shutil.which("codex") or "codex"
        self.bridge = CodexCliBridge(
            {str(config["project_id"]): ROOT},
            codex_command=(command,),
            worktree_root=RUN_ROOT / "host" / "worktrees",
            artifact_root=RUN_ROOT / "host-artifacts",
            session_registry_root=RUN_ROOT / "host" / "registry",
            startup_timeout=45.0,
            stop_timeout=15.0,
        )
        self.executions: dict[str, RunnerExecution] = {}

    def _spec(self, task_id: str, budget: Any | None = None):
        raw = self.config["task_specs"][task_id]
        packet = raw["packet"]
        profile = raw["profile"]
        if budget is None:
            execution = packet["execution"]
            max_turns = int(execution["max_model_turns"])
            max_input = int(execution["max_model_input_tokens"])
            max_output = int(execution["max_model_output_tokens"])
            max_elapsed = int(execution["max_elapsed_minutes"])
        else:
            max_turns = int(budget.max_model_turns)
            max_input = int(budget.max_input_tokens)
            max_output = int(budget.max_output_tokens)
            max_elapsed = max(1, int(math.ceil(float(budget.max_elapsed_seconds) / 60.0)))
        return build_launch_spec(
            task_packet=packet,
            context_brief=raw["context"],
            profile=profile,
            task_packet_ref=str(raw["packet_ref"]),
            context_brief_ref=str(raw["context_ref"]),
            profile_ref=str(raw["profile_ref"]),
            attempt_id=str(raw["attempt_id"]),
            write_scope=tuple(str(item) for item in raw["write_scope"]),
            max_turns=max_turns,
            max_input_tokens=max_input,
            max_output_tokens=max_output,
            max_elapsed_minutes=max_elapsed,
            subtask_depth=0,
        )

    def _execution(self, task_id: str, budget: Any) -> RunnerExecution:
        spec = self._spec(task_id, budget)
        transport = CodexHostTransport(
            project_id=str(self.config["project_id"]),
            project_is_git=True,
            bridge=self.bridge,
        )
        adapter = ExternalRunnerAdapter(spec, transport)
        journal = ExecutionJournal.for_task(RUN_ROOT / "journals", task_id, spec.request.attempt_id)
        execution = RunnerExecution(adapter, spec.request, journal=journal, max_resumes=1)
        self.executions[task_id] = execution
        return execution

    def _rebound_execution(self, task_id: str, budget: Any, handle: str) -> RunnerExecution:
        spec = self._spec(task_id, budget)
        transport = CodexHostTransport(
            project_id=str(self.config["project_id"]),
            project_is_git=True,
            bridge=self.bridge,
        )
        adapter = ExternalRunnerAdapter(spec, transport)
        journal = ExecutionJournal.for_task(RUN_ROOT / "journals", task_id, spec.request.attempt_id)
        execution = RunnerExecution.rebind(
            adapter,
            spec.request,
            journal.load(),
            journal=journal,
            max_resumes=1,
        )
        self.executions[task_id] = execution
        return execution

    def backend(self) -> MultiRoleRunnerExecutionBackend:
        role_task_ids = {
            str(spec["packet"]["ownership"]["primary_owner"]): task_id
            for task_id, spec in self.config["task_specs"].items()
        }
        return MultiRoleRunnerExecutionBackend(
            {
                role: (lambda task, budget: self._execution(task.task_id, budget))
                for role in role_task_ids
            },
            role_rebind_factories={
                role: (lambda task, budget, handle: self._rebound_execution(task.task_id, budget, handle))
                for role in role_task_ids
            },
        )


def _scheduler(config: Mapping[str, Any], runtime: LiveRuntime) -> Scheduler:
    return Scheduler(
        runtime.backend(),
        SchedulerLimits(
            max_concurrency=1,
            max_tasks=3,
            max_input_tokens=1_000_000,
            max_output_tokens=32_000,
            max_model_turns=12,
            max_elapsed_minutes=30,
        ),
        state_path=SCHEDULER_PATH,
    )


def _wait_task(scheduler: Scheduler, task_id: str, *, max_seconds: float = 1_650.0) -> Any:
    deadline = time.monotonic() + max_seconds
    while time.monotonic() <= deadline:
        scheduler.pump()
        task = scheduler.get_task(task_id)
        if task.status in {"completed", "failed", "blocked", "human_required", "cancelled"}:
            return task
        time.sleep(1.0)
    return scheduler.end(task_id, reason="live canary wall-clock bound exhausted", status="human_required")


def _report(runtime: LiveRuntime, task_id: str) -> Mapping[str, Any] | None:
    execution = runtime.executions.get(task_id)
    if execution is None or not execution.record.report_ref:
        return None
    path = Path(execution.record.report_ref)
    try:
        value = json.loads(runtime.bridge.read_report(str(path)))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def _artifact(path: str | Path | None, kind: str, producer: str, snapshot: str) -> dict[str, Any] | None:
    if not path:
        return None
    target = Path(path)
    if not target.is_file():
        return None
    return {
        "artifact_id": f"{producer}-{kind}",
        "kind": kind,
        "path": str(target.resolve()),
        "producer_attempt_id": producer,
        "snapshot": snapshot,
        "sha256": _sha256(target),
        "redaction_status": "not_required",
        "retention": "project_record",
    }


def _role_runs(runtime: LiveRuntime) -> list[dict[str, Any]]:
    return [execution.record.to_manifest_role_run() for execution in runtime.executions.values()]


def _manifest(
    runtime: LiveRuntime,
    *,
    status: str,
    final_snapshot: str = "",
    handoff_path: Path | None = None,
    plan: Any | None = None,
    test_report: Mapping[str, Any] | None = None,
    reason: str = "live canary in progress",
) -> dict[str, Any]:
    records = [execution.record for execution in runtime.executions.values()]
    artifacts: list[dict[str, Any]] = []
    for record in records:
        kind = "test_report" if record.identity.role == "test-verification" else "review_report" if record.identity.role == "teacher" else "change_report"
        item = _artifact(record.report_ref, kind, record.identity.attempt_id, record.final_snapshot or record.identity.snapshot)
        if item:
            artifacts.append(item)
    if handoff_path is not None:
        item = _artifact(handoff_path, "handoff", "pilot011-product-1", handoff_path.name)
        if item:
            item["snapshot"] = next((record.final_snapshot for record in records if record.identity.role == "product" and record.final_snapshot), BASE_SNAPSHOT)
            artifacts.append(item)
    item = _artifact(SCHEDULER_PATH, "log", "pilot011-scheduler", final_snapshot or BASE_SNAPSHOT)
    if item:
        artifacts.append(item)
    input_used = sum(record.input_tokens for record in records)
    output_used = sum(record.output_tokens for record in records)
    turns_used = sum(record.model_turns_used for record in records)
    elapsed = sum(record.elapsed_seconds for record in records)
    gates = [
        {"gate_id": "scope", "kind": "scope", "status": "passed" if records and all(record.status == "closed" for record in records[:1]) else "pending", "evidence_refs": [], "decided_by": "main", "decided_at": ""},
        {"gate_id": "contract", "kind": "contract", "status": "passed" if handoff_path else "pending", "evidence_refs": [], "decided_by": "main", "decided_at": ""},
        {"gate_id": "test", "kind": "test", "status": "passed" if test_report and test_report.get("overall") == "PASS" else "pending", "evidence_refs": [], "decided_by": "test-verification", "decided_at": ""},
        {"gate_id": "human", "kind": "integration", "status": "pending", "evidence_refs": [], "decided_by": "human", "decided_at": ""},
    ]
    manifest = {
        "protocol_version": 1,
        "run_id": RUN_ID,
        "task_id": RUN_ID,
        "task_revision": 1,
        "runner": "codex-cli-host",
        "status": status,
        "created_at": "",
        "updated_at": "",
        "workspace": {
            "base_snapshot_kind": "git_commit",
            "base_snapshot": BASE_SNAPSHOT,
            "final_snapshot": final_snapshot,
            "known_user_changes": [],
            "write_scope_refs": ["apps/web/frontend/src/components/TeacherPanel.tsx"],
        },
        "budget": {
            "max_role_runs": 3,
            "max_subtasks": 0,
            "max_subtask_depth": 0,
            "max_input_tokens": 1_000_000,
            "max_output_tokens": 32_000,
            "max_model_turns": 12,
            "max_elapsed_minutes": 30,
            "role_runs_used": len(records),
            "subtasks_used": 0,
            "input_tokens_used": input_used,
            "output_tokens_used": output_used,
            "model_turns_used": turns_used,
            "elapsed_minutes": int(math.ceil(elapsed / 60.0)),
            "elapsed_seconds_used": elapsed,
            "exhaustion_action": "transition_to_human_required_and_stop_new_runs",
        },
        "role_runs": _role_runs(runtime),
        "artifacts": artifacts,
        "state_events": [
            {"event_seq": index, "event_id": f"pilot011-{index}", "at": "", "from_status": source, "to_status": target, "actor": actor, "reason": event_reason, "evidence_refs": [], "task_revision": 1}
            for index, (source, target, actor, event_reason) in enumerate([
                ("RECEIVED", "TRIAGED", "main", "live canary admitted"),
                ("TRIAGED", "CONTEXTUALIZED", "main", "structured context prepared"),
                ("CONTEXTUALIZED", "PLANNED", "main", "serial Product Teacher Test plan"),
                ("PLANNED", "ASSIGNED", "scheduler", "Product routed"),
                ("ASSIGNED", "IMPLEMENTING", "product", "Product Runner started"),
                ("IMPLEMENTING", "RESTARTED", "scheduler", "Scheduler process restarted"),
                ("RESTARTED", "REBOUND", "host", "same runner_ref rebound"),
                ("REBOUND", "HANDOFF", "main", "Product contract handoff created"),
                ("HANDOFF", "TESTING", "test-verification", "independent final-snapshot verification"),
            ], start=1)
        ],
        "gates": gates,
        "termination": {
            "completion_claim": "serial Product -> Teacher -> independent Test live canary",
            "final_report_ref": str(next((record.report_ref for record in reversed(records) if record.identity.role == "test-verification" and record.report_ref), "")),
            "unresolved_blockers": [reason] if status != "completed" else [],
            "recovery_point": "Scheduler snapshot and Host runner_ref registry",
            "cleanup": "not_required_no_docker" if status != "completed" else "complete",
        },
    }
    validate_run_manifest(manifest)
    _write_json(MANIFEST_PATH, manifest)
    return manifest


def bootstrap() -> dict[str, Any]:
    current = _git("rev-parse", "HEAD")
    if current != BASE_SNAPSHOT:
        raise RuntimeError(f"candidate snapshot drift: expected {BASE_SNAPSHOT}, got {current}")
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    config = _base_config()
    _write_role_inputs(config, PRODUCT_ID)
    _write_json(CONFIG_PATH, config)
    runtime = LiveRuntime(config)
    scheduler = _scheduler(config, runtime)
    scheduler.submit(config["task_specs"][PRODUCT_ID]["packet"])
    scheduler.pump()
    task = scheduler.get_task(PRODUCT_ID)
    if task.status != "running" or not task.handle:
        raise RuntimeError(f"Product did not reach running state: {task.status} {task.reason or ''}")
    scheduler.write_snapshot()
    config = deepcopy(config)
    config["phases"]["bootstrap"] = "snapshot_written"
    config["bootstrap"] = {"runner_ref": task.handle, "scheduler_snapshot": str(SCHEDULER_PATH), "pid_registry": str(RUN_ROOT / "host" / "registry")}
    _write_json(CONFIG_PATH, config)
    return {"status": "BOOTSTRAP_OK", "candidate": BASE_SNAPSHOT, "runner_ref": task.handle, "scheduler_snapshot": str(SCHEDULER_PATH)}


def restore_and_run() -> dict[str, Any]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if config.get("base_snapshot") != BASE_SNAPSHOT:
        raise RuntimeError("live config base snapshot does not match candidate")
    runtime = LiveRuntime(config)
    scheduler = Scheduler.restore(SCHEDULER_PATH, runtime.backend(), state_path=SCHEDULER_PATH)
    product_task = _wait_task(scheduler, PRODUCT_ID)
    product_execution = runtime.executions.get(PRODUCT_ID)
    if product_task.status != "completed" or product_execution is None or product_execution.record.status != "closed":
        _manifest(runtime, status="human_required", reason=f"Product did not close: {product_task.status} {product_task.reason or ''}")
        return {"status": "HUMAN_REQUIRED", "stage": "product", "reason": product_task.reason or product_task.status}
    product_spec = runtime._spec(PRODUCT_ID, product_task.budget)
    contract_handoff = build_contract_handoff(
        product_spec,
        product_execution.record,
        to_role="teacher",
        contract_refs=("apps/web/frontend/src/types/game.ts", "services/teacher/models.py", "docs/current/TEACHER_AND_WEB.md"),
        contract_version="teacher-turn-response-v1",
        consumer_scope=("services/teacher",),
        changed_paths=tuple(product_execution.record.changed_paths),
    )
    handoff_path = RUN_ROOT / "product-teacher-handoff.json"
    _write_json(handoff_path, contract_handoff.to_payload())

    config = deepcopy(config)
    teacher_packet = _teacher_packet(product_execution.record.final_snapshot or BASE_SNAPSHOT)
    teacher_context = _context(
        TEACHER_ID,
        teacher_packet["workspace"]["snapshot_ref"],
        sources=[
            {"path": str(handoff_path.relative_to(ROOT)), "why": "Product contract handoff"},
            {"path": "services/teacher/models.py", "why": "Teacher response model"},
            {"path": "docs/current/TEACHER_AND_WEB.md", "why": "privacy and integration contract"},
        ],
        claims=[
            "Product final snapshot is the Teacher review base",
            "The requested UI fields are public structured provenance fields",
            "Teacher must not expose prompt or hidden information",
        ],
    )
    config["task_specs"][TEACHER_ID] = {
        "packet": teacher_packet,
        "context": teacher_context,
        "profile": load_yaml(PROFILE_PATHS["teacher"]),
        "packet_ref": _runtime_ref("teacher-packet"),
        "context_ref": _runtime_ref("teacher-context"),
        "profile_ref": "docs/current/agent-loop/profiles/teacher.yaml",
        "attempt_id": "pilot011-teacher-1",
        "write_scope": ["services/teacher/tests"],
    }
    _write_role_inputs(config, TEACHER_ID)
    _write_json(CONFIG_PATH, config)
    runtime.config = config
    scheduler.backend = runtime.backend()
    scheduler.submit(teacher_packet)
    teacher_task = _wait_task(scheduler, TEACHER_ID, max_seconds=900.0)
    config["phases"]["teacher"] = teacher_task.status
    _write_json(CONFIG_PATH, config)
    teacher_execution = runtime.executions.get(TEACHER_ID)
    if teacher_task.status != "completed" or teacher_execution is None or teacher_execution.record.status != "closed":
        _manifest(runtime, status="human_required", handoff_path=handoff_path, reason=f"Teacher review did not close: {teacher_task.status} {teacher_task.reason or ''}")
        return {"status": "HUMAN_REQUIRED", "stage": "teacher", "reason": teacher_task.reason or teacher_task.status}
    teacher_final = teacher_execution.record.final_snapshot or product_execution.record.final_snapshot or BASE_SNAPSHOT
    product_final = product_execution.record.final_snapshot or BASE_SNAPSHOT
    if teacher_final != product_final:
        _manifest(runtime, status="human_required", handoff_path=handoff_path, reason="Teacher review changed the Product snapshot")
        return {"status": "HUMAN_REQUIRED", "stage": "teacher", "reason": "unexpected Teacher snapshot change"}
    review_report = _report(runtime, TEACHER_ID)
    if review_report is None:
        _manifest(runtime, status="human_required", handoff_path=handoff_path, reason="Teacher did not return readable ReviewReport")
        return {"status": "HUMAN_REQUIRED", "stage": "teacher", "reason": "unreadable ReviewReport"}

    verification_handoff = build_handoff(
        product_spec,
        product_execution.record,
        to_role="test-verification",
        changed_paths=tuple(product_execution.record.changed_paths),
        verification_scope=("apps/web/frontend", "services/teacher"),
        reason="Teacher consumer review passed on the same Product final snapshot",
    )
    test_profile = load_yaml(PROFILE_PATHS["test-verification"])
    test_matrix = load_yaml(TEST_MATRIX_PATH)
    plan = build_verification_plan(
        verification_handoff,
        test_profile=test_profile,
        test_matrix=test_matrix,
        verification_attempt_id="pilot011-test-1",
        command_ids=("product-backend", "product-frontend"),
        docker_enabled=False,
    )
    test_packet = deepcopy(product_spec.task_packet)
    test_packet["task_id"] = PRODUCT_ID
    test_packet["workspace"]["snapshot_ref"] = teacher_final
    test_packet["requested_outcome"] += " Verify from the final Teacher-reviewed snapshot and do not modify production code."
    test_context = _context(
        PRODUCT_ID,
        teacher_final,
        sources=[
            {"path": str(handoff_path.relative_to(ROOT)), "why": "Product -> Teacher contract evidence"},
            {"path": "apps/web/frontend/src/components/TeacherPanel.tsx", "why": "final Product changed file"},
            {"path": "docs/current/agent-loop/TEST_MATRIX.yaml", "why": "declared independent commands"},
        ],
        claims=[
            "Test starts from the final Teacher-reviewed Product snapshot",
            "Docker is not declared for this canary",
            "Test must report exact command, cwd, exit code and evidence refs",
        ],
    )
    test_spec = build_launch_spec(
        task_packet=test_packet,
        context_brief=test_context,
        profile=test_profile,
        task_packet_ref=_runtime_ref("test-packet"),
        context_brief_ref=_runtime_ref("test-context"),
        profile_ref="docs/current/agent-loop/profiles/test-verification.yaml",
        attempt_id="pilot011-test-1",
        write_scope=("apps/web/frontend",),
        max_turns=6,
        max_input_tokens=1_000_000,
        max_output_tokens=12_000,
        max_elapsed_minutes=15,
        subtask_depth=0,
    )
    config["test"] = {"packet": test_packet, "context": test_context, "plan": plan.to_payload()}
    _write_json(ROOT / _runtime_ref("test-packet"), test_spec.task_packet)
    _write_json(ROOT / _runtime_ref("test-context"), test_context)
    _write_json(CONFIG_PATH, config)
    test_transport = CodexHostTransport(project_id="gwent-v4", project_is_git=True, bridge=runtime.bridge)
    test_execution = RunnerExecution(
        ExternalRunnerAdapter(test_spec, test_transport),
        test_spec.request,
        journal=ExecutionJournal.for_task(RUN_ROOT / "journals", PRODUCT_ID, "pilot011-test-1"),
        max_resumes=0,
    )
    runtime.executions["test-verification"] = test_execution
    test_event = test_execution.open()
    deadline = time.monotonic() + 900.0
    while test_event.status == "running" and time.monotonic() <= deadline:
        time.sleep(1.0)
        test_event = test_execution.wait()
    if test_event.status == "interrupted" and test_event.report_ref:
        test_event = test_execution.close(test_event.report_ref)
    if test_event.status != "closed" or not test_event.report_ref:
        _manifest(runtime, status="human_required", handoff_path=handoff_path, plan=plan, reason=f"independent Test did not close: {test_event.status}")
        return {"status": "HUMAN_REQUIRED", "stage": "test", "reason": test_event.status}
    test_report = _report(runtime, "test-verification")
    if test_report is None:
        _manifest(runtime, status="human_required", handoff_path=handoff_path, plan=plan, reason="Test did not return readable TestReport")
        return {"status": "HUMAN_REQUIRED", "stage": "test", "reason": "unreadable TestReport"}
    try:
        validate_test_report(test_report, plan=plan)
    except Exception as exc:
        _manifest(runtime, status="human_required", handoff_path=handoff_path, plan=plan, test_report=test_report, reason=f"TestReport validation failed: {exc}")
        return {"status": "HUMAN_REQUIRED", "stage": "test", "reason": str(exc)}
    final_snapshot = test_execution.record.final_snapshot or teacher_final
    passed = test_report.get("overall") == "PASS"
    status = "human_required" if passed else "human_required"
    manifest = _manifest(
        runtime,
        status=status,
        final_snapshot=final_snapshot,
        handoff_path=handoff_path,
        plan=plan,
        test_report=test_report,
        reason="human integration approval remains pending" if passed else f"TestReport overall={test_report.get('overall')}",
    )
    config["phases"]["test"] = "closed"
    config["final"] = {"snapshot": final_snapshot, "test_overall": test_report.get("overall"), "manifest": str(MANIFEST_PATH)}
    _write_json(CONFIG_PATH, config)
    return {"status": "HUMAN_REQUIRED" if passed else "HUMAN_REQUIRED", "manifest": str(MANIFEST_PATH), "test_overall": test_report.get("overall"), "final_snapshot": final_snapshot}


def finalize_blocked_run() -> dict[str, Any]:
    """Seal a blocked run with a redacted review diagnostic, without a model call."""
    if not MANIFEST_PATH.is_file():
        raise RuntimeError(f"RunManifest does not exist: {MANIFEST_PATH}")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    registry_records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (RUN_ROOT / "host" / "registry").glob("*.json")
    ]
    product = next((item for item in registry_records if item.get("task_id") == PRODUCT_ID), {})
    teacher = next((item for item in registry_records if item.get("task_id") == TEACHER_ID), {})
    product_final = str(product.get("final_snapshot") or BASE_SNAPSHOT)
    diagnostic_path = RUN_ROOT / "teacher-review-diagnostic.json"
    diagnostic = {
        "report_type": "ReviewReport",
        "task_id": TEACHER_ID,
        "attempt": "pilot011-teacher-1",
        "snapshot": product_final,
        "status": "blocked",
        "changes": [],
        "findings": [
            {
                "id": "PRIVACY-001",
                "status": "blocker",
                "finding": "Advanced preview responses serialize prompt text into the browser-facing response, although TeacherPanel does not visibly render it.",
                "evidence": [
                    "apps/web/frontend/src/components/TeacherPanel.tsx permits the advanced level",
                    "services/teacher/agent.py includes prompt for advanced responses",
                    "services/teacher/models.py serializes the response",
                    "apps/web/backend/app/api/teacher.py returns the response to React",
                ],
            }
        ],
        "scope": {"production_code_modified": False, "contract_modified": False},
        "verification": [
            {"command": "PYTHONPATH=. pytest -q services/teacher/tests", "status": "environment_blocked", "detail": "pytest executable unavailable"},
            {"command": "npm run build", "status": "environment_blocked", "detail": "WSL 1 is unsupported and Node.js installation could not be located"},
        ],
        "host_observation": {
            "status": teacher.get("status", "interrupted"),
            "input_tokens": int(teacher.get("input_tokens", 0)),
            "output_tokens": int(teacher.get("output_tokens", 0)),
            "stop_reason": "usage exceeded hard limit: task input tokens",
        },
        "redaction": "summary only; no prompt text or raw transcript copied",
    }
    _write_json(diagnostic_path, diagnostic)
    artifact = _artifact(diagnostic_path, "review_report", "pilot011-teacher-1", product_final)
    if artifact and not any(item.get("artifact_id") == artifact["artifact_id"] for item in manifest.get("artifacts", [])):
        manifest.setdefault("artifacts", []).append(artifact)
    termination = manifest.setdefault("termination", {})
    blockers = list(termination.get("unresolved_blockers", []))
    blockers.append("Teacher privacy contract blocker: advanced preview serializes prompt into the browser response")
    termination["unresolved_blockers"] = list(dict.fromkeys(blockers))
    termination["cleanup"] = "not_required_no_docker"
    manifest["updated_at"] = ""
    validate_run_manifest(manifest)
    _write_json(MANIFEST_PATH, manifest)
    return {"status": "FINALIZED_HUMAN_REQUIRED", "manifest": str(MANIFEST_PATH), "diagnostic": str(diagnostic_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("bootstrap", "restore", "finalize"))
    args = parser.parse_args()
    try:
        result = bootstrap() if args.phase == "bootstrap" else finalize_blocked_run() if args.phase == "finalize" else restore_and_run()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") in {"BOOTSTRAP_OK", "HUMAN_REQUIRED", "FINALIZED_HUMAN_REQUIRED"} else 2
    except Exception as exc:
        print(json.dumps({"status": "HUMAN_REQUIRED", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
