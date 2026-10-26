"""Tests for the data loader and the table/column description catalog."""

from __future__ import annotations

import shutil

import pytest

from copilot.catalog import (
    ALL_TABLE_NAMES,
    CATALOG,
    OPTIONAL_TABLE_NAMES,
    TABLE_NAMES,
    UNDOCUMENTED,
    column_types,
    get_table,
    loaded_tables,
    render_catalog,
    undocumented_columns,
)
from copilot.data import DATA_DIR_ENV, default_data_dir, load_database

REQUIRED = {
    "weekly_store_family_summary",
    "promo_elasticity_summary",
    "zero_sales_day_proxy_summary",
    "perishable_volatility_summary",
    "sim_policy_summary",
}
OPTIONAL = {"forecast_sample_summary"}
HAS_OPTIONAL = all((default_data_dir() / f"{n}.parquet").is_file() for n in OPTIONAL)
needs_optional = pytest.mark.skipif(not HAS_OPTIONAL, reason="optional parquet not present")


@pytest.fixture(scope="module")
def full_con():
    connection = load_database()
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def required_only_con(tmp_path_factory):
    """A database loaded from a data directory that has no optional files."""
    directory = tmp_path_factory.mktemp("data_required_only")
    for name in TABLE_NAMES:
        shutil.copy(default_data_dir() / f"{name}.parquet", directory / f"{name}.parquet")
    assert not (directory / "forecast_sample_summary.parquet").exists()
    connection = load_database(directory)
    yield connection
    connection.close()


def test_catalog_required_and_optional_split():
    assert set(TABLE_NAMES) == REQUIRED
    assert set(OPTIONAL_TABLE_NAMES) == OPTIONAL
    assert set(ALL_TABLE_NAMES) == REQUIRED | OPTIONAL
    assert len(ALL_TABLE_NAMES) == len(set(ALL_TABLE_NAMES))


def test_required_tables_load_without_optional_file(required_only_con):
    loaded = {r[0] for r in required_only_con.execute("SHOW TABLES").fetchall()}
    assert loaded == REQUIRED
    for name in TABLE_NAMES:
        (n,) = required_only_con.execute(f'SELECT count(*) FROM "{name}"').fetchone()
        assert n > 0, name


def test_render_catalog_omits_missing_optional_table(required_only_con):
    text = render_catalog(required_only_con)
    assert "forecast_sample_summary" not in text
    for name in TABLE_NAMES:
        assert f"TABLE {name}:" in text


@needs_optional
def test_full_load_includes_optional_table_when_present(full_con):
    loaded = {r[0] for r in full_con.execute("SHOW TABLES").fetchall()}
    assert loaded == REQUIRED | OPTIONAL
    assert "TABLE forecast_sample_summary:" in render_catalog(full_con)


@pytest.mark.parametrize("table", ALL_TABLE_NAMES)
def test_catalog_columns_match_live_schema(full_con, table):
    if table in OPTIONAL and not HAS_OPTIONAL:
        pytest.skip("optional parquet not present")
    live = list(column_types(full_con, table))
    assert list(get_table(table).column_names) == live


def test_every_table_and_column_has_a_description():
    for table in CATALOG:
        assert len(table.description.strip()) > 20, table.name
        for col in table.columns:
            assert len(col.description.strip()) > 5, (table.name, col.name)


def test_undocumented_columns_are_explicitly_marked():
    marked = undocumented_columns()
    assert marked
    for table, column in marked:
        assert UNDOCUMENTED in {c.name: c.description for c in get_table(table).columns}[column]
    documented_tables = {"weekly_store_family_summary", "perishable_volatility_summary"}
    # Every column in these tables is defined by sql/*.sql except the store attribute codes.
    allowed = {"store_type", "store_cluster"}
    assert all(c in allowed for t, c in marked if t in documented_tables)


def test_exact_definitions_from_source_sql():
    cols = {c.name: c.description for c in get_table("weekly_store_family_summary").columns}
    assert "holidays_events" in cols["holiday_count"]
    assert "transferred = FALSE" in cols["non_transferred_holidays"]
    perishable = {c.name: c.description for c in get_table("perishable_volatility_summary").columns}
    assert "std_daily_sales" in perishable["volatility_exposure_index"]


def test_render_catalog_mentions_every_loaded_table_and_column(full_con):
    text = render_catalog(full_con)
    for table in loaded_tables(full_con):
        assert f"TABLE {table.name}:" in text
        for col in table.columns:
            assert f"- {col.name} (" in text


def test_render_catalog_without_connection_describes_required_tables_only():
    text = render_catalog()
    assert "TABLE weekly_store_family_summary:" in text
    assert "- store_nbr:" in text
    assert "forecast_sample_summary" not in text


def test_default_data_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path))
    assert default_data_dir() == tmp_path


def test_load_database_reports_missing_required_files(tmp_path):
    with pytest.raises(FileNotFoundError, match="Missing Parquet files"):
        load_database(tmp_path)


def test_tables_are_materialised_not_file_views(full_con):
    rows = full_con.execute(
        "SELECT table_name, table_type FROM information_schema.tables"
    ).fetchall()
    types = dict(rows)
    assert all(types[t.name] == "BASE TABLE" for t in loaded_tables(full_con))
