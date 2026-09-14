"""Concrete Codex CLI bridge for one bounded Agent Loop task.

The bridge owns only the platform boundary: it starts Codex in an isolated
Git worktree, exposes a small lifecycle to ``CodexHostTransport``, commits
the child result, and preserves the final response as a local artifact.  It
does not create another child task or bypass the Runner contracts.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .codex_bridge import CodexThreadHandle
from .codex_host_transport import CodexHostBridge
from .errors import ValidationError
from .host_registry import HostSessionRecord, HostSessionRegistry


class CodexCliBridgeError(ValidationError):
    """Raised when a Codex CLI task cannot be safely managed."""


_SAFE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}")
_SAFE_REF = re.compile(r"[A-Za-z0-9._/-]+")


@dataclass
class _CliSession:
    thread_id: str
    task_id: str
    task_revision: int
    attempt_id: str
    role: str
    profile_revision: str
    snapshot: str
    project_id: str
    project_root: Path
    session_dir: Path
    worktree: Path
    output_path: Path
    stderr_path: Path
    stdout_path: Path
    write_scope: tuple[str, ...]
    process: subprocess.Popen[str] | None = None
    status: str = "running"
    thread_ready: threading.Event = field(default_factory=threading.Event)
    output_lines: list[str] = field(default_factory=list)
    reader: threading.Thread | None = None
    loss_reason: str | None = None
    report_ref: str | None = None
    final_snapshot: str | None = None
    changed_paths: tuple[str, ...] = ()
    resume_count: int = 0
    started_monotonic: float | None = None
    ended_monotonic: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_base: float = 0.0
    pid: int | None = None
    exit_code: int | None = None
    host_id: str = "local"


class _AttachedProcess:
    """Minimal process view for a child owned by a still-running Host."""

    def __init__(self, pid: int):
        self.pid = int(pid)
        self.stdout = None

    def poll(self) -> int | None:
        if self._zombie():
            return 0
        try:
            os.kill(self.pid, 0)
        except ProcessLookupError:
            return 0
        except PermissionError:
            return None
        return None

    def wait(self, timeout: float | None = None) -> int:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            result = self.poll()
            if result is not None:
                return result
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(["pid", str(self.pid)], timeout)
            time.sleep(0.02)

    def terminate(self) -> None:
        os.kill(self.pid, signal.SIGTERM)

    def kill(self) -> None:
        os.kill(self.pid, signal.SIGKILL)

    def _zombie(self) -> bool:
        stat = Path(f"/proc/{self.pid}/stat")
        if not stat.is_file():
            return False
        try:
            fields = stat.read_text(encoding="ascii").split()
        except OSError:
            return False
        return len(fields) > 2 and fields[2] == "Z"


class CodexCliBridge:
    """Implement ``CodexHostBridge`` with the installed Codex CLI.

    ``project_roots`` is an explicit project-id to filesystem mapping.  The
    bridge never guesses a project from the current directory, which prevents
    a task from silently launching in the wrong repository.
    """

    def __init__(
        self,
        project_roots: Mapping[str, str | Path],
        *,
        codex_command: Sequence[str] | None = None,
        worktree_root: str | Path | None = None,
        artifact_root: str | Path | None = None,
        session_registry_root: str | Path | None = None,
        startup_timeout: float = 30.0,
        stop_timeout: float = 10.0,
    ) -> None:
        if not project_roots:
            raise CodexCliBridgeError("Codex CLI bridge requires project roots")
        self.project_roots = {
            str(project_id): Path(root).resolve()
            for project_id, root in project_roots.items()
        }
        self.codex_command = tuple(codex_command or ("codex",))
        if not self.codex_command or any(not str(item).strip() for item in self.codex_command):
            raise CodexCliBridgeError("Codex CLI command must not be empty")
        self.worktree_root = Path(worktree_root or (Path(tempfile.gettempdir()) / "gwent-agent-loop"))
        self.artifact_root = Path(artifact_root) if artifact_root else None
        self.session_registry = HostSessionRegistry(
            session_registry_root or (self.worktree_root / "host-registry")
        )
        self.startup_timeout = float(startup_timeout)
        self.stop_timeout = float(stop_timeout)
        if self.startup_timeout <= 0 or self.stop_timeout <= 0:
            raise CodexCliBridgeError("Codex CLI timeouts must be positive")
        self._sessions: dict[str, _CliSession] = {}

    def create_task(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        project_id = self._text(payload.get("project_id"), "project_id")
        project_root = self.project_roots.get(project_id)
        if project_root is None or not project_root.is_dir():
            raise CodexCliBridgeError(f"unknown or missing Codex project: {project_id}")
        task = payload.get("task")
        target = payload.get("target")
        if not isinstance(task, Mapping) or not isinstance(target, Mapping):
            raise CodexCliBridgeError("Codex task payload requires task and target")
        snapshot = self._repo_ref(task.get("snapshot"), "snapshot")
        target_snapshot = (
            target.get("environment", {})
            .get("startingState", {})
            .get("branchName")
            if isinstance(target.get("environment"), Mapping)
            and isinstance(target.get("environment", {}).get("startingState"), Mapping)
            else None
        )
        if self._repo_ref(target_snapshot, "target snapshot") != snapshot:
            raise CodexCliBridgeError("Codex target snapshot does not match task snapshot")
        task_id = self._token(task.get("task_id"), "task_id")
        attempt_id = self._token(task.get("attempt_id"), "attempt_id")
        role = self._text(task.get("role"), "role")
        write_scope = tuple(str(path).strip("/") for path in task.get("write_scope", ()))
        if not write_scope or any(not path for path in write_scope):
            raise CodexCliBridgeError("Codex task write_scope must not be empty")
        self._git(project_root, "rev-parse", "--verify", f"{snapshot}^{{commit}}")
        self.worktree_root.mkdir(parents=True, exist_ok=True)
        session_dir = Path(tempfile.mkdtemp(prefix=f"{task_id}-{attempt_id}-", dir=self.worktree_root))
        worktree = session_dir / "worktree"
        session_dir.rmdir()
        self._add_isolated_worktree(project_root, worktree, snapshot)
        session_dir.mkdir(parents=True, exist_ok=True)
        output_path = session_dir / "last-message.json"
        stderr_path = session_dir / "stderr.log"
        stdout_path = session_dir / "stdout.log"
        session = _CliSession(
            thread_id="",
            task_id=task_id,
            task_revision=int(task.get("task_revision", 1)),
            attempt_id=attempt_id,
            role=role,
            profile_revision=self._text(task.get("profile_revision") or "unknown", "profile_revision"),
            snapshot=snapshot,
            project_id=project_id,
            project_root=project_root,
            session_dir=session_dir,
            worktree=worktree,
            output_path=output_path,
            stderr_path=stderr_path,
            stdout_path=stdout_path,
            write_scope=write_scope,
        )
        try:
            self._materialize_inputs(worktree, payload)
            self._start(session, [
                "exec", "--json", "--sandbox", "workspace-write",
                "-C", str(worktree), "--output-last-message", str(output_path),
                self._text(payload.get("prompt"), "prompt"),
            ])
            if not session.thread_ready.wait(self.startup_timeout):
                raise CodexCliBridgeError(self._startup_failure(session))
            if not session.thread_id:
                raise CodexCliBridgeError("Codex CLI did not return a thread id")
            self._sessions[session.thread_id] = session
            self._sync_registry(session)
            return {"thread_id": session.thread_id, "host_id": "local", "status": "running"}
        except BaseException:
            self._stop(session)
            self._remove_worktree(session)
            raise

    def wait_task(self, handle: CodexThreadHandle) -> Mapping[str, Any]:
        session = self._session(handle)
        if session.status == "closed":
            return self._metrics(session, status="closed", report_ref=session.output_path.as_posix())
        if session.status == "lost":
            return self._metrics(session, status="lost", reason=session.loss_reason or "runner loss injected")
        if session.process is not None and session.process.poll() is None:
            return self._metrics(session, status="running")
        return self._finished(session)

    def inject_loss(
        self, handle: CodexThreadHandle, *, reason: str
    ) -> Mapping[str, Any]:
        """Inject one controlled Runner loss for the phase-two field trial.

        This is an explicit experiment hook, not part of the normal host
        lifecycle. It preserves the session worktree and thread id so the
        caller can exercise the bounded same-runner resume path.
        """
        session = self._session(handle)
        if session.status != "completed":
            raise CodexCliBridgeError(
                "loss injection requires a persisted completed rollout before close"
            )
        if not str(reason).strip():
            raise CodexCliBridgeError("loss reason must not be empty")
        self._stop(session)
        session.loss_reason = str(reason)
        session.status = "lost"
        self._sync_registry(session)
        return {"status": "lost", "reason": session.loss_reason}

    def interrupt_task(self, handle: CodexThreadHandle, *, reason: str) -> Mapping[str, Any]:
        session = self._session(handle)
        if not str(reason).strip():
            raise CodexCliBridgeError("interrupt reason must not be empty")
        if session.process is not None and session.process.poll() is None:
            self._stop(session)
            session.status = "interrupted"
            self._sync_registry(session)
            return {"status": "interrupted", "reason": str(reason)}
        return self._finished(session)

    def resume_task(
        self, handle: CodexThreadHandle, *, artifact_refs: tuple[str, ...]
    ) -> Mapping[str, Any]:
        session = self._session(handle)
        if session.status not in {"interrupted", "lost"}:
            raise CodexCliBridgeError(f"cannot resume Codex task in state {session.status}")
        if not artifact_refs or any(not str(ref).strip() for ref in artifact_refs):
            raise CodexCliBridgeError("resume requires non-empty artifact_refs")
        session.thread_ready.clear()
        self._start(session, [
            "exec", "resume", session.thread_id, "--json",
            "--output-last-message", str(session.output_path),
            "Continue the bounded task. Read these persisted artifacts before acting: "
            + ", ".join(str(ref) for ref in artifact_refs),
        ])
        if not session.thread_ready.wait(self.startup_timeout):
            session.status = "lost"
            raise CodexCliBridgeError(self._startup_failure(session))
        session.status = "running"
        session.resume_count += 1
        self._sync_registry(session)
        return self._metrics(session, status="running")

    def rebind_task(
        self, handle: CodexThreadHandle, *, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Attach a new bridge instance to a session created by this Host.

        Rebind is lookup-only.  It never creates a task or calls ``open``.
        The persisted record is checked against the complete launch identity
        before the caller can poll or resume the session.
        """
        if handle.thread_id in self._sessions:
            raise CodexCliBridgeError(f"Codex thread already bound: {handle.thread_id}")
        record = self.session_registry.require(handle.runner_ref)
        self._validate_registry_identity(record, handle, payload)
        project_root = self.project_roots.get(record.project_id)
        if project_root is None or not project_root.is_dir():
            raise CodexCliBridgeError(f"unknown or missing Codex project: {record.project_id}")
        session_dir = Path(record.session_dir).resolve()
        worktree = Path(record.worktree).resolve()
        output_path = Path(record.output_path).resolve()
        stderr_path = Path(record.stderr_path).resolve()
        stdout_path = Path(record.stdout_path).resolve()
        for path, label in (
            (session_dir, "session_dir"),
            (worktree, "worktree"),
            (output_path, "output_path"),
            (stderr_path, "stderr_path"),
            (stdout_path, "stdout_path"),
        ):
            if not self._inside_host_root(path):
                raise CodexCliBridgeError(f"persisted {label} is outside Host worktree root")
        if not worktree.is_dir() or not session_dir.is_dir():
            raise CodexCliBridgeError("persisted Codex session worktree is unavailable")
        process = _AttachedProcess(record.pid) if record.pid is not None else None
        session = _CliSession(
            thread_id=record.thread_id,
            task_id=record.task_id,
            task_revision=record.task_revision,
            attempt_id=record.attempt_id,
            role=record.role,
            profile_revision=record.profile_revision,
            snapshot=record.snapshot,
            project_id=record.project_id,
            project_root=project_root,
            session_dir=session_dir,
            worktree=worktree,
            output_path=output_path,
            stderr_path=stderr_path,
            stdout_path=stdout_path,
            write_scope=record.write_scope,
            process=process,
            status=record.status,
            resume_count=record.resume_count,
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
            host_id=record.host_id,
            pid=record.pid,
            elapsed_base=record.elapsed_seconds,
        )
        session.loss_reason = record.reason
        session.report_ref = record.report_ref
        session.final_snapshot = record.final_snapshot
        session.changed_paths = record.changed_paths
        self._sessions[session.thread_id] = session
        self._refresh_stdout(session)
        if session.status == "running" and process is None:
            self._sessions.pop(session.thread_id, None)
            raise CodexCliBridgeError(
                "running Host session has no persisted process identity"
            )
        if session.status == "running" and process is not None and process.poll() is None:
            result = self._metrics(session, status="running")
            result["runner_ref"] = handle.runner_ref
            return result
        if session.status in {"running", "interrupted", "lost"}:
            result = self._finished(session) if session.status == "running" else self._metrics(
                session, status=session.status, reason=session.loss_reason
            )
        else:
            result = self._metrics(session, status=session.status, reason=session.loss_reason)
        result["runner_ref"] = handle.runner_ref
        return result

    def close_task(self, handle: CodexThreadHandle, *, report_ref: str) -> Mapping[str, Any]:
        session = self._session(handle)
        if session.process is not None and session.process.poll() is None:
            raise CodexCliBridgeError("cannot close a running Codex task")
        result = self._finished(session)
        if result.get("status") != "completed":
            raise CodexCliBridgeError(str(result.get("reason") or "Codex task did not complete"))
        if Path(str(report_ref)).resolve() != session.output_path.resolve():
            raise CodexCliBridgeError("close report_ref does not belong to the Codex task")
        changed_paths = self._changed_paths(session)
        self._validate_scope(changed_paths, session.write_scope)
        self._commit(session, changed_paths)
        final_snapshot = self._git(session.worktree, "rev-parse", "HEAD").strip()
        saved_report = self._save_report(session)
        session.status = "closed"
        session.report_ref = saved_report
        session.final_snapshot = final_snapshot
        session.changed_paths = tuple(changed_paths)
        self._remove_worktree(session)
        session.output_path = Path(saved_report)
        self._sync_registry(session)
        return {
            "status": "completed",
            "report_ref": saved_report,
            "final_snapshot": final_snapshot,
            "changed_paths": changed_paths,
            "input_tokens": int(result.get("input_tokens", 0)),
            "output_tokens": int(result.get("output_tokens", 0)),
            "elapsed_seconds": float(result.get("elapsed_seconds", 0.0)),
        }

    def cleanup_task(self, handle: CodexThreadHandle) -> None:
        """Clean up one bridge-owned session after a bounded failure."""
        session = self._session(handle)
        self._stop(session)
        self._remove_worktree(session)
        session.status = "blocked"
        self._sync_registry(session)
        self._sessions.pop(handle.thread_id, None)

    def read_report(self, report_ref: str) -> str:
        path = Path(report_ref).resolve()
        if not path.is_file():
            raise CodexCliBridgeError(f"Codex report does not exist: {report_ref}")
        return path.read_text(encoding="utf-8")

    def _start(self, session: _CliSession, args: list[str]) -> None:
        if session.started_monotonic is None:
            session.started_monotonic = time.monotonic()
        session.ended_monotonic = None
        stderr = session.stderr_path.open("w", encoding="utf-8")
        stdout = session.stdout_path.open("a", encoding="utf-8")
        session.stdout_offset = stdout.tell()
        try:
            process = subprocess.Popen(
                [*self.codex_command, *args],
                cwd=session.project_root if args[0] == "exec" and "resume" not in args else session.worktree,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                text=True,
                bufsize=1,
                start_new_session=os.name != "nt",
            )
        finally:
            stderr.close()
            stdout.close()
        session.process = process
        session.pid = process.pid
        session.reader = threading.Thread(target=self._read_stdout, args=(session,), daemon=True)
        session.reader.start()

    def _materialize_inputs(self, worktree: Path, payload: Mapping[str, Any]) -> None:
        refs = payload.get("refs", {})
        inputs = payload.get("structured_inputs", {})
        if not isinstance(refs, Mapping) or not isinstance(inputs, Mapping):
            return
        names = {
            "task_packet": "task_packet",
            "context_brief": "context_brief",
            "profile": "profile",
        }
        for name, input_name in names.items():
            value = inputs.get(input_name)
            ref = refs.get(name)
            if not isinstance(value, Mapping) or not isinstance(ref, str):
                continue
            relative = Path(self._repo_ref(ref, f"{name} ref"))
            if not relative.parts or relative.parts[0] != ".agent-loop":
                continue
            target = worktree / relative
            if target.exists():
                if target.read_text(encoding="utf-8") != json.dumps(value, ensure_ascii=True, indent=2) + "\n":
                    raise CodexCliBridgeError(f"refusing to overwrite existing input: {ref}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(deepcopy(dict(value)), ensure_ascii=True, indent=2) + "\n",
                encoding="utf-8",
            )

    def _read_stdout(self, session: _CliSession) -> None:
        process = session.process
        if process is None:
            session.thread_ready.set()
            return
        while True:
            made_progress = False
            try:
                with session.stdout_path.open(
                    "r", encoding="utf-8", errors="replace"
                ) as stream:
                    stream.seek(session.stdout_offset)
                    while True:
                        line = stream.readline()
                        if not line:
                            break
                        made_progress = True
                        session.stdout_offset = stream.tell()
                        self._accept_stdout_line(session, line)
            except OSError:
                pass
            if process.poll() is not None:
                if not made_progress:
                    break
                continue
            if not made_progress:
                time.sleep(0.02)
        if not session.thread_ready.is_set():
            session.thread_ready.set()

    def _accept_stdout_line(self, session: _CliSession, line: str) -> None:
        stripped = line.strip()
        if not stripped:
            return
        session.output_lines.append(stripped[-4096:])
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            return
        if isinstance(event, Mapping):
            thread_id = event.get("thread_id") or event.get("threadId")
            if thread_id:
                session.thread_id = self._token(thread_id, "thread_id")
                session.thread_ready.set()
            self._record_usage(session, event)
            self._sync_registry(session)

    def _refresh_stdout(self, session: _CliSession) -> None:
        """Rebuild Host-observed output metrics after a bridge restart."""
        try:
            lines = session.stdout_path.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
        except OSError:
            return
        session.input_tokens = 0
        session.output_tokens = 0
        session.output_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            session.output_lines.append(stripped[-4096:])
            try:
                event = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(event, Mapping):
                thread_id = event.get("thread_id") or event.get("threadId")
                if thread_id:
                    session.thread_id = self._token(thread_id, "thread_id")
                self._record_usage(session, event)
        session.stdout_offset = session.stdout_path.stat().st_size
        if session.thread_id:
            session.thread_ready.set()

    def _finished(self, session: _CliSession) -> dict[str, Any]:
        self._refresh_stdout(session)
        process = session.process
        exit_code = process.poll() if process is not None else 1
        if process is not None and exit_code is not None:
            if session.reader is not None:
                session.reader.join(timeout=1)
        session.ended_monotonic = time.monotonic()
        if exit_code == 0 and session.output_path.is_file() and session.output_path.stat().st_size > 0:
            session.status = "completed"
            session.report_ref = str(session.output_path)
            result = self._metrics(session, status="completed", report_ref=str(session.output_path))
        else:
            session.status = "blocked"
            session.loss_reason = self._failure_reason(session, exit_code)
            result = self._metrics(session, status="blocked", reason=session.loss_reason)
        session.exit_code = exit_code
        self._sync_registry(session)
        return result

    @staticmethod
    def _record_usage(session: _CliSession, event: Mapping[str, Any]) -> None:
        if event.get("type") not in {"turn.completed", "response.completed"}:
            return
        usage = event.get("usage")
        if not isinstance(usage, Mapping):
            return
        for field_name, aliases in {
            "input_tokens": ("input_tokens", "prompt_tokens"),
            "output_tokens": ("output_tokens", "completion_tokens"),
        }.items():
            value = next((usage.get(alias) for alias in aliases if usage.get(alias) is not None), None)
            if value is None:
                continue
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed >= 0:
                setattr(session, field_name, getattr(session, field_name) + parsed)

    @staticmethod
    def _metrics(
        session: _CliSession,
        *,
        status: str,
        report_ref: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        started = session.started_monotonic
        ended = session.ended_monotonic or time.monotonic()
        elapsed = session.elapsed_base
        if started is not None:
            elapsed += max(0.0, ended - started)
        payload: dict[str, Any] = {
            "status": status,
            "resume_count": int(session.resume_count),
            "input_tokens": int(session.input_tokens),
            "output_tokens": int(session.output_tokens),
            "elapsed_seconds": elapsed,
        }
        if report_ref:
            payload["report_ref"] = report_ref
        if reason:
            payload["reason"] = reason
        return payload

    def _changed_paths(self, session: _CliSession) -> list[str]:
        raw = subprocess.run(
            ["git", "-C", str(session.worktree), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            check=True,
            capture_output=True,
        ).stdout.decode("utf-8", errors="strict")
        paths: list[str] = []
        for entry in raw.split("\0"):
            if not entry:
                continue
            path = entry[3:]
            if " -> " in path:
                path = path.rsplit(" -> ", 1)[1]
            if not path or path.startswith("/") or "\\" in path or ".." in Path(path).parts:
                raise CodexCliBridgeError(f"unsafe changed path: {path}")
            paths.append(path)
        return list(dict.fromkeys(paths))

    @staticmethod
    def _validate_scope(paths: list[str], scope: tuple[str, ...]) -> None:
        if any(path in {"declared test scope only", "task scope"} for path in scope):
            raise CodexCliBridgeError("Codex CLI bridge requires concrete write scope paths")
        for path in paths:
            if not any(path == root or path.startswith(root.rstrip("/") + "/") for root in scope):
                raise CodexCliBridgeError(f"Codex task changed path outside write scope: {path}")

    def _commit(self, session: _CliSession, paths: list[str]) -> None:
        if not paths:
            return
        name = self._git_optional(session.worktree, "config", "user.name")
        email = self._git_optional(session.worktree, "config", "user.email")
        if not name or not email:
            raise CodexCliBridgeError("Git user.name and user.email are required before commit")
        self._git(session.worktree, "add", "-A", "--", *paths)
        self._git(session.worktree, "commit", "-m", f"agent-loop {session.task_id}/{session.attempt_id}")

    def _save_report(self, session: _CliSession) -> str:
        root = self.artifact_root or (session.project_root / ".agent-loop" / "host-artifacts")
        destination = root / session.task_id / f"{session.attempt_id}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(session.output_path, destination)
        return str(destination.resolve())

    def _stop(self, session: _CliSession) -> None:
        process = session.process
        if process is None or process.poll() is not None:
            return
        try:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            process.wait(timeout=self.stop_timeout)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            process.kill()
            process.wait(timeout=self.stop_timeout)
        if session.reader is not None:
            session.reader.join(timeout=1)

    def _remove_worktree(self, session: _CliSession) -> None:
        if session.worktree.exists():
            self._git(session.project_root, "worktree", "remove", "--force", str(session.worktree))
        shutil.rmtree(session.session_dir, ignore_errors=True)

    def _sync_registry(self, session: _CliSession) -> None:
        """Persist the Host-owned identity and latest lifecycle observation."""
        if not session.thread_id:
            return
        elapsed = self._metrics(session, status=session.status).get("elapsed_seconds", 0.0)
        self.session_registry.put(
            HostSessionRecord(
                runner_ref=f"codex:{session.host_id}:{session.thread_id}",
                thread_id=session.thread_id,
                host_id=session.host_id,
                project_id=session.project_id,
                task_id=session.task_id,
                task_revision=getattr(session, "task_revision", 1),
                attempt_id=session.attempt_id,
                role=session.role,
                profile_revision=session.profile_revision,
                snapshot=session.snapshot,
                write_scope=session.write_scope,
                session_dir=str(session.session_dir),
                worktree=str(session.worktree),
                output_path=str(session.output_path),
                stderr_path=str(session.stderr_path),
                stdout_path=str(session.stdout_path),
                pid=session.pid,
                status=session.status,
                resume_count=session.resume_count,
                input_tokens=session.input_tokens,
                output_tokens=session.output_tokens,
                elapsed_seconds=float(elapsed),
                report_ref=session.report_ref,
                final_snapshot=session.final_snapshot,
                changed_paths=session.changed_paths,
                reason=session.loss_reason,
            )
        )

    def _inside_host_root(self, path: Path) -> bool:
        try:
            path.relative_to(self.worktree_root.resolve())
        except ValueError:
            return False
        return True

    @staticmethod
    def _validate_registry_identity(
        record: HostSessionRecord,
        handle: CodexThreadHandle,
        payload: Mapping[str, Any],
    ) -> None:
        task = payload.get("task")
        if not isinstance(task, Mapping):
            raise CodexCliBridgeError("rebind payload requires task identity")
        if str(payload.get("project_id") or "").strip() != record.project_id:
            raise CodexCliBridgeError("rebind project_id mismatch")
        expected = {
            "task_id": task.get("task_id"),
            "task_revision": task.get("task_revision", 1),
            "attempt_id": task.get("attempt_id"),
            "role": task.get("role"),
            "profile_revision": task.get("profile_revision") or "unknown",
            "snapshot": task.get("snapshot"),
        }
        checks = (
            (record.runner_ref, handle.runner_ref, "runner_ref"),
            (record.thread_id, handle.thread_id, "thread_id"),
            (record.task_id, str(expected["task_id"] or ""), "task_id"),
            (record.attempt_id, str(expected["attempt_id"] or ""), "attempt_id"),
            (record.role, str(expected["role"] or ""), "role"),
            (record.profile_revision, str(expected["profile_revision"] or ""), "profile_revision"),
            (record.snapshot, str(expected["snapshot"] or ""), "snapshot"),
        )
        for actual, wanted, label in checks:
            if actual != wanted:
                raise CodexCliBridgeError(f"rebind {label} mismatch")
        try:
            revision = int(expected["task_revision"])
        except (TypeError, ValueError) as exc:
            raise CodexCliBridgeError("rebind task_revision is invalid") from exc
        if record.task_revision != revision:
            raise CodexCliBridgeError("rebind task_revision mismatch")

    def _add_isolated_worktree(
        self, project_root: Path, worktree: Path, snapshot: str
    ) -> None:
        """Add a child worktree, allowing a duplicate detached commit only.

        Git normally rejects checking out a commit already present in another
        worktree.  A bounded child is safe to duplicate because it is detached
        and has its own filesystem path; the existing worktree is never
        modified.  Retry only this specific Git refusal and keep all other
        failures visible to the caller.
        """
        try:
            self._git(project_root, "worktree", "add", "--detach", str(worktree), snapshot)
        except subprocess.CalledProcessError as exc:
            detail = "\n".join(item for item in (exc.stdout, exc.stderr) if item)
            if "already used by worktree" not in detail:
                raise
            self._git(
                project_root,
                "worktree",
                "add",
                "--force",
                "--detach",
                str(worktree),
                snapshot,
            )

    def _session(self, handle: CodexThreadHandle) -> _CliSession:
        try:
            return self._sessions[handle.thread_id]
        except KeyError as exc:
            raise CodexCliBridgeError(f"unknown Codex thread: {handle.thread_id}") from exc

    def _startup_failure(self, session: _CliSession) -> str:
        detail = session.stderr_path.read_text(encoding="utf-8", errors="replace").strip()
        if detail:
            return f"Codex CLI did not start a task: {detail[-1000:]}"
        return "Codex CLI did not return a thread id before startup timeout"

    def _failure_reason(self, session: _CliSession, exit_code: int | None) -> str:
        detail = session.stderr_path.read_text(encoding="utf-8", errors="replace").strip()
        if detail:
            return f"Codex CLI exited with code {exit_code}: {detail[-1000:]}"
        return f"Codex CLI exited without a report (code {exit_code})"

    @staticmethod
    def _text(value: Any, label: str) -> str:
        text = str(value or "").strip()
        if not text or "\x00" in text:
            raise CodexCliBridgeError(f"{label} must not be empty")
        return text

    @staticmethod
    def _token(value: Any, label: str) -> str:
        text = CodexCliBridge._text(value, label)
        if not _SAFE_TOKEN.fullmatch(text):
            raise CodexCliBridgeError(f"invalid {label}")
        return text

    @staticmethod
    def _repo_ref(value: Any, label: str) -> str:
        text = CodexCliBridge._text(value, label)
        if text.startswith("-") or "\\" in text or not _SAFE_REF.fullmatch(text):
            raise CodexCliBridgeError(f"invalid {label}")
        if any(part == ".." for part in Path(text).parts):
            raise CodexCliBridgeError(f"invalid {label}")
        return text

    @staticmethod
    def _git(cwd: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout

    @staticmethod
    def _git_optional(cwd: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
