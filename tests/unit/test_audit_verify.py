"""Tests for ``guardmcp audit verify`` + the underlying ``verify_chain``.

Builds a REAL signed chain via :class:`AuditLogger` (no hand-rolled HMAC) and
checks: clean chain verifies (exit 0); a tampered record reports the FIRST bad
line + nonzero exit; a log with no ``_hmac`` (or no secret) is "not verifiable"
+ nonzero; empty/missing files are handled gracefully. CLI is driven via
``guardmcp.cli.main([...])`` (no shelling out).
"""

from __future__ import annotations

import asyncio
import json

import pytest

from guardmcp import cli
from guardmcp.core.audit.logger import AuditLogger
from guardmcp.core.audit.verify import verify_chain

SECRET = "test-secret-key"


def _write_signed_chain(path, n=3, secret=SECRET):
    """Write ``n`` HMAC-signed audit records via the real AuditLogger."""

    async def _run():
        logger = AuditLogger(path, hmac_secret=secret)
        try:
            for i in range(n):
                rec = logger.build(
                    agent="bot",
                    collection="customers",
                    action="find",
                    status="allowed",
                    request_id=f"req-{i}",
                )
                await logger.log(rec)
        finally:
            await logger.aclose()

    asyncio.run(_run())


def _run_cli(argv):
    """Invoke cli.main; return the exit code (subcommands raise SystemExit)."""
    try:
        cli.main(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 0
    return 0


# ── verify_chain (unit) ──────────────────────────────────────────────────────


def test_clean_chain_verifies(tmp_path):
    log = tmp_path / "audit.jsonl"
    _write_signed_chain(log, n=3)
    result = verify_chain(log, SECRET)
    assert result.ok is True
    assert result.status == "ok"
    assert result.records == 3
    assert result.exit_code == 0


def test_tamper_reports_first_bad_line(tmp_path):
    log = tmp_path / "audit.jsonl"
    _write_signed_chain(log, n=4)
    lines = log.read_text().splitlines()
    # Tamper the SECOND record's payload, leaving its _hmac stale.
    rec = json.loads(lines[1])
    rec["collection"] = "payroll"  # was "customers"
    lines[1] = json.dumps(rec, separators=(",", ":"))
    log.write_text("\n".join(lines) + "\n")

    result = verify_chain(log, SECRET)
    assert result.ok is False
    assert result.status == "bad_chain"
    assert result.bad_line == 2  # first bad line is the tampered one
    assert result.exit_code != 0


def test_no_hmac_log_not_verifiable(tmp_path):
    log = tmp_path / "audit.jsonl"
    # Records written with no secret carry no _hmac field.
    _write_signed_chain(log, n=2, secret="")
    result = verify_chain(log, SECRET)
    assert result.ok is False
    assert result.status == "no_hmac"
    assert result.exit_code != 0
    assert "not verifiable" in result.render().lower()


def test_no_secret_not_verifiable(tmp_path):
    log = tmp_path / "audit.jsonl"
    _write_signed_chain(log, n=2)
    result = verify_chain(log, secret="")
    assert result.ok is False
    assert result.status == "no_hmac"
    assert result.exit_code != 0


def test_empty_file(tmp_path):
    log = tmp_path / "audit.jsonl"
    log.write_text("")
    result = verify_chain(log, SECRET)
    assert result.ok is False
    assert result.status == "empty"
    assert result.exit_code != 0


def test_missing_file(tmp_path):
    result = verify_chain(tmp_path / "nope.jsonl", SECRET)
    assert result.ok is False
    assert result.status == "read_error"
    assert result.exit_code != 0


# ── CLI: stdout + exit code ──────────────────────────────────────────────────


def test_cli_verify_ok_exit_0(tmp_path, capsys):
    log = tmp_path / "audit.jsonl"
    _write_signed_chain(log, n=2)
    code = _run_cli(["audit", "verify", str(log), "--secret", SECRET])
    out = capsys.readouterr().out
    assert code == 0
    assert "OK" in out and "verified" in out


def test_cli_verify_tamper_prints_bad_line_to_stdout(tmp_path, capsys):
    log = tmp_path / "audit.jsonl"
    _write_signed_chain(log, n=3)
    lines = log.read_text().splitlines()
    rec = json.loads(lines[0])
    rec["action"] = "drop"
    lines[0] = json.dumps(rec, separators=(",", ":"))
    log.write_text("\n".join(lines) + "\n")

    code = _run_cli(["audit", "verify", str(log), "--secret", SECRET])
    captured = capsys.readouterr()
    assert code != 0
    # The failure (first bad line) must be on STDOUT, not silent/stderr-only.
    assert "line 1" in captured.out
    assert "FAIL" in captured.out


def test_cli_verify_no_secret_not_verifiable(tmp_path, capsys):
    log = tmp_path / "audit.jsonl"
    _write_signed_chain(log, n=1)
    code = _run_cli(["audit", "verify", str(log)])  # no --secret, no env
    out = capsys.readouterr().out
    assert code != 0
    assert "not verifiable" in out.lower()


def test_cli_verify_uses_env_secret(tmp_path, capsys, monkeypatch):
    log = tmp_path / "audit.jsonl"
    _write_signed_chain(log, n=1)
    monkeypatch.setenv("GUARDMCP_AUDIT_HMAC_SECRET", SECRET)
    code = _run_cli(["audit", "verify", str(log)])
    assert code == 0
    assert "OK" in capsys.readouterr().out


@pytest.mark.parametrize("status", ["ok", "empty", "read_error", "no_hmac", "bad_chain"])
def test_render_never_empty(tmp_path, status):
    # Render must produce a non-empty line for every status (CLI prints it).
    from guardmcp.core.audit.verify import VerifyResult

    r = VerifyResult(ok=(status == "ok"), status=status, records=2, bad_line=1, detail="x")
    assert r.render().strip()
