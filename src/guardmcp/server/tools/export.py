"""db_export — write an already-governed find/aggregate result to a local
file, for bulk reads too large for a normal inline response.

SAFETY INVARIANT: this tool NEVER reads raw executor output. It calls the
EXACT SAME `pipeline.run()` path as db_find/db_aggregate and only writes the
already-masked `data["documents"]` those calls return — masking cannot be
bypassed because there is no separate code path to bypass it with. The write
itself is delegated to core/export.py (data-agnostic, no backend import).
"""

from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from ...core.export import sweep_expired, write_export
from ...core.models.domain import Action
from ...core.validation import JsonList
from ...plugins.mongodb.guard import validate_filter, validate_pipeline_stages
from ._common import (
    ErrorCode,
    FilterParam,
    SafeLimit,
    ToolContext,
    _capability_check,
    _resolve_database,
    _validation_guard,
    err,
    from_pipeline_result,
    ok,
)
from ._registry import register_dual


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    get_pipeline = ctx.get_pipeline
    get_agent = ctx.get_agent
    get_settings = ctx.get_settings
    _RO = ctx.RO

    _EXPORT_DESC = (
        "Run a find or aggregation and write the (already-masked) result to a "
        "local file instead of returning it inline — for bulk reads too large "
        "for a normal response. Returns a manifest (export_id/path/"
        "document_count/size_bytes), NOT the data itself.\n"
        "Use when: you need many/large documents and don't need them inline "
        "in this response.\n"
        "Do NOT use when: a normal db_find/db_aggregate response is small "
        "enough — this adds a file-write round trip for no benefit.\n"
        "Side effects: writes a file under the server's configured export "
        "directory (operator-secured — see GUARDMCP_EXPORT_DIR). Files older "
        "than the configured TTL are swept on the NEXT export call (not "
        "eagerly). Masking is identical to db_find/db_aggregate.\n"
        "Example: db_export(collection='users', mode='find', filter={'status':'active'})"
    )

    @_validation_guard
    async def _export(
        collection: str,
        mode: Literal["find", "aggregate"] = "find",
        filter: FilterParam = None,
        pipeline_stages: JsonList = None,
        limit: SafeLimit = 500,
        database: str | None = None,
    ) -> str:
        pipeline = get_pipeline()
        action = Action.FIND if mode == "find" else Action.AGGREGATE
        unsupported = _capability_check(pipeline, action)
        if unsupported:
            return unsupported

        if mode == "find":
            if filter:
                validate_filter(filter)
            params = {"filter": filter or {}, "limit": limit}
        else:
            stages = pipeline_stages or []
            validate_pipeline_stages(stages)
            params = {"pipeline": stages}

        db = _resolve_database(ctx, database)
        result = await pipeline.run(get_agent(), collection, action, params, database=db)
        if result.get("status") != "success":
            return from_pipeline_result(result)

        data = result.get("data")
        documents = data.get("documents", []) if isinstance(data, dict) else (data or [])

        settings = get_settings()
        export_dir = getattr(settings, "export_dir", None)
        ttl = getattr(settings, "export_ttl_seconds", 300.0)
        if export_dir is None:
            return err(
                ErrorCode.BACKEND_ERROR,
                "export_dir not configured",
                retryable=False,
            )
        sweep_expired(export_dir, ttl)
        manifest = write_export(export_dir, documents)
        return ok(manifest)

    register_dual(mcp, "db_export", "mongodb_export", _EXPORT_DESC, _RO, _export)
