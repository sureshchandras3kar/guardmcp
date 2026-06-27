# Graph Report - guardmcp  (2026-06-27)

## Corpus Check
- 159 files · ~80,355 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1967 nodes · 4203 edges · 121 communities (109 shown, 12 thin omitted)
- Extraction: 81% EXTRACTED · 19% INFERRED · 0% AMBIGUOUS · INFERRED: 805 edges (avg confidence: 0.62)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `9b2e9dc9`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 73|Community 73]]
- [[_COMMUNITY_Community 74|Community 74]]
- [[_COMMUNITY_Community 75|Community 75]]
- [[_COMMUNITY_Community 76|Community 76]]
- [[_COMMUNITY_Community 77|Community 77]]
- [[_COMMUNITY_Community 78|Community 78]]
- [[_COMMUNITY_Community 79|Community 79]]
- [[_COMMUNITY_Community 80|Community 80]]
- [[_COMMUNITY_Community 81|Community 81]]
- [[_COMMUNITY_Community 82|Community 82]]
- [[_COMMUNITY_Community 105|Community 105]]
- [[_COMMUNITY_Community 106|Community 106]]
- [[_COMMUNITY_Community 107|Community 107]]
- [[_COMMUNITY_Community 108|Community 108]]
- [[_COMMUNITY_Community 109|Community 109]]
- [[_COMMUNITY_Community 110|Community 110]]
- [[_COMMUNITY_Community 111|Community 111]]
- [[_COMMUNITY_Community 112|Community 112]]
- [[_COMMUNITY_Community 113|Community 113]]
- [[_COMMUNITY_Community 114|Community 114]]
- [[_COMMUNITY_Community 115|Community 115]]
- [[_COMMUNITY_Community 116|Community 116]]
- [[_COMMUNITY_Community 117|Community 117]]
- [[_COMMUNITY_Community 118|Community 118]]
- [[_COMMUNITY_Community 119|Community 119]]
- [[_COMMUNITY_Community 123|Community 123]]

## God Nodes (most connected - your core abstractions)
1. `MongoExecutor` - 65 edges
2. `AuditLogger` - 63 edges
3. `Action` - 54 edges
4. `GuardPipeline` - 50 edges
5. `GuardValidationError` - 43 edges
6. `DatabasePlugin` - 43 edges
7. `PolicyEngine` - 41 edges
8. `FakePlugin` - 41 edges
9. `CapabilityRequest` - 40 edges
10. `ApprovalStore` - 38 edges

## Surprising Connections (you probably didn't know these)
- `audit_logger()` --calls--> `AuditLogger`  [INFERRED]
  tests/conftest.py → src/guardmcp/core/audit/logger.py
- `test_rate_limiter_satisfies_protocol()` --calls--> `RateLimiter`  [INFERRED]
  tests/unit/test_seams.py → src/guardmcp/core/ratelimit/limiter.py
- `test_adapter_estimate_delegates_to_plugin()` --calls--> `CapabilityExecutorAdapter`  [INFERRED]
  tests/unit/test_cost_estimate.py → src/guardmcp/core/registry/adapter.py
- `test_mongo_plugin_estimate_failure_is_unknown()` --calls--> `MongoPlugin`  [INFERRED]
  tests/unit/test_cost_estimate.py → src/guardmcp/plugins/mongodb/plugin.py
- `test_mongo_find_result_exposes_neutral()` --calls--> `from_pipeline_result()`  [INFERRED]
  tests/unit/test_neutral_envelope.py → src/guardmcp/server/responses.py

## Import Cycles
- 1-file cycle: `src/guardmcp/api/approval.py -> src/guardmcp/api/approval.py`
- 1-file cycle: `src/guardmcp/plugins/mongodb/marshal.py -> src/guardmcp/plugins/mongodb/marshal.py`
- 1-file cycle: `src/guardmcp/server/tools/__init__.py -> src/guardmcp/server/tools/__init__.py`
- 1-file cycle: `src/guardmcp/server/tools/meta/__init__.py -> src/guardmcp/server/tools/meta/__init__.py`

## Communities (121 total, 12 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.05
Nodes (39): ApprovalStore, Remove resolved approvals older than max_age_seconds. Returns count pruned., Deny all pending approvals immediately and signal their events.         Call on, ApprovalRequest, PolicyLoader, Sorted list of *.yaml/*.yml files when _path is a directory.          Sorting ma, Apply the SAME doc shape parsing (list / {agents:[...]} / single)., Max mtime to watch. For a directory: the dir's own mtime (catches         add/re (+31 more)

### Community 1 - "Community 1"
Cohesion: 0.07
Nodes (30): ApprovalStoreProtocol, AuditSinkProtocol, EvalResult, GuardPipeline, Return executor for the active connection (or default)., Run policy + risk check. Does NOT execute or audit.          `trace` (optional):, #1 seam: capability-native entry point.          Maps a Capability → a represent, Deny if the policy has a temporal window and now is outside it. (+22 more)

### Community 2 - "Community 2"
Cohesion: 0.05
Nodes (28): MySQLPlugin, Map cursor rows to dicts.          aiomysql's default cursor returns tuples; we, Estimate a READ/COUNT via ``EXPLAIN FORMAT=JSON <sql>`` (plan only —         no, EXPLAIN FORMAT=JSON returns one row with the JSON plan in its single         col, Any, CapabilityRequest, CapabilityResult, CostEstimate (+20 more)

### Community 3 - "Community 3"
Cohesion: 0.11
Nodes (30): Context, Action, Any, FastMCP, FastMCP, ToolContext, FastMCP, FastMCP (+22 more)

### Community 4 - "Community 4"
Cohesion: 0.08
Nodes (31): _coerce_none_sentinels(), _parse_json_or_pass(), Database-agnostic grounding/security helpers.  MongoDB-specific validation (oper, Coerce a JSON-encoded string to dict/list. Non-strings pass through., Map '', 'null', 'none', 'undefined' → None for optional dict params., guardmcp_capabilities — backend + per-collection permitted-action discovery., register(), GuardMCP meta tools (single-named, no db_/mongodb_ alias).  The former monolithi (+23 more)

### Community 5 - "Community 5"
Cohesion: 0.14
Nodes (14): EC-3 fail-safe: a masked field nested far beyond _MAX_DEPTH must NOT be     retu, test_ec3_beyond_bound_redacts_not_raw(), FieldMasker, #10: split mask entries into bare names (match a key at ANY depth, the     histo, Recursively mask sensitive fields. Bare names match a key at any         depth;, H3: single-pass field allow-list + masking. Replaces two separate full     trave, ResultTransformer, _split_mask_entries() (+6 more)

### Community 6 - "Community 6"
Cohesion: 0.08
Nodes (33): CapabilityExecutorAdapter, Delegate cost estimation to the plugin through the same Backend         boundary, Generic safe error message — never leaks backend internals., Presents a DatabasePlugin behind the legacy Backend interface the     pipeline c, Action, Any, Capability, CapabilityRequest (+25 more)

### Community 7 - "Community 7"
Cohesion: 0.19
Nodes (8): from_pipeline_result(), Map a GuardPipeline result dict to the standard envelope.      Pipeline shapes:, test_from_pipeline_result_denied_collection(), test_from_pipeline_result_denied_readonly(), test_from_pipeline_result_error_backend(), test_from_pipeline_result_rate_limited(), test_from_pipeline_result_success(), TestFromPipelineResultPrefersCode

### Community 8 - "Community 8"
Cohesion: 0.05
Nodes (41): Approval REST API, Architecture Challenges & Improvements, Deliverable 10: Async Performance Considerations, Deliverable 11: Docker Deployment Design, Deliverable 12: Testing Strategy, Deliverable 13: API Contracts, Deliverable 14: Example Policy Files, Deliverable 15: Open-Source Roadmap (+33 more)

### Community 9 - "Community 9"
Cohesion: 0.06
Nodes (44): ApprovalStore, Deterministic assertion engine for GuardMCP evals.  Checks actual pipeline outpu, main(), guardmcp eval — CLI entry point.  Usage:     python -m guardmcp.eval evals/cases, Seed mongomock-motor databases from fixture declarations., seed(), discover(), _load_file() (+36 more)

### Community 10 - "Community 10"
Cohesion: 0.14
Nodes (21): current_traceparent(), _format(), get_trace_id(), new_span_id(), new_trace_id(), parse_traceparent(), Dependency-free structured logging + trace-id correlation.  Replaces ad-hoc `pri, Parse a W3C `traceparent` header and return its 32-hex trace-id, or None     if (+13 more)

### Community 11 - "Community 11"
Cohesion: 0.16
Nodes (20): _indexes_sql(), _list_databases_sql(), _list_resources_sql(), quote_ident(), PURE translation: CapabilityRequest -> (sql, args) for PostgreSQL.  This is now, Translate a CapabilityRequest into parameterized SQL + positional args.      Rai, Validate a (possibly schema-qualified) identifier and return it verbatim.      E, _schema_from_options() (+12 more)

### Community 12 - "Community 12"
Cohesion: 0.19
Nodes (12): GuardValidationError, Request failed backend safety validation (injection, banned construct).      Mes, _ArgCounter, Issues placeholders (dialect-specific) and accumulates the bound values., Build a parameterized WHERE clause (without the WHERE keyword).          Returns, Single-row insert from documents[0], or UPDATE if filter+update present., Bound a single-row DELETE per the dialect strategy., Translate a CapabilityRequest into parameterized SQL + positional args. (+4 more)

### Community 13 - "Community 13"
Cohesion: 0.09
Nodes (39): BaseModel, Policy-introspection tools: guardmcp_explain_policy + guardmcp_simulate_policy., register(), build_explanation(), build_policy_from_input(), classify_impact(), diff_policies(), _effective_mask_map() (+31 more)

### Community 14 - "Community 14"
Cohesion: 0.07
Nodes (31): Integration tests — full pipeline with mongomock-motor (no real MongoDB)., test_approval_required_then_approved(), _merge(), _merge_mask_fields(), Order-preserving union of two string lists (base first, child appended)., Merge mask_fields. If either is a dict, merge per-collection (union per     key), Merge `base` under `child` (child overrides). Scalars: child wins when set     t, _union() (+23 more)

### Community 15 - "Community 15"
Cohesion: 0.12
Nodes (8): MongoExecutor, True if at least one filter field has an index (or _id is filtered)., Raise ValueError if enforce_index_usage is True and filter has no index., Schema-driven type-marshal a filter at the Mongo boundary.          Fetches the, Return max_time_ms kwarg when configured., Canonical BSON type map for the filter marshaller (cached).          Delegates t, Action, Any

### Community 16 - "Community 16"
Cohesion: 0.10
Nodes (17): classify_cost(), Map normalized signals → a single coarse CostLevel.      Rules (in order):, _FakeMongoExecutor, _mongo_explain(), Feature 1 — Query Cost Estimation unit tests.  Covers the frozen CostEstimate mo, Returns a canned explain(executionStats) dict for find., test_adapter_estimate_delegates_to_plugin(), test_classify_collection_scan_is_high() (+9 more)

### Community 17 - "Community 17"
Cohesion: 0.16
Nodes (9): _affected_from_status(), Estimate a READ/COUNT via ``EXPLAIN (FORMAT JSON) <sql>`` (plan only —         N, EXPLAIN (FORMAT JSON) returns a single row whose one column holds the         JS, Parse asyncpg command status tag → affected row count.      'DELETE 5' → 5, 'UPD, Any, CapabilityRequest, CapabilityResult, CostEstimate (+1 more)

### Community 18 - "Community 18"
Cohesion: 0.11
Nodes (17): MongoPlugin, Backend safety validation. Re-raises tool-layer ToolError as         GuardValida, Estimate the cost of a find/aggregate via explain(executionStats),         norma, CostEstimate, Action, CapabilityRequest, CapabilityResult, CostEstimate (+9 more)

### Community 20 - "Community 20"
Cohesion: 0.14
Nodes (22): Capability, CapabilityRequest, CapabilityResult, CostEstimate, CostLevel, Query cost estimation — the FROZEN, backend-neutral public contract.  A plugin e, Normalized, backend-neutral cost estimate.      FROZEN public contract: this is, GuardExecutionError (+14 more)

### Community 21 - "Community 21"
Cohesion: 0.14
Nodes (16): AuditLogger, Drain the queue, stop the flusher, flush+close the handle (R-2)., Single writer: batch all queued records into one write + one fsync., Sign (ordered), write all lines, ONE flush, then resolve futures.         Chain, HMAC-SHA256 of (prev_hash + line). Returns hex digest., P-1: open the append handle once and reuse it across log() calls., AuditRecord, _expected_hmac() (+8 more)

### Community 22 - "Community 22"
Cohesion: 0.10
Nodes (19): AuditWriteError, Raised when an audit record cannot be persisted and fail_closed is set., Exception, GuardError, PluginError, PluginVersionError, Plugin registration/loading/version error., Base class for all GuardMCP errors. (+11 more)

### Community 23 - "Community 23"
Cohesion: 0.14
Nodes (17): GuardMCP plugin conformance kit.  Reusable contract checks that any :class:`~gua, assert_plugin_conformant(), check_plugin_conformance(), _pick_probe_capability(), Reusable conformance checks for GuardMCP DatabasePlugin implementations.  Third-, Strict variant: raise AssertionError listing all conformance failures.      Empt, Return a list of conformance failure strings (empty == conformant).      Args:, Conformance tests for the three builtin GuardMCP plugins.  These prove both (a) (+9 more)

### Community 24 - "Community 24"
Cohesion: 0.19
Nodes (13): neutralize(), #6: backend-neutral success accessors.      Map a backend-native success `data`, Action, Any, #6: backend-neutral success envelope — Mongo native results ALSO expose rows/aff, test_mongo_find_result_exposes_neutral(), test_neutralize_aggregate(), test_neutralize_count() (+5 more)

### Community 25 - "Community 25"
Cohesion: 0.10
Nodes (20): Audit Log, Development, Discovery, Environment Variables, Features, Governance (meta tools), GuardMCP, Human Approval Workflow (+12 more)

### Community 26 - "Community 26"
Cohesion: 0.16
Nodes (20): _build_pipeline(), _Loader, _mock_client(), Adversarial / user-centric behavior tests (scenarios that the YAML eval framewor, db_explain output is run through the audit masker (S-1). A masked field's     li, Sorting by a masked field still returns the field MASKED. The relative     ORDER, A CRITICAL op that requires approval but never gets resolved times out and     t, An empty/missing filter on a mutation escalates risk to CRITICAL (S-4),     so i (+12 more)

### Community 28 - "Community 28"
Cohesion: 0.13
Nodes (12): PrincipalResolver, Principal (agent identity) resolution seam (Risk #7).  The runtime currently obt, Resolve the authenticated agent id for a request.      `transport_hint` carries, Default resolver: always returns the operator-configured agent id.      Preserve, StaticPrincipalResolver, Path, Seam conformance tests (Risks #4, #5, #7, #8).  These assert the shipped single-, test_audit_logger_satisfies_protocol() (+4 more)

### Community 29 - "Community 29"
Cohesion: 0.14
Nodes (21): apply_mask(), build_type_map(), MongoSchemaCache — collaborator owning the schema-cache + type-map group.  Extra, _canonical_bson_type(), infer_schema(), Schema inference from sampled MongoDB documents. Returns a simplified type map:, Replace type of masked fields with 'masked' so AI knows the field exists but can, Map a RAW bson/python value to a canonical BSON type token.      Tokens: objectI (+13 more)

### Community 30 - "Community 30"
Cohesion: 0.06
Nodes (69): BaseSettings, default_audit_log_path(), default_state_dir(), Cross-platform, dependency-free resolution of per-user state/log dirs.  The audi, Return the OS-appropriate per-user state/log directory for ``app``.      - Windo, Default absolute audit log path: ``<state_dir>/audit.jsonl``., Resolve the configured audit path to a final ABSOLUTE path.      - If ``configur, resolve_audit_path() (+61 more)

### Community 31 - "Community 31"
Cohesion: 0.12
Nodes (5): _MinimalPlugin, Tests for the additive data-model fields and seams (Risks #1, #2, #10)., Concrete plugin overriding only the abstract methods — exercises the     default, test_database_plugin_begin_returns_none_by_default(), test_database_plugin_default_transaction_seam()

### Community 32 - "Community 32"
Cohesion: 0.20
Nodes (13): ConnectionRegistry, _factory(), _FakeClient, Backend-agnostic stub satisfying the ClosableClient protocol., _reg(), test_close_all_closes_clients(), test_default_active_is_default(), test_get_returns_entry() (+5 more)

### Community 33 - "Community 33"
Cohesion: 0.17
Nodes (10): _Bucket, RateLimiter, Token bucket rate limiter per agent.  Limits: max N requests per second per agen, Token bucket limiter. Thread-safe via asyncio.Lock per agent.      rps: sustaine, Return True if request is allowed, False if rate-limited.         No-op (always, Tests for the per-agent token-bucket rate limiter., test_burst_exhaustion(), test_disabled_when_rps_zero() (+2 more)

### Community 35 - "Community 35"
Cohesion: 0.12
Nodes (15): `api_version` and `CORE_API_MAJOR`, Architecture in one paragraph, CapabilityResult mapping, Deprecation policy, Internal — may change without notice, Optional driver dependency pattern, Public contract (semver-stable), Public vs internal at a glance (+7 more)

### Community 36 - "Community 36"
Cohesion: 0.16
Nodes (6): ApprovalStoreProtocol, AuditSinkProtocol, Durable surface for approval-request lifecycle.      A distributed impl (e.g. Re, Durable-write surface for the audit trail.      The shipped AuditLogger writes a, Any, RiskLevel

### Community 37 - "Community 37"
Cohesion: 0.17
Nodes (16): _asyncpg_dsn(), mongo_container(), mysql_container(), _mysql_plugin(), pg_container(), _pg_plugin(), Live-backend integration tests (testcontainers).  These tests prove the real dri, Build a real GuardPipeline over the live PG plugin via     CapabilityExecutorAda (+8 more)

### Community 38 - "Community 38"
Cohesion: 0.22
Nodes (4): _Model, Tests for all 8 grounding/security fixes in validation.py., TestJsonDict, TestSafeLimit

### Community 39 - "Community 39"
Cohesion: 0.22
Nodes (4): Fix 7: reject pipelines containing write or JS-execution stages.     Fix 8: erro, validate_pipeline_stages(), TestValidatePipelineStages, TestValidatePipelineStages

### Community 40 - "Community 40"
Cohesion: 0.34
Nodes (18): CollectionPolicy, GuardPipeline, Path, Policy, _call(), _client(), _pipeline(), _pol_dict() (+10 more)

### Community 41 - "Community 41"
Cohesion: 0.16
Nodes (8): _CountingCollection, _FakeClient, S-8: writes get a single attempt; reads get retried on transient errors., Minimal collection that raises AutoReconnect, counting each attempt., Same property, but isolated at the _execute_once boundary., test_execute_once_call_counts_via_monkeypatch(), test_read_action_retries_max_retries_plus_one(), test_write_action_attempted_exactly_once()

### Community 43 - "Community 43"
Cohesion: 0.20
Nodes (10): ErrorCode, err(), _infer_denied_code(), ok(), Success envelope. `data` carries the payload; `meta` is optional context., Error envelope with a stable machine-readable `code`., Map a pipeline 'denied' reason string to a specific ErrorCode., Any (+2 more)

### Community 44 - "Community 44"
Cohesion: 0.13
Nodes (8): DatabasePlugin, CapabilityRequest, CapabilityResult, _FakePlugin, test_capability_request_roundtrip(), test_capability_result_roundtrip(), test_concrete_plugin_instantiates(), test_database_plugin_is_abstract()

### Community 45 - "Community 45"
Cohesion: 0.11
Nodes (17): Approval Workflow, Audit, Deferred (apiVersion v2 / backlog), Field Masking, Governance Core (database-agnostic — imports zero plugin code), GuardMCP — Features, MCP Interface, Multi-Connection & Config (+9 more)

### Community 46 - "Community 46"
Cohesion: 0.20
Nodes (16): _call(), _FakeManager, _get_tool(), _make_client(), Tests for the MCP tool-design overhaul: dual names, envelopes, plan, capabilitie, Register real tools into a FastMCP and fetch the callable for `name`., _register_into_fake(), rw_pipeline() (+8 more)

### Community 47 - "Community 47"
Cohesion: 0.15
Nodes (25): Tamper-evident audit log (per-process HMAC chain).  Risk #5 — multi-writer attri, AuditLogger, datetime, Enum, ExpectedDecision, Eval runner: builds an isolated GuardPipeline per eval case and runs it.  Uses m, Backend Protocol — INTERNAL execution interface consumed by GuardPipeline.  NOT, ErrorCode (+17 more)

### Community 48 - "Community 48"
Cohesion: 0.24
Nodes (10): compile_predicate_to_filter(), #2 seam: lower a simple predicate AST to the existing Mongo-operator     `filter, Any, #2 seam: structured predicate AST field + lowering to the Mongo-operator filter, test_lower_and(), test_lower_leaf_eq_default(), test_lower_leaf_operators(), test_lower_or() (+2 more)

### Community 49 - "Community 49"
Cohesion: 0.20
Nodes (7): True for transient network/connection errors worth retrying., Backend-specific error sanitization (delegated to by core pipeline)., Fix 6: return a generic, actionable message instead of raw MongoDB internals., sanitize_mongo_error(), Exception, Exception, TestSanitizeMongoError

### Community 50 - "Community 50"
Cohesion: 0.24
Nodes (7): A backend whose supported set excludes AGGREGATE makes _capability_check     ret, test_ag5_unsupported_capability_returns_envelope(), test_unsupported_capability_helper(), #7: capability manifests read from plugin CLASSES without instantiation or conne, _registry(), test_registry_manifest_single(), test_registry_manifests_no_instantiation()

### Community 51 - "Community 51"
Cohesion: 0.16
Nodes (10): Backend, Formal interface for GuardMCP database backends., Execute an action against the backend. Raises ValueError for unsupported actions, Return all collection/table names in the active database., Infer field types from a sample of documents. Masked fields shown as 'masked'., Return index metadata for the collection., Return database names and sizes., Raise ValueError if filter has no covering index and enforcement is enabled. (+2 more)

### Community 52 - "Community 52"
Cohesion: 0.31
Nodes (3): has_dangerous_operators(), True if value contains any banned operator key at any nesting depth., TestHasDangerousOperators

### Community 53 - "Community 53"
Cohesion: 0.17
Nodes (18): _indexes_sql(), _list_databases_sql(), _list_resources_sql(), quote_ident(), PURE translation: CapabilityRequest -> (sql, args) for MySQL.  This is now a THI, Translate a CapabilityRequest into parameterized SQL + positional args.      Rai, Validate a (possibly schema-qualified) identifier and backtick-quote it.      Ea, _schema_sql() (+10 more)

### Community 54 - "Community 54"
Cohesion: 0.18
Nodes (10): _FakeConn, _FakePool, test_ddl_create_via_execute_path_rejected(), test_execute_count_sets_scalar(), test_execute_insert_reports_affected(), test_execute_read_returns_rows(), test_execute_validates_before_touching_pool(), test_health_true_on_success() (+2 more)

### Community 56 - "Community 56"
Cohesion: 0.33
Nodes (7): _build_pipeline(), Minimal registry: every switch to a known name succeeds., _read_audit(), _StubRegistry, test_empty_allowlist_permits_all(), test_switch_allowed_when_in_allowlist(), test_switch_denied_when_not_in_allowlist()

### Community 57 - "Community 57"
Cohesion: 0.23
Nodes (4): AssertionEngine, Dot-notation field access: 'contact.email' → doc['contact']['email']., ExpectedResult, Any

### Community 58 - "Community 58"
Cohesion: 0.36
Nodes (9): _create(), Tests for the human-in-the-loop approval store., test_create_get_list_pending(), test_prune_removes_resolved(), test_prune_shrinks_store_and_events_in_lockstep(), test_resolve_approved(), test_resolve_denied(), test_shutdown_denies_all_pending() (+1 more)

### Community 59 - "Community 59"
Cohesion: 0.15
Nodes (11): PostgresPlugin, DELETE has no RETURNING → affected must come from the status tag, not fetch()., test_aggregate_and_ddl_not_supported(), test_cross_resource_refs_default_empty(), test_cross_resource_refs_from_joins_option(), test_delete_reports_affected_via_status(), test_health_false_without_pool(), test_is_database_plugin_instance() (+3 more)

### Community 60 - "Community 60"
Cohesion: 0.31
Nodes (17): Dialect-parameterized translator. ``translate(req)`` -> Translated., SqlTranslator, _catalog(), _make_dialect(), Tests for the shared SqlTranslator core with a fake dialect.  These exercise the, _req(), test_catalog_dispatch(), test_delete_one_ctid_vs_limit() (+9 more)

### Community 61 - "Community 61"
Cohesion: 0.20
Nodes (9): Adding a backend plugin, Code layout, Code quality, Contributing to GuardMCP, Dev setup, Live-backend integration tests, PR expectations, Running the gates (+1 more)

### Community 62 - "Community 62"
Cohesion: 0.06
Nodes (53): A filter value could not be coerced to a field's known BSON type.      Unlike a, TypeMarshalError, _coerce_date(), _coerce_decimal(), _coerce_int(), _coerce_objectid(), _coerce_objectid_best_effort(), _marshal_field_value() (+45 more)

### Community 63 - "Community 63"
Cohesion: 0.33
Nodes (3): extract_pipeline_collections(), Return every foreign collection name referenced by an aggregation pipeline,, TestExtractPipelineCollections

### Community 64 - "Community 64"
Cohesion: 0.22
Nodes (3): audit_logger(), mock_mongo_client(), Mongomock-based client — no real MongoDB needed.

### Community 65 - "Community 65"
Cohesion: 0.21
Nodes (15): _mysql_first_table(), normalize_mysql_explain(), normalize_postgres_explain(), _pg_top_plan(), Shared SQL cost normalization for the relational plugins.  Postgres (``EXPLAIN (, Locate the primary table node in a MySQL EXPLAIN query_block.      MySQL nests t, Normalize a Postgres ``EXPLAIN (FORMAT JSON)`` payload → CostEstimate.      The, Normalize a MySQL ``EXPLAIN FORMAT=JSON`` payload → CostEstimate.      Reads ``q (+7 more)

### Community 66 - "Community 66"
Cohesion: 0.25
Nodes (7): Active-connection isolation (Risk #8), Audit attribution under multiple writers (Risk #5), Backend interfaces: public vs internal (Risk #9), Governance-state seams (Risk #4), GuardMCP Architecture, Principal (agent identity) resolution (Risk #7), Request / result flow

### Community 67 - "Community 67"
Cohesion: 0.32
Nodes (4): find_masked_field_references(), Return the set of masked field names referenced as aggregation field paths     (, Any, TestFindMaskedFieldReferences

### Community 68 - "Community 68"
Cohesion: 0.23
Nodes (6): MongoSchemaCache, Return (canonical display schema, canonical type_map) for a collection., Canonical-token display schema. Polymorphic fields (absent from the         sing, Canonical BSON type map for the filter marshaller (cached)., MongoClient, MongoClient

### Community 69 - "Community 69"
Cohesion: 0.31
Nodes (4): MongoDB-specific validation / guard logic.  Moved out of core/validation.py in P, Fix 2: raise ToolError if filter is not a dict or contains dangerous operators., validate_filter(), TestValidateFilter

### Community 70 - "Community 70"
Cohesion: 0.22
Nodes (8): _is_unscoped(), True if the filter targets the whole collection (empty or missing)., Classify the risk of an action.          S-4 scope escalation: when `params` is, ADDITIVE, OPT-IN cost-aware escalation. Returns max(base, cost-floor):         a, Action, Any, CostEstimate, RiskLevel

### Community 71 - "Community 71"
Cohesion: 0.29
Nodes (6): Hardening Checklist, Known Limitations, Reporting a Vulnerability, Security Model, Security Policy, Supported Versions

### Community 72 - "Community 72"
Cohesion: 0.29
Nodes (3): Tests for aggregation-pipeline guards: cross-collection, masked-field, stage all, P3: _guard_aggregation now reaches MongoDB pipeline knowledge THROUGH the     ac, TestGuardAggregationViaExecutorDelegation

### Community 73 - "Community 73"
Cohesion: 0.24
Nodes (11): _descend(), _nest(), Control: a masked field within the depth limit IS masked., EC-3 FIXED: a masked field nested at depth 12 (was > old _MAX_DEPTH==10)     is, EC-3 FIXED: same, via the ResultTransformer (find/aggregate path)., EC-3 evidence (now SECURE): the deep ssn never comes back in clear-text., Return a doc with `leaf` wrapped `depth` levels deep under key 'lvl'., test_ec3_deep_masked_field_is_masked_fieldmasker() (+3 more)

### Community 75 - "Community 75"
Cohesion: 0.20
Nodes (9): Audit log default moved to a platform per-user state dir (minor behavior change), BREAKING — empty `collections.allow` is now DENY-ALL (AD-1, CRITICAL), Changed, Changelog, Masking depth-limit leak fixed (EC-3, HIGH), Plugin architecture refactor (P1–P6, S-4), Security fixes, Security hardening (CR-1..3, H1..3, S-1/2/3/5/8, P-1, R-1/2) (+1 more)

### Community 76 - "Community 76"
Cohesion: 0.31
Nodes (10): QuoteIdent, cross_resource_refs(), Shared SQL request validation for the relational plugins.  PostgreSQL and MySQL, Raise GuardValidationError if the request is unsafe for this backend., Return foreign resources referenced by the request.      Requests are structured, _validate_filter(), _validate_keys(), validate_request() (+2 more)

### Community 78 - "Community 78"
Cohesion: 0.60
Nodes (4): _build_success(), S-1: EXPLAIN plan masking via GuardPipeline._build_success., test_explain_masks_filter_literals(), test_explain_without_mask_fields_unchanged()

### Community 105 - "Community 105"
Cohesion: 0.24
Nodes (5): Return the _hmac of the last record on disk, or genesis if none., log_event(), Emit ONE structured log line to stderr if `level` meets the threshold., Path, TestLogEvent

### Community 106 - "Community 106"
Cohesion: 0.23
Nodes (5): ClientFactory, ConnectionEntry, ConnectionRegistry, Switch active connection. Returns False if name not registered., test_active_connection_isolated_across_contexts()

### Community 107 - "Community 107"
Cohesion: 0.22
Nodes (5): Explain a find in ``executionStats`` mode (planner + execution metrics,, Explain an aggregate in ``executionStats`` mode (no result materialized)., _bson_to_json(), Recursively convert BSON types to JSON-serializable equivalents., Any

### Community 108 - "Community 108"
Cohesion: 0.24
Nodes (7): Shared SQL translation core for relational plugins (PostgreSQL, MySQL, ...).  Th, Dialect, Dialect-parameterized, PURE translation: CapabilityRequest -> (sql, args).  This, Validate a (possibly schema-qualified) identifier; return its parts.      Each d, Captures the per-backend deltas the shared translator needs.      ``name`` is us, validate_ident(), test_validate_ident_returns_parts()

### Community 109 - "Community 109"
Cohesion: 0.31
Nodes (9): _execution_stats(), normalize_mongo_explain(), _plan_stages(), Return the winningPlan, tolerating both find and aggregate shapes., Flatten the (possibly nested) winningPlan into its stage names., Normalize a raw Mongo explain(executionStats) dict → CostEstimate.      Extracts, _winning_plan(), Any (+1 more)

### Community 110 - "Community 110"
Cohesion: 0.10
Nodes (9): ABC, DatabasePlugin, Public, capability-based contract for a database backend plugin., Return {name, api_version, supported, dialect_features} from class         attrs, Begin a transaction and return its tx_id, or None if unsupported., Commit the transaction identified by tx_id. No-op by default., Roll back the transaction identified by tx_id. No-op by default., Connection registry for switch-connection support. Each named connection maps to (+1 more)

### Community 111 - "Community 111"
Cohesion: 0.29
Nodes (7): _make_policy(), pipeline_with(), S-3: field allow-list enforced end-to-end through GuardPipeline.run (FIND)., Minimal policy loader exposing the single .get(agent) used by pipeline., _StubLoader, test_field_allow_drops_disallowed_fields(), test_field_allow_with_masking()

### Community 113 - "Community 113"
Cohesion: 0.50
Nodes (3): raise_guard_error(), Fix 8: always include what IS allowed so AI can self-correct on retry., TestRaiseGuardError

### Community 114 - "Community 114"
Cohesion: 0.39
Nodes (8): _doc(), #10: first-class dotted mask paths — "contact.email" is path-specific while a ba, test_bare_name_masks_any_depth_backcompat(), test_dotted_path_is_specific(), test_mixed_bare_and_dotted(), test_per_collection_dict_with_dotted(), test_transformer_bare_backcompat(), test_transformer_dotted_path_specific()

### Community 115 - "Community 115"
Cohesion: 0.33
Nodes (6): build_approval_app(), DecisionPayload, Build the approval REST API.      When api_token is set, all requests must inclu, ApprovalRequest, FastAPI, ApprovalStore

### Community 116 - "Community 116"
Cohesion: 0.33
Nodes (3): Effective mask fields for a collection. Flat list → global (same list         fo, Cached single-pass field-allow + mask transformer (H3/M1)., Cached mask-only masker for audit-param scrubbing + explain (M1).

### Community 118 - "Community 118"
Cohesion: 0.50
Nodes (4): Register all meta tools onto ``mcp``., register(), FastMCP, ToolContext

### Community 119 - "Community 119"
Cohesion: 0.22
Nodes (5): RateLimiterProtocol, Per-agent admission control.      A distributed impl (shared token bucket in Red, Protocol, ClosableClient, Minimal contract a connection client must satisfy.

### Community 123 - "Community 123"
Cohesion: 0.53
Nodes (5): P-1/R-2: AuditLogger reuses one persistent append handle; aclose resets it., _record(), test_aclose_resets_handle_to_none(), test_handle_reused_across_log_calls(), test_log_after_aclose_reopens_and_appends()

## Knowledge Gaps
- **144 isolated node(s):** `ApprovalStore`, `Any`, `Capability`, `Action`, `Any` (+139 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **12 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Action` connect `Community 47` to `Community 0`, `Community 3`, `Community 4`, `Community 6`, `Community 9`, `Community 13`, `Community 14`, `Community 20`, `Community 26`, `Community 29`, `Community 30`, `Community 31`, `Community 39`, `Community 41`, `Community 46`, `Community 63`, `Community 67`, `Community 72`, `Community 111`?**
  _High betweenness centrality (0.081) - this node is a cross-community bridge._
- **Why does `AuditLogger` connect `Community 21` to `Community 64`, `Community 0`, `Community 37`, `Community 6`, `Community 7`, `Community 40`, `Community 105`, `Community 9`, `Community 10`, `Community 46`, `Community 47`, `Community 117`, `Community 56`, `Community 26`, `Community 123`, `Community 28`, `Community 30`?**
  _High betweenness centrality (0.071) - this node is a cross-community bridge._
- **Why does `MongoExecutor` connect `Community 15` to `Community 0`, `Community 67`, `Community 68`, `Community 40`, `Community 9`, `Community 42`, `Community 107`, `Community 41`, `Community 46`, `Community 47`, `Community 49`, `Community 18`, `Community 20`, `Community 26`, `Community 29`, `Community 30`, `Community 63`?**
  _High betweenness centrality (0.064) - this node is a cross-community bridge._
- **Are the 24 inferred relationships involving `MongoExecutor` (e.g. with `AuditLogger` and `_Loader`) actually correct?**
  _`MongoExecutor` has 24 INFERRED edges - model-reasoned connections that need verification._
- **Are the 48 inferred relationships involving `AuditLogger` (e.g. with `AuditLogger` and `_Loader`) actually correct?**
  _`AuditLogger` has 48 INFERRED edges - model-reasoned connections that need verification._
- **Are the 33 inferred relationships involving `Action` (e.g. with `AuditLogger` and `_Loader`) actually correct?**
  _`Action` has 33 INFERRED edges - model-reasoned connections that need verification._
- **Are the 24 inferred relationships involving `GuardPipeline` (e.g. with `AuditLogger` and `_Loader`) actually correct?**
  _`GuardPipeline` has 24 INFERRED edges - model-reasoned connections that need verification._