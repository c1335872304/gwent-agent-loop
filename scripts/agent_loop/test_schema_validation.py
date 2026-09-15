"""Negative tests for packet and run-manifest guards."""

from __future__ import annotations

import unittest

from .errors import ValidationError
from .manifest import validate_run_manifest
from .validate_packet import validate_context_brief, validate_task_packet


class SchemaValidationTests(unittest.TestCase):
    def test_context_brief_requires_snapshot_and_source_graph(self) -> None:
        brief = {"task_id": "T1", "packet_revision": 1}
        with self.assertRaises(ValidationError):
            validate_context_brief(brief)
        brief.update(
            {
                "context_snapshot": "s1",
                "fact_source_graph": [{"path": "AGENTS.md"}],
            }
        )
        validate_context_brief(brief)

    def test_context_brief_rejects_raw_conversation(self) -> None:
        brief = {
            "task_id": "T1",
            "packet_revision": 1,
            "context_snapshot": "s1",
            "fact_source_graph": [{"path": "AGENTS.md"}],
            "chat_history": ["do not forward"],
        }
        with self.assertRaisesRegex(ValidationError, "raw conversation"):
            validate_context_brief(brief)

    def test_context_brief_rejects_prompt_and_messages(self) -> None:
        for field in ("prompt", "messages"):
            brief = {
                "task_id": "T1",
                "packet_revision": 1,
                "context_snapshot": "s1",
                "fact_source_graph": [{"path": "AGENTS.md"}],
                field: ["do not forward"],
            }
            with self.subTest(field=field), self.assertRaisesRegex(ValidationError, "raw conversation"):
                validate_context_brief(brief)

    def test_task_packet_rejects_unknown_contract_and_latest_snapshot(self) -> None:
        packet = {
            "protocol_version": 1,
            "task_id": "T1",
            "revision": 1,
            "requested_outcome": "x",
            "authority": {},
            "ownership": {"primary_owner": "product"},
            "scope": {"allowed_write_paths": ["apps/web"], "forbidden_paths": [], "declared_contracts": ["core_http: unknown"]},
            "workspace": {"snapshot_ref": "latest"},
            "inputs": {},
            "acceptance": {},
            "execution": {"max_owner_attempts": 1, "max_elapsed_minutes": 1, "max_role_runs": 1, "max_subtasks": 0, "max_subtask_depth": 0, "max_model_input_tokens": 1, "max_model_output_tokens": 1, "max_model_turns": 1},
            "artifacts": {"task_root": ".agent-loop/tasks/T1"},
        }
        with self.assertRaises(ValidationError):
            validate_task_packet(packet)

    def test_run_manifest_rejects_budget_overrun(self) -> None:
        manifest = {
            "protocol_version": 1,
            "run_id": "R1",
            "task_id": "T1",
            "task_revision": 1,
            "runner": "manual",
            "status": "running",
            "workspace": {"base_snapshot": "s1"},
            "budget": {"max_role_runs": 1, "max_subtasks": 0, "max_input_tokens": 10, "max_output_tokens": 10, "max_model_turns": 1, "max_elapsed_minutes": 1, "role_runs_used": 2, "subtasks_used": 0, "input_tokens_used": 0, "output_tokens_used": 0, "model_turns_used": 0, "elapsed_minutes": 0},
            "role_runs": [],
            "artifacts": [],
            "state_events": [],
            "gates": [],
            "termination": {},
        }
        with self.assertRaises(ValidationError):
            validate_run_manifest(manifest)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
