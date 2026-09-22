"""Regression coverage for the config-backed service assembly."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

from .control_runtime import ControlRuntime, ControlRuntimeError
from .test_launch import build, context, packet, profile


class ControlRuntimeTests(unittest.TestCase):
    def _runtime_fixture(self, temp: str) -> tuple[ControlRuntime, str]:
        root = Path(temp) / "project"
        root.mkdir()
        (root / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "base"], check=True)
        snapshot = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        raw_packet = packet(snapshot)
        raw_packet["workspace"]["snapshot_kind"] = "git_commit"
        raw_packet["scope"]["allowed_write_paths"] = ["README.md"]
        spec = build(
            task_packet=raw_packet, context_brief=context(snapshot), profile=profile(),
            task_packet_ref=".agent-loop/tasks/TASK-1.json", context_brief_ref=".agent-loop/context/TASK-1.json",
            profile_ref=".agent-loop/profiles/product.json", write_scope=("README.md",),
        )
        state = Path(temp) / "state"
        config = {
            "schema": "agent-loop.control-runtime.v1", "project_id": "project", "project_root": str(root), "state_root": str(state),
            "host": {"codex_command": ["codex"], "worktree_root": str(state / "worktrees"), "artifact_root": str(state / "artifacts"), "session_registry_root": str(state / "registry")},
            "scheduler_limits": {"max_concurrency": 1, "max_tasks": 1, "max_input_tokens": 1000, "max_output_tokens": 800, "max_model_turns": 4, "max_elapsed_minutes": 20},
            "launch_specs": {"TASK-1": spec.to_payload()},
        }
        return self._write_runtime_config(temp, config), snapshot

    def _write_runtime_config(self, temp: str, config: dict) -> ControlRuntime:
        config_path = Path(temp) / "runtime.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        return ControlRuntime(config_path)

    def test_declared_specs_are_preloaded_without_creating_a_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime, _snapshot = self._runtime_fixture(temp)
            runtime.config["preload_task_ids"] = ["TASK-1"]
            runtime = self._write_runtime_config(temp, runtime.config)
            task = runtime.scheduler.get_task("TASK-1")
            self.assertEqual(task.status, "queued")
            self.assertIsNone(task.handle)
            response = runtime.control().dispatch({
                "protocol_version": 1, "action": "inspect", "task_id": "TASK-1", "expected_revision": None,
                "expected_runner_ref": None, "actor": "main_control", "reason": "", "idempotency_key": str(uuid.uuid4()), "payload": {},
            })
            self.assertEqual(response["status"], "OK")

    def test_host_model_and_reasoning_are_bound_to_cli_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime, _snapshot = self._runtime_fixture(temp)
            runtime.config["host"]["model"] = "gpt-5.6-luna"
            runtime.config["host"]["model_reasoning_effort"] = "xhigh"
            runtime = self._write_runtime_config(temp, runtime.config)
            self.assertEqual(runtime.bridge.model, "gpt-5.6-luna")
            self.assertEqual(runtime.bridge.model_reasoning_effort, "xhigh")

    def test_submit_admits_only_a_declared_launch_spec(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime, _snapshot = self._runtime_fixture(temp)
            control = runtime.control()
            response = control.dispatch({
                "protocol_version": 1, "action": "submit", "task_id": "TASK-1", "expected_revision": 1,
                "expected_runner_ref": None, "actor": "main_control", "reason": "start declared task",
                "idempotency_key": str(uuid.uuid4()), "payload": {"task_packet_ref": ".agent-loop/tasks/TASK-1.json"},
            })
            self.assertEqual(response["status"], "OK")
            self.assertEqual(response["task_status"], "queued")
            blocked = control.dispatch({
                "protocol_version": 1, "action": "submit", "task_id": "TASK-2", "expected_revision": None,
                "expected_runner_ref": None, "actor": "main_control", "reason": "try undeclared task",
                "idempotency_key": str(uuid.uuid4()), "payload": {},
            })
            self.assertEqual(blocked["status"], "HUMAN_REQUIRED")
            self.assertIn("declared", blocked["reason"])

    def test_rejects_a_runtime_without_declared_launch_specs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "runtime.json"
            path.write_text(json.dumps({"schema": "agent-loop.control-runtime.v1"}), encoding="utf-8")
            with self.assertRaisesRegex(ControlRuntimeError, "project_id"):
                ControlRuntime(path)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
