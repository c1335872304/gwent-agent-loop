"""Regression tests for the current documentation entry contract."""

from __future__ import annotations

import copy
import unittest
from pathlib import Path

from .check_docs import (
    validate_authority_delegation,
    validate_context_index_freshness,
    validate_context_policy,
    validate_documentation,
    validate_entry_cards,
)
from .errors import ValidationError
from .validate_packet import load_yaml

ROOT = Path(__file__).resolve().parents[2]
INDEX_PATH = ROOT / "docs/current/agent-loop/CONTEXT_INDEX.yaml"


class DocumentationConsistencyTests(unittest.TestCase):
    def test_current_documentation_contract_passes(self) -> None:
        validate_documentation(root=ROOT)

    def test_missing_domain_card_is_rejected(self) -> None:
        index = copy.deepcopy(load_yaml(INDEX_PATH))
        del index["entry_cards"]["product"]
        with self.assertRaisesRegex(ValidationError, "entry_cards must contain exactly"):
            validate_entry_cards(index, root=ROOT)

    def test_missing_card_marker_is_rejected(self) -> None:
        index = copy.deepcopy(load_yaml(INDEX_PATH))
        index["entry_cards"]["teacher"]["required_markers"] = ["Teacher", "missing-marker"]
        with self.assertRaisesRegex(ValidationError, "required_markers do not match"):
            validate_entry_cards(index, root=ROOT)

    def test_context_policy_is_required(self) -> None:
        index = copy.deepcopy(load_yaml(INDEX_PATH))
        del index["context_policy"]
        with self.assertRaisesRegex(ValidationError, "context_policy"):
            validate_context_policy(index, root=ROOT)

    def test_confirmed_facts_must_share_index_snapshot(self) -> None:
        index = copy.deepcopy(load_yaml(INDEX_PATH))
        index["entries"][0]["verified_snapshot"] = "different-snapshot"
        with self.assertRaisesRegex(ValidationError, "different verified_snapshot"):
            validate_context_index_freshness(index)

    def test_authority_documents_delegate_instead_of_repeating(self) -> None:
        validate_authority_delegation(root=ROOT)

    def test_cold_start_route_reaches_owner_card_skill_and_template(self) -> None:
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        onboarding = (ROOT / "docs/current/AGENT_ONBOARDING_INDEX.md").read_text(encoding="utf-8")
        context_index = (ROOT / "docs/current/agent-loop/CONTEXT_INDEX.yaml").read_text(encoding="utf-8")
        cards = (ROOT / "docs/current/agent-entry/README.md").read_text(encoding="utf-8")
        templates = (ROOT / "docs/current/agent-entry/TASK_TEMPLATES.md").read_text(encoding="utf-8")

        self.assertLess(agents.index("AGENT_ONBOARDING_INDEX.md"), agents.index("START_HERE.md"))
        self.assertLess(agents.index("CONTEXT_INDEX.yaml"), agents.index("START_HERE.md"))
        self.assertIn("read_order:", context_index)
        self.assertIn("authority_order:", context_index)
        self.assertIn("agent-entry/README.md", agents)
        for domain in ("CORE", "TRAINER", "PRODUCT", "TEACHER"):
            self.assertIn(f"agent-entry/{domain}.md", onboarding)
            self.assertIn(f"{domain}.md", cards)
        for heading in ("Product bug", "Core contract", "Training task", "Teacher privacy"):
            self.assertIn(f"## {heading}", templates)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
