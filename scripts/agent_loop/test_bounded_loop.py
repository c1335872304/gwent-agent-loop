import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts.agent_loop.bounded_loop import SingleDomainLoop
from scripts.agent_loop.execution import RunnerExecution
from scripts.agent_loop.launch import build_verification_launch_spec
from scripts.agent_loop.runner import DeterministicRunner
from scripts.agent_loop.test_launch import build
from scripts.agent_loop.validate_packet import load_yaml


ROOT = Path(__file__).resolve().parents[2]


class OneShotRunner(DeterministicRunner):
    def __init__(self, report_ref=None):
        super().__init__()
        self.report_ref = report_ref

    def wait(self, runner_ref):
        return replace(
            super().wait(runner_ref),
            status="interrupted",
            report_ref=self.report_ref,
            final_snapshot="final-snapshot",
            changed_paths=("apps/web/frontend/src/App.tsx",),
        )

    def close(self, runner_ref, *, report_ref):
        return replace(
            super().close(runner_ref, report_ref=report_ref),
            final_snapshot="final-snapshot",
            changed_paths=("apps/web/frontend/src/App.tsx",),
        )


class BoundedLoopTests(unittest.TestCase):
    def test_runs_owner_handoff_and_independent_verifier_with_manifest(self):
        packet = copy.deepcopy(build().task_packet)
        packet["execution"] = dict(packet["execution"])
        packet["execution"].update({"max_subtasks": 1, "max_role_runs": 2, "max_model_turns": 8})
        owner_spec = build(task_packet=packet)
        test_profile = load_yaml(ROOT / "docs/current/agent-loop/profiles/test-verification.yaml")
        test_matrix = load_yaml(ROOT / "docs/current/agent-loop/TEST_MATRIX.yaml")

        with tempfile.TemporaryDirectory() as temp:
            report_path = Path(temp) / "test-report.json"
            report_path.write_text("{}\n", encoding="utf-8")
            owner_execution = RunnerExecution(OneShotRunner("change-report.json"), owner_spec.request)
            handoff_seed = type("HandoffSeed", (), {"final_snapshot": "final-snapshot"})()
            verifier_spec = build_verification_launch_spec(
                owner_spec,
                handoff_seed,
                test_profile=test_profile,
                attempt_id="verify-1",
                task_packet_ref=owner_spec.task_packet_ref,
                context_brief_ref=owner_spec.context_brief_ref,
                profile_ref="profiles/test-verification.yaml",
                write_scope=("apps/web/backend/tests",),
                max_turns=2,
                max_input_tokens=900,
                max_output_tokens=700,
                max_elapsed_minutes=15,
            )
            verifier_execution = RunnerExecution(OneShotRunner(str(report_path)), verifier_spec.request)

            def load_report(_ref):
                return {
                    "task_id": "TASK-1",
                    "packet_revision": 1,
                    "tested_snapshot": "final-snapshot",
                    "tester": "test-verification",
                    "overall": "PASS",
                    "results": [
                        {
                            "command": "PYTHONPATH=apps/web/backend pytest -q apps/web/backend/tests",
                            "cwd": ".",
                            "status": "PASS",
                            "exit_code": 0,
                            "evidence_ref": "evidence/backend.log",
                        }
                    ],
                    "environment": {
                        "runner": "host-diagnostic",
                        "missing_dependencies": [],
                        "docker": {"used": False},
                    },
                    "failures": [],
                    "manual_checks": [],
                    "changed_test_paths": [],
                }

            result = SingleDomainLoop(
                owner_spec=owner_spec,
                verifier_spec=verifier_spec,
                owner_execution=owner_execution,
                verifier_execution=verifier_execution,
                test_profile=test_profile,
                test_matrix=test_matrix,
                verification_attempt_id="verify-1",
                command_ids=("product-backend",),
                docker_enabled=False,
                verification_scope=("apps/web/frontend",),
                report_loader=load_report,
                manifest_path=Path(temp) / "run-manifest.json",
                human_approved=True,
                max_wait_seconds=2,
                poll_interval_seconds=0.001,
            ).run()

            self.assertEqual(result.handoff.final_snapshot, "final-snapshot")
            self.assertEqual(result.verification_plan.snapshot, "final-snapshot")
            self.assertEqual(result.manifest["status"], "completed")
            self.assertTrue((Path(temp) / "run-manifest.json").is_file())
            saved = json.loads((Path(temp) / "run-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["workspace"]["final_snapshot"], "final-snapshot")
            self.assertEqual(len(saved["role_runs"]), 2)
            self.assertEqual(saved["retry_learning"]["retry_count"], 0)
            self.assertEqual(saved["retry_learning"]["savings"]["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
