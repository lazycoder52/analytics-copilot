"""Table and column description catalog used to ground the LLM prompt.

Every description is taken from the exact definitions in the grocery demand planner repository
(``sql/*.sql``, ``docs/DATA_CARD.md``, ``docs/INSIGHTS.md`` and ``outputs/README.md``).
Where a definition cannot be found there, the description says "definition not documented"
instead of guessing. ``undocumented_columns`` lists those columns.

Column types are not stored here; they are read from the live DuckDB connection so the
catalog cannot drift from the data.

``forecast_sample_summary`` is an optional table: it is loaded and described only when its
Parquet file is present (see ``data/README.md``).
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

UNDOCUMENTED = "definition not documented"


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    description: str


@dataclass(frozen=True)
class TableInfo:
    name: str
    description: str
    columns: tuple[ColumnInfo, ...]
    optional: bool = False

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)


def _t(
    name: str, description: str, cols: list[tuple[str, str]], optional: bool = False
) -> TableInfo:
    return TableInfo(name, description, tuple(ColumnInfo(n, d) for n, d in cols), optional)


_COMMON = {
    "store_nbr": "Store identifier (store_nbr in the stores table).",
    "city": "City of the store, from the stores table.",
    "state": "State of the store, from the stores table.",
    "store_type": f"Store type code from the stores table; {UNDOCUMENTED}.",
    "store_cluster": f"Store cluster number from the stores table; {UNDOCUMENTED}.",
    "family": "Product family name in upper case (33 families), e.g. GROCERY I, PRODUCE, MEATS.",
    "total_days": "Number of daily records counted for the store-family series.",
    "mean_daily_sales": "Average daily unit sales over the series days.",
    "max_daily_sales": "Highest single-day unit sales in the series.",
    "zero_sales_days": "Number of days in the series with zero unit sales.",
}


def _c(*names: str) -> list[tuple[str, str]]:
    return [(n, _COMMON[n]) for n in names]


_SERIES_NOTE = (
    "Series start at each store-family's first positive sale and exclude December 25 "
    "(Christmas closure); only series with at least 60 days are kept."
)

_WEEKLY = _t(
    "weekly_store_family_summary",
    "Weekly view joining daily sales with store transactions, oil prices and holiday entries. "
    "One row per store, product family and Monday-aligned week (date_trunc('week')), 431,244 "
    "rows from 2012-12-31 to 2017-08-14. Built from all train rows with no opening-date filter. "
    "Sales are unit sales.",
    [
        *_c("store_nbr", "city", "state", "store_type", "store_cluster", "family"),
        ("week_start_date", "Monday that starts the week (date_trunc('week', date))."),
        ("total_sales", "Sum of daily unit sales for the store and family in the week."),
        (
            "mean_daily_sales",
            "Average of the daily unit sales rows for the store and family in the week.",
        ),
        (
            "promo_days",
            "Number of daily rows in the week where onpromotion > 0 for the store and family.",
        ),
        (
            "total_promo_count",
            "Sum of the daily onpromotion values (number of items on promotion) in the week.",
        ),
        (
            "active_days",
            "Number of daily train rows for the store and family in the week (COUNT(*)); "
            "normally 7, lower in weeks missing December 25.",
        ),
        (
            "weekly_transactions",
            "Sum of the store's daily transactions in the week, 0 if none. It is a store-level "
            "figure repeated on every family row of that store and week, so summing it across "
            "families double counts.",
        ),
        (
            "avg_oil_price",
            "Average of dcoilwtico (WTI crude oil spot price) over the oil table rows in the "
            "week. Chain-wide, not store-specific.",
        ),
        (
            "holiday_count",
            "Count of all holidays_events rows dated in the week (every type, locale and "
            "transferred flag), 0 if none. Chain-wide, not store-specific.",
        ),
        (
            "non_transferred_holidays",
            "Count of holidays_events rows dated in the week with transferred = FALSE, 0 if "
            "none. Chain-wide, not store-specific.",
        ),
    ],
)

_PROMO = _t(
    "promo_elasticity_summary",
    "Promotion lift by store and product family, 1,395 series. Compares average daily unit "
    "sales on promotion days (onpromotion > 0) with non-promotion days. Uses data from "
    "2014-04-01 (when promotion tracking began) and from each store's first positive sale, "
    "excludes December 25, and keeps only series with at least 30 non-promotion days, at least "
    "10 promotion days and non-promotion mean daily sales above 0.1. Observational, not an "
    "experiment.",
    [
        *_c("store_nbr", "city", "state", "store_type", "store_cluster", "family"),
        ("total_evaluated_days", "Number of daily rows evaluated for the series."),
        ("promo_days", "Days with onpromotion > 0."),
        ("non_promo_days", "Days with onpromotion = 0."),
        ("promo_day_share_pct", "100 * promo_days / total_evaluated_days."),
        ("promo_mean_daily_sales", "Average daily unit sales on promotion days."),
        ("non_promo_mean_daily_sales", "Average daily unit sales on non-promotion days."),
        ("promo_total_sales", "Total unit sales on promotion days."),
        ("total_sales", "Total unit sales over all evaluated days."),
        (
            "empirical_promo_lift_pct",
            "100 * (promo_mean_daily_sales - non_promo_mean_daily_sales) / "
            "non_promo_mean_daily_sales. Descriptive daily sales velocity lift, not a causal "
            "estimate.",
        ),
    ],
)

_ZERO = _t(
    "zero_sales_day_proxy_summary",
    "Zero-sales-day frequency by store and product family, 1,728 series. Zero sales days are "
    "only a proxy for stock-outs because on-hand inventory is not recorded. " + _SERIES_NOTE,
    [
        *_c("store_nbr", "city", "state", "store_type", "family"),
        ("total_days", _COMMON["total_days"]),
        ("zero_sales_days", _COMMON["zero_sales_days"]),
        ("zero_sales_rate_pct", "100 * zero_sales_days / total_days."),
        ("mean_daily_sales", _COMMON["mean_daily_sales"]),
        (
            "active_mean_daily_sales",
            "Average daily unit sales over days with sales > 0 only.",
        ),
        ("max_daily_sales", _COMMON["max_daily_sales"]),
        ("total_sales", "Total unit sales over the series days."),
        (
            "zero_sales_proxy_tier",
            "HIGH_VELOCITY_ELEVATED_ZERO_SALES_DAYS_PROXY: mean daily sales >= 50 and zero-sales "
            "share >= 10%. MODERATE_ZERO_SALES_DAYS_PROXY: mean >= 15 and share >= 25%. "
            "SLOW_MOVING_INTERMITTENT_TAIL: mean < 5 and share >= 50%. "
            "LOW_ZERO_SALES_DAYS: everything else.",
        ),
    ],
)

_PERISHABLE = _t(
    "perishable_volatility_summary",
    "Demand volatility by store and product family, 1,525 series. Demand variability is only a "
    "proxy for perishable inventory risk because spoilage and shrinkage are not recorded. "
    "Series start at each store-family's first positive sale and exclude December 25; only "
    "series with at least 60 days and mean daily sales of at least 1.0 are kept.",
    [
        *_c("store_nbr", "city", "store_type", "family"),
        (
            "perishability_class",
            "PERISHABLE for the families DAIRY, MEATS, POULTRY, PRODUCE, SEAFOOD, BREAD/BAKERY, "
            "DELI and EGGS; NON_PERISHABLE for all other families.",
        ),
        ("total_days", _COMMON["total_days"]),
        ("mean_daily_sales", _COMMON["mean_daily_sales"]),
        ("std_daily_sales", "Population standard deviation of daily unit sales (STDDEV_POP)."),
        (
            "cv_demand",
            "Coefficient of variation of daily demand: std_daily_sales / mean_daily_sales.",
        ),
        ("max_daily_sales", _COMMON["max_daily_sales"]),
        ("zero_sales_days", _COMMON["zero_sales_days"]),
        (
            "volatility_exposure_index",
            "mean_daily_sales * cv_demand, which equals std_daily_sales.",
        ),
        (
            "volatility_proxy_tier",
            "HIGH_VOLATILITY_PERISHABLE_PROXY: perishable with cv_demand >= 0.75. "
            "MODERATE_VOLATILITY_PERISHABLE_PROXY: other perishable series. "
            "NON_PERISHABLE_OR_LOW_VOLATILITY: non-perishable series.",
        ),
    ],
)

_SIM = _t(
    "sim_policy_summary",
    "Tracked aggregate table of fill rate, inventory, stockout rate and service level across "
    "replenishment policies, 39 rows (outputs/README.md). It is not store-level data. Most "
    "column definitions are not documented in the source repository.",
    [
        (
            "policy",
            f"Replenishment policy key; {UNDOCUMENTED}. INSIGHTS.md refers to the Seasonal Naive "
            "and LightGBM Point policies.",
        ),
        ("policy_label", f"Display label for the policy; {UNDOCUMENTED}."),
        ("stitching_rule", f"Forecast stitching rule; {UNDOCUMENTED}."),
        (
            "lead_time_days",
            "Replenishment lead time L in days. INSIGHTS.md reports results at L=3 and L=7.",
        ),
        ("is_sensitivity_extrapolation", f"Boolean flag; {UNDOCUMENTED}."),
        ("service_level", f"Target service level; {UNDOCUMENTED}."),
        (
            "z_value",
            "Safety multiplier z applied to out-of-sample residual safety stock (INSIGHTS.md).",
        ),
        (
            "fill_rate_pct",
            "Simulated on-shelf fill rate in percent; exact definition not documented. "
            "INSIGHTS.md compares policies at matched target fill rates such as 99.0%.",
        ),
        (
            "stockout_day_share_pct",
            f"Simulated stockout rate in percent (outputs/README.md); {UNDOCUMENTED}.",
        ),
        (
            "average_inventory_units",
            "Average simulated inventory in units, not value-weighted (INSIGHTS.md).",
        ),
        ("inventory_turns", f"Inventory turns; {UNDOCUMENTED}."),
        ("inventory_turns_note", f"Text note stored with inventory_turns; {UNDOCUMENTED}."),
        ("total_sales_units", f"Total unit sales in the simulation; {UNDOCUMENTED}."),
        ("total_demand_units", f"Total demand units in the simulation; {UNDOCUMENTED}."),
        ("simulation_days", f"Number of simulated days; {UNDOCUMENTED}."),
        ("evaluated_days", f"Number of days used in the metrics; {UNDOCUMENTED}."),
        ("warmup_days_excluded", f"Number of warm-up days excluded; {UNDOCUMENTED}."),
        ("n_store_families", f"Number of store-family series simulated; {UNDOCUMENTED}."),
    ],
)

_FORECAST = _t(
    "forecast_sample_summary",
    "OPTIONAL table. Daily actual unit sales and forecasts per store and product family across "
    "the 5 rolling-origin cross-validation folds and the final holdout window, 171,072 rows "
    "from 2017-05-12 to 2017-08-15. Only present when forecast_sample_summary.parquet is in "
    "the data directory.",
    [
        ("date", "Forecast date."),
        *_c("store_nbr", "family"),
        ("sales", "Actual daily unit sales."),
        ("pred_lgbm", "LightGBM point forecast of daily unit sales."),
        ("pred_snaive", "7-day seasonal naive forecast of daily unit sales."),
        (
            "split",
            "Evaluation split: fold_1 to fold_5 (rolling-origin cross-validation folds) or "
            "holdout (2017-07-31 to 2017-08-15).",
        ),
    ],
    optional=True,
)

CATALOG: tuple[TableInfo, ...] = (_WEEKLY, _PROMO, _ZERO, _PERISHABLE, _SIM, _FORECAST)
REQUIRED_TABLES: tuple[TableInfo, ...] = tuple(t for t in CATALOG if not t.optional)
OPTIONAL_TABLES: tuple[TableInfo, ...] = tuple(t for t in CATALOG if t.optional)

TABLE_NAMES: tuple[str, ...] = tuple(t.name for t in REQUIRED_TABLES)
OPTIONAL_TABLE_NAMES: tuple[str, ...] = tuple(t.name for t in OPTIONAL_TABLES)
ALL_TABLE_NAMES: tuple[str, ...] = TABLE_NAMES + OPTIONAL_TABLE_NAMES
_BY_NAME = {t.name: t for t in CATALOG}


def get_table(name: str) -> TableInfo:
    """Return catalog metadata for a table, raising KeyError if it is not catalogued."""
    return _BY_NAME[name]


def loaded_tables(con: duckdb.DuckDBPyConnection) -> tuple[TableInfo, ...]:
    """Return catalog entries for the tables that exist in the connection, in catalog order."""
    present = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    return tuple(t for t in CATALOG if t.name in present)


def undocumented_columns() -> list[tuple[str, str]]:
    """Return (table, column) pairs whose description says the definition is not documented."""
    return [(t.name, c.name) for t in CATALOG for c in t.columns if UNDOCUMENTED in c.description]


def column_types(con: duckdb.DuckDBPyConnection, table: str) -> dict[str, str]:
    """Return the live DuckDB column types for a table, keyed by column name."""
    rows = con.execute(f'DESCRIBE "{table}"').fetchall()
    return {r[0]: r[1] for r in rows}


def render_catalog(con: duckdb.DuckDBPyConnection | None = None) -> str:
    """Render the catalog as plain text for prompts.

    With a connection, only tables that are loaded are described and live column types are
    included. Without one, the required tables are described without types.
    """
    tables = loaded_tables(con) if con is not None else REQUIRED_TABLES
    blocks: list[str] = []
    for table in tables:
        types = column_types(con, table.name) if con is not None else {}
        lines = [f"TABLE {table.name}: {table.description}"]
        for col in table.columns:
            type_part = f" ({types[col.name]})" if col.name in types else ""
            lines.append(f"  - {col.name}{type_part}: {col.description}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
