"""Internal operation ownership; never exposed as a caller-supplied tool flag."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Literal

OperationKind = Literal["trusted", "metadata", "read"]
_operation: ContextVar[OperationKind] = ContextVar("database_operation", default="trusted")
_analysis: ContextVar[object | None] = ContextVar("database_read_analysis", default=None)


@contextmanager
def operation_scope(kind: OperationKind, analysis=None):
    token = _operation.set(kind)
    analysis_token = _analysis.set(analysis)
    try:
        yield
    finally:
        _operation.reset(token)
        _analysis.reset(analysis_token)


def operation_kind() -> OperationKind:
    return _operation.get()


def operation_analysis():
    return _analysis.get()


def exclusive_connection(method):
    """Serialize complete uses of a StaticPool's shared physical connection."""
    @wraps(method)
    def invoke(self, *args, **kwargs):
        with self._operation_lock:
            return method(self, *args, **kwargs)
    return invoke
