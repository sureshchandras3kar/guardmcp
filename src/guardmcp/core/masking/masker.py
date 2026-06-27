from typing import Any

MASK_VALUE = "***masked***"
# EC-3: bound is a realistic nesting depth. BEYOND it we MUST fail safe and
# redact rather than return the raw subtree (which would leak masked fields
# nested deeper than the bound). See _DEPTH_REDACTION below.
_MAX_DEPTH = 25
# Sentinel returned for an over-deep subtree when masking/allow rules are active.
_DEPTH_REDACTION = {"***": "depth-limit-exceeded"}


def _split_mask_entries(
    fields: list[str],
) -> tuple[frozenset[str], frozenset[tuple[str, ...]]]:
    """#10: split mask entries into bare names (match a key at ANY depth, the
    historical behaviour) and dotted PATHS (root-anchored, match ONLY that path).

    Returns (bare_names, path_tuples)."""
    bare: set[str] = set()
    paths: set[tuple[str, ...]] = set()
    for f in fields:
        if "." in f:
            paths.add(tuple(f.split(".")))
        else:
            bare.add(f)
    return frozenset(bare), frozenset(paths)


class FieldMasker:
    def __init__(self, fields: list[str]) -> None:
        # #10: bare names mask any-depth keys (back-compat); dotted entries are
        # first-class root-anchored paths that mask ONLY that exact path.
        self._bare, self._paths = _split_mask_entries(list(fields))

    def _has_rules(self) -> bool:
        return bool(self._bare or self._paths)

    def mask(
        self,
        doc: dict[str, Any],
        _depth: int = 0,
        _path: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Recursively mask sensitive fields. Bare names match a key at any
        depth; dotted paths match only their exact path from the document root."""
        if not self._has_rules():
            return doc  # fast path — no rules, nothing to mask
        if _depth > _MAX_DEPTH:
            # EC-3 fail-safe: rules ARE active but we can no longer guarantee
            # masking at this depth, so redact the subtree rather than reveal it.
            return dict(_DEPTH_REDACTION)
        result: dict[str, Any] = {}
        for k, v in doc.items():
            cur = _path + (k,)
            if k in self._bare or cur in self._paths:
                result[k] = MASK_VALUE
            elif isinstance(v, dict):
                result[k] = self.mask(v, _depth + 1, cur)
            elif isinstance(v, list):
                result[k] = [
                    self.mask(item, _depth + 1, cur) if isinstance(item, dict) else item
                    for item in v
                ]
            else:
                result[k] = v
        return result

    def mask_result(self, result: Any) -> Any:
        if not self._has_rules():
            return result
        if isinstance(result, list):
            return [self.mask(doc) if isinstance(doc, dict) else doc for doc in result]
        if isinstance(result, dict):
            return self.mask(result)
        return result


class ResultTransformer:
    """
    H3: single-pass field allow-list + masking. Replaces two separate full
    traversals (FieldAllowFilter then FieldMasker) with ONE recursion:
    top-level allow-list projection + recursive masking in the same walk.
    Cached on the Policy (M1) so it is built once, not per request.
    """

    def __init__(self, mask_fields: list[str], fields_allow: list[str]) -> None:
        # #10: bare names mask any-depth keys (back-compat); dotted entries are
        # first-class root-anchored paths that mask ONLY that exact path.
        self._mask, self._mask_paths = _split_mask_entries(list(mask_fields))
        self._allow = frozenset(fields_allow)
        self._keep_id = "_id" not in self._allow

    def _doc(
        self, doc: dict[str, Any], _depth: int = 0, _path: tuple[str, ...] = ()
    ) -> dict[str, Any]:
        if _depth > _MAX_DEPTH:
            # EC-3 fail-safe: _doc is only reached when mask/allow rules are
            # active (transform_result fast-paths otherwise), so redact the
            # over-deep subtree instead of returning it raw.
            return dict(_DEPTH_REDACTION)
        result: dict[str, Any] = {}
        for k, v in doc.items():
            # Top-level allow-list projection (depth 0 only).
            if (
                _depth == 0
                and self._allow
                and k not in self._allow
                and not (self._keep_id and k == "_id")
            ):
                continue
            cur = _path + (k,)
            if k in self._mask or cur in self._mask_paths:
                result[k] = MASK_VALUE
            elif isinstance(v, dict):
                result[k] = self._doc(v, _depth + 1, cur)
            elif isinstance(v, list):
                result[k] = [
                    self._doc(item, _depth + 1, cur) if isinstance(item, dict) else item
                    for item in v
                ]
            else:
                result[k] = v
        return result

    def transform_result(self, result: Any) -> Any:
        if not self._mask and not self._mask_paths and not self._allow:
            return result  # fast path — nothing to do
        if isinstance(result, list):
            return [self._doc(d) if isinstance(d, dict) else d for d in result]
        if isinstance(result, dict):
            return self._doc(result)
        return result
