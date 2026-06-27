"""P-1/R-2: AuditLogger reuses one persistent append handle; aclose resets it."""

from guardmcp.core.audit.logger import AuditLogger


def _record(logger, action="find"):
    return logger.build(agent="a", collection="c", action=action, status="allowed")


async def test_handle_reused_across_log_calls(tmp_path):
    logger = AuditLogger(tmp_path / "audit.jsonl")
    await logger.log(_record(logger))
    fh1 = logger._fh
    assert fh1 is not None
    await logger.log(_record(logger))
    fh2 = logger._fh
    assert fh2 is fh1
    await logger.aclose()


async def test_aclose_resets_handle_to_none(tmp_path):
    logger = AuditLogger(tmp_path / "audit.jsonl")
    await logger.log(_record(logger))
    assert logger._fh is not None
    await logger.aclose()
    assert logger._fh is None


async def test_log_after_aclose_reopens_and_appends(tmp_path):
    path = tmp_path / "audit.jsonl"
    logger = AuditLogger(path)
    await logger.log(_record(logger))
    await logger.log(_record(logger))
    await logger.aclose()

    lines_before = path.read_text().count("\n")
    assert lines_before == 2

    # Reopen via a fresh log() call after aclose.
    await logger.log(_record(logger))
    assert logger._fh is not None  # new handle
    await logger.aclose()

    lines_after = path.read_text().count("\n")
    assert lines_after == lines_before + 1
