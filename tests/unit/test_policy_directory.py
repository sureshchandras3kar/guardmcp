"""#6 — PolicyLoader accepts a directory of *.yaml/*.yml files, merging + resolving
extends-inheritance ACROSS files. Single-file behavior is unchanged."""

import pytest

from guardmcp.core.policy.loader import PolicyLoader


def test_directory_loads_and_resolves_cross_file(tmp_path):
    # File A defines a role:* template.
    (tmp_path / "10-roles.yaml").write_text(
        """
agent: "role:reader"
mode: readonly
collections:
  allow:
    - customers
actions:
  allow:
    - find
    - count
mask_fields:
  - email
"""
    )
    # File B defines a real agent that extends the template from file A.
    (tmp_path / "20-agents.yml").write_text(
        """
agent: analyst
extends: "role:reader"
collections:
  allow:
    - orders
"""
    )
    loader = PolicyLoader(tmp_path)
    loader.load()

    # The role template is dropped from get(); the agent is fully resolved.
    assert loader.get("role:reader") is None
    p = loader.get("analyst")
    assert p is not None
    assert p.mode == "readonly"
    # inherited from the template + own additions (order-preserving union)
    assert set(p.collections.allow) == {"customers", "orders"}
    assert "find" in p.actions.allow
    assert "email" in p.mask_fields


def test_directory_duplicate_agent_across_files_raises(tmp_path):
    (tmp_path / "a.yaml").write_text(
        """
agent: dup
mode: readonly
"""
    )
    (tmp_path / "b.yaml").write_text(
        """
agent: dup
mode: readonly
"""
    )
    loader = PolicyLoader(tmp_path)
    with pytest.raises(ValueError) as exc:
        loader.load()
    msg = str(exc.value)
    assert "dup" in msg
    assert "a.yaml" in msg and "b.yaml" in msg


def test_single_file_path_unchanged(tmp_path):
    f = tmp_path / "policy.yaml"
    f.write_text(
        """
agent: solo
mode: readonly
collections:
  allow:
    - customers
actions:
  allow:
    - find
"""
    )
    loader = PolicyLoader(f)
    loader.load()
    p = loader.get("solo")
    assert p is not None
    assert p.collections.allow == ["customers"]


def test_directory_reload_picks_up_new_file(tmp_path):
    (tmp_path / "a.yaml").write_text(
        """
agent: one
mode: readonly
"""
    )
    loader = PolicyLoader(tmp_path)
    loader.load()
    assert loader.get("one") is not None
    assert loader.get("two") is None

    # Add a second file and reload — cross-file detection of the new agent.
    (tmp_path / "b.yaml").write_text(
        """
agent: two
mode: readonly
"""
    )
    loader.load()
    assert loader.get("two") is not None
