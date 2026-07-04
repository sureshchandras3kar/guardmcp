"""
MongoSchemaCache — collaborator owning the schema-cache + type-map group.

Extracted from MongoExecutor so execution and the schema-sampling/caching
concern are separable. Holds the bounded TTL/LRU cache state, samples documents
ONCE per collection, and derives BOTH the canonical display schema and the BSON
type map (consumed by the filter marshaller) from the SAME sample so they never
disagree. The executor holds an instance and delegates ``collection_schema`` /
``type_map_for`` to it.
"""

import time
from collections import OrderedDict

from ._serialize import _bson_to_json
from .client import MongoClient
from .schema import apply_mask, build_type_map, infer_schema


class MongoSchemaCache:
    def __init__(
        self,
        client: MongoClient,
        schema_sample_size: int = 20,
        schema_cache_ttl: int = 300,
    ) -> None:
        self._client = client
        self._schema_sample = schema_sample_size
        self._schema_cache_ttl = schema_cache_ttl
        # M3: bounded LRU cache: (database, collection) → (raw_schema, type_map, expiry).
        # database=None means the configured default DB (back-compat bucket).
        # raw_schema is the canonical display schema (pre-mask); type_map is the
        # canonical BSON type map consumed by the filter marshaller. Both are
        # derived from the SAME document sample so they never disagree.
        # Capped so a DB with thousands of collections can't grow it unbounded.
        self._schema_cache_max = 256
        self._schema_cache: OrderedDict[
            tuple[str | None, str], tuple[dict, dict, float]
        ] = OrderedDict()

    async def _sample_schema(
        self,
        collection: str,
        sample_size: int | None = None,
        database: str | None = None,
    ) -> tuple[dict, dict]:
        """Return (canonical display schema, canonical type_map) for a collection.

        Samples documents ONCE and derives both views from the same raw sample,
        caching them together under the TTL/LRU cache. The display schema uses
        canonical BSON tokens (objectId/date/decimal/int/long/double/string/
        bool/array/object) so db_schema reports the same types the marshaller
        coerces to. The type_map drops polymorphic fields (see build_type_map).

        Cache key is (database, collection): database=None → configured default DB
        (backward-compatible with the previous single-DB cache bucket).
        """
        cache_key = (database, collection)

        if self._schema_cache_ttl > 0:
            cached = self._schema_cache.get(cache_key)
            if cached is not None:
                raw_schema, type_map, expiry = cached
                if time.monotonic() < expiry:
                    self._schema_cache.move_to_end(cache_key)  # LRU touch
                    return raw_schema, type_map

        col = self._client.get_collection(collection, database)
        n = sample_size or self._schema_sample
        docs = await col.find({}).limit(n).to_list(n)
        # Canonical type map is built from RAW docs (ObjectId/datetime/Decimal128
        # intact); the display schema reuses that per-field canonical token.
        type_map = build_type_map(docs)
        raw_schema = self._display_schema(docs, type_map)

        if self._schema_cache_ttl > 0:
            self._schema_cache[cache_key] = (
                raw_schema,
                type_map,
                time.monotonic() + self._schema_cache_ttl,
            )
            self._schema_cache.move_to_end(cache_key)
            while len(self._schema_cache) > self._schema_cache_max:
                self._schema_cache.popitem(last=False)  # evict LRU

        return raw_schema, type_map

    @staticmethod
    def _display_schema(raw_docs: list[dict], type_map: dict[str, str]) -> dict:
        """Canonical-token display schema. Polymorphic fields (absent from the
        single-type type_map) fall back to infer_schema's multi-type list so the
        agent still sees the field, just without a single canonical token."""
        canonical = dict(type_map)
        fallback = infer_schema([_bson_to_json(d) for d in raw_docs])
        for field, label in fallback.items():
            canonical.setdefault(field, label)
        return canonical

    async def type_map_for(
        self, collection: str, database: str | None = None
    ) -> dict[str, str]:
        """Canonical BSON type map for the filter marshaller (cached)."""
        _, type_map = await self._sample_schema(collection, database=database)
        return type_map

    async def collection_schema(
        self,
        collection: str,
        mask_fields: list[str],
        sample_size: int | None = None,
        database: str | None = None,
    ) -> dict:
        raw_schema, _ = await self._sample_schema(collection, sample_size, database=database)
        return apply_mask(raw_schema, mask_fields)

