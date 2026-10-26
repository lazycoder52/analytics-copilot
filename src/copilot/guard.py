"""Guarded SQL parsing, AST validation, rewriting, and safe execution layer.

Enforces strict read-only execution on allowlisted tables using sqlglot AST analysis,
DuckDB engine-level sandbox hardening, automatic LIMIT injection, and execution timeout.

Guard layers:
1. Single SELECT / WITH / set-operation statement (sqlglot AST).
2. Table allowlist with identifier normalization (quoted lookalikes rejected).
3. Function allowlist (aggregates, window, math, string, date/time, conditional, cast).
4. Blocked catalogs (information_schema, duckdb_*, pragma_*, sqlite_master).
5. Resource guards (generate_series / range, AST depth cap).
6. Engine hardening: enable_external_access=false, memory_limit, threads, then
   lock_configuration=true so later SET cannot undo the sandbox.
7. Execution timeout via con.interrupt.
"""

from __future__ import annotations

import logging
import re
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
DEFAULT_MEMORY_LIMIT = "256MB"
DEFAULT_THREADS = 2
MAX_AST_DEPTH = 48

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

# Normalized (lowercase, no underscores) function names permitted in SELECT queries.
_ALLOWED_FUNCTION_NAMES = frozenset(
    n.lower().replace("_", "")
    for n in (
        # Aggregates
        "count",
        "sum",
        "avg",
        "mean",
        "min",
        "max",
        "median",
        "mode",
        "stddev",
        "stddev_pop",
        "stddev_samp",
        "std",
        "variance",
        "var_pop",
        "var_samp",
        "corr",
        "covar_pop",
        "covar_samp",
        "string_agg",
        "group_concat",
        "list_agg",
        "listagg",
        "array_agg",
        "bool_and",
        "bool_or",
        "bit_and",
        "bit_or",
        "any_value",
        "first",
        "last",
        "arg_min",
        "argmin",
        "arg_max",
        "argmax",
        "count_if",
        "approx_count_distinct",
        "approx_quantile",
        "quantile",
        "quantile_cont",
        "quantile_disc",
        "histogram",
        "kurtosis",
        "skewness",
        # Window
        "row_number",
        "rank",
        "dense_rank",
        "percent_rank",
        "cume_dist",
        "ntile",
        "lag",
        "lead",
        "first_value",
        "last_value",
        "nth_value",
        # Math
        "abs",
        "ceil",
        "ceiling",
        "floor",
        "round",
        "trunc",
        "truncate",
        "sqrt",
        "cbrt",
        "pow",
        "power",
        "exp",
        "ln",
        "log",
        "log2",
        "log10",
        "sign",
        "mod",
        "pi",
        "radians",
        "degrees",
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan",
        "atan2",
        "cot",
        "factorial",
        "gcd",
        "lcm",
        "greatest",
        "least",
        "random",
        "isfinite",
        "isinf",
        "isnan",
        # String
        "lower",
        "upper",
        "trim",
        "ltrim",
        "rtrim",
        "length",
        "len",
        "strlen",
        "char_length",
        "character_length",
        "octet_length",
        "concat",
        "concat_ws",
        "substr",
        "substring",
        "replace",
        "left",
        "right",
        "position",
        "strpos",
        "instr",
        "starts_with",
        "ends_with",
        "contains",
        "prefix",
        "suffix",
        "regexp_matches",
        "regexp_replace",
        "regexp_extract",
        "regexp_extract_all",
        "split_part",
        "string_split",
        "reverse",
        "repeat",
        "lpad",
        "rpad",
        "ascii",
        "chr",
        "md5",
        "format",
        "printf",
        "translate",
        "initcap",
        "like",
        "ilike",
        # Date / time
        "date_trunc",
        "timestamp_trunc",
        "date_part",
        "datepart",
        "date_diff",
        "datediff",
        "date_add",
        "dateadd",
        "extract",
        "year",
        "month",
        "day",
        "hour",
        "minute",
        "second",
        "week",
        "quarter",
        "epoch",
        "age",
        "current_date",
        "current_timestamp",
        "current_time",
        "localtimestamp",
        "localtime",
        "now",
        "today",
        "strftime",
        "strptime",
        "make_date",
        "make_time",
        "make_timestamp",
        "to_timestamp",
        "to_date",
        "last_day",
        "date",
        "time",
        "timestamp",
        # Conditional / logical / null
        "and",
        "or",
        "xor",
        "not",
        "is",
        "in",
        "between",
        "exists",
        "coalesce",
        "nullif",
        "if",
        "ifnull",
        "iff",
        "case",
        "nvl",
        "nvl2",
        "filter",
        "within_group",
        # Cast / type
        "cast",
        "try_cast",
        "typeof",
    )
)

_SAFE_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ALLOWED_SCHEMAS = frozenset({"", "main"})
_ALLOWED_CATALOGS = frozenset({"", "memory", "main"})
_BLOCKED_TABLE_NAMES = frozenset(
    {
        "sqlite_master",
        "sqlite_temp_master",
        "sqlite_sequence",
        "information_schema",
    }
)
_RESOURCE_FUNCTIONS = frozenset({"generateseries", "range"})


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


def harden_connection(
    con: duckdb.DuckDBPyConnection,
    memory_limit: str = DEFAULT_MEMORY_LIMIT,
    threads: int = DEFAULT_THREADS,
) -> None:
    """Harden a DuckDB connection against filesystem, resource, and configuration abuse.

    Sets ``memory_limit`` (default 256MB) and ``threads`` (default 2) first, then disables
    external access and locks configuration so later SET statements cannot undo the sandbox.
    """
    con.execute(f"SET memory_limit = '{memory_limit}';")
    con.execute(f"SET threads = {int(threads)};")
    con.execute("SET enable_external_access = false;")
    con.execute("SET lock_configuration = true;")


def _normalize_func_token(name: str) -> str:
    return name.lower().replace("_", "").replace(" ", "")


def _function_tokens(func: exp.Func) -> list[str]:
    tokens: list[str] = []
    raw = (func.name or "").strip()
    if raw and raw != "*" and _SAFE_IDENT_RE.match(raw):
        tokens.append(raw)
    if isinstance(func, exp.Anonymous):
        if func.name:
            tokens.append(func.name)
    else:
        sql_name = func.sql_name() if hasattr(func, "sql_name") else ""
        if sql_name and sql_name.lower() != "anonymous":
            tokens.append(sql_name)
        key = getattr(func, "key", None)
        if key:
            tokens.append(str(key))
    # Preserve order, drop empties
    seen: set[str] = set()
    unique: list[str] = []
    for token in tokens:
        lowered = token.lower()
        if lowered and lowered not in seen:
            seen.add(lowered)
            unique.append(token)
    return unique


def _display_func_name(func: exp.Func) -> str:
    tokens = _function_tokens(func)
    return tokens[0] if tokens else type(func).__name__


def _ast_depth(node: exp.Expression, depth: int = 0) -> int:
    deepest = depth
    for child in node.iter_expressions():
        deepest = max(deepest, _ast_depth(child, depth + 1))
    return deepest


def _check_forbidden_nodes(ast: exp.Expression) -> None:
    """Traverse the AST to ensure no disallowed expression nodes exist anywhere in the tree."""
    for node in ast.walk():
        if isinstance(node, DISALLOWED_EXPRESSION_TYPES):
            raise SecurityViolation(f"Disallowed operation detected: {type(node).__name__.upper()}")


def _check_functions(ast: exp.Expression) -> None:
    """Allow only analytics functions; reject catalogs, scanners, and resource generators."""
    for func in ast.find_all(exp.Func):
        tokens = _function_tokens(func)
        display = _display_func_name(func)
        normalized = {_normalize_func_token(t) for t in tokens}
        lowered = [t.lower() for t in tokens]
        if any(t.startswith("duckdb_") or t.startswith("pragma_") for t in lowered):
            raise SecurityViolation(f"System catalog function blocked: {display}()")
        if normalized & _RESOURCE_FUNCTIONS:
            raise SecurityViolation(
                f"Resource-exhaustion function blocked: {display}(); "
                "generate_series/range/repeat table generation is not permitted"
            )
        if not normalized or normalized.isdisjoint(_ALLOWED_FUNCTION_NAMES):
            raise SecurityViolation(f"Function not in allowlist: {display}()")

    for anon in ast.find_all(exp.Anonymous):
        name = (anon.name or "").lower()
        if not name:
            continue
        if name.startswith("duckdb_") or name.startswith("pragma_"):
            raise SecurityViolation(f"System catalog function blocked: {name}()")
        if _normalize_func_token(name) not in _ALLOWED_FUNCTION_NAMES:
            raise SecurityViolation(f"Function not in allowlist: {name}()")


def _validate_identifier(raw_name: str, *, quoted: bool) -> str:
    """Return a canonical table name or raise if the identifier is a lookalike / path."""
    if quoted and raw_name != raw_name.strip():
        raise SecurityViolation(f"Quoted identifier is not an allowlisted name: {raw_name!r}")
    if any(char in raw_name for char in ("/", "\\", ".", " ", "\t", "\n", "\r", "\x00", "'", ";")):
        raise SecurityViolation(f"Direct file or path reference blocked: {raw_name}")
    if not _SAFE_IDENT_RE.match(raw_name):
        raise SecurityViolation(f"Quoted identifier is not an allowlisted name: {raw_name!r}")
    return raw_name.lower()


def _validate_tables_and_ctes(ast: exp.Expression, allowlisted_tables: set[str]) -> None:
    """Validate that every table reference resolves to an allowlisted table or a valid CTE alias."""
    cte_aliases: set[str] = set()
    for cte in ast.find_all(exp.CTE):
        if cte.alias:
            cte_aliases.add(cte.alias.lower())

    for table in ast.find_all(exp.Table):
        raw_name = table.name
        this_node = table.this
        catalog = (table.catalog or "").lower()
        schema = (table.db or "").lower()

        if catalog not in _ALLOWED_CATALOGS:
            raise SecurityViolation(f"Catalog not permitted: {table.catalog}")
        if schema not in _ALLOWED_SCHEMAS:
            raise SecurityViolation(f"Schema not permitted: {table.db}")
        if schema in {"information_schema"} or catalog in {"information_schema"}:
            raise SecurityViolation("information_schema catalog access is blocked")

        if isinstance(this_node, exp.Literal) and this_node.is_string:
            raise SecurityViolation(f"Quoted-path file scans are blocked: {this_node.this}")

        if isinstance(this_node, (exp.Func, exp.Anonymous, exp.ReadParquet, exp.ReadCSV)):
            if isinstance(this_node, exp.Func):
                func_name = _display_func_name(this_node)
            else:
                func_name = type(this_node).__name__
            raise SecurityViolation(f"Table function blocked: {func_name}")

        if not raw_name:
            raise SecurityViolation("Unnamed or function-derived table scan is not permitted")

        quoted = isinstance(this_node, exp.Identifier) and bool(this_node.quoted)
        lower_name = _validate_identifier(raw_name, quoted=quoted)

        if (
            lower_name in _BLOCKED_TABLE_NAMES
            or lower_name.startswith("duckdb_")
            or lower_name.startswith("pragma_")
            or lower_name.startswith("sqlite_")
        ):
            raise SecurityViolation(f"System catalog table blocked: {raw_name}")

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

    depth = _ast_depth(ast)
    if depth > MAX_AST_DEPTH:
        raise SecurityViolation(f"Expression nesting exceeds maximum depth of {MAX_AST_DEPTH}")

    _check_forbidden_nodes(ast)
    _check_functions(ast)

    if allowlisted_tables is None:
        allowed = {t.lower() for t in ALL_TABLE_NAMES}
    else:
        allowed = {t.lower() for t in allowlisted_tables}

    _validate_tables_and_ctes(ast, allowed)

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
