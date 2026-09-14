import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.agent_loop.codex_bridge import parse_codex_thread_handle
from scripts.agent_loop.codex_cli_bridge import CodexCliBridge, CodexCliBridgeError


FAKE_CODEX = r'''
import json
import os
import sys
import time
from pathlib import Path

args = sys.argv[1:]
if args and args[0] == "exec" and len(args) > 1 and args[1] == "resume":
    args = ["exec", *args[2:]]
if "-C" in args:
    os.chdir(args[args.index("-C") + 1])
output = Path(args[args.index("--output-last-message") + 1])
print(json.dumps({"type": "thread.started", "thread_id": "fake-thread"}), flush=True)
if args and args[-1] == "sleep":
    time.sleep(30)
Path("allowed.txt").write_text("changed\n", encoding="utf-8")
output.write_text(json.dumps({"overall": "PASS"}), encoding="utf-8")
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 11, "output_tokens": 7}}), flush=True)
'''


REBINDSCRIPT = r'''
import json
import sys
from scripts.agent_loop.codex_bridge import parse_codex_runner_ref
from scripts.agent_loop.codex_cli_bridge import CodexCliBridge

root, worktrees, artifacts, registry, payload, runner_ref = sys.argv[1:]
bridge = CodexCliBridge(
    {"project": root},
    codex_command=(sys.executable, "-c", "raise SystemExit(99)"),
    worktree_root=worktrees,
    artifact_root=artifacts,
    session_registry_root=registry,
    startup_timeout=2,
)
result = bridge.rebind_task(
    parse_codex_runner_ref(runner_ref),
    payload=json.loads(payload),
)
print(json.dumps(result, sort_keys=True))
'''


class CodexCliBridgeTests(unittest.TestCase):
    def test_host_docker_sandbox_requires_explicit_test_capability(self):
        base = {
            "task": {"role": "test-verification"},
            "task_packet": {
                "execution": {"host_docker": True},
                "acceptance": {"verification_commands": ["python3 scripts/check.py docker-test"]},
            },
            "profile": {"docker": {"allowed": True}},
        }
        self.assertEqual(CodexCliBridge._sandbox_mode(base), "danger-full-access")

        ordinary = {
            **base,
            "task_packet": {
                "execution": {"host_docker": False},
                "acceptance": {"verification_commands": []},
            },
        }
        self.assertEqual(CodexCliBridge._sandbox_mode(ordinary), "workspace-write")

        product = {**base, "task": {"role": "product"}}
        with self.assertRaisesRegex(CodexCliBridgeError, "restricted to test-verification"):
            CodexCliBridge._sandbox_mode(product)

    def test_new_bridge_process_rebinds_existing_host_session(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "allowed.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(root), "add", "allowed.txt"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
            base = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
            worktrees = root / "worktrees"
            artifacts = root / "artifacts"
            registry = root / "registry"
            bridge = CodexCliBridge(
                {"project": root},
                codex_command=(sys.executable, "-c", FAKE_CODEX),
                worktree_root=worktrees,
                artifact_root=artifacts,
                session_registry_root=registry,
                startup_timeout=2,
                stop_timeout=1,
            )
            payload = {
                "protocol_version": 1,
                "project_id": "project",
                "target": {"type": "project", "environment": {"type": "worktree", "startingState": {"branchName": base}}},
                "task": {"task_id": "TASK-REBIND", "attempt_id": "attempt-1", "role": "product", "snapshot": base, "write_scope": ["allowed.txt"]},
                "prompt": "sleep",
            }
            handle = parse_codex_thread_handle(bridge.create_task(payload))
            record = bridge.session_registry.require(handle.runner_ref)
            helper = Path(__file__).resolve().parents[2]
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    REBINDSCRIPT,
                    str(root),
                    str(worktrees),
                    str(artifacts),
                    str(registry),
                    json.dumps(payload),
                    handle.runner_ref,
                ],
                cwd=helper,
                env={**os.environ, "PYTHONPATH": str(helper)},
                check=True,
                capture_output=True,
                text=True,
            )
            rebound = json.loads(result.stdout)
            self.assertEqual(rebound["status"], "running")
            self.assertEqual(rebound["runner_ref"], handle.runner_ref)
            self.assertEqual(bridge.session_registry.require(handle.runner_ref).pid, record.pid)
            self.assertEqual(bridge.session_registry.require(handle.runner_ref).attempt_id, "attempt-1")
            bridge.interrupt_task(handle, reason="rebind test cleanup")
            bridge.cleanup_task(handle)

    def test_creates_isolated_worktree_commits_scope_and_preserves_report(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "allowed.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(root), "add", "allowed.txt"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
            base = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
            bridge = CodexCliBridge(
                {"project": root},
                codex_command=(sys.executable, "-c", FAKE_CODEX),
                worktree_root=root / "worktrees",
                artifact_root=root / "artifacts",
                startup_timeout=2,
            )
            payload = {
                "protocol_version": 1,
                "project_id": "project",
                "target": {
                    "type": "project",
                    "environment": {
                        "type": "worktree",
                        "startingState": {"branchName": base},
                    },
                },
                "task": {
                    "task_id": "TASK-1",
                    "attempt_id": "attempt-1",
                    "role": "product",
                    "snapshot": base,
                    "write_scope": ["allowed.txt"],
                },
                "prompt": "bounded test",
            }
            created = bridge.create_task(payload)
            handle = parse_codex_thread_handle(created)
            result = {"status": "running"}
            for _ in range(20):
                result = bridge.wait_task(handle)
                if result["status"] != "running":
                    break
                time.sleep(0.01)
            self.assertEqual(result["status"], "completed")
            closed = bridge.close_task(handle, report_ref=result["report_ref"])
            self.assertEqual(closed["changed_paths"], ["allowed.txt"])
            self.assertEqual(closed["input_tokens"], 11)
            self.assertEqual(closed["output_tokens"], 7)
            self.assertGreater(closed["elapsed_seconds"], 0)
            self.assertNotEqual(closed["final_snapshot"], base)
            self.assertTrue(Path(closed["report_ref"]).is_file())
            self.assertEqual(
                subprocess.check_output(
                    ["git", "-C", str(root), "show", f"{closed['final_snapshot']}:allowed.txt"],
                    text=True,
                ),
                "changed\n",
            )

    def test_interrupt_and_resume_reuse_the_same_thread(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "allowed.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(root), "add", "allowed.txt"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
            base = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
            bridge = CodexCliBridge(
                {"project": root},
                codex_command=(sys.executable, "-c", FAKE_CODEX),
                worktree_root=root / "worktrees",
                artifact_root=root / "artifacts",
                startup_timeout=2,
                stop_timeout=1,
            )
            payload = {
                "protocol_version": 1,
                "project_id": "project",
                "target": {"type": "project", "environment": {"type": "worktree", "startingState": {"branchName": base}}},
                "task": {"task_id": "TASK-2", "attempt_id": "attempt-1", "role": "product", "snapshot": base, "write_scope": ["allowed.txt"]},
                "prompt": "sleep",
            }
            handle = parse_codex_thread_handle(bridge.create_task(payload))
            self.assertEqual(bridge.wait_task(handle)["status"], "running")
            self.assertEqual(bridge.interrupt_task(handle, reason="bounded stop")["status"], "interrupted")
            self.assertEqual(bridge.resume_task(handle, artifact_refs=("change-report.json",))["status"], "running")
            for _ in range(20):
                result = bridge.wait_task(handle)
                if result["status"] != "running":
                    break
                time.sleep(0.01)
            self.assertEqual(result["status"], "completed")
            closed = bridge.close_task(handle, report_ref=result["report_ref"])
            self.assertEqual(closed["changed_paths"], ["allowed.txt"])
            self.assertEqual(closed["input_tokens"], 11)
            self.assertEqual(closed["output_tokens"], 7)

    def test_duplicate_detached_snapshot_uses_isolated_force_fallback(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "allowed.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(root), "add", "allowed.txt"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
            base = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
            existing = root / "existing"
            subprocess.run(["git", "-C", str(root), "worktree", "add", "--detach", str(existing), base], check=True)
            self.addCleanup(lambda: subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(existing)], check=False, capture_output=True))
            bridge = CodexCliBridge(
                {"project": root},
                codex_command=(sys.executable, "-c", FAKE_CODEX),
                worktree_root=root / "worktrees",
                artifact_root=root / "artifacts",
                startup_timeout=2,
            )
            payload = {
                "protocol_version": 1,
                "project_id": "project",
                "target": {"type": "project", "environment": {"type": "worktree", "startingState": {"branchName": base}}},
                "task": {"task_id": "TASK-DUPLICATE", "attempt_id": "attempt-1", "role": "product", "snapshot": base, "write_scope": ["allowed.txt"]},
                "prompt": "bounded test",
            }
            handle = parse_codex_thread_handle(bridge.create_task(payload))
            result = bridge.wait_task(handle)
            for _ in range(20):
                if result["status"] != "running":
                    break
                time.sleep(0.01)
                result = bridge.wait_task(handle)
            self.assertEqual(result["status"], "completed")
            closed = bridge.close_task(handle, report_ref=result["report_ref"])
            self.assertEqual(closed["changed_paths"], ["allowed.txt"])
            self.assertTrue(existing.is_dir())
            self.assertEqual((existing / "allowed.txt").read_text(encoding="utf-8"), "base\n")

    def test_controlled_loss_is_visible_and_resumes_same_thread(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "allowed.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(root), "add", "allowed.txt"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
            base = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
            bridge = CodexCliBridge(
                {"project": root},
                codex_command=(sys.executable, "-c", FAKE_CODEX),
                worktree_root=root / "worktrees",
                artifact_root=root / "artifacts",
                startup_timeout=2,
                stop_timeout=1,
            )
            payload = {
                "protocol_version": 1,
                "project_id": "project",
                "target": {"type": "project", "environment": {"type": "worktree", "startingState": {"branchName": base}}},
                "task": {"task_id": "TASK-LOSS", "attempt_id": "attempt-1", "role": "product", "snapshot": base, "write_scope": ["allowed.txt"]},
                "prompt": "bounded test",
            }
            handle = parse_codex_thread_handle(bridge.create_task(payload))
            for _ in range(20):
                result = bridge.wait_task(handle)
                if result["status"] != "running":
                    break
                time.sleep(0.01)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(bridge.inject_loss(handle, reason="controlled phase-two loss")["status"], "lost")
            self.assertEqual(bridge.wait_task(handle)["status"], "lost")
            self.assertEqual(bridge.resume_task(handle, artifact_refs=("loss.json",))["status"], "running")
            for _ in range(20):
                result = bridge.wait_task(handle)
                if result["status"] != "running":
                    break
                time.sleep(0.01)
            self.assertEqual(result["status"], "completed")
            closed = bridge.close_task(handle, report_ref=result["report_ref"])
            self.assertEqual(closed["changed_paths"], ["allowed.txt"])
            self.assertEqual(closed["input_tokens"], 22)
            self.assertEqual(closed["output_tokens"], 14)


if __name__ == "__main__":
    unittest.main()
