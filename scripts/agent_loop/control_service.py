"""Local Unix-socket service for :mod:`control_protocol`.

The service owns a single Scheduler instance and is intentionally WSL/Linux
only in this phase.  It exposes JSON-lines requests to a local socket, checks a
separate capability token, and periodically calls ``SchedulerControl.pump``.
It never accepts arbitrary shell commands or public TCP connections.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import selectors
import socket
import stat
import time
from pathlib import Path
from typing import Any, Mapping

from .control_protocol import ControlProtocolError, SchedulerControl


class ControlServiceError(ControlProtocolError):
    """Raised for local service startup, authentication, or framing failures."""


def create_capability_token(path: str | Path) -> str:
    """Create one private local capability token, refusing to overwrite it."""
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise ControlServiceError(f"control token already exists: {target}")
    token = secrets.token_urlsafe(32)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(target, flags, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as stream:
        stream.write(token + "\n")
    return token


def read_capability_token(path: str | Path) -> str:
    target = Path(path).resolve()
    try:
        mode = stat.S_IMODE(target.stat().st_mode)
    except OSError as exc:
        raise ControlServiceError(f"cannot read control token: {target}") from exc
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ControlServiceError("control token permissions must be owner-only")
    token = target.read_text(encoding="ascii").strip()
    if len(token) < 24:
        raise ControlServiceError("control token is invalid")
    return token


class _ServiceLock:
    """Advisory process lock retained for the lifetime of a WSL service."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._stream: Any | None = None

    def acquire(self) -> None:
        try:
            import fcntl
        except ImportError as exc:  # pragma: no cover - documented Phase 1 boundary
            raise ControlServiceError("Phase 1 control service requires a Unix file-lock host") from exc
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+", encoding="ascii")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            stream.close()
            raise ControlServiceError("another Scheduler control service owns this state root") from exc
        stream.seek(0)
        stream.truncate(0)
        stream.write(str(os.getpid()) + "\n")
        stream.flush()
        self._stream = stream

    def release(self) -> None:
        if self._stream is None:
            return
        try:
            import fcntl

            fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
        finally:
            self._stream.close()
            self._stream = None


class SchedulerControlService:
    """A single-threaded, bounded local command server.

    ``control`` is already connected to an injected Scheduler backend.  This
    class deliberately does not know whether that backend is deterministic,
    CLI-hosted, or a future SDK-hosted implementation.
    """

    def __init__(
        self,
        control: SchedulerControl,
        *,
        socket_path: str | Path,
        capability_token: str,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        if len(capability_token) < 24:
            raise ControlServiceError("capability token is invalid")
        if poll_interval_seconds <= 0 or poll_interval_seconds > 10:
            raise ControlServiceError("poll interval must be between 0 and 10 seconds")
        self.control = control
        self.socket_path = Path(socket_path).resolve()
        self.capability_token = capability_token
        self.poll_interval_seconds = float(poll_interval_seconds)
        self._stop = False
        self._lock = _ServiceLock(self.control.journal.root / "scheduler-control.lock")

    def request_stop(self) -> None:
        self._stop = True

    def serve_forever(self) -> None:
        if os.name == "nt":  # pragma: no cover - documented Phase 1 boundary
            raise ControlServiceError("Phase 1 control service supports Unix sockets only")
        self._lock.acquire()
        selector = selectors.DefaultSelector()
        listener: socket.socket | None = None
        try:
            self.socket_path.parent.mkdir(parents=True, exist_ok=True)
            if self.socket_path.exists():
                raise ControlServiceError(f"control socket already exists: {self.socket_path}")
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(self.socket_path))
            os.chmod(self.socket_path, stat.S_IRUSR | stat.S_IWUSR)
            listener.listen(16)
            listener.setblocking(False)
            selector.register(listener, selectors.EVENT_READ)
            next_poll = time.monotonic()
            while not self._stop:
                timeout = max(0.0, next_poll - time.monotonic())
                for key, _mask in selector.select(timeout):
                    if key.fileobj is listener:
                        client, _ = listener.accept()
                        with client:
                            self._serve_client(client)
                if time.monotonic() >= next_poll:
                    self.control.pump()
                    next_poll = time.monotonic() + self.poll_interval_seconds
        finally:
            selector.close()
            if listener is not None:
                listener.close()
            try:
                self.socket_path.unlink()
            except FileNotFoundError:
                pass
            self._lock.release()

    def _serve_client(self, client: socket.socket) -> None:
        client.settimeout(5.0)
        try:
            raw = self._read_frame(client)
            envelope = json.loads(raw)
            if not isinstance(envelope, Mapping):
                raise ControlServiceError("control envelope must be a mapping")
            token = str(envelope.get("capability_token", ""))
            if not hmac.compare_digest(token, self.capability_token):
                raise ControlServiceError("control capability token was rejected")
            request = envelope.get("request")
            if not isinstance(request, Mapping):
                raise ControlServiceError("control envelope requires a request mapping")
            response = self.control.dispatch(request)
        except (ValueError, ControlProtocolError) as exc:
            response = {"status": "HUMAN_REQUIRED", "reason": str(exc)}
        self._write_frame(client, response)

    @staticmethod
    def _read_frame(client: socket.socket) -> str:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > 64 * 1024:
                raise ControlServiceError("control request exceeds 64 KiB")
            if b"\n" in chunk:
                break
        raw = b"".join(chunks).split(b"\n", 1)[0]
        if not raw:
            raise ControlServiceError("control request is empty")
        return raw.decode("utf-8")

    @staticmethod
    def _write_frame(client: socket.socket, response: Mapping[str, Any]) -> None:
        encoded = json.dumps(dict(response), ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
        client.sendall(encoded)


def send_control_request(
    socket_path: str | Path,
    capability_token: str,
    request: Mapping[str, Any],
    *,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Send one authenticated request to the Phase 1 Unix-socket service."""
    if timeout_seconds <= 0:
        raise ControlServiceError("control client timeout must be positive")
    envelope = json.dumps(
        {"capability_token": capability_token, "request": dict(request)},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8") + b"\n"
    if len(envelope) > 64 * 1024:
        raise ControlServiceError("control request exceeds 64 KiB")
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout_seconds)
    try:
        client.connect(str(Path(socket_path).resolve()))
        client.sendall(envelope)
        response = SchedulerControlService._read_frame(client)
    except OSError as exc:
        raise ControlServiceError("cannot reach Scheduler control service") from exc
    finally:
        client.close()
    try:
        decoded = json.loads(response)
    except json.JSONDecodeError as exc:
        raise ControlServiceError("control service returned invalid JSON") from exc
    if not isinstance(decoded, Mapping):
        raise ControlServiceError("control service response must be a mapping")
    return dict(decoded)
