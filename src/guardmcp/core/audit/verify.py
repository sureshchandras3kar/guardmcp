"""Offline verification of the tamper-evident audit HMAC chain.

This shares ONE implementation of the chain math with the writer
(:class:`~guardmcp.core.audit.logger.AuditLogger`): the per-record signature is
``HMAC-SHA256(secret, prev_hash + base_line)`` where ``base_line`` is the record
serialized with ``json.dumps(rec_without_hmac, separators=(",", ":"))`` and
``prev_hash`` starts at the genesis value. The CLI (``guardmcp audit verify``)
calls :func:`verify_chain` so there is no second copy of the hash logic.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from pathlib import Path

# Genesis seed for the chain — must match AuditLogger._GENESIS.
from .logger import _GENESIS


def sign_record(secret: bytes, prev_hash: str, base_line: str) -> str:
    """HMAC-SHA256 of ``prev_hash + base_line`` → hex digest.

    Identical math to ``AuditLogger._sign`` (kept as a free function so both the
    writer-side verification and the offline CLI use exactly one definition).
    """
    return hmac.new(secret, (prev_hash + base_line).encode(), hashlib.sha256).hexdigest()


@dataclass
class VerifyResult:
    """Outcome of verifying an audit-log file."""

    ok: bool
    # One of: "ok", "no_hmac", "empty", "bad_chain", "read_error".
    status: str
    records: int = 0
    # 1-based line number of the FIRST bad record (None when ok / not applicable).
    bad_line: int | None = None
    expected: str | None = None
    got: str | None = None
    detail: str | None = None

    @property
    def exit_code(self) -> int:
        """0 only when the whole chain verifies; distinct codes otherwise."""
        return {
            "ok": 0,
            "bad_chain": 1,
            "no_hmac": 3,
            "empty": 3,
            "read_error": 2,
        }.get(self.status, 1)

    def render(self) -> str:
        """A single human-readable summary line (success OR failure).

        Used by ``guardmcp audit verify`` so both outcomes print a clear message;
        the failure case names the FIRST bad line + reason. Exit code semantics
        live in :attr:`exit_code` and are unaffected by this text.
        """
        if self.status == "ok":
            return f"OK — audit chain verified ({self.records} records)."
        if self.status == "empty":
            return "NOT VERIFIABLE — audit log is empty."
        if self.status == "no_hmac":
            where = f" (at line {self.bad_line})" if self.bad_line is not None else ""
            return f"NOT VERIFIABLE — integrity not verifiable{where}: {self.detail}"
        if self.status == "read_error":
            return f"ERROR — {self.detail}"
        # bad_chain
        parts = [f"FAIL — chain broken at line {self.bad_line}"]
        if self.records:
            parts.append(f" (after {self.records - 1} good record(s))")
        parts.append(".")
        line = "".join(parts)
        if self.detail:
            line += f" {self.detail}"
        if self.expected is not None:
            line += f" expected={self.expected} got={self.got}"
        return line


def verify_chain(path: Path | str, secret: str) -> VerifyResult:
    """Recompute the HMAC chain from genesis and verify each record's ``_hmac``.

    Returns a :class:`VerifyResult`. ``ok`` is True only when every signed
    record matches. If records carry no ``_hmac`` (HMAC disabled when written),
    integrity is not verifiable and ``status == "no_hmac"``.
    """
    path = Path(path)
    if not path.exists():
        return VerifyResult(ok=False, status="read_error", detail=f"file not found: {path}")
    if not secret:
        return VerifyResult(
            ok=False,
            status="no_hmac",
            detail="no HMAC secret provided — pass --secret or set GUARDMCP_AUDIT_HMAC_SECRET",
        )

    secret_b = secret.encode()
    prev_hash = _GENESIS
    count = 0
    saw_hmac = False

    try:
        with open(path, encoding="utf-8") as f:
            for lineno, raw in enumerate(f, start=1):
                line = raw.strip()
                if not line:
                    continue
                count += 1
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as exc:
                    return VerifyResult(
                        ok=False,
                        status="bad_chain",
                        records=count,
                        bad_line=lineno,
                        detail=f"line is not valid JSON: {exc}",
                    )
                stored = rec.get("_hmac")
                if stored is None:
                    # A record with no signature breaks integrity verification.
                    return VerifyResult(
                        ok=False,
                        status="no_hmac",
                        records=count,
                        bad_line=lineno,
                        detail="record has no _hmac field — integrity not verifiable",
                    )
                saw_hmac = True
                base = {k: v for k, v in rec.items() if k != "_hmac"}
                base_line = json.dumps(base, separators=(",", ":"))
                expected = sign_record(secret_b, prev_hash, base_line)
                if not hmac.compare_digest(expected, str(stored)):
                    return VerifyResult(
                        ok=False,
                        status="bad_chain",
                        records=count,
                        bad_line=lineno,
                        expected=expected,
                        got=str(stored),
                        detail="HMAC mismatch — chain broken at this line",
                    )
                prev_hash = expected
    except OSError as exc:
        return VerifyResult(ok=False, status="read_error", detail=str(exc))

    if count == 0:
        return VerifyResult(ok=False, status="empty", records=0, detail="audit log is empty")
    if not saw_hmac:
        return VerifyResult(
            ok=False,
            status="no_hmac",
            records=count,
            detail="no HMAC signatures — integrity not verifiable",
        )
    return VerifyResult(ok=True, status="ok", records=count)
