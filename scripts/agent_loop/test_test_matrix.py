"""Test matrix and Docker allowlist validation tests."""

from __future__ import annotations

import unittest
from pathlib import Path

from .errors import ValidationError
from .validate_packet import load_yaml, validate_test_matrix

ROOT = Path(__file__).resolve().parents[2]


class TestMatrixTests(unittest.TestCase):
    def test_repository_test_matrix_is_valid(self) -> None:
        validate_test_matrix(load_yaml(ROOT / "docs/current/agent-loop/TEST_MATRIX.yaml"), root=ROOT)

    def test_matrix_rejects_unknown_docker_action(self) -> None:
        matrix = load_yaml(ROOT / "docs/current/agent-loop/TEST_MATRIX.yaml")
        matrix["domains"][0]["docker"]["allowed_actions"] = ["deploy"]
        with self.assertRaises(ValidationError):
            validate_test_matrix(matrix, root=ROOT)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
