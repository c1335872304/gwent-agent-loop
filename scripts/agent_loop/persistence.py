"""Crash-tolerant local persistence for one Agent Loop task."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .errors import StateTransitionError, ValidationError
from .state_machine import apply_event

_SAFE_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


class TaskStore:
    """Store one task's projection, append-only events, and JSON artifacts."""

    def __init__(self, root: str | Path = ".agent-loop/tasks") -> None:
        self.root = Path(root).resolve()

    def _task_dir(self, task_id: str) -> Path:
        if not _SAFE_TASK_ID.fullmatch(task_id):
            raise ValidationError(f"unsafe task_id for local persistence: {task_id!r}")
        return self.root / task_id

    def initialize(self, task_id: str, *, packet_revision: int, initial_state: str = "RECEIVED") -> dict[str, Any]:
        task_dir = self._task_dir(task_id)
        if task_dir.exists():
            raise ValidationError(f"task store already exists: {task_id}")
        task_dir.mkdir(parents=True)
        (task_dir / "artifacts").mkdir()
        (task_dir / "locks").mkdir()
        (task_dir / "events.ndjson").touch()
        state = {
            "protocol_version": 1,
            "task_id": task_id,
            "packet_revision": packet_revision,
            "state": initial_state,
            "event_seq": 0,
            "event_ids": [],
            "artifact_refs": [],
            "updated_at": _now(),
        }
        _write_json_atomic(task_dir / "state.json", state)
        return state

    def read_state(self, task_id: str) -> dict[str, Any]:
        path = self._task_dir(task_id) / "state.json"
        if not path.is_file():
            raise ValidationError(f"task state does not exist: {task_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _event_log(self, task_id: str) -> Path:
        path = self._task_dir(task_id) / "events.ndjson"
        if not path.is_file():
            raise ValidationError(f"task event log does not exist: {task_id}")
        return path

    def _logged_events(self, task_id: str) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for line in self._event_log(task_id).read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
        return events

    def recover_state(self, task_id: str) -> dict[str, Any]:
        """Replay log entries missing from the projection after an interrupted write."""
        state = self.read_state(task_id)
        for event in self._logged_events(task_id):
            if str(event.get("event_id")) in {str(value) for value in state.get("event_ids", [])}:
                continue
            state = apply_event(state, event, expected_task_revision=int(state["packet_revision"]))
        if state != self.read_state(task_id):
            state["updated_at"] = _now()
            _write_json_atomic(self._task_dir(task_id) / "state.json", state)
        return state

    def append_event(self, task_id: str, event: Mapping[str, Any]) -> dict[str, Any]:
        state = self.recover_state(task_id)
        event_id = str(event.get("event_id", ""))
        if event_id in {str(value) for value in state.get("event_ids", [])}:
            result = dict(state)
            result["idempotent_replay"] = True
            return result
        next_state = apply_event(state, event, expected_task_revision=int(state["packet_revision"]))
        existing_ids = {str(item.get("event_id")) for item in self._logged_events(task_id)}
        if event_id not in existing_ids:
            with self._event_log(task_id).open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(dict(event), ensure_ascii=False, sort_keys=True) + "\n")
        next_state["updated_at"] = _now()
        _write_json_atomic(self._task_dir(task_id) / "state.json", next_state)
        return next_state

    def write_artifact(self, task_id: str, name: str, content: Mapping[str, Any]) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", name):
            raise ValidationError(f"unsafe artifact name: {name!r}")
        target = self._task_dir(task_id) / "artifacts" / f"{name}.json"
        if target.exists():
            raise ValidationError(f"artifact already exists: {name}")
        _write_json_atomic(target, content)
        return target.relative_to(self.root.parent.parent).as_posix()
