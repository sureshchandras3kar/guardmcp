from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .core.paths import default_audit_log_path


class ConnectionConfig(BaseModel):
    type: str = "mongodb"  # mongodb | postgres | mysql
    dsn: str
    database: str = ""
    # Arbitrary per-connection backend options (pool sizing, ssl, schema,
    # timeouts, ...). Passed verbatim to the plugin's connect(dsn, options) so a
    # later connect() has them without bloating the flat Settings surface, e.g.
    #   GUARDMCP_CONNECTIONS='{"analytics":{"type":"postgres","dsn":"postgres://...",
    #     "database":"app","options":{"min_size":1,"max_size":10,"ssl":true}}}'
    # MongoDB is unaffected (it uses Settings.mongo_* pool sizes).
    options: dict[str, Any] = Field(default_factory=dict)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GUARDMCP_")

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_database: str = "guardmcp"
    policy_path: Path = Path("policies/policy.yaml")
    # Default audit log goes to a PLATFORM-APPROPRIATE per-user state/log dir,
    # resolved to an ABSOLUTE path (see core/paths.py). NOT cwd-relative: stdio
    # launches often have cwd=/ , so a relative default would write to root.
    # An explicit absolute GUARDMCP_AUDIT_LOG_PATH (e.g. a Docker volume) wins;
    # a relative override is resolved under the state dir by resolve_audit_path
    # in __main__.build(), never against cwd.
    audit_log_path: Path = Field(default_factory=default_audit_log_path)
    approval_timeout_seconds: float = 300.0

    # Fix 1: agent identity set by operator at server startup, never by AI.
    # For stdio (Claude Desktop): set GUARDMCP_AGENT in the MCP server config.
    # For HTTP: set GUARDMCP_AGENT per deployment or use X-GuardMCP-Agent header.
    agent: str = "default-agent"

    transport: str = "stdio"  # stdio | sse | streamable-http
    host: str = "127.0.0.1"
    port: int = 8000
    approval_port: int = 8001

    # Query safety
    max_time_ms: int = 30_000  # 30s per-query timeout; 0 = unlimited
    enforce_index_usage: bool = False  # block find() with no covering index
    schema_sample_size: int = 20  # docs sampled for collection-schema

    # Confirmation mode for approval-required operations
    # True  → ctx.elicit() (in-band, appears in chat)
    # False → elicit_url() pointing at approval REST API (out-of-band)
    inband_confirm: bool = True

    approval_api_token: str = ""
    # empty = no auth (stdio-only deployments)
    # Set GUARDMCP_APPROVAL_API_TOKEN=<secret> for SSE/HTTP deployments

    approval_allow_insecure: bool = False
    # H1: SSE/streamable-http expose the approval REST API on a TCP port. If the
    # token is empty, any local process can approve CRITICAL writes. The server
    # REFUSES to start in those transports unless a token is set OR this flag is
    # explicitly True. stdio is unaffected (no port is opened).

    # DNS-rebinding protection: Host-header allow-list for the networked approval
    # API. Empty (default) → __main__ derives a safe default (configured host +
    # loopback). Set GUARDMCP_ALLOWED_HOSTS (JSON list) to add proxy/ingress
    # hostnames. ["*"] disables the check (only behind a trusted proxy).
    allowed_hosts: list[str] = []

    # Extra named connections: GUARDMCP_EXTRA_CONNECTIONS__staging=mongodb://stg:27017/db
    extra_connections: dict[str, str] = {}

    # Typed multi-backend connections. Parsed from a JSON object in the
    # GUARDMCP_CONNECTIONS env var, e.g.
    #   GUARDMCP_CONNECTIONS='{"analytics": {"type":"postgres","dsn":"postgres://...","database":"app"}}'
    # ADDITIVE: the "default" mongodb connection (from mongodb_uri) is always
    # built regardless. Entries with type in {postgres, mysql} are wired through
    # the plugin pipeline via CapabilityExecutorAdapter.
    connections: dict[str, ConnectionConfig] = {}

    # Rate limiting
    rate_limit_rps: float = 0.0  # requests per second per agent (0 = disabled)
    rate_limit_burst: int = 10  # token bucket burst size

    # Retry strategy for transient errors
    max_retries: int = 3
    retry_base_delay: float = 0.1

    # Schema inference TTL cache
    schema_cache_ttl: int = 300  # seconds; 0 = disabled

    # Motor connection pool
    mongo_min_pool_size: int = 0  # Motor default
    mongo_max_pool_size: int = 100  # Motor default

    # Audit log HMAC integrity
    audit_hmac_secret: str = ""
    # When set, each audit log entry includes an HMAC-SHA256 signature.
    # Set GUARDMCP_AUDIT_HMAC_SECRET=<random-secret> in production.
    # Empty string = HMAC disabled.

    # Risk #5: identifies this process/replica in every audit record it writes.
    # Default "" (single process). In a multi-replica deployment set a UNIQUE
    # GUARDMCP_NODE_ID per replica (e.g. the pod/hostname) so a centralized audit
    # sink can attribute and aggregate records by writer. The HMAC chain is
    # per-process single-writer — see core/audit/logger.py for the cross-replica
    # caveat and the AuditSinkProtocol seam.
    node_id: str = ""

    # Risk #7: when True, a request with no resolvable authenticated principal is
    # denied. The default StaticPrincipalResolver always resolves the configured
    # agent, so this is a no-op until a real PrincipalResolver (JWT/mTLS) is wired
    # in the composition layer. The X-GuardMCP-Agent header is trusted ONLY behind
    # a gateway that authenticates and sets it.
    require_authenticated_principal: bool = False

    # #8: structured logging controls (read directly by core/observability/log.py
    # from the env, mirrored here so they appear in Settings + can be set via
    # GUARDMCP_LOG_LEVEL / GUARDMCP_LOG_FORMAT like every other setting).
    log_level: str = "info"  # debug | info | warning | error
    log_format: str = "json"  # json | text (text = legacy human prints)

    audit_fail_closed: bool = False
    # CR-2: when True, a failed audit write ABORTS the operation instead of
    # silently proceeding. Recommended for compliance deployments — a request
    # that cannot be audited must not mutate data. Default False (fail-open)
    # preserves availability for dev/stdio use.
