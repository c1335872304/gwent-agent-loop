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
    validate_current_doc_semantics(root=root_path)


if __name__ == "__main__":  # pragma: no cover
    validate_documentation()
    print("PASS documentation consistency: 4 entry cards/current markers")
