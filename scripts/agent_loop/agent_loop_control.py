"""Human CLI for the Phase 1 local Scheduler control service.

Examples (the service must already own the Scheduler runtime)::

    python3 scripts/agent_loop/agent_loop_control.py init-token --token-file .agent-loop/control/token
    python3 scripts/agent_loop/agent_loop_control.py serve --factory scripts.agent_loop.my_runtime:build_control ...
    python3 scripts/agent_loop/agent_loop_control.py inspect TASK-001 --socket ... --token-file ...

The CLI never starts a Codex task by itself.  It only sends structured control
requests to the service and prints its persisted response.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.agent_loop.control_protocol import SchedulerControl
    from scripts.agent_loop.control_runtime import build_control
    from scripts.agent_loop.control_service import (
        SchedulerControlService,
        create_capability_token,
        read_capability_token,
        send_control_request,
    )
else:
    from .control_protocol import SchedulerControl
    from .control_runtime import build_control
    from .control_service import (
        SchedulerControlService,
        create_capability_token,
        read_capability_token,
        send_control_request,
    )


def _load_payload(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read --payload-json: {path}") from exc
    if not isinstance(value, Mapping):
        raise ValueError("--payload-json must contain a JSON object")
    return dict(value)


def _factory(reference: str) -> SchedulerControl:
    if ":" not in reference:
        raise ValueError("--factory must be scripts.agent_loop.<module>:<callable>")
    module_name, callable_name = reference.split(":", 1)
    if not module_name.startswith("scripts.agent_loop.") or not callable_name.isidentifier():
        raise ValueError("--factory is restricted to scripts.agent_loop.<module>:<callable>")
    module = importlib.import_module(module_name)
    factory: Callable[[], Any] = getattr(module, callable_name)
    control = factory()
    if not isinstance(control, SchedulerControl):
        raise ValueError("--factory callable must return SchedulerControl")
    return control


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    token = commands.add_parser("init-token", help="create a private local capability token")
    token.add_argument("--token-file", type=Path, required=True)

    serve = commands.add_parser("serve", help="run one local Unix-socket Scheduler control service")
    source = serve.add_mutually_exclusive_group(required=True)
    source.add_argument("--factory")
    source.add_argument("--runtime-config", type=Path)
    serve.add_argument("--socket", type=Path, required=True)
    serve.add_argument("--token-file", type=Path, required=True)
    serve.add_argument("--poll-seconds", type=float, default=0.5)

    for name in ("inspect", "submit", "pause", "cancel", "prepare-resume", "resume", "events"):
        item = commands.add_parser(name)
        item.add_argument("task_id")
        item.add_argument("--socket", type=Path, required=True)
        item.add_argument("--token-file", type=Path, required=True)
        item.add_argument("--expected-revision", type=int, default=None)
        item.add_argument("--expected-runner-ref", default=None)
        item.add_argument("--actor", choices=("user", "main_control"), default="user")
        item.add_argument("--reason", default="")
        item.add_argument("--idempotency-key", default=None)
        item.add_argument("--payload-json", type=Path, default=None)
        item.add_argument("--timeout-seconds", type=float, default=5.0)
    return parser


def _request(args: argparse.Namespace) -> dict[str, Any]:
    action = args.command.replace("-", "_")
    return {
        "protocol_version": 1,
        "action": action,
        "task_id": args.task_id,
        "expected_revision": args.expected_revision,
        "expected_runner_ref": args.expected_runner_ref,
        "actor": args.actor,
        "reason": args.reason,
        "idempotency_key": args.idempotency_key or str(uuid.uuid4()),
        "payload": _load_payload(args.payload_json),
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init-token":
            create_capability_token(args.token_file)
            print(json.dumps({"status": "OK", "token_file": str(args.token_file)}))
            return 0
        if args.command == "serve":
            control = build_control(args.runtime_config) if args.runtime_config else _factory(args.factory)
            SchedulerControlService(
                control,
                socket_path=args.socket,
                capability_token=read_capability_token(args.token_file),
                poll_interval_seconds=args.poll_seconds,
            ).serve_forever()
            return 0
        response = send_control_request(
            args.socket,
            read_capability_token(args.token_file),
            _request(args),
            timeout_seconds=args.timeout_seconds,
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "HUMAN_REQUIRED", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if response.get("status") == "OK" else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
