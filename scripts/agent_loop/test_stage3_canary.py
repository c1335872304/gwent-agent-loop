"""Regression test for the bounded Stage 3 multi-role canary."""

from __future__ import annotations

import unittest

from .run_stage3_canary import run


class Stage3CanaryTests(unittest.TestCase):
    def test_serial_multi_role_restart_and_contract_handoff(self):
        result = run()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(result["docker"], "not_run")
        self.assertEqual(result["started_roles"], ["product", "core"])
        self.assertEqual(result["task_statuses"], {
            "STAGE3-PRODUCT-001": "completed",
            "STAGE3-CORE-001": "completed",
        })
        self.assertEqual(result["contract_handoff"]["to_role"], "core")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
