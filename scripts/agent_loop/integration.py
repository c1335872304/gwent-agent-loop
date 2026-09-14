"""Safe worktree-to-main integration planning for Agent Loop phase two.

This module is intentionally read-only by default.  It resolves the candidate
commit, records the exact diff and user changes, performs a merge-tree dry run,
and emits an IntegrationManifest.  A manifest that needs a human decision is
never silently applied to the parent checkout.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

from .errors import ValidationError


class IntegrationManifestError(ValidationError):
    """Raised when an integration plan is incomplete or unsafe."""


_SAFE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}")
_SAFE_REF = re.compile(r"[A-Za-z0-9._/~^:{}@+-]+")
_STATUSES = {"ready", "human_required", "blocked", "approved", "applied", "rolled_back"}


def _text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text or "\x00" in text:
        raise IntegrationManifestError(f"{label} must not be empty")
    return text


def _token(value: Any, label: str) -> str:
    text = _text(value, label)
    if not _SAFE_TOKEN.fullmatch(text):
        raise IntegrationManifestError(f"invalid {label}")
    return text


def _ref(value: Any, label: str) -> str:
    text = _text(value, label)
    if text.startswith("-") or "\\" in text or not _SAFE_REF.fullmatch(text):
        raise IntegrationManifestError(f"invalid {label}")
    if any(part == ".." for part in Path(text).parts):
        raise IntegrationManifestError(f"invalid {label}")
    return text


def _path(value: Any, label: str) -> str:
    text = _text(value, label).strip("/")
    if not text or text.startswith("-") or "\\" in text:
        raise IntegrationManifestError(f"invalid {label}")
    if any(part in {"", ".", ".."} for part in Path(text).parts):
        raise IntegrationManifestError(f"invalid {label}")
    return text


def _inside(path: str, roots: Sequence[str]) -> bool:
    normalized = path.strip("/")
    return any(
        normalized == root.strip("/")
        or normalized.startswith(root.strip("/") + "/")
        for root in roots
    )


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _commit(root: Path, value: Any, label: str) -> str:
    requested = _ref(value, label)
    result = _git(root, "rev-parse", "--verify", f"{requested}^{{commit}}")
    resolved = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", resolved):
        raise IntegrationManifestError(f"{label} did not resolve to a commit")
    return resolved


def _status_paths(root: Path) -> list[str]:
    raw = _git(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    ).stdout
    paths: list[str] = []
    for entry in raw.split("\0"):
        if not entry:
            continue
        value = entry[3:] if len(entry) >= 3 else entry
        if " -> " in value:
            value = value.rsplit(" -> ", 1)[1]
        paths.append(_path(value, "user change path"))
    return list(dict.fromkeys(paths))


def _diff_paths(root: Path, base: str, candidate: str) -> list[str]:
    result = _git(root, "diff", "--name-only", f"{base}..{candidate}")
    return list(dict.fromkeys(_path(line, "candidate changed path") for line in result.stdout.splitlines() if line.strip()))


def _merge_dry_run(root: Path, parent: str, candidate: str) -> tuple[list[str], str | None]:
    if parent == candidate:
        return [], None
    merge_base = _git(root, "merge-base", parent, candidate).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", merge_base):
        return [], "unable to resolve merge base"
    # The three-tree form is read-only.  ``--write-tree`` creates temporary
    # Git objects and is deliberately excluded from planning.
    result = _git(root, "merge-tree", merge_base, parent, candidate, check=False)
    output = (result.stdout + "\n" + result.stderr).strip()
    conflicts = re.findall(r"CONFLICT[^\n]*?(?: in |: )([^\n]+)", output)
    conflicts = [item.strip().strip("'") for item in conflicts if item.strip()]
    if conflicts:
        return list(dict.fromkeys(conflicts)), "merge conflict requires human resolution"
    if result.returncode != 0:
        return [], output[-1000:] or "merge-tree failed"
    return [], None


def _attempts(
    value: Sequence[Mapping[str, Any]],
    *,
    accepted_bases: Sequence[str],
    allowed: Sequence[str],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            raise IntegrationManifestError("each integration attempt must be a mapping")
        attempt_id = _token(raw.get("attempt_id"), "attempt_id")
        role = _text(raw.get("role"), "attempt role")
        attempt_base = _commit_from_value(raw.get("base_snapshot"), "attempt base_snapshot")
        final_snapshot = _commit_from_value(raw.get("final_snapshot"), "attempt final_snapshot")
        changed = [_path(item, "attempt changed path") for item in raw.get("changed_paths", [])]
        outside = [item for item in changed if not _inside(item, allowed)]
        if outside:
            raise IntegrationManifestError("attempt changed path exceeds allowed scope: " + ", ".join(outside))
        if attempt_base not in accepted_bases:
            raise IntegrationManifestError(
                f"attempt {attempt_id} is not based on an accepted responsibility-chain snapshot"
            )
        normalized.append(
            {
                "attempt_id": attempt_id,
                "role": role,
                "base_snapshot": attempt_base,
                "final_snapshot": final_snapshot,
                "changed_paths": list(dict.fromkeys(changed)),
                "status": _text(raw.get("status") or "closed", "attempt status"),
                "artifact_refs": [str(item) for item in raw.get("artifact_refs", [])],
            }
        )
    return normalized


def _commit_from_value(value: Any, label: str) -> str:
    text = _text(value, label)
    if not re.fullmatch(r"[0-9a-f]{40}", text):
        raise IntegrationManifestError(f"{label} must be a resolved 40-character commit")
    return text


def build_integration_manifest(
    root: str | Path,
    *,
    task_id: str,
    task_revision: int,
    base_snapshot: str,
    candidate_snapshot: str,
    allowed_write_paths: Sequence[str],
    attempts: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build a read-only integration manifest for one candidate snapshot."""
    repo = Path(root).resolve()
    if not repo.is_dir():
        raise IntegrationManifestError("integration root does not exist")
    task = _token(task_id, "task_id")
    if int(task_revision) < 1:
        raise IntegrationManifestError("task_revision must be positive")
    allowed = [_path(item, "allowed_write_path") for item in allowed_write_paths]
    if not allowed:
        raise IntegrationManifestError("allowed_write_paths must not be empty")
    base = _commit(repo, base_snapshot, "base_snapshot")
    candidate = _commit(repo, candidate_snapshot, "candidate_snapshot")
    parent = _commit(repo, _git(repo, "rev-parse", "HEAD").stdout.strip(), "parent_snapshot")
    changed_paths = _diff_paths(repo, base, candidate)
    scope_violations = [path for path in changed_paths if not _inside(path, allowed)]
    user_changes = _status_paths(repo)
    conflicts, merge_reason = _merge_dry_run(repo, parent, candidate)
    attempt_records = _attempts(
        attempts,
        accepted_bases=(base, candidate),
        allowed=allowed,
    )

    status = "ready"
    reasons: list[str] = []
    if scope_violations:
        status = "blocked"
        reasons.append("candidate changed paths exceed the declared write scope")
    if merge_reason:
        status = "blocked" if "unable" in merge_reason or "failed" in merge_reason else "human_required"
        reasons.append(merge_reason)
    if user_changes:
        status = "human_required" if status == "ready" else status
        reasons.append("parent worktree contains user changes")

    manifest: dict[str, Any] = {
        "schema": "agent-loop.integration-manifest.v1",
        "task_id": task,
        "task_revision": int(task_revision),
        "status": status,
        "repository": str(repo),
        "base_snapshot": base,
        "parent_snapshot": parent,
        "candidate_snapshot": candidate,
        "changed_paths": changed_paths,
        "allowed_write_paths": allowed,
        "scope_violations": scope_violations,
        "attempts": attempt_records,
        "conflicts": conflicts,
        "known_user_changes": user_changes,
        "human_gate": {
            "status": "pending" if status != "blocked" else "not_available",
            "required": status in {"human_required", "ready"},
            "approved": False,
            "decided_by": "",
            "reason": "; ".join(dict.fromkeys(reasons)) or "candidate is ready for human integration approval",
        },
        "rollback": {
            "available": True,
            "ref": parent,
            "method": "revert_or_restore_parent_snapshot only after human approval",
            "executed": False,
        },
        "apply": {
            "status": "not_applied",
            "method": "human-approved merge/cherry-pick",
            "applied_snapshot": "",
        },
    }
    validate_integration_manifest(manifest)
    return manifest


def validate_integration_manifest(manifest: Mapping[str, Any]) -> None:
    required = {
        "schema", "task_id", "task_revision", "status", "base_snapshot",
        "parent_snapshot", "candidate_snapshot", "changed_paths",
        "allowed_write_paths", "scope_violations", "attempts", "conflicts",
        "known_user_changes", "human_gate", "rollback", "apply",
    }
    missing = sorted(required - set(manifest))
    if missing:
        raise IntegrationManifestError("IntegrationManifest missing fields: " + ", ".join(missing))
    if manifest["schema"] != "agent-loop.integration-manifest.v1":
        raise IntegrationManifestError("unsupported IntegrationManifest schema")
    _token(manifest["task_id"], "task_id")
    if int(manifest["task_revision"]) < 1 or manifest["status"] not in _STATUSES:
        raise IntegrationManifestError("invalid IntegrationManifest identity or status")
    for field in ("base_snapshot", "parent_snapshot", "candidate_snapshot"):
        _commit_from_value(manifest[field], field)
    allowed = [_path(item, "allowed_write_path") for item in manifest["allowed_write_paths"]]
    for field in ("changed_paths", "scope_violations", "conflicts", "known_user_changes"):
        if not isinstance(manifest[field], list):
            raise IntegrationManifestError(f"IntegrationManifest.{field} must be a list")
    for path in manifest["changed_paths"]:
        normalized = _path(path, "changed path")
        if not _inside(normalized, allowed) and normalized not in manifest["scope_violations"]:
            raise IntegrationManifestError(f"changed path exceeds allowed scope: {normalized}")
    for path in manifest["scope_violations"]:
        normalized = _path(path, "scope violation path")
        if normalized not in manifest["changed_paths"] or _inside(normalized, allowed):
            raise IntegrationManifestError("scope_violations must identify out-of-scope changed paths")
    if manifest["scope_violations"]:
        if manifest["status"] not in {"blocked", "human_required"}:
            raise IntegrationManifestError("scope violations require a blocked or human_required manifest")
    attempts = manifest["attempts"]
    if not isinstance(attempts, list):
        raise IntegrationManifestError("IntegrationManifest.attempts must be a list")
    gate = manifest["human_gate"]
    if not isinstance(gate, Mapping) or bool(gate.get("approved")) and manifest["status"] not in {"approved", "applied", "rolled_back"}:
        raise IntegrationManifestError("human gate approval has an invalid manifest status")
    rollback = manifest["rollback"]
    if not isinstance(rollback, Mapping) or rollback.get("ref") != manifest["parent_snapshot"]:
        raise IntegrationManifestError("IntegrationManifest rollback ref must preserve parent_snapshot")
    apply = manifest["apply"]
    if not isinstance(apply, Mapping) or apply.get("status") not in {"not_applied", "applied", "rolled_back"}:
        raise IntegrationManifestError("invalid IntegrationManifest apply state")
    isolated = manifest.get("isolated_apply")
    if isolated is not None:
        if not isinstance(isolated, Mapping) or isolated.get("status") not in {"not_applied", "applied", "blocked"}:
            raise IntegrationManifestError("invalid isolated integration state")
        if isolated.get("status") == "applied":
            _ref(isolated.get("branch"), "isolated integration branch")
            _text(isolated.get("worktree"), "isolated integration worktree")
            _commit_from_value(isolated.get("applied_snapshot"), "isolated applied_snapshot")
            if isolated.get("parent_untouched") is not True:
                raise IntegrationManifestError("isolated integration must prove parent_untouched")


def write_integration_manifest(path: str | Path, manifest: Mapping[str, Any]) -> str:
    """Atomically persist a validated IntegrationManifest."""
    validate_integration_manifest(manifest)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=destination.name + ".", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(dict(manifest), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_name, destination)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
    return str(destination)


def approve_integration(
    manifest: Mapping[str, Any],
    *,
    approver: str,
    allow_disjoint_user_changes: bool = False,
) -> dict[str, Any]:
    """Record an explicit human approval without applying the candidate.

    A dirty parent, conflict, or scope violation cannot be approved by this
    helper unless the caller explicitly authorizes disjoint user changes. The
    disjoint mode still rejects any path overlap and never applies the
    candidate; the caller must perform the separately reviewed merge and then
    record its resulting snapshot.
    """
    validate_integration_manifest(manifest)
    user_changes = {
        _path(item, "known user change path") for item in manifest["known_user_changes"]
    }
    changed_paths = {
        _path(item, "changed path") for item in manifest["changed_paths"]
    }
    overlaps = sorted(
        left
        for left in changed_paths
        for right in user_changes
        if left == right or left.startswith(right + "/") or right.startswith(left + "/")
    )
    disjoint_dirty_approval = (
        allow_disjoint_user_changes
        and manifest["status"] == "human_required"
        and bool(user_changes)
        and not overlaps
        and not manifest["conflicts"]
        and not manifest["scope_violations"]
    )
    if manifest["status"] != "ready" and not disjoint_dirty_approval:
        raise IntegrationManifestError(
            "only a clean ready or explicitly disjoint human_required IntegrationManifest may pass the human gate"
        )
    decision_maker = _text(approver, "integration approver")
    updated = deepcopy(dict(manifest))
    updated["status"] = "approved"
    updated["human_gate"].update(
        {
            "status": "passed",
            "required": True,
            "approved": True,
            "decided_by": decision_maker,
            "reason": (
                "explicit human approval recorded for disjoint user changes; candidate not yet applied"
                if disjoint_dirty_approval
                else "explicit human approval recorded; candidate not yet applied"
            ),
        }
    )
    validate_integration_manifest(updated)
    return updated


def record_applied_snapshot(
    manifest: Mapping[str, Any], *, applied_snapshot: str
) -> dict[str, Any]:
    """Record a human-approved merge result after the caller has applied it."""
    validate_integration_manifest(manifest)
    if manifest["status"] != "approved" or not manifest["human_gate"].get("approved"):
        raise IntegrationManifestError("integration must pass the human gate before apply")
    applied = _commit_from_value(applied_snapshot, "applied_snapshot")
    updated = deepcopy(dict(manifest))
    updated["status"] = "applied"
    updated["human_gate"]["reason"] = (
        "explicit human approval recorded for disjoint user changes; candidate applied"
        if "disjoint user changes" in str(updated["human_gate"].get("reason", ""))
        else "explicit human approval recorded; candidate applied"
    )
    updated["apply"].update({"status": "applied", "applied_snapshot": applied})
    updated["rollback"].update(
        {
            "available": True,
            "method": "revert_or_restore parent_snapshot only after human review",
            "executed": False,
        }
    )
    validate_integration_manifest(updated)
    return updated


def auto_integrate_isolated(
    manifest: Mapping[str, Any],
    *,
    worktree_root: str | Path,
    branch_name: str | None = None,
) -> dict[str, Any]:
    """Apply a candidate to a new branch/worktree without touching its parent.

    This is the unattended integration path for a dirty parent checkout. It
    only proceeds when the current parent still matches the manifest and the
    candidate paths are disjoint from the recorded user changes. The created
    branch and worktree are retained as the reviewable output; the caller's
    parent checkout is never staged, committed, or reset.
    """
    validate_integration_manifest(manifest)
    if manifest["status"] not in {"ready", "human_required"}:
        raise IntegrationManifestError(
            "isolated auto-integration requires a ready or human_required manifest"
        )
    repository = Path(_text(manifest.get("repository"), "repository")).resolve()
    if not repository.is_dir():
        raise IntegrationManifestError("integration repository does not exist")
    current_parent = _commit(
        repository,
        _git(repository, "rev-parse", "HEAD").stdout.strip(),
        "current parent_snapshot",
    )
    if current_parent != manifest["parent_snapshot"]:
        raise IntegrationManifestError("parent snapshot drifted since IntegrationManifest planning")
    current_user_changes = _status_paths(repository)
    expected_user_changes = list(
        dict.fromkeys(
            _path(item, "known user change path")
            for item in manifest["known_user_changes"]
        )
    )
    if current_user_changes != expected_user_changes:
        raise IntegrationManifestError("parent user changes drifted since IntegrationManifest planning")
    changed_paths = [_path(item, "changed path") for item in manifest["changed_paths"]]
    user_changes = [_path(item, "known user change path") for item in manifest["known_user_changes"]]
    overlaps = sorted(
        left
        for left in changed_paths
        for right in user_changes
        if left == right or left.startswith(right + "/") or right.startswith(left + "/")
    )
    if manifest["conflicts"] or manifest["scope_violations"] or overlaps:
        raise IntegrationManifestError(
            "isolated auto-integration requires no conflicts, scope violations, or path overlap"
        )

    branch = branch_name or f"agent-loop/{manifest['task_id']}/integration-{manifest['task_revision']}"
    branch = _ref(branch, "isolated integration branch")
    branch_check = _git(
        repository,
        "show-ref",
        "--verify",
        f"refs/heads/{branch}",
        check=False,
    )
    if branch_check.returncode == 0:
        raise IntegrationManifestError(f"isolated integration branch already exists: {branch}")
    destination_root = Path(worktree_root).resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    worktree = Path(
        tempfile.mkdtemp(prefix=f"{manifest['task_id']}-integration-", dir=destination_root)
    )
    worktree.rmdir()
    branch_created = False
    try:
        # The parent may already be checked out by a dirty main or another
        # detached worktree. --force is safe here because this creates a new
        # branch in a new directory and all parent mutation was preflighted.
        _git(
            repository,
            "worktree",
            "add",
            "--force",
            "-b",
            branch,
            str(worktree),
            manifest["parent_snapshot"],
        )
        branch_created = True
        _git(worktree, "cherry-pick", "--no-edit", manifest["candidate_snapshot"])
        applied_snapshot = _commit(
            worktree,
            _git(worktree, "rev-parse", "HEAD").stdout.strip(),
            "isolated applied_snapshot",
        )
        applied_paths = _diff_paths(worktree, manifest["parent_snapshot"], applied_snapshot)
        if applied_paths != changed_paths:
            raise IntegrationManifestError(
                "isolated applied paths differ from planned candidate paths"
            )
        updated = deepcopy(dict(manifest))
        updated["isolated_apply"] = {
            "status": "applied",
            "branch": branch,
            "worktree": str(worktree),
            "parent_snapshot": manifest["parent_snapshot"],
            "applied_snapshot": applied_snapshot,
            "method": "isolated branch + cherry-pick",
            "parent_untouched": True,
        }
        updated["human_gate"]["reason"] = (
            str(updated["human_gate"].get("reason", ""))
            + "; isolated branch auto-applied; parent checkout unchanged"
        ).strip(" ;")
        validate_integration_manifest(updated)
        return updated
    except BaseException:
        _git(worktree, "cherry-pick", "--abort", check=False)
        if branch_created:
            _git(repository, "worktree", "remove", "--force", str(worktree), check=False)
            _git(repository, "branch", "-D", branch, check=False)
        shutil.rmtree(worktree, ignore_errors=True)
        raise


def manifest_digest(manifest: Mapping[str, Any]) -> str:
    """Return a stable digest for a manifest used as an approval reference."""
    validate_integration_manifest(manifest)
    encoded = json.dumps(dict(manifest), ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
