"""Tests for policy loading and the H3 atomic-swap hot-reload fix."""

import pytest

from guardmcp.core.policy.loader import PolicyLoader

_VALID = """
agent: test-agent
mode: readonly
collections:
  allow:
    - customers
actions:
  allow:
    - find
"""

_INVALID = """
agent: test-agent
mode: INVALID_MODE
"""


def test_load_valid_policy(tmp_path):
    p = tmp_path / "policy.yaml"
    p.write_text(_VALID)
    loader = PolicyLoader(p)
    loader.load()
    assert loader.get("test-agent") is not None


def test_invalid_reload_keeps_previous(tmp_path):
    p = tmp_path / "policy.yaml"
    p.write_text(_VALID)
    loader = PolicyLoader(p)
    loader.load()
    assert loader.get("test-agent") is not None

    # Overwrite with invalid policy; reload must raise but keep the previous map.
    p.write_text(_INVALID)
    with pytest.raises(Exception):
        loader.load()
    # H3: atomic swap means the previously loaded policy is still present.
    assert loader.get("test-agent") is not None


def test_missing_file_does_not_raise(tmp_path):
    loader = PolicyLoader(tmp_path / "does_not_exist.yaml")
    loader.load()  # must not raise
    assert loader.get("anyone") is None
