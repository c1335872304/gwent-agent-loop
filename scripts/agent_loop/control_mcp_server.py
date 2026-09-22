"""Main-control-only MCP adapter for the durable Scheduler control service.

This is a small stdio MCP server with no third-party dependency.  It never
starts a Scheduler or Codex task.  It forwards a deliberately tiny command
set to a separately running, token-protected local control service.

Register this server only in the *main control host* configuration.  The
CLI bridge starts Owner/Test sessions with ``--ignore-user-config`` so those
child sessions do not inherit a user-level control MCP registration.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.agent_loop.control_service import read_capability_token, send_control_request
else:
    from .control_service import read_capability_token, send_control_request


MCP_PROTOCOL_VERSION = "2025-03-26"
_READ_ACTIONS = frozenset({"inspect"})
_TOOL_ACTIONS = {
    "loop_inspect": "inspect",
    "loop_submit": "submit",
    "loop_pause": "pause",
    "loop_prepare_resume": "prepare_resume",
    "loop_resume": "resume",
    "loop_cancel": "cancel",
}


def _tool(name: str, description: str, *, required: list[str]) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "task_id": {"type": "string", "description": "持久化 TaskPacket 的 task_id。"},
        "expected_revision": {"type": "integer", "minimum": 1, "description": "先 inspect 得到的 revision。"},
        "expected_runner_ref": {"type": "string", "description": "先 inspect 得到的 runner_ref。"},
        "reason": {"type": "string", "description": "用户明确意图的简短审计理由。"},
    }
    if name == "loop_prepare_resume":
        properties["facts"] = {
            "type": "array",
            "minItems": 1,
            "maxItems": 16,
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "source_ref": {"type": "string"},
                    "effect": {"type": "string"},
                },
                "required": ["claim", "source_ref", "effect"],
                "additionalProperties": False,
            },
            "description": "只包含新补充事实、来源和对原任务的影响；不要复制聊天记录。",
        }
    if name == "loop_submit":
        properties["task_packet_ref"] = {
            "type": "string",
            "description": "可选：必须匹配 runtime.json 中已声明的 LaunchSpec；不能上传新的 TaskPacket。",
        }
    return {
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
    }


TOOLS = (
    _tool("loop_inspect", "查询任务状态；任何写操作前必须先调用。", required=["task_id"]),
    _tool("loop_submit", "提交 runtime.json 中已声明的 TaskPacket；不能从自然语言创建新任务。", required=["task_id", "reason"]),
    _tool("loop_pause", "按已查询的身份暂停同一个 Runner。", required=["task_id", "expected_revision", "expected_runner_ref", "reason"]),
    _tool("loop_prepare_resume", "记录不改变 TaskPacket 范围的补充事实，但不启动模型。", required=["task_id", "expected_revision", "expected_runner_ref", "reason", "facts"]),
    _tool("loop_resume", "使用已准备的恢复说明恢复同一个 Runner；不会创建新 Runner。", required=["task_id", "expected_revision", "expected_runner_ref", "reason"]),
    _tool("loop_cancel", "取消任务；这是不可自动恢复的终止。", required=["task_id", "expected_revision", "expected_runner_ref", "reason"]),
)


class ControlMcpServer:
    """Translate MCP tool calls into audited, identity-bound control requests."""

    def __init__(
        self,
        *,
        socket_path: str | Path,
        token_file: str | Path,
        request_sender: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    ) -> None:
        self.socket_path = Path(socket_path).resolve()
        self.token_file = Path(token_file).resolve()
        self._request_sender = request_sender

    def handle(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        if not isinstance(message, Mapping) or message.get("jsonrpc") != "2.0":
            return self._error(message.get("id") if isinstance(message, Mapping) else None, -32600, "invalid JSON-RPC request")
        method = str(message.get("method") or "")
        request_id = message.get("id")
        params = message.get("params") or {}
        if not isinstance(params, Mapping):
            return self._error(request_id, -32602, "params must be an object")
        if method.startswith("notifications/"):
            return None
        if method == "initialize":
            requested = str(params.get("protocolVersion") or MCP_PROTOCOL_VERSION)
            return self._result(request_id, {
                "protocolVersion": requested if requested == MCP_PROTOCOL_VERSION else MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "agent-loop-control", "version": "1"},
                "instructions": "仅主控使用：先 loop_inspect；写操作必须使用返回的 revision 与 runner_ref。补充信息先 prepare，再 resume。身份、范围或环境不确定时停止并报告 HUMAN_REQUIRED。",
            })
        if method == "ping":
            return self._result(request_id, {})
        if method == "tools/list":
            return self._result(request_id, {"tools": list(TOOLS)})
        if method == "tools/call":
            return self._call(request_id, params)
        return self._error(request_id, -32601, f"unsupported method: {method}")

    def _call(self, request_id: Any, params: Mapping[str, Any]) -> dict[str, Any]:
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if name not in _TOOL_ACTIONS or not isinstance(arguments, Mapping):
            return self._error(request_id, -32602, "unknown control tool or invalid arguments")
        schema = next(tool["inputSchema"] for tool in TOOLS if tool["name"] == name)
        missing = [field for field in schema["required"] if field not in arguments]
        unexpected = sorted(set(arguments) - set(schema["properties"]))
        if missing or unexpected:
            detail = []
            if missing:
                detail.append("missing: " + ", ".join(missing))
            if unexpected:
                detail.append("unexpected: " + ", ".join(unexpected))
            return self._error(request_id, -32602, "; ".join(detail))
        action = _TOOL_ACTIONS[name]
        try:
            task_id = str(arguments["task_id"]).strip()
            expected_revision = arguments.get("expected_revision")
            request = {
                "protocol_version": 1,
                "action": action,
                "task_id": task_id,
                "expected_revision": int(expected_revision) if expected_revision is not None else None,
                "expected_runner_ref": str(arguments.get("expected_runner_ref") or "").strip() or None,
                "actor": "main_control",
                "reason": str(arguments.get("reason") or "").strip(),
                "idempotency_key": str(uuid.uuid4()),
                "payload": self._payload_for(action, arguments),
            }
            response = dict(self._send(request))
        except (KeyError, TypeError, ValueError, OSError) as exc:
            return self._error(request_id, -32602, str(exc))
        failed = response.get("status") != "OK"
        return self._result(request_id, {
            "content": [{"type": "text", "text": json.dumps(response, ensure_ascii=False, sort_keys=True)}],
            "isError": failed,
        })

    def _send(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if self._request_sender is not None:
            return self._request_sender(request)
        return send_control_request(
            self.socket_path,
            read_capability_token(self.token_file),
            request,
        )

    @staticmethod
    def _payload_for(action: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if action == "prepare_resume":
            return {"facts": arguments.get("facts", [])}
        if action == "submit" and str(arguments.get("task_packet_ref") or "").strip():
            return {"task_packet_ref": str(arguments["task_packet_ref"]).strip()}
        return {}

    @staticmethod
    def _result(request_id: Any, result: Mapping[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": dict(result)}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    args = parser.parse_args(argv)
    server = ControlMcpServer(socket_path=args.socket, token_file=args.token_file)
    for raw in sys.stdin:
        try:
            parsed = json.loads(raw)
            response = server.handle(parsed)
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
                sys.stdout.flush()
        except (json.JSONDecodeError, TypeError) as exc:
            sys.stdout.write(json.dumps(ControlMcpServer._error(None, -32700, str(exc)), separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
