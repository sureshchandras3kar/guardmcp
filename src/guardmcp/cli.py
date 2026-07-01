"""GuardMCP operator / CI command-line interface.

A thin subcommand dispatcher layered ON TOP of the existing engine. It is
ADDITIVE and backward compatible:

    python -m guardmcp                       → serve (stdio default)
    python -m guardmcp --transport stdio     → serve (flags pass through)
    guardmcp serve --transport streamable-http → serve
    guardmcp doctor / version / audit / policy / plugin / tools / capability / config

Dispatch rule: if the first non-flag argument is a known subcommand, dispatch
it; otherwise fall through to the server's ``serve_main`` (so bare invocation
and ``--transport``-style flags still start the server — Claude Desktop relies
on this).

Every subcommand reuses engine code (no duplicated hash/policy/manifest logic),
stays offline where possible, and exits nonzero on failure.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

# Subcommands the dispatcher recognizes. Anything else (including bare invocation
# and --transport/--host/... flags) falls through to the server.
_SUBCOMMANDS = frozenset(
    {
        "serve",
        "doctor",
        "version",
        "audit",
        "policy",
        "plugin",
        "tools",
        "capability",
        "config",
        "eval",
    }
)


# ── audit verify ───────────────────────────────────────────────────────────────


def _cmd_audit_verify(args: argparse.Namespace) -> int:
    from .core.audit.verify import verify_chain

    secret = args.secret or os.environ.get("GUARDMCP_AUDIT_HMAC_SECRET", "")
    result = verify_chain(args.log_path, secret)
    # Always print the human summary to STDOUT (success AND failure) so CI and
    # operators see the first bad line / reason. Exit code carries the verdict.
    print(result.render())
    return result.exit_code


# ── policy lint ──────────────────────────────────────────────────────────────


# PII-ish field names that should usually be masked when reads are allowed.
_PII_FIELDS = (
    "password",
    "ssn",
    "token",
    "secret",
    "email",
    "api_key",
    "credit_card",
)
# Destructive DDL actions that warrant approval.critical.
_DESTRUCTIVE_DDL = ("drop", "drop_index")


def _lint_one(policy, *, multi_connection: bool) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for a single already-validated Policy."""
    errors: list[str] = []
    warnings: list[str] = []
    allows_reads = True  # both readonly and readwrite return data

    # Wide-open collections.
    if "*" in policy.collections.allow:
        warnings.append("collections.allow includes '*' (wide open — all collections accessible)")

    # readwrite without approval gates.
    if policy.mode == "readwrite":
        if not policy.approval.high:
            warnings.append("mode=readwrite but approval.high=false (HIGH-risk writes unguarded)")
        if not policy.approval.critical:
            warnings.append(
                "mode=readwrite but approval.critical=false (CRITICAL writes unguarded)"
            )

    # PII-ish names not masked while reads are allowed (heuristic, best-effort).
    if allows_reads:
        masked = {f.lower() for f in policy.mask_fields_for("*")}
        # Include any per-collection masks so we don't over-warn on dict masks.
        if isinstance(policy.mask_fields, dict):
            for fields in policy.mask_fields.values():
                masked.update(f.lower() for f in fields)
        unmasked = [p for p in _PII_FIELDS if p not in masked]
        if unmasked:
            warnings.append(
                "PII-ish fields not in mask_fields (heuristic): "
                f"{', '.join(unmasked)} — reads may leak these"
            )

    # Empty connections_allow when multiple connections are configured.
    if multi_connection and not policy.connections_allow:
        warnings.append(
            "connections_allow is empty while multiple connections are configured "
            "(agent may switch to any connection)"
        )

    # Destructive DDL allowed without approval.critical.
    allowed_actions = set(policy.actions.allow)
    ddl = [d for d in _DESTRUCTIVE_DDL if d in allowed_actions]
    if ddl and not policy.approval.critical:
        warnings.append(
            f"destructive DDL allowed ({', '.join(ddl)}) without approval.critical=true"
        )

    return errors, warnings


def _cmd_policy_lint(args: argparse.Namespace) -> int:
    from .core.policy.loader import PolicyLoader

    path = Path(args.path)
    loader = PolicyLoader(path)
    # Reuse loader parsing + inheritance. A schema/parse error raises here.
    try:
        loader.load()
    except Exception as exc:
        print(f"ERROR — failed to load policy at {path}:\n  {exc}", file=sys.stderr)
        return 1

    policies = loader.all()
    if not policies:
        print(f"ERROR — no policies found at {path}", file=sys.stderr)
        return 1

    # Best-effort: is more than one connection configured for this deployment?
    multi_connection = bool(os.environ.get("GUARDMCP_CONNECTIONS")) or bool(
        os.environ.get("GUARDMCP_EXTRA_CONNECTIONS")
    )

    total_errors = 0
    total_warnings = 0
    for policy in policies:
        errors, warnings = _lint_one(policy, multi_connection=multi_connection)
        total_errors += len(errors)
        total_warnings += len(warnings)
        header = f"agent: {policy.agent}  (mode={policy.mode})"
        if not errors and not warnings:
            print(f"OK   {header}")
            continue
        print(f"     {header}")
        for e in errors:
            print(f"  ERROR   {e}")
        for w in warnings:
            label = "ERROR  " if args.strict else "WARN   "
            print(f"  {label} {w}")

    print(
        f"\n{len(policies)} policy(ies) checked — "
        f"{total_errors} error(s), {total_warnings} warning(s)."
    )
    if total_errors:
        return 1
    if args.strict and total_warnings:
        return 1
    return 0


# ── doctor / config validate ─────────────────────────────────────────────────


def _check_h1(settings) -> tuple[bool, str]:
    """The H1 rule: networked transport must have an approval token (or insecure
    override). Returns (passed, detail)."""
    if settings.transport in ("sse", "streamable-http") and not (
        settings.approval_api_token or settings.approval_allow_insecure
    ):
        return (
            False,
            f"transport={settings.transport} exposes the approval API with no "
            "GUARDMCP_APPROVAL_API_TOKEN (set the token, or "
            "GUARDMCP_APPROVAL_ALLOW_INSECURE=true to override)",
        )
    return True, f"transport={settings.transport} authentication OK"


def _doctor_settings_section(settings) -> list[tuple[str, str, str]]:
    """Return [(level, label, detail)] for the config-only portion (no DB)."""
    from .core.paths import resolve_audit_path

    rows: list[tuple[str, str, str]] = []

    # H1 token rule.
    ok, detail = _check_h1(settings)
    rows.append(("PASS" if ok else "FAIL", "transport/auth (H1)", detail))

    # Audit path resolution + writability (same probe build() uses).
    audit_path = resolve_audit_path(settings.audit_log_path)
    try:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        probe = audit_path.parent / ".guardmcp-write-test"
        probe.write_text("")
        probe.unlink()
        rows.append(("PASS", "audit path", f"writable: {audit_path}"))
    except OSError as exc:
        rows.append(("FAIL", "audit path", f"NOT writable: {audit_path} ({exc})"))

    return rows


def _cmd_config_validate(args: argparse.Namespace) -> int:
    from .config import Settings

    try:
        settings = Settings()
    except Exception as exc:
        print(f"FAIL — invalid settings: {exc}", file=sys.stderr)
        return 1

    rows = _doctor_settings_section(settings)
    hard_fail = False
    for level, label, detail in rows:
        print(f"[{level}] {label}: {detail}")
        if level == "FAIL":
            hard_fail = True

    print("\nVERDICT:", "FAIL" if hard_fail else "PASS")
    return 1 if hard_fail else 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    from .config import Settings
    from .core.policy.loader import PolicyLoader

    print("GuardMCP doctor — readiness report\n")

    rows: list[tuple[str, str, str]] = []

    # Settings.
    try:
        settings = Settings()
    except Exception as exc:
        print(f"[FAIL] settings: could not load — {exc}", file=sys.stderr)
        print("\nVERDICT: FAIL")
        return 1
    rows.append(("PASS", "settings", "loaded"))

    # Config-only checks (H1, audit path).
    rows.extend(_doctor_settings_section(settings))

    # Policy load.
    try:
        loader = PolicyLoader(settings.policy_path)
        loader.load()
        agents = [p.agent for p in loader.all()]
        if agents:
            rows.append(("PASS", "policy", f"{len(agents)} agent(s): {', '.join(agents)}"))
        else:
            rows.append(("WARN", "policy", f"no agents loaded from {settings.policy_path}"))
    except Exception as exc:
        rows.append(("FAIL", "policy", f"invalid policy: {exc}"))

    # Connections configured.
    conn_names = ["default", *settings.extra_connections.keys(), *settings.connections.keys()]
    rows.append(("PASS", "connections", f"configured: {', '.join(conn_names)}"))

    # MongoDB connectivity (WARN, never FAIL).
    try:
        import asyncio

        from .plugins.mongodb.client import MongoClient

        async def _ping() -> bool:
            client = MongoClient(settings.mongodb_uri, settings.mongodb_database)
            try:
                return await asyncio.wait_for(client.ping(), timeout=2.0)
            finally:
                client.close()

        asyncio.run(_ping())
        rows.append(("PASS", "mongodb", f"reachable: {settings.mongodb_uri}"))
    except Exception as exc:
        rows.append(
            ("WARN", "mongodb", f"unreachable ({type(exc).__name__}): {settings.mongodb_uri}")
        )

    hard_fail = False
    for level, label, detail in rows:
        print(f"[{level}] {label}: {detail}")
        if level == "FAIL":
            hard_fail = True

    print("\nVERDICT:", "FAIL" if hard_fail else "PASS")
    return 1 if hard_fail else 0


# ── plugin / capability ──────────────────────────────────────────────────────


def _builtin_registry():
    """A driver-free PluginRegistry of the built-in plugins (+ entry points)."""
    from .__main__ import _build_plugin_registry

    return _build_plugin_registry()


def _cmd_plugin_list(args: argparse.Namespace) -> int:
    reg = _builtin_registry()
    manifests = reg.manifests()
    if args.format == "json":
        print(json.dumps(manifests, indent=2, sort_keys=True))
        return 0
    for name, m in sorted(manifests.items()):
        print(f"{name}")
        print(f"  api_version: {m['api_version']}")
        print(f"  supported:   {', '.join(m['supported'])}")
        if m.get("dialect_features"):
            print(f"  dialect:     {json.dumps(m['dialect_features'])}")
    return 0


def _cmd_plugin_validate(args: argparse.Namespace) -> int:
    from .conformance import check_plugin_conformance

    reg = _builtin_registry()
    types = [args.type] if args.type else sorted(reg.names())
    any_fail = False
    for t in types:
        try:
            plugin = reg.instantiate(t)
        except Exception as exc:
            print(f"[FAIL] {t}: could not instantiate — {exc}", file=sys.stderr)
            any_fail = True
            continue
        failures = check_plugin_conformance(plugin)
        if failures:
            any_fail = True
            print(f"[FAIL] {t}: not conformant", file=sys.stderr)
            for f in failures:
                print(f"  - {f}", file=sys.stderr)
        else:
            print(f"[PASS] {t}: conformant")
    return 1 if any_fail else 0


def _cmd_capability_inspect(args: argparse.Namespace) -> int:
    from .core.interfaces.errors import PluginError

    reg = _builtin_registry()
    try:
        m = reg.manifest(args.type)
    except PluginError as exc:
        print(f"ERROR — {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps(m, indent=2, sort_keys=True))
        return 0
    print(f"{m['name']}")
    print(f"  api_version: {m['api_version']}")
    print(f"  capabilities: {', '.join(m['supported'])}")
    print(f"  dialect_features: {json.dumps(m.get('dialect_features', {}))}")
    return 0


# ── tools (doc generator) ─────────────────────────────────────────────────────


def _introspect_tools() -> list[dict]:
    """Build the FastMCP server (register_tools) WITHOUT starting a transport
    and return a list of tool dicts: name, description, annotations, params."""
    import asyncio
    from typing import cast

    from mcp.server.fastmcp import FastMCP

    from .core.pipeline import GuardPipeline
    from .server.tools import register_tools

    mcp = FastMCP("GuardMCP")
    # Doc-gen only introspects tool schemas; the pipeline getter is never invoked,
    # so a None-returning stub cast to the expected callable type is safe here.
    register_tools(
        mcp,
        get_pipeline=cast("Callable[[], GuardPipeline]", lambda: None),
        get_agent=lambda: "doc-gen",
        get_settings=lambda: None,
    )
    tools = asyncio.run(mcp.list_tools())

    out: list[dict] = []
    for t in tools:
        schema = t.inputSchema or {}
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        params = [
            {
                "name": pname,
                "type": pinfo.get("type", pinfo.get("anyOf", "any")),
                "required": pname in required,
                "description": pinfo.get("description", ""),
            }
            for pname, pinfo in props.items()
        ]
        annotations = None
        if t.annotations is not None:
            annotations = t.annotations.model_dump(exclude_none=True)
        out.append(
            {
                "name": t.name,
                "description": t.description or "",
                "annotations": annotations,
                "params": params,
            }
        )
    out.sort(key=lambda d: d["name"])
    return out


def _render_tools_md(tools: list[dict]) -> str:
    lines = [f"# GuardMCP Tool Reference ({len(tools)} tools)", ""]
    for t in tools:
        lines.append(f"## `{t['name']}`")
        lines.append("")
        if t["description"]:
            lines.append(t["description"])
            lines.append("")
        if t["annotations"]:
            ann = ", ".join(f"{k}={v}" for k, v in t["annotations"].items())
            lines.append(f"**Annotations:** {ann}")
            lines.append("")
        if t["params"]:
            lines.append("| Param | Type | Required | Description |")
            lines.append("| --- | --- | --- | --- |")
            for p in t["params"]:
                typ = p["type"] if isinstance(p["type"], str) else "any"
                req = "yes" if p["required"] else "no"
                desc = str(p["description"]).replace("\n", " ").replace("|", "\\|")
                lines.append(f"| `{p['name']}` | {typ} | {req} | {desc} |")
            lines.append("")
    return "\n".join(lines)


def _cmd_tools(args: argparse.Namespace) -> int:
    tools = _introspect_tools()
    if args.format == "json":
        print(json.dumps(tools, indent=2))
    else:
        print(_render_tools_md(tools))
    return 0


# ── version ────────────────────────────────────────────────────────────────────


def _cmd_version(args: argparse.Namespace) -> int:
    from importlib.metadata import PackageNotFoundError, version

    from .core.registry.registry import CORE_API_MAJOR

    try:
        pkg_version = version("guardmcp")
    except PackageNotFoundError:
        pkg_version = "unknown (not installed)"

    print(f"guardmcp {pkg_version}")
    print("policy apiVersion supported: guardmcp/v1")
    print(f"core API major: {CORE_API_MAJOR}")
    reg = _builtin_registry()
    print("plugin api_versions:")
    for name, m in sorted(reg.manifests().items()):
        print(f"  {name}: {m['api_version']}")
    return 0


# ── parser ───────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="guardmcp",
        description="GuardMCP — policy-enforced multi-backend MCP server + operator CLI",
        epilog=(
            "Running the server (back-compat): a bare `guardmcp` (or `python -m guardmcp`),"
            " an explicit `guardmcp serve`, or any `--transport/--host/--port/--approval-port`"
            " flag starts the MCP server. Examples:\n"
            "  guardmcp                          # serve (stdio default)\n"
            "  guardmcp --transport stdio        # serve (Claude Desktop)\n"
            "  guardmcp serve --transport streamable-http\n"
            "\nEach subcommand has its own --help (e.g. `guardmcp policy lint --help`).\n"
            "`policy lint` and `audit verify` exit nonzero on failure (CI-friendly)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(
        dest="command",
        title="subcommands",
        metavar="{version,doctor,config,policy,audit,capability,plugin,tools,serve,eval}",
    )

    # eval — documented here so it shows in --help; actually handled by main()
    # (delegates to guardmcp.eval.cli) before argparse sees it.
    sub.add_parser("eval", help="Run the eval harness over a cases directory.")

    # serve — explicit alias for the server path (flags handled by serve_main).
    p_serve = sub.add_parser("serve", help="Start the MCP server (default action).")
    p_serve.add_argument("--transport", choices=["stdio", "sse", "streamable-http"])
    p_serve.add_argument("--host")
    p_serve.add_argument("--port", type=int)
    p_serve.add_argument("--approval-port", type=int)

    # version
    sub.add_parser("version", help="Print version, policy/core API, plugin manifests.")

    # doctor
    sub.add_parser("doctor", help="Readiness report (config, policy, DB, audit path).")

    # config validate
    p_config = sub.add_parser("config", help="Configuration checks.")
    config_sub = p_config.add_subparsers(dest="subcommand", required=True)
    config_sub.add_parser("validate", help="Validate Settings/H1/paths (no DB call).")

    # audit verify
    p_audit = sub.add_parser("audit", help="Audit-log operations.")
    audit_sub = p_audit.add_subparsers(dest="subcommand", required=True)
    p_av = audit_sub.add_parser("verify", help="Verify the HMAC chain of an audit log.")
    p_av.add_argument("log_path", help="Path to the JSONL audit log.")
    p_av.add_argument("--secret", default="", help="HMAC secret (or GUARDMCP_AUDIT_HMAC_SECRET).")

    # policy lint
    p_policy = sub.add_parser("policy", help="Policy operations.")
    policy_sub = p_policy.add_subparsers(dest="subcommand", required=True)
    p_pl = policy_sub.add_parser("lint", help="Validate + check policies for danger.")
    p_pl.add_argument("path", help="Policy file or directory.")
    p_pl.add_argument("--strict", action="store_true", help="Treat warnings as errors.")

    # plugin list / validate
    p_plugin = sub.add_parser("plugin", help="Plugin operations.")
    plugin_sub = p_plugin.add_subparsers(dest="subcommand", required=True)
    p_pl_list = plugin_sub.add_parser("list", help="List plugin manifests (driver-free).")
    p_pl_list.add_argument("--format", choices=["text", "json"], default="text")
    p_pl_val = plugin_sub.add_parser("validate", help="Run conformance on builtin plugin(s).")
    p_pl_val.add_argument("type", nargs="?", help="Plugin type (omit = all builtins).")

    # capability inspect
    p_cap = sub.add_parser("capability", help="Capability/manifest inspection.")
    cap_sub = p_cap.add_subparsers(dest="subcommand", required=True)
    p_ci = cap_sub.add_parser("inspect", help="Print one plugin's manifest (no connect).")
    p_ci.add_argument("type", help="Plugin type (mongodb/postgres/mysql).")
    p_ci.add_argument("--format", choices=["text", "json"], default="text")

    # tools
    p_tools = sub.add_parser("tools", help="Emit the tool reference (doc generator).")
    p_tools.add_argument("--format", choices=["md", "json"], default="md")

    return parser


def _dispatch(command: str, args: argparse.Namespace) -> int:
    sc = getattr(args, "subcommand", None)
    if command == "version":
        return _cmd_version(args)
    if command == "doctor":
        return _cmd_doctor(args)
    if command == "config" and sc == "validate":
        return _cmd_config_validate(args)
    if command == "audit" and sc == "verify":
        return _cmd_audit_verify(args)
    if command == "policy" and sc == "lint":
        return _cmd_policy_lint(args)
    if command == "plugin" and sc == "list":
        return _cmd_plugin_list(args)
    if command == "plugin" and sc == "validate":
        return _cmd_plugin_validate(args)
    if command == "capability" and sc == "inspect":
        return _cmd_capability_inspect(args)
    if command == "tools":
        return _cmd_tools(args)
    # Should be unreachable: argparse enforces required subcommands.
    print(f"unknown command: {command} {sc}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> None:
    """Dispatch a subcommand, or fall through to the server.

    Backward compat: only the explicit subcommand names route to the CLI. Bare
    invocation and ``--transport``-style flags fall through to ``serve_main``.
    """
    if argv is None:
        argv = sys.argv[1:]

    first = next((a for a in argv if not a.startswith("-")), None)

    # Top-level help: `guardmcp -h/--help` with NO preceding subcommand must list
    # the subcommands (not the serve parser). A subcommand's own --help still
    # routes through that subcommand below (e.g. `policy lint --help`).
    if first is None and any(a in ("-h", "--help") for a in argv):
        _build_parser().print_help()
        return

    if first not in _SUBCOMMANDS:
        # No (recognized) subcommand → serve. Pass through any server flags.
        from .__main__ import serve_main

        serve_main(argv)
        return

    if first == "serve":
        # Strip the "serve" token and hand the rest to the server.
        from .__main__ import serve_main

        serve_argv = list(argv)
        serve_argv.remove("serve")
        serve_main(serve_argv)
        return

    if first == "eval":
        # Back-compat convenience: `guardmcp eval ...` mirrors `guardmcp-eval`.
        from .eval.cli import main as eval_main

        idx = argv.index("eval")
        raise SystemExit(eval_main(argv[idx + 1 :]))

    parser = _build_parser()
    args = parser.parse_args(argv)
    raise SystemExit(_dispatch(args.command, args))


if __name__ == "__main__":
    main()
