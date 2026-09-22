"""Protocol regressions for the main-control MCP adapter."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from .control_mcp_server import ControlMcpServer, MCP_PROTOCOL_VERSION


class ControlMcpServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.requests: list[dict] = []

        def sender(request):
            self.requests.append(dict(request))
            return {
                "status": "OK",
                "task_id": request["task_id"],
                "task_revision": request.get("expected_revision"),
                "runner_ref": request.get("expected_runner_ref"),
            }

        self.server = ControlMcpServer(
            socket_path=Path("/tmp/agent-loop-control.sock"),
            token_file=Path("/tmp/agent-loop-control.token"),
            request_sender=sender,
        )

    def test_initialize_and_tool_catalog_expose_only_control_actions(self) -> None:
        initialized = self.server.handle({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
        })
        self.assertEqual(initialized["result"]["protocolVersion"], MCP_PROTOCOL_VERSION)
        listed = self.server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = [tool["name"] for tool in listed["result"]["tools"]]
        self.assertEqual(names, ["loop_inspect", "loop_submit", "loop_pause", "loop_prepare_resume", "loop_resume", "loop_cancel"])

    def test_submit_is_a_declared_task_request_not_a_task_payload_upload(self) -> None:
        response = self.server.handle({
            "jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {"name": "loop_submit", "arguments": {
                "task_id": "TASK-017", "reason": "user approved starting the declared canary",
                "task_packet_ref": ".agent-loop/tasks/TASK-017.json",
            }},
        })
        self.assertFalse(response["result"]["isError"])
        request = self.requests[-1]
        self.assertEqual(request["action"], "submit")
        self.assertEqual(request["actor"], "main_control")
        self.assertEqual(request["payload"], {"task_packet_ref": ".agent-loop/tasks/TASK-017.json"})
        invalid = self.server.handle({
            "jsonrpc": "2.0", "id": 8, "method": "tools/call",
            "params": {"name": "loop_submit", "arguments": {
                "task_id": "TASK-017", "reason": "try arbitrary payload", "task_packet": {"task_id": "TASK-017"},
            }},
        })
        self.assertEqual(invalid["error"]["code"], -32602)

    def test_mutation_is_main_control_and_identity_bound(self) -> None:
        response = self.server.handle({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "loop_pause", "arguments": {
                "task_id": "TASK-017", "expected_revision": 2,
                "expected_runner_ref": "codex:local:thread-17", "reason": "user asked to pause",
            }},
        })
        self.assertFalse(response["result"]["isError"])
        request = self.requests[-1]
        self.assertEqual(request["action"], "pause")
        self.assertEqual(request["actor"], "main_control")
        self.assertEqual(request["expected_revision"], 2)
        self.assertEqual(request["expected_runner_ref"], "codex:local:thread-17")
        self.assertTrue(request["idempotency_key"])

    def test_resume_facts_are_minimal_and_server_errors_are_reported(self) -> None:
        self.server.handle({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "loop_prepare_resume", "arguments": {
                "task_id": "TASK-017", "expected_revision": 2,
                "expected_runner_ref": "codex:local:thread-17", "reason": "clarified acceptance",
                "facts": [{"claim": "keep scope", "source_ref": "user-message-2", "effect": "continue"}],
            }},
        })
        self.assertEqual(self.requests[-1]["payload"]["facts"][0]["claim"], "keep scope")
        invalid = self.server.handle({
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "loop_pause", "arguments": {"task_id": "TASK-017"}},
        })
        self.assertEqual(invalid["error"]["code"], -32602)
        self.assertEqual(len(self.requests), 1)

    def test_human_required_is_preserved_as_a_tool_error(self) -> None:
        def blocked(_request):
            return {"status": "HUMAN_REQUIRED", "reason": "revision drift"}

        server = ControlMcpServer(
            socket_path="/tmp/socket", token_file="/tmp/token", request_sender=blocked
        )
        response = server.handle({
            "jsonrpc": "2.0", "id": 6, "method": "tools/call",
            "params": {"name": "loop_inspect", "arguments": {"task_id": "TASK-017"}},
        })
        self.assertTrue(response["result"]["isError"])
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload["status"], "HUMAN_REQUIRED")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
