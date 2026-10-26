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
    with pytest.raises(SecurityViolation, match="(?i)duckdb_|system catalog|blocked function"):
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
