"""Cross-platform audit/state path resolution (core/paths.py)."""

from pathlib import Path

from guardmcp.config import Settings
from guardmcp.core.paths import (
    default_audit_log_path,
    default_state_dir,
    resolve_audit_path,
)


def test_state_dir_macos(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("os.name", "posix")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/Users/alice")))
    assert default_state_dir() == Path("/Users/alice/Library/Logs/guardmcp")


def test_state_dir_windows_with_localappdata(monkeypatch):
    # Trigger the Windows branch via sys.platform only. Patching os.name to "nt"
    # too would make pathlib refuse to construct Path() on a POSIX test host, so
    # we rely on the `sys.platform == "win32"` half of the branch condition. The
    # LOCALAPPDATA value uses POSIX separators so the path is parsed on any host.
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", "/c/Users/Bob/AppData/Local")
    got = default_state_dir()
    assert got.parts[-2:] == ("guardmcp", "logs")
    assert "AppData" in got.parts and "Local" in got.parts


def test_state_dir_windows_fallback(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/bob")))
    got = default_state_dir()
    # Falls back to ~/AppData/Local/<app>/logs when LOCALAPPDATA is unset.
    assert got.parts[-4:] == ("AppData", "Local", "guardmcp", "logs")


def test_state_dir_linux_default(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("os.name", "posix")
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/carol")))
    assert default_state_dir() == Path("/home/carol/.local/state/guardmcp")


def test_state_dir_linux_xdg(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("os.name", "posix")
    monkeypatch.setenv("XDG_STATE_HOME", "/var/lib/state")
    assert default_state_dir() == Path("/var/lib/state/guardmcp")


def test_default_audit_log_path_macos(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("os.name", "posix")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/Users/alice")))
    p = default_audit_log_path()
    assert p == Path("/Users/alice/Library/Logs/guardmcp/audit.jsonl")
    assert p.parts[-3:] == ("Logs", "guardmcp", "audit.jsonl")


def test_default_audit_log_path_linux_ends_with_guardmcp_audit(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("os.name", "posix")
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/carol")))
    assert default_audit_log_path().parts[-2:] == ("guardmcp", "audit.jsonl")


def test_resolve_absolute_passes_through():
    abs_path = Path("/var/log/guardmcp/audit.jsonl")
    assert resolve_audit_path(abs_path) == abs_path


def test_resolve_relative_lands_under_state_dir_not_cwd(monkeypatch, tmp_path):
    # Pretend Linux with a known state dir, and a cwd that is clearly different.
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("os.name", "posix")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.chdir(tmp_path)

    resolved = resolve_audit_path(Path("logs/audit.jsonl"))

    assert resolved.is_absolute()
    # Resolves under the state dir...
    assert str(resolved).startswith(str(tmp_path / "state" / "guardmcp"))
    # ...and NOT under the current working directory.
    cwd = Path.cwd()
    assert not str(resolved).startswith(str(cwd / "logs"))


def test_resolve_empty_path_uses_default_filename(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("os.name", "posix")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert resolve_audit_path(Path("")).name == "audit.jsonl"


def test_settings_default_audit_path_is_absolute_and_platform():
    # No GUARDMCP_AUDIT_LOG_PATH set -> default_factory yields the platform path.
    s = Settings()
    assert s.audit_log_path.is_absolute()
    assert s.audit_log_path.name == "audit.jsonl"
    assert "guardmcp" in s.audit_log_path.parts


def test_env_absolute_override_wins(monkeypatch, tmp_path):
    override = tmp_path / "vol" / "audit.jsonl"
    monkeypatch.setenv("GUARDMCP_AUDIT_LOG_PATH", str(override))
    s = Settings()
    assert s.audit_log_path == override
    # resolve keeps an explicit absolute override unchanged.
    assert resolve_audit_path(s.audit_log_path) == override
