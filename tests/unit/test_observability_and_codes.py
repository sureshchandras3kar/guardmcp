"""#8 + #9 tests: structured logging, trace-id correlation, explicit error codes."""

import json
from datetime import UTC

from guardmcp.core.audit.logger import AuditLogger
from guardmcp.core.observability import (
    get_trace_id,
    log_event,
    new_trace_id,
    trace_id,
)
from guardmcp.server.responses import ErrorCode, from_pipeline_result

# ── #8: structured logging ────────────────────────────────────────────────


class TestLogEvent:
    def test_emits_parseable_json_with_trace_id(self, capsys, monkeypatch):
        monkeypatch.setenv("GUARDMCP_LOG_FORMAT", "json")
        monkeypatch.setenv("GUARDMCP_LOG_LEVEL", "info")
        tok = trace_id.set("abc123")
        try:
            log_event("warning", "unit_test_event", detail="hello", count=3)
        finally:
            trace_id.reset(tok)
        line = capsys.readouterr().err.strip().splitlines()[-1]
        rec = json.loads(line)
        assert rec["event"] == "unit_test_event"
        assert rec["level"] == "warning"
        assert rec["trace_id"] == "abc123"
        assert rec["detail"] == "hello"
        assert rec["count"] == 3
        assert "ts" in rec

    def test_level_threshold_suppresses_below(self, capsys, monkeypatch):
        monkeypatch.setenv("GUARDMCP_LOG_LEVEL", "error")
        log_event("info", "should_be_suppressed")
        assert capsys.readouterr().err.strip() == ""

    def test_text_format_human_line(self, capsys, monkeypatch):
        monkeypatch.setenv("GUARDMCP_LOG_FORMAT", "text")
        monkeypatch.setenv("GUARDMCP_LOG_LEVEL", "info")
        log_event("info", "human_event", detail="x")
        out = capsys.readouterr().err
        assert "[guardmcp]" in out
        assert "human_event" in out


class TestTraceId:
    def test_new_and_get_roundtrip(self):
        tid = new_trace_id()
        assert tid
        assert get_trace_id() == tid

    def test_new_trace_id_changes(self):
        a = new_trace_id()
        b = new_trace_id()
        assert a != b
        assert get_trace_id() == b


class TestAuditTraceId:
    def test_audit_record_carries_field(self):
        from datetime import datetime

        from guardmcp.core.models.domain import AuditRecord

        rec = AuditRecord(
            timestamp=datetime.now(UTC),
            agent="a",
            collection="c",
            action="find",
            status="allowed",
        )
        assert rec.trace_id == ""

    def test_build_stamps_current_trace_id(self, tmp_path):
        logger = AuditLogger(tmp_path / "audit.jsonl")
        tid = new_trace_id()
        rec = logger.build(agent="a", collection="c", action="find", status="allowed")
        assert rec.trace_id == tid


# ── #9: explicit error codes preferred over substring inference ────────────


class TestFromPipelineResultPrefersCode:
    def test_explicit_code_used_directly(self):
        # Reason text would substring-infer COLLECTION_NOT_ALLOWED ("not permitted"),
        # but the explicit code must win.
        result = {
            "status": "denied",
            "reason": "collection 'x' is not permitted.",
            "code": ErrorCode.READONLY.value,
        }
        env = json.loads(from_pipeline_result(result))
        assert env["error"]["code"] == "READONLY"

    def test_explicit_action_code(self):
        result = {"status": "denied", "reason": "nope", "code": ErrorCode.ACTION_NOT_ALLOWED.value}
        env = json.loads(from_pipeline_result(result))
        assert env["error"]["code"] == "ACTION_NOT_ALLOWED"

    def test_substring_fallback_when_no_code(self):
        result = {"status": "denied", "reason": "action 'drop' is explicitly denied."}
        env = json.loads(from_pipeline_result(result))
        assert env["error"]["code"] == "ACTION_NOT_ALLOWED"

    def test_error_with_explicit_rate_limited_code(self):
        result = {
            "status": "error",
            "reason": "rate limit exceeded",
            "code": ErrorCode.RATE_LIMITED.value,
        }
        env = json.loads(from_pipeline_result(result))
        assert env["error"]["code"] == "RATE_LIMITED"
        assert env["error"]["retryable"] is True

    def test_error_backend_explicit_code(self):
        result = {"status": "error", "reason": "boom", "code": ErrorCode.BACKEND_ERROR.value}
        env = json.loads(from_pipeline_result(result))
        assert env["error"]["code"] == "BACKEND_ERROR"

    def test_errorcode_reexport_identity(self):
        # Backward-compat: server re-export is the same enum as core's.
        from guardmcp.core.interfaces.errors import ErrorCode as CoreErrorCode

        assert ErrorCode is CoreErrorCode
