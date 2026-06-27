"""
Live-backend integration tests (testcontainers).

These tests prove the real driver path end-to-end — asyncpg for PostgreSQL,
aiomysql for MySQL, and the real pymongo driver for MongoDB — rather than the
mongomock path the unit tests exercise. They spin a real database in a Docker
container.

SKIP DISCIPLINE: this module must NEVER fail or error the normal suite in a
Docker-less CI. Every test (and the module-level container fixtures) is guarded:

  * ``pytest.importorskip("testcontainers")`` — skip if the lib isn't installed.
  * the relevant driver is import-or-skipped (asyncpg / aiomysql / pymongo).
  * starting a container is wrapped so a missing/broken Docker daemon turns into
    ``pytest.skip("docker unavailable")`` instead of an error.

Run only these with::

    pytest -m integration
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest

pytestmark = pytest.mark.integration


def _start_or_skip(make_container):
    """Start a testcontainer, converting any Docker-unavailable failure into a
    clean skip. Returns the started container; the caller is responsible for
    stopping it."""
    try:
        container = make_container()
        container.start()
        return container
    except Exception as exc:  # noqa: BLE001 - any startup failure → skip, never error
        pytest.skip(f"docker unavailable: {exc!r}")


# ── PostgreSQL ──────────────────────────────────────────────────────────────


@pytest.fixture
def pg_container() -> Iterator[object]:
    pytest.importorskip("testcontainers")
    pytest.importorskip("asyncpg")
    from testcontainers.postgres import PostgresContainer

    container = _start_or_skip(lambda: PostgresContainer("postgres:16-alpine"))
    try:
        yield container
    finally:
        container.stop()


def _asyncpg_dsn(pg_container) -> str:
    """Build an asyncpg-compatible DSN (postgresql://, not postgresql+psycopg2://)."""
    return (
        f"postgresql://{pg_container.username}:{pg_container.password}"
        f"@{pg_container.get_container_host_ip()}"
        f":{pg_container.get_exposed_port(pg_container.port)}"
        f"/{pg_container.dbname}"
    )


async def _pg_plugin(pg_container):
    from guardmcp.plugins.postgres.plugin import PostgresPlugin

    plugin = PostgresPlugin()
    await plugin.connect(_asyncpg_dsn(pg_container), {"min_size": 1, "max_size": 4})
    return plugin


@pytest.mark.asyncio
async def test_postgres_crud_through_plugin(pg_container):
    from guardmcp.core.interfaces.capability import Capability, CapabilityRequest

    plugin = await _pg_plugin(pg_container)
    try:
        # Bootstrap a table directly via the pool (DDL is intentionally not a
        # plugin capability; the harness owns schema setup).
        async with plugin._pool.acquire() as conn:
            await conn.execute("DROP TABLE IF EXISTS widgets")
            await conn.execute("CREATE TABLE widgets (id serial PRIMARY KEY, name text, qty int)")

        # INSERT through the plugin (real asyncpg path, RETURNING *).
        ins = await plugin.execute(
            CapabilityRequest(
                capability=Capability.WRITE_ONE,
                action="insert_one",
                resource="widgets",
                documents=[{"name": "gear", "qty": 3}],
            )
        )
        assert ins.affected == 1
        assert ins.rows and ins.rows[0]["name"] == "gear"

        await plugin.execute(
            CapabilityRequest(
                capability=Capability.WRITE_MANY,
                action="insert_many",
                resource="widgets",
                documents=[{"name": "bolt", "qty": 10}, {"name": "nut", "qty": 20}],
            )
        )

        # READ
        read = await plugin.execute(
            CapabilityRequest(capability=Capability.READ, action="find", resource="widgets")
        )
        assert len(read.rows) == 3

        # COUNT
        cnt = await plugin.execute(
            CapabilityRequest(capability=Capability.COUNT, action="count", resource="widgets")
        )
        assert cnt.scalar == 3

        # DELETE (filtered). The Postgres plugin reports affected rows from a
        # RETURNING projection; a plain DELETE has none, so verify the OUTCOME
        # via a follow-up COUNT (the durable, backend-truthful assertion).
        await plugin.execute(
            CapabilityRequest(
                capability=Capability.DELETE_MANY,
                action="delete_many",
                resource="widgets",
                filter={"name": "gear"},
            )
        )

        cnt2 = await plugin.execute(
            CapabilityRequest(capability=Capability.COUNT, action="count", resource="widgets")
        )
        assert cnt2.scalar == 2  # gear removed, bolt + nut remain
    finally:
        await plugin.close()


@pytest.mark.asyncio
async def test_postgres_governance_e2e(pg_container, tmp_path):
    """Build a real GuardPipeline over the live PG plugin via
    CapabilityExecutorAdapter, apply a policy (readonly denies insert; mask a
    column), and assert deny + masking on real Postgres."""
    from guardmcp.core.audit.logger import AuditLogger
    from guardmcp.core.interfaces.capability import Capability, CapabilityRequest
    from guardmcp.core.models.domain import Action
    from guardmcp.core.pipeline import GuardPipeline
    from guardmcp.core.policy.engine import PolicyEngine
    from guardmcp.core.policy.loader import PolicyLoader
    from guardmcp.core.registry.adapter import CapabilityExecutorAdapter
    from guardmcp.core.registry.connections import ConnectionEntry, ConnectionRegistry
    from guardmcp.core.risk.engine import RiskEngine

    plugin = await _pg_plugin(pg_container)
    try:
        async with plugin._pool.acquire() as conn:
            await conn.execute("DROP TABLE IF EXISTS people")
            await conn.execute("CREATE TABLE people (id serial PRIMARY KEY, name text, email text)")
        # Seed rows directly so the masking assertion is meaningful.
        await plugin.execute(
            CapabilityRequest(
                capability=Capability.WRITE_MANY,
                action="insert_many",
                resource="people",
                documents=[
                    {"name": "Alice", "email": "alice@example.com"},
                    {"name": "Bob", "email": "bob@example.com"},
                ],
            )
        )

        # Policy: readonly (denies insert), mask the email column.
        policy_file = tmp_path / "policy.yaml"
        policy_file.write_text(
            """
agent: live-agent
mode: readonly
collections:
  allow:
    - people
actions:
  allow:
    - find
    - count
mask_fields:
  - email
"""
        )
        loader = PolicyLoader(policy_file)
        loader.load()

        adapter = CapabilityExecutorAdapter(plugin)
        registry = ConnectionRegistry()
        registry._registry["default"] = ConnectionEntry(
            client=plugin, database="", executor=adapter, plugin=plugin
        )

        pipeline = GuardPipeline(
            policy_loader=loader,
            policy_engine=PolicyEngine(),
            risk_engine=RiskEngine(),
            audit_logger=AuditLogger(tmp_path / "audit.jsonl"),
            approval_store=None,
            executor=adapter,
            registry=registry,
        )

        # readonly → insert is DENIED before touching the DB.
        denied = await pipeline.run(
            "live-agent", "people", Action.INSERT_ONE, {"document": {"name": "Eve"}}
        )
        assert denied["status"] == "denied"

        # find is allowed; email is masked on real Postgres rows.
        from guardmcp.core.masking.masker import MASK_VALUE

        ok = await pipeline.run("live-agent", "people", Action.FIND, {"filter": {}, "limit": 10})
        assert ok["status"] == "success"
        docs = ok["data"]["documents"]
        assert len(docs) == 2
        assert all(d["email"] == MASK_VALUE for d in docs)
        assert {d["name"] for d in docs} == {"Alice", "Bob"}
    finally:
        await plugin.close()


# ── MySQL ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def mysql_container() -> Iterator[object]:
    pytest.importorskip("testcontainers")
    pytest.importorskip("aiomysql")
    from testcontainers.mysql import MySqlContainer

    container = _start_or_skip(lambda: MySqlContainer("mysql:8.0"))
    try:
        yield container
    finally:
        container.stop()


async def _mysql_plugin(mysql_container):
    from guardmcp.plugins.mysql.plugin import MySQLPlugin

    plugin = MySQLPlugin()
    # aiomysql.create_pool takes discrete kwargs — pass them via options.
    await plugin.connect(
        "",
        {
            "host": mysql_container.get_container_host_ip(),
            "port": int(mysql_container.get_exposed_port(mysql_container.port)),
            "user": mysql_container.username,
            "password": mysql_container.password,
            "db": mysql_container.dbname,
            "minsize": 1,
            "maxsize": 4,
            "autocommit": True,
        },
    )
    return plugin


@pytest.mark.asyncio
async def test_mysql_crud_through_plugin(mysql_container):
    from guardmcp.core.interfaces.capability import Capability, CapabilityRequest

    plugin = await _mysql_plugin(mysql_container)
    try:
        async with plugin._pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute("DROP TABLE IF EXISTS widgets")
            await cur.execute(
                "CREATE TABLE widgets (id INT AUTO_INCREMENT PRIMARY KEY, "
                "name VARCHAR(64), qty INT)"
            )

        ins = await plugin.execute(
            CapabilityRequest(
                capability=Capability.WRITE_ONE,
                action="insert_one",
                resource="widgets",
                documents=[{"name": "gear", "qty": 3}],
            )
        )
        # MySQL has no RETURNING — affected rows reported instead.
        assert ins.affected == 1

        await plugin.execute(
            CapabilityRequest(
                capability=Capability.WRITE_MANY,
                action="insert_many",
                resource="widgets",
                documents=[{"name": "bolt", "qty": 10}, {"name": "nut", "qty": 20}],
            )
        )

        cnt = await plugin.execute(
            CapabilityRequest(capability=Capability.COUNT, action="count", resource="widgets")
        )
        assert cnt.scalar == 3

        read = await plugin.execute(
            CapabilityRequest(capability=Capability.READ, action="find", resource="widgets")
        )
        assert len(read.rows) == 3

        dele = await plugin.execute(
            CapabilityRequest(
                capability=Capability.DELETE_MANY,
                action="delete_many",
                resource="widgets",
                filter={"name": "gear"},
            )
        )
        assert dele.affected == 1
    finally:
        await plugin.close()


# ── MongoDB (real driver, minimal) ─────────────────────────────────────────────


@pytest.fixture
def mongo_container() -> Iterator[object]:
    pytest.importorskip("testcontainers")
    pytest.importorskip("motor")
    from testcontainers.mongodb import MongoDbContainer

    container = _start_or_skip(lambda: MongoDbContainer("mongo:7"))
    try:
        yield container
    finally:
        container.stop()


@pytest.mark.asyncio
async def test_mongo_real_driver_find_insert(mongo_container):
    """Prove the real motor/pymongo driver path (unit tests use mongomock)."""
    from guardmcp.core.models.domain import Action
    from guardmcp.plugins.mongodb.client import MongoClient
    from guardmcp.plugins.mongodb.executor import MongoExecutor

    uri = mongo_container.get_connection_url()
    client = MongoClient(uri, "livetest")
    executor = MongoExecutor(client)
    try:
        col = client.get_collection("widgets")
        await col.delete_many({})
        await col.insert_many([{"name": "gear"}, {"name": "bolt"}])

        result = await executor.execute("widgets", Action.FIND, {"filter": {}, "limit": 10})
        docs = result["documents"]
        assert len(docs) == 2
        assert {d["name"] for d in docs} == {"gear", "bolt"}
    finally:
        client.close()
        await asyncio.sleep(0)  # let driver close cleanly
