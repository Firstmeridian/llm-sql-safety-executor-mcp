"""Bounded, disposable connection probes, independent of business transactions.

Cancellation stops waiting, not a running DBAPI call. The process-wide runner
retains batch ownership until workers finish cleanup attempts. An observed
cleanup failure disables further batches until the server process is replaced.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import logging
from threading import Event, RLock
import time
from typing import Annotated, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from db_adapter import DatabaseConfig, create_adapter

logger = logging.getLogger(__name__)
DIAGNOSTIC_BUDGET_SECONDS = 30.0
MAX_DIAGNOSTIC_WORKERS = 4
ConnectionScope = Literal["single", "all"]


class _CheckBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    db_type: str
    cleanup_failed: bool = False


class ConnectedCheck(_CheckBase):
    status: Literal["connected"]
    connected: Literal[True]


class FailedCheck(_CheckBase):
    status: Literal["failed"]
    connected: Literal[False]
    error: str


class IncompleteCheck(_CheckBase):
    status: Literal["timeout", "not_checked"]
    connected: None
    error: str = "The diagnostic deadline was reached."


ConnectionCheck = Annotated[
    ConnectedCheck | FailedCheck | IncompleteCheck, Field(discriminator="status")
]


class ConnectionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: ConnectionScope = Field(description="Requested scope, even when all selects only one configured alias.")
    all_connected: bool = Field(description="All aliases in this report connected; cleanup health is separate.")
    complete: bool = Field(description="Every selected alias has a connected or failed result, with none unresolved.")
    connection_count: int = Field(description="Number of aliases selected for this diagnostic, not necessarily all configured aliases.")
    connected_count: int
    cleanup_failed: bool
    results: dict[str, ConnectionCheck]


class DiagnosticsUnavailable(RuntimeError):
    """Safe request-level errors, suitable for conversion to MCP ToolError."""


def diagnostic_budget(tool_timeout: float | None) -> float:
    return min(DIAGNOSTIC_BUDGET_SECONDS, 0.8 * tool_timeout) if tool_timeout else DIAGNOSTIC_BUDGET_SECONDS


def probe_connection(config: DatabaseConfig) -> ConnectedCheck | FailedCheck:
    """Create, query and dispose an uncached adapter on the calling thread."""
    adapter = None
    result = FailedCheck(db_type=config.db_type, status="failed", connected=False,
                         error="Database connection check failed.")
    try:
        adapter = create_adapter(config=config, diagnostic=True)
        connected, message = adapter.check_connection()
        if connected:
            result = ConnectedCheck(db_type=config.db_type, status="connected", connected=True)
        else:
            # Adapter errors have already passed through the backend sanitizer.
            result = FailedCheck(db_type=config.db_type, status="failed", connected=False, error=message)
    except Exception as exc:
        logger.warning("Connection diagnostic failed: %s", type(exc).__name__)
    finally:
        if adapter is not None:
            try:
                adapter.close()
            except Exception as exc:
                logger.warning("Diagnostic cleanup failed: %s", type(exc).__name__)
                result = result.model_copy(update={"cleanup_failed": True})
    return result


@dataclass(frozen=True)
class _Outcome:
    result: ConnectionCheck
    finished_at: float


class ConnectionDiagnostics:
    """One batch at a time, with no queue beyond available worker slots."""

    def __init__(self, probe: Callable[[DatabaseConfig], ConnectionCheck] = probe_connection):
        self._probe = probe
        self._lock = RLock()
        self._executor: ThreadPoolExecutor | None = None
        self._pending: set[Future[_Outcome]] = set()
        self._batch_active = False
        self._draining = False
        # Not reset by start()/close(): a new process is the recovery boundary.
        self._cleanup_failed = False

    def start(self) -> None:
        with self._lock:
            if self._executor is None:
                if self._batch_active:
                    raise DiagnosticsUnavailable("Previous connection diagnostics are still draining.")
                self._executor = ThreadPoolExecutor(
                    max_workers=MAX_DIAGNOSTIC_WORKERS, thread_name_prefix="connection-check",
                )

    @property
    def cleanup_failed(self) -> bool:
        with self._lock:
            return self._cleanup_failed

    def close(self) -> None:
        with self._lock:
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def _done(self, future: Future[_Outcome]) -> None:
        with self._lock:
            self._pending.discard(future)
            if self._draining and not self._pending:
                self._batch_active = False

    def _work(self, config: DatabaseConfig, deadline: float, started: Event) -> _Outcome:
        with self._lock:
            if self._cleanup_failed:
                return _Outcome(IncompleteCheck(
                    db_type=config.db_type, status="not_checked", connected=None,
                    error="Diagnostics stopped after a cleanup failure.",
                ), time.monotonic())
        if time.monotonic() >= deadline:
            return _Outcome(IncompleteCheck(db_type=config.db_type, status="not_checked", connected=None), time.monotonic())
        started.set()
        try:
            result = self._probe(config)
        except Exception as exc:
            logger.warning("Connection diagnostic worker failed: %s", type(exc).__name__)
            result = FailedCheck(db_type=config.db_type, status="failed", connected=False, error="Database connection check failed.")
        if result.cleanup_failed:
            with self._lock:
                self._cleanup_failed = True
        return _Outcome(result, time.monotonic())

    async def run(
        self, configs: list[DatabaseConfig], budget: float, *, scope: ConnectionScope,
    ) -> ConnectionReport:
        # Scope is request identity, not something inferred from the list size:
        # an all-connections request may also contain exactly one connection.
        if scope not in ("single", "all") or not configs or (scope == "single" and len(configs) != 1):
            raise ValueError("Invalid diagnostic scope or connection selection.")
        deadline = time.monotonic() + budget
        with self._lock:
            if self._executor is None:
                raise DiagnosticsUnavailable("Connection diagnostics are unavailable while the server is stopped.")
            if self._cleanup_failed:
                raise DiagnosticsUnavailable(
                    "Connection diagnostics are disabled after a cleanup failure. "
                    "Restart the server process before retrying."
                )
            if self._batch_active:
                raise DiagnosticsUnavailable("Connection diagnostics are busy. Please retry later.")
            self._batch_active = True
            self._draining = False

        submitted: dict[str, tuple[Future[_Outcome], Event]] = {}
        waiting: set[asyncio.Future[_Outcome]] = set()
        next_index = 0
        try:
            while next_index < len(configs) or waiting:
                with self._lock:
                    if self._executor is None:
                        raise DiagnosticsUnavailable("Connection diagnostics stopped during server shutdown.")
                    while (next_index < len(configs) and len(waiting) < MAX_DIAGNOSTIC_WORKERS
                           and not self._cleanup_failed and time.monotonic() < deadline):
                        config = configs[next_index]
                        started = Event()
                        future = self._executor.submit(self._work, config, deadline, started)
                        self._pending.add(future)
                        future.add_done_callback(self._done)
                        submitted[config.connection_id] = (future, started)
                        waiting.add(asyncio.wrap_future(future))
                        next_index += 1
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not waiting:
                    break
                _, waiting = await asyncio.wait(waiting, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)

            with self._lock:
                if self._executor is None:
                    raise DiagnosticsUnavailable("Connection diagnostics stopped during server shutdown.")
                cleanup_failed = self._cleanup_failed
            results: dict[str, ConnectionCheck] = {}
            for config in configs:
                entry = submitted.get(config.connection_id)
                result: ConnectionCheck = IncompleteCheck(
                    db_type=config.db_type, status="not_checked", connected=None,
                    error=("Diagnostics stopped after a cleanup failure." if cleanup_failed
                           else "The diagnostic deadline was reached."),
                )
                if entry is not None:
                    future, started = entry
                    if started.is_set():
                        result = IncompleteCheck(db_type=config.db_type, status="timeout", connected=None)
                    if future.done() and not future.cancelled():
                        outcome = future.result()
                        if outcome.finished_at <= deadline:
                            result = outcome.result
                        elif outcome.result.cleanup_failed:
                            result = result.model_copy(update={"cleanup_failed": True})
                results[config.connection_id] = result
            connected_count = sum(result.connected is True for result in results.values())
            return ConnectionReport(
                scope=scope,
                all_connected=connected_count == len(configs),
                complete=all(result.status in ("connected", "failed") for result in results.values()),
                connection_count=len(configs), connected_count=connected_count,
                cleanup_failed=cleanup_failed or any(item.cleanup_failed for item in results.values()),
                results=results,
            )
        finally:
            # Waiters cannot release running workers. Observable cleanup failures
            # separately latch admission disabled, even after workers finish.
            for future, _ in submitted.values():
                future.cancel()
            with self._lock:
                self._draining = True
                if not self._pending:
                    self._batch_active = False
