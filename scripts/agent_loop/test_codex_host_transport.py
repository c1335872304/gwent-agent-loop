import unittest

from scripts.agent_loop.codex_host_transport import (
    CodexHostTransport,
    CodexHostTransportError,
)
from scripts.agent_loop.external import ExternalRunnerAdapter
from scripts.agent_loop.execution import RunnerExecution
from scripts.agent_loop.test_codex_bridge import git_spec


class FakeCodexHostBridge:
    def __init__(self):
        self.created = None
        self.wait_status = {"status": "running"}
        self.rebound = None

    def create_task(self, payload):
        self.created = payload
        return {"threadId": "thread-1", "hostId": "local"}

    def wait_task(self, handle):
        return dict(self.wait_status)

    def rebind_task(self, handle, *, payload):
        self.rebound = (handle.runner_ref, payload)
        return {"status": "running", "resume_count": 1}

    def interrupt_task(self, handle, *, reason):
        return {"status": "interrupted", "reason": reason}

    def resume_task(self, handle, *, artifact_refs):
        return {"status": "running"}

    def close_task(self, handle, *, report_ref):
        return {
            "status": "completed",
            "report_ref": "stable-report.yaml",
            "final_snapshot": "final-1",
            "changed_paths": ["apps/web/frontend/src/App.tsx"],
        }

    def inject_loss(self, handle, *, reason):
        return {"status": "lost", "reason": reason}


class CodexHostTransportTests(unittest.TestCase):
    def test_rebind_uses_persisted_reference_without_create(self):
        spec = git_spec()
        bridge = FakeCodexHostBridge()
        transport = CodexHostTransport(
            project_id="gwent-v4", project_is_git=True, bridge=bridge
        )

        rebound = transport.rebind(spec.to_payload(), "codex:local:thread-1")

        self.assertEqual(rebound["event"], "rebound")
        self.assertEqual(rebound["runner_ref"], "codex:local:thread-1")
        self.assertEqual(rebound["resume_count"], 1)
        self.assertIsNotNone(bridge.rebound)
        self.assertIsNone(bridge.created)

    def test_round_trip_maps_host_lifecycle_to_runner_execution(self):
        spec = git_spec()
        bridge = FakeCodexHostBridge()
        transport = CodexHostTransport(
            project_id="gwent-v4", project_is_git=True, bridge=bridge
        )
        execution = RunnerExecution(
            ExternalRunnerAdapter(spec, transport), spec.request, max_resumes=2
        )

        execution.open()
        execution.wait()
        execution.interrupt("verification")
        execution.resume(["change-report.yaml"])
        closed = execution.close("test-report.yaml")

        self.assertEqual(closed.status, "closed")
        self.assertEqual(closed.runner_ref, "codex:local:thread-1")
        self.assertEqual(closed.report_ref, "stable-report.yaml")
        self.assertEqual(closed.final_snapshot, "final-1")
        self.assertEqual(closed.changed_paths, ("apps/web/frontend/src/App.tsx",))
        self.assertEqual(bridge.created["project_id"], "gwent-v4")
        self.assertFalse(bridge.created["spawn_policy"]["allow_child_tasks"])

    def test_completed_wait_requires_explicit_close(self):
        spec = git_spec()
        bridge = FakeCodexHostBridge()
        bridge.wait_status = {"status": "completed", "report_ref": "report.yaml"}
        transport = CodexHostTransport(
            project_id="gwent-v4", project_is_git=True, bridge=bridge
        )
        execution = RunnerExecution(
            ExternalRunnerAdapter(spec, transport), spec.request
        )
        execution.open()
        event = execution.wait()
        self.assertEqual(event.status, "interrupted")
        self.assertEqual(execution.close("report.yaml").status, "closed")

    def test_unknown_or_unexplained_host_failure_stops(self):
        spec = git_spec()
        bridge = FakeCodexHostBridge()
        bridge.wait_status = {"status": "failed"}
        transport = CodexHostTransport(
            project_id="gwent-v4", project_is_git=True, bridge=bridge
        )
        execution = RunnerExecution(
            ExternalRunnerAdapter(spec, transport), spec.request
        )
        execution.open()
        with self.assertRaisesRegex(CodexHostTransportError, "unsupported"):
            execution.wait()

    def test_blocked_host_failure_requires_reason(self):
        spec = git_spec()
        bridge = FakeCodexHostBridge()
        bridge.wait_status = {"status": "blocked"}
        transport = CodexHostTransport(
            project_id="gwent-v4", project_is_git=True, bridge=bridge
        )
        execution = RunnerExecution(
            ExternalRunnerAdapter(spec, transport), spec.request
        )
        execution.open()
        with self.assertRaisesRegex(CodexHostTransportError, "requires a reason"):
            execution.wait()

    def test_controlled_loss_hook_maps_to_lost_runner_event(self):
        spec = git_spec()
        transport = CodexHostTransport(
            project_id="gwent-v4", project_is_git=True, bridge=FakeCodexHostBridge()
        )
        execution = RunnerExecution(
            ExternalRunnerAdapter(spec, transport), spec.request, max_resumes=1
        )
        opened = execution.open()
        lost = transport.inject_loss(opened.runner_ref, reason="field trial")
        self.assertEqual(lost["status"], "lost")


if __name__ == "__main__":
    unittest.main()
