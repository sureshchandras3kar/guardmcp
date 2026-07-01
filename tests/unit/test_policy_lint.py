"""Tests for ``guardmcp policy lint``.

Covers: the shipped ``policies/example.yaml`` lints clean (exit 0, warnings ok);
an invalid-schema policy (bad mode) is a hard error (nonzero); a deliberately
dangerous policy raises warnings; ``--strict`` promotes warnings to a nonzero
exit. CLI is driven via ``guardmcp.cli.main([...])``.
"""

from __future__ import annotations

from pathlib import Path

from guardmcp import cli

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_POLICY = REPO_ROOT / "policies" / "example.yaml"


def _run(argv, capsys):
    try:
        cli.main(argv)
        code = 0
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 0
    return code, capsys.readouterr()


DANGEROUS = """\
agent: risky-bot
mode: readwrite
collections:
  allow:
    - "*"
actions:
  allow:
    - find
    - update_one
    - drop
approval:
  high: false
  critical: false
mask_fields: []
"""

INVALID_MODE = """\
agent: broken-bot
mode: superuser
collections:
  allow:
    - customers
"""


def test_example_policy_clean_exit_0(capsys):
    code, captured = _run(["policy", "lint", str(EXAMPLE_POLICY)], capsys)
    # Clean policy: exit 0 even if heuristic warnings are emitted (no errors).
    assert code == 0
    assert "0 error(s)" in captured.out


def test_invalid_schema_bad_mode_errors(tmp_path, capsys):
    p = tmp_path / "bad.yaml"
    p.write_text(INVALID_MODE)
    code, captured = _run(["policy", "lint", str(p)], capsys)
    assert code != 0
    # Schema/parse failures go to stderr via the loader except handler.
    assert "ERROR" in (captured.out + captured.err)


def test_dangerous_policy_warns_exit_0(tmp_path, capsys):
    p = tmp_path / "danger.yaml"
    p.write_text(DANGEROUS)
    code, captured = _run(["policy", "lint", str(p)], capsys)
    out = captured.out
    # Warnings alone do not fail without --strict.
    assert code == 0
    assert "WARN" in out
    # The specific dangers we baked in should surface.
    assert "*" in out  # wide-open collections
    assert "approval.high" in out  # unguarded HIGH writes
    assert "PII" in out  # unmasked PII heuristic


def test_dangerous_policy_strict_fails(tmp_path, capsys):
    p = tmp_path / "danger.yaml"
    p.write_text(DANGEROUS)
    code, captured = _run(["policy", "lint", "--strict", str(p)], capsys)
    assert code != 0
    # Under --strict, warnings render as ERROR.
    assert "ERROR" in captured.out


def test_missing_path_errors(tmp_path, capsys):
    code, captured = _run(["policy", "lint", str(tmp_path / "nope.yaml")], capsys)
    assert code != 0
