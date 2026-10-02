"""Structured index metadata returned by adapters and describe_table()."""

import sqlite3

import pytest

from sql_safety_executor.database.outcomes import MetadataQueryError
from tests.support_adapters import MySQLAdapter, SQLiteAdapter


@pytest.fixture
def sqlite_adapter(tmp_path):
    path = tmp_path / "indexes.db"
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER,
            status TEXT,
            created TEXT,
            code TEXT UNIQUE
        );
        CREATE INDEX idx_customer_created ON orders(customer_id, created);
        CREATE INDEX idx_open ON orders(status) WHERE status = 'open';
        CREATE INDEX idx_lower_status ON orders(lower(status), customer_id);
        CREATE INDEX "odd ""name" ON orders(created);
        CREATE TABLE pairs (a TEXT, b TEXT, PRIMARY KEY (a, b)) WITHOUT ROWID;
        CREATE TABLE plain (x INTEGER);
        """
    )
    db.commit()
    db.close()
    adapter = SQLiteAdapter(path)
    adapter.connect()
    yield adapter
    adapter.close()


def test_sqlite_indexes_cover_rowid_composite_unique_partial_and_expression(
    sqlite_adapter,
):
    indexes = sqlite_adapter.get_indexes("orders")
    by_name = {index["name"]: index for index in indexes}

    # The rowid alias has no index entry; a synthesized primary key comes first.
    assert indexes[0] == {
        "name": None,
        "primary": True,
        "unique": True,
        "columns": ["id"],
        "partial": False,
    }
    assert by_name["idx_customer_created"] == {
        "name": "idx_customer_created",
        "primary": False,
        "unique": False,
        "columns": ["customer_id", "created"],
        "partial": False,
    }
    assert by_name["idx_open"]["partial"] is True
    assert by_name["idx_lower_status"]["columns"] == [None, "customer_id"]
    assert by_name["idx_lower_status"]["has_expression"] is True
    assert by_name['odd "name']["columns"] == ["created"]
    autoindex = next(i for i in indexes if i["columns"] == ["code"])
    assert autoindex["unique"] is True and autoindex["primary"] is False
    # Predicates and expressions are not disclosed.
    assert "'open'" not in repr(indexes) and "lower(" not in repr(indexes)


def test_sqlite_indexes_use_real_primary_key_and_empty_tables(sqlite_adapter):
    pairs = sqlite_adapter.get_indexes("pairs")
    assert [i for i in pairs if i["primary"]] == [
        {
            "name": pairs[0]["name"],
            "primary": True,
            "unique": True,
            "columns": ["a", "b"],
            "partial": False,
        }
    ]
    assert pairs[0]["name"] is not None
    assert sqlite_adapter.get_indexes("plain") == []
    with pytest.raises(MetadataQueryError):
        sqlite_adapter.get_indexes("bad;name")


def test_mysql_indexes_map_statistics_rows(monkeypatch):
    adapter = MySQLAdapter()
    calls = []

    def fake_execute(sql, params=None, **_kwargs):
        calls.append((sql, params))
        return [
            ("PRIMARY", 0, 1, "id", "BTREE"),
            ("idx_code_group", 1, 1, "code", "BTREE"),
            ("idx_code_group", 1, 2, "group_no", "BTREE"),
            ("ft_note", 1, 1, "note", "FULLTEXT"),
            ("idx_expr", 1, 1, None, "BTREE"),
            ("ux_source", 0, 1, "source_file", "BTREE"),
        ]

    monkeypatch.setattr(adapter, "execute", fake_execute)
    indexes = adapter.get_indexes("va_table")

    assert [i["name"] for i in indexes] == [
        "PRIMARY",
        "ft_note",
        "idx_code_group",
        "idx_expr",
        "ux_source",
    ]
    by_name = {index["name"]: index for index in indexes}
    assert by_name["PRIMARY"] == {
        "name": "PRIMARY",
        "primary": True,
        "unique": True,
        "columns": ["id"],
    }
    assert by_name["idx_code_group"]["columns"] == ["code", "group_no"]
    assert by_name["ft_note"]["type"] == "FULLTEXT"
    assert by_name["idx_expr"] == {
        "name": "idx_expr",
        "primary": False,
        "unique": False,
        "columns": [None],
        "has_expression": True,
    }
    assert by_name["ux_source"]["unique"] is True
    sql, params = calls[0]
    assert params == {"table_name": "va_table"}
    assert "TABLE_SCHEMA = DATABASE()" in sql and "CARDINALITY" not in sql


def test_mysql_index_failure_is_not_an_empty_list(monkeypatch):
    adapter = MySQLAdapter()
    monkeypatch.setattr(adapter, "execute", lambda *_a, **_k: "Error: denied")
    with pytest.raises(MetadataQueryError):
        adapter.get_indexes("va_table")
    with pytest.raises(MetadataQueryError):
        adapter.get_indexes("bad;name")
