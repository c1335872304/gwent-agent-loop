"""Run one live, bounded Owner -> Test/Verification loop through Codex CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.agent_loop.bounded_loop import SingleDomainLoop
    from scripts.agent_loop.codex_cli_bridge import CodexCliBridge
    from scripts.agent_loop.codex_host_transport import CodexHostTransport
    from scripts.agent_loop.execution import ExecutionJournal, RunnerExecution
    from scripts.agent_loop.external import ExternalRunnerAdapter
    from scripts.agent_loop.launch import build_launch_spec, build_verification_launch_spec
    from scripts.agent_loop.validate_packet import load_yaml
else:
    from .bounded_loop import SingleDomainLoop
    from .codex_cli_bridge import CodexCliBridge
    from .codex_host_transport import CodexHostTransport
    from .execution import ExecutionJournal, RunnerExecution
    from .external import ExternalRunnerAdapter
    from .launch import build_launch_spec, build_verification_launch_spec
    from .validate_packet import load_yaml


def _relative(path: Path, root: Path, label: str) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"{label} must be inside the project root") from exc


def _limits(packet: dict, profile: dict, args: argparse.Namespace) -> tuple[int, int, int, int]:
    execution = packet["execution"]
    profile_limits = profile["execution_limits"]
    return (
        int(args.max_turns or execution["max_model_turns"]),
        min(int(args.max_input_tokens or execution["max_model_input_tokens"]), int(profile_limits["max_input_tokens"])),
        min(int(args.max_output_tokens or execution["max_model_output_tokens"]), int(profile_limits["max_output_tokens"])),
        min(int(args.max_elapsed_minutes or execution["max_elapsed_minutes"]), int(profile_limits["max_elapsed_minutes"])),
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
    parser.add_argument("--owner-attempt-id", required=True)
    parser.add_argument("--verification-attempt-id", required=True)
    parser.add_argument("--owner-write-scope", action="append", required=True)
    parser.add_argument("--test-write-scope", action="append", required=True)
    parser.add_argument("--verification-scope", action="append", required=True)
    parser.add_argument("--command-id", action="append", required=True)
    parser.add_argument("--test-task-packet-ref", default="")
    parser.add_argument("--test-context-brief-ref", default="")
    parser.add_argument("--test-profile-ref", default="")
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--max-turns", type=int, default=None)
    parser.add_argument("--max-input-tokens", type=int, default=None)
    parser.add_argument("--max-output-tokens", type=int, default=None)
    parser.add_argument("--max-elapsed-minutes", type=int, default=None)
    parser.add_argument("--docker", action="store_true")
    parser.add_argument("--human-approved", action="store_true")
    return parser


def run(args: argparse.Namespace) -> dict:
    root = args.project_root.resolve()
    packet = load_yaml(args.task_packet)
    context = load_yaml(args.context_brief)
    owner_profile = load_yaml(args.owner_profile)
    test_profile = load_yaml(args.test_profile)
    test_matrix = load_yaml(args.test_matrix)
    owner_packet_ref = _relative(args.task_packet, root, "TaskPacket")
    owner_context_ref = _relative(args.context_brief, root, "ContextBrief")
    owner_profile_ref = _relative(args.owner_profile, root, "Owner profile")
    task_id = str(packet["task_id"])
    test_packet_ref = args.test_task_packet_ref or f".agent-loop/runtime/{task_id}/verification-task.json"
    test_context_ref = args.test_context_brief_ref or f".agent-loop/runtime/{task_id}/verification-context.json"
    test_profile_ref = args.test_profile_ref or f".agent-loop/runtime/{task_id}/verification-profile.json"
    owner_budgets = _limits(packet, owner_profile, args)
    owner_spec = build_launch_spec(
        task_packet=packet,
        context_brief=context,
        profile=owner_profile,
        task_packet_ref=owner_packet_ref,
        context_brief_ref=owner_context_ref,
        profile_ref=owner_profile_ref,
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

    def make_execution(spec):
        transport = CodexHostTransport(
            project_id=args.project_id,
            project_is_git=True,
            bridge=bridge,
        )
        adapter = ExternalRunnerAdapter(spec, transport)
        journal = ExecutionJournal.for_task(root / ".agent-loop", task_id, spec.request.attempt_id)
        return RunnerExecution(adapter, spec.request, journal=journal, max_resumes=2)

    def make_verifier(handoff, _plan):
        budgets = _limits(packet, test_profile, args)
        spec = build_verification_launch_spec(
            owner_spec,
            handoff,
            test_profile=test_profile,
            attempt_id=args.verification_attempt_id,
            task_packet_ref=test_packet_ref,
            context_brief_ref=test_context_ref,
            profile_ref=test_profile_ref,
            write_scope=tuple(args.test_write_scope),
            max_turns=budgets[0],
            max_input_tokens=budgets[1],
            max_output_tokens=budgets[2],
            max_elapsed_minutes=budgets[3],
        )
        return spec, make_execution(spec)

    manifest_path = args.manifest or root / ".agent-loop" / "tasks" / task_id / "run-manifest.json"
    result = SingleDomainLoop(
        owner_spec=owner_spec,
        owner_execution=make_execution(owner_spec),
        test_profile=test_profile,
        test_matrix=test_matrix,
        verification_attempt_id=args.verification_attempt_id,
        command_ids=tuple(args.command_id),
        docker_enabled=args.docker,
        verification_scope=tuple(args.verification_scope),
        report_loader=bridge.read_report,
        manifest_path=manifest_path,
        human_approved=args.human_approved,
        verifier_factory=make_verifier,
    ).run()
    return {
        "task_id": task_id,
        "status": result.manifest["status"],
        "base_snapshot": result.handoff.snapshot,
        "final_snapshot": result.manifest["workspace"]["final_snapshot"],
        "manifest": str(manifest_path),
        "owner_report": result.owner_record.report_ref,
        "test_report": result.verifier_record.report_ref,
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
