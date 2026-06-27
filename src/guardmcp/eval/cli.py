"""
guardmcp eval — CLI entry point.

Usage:
    python -m guardmcp.eval evals/cases/
    python -m guardmcp.eval evals/cases/ --format json --output report.json
    python -m guardmcp.eval evals/cases/ --tag masking
    python -m guardmcp.eval evals/cases/ --fail-fast
"""

import asyncio
import sys
import time
from pathlib import Path

from .loader import discover
from .models import EvalCaseResult, EvalReport
from .runner import run_case


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="guardmcp eval",
        description="GuardMCP Eval — deterministic policy and security evaluation framework",
    )
    parser.add_argument("paths", nargs="+", type=Path, help="Eval files or directories")
    parser.add_argument(
        "--format",
        choices=["console", "json", "junit"],
        default="console",
        help="Output format (default: console)",
    )
    parser.add_argument("--output", type=Path, default=None, help="Write report to file")
    parser.add_argument(
        "--tag",
        action="append",
        dest="tags",
        metavar="TAG",
        help="Run only evals matching this tag (repeatable)",
    )
    parser.add_argument("--fail-fast", action="store_true", help="Stop after first failure")
    args = parser.parse_args(argv)

    # Discover
    try:
        cases = discover(args.paths)
    except Exception as exc:
        print(f"Error loading evals: {exc}", file=sys.stderr)
        return 1

    if not cases:
        print("No eval cases found.", file=sys.stderr)
        return 1

    # Tag filter
    if args.tags:
        cases = [(p, c) for p, c in cases if any(t in c.tags for t in args.tags)]
        if not cases:
            print(f"No evals match tags: {args.tags}", file=sys.stderr)
            return 1

    # Run
    results: list[EvalCaseResult] = []
    wall_start = time.monotonic()

    for _path, case in cases:
        result = asyncio.run(run_case(case))
        results.append(result)
        if args.fail_fast and not result.passed and not result.skipped:
            break

    wall_ms = (time.monotonic() - wall_start) * 1000

    report = EvalReport(
        total=len(cases),
        passed=sum(1 for r in results if r.passed and not r.skipped),
        failed=sum(1 for r in results if not r.passed),
        skipped=sum(1 for r in results if r.skipped),
        duration_ms=wall_ms,
        results=results,
    )

    # Render
    if args.format == "json":
        from .reports.json_report import render
    elif args.format == "junit":
        from .reports.junit import render
    else:
        from .reports.console import render

    output = render(report)

    if args.output:
        args.output.write_text(output)
        print(f"Report written to {args.output}")
    else:
        print(output)

    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
