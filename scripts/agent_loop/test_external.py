import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from scripts.agent_loop.errors import ValidationError
from scripts.agent_loop.external import ExternalRunnerAdapter, ExternalRunnerError
from scripts.agent_loop.execution import ExecutionJournal, RunnerExecution
from scripts.agent_loop.runner import DeterministicRunner, RunnerRequest, runner_event_dict
from scripts.agent_loop.test_launch import build


class MemoryTransport:
    def __init__(self):
        self.runner = DeterministicRunner()
        self.open_payload = None

    def open(self, payload):
        self.open_payload = payload
        request = payload["request"]
        runner_request = RunnerRequest(
            task_id=request["task_id"],
            task_revision=request["task_revision"],
            attempt_id=request["attempt_id"],
            role=request["role"],
            profile_revision=request["profile_revision"],
            snapshot=request["snapshot"],
            write_scope=tuple(request["write_scope"]),
            max_turns=request["max_turns"],
        )
        return runner_event_dict(self.runner.open(runner_request))

    def wait(self, runner_ref):
        return runner_event_dict(self.runner.wait(runner_ref))

    def rebind(self, payload, runner_ref):
        event = runner_event_dict(self.runner.wait(runner_ref))
        event["event"] = "rebound"
        return event

    def interrupt(self, runner_ref, *, reason):
        return runner_event_dict(self.runner.interrupt(runner_ref, reason=reason))

    def resume(self, runner_ref, *, artifact_refs):
        return runner_event_dict(
            self.runner.resume(runner_ref, artifact_refs=artifact_refs)
        )

    def close(self, runner_ref, *, report_ref):
        return runner_event_dict(
            self.runner.close(runner_ref, report_ref=report_ref)
        )


class ExternalRunnerTests(unittest.TestCase):
    def test_execution_rebind_hydrates_journal_without_opening_runner(self):
        spec = build()
        transport = MemoryTransport()
        with TemporaryDirectory() as temp:
            journal = ExecutionJournal(Path(temp) / "runner.json")
            original = RunnerExecution(
                ExternalRunnerAdapter(spec, transport), spec.request, journal=journal
            )
            opened = original.open()
            original.wait()

            rebound = RunnerExecution.rebind(
                ExternalRunnerAdapter(spec, transport),
                spec.request,
                journal.load(),
                journal=journal,
            )
            self.assertEqual(rebound.record.runner_ref, opened.runner_ref)
            self.assertEqual(rebound.record.status, "running")
            self.assertEqual(rebound.record.events[-1]["event"], "rebound")

    def test_adapter_round_trip_uses_structured_launch_payload(self):
        spec = build()
        transport = MemoryTransport()
        execution = RunnerExecution(
            ExternalRunnerAdapter(spec, transport), spec.request
        )

        execution.open()
        execution.wait()
        execution.interrupt("verification")
        execution.resume(["change-report.yaml"])
        closed = execution.close("test-report.yaml")

        self.assertEqual(closed.status, "closed")
        self.assertEqual(transport.open_payload["task_packet"]["task_id"], "TASK-1")
        self.assertEqual(
            transport.open_payload["context_brief"]["context_snapshot"],
            "snapshot-1",
        )
        self.assertNotIn("raw_transcript", transport.open_payload["context_brief"])

    def test_malformed_external_response_is_rejected(self):
        class MalformedTransport(MemoryTransport):
            def open(self, payload):
                return {"runner_ref": "bad"}

        spec = build()
        adapter = ExternalRunnerAdapter(spec, MalformedTransport())
        with self.assertRaisesRegex(ExternalRunnerError, "missing fields"):
            adapter.open(spec.request)

    def test_external_reference_mismatch_is_rejected(self):
        class WrongReferenceTransport(MemoryTransport):
            def wait(self, runner_ref):
                event = super().wait(runner_ref)
                event["runner_ref"] = "other-runner"
                return event

        spec = build()
        adapter = ExternalRunnerAdapter(spec, WrongReferenceTransport())
        execution = RunnerExecution(adapter, spec.request)
        execution.open()
        with self.assertRaisesRegex(ExternalRunnerError, "reference mismatch"):
            execution.wait()


if __name__ == "__main__":
    unittest.main()
