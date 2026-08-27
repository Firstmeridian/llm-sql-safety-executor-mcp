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
    assert store.issue("digest", 2_000, "request", "{}", now=1_000) is True

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(
                lambda _index: store.consume_if_matches(
                    "digest",
                    "request",
                    now=1_001,
                ),
                range(16),
            )
        )

    assert sum(status == "consumed" for status, _record in results) == 1
    assert sum(status == "not_found" for status, _record in results) == 15
    assert len(store) == 0


def test_memory_store_capacity_does_not_evict_valid_token() -> None:
    store = InMemoryPreviewTokenStore(max_entries=1)
    assert store.issue("first", 2_000, "request", "{}", now=1_000) is True
    assert store.issue("second", 2_000, "request", "{}", now=1_000) is False
    status, record = store.consume_if_matches(
        "first",
        "request",
        now=1_001,
    )
    assert status == "consumed"
    assert record is not None


def test_memory_store_expired_entry_releases_capacity() -> None:
    store = InMemoryPreviewTokenStore(max_entries=1)
    assert store.issue("expired", 1_001, "request", "{}", now=1_000) is True
    assert store.issue("replacement", 2_000, "request", "{}", now=1_001) is True
    status, record = store.consume_if_matches(
        "expired",
        "request",
        now=1_001,
    )
    assert status == "not_found"
    assert record is None
    status, record = store.consume_if_matches(
        "replacement",
        "request",
        now=1_001,
    )
    assert status == "consumed"
    assert record is not None


def test_memory_store_request_mismatch_does_not_consume_record() -> None:
    store = InMemoryPreviewTokenStore(max_entries=1)
    assert store.issue(
        "digest",
        2_000,
        '{"params_hash":"expected"}',
        '{"expected":"pending"}',
        now=1_000,
    )

    status, record = store.consume_if_matches(
        "digest",
        '{"params_hash":"different"}',
        now=1_001,
    )
    assert status == "mismatch"
    assert record is None

    status, record = store.consume_if_matches(
        "digest",
        '{"params_hash":"expected"}',
        now=1_001,
    )
    assert status == "consumed"
    assert record is not None
    assert record.execution_binding_json == '{"expected":"pending"}'


def test_memory_store_reports_expiry_at_redemption_boundary() -> None:
    store = InMemoryPreviewTokenStore(max_entries=1)
    assert store.issue("digest", 1_001, "request", "{}", now=1_000)

    status, record = store.consume_if_matches(
        "digest",
        "request",
        now=1_001,
    )

    assert status == "expired"
    assert record is None
    assert len(store) == 0
