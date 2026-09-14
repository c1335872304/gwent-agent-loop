import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from .host_registry import HostSessionRecord, HostSessionRegistry, HostRegistryError


def record() -> HostSessionRecord:
    return HostSessionRecord(
        runner_ref="codex:local:thread-1",
        thread_id="thread-1",
        host_id="local",
        project_id="gwent-v4",
        task_id="TASK-1",
        task_revision=1,
        attempt_id="attempt-1",
        role="product",
        profile_revision="product@1",
        snapshot="abc123",
        write_scope=("apps/web",),
        session_dir="/tmp/agent-loop/task",
        worktree="/tmp/agent-loop/task/worktree",
        output_path="/tmp/agent-loop/task/last-message.json",
        stderr_path="/tmp/agent-loop/task/stderr.log",
        stdout_path="/tmp/agent-loop/task/stdout.log",
        pid=1234,
        status="running",
    )


class HostRegistryTests(unittest.TestCase):
    def test_round_trip_uses_stable_runner_reference_key(self):
        with TemporaryDirectory() as temp:
            registry = HostSessionRegistry(Path(temp) / "registry")
            saved = registry.put(record())
            loaded = registry.require(saved.runner_ref)
            self.assertEqual(loaded, saved)
            self.assertEqual(len(list((Path(temp) / "registry").glob("*.json"))), 1)

    def test_tampered_reference_is_rejected(self):
        with TemporaryDirectory() as temp:
            registry = HostSessionRegistry(Path(temp) / "registry")
            registry.put(record())
            path = next((Path(temp) / "registry").glob("*.json"))
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["runner_ref"] = "codex:local:other-thread"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(HostRegistryError):
                registry.require("codex:local:thread-1")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
