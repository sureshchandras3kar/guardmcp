import argparse
import asyncio
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass

import uvicorn
from mcp.server.fastmcp import FastMCP

from .api.approval import build_approval_app
from .config import Settings
from .core.approval.store import ApprovalStore
from .core.audit.logger import AuditLogger
from .core.observability import log_event
from .core.paths import resolve_audit_path
from .core.pipeline import GuardPipeline
from .core.policy.engine import PolicyEngine
from .core.policy.loader import PolicyLoader
from .core.ratelimit.limiter import RateLimiter
from .core.registry.adapter import CapabilityExecutorAdapter
from .core.registry.connections import ConnectionEntry, ConnectionRegistry
from .core.registry.registry import PluginRegistry
from .core.risk.engine import RiskEngine
from .plugins.mongodb.client import MongoClient
from .plugins.mongodb.executor import MongoExecutor
from .plugins.mongodb.plugin import MongoPlugin
from .plugins.mysql.plugin import MySQLPlugin
from .plugins.postgres.plugin import PostgresPlugin
from .server.tools import register_tools


@dataclass
class AppContext:
    agent: str
    settings: Settings
    pipeline: GuardPipeline
    approval_store: ApprovalStore
    registry: ConnectionRegistry


def _build_plugin_registry() -> PluginRegistry:
    """Composition layer: register the built-in plugins + discover any
    entry-point plugins. Concrete plugins are imported HERE (in __main__),
    never inside core, so core/registry stays backend-agnostic."""
    preg = PluginRegistry()
    preg.register(MongoPlugin)
    preg.register(PostgresPlugin)
    preg.register(MySQLPlugin)
    # Additionally pick up any third-party plugins advertised via entry points.
    try:
        preg.discover()
    except Exception as exc:  # pragma: no cover - discovery is best-effort
        log_event("warning", "plugin_discovery_skipped", detail=repr(exc))
    return preg


def register_sql_connections(
    registry: ConnectionRegistry,
    plugin_registry: PluginRegistry,
    connections: dict,
) -> None:
    """Register non-MongoDB (postgres/mysql) connections behind the legacy
    Backend interface via CapabilityExecutorAdapter.

    P6 scope + testability: the plugin is instantiated but NOT connected here
    (connect() needs a live DB pool we don't have in CI). The adapter performs
    pure Action→Capability translation regardless; the plugin establishes its
    pool lazily/out of band when an operation actually runs. MongoDB remains the
    live default and is untouched by this loop.
    """
    for name, conn in connections.items():
        if conn.type not in {"postgres", "mysql"}:
            continue
        plugin = plugin_registry.instantiate(conn.type)
        adapter = CapabilityExecutorAdapter(plugin)
        registry._registry[name] = ConnectionEntry(
            client=plugin,  # plugin doubles as the (lazily-connected) client
            database=conn.database,
            executor=adapter,
            plugin=plugin,
            # P7: carry per-connection backend options through to the entry so a
            # later plugin.connect(conn.dsn, entry.options) uses them.
            options=dict(conn.options),
        )


def build(settings: Settings) -> tuple[FastMCP, object, AppContext]:
    policy_loader = PolicyLoader(settings.policy_path)
    # R-1: a malformed/invalid policy at startup must produce a clear, actionable
    # error — not a raw pydantic/yaml traceback. (Missing file is handled inside
    # load() as safe deny-all; this guards invalid CONTENT.)
    try:
        policy_loader.load()
    except Exception as exc:
        log_event(
            "error",
            "fatal_policy_load_failed",
            path=str(settings.policy_path),
            detail=str(exc),
            hint="Fix the YAML/schema, or remove the file and run guardmcp_setup.",
        )
        raise SystemExit(2) from exc

    # Backend-agnostic registry + MongoDB client factory (composition layer
    # owns the concrete backend choice; core/registry never names a backend).
    def _mongo_client_factory(uri, database, *, min_pool_size, max_pool_size):
        return MongoClient(uri, database, min_pool_size=min_pool_size, max_pool_size=max_pool_size)

    registry = ConnectionRegistry(client_factory=_mongo_client_factory)
    registry.register(
        "default",
        settings.mongodb_uri,
        settings.mongodb_database,
        min_pool_size=settings.mongo_min_pool_size,
        max_pool_size=settings.mongo_max_pool_size,
    )

    for name, uri in settings.extra_connections.items():
        db = settings.mongodb_database
        registry.register(
            name,
            uri,
            db,
            min_pool_size=settings.mongo_min_pool_size,
            max_pool_size=settings.mongo_max_pool_size,
        )

    # Build one executor per registered connection (avoids Settings() re-instantiation per call)
    for name in registry.list_names():
        entry = registry.get(name)
        if entry is not None:
            entry.executor = MongoExecutor(
                entry.client,
                max_time_ms=settings.max_time_ms,
                enforce_index_usage=settings.enforce_index_usage,
                schema_sample_size=settings.schema_sample_size,
                max_retries=settings.max_retries,
                retry_base_delay=settings.retry_base_delay,
                schema_cache_ttl=settings.schema_cache_ttl,
            )
            # P3: wrap each connection's executor in the formal MongoPlugin.
            # This proves the plugin contract is wired without changing the
            # execution flow (execution still goes through entry.executor).
            entry.plugin = MongoPlugin(executor=entry.executor, client=entry.client)

    # P6: wire any typed non-MongoDB connections (postgres/mysql) through the
    # plugin pipeline via CapabilityExecutorAdapter. MongoDB above is untouched.
    if settings.connections:
        plugin_registry = _build_plugin_registry()
        register_sql_connections(registry, plugin_registry, settings.connections)

    default_entry = registry.get("default")
    if default_entry is None or default_entry.executor is None:
        raise RuntimeError("default connection was not registered/built — cannot start GuardMCP")
    executor = default_entry.executor  # use the already-built executor

    # Resolve the final ABSOLUTE audit path. An explicit absolute
    # GUARDMCP_AUDIT_LOG_PATH (e.g. a Docker volume) passes through unchanged; a
    # relative path is resolved under the platform state dir, never cwd (stdio
    # launches with cwd=/). Operators SEE the resolved path at startup.
    audit_path = resolve_audit_path(settings.audit_log_path)
    log_event("info", "audit_log_path", path=str(audit_path))

    # Startup safety: ensure the audit dir exists and is writable. Fail LOUD
    # with an actionable error instead of a raw traceback from AuditLogger's
    # mkdir / first write — critical when audit_fail_closed denies operations
    # whose audit record cannot be persisted.
    try:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        probe = audit_path.parent / ".guardmcp-write-test"
        probe.write_text("")
        probe.unlink()
    except OSError as exc:
        log_event(
            "error",
            "fatal_audit_path_not_writable",
            path=str(audit_path),
            detail=str(exc),
            hint=(
                "Pick a writable location via GUARDMCP_AUDIT_LOG_PATH=/abs/path "
                "(e.g. a mounted volume), or fix permissions on the directory."
            ),
        )
        raise SystemExit(2) from exc

    audit_logger = AuditLogger(
        audit_path,
        hmac_secret=settings.audit_hmac_secret,
        fail_closed=settings.audit_fail_closed,
        node_id=settings.node_id,
    )
    approval_store = ApprovalStore(settings.approval_timeout_seconds)

    limiter = RateLimiter(rps=settings.rate_limit_rps, burst=settings.rate_limit_burst)
    pipeline = GuardPipeline(
        policy_loader=policy_loader,
        policy_engine=PolicyEngine(),
        risk_engine=RiskEngine(),
        audit_logger=audit_logger,
        approval_store=approval_store,
        executor=executor,
        registry=registry,
        limiter=limiter,
    )

    ctx = AppContext(
        agent=settings.agent,
        settings=settings,
        pipeline=pipeline,
        approval_store=approval_store,
        registry=registry,
    )

    async def _prune_loop(interval: float = 300.0) -> None:
        # M3: periodically drop resolved approvals so the in-memory store can't
        # grow unbounded over a long-running process.
        import asyncio as _a

        while True:
            await _a.sleep(interval)
            with suppress(Exception):
                approval_store.prune()

    @asynccontextmanager
    async def lifespan(_: FastMCP):
        import asyncio as _asyncio
        import contextlib

        policy_loader.start_hot_reload()
        prune_task = _asyncio.create_task(_prune_loop(), name="approval-prune")
        yield ctx
        # R-2: orderly shutdown — stop + AWAIT the hot-reload task (cancel is
        # otherwise fire-and-forget), drain approvals, flush+close the audit
        # handle so no in-flight record is lost, then close connections.
        policy_loader.stop_hot_reload()
        prune_task.cancel()
        with contextlib.suppress(_asyncio.CancelledError):
            await prune_task
        task = getattr(policy_loader, "_task", None)
        if task is not None:
            with contextlib.suppress(_asyncio.CancelledError):
                await task
        drained = approval_store.shutdown()
        if drained:
            log_event("info", "shutdown_drained_approvals", count=drained)
        await audit_logger.aclose()
        registry.close_all()

    mcp = FastMCP("GuardMCP", lifespan=lifespan)
    register_tools(
        mcp,
        get_pipeline=lambda: ctx.pipeline,
        get_agent=lambda: ctx.agent,
        get_settings=lambda: ctx.settings,
    )

    async def _readiness() -> tuple[bool, str]:
        # Ready when a policy is loaded AND the default backend answers a ping.
        # Best-effort: a short timeout, and any error → not-ready (never raises).
        if not policy_loader.all():
            return False, "no policy loaded"
        entry = registry.get("default")
        client = getattr(entry, "client", None) if entry is not None else None
        ping = getattr(client, "ping", None)
        if ping is None:
            return False, "default backend has no reachability probe"
        try:
            await asyncio.wait_for(ping(), timeout=2.0)
        except Exception as exc:  # noqa: BLE001 - readiness must not raise
            return False, f"default backend unreachable: {type(exc).__name__}"
        return True, "ready"

    # DNS-rebinding protection: default the Host allow-list to the configured
    # host + loopback when the operator didn't set one. A 0.0.0.0 bind (Docker)
    # still allows localhost/127.0.0.1; add the external hostname via
    # GUARDMCP_ALLOWED_HOSTS. ["*"] disables (trusted-proxy only).
    allowed_hosts = settings.allowed_hosts or [settings.host, "localhost", "127.0.0.1"]
    rest_app = build_approval_app(
        approval_store,
        api_token=settings.approval_api_token,
        readiness=_readiness,
        allowed_hosts=allowed_hosts,
    )
    return mcp, rest_app, ctx


async def _run_with_approval_api(mcp: FastMCP, rest_app, settings: Settings) -> None:
    match settings.transport:
        case "stdio":
            # stdio: no REST API — process is private to Claude Desktop.
            # Approval via in-band ctx.elicit() only.
            await mcp.run_stdio_async()
        case "sse" | "streamable-http":
            rest_config = uvicorn.Config(
                rest_app,
                host=settings.host,
                port=settings.approval_port,
                log_level="warning",
            )
            rest_server = uvicorn.Server(rest_config)
            async with asyncio.TaskGroup() as tg:
                tg.create_task(rest_server.serve())
                if settings.transport == "sse":
                    tg.create_task(mcp.run_sse_async())
                else:
                    tg.create_task(mcp.run_streamable_http_async())
        case _:
            raise ValueError(f"unknown transport: {settings.transport}")


def serve_main(argv: list[str] | None = None) -> None:
    """Start the GuardMCP server (the original entry-point behavior).

    This is the SERVE path. ``main`` is kept as an alias so any direct importer
    of ``guardmcp.__main__:main`` still starts the server. The subcommand
    dispatcher lives in ``guardmcp.cli`` and falls through to here when no
    subcommand is given (bare invocation or ``--transport/...`` flags).
    """
    parser = argparse.ArgumentParser(description="GuardMCP — policy-enforced MongoDB MCP server")
    parser.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--approval-port", type=int, default=None)
    args = parser.parse_args(argv)

    overrides: dict = {}
    if args.transport:
        overrides["transport"] = args.transport
    if args.host:
        overrides["host"] = args.host
    if args.port:
        overrides["port"] = args.port
    if args.approval_port:
        overrides["approval_port"] = args.approval_port

    settings = Settings(**overrides)

    # H1: refuse to expose an unauthenticated approval API over the network.
    if settings.transport in ("sse", "streamable-http") and (
        not settings.approval_api_token and not settings.approval_allow_insecure
    ):
        log_event(
            "error",
            "fatal_unauthenticated_approval_api",
            transport=settings.transport,
            approval_endpoint=f"{settings.host}:{settings.approval_port}",
            detail=(
                "approval REST API would be exposed with no "
                "GUARDMCP_APPROVAL_API_TOKEN; any local process could approve "
                "CRITICAL writes."
            ),
            hint=(
                "Set GUARDMCP_APPROVAL_API_TOKEN=<secret> (recommended), or "
                "GUARDMCP_APPROVAL_ALLOW_INSECURE=true to override (NOT for production)."
            ),
        )
        raise SystemExit(2)

    mcp, rest_app, _ = build(settings)
    asyncio.run(_run_with_approval_api(mcp, rest_app, settings))


# Back-compat alias: importers of `guardmcp.__main__:main` still get the server.
main = serve_main


if __name__ == "__main__":
    # `python -m guardmcp [...]` routes through the subcommand dispatcher, which
    # falls through to serve_main() when no subcommand is present.
    from .cli import main as cli_main

    cli_main()
