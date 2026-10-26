"""Load the tracked Parquet aggregates into an in-memory DuckDB database."""

from __future__ import annotations

import os
from pathlib import Path

import duckdb

from copilot.catalog import OPTIONAL_TABLE_NAMES, TABLE_NAMES

DATA_DIR_ENV = "COPILOT_DATA_DIR"


def default_data_dir() -> Path:
    """Return the data directory: $COPILOT_DATA_DIR if set, else <repo root>/data."""
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "data"


def load_database(
    data_dir: Path | str | None = None,
    harden: bool = True,
) -> duckdb.DuckDBPyConnection:
    """Create an in-memory DuckDB connection with one table per Parquet file.

    Required tables must be present. Optional tables (see ``OPTIONAL_TABLE_NAMES``) are
    loaded only if their file exists. Tables are materialised (CREATE TABLE AS) so later
    queries never touch the filesystem. If ``harden`` is True, external access is disabled
    and configuration is locked.
    """
    directory = Path(data_dir) if data_dir is not None else default_data_dir()
    missing = [n for n in TABLE_NAMES if not (directory / f"{n}.parquet").is_file()]
    if missing:
        raise FileNotFoundError(
            f"Missing Parquet files in {directory.name!r}: {', '.join(missing)}. "
            f"See data/README.md or set {DATA_DIR_ENV}."
        )

    names = list(TABLE_NAMES) + [
        n for n in OPTIONAL_TABLE_NAMES if (directory / f"{n}.parquet").is_file()
    ]
    con = duckdb.connect(":memory:")
    for name in names:
        path = (directory / f"{name}.parquet").as_posix()
        con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM read_parquet(?)', [path])

    if harden:
        from copilot.guard import harden_connection

        harden_connection(con)

    return con
