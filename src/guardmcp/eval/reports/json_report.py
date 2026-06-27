"""JSON report renderer."""

import json

from ..models import EvalReport


def render(report: EvalReport) -> str:
    return json.dumps(report.model_dump(mode="json"), indent=2)
