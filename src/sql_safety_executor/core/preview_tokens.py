"""Bounded in-process store for one-time mutation preview-token state."""

from __future__ import annotations

import hmac
import threading
from dataclasses import dataclass
from typing import Literal


PreviewTokenConsumeStatus = Literal[
    "consumed",
    "not_found",
    "expired",
    "mismatch",
]


@dataclass(frozen=True)
class PreviewTokenRecord:
    """Minimal server-side state needed for one-time mutation execution."""

    expires_at: int
    request_binding_json: str
    execution_binding_json: str
    review_json: str | None = None


class InMemoryPreviewTokenStore:
    """Bounded process-local preview-token store with atomic consumption."""

    def __init__(self, max_entries: int):
        if max_entries < 1:
            raise ValueError("Preview token store max_entries must be positive")
        self._max_entries = max_entries
        self._entries: dict[str, PreviewTokenRecord] = {}
        self._lock = threading.Lock()

    def _purge_expired_locked(self, now: int) -> None:
        expired = [
            token_digest
            for token_digest, record in self._entries.items()
            if record.expires_at <= now
        ]
        for token_digest in expired:
            self._entries.pop(token_digest, None)

    def issue(
        self,
        token_digest: str,
        expires_at: int,
        request_binding_json: str,
        execution_binding_json: str,
        *,
        now: int,
    ) -> bool:
        """Register one issued token, returning False on collision/capacity."""
        with self._lock:
            self._purge_expired_locked(now)
            if expires_at <= now or token_digest in self._entries:
                return False
            if len(self._entries) >= self._max_entries:
                return False
            self._entries[token_digest] = PreviewTokenRecord(
                expires_at=expires_at,
                request_binding_json=request_binding_json,
                execution_binding_json=execution_binding_json,
            )
            return True

    def consume_if_matches(
        self,
        token_digest: str,
        request_binding_json: str,
        *,
        now: int,
    ) -> tuple[PreviewTokenConsumeStatus, PreviewTokenRecord | None]:
        """Atomically validate the request binding and consume one token."""
        with self._lock:
            record = self._entries.get(token_digest)
            if record is None:
                self._purge_expired_locked(now)
                return "not_found", None
            if record.expires_at <= now:
                self._entries.pop(token_digest, None)
                self._purge_expired_locked(now)
                return "expired", None

            self._purge_expired_locked(now)
            if not hmac.compare_digest(
                record.request_binding_json.encode("utf-8"),
                request_binding_json.encode("utf-8"),
            ):
                return "mismatch", None
            return "consumed", self._entries.pop(token_digest)

    def clear(self) -> None:
        """Invalidate pending proposals when the owning service shuts down."""
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def inspect_if_matches(
        self, token_digest: str, request_binding_json: str, *, now: int
    ):
        """Read an unconsumed proposal without extending its TTL."""
        with self._lock:
            record = self._entries.get(token_digest)
            if record is None:
                self._purge_expired_locked(now)
                return "not_found", None
            if record.expires_at <= now:
                self._entries.pop(token_digest, None)
                return "expired", None
            if not hmac.compare_digest(
                record.request_binding_json.encode(), request_binding_json.encode()
            ):
                return "mismatch", None
            return "pending", record

    def attach_review(
        self,
        token_digest: str,
        request_binding_json: str,
        review_json: str,
        *,
        now: int,
    ) -> bool:
        """Attach the immutable MRTR review before disclosing the continuation."""
        from dataclasses import replace

        if len(review_json.encode("utf-8")) > 65536:
            return False
        with self._lock:
            record = self._entries.get(token_digest)
            if (
                record is None
                or record.expires_at <= now
                or record.review_json is not None
            ):
                return False
            if not hmac.compare_digest(
                record.request_binding_json.encode(), request_binding_json.encode()
            ):
                return False
            self._entries[token_digest] = replace(record, review_json=review_json)
            return True
