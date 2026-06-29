"""Tests for ``guardmcp doctor`` and ``guardmcp config validate``.

A valid config → PASS / exit 0. An H1 violation (networked transport with an
empty approval token and no insecure override) → FAIL / nonzero. Neither test
requires a live database: ``doctor`` WARNs (never FAILs) when MongoDB is
unreachable, so the verdict stays PASS / exit 0.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from guardmcp import cli

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_POLICY = REPO_ROOT / "policies" / "example.yaml"


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """Drop any GUARDMCP_* env the host set; give a writable audit path + policy."""
    for key in list(__import__("os").environ):
        if key.startswith("GUARDMCP_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GUARDMCP_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("GUARDMCP_POLICY_PATH", str(EXAMPLE_POLICY))
    # Unreachable URI so the doctor DB probe fails FAST and only WARNs.
    monkeypatch.setenv("GUARDMCP_MONGODB_URI", "mongodb://127.0.0.1:1/db")
    return monkeypatch


def _run(argv, capsys):
    try:
        cli.main(argv)
        code = 0
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 0
    return code, capsys.readouterr()


# ── config validate ──────────────────────────────────────────────────────────


def test_config_validate_valid_exit_0(clean_env, capsys):
    clean_env.setenv("GUARDMCP_TRANSPORT", "stdio")
    code, captured = _run(["config", "validate"], capsys)
    assert code == 0
    assert "VERDICT: PASS" in captured.out


def test_config_validate_h1_violation_fails(clean_env, capsys):
    # streamable-http + empty token + not allow_insecure → H1 FAIL.
    clean_env.setenv("GUARDMCP_TRANSPORT", "streamable-http")
    clean_env.setenv("GUARDMCP_APPROVAL_API_TOKEN", "")
    clean_env.setenv("GUARDMCP_APPROVAL_ALLOW_INSECURE", "false")
    code, captured = _run(["config", "validate"], capsys)
    assert code != 0
    assert "FAIL" in captured.out
    assert "H1" in captured.out


def test_config_validate_h1_satisfied_by_token(clean_env, capsys):
    clean_env.setenv("GUARDMCP_TRANSPORT", "streamable-http")
    clean_env.setenv("GUARDMCP_APPROVAL_API_TOKEN", "a-secret-token")
    code, captured = _run(["config", "validate"], capsys)
    assert code == 0
    assert "VERDICT: PASS" in captured.out


# ── doctor ────────────────────────────────────────────────────────────────────


def test_doctor_valid_db_unreachable_warns_exit_0(clean_env, capsys):
    clean_env.setenv("GUARDMCP_TRANSPORT", "stdio")
    code, captured = _run(["doctor"], capsys)
    out = captured.out
    assert code == 0
    assert "VERDICT: PASS" in out
    # DB unreachable should be a WARN, not a FAIL.
    assert "WARN" in out
    assert "mongodb" in out


def test_doctor_h1_violation_fails(clean_env, capsys):
    clean_env.setenv("GUARDMCP_TRANSPORT", "streamable-http")
    clean_env.setenv("GUARDMCP_APPROVAL_API_TOKEN", "")
    code, captured = _run(["doctor"], capsys)
    assert code != 0
    assert "VERDICT: FAIL" in captured.out
