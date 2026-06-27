"""JUnit XML report renderer — compatible with GitHub Actions and CI systems."""

from xml.etree import ElementTree as ET

from ..models import EvalReport


def render(report: EvalReport) -> str:
    suite = ET.Element(
        "testsuite",
        attrib={
            "name": "GuardMCP Eval",
            "tests": str(report.total),
            "failures": str(report.failed),
            "skipped": str(report.skipped),
            "time": f"{report.duration_ms / 1000:.3f}",
        },
    )

    for r in report.results:
        tc = ET.SubElement(
            suite,
            "testcase",
            attrib={
                "name": r.case_name,
                "classname": "guardmcp.eval",
                "time": f"{r.duration_ms / 1000:.3f}",
            },
        )
        if r.skipped:
            ET.SubElement(tc, "skipped", attrib={"message": r.skip_reason or "skipped"})
        elif not r.passed:
            failure = ET.SubElement(
                tc,
                "failure",
                attrib={
                    "message": f"{len(r.failures)} assertion(s) failed",
                    "type": "AssertionError",
                },
            )
            failure.text = "\n".join(r.failures)

    ET.indent(suite)
    return ET.tostring(suite, encoding="unicode", xml_declaration=True)
