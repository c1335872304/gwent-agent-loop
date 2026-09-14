"""Run the model-free Stage 3 multi-role Scheduler canary.

The canary uses the same ``RunnerExecutionBackend`` path that a Codex Host
factory uses, but injects deterministic adapters so it is safe and repeatable
in architecture tests.  It proves role routing, serial admission, snapshot
restore/rebind, and a closed cross-domain contract handoff.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.agent_loop.execution import RunnerExecution
    from scripts.agent_loop.handoff import build_contract_handoff
    from scripts.agent_loop.runner import DeterministicRunner
    from scripts.agent_loop.scheduler import Scheduler, SchedulerLimits
    from scripts.agent_loop.scheduler_backend import MultiRoleRunnerExecutionBackend
    from scripts.agent_loop.test_launch import build, context, packet, profile
else:
    from .execution import RunnerExecution
    from .handoff import build_contract_handoff
    from .runner import DeterministicRunner
    from .scheduler import Scheduler, SchedulerLimits
    from .scheduler_backend import MultiRoleRunnerExecutionBackend
    from .test_launch import build, context, packet, profile


class CompletingAdapter:
    """Deterministic adapter that closes after one scheduler poll."""

    def __init__(self, task_id: str, final_snapshot: str) -> None:
        self.task_id = task_id
        self.final_snapshot = final_snapshot
        self.runner = DeterministicRunner()
        self.polls = 0

    def open(self, request):
        return self.runner.open(request)

    def wait(self, runner_ref):
        event = self.runner.wait(runner_ref)
        self.polls += 1
        if self.polls == 1:
            return replace(
                event,
                status="interrupted",
                report_ref=f"artifacts/{self.task_id}-change-report.json",
                final_snapshot=self.final_snapshot,
                changed_paths=("apps/web/frontend/src/App.tsx",),
                input_tokens=17,
                output_tokens=9,
                elapsed_seconds=0.4,
            )
        return event

    def interrupt(self, runner_ref, *, reason):
        return self.runner.interrupt(runner_ref, reason=reason)

    def resume(self, runner_ref, *, artifact_refs):
        return self.runner.resume(runner_ref, artifact_refs=artifact_refs)

    def close(self, runner_ref, *, report_ref):
        return replace(
            self.runner.close(runner_ref, report_ref=report_ref),
            final_snapshot=self.final_snapshot,
            changed_paths=("apps/web/frontend/src/App.tsx",),
            input_tokens=17,
            output_tokens=9,
            elapsed_seconds=0.4,
        )


def _spec(task_id: str, owner: str):
    task = copy.deepcopy(packet())
    task["task_id"] = task_id
    task["ownership"]["primary_owner"] = owner
    brief = context()
    brief["task_id"] = task_id
    role_profile = copy.deepcopy(profile())
    role_profile["agent_id"] = owner
    role_profile["profile_id"] = f"{owner}-owner-v1"
    role_profile["authority"]["boundary"] = owner
    return build(
        task_packet=task,
        context_brief=brief,
        profile=role_profile,
        task_packet_ref=f"tasks/{task_id}.yaml",
        context_brief_ref=f"context/{task_id}.yaml",
        profile_ref=f"profiles/{owner}.yaml",
        attempt_id=f"attempt-{task_id.lower()}",
    )


def run() -> dict:
    product_id = "STAGE3-PRODUCT-001"
    core_id = "STAGE3-CORE-001"
    specs = {
        "product": _spec(product_id, "product"),
        "core": _spec(core_id, "core"),
    }
    adapters = {
        "product": CompletingAdapter(product_id, "snapshot-product-final"),
        "core": CompletingAdapter(core_id, "snapshot-core-final"),
    }
    executions: dict[str, RunnerExecution] = {}
    started_roles: list[str] = []
    rebound: list[str] = []

    def create(task, _budget):
        owner = task.owner
        started_roles.append(owner)
        execution = RunnerExecution(adapters[owner], specs[owner].request)
        executions[task.task_id] = execution
        return execution

    def rebind(task, _budget, handle):
        rebound.append(f"{task.task_id}:{handle}")
        return executions[task.task_id]

    def backend():
        return MultiRoleRunnerExecutionBackend(
            {"product": create, "core": create},
            role_rebind_factories={"product": rebind, "core": rebind},
        )

    limits = SchedulerLimits(
        max_concurrency=1,
        max_tasks=2,
        max_input_tokens=2000,
        max_output_tokens=1600,
        max_model_turns=8,
        max_elapsed_minutes=5,
    )
    with tempfile.TemporaryDirectory(prefix="gwent-stage3-") as raw:
        state_path = Path(raw) / "scheduler.json"
        first_scheduler = Scheduler(backend(), limits, state_path=state_path)
        first_scheduler.submit(specs["product"].task_packet)
        first_scheduler.submit(specs["core"].task_packet)
        first_scheduler.pump()
        checkpoint = json.loads(state_path.read_text(encoding="utf-8"))

        restarted_backend = backend()
        restarted = Scheduler.restore(state_path, restarted_backend)
        restarted.pump()
        restarted.pump()

        product_record = executions[product_id].record
        contract_handoff = build_contract_handoff(
            specs["product"],
            product_record,
            to_role="core",
            contract_refs=("contracts/product-http.yaml",),
            contract_version="product-http:v1",
            consumer_scope=("apps/web/backend",),
            changed_paths=("apps/web/frontend/src/App.tsx",),
        )
        final = restarted.snapshot()
        result = {
            "status": "PASS",
            "mode": "serial-multi-role-model-free",
            "model_calls": 0,
            "docker": "not_run",
            "max_concurrency": 1,
            "started_roles": started_roles,
            "checkpoint_scheduler_status": checkpoint["scheduler_status"],
            "rebound": rebound,
            "task_statuses": {
                product_id: restarted.get_task(product_id).status,
                core_id: restarted.get_task(core_id).status,
            },
            "final_snapshot": final["tasks"][-1]["final_snapshot"],
            "scheduler_event_count": len(restarted.events),
            "contract_handoff": contract_handoff.to_payload(),
        }
    if result["started_roles"] != ["product", "core"]:
        raise RuntimeError("multi-role canary did not preserve serial role order")
    if result["rebound"] != [f"{product_id}:deterministic:{product_id}:attempt-{product_id.lower()}"]:
        raise RuntimeError("multi-role canary did not rebind the original Runner")
    if any(status != "completed" for status in result["task_statuses"].values()):
        raise RuntimeError(
            "multi-role canary did not complete every task: "
            + json.dumps(result["task_statuses"], ensure_ascii=False)
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    try:
        result = run()
        encoded = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded + "\n", encoding="utf-8")
        print(encoded)
        return 0
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
