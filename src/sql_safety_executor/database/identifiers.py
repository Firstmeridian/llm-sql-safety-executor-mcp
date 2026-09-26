from __future__ import annotations
import re
import logging

logger = logging.getLogger(__name__)

METADATA_IDENTIFIER_PATTERN = re.compile(
    r"^[a-zA-Z_\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]{0,63}$"
)


def _adapter_logging_name(prefix: str, connection_id: str) -> str:
    """Keep legacy default log names, add safe id for named connections."""
    return prefix if connection_id == "default" else f"{prefix}.{connection_id}"


def _is_valid_metadata_identifier(identifier: str) -> bool:
    return isinstance(identifier, str) and bool(
        METADATA_IDENTIFIER_PATTERN.fullmatch(identifier)
    )


def _metadata_identifier_is_rejected(identifier: str) -> bool:
    if _is_valid_metadata_identifier(identifier):
        return False
    logger.warning("Invalid metadata identifier rejected at adapter boundary")
    return True


def _quote_sqlite_identifier(identifier: str) -> str:
    if not _is_valid_metadata_identifier(identifier):
        raise ValueError("Invalid metadata identifier")
    return f'"{identifier}"'
