"""Shared reserved read operations; these names never become grants."""

_ACCOUNT_FUNCTIONS = frozenset(
    {"user", "current_user", "session_user", "system_user", "current_role"}
)

_LOCK_FUNCTIONS = frozenset({"get_lock", "release_lock", "release_all_locks"})

_EXPENSIVE_FUNCTIONS = frozenset({"sleep", "benchmark"})

_SQLITE_PRAGMA_OBJECTS = frozenset(
    "pragma_" + name
    for name in """
    analysis_limit application_id auto_vacuum automatic_index busy_timeout
    cache_size cache_spill case_sensitive_like cell_size_check checkpoint_fullfsync
    collation_list compile_options count_changes data_store_directory data_version
    database_list default_cache_size defer_foreign_keys empty_result_callbacks
    encoding foreign_key_check foreign_key_list foreign_keys freelist_count
    full_column_names fullfsync function_list hard_heap_limit ignore_check_constraints
    incremental_vacuum index_info index_list index_xinfo integrity_check journal_mode
    journal_size_limit legacy_alter_table legacy_file_format locking_mode max_page_count
    mmap_size module_list optimize page_count page_size pragma_list query_only quick_check
    read_uncommitted recursive_triggers reverse_unordered_selects schema_version
    secure_delete short_column_names shrink_memory soft_heap_limit stats synchronous
    table_info table_list table_xinfo temp_store temp_store_directory threads
    trusted_schema user_version vdbe_addoptrace vdbe_debug vdbe_listing vdbe_trace
    wal_autocheckpoint wal_checkpoint writable_schema
    """.split()
)
