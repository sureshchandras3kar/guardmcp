# Graph Report - guardmcp  (2026-06-30)

## Corpus Check
- 167 files · ~86,495 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2093 nodes · 4451 edges · 134 communities (121 shown, 13 thin omitted)
- Extraction: 82% EXTRACTED · 18% INFERRED · 0% AMBIGUOUS · INFERRED: 818 edges (avg confidence: 0.63)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `906d5c26`
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
- [[_COMMUNITY_Community 117|Community 117]]
- [[_COMMUNITY_Community 119|Community 119]]
- [[_COMMUNITY_Community 120|Community 120]]
- [[_COMMUNITY_Community 121|Community 121]]
- [[_COMMUNITY_Community 123|Community 123]]
- [[_COMMUNITY_Community 124|Community 124]]
- [[_COMMUNITY_Community 127|Community 127]]
- [[_COMMUNITY_Community 128|Community 128]]
- [[_COMMUNITY_Community 131|Community 131]]
- [[_COMMUNITY_Community 132|Community 132]]
- [[_COMMUNITY_Community 133|Community 133]]
- [[_COMMUNITY_Community 134|Community 134]]
- [[_COMMUNITY_Community 135|Community 135]]
- [[_COMMUNITY_Community 136|Community 136]]
- [[_COMMUNITY_Community 137|Community 137]]
- [[_COMMUNITY_Community 138|Community 138]]
- [[_COMMUNITY_Community 140|Community 140]]
- [[_COMMUNITY_Community 141|Community 141]]

## God Nodes (most connected - your core abstractions)
1. `MongoExecutor` - 65 edges
2. `AuditLogger` - 63 edges
3. `Action` - 54 edges
4. `GuardPipeline` - 51 edges
5. `GuardValidationError` - 43 edges
6. `DatabasePlugin` - 43 edges
7. `PolicyEngine` - 41 edges
8. `FakePlugin` - 41 edges
9. `CapabilityRequest` - 40 edges
10. `Capability` - 39 edges

## Surprising Connections (you probably didn't know these)
- `audit_logger()` --calls--> `AuditLogger`  [INFERRED]
  tests/conftest.py → src/guardmcp/core/audit/logger.py
- `test_fail_closed_raises_on_write_failure()` --calls--> `AuditLogger`  [INFERRED]
  tests/unit/test_audit_logger.py → src/guardmcp/core/audit/logger.py
- `test_fail_open_does_not_raise()` --calls--> `AuditLogger`  [INFERRED]
  tests/unit/test_audit_logger.py → src/guardmcp/core/audit/logger.py
- `test_rate_limiter_satisfies_protocol()` --calls--> `RateLimiter`  [INFERRED]
  tests/unit/test_seams.py → src/guardmcp/core/ratelimit/limiter.py
- `test_adapter_estimate_delegates_to_plugin()` --calls--> `CapabilityExecutorAdapter`  [INFERRED]
  tests/unit/test_cost_estimate.py → src/guardmcp/core/registry/adapter.py

## Import Cycles
- 1-file cycle: `src/guardmcp/api/approval.py -> src/guardmcp/api/approval.py`
- 1-file cycle: `src/guardmcp/plugins/mongodb/marshal.py -> src/guardmcp/plugins/mongodb/marshal.py`
- 1-file cycle: `src/guardmcp/server/tools/__init__.py -> src/guardmcp/server/tools/__init__.py`
- 1-file cycle: `src/guardmcp/server/tools/meta/__init__.py -> src/guardmcp/server/tools/meta/__init__.py`

## Communities (134 total, 13 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.07
Nodes (23): PolicyLoader, Sorted list of *.yaml/*.yml files when _path is a directory.          Sorting ma, Apply the SAME doc shape parsing (list / {agents:[...]} / single)., Max mtime to watch. For a directory: the dir's own mtime (catches         add/re, Load (or reload) policies from disk. Called at startup and by hot-reload., Start background asyncio task that polls for policy file changes., Cancel the background watcher task., Policy (+15 more)

### Community 1 - "Community 1"
Cohesion: 0.07
Nodes (30): ApprovalStoreProtocol, AuditSinkProtocol, EvalResult, GuardPipeline, Return executor for the active connection (or default)., Run policy + risk check. Does NOT execute or audit.          `trace` (optional):, #1 seam: capability-native entry point.          Maps a Capability → a represent, Deny if the policy has a temporal window and now is outside it. (+22 more)

### Community 3 - "Community 3"
Cohesion: 0.06
Nodes (57): Context, _coerce_none_sentinels(), _parse_json_or_pass(), Database-agnostic grounding/security helpers.  MongoDB-specific validation (oper, Coerce a JSON-encoded string to dict/list. Non-strings pass through., Map '', 'null', 'none', 'undefined' → None for optional dict params., register(), GuardMCP meta tools (single-named, no db_/mongodb_ alias).  The former monolithi (+49 more)

### Community 4 - "Community 4"
Cohesion: 0.18
Nodes (5): AuditRecord, #8 + #9 tests: structured logging, trace-id correlation, explicit error codes., TestAuditTraceId, TestLogEvent, TestTraceId

### Community 5 - "Community 5"
Cohesion: 0.11
Nodes (15): FieldMasker, #10: split mask entries into bare names (match a key at ANY depth, the     histo, Recursively mask sensitive fields. Bare names match a key at any         depth;, H3: single-pass field allow-list + masking. Replaces two separate full     trave, ResultTransformer, _split_mask_entries(), Effective mask fields for a collection. Flat list → global (same list         fo, Cached single-pass field-allow + mask transformer (H3/M1). (+7 more)

### Community 6 - "Community 6"
Cohesion: 0.08
Nodes (33): CapabilityExecutorAdapter, Delegate cost estimation to the plugin through the same Backend         boundary, Generic safe error message — never leaks backend internals., Presents a DatabasePlugin behind the legacy Backend interface the     pipeline c, Action, Any, Capability, CapabilityRequest (+25 more)

### Community 7 - "Community 7"
Cohesion: 0.14
Nodes (12): from_pipeline_result(), ok(), Success envelope. `data` carries the payload; `meta` is optional context., Map a GuardPipeline result dict to the standard envelope.      Pipeline shapes:, Any, test_from_pipeline_result_denied_collection(), test_from_pipeline_result_denied_readonly(), test_from_pipeline_result_error_backend() (+4 more)

### Community 8 - "Community 8"
Cohesion: 0.05
Nodes (41): Approval REST API, Architecture Challenges & Improvements, Deliverable 10: Async Performance Considerations, Deliverable 11: Docker Deployment Design, Deliverable 12: Testing Strategy, Deliverable 13: API Contracts, Deliverable 14: Example Policy Files, Deliverable 15: Open-Source Roadmap (+33 more)

### Community 9 - "Community 9"
Cohesion: 0.17
Nodes (18): ApprovalStore, EvalCase, EvalCaseResult, InlinePolicy, _build_mock_client(), _build_policy(), _EvalApprovalStore, _InlineLoader (+10 more)

### Community 10 - "Community 10"
Cohesion: 0.18
Nodes (15): Tamper-evident audit log (per-process HMAC chain).  Risk #5 — multi-writer attri, register(), current_traceparent(), _format(), get_trace_id(), log_event(), new_span_id(), Dependency-free structured logging + trace-id correlation.  Replaces ad-hoc `pri (+7 more)

### Community 11 - "Community 11"
Cohesion: 0.17
Nodes (19): _indexes_sql(), _list_databases_sql(), _list_resources_sql(), quote_ident(), PURE translation: CapabilityRequest -> (sql, args) for PostgreSQL.  This is now, Translate a CapabilityRequest into parameterized SQL + positional args.      Rai, Validate a (possibly schema-qualified) identifier and return it verbatim.      E, _schema_from_options() (+11 more)

### Community 12 - "Community 12"
Cohesion: 0.21
Nodes (9): _ArgCounter, Issues placeholders (dialect-specific) and accumulates the bound values., Build a parameterized WHERE clause (without the WHERE keyword).          Returns, Single-row insert from documents[0], or UPDATE if filter+update present., Translate a CapabilityRequest into parameterized SQL + positional args., Result of a pure translation: parameterized SQL plus positional args., Translated, Any (+1 more)

### Community 13 - "Community 13"
Cohesion: 0.09
Nodes (40): BaseModel, Policy-introspection tools: guardmcp_explain_policy + guardmcp_simulate_policy., register(), build_explanation(), build_policy_from_input(), classify_impact(), diff_policies(), _effective_mask_map() (+32 more)

### Community 14 - "Community 14"
Cohesion: 0.05
Nodes (57): Integration tests — full pipeline with mongomock-motor (no real MongoDB)., test_approval_required_then_approved(), _merge(), _merge_mask_fields(), Order-preserving union of two string lists (base first, child appended)., Merge mask_fields. If either is a dict, merge per-collection (union per     key), Merge `base` under `child` (child overrides). Scalars: child wins when set     t, _union() (+49 more)

### Community 15 - "Community 15"
Cohesion: 0.12
Nodes (8): MongoExecutor, True if at least one filter field has an index (or _id is filtered)., Raise ValueError if enforce_index_usage is True and filter has no index., Schema-driven type-marshal a filter at the Mongo boundary.          Fetches the, Return max_time_ms kwarg when configured., Canonical BSON type map for the filter marshaller (cached).          Delegates t, Action, Any

### Community 16 - "Community 16"
Cohesion: 0.18
Nodes (7): _mongo_explain(), Feature 1 — Query Cost Estimation unit tests.  Covers the frozen CostEstimate mo, test_adapter_estimate_delegates_to_plugin(), test_mongo_collscan_normalizes_to_high(), test_mongo_does_not_leak_raw_plan(), test_mongo_plugin_estimate_collscan(), test_mongo_plugin_estimate_failure_is_unknown()

### Community 17 - "Community 17"
Cohesion: 0.16
Nodes (9): _affected_from_status(), Estimate a READ/COUNT via ``EXPLAIN (FORMAT JSON) <sql>`` (plan only —         N, EXPLAIN (FORMAT JSON) returns a single row whose one column holds the         JS, Parse asyncpg command status tag → affected row count.      'DELETE 5' → 5, 'UPD, Any, CapabilityRequest, CapabilityResult, CostEstimate (+1 more)

### Community 18 - "Community 18"
Cohesion: 0.11
Nodes (18): MongoPlugin, Backend safety validation. Re-raises tool-layer ToolError as         GuardValida, Estimate the cost of a find/aggregate via explain(executionStats),         norma, CostEstimate, Action, CapabilityRequest, CapabilityResult, CostEstimate (+10 more)

### Community 20 - "Community 20"
Cohesion: 0.08
Nodes (33): ABC, Reusable conformance checks for GuardMCP DatabasePlugin implementations.  Third-, Capability, CapabilityRequest, CapabilityResult, CostEstimate, CostLevel, Query cost estimation — the FROZEN, backend-neutral public contract.  A plugin e (+25 more)

### Community 21 - "Community 21"
Cohesion: 0.13
Nodes (12): AuditLogger, Drain the queue, stop the flusher, flush+close the handle (R-2)., Single writer: batch all queued records into one write + one fsync., Return the _hmac of the last record on disk, or genesis if none., AuditRecord, Path, Path, Seam conformance tests (Risks #4, #5, #7, #8).  These assert the shipped single- (+4 more)

### Community 22 - "Community 22"
Cohesion: 0.24
Nodes (9): PluginError, PluginVersionError, A filter value could not be coerced to a field's known BSON type.      Unlike a, Plugin registration/loading/version error., _check_version(), Raise PluginVersionError if the plugin's api_version major != CORE_API_MAJOR., Register a plugin class after validating its API version., Instantiate a registered plugin by name. (+1 more)

### Community 23 - "Community 23"
Cohesion: 0.14
Nodes (16): GuardMCP plugin conformance kit.  Reusable contract checks that any :class:`~gua, assert_plugin_conformant(), check_plugin_conformance(), _pick_probe_capability(), Strict variant: raise AssertionError listing all conformance failures.      Empt, Return a list of conformance failure strings (empty == conformant).      Args:, Conformance tests for the three builtin GuardMCP plugins.  These prove both (a), SQL-style plugins must reject an injection-style resource identifier. (+8 more)

### Community 24 - "Community 24"
Cohesion: 0.16
Nodes (26): _builtin_registry(), _check_h1(), _cmd_audit_verify(), _cmd_capability_inspect(), _cmd_config_validate(), _cmd_doctor(), _cmd_plugin_list(), _cmd_plugin_validate() (+18 more)

### Community 25 - "Community 25"
Cohesion: 0.13
Nodes (14): Audit log, CLI / operations, Configuration, Development, Features (overview), GuardMCP, License, MCP tools (44) (+6 more)

### Community 26 - "Community 26"
Cohesion: 0.10
Nodes (34): _build_pipeline(), _descend(), _mock_client(), _nest(), Adversarial / user-centric behavior tests (scenarios that the YAML eval framewor, Control: a masked field within the depth limit IS masked., EC-3 FIXED: a masked field nested at depth 12 (was > old _MAX_DEPTH==10)     is, EC-3 FIXED: same, via the ResultTransformer (find/aggregate path). (+26 more)

### Community 28 - "Community 28"
Cohesion: 0.20
Nodes (6): PrincipalResolver, Principal (agent identity) resolution seam (Risk #7).  The runtime currently obt, Resolve the authenticated agent id for a request.      `transport_hint` carries, Default resolver: always returns the operator-configured agent id.      Preserve, StaticPrincipalResolver, test_static_principal_resolver_returns_configured_agent()

### Community 29 - "Community 29"
Cohesion: 0.12
Nodes (12): MongoClient, apply_mask(), build_type_map(), MongoSchemaCache — collaborator owning the schema-cache + type-map group.  Extra, _canonical_bson_type(), Schema inference from sampled MongoDB documents. Returns a simplified type map:, Replace type of masked fields with 'masked' so AI knows the field exists but can, Map a RAW bson/python value to a canonical BSON type token.      Tokens: objectI (+4 more)

### Community 30 - "Community 30"
Cohesion: 0.14
Nodes (21): default_audit_log_path(), default_state_dir(), Cross-platform, dependency-free resolution of per-user state/log dirs.  The audi, Return the OS-appropriate per-user state/log directory for ``app``.      - Windo, Default absolute audit log path: ``<state_dir>/audit.jsonl``., Resolve the configured audit path to a final ABSOLUTE path.      - If ``configur, resolve_audit_path(), Path (+13 more)

### Community 31 - "Community 31"
Cohesion: 0.12
Nodes (5): _MinimalPlugin, Tests for the additive data-model fields and seams (Risks #1, #2, #10)., Concrete plugin overriding only the abstract methods — exercises the     default, test_database_plugin_begin_returns_none_by_default(), test_database_plugin_default_transaction_seam()

### Community 32 - "Community 32"
Cohesion: 0.27
Nodes (10): infer_schema(), Infer field types from a sample of documents.     Returns {field: type} or {fiel, test_apply_mask_empty_list(), test_apply_mask_hides_type(), test_infer_basic_types(), test_infer_empty_docs(), test_infer_merges_fields_across_docs(), test_infer_mixed_types() (+2 more)

### Community 33 - "Community 33"
Cohesion: 0.17
Nodes (10): _Bucket, RateLimiter, Token bucket rate limiter per agent.  Limits: max N requests per second per agen, Token bucket limiter. Thread-safe via asyncio.Lock per agent.      rps: sustaine, Return True if request is allowed, False if rate-limited.         No-op (always, Tests for the per-agent token-bucket rate limiter., test_burst_exhaustion(), test_disabled_when_rps_zero() (+2 more)

### Community 35 - "Community 35"
Cohesion: 0.11
Nodes (18): `api_version` and `CORE_API_MAJOR`, Architecture in one paragraph, CapabilityRequest shape, CapabilityResult examples, CapabilityResult mapping, Deprecation policy, Error handling, Internal — may change without notice (+10 more)

### Community 36 - "Community 36"
Cohesion: 0.10
Nodes (11): ApprovalStoreProtocol, AuditSinkProtocol, RateLimiterProtocol, Durable surface for approval-request lifecycle.      A distributed impl (e.g. Re, Per-agent admission control.      A distributed impl (shared token bucket in Red, Durable-write surface for the audit trail.      The shipped AuditLogger writes a, Protocol, ClosableClient (+3 more)

### Community 37 - "Community 37"
Cohesion: 0.07
Nodes (34): ClientFactory, _asyncpg_dsn(), mongo_container(), mysql_container(), _mysql_plugin(), pg_container(), _pg_plugin(), Live-backend integration tests (testcontainers).  These tests prove the real dri (+26 more)

### Community 38 - "Community 38"
Cohesion: 0.22
Nodes (4): _Model, Tests for all 8 grounding/security fixes in validation.py., TestJsonDict, TestSafeLimit

### Community 39 - "Community 39"
Cohesion: 0.22
Nodes (4): Fix 7: reject pipelines containing write or JS-execution stages.     Fix 8: erro, validate_pipeline_stages(), TestValidatePipelineStages, TestValidatePipelineStages

### Community 40 - "Community 40"
Cohesion: 0.22
Nodes (5): PluginRegistry, Registry of DatabasePlugin classes keyed by their declared ``name``., Discover plugins advertised via the ``guardmcp.plugins`` entry-point group., #7: return a registered plugin's manifest from its CLASS, WITHOUT         instan, #7: manifests for every registered plugin, keyed by name. Read from         clas

### Community 41 - "Community 41"
Cohesion: 0.16
Nodes (8): _CountingCollection, _FakeClient, S-8: writes get a single attempt; reads get retried on transient errors., Minimal collection that raises AutoReconnect, counting each attempt., Same property, but isolated at the _execute_once boundary., test_execute_once_call_counts_via_monkeypatch(), test_read_action_retries_max_retries_plus_one(), test_write_action_attempted_exactly_once()

### Community 42 - "Community 42"
Cohesion: 0.33
Nodes (9): _expected_hmac(), Tests for the tamper-evident audit log (HMAC chain, restart seeding, fail-closed, _read_records(), test_chain_seeds_across_restart(), test_chain_verifies(), test_fail_closed_raises_on_write_failure(), test_fail_open_does_not_raise(), test_hmac_absent_when_no_secret() (+1 more)

### Community 43 - "Community 43"
Cohesion: 0.22
Nodes (7): ErrorCode, _infer_denied_code(), Map a pipeline 'denied' reason string to a specific ErrorCode., _FakeManager, _register_into_fake(), test_annotations_applied_or_skipped(), test_both_db_and_mongodb_names_registered()

### Community 44 - "Community 44"
Cohesion: 0.13
Nodes (7): DatabasePlugin, CapabilityRequest, _FakePlugin, test_capability_request_roundtrip(), test_capability_result_roundtrip(), test_concrete_plugin_instantiates(), test_database_plugin_is_abstract()

### Community 45 - "Community 45"
Cohesion: 0.11
Nodes (26): Offline verification of the tamper-evident audit HMAC chain.  This shares ONE im, HMAC-SHA256 of ``prev_hash + base_line`` → hex digest.      Identical math to ``, Outcome of verifying an audit-log file., 0 only when the whole chain verifies; distinct codes otherwise., A single human-readable summary line (success OR failure).          Used by ``gu, Recompute the HMAC chain from genesis and verify each record's ``_hmac``.      R, sign_record(), verify_chain() (+18 more)

### Community 46 - "Community 46"
Cohesion: 0.22
Nodes (19): _call(), _get_tool(), _make_client(), Tests for the MCP tool-design overhaul: dual names, envelopes, plan, capabilitie, Register real tools into a FastMCP and fetch the callable for `name`., A readonly policy exposes only read actions (engine-derived)., Engine-consistency: a temporally-expired policy → evaluate() DENIES every     ac, No-policy branch: top-level keys present, mode null, collections empty. (+11 more)

### Community 47 - "Community 47"
Cohesion: 0.13
Nodes (26): AuditLogger, Enum, ExpectedDecision, _Loader, Backend, Backend Protocol — INTERNAL execution interface consumed by GuardPipeline.  NOT, Formal interface for GuardMCP database backends., Return all collection/table names in the active database. (+18 more)

### Community 48 - "Community 48"
Cohesion: 0.24
Nodes (10): compile_predicate_to_filter(), #2 seam: lower a simple predicate AST to the existing Mongo-operator     `filter, Any, #2 seam: structured predicate AST field + lowering to the Mongo-operator filter, test_lower_and(), test_lower_leaf_eq_default(), test_lower_leaf_operators(), test_lower_or() (+2 more)

### Community 49 - "Community 49"
Cohesion: 0.20
Nodes (7): True for transient network/connection errors worth retrying., Backend-specific error sanitization (delegated to by core pipeline)., Fix 6: return a generic, actionable message instead of raw MongoDB internals., sanitize_mongo_error(), Exception, Exception, TestSanitizeMongoError

### Community 50 - "Community 50"
Cohesion: 0.32
Nodes (5): test_unsupported_capability_helper(), #7: capability manifests read from plugin CLASSES without instantiation or conne, _registry(), test_registry_manifest_single(), test_registry_manifests_no_instantiation()

### Community 51 - "Community 51"
Cohesion: 0.17
Nodes (7): Execute an action against the backend. Raises ValueError for unsupported actions, Infer field types from a sample of documents. Masked fields shown as 'masked'., Return index metadata for the collection., Return database names and sizes., Raise ValueError if filter has no covering index and enforcement is enabled., Action, Any

### Community 52 - "Community 52"
Cohesion: 0.31
Nodes (3): has_dangerous_operators(), True if value contains any banned operator key at any nesting depth., TestHasDangerousOperators

### Community 53 - "Community 53"
Cohesion: 0.25
Nodes (13): _indexes_sql(), _list_databases_sql(), _list_resources_sql(), quote_ident(), PURE translation: CapabilityRequest -> (sql, args) for MySQL.  This is now a THI, Translate a CapabilityRequest into parameterized SQL + positional args.      Rai, Validate a (possibly schema-qualified) identifier and backtick-quote it.      Ea, _schema_sql() (+5 more)

### Community 54 - "Community 54"
Cohesion: 0.18
Nodes (10): _FakeConn, _FakePool, test_ddl_create_via_execute_path_rejected(), test_execute_count_sets_scalar(), test_execute_insert_reports_affected(), test_execute_read_returns_rows(), test_execute_validates_before_touching_pool(), test_health_true_on_success() (+2 more)

### Community 56 - "Community 56"
Cohesion: 0.39
Nodes (8): _doc(), #10: first-class dotted mask paths — "contact.email" is path-specific while a ba, test_bare_name_masks_any_depth_backcompat(), test_dotted_path_is_specific(), test_mixed_bare_and_dotted(), test_per_collection_dict_with_dotted(), test_transformer_bare_backcompat(), test_transformer_dotted_path_specific()

### Community 57 - "Community 57"
Cohesion: 0.23
Nodes (4): AssertionEngine, Dot-notation field access: 'contact.email' → doc['contact']['email']., ExpectedResult, Any

### Community 58 - "Community 58"
Cohesion: 0.36
Nodes (9): _create(), Tests for the human-in-the-loop approval store., test_create_get_list_pending(), test_prune_removes_resolved(), test_prune_shrinks_store_and_events_in_lockstep(), test_resolve_approved(), test_resolve_denied(), test_shutdown_denies_all_pending() (+1 more)

### Community 59 - "Community 59"
Cohesion: 0.14
Nodes (11): PostgresPlugin, DELETE has no RETURNING → affected must come from the status tag, not fetch()., test_aggregate_and_ddl_not_supported(), test_cross_resource_refs_default_empty(), test_cross_resource_refs_from_joins_option(), test_delete_reports_affected_via_status(), test_health_false_without_pool(), test_is_database_plugin_instance() (+3 more)

### Community 60 - "Community 60"
Cohesion: 0.31
Nodes (17): Dialect-parameterized translator. ``translate(req)`` -> Translated., SqlTranslator, _catalog(), _make_dialect(), Tests for the shared SqlTranslator core with a fake dialect.  These exercise the, _req(), test_catalog_dispatch(), test_delete_one_ctid_vs_limit() (+9 more)

### Community 61 - "Community 61"
Cohesion: 0.18
Nodes (10): Adding a backend plugin, Code layout, Code quality, Continuous Integration, Contributing to GuardMCP, Dev setup, Live-backend integration tests, PR expectations (+2 more)

### Community 62 - "Community 62"
Cohesion: 0.07
Nodes (53): datetime, TypeMarshalError, _coerce_date(), _coerce_decimal(), _coerce_int(), _coerce_objectid(), _coerce_objectid_best_effort(), _marshal_field_value() (+45 more)

### Community 63 - "Community 63"
Cohesion: 0.33
Nodes (3): extract_pipeline_collections(), Return every foreign collection name referenced by an aggregation pipeline,, TestExtractPipelineCollections

### Community 64 - "Community 64"
Cohesion: 0.22
Nodes (3): audit_logger(), mock_mongo_client(), Mongomock-based client — no real MongoDB needed.

### Community 65 - "Community 65"
Cohesion: 0.21
Nodes (14): _mysql_first_table(), normalize_mysql_explain(), normalize_postgres_explain(), _pg_top_plan(), Locate the primary table node in a MySQL EXPLAIN query_block.      MySQL nests t, Normalize a Postgres ``EXPLAIN (FORMAT JSON)`` payload → CostEstimate.      The, Normalize a MySQL ``EXPLAIN FORMAT=JSON`` payload → CostEstimate.      Reads ``q, _scan_warning() (+6 more)

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
Cohesion: 0.43
Nodes (3): Fix 2: raise ToolError if filter is not a dict or contains dangerous operators., validate_filter(), TestValidateFilter

### Community 70 - "Community 70"
Cohesion: 0.22
Nodes (9): _is_unscoped(), True if the filter targets the whole collection (empty or missing)., Classify the risk of an action.          S-4 scope escalation: when `params` is, ADDITIVE, OPT-IN cost-aware escalation. Returns max(base, cost-floor):         a, RiskEngine, Action, Any, CostEstimate (+1 more)

### Community 71 - "Community 71"
Cohesion: 0.29
Nodes (6): Hardening Checklist, Known Limitations, Reporting a Vulnerability, Security Model, Security Policy, Supported Versions

### Community 72 - "Community 72"
Cohesion: 0.29
Nodes (3): Tests for aggregation-pipeline guards: cross-collection, masked-field, stage all, P3: _guard_aggregation now reaches MongoDB pipeline knowledge THROUGH the     ac, TestGuardAggregationViaExecutorDelegation

### Community 73 - "Community 73"
Cohesion: 0.16
Nodes (12): main(), guardmcp eval — CLI entry point.  Usage:     python -m guardmcp.eval evals/cases, EvalReport, Console report renderer., render(), JSON report renderer., render(), JUnit XML report renderer — compatible with GitHub Actions and CI systems. (+4 more)

### Community 75 - "Community 75"
Cohesion: 0.21
Nodes (12): [0.0.1-alpha] — 2026-06-27, Added, Audit log default moved to a platform per-user state dir (minor behavior change), BREAKING — empty `collections.allow` is now DENY-ALL (AD-1, CRITICAL), Changed, Changelog, Known Limitations, Masking depth-limit leak fixed (EC-3, HIGH) (+4 more)

### Community 76 - "Community 76"
Cohesion: 0.16
Nodes (17): GuardValidationError, Request failed backend safety validation (injection, banned construct).      Mes, cross_resource_refs(), Raise GuardValidationError if the request is unsafe for this backend., Return foreign resources referenced by the request., validate_request(), QuoteIdent, Bound a single-row DELETE per the dialect strategy. (+9 more)

### Community 78 - "Community 78"
Cohesion: 0.60
Nodes (4): _build_success(), S-1: EXPLAIN plan masking via GuardPipeline._build_success., test_explain_masks_filter_literals(), test_explain_without_mask_fields_unchanged()

### Community 105 - "Community 105"
Cohesion: 0.23
Nodes (19): build(), _patch_mongo_factory(), _pipeline_with_registry(), Multi-backend CONNECTION lifecycle / use-case coverage.  These tests exercise EV, Replace MongoClient (used by build()'s _mongo_client_factory) with a     mongomo, _read_audit(), _settings(), _StubRegistry (+11 more)

### Community 106 - "Community 106"
Cohesion: 0.25
Nodes (8): classify_cost(), Map normalized signals → a single coarse CostLevel.      Rules (in order):, test_classify_collection_scan_is_high(), test_classify_collection_scan_large_is_critical(), test_classify_indexed_large_is_high(), test_classify_indexed_medium_volume(), test_classify_indexed_small_is_low(), test_classify_no_signal_is_unknown()

### Community 107 - "Community 107"
Cohesion: 0.22
Nodes (5): Explain a find in ``executionStats`` mode (planner + execution metrics,, Explain an aggregate in ``executionStats`` mode (no result materialized)., _bson_to_json(), Recursively convert BSON types to JSON-serializable equivalents., Any

### Community 108 - "Community 108"
Cohesion: 0.24
Nodes (7): Shared SQL translation core for relational plugins (PostgreSQL, MySQL, ...).  Th, Dialect, Dialect-parameterized, PURE translation: CapabilityRequest -> (sql, args).  This, Validate a (possibly schema-qualified) identifier; return its parts.      Each d, Captures the per-backend deltas the shared translator needs.      ``name`` is us, validate_ident(), test_validate_ident_returns_parts()

### Community 109 - "Community 109"
Cohesion: 0.31
Nodes (9): _execution_stats(), normalize_mongo_explain(), _plan_stages(), Return the winningPlan, tolerating both find and aggregate shapes., Flatten the (possibly nested) winningPlan into its stage names., Normalize a raw Mongo explain(executionStats) dict → CostEstimate.      Extracts, _winning_plan(), Any (+1 more)

### Community 111 - "Community 111"
Cohesion: 0.19
Nodes (13): neutralize(), #6: backend-neutral success accessors.      Map a backend-native success `data`, Action, Any, #6: backend-neutral success envelope — Mongo native results ALSO expose rows/aff, test_mongo_find_result_exposes_neutral(), test_neutralize_aggregate(), test_neutralize_count() (+5 more)

### Community 113 - "Community 113"
Cohesion: 0.50
Nodes (3): raise_guard_error(), Fix 8: always include what IS allowed so AI can self-correct on retry., TestRaiseGuardError

### Community 114 - "Community 114"
Cohesion: 0.23
Nodes (9): Deterministic assertion engine for GuardMCP evals.  Checks actual pipeline outpu, Seed mongomock-motor databases from fixture declarations., seed(), EvalRequest, ExpectedResult, FixtureDoc, Domain models for the GuardMCP eval framework., FixtureDoc (+1 more)

### Community 115 - "Community 115"
Cohesion: 0.26
Nodes (11): new_trace_id(), parse_traceparent(), Parse a W3C `traceparent` header and return its 32-hex trace-id, or None     if, Set the current trace id and return it.      #9: when a valid inbound W3C `trace, #9: W3C traceparent parsing, continuation, and round-trip., test_current_traceparent_round_trips(), test_new_trace_id_continues_incoming(), test_new_trace_id_mints_fresh_on_bad_incoming() (+3 more)

### Community 117 - "Community 117"
Cohesion: 0.13
Nodes (12): MySQLPlugin, Map cursor rows to dicts.          aiomysql's default cursor returns tuples; we, EXPLAIN FORMAT=JSON returns one row with the JSON plan in its single         col, Any, test_aggregate_and_ddl_not_supported(), test_cross_resource_refs_default_empty(), test_cross_resource_refs_from_joins_option(), test_health_false_without_pool() (+4 more)

### Community 119 - "Community 119"
Cohesion: 0.43
Nodes (6): discover(), _load_file(), Discover and load YAML eval case files., Recursively find .yaml eval files and parse them into EvalCase objects., EvalCase, Path

### Community 120 - "Community 120"
Cohesion: 0.27
Nodes (14): ConnectionConfig, _build_plugin_registry(), Composition layer: register the built-in plugins + discover any     entry-point, Register non-MongoDB (postgres/mysql) connections behind the legacy     Backend, register_sql_connections(), test_per_connection_options_flow_to_entry(), test_plugin_manifests_without_instantiation(), PluginRegistry (+6 more)

### Community 121 - "Community 121"
Cohesion: 0.13
Nodes (14): A. pip (local / stdio — Claude Desktop, Cursor, …), Audit & logging, B. Docker (server mode — SSE / streamable-http), C. Backends (PostgreSQL / MySQL) {#backends}, Checklist before production, CLI / operations, Configuration {#configuration}, Core (+6 more)

### Community 123 - "Community 123"
Cohesion: 0.21
Nodes (10): Tests for the top-level CLI dispatcher in ``guardmcp.cli``.  Verifies the routin, _run(), test_audit_verify_routes_to_handler(), test_capability_inspect_mongodb(), test_capability_inspect_unknown_type_errors(), test_doctor_routes_to_handler(), test_missing_required_subcommand_errors(), test_policy_lint_routes_to_handler() (+2 more)

### Community 124 - "Community 124"
Cohesion: 0.18
Nodes (16): ArgumentParser, BaseSettings, _build_parser(), main(), Dispatch a subcommand, or fall through to the server.      Backward compat: only, Settings, AppContext, Start the GuardMCP server (the original entry-point behavior).      This is the (+8 more)

### Community 127 - "Community 127"
Cohesion: 0.27
Nodes (4): Estimate a READ/COUNT via ``EXPLAIN FORMAT=JSON <sql>`` (plan only —         no, CapabilityRequest, CapabilityResult, CostEstimate

### Community 128 - "Community 128"
Cohesion: 0.24
Nodes (10): _FakePool, test_ddl_create_via_execute_path_rejected(), test_execute_count_sets_scalar(), test_execute_insert_reports_affected_and_lastrowid(), test_execute_maps_tuple_rows_via_description(), test_execute_read_returns_rows(), test_execute_validates_before_touching_pool(), test_health_true_on_success() (+2 more)

### Community 131 - "Community 131"
Cohesion: 0.53
Nodes (5): P-1/R-2: AuditLogger reuses one persistent append handle; aclose resets it., _record(), test_aclose_resets_handle_to_none(), test_handle_reused_across_log_calls(), test_log_after_aclose_reopens_and_appends()

### Community 132 - "Community 132"
Cohesion: 0.31
Nodes (9): clean_env(), Tests for ``guardmcp doctor`` and ``guardmcp config validate``.  A valid config, Drop any GUARDMCP_* env the host set; give a writable audit path + policy., _run(), test_config_validate_h1_satisfied_by_token(), test_config_validate_h1_violation_fails(), test_config_validate_valid_exit_0(), test_doctor_h1_violation_fails() (+1 more)

### Community 133 - "Community 133"
Cohesion: 0.06
Nodes (47): build_approval_app(), DecisionPayload, Build the approval REST API.      When api_token is set, all requests must inclu, ApprovalRequest, ApprovalStore, Remove resolved approvals older than max_age_seconds. Returns count pruned., Deny all pending approvals immediately and signal their events.         Call on, ApprovalRequest (+39 more)

### Community 134 - "Community 134"
Cohesion: 0.22
Nodes (6): AuditWriteError, P-1: open the append handle once and reuse it across log() calls., Sign (ordered), write all lines, ONE flush, then resolve futures.         Chain, Raised when an audit record cannot be persisted and fail_closed is set., HMAC-SHA256 of (prev_hash + line). Returns hex digest.          Delegates to the, Exception

### Community 135 - "Community 135"
Cohesion: 0.50
Nodes (4): Register all meta tools onto ``mcp``., register(), FastMCP, ToolContext

### Community 136 - "Community 136"
Cohesion: 0.22
Nodes (8): 1. Install, 2. Create a policy, 3. Connect Claude Desktop (stdio), 4. Try it, 5. Verify the install (optional), GuardMCP — Quickstart, Next, Prerequisites

### Community 137 - "Community 137"
Cohesion: 0.43
Nodes (7): Tests for ``guardmcp policy lint``.  Covers: the shipped ``policies/example.yaml, _run(), test_dangerous_policy_strict_fails(), test_dangerous_policy_warns_exit_0(), test_example_policy_clean_exit_0(), test_invalid_schema_bad_mode_errors(), test_missing_path_errors()

### Community 138 - "Community 138"
Cohesion: 0.67
Nodes (3): register(), FastMCP, ToolContext

### Community 141 - "Community 141"
Cohesion: 0.50
Nodes (4): Each test starts and ends on the default active connection so a switch in     on, _reset_active_connection(), Reset the active connection for the CURRENT context back to the default.      On, reset_active()

## Knowledge Gaps
- **152 isolated node(s):** `ApprovalStore`, `ReadinessProbe`, `Any`, `Capability`, `Path` (+147 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **13 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `AuditLogger` connect `Community 21` to `Community 0`, `Community 131`, `Community 4`, `Community 133`, `Community 134`, `Community 6`, `Community 7`, `Community 9`, `Community 10`, `Community 14`, `Community 26`, `Community 37`, `Community 42`, `Community 43`, `Community 46`, `Community 47`, `Community 64`, `Community 105`, `Community 124`?**
  _High betweenness centrality (0.083) - this node is a cross-community bridge._
- **Why does `MongoExecutor` connect `Community 15` to `Community 67`, `Community 68`, `Community 133`, `Community 9`, `Community 105`, `Community 107`, `Community 43`, `Community 41`, `Community 14`, `Community 47`, `Community 49`, `Community 18`, `Community 20`, `Community 26`, `Community 124`, `Community 29`, `Community 63`?**
  _High betweenness centrality (0.077) - this node is a cross-community bridge._
- **Why does `CapabilityRequest` connect `Community 20` to `Community 128`, `Community 3`, `Community 6`, `Community 11`, `Community 108`, `Community 13`, `Community 44`, `Community 47`, `Community 112`, `Community 110`, `Community 18`, `Community 140`, `Community 80`, `Community 53`, `Community 55`, `Community 23`, `Community 54`, `Community 31`?**
  _High betweenness centrality (0.064) - this node is a cross-community bridge._
- **Are the 24 inferred relationships involving `MongoExecutor` (e.g. with `AuditLogger` and `_Loader`) actually correct?**
  _`MongoExecutor` has 24 INFERRED edges - model-reasoned connections that need verification._
- **Are the 48 inferred relationships involving `AuditLogger` (e.g. with `AuditLogger` and `_Loader`) actually correct?**
  _`AuditLogger` has 48 INFERRED edges - model-reasoned connections that need verification._
- **Are the 33 inferred relationships involving `Action` (e.g. with `AuditLogger` and `_Loader`) actually correct?**
  _`Action` has 33 INFERRED edges - model-reasoned connections that need verification._
- **Are the 24 inferred relationships involving `GuardPipeline` (e.g. with `AuditLogger` and `_Loader`) actually correct?**
  _`GuardPipeline` has 24 INFERRED edges - model-reasoned connections that need verification._