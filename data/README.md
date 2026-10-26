# Data

This directory holds six small Parquet files that are loaded into an in-memory DuckDB
database at startup. Together they are under 5 MB, so the project runs from a clean clone
with no raw data.

| File | Rows | Contents |
| --- | --- | --- |
| `weekly_store_family_summary.parquet` | 431,244 | Weekly sales by store and product family with promo, transaction, oil and holiday context |
| `promo_elasticity_summary.parquet` | 1,395 | Promotion vs non-promotion daily sales by store and family |
| `zero_sales_day_proxy_summary.parquet` | 1,728 | Zero-sales-day statistics by store and family |
| `perishable_volatility_summary.parquet` | 1,525 | Demand volatility and perishability class by store and family |
| `sim_policy_summary.parquet` | 39 | Inventory simulation results per policy, lead time and service level |
| `forecast_sample_summary.parquet` | 171,072 | Daily actuals vs LightGBM and seasonal naive forecasts, 2017-05-12 to 2017-08-15 |

Plain-English descriptions of every table and column are in `src/copilot/catalog.py`.

## Source

The files are tracked aggregate outputs copied unchanged from the author's grocery demand
planner project (the `kirana-demand-forecaster` repository, `outputs/` directory). They were
derived from a public retail dataset of store, product-family, promotion, transaction, oil
price and holiday records for 54 stores and 33 product families (the column layout matches
the Kaggle "Store Sales - Time Series Forecasting" competition data). No raw data files are
included in this repository.

## Kaggle rules caveat

Data from Kaggle competitions is distributed under that competition's rules, which can
restrict redistribution of the raw data and of material derived from it. These files contain
only aggregates and model outputs, not the raw competition files, but
`forecast_sample_summary.parquet` and `weekly_store_family_summary.parquet` are fine-grained
(per store, family and day or week). Confirm that the competition rules permit
redistributing them before making this repository public. The repository is private.

Row counts above were measured with DuckDB from the files in this directory.
