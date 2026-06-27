"""Single-sourced BSON→JSON conversion shared by the executor and schema cache."""

from typing import Any

from bson import ObjectId


def _bson_to_json(obj: Any) -> Any:
    """Recursively convert BSON types to JSON-serializable equivalents."""
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, list):
        return [_bson_to_json(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _bson_to_json(v) for k, v in obj.items()}
    return obj
