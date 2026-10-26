"""Guarded SQL parsing, AST validation, rewriting, and safe execution layer.

Enforces strict read-only execution on allowlisted tables using sqlglot AST analysis,
DuckDB engine-level sandbox hardening (enable_external_access=false, lock_configuration),
automatic LIMIT injection, and execution timeout protection.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import duckdb
import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from copilot.catalog import ALL_TABLE_NAMES

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 100
DEFAULT_TIMEOUT_SECONDS = 10.0

# Forbidden root / nested expression types (DDL, DML, Administrative, Ingestion, Transaction)
DISALLOWED_EXPRESSION_TYPES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Command,
    exp.Pragma,
    exp.Copy,
    exp.Attach,
    exp.Detach,
    exp.Set,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Schema,
)

# Forbidden table/file/URL/system functions
BLOCKED_FUNCTION_NAMES = frozenset(
    {
        "read_parquet",
        "read_csv",
        "read_csv_auto",
        "read_json",
        "read_json_auto",
        "read_text",
        "read_blob",
        "scan_parquet",
        "scan_csv",
        "parquet_scan",
        "csv_scan",
        "glob",
        "httpfs",
        "http",
        "https",
        "query",
        "python",
        "load",
        "install",
        "current_setting",
        "set_variable",
        "get_variable",
    }
)


class SecurityViolation(ValueError):
    """Raised when an SQL query violates security, AST guard, or table allowlist policies."""


class QueryTimeoutError(TimeoutError):
    """Raised when an SQL query exceeds the configured timeout duration."""


@dataclass(frozen=True)
class ExecutionResult:
    """Encapsulates the output and performance metrics of a successfully executed query."""

    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    row_count: int
    duration_ms: float
    sql: str


def harden_connection(con: duckdb.DuckDBPyConnection) -> None:
    """Harden a DuckDB connection against out-of-band filesystem and configuration tampering.

    Disables external access and locks configuration settings permanently for the session.
    """
    con.execute("SET enable_external_access = false;")
    con.execute("SET lock_configuration = true;")


def _check_forbidden_nodes(ast: exp.Expression) -> None:
    """Traverse the AST to ensure no disallowed expression nodes exist anywhere in the tree."""
    for node in ast.walk():
        if isinstance(node, DISALLOWED_EXPRESSION_TYPES):
            raise SecurityViolation(f"Disallowed operation detected: {type(node).__name__.upper()}")
        # Check command/install/load specifically
        if isinstance(node, exp.Command):
            raise SecurityViolation(f"Administrative command detected: {node.sql()}")


def _check_functions(ast: exp.Expression) -> None:
    """Ensure no blocked file/URL/system functions or duckdb_/pragma_ functions are invoked."""
    for func in ast.find_all(exp.Func):
        name = (func.name or func.sql_name() or "").lower()
        if not name and isinstance(func, exp.Anonymous):
            name = (func.name or "").lower()

        # Check against blocked list
        if name in BLOCKED_FUNCTION_NAMES:
            raise SecurityViolation(f"Blocked function invocation: {name}()")

        # Check for duckdb_ or pragma_ system functions
        if name.startswith("duckdb_") or name.startswith("pragma_"):
            raise SecurityViolation(f"System catalog function blocked: {name}()")

    for anon in ast.find_all(exp.Anonymous):
        name = (anon.name or "").lower()
        if name in BLOCKED_FUNCTION_NAMES:
            raise SecurityViolation(f"Blocked function invocation: {name}()")
        if name.startswith("duckdb_") or name.startswith("pragma_"):
            raise SecurityViolation(f"System catalog function blocked: {name}()")


def _validate_tables_and_ctes(ast: exp.Expression, allowlisted_tables: set[str]) -> None:
    """Validate that every table reference resolves to an allowlisted table or a valid CTE alias.

    Detects file-path scans (e.g. 'file.parquet'), functions as tables, and non-allowlisted tables.
    """
    # Track CTE aliases defined in the query
    cte_aliases: set[str] = set()
    for cte in ast.find_all(exp.CTE):
        if cte.alias:
            cte_aliases.add(cte.alias.lower())

    for table in ast.find_all(exp.Table):
        # In sqlglot, table.this may be an Identifier, a Literal/string, or a Function/Anonymous
        raw_name = table.name
        this_node = table.this

        # If table scan is a string literal (e.g. FROM 'file.parquet')
        if isinstance(this_node, exp.Literal) and this_node.is_string:
            raise SecurityViolation(f"Quoted-path file scans are blocked: {this_node.this}")

        # Check if table name indicates a file or path
        if any(char in raw_name for char in ("/", "\\", ".")):
            raise SecurityViolation(f"Direct file or path reference blocked: {raw_name}")

        # Check if the table expression is actually a function (e.g. FROM read_parquet(...))
        if isinstance(this_node, (exp.Func, exp.Anonymous, exp.ReadParquet, exp.ReadCSV)):
            func_name = (
                this_node.sql_name()
                if hasattr(this_node, "sql_name") and callable(this_node.sql_name)
                else type(this_node).__name__
            )
            raise SecurityViolation(f"Table function blocked: {func_name}")

        lower_name = raw_name.lower()
        if not lower_name:
            # Table node without name (e.g. derived table function)
            raise SecurityViolation("Unnamed or function-derived table scan is not permitted")

        # Must be in allowlist or a valid CTE alias
        if lower_name not in allowlisted_tables and lower_name not in cte_aliases:
            raise SecurityViolation(f"Table not in allowlist: {raw_name}")


def _inject_limit_if_absent(ast: exp.Expression, default_limit: int) -> exp.Expression:
    """Inject a LIMIT clause if the outermost query lacks one."""
    if (
        isinstance(ast, (exp.Select, exp.Union, exp.Intersect, exp.Except))
        and ast.args.get("limit") is None
    ):
        return ast.limit(default_limit)
    return ast


def validate_and_rewrite_sql(
    sql: str,
    allowlisted_tables: Sequence[str] | set[str] | None = None,
    default_limit: int = DEFAULT_LIMIT,
) -> str:
    """Parse, validate, guard, and rewrite an SQL query string.

    Args:
        sql: The user-supplied or LLM-generated SQL query.
        allowlisted_tables: Set of allowed base table names. Defaults to ALL_TABLE_NAMES.
        default_limit: Default LIMIT to inject if absent.

    Returns:
        Guarded, rewritten SQL string ready for safe execution.

    Raises:
        SecurityViolation: If the query violates syntax, statement-count, AST, or allowlist rules.
    """
    if not sql or not sql.strip():
        raise SecurityViolation("Query string is empty")

    try:
        statements = sqlglot.parse(sql, read="duckdb")
    except ParseError as err:
        raise SecurityViolation(f"SQL parse error: {err}") from err
    except Exception as err:
        raise SecurityViolation(f"Failed to parse SQL: {err}") from err

    # Filter out empty statements and trailing semicolons (e.g. Semicolon nodes)
    active_statements = [
        s for s in statements if s is not None and not isinstance(s, exp.Semicolon)
    ]
    if len(active_statements) == 0:
        raise SecurityViolation("No valid SQL statement found")
    if len(active_statements) > 1:
        raise SecurityViolation(
            f"Multiple statements are not allowed ({len(active_statements)} found)"
        )

    ast = active_statements[0]

    # Validate that root expression is a query statement (SELECT / WITH / UNION)
    if not isinstance(ast, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise SecurityViolation(
            f"Only SELECT or WITH queries are permitted; got {type(ast).__name__}"
        )

    # Deep AST checks
    _check_forbidden_nodes(ast)
    _check_functions(ast)

    # Normalize allowlist
    if allowlisted_tables is None:
        allowed = {t.lower() for t in ALL_TABLE_NAMES}
    else:
        allowed = {t.lower() for t in allowlisted_tables}

    _validate_tables_and_ctes(ast, allowed)

    # Inject LIMIT if absent
    ast_with_limit = _inject_limit_if_absent(ast, default_limit)

    return ast_with_limit.sql(dialect="duckdb")


def execute_guarded_sql(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    allowlisted_tables: Sequence[str] | set[str] | None = None,
    default_limit: int = DEFAULT_LIMIT,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> ExecutionResult:
    """Validate, rewrite, and safely execute a query against DuckDB with timeout protection.

    Args:
        con: Active DuckDB connection (should be hardened).
        sql: Raw SQL query string.
        allowlisted_tables: Optional allowlist of table names.
        default_limit: Row limit to inject if none present.
        timeout_seconds: Maximum allowed query duration before interrupt.

    Returns:
        ExecutionResult containing columns, rows, row count, duration, and final SQL.

    Raises:
        SecurityViolation: If validation fails.
        QueryTimeoutError: If execution exceeds timeout_seconds.
        duckdb.Error: If the SQL fails execution in DuckDB.
    """
    guarded_sql = validate_and_rewrite_sql(sql, allowlisted_tables, default_limit)

    timer = threading.Timer(timeout_seconds, con.interrupt)
    timer.daemon = True
    start_time = time.perf_counter()
    timer.start()

    try:
        cursor = con.execute(guarded_sql)
        rows_list = cursor.fetchall()
        columns = tuple(desc[0] for desc in cursor.description) if cursor.description else ()
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        return ExecutionResult(
            columns=columns,
            rows=tuple(rows_list),
            row_count=len(rows_list),
            duration_ms=round(duration_ms, 2),
            sql=guarded_sql,
        )
    except duckdb.InterruptException as err:
        raise QueryTimeoutError(
            f"Query execution exceeded timeout limit of {timeout_seconds:.1f}s"
        ) from err
    finally:
        timer.cancel()
