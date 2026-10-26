"""analytics-copilot: natural-language-to-SQL assistant over grocery demand aggregates."""

__version__ = "0.1.0"

from copilot.guard import (
    DEFAULT_LIMIT,
    DEFAULT_TIMEOUT_SECONDS,
    ExecutionResult,
    QueryTimeoutError,
    SecurityViolation,
    execute_guarded_sql,
    harden_connection,
    validate_and_rewrite_sql,
)

__all__ = [
    "DEFAULT_LIMIT",
    "DEFAULT_TIMEOUT_SECONDS",
    "ExecutionResult",
    "QueryTimeoutError",
    "SecurityViolation",
    "execute_guarded_sql",
    "harden_connection",
    "validate_and_rewrite_sql",
]
