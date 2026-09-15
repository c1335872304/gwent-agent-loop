import unittest
from dataclasses import replace

from scripts.agent_loop.codex_bridge import (
    CodexBridgeError,
    build_codex_thread_launch,
    parse_codex_thread_handle,
)
from scripts.agent_loop.test_launch import build


def git_spec():
    packet = build().task_packet.copy()
    packet["workspace"] = dict(packet["workspace"])
    packet["workspace"]["snapshot_kind"] = "git_commit"
    packet["title"] = "Bounded Product pilot"
    return build(task_packet=packet)


class CodexBridgeTests(unittest.TestCase):
    def test_builds_project_worktree_request_without_transcript(self):
        launch = build_codex_thread_launch(
            git_spec(), project_id="gwent-v4", project_is_git=True
        )
        payload = launch.to_payload()
        self.assertEqual(payload["target"]["type"], "project")
        self.assertEqual(
            payload["target"]["environment"]["startingState"]["branchName"],
            "snapshot-1",
        )
        self.assertNotIn("raw_transcript", payload)
        self.assertFalse(payload["spawn_policy"]["allow_child_tasks"])
        self.assertEqual(payload["structured_inputs"]["task_packet"]["task_id"], "TASK-1")
        self.assertIn("TaskPacket: tasks/TASK-1.yaml", launch.prompt)

    def test_verifier_prompt_requires_exact_test_report_shape(self):
        verifier = git_spec()
        verifier = replace(verifier, profile={**verifier.profile, "agent_id": "test-verification", "role_type": "verification"})
        verifier = replace(verifier, request=replace(verifier.request, role="test-verification"))
        launch = build_codex_thread_launch(
            verifier, project_id="gwent-v4", project_is_git=True
        )
        self.assertIn("tested_snapshot", launch.prompt)
        self.assertIn("exact full command string", launch.prompt)
        self.assertIn("status exactly to one of PASS, FAIL, NOT_RUN, or INCONCLUSIVE", launch.prompt)

    def test_requires_git_project_and_git_snapshot(self):
        with self.assertRaisesRegex(CodexBridgeError, "Git project"):
            build_codex_thread_launch(
                git_spec(), project_id="gwent-v4", project_is_git=False
            )
        with self.assertRaisesRegex(CodexBridgeError, "snapshot_kind"):
            build_codex_thread_launch(
                build(), project_id="gwent-v4", project_is_git=True
            )

    def test_rejects_unsafe_file_reference(self):
        with self.assertRaisesRegex(CodexBridgeError, "parent traversal"):
            build_codex_thread_launch(
                replace(git_spec(), task_packet_ref="../TASK-1.yaml"),
                project_id="gwent-v4",
                project_is_git=True,
            )

    def test_parses_thread_handle_and_runner_identity(self):
        handle = parse_codex_thread_handle({"threadId": "thread-1", "hostId": "local"})
        self.assertEqual(handle.runner_ref, "codex:local:thread-1")
        with self.assertRaisesRegex(CodexBridgeError, "thread_id"):
            parse_codex_thread_handle({})


if __name__ == "__main__":
    unittest.main()
