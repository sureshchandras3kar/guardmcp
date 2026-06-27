"""Seed mongomock-motor databases from fixture declarations."""

from mongomock_motor import AsyncMongoMockClient

from .models import FixtureDoc


async def seed(
    client: AsyncMongoMockClient, fixtures: list[FixtureDoc], db_name: str = "evaldb"
) -> None:
    for fixture in fixtures:
        if fixture.documents:
            col = client[db_name][fixture.collection]
            await col.insert_many([dict(d) for d in fixture.documents])
