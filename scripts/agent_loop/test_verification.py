import copy
import unittest
from pathlib import Path

from scripts.agent_loop.errors import ValidationError
from scripts.agent_loop.handoff import build_handoff
from scripts.agent_loop.runner import DeterministicRunner
from scripts.agent_loop.execution import RunnerExecution
from scripts.agent_loop.test_launch import build
from scripts.agent_loop.validate_packet import load_yaml
from scripts.agent_loop.verification import VerificationPlan, build_verification_plan


ROOT = Path(__file__).resolve().parents[2]


def closed_product_handoff():
    spec = build()
    execution = RunnerExecution(DeterministicRunner(), spec.request)
    execution.open()
    execution.close("change-report.yaml")
    return build_handoff(
        spec,
        execution.record,
        to_role="test-verification",
        changed_paths=("apps/web/frontend/src/App.tsx",),
        verification_scope=("apps/web/frontend",),
    )


class VerificationPlanTests(unittest.TestCase):
    def setUp(self):
        self.handoff = closed_product_handoff()
        self.profile = load_yaml(
            ROOT / "docs/current/agent-loop/profiles/test-verification.yaml"
        )
        self.matrix = load_yaml(ROOT / "docs/current/agent-loop/TEST_MATRIX.yaml")

    def test_plan_selects_only_allowlisted_product_commands(self):
        plan = build_verification_plan(
            self.handoff,
            test_profile=self.profile,
            test_matrix=self.matrix,
            verification_attempt_id="verify-1",
            command_ids=("product-backend", "product-frontend"),
            docker_enabled=True,
        )
        self.assertIsInstance(plan, VerificationPlan)
        self.assertEqual(plan.domain, "product")
        self.assertEqual(plan.snapshot, "snapshot-1")
        self.assertTrue(plan.docker_enabled)
        self.assertTrue(plan.cleanup_required)
        self.assertEqual(plan.docker_compose_files, ("deploy/docker/compose.cpu.yml",))
        payload = plan.to_payload()
        self.assertEqual(payload["command_ids"], ["product-backend", "product-frontend"])
        self.assertEqual(payload["artifact_refs"], ["change-report.yaml"])

    def test_unknown_command_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "not in TestMatrix"):
            build_verification_plan(
                self.handoff,
                test_profile=self.profile,
                test_matrix=self.matrix,
                verification_attempt_id="verify-1",
                command_ids=("product-deploy",),
            )

    def test_non_test_profile_is_rejected(self):
        bad_profile = copy.deepcopy(self.profile)
        bad_profile["agent_id"] = "product"
        bad_profile["profile_id"] = "product-owner-v1"
        bad_profile["role_type"] = "domain_owner"
        with self.assertRaisesRegex(ValidationError, "test-verification profile"):
            build_verification_plan(
                self.handoff,
                test_profile=bad_profile,
                test_matrix=self.matrix,
                verification_attempt_id="verify-1",
                command_ids=("product-backend",),
            )

    def test_docker_requires_profile_compose_ownership(self):
        limited_profile = copy.deepcopy(self.profile)
        limited_profile["docker"]["allowed"] = False
        limited_profile["docker"]["compose_files"] = []
        with self.assertRaisesRegex(ValidationError, "Docker policy is not ready"):
            build_verification_plan(
                self.handoff,
                test_profile=limited_profile,
                test_matrix=self.matrix,
                verification_attempt_id="verify-1",
                command_ids=("product-backend",),
                docker_enabled=True,
            )


if __name__ == "__main__":
    unittest.main()
