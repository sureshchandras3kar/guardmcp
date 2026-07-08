"""
Read / introspection tools: find, count, aggregate, explain, schema, indexes,
list_collections, list_databases, stats, list_connections, switch_connection.

Each is registered under both ``db_X`` and the legacy ``mongodb_X`` alias.
"""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ...core.models.domain import Action
from ...core.validation import JsonList
from ...plugins.mongodb.guard import (
    validate_db_pipeline_stages,
    validate_filter,
    validate_pipeline_stages,
)
from ._common import (
    ErrorCode,
    FilterParam,
    ProjectionParam,
    SafeLimit,
    SafeSkip,
    SortParam,
    ToolContext,
    _annot,
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
    _RO = ctx.RO
    set_active_database = ctx.set_active_database

    # ── Discovery / introspection ───────────────────────────────────────────────

    _LIST_COLLECTIONS_DESC = (
        "List collections in the active database you are permitted to access.\n"
        "Use when: before any query, to confirm a collection name exists.\n"
        "Do NOT use when: you already know the collection is accessible.\n"
        "Side effects: none (read-only).\n"
        "Example: db_list_collections()"
    )

    @_validation_guard
    async def _list_collections(database: str | None = None) -> str:
        db = _resolve_database(ctx, database)
        cols = await get_pipeline().discover_collections(get_agent(), database=db)
        return ok({"collections": cols})

    register_dual(
        mcp,
        "db_list_collections",
        "mongodb_list_collections",
        _LIST_COLLECTIONS_DESC,
        _RO,
        _list_collections,
    )

    _SCHEMA_DESC = (
        "Infer field names and canonical BSON types for a collection from a "
        "document sample. Types use canonical tokens: objectId, date, decimal, "
        "int, long, double, string, bool, array, object. Sensitive fields return "
        "as '***masked***'.\n"
        "Use when: before building filters/projections, to learn queryable field "
        "types so date/ObjectId/decimal filters coerce correctly. For a date "
        "field pass an ISO string or {'$date':'<iso>'}; for objectId a 24-hex "
        "string or {'$oid':'<24hex>'}; for decimal {'$decimal':'<num>'}.\n"
        "Do NOT use when: you already know the schema.\n"
        "Side effects: none (read-only).\n"
        "Example: db_schema(collection='users')"
    )

    @_validation_guard
    async def _schema(
        collection: str,
        sample_size: Annotated[int, Field(ge=1, le=100, description="Docs to sample.")] = 20,
        database: str | None = None,
    ) -> str:
        db = _resolve_database(ctx, database)
        pipeline = get_pipeline()
        agent = get_agent()
        unsupported = _capability_check(pipeline, Action.COLLECTION_SCHEMA)
        if unsupported:
            return unsupported
        schema = await pipeline.describe_collection(agent, collection, database=db)
        if schema is None:
            return err(
                ErrorCode.COLLECTION_NOT_ALLOWED,
                f"collection '{collection}' is not accessible.",
                retryable=False,
                suggested_action="call guardmcp_capabilities",
            )
        return ok({**schema, "sample_size": sample_size})

    register_dual(mcp, "db_schema", "mongodb_collection_schema", _SCHEMA_DESC, _RO, _schema)

    _INDEXES_DESC = (
        "List all indexes on a collection, including vector search indexes.\n"
        "Use when: understanding query performance before db_explain.\n"
        "Do NOT use when: you don't need index info.\n"
        "Side effects: none (read-only).\n"
        "Example: db_indexes(collection='users')"
    )

    @_validation_guard
    async def _indexes(collection: str, database: str | None = None) -> str:
        db = _resolve_database(ctx, database)
        pipeline = get_pipeline()
        unsupported = _capability_check(pipeline, Action.COLLECTION_INDEXES)
        if unsupported:
            return unsupported
        result = await pipeline.run(
            get_agent(), collection, Action.COLLECTION_INDEXES, {}, database=db
        )
        return from_pipeline_result(result)

    register_dual(mcp, "db_indexes", "mongodb_collection_indexes", _INDEXES_DESC, _RO, _indexes)

    _STORAGE_SIZE_DESC = (
        "Return a collection's storage statistics: document count, data size, "
        "storage size, average object size, and total index size.\n"
        "Use when: assessing whether a specific collection is large/needs cleanup.\n"
        "Do NOT use when: you need whole-database stats — call db_stats.\n"
        "Side effects: none (read-only).\n"
        "Example: db_collection_storage_size(collection='users')"
    )

    @_validation_guard
    async def _collection_storage_size(collection: str, database: str | None = None) -> str:
        db = _resolve_database(ctx, database)
        pipeline = get_pipeline()
        unsupported = _capability_check(pipeline, Action.COLLECTION_STORAGE_SIZE)
        if unsupported:
            return unsupported
        result = await pipeline.run(
            get_agent(), collection, Action.COLLECTION_STORAGE_SIZE, {}, database=db
        )
        return from_pipeline_result(result)

    register_dual(
        mcp,
        "db_collection_storage_size",
        "mongodb_collection_storage_size",
        _STORAGE_SIZE_DESC,
        _RO,
        _collection_storage_size,
    )

    _LIST_DB_DESC = (
        "List all databases on the active server.\n"
        "Use when: discovering available databases.\n"
        "Do NOT use when: you only need collections — call db_list_collections.\n"
        "Side effects: none (read-only).\n"
        "Example: db_list_databases()"
    )

    @_validation_guard
    async def _list_databases() -> str:
        pipeline = get_pipeline()
        unsupported = _capability_check(pipeline, Action.LIST_DATABASES)
        if unsupported:
            return unsupported
        result = await pipeline.run(get_agent(), "", Action.LIST_DATABASES, {})
        # Phase 3: filter by databases_allow when non-empty.
        if (
            result.get("status") == "success"
            and isinstance(result.get("data"), dict)
            and isinstance(result["data"].get("databases"), list)
        ):
            policy = pipeline._policies.get(get_agent())
            allow = policy.databases_allow if policy is not None else []
            if allow:
                allowed_set = set(allow)
                result["data"]["databases"] = [
                    db for db in result["data"]["databases"]
                    if db.get("name") in allowed_set
                ]
        return from_pipeline_result(result)

    register_dual(
        mcp, "db_list_databases", "mongodb_list_databases", _LIST_DB_DESC, _RO, _list_databases
    )

    _STATS_DESC = (
        "Return statistics for the active database: document counts, storage and index sizes.\n"
        "Use when: assessing database size or collection counts.\n"
        "Do NOT use when: you need per-collection schema — call db_schema.\n"
        "Side effects: none (read-only).\n"
        "Example: db_stats()"
    )

    @_validation_guard
    async def _db_stats() -> str:
        pipeline = get_pipeline()
        unsupported = _capability_check(pipeline, Action.DB_STATS)
        if unsupported:
            return unsupported
        result = await pipeline.run(get_agent(), "", Action.DB_STATS, {})
        return from_pipeline_result(result)

    register_dual(mcp, "db_stats", "mongodb_db_stats", _STATS_DESC, _RO, _db_stats)

    _EXPLAIN_DESC = (
        "Return the query execution plan for a find or aggregate operation (index usage, "
        "winning/rejected plans). Masked fields are redacted in the plan.\n"
        "Use when: debugging a slow query.\n"
        "Do NOT use when: you want results — call db_find/db_aggregate.\n"
        "Side effects: none (read-only).\n"
        "Example: db_explain(collection='users', mode='find', filter={'status':'active'})"
    )

    @_validation_guard
    async def _explain(
        collection: str,
        mode: Literal["find", "aggregate"] = "find",
        filter: FilterParam = None,
        pipeline_stages: JsonList = None,
        projection: ProjectionParam = None,
        database: str | None = None,
    ) -> str:
        db = _resolve_database(ctx, database)
        pipeline = get_pipeline()
        unsupported = _capability_check(pipeline, Action.EXPLAIN)
        if unsupported:
            return unsupported
        if filter:
            validate_filter(filter)
        params: dict = {"mode": mode}
        if mode == "aggregate":
            stages = pipeline_stages or []
            validate_pipeline_stages(stages)
            params["pipeline"] = stages
        else:
            params["filter"] = filter or {}
            if projection:
                params["projection"] = projection
        result = await pipeline.run(get_agent(), collection, Action.EXPLAIN, params, database=db)
        return from_pipeline_result(result)

    register_dual(mcp, "db_explain", "mongodb_explain", _EXPLAIN_DESC, _RO, _explain)

    _SWITCH_DESC = (
        "Switch the active database connection.\n"
        "Use when: you need to read/write a different named connection.\n"
        "Do NOT use when: only one connection is configured.\n"
        "Side effects: changes which database subsequent calls target.\n"
        "Example: db_switch_connection(connection_name='analytics')"
    )

    _USE_DB_DESC = (
        "Set the active database for subsequent calls that omit a `database` arg.\n"
        "Use when: running several operations against one database.\n"
        "Do NOT use when: a single call — pass `database=` on that call instead.\n"
        "Side effects: changes which database later calls target on THIS connection "
        "(per-connection: switching to another connection and back restores it).\n"
        "Example: db_use_database(database='corestack_identity')"
    )

    @_validation_guard
    async def _use_database(database: str) -> str:
        ok_ = await get_pipeline().use_database_audited(get_agent(), database)
        if not ok_:
            return err(ErrorCode.DATABASE_NOT_ALLOWED,
                       f"database '{database}' is not permitted by policy.", retryable=False)
        set_active_database(database)
        return ok({"active_database": database})

    register_dual(mcp, "db_use_database", "mongodb_use_database",
                  _USE_DB_DESC, _annot(readOnlyHint=False, destructiveHint=False), _use_database)

    @_validation_guard
    async def _switch_connection(connection_name: str) -> str:
        pipeline = get_pipeline()
        success = await pipeline.switch_connection_audited(get_agent(), connection_name)
        if not success:
            available = pipeline.list_connections()
            return err(
                ErrorCode.NOT_FOUND,
                f"connection '{connection_name}' not found or not permitted. "
                f"Available: {available}",
                retryable=False,
            )
        return ok({"active_connection": connection_name})

    register_dual(
        mcp,
        "db_switch_connection",
        "mongodb_switch_connection",
        _SWITCH_DESC,
        _annot(readOnlyHint=False, destructiveHint=False),
        _switch_connection,
    )

    _LIST_CONN_DESC = (
        "List all named database connections available on this server.\n"
        "Use when: choosing a connection to switch to.\n"
        "Do NOT use when: you only need collections.\n"
        "Side effects: none (read-only).\n"
        "Example: db_list_connections()"
    )

    @_validation_guard
    async def _list_connections() -> str:
        pipeline = get_pipeline()
        return ok(
            {
                "connections": pipeline.list_connections(),
                "active": pipeline.active_connection(),
            }
        )

    register_dual(
        mcp,
        "db_list_connections",
        "mongodb_list_connections",
        _LIST_CONN_DESC,
        _RO,
        _list_connections,
    )

    # ── Read operations ────────────────────────────────────────────────────────

    _FIND_DESC = (
        "Find documents in a collection. Sensitive fields return as '***masked***'.\n"
        "Use when: reading documents; use skip+limit for pagination (page 1 skip=0).\n"
        "Do NOT use when: counting — call db_count; aggregating — call db_aggregate.\n"
        "Side effects: none (read-only). filter must be plain JSON (no $where/$function).\n"
        "Typed values: filter values are auto-coerced to each field's BSON type "
        "(date/ObjectId/decimal) per the collection schema — e.g. a date field "
        "accepts an ISO string {'created_at':{'$gte':'2026-06-01'}}. To force a "
        "type regardless of schema, use an extended-JSON literal: {'$date':'<iso>'}, "
        "{'$oid':'<24hex>'}, {'$decimal':'<num>'}, {'$int':n}, {'$long':n}. A value "
        "that cannot match a field's known type fails with TYPE_MISMATCH (not an "
        "empty result) — call db_schema to see field types.\n"
        "Example: db_find(collection='users', filter={'status':'active'}, limit=20)"
    )

    @_validation_guard
    async def _find(
        collection: str,
        filter: FilterParam = None,
        limit: SafeLimit = 20,
        skip: SafeSkip = 0,
        projection: ProjectionParam = None,
        sort: SortParam = None,
        database: str | None = None,
    ) -> str:
        db = _resolve_database(ctx, database)
        pipeline = get_pipeline()
        unsupported = _capability_check(pipeline, Action.FIND)
        if unsupported:
            return unsupported
        if filter:
            validate_filter(filter)
        result = await pipeline.run(
            agent=get_agent(),
            collection=collection,
            action=Action.FIND,
            params={
                "filter": filter or {},
                "limit": limit,
                "skip": skip,
                **({"projection": projection} if projection else {}),
                **({"sort": sort} if sort else {}),
            },
            database=db,
        )
        return from_pipeline_result(result)

    register_dual(mcp, "db_find", "mongodb_find", _FIND_DESC, _RO, _find)

    _COUNT_DESC = (
        "Count documents matching a filter.\n"
        "Use when: you need a total, not the documents.\n"
        "Do NOT use when: you want the documents — call db_find.\n"
        "Side effects: none (read-only). filter must be plain JSON (no $where/$function).\n"
        "Typed values: filter values are auto-coerced to each field's BSON type "
        "per the collection schema; force a type with {'$date':...}/{'$oid':...}/"
        "{'$decimal':...}/{'$int':n}. An un-coercible value on a known-typed field "
        "fails with TYPE_MISMATCH (not a zero count). Call db_schema for field types.\n"
        "Example: db_count(collection='users', filter={'status':'active'})"
    )

    @_validation_guard
    async def _count(
        collection: str, filter: FilterParam = None, database: str | None = None
    ) -> str:
        db = _resolve_database(ctx, database)
        pipeline = get_pipeline()
        unsupported = _capability_check(pipeline, Action.COUNT)
        if unsupported:
            return unsupported
        if filter:
            validate_filter(filter)
        result = await pipeline.run(
            agent=get_agent(),
            collection=collection,
            action=Action.COUNT,
            params={"filter": filter or {}},
            database=db,
        )
        return from_pipeline_result(result)

    register_dual(mcp, "db_count", "mongodb_count", _COUNT_DESC, _RO, _count)

    _AGG_DESC = (
        "Run an aggregation pipeline. Sensitive fields return as '***masked***'.\n"
        "Use when: grouping/joining/transforming beyond a simple find.\n"
        "Do NOT use when: a plain find/count suffices.\n"
        "Side effects: none (read-only). $out/$merge/$function/$accumulator are blocked; "
        "each stage is a single-key object.\n"
        "Example: db_aggregate(collection='orders', pipeline_stages=[{'$match':{'status':'paid'}}])"
    )

    @_validation_guard
    async def _aggregate(
        collection: str, pipeline_stages: JsonList, database: str | None = None
    ) -> str:
        db = _resolve_database(ctx, database)
        guard_pipeline = get_pipeline()
        unsupported = _capability_check(guard_pipeline, Action.AGGREGATE)
        if unsupported:
            return unsupported
        stages = pipeline_stages or []
        validate_pipeline_stages(stages)
        result = await guard_pipeline.run(
            agent=get_agent(),
            collection=collection,
            action=Action.AGGREGATE,
            params={"pipeline": stages},
            database=db,
        )
        return from_pipeline_result(result)

    register_dual(mcp, "db_aggregate", "mongodb_aggregate", _AGG_DESC, _RO, _aggregate)

    _AGG_DB_DESC = (
        "Run a DATABASE-LEVEL aggregation — NOT collection data. The first "
        "stage must be one of $currentOp/$changeStream/$documents/"
        "$listLocalSessions/$queryStats.\n"
        "Use when: inspecting currently-running operations ($currentOp) or "
        "server-side query stats — server introspection, not your data.\n"
        "Do NOT use when: querying collection data — call db_aggregate/db_find.\n"
        "Side effects: none (read-only). $currentOp shows operations from ALL "
        "connections/agents, not just this one — treat results as sensitive. "
        "$changeStream is bounded to a short best-effort collection window "
        "(not a persistent watch — this is a single request/response call). "
        "Risk: HIGH.\n"
        "Example: db_aggregate_db(pipeline_stages=[{'$currentOp': {}}])"
    )

    @_validation_guard
    async def _aggregate_db(pipeline_stages: JsonList, database: str | None = None) -> str:
        db = _resolve_database(ctx, database)
        guard_pipeline = get_pipeline()
        unsupported = _capability_check(guard_pipeline, Action.AGGREGATE_DB)
        if unsupported:
            return unsupported
        stages = pipeline_stages or []
        validate_db_pipeline_stages(stages)
        result = await guard_pipeline.run(
            agent=get_agent(),
            collection="",
            action=Action.AGGREGATE_DB,
            params={"pipeline": stages},
            database=db,
        )
        return from_pipeline_result(result)

    register_dual(mcp, "db_aggregate_db", "mongodb_aggregate_db", _AGG_DB_DESC, _RO, _aggregate_db)

    _LOGS_DESC = (
        "Return the most recent mongod log lines (admin `getLog` command).\n"
        "Use when: debugging server-side errors/warnings alongside a slow or "
        "failing operation.\n"
        "Do NOT use when: you need query-level detail — call db_explain.\n"
        "Side effects: none (read-only). Log lines are raw server text, not "
        "masked (they are not documents — see docs). Risk: LOW.\n"
        "Example: db_mongodb_logs()"
    )

    @_validation_guard
    async def _mongodb_logs(
        log_type: Annotated[
            Literal["global", "startupWarnings"], Field(description="Which log buffer to read.")
        ] = "global",
    ) -> str:
        pipeline = get_pipeline()
        unsupported = _capability_check(pipeline, Action.MONGODB_LOGS)
        if unsupported:
            return unsupported
        result = await pipeline.run(
            get_agent(), "", Action.MONGODB_LOGS, {"log_type": log_type}
        )
        return from_pipeline_result(result)

    register_dual(mcp, "db_logs", "mongodb_logs", _LOGS_DESC, _RO, _mongodb_logs)
