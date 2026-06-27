"""
CapabilityExecutorAdapter — the integration seam between the generic plugin
contract (DatabasePlugin / Capability) and the legacy Backend interface the
pipeline consumes.

The pipeline speaks Action + params and expects MongoDB-shaped results
({"documents": [...]} for reads, ints for counts, {"matched", "modified"} for
updates, etc.). Non-MongoDB plugins (postgres, mysql) reason in terms of
Capability and return CapabilityResult. This adapter translates between the two
so the pipeline, tools, masking and eval runner work UNCHANGED for ANY backend.

MongoDB does NOT use this adapter — it continues to drive MongoExecutor directly
(byte-identical behaviour). This file lives in core/registry and imports ONLY
core.interfaces — never a concrete plugin — so the core-clean invariant holds.
"""

from __future__ import annotations

from typing import Any

from ..interfaces.capability import (
    ACTION_TO_CAPABILITY,
    Capability,
    CapabilityRequest,
    CapabilityResult,
)
from ..interfaces.cost import CostEstimate
from ..interfaces.errors import GuardError
from ..interfaces.plugin import DatabasePlugin
from ..models.domain import Action


class CapabilityExecutorAdapter:
    """Presents a DatabasePlugin behind the legacy Backend interface the
    pipeline consumes. Translates Action+params → CapabilityRequest, calls
    plugin.execute → CapabilityResult, maps back to MongoDB-style result shapes
    so the pipeline/tools/masking work unchanged for ANY backend."""

    def __init__(self, plugin: DatabasePlugin) -> None:
        self._plugin = plugin

    # ── Core execution ─────────────────────────────────────────────────────────
    async def execute(self, collection: str, action: Action, params: dict[str, Any]) -> Any:
        # COLLECTION_SCHEMA has a dedicated introspection path on the plugin that
        # yields the {"fields": {...}} shape the pipeline expects — route to it.
        if action == Action.COLLECTION_SCHEMA:
            return await self.collection_schema(
                collection, params.get("mask_fields", []), params.get("sample_size")
            )
        if action == Action.COLLECTION_INDEXES:
            return await self.collection_indexes(collection)
        if action == Action.LIST_DATABASES:
            return await self.list_databases()

        capability = ACTION_TO_CAPABILITY.get(action)
        if capability is None:
            raise ValueError(f"unsupported action: {action}")

        documents = params.get("documents")
        document = params.get("document")
        if document is not None and documents is None:
            documents = [document]

        req = CapabilityRequest(
            capability=capability,
            # Risk #1: carry the concrete operation name explicitly via the
            # first-class action field so the plugin can disambiguate (e.g.
            # update_one vs insert_one) WITHOUT any control key smuggled in options.
            action=action.value,
            resource=collection,
            filter=params.get("filter"),
            projection=params.get("projection"),
            documents=documents,
            update=params.get("update"),
            pipeline=params.get("pipeline"),
            limit=params.get("limit"),
            skip=params.get("skip"),
            # Risk #2: additive request surface, populated from params when present.
            sort=params.get("sort"),
            returning=params.get("returning"),
            tx_id=params.get("tx_id"),
        )

        try:
            result = await self._plugin.execute(req)
        except GuardError:
            # The pipeline's _execute_and_build wraps execute() in try/except
            # Exception and calls sanitize_error → {status: error}. Re-raise so
            # that path handles it; never leak raw plugin internals here.
            raise

        return self._map_result(action, capability, params, result)

    def _map_result(
        self,
        action: Action,
        capability: Capability,
        params: dict[str, Any],
        result: CapabilityResult,
    ) -> Any:
        rows = result.rows

        if capability == Capability.READ:
            limit = int(params.get("limit", 20))
            skip = int(params.get("skip", 0))
            count = len(rows)
            # Risk #3: keep the Mongo-style `documents` for backward compat AND
            # carry the neutral `rows` alias + `_neutral` marker so SQL consumers
            # are not forced into Mongo result semantics.
            return {
                "documents": rows,
                "rows": rows,
                "skip": skip,
                "limit": limit,
                "count": count,
                "next_skip": skip + count,
                "has_more": count == limit,
                "_neutral": True,
            }

        if capability == Capability.COUNT:
            return result.scalar if result.scalar is not None else 0

        if capability == Capability.AGGREGATE:
            return rows

        if capability == Capability.EXPLAIN:
            return {"plan": rows}

        if capability == Capability.STATS:
            return rows[0] if rows else {}

        if capability in (Capability.WRITE_ONE, Capability.WRITE_MANY):
            # update present → an update; otherwise an insert.
            if params.get("update") is not None:
                affected = result.affected or 0
                # Risk #3: neutral `affected` + marker alongside Mongo-style keys.
                return {
                    "matched": affected,
                    "modified": affected,
                    "affected": affected,
                    "_neutral": True,
                }
            if capability == Capability.WRITE_ONE:
                return {
                    "inserted_id": result.meta.get("lastrowid"),
                    "affected": result.affected if result.affected is not None else 1,
                    "_neutral": True,
                }
            return {
                "inserted_count": result.affected,
                "inserted_ids": [],
                "affected": result.affected or 0,
                "_neutral": True,
            }

        if capability in (Capability.DELETE_ONE, Capability.DELETE_MANY):
            affected = result.affected or 0
            return {"deleted": affected, "affected": affected, "_neutral": True}

        if capability == Capability.DDL_CREATE:
            return {"created_index": result.meta.get("name", "")}

        if capability == Capability.DDL_DESTROY:
            return {"dropped": params.get("resource", "")}

        # Fallback: hand back rows so callers see something useful.
        return rows

    # ── Discovery / introspection ───────────────────────────────────────────────
    async def list_collections(self) -> list[str]:
        return await self._plugin.list_resources()

    async def collection_schema(
        self, collection: str, mask_fields: list[str], sample_size: int | None = None
    ) -> dict[str, Any]:
        schema = await self._plugin.schema(collection, sample_size)
        fields = schema.get("fields", {}) if isinstance(schema, dict) else {}
        # Apply masking by key name so masked SQL columns are redacted too.
        if mask_fields:
            masked = set(mask_fields)
            fields = {k: ("masked" if k in masked else v) for k, v in fields.items()}
        return fields

    async def collection_indexes(self, collection: str) -> list[dict[str, Any]]:
        req = CapabilityRequest(capability=Capability.INDEXES, resource=collection)
        result = await self._plugin.execute(req)
        return result.rows

    async def list_databases(self) -> list[dict[str, Any]]:
        req = CapabilityRequest(capability=Capability.LIST_DATABASES)
        result = await self._plugin.execute(req)
        return result.rows

    async def enforce_index_for_find(self, collection: str, filter_: dict[str, Any]) -> None:
        # No-op for non-Mongo backends (SQL planners pick indexes themselves).
        return None

    async def estimate(self, req: CapabilityRequest) -> CostEstimate:
        """Delegate cost estimation to the plugin through the same Backend
        boundary, so the pipeline/plan can request an estimate for ANY backend.
        Returns the plugin's normalized CostEstimate (never the raw plan)."""
        return await self._plugin.estimate(req)

    def sanitize_error(self, exc: Exception) -> str:
        """Generic safe error message — never leaks backend internals."""
        return "Operation failed. Check parameters and try again."
