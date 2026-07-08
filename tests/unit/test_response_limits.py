from guardmcp.core.response_limits import cap_by_bytes, cap_lines


def test_cap_by_bytes_keeps_all_when_under_budget():
    items = [{"a": 1}, {"a": 2}]
    kept, truncated = cap_by_bytes(items, max_bytes=1_000_000)
    assert kept == items and truncated is False


def test_cap_by_bytes_stops_before_exceeding_budget():
    # Each item ~ "aaaa...a" of 100 chars -> json size ~103 bytes with quotes.
    items = [{"v": "a" * 100} for _ in range(10)]
    kept, truncated = cap_by_bytes(items, max_bytes=250)
    assert len(kept) < 10
    assert truncated is True
    assert kept == items[: len(kept)]  # order preserved, prefix kept


def test_cap_by_bytes_empty_list():
    assert cap_by_bytes([], max_bytes=100) == ([], False)


def test_cap_by_bytes_single_item_over_budget_is_dropped_and_truncated():
    items = [{"v": "x" * 1000}]
    kept, truncated = cap_by_bytes(items, max_bytes=10)
    assert kept == []
    assert truncated is True


def test_cap_lines_shortens_long_lines():
    lines = ["short", "x" * 5000]
    kept, truncated = cap_lines(lines, max_line_chars=100)
    assert kept[0] == "short"
    assert len(kept[1]) == 100 + len("...[truncated]")
    assert kept[1].endswith("...[truncated]")
    assert truncated is True


def test_cap_lines_no_truncation_when_short_and_few():
    lines = ["a", "b", "c"]
    kept, truncated = cap_lines(lines)
    assert kept == lines and truncated is False


def test_cap_lines_overall_byte_budget_applies_after_shortening():
    lines = ["x" * 50 for _ in range(20)]
    kept, truncated = cap_lines(lines, max_bytes=200, max_line_chars=1000)
    assert len(kept) < 20
    assert truncated is True
