"""Regression tests for the Phase 1 Scheduler control protocol and socket service."""

from __future__ import annotations

import os
import tempfile
import unittest
import uuid
from pathlib import Path

from .control_protocol import SchedulerControl
from .control_service import ControlServiceError, SchedulerControlService, create_capability_token, read_capability_token
from .scheduler import Scheduler, SchedulerLimits
from .test_scheduler import FakeBackend, task_packet


class SchedulerControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw = tempfile.TemporaryDirectory()
        self.root = Path(self.raw.name)
        self.backend = FakeBackend()
        self.scheduler = Scheduler(
            self.backend,
            SchedulerLimits(1, 2, 2000, 1600, 8, 5),
            state_path=self.root / "scheduler.json",
        )
        self.scheduler.submit(task_packet("TASK-CONTROL"))
        self.scheduler.pump()
        self.control = SchedulerControl(self.scheduler, state_root=self.root / "control")

    def tearDown(self) -> None:
        self.raw.cleanup()

    def request(self, action: str, *, reason: str = "operator action", payload: dict | None = None, key: str | None = None, revision: int = 1, runner_ref: str | None = "fake:TASK-CONTROL") -> dict:
        return {
            "protocol_version": 1,
            "action": action,
            "task_id": "TASK-CONTROL",
            "expected_revision": revision if action not in {"inspect", "events"} else None,
            "expected_runner_ref": runner_ref,
            "actor": "user",
            "reason": reason,
            "idempotency_key": key or str(uuid.uuid4()),
            "payload": payload or {},
        }

    def test_pause_is_identity_bound_and_idempotent(self) -> None:
        request = self.request("pause")
        first = self.control.dispatch(request)
        replay = self.control.dispatch(request)
        self.assertEqual(first["status"], "OK")
        self.assertEqual(first["task_status"], "paused")
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(self.backend.paused, ["TASK-CONTROL"])
        self.assertEqual(self.scheduler.events[-1].actor, "user")

    def test_drift_fails_closed_without_touching_runner(self) -> None:
        response = self.control.dispatch(self.request("pause", revision=2))
        self.assertEqual(response["status"], "HUMAN_REQUIRED")
        self.assertIn("expected_revision", response["reason"])
        self.assertEqual(self.backend.paused, [])

    def test_prepare_resume_is_persisted_and_can_be_used_after_facade_restart(self) -> None:
        self.control.dispatch(self.request("pause"))
        prepared = self.control.dispatch(
            self.request(
                "prepare_resume",
                payload={
                    "facts": [
                        {
                            "claim": "Only update the already-declared UI presentation.",
                            "source_ref": "docs/current/agent-loop/TASK_PACKET_TEMPLATE.yaml",
                            "effect": "No TaskPacket revision change is needed.",
                        }
                    ]
                },
            )
        )
        artifact = Path(prepared["resume_artifact_ref"])
        self.assertTrue(artifact.is_file())
        restarted = SchedulerControl(self.scheduler, state_root=self.root / "control")
        resumed = restarted.dispatch(self.request("resume"))
        self.assertEqual(resumed["status"], "OK")
        self.assertEqual(resumed["task_status"], "running")
        self.assertEqual(resumed["resume_artifact_ref"], str(artifact))
        self.assertEqual(self.backend.resumed, ["TASK-CONTROL"])

    def test_resume_without_directive_stops_for_human(self) -> None:
        self.control.dispatch(self.request("pause"))
        response = self.control.dispatch(self.request("resume"))
        self.assertEqual(response["status"], "HUMAN_REQUIRED")
        self.assertIn("prepare_resume", response["reason"])
        self.assertEqual(self.backend.resumed, [])

    def test_events_returns_control_audit(self) -> None:
        self.control.dispatch(self.request("inspect", reason=""))
        response = self.control.dispatch(
            {
                "protocol_version": 1,
                "action": "events",
                "task_id": "TASK-CONTROL",
                "expected_revision": None,
                "expected_runner_ref": None,
                "actor": "user",
                "reason": "",
                "idempotency_key": str(uuid.uuid4()),
                "payload": {"after_seq": 0},
            }
        )
        self.assertEqual(response["status"], "OK")
        self.assertEqual(len(response["control_events"]), 1)
        self.assertTrue(response["scheduler_events"])

    def test_service_requires_a_private_capability_token(self) -> None:
        token_path = self.root / "token"
        created = create_capability_token(token_path)
        self.assertEqual(read_capability_token(token_path), created)
        service = SchedulerControlService(
            self.control,
            socket_path=self.root / "control.sock",
            capability_token=created,
            poll_interval_seconds=0.02,
        )
        self.assertEqual(service.socket_path, (self.root / "control.sock").resolve())
        os.chmod(token_path, 0o644)
        with self.assertRaises(ControlServiceError):
            read_capability_token(token_path)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
