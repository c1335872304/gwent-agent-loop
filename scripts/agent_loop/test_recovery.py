import unittest

from scripts.agent_loop.recovery import decide_recovery


class RecoveryPolicyTests(unittest.TestCase):
    def test_lost_runner_resumes_only_within_limit(self):
        decision = decide_recovery(status="LOST", resumes_used=1, max_resumes=2)
        self.assertEqual(decision.action, "RESUME_SAME_RUNNER")
        self.assertTrue(decision.consumes_model_call)

        blocked = decide_recovery(status="LOST", resumes_used=2, max_resumes=2)
        self.assertEqual(blocked.action, "WAIT_HUMAN")
        self.assertFalse(blocked.consumes_model_call)

    def test_budget_and_invalid_report_are_hard_stops(self):
        budget = decide_recovery(status="FAIL", remaining_budget=0)
        self.assertEqual(budget.action, "STOP_BUDGET")

        report = decide_recovery(status="FAIL", report_valid=False)
        self.assertEqual(report.action, "WAIT_HUMAN")
        self.assertTrue(report.requires_human)

    def test_environment_does_not_trigger_model_retry(self):
        decision = decide_recovery(
            status="FAIL", failure_class="DOCKER_FAILURE", remaining_budget=99
        )
        self.assertEqual(decision.action, "WAIT_HUMAN")
        self.assertFalse(decision.consumes_model_call)

    def test_owner_retry_is_bounded(self):
        retry = decide_recovery(
            status="FAIL", failure_class="CODE_DEFECT", attempts_used=0
        )
        self.assertEqual(retry.action, "RETURN_TO_OWNER")
        self.assertTrue(retry.consumes_model_call)

        stopped = decide_recovery(
            status="FAIL", failure_class="CODE_DEFECT", attempts_used=2, max_attempts=2
        )
        self.assertEqual(stopped.action, "WAIT_HUMAN")

    def test_protocol_failure_is_not_retried(self):
        decision = decide_recovery(status="FAIL", failure_class="PROTOCOL_FAILURE")
        self.assertEqual(decision.action, "STOP")
        self.assertTrue(decision.terminal)


if __name__ == "__main__":
    unittest.main()
