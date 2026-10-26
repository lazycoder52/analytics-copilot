"""Load the tracked Parquet aggregates into an in-memory DuckDB database."""

from __future__ import annotations

import os
from pathlib import Path

import duckdb

from copilot.catalog import TABLE_NAMES

DATA_DIR_ENV = "COPILOT_DATA_DIR"


def default_data_dir() -> Path:
    """Return the data directory: $COPILOT_DATA_DIR if set, else <repo root>/data."""
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "data"


def load_database(data_dir: Path | str | None = None) -> duckdb.DuckDBPyConnection:
    """Create an in-memory DuckDB connection with one table per catalogued Parquet file.

    Tables are materialised (CREATE TABLE AS) so later queries never touch the filesystem.
    """
    directory = Path(data_dir) if data_dir is not None else default_data_dir()
    missing = [n for n in TABLE_NAMES if not (directory / f"{n}.parquet").is_file()]
    if missing:
        raise FileNotFoundError(
            f"Missing Parquet files in {directory.name!r}: {', '.join(missing)}. "
            f"See data/README.md or set {DATA_DIR_ENV}."
        )

    con = duckdb.connect(":memory:")
    for name in TABLE_NAMES:
        path = (directory / f"{name}.parquet").as_posix()
        con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM read_parquet(?)', [path])
    return con
