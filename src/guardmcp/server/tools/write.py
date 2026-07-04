"""
Write tools: insert_one/many, update_one/many, delete_one/many, create_index,
drop_index. Each registers under both ``db_X`` and the legacy ``mongodb_X`` alias.

HIGH/CRITICAL writes go through in-band confirmation via the shared
``_run_with_confirm`` helper (see _common).
"""

from __future__ import annotations

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ...core.models.domain import Action
from ...core.validation import JsonDict, JsonList
from ...plugins.mongodb.guard import validate_filter
from ._common import (
    Context,
    DocumentParam,
    ErrorCode,
    FilterParam,
    ToolContext,
    UpdateParam,
    _capability_check,
    _resolve_database,
    _run_with_confirm,
    _validation_guard,
    err,
)
from ._registry import register_dual


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    get_pipeline = ctx.get_pipeline
    get_agent = ctx.get_agent
    _WRITE = ctx.WRITE
    _DESTRUCTIVE = ctx.DESTRUCTIVE
    _DESTRUCTIVE_IDEMPOTENT = ctx.DESTRUCTIVE_IDEMPOTENT
    tool_ctx = ctx  # ToolContext captured for _resolve_database (inner ctx is FastMCP Context)

    # ── Write operations (in-band confirmation for HIGH/CRITICAL) ─────────────

    _INSERT_ONE_DESC = (
        "Insert a single document. Blocked in readonly mode.\n"
        "Use when: adding one record.\n"
        "Do NOT use when: adding many — call db_insert_many.\n"
        "Side effects: writes data; may require approval per policy. Risk: MEDIUM.\n"
        "Example: db_insert_one(collection='users', document={'name':'Ada'})"
    )

    @_validation_guard
    async def _insert_one(
        ctx: Context, collection: str, document: DocumentParam, database: str | None = None
    ) -> str:
        pipeline = get_pipeline()
        unsupported = _capability_check(pipeline, Action.INSERT_ONE)
        if unsupported:
            return unsupported
        if not document:
            return err(ErrorCode.VALIDATION, "document must not be empty.", retryable=False)
        db = _resolve_database(tool_ctx, database)
        return await _run_with_confirm(
            ctx, pipeline, get_agent(), collection, Action.INSERT_ONE, {"document": document},
            database=db,
        )

    register_dual(mcp, "db_insert_one", "mongodb_insert_one", _INSERT_ONE_DESC, _WRITE, _insert_one)

    _INSERT_MANY_DESC = (
        "Insert multiple documents in one operation. Blocked in readonly mode.\n"
        "Use when: adding several records efficiently.\n"
        "Do NOT use when: adding one — call db_insert_one.\n"
        "Side effects: writes data; may require approval per policy. Risk: MEDIUM.\n"
        "Example: db_insert_many(collection='users', documents=[{'name':'Ada'},{'name':'Bob'}])"
    )

    @_validation_guard
    async def _insert_many(
        ctx: Context, collection: str, documents: JsonList, database: str | None = None
    ) -> str:
        pipeline = get_pipeline()
        unsupported = _capability_check(pipeline, Action.INSERT_MANY)
        if unsupported:
            return unsupported
        if not documents:
            return err(ErrorCode.VALIDATION, "documents list must not be empty.", retryable=False)
        db = _resolve_database(tool_ctx, database)
        return await _run_with_confirm(
            ctx, pipeline, get_agent(), collection, Action.INSERT_MANY, {"documents": documents},
            database=db,
        )

    register_dual(
        mcp, "db_insert_many", "mongodb_insert_many", _INSERT_MANY_DESC, _WRITE, _insert_many
    )

    _UPDATE_ONE_DESC = (
        "Update a single matching document. Blocked in readonly mode.\n"
        "Use when: changing one record. Call guardmcp_plan first to preview.\n"
        "Do NOT use when: changing all matches — call db_update_many.\n"
        "Side effects: mutates data; may require approval. Risk: HIGH.\n"
        "Example: db_update_one(collection='users', filter={'_id':1}, "
        "update={'$set':{'status':'x'}})"
    )

    @_validation_guard
    async def _update_one(
        ctx: Context,
        collection: str,
        filter: FilterParam,
        update: UpdateParam,
        database: str | None = None,
    ) -> str:
        pipeline = get_pipeline()
        unsupported = _capability_check(pipeline, Action.UPDATE_ONE)
        if unsupported:
            return unsupported
        validate_filter(filter or {})
        db = _resolve_database(tool_ctx, database)
        return await _run_with_confirm(
            ctx,
            pipeline,
            get_agent(),
            collection,
            Action.UPDATE_ONE,
            {"filter": filter or {}, "update": update or {}},
            database=db,
        )

    register_dual(
        mcp, "db_update_one", "mongodb_update_one", _UPDATE_ONE_DESC, _DESTRUCTIVE, _update_one
    )

    _UPDATE_MANY_DESC = (
        "Update ALL matching documents. Blocked in readonly mode.\n"
        "Use when: changing every match. Call guardmcp_plan first to see blast radius.\n"
        "Do NOT use when: changing one — call db_update_one.\n"
        "Side effects: mutates data in bulk; may require approval. Risk: HIGH.\n"
        "Example: db_update_many(collection='users', filter={'status':'a'}, "
        "update={'$set':{'status':'b'}})"
    )

    @_validation_guard
    async def _update_many(
        ctx: Context,
        collection: str,
        filter: FilterParam,
        update: UpdateParam,
        database: str | None = None,
    ) -> str:
        pipeline = get_pipeline()
        unsupported = _capability_check(pipeline, Action.UPDATE_MANY)
        if unsupported:
            return unsupported
        validate_filter(filter or {})
        db = _resolve_database(tool_ctx, database)
        return await _run_with_confirm(
            ctx,
            pipeline,
            get_agent(),
            collection,
            Action.UPDATE_MANY,
            {"filter": filter or {}, "update": update or {}},
            database=db,
        )

    register_dual(
        mcp, "db_update_many", "mongodb_update_many", _UPDATE_MANY_DESC, _DESTRUCTIVE, _update_many
    )

    _DELETE_ONE_DESC = (
        "Delete a single matching document. Blocked in readonly mode.\n"
        "Use when: removing one record (idempotent when filtering by _id).\n"
        "Do NOT use when: removing all matches — call db_delete_many.\n"
        "Side effects: deletes data; may require approval. Risk: HIGH.\n"
        "Example: db_delete_one(collection='users', filter={'_id':1})"
    )

    @_validation_guard
    async def _delete_one(
        ctx: Context, collection: str, filter: FilterParam, database: str | None = None
    ) -> str:
        pipeline = get_pipeline()
        unsupported = _capability_check(pipeline, Action.DELETE_ONE)
        if unsupported:
            return unsupported
        validate_filter(filter or {})
        db = _resolve_database(tool_ctx, database)
        return await _run_with_confirm(
            ctx, pipeline, get_agent(), collection, Action.DELETE_ONE, {"filter": filter or {}},
            database=db,
        )

    register_dual(
        mcp,
        "db_delete_one",
        "mongodb_delete_one",
        _DELETE_ONE_DESC,
        _DESTRUCTIVE_IDEMPOTENT,
        _delete_one,
    )

    _DELETE_MANY_DESC = (
        "Delete ALL matching documents. Blocked in readonly mode. An empty filter {} "
        "deletes the entire collection.\n"
        "Use when: bulk removal. ALWAYS call guardmcp_plan first to see would_affect.\n"
        "Do NOT use when: removing one — call db_delete_one.\n"
        "Side effects: bulk delete; may require approval. Risk: CRITICAL.\n"
        "Example: db_delete_many(collection='logs', filter={'level':'debug'})"
    )

    @_validation_guard
    async def _delete_many(
        ctx: Context, collection: str, filter: FilterParam, database: str | None = None
    ) -> str:
        pipeline = get_pipeline()
        unsupported = _capability_check(pipeline, Action.DELETE_MANY)
        if unsupported:
            return unsupported
        validate_filter(filter or {})
        db = _resolve_database(tool_ctx, database)
        return await _run_with_confirm(
            ctx, pipeline, get_agent(), collection, Action.DELETE_MANY, {"filter": filter or {}},
            database=db,
        )

    register_dual(
        mcp, "db_delete_many", "mongodb_delete_many", _DELETE_MANY_DESC, _DESTRUCTIVE, _delete_many
    )

    # ── Index management ───────────────────────────────────────────────────────

    _CREATE_INDEX_DESC = (
        "Create an index on a collection.\n"
        "Use when: improving query performance on common filters/sorts.\n"
        "Do NOT use when: the index already exists — call db_indexes first.\n"
        "Side effects: builds an index (can be expensive). Risk: MEDIUM.\n"
        "Example: db_create_index(collection='users', keys={'name':1,'age':-1})"
    )

    @_validation_guard
    async def _create_index(
        ctx: Context,
        collection: str,
        keys: Annotated[
            dict[str, int] | list | None,
            Field(
                description="Index keys, field -> 1/-1 (or legacy [[field,dir],...]).",
                examples=[{"name": 1, "age": -1}],
            ),
        ],
        options: JsonDict = None,
        database: str | None = None,
    ) -> str:
        pipeline = get_pipeline()
        unsupported = _capability_check(pipeline, Action.CREATE_INDEX)
        if unsupported:
            return unsupported
        if not keys:
            return err(ErrorCode.VALIDATION, "keys must not be empty.", retryable=False)
        # Point 7: accept dict {field: dir}; translate to [[field, dir], ...].
        if isinstance(keys, dict):
            key_pairs = [[field, int(direction)] for field, direction in keys.items()]
        else:
            key_pairs = keys
        db = _resolve_database(tool_ctx, database)
        return await _run_with_confirm(
            ctx,
            pipeline,
            get_agent(),
            collection,
            Action.CREATE_INDEX,
            {"keys": key_pairs, "options": options or {}},
            database=db,
        )

    register_dual(
        mcp, "db_create_index", "mongodb_create_index", _CREATE_INDEX_DESC, _WRITE, _create_index
    )

    _DROP_INDEX_DESC = (
        "Drop an index by name. Use db_indexes to list index names first.\n"
        "Use when: removing an unused index "
        "(idempotent — dropping a gone index is a no-op intent).\n"
        "Do NOT use when: unsure of the name — call db_indexes.\n"
        "Side effects: removes an index; recreating it is costly. Risk: HIGH.\n"
        "Example: db_drop_index(collection='users', index_name='name_1')"
    )

    @_validation_guard
    async def _drop_index(
        ctx: Context, collection: str, index_name: str, database: str | None = None
    ) -> str:
        pipeline = get_pipeline()
        unsupported = _capability_check(pipeline, Action.DROP_INDEX)
        if unsupported:
            return unsupported
        db = _resolve_database(tool_ctx, database)
        return await _run_with_confirm(
            ctx, pipeline, get_agent(), collection, Action.DROP_INDEX, {"index_name": index_name},
            database=db,
        )

    register_dual(
        mcp,
        "db_drop_index",
        "mongodb_drop_index",
        _DROP_INDEX_DESC,
        _DESTRUCTIVE_IDEMPOTENT,
        _drop_index,
    )
