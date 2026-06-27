"""#9: W3C traceparent parsing, continuation, and round-trip."""

from guardmcp.core.observability.log import (
    current_traceparent,
    new_trace_id,
    parse_traceparent,
)

_VALID = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


def test_parse_valid_traceparent():
    tid = parse_traceparent(_VALID)
    assert tid == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert len(tid) == 32


def test_parse_invalid_returns_none():
    assert parse_traceparent(None) is None
    assert parse_traceparent("") is None
    assert parse_traceparent("garbage") is None
    # wrong version
    assert parse_traceparent("01-" + "a" * 32 + "-" + "b" * 16 + "-01") is None
    # too few parts
    assert parse_traceparent("00-" + "a" * 32 + "-01") is None
    # all-zero trace id is invalid per spec
    assert parse_traceparent("00-" + "0" * 32 + "-" + "b" * 16 + "-01") is None
    # non-hex
    assert parse_traceparent("00-" + "z" * 32 + "-" + "b" * 16 + "-01") is None


def test_new_trace_id_continues_incoming():
    tid = new_trace_id(_VALID)
    assert tid == "4bf92f3577b34da6a3ce929d0e0e4736"


def test_new_trace_id_mints_fresh_when_no_incoming():
    tid = new_trace_id()
    assert len(tid) == 32
    int(tid, 16)  # valid hex


def test_new_trace_id_mints_fresh_on_bad_incoming():
    tid = new_trace_id("not-a-traceparent")
    assert len(tid) == 32
    assert tid != "not-a-traceparent"


def test_current_traceparent_round_trips():
    tid = new_trace_id()
    tp = current_traceparent()
    parts = tp.split("-")
    assert parts[0] == "00"
    assert parts[1] == tid
    assert len(parts[2]) == 16  # fresh span
    # round-trip: parsing the emitted header recovers the trace-id
    assert parse_traceparent(tp) == tid
