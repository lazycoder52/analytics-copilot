"""Tests for the data loader and the table/column description catalog."""

from __future__ import annotations

import pytest

from copilot.catalog import CATALOG, TABLE_NAMES, column_types, get_table, render_catalog
from copilot.data import DATA_DIR_ENV, default_data_dir, load_database

EXPECTED_TABLES = {
    "weekly_store_family_summary",
    "promo_elasticity_summary",
    "zero_sales_day_proxy_summary",
    "perishable_volatility_summary",
    "sim_policy_summary",
    "forecast_sample_summary",
}


@pytest.fixture(scope="module")
def con():
    connection = load_database()
    yield connection
    connection.close()


def test_catalog_covers_expected_tables():
    assert set(TABLE_NAMES) == EXPECTED_TABLES
    assert len(TABLE_NAMES) == len(set(TABLE_NAMES))


def test_all_tables_loaded_and_non_empty(con):
    loaded = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    assert loaded == EXPECTED_TABLES
    for name in TABLE_NAMES:
        (n,) = con.execute(f'SELECT count(*) FROM "{name}"').fetchone()
        assert n > 0, name


@pytest.mark.parametrize("table", TABLE_NAMES)
def test_catalog_columns_match_live_schema(con, table):
    live = list(column_types(con, table))
    assert list(get_table(table).column_names) == live


def test_every_table_and_column_has_a_description():
    for table in CATALOG:
        assert len(table.description.strip()) > 20, table.name
        for col in table.columns:
            assert len(col.description.strip()) > 5, (table.name, col.name)


def test_render_catalog_mentions_every_table_and_column(con):
    text = render_catalog(con)
    for table in CATALOG:
        assert f"TABLE {table.name}:" in text
        for col in table.columns:
            assert f"- {col.name} (" in text


def test_render_catalog_without_connection_omits_types():
    text = render_catalog()
    assert "TABLE weekly_store_family_summary:" in text
    assert "- store_nbr:" in text


def test_default_data_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path))
    assert default_data_dir() == tmp_path


def test_load_database_reports_missing_files(tmp_path):
    with pytest.raises(FileNotFoundError, match="Missing Parquet files"):
        load_database(tmp_path)


def test_tables_are_materialised_not_file_views(con):
    rows = con.execute("SELECT table_name, table_type FROM information_schema.tables").fetchall()
    types = dict(rows)
    assert all(types[name] == "BASE TABLE" for name in EXPECTED_TABLES)
