"""Run the deterministic Agent Loop asset and control-plane checks."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agent_loop.validate_packet import load_yaml, validate_context_index, validate_profile, validate_test_matrix  # noqa: E402


def main() -> int:
    profile_dir = ROOT / "docs/current/agent-loop/profiles"
    profiles = sorted(profile_dir.glob("*.yaml"))
    if len(profiles) != 6:
        raise ValueError(f"expected 6 AgentProfiles, found {len(profiles)}")
    for path in profiles:
        validate_profile(load_yaml(path), root=ROOT)
    context_index = ROOT / "docs/current/agent-loop/CONTEXT_INDEX.yaml"
    validate_context_index(load_yaml(context_index), root=ROOT)
    test_matrix = ROOT / "docs/current/agent-loop/TEST_MATRIX.yaml"
    validate_test_matrix(load_yaml(test_matrix), root=ROOT)
    test_agent_path = ROOT / ".codex/agents/test-verification.toml"
    test_agent = tomllib.loads(test_agent_path.read_text(encoding="utf-8"))
    if test_agent.get("name") != "test-verification":
        raise ValueError("test-verification Agent config has an invalid name")
    instructions = str(test_agent.get("developer_instructions", ""))
    required_markers = ("TEST_MATRIX.yaml", "HUMAN_REQUIRED", "policy.pt", "Docker")
    missing_markers = [marker for marker in required_markers if marker not in instructions]
    if missing_markers:
        raise ValueError("test-verification Agent config is missing markers: " + ", ".join(missing_markers))
    navigation = (ROOT / "docs/current/AGENT_LOOP_NAVIGATION.md").read_text(encoding="utf-8")
    lessons = (ROOT / "docs/current/agent-loop/LESSONS_LEARNED.md").read_text(encoding="utf-8")
    required_write_markers = ("Windows", "LL-007", "LL-008", "not applied")
    missing_write_markers = [marker for marker in required_write_markers if marker not in navigation + lessons]
    if missing_write_markers:
        raise ValueError("Windows write preflight is missing markers: " + ", ".join(missing_write_markers))
    print(
        f"PASS agent-loop assets: profiles={len(profiles)} context_index={context_index} "
        f"test_matrix={test_matrix} test_agent={test_agent_path}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
