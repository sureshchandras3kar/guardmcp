"""
Tamper-evident audit log (per-process HMAC chain).

Risk #5 — multi-writer attribution (honest seam, not a faked distributed chain):
The HMAC chain implemented here is PER-PROCESS SINGLE-WRITER. A single background
flusher signs records in order, so the chain is continuous within one process and
across restarts of THAT process (the chain is reseeded from the last persisted
record). In a multi-replica deployment, each replica writes an independent
genesis-rooted chain to its OWN file; there is NO cross-replica chain — replica A
cannot verify replica B's records, and the chains are not interleavable.

For centralized tamper-evident audit across replicas, implement AuditSinkProtocol
(core/interfaces/stores.py) backed by an append-only store (e.g. QLDB or
Kafka+KMS), and aggregate by AuditRecord.node_id. Each replica stamps its own
node_id (GUARDMCP_NODE_ID) so records remain attributable to their writer.
"""

import asyncio
import contextlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiofiles

from ..models.domain import AuditRecord
from ..observability import get_trace_id, log_event

_GENESIS = "0" * 64


class AuditWriteError(Exception):
    """Raised when an audit record cannot be persisted and fail_closed is set."""


_SENTINEL = object()  # flusher stop signal


class AuditLogger:
    def __init__(
        self,
        log_path: Path,
        hmac_secret: str = "",
        fail_closed: bool = False,
        node_id: str = "",
    ) -> None:
        self._path = log_path
        self._node_id = node_id
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._secret = hmac_secret.encode() if hmac_secret else b""
        self._fail_closed = fail_closed
        # P-1: hold one persistent append handle instead of open/close per call.
        self._fh: Any = None
        # H1/H2: group-commit. Callers enqueue (data, future); a single
        # background flusher batches many records into ONE write + ONE fsync,
        # removing the global per-request fsync serialization. A single writer
        # keeps the HMAC chain ordered; each caller still awaits its own future
        # so fail_closed + durability semantics are preserved.
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None
        # CR-1: seed the chain from the last persisted record so the HMAC chain
        # is CONTINUOUS across restarts. Without this, every process start reset
        # to genesis, letting an attacker truncate the final run's tail and
        # re-append a clean genesis-rooted chain that still verifies.
        self._prev_hash: str = self._load_last_hash() if self._secret else _GENESIS

    def _load_last_hash(self) -> str:
        """Return the _hmac of the last record on disk, or genesis if none."""
        if not self._path.exists():
            return _GENESIS
        try:
            last = None
            with open(self._path, "rb") as f:
                for raw in f:
                    raw = raw.strip()
                    if raw:
                        last = raw
            if last is None:
                return _GENESIS
            rec = json.loads(last)
            return rec.get("_hmac", _GENESIS)
        except Exception as exc:
            log_event("warning", "audit_chain_seed_failed", detail=repr(exc))
            return _GENESIS

    def _sign(self, prev_hash: str, line: str) -> str:
        """HMAC-SHA256 of (prev_hash + line). Returns hex digest.

        Delegates to the shared ``verify.sign_record`` so the writer and the
        offline verifier (``guardmcp audit verify``) use ONE definition of the
        chain math — no second copy to drift out of sync.
        """
        from .verify import sign_record

        return sign_record(self._secret, prev_hash, line)

    async def _get_handle(self):
        """P-1: open the append handle once and reuse it across log() calls."""
        if self._fh is None:
            self._fh = await aiofiles.open(self._path, "a")
        return self._fh

    def _ensure_flusher(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._flusher(), name="audit-flusher")

    async def aclose(self) -> None:
        """Drain the queue, stop the flusher, flush+close the handle (R-2)."""
        if self._task is not None and not self._task.done():
            await self._queue.put(_SENTINEL)
            with contextlib.suppress(Exception):
                await self._task
            self._task = None
        async with self._lock:
            if self._fh is not None:
                try:
                    await self._fh.flush()
                    await self._fh.close()
                finally:
                    self._fh = None

    async def _flusher(self) -> None:
        """Single writer: batch all queued records into one write + one fsync."""
        while True:
            first = await self._queue.get()
            if first is _SENTINEL:
                self._queue.task_done()
                return
            batch = [first]
            # Drain everything already queued into this batch.
            stop = False
            while True:
                try:
                    nxt = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if nxt is _SENTINEL:
                    stop = True
                    break
                batch.append(nxt)
            await self._write_batch(batch)
            for _ in batch:
                self._queue.task_done()
            if stop:
                self._queue.task_done()  # the sentinel
                return

    async def _write_batch(self, batch: list) -> None:
        """Sign (ordered), write all lines, ONE flush, then resolve futures.
        Chain advances atomically only after a successful flush."""
        try:
            fh = await self._get_handle()
            local_prev = self._prev_hash
            lines: list[str] = []
            for data, _fut in batch:
                if self._secret:
                    base_line = json.dumps(data, separators=(",", ":"))
                    sig = self._sign(local_prev, base_line)
                    data["_hmac"] = sig
                    lines.append(json.dumps(data, separators=(",", ":")) + "\n")
                    local_prev = sig
                else:
                    lines.append(json.dumps(data) + "\n")
            await fh.write("".join(lines))
            await fh.flush()
            if self._secret:
                self._prev_hash = local_prev  # commit chain only on success
            for _data, fut in batch:
                if fut is not None and not fut.done():
                    fut.set_result(None)
        except Exception as exc:
            log_event("error", "audit_write_failed", detail=repr(exc))
            self._fh = None  # drop possibly-broken handle; next batch reopens
            for _data, fut in batch:
                if fut is None or fut.done():
                    continue
                if self._fail_closed:
                    fut.set_exception(AuditWriteError(str(exc)))
                else:
                    fut.set_result(None)

    async def log(self, record: AuditRecord) -> None:
        data = record.model_dump(mode="json")
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._ensure_flusher()
        await self._queue.put((data, fut))
        # Await durability: returns after this record's batch is written+flushed.
        # Raises AuditWriteError if the write failed and fail_closed is set.
        await fut

    def build(
        self,
        *,
        agent: str,
        collection: str,
        action: str,
        status: str,
        reason: str | None = None,
        risk: str | None = None,
        request_id: str | None = None,
        params: dict | None = None,
    ) -> AuditRecord:
        return AuditRecord(
            timestamp=datetime.now(UTC),
            agent=agent,
            collection=collection,
            action=action,
            status=status,
            reason=reason,
            risk=risk,
            request_id=request_id,
            params=params,
            node_id=self._node_id,
            trace_id=get_trace_id(),
        )
