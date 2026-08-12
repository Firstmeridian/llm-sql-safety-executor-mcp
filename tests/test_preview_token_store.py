"""Unit regressions for the process-local preview-token store."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from preview_token_store import InMemoryPreviewTokenStore


@pytest.mark.parametrize("max_entries", [0, -1])
def test_memory_store_rejects_nonpositive_capacity(max_entries: int) -> None:
    with pytest.raises(ValueError, match="max_entries must be positive"):
        InMemoryPreviewTokenStore(max_entries=max_entries)


def test_memory_store_concurrent_consume_has_one_winner() -> None:
    store = InMemoryPreviewTokenStore(max_entries=1)
    assert store.issue("digest", 2_000, "{}", now=1_000) is True

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(
                lambda _index: store.consume("digest", 2_000, now=1_001),
                range(16),
            )
        )

    assert sum(record is not None for record in results) == 1
    assert len(store) == 0


def test_memory_store_capacity_does_not_evict_valid_token() -> None:
    store = InMemoryPreviewTokenStore(max_entries=1)
    assert store.issue("first", 2_000, "{}", now=1_000) is True
    assert store.issue("second", 2_000, "{}", now=1_000) is False
    assert store.consume("first", 2_000, now=1_001) is not None


def test_memory_store_expired_entry_releases_capacity() -> None:
    store = InMemoryPreviewTokenStore(max_entries=1)
    assert store.issue("expired", 1_001, "{}", now=1_000) is True
    assert store.issue("replacement", 2_000, "{}", now=1_001) is True
    assert store.consume("expired", 1_001, now=1_001) is None
    assert store.consume("replacement", 2_000, now=1_001) is not None


def test_memory_store_expiry_mismatch_does_not_consume_record() -> None:
    store = InMemoryPreviewTokenStore(max_entries=1)
    assert store.issue("digest", 2_000, '{"expected":"pending"}', now=1_000)

    assert store.consume("digest", 2_001, now=1_001) is None
    record = store.consume("digest", 2_000, now=1_001)
    assert record is not None
    assert record.execution_binding_json == '{"expected":"pending"}'
