"""Comprehensive attack and edge case tests for guarded SQL execution (Phase 2)."""

from __future__ import annotations

import pytest

from copilot.data import load_database
from copilot.guard import (
    ExecutionResult,
    QueryTimeoutError,
    SecurityViolation,
    execute_guarded_sql,
    validate_and_rewrite_sql,
)

ALLOWLIST = {
    "weekly_store_family_summary",
    "promo_elasticity_summary",
    "zero_sales_day_proxy_summary",
    "perishable_volatility_summary",
    "sim_policy_summary",
}


@pytest.fixture(scope="module")
def con():
    """Module-level hardened DuckDB connection."""
    connection = load_database(harden=True)
    yield connection
    connection.close()


# ---------------------------------------------------------------------------
# Required Attack Vector Tests
# ---------------------------------------------------------------------------


def test_attack_quoted_path_scan():
    """Attack: SELECT * FROM 'file.parquet' (direct quoted-path file scan)."""
    with pytest.raises(SecurityViolation, match="(?i)quoted-path|file|allowlist"):
        validate_and_rewrite_sql(
            "SELECT * FROM 'data/weekly_store_family_summary.parquet'", ALLOWLIST
        )


def test_attack_read_parquet():
    """Attack: SELECT * FROM read_parquet(...)."""
    with pytest.raises(SecurityViolation, match="(?i)read_parquet|table function|allowlist"):
        validate_and_rewrite_sql(
            "SELECT * FROM read_parquet('data/weekly_store_family_summary.parquet')",
            ALLOWLIST,
        )


def test_attack_read_csv():
    """Attack: SELECT * FROM read_csv(...)."""
    with pytest.raises(SecurityViolation, match="(?i)read_csv|table function|allowlist"):
        validate_and_rewrite_sql("SELECT * FROM read_csv('secret.csv')", ALLOWLIST)


def test_attack_glob():
    """Attack: SELECT * FROM glob(...)."""
    with pytest.raises(SecurityViolation, match="(?i)glob|table function|allowlist"):
        validate_and_rewrite_sql("SELECT * FROM glob('*.parquet')", ALLOWLIST)


def test_attack_copy():
    """Attack: COPY weekly_store_family_summary TO 'dump.parquet'."""
    with pytest.raises(SecurityViolation, match="(?i)copy|disallowed"):
        validate_and_rewrite_sql(
            "COPY weekly_store_family_summary TO 'dump.parquet'",
            ALLOWLIST,
        )


def test_attack_attach():
    """Attack: ATTACH 'evil.db' AS evil."""
    with pytest.raises(SecurityViolation, match="(?i)attach|disallowed"):
        validate_and_rewrite_sql("ATTACH 'evil.db' AS evil", ALLOWLIST)


def test_attack_pragma():
    """Attack: PRAGMA version or PRAGMA database_list."""
    with pytest.raises(SecurityViolation, match="(?i)pragma|disallowed"):
        validate_and_rewrite_sql("PRAGMA version", ALLOWLIST)


def test_attack_set():
    """Attack: SET enable_external_access = true."""
    with pytest.raises(SecurityViolation, match="(?i)set|disallowed"):
        validate_and_rewrite_sql("SET enable_external_access = true", ALLOWLIST)


def test_attack_install_and_load():
    """Attack: INSTALL httpfs or LOAD httpfs."""
    with pytest.raises(SecurityViolation, match="(?i)install|load|command|disallowed"):
        validate_and_rewrite_sql("INSTALL httpfs", ALLOWLIST)
    with pytest.raises(SecurityViolation, match="(?i)install|load|command|disallowed"):
        validate_and_rewrite_sql("LOAD httpfs", ALLOWLIST)


def test_attack_duckdb_system_functions():
    """Attack: duckdb_* system functions in FROM or SELECT expressions."""
    with pytest.raises(SecurityViolation, match="(?i)duckdb_|system catalog"):
        validate_and_rewrite_sql("SELECT * FROM duckdb_tables()", ALLOWLIST)
    with pytest.raises(SecurityViolation, match="(?i)duckdb_|system catalog"):
        validate_and_rewrite_sql("SELECT duckdb_memory()", ALLOWLIST)
    with pytest.raises(
        SecurityViolation, match="(?i)duckdb_|system catalog|blocked function|allowlist"
    ):
        validate_and_rewrite_sql("SELECT current_setting('enable_external_access')", ALLOWLIST)


def test_attack_multiple_statements():
    """Attack: Multiple statements separated by semicolon."""
    sql = "SELECT 1 FROM weekly_store_family_summary; DROP TABLE weekly_store_family_summary;"
    with pytest.raises(SecurityViolation, match="(?i)multiple statements"):
        validate_and_rewrite_sql(sql, ALLOWLIST)


def test_attack_comments_hiding_second_statement():
    """Attack: Comments hiding a second statement."""
    sql1 = (
        "SELECT 1 FROM weekly_store_family_summary -- comment\n"
        "; DROP TABLE weekly_store_family_summary;"
    )
    with pytest.raises(SecurityViolation, match="(?i)multiple statements|hidden statement"):
        validate_and_rewrite_sql(sql1, ALLOWLIST)

    sql2 = (
        "SELECT 1 FROM weekly_store_family_summary /* comment */"
        "; DROP TABLE weekly_store_family_summary;"
    )
    with pytest.raises(SecurityViolation, match="(?i)multiple statements|hidden statement"):
        validate_and_rewrite_sql(sql2, ALLOWLIST)


def test_attack_cte_referencing_non_allowlisted_table():
    """Attack: A CTE that references a non-allowlisted table."""
    with pytest.raises(SecurityViolation, match="(?i)not in allowlist.*secret_table"):
        validate_and_rewrite_sql(
            "WITH evil_cte AS (SELECT * FROM secret_table) SELECT * FROM evil_cte",
            ALLOWLIST,
        )


# ---------------------------------------------------------------------------
# Additional DDL / DML / Edge Attack Tests (reaches >= 20 attack tests)
# ---------------------------------------------------------------------------


def test_attack_drop_table():
    """Attack: DROP TABLE."""
    with pytest.raises(SecurityViolation, match="(?i)drop|disallowed"):
        validate_and_rewrite_sql("DROP TABLE weekly_store_family_summary", ALLOWLIST)


def test_attack_create_table():
    """Attack: CREATE TABLE."""
    with pytest.raises(SecurityViolation, match="(?i)create|disallowed"):
        validate_and_rewrite_sql(
            "CREATE TABLE backdoor AS SELECT * FROM weekly_store_family_summary",
            ALLOWLIST,
        )


def test_attack_alter_table():
    """Attack: ALTER TABLE."""
    with pytest.raises(SecurityViolation, match="(?i)alter|disallowed"):
        validate_and_rewrite_sql(
            "ALTER TABLE weekly_store_family_summary RENAME TO hacked",
            ALLOWLIST,
        )


def test_attack_insert():
    """Attack: INSERT INTO table."""
    sql = (
        "INSERT INTO weekly_store_family_summary "
        "VALUES (1, 'Quito', 'P', 'A', 1, 'DAIRY', '2023-01-01', 0, 0, 0, 0, 0, 0, 0, 0, 0)"
    )
    with pytest.raises(SecurityViolation, match="(?i)insert|disallowed"):
        validate_and_rewrite_sql(sql, ALLOWLIST)


def test_attack_update():
    """Attack: UPDATE table."""
    with pytest.raises(SecurityViolation, match="(?i)update|disallowed"):
        validate_and_rewrite_sql(
            "UPDATE weekly_store_family_summary SET total_sales = 0",
            ALLOWLIST,
        )


def test_attack_delete():
    """Attack: DELETE FROM table."""
    with pytest.raises(SecurityViolation, match="(?i)delete|disallowed"):
        validate_and_rewrite_sql("DELETE FROM weekly_store_family_summary", ALLOWLIST)


def test_attack_detach():
    """Attack: DETACH DATABASE."""
    with pytest.raises(SecurityViolation, match="(?i)detach|disallowed"):
        validate_and_rewrite_sql("DETACH DATABASE evil", ALLOWLIST)


def test_attack_cte_hiding_dml():
    """Attack: WITH clause attempting to run an INSERT or UPDATE."""
    sql = "WITH cte AS (SELECT 1) INSERT INTO weekly_store_family_summary SELECT * FROM cte"
    with pytest.raises(SecurityViolation, match="(?i)insert|disallowed"):
        validate_and_rewrite_sql(sql, ALLOWLIST)


def test_attack_subquery_referencing_non_allowlisted_table():
    """Attack: Subquery referencing an unapproved table."""
    with pytest.raises(SecurityViolation, match="(?i)not in allowlist.*unauthorized_table"):
        validate_and_rewrite_sql(
            "SELECT * FROM (SELECT * FROM unauthorized_table) AS sub",
            ALLOWLIST,
        )


def test_attack_blocked_function_in_where_clause():
    """Attack: Disallowed function hidden inside WHERE clause."""
    sql = (
        "SELECT * FROM weekly_store_family_summary "
        "WHERE total_sales > (SELECT count(*) FROM read_csv('foo.csv'))"
    )
    with pytest.raises(SecurityViolation, match="(?i)read_csv|blocked function"):
        validate_and_rewrite_sql(sql, ALLOWLIST)


def test_attack_quoted_csv_path():
    """Attack: Quoted CSV path scan."""
    with pytest.raises(SecurityViolation, match="(?i)quoted-path|file|allowlist"):
        validate_and_rewrite_sql("SELECT * FROM 'secret.csv'", ALLOWLIST)


def test_edge_empty_and_whitespace_query():
    """Edge case: Empty or whitespace query."""
    with pytest.raises(SecurityViolation, match="(?i)empty"):
        validate_and_rewrite_sql("", ALLOWLIST)
    with pytest.raises(SecurityViolation, match="(?i)empty"):
        validate_and_rewrite_sql("   \n\t  ", ALLOWLIST)


def test_edge_syntax_error():
    """Edge case: Syntax error or unparseable SQL."""
    with pytest.raises(SecurityViolation, match="(?i)parse error|failed to parse"):
        validate_and_rewrite_sql("SELECT * FROM WHERE ORDER BY ;;;", ALLOWLIST)


# ---------------------------------------------------------------------------
# LIMIT Injection & Query Rewriting Tests
# ---------------------------------------------------------------------------


def test_limit_injected_when_absent():
    """Verify LIMIT is injected if absent."""
    rewritten = validate_and_rewrite_sql(
        "SELECT * FROM weekly_store_family_summary",
        ALLOWLIST,
        default_limit=100,
    )
    assert "LIMIT 100" in rewritten.upper()


def test_existing_limit_preserved():
    """Verify existing user-specified LIMIT is preserved."""
    rewritten = validate_and_rewrite_sql(
        "SELECT * FROM weekly_store_family_summary LIMIT 25",
        ALLOWLIST,
        default_limit=100,
    )
    assert "LIMIT 25" in rewritten.upper()
    assert "LIMIT 100" not in rewritten.upper()


def test_semicolon_inside_string_literal_allowed():
    """Semicolons inside string literals should not be flagged as multiple statements."""
    rewritten = validate_and_rewrite_sql(
        "SELECT 'part1; part2' AS combined_val FROM weekly_store_family_summary",
        ALLOWLIST,
    )
    assert "combined_val" in rewritten


# ---------------------------------------------------------------------------
# Execution, Timeout, and Engine Sandbox Tests
# ---------------------------------------------------------------------------


def test_successful_guarded_execution(con):
    """Verify legitimate query executes and returns ExecutionResult."""
    sql = (
        "SELECT family, SUM(total_sales) AS total "
        "FROM weekly_store_family_summary "
        "GROUP BY family LIMIT 5"
    )
    result = execute_guarded_sql(con, sql, ALLOWLIST)
    assert isinstance(result, ExecutionResult)
    assert result.columns == ("family", "total")
    assert result.row_count == 5
    assert len(result.rows) == 5
    assert result.duration_ms >= 0


def test_valid_cte_execution(con):
    """Verify query with legitimate CTE executes properly."""
    sql = """
    WITH filtered AS (
        SELECT store_nbr, family, total_sales
        FROM weekly_store_family_summary
        WHERE total_sales > 1000
    )
    SELECT store_nbr, count(*) AS count_high_sales
    FROM filtered
    GROUP BY store_nbr
    ORDER BY count_high_sales DESC
    LIMIT 3
    """
    result = execute_guarded_sql(con, sql, ALLOWLIST)
    assert result.row_count <= 3
    assert "count_high_sales" in result.columns


def test_query_timeout(con):
    """Verify runaway queries trigger QueryTimeoutError."""
    # Cross join generating billions of rows on allowlisted table with short timeout
    runaway_sql = """
    SELECT count(*)
    FROM weekly_store_family_summary w1
    CROSS JOIN weekly_store_family_summary w2
    """
    with pytest.raises(QueryTimeoutError, match="(?i)exceeded timeout"):
        execute_guarded_sql(
            con,
            runaway_sql,
            allowlisted_tables=ALLOWLIST,
            timeout_seconds=0.2,
        )


def test_duckdb_sandbox_engine_hardening(con):
    """Verify DuckDB rejects external access and locked configuration at the engine level."""
    # Attempting to re-enable external access must fail
    with pytest.raises(Exception, match="(?i)configuration has been locked"):
        con.execute("SET enable_external_access = true;")
    with pytest.raises(Exception, match="(?i)configuration has been locked"):
        con.execute("SET memory_limit = '8GB';")
    with pytest.raises(Exception, match="(?i)configuration has been locked"):
        con.execute("SET threads = 64;")


def test_harden_connection_sets_memory_and_threads():
    """memory_limit=256MB and threads=2 are applied before lock_configuration."""
    import duckdb

    from copilot.guard import DEFAULT_MEMORY_LIMIT, DEFAULT_THREADS, harden_connection

    raw = duckdb.connect(":memory:")
    try:
        harden_connection(raw)
        memory = str(raw.execute("SELECT current_setting('memory_limit')").fetchone()[0])
        threads = raw.execute("SELECT current_setting('threads')").fetchone()[0]
        # DuckDB reports 256MB as ~244 MiB.
        assert "mib" in memory.lower() or "mb" in memory.lower()
        numeric = float(memory.lower().replace("mib", "").replace("mb", "").strip())
        assert 200 <= numeric <= 256
        assert int(threads) == DEFAULT_THREADS
        assert DEFAULT_MEMORY_LIMIT == "256MB"
    finally:
        raw.close()


# ---------------------------------------------------------------------------
# Phase 2.5 additional attack tests (function allowlist, catalogs, resources)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT read_text('C:/Windows/win.ini')",
        "SELECT read_blob('C:/Windows/win.ini')",
        "SELECT * FROM parquet_scan('x.parquet')",
        "SELECT parquet_metadata('x.parquet')",
        "SELECT parquet_schema('x.parquet')",
        "SELECT * FROM sniff_csv('x.csv')",
        "SELECT query('SELECT 1')",
        "SELECT query_table('weekly_store_family_summary')",
        "SELECT getenv('PATH')",
        "SELECT current_query()",
        "SELECT version()",
    ],
)
def test_attack_blocked_or_non_allowlisted_functions(sql):
    with pytest.raises(SecurityViolation, match="(?i)allowlist|blocked|table function"):
        validate_and_rewrite_sql(sql, ALLOWLIST)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM information_schema.columns",
        "SELECT * FROM duckdb_tables",
        "SELECT * FROM duckdb_columns()",
        "SELECT * FROM pragma_database_list()",
        "SELECT * FROM pragma_table_info('weekly_store_family_summary')",
        "SELECT * FROM sqlite_master",
        "SELECT sql FROM sqlite_temp_master",
    ],
)
def test_attack_system_catalog_tables(sql):
    with pytest.raises(
        SecurityViolation,
        match="(?i)information_schema|schema not permitted|system catalog|allowlist|table function",
    ):
        validate_and_rewrite_sql(sql, ALLOWLIST)


def test_attack_generate_series_and_range_cross_join():
    with pytest.raises(SecurityViolation, match="(?i)generate_series|range|resource"):
        validate_and_rewrite_sql("SELECT * FROM generate_series(1, 100000000)", ALLOWLIST)
    with pytest.raises(SecurityViolation, match="(?i)generate_series|range|resource"):
        validate_and_rewrite_sql("SELECT * FROM range(1, 100000000)", ALLOWLIST)
    with pytest.raises(SecurityViolation, match="(?i)generate_series|range|resource"):
        validate_and_rewrite_sql(
            "SELECT * FROM weekly_store_family_summary CROSS JOIN generate_series(1, 1000000)",
            ALLOWLIST,
        )


def test_attack_deeply_nested_expression():
    nested = "1"
    for _ in range(60):
        nested = f"({nested} + 1)"
    sql = f"SELECT {nested} FROM weekly_store_family_summary"
    with pytest.raises(SecurityViolation, match="(?i)nesting|depth"):
        validate_and_rewrite_sql(sql, ALLOWLIST)


def test_attack_quoted_identifier_lookalikes():
    with pytest.raises(SecurityViolation, match="(?i)quoted identifier|allowlist|path"):
        validate_and_rewrite_sql(
            'SELECT * FROM " weekly_store_family_summary"',
            ALLOWLIST,
        )
    with pytest.raises(SecurityViolation, match="(?i)quoted identifier|allowlist|path"):
        validate_and_rewrite_sql(
            'SELECT * FROM "weekly_store_family_summary.parquet"',
            ALLOWLIST,
        )
    with pytest.raises(SecurityViolation, match="(?i)quoted identifier|allowlist"):
        validate_and_rewrite_sql(
            'SELECT * FROM "sim_policy_summary\u200b"',
            ALLOWLIST,
        )


def test_quoted_allowlisted_identifier_is_accepted():
    rewritten = validate_and_rewrite_sql(
        'SELECT 1 FROM "weekly_store_family_summary"',
        ALLOWLIST,
    )
    assert "weekly_store_family_summary" in rewritten.lower()


def test_allowlisted_analytics_functions_are_accepted():
    sql = """
    SELECT
      family,
      COUNT(*) AS n,
      SUM(total_sales) AS total,
      DATE_TRUNC('month', week_start_date) AS month,
      ROW_NUMBER() OVER (PARTITION BY family ORDER BY SUM(total_sales) DESC) AS rk
    FROM weekly_store_family_summary
    GROUP BY family, DATE_TRUNC('month', week_start_date)
    """
    rewritten = validate_and_rewrite_sql(sql, ALLOWLIST)
    assert "LIMIT" in rewritten.upper()
