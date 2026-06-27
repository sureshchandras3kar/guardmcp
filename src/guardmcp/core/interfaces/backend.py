"""
Backend Protocol — INTERNAL execution interface consumed by GuardPipeline.

NOT the public plugin contract. Third-party backends implement DatabasePlugin
(core/interfaces/plugin.py) and are bridged to this internal interface by
CapabilityExecutorAdapter. Do NOT implement Backend directly in a plugin.

This is the Mongo-shaped surface the pipeline calls (execute / list_collections /
collection_schema / collection_indexes / list_databases / enforce_index_for_find).
MongoExecutor satisfies it natively; the adapter satisfies it on behalf of any
DatabasePlugin. See docs/ARCHITECTURE.md for the public-vs-internal table.
"""

from typing import Any, Protocol, runtime_checkable

from ..models.domain import Action


@runtime_checkable
class Backend(Protocol):
    """Formal interface for GuardMCP database backends."""

    async def execute(self, collection: str, action: Action, params: dict[str, Any]) -> Any:
        """Execute an action against the backend. Raises ValueError for unsupported actions."""
        ...

    async def list_collections(self) -> list[str]:
        """Return all collection/table names in the active database."""
        ...

    async def collection_schema(
        self, collection: str, mask_fields: list[str], sample_size: int | None = None
    ) -> dict[str, Any]:
        """Infer field types from a sample of documents. Masked fields shown as 'masked'."""
        ...

    async def collection_indexes(self, collection: str) -> list[dict[str, Any]]:
        """Return index metadata for the collection."""
        ...

    async def list_databases(self) -> list[dict[str, Any]]:
        """Return database names and sizes."""
        ...

    async def enforce_index_for_find(self, collection: str, filter_: dict[str, Any]) -> None:
        """Raise ValueError if filter has no covering index and enforcement is enabled."""
        ...
