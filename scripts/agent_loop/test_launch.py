import unittest

from scripts.agent_loop.errors import ValidationError
from scripts.agent_loop.launch import RunnerLaunchSpec, build_launch_spec


def packet(snapshot="snapshot-1"):
    return {
        "protocol_version": 1,
        "task_id": "TASK-1",
        "revision": 1,
        "requested_outcome": "Make one bounded change",
        "authority": {},
        "ownership": {"primary_owner": "product"},
        "scope": {
            "allowed_write_paths": ["apps/web"],
            "forbidden_paths": ["models"],
            "declared_contracts": ["product-http: unchanged"],
        },
        "workspace": {"snapshot_ref": snapshot},
        "inputs": {},
        "acceptance": {},
        "execution": {
            "max_owner_attempts": 1,
            "max_elapsed_minutes": 20,
            "max_role_runs": 2,
            "max_model_input_tokens": 1000,
            "max_model_output_tokens": 800,
            "max_model_turns": 4,
            "max_subtasks": 0,
            "max_subtask_depth": 1,
        },
        "artifacts": {},
    }


def context(snapshot="snapshot-1"):
    return {
        "task_id": "TASK-1",
        "packet_revision": 1,
        "context_snapshot": snapshot,
        "context_floor_refs": [{"path": "AGENTS.md"}],
        "fact_source_graph": [{"path": "apps/web", "why": "target"}],
        "fact_ledger": [],
        "lessons": {"relevant_refs": []},
    }


def profile():
    return {
        "protocol_version": 1,
        "profile_id": "product-owner-v1",
        "profile_revision": 1,
        "agent_id": "product",
        "role_type": "domain_owner",
        "authority": {
            "boundary": "product",
            "required_skills": [],
            "source_of_truth_refs": [],
            "handoff_recipients": [],
        },
        "capabilities": {
            "read_roots": ["."],
            "write_roots": ["."],
            "test_write_roots": ["."],
            "tools": ["read", "edit"],
            "can_modify_production_code": True,
            "can_modify_tests": True,
            "can_change_contracts": False,
        },
        "forbidden_roots": [],
        "docker": {
            "allowed": False,
            "compose_files": [],
            "allowed_actions": [],
            "cleanup_required": True,
            "max_runtime_minutes": 0,
        },
        "execution_limits": {
            "max_attempts": 1,
            "max_elapsed_minutes": 20,
            "max_input_tokens": 1000,
            "max_output_tokens": 800,
            "max_subtask_depth": 0,
            "may_spawn_subtasks": False,
        },
    }


def build(**overrides):
    values = {
        "task_packet": packet(),
        "context_brief": context(),
        "profile": profile(),
        "task_packet_ref": "tasks/TASK-1.yaml",
        "context_brief_ref": "context/TASK-1.yaml",
        "profile_ref": "profiles/product.yaml",
        "attempt_id": "attempt-1",
        "write_scope": ("apps/web/frontend/src/App.tsx",),
        "max_turns": 2,
        "max_input_tokens": 900,
        "max_output_tokens": 700,
        "max_elapsed_minutes": 15,
        "subtask_depth": 0,
    }
    values.update(overrides)
    return build_launch_spec(**values)


class RunnerLaunchTests(unittest.TestCase):
    def test_builds_bounded_structured_payload(self):
        spec = build()
        self.assertIsInstance(spec, RunnerLaunchSpec)
        self.assertEqual(spec.request.task_id, "TASK-1")
        self.assertEqual(spec.request.profile_revision, "product-owner-v1@1")
        self.assertEqual(spec.request.write_scope, ("apps/web/frontend/src/App.tsx",))
        payload = spec.to_payload()
        self.assertEqual(payload["protocol_version"], 1)
        self.assertNotIn("raw_transcript", payload)
        self.assertEqual(payload["budgets"]["max_turns"], 2)

    def test_snapshot_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "snapshot"):
            build(context_brief=context("snapshot-2"))

    def test_write_scope_cannot_escape_packet_scope(self):
        with self.assertRaisesRegex(ValidationError, "exceeds TaskPacket scope"):
            build(write_scope=("services/teacher/app.py",))

    def test_budget_cannot_exceed_packet_or_profile(self):
        with self.assertRaisesRegex(ValidationError, "max_turns"):
            build(max_turns=5)
        with self.assertRaisesRegex(ValidationError, "TaskPacket budget"):
            build(max_input_tokens=1001)
        limited_profile = profile()
        limited_profile["execution_limits"]["max_input_tokens"] = 899
        with self.assertRaisesRegex(ValidationError, "input budget"):
            build(profile=limited_profile)

    def test_raw_conversation_is_rejected(self):
        brief = context()
        brief["raw_transcript"] = ["do not forward this"]
        with self.assertRaisesRegex(ValidationError, "raw conversation"):
            build(context_brief=brief)


if __name__ == "__main__":
    unittest.main()
