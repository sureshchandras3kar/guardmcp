from typing import Any

from ...core.models.domain import Action
from ...core.observability import log_event
from ._serialize import _bson_to_json
from .client import MongoClient
from .marshal import marshal_filter
from .schema_cache import MongoSchemaCache


class MongoExecutor:
    def __init__(
        self,
        client: MongoClient,
        max_limit: int = 500,
        max_time_ms: int = 30_000,
        enforce_index_usage: bool = False,
        schema_sample_size: int = 20,
        max_retries: int = 3,
        retry_base_delay: float = 0.1,
        schema_cache_ttl: int = 300,
    ) -> None:
        self._client = client
        self._max_limit = max_limit
        self._max_time_ms = max_time_ms
        self._enforce_index = enforce_index_usage
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        # Schema sampling + the bounded TTL/LRU type-map/display-schema cache are
        # owned by a MongoSchemaCache collaborator; the executor delegates
        # collection_schema / type_map_for to it (and the marshaller reads
        # type_map_for through that delegation).
        self._schema = MongoSchemaCache(
            client,
            schema_sample_size=schema_sample_size,
            schema_cache_ttl=schema_cache_ttl,
        )

    def _mtms(self) -> dict:
        """Return max_time_ms kwarg when configured."""
        return {"max_time_ms": self._max_time_ms} if self._max_time_ms > 0 else {}

    # ── Aggregation-guard knowledge (MongoDB pipeline structure) ────────────────
    # These expose MongoDB-specific pipeline introspection ($lookup/$graphLookup/
    # $unionWith foreign collections, "$field" masked-path references) as a plugin
    # capability so core/pipeline.py guards through the executor boundary instead
    # of importing Mongo pipeline knowledge directly.

    def referenced_collections(self, params: dict) -> set[str]:
        from .guard import extract_pipeline_collections

        return extract_pipeline_collections(params.get("pipeline") or [])

    def masked_field_references(self, params: dict, mask_fields: list[str]) -> set[str]:
        from .guard import find_masked_field_references

        return find_masked_field_references(params.get("pipeline") or [], mask_fields)

    def sanitize_error(self, exc: Exception) -> str:
        """Backend-specific error sanitization (delegated to by core pipeline)."""
        from .guard import sanitize_mongo_error

        return sanitize_mongo_error(exc)

    # ── Discovery helpers ──────────────────────────────────────────────────────

    async def list_collections(self, database: str | None = None) -> list[str]:
        return await self._client.list_collection_names(database)

    async def list_databases(self) -> list[dict]:
        result = await self._client.list_databases()
        return _bson_to_json(result)

    async def db_stats(self, database: str | None = None) -> dict:
        stats = await self._client.get_db(database).command("dbStats")
        return _bson_to_json(stats)

    async def type_map_for(
        self, collection: str, database: str | None = None
    ) -> dict[str, str]:
        """Canonical BSON type map for the filter marshaller (cached).

        Delegates to the schema-cache collaborator; kept on the executor so the
        marshaller wiring (``_marshal``) and any external callers are unchanged.
        """
        return await self._schema.type_map_for(collection, database)

    async def collection_schema(
        self,
        collection: str,
        mask_fields: list[str],
        sample_size: int | None = None,
        database: str | None = None,
    ) -> dict:
        return await self._schema.collection_schema(
            collection, mask_fields, sample_size, database=database
        )

    async def sample_field_values(
        self, collection: str, field: str, database: str | None = None, cap: int = 100
    ) -> list:
        col = self._client.get_collection(collection, database)
        cursor = col.find({field: {"$ne": None}}, {field: 1, "_id": 0}).limit(cap)
        docs = await cursor.to_list(cap)
        seen: list = []
        seen_set: set = set()
        for d in docs:
            if field in d:
                v = _bson_to_json(d[field])
                key = str(v)
                if key not in seen_set:
                    seen_set.add(key)
                    seen.append(v)
        return seen

    async def collection_indexes(
        self, collection: str, database: str | None = None
    ) -> list[dict]:
        col = self._client.get_collection(collection, database)
        info = await col.index_information()
        result = []
        for name, idx in info.items():
            result.append(
                {
                    "name": name,
                    "key": idx.get("key", []),
                    "unique": idx.get("unique", False),
                    "sparse": idx.get("sparse", False),
                    "type": idx.get("type", "regular"),
                }
            )
        return result

    # ── Index scan enforcement ─────────────────────────────────────────────────

    async def _check_index_coverage(
        self, collection: str, filter_keys: set[str], database: str | None = None
    ) -> bool:
        """True if at least one filter field has an index (or _id is filtered)."""
        if not filter_keys or "_id" in filter_keys:
            return True
        col = self._client.get_collection(collection, database)
        info = await col.index_information()
        for idx in info.values():
            indexed = {k for k, _ in idx.get("key", [])}
            if filter_keys & indexed:
                return True
        return False

    async def enforce_index_for_find(
        self, collection: str, filter_: dict, database: str | None = None
    ) -> None:
        """Raise ValueError if enforce_index_usage is True and filter has no index."""
        if not self._enforce_index:
            return
        keys = set(filter_.keys())
        if keys and not await self._check_index_coverage(collection, keys, database):
            raise ValueError(
                f"Query on '{collection}' with fields {sorted(keys)} has no covering index. "
                "Create an index first or use mongodb_collection_indexes to inspect "
                "existing indexes."
            )

    # ── Explain ────────────────────────────────────────────────────────────────

    async def explain_find(
        self,
        collection: str,
        filter_: dict,
        projection: dict | None = None,
        database: str | None = None,
    ) -> dict:
        col = self._client.get_collection(collection, database)
        cursor = col.find(filter_, projection)
        plan = await cursor.explain()
        return _bson_to_json(plan)

    async def explain_aggregate(
        self, collection: str, pipeline: list, database: str | None = None
    ) -> dict:
        # Motor aggregate with explain
        plan = await self._client.get_db(database).command(
            "explain",
            {"aggregate": collection, "pipeline": pipeline, "cursor": {}},
        )
        return _bson_to_json(plan)

    async def explain_find_stats(
        self,
        collection: str,
        filter_: dict,
        projection: dict | None = None,
        database: str | None = None,
    ) -> dict:
        """Explain a find in ``executionStats`` mode (planner + execution metrics,
        WITHOUT returning documents). Used by cost estimation to read
        totalDocsExamined / totalKeysExamined / nReturned / executionTimeMillis
        and the winning-plan stage. Raw plan stays inside the plugin boundary —
        the plugin normalizes it to a CostEstimate and never leaks it."""
        plan = await self._client.get_db(database).command(
            "explain",
            {
                "find": collection,
                "filter": filter_,
                **({"projection": projection} if projection else {}),
            },
            verbosity="executionStats",
        )
        return _bson_to_json(plan)

    async def explain_aggregate_stats(
        self, collection: str, pipeline: list, database: str | None = None
    ) -> dict:
        """Explain an aggregate in ``executionStats`` mode (no result materialized)."""
        plan = await self._client.get_db(database).command(
            "explain",
            {"aggregate": collection, "pipeline": pipeline, "cursor": {}},
            verbosity="executionStats",
        )
        return _bson_to_json(plan)

    # ── Core CRUD + DDL ────────────────────────────────────────────────────────

    # Actions that operate at DB level and don't need a collection handle
    _DB_LEVEL_ACTIONS: frozenset[Action] = frozenset({Action.LIST_DATABASES, Action.DB_STATS})

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        """True for transient network/connection errors worth retrying."""
        from pymongo.errors import AutoReconnect, ConnectionFailure, NetworkTimeout

        return isinstance(exc, (AutoReconnect, ConnectionFailure, NetworkTimeout))

    async def execute(
        self,
        collection: str,
        action: Action,
        params: dict[str, Any],
        database: str | None = None,
    ) -> Any:
        # S-8: client-side retry re-issues the operation. For NON-idempotent
        # writes (insert/update/delete), a NetworkTimeout AFTER the server
        # committed but before the ack would cause a duplicate/double-applied
        # write on retry. So writes get a SINGLE attempt here — durable
        # at-most-once semantics should come from the driver's retryWrites
        # (set retryWrites=true on the connection URI). Reads/introspection,
        # being idempotent, keep the backoff retry.
        from ...core.models.domain import WRITE_ACTIONS

        max_attempts = 1 if action in WRITE_ACTIONS else self._max_retries + 1

        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                return await self._execute_once(collection, action, params, database)
            except Exception as exc:
                if not self._is_retryable(exc) or attempt == max_attempts - 1:
                    raise
                delay = self._retry_base_delay * (2**attempt)
                import asyncio as _asyncio

                log_event(
                    "warning",
                    "transient_error_retry",
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                    retry_in=round(delay, 2),
                    detail=repr(exc),
                )
                await _asyncio.sleep(delay)
                last_exc = exc
        assert last_exc is not None  # unreachable but satisfies type checker
        raise last_exc

    async def _execute_once(
        self,
        collection: str,
        action: Action,
        params: dict[str, Any],
        database: str | None = None,
    ) -> Any:
        col = (
            self._client.get_collection(collection, database)
            if action not in self._DB_LEVEL_ACTIONS
            else None
        )
        match action:
            case Action.FIND:
                return await self._exec_find(col, params, database)
            case Action.COUNT:
                return await self._exec_count(col, params, database)
            case Action.AGGREGATE:
                return await self._exec_aggregate(col, params)
            case Action.EXPLAIN:
                return await self._exec_explain(collection, params, database)
            case Action.COLLECTION_SCHEMA:
                return await self._exec_collection_schema(collection, params, database)
            case Action.COLLECTION_INDEXES:
                return await self.collection_indexes(collection, database)
            case Action.LIST_DATABASES:
                return await self.list_databases()
            case Action.DB_STATS:
                return await self.db_stats(database)
            case Action.INSERT_ONE:
                return await self._exec_insert_one(col, params)
            case Action.INSERT_MANY:
                return await self._exec_insert_many(col, params)
            case Action.UPDATE_ONE:
                return await self._exec_update_one(col, params, database)
            case Action.UPDATE_MANY:
                return await self._exec_update_many(col, params, database)
            case Action.DELETE_ONE:
                return await self._exec_delete_one(col, params, database)
            case Action.DELETE_MANY:
                return await self._exec_delete_many(col, params, database)
            case Action.CREATE_INDEX:
                return await self._exec_create_index(col, params)
            case Action.DROP_INDEX:
                return await self._exec_drop_index(col, params)
            case Action.DROP:
                return await self._exec_drop(col, collection)
            case _:
                raise ValueError(f"unsupported action: {action}")

    # ── Action handlers ────────────────────────────────────────────────────────

    async def _marshal(
        self, collection: str, filter_: Any, database: str | None = None
    ) -> Any:
        """Schema-driven type-marshal a filter at the Mongo boundary.

        Fetches the (cached) canonical type map for the collection and coerces
        filter values to their fields' BSON types. Raises MarshalError (mapped
        to TYPE_MISMATCH upstream) when a known-typed field gets an
        un-coercible value — instead of silently matching nothing.
        """
        type_map = await self.type_map_for(collection, database)
        return marshal_filter(filter_, type_map)

    async def _exec_find(
        self, col, params: dict, database: str | None = None
    ) -> dict:
        filter_ = await self._marshal(col.name, params.get("filter", {}), database)
        await self.enforce_index_for_find(col.name, filter_, database)
        limit = min(int(params.get("limit", 20)), self._max_limit)
        skip = max(0, int(params.get("skip", 0)))
        projection = params.get("projection")
        sort_spec = params.get("sort")
        cursor = col.find(filter_, projection, **self._mtms())
        if sort_spec:
            cursor = cursor.sort(list(sort_spec.items()))
        cursor = cursor.skip(skip).limit(limit)
        docs = await cursor.to_list(limit)
        serialized = _bson_to_json(docs)
        return {
            "documents": serialized,
            "skip": skip,
            "limit": limit,
            "count": len(serialized),
            "next_skip": skip + len(serialized),
            "has_more": len(serialized) == limit,
        }

    async def _exec_count(self, col, params: dict, database: str | None = None) -> int:
        filter_ = await self._marshal(col.name, params.get("filter", {}), database)
        return await col.count_documents(filter_)

    async def _exec_aggregate(self, col, params: dict) -> list:
        pipeline = params.get("pipeline", [])
        # Motor aggregate uses maxTimeMS (not max_time_ms) as a cursor option
        kwargs = {"maxTimeMS": self._max_time_ms} if self._max_time_ms > 0 else {}
        # S-5: cap result materialization. to_list(None) drains the whole cursor
        # into memory (and into the LLM response) — an unbounded {"$match":{}}
        # pipeline could OOM the server. Fetch at most max_limit+1 to detect
        # truncation without loading everything.
        cap = self._max_limit
        docs = await col.aggregate(pipeline, **kwargs).to_list(cap + 1)
        truncated = len(docs) > cap
        if truncated:
            docs = docs[:cap]
        result = _bson_to_json(docs)
        if truncated:
            # marker doc so the agent knows results were capped
            result.append(
                {
                    "_guardmcp_truncated": True,
                    "_note": f"aggregation result capped at {cap} documents. "
                    "Add $limit/$match to narrow the result set.",
                }
            )
        return result

    async def _exec_explain(
        self, collection: str, params: dict, database: str | None = None
    ) -> dict:
        mode = params.get("mode", "find")
        if mode == "aggregate":
            return await self.explain_aggregate(
                collection, params.get("pipeline", []), database
            )
        return await self.explain_find(
            collection, params.get("filter", {}), params.get("projection"), database
        )

    async def _exec_collection_schema(
        self, collection: str, params: dict, database: str | None = None
    ) -> dict:
        return await self.collection_schema(
            collection,
            params.get("mask_fields", []),
            params.get("sample_size"),
            database=database,
        )

    async def _exec_insert_one(self, col, params: dict) -> dict:
        result = await col.insert_one(params["document"])
        return {"inserted_id": str(result.inserted_id)}

    async def _exec_insert_many(self, col, params: dict) -> dict:
        docs = params.get("documents", [])
        result = await col.insert_many(docs)
        return {
            "inserted_count": len(result.inserted_ids),
            "inserted_ids": [str(i) for i in result.inserted_ids],
        }

    async def _exec_update_one(
        self, col, params: dict, database: str | None = None
    ) -> dict:
        filter_ = await self._marshal(col.name, params["filter"], database)
        result = await col.update_one(filter_, params["update"])
        return {"matched": result.matched_count, "modified": result.modified_count}

    async def _exec_update_many(
        self, col, params: dict, database: str | None = None
    ) -> dict:
        filter_ = await self._marshal(col.name, params["filter"], database)
        result = await col.update_many(filter_, params["update"])
        return {"matched": result.matched_count, "modified": result.modified_count}

    async def _exec_delete_one(
        self, col, params: dict, database: str | None = None
    ) -> dict:
        filter_ = await self._marshal(col.name, params["filter"], database)
        result = await col.delete_one(filter_)
        return {"deleted": result.deleted_count}

    async def _exec_delete_many(
        self, col, params: dict, database: str | None = None
    ) -> dict:
        filter_ = await self._marshal(col.name, params["filter"], database)
        result = await col.delete_many(filter_)
        return {"deleted": result.deleted_count}

    async def _exec_create_index(self, col, params: dict) -> dict:
        keys = params["keys"]
        options = params.get("options", {})
        name = await col.create_index([(k, v) for k, v in keys], **options)
        return {"created_index": name}

    async def _exec_drop_index(self, col, params: dict) -> dict:
        index_name = params["index_name"]
        await col.drop_index(index_name)
        return {"dropped_index": index_name}

    async def _exec_drop(self, col, collection: str) -> dict:
        await col.drop()
        return {"dropped": collection}
