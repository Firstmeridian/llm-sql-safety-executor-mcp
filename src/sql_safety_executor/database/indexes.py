"""Bounded, all-or-unavailable index metadata collection.

The deadline covers index collection only, using the configured query timeout.
Checks between calls and the adapters' remaining query timeout are cooperative:
connection establishment, driver waits and result mapping are not hard-cancelled.
The byte limit covers the JSON index array, not the complete MCP envelope.
"""

import json
import time
from typing import Any

from .outcomes import MetadataQueryError

MAX_INDEXES = 128
MAX_INDEX_KEY_PARTS = 2048
MAX_INDEX_JSON_BYTES = 64 * 1024


class IndexMetadataBudget:
    def __init__(self, timeout_seconds: float):
        self._deadline = time.monotonic() + timeout_seconds

    def remaining(self) -> float:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise MetadataQueryError("reading table indexes within budget")
        return remaining

    def rows(self, result: list | str) -> list:
        self.remaining()
        if isinstance(result, str) or len(result) > MAX_INDEX_KEY_PARTS:
            raise MetadataQueryError("reading table indexes within budget")
        return result

    def finish(self, indexes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.remaining()
        if len(indexes) > MAX_INDEXES or sum(
            len(index["columns"]) for index in indexes
        ) > MAX_INDEX_KEY_PARTS:
            raise MetadataQueryError("reading table indexes within budget")
        # Reject the whole set: neither a list nor a composite key is silently
        # truncated, and no unavailable metadata is misreported as an empty set.
        encoded = json.dumps(indexes, ensure_ascii=False).encode("utf-8")
        if len(encoded) > MAX_INDEX_JSON_BYTES:
            raise MetadataQueryError("reading table indexes within budget")
        self.remaining()
        return indexes
