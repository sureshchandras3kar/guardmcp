"""guardmcp_setup — interactive policy setup wizard (survey + YAML writer)."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ....core.validation import JsonDict
from .._common import (
    Any,
    ErrorCode,
    ToolContext,
    _annot,
    err,
    ok,
)


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    get_pipeline = ctx.get_pipeline
    get_settings = ctx.get_settings

    @mcp.tool(
        description=(
            "Interactive setup wizard for the GuardMCP policy.\n"
            "Use when: no policy is configured, or you want to reconfigure access.\n"
            "Do NOT use when: a policy is already loaded and correct.\n"
            "Side effects: writes policy.yaml and hot-reloads it.\n"
            "Example: call with no args to see the survey, then guardmcp_setup(answers={...})."
        ),
        annotations=_annot(readOnlyHint=False, destructiveHint=False),
    )
    async def guardmcp_setup(answers: JsonDict = None) -> str:
        from ....core.observability import log_event

        settings = get_settings()
        pipeline = get_pipeline()

        survey = {
            "setup_required": True,
            "message": "Welcome to GuardMCP Setup! Answer these questions to create your policy.",
            "questions": [
                {
                    "id": "agent_name",
                    "question": "What name identifies this AI agent?",
                    "hint": "Must match GUARDMCP_AGENT env var. Example: claude, my-bot",
                    "default": "claude",
                },
                {
                    "id": "mode",
                    "question": "What access mode should this agent have?",
                    "options": ["readonly", "readwrite"],
                    "hint": (
                        "readonly = safe default, readwrite = allows writes with approval gates"
                    ),
                    "default": "readonly",
                },
                {
                    "id": "collections_allow",
                    "question": (
                        "Which collections should the agent access? (comma-separated, or * for all)"
                    ),
                    "hint": "Example: users, orders, products",
                    "default": "*",
                },
                {
                    "id": "collections_deny",
                    "question": (
                        "Which collections should ALWAYS be blocked? "
                        "(comma-separated, or leave empty)"
                    ),
                    "hint": "Example: payroll, audit_log, secrets",
                    "default": "",
                },
                {
                    "id": "mask_fields",
                    "question": "Which fields should be masked in all results? (comma-separated)",
                    "hint": "Example: password, email, ssn, api_key",
                    "default": "password, token, api_key, secret",
                },
                {
                    "id": "approval_writes",
                    "question": (
                        "Require human approval for HIGH risk writes (update_many, delete_one)?"
                    ),
                    "options": ["yes", "no"],
                    "default": "yes",
                },
                {
                    "id": "approval_critical",
                    "question": (
                        "Require human approval for CRITICAL risk writes (delete_many, drop)?"
                    ),
                    "options": ["yes", "no"],
                    "default": "yes",
                },
            ],
            "example_call": (
                'Call guardmcp_setup with answers={"agent_name": "claude", "mode": "readonly", ...}'
            ),
        }

        if not answers:
            return ok(survey)

        agent_name = str(answers.get("agent_name", "claude")).strip()
        mode = str(answers.get("mode", "readonly")).strip()
        if mode not in ("readonly", "readwrite"):
            mode = "readonly"

        collections_allow_raw = str(answers.get("collections_allow", "*")).strip()
        collections_deny_raw = str(answers.get("collections_deny", "")).strip()
        mask_fields_raw = str(
            answers.get("mask_fields", "password, token, api_key, secret")
        ).strip()
        approval_writes = str(answers.get("approval_writes", "yes")).strip().lower() == "yes"
        approval_critical = str(answers.get("approval_critical", "yes")).strip().lower() == "yes"

        def _parse_csv(s: str) -> list[str]:
            return [x.strip() for x in s.split(",") if x.strip()]

        allow_list = _parse_csv(collections_allow_raw)
        deny_list = _parse_csv(collections_deny_raw)
        mask_list = _parse_csv(mask_fields_raw)

        read_actions = [
            "find",
            "count",
            "aggregate",
            "collection_schema",
            "collection_indexes",
            "list_databases",
            "db_stats",
            "explain",
        ]
        import yaml as _yaml

        policy_doc: dict[str, Any] = {"agent": agent_name, "mode": mode}

        # AD-1: deny-by-default. Omitting `allow` now means DENY-ALL, so we must
        # ALWAYS write an explicit allow list. "*" answer ⇒ allow: ["*"] (all).
        wildcard = collections_allow_raw == "*"
        collections: dict[str, Any] = {}
        collections["allow"] = ["*"] if wildcard else allow_list
        if deny_list:
            collections["deny"] = deny_list
        policy_doc["collections"] = collections

        policy_doc["actions"] = {"allow": read_actions}
        if mask_list:
            policy_doc["mask_fields"] = mask_list
        policy_doc["approval"] = {"high": approval_writes, "critical": approval_critical}

        header = (
            "# GuardMCP Policy — generated by guardmcp_setup\n"
            "# Edit this file to customize. GuardMCP hot-reloads changes every 30s.\n"
            "# readwrite mode: add write actions (insert_one, update_one, delete_one, ...)\n"
            "# to actions.allow below.\n\n"
        )
        yaml_content = header + _yaml.safe_dump(
            policy_doc, sort_keys=False, default_flow_style=False, allow_unicode=True
        )

        if settings is None:
            return err(
                ErrorCode.BACKEND_ERROR,
                "Settings not available — cannot determine policy path.",
                retryable=False,
                yaml=yaml_content,
            )

        policy_path = settings.policy_path
        try:
            policy_path.parent.mkdir(parents=True, exist_ok=True)
            policy_path.write_text(yaml_content)
        except Exception as exc:
            return err(
                ErrorCode.BACKEND_ERROR,
                f"Failed to write policy file: {exc}",
                retryable=True,
                yaml=yaml_content,
            )

        try:
            pipeline._policies.load()
            log_event("info", "policy_reloaded_after_setup", path=str(policy_path))
        except Exception as exc:
            log_event("error", "policy_reload_after_setup_error", detail=repr(exc))

        return ok(
            {
                "message": f"Policy written to {policy_path} and reloaded.",
                "agent": agent_name,
                "mode": mode,
                "yaml": yaml_content,
            }
        )
