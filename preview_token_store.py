"""Bounded in-process store for one-time mutation preview-token state."""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class PreviewTokenRecord:
    """Minimal server-side state needed for one-time mutation execution."""

    expires_at: int
    execution_binding_json: str


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
                execution_binding_json=execution_binding_json,
            )
            return True

    def consume(
        self,
        token_digest: str,
        expires_at: int,
        *,
        now: int,
    ) -> PreviewTokenRecord | None:
        """Atomically claim and remove one unexpired matching token."""
        with self._lock:
            self._purge_expired_locked(now)
            record = self._entries.get(token_digest)
            if record is None or record.expires_at != expires_at:
                return None
            return self._entries.pop(token_digest)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
