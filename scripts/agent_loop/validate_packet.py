"""Schema and scope checks for Agent Loop packets and Phase 1 assets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from .errors import ValidationError

try:
    import yaml
except ModuleNotFoundError as exc:  # pragma: no cover - environment-specific
    raise RuntimeError("Agent Loop YAML validation requires PyYAML") from exc

ROOT = Path(__file__).resolve().parents[2]
DOMAIN_OWNERS = {"core", "trainer", "product", "teacher"}
PROFILE_ROLES = DOMAIN_OWNERS | {"test-verification", "context-integration"}
TASK_OWNERS = DOMAIN_OWNERS | {"context-integration"}
_CONTEXT_FORBIDDEN_KEYS = {"conversation", "chat_history", "raw_transcript", "full_transcript"}
_ADVISORY_STATUSES = {"empty", "applied", "unavailable", "blocked"}
_ADVISORY_LESSON_STATUSES = {"confirmed", "promoted"}


def load_yaml(path: str | Path) -> Any:
    target = Path(path)
    try:
        return yaml.safe_load(target.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValidationError(f"cannot read YAML asset {target}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ValidationError(f"invalid YAML in {target}: {exc}") from exc


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{label} must be a mapping")
    return value


def _require_keys(value: Mapping[str, Any], keys: set[str], label: str) -> None:
    missing = sorted(key for key in keys if key not in value)
    if missing:
        raise ValidationError(f"{label} missing fields: {', '.join(missing)}")


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValidationError(f"{label} must be a list")
    return value


def _repo_path_exists(raw: str, *, root: Path) -> bool:
    if raw in {".", "declared test scope only", "task scope", "ContextBrief", "contract refs"}:
        return True
    return (root / raw).exists()


def validate_profile(profile: Mapping[str, Any], *, root: str | Path = ROOT) -> None:
    root_path = Path(root).resolve()
    _require_keys(
        profile,
        {"protocol_version", "profile_id", "profile_revision", "agent_id", "role_type", "authority", "capabilities", "forbidden_roots", "docker", "execution_limits"},
        "AgentProfile",
    )
    if profile["protocol_version"] != 1 or not isinstance(profile["profile_revision"], int) or profile["profile_revision"] < 1:
        raise ValidationError("AgentProfile protocol_version must be 1 and profile_revision must be positive")
    agent_id = str(profile["agent_id"])
    if agent_id not in PROFILE_ROLES:
        raise ValidationError(f"unknown AgentProfile agent_id: {agent_id}")
    role_type = str(profile["role_type"])
    if agent_id == "test-verification" and role_type != "verification":
        raise ValidationError("test-verification must use role_type=verification")
    if agent_id in DOMAIN_OWNERS and role_type != "domain_owner":
        raise ValidationError(f"{agent_id} must use role_type=domain_owner")
    if agent_id == "context-integration" and role_type != "context_integration":
        raise ValidationError("context-integration must use role_type=context_integration")

    authority = _require_mapping(profile["authority"], "AgentProfile.authority")
    _require_keys(authority, {"boundary", "required_skills", "source_of_truth_refs", "handoff_recipients"}, "AgentProfile.authority")
    capabilities = _require_mapping(profile["capabilities"], "AgentProfile.capabilities")
    _require_keys(capabilities, {"read_roots", "write_roots", "test_write_roots", "tools", "can_modify_production_code", "can_modify_tests", "can_change_contracts"}, "AgentProfile.capabilities")
    for field in ("read_roots", "write_roots", "test_write_roots", "tools"):
        _list(capabilities[field], f"AgentProfile.capabilities.{field}")
    if agent_id == "test-verification" and capabilities["can_modify_production_code"]:
        raise ValidationError("Test / Verification cannot modify production code")
    for field in ("read_roots", "write_roots"):
        for raw in capabilities[field]:
            if not _repo_path_exists(str(raw), root=root_path):
                raise ValidationError(f"{agent_id} {field} references missing path: {raw}")
    forbidden = _list(profile["forbidden_roots"], "AgentProfile.forbidden_roots")
    for raw in forbidden:
        if str(raw).endswith("/**"):
            raw = str(raw)[:-3]
        if str(raw) and not _repo_path_exists(str(raw), root=root_path):
            raise ValidationError(f"{agent_id} forbidden_roots references missing path: {raw}")

    docker = _require_mapping(profile["docker"], "AgentProfile.docker")
    _require_keys(docker, {"allowed", "compose_files", "allowed_actions", "cleanup_required", "max_runtime_minutes"}, "AgentProfile.docker")
    compose_files = _list(docker["compose_files"], "AgentProfile.docker.compose_files")
    if docker["allowed"]:
        if not compose_files or int(docker["max_runtime_minutes"]) <= 0:
            raise ValidationError(f"{agent_id} Docker profile must declare compose files and positive runtime")
        for raw in compose_files:
            if not _repo_path_exists(str(raw), root=root_path):
                raise ValidationError(f"{agent_id} Docker compose file missing: {raw}")

    limits = _require_mapping(profile["execution_limits"], "AgentProfile.execution_limits")
    for field in ("max_attempts", "max_elapsed_minutes", "max_input_tokens", "max_output_tokens", "max_subtask_depth"):
        if int(limits.get(field, 0)) < 0:
            raise ValidationError(f"{agent_id} execution limit cannot be negative: {field}")
    if int(limits.get("max_subtask_depth", 0)) > 1 or bool(limits.get("may_spawn_subtasks", False)):
        raise ValidationError("domain Profiles may not recursively spawn subtasks; Coordinator owns dispatch")


def validate_context_index(index: Mapping[str, Any], *, root: str | Path = ROOT) -> None:
    root_path = Path(root).resolve()
    _require_keys(index, {"index_version", "workspace_snapshot", "generated_at", "entries", "maintenance"}, "ContextIndex")
    if index["index_version"] != 1 or not str(index["workspace_snapshot"]).strip():
        raise ValidationError("ContextIndex must declare version 1 and a non-empty workspace_snapshot")
    entries = _list(index["entries"], "ContextIndex.entries")
    if not entries:
        raise ValidationError("ContextIndex must contain at least one fact")
    ids: set[str] = set()
    for entry in entries:
        item = _require_mapping(entry, "ContextIndex entry")
        _require_keys(item, {"id", "domain", "claim", "source_refs", "verified_at", "verified_snapshot", "status", "confidence", "trigger_terms", "owner", "lesson_refs"}, "ContextIndex entry")
        if item["id"] in ids:
            raise ValidationError(f"duplicate ContextIndex id: {item['id']}")
        ids.add(str(item["id"]))
        if item["status"] not in {"confirmed", "inferred", "superseded"}:
            raise ValidationError(f"invalid ContextIndex status: {item['status']}")
        if item["status"] == "confirmed" and not str(item["verified_snapshot"]).strip():
            raise ValidationError(f"confirmed fact lacks verified_snapshot: {item['id']}")
        for source in _list(item["source_refs"], f"ContextIndex[{item['id']}].source_refs"):
            source_map = _require_mapping(source, "ContextIndex source_ref")
            _require_keys(source_map, {"path", "locator", "source_kind"}, "ContextIndex source_ref")
            if not _repo_path_exists(str(source_map["path"]), root=root_path):
                raise ValidationError(f"ContextIndex source path missing: {source_map['path']}")


def validate_test_matrix(matrix: Mapping[str, Any], *, root: str | Path = ROOT) -> None:
    root_path = Path(root).resolve()
    _require_keys(matrix, {"protocol_version", "matrix_version", "default_report", "failure_classes", "default_docker", "domains"}, "TestMatrix")
    if matrix["protocol_version"] != 1 or matrix["matrix_version"] != 1:
        raise ValidationError("TestMatrix protocol and matrix versions must be 1")
    failure_classes = _list(matrix["failure_classes"], "TestMatrix.failure_classes")
    if not failure_classes:
        raise ValidationError("TestMatrix must define failure classes")
    default_docker = _require_mapping(matrix["default_docker"], "TestMatrix.default_docker")
    _require_keys(default_docker, {"allowed_actions", "cleanup_required", "max_runtime_minutes"}, "TestMatrix.default_docker")
    default_actions = set(_list(default_docker["allowed_actions"], "TestMatrix.default_docker.allowed_actions"))
    if not default_docker["cleanup_required"] or int(default_docker["max_runtime_minutes"]) <= 0:
        raise ValidationError("TestMatrix default Docker policy must require cleanup and a positive runtime")

    domains = _list(matrix["domains"], "TestMatrix.domains")
    expected_domains = {"core", "trainer", "product", "teacher"}
    actual_domains: set[str] = set()
    for raw_domain in domains:
        domain = _require_mapping(raw_domain, "TestMatrix domain")
        _require_keys(domain, {"domain", "owner", "production_read_roots", "production_write_roots", "test_write_roots", "required_skills", "commands", "docker", "manual_gates"}, "TestMatrix domain")
        name = str(domain["domain"])
        if name in actual_domains or name not in expected_domains:
            raise ValidationError(f"invalid or duplicate TestMatrix domain: {name}")
        actual_domains.add(name)
        if domain["owner"] != name:
            raise ValidationError(f"TestMatrix owner must match domain: {name}")
        for field in ("production_read_roots", "production_write_roots", "test_write_roots", "required_skills", "manual_gates"):
            _list(domain[field], f"TestMatrix[{name}].{field}")
        for path in domain["production_read_roots"] + domain["test_write_roots"]:
            if not _repo_path_exists(str(path), root=root_path):
                raise ValidationError(f"TestMatrix[{name}] references missing path: {path}")
        commands = _list(domain["commands"], f"TestMatrix[{name}].commands")
        if not commands:
            raise ValidationError(f"TestMatrix[{name}] needs at least one command")
        for raw_command in commands:
            command = _require_mapping(raw_command, "TestMatrix command")
            _require_keys(command, {"id", "command", "cwd", "evidence"}, "TestMatrix command")
            if not str(command["command"]).strip() or not _repo_path_exists(str(command["cwd"]), root=root_path):
                raise ValidationError(f"TestMatrix[{name}] command has invalid command/cwd")
        docker = _require_mapping(domain["docker"], f"TestMatrix[{name}].docker")
        _require_keys(docker, {"compose_files", "allowed_actions"}, f"TestMatrix[{name}].docker")
        compose_files = _list(docker["compose_files"], f"TestMatrix[{name}].docker.compose_files")
        for compose in compose_files:
            if not _repo_path_exists(str(compose), root=root_path):
                raise ValidationError(f"TestMatrix[{name}] compose file missing: {compose}")
        actions = set(_list(docker["allowed_actions"], f"TestMatrix[{name}].docker.allowed_actions"))
        if not actions.issubset(default_actions):
            raise ValidationError(f"TestMatrix[{name}] Docker actions exceed default allowlist")
    if actual_domains != expected_domains:
        raise ValidationError(f"TestMatrix domains must be exactly {sorted(expected_domains)}")


def _contract_statuses(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        return [str(item) for item in value.values()]
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def validate_task_packet(packet: Mapping[str, Any]) -> None:
    required = {"protocol_version", "task_id", "revision", "requested_outcome", "authority", "ownership", "scope", "workspace", "inputs", "acceptance", "execution", "artifacts"}
    _require_keys(packet, required, "TaskPacket")
    if packet["protocol_version"] != 1 or int(packet["revision"]) < 1:
        raise ValidationError("TaskPacket protocol_version must be 1 and revision must be positive")
    ownership = _require_mapping(packet["ownership"], "TaskPacket.ownership")
    if ownership.get("primary_owner") not in TASK_OWNERS:
        raise ValidationError("TaskPacket primary_owner must be a domain owner or context-integration")
    scope = _require_mapping(packet["scope"], "TaskPacket.scope")
    for field in ("allowed_write_paths", "forbidden_paths", "declared_contracts"):
        _list(scope.get(field), f"TaskPacket.scope.{field}")
    _list(scope.get("allowed_test_write_paths", []), "TaskPacket.scope.allowed_test_write_paths")
    for contract in scope["declared_contracts"]:
        statuses = _contract_statuses(contract)
        if any(status.strip().lower() == "unknown" for status in statuses):
            raise ValidationError("TaskPacket cannot enter implementation with unknown contract impact")
    workspace = _require_mapping(packet["workspace"], "TaskPacket.workspace")
    if not str(workspace.get("snapshot_ref", "")).strip() or str(workspace["snapshot_ref"]).strip().lower() in {"current", "latest", "current latest"}:
        raise ValidationError("TaskPacket requires a reproducible workspace snapshot_ref")
    execution = _require_mapping(packet["execution"], "TaskPacket.execution")
    positive_budget_fields = ("max_owner_attempts", "max_elapsed_minutes", "max_role_runs", "max_model_input_tokens", "max_model_output_tokens", "max_model_turns")
    for field in positive_budget_fields:
        if int(execution.get(field, 0)) <= 0:
            raise ValidationError(f"TaskPacket execution budget must be positive: {field}")
    for field in ("max_subtasks", "max_subtask_depth"):
        if int(execution.get(field, -1)) < 0:
            raise ValidationError(f"TaskPacket execution budget cannot be negative: {field}")
    if int(execution.get("max_subtask_depth", 0)) > 1:
        raise ValidationError("TaskPacket max_subtask_depth cannot exceed 1")


def _reject_context_transcript(value: Any, path: str = "ContextBrief") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in _CONTEXT_FORBIDDEN_KEYS:
                raise ValidationError(
                    f"ContextBrief cannot carry raw conversation field: {path}.{key}"
                )
            _reject_context_transcript(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_context_transcript(child, f"{path}[{index}]")


def _validate_advisory(value: Any) -> None:
    advisory = _require_mapping(value, "ContextBrief.advisory")
    _require_keys(
        advisory,
        {"enabled", "status", "source_report_ref", "items", "omitted", "limits", "adoption"},
        "ContextBrief.advisory",
    )
    if not isinstance(advisory["enabled"], bool):
        raise ValidationError("ContextBrief.advisory.enabled must be boolean")
    if advisory["status"] not in _ADVISORY_STATUSES:
        raise ValidationError("ContextBrief.advisory.status is invalid")
    if not str(advisory["source_report_ref"] or "").strip():
        raise ValidationError("ContextBrief.advisory.source_report_ref must not be empty")
    items = _list(advisory["items"], "ContextBrief.advisory.items")
    item_ids: list[str] = []
    used_tokens = 0
    for index, raw_item in enumerate(items):
        item = _require_mapping(raw_item, f"ContextBrief.advisory.items[{index}]")
        _require_keys(
            item,
            {
                "lesson_id",
                "status",
                "advisory_only",
                "statement",
                "when",
                "avoid",
                "prefer",
                "preflight",
                "evidence_snapshot",
                "source_refs",
                "estimated_tokens",
            },
            f"ContextBrief.advisory.items[{index}]",
        )
        lesson_id = str(item["lesson_id"]).strip()
        if not lesson_id:
            raise ValidationError(f"ContextBrief.advisory.items[{index}].lesson_id must not be empty")
        if lesson_id in item_ids:
            raise ValidationError("ContextBrief.advisory lesson ids must be unique")
        item_ids.append(lesson_id)
        if item["status"] not in _ADVISORY_LESSON_STATUSES or item["advisory_only"] is not True:
            raise ValidationError("ContextBrief.advisory item is not an eligible advisory")
        for field in ("statement", "evidence_snapshot"):
            if not str(item[field] or "").strip():
                raise ValidationError(f"ContextBrief.advisory.items[{index}].{field} must not be empty")
        for field in ("when", "avoid", "prefer", "preflight", "source_refs"):
            values = _list(item[field], f"ContextBrief.advisory.items[{index}].{field}")
            if field in {"avoid", "prefer", "preflight", "source_refs"} and not values:
                raise ValidationError(f"ContextBrief.advisory.items[{index}].{field} must be non-empty")
        try:
            estimate = int(item["estimated_tokens"])
        except (TypeError, ValueError) as exc:
            raise ValidationError("ContextBrief.advisory estimated_tokens must be an integer") from exc
        if estimate < 1:
            raise ValidationError("ContextBrief.advisory estimated_tokens must be positive")
        used_tokens += estimate

    omitted = _list(advisory["omitted"], "ContextBrief.advisory.omitted")
    for index, raw_item in enumerate(omitted):
        item = _require_mapping(raw_item, f"ContextBrief.advisory.omitted[{index}]")
        if not str(item.get("lesson_id", "")).strip() or not str(item.get("reason", "")).strip():
            raise ValidationError("ContextBrief.advisory.omitted requires lesson_id and reason")

    limits = _require_mapping(advisory["limits"], "ContextBrief.advisory.limits")
    for field in ("max_items", "max_tokens"):
        try:
            if int(limits.get(field, 0)) < 1:
                raise ValidationError(f"ContextBrief.advisory.limits.{field} must be positive")
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"ContextBrief.advisory.limits.{field} must be positive") from exc
    if len(items) > int(limits["max_items"]) or used_tokens > int(limits["max_tokens"]):
        raise ValidationError("ContextBrief advisory exceeds its limits")
    if int(limits.get("used_items", -1)) != len(items) or int(limits.get("used_tokens", -1)) != used_tokens:
        raise ValidationError("ContextBrief advisory usage counters do not match items")

    adoption = _require_mapping(advisory["adoption"], "ContextBrief.advisory.adoption")
    _require_keys(adoption, {"status", "adopted_lesson_ids", "not_adopted_lesson_ids", "evidence_ref"}, "ContextBrief.advisory.adoption")
    if adoption["status"] not in {"not_recorded", "recorded"}:
        raise ValidationError("ContextBrief.advisory.adoption.status is invalid")
    adopted = _list(adoption["adopted_lesson_ids"], "ContextBrief.advisory.adoption.adopted_lesson_ids")
    not_adopted = _list(adoption["not_adopted_lesson_ids"], "ContextBrief.advisory.adoption.not_adopted_lesson_ids")
    if not set(str(item) for item in [*adopted, *not_adopted]).issubset(set(item_ids)):
        raise ValidationError("ContextBrief.advisory adoption references an unknown lesson")
    if set(str(item) for item in adopted) & set(str(item) for item in not_adopted):
        raise ValidationError("ContextBrief.advisory adoption cannot classify a lesson twice")
    if adoption["status"] == "recorded" and not str(adoption["evidence_ref"] or "").strip():
        raise ValidationError("recorded advisory adoption requires evidence_ref")
    if not advisory["enabled"] and items:
        raise ValidationError("disabled ContextBrief advisory cannot contain items")
    if advisory["status"] == "applied" and (not advisory["enabled"] or not items):
        raise ValidationError("applied ContextBrief advisory requires enabled items")


def validate_context_brief(context_brief: Mapping[str, Any]) -> None:
    """Validate the reusable minimum ContextBrief contract."""
    _require_keys(
        context_brief,
        {"task_id"},
        "ContextBrief",
    )
    if not str(context_brief.get("task_id", "")).strip():
        raise ValidationError("ContextBrief task_id must not be empty")
    snapshot = context_brief.get("context_snapshot") or context_brief.get("snapshot_id")
    if not str(snapshot or "").strip():
        raise ValidationError("ContextBrief requires a snapshot")
    try:
        revision = int(
            context_brief.get("packet_revision")
            or context_brief.get("revision")
            or 0
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError("ContextBrief packet revision must be an integer") from exc
    if revision < 1:
        raise ValidationError("ContextBrief packet revision must be positive")
    source_graph = context_brief.get("fact_source_graph") or context_brief.get("source_graph")
    if not isinstance(source_graph, list) or not source_graph:
        raise ValidationError("ContextBrief requires a non-empty source graph")
    for index, source in enumerate(source_graph):
        item = _require_mapping(source, f"ContextBrief source_graph[{index}]")
        if not str(item.get("path", "")).strip():
            raise ValidationError(f"ContextBrief source_graph[{index}] requires path")
    if "advisory" in context_brief:
        _validate_advisory(context_brief["advisory"])
    _reject_context_transcript(context_brief)


def validate_file(path: str | Path, kind: str) -> None:
    data = load_yaml(path)
    mapping = _require_mapping(data, str(path))
    if kind == "profile":
        validate_profile(mapping)
    elif kind == "context-index":
        validate_context_index(mapping)
    elif kind == "test-matrix":
        validate_test_matrix(mapping)
    elif kind == "task-packet":
        validate_task_packet(mapping)
    else:
        raise ValidationError(f"unknown validation kind: {kind}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("profile", "context-index", "test-matrix", "task-packet"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    validate_file(args.path, args.kind)
    print(f"PASS {args.kind}: {args.path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
