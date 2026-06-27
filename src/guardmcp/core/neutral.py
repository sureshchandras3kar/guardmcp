from typing import Any

from .models.domain import Action


def neutralize(action: Action, data: Any) -> dict[str, Any]:
    """
    #6: backend-neutral success accessors.

    Map a backend-native success `data` shape to uniform neutral fields so a
    consumer can read result["rows"]/["affected"]/["scalar"] regardless of the
    backend. This is ADDITIVE: the caller keeps the native keys intact and only
    layers these aliases alongside. SQL results already carry rows/affected via
    the adapter; this makes the Mongo native path uniform too.

    Returns a dict with keys present only when meaningful for the action:
      rows:     list of result documents (find/aggregate), [] for count/writes
      affected: write/delete count, or None for reads
      scalar:   count() integer, or None
    """
    rows: list[Any] | None = None
    affected: int | None = None
    scalar: int | None = None

    if action == Action.FIND:
        if isinstance(data, dict):
            rows = data.get("documents", data.get("rows", []))
            scalar = data.get("count")
        else:
            rows = data if isinstance(data, list) else []
    elif action == Action.AGGREGATE:
        rows = (
            data
            if isinstance(data, list)
            else (data.get("rows", []) if isinstance(data, dict) else [])
        )
    elif action == Action.COUNT:
        rows = []
        scalar = (
            data
            if isinstance(data, int)
            else (data.get("scalar") if isinstance(data, dict) else None)
        )
    elif action == Action.INSERT_ONE:
        affected = data.get("affected", 1) if isinstance(data, dict) else 1
    elif action == Action.INSERT_MANY:
        if isinstance(data, dict):
            affected = data.get("affected", data.get("inserted_count"))
    elif action in (Action.UPDATE_ONE, Action.UPDATE_MANY):
        if isinstance(data, dict):
            affected = data.get("affected", data.get("modified"))
    elif action in (Action.DELETE_ONE, Action.DELETE_MANY) and isinstance(data, dict):
        affected = data.get("affected", data.get("deleted"))

    out: dict[str, Any] = {}
    if rows is not None:
        out["rows"] = rows
    out["affected"] = affected
    out["scalar"] = scalar
    return out
