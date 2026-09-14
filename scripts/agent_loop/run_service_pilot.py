"""Run a bounded Product service-backed Docker verification pilot.

The pilot uses an isolated Compose project, proves the healthy Core -> BFF ->
Web path, injects a missing-Core dependency failure, records health/logs, and
always cleans only resources owned by that project.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


class PilotError(RuntimeError):
    """A bounded service pilot failed or could not prove its evidence."""


def _command_text(command: list[str]) -> str:
    return " ".join(
        item if re.fullmatch(r"[A-Za-z0-9_./:=+-]+", item) else repr(item)
        for item in command
    )


class ServicePilot:
    def __init__(self, args: argparse.Namespace) -> None:
        self.root = args.project_root.resolve()
        self.compose_file = self.root / "deploy/docker/compose.cpu.yml"
        self.project = args.project_name
        self.web_port = str(args.web_port)
        self.artifact_root = args.artifact_root.resolve()
        self.records: list[dict[str, Any]] = []
        self.started = False
        self.ownership_proven = False
        self.cleanup_ok = False
        self.failure_evidence: dict[str, Any] = {}

    @property
    def env(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment["GWENT_DOCKER_WEB_PORT"] = self.web_port
        return environment

    def compose(self, *arguments: str, timeout: int = 1800) -> subprocess.CompletedProcess[str]:
        command = [
            "docker",
            "compose",
            "-p",
            self.project,
            "-f",
            str(self.compose_file),
            *arguments,
        ]
        try:
            result = subprocess.run(
                command,
                cwd=self.root,
                env=self.env,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PilotError(f"command timed out after {timeout}s: {_command_text(command)}") from exc
        self.records.append(
            {
                "command": _command_text(command),
                "exit_code": result.returncode,
                "stdout": result.stdout[-12000:],
                "stderr": result.stderr[-12000:],
            }
        )
        return result

    def docker(self, *arguments: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
        command = ["docker", *arguments]
        try:
            result = subprocess.run(
                command,
                cwd=self.root,
                env=self.env,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PilotError(f"command timed out after {timeout}s: {_command_text(command)}") from exc
        self.records.append(
            {
                "command": _command_text(command),
                "exit_code": result.returncode,
                "stdout": result.stdout[-12000:],
                "stderr": result.stderr[-12000:],
            }
        )
        return result

    def require(self, result: subprocess.CompletedProcess[str], label: str) -> None:
        if result.returncode != 0:
            raise PilotError(f"{label} failed with exit code {result.returncode}")

    def service_id(self, service: str) -> str:
        result = self.compose("ps", "-aq", service)
        self.require(result, f"lookup {service} container")
        container_id = result.stdout.strip().splitlines()
        if not container_id:
            raise PilotError(f"{service} container is missing")
        return container_id[-1].strip()

    def health_status(self, service: str) -> str:
        container_id = self.service_id(service)
        result = self.docker("inspect", "--format", "{{.State.Health.Status}}", container_id)
        self.require(result, f"inspect {service} health")
        return result.stdout.strip()

    def health_payload(self, service: str) -> dict[str, Any]:
        container_id = self.service_id(service)
        result = self.docker("inspect", "--format", "{{json .State.Health}}", container_id)
        self.require(result, f"inspect {service} health payload")
        return json.loads(result.stdout)

    def wait_health(self, service: str, expected: str, timeout: int = 180) -> None:
        deadline = time.monotonic() + timeout
        last = "unknown"
        while time.monotonic() < deadline:
            last = self.health_status(service)
            if last == expected:
                return
            time.sleep(2)
        raise PilotError(f"{service} did not reach {expected}; last status was {last}")

    def http_json(self, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> tuple[int, Any]:
        url = f"http://127.0.0.1:{self.web_port}{path}"
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data is not None else {},
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=15) as response:
                body = response.read().decode()
                return response.status, json.loads(body)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise PilotError(f"HTTP check failed for {url}: {exc}") from exc

    def healthy_product_checks(self) -> dict[str, Any]:
        status, health = self.http_json("/api/health")
        if status != 200 or health.get("ok") is not True:
            raise PilotError(f"BFF health did not report Core healthy: {health}")
        core = health.get("core") or {}
        if core.get("schema_version") != 13 or core.get("device") != "cpu":
            raise PilotError(f"unexpected Core health contract: {core}")

        request = urllib.request.Request(f"http://127.0.0.1:{self.web_port}/")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=15) as response:
            shell_status = response.status
            html = response.read().decode()
        if shell_status != 200:
            raise PilotError(f"Product shell returned HTTP {shell_status}")
        if html.count('name="theme-color"') != 1 or 'content="#0f172a"' not in html:
            raise PilotError("Product shell theme-color contract is missing")

        game_status, game = self.http_json(
            "/api/game/new",
            method="POST",
            payload={"seed": 20260914, "mode": "manual_test"},
        )
        actions = game.get("actions")
        if game_status != 200 or not game.get("match_id") or not isinstance(actions, list) or not actions:
            raise PilotError("Product game creation contract failed")
        return {
            "api_health_status": status,
            "core_schema_version": core.get("schema_version"),
            "core_device": core.get("device"),
            "shell_theme_color": "#0f172a",
            "new_game_status": game_status,
            "actions_count": len(actions),
        }

    def capture_logs(self, *services: str) -> str:
        result = self.compose("logs", "--no-color", "--tail=80", *services)
        self.require(result, "collect service logs")
        return result.stdout

    def run(self) -> dict[str, Any]:
        if not self.compose_file.is_file():
            raise PilotError(f"Compose file is missing: {self.compose_file}")
        preexisting = self.compose("ps", "-aq")
        self.require(preexisting, "record pre-existing project containers")
        if preexisting.stdout.strip():
            raise PilotError("isolated Compose project already owns containers")
        self.ownership_proven = True

        self.require(self.compose("config", "--quiet"), "validate Compose config")
        self.require(self.compose("up", "-d", "--build", "core", "bff", "web"), "start healthy service stack")
        self.started = True
        for service in ("core", "bff", "web"):
            self.wait_health(service, "healthy")
        healthy_ps = self.compose("ps", "--all")
        self.require(healthy_ps, "collect healthy service status")
        healthy_checks = self.healthy_product_checks()
        healthy_logs = self.capture_logs("core", "bff", "web")

        self.require(self.compose("down", "--remove-orphans"), "tear down healthy stack")
        self.started = False
        self.require(self.compose("up", "-d", "--no-deps", "bff"), "start BFF without Core")
        self.started = True
        self.wait_health("bff", "unhealthy", timeout=120)
        failed_ps = self.compose("ps", "--all")
        self.require(failed_ps, "collect failed service status")
        failure_health = self.health_payload("bff")
        failure_logs = self.capture_logs("bff")
        if int(failure_health.get("FailingStreak", 0)) <= 0:
            raise PilotError("missing-Core failure did not produce healthcheck failures")
        self.failure_evidence = {
            "classification": "DOCKER_FAILURE",
            "injection": "Compose project was recreated with BFF only; Core was intentionally absent",
            "bff_status": "unhealthy",
            "failing_streak": failure_health.get("FailingStreak"),
            "health_log_tail": failure_health.get("Log", [])[-2:],
            "compose_status": failed_ps.stdout,
            "logs": failure_logs,
        }
        return {
            "healthy_status": healthy_ps.stdout,
            "healthy_checks": healthy_checks,
            "healthy_logs": healthy_logs,
            "failure": self.failure_evidence,
        }

    def cleanup(self) -> None:
        if not self.ownership_proven:
            raise PilotError("resource ownership was not proven; cleanup refused")
        result = self.compose("down", "--remove-orphans")
        remaining = self.compose("ps", "-aq")
        network = self.docker(
            "network",
            "ls",
            "--filter",
            f"label=com.docker.compose.project={self.project}",
            "--format",
            "{{.Name}}",
        )
        self.cleanup_ok = (
            result.returncode == 0
            and not remaining.stdout.strip()
            and not network.stdout.strip()
        )
        if not self.cleanup_ok:
            raise PilotError("service pilot cleanup could not be proven complete")
        self.started = False

    def write_evidence(self, *, args: argparse.Namespace, status: str, summary: dict[str, Any] | None, error: str | None) -> Path:
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        evidence = {
            "schema": "agent-loop.service-pilot.v1",
            "task_id": args.task_id,
            "tested_snapshot": args.tested_snapshot,
            "tester": "test-verification",
            "overall": status,
            "project": self.project,
            "compose_file": str(self.compose_file),
            "web_port": int(self.web_port),
            "cleanup": "complete" if self.cleanup_ok else "incomplete",
            "error": error,
            "summary": summary or {},
            "commands": self.records,
        }
        destination = self.artifact_root / "service-pilot-evidence.json"
        destination.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--task-id", default="GW-REAL-PRODUCT-001-SERVICE")
    parser.add_argument("--tested-snapshot", required=True)
    parser.add_argument("--project-name", default="agent-loop-gw-real-product-001-service-v2")
    parser.add_argument("--web-port", type=int, default=18080)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    pilot = ServicePilot(args)
    status = "PASS"
    summary: dict[str, Any] | None = None
    error: str | None = None
    try:
        summary = pilot.run()
    except Exception as exc:  # CLI boundary: preserve evidence and classify failure.
        status = "BLOCKED"
        error = str(exc)
    finally:
        try:
            pilot.cleanup()
        except Exception as exc:
            status = "HUMAN_REQUIRED"
            error = f"{error + '; ' if error else ''}cleanup: {exc}"
    evidence = pilot.write_evidence(args=args, status=status, summary=summary, error=error)
    result = {
        "status": status,
        "evidence": str(evidence),
        "cleanup": "complete" if pilot.cleanup_ok else "incomplete",
    }
    if error:
        result["error"] = error
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
