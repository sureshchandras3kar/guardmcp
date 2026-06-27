"""Tests for the tamper-evident audit log (HMAC chain, restart seeding, fail-closed)."""

import hashlib
import hmac
import json

import pytest

from guardmcp.core.audit.logger import AuditLogger, AuditWriteError

_GENESIS = "0" * 64
_SECRET = "super-secret-key"


def _read_records(path):
    records = []
    with open(path) as f:
        for raw in f:
            raw = raw.strip()
            if raw:
                records.append(json.loads(raw))
    return records


def _expected_hmac(secret: str, prev: str, rec: dict) -> str:
    base = json.dumps(rec, separators=(",", ":"))
    return hmac.new(secret.encode(), (prev + base).encode(), hashlib.sha256).hexdigest()


async def test_hmac_present_when_secret_set(tmp_path):
    logger = AuditLogger(tmp_path / "audit.jsonl", hmac_secret=_SECRET)
    rec = logger.build(agent="a", collection="c", action="find", status="allowed")
    await logger.log(rec)
    records = _read_records(tmp_path / "audit.jsonl")
    assert len(records) == 1
    assert "_hmac" in records[0]


async def test_hmac_absent_when_no_secret(tmp_path):
    logger = AuditLogger(tmp_path / "audit.jsonl")
    rec = logger.build(agent="a", collection="c", action="find", status="allowed")
    await logger.log(rec)
    records = _read_records(tmp_path / "audit.jsonl")
    assert len(records) == 1
    assert "_hmac" not in records[0]


async def test_chain_verifies(tmp_path):
    path = tmp_path / "audit.jsonl"
    logger = AuditLogger(path, hmac_secret=_SECRET)
    for i in range(3):
        rec = logger.build(agent=f"a{i}", collection="c", action="find", status="allowed")
        await logger.log(rec)

    records = _read_records(path)
    assert len(records) == 3
    prev = _GENESIS
    for rec in records:
        sig = rec.pop("_hmac")
        assert sig == _expected_hmac(_SECRET, prev, rec)
        prev = sig


async def test_chain_seeds_across_restart(tmp_path):
    path = tmp_path / "audit.jsonl"
    logger1 = AuditLogger(path, hmac_secret=_SECRET)
    for i in range(2):
        rec = logger1.build(agent=f"a{i}", collection="c", action="find", status="allowed")
        await logger1.log(rec)

    # New logger over the same file+secret seeds its chain from the last record.
    logger2 = AuditLogger(path, hmac_secret=_SECRET)
    assert logger2._prev_hash == logger1._prev_hash
    assert logger2._prev_hash != _GENESIS

    rec = logger2.build(agent="a2", collection="c", action="find", status="allowed")
    await logger2.log(rec)

    # Full-file chain still verifies from genesis after the restart.
    records = _read_records(path)
    assert len(records) == 3
    prev = _GENESIS
    for rec in records:
        sig = rec.pop("_hmac")
        assert sig == _expected_hmac(_SECRET, prev, rec)
        prev = sig


async def test_fail_closed_raises_on_write_failure(tmp_path):
    # Point the logger at a path that is itself a directory so append fails.
    bad = tmp_path / "as_dir"
    bad.mkdir()
    logger = AuditLogger(bad, hmac_secret=_SECRET, fail_closed=True)
    rec = logger.build(agent="a", collection="c", action="find", status="allowed")
    with pytest.raises(AuditWriteError):
        await logger.log(rec)


async def test_fail_open_does_not_raise(tmp_path):
    bad = tmp_path / "as_dir"
    bad.mkdir()
    logger = AuditLogger(bad, hmac_secret=_SECRET, fail_closed=False)
    rec = logger.build(agent="a", collection="c", action="find", status="allowed")
    # Must swallow the failure rather than raise.
    await logger.log(rec)
