"""analytics-copilot: natural-language-to-SQL assistant over grocery demand aggregates."""

__version__ = "0.1.0"

from copilot.guard import (
    DEFAULT_LIMIT,
    DEFAULT_MEMORY_LIMIT,
    DEFAULT_THREADS,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_AST_DEPTH,
    ExecutionResult,
    QueryTimeoutError,
    SecurityViolation,
    execute_guarded_sql,
    harden_connection,
    validate_and_rewrite_sql,
)

__all__ = [
    "DEFAULT_LIMIT",
    "DEFAULT_MEMORY_LIMIT",
    "DEFAULT_THREADS",
    "DEFAULT_TIMEOUT_SECONDS",
    "ExecutionResult",
    "MAX_AST_DEPTH",
    "QueryTimeoutError",
    "SecurityViolation",
    "execute_guarded_sql",
    "harden_connection",
    "validate_and_rewrite_sql",
]
