from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase


class MongoClient:
    def __init__(
        self,
        uri: str,
        database: str,
        min_pool_size: int = 0,
        max_pool_size: int = 100,
    ) -> None:
        self._client: AsyncIOMotorClient = AsyncIOMotorClient(
            uri,
            minPoolSize=min_pool_size,
            maxPoolSize=max_pool_size,
            # S-8: server-side at-most-once retry for writes. The client-side
            # retry loop deliberately does NOT re-issue writes; durable write
            # retry is delegated to the driver. Can be overridden in the URI.
            retryWrites=True,
        )
        self._db: AsyncIOMotorDatabase = self._client[database]

    def get_db(self, name: str | None = None):
        return self._client[name] if name else self._db

    def get_collection(self, name: str, database: str | None = None):
        return self.get_db(database)[name]

    async def list_collection_names(self, database: str | None = None) -> list[str]:
        return await self.get_db(database).list_collection_names()

    async def list_databases(self) -> list[dict]:
        result: Any = await self._client.list_databases()
        return [{"name": db["name"], "sizeOnDisk": db.get("sizeOnDisk", 0)} for db in result]

    async def ping(self) -> bool:
        await self._client.admin.command("ping")
        return True

    def close(self) -> None:
        self._client.close()
