# GuardMCP Architecture

**Legend:** Risk #N references are numbered findings from security and architecture reviews
conducted during development. They document known limitations or design seams (e.g. distributed
audit, principal identity resolution) that are correctly handled today but deferred to v2.

## Backend interfaces: public vs internal (Risk #9)

GuardMCP has two backend-facing interfaces with distinct roles. Implement only
the public one.

| Interface | File | Role | Who implements it |
|-----------|------|------|-------------------|
| `DatabasePlugin` | `core/interfaces/plugin.py` | **PUBLIC** plugin contract. Capability-based, database-neutral. | Third-party / built-in backend authors (Postgres, MySQL, …) |
| `Backend` | `core/interfaces/backend.py` | **INTERNAL** execution interface consumed by `GuardPipeline`. Mongo-shaped (`execute`, `list_collections`, `collection_schema`, …). | `MongoExecutor` (natively) and `CapabilityExecutorAdapter` (on behalf of any plugin). Never implemented directly by a plugin. |

A new backend implements `DatabasePlugin`. `CapabilityExecutorAdapter`
(`core/registry/adapter.py`) bridges it to the internal `Backend` surface the
pipeline calls. `MongoExecutor` is the one backend that implements `Backend`
directly (and is also wrapped by `MongoPlugin` to prove the public contract).

### Request / result flow

```
MCP tool call
  → server/tools  (resolves agent id; see PrincipalResolver, Risk #7)
    → GuardPipeline.run / evaluate
        policy + risk + aggregation guards
        rate-limit check        (RateLimiterProtocol)
        audit log               (AuditSinkProtocol)
        approval if required    (ApprovalStoreProtocol)
      → Backend.execute()       (INTERNAL interface)
           MongoExecutor          → MongoDB
           CapabilityExecutorAdapter → DatabasePlugin.execute() (PUBLIC contract)
      ← raw result → field-allow + masking → response
```

## Governance-state seams (Risk #4)

`GuardPipeline` is typed against Protocols in `core/interfaces/stores.py`, not the
concrete classes, so distributed backends drop in via the composition layer
(`__main__`) without touching core call sites:

| Protocol | Shipped default | Distributed drop-in |
|----------|-----------------|---------------------|
| `ApprovalStoreProtocol` | `ApprovalStore` (in-memory dict + asyncio.Event) | Redis store + pub/sub |
| `RateLimiterProtocol` | `RateLimiter` (per-process token bucket) | shared token bucket in Redis |
| `AuditSinkProtocol` | `AuditLogger` (per-process HMAC-chained JSONL) | Kafka+KMS / QLDB / append-only S3 |

## Audit attribution under multiple writers (Risk #5)

The HMAC chain in `AuditLogger` is **per-process single-writer**. Each replica
writes an independent genesis-rooted chain to its own file — there is **no
cross-replica chain**. Set a unique `GUARDMCP_NODE_ID` per replica; it is stamped
on every `AuditRecord.node_id`. For centralized tamper-evident audit across
replicas, implement `AuditSinkProtocol` over an append-only store and aggregate by
`node_id`.

## Principal (agent identity) resolution (Risk #7)

`core/interfaces/identity.py` defines `PrincipalResolver`. The default
`StaticPrincipalResolver` returns the operator-configured `settings.agent`
(current behavior). The `X-GuardMCP-Agent` header is trusted **only** behind a
gateway that authenticates and sets it. For zero-trust, supply a JWT/mTLS
resolver in the composition layer; `require_authenticated_principal` denies when
no principal resolves.

## Active-connection isolation (Risk #8)

The active connection is a `ContextVar` in `core/registry/connections.py`.
Correctness under concurrent multi-agent transports REQUIRES each request to run
in its own `contextvars.Context` (FastMCP copies context per request) so a
`switch()` in one request never leaks to another. Verified for stdio (single
session); for SSE/streamable-http the active connection must remain
request-scoped.
