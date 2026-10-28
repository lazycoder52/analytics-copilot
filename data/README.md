# Data

This directory holds small Parquet files that are loaded into an in-memory DuckDB database at
startup. Together they are under 5 MB, so the project runs from a clean clone with no raw data.

| File | Rows | Required | Contents |
| --- | --- | --- | --- |
| `weekly_store_family_summary.parquet` | 431,244 | yes | Weekly sales by store and product family with promo, transaction, oil and holiday context |
| `promo_elasticity_summary.parquet` | 1,395 | yes | Promotion vs non-promotion daily sales by store and family |
| `zero_sales_day_proxy_summary.parquet` | 1,728 | yes | Zero-sales-day statistics by store and family |
| `perishable_volatility_summary.parquet` | 1,525 | yes | Demand volatility and perishability class by store and family |
| `sim_policy_summary.parquet` | 39 | yes | Inventory simulation results per policy, lead time and service level |
| `forecast_sample_summary.parquet` | 171,072 | no (optional) | Daily actuals vs LightGBM and seasonal naive forecasts, 2017-05-12 to 2017-08-15 |

Row counts were measured with DuckDB from the files in this directory.

Plain-English descriptions of every table and column are in `src/copilot/catalog.py`. They
are taken from the source repository's `sql/*.sql`, `docs/DATA_CARD.md` and
`docs/INSIGHTS.md`; columns with no documented definition say "definition not documented".

## Source

The files are tracked aggregate outputs copied unchanged from the `outputs/` directory of the
[grocery-demand-planner](https://github.com/lazycoder52/grocery-demand-planner) repository.
They are derived from the Kaggle competition
[Store Sales - Time Series Forecasting](https://www.kaggle.com/competitions/store-sales-time-series-forecasting)
(Corporación Favorita) data: 54 stores and 33 product families in Ecuador. No raw competition
files are included in this repository.

## Optional file

`forecast_sample_summary.parquet` is row-level (one row per date, store and family), so it is
closer to the raw competition data than the other files. The loader and all tests work
without it, and the evaluation gold set does not use it. If the file is absent, the table is
not loaded, is not described in the prompt catalog and is not queryable.

It can be regenerated from raw data with the grocery-demand-planner pipeline
(`python -m demand_planner.pipeline --stages models`).

## Kaggle rules

Data from the Kaggle competition [Store Sales - Time Series Forecasting](https://www.kaggle.com/competitions/store-sales-time-series-forecasting) is subject to its competition rules. Section 7 of the competition rules permits non-commercial and academic use of the Competition Data and restricts redistribution. These files are aggregated derivatives published by the author for non-commercial educational purposes and will be removed on request.
