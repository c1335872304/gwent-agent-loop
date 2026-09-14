"""Continue phase-two verification from a persisted, recovered Owner run."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.agent_loop.bounded_loop import SingleDomainLoop
    from scripts.agent_loop.codex_cli_bridge import CodexCliBridge
    from scripts.agent_loop.codex_host_transport import CodexHostTransport
    from scripts.agent_loop.execution import ExecutionIdentity, ExecutionJournal, ExecutionRecord, RunnerExecution
    from scripts.agent_loop.external import ExternalRunnerAdapter
    from scripts.agent_loop.launch import build_launch_spec, build_verification_launch_spec
    from scripts.agent_loop.run_bounded_loop import _limits
    from scripts.agent_loop.runner import RunnerEvent
    from scripts.agent_loop.validate_packet import load_yaml
else:
    from .bounded_loop import SingleDomainLoop
    from .codex_cli_bridge import CodexCliBridge
    from .codex_host_transport import CodexHostTransport
    from .execution import ExecutionIdentity, ExecutionJournal, ExecutionRecord, RunnerExecution
    from .external import ExternalRunnerAdapter
    from .launch import build_launch_spec, build_verification_launch_spec
    from .run_bounded_loop import _limits
    from .runner import RunnerEvent
    from .validate_packet import load_yaml


def _relative(path: Path, root: Path, label: str) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"{label} must be inside the project root") from exc


def _event(payload: dict) -> RunnerEvent:
    return RunnerEvent(
        runner_ref=str(payload["runner_ref"]),
        event=str(payload["event"]),
        status=str(payload["status"]),  # type: ignore[arg-type]
        task_id=str(payload["task_id"]),
        task_revision=int(payload["task_revision"]),
        attempt_id=str(payload["attempt_id"]),
        profile_revision=str(payload["profile_revision"]),
        snapshot=str(payload["snapshot"]),
        write_scope=tuple(str(item) for item in payload["write_scope"]),
        resume_count=int(payload["resume_count"]),
        report_ref=str(payload["report_ref"]) if payload.get("report_ref") else None,
        reason=str(payload["reason"]) if payload.get("reason") else None,
        final_snapshot=str(payload["final_snapshot"]) if payload.get("final_snapshot") else None,
        changed_paths=tuple(str(item) for item in payload.get("changed_paths", [])),
        input_tokens=int(payload.get("input_tokens", 0)),
        output_tokens=int(payload.get("output_tokens", 0)),
        elapsed_seconds=float(payload.get("elapsed_seconds", 0.0)),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--task-packet", type=Path, required=True)
    parser.add_argument("--context-brief", type=Path, required=True)
    parser.add_argument("--owner-profile", type=Path, required=True)
    parser.add_argument("--test-profile", type=Path, required=True)
    parser.add_argument("--test-matrix", type=Path, required=True)
    parser.add_argument("--owner-journal", type=Path, required=True)
    parser.add_argument(
        "--owner-final-snapshot",
        default="",
        help="post-integration snapshot to verify without rerunning the Owner",
    )
    parser.add_argument("--verification-attempt-id", required=True)
    parser.add_argument("--test-write-scope", action="append", required=True)
    parser.add_argument("--verification-scope", action="append", required=True)
    parser.add_argument("--command-id", action="append", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--human-approved", action="store_true")
    parser.add_argument("--max-turns", type=int, default=None)
    parser.add_argument("--max-input-tokens", type=int, default=None)
    parser.add_argument("--max-output-tokens", type=int, default=None)
    parser.add_argument("--max-elapsed-minutes", type=int, default=None)
    return parser


def run(args: argparse.Namespace) -> dict:
    root = args.project_root.resolve()
    packet = load_yaml(args.task_packet)
    context = load_yaml(args.context_brief)
    owner_profile = load_yaml(args.owner_profile)
    test_profile = load_yaml(args.test_profile)
    test_matrix = load_yaml(args.test_matrix)
    owner_payload = json.loads(args.owner_journal.read_text(encoding="utf-8"))
    owner_final_snapshot = str(args.owner_final_snapshot or owner_payload.get("final_snapshot", "")).strip()
    owner_budgets = _limits(packet, owner_profile, args)
    owner_spec = build_launch_spec(
        task_packet=packet,
        context_brief=context,
        profile=owner_profile,
        task_packet_ref=_relative(args.task_packet, root, "TaskPacket"),
        context_brief_ref=_relative(args.context_brief, root, "ContextBrief"),
        profile_ref=_relative(args.owner_profile, root, "Owner profile"),
        attempt_id=str(owner_payload["identity"]["attempt_id"]),
        write_scope=tuple(str(item) for item in owner_payload["identity"]["write_scope"]),
        max_turns=owner_budgets[0],
        max_input_tokens=owner_budgets[1],
        max_output_tokens=owner_budgets[2],
        max_elapsed_minutes=owner_budgets[3],
        subtask_depth=0,
    )
    identity = ExecutionIdentity.from_request(owner_spec.request)
    owner_record = ExecutionRecord(
        identity,
        runner_ref=owner_payload.get("runner_ref"),
        status=str(owner_payload["status"]),
        resume_count=int(owner_payload.get("resume_count", 0)),
        events=list(owner_payload.get("events", [])),
        artifact_refs=list(owner_payload.get("artifact_refs", [])),
        report_ref=owner_payload.get("report_ref"),
        last_reason=owner_payload.get("last_reason"),
        final_snapshot=owner_payload.get("final_snapshot"),
        changed_paths=list(owner_payload.get("changed_paths", [])),
        recovery_decisions=list(owner_payload.get("recovery_decisions", [])),
        input_tokens=int(owner_payload.get("input_tokens", 0)),
        output_tokens=int(owner_payload.get("output_tokens", 0)),
        elapsed_seconds=float(owner_payload.get("elapsed_seconds", 0.0)),
    )
    if owner_record.status != "closed" or not owner_final_snapshot:
        raise RuntimeError("Owner journal must contain a closed recovered run with final_snapshot")
    owner_record.final_snapshot = owner_final_snapshot
    owner_execution = RunnerExecution(object(), owner_spec.request, max_resumes=1)
    owner_execution.record = owner_record
    owner_execution._opened = True
    owner_execution._last_event = _event(owner_record.events[-1])

    bridge = CodexCliBridge(
        {args.project_id: root},
        worktree_root=root / ".agent-loop" / "worktrees",
        artifact_root=root / ".agent-loop" / "host-artifacts",
    )
    verifier_execution: RunnerExecution | None = None

    def make_verifier(handoff, _plan):
        nonlocal verifier_execution
        budgets = _limits(packet, test_profile, args)
        spec = build_verification_launch_spec(
            owner_spec,
            handoff,
            test_profile=test_profile,
            attempt_id=args.verification_attempt_id,
            task_packet_ref=f".agent-loop/runtime/{packet['task_id']}/verification-task.json",
            context_brief_ref=f".agent-loop/runtime/{packet['task_id']}/verification-context.json",
            profile_ref=f".agent-loop/runtime/{packet['task_id']}/verification-profile.json",
            write_scope=tuple(args.test_write_scope),
            max_turns=budgets[0],
            max_input_tokens=budgets[1],
            max_output_tokens=budgets[2],
            max_elapsed_minutes=budgets[3],
        )
        transport = CodexHostTransport(project_id=args.project_id, project_is_git=True, bridge=bridge)
        verifier_execution = RunnerExecution(
            ExternalRunnerAdapter(spec, transport),
            spec.request,
            journal=ExecutionJournal.for_task(root / ".agent-loop", str(packet["task_id"]), args.verification_attempt_id),
            max_resumes=1,
        )
        return spec, verifier_execution

    try:
        result = SingleDomainLoop(
            owner_spec=owner_spec,
            owner_execution=owner_execution,
            test_profile=test_profile,
            test_matrix=test_matrix,
            verification_attempt_id=args.verification_attempt_id,
            command_ids=tuple(args.command_id),
            docker_enabled=False,
            verification_scope=tuple(args.verification_scope),
            report_loader=bridge.read_report,
            manifest_path=args.manifest,
            human_approved=args.human_approved,
            max_wait_seconds=300,
            poll_interval_seconds=0.5,
            verifier_factory=make_verifier,
        ).run()
    except BaseException:
        if verifier_execution is not None:
            transport = verifier_execution.adapter.transport
            handle = getattr(transport, "_handle", None)
            if handle is not None:
                bridge.cleanup_task(handle)
        raise
    return {
        "task_id": packet["task_id"],
        "status": result.manifest["status"],
        "recovery_decisions": owner_record.recovery_decisions,
        "test_report": result.verifier_record.report_ref,
        "final_snapshot": result.manifest["workspace"]["final_snapshot"],
        "manifest": str(args.manifest),
    }


def main() -> int:
    try:
        result = run(build_parser().parse_args())
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
