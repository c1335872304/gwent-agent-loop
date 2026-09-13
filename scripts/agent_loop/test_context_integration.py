"""Context/integration ownership tests."""

from __future__ import annotations

import unittest

from .validate_packet import validate_task_packet


class ContextIntegrationTests(unittest.TestCase):
    def test_document_task_can_be_owned_without_faking_a_domain_owner(self) -> None:
        packet = {
            "protocol_version": 1,
            "task_id": "DOC-1",
            "revision": 1,
            "requested_outcome": "update Agent Loop navigation",
            "authority": {"repo_rules": ["AGENTS.md"]},
            "ownership": {"primary_owner": "context-integration"},
            "scope": {"allowed_write_paths": ["docs/current/agent-loop"], "forbidden_paths": ["src", "apps/web"], "declared_contracts": ["agent_loop_docs: unchanged"]},
            "workspace": {"snapshot_ref": "file-hash-manifest:abc"},
            "inputs": {"context_brief_ref": "docs/current/agent-loop/CONTEXT_BRIEF_TEMPLATE.yaml"},
            "acceptance": {"behavioral": ["links resolve"]},
            "execution": {"max_owner_attempts": 1, "max_elapsed_minutes": 30, "max_role_runs": 1, "max_subtasks": 0, "max_subtask_depth": 0, "max_model_input_tokens": 1000, "max_model_output_tokens": 1000, "max_model_turns": 2},
            "artifacts": {"task_root": ".agent-loop/tasks/DOC-1"},
        }
        validate_task_packet(packet)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
