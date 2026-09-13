import unittest
from pathlib import Path

from scripts.agent_loop.errors import ValidationError
from scripts.agent_loop.test_verification import closed_product_handoff
from scripts.agent_loop.verification import build_verification_plan
from scripts.agent_loop.report_validation import validate_test_report
from scripts.agent_loop.validate_packet import load_yaml


ROOT = Path(__file__).resolve().parents[2]


def report(plan, overall="PASS"):
    results = [
        {
            "command": command["command"],
            "cwd": command["cwd"],
            "status": "PASS",
            "exit_code": 0,
            "duration_seconds": 1,
            "evidence_ref": f"evidence/{index}.log",
        }
        for index, command in enumerate(plan.commands)
    ]
    return {
        "task_id": plan.task_id,
        "packet_revision": plan.task_revision,
        "tested_snapshot": plan.snapshot,
        "tester": "test-verification",
        "overall": overall,
        "results": results,
        "environment": {
            "runner": "docker" if plan.docker_enabled else "host-diagnostic",
            "missing_dependencies": [],
            "docker": {
                "used": plan.docker_enabled,
                "compose_files": list(plan.docker_compose_files),
                "health": "passed" if plan.docker_enabled else "not_required",
                "cleanup": "complete" if plan.docker_enabled else "not_required",
                "evidence_refs": ["docker/health.log"] if plan.docker_enabled else [],
            },
        },
        "failures": [],
        "manual_checks": [],
        "changed_test_paths": [],
    }


class TestReportValidationTests(unittest.TestCase):
    def setUp(self):
        self.handoff = closed_product_handoff()
        self.profile = load_yaml(
            ROOT / "docs/current/agent-loop/profiles/test-verification.yaml"
        )
        self.matrix = load_yaml(ROOT / "docs/current/agent-loop/TEST_MATRIX.yaml")
        self.plan = build_verification_plan(
            self.handoff,
            test_profile=self.profile,
            test_matrix=self.matrix,
            verification_attempt_id="verify-1",
            command_ids=("product-backend", "product-frontend"),
            docker_enabled=True,
        )

    def test_pass_requires_complete_command_and_docker_evidence(self):
        validate_test_report(report(self.plan), plan=self.plan)

    def test_pass_with_not_run_command_is_rejected(self):
        bad = report(self.plan)
        bad["results"][0]["status"] = "NOT_RUN"
        bad["results"][0]["exit_code"] = None
        with self.assertRaisesRegex(ValidationError, "PASS TestReport"):
            validate_test_report(bad, plan=self.plan)

    def test_missing_docker_cleanup_evidence_is_rejected(self):
        bad = report(self.plan)
        bad["environment"]["docker"]["cleanup"] = "incomplete"
        with self.assertRaisesRegex(ValidationError, "complete cleanup"):
            validate_test_report(bad, plan=self.plan)

    def test_command_outside_plan_is_rejected(self):
        bad = report(self.plan)
        bad["results"][0]["command"] = "python scripts/unknown.py"
        with self.assertRaisesRegex(ValidationError, "outside VerificationPlan"):
            validate_test_report(bad, plan=self.plan)

    def test_failure_requires_classification_evidence(self):
        bad = report(self.plan, overall="FAIL")
        bad["results"][0]["status"] = "FAIL"
        bad["results"][0]["exit_code"] = 1
        bad["failures"] = [
            {
                "classification": "CODE_DEFECT",
                "reproduction": "command failed",
                "likely_owner": "product",
            }
        ]
        validate_test_report(bad, plan=self.plan)


if __name__ == "__main__":
    unittest.main()
