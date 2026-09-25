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
        self.assertEqual(names, ["loop_inspect", "loop_submit", "loop_update", "loop_pause", "loop_prepare_resume", "loop_resume", "loop_cancel"])

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

    def test_loop_update_pauses_records_and_resumes_the_same_runner(self) -> None:
        responses = {
            "inspect": {"status": "OK", "task_revision": 3, "runner_ref": "codex:local:thread-17", "task_status": "running"},
            "pause": {"status": "OK", "task_revision": 3, "runner_ref": "codex:local:thread-17", "task_status": "paused"},
            "prepare_resume": {"status": "OK", "task_revision": 3, "runner_ref": "codex:local:thread-17", "task_status": "paused", "resume_artifact_ref": "directive.json"},
            "resume": {"status": "OK", "task_revision": 3, "runner_ref": "codex:local:thread-17", "task_status": "running", "resume_artifact_ref": "directive.json"},
        }

        def sender(request):
            self.requests.append(dict(request))
            return responses[request["action"]]

        server = ControlMcpServer(socket_path="/tmp/socket", token_file="/tmp/token", request_sender=sender)
        arguments = {
            "task_id": "TASK-017",
            "reason": "user added a privacy constraint",
            "facts": [{"claim": "Do not expose hidden AI cards.", "source_ref": "user-message", "effect": "add privacy constraint"}],
        }
        response = server.handle({
            "jsonrpc": "2.0", "id": 9, "method": "tools/call",
            "params": {"name": "loop_update", "arguments": arguments},
        })
        self.assertFalse(response["result"]["isError"])
        result = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(result["direct_stage"], "completed")
        self.assertTrue(result["same_runner_resumed"])
        self.assertEqual([item["action"] for item in self.requests], ["inspect", "pause", "prepare_resume", "resume"])
        self.assertTrue(all(item["expected_runner_ref"] in {None, "codex:local:thread-17"} for item in self.requests))
        self.assertEqual(self.requests[2]["payload"]["facts"], arguments["facts"])
        self.assertTrue(all(item["actor"] == "main_control" for item in self.requests))
        first_write_keys = [item["idempotency_key"] for item in self.requests if item["action"] != "inspect"]

        repeated = server.handle({
            "jsonrpc": "2.0", "id": 9, "method": "tools/call",
            "params": {"name": "loop_update", "arguments": arguments},
        })
        self.assertFalse(repeated["result"]["isError"])
        repeated_write_keys = [item["idempotency_key"] for item in self.requests if item["action"] != "inspect"]
        self.assertEqual(repeated_write_keys[len(first_write_keys):], first_write_keys)

    def test_loop_update_on_paused_runner_skips_pause_and_fails_closed_on_completed(self) -> None:
        requests: list[dict] = []

        def paused_sender(request):
            requests.append(dict(request))
            state = "paused" if request["action"] != "resume" else "running"
            return {
                "status": "OK", "task_revision": 4,
                "runner_ref": "codex:local:thread-18", "task_status": state,
            }

        server = ControlMcpServer(socket_path="/tmp/socket", token_file="/tmp/token", request_sender=paused_sender)
        arguments = {
            "task_id": "TASK-018", "reason": "clarified acceptance",
            "facts": [{"claim": "Keep the existing scope.", "source_ref": "user-message", "effect": "clarification"}],
        }
        response = server.handle({
            "jsonrpc": "2.0", "id": 10, "method": "tools/call",
            "params": {"name": "loop_update", "arguments": arguments},
        })
        self.assertFalse(response["result"]["isError"])
        self.assertEqual([item["action"] for item in requests], ["inspect", "prepare_resume", "resume"])

        completed = ControlMcpServer(
            socket_path="/tmp/socket", token_file="/tmp/token",
            request_sender=lambda request: {
                "status": "OK", "task_revision": 4,
                "runner_ref": "codex:local:thread-18", "task_status": "completed",
            },
        )
        blocked = completed.handle({
            "jsonrpc": "2.0", "id": 11, "method": "tools/call",
            "params": {"name": "loop_update", "arguments": arguments},
        })
        self.assertTrue(blocked["result"]["isError"])
        result = json.loads(blocked["result"]["content"][0]["text"])
        self.assertEqual(result["status"], "HUMAN_REQUIRED")
        self.assertEqual(result["direct_stage"], "inspect")

    def test_loop_update_reports_paused_state_when_directive_preparation_fails(self) -> None:
        requests: list[dict] = []

        def sender(request):
            requests.append(dict(request))
            if request["action"] == "inspect":
                return {"status": "OK", "task_revision": 2, "runner_ref": "codex:local:thread-19", "task_status": "running"}
            if request["action"] == "pause":
                return {"status": "OK", "task_revision": 2, "runner_ref": "codex:local:thread-19", "task_status": "paused"}
            return {"status": "HUMAN_REQUIRED", "reason": "invalid directive"}

        server = ControlMcpServer(socket_path="/tmp/socket", token_file="/tmp/token", request_sender=sender)
        response = server.handle({
            "jsonrpc": "2.0", "id": 12, "method": "tools/call",
            "params": {"name": "loop_update", "arguments": {
                "task_id": "TASK-019", "reason": "add constraint",
                "facts": [{"claim": "fact", "source_ref": "user-message", "effect": "scope note"}],
            }},
        })
        self.assertTrue(response["result"]["isError"])
        result = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(result["direct_stage"], "prepare_resume")
        self.assertTrue(result["resume_required"])
        self.assertEqual(result["task_status"], "paused")
        self.assertEqual([item["action"] for item in requests], ["inspect", "pause", "prepare_resume"])

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
