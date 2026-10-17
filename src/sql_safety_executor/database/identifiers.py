from __future__ import annotations

_ASCII_IDENTIFIER_CASE = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def ascii_identifier_lower(name: str) -> str:
    """SQLite identifier comparison folds ASCII, not Python's Unicode case map."""
    return name.translate(_ASCII_IDENTIFIER_CASE)

def _adapter_logging_name(prefix: str, connection_id: str) -> str:
    """Keep legacy default log names, add safe id for named connections."""
    return prefix if connection_id == "default" else f"{prefix}.{connection_id}"
