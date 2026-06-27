"""guardmcp_status — connection status, statistics, version, policy summary."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .._common import (
    ToolContext,
    _active_backend_info,
    ok,
)


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    get_pipeline = ctx.get_pipeline
    get_agent = ctx.get_agent
    get_settings = ctx.get_settings
    _RO = ctx.RO

    @mcp.tool(
        description=(
            "GuardMCP connection status, statistics, version, and policy summary.\n"
            "Use when: confirming GuardMCP is connected or reviewing the active policy/backend.\n"
            "Do NOT use when: you need per-collection permitted actions — "
            "call guardmcp_capabilities.\n"
            "Side effects: none (read-only).\n"
            "Example: guardmcp_status()"
        ),
        annotations=_RO,
    )
    async def guardmcp_status() -> str:
        pipeline = get_pipeline()
        agent = get_agent()
        settings = get_settings()

        conn_name = pipeline.active_connection()
        executor = pipeline._get_executor()

        try:
            all_cols = await executor.list_collections()
            collection_count = len(all_cols)
        except Exception:
            collection_count = 0

        db_size_str = "unavailable"
        raw_stats: dict = {}
        try:
            # db_stats is Mongo-specific (not on the Backend protocol); call
            # dynamically and let the surrounding try/except handle backends
            # that don't expose it.
            raw_stats = await executor.db_stats()  # type: ignore[attr-defined]
            total_bytes = raw_stats.get("storageSize", raw_stats.get("dataSize", 0))

            def _fmt_bytes(n: int) -> str:
                if n >= 1_048_576:
                    return f"{n / 1_048_576:.1f} MB"
                if n >= 1024:
                    return f"{n / 1024:.1f} KB"
                return f"{n} B"

            db_size_str = _fmt_bytes(total_bytes)
        except Exception:
            pass

        db_name = settings.mongodb_database if settings else "unknown"

        policy = pipeline._policies.get(agent)
        if policy is not None:
            mode = policy.mode
            policy_loaded = "✓ loaded"
            mf = policy.mask_fields
            masked_fields = (
                sorted({f for fs in mf.values() for f in fs}) if isinstance(mf, dict) else mf
            )
            col_allow = policy.collections.allow
            col_deny = policy.collections.deny
        else:
            mode = "none"
            policy_loaded = "✗ not configured — run guardmcp_setup"
            masked_fields = []
            col_allow = []
            col_deny = []

        rate_info = ""
        if settings and getattr(settings, "rate_limit_rps", 0) > 0:
            rate_info = (
                f"\nRate limit  : {settings.rate_limit_rps} rps (burst {settings.rate_limit_burst})"
            )

        # Point 10: version + backend info.
        try:
            from importlib.metadata import version as _pkg_version

            server_version = _pkg_version("guardmcp")
        except Exception:
            server_version = "0.1.0"
        protocol_version = getattr(settings, "protocol_version", None) or "2024-11-05"

        backend_name, supported_count = _active_backend_info(pipeline)

        masked_str = ", ".join(masked_fields) if masked_fields else "(none)"
        welcome_lines = [
            "╔══════════════════════════════════════╗",
            "║         GuardMCP Connected ✓         ║",
            "╚══════════════════════════════════════╝",
            "",
            f"Agent    : {agent}",
            f"Database : {db_name}",
            f"Backend  : {backend_name} ({supported_count} capabilities)",
            f"Mode     : {mode}",
            f"Policy   : {policy_loaded}",
            f"Version  : {server_version} (protocol {protocol_version})",
            "",
            f"Collections : {collection_count}",
            f"DB Size     : {db_size_str}",
        ]
        if rate_info:
            welcome_lines.append(rate_info.lstrip("\n"))
        welcome_lines.append("")
        welcome_lines.append(f"Masked fields : {masked_str}")
        welcome = "\n".join(welcome_lines)

        stats_obj: dict = {
            "connection": conn_name,
            "database": db_name,
            "agent": agent,
            "mode": mode,
            "policy_loaded": policy is not None,
            "collection_count": collection_count,
            "collections_allow": col_allow,
            "collections_deny": col_deny,
            "masked_fields": masked_fields,
            "db_stats": raw_stats,
            "server_version": server_version,
            "protocol_version": protocol_version,
            "backend": backend_name,
            "backend_capability_count": supported_count,
        }
        if settings and getattr(settings, "rate_limit_rps", 0) > 0:
            stats_obj["rate_limit_rps"] = settings.rate_limit_rps
            stats_obj["rate_limit_burst"] = settings.rate_limit_burst

        return ok({"welcome": welcome, "stats": stats_obj})
