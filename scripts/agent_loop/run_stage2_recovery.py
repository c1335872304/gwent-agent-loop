"""Run the phase-two loss/resume pilot and independent verification.

The pilot intentionally injects one loss into a real local Codex CLI Runner,
resumes the same thread once, and then runs the ordinary independent verifier.
It never merges the candidate into the caller's parent worktree.
"""

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
    from scripts.agent_loop.execution import ExecutionJournal, RunnerExecution
    from scripts.agent_loop.external import ExternalRunnerAdapter
    from scripts.agent_loop.launch import build_launch_spec, build_verification_launch_spec
    from scripts.agent_loop.run_bounded_loop import _limits
    from scripts.agent_loop.validate_packet import load_yaml
else:
    from .bounded_loop import SingleDomainLoop
    from .codex_cli_bridge import CodexCliBridge
    from .codex_host_transport import CodexHostTransport
    from .execution import ExecutionJournal, RunnerExecution
    from .external import ExternalRunnerAdapter
    from .launch import build_launch_spec, build_verification_launch_spec
    from .run_bounded_loop import _limits
    from .validate_packet import load_yaml


def _relative(path: Path, root: Path, label: str) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"{label} must be inside the project root") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--task-packet", type=Path, required=True)
    parser.add_argument("--context-brief", type=Path, required=True)
    parser.add_argument("--owner-profile", type=Path, required=True)
    parser.add_argument("--test-profile", type=Path, required=True)
    parser.add_argument("--test-matrix", type=Path, required=True)
    parser.add_argument("--owner-attempt-id", required=True)
    parser.add_argument("--verification-attempt-id", required=True)
    parser.add_argument("--owner-write-scope", action="append", required=True)
    parser.add_argument("--test-write-scope", action="append", required=True)
    parser.add_argument("--verification-scope", action="append", required=True)
    parser.add_argument("--command-id", action="append", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
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
    task_id = str(packet["task_id"])
    owner_budgets = _limits(packet, owner_profile, args)
    owner_spec = build_launch_spec(
        task_packet=packet,
        context_brief=context,
        profile=owner_profile,
        task_packet_ref=_relative(args.task_packet, root, "TaskPacket"),
        context_brief_ref=_relative(args.context_brief, root, "ContextBrief"),
        profile_ref=_relative(args.owner_profile, root, "Owner profile"),
        attempt_id=args.owner_attempt_id,
        write_scope=tuple(args.owner_write_scope),
        max_turns=owner_budgets[0],
        max_input_tokens=owner_budgets[1],
        max_output_tokens=owner_budgets[2],
        max_elapsed_minutes=owner_budgets[3],
        subtask_depth=0,
    )
    bridge = CodexCliBridge(
        {args.project_id: root},
        worktree_root=root / ".agent-loop" / "worktrees",
        artifact_root=root / ".agent-loop" / "host-artifacts",
    )

    def make_execution(spec: object) -> RunnerExecution:
        transport = CodexHostTransport(
            project_id=args.project_id,
            project_is_git=True,
            bridge=bridge,
        )
        adapter = ExternalRunnerAdapter(spec, transport)
        journal = ExecutionJournal.for_task(root / ".agent-loop", task_id, spec.request.attempt_id)
        return RunnerExecution(adapter, spec.request, journal=journal, max_resumes=1)

    owner_execution = make_execution(owner_spec)
    opened = owner_execution.open()
    owner_transport = owner_execution.adapter.transport
    initial = owner_execution.last_event
    initial_deadline = time.monotonic() + 300
    while initial is not None and initial.status == "running" and time.monotonic() <= initial_deadline:
        time.sleep(0.5)
        initial = owner_execution.wait()
    if initial is None or initial.status != "interrupted" or not initial.report_ref:
        raise RuntimeError("initial Codex rollout did not finish before loss injection")
    owner_transport.inject_loss(opened.runner_ref, reason="phase-two controlled Runner loss")
    lost = owner_execution.wait()
    if lost.status != "lost":
        raise RuntimeError(f"loss injection did not produce lost status: {lost.status}")
    loss_ref = root / ".agent-loop" / "tasks" / task_id / "artifacts" / f"{args.owner_attempt_id}-loss.json"
    loss_ref.parent.mkdir(parents=True, exist_ok=True)
    loss_ref.write_text(
        json.dumps({"reason": lost.reason, "runner_ref": lost.runner_ref}, indent=2) + "\n",
        encoding="utf-8",
    )
    decision = owner_execution.recover(
        artifact_refs=[_relative(loss_ref, root, "loss evidence")],
        failure_class="RUNNER_FAILURE",
        remaining_budget=1,
    )
    if decision.action != "RESUME_SAME_RUNNER":
        raise RuntimeError(f"controlled loss was not resumable: {decision.action}")

    def wait_for_close(execution: RunnerExecution) -> None:
        event = execution.last_event
        deadline = time.monotonic() + 300
        while event is not None and time.monotonic() <= deadline:
            if event.status == "running":
                time.sleep(0.5)
                event = execution.wait()
                continue
            if event.status == "interrupted" and event.report_ref:
                execution.close(event.report_ref)
                return
            if event.status == "closed":
                return
            raise RuntimeError(f"Runner stopped in {event.status}: {event.reason}")
        raise RuntimeError("Runner exceeded phase-two bounded wait")

    wait_for_close(owner_execution)

    def make_verifier(handoff, plan):
        budgets = _limits(packet, test_profile, args)
        spec = build_verification_launch_spec(
            owner_spec,
            handoff,
            test_profile=test_profile,
            attempt_id=args.verification_attempt_id,
            task_packet_ref=f".agent-loop/runtime/{task_id}/verification-task.json",
            context_brief_ref=f".agent-loop/runtime/{task_id}/verification-context.json",
            profile_ref=f".agent-loop/runtime/{task_id}/verification-profile.json",
            write_scope=tuple(args.test_write_scope),
            max_turns=budgets[0],
            max_input_tokens=budgets[1],
            max_output_tokens=budgets[2],
            max_elapsed_minutes=budgets[3],
        )
        return spec, make_execution(spec)

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
        human_approved=False,
        max_wait_seconds=300,
        poll_interval_seconds=0.5,
        verifier_factory=make_verifier,
    ).run()
    return {
        "task_id": task_id,
        "status": result.manifest["status"],
        "recovery_action": decision.action,
        "recovery_decisions": result.owner_record.recovery_decisions,
        "owner_report": result.owner_record.report_ref,
        "test_report": result.verifier_record.report_ref,
        "final_snapshot": result.manifest["workspace"]["final_snapshot"],
        "manifest": str(args.manifest),
    }


def main() -> int:
    try:
        result = run(build_parser().parse_args())
    except Exception as exc:  # CLI boundary: preserve a bounded, classified failure.
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
