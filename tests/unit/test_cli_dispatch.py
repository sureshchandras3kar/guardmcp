"""Tests for the top-level CLI dispatcher in ``guardmcp.cli``.

Verifies the routing contract WITHOUT starting the server loop or DB calls:
known subcommands reach their handler; bare invocation and ``--transport`` flags
fall through to the SERVE path (``serve_main`` is monkeypatched, never run); an
unknown subcommand exits with an error; ``--help`` lists subcommands; and
``version`` / ``capability inspect mongodb`` print the expected fields.
"""

from __future__ import annotations

from guardmcp import cli


def _run(argv, capsys=None):
    try:
        cli.main(argv)
        code = 0
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 0
    out = capsys.readouterr() if capsys else None
    return code, out


# ── serve fall-through (back-compat) ──────────────────────────────────────────


def test_bare_invocation_routes_to_serve(monkeypatch):
    calls = []
    monkeypatch.setattr("guardmcp.__main__.serve_main", lambda argv: calls.append(argv))
    cli.main([])
    assert calls == [[]]


def test_transport_flag_routes_to_serve(monkeypatch):
    calls = []
    monkeypatch.setattr("guardmcp.__main__.serve_main", lambda argv: calls.append(argv))
    cli.main(["--transport", "stdio"])
    assert calls == [["--transport", "stdio"]]


def test_serve_subcommand_strips_token(monkeypatch):
    calls = []
    monkeypatch.setattr("guardmcp.__main__.serve_main", lambda argv: calls.append(argv))
    cli.main(["serve", "--transport", "stdio"])
    # "serve" token is stripped before handing to the server parser.
    assert calls == [["--transport", "stdio"]]


# ── known subcommands route to their handler ──────────────────────────────────


def test_doctor_routes_to_handler(monkeypatch):
    seen = {}

    def fake(args):
        seen["hit"] = True
        return 0

    monkeypatch.setattr(cli, "_cmd_doctor", fake)
    code, _ = _run(["doctor"])
    assert seen.get("hit") is True
    assert code == 0


def test_policy_lint_routes_to_handler(monkeypatch):
    captured_args = {}

    def fake(args):
        captured_args["path"] = args.path
        captured_args["strict"] = args.strict
        return 0

    monkeypatch.setattr(cli, "_cmd_policy_lint", fake)
    code, _ = _run(["policy", "lint", "/tmp/p.yaml", "--strict"])
    assert code == 0
    assert captured_args == {"path": "/tmp/p.yaml", "strict": True}


def test_audit_verify_routes_to_handler(monkeypatch):
    captured_args = {}

    def fake(args):
        captured_args["log_path"] = args.log_path
        return 7  # arbitrary nonzero to confirm exit code propagates

    monkeypatch.setattr(cli, "_cmd_audit_verify", fake)
    code, _ = _run(["audit", "verify", "/tmp/a.jsonl"])
    assert captured_args["log_path"] == "/tmp/a.jsonl"
    assert code == 7


# ── error / help paths ────────────────────────────────────────────────────────


def test_unknown_subcommand_is_not_treated_as_subcommand(monkeypatch):
    # "frobnicate" is not in _SUBCOMMANDS → falls through to serve with the raw
    # argv (serve's own parser would then reject it). Confirm it does NOT reach
    # the CLI dispatcher and DOES hit the serve path.
    calls = []
    monkeypatch.setattr("guardmcp.__main__.serve_main", lambda argv: calls.append(argv))
    cli.main(["frobnicate"])
    assert calls == [["frobnicate"]]


def test_missing_required_subcommand_errors(capsys):
    # `policy` with no action → argparse error (required subparser) → exit 2.
    code, _ = _run(["policy"], capsys)
    assert code == 2


def test_top_level_help_lists_subcommands(capsys):
    code, out = _run(["--help"], capsys)
    assert code == 0
    text = out.out
    for name in ("version", "doctor", "policy", "audit", "capability", "serve"):
        assert name in text
    # Back-compat note about the server must be present.
    assert "--transport" in text


# ── version / capability inspect output ───────────────────────────────────────


def test_version_prints_expected_fields(capsys):
    code, out = _run(["version"], capsys)
    text = out.out
    assert code == 0
    assert "guardmcp" in text
    assert "guardmcp/v1" in text
    assert "core API major" in text
    assert "mongodb" in text


def test_capability_inspect_mongodb(capsys):
    code, out = _run(["capability", "inspect", "mongodb"], capsys)
    text = out.out
    assert code == 0
    assert "mongodb" in text
    assert "api_version" in text
    assert "capabilities" in text


def test_capability_inspect_unknown_type_errors(capsys):
    code, out = _run(["capability", "inspect", "nosuchdb"], capsys)
    assert code != 0
    assert "ERROR" in (out.out + out.err)
