"""Discover and load YAML eval case files."""

from pathlib import Path

import yaml

from .models import EvalCase


def discover(paths: list[Path]) -> list[tuple[Path, EvalCase]]:
    """Recursively find .yaml eval files and parse them into EvalCase objects."""
    cases: list[tuple[Path, EvalCase]] = []
    for path in paths:
        if path.is_dir():
            for f in sorted(path.rglob("*.yaml")):
                cases.extend(_load_file(f))
        elif path.suffix in (".yaml", ".yml") and path.exists():
            cases.extend(_load_file(path))
    return cases


def _load_file(path: Path) -> list[tuple[Path, EvalCase]]:
    with open(path) as f:
        data = yaml.safe_load(f)

    items = data if isinstance(data, list) else [data]
    cases: list[tuple[Path, EvalCase]] = []
    for item in items:
        try:
            cases.append((path, EvalCase.model_validate(item)))
        except Exception as exc:
            raise ValueError(f"Invalid eval case in {path}: {exc}") from exc
    return cases
