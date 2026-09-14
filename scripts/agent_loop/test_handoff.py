import unittest

from scripts.agent_loop.errors import ValidationError
from scripts.agent_loop.execution import RunnerExecution
from scripts.agent_loop.handoff import (
    ContractHandoffEnvelope,
    HandoffEnvelope,
    build_contract_handoff,
    build_handoff,
)
from scripts.agent_loop.runner import DeterministicRunner
from scripts.agent_loop.test_launch import build


class HandoffTests(unittest.TestCase):
    def make_closed_source(self):
        spec = build()
        execution = RunnerExecution(DeterministicRunner(), spec.request)
        execution.open()
        execution.close("change-report.yaml")
        return spec, execution

    def test_closed_owner_produces_scoped_verification_handoff(self):
        spec, execution = self.make_closed_source()
        handoff = build_handoff(
            spec,
            execution.record,
            to_role="test-verification",
            changed_paths=("apps/web/frontend/src/App.tsx",),
            verification_scope=("apps/web/frontend",),
        )
        self.assertIsInstance(handoff, HandoffEnvelope)
        payload = handoff.to_payload()
        self.assertEqual(payload["from_role"], "product")
        self.assertEqual(payload["to_role"], "test-verification")
        self.assertEqual(payload["snapshot"], "snapshot-1")
        self.assertIn("change-report.yaml", payload["artifact_refs"])

    def test_open_source_cannot_handoff(self):
        spec = build()
        execution = RunnerExecution(DeterministicRunner(), spec.request)
        execution.open()
        with self.assertRaisesRegex(ValidationError, "closed source Runner"):
            build_handoff(
                spec,
                execution.record,
                to_role="test-verification",
                verification_scope=("apps/web/frontend",),
            )

    def test_changed_path_cannot_escape_owner_scope(self):
        spec, execution = self.make_closed_source()
        with self.assertRaisesRegex(ValidationError, "exceeds write scope"):
            build_handoff(
                spec,
                execution.record,
                to_role="test-verification",
                changed_paths=("services/teacher/app.py",),
                verification_scope=("apps/web/frontend",),
            )

    def test_handoff_target_cannot_be_another_owner(self):
        spec, execution = self.make_closed_source()
        with self.assertRaisesRegex(ValidationError, "target role"):
            build_handoff(
                spec,
                execution.record,
                to_role="trainer",
                verification_scope=("apps/web/frontend",),
            )

    def test_closed_owner_produces_cross_domain_contract_handoff(self):
        spec, execution = self.make_closed_source()
        handoff = build_contract_handoff(
            spec,
            execution.record,
            to_role="core",
            contract_refs=("contracts/product-http.yaml", "docs/current/AGENTS.md"),
            contract_version="product-http:v1",
            consumer_scope=("apps/web/backend",),
            changed_paths=("apps/web/frontend/src/App.tsx",),
        )
        self.assertIsInstance(handoff, ContractHandoffEnvelope)
        payload = handoff.to_payload()
        self.assertEqual(payload["handoff_type"], "cross-domain-contract")
        self.assertEqual(payload["from_role"], "product")
        self.assertEqual(payload["to_role"], "core")
        self.assertEqual(payload["contract_version"], "product-http:v1")

    def test_contract_handoff_requires_contract_and_consumer_scope(self):
        spec, execution = self.make_closed_source()
        with self.assertRaisesRegex(ValidationError, "contract_refs"):
            build_contract_handoff(
                spec,
                execution.record,
                to_role="core",
                contract_refs=(),
                contract_version="product-http:v1",
                consumer_scope=("apps/web/backend",),
            )
        with self.assertRaisesRegex(ValidationError, "consumer_scope"):
            build_contract_handoff(
                spec,
                execution.record,
                to_role="core",
                contract_refs=("contracts/product-http.yaml",),
                contract_version="product-http:v1",
                consumer_scope=(),
            )

    def test_contract_handoff_cannot_target_test_agent(self):
        spec, execution = self.make_closed_source()
        with self.assertRaisesRegex(ValidationError, "different domain owner"):
            build_contract_handoff(
                spec,
                execution.record,
                to_role="test-verification",
                contract_refs=("contracts/product-http.yaml",),
                contract_version="product-http:v1",
                consumer_scope=("apps/web/backend",),
            )


if __name__ == "__main__":
    unittest.main()
