"""Console report renderer."""

from ..models import EvalReport


def render(report: EvalReport) -> str:
    lines: list[str] = []
    lines.append(f"\nRunning {report.total} evaluation(s)...\n")

    for r in report.results:
        if r.skipped:
            reason = f"  ({r.skip_reason})" if r.skip_reason else ""
            lines.append(f"  SKIP  {r.case_name}{reason}")
        elif r.passed:
            lines.append(f"  PASS  {r.case_name}")
        else:
            lines.append(f"  FAIL  {r.case_name}")
            for f in r.failures:
                lines.append(f"        → {f}")

    lines.append("")
    ran = report.total - report.skipped
    verdict = "passed" if report.failed == 0 else "FAILED"
    parts = [f"{report.passed}/{ran} passed"]
    if report.failed:
        parts.append(f"{report.failed} failed")
    if report.skipped:
        parts.append(f"{report.skipped} skipped")
    parts.append(f"{report.duration_ms:.0f}ms")
    parts.append(f"[{verdict}]")
    lines.append("  ".join(parts))
    return "\n".join(lines)
