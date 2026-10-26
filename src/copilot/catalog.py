"""Table and column description catalog used to ground the LLM prompt.

Every table and column carries a plain-English description. Column types are not stored here;
they are read from the live DuckDB connection so the catalog cannot drift from the data.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    description: str


@dataclass(frozen=True)
class TableInfo:
    name: str
    description: str
    columns: tuple[ColumnInfo, ...]

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)


def _t(name: str, description: str, cols: list[tuple[str, str]]) -> TableInfo:
    return TableInfo(name, description, tuple(ColumnInfo(n, d) for n, d in cols))


_STORE_COLS = {
    "store_nbr": "Store identifier (integer, 1-54).",
    "city": "City where the store is located.",
    "state": "State or province where the store is located.",
    "store_type": "Store format code: one of A, B, C, D, E.",
    "store_cluster": "Cluster number grouping similar stores (integer, 1-17).",
    "family": "Product family (category) name in upper case, e.g. GROCERY I, PRODUCE, MEATS.",
}


def _store_col(name: str) -> tuple[str, str]:
    return name, _STORE_COLS[name]


CATALOG: tuple[TableInfo, ...] = (
    _t(
        "weekly_store_family_summary",
        "Weekly sales by store and product family from 2012-12-31 to 2017-08-14 "
        "(54 stores, 33 families). One row per store, family and week. Includes promotion, "
        "transaction, oil price and holiday context for the week. Sales are in units sold.",
        [
            _store_col("store_nbr"),
            _store_col("city"),
            _store_col("state"),
            _store_col("store_type"),
            _store_col("store_cluster"),
            _store_col("family"),
            ("week_start_date", "Monday that starts the week (timestamp)."),
            ("total_sales", "Total units sold for the store and family during the week."),
            ("mean_daily_sales", "Average units sold per day during the week."),
            ("promo_days", "Number of days in the week with at least one item on promotion."),
            ("total_promo_count", "Sum of items on promotion across the days of the week."),
            ("active_days", "Number of days in the week with data for this store and family."),
            ("weekly_transactions", "Total store transactions (receipts) during the week."),
            ("avg_oil_price", "Average daily oil price during the week (USD per barrel)."),
            ("holiday_count", "Number of holiday or event days in the week."),
            (
                "non_transferred_holidays",
                "Number of holidays in the week that were observed on their actual date "
                "(not transferred to another day).",
            ),
        ],
    ),
    _t(
        "promo_elasticity_summary",
        "Promotion effect by store and product family. Compares average daily sales on "
        "promotion days against non-promotion days. One row per store and family.",
        [
            _store_col("store_nbr"),
            _store_col("city"),
            _store_col("state"),
            _store_col("store_type"),
            _store_col("store_cluster"),
            _store_col("family"),
            ("total_evaluated_days", "Total days evaluated for this store and family."),
            ("promo_days", "Days with the family on promotion."),
            ("non_promo_days", "Days without promotion."),
            ("promo_day_share_pct", "Percentage of evaluated days that were promotion days."),
            ("promo_mean_daily_sales", "Average units sold per day on promotion days."),
            ("non_promo_mean_daily_sales", "Average units sold per day on non-promotion days."),
            ("promo_total_sales", "Total units sold on promotion days."),
            ("total_sales", "Total units sold over all evaluated days."),
            (
                "empirical_promo_lift_pct",
                "Observed promotion lift as a percentage: "
                "(promo_mean_daily_sales / non_promo_mean_daily_sales - 1) * 100. "
                "Descriptive only, not a causal estimate; can be very large when "
                "non-promotion sales are near zero.",
            ),
        ],
    ),
    _t(
        "zero_sales_day_proxy_summary",
        "Zero-sales-day statistics by store and product family, used as a proxy for "
        "stock-outs or intermittent demand (zero sales does not prove a stock-out). "
        "One row per store and family.",
        [
            _store_col("store_nbr"),
            _store_col("city"),
            _store_col("state"),
            _store_col("store_type"),
            _store_col("family"),
            ("total_days", "Total days observed."),
            ("zero_sales_days", "Number of days with zero units sold."),
            ("zero_sales_rate_pct", "zero_sales_days as a percentage of total_days."),
            ("mean_daily_sales", "Average units sold per day over all days."),
            ("active_mean_daily_sales", "Average units sold per day over days with sales."),
            ("max_daily_sales", "Highest single-day units sold."),
            ("total_sales", "Total units sold over all days."),
            (
                "zero_sales_proxy_tier",
                "Tier label: LOW_ZERO_SALES_DAYS, MODERATE_ZERO_SALES_DAYS, "
                "HIGH_VELOCITY_ELEVATED_ZERO_SALES_DAYS_PROXY or SLOW_MOVING_INTERMITTENT_TAIL.",
            ),
        ],
    ),
    _t(
        "perishable_volatility_summary",
        "Demand volatility by store and product family, with a perishability flag. "
        "One row per store and family.",
        [
            _store_col("store_nbr"),
            _store_col("city"),
            ("store_type", _STORE_COLS["store_type"]),
            _store_col("family"),
            ("perishability_class", "PERISHABLE or NON_PERISHABLE."),
            ("total_days", "Total days observed."),
            ("mean_daily_sales", "Average units sold per day."),
            ("std_daily_sales", "Standard deviation of daily units sold."),
            (
                "cv_demand",
                "Coefficient of variation of daily demand (std_daily_sales / mean_daily_sales).",
            ),
            ("max_daily_sales", "Highest single-day units sold."),
            ("zero_sales_days", "Number of days with zero units sold."),
            (
                "volatility_exposure_index",
                "Volatility exposure index used to rank volatility risk.",
            ),
            (
                "volatility_proxy_tier",
                "HIGH_VOLATILITY_PERISHABLE_PROXY, MODERATE_VOLATILITY_PERISHABLE_PROXY "
                "or NON_PERISHABLE_OR_LOW_VOLATILITY.",
            ),
        ],
    ),
    _t(
        "sim_policy_summary",
        "Inventory simulation results, one row per replenishment policy, lead time and "
        "service level (39 rows). Compares seasonal naive, LightGBM and summed-P90 ordering "
        "policies on fill rate, stock-out share and inventory. Not store-level data.",
        [
            (
                "policy",
                "Policy key, e.g. seasonal_naive, lightgbm_p50, lightgbm_point, summed_p90, "
                "or a *_safety_stock variant.",
            ),
            ("policy_label", "Human-readable policy name."),
            ("stitching_rule", "How forecasts are stitched together over time (e.g. reforecast)."),
            ("lead_time_days", "Replenishment lead time in days: 3, 7 or 14."),
            (
                "is_sensitivity_extrapolation",
                "True for the 14-day lead time, which is a sensitivity extrapolation "
                "rather than a primary result.",
            ),
            (
                "service_level",
                "Target service level (0.90, 0.95 or 0.98) for safety-stock policies; "
                "NULL for policies without safety stock.",
            ),
            ("z_value", "Z-score used for safety stock (0 when no safety stock)."),
            ("fill_rate_pct", "Percentage of demand units fulfilled."),
            (
                "stockout_day_share_pct",
                "Percentage of simulated store-family days with a stock-out.",
            ),
            ("average_inventory_units", "Average inventory held, in units."),
            ("inventory_turns", "Inventory turns (idealized, see inventory_turns_note)."),
            ("inventory_turns_note", "Caveat on how inventory_turns should be interpreted."),
            ("total_sales_units", "Total units sold in the simulation."),
            ("total_demand_units", "Total demand units in the simulation."),
            ("simulation_days", "Number of days simulated."),
            ("evaluated_days", "Days counted in the metrics after excluding warm-up."),
            ("warmup_days_excluded", "Warm-up days excluded from metrics."),
            ("n_store_families", "Number of store-family series simulated."),
        ],
    ),
    _t(
        "forecast_sample_summary",
        "Daily actual sales and model forecasts per store and family for cross-validation "
        "folds and a holdout period, 2017-05-12 to 2017-08-15 (54 stores, 33 families). "
        "Use it to compare LightGBM against the seasonal naive baseline.",
        [
            ("date", "Forecast date (timestamp)."),
            ("store_nbr", _STORE_COLS["store_nbr"]),
            ("family", _STORE_COLS["family"]),
            ("sales", "Actual units sold on the date."),
            ("pred_lgbm", "LightGBM forecast of units sold."),
            ("pred_snaive", "Seasonal naive (7-day) forecast of units sold."),
            ("split", "Evaluation split: fold_1 to fold_5, or holdout."),
        ],
    ),
)

TABLE_NAMES: tuple[str, ...] = tuple(t.name for t in CATALOG)
_BY_NAME = {t.name: t for t in CATALOG}


def get_table(name: str) -> TableInfo:
    """Return catalog metadata for a table, raising KeyError if it is not catalogued."""
    return _BY_NAME[name]


def column_types(con: duckdb.DuckDBPyConnection, table: str) -> dict[str, str]:
    """Return the live DuckDB column types for a table, keyed by column name."""
    rows = con.execute(f'DESCRIBE "{table}"').fetchall()
    return {r[0]: r[1] for r in rows}


def render_catalog(con: duckdb.DuckDBPyConnection | None = None) -> str:
    """Render the catalog as plain text for prompts.

    When a connection is supplied, live column types are included.
    """
    blocks: list[str] = []
    for table in CATALOG:
        types = column_types(con, table.name) if con is not None else {}
        lines = [f"TABLE {table.name}: {table.description}"]
        for col in table.columns:
            type_part = f" ({types[col.name]})" if col.name in types else ""
            lines.append(f"  - {col.name}{type_part}: {col.description}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
