"""Deterministic checks for Agent onboarding cards and current-doc semantics."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .errors import ValidationError
from .validate_packet import load_yaml

ROOT = Path(__file__).resolve().parents[2]

EXPECTED_ENTRY_CARDS = {
    "core": {
        "card": "docs/current/agent-entry/CORE.md",
        "owner": "core",
        "skill": ".agents/skills/core-environment/SKILL.md",
        "required_markers": ("Core", "check_schema.py", "handoff"),
    },
    "trainer": {
        "card": "docs/current/agent-entry/TRAINER.md",
        "owner": "trainer",
        "skill": ".agents/skills/training-config/SKILL.md",
        "required_markers": ("Trainer", "validate_training.py", "handoff"),
    },
    "product": {
        "card": "docs/current/agent-entry/PRODUCT.md",
        "owner": "product",
        "skill": ".agents/skills/product-integration/SKILL.md",
        "required_markers": ("Product", "npm run build", "handoff"),
    },
    "teacher": {
        "card": "docs/current/agent-entry/TEACHER.md",
        "owner": "teacher",
        "skill": ".agents/skills/teacher-explanation/SKILL.md",
        "required_markers": ("Teacher", "check_teacher.py", "handoff"),
    },
}

EXPECTED_CONTEXT_POLICY = {
    "read_order": (
        "user_request_and_safety",
        "AGENTS.md",
        "docs/current/AGENT_ONBOARDING_INDEX.md",
        "docs/current/agent-loop/CONTEXT_INDEX.yaml#context_policy",
        "docs/current/agent-loop/START_HERE.md",
        "docs/current/agent-loop/CURRENT_STATE.md",
        "domain_entry_card_then_skill_contract",
        "task_specific_code_test_and_lessons",
    ),
    "authority_order": (
        "user_request_and_safety",
        "AGENTS.md",
        "domain_skill_and_contract",
        "current_code_and_snapshot",
        "task_packet_and_reports",
        "archive",
    ),
    "required_floor": (
        "AGENTS.md",
        "docs/current/AGENT_ONBOARDING_INDEX.md",
        "docs/current/agent-loop/CONTEXT_INDEX.yaml",
        "docs/current/agent-loop/START_HERE.md",
        "docs/current/agent-loop/CURRENT_STATE.md",
    ),
    "domain_route": "docs/current/agent-entry/<DOMAIN>.md -> Skill -> contract -> nearest code/test",
    "default_exclusions": (
        "raw conversation",
        "full repository scan",
        "historical archive",
        "models/v3/policy.pt unless Trainer task",
        "external ZIPs",
    ),
    "handoff_payload": (
        "TaskPacket",
        "ContextBrief",
        "ChangeReport",
        "final_snapshot",
        "contract_diff",
    ),
    "stop_on": (
        "missing_authority",
        "conflicting_contract",
        "snapshot_drift",
        "privacy_uncertainty",
        "budget_or_permission_uncertainty",
    ),
}

STALE_CURRENT_MARKERS = (
    "initial-baseline-pending",
    "Proposed（地基文档，尚未启用自动执行）",
    "真实 Host-backed rebind 与独立进程恢复仍待现场试点",
    "当前阶段三继续验证多角色 Scheduler",
    "当前状态是“非训练产品链路基本通过",
)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{label} must be a mapping")
    return value


def validate_entry_cards(index: Mapping[str, Any], *, root: str | Path = ROOT) -> None:
    """Require one complete, source-linked card for each domain Owner."""
    root_path = Path(root).resolve()
    cards = _mapping(index.get("entry_cards"), "ContextIndex.entry_cards")
    expected_domains = set(EXPECTED_ENTRY_CARDS)
    if set(cards) != expected_domains:
        raise ValidationError(
            "ContextIndex.entry_cards must contain exactly: "
            + ", ".join(sorted(expected_domains))
        )

    for domain, expected in EXPECTED_ENTRY_CARDS.items():
        item = _mapping(cards.get(domain), f"ContextIndex.entry_cards.{domain}")
        for key in ("card", "owner", "skill", "required_markers"):
            if key not in item:
                raise ValidationError(f"ContextIndex.entry_cards.{domain} missing {key}")
        for key in ("card", "owner", "skill"):
            if item[key] != expected[key]:
                raise ValidationError(
                    f"ContextIndex.entry_cards.{domain}.{key} must be {expected[key]}"
                )
        markers = item["required_markers"]
        if not isinstance(markers, list) or not markers:
            raise ValidationError(
                f"ContextIndex.entry_cards.{domain}.required_markers must be a non-empty list"
            )
        if tuple(markers) != expected["required_markers"]:
            raise ValidationError(
                f"ContextIndex.entry_cards.{domain}.required_markers do not match the card contract"
            )
        card_path = root_path / str(item["card"])
        skill_path = root_path / str(item["skill"])
        if not card_path.is_file():
            raise ValidationError(f"entry card missing: {item['card']}")
        if not skill_path.is_file():
            raise ValidationError(f"entry card skill missing: {item['skill']}")
        card_text = card_path.read_text(encoding="utf-8")
        missing = [marker for marker in markers if str(marker) not in card_text]
        if missing:
            raise ValidationError(
                f"entry card {item['card']} missing required markers: {', '.join(missing)}"
            )


def validate_context_policy(index: Mapping[str, Any], *, root: str | Path = ROOT) -> None:
    """Require one machine-readable context assembly and stop policy."""
    root_path = Path(root).resolve()
    policy = _mapping(index.get("context_policy"), "ContextIndex.context_policy")
    if policy.get("version") != 1:
        raise ValidationError("ContextIndex.context_policy.version must be 1")

    for key, expected in EXPECTED_CONTEXT_POLICY.items():
        actual = policy.get(key)
        if key == "domain_route":
            if actual != expected:
                raise ValidationError(
                    "ContextIndex.context_policy.domain_route must be the shared domain route"
                )
            continue
        if not isinstance(actual, list) or tuple(actual) != expected:
            raise ValidationError(
                f"ContextIndex.context_policy.{key} must match the shared context contract"
            )

    for relative_path in EXPECTED_CONTEXT_POLICY["required_floor"]:
        if not (root_path / relative_path).is_file():
            raise ValidationError(f"context policy floor file missing: {relative_path}")


def validate_context_index_freshness(index: Mapping[str, Any]) -> None:
    """Keep current fact entries bound to the same declared index snapshot."""
    snapshot = index.get("workspace_snapshot")
    generated_at = index.get("generated_at")
    if not isinstance(snapshot, str) or not snapshot.strip() or "<" in snapshot:
        raise ValidationError("ContextIndex.workspace_snapshot must identify a real snapshot")
    if not isinstance(generated_at, str) or not generated_at.strip() or "YYYY" in generated_at:
        raise ValidationError("ContextIndex.generated_at must identify the verification time")

    entries = index.get("entries")
    if not isinstance(entries, list):
        raise ValidationError("ContextIndex.entries must be a list")
    for entry in entries:
        item = _mapping(entry, "ContextIndex.entries[]")
        if item.get("status") == "confirmed":
            if item.get("verified_snapshot") != snapshot:
                raise ValidationError(
                    f"confirmed fact {item.get('id', '<unknown>')} has a different verified_snapshot"
                )
            if item.get("verified_at") != generated_at:
                raise ValidationError(
                    f"confirmed fact {item.get('id', '<unknown>')} has a different verified_at"
                )


def validate_authority_delegation(*, root: str | Path = ROOT) -> None:
    """Prevent the human-facing entry documents from becoming duplicates."""
    root_path = Path(root).resolve()
    required_markers = {
        root_path / "docs/current/AGENT_ONBOARDING_INDEX.md": (
            "文档职责（单向引用）",
            "首次读取顺序、责任域路由、事实来源和验证等级",
        ),
        root_path / "docs/current/agent-loop/START_HERE.md": (
            "本页不复制这些表",
            "context_policy",
            "必须停止",
        ),
        root_path / "docs/current/AGENT_LOOP_NAVIGATION.md": (
            "维护附录",
            "不再复制入口表、领域路由或当前状态",
            "当前能力、现场证据、关闭的能力和路线阶段只读取",
        ),
        root_path / "docs/current/agent-loop/README.md": (
            "本页只做模板目录",
            "不复制上述协议",
        ),
    }
    for path, markers in required_markers.items():
        if not path.is_file():
            raise ValidationError(f"authority document missing: {path.relative_to(root_path)}")
        text = path.read_text(encoding="utf-8")
        missing = [marker for marker in markers if marker not in text]
        if missing:
            raise ValidationError(
                f"{path.relative_to(root_path)} missing delegation markers: {', '.join(missing)}"
            )

    forbidden_duplicates = {
        root_path / "docs/current/agent-loop/START_HERE.md": (
            "## 先判断任务类型",
            "| 问题涉及 | Owner | 必读 Skill | 事实来源 |",
        ),
        root_path / "docs/current/AGENT_LOOP_NAVIGATION.md": (
            "## 首次进入项目的读取顺序",
            "## 按问题路由",
            "当前推进到三阶段路线图的阶段三",
        ),
        root_path / "docs/current/agent-loop/README.md": (
            "## 当前默认上下文",
            "PILOT_018_REPORT.md 是当前现场证据",
        ),
    }
    for path, markers in forbidden_duplicates.items():
        text = path.read_text(encoding="utf-8")
        hits = [marker for marker in markers if marker in text]
        if hits:
            raise ValidationError(
                f"{path.relative_to(root_path)} repeats delegated content: {', '.join(hits)}"
            )


def validate_context_templates(*, root: str | Path = ROOT) -> None:
    """Keep task artifacts linked to the shared policy instead of copying it."""
    root_path = Path(root).resolve()
    required_refs = {
        root_path / "docs/current/agent-loop/TASK_PACKET_TEMPLATE.yaml": (
            "context_policy_ref: \"docs/current/agent-loop/CONTEXT_INDEX.yaml#context_policy\"",
        ),
        root_path / "docs/current/agent-loop/CONTEXT_BRIEF_TEMPLATE.yaml": (
            "context_policy_ref: \"docs/current/agent-loop/CONTEXT_INDEX.yaml#context_policy\"",
            "included_refs: []",
            "excluded_refs: []",
            "authority_conflicts: []",
        ),
        root_path / "docs/current/agent-loop/CONTEXT_INDEX_TEMPLATE.yaml": (
            "context_policy:",
            "default_exclusions:",
            "handoff_payload:",
            "stop_on:",
        ),
    }
    for path, markers in required_refs.items():
        if not path.is_file():
            raise ValidationError(f"context template missing: {path.relative_to(root_path)}")
        text = path.read_text(encoding="utf-8")
        missing = [marker for marker in markers if marker not in text]
        if missing:
            raise ValidationError(
                f"{path.relative_to(root_path)} missing context markers: {', '.join(missing)}"
            )


def validate_current_doc_semantics(*, root: str | Path = ROOT) -> None:
    """Reject known stale current-state claims and require current anchors."""
    root_path = Path(root).resolve()
    active_docs = [
        path
        for path in root_path.rglob("*.md")
        if "archive" not in path.parts and ".agent-loop" not in path.parts
    ]
    stale_hits = []
    for path in active_docs:
        text = path.read_text(encoding="utf-8", errors="replace")
        for marker in STALE_CURRENT_MARKERS:
            if marker in text:
                stale_hits.append(f"{path.relative_to(root_path)} contains {marker}")
    if stale_hits:
        raise ValidationError("stale current-doc markers:\n  " + "\n  ".join(stale_hits))

    current_state = root_path / "docs/current/agent-loop/CURRENT_STATE.md"
    plan = root_path / "docs/current/AGENT_LOOP_PLAN.md"
    test_plan = root_path / "docs/current/PROJECT_TEST_PLAN.md"
    required_markers = {
        current_state: ("Canonical current-state document", "PILOT_018_REPORT.md"),
        plan: ("稳定协议", "CURRENT_STATE.md", "IDEAL_LOOP_3_STAGE_PLAN.md"),
        test_plan: ("历史快照", "snapshot", "TestReport"),
    }
    for path, markers in required_markers.items():
        if not path.is_file():
            raise ValidationError(f"required current document missing: {path.relative_to(root_path)}")
        text = path.read_text(encoding="utf-8")
        missing = [marker for marker in markers if marker not in text]
        if missing:
            raise ValidationError(
                f"{path.relative_to(root_path)} missing current-doc markers: {', '.join(missing)}"
            )

    old_plan = root_path / "docs/current/LOGIC_OPTIMIZATION_PLAN.md"
    if old_plan.exists():
        raise ValidationError(
            "completed logic optimization plan must stay archived: "
            "docs/current/archive/design/LOGIC_OPTIMIZATION_PLAN.md"
        )


def validate_documentation(*, root: str | Path = ROOT) -> None:
    root_path = Path(root).resolve()
    index_path = root_path / "docs/current/agent-loop/CONTEXT_INDEX.yaml"
    index = _mapping(load_yaml(index_path), str(index_path))
    validate_entry_cards(index, root=root_path)
    validate_context_policy(index, root=root_path)
    validate_context_index_freshness(index)
    validate_authority_delegation(root=root_path)
    validate_context_templates(root=root_path)
    validate_current_doc_semantics(root=root_path)


if __name__ == "__main__":  # pragma: no cover
    validate_documentation()
    print("PASS documentation consistency: 4 entry cards/current markers")
