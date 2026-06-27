import asyncio
import os
from pathlib import Path

import yaml

from ..observability import log_event
from .models import ApprovalPolicy, Policy


def _union(a: list[str], b: list[str]) -> list[str]:
    """Order-preserving union of two string lists (base first, child appended)."""
    seen: dict[str, None] = {}
    for x in a:
        seen[x] = None
    for x in b:
        seen[x] = None
    return list(seen)


def _merge_mask_fields(
    base: "list[str] | dict[str, list[str]]",
    child: "list[str] | dict[str, list[str]]",
) -> "list[str] | dict[str, list[str]]":
    """Merge mask_fields. If either is a dict, merge per-collection (union per
    key); otherwise union the two flat lists."""
    if isinstance(base, dict) or isinstance(child, dict):
        base_d = base if isinstance(base, dict) else ({"*": base} if base else {})
        child_d = child if isinstance(child, dict) else ({"*": child} if child else {})
        out: dict[str, list[str]] = {k: list(v) for k, v in base_d.items()}
        for k, v in child_d.items():
            out[k] = _union(out.get(k, []), v)
        return out
    return _union(base, child)


def _merge(base: Policy, child: Policy) -> Policy:
    """
    Merge `base` under `child` (child overrides). Scalars: child wins when set
    to a non-default value, else base. Lists: union. Approval: per-field OR
    (child True wins; otherwise base value).
    """
    from .models import ActionPolicy, CollectionPolicy

    mode = child.mode if child.mode != "readonly" else base.mode
    return Policy(
        # populate_by_name=True accepts the field name; mypy only sees the
        # `apiVersion` alias without the (mypy-version-incompatible) pydantic plugin.
        api_version=child.api_version,  # type: ignore[call-arg]
        agent=child.agent,
        extends=None,
        not_before=child.not_before if child.not_before is not None else base.not_before,
        not_after=child.not_after if child.not_after is not None else base.not_after,
        mode=mode,
        collections=CollectionPolicy(
            allow=_union(base.collections.allow, child.collections.allow),
            deny=_union(base.collections.deny, child.collections.deny),
        ),
        actions=ActionPolicy(
            allow=_union(base.actions.allow, child.actions.allow),
            deny=_union(base.actions.deny, child.actions.deny),
        ),
        mask_fields=_merge_mask_fields(base.mask_fields, child.mask_fields),
        fields_allow=_union(base.fields_allow, child.fields_allow),
        connections_allow=_union(base.connections_allow, child.connections_allow),
        approval=ApprovalPolicy(
            high=child.approval.high or base.approval.high,
            critical=child.approval.critical or base.approval.critical,
        ),
    )


def _resolve_inheritance(parsed: dict[str, Policy]) -> dict[str, Policy]:
    """Resolve `extends` chains into fully-merged policies. Detects cycles and
    missing bases, raising a clear ValueError."""

    resolved: dict[str, Policy] = {}

    def resolve(name: str, stack: tuple[str, ...]) -> Policy:
        if name in resolved:
            return resolved[name]
        policy = parsed.get(name)
        if policy is None:
            raise ValueError(f"policy '{stack[-1]}' extends unknown base '{name}'")
        if policy.extends is None:
            resolved[name] = policy
            return policy
        if policy.extends in stack:
            cycle = " -> ".join((*stack, policy.extends))
            raise ValueError(f"cyclic policy inheritance detected: {cycle}")
        base = resolve(policy.extends, (*stack, name))
        merged = _merge(base, policy)
        resolved[name] = merged
        return merged

    for agent in parsed:
        resolve(agent, (agent,))
    return resolved


class PolicyLoader:
    def __init__(self, policy_path: Path, poll_interval: float = 30.0) -> None:
        self._path = policy_path
        self._poll_interval = poll_interval
        self._policies: dict[str, Policy] = {}
        self._mtime: float = 0.0
        self._task: asyncio.Task | None = None

    def _policy_files(self) -> list[Path]:
        """Sorted list of *.yaml/*.yml files when _path is a directory.

        Sorting makes cross-file resolution + duplicate detection deterministic.
        """
        files = [p for p in self._path.iterdir() if p.is_file() and p.suffix in (".yaml", ".yml")]
        return sorted(files)

    def _parse_items(self, data: object) -> list:
        """Apply the SAME doc shape parsing (list / {agents:[...]} / single)."""
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "agents" in data:
            return data["agents"]
        return [data]

    def _current_mtime(self) -> float:
        """Max mtime to watch. For a directory: the dir's own mtime (catches
        add/remove) plus every *.yaml/*.yml file mtime (catches edits)."""
        if self._path.is_dir():
            mtimes = [os.path.getmtime(self._path)]
            mtimes += [os.path.getmtime(f) for f in self._policy_files()]
            return max(mtimes)
        return os.path.getmtime(self._path)

    def load(self) -> None:
        """
        Load (or reload) policies from disk. Called at startup and by hot-reload.

        Accepts EITHER a single file path OR a directory. For a directory, every
        *.yaml/*.yml file (sorted) is parsed with the same doc-shape handling and
        the extends-inheritance is resolved ACROSS all files (a role:* template
        defined in one file may be extended by an agent in another). A duplicate
        agent name across two files raises a clear ValueError naming both files.

        H3: builds the new policy map in a LOCAL variable and swaps it in only
        after parsing + validation fully succeed. A concurrent get() therefore
        never observes a half-built or empty map. On any parse/validation error
        during a reload, the previously loaded policies are kept unchanged.
        """
        if not self._path.exists():
            log_event(
                "warning",
                "policy_file_missing",
                path=str(self._path),
                detail="Run guardmcp_setup to create one.",
            )
            self._policies = {}
            return

        # Build into a local dict — validation may raise; if it does, the live
        # self._policies is untouched and the caller's exception handler keeps
        # the previous good state. For a directory we track which file defined
        # each agent so a cross-file duplicate produces a clear error.
        parsed: dict[str, Policy] = {}

        if self._path.is_dir():
            source_of: dict[str, str] = {}
            for file in self._policy_files():
                with open(file) as f:
                    data = yaml.safe_load(f)
                if data is None:
                    continue
                for item in self._parse_items(data):
                    policy = Policy.model_validate(item)
                    if policy.agent in parsed:
                        raise ValueError(
                            f"duplicate agent '{policy.agent}' defined in both "
                            f"'{source_of[policy.agent]}' and '{file}'"
                        )
                    parsed[policy.agent] = policy
                    source_of[policy.agent] = str(file)
        else:
            with open(self._path) as f:
                data = yaml.safe_load(f)
            for item in self._parse_items(data):
                policy = Policy.model_validate(item)
                parsed[policy.agent] = policy

        # Resolve `extends` inheritance, then drop role-only templates so they
        # are never returned by get() for a real agent.
        resolved = _resolve_inheritance(parsed)
        new_policies = {name: p for name, p in resolved.items() if not p.is_role_template()}

        # Atomic swap — single reference assignment, no observable empty window.
        self._policies = new_policies
        self._mtime = self._current_mtime()

    def get(self, agent: str) -> Policy | None:
        return self._policies.get(agent)

    def all(self) -> list[Policy]:
        return list(self._policies.values())

    def start_hot_reload(self) -> None:
        """Start background asyncio task that polls for policy file changes."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._watch(), name="policy-hot-reload")

    def stop_hot_reload(self) -> None:
        """Cancel the background watcher task."""
        if self._task and not self._task.done():
            self._task.cancel()

    async def _watch(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._poll_interval)
                if not self._path.exists():
                    continue
                current_mtime = self._current_mtime()
                if current_mtime != self._mtime:
                    self.load()
                    log_event(
                        "info",
                        "policy_reloaded",
                        path=str(self._path),
                        agents=len(self._policies),
                    )
            except asyncio.CancelledError:
                return
            except Exception as exc:
                log_event("error", "policy_hot_reload_error", detail=repr(exc))
