# Gold Evaluation Set Review (`evals/gold.jsonl`)

**Status: AI-assisted, needs human review.**

This document lists all 45 evaluation items (10 easy, 20 medium, 10 hard, and 5 unanswerable/ambiguous) 
together with their reference DuckDB SQL and the exact expected result executed against the tracked 
Parquet aggregates in `data/`. Spot-check at least 15 questions to verify domain alignment with 
`grocery-demand-planner`.

| Summary | Count |
| --- | --- |
| Easy (`easy_01` - `easy_10`) | 10 |
| Medium (`med_01` - `med_20`) | 20 |
| Hard (`hard_01` - `hard_10`) | 10 |
| Unanswerable (`unans_01` - `unans_05`) | 5 |
| **Total** | **45** |

## `easy_01` (EASY) — Answerable: Yes

**Question:** How many total rows are in the weekly_store_family_summary table?

**Reference SQL:**
```sql
SELECT COUNT(*) AS row_count FROM weekly_store_family_summary
```

**Expected Result (1 row(s)):**

| row_count |
| --- |
| 431244 |

## `easy_02` (EASY) — Answerable: Yes

**Question:** How many distinct stores are represented in weekly_store_family_summary?

**Reference SQL:**
```sql
SELECT COUNT(DISTINCT store_nbr) AS store_count FROM weekly_store_family_summary
```

**Expected Result (1 row(s)):**

| store_count |
| --- |
| 54 |

## `easy_03` (EASY) — Answerable: Yes

**Question:** How many distinct product families exist in weekly_store_family_summary?

**Reference SQL:**
```sql
SELECT COUNT(DISTINCT family) AS family_count FROM weekly_store_family_summary
```

**Expected Result (1 row(s)):**

| family_count |
| --- |
| 33 |

## `easy_04` (EASY) — Answerable: Yes

**Question:** What are the earliest and latest week_start_date values in weekly_store_family_summary?

**Reference SQL:**
```sql
SELECT MIN(week_start_date) AS min_week, MAX(week_start_date) AS max_week FROM weekly_store_family_summary
```

**Expected Result (1 row(s)):**

| min_week | max_week |
| --- | --- |
| 2012-12-31 | 2017-08-14 |

## `easy_05` (EASY) — Answerable: Yes

**Question:** How many store-family series are evaluated in promo_elasticity_summary?

**Reference SQL:**
```sql
SELECT COUNT(*) AS series_count FROM promo_elasticity_summary
```

**Expected Result (1 row(s)):**

| series_count |
| --- |
| 1395 |

## `easy_06` (EASY) — Answerable: Yes

**Question:** How many store-family series in perishable_volatility_summary are classified as PERISHABLE?

**Reference SQL:**
```sql
SELECT COUNT(*) AS perishable_series FROM perishable_volatility_summary WHERE perishability_class = 'PERISHABLE'
```

**Expected Result (1 row(s)):**

| perishable_series |
| --- |
| 430 |

## `easy_07` (EASY) — Answerable: Yes

**Question:** How many rows are in sim_policy_summary?

**Reference SQL:**
```sql
SELECT COUNT(*) AS row_count FROM sim_policy_summary
```

**Expected Result (1 row(s)):**

| row_count |
| --- |
| 39 |

## `easy_08` (EASY) — Answerable: Yes

**Question:** What are the distinct replenishment lead times (lead_time_days) in sim_policy_summary, ordered ascending?

**Reference SQL:**
```sql
SELECT DISTINCT lead_time_days FROM sim_policy_summary ORDER BY lead_time_days ASC
```

**Expected Result (3 row(s)):**

| lead_time_days |
| --- |
| 3 |
| 7 |
| 14 |

## `easy_09` (EASY) — Answerable: Yes

**Question:** How many series in zero_sales_day_proxy_summary fall into the HIGH_VELOCITY_ELEVATED_ZERO_SALES_DAYS_PROXY tier?

**Reference SQL:**
```sql
SELECT COUNT(*) AS high_velocity_tier_count FROM zero_sales_day_proxy_summary WHERE zero_sales_proxy_tier = 'HIGH_VELOCITY_ELEVATED_ZERO_SALES_DAYS_PROXY'
```

**Expected Result (1 row(s)):**

| high_velocity_tier_count |
| --- |
| 117 |

## `easy_10` (EASY) — Answerable: Yes

**Question:** Which city and state does store 1 belong to in weekly_store_family_summary?

**Reference SQL:**
```sql
SELECT DISTINCT city, state FROM weekly_store_family_summary WHERE store_nbr = 1
```

**Expected Result (1 row(s)):**

| city | state |
| --- | --- |
| Quito | Pichincha |

## `med_01` (MEDIUM) — Answerable: Yes

**Question:** Which 5 product families have the highest total unit sales across all weeks in weekly_store_family_summary?

**Reference SQL:**
```sql
SELECT family, ROUND(SUM(total_sales), 2) AS total_sales FROM weekly_store_family_summary GROUP BY family ORDER BY total_sales DESC LIMIT 5
```

**Expected Result (5 row(s)):**

| family | total_sales |
| --- | --- |
| GROCERY I | 343462735.71 |
| BEVERAGES | 216954486.0 |
| PRODUCE | 122704686.65 |
| CLEANING | 97521289.0 |
| DAIRY | 64487709.0 |

## `med_02` (MEDIUM) — Answerable: Yes

**Question:** Which 5 cities have the highest total unit sales in weekly_store_family_summary?

**Reference SQL:**
```sql
SELECT city, ROUND(SUM(total_sales), 2) AS total_sales FROM weekly_store_family_summary GROUP BY city ORDER BY total_sales DESC LIMIT 5
```

**Expected Result (5 row(s)):**

| city | total_sales |
| --- | --- |
| Quito | 556741844.32 |
| Guayaquil | 122967263.22 |
| Cuenca | 49168597.36 |
| Ambato | 40304402.01 |
| Santo Domingo | 35834323.85 |

## `med_03` (MEDIUM) — Answerable: Yes

**Question:** What is the number of distinct stores and total unit sales for each store_type in weekly_store_family_summary, ordered by store_type?

**Reference SQL:**
```sql
SELECT store_type, COUNT(DISTINCT store_nbr) AS store_count, ROUND(SUM(total_sales), 2) AS total_sales FROM weekly_store_family_summary GROUP BY store_type ORDER BY store_type ASC
```

**Expected Result (5 row(s)):**

| store_type | store_count | total_sales |
| --- | --- | --- |
| A | 9 | 353043845.95 |
| B | 8 | 145260638.02 |
| C | 15 | 164434744.87 |
| D | 18 | 351083304.33 |
| E | 4 | 59822437.04 |

## `med_04` (MEDIUM) — Answerable: Yes

**Question:** Which 5 store-family series in promo_elasticity_summary have the highest empirical_promo_lift_pct?

**Reference SQL:**
```sql
SELECT store_nbr, family, ROUND(empirical_promo_lift_pct, 2) AS empirical_promo_lift_pct FROM promo_elasticity_summary ORDER BY empirical_promo_lift_pct DESC LIMIT 5
```

**Expected Result (5 row(s)):**

| store_nbr | family | empirical_promo_lift_pct |
| --- | --- | --- |
| 36 | SCHOOL AND OFFICE SUPPLIES | 7980.77002 |
| 54 | SCHOOL AND OFFICE SUPPLIES | 6721.430176 |
| 6 | SCHOOL AND OFFICE SUPPLIES | 3617.389893 |
| 22 | SCHOOL AND OFFICE SUPPLIES | 3605.0 |
| 10 | SCHOOL AND OFFICE SUPPLIES | 3094.120117 |

## `med_05` (MEDIUM) — Answerable: Yes

**Question:** For each product family in promo_elasticity_summary with at least 20 evaluated series, what is the average empirical_promo_lift_pct, ordered highest first (top 5)?

**Reference SQL:**
```sql
SELECT family, COUNT(*) AS n_series, ROUND(AVG(empirical_promo_lift_pct), 2) AS avg_lift_pct FROM promo_elasticity_summary GROUP BY family HAVING COUNT(*) >= 20 ORDER BY avg_lift_pct DESC LIMIT 5
```

**Expected Result (5 row(s)):**

| family | n_series | avg_lift_pct |
| --- | --- | --- |
| SCHOOL AND OFFICE SUPPLIES | 45 | 1958.48 |
| PET SUPPLIES | 43 | 119.28 |
| BEAUTY | 54 | 113.24 |
| LAWN AND GARDEN | 39 | 98.25 |
| PRODUCE | 53 | 93.57 |

## `med_06` (MEDIUM) — Answerable: Yes

**Question:** How many store-family series belong to each zero_sales_proxy_tier in zero_sales_day_proxy_summary, ordered by count descending?

**Reference SQL:**
```sql
SELECT zero_sales_proxy_tier, COUNT(*) AS series_count FROM zero_sales_day_proxy_summary GROUP BY zero_sales_proxy_tier ORDER BY series_count DESC
```

**Expected Result (4 row(s)):**

| zero_sales_proxy_tier | series_count |
| --- | --- |
| LOW_ZERO_SALES_DAYS | 1386 |
| SLOW_MOVING_INTERMITTENT_TAIL | 222 |
| HIGH_VELOCITY_ELEVATED_ZERO_SALES_DAYS_PROXY | 117 |
| MODERATE_ZERO_SALES_DAYS_PROXY | 3 |

## `med_07` (MEDIUM) — Answerable: Yes

**Question:** Which 5 HIGH_VELOCITY_ELEVATED_ZERO_SALES_DAYS_PROXY series in zero_sales_day_proxy_summary have the highest zero_sales_rate_pct?

**Reference SQL:**
```sql
SELECT store_nbr, city, family, ROUND(zero_sales_rate_pct, 2) AS zero_sales_rate_pct, ROUND(mean_daily_sales, 2) AS mean_daily_sales FROM zero_sales_day_proxy_summary WHERE zero_sales_proxy_tier = 'HIGH_VELOCITY_ELEVATED_ZERO_SALES_DAYS_PROXY' ORDER BY zero_sales_rate_pct DESC, mean_daily_sales DESC LIMIT 5
```

**Expected Result (5 row(s)):**

| store_nbr | city | family | zero_sales_rate_pct | mean_daily_sales |
| --- | --- | --- | --- | --- |
| 18 | Quito | PRODUCE | 31.309999 | 1117.77002 |
| 18 | Quito | HOME CARE | 29.190001 | 139.020004 |
| 25 | Salinas | HOME CARE | 25.68 | 84.120003 |
| 14 | Riobamba | PRODUCE | 23.73 | 291.649994 |
| 43 | Esmeraldas | PRODUCE | 23.280001 | 625.869995 |

## `med_08` (MEDIUM) — Answerable: Yes

**Question:** In perishable_volatility_summary, what is the average cv_demand and series count for each volatility_proxy_tier?

**Reference SQL:**
```sql
SELECT volatility_proxy_tier, COUNT(*) AS series_count, ROUND(AVG(cv_demand), 4) AS avg_cv_demand FROM perishable_volatility_summary GROUP BY volatility_proxy_tier ORDER BY avg_cv_demand DESC
```

**Expected Result (3 row(s)):**

| volatility_proxy_tier | series_count | avg_cv_demand |
| --- | --- | --- |
| HIGH_VOLATILITY_PERISHABLE_PROXY | 61 | 1.1004 |
| NON_PERISHABLE_OR_LOW_VOLATILITY | 1095 | 0.9434 |
| MODERATE_VOLATILITY_PERISHABLE_PROXY | 369 | 0.4024 |

## `med_09` (MEDIUM) — Answerable: Yes

**Question:** Among PERISHABLE families in perishable_volatility_summary, what is the average cv_demand per family, ordered highest first?

**Reference SQL:**
```sql
SELECT family, COUNT(*) AS n_stores, ROUND(AVG(cv_demand), 4) AS avg_cv_demand FROM perishable_volatility_summary WHERE perishability_class = 'PERISHABLE' GROUP BY family ORDER BY avg_cv_demand DESC
```

**Expected Result (8 row(s)):**

| family | n_stores | avg_cv_demand |
| --- | --- | --- |
| PRODUCE | 54 | 0.7192 |
| SEAFOOD | 52 | 0.6944 |
| MEATS | 54 | 0.5745 |
| EGGS | 54 | 0.484 |
| POULTRY | 54 | 0.4621 |
| DAIRY | 54 | 0.4065 |
| DELI | 54 | 0.3423 |
| BREAD/BAKERY | 54 | 0.3353 |

## `med_10` (MEDIUM) — Answerable: Yes

**Question:** Which 5 PERISHABLE store-family series in perishable_volatility_summary have the highest volatility_exposure_index?

**Reference SQL:**
```sql
SELECT store_nbr, city, family, ROUND(volatility_exposure_index, 2) AS volatility_exposure_index FROM perishable_volatility_summary WHERE perishability_class = 'PERISHABLE' ORDER BY volatility_exposure_index DESC LIMIT 5
```

**Expected Result (5 row(s)):**

| store_nbr | city | family | volatility_exposure_index |
| --- | --- | --- | --- |
| 44 | Quito | PRODUCE | 5523.839844 |
| 3 | Quito | PRODUCE | 4346.220215 |
| 49 | Quito | PRODUCE | 4088.47998 |
| 45 | Quito | PRODUCE | 3577.929932 |
| 47 | Quito | PRODUCE | 3316.689941 |

## `med_11` (MEDIUM) — Answerable: Yes

**Question:** In sim_policy_summary, for lead_time_days = 3 and z_value = 0.0, what are the fill_rate_pct and average_inventory_units for each policy, ordered by fill_rate_pct descending?

**Reference SQL:**
```sql
SELECT policy, fill_rate_pct, average_inventory_units FROM sim_policy_summary WHERE lead_time_days = 3 AND z_value = 0.0 ORDER BY fill_rate_pct DESC
```

**Expected Result (4 row(s)):**

| policy | fill_rate_pct | average_inventory_units |
| --- | --- | --- |
| lightgbm_point | 98.63 | 3645308.83 |
| lightgbm_p50 | 98.16 | 3557848.49 |
| summed_p90 | 98.16 | 3557848.49 |
| seasonal_naive | 97.58 | 3832656.99 |

## `med_12` (MEDIUM) — Answerable: Yes

**Question:** In sim_policy_summary, which rows achieve a fill_rate_pct of at least 99.0 at lead_time_days = 7, ordered by average_inventory_units ascending?

**Reference SQL:**
```sql
SELECT policy, service_level, z_value, fill_rate_pct, average_inventory_units FROM sim_policy_summary WHERE lead_time_days = 7 AND fill_rate_pct >= 99.0 ORDER BY average_inventory_units ASC
```

**Expected Result (8 row(s)):**

| policy | service_level | z_value | fill_rate_pct | average_inventory_units |
| --- | --- | --- | --- | --- |
| lightgbm_p50_safety_stock | 0.9 | 1.281552 | 99.07 | 4041625.9 |
| lightgbm_point_safety_stock | 0.9 | 1.281552 | 99.25 | 4119750.09 |
| lightgbm_p50_safety_stock | 0.95 | 1.644854 | 99.27 | 4279761.61 |
| lightgbm_point_safety_stock | 0.95 | 1.644854 | 99.39 | 4347062.97 |
| lightgbm_p50_safety_stock | 0.98 | 2.053749 | 99.43 | 4552659.84 |
| lightgbm_point_safety_stock | 0.98 | 2.053749 | 99.51 | 4606306.39 |
| seasonal_naive_safety_stock | 0.95 | 1.644854 | 99.2 | 4706994.86 |
| seasonal_naive_safety_stock | 0.98 | 2.053749 | 99.43 | 5021992.13 |

## `med_13` (MEDIUM) — Answerable: Yes

**Question:** What was the total unit sales in weekly_store_family_summary for each calendar year of week_start_date, ordered by year?

**Reference SQL:**
```sql
SELECT EXTRACT(YEAR FROM week_start_date) AS yr, ROUND(SUM(total_sales), 2) AS yearly_sales FROM weekly_store_family_summary GROUP BY yr ORDER BY yr ASC
```

**Expected Result (6 row(s)):**

| yr | yearly_sales |
| --- | --- |
| 2012 | 2211570.56 |
| 2013 | 141583980.1 |
| 2014 | 208148056.86 |
| 2015 | 241139609.98 |
| 2016 | 286356763.54 |
| 2017 | 194204989.17 |

## `med_14` (MEDIUM) — Answerable: Yes

**Question:** What is the chain-wide average of avg_oil_price by calendar year in weekly_store_family_summary?

**Reference SQL:**
```sql
SELECT EXTRACT(YEAR FROM week_start_date) AS yr, ROUND(AVG(avg_oil_price), 2) AS mean_oil_price FROM weekly_store_family_summary GROUP BY yr ORDER BY yr ASC
```

**Expected Result (6 row(s)):**

| yr | mean_oil_price |
| --- | --- |
| 2012 | 93.08 |
| 2013 | 97.99 |
| 2014 | 92.81 |
| 2015 | 48.58 |
| 2016 | 43.27 |
| 2017 | 49.38 |

## `med_15` (MEDIUM) — Answerable: Yes

**Question:** How many distinct weeks in weekly_store_family_summary had at least one non-transferred holiday (non_transferred_holidays > 0)?

**Reference SQL:**
```sql
SELECT COUNT(DISTINCT week_start_date) AS holiday_weeks FROM weekly_store_family_summary WHERE non_transferred_holidays > 0
```

**Expected Result (1 row(s)):**

| holiday_weeks |
| --- |
| 124 |

## `med_16` (MEDIUM) — Answerable: Yes

**Question:** Which 5 stores in Quito had the highest total unit sales of GROCERY I in weekly_store_family_summary?

**Reference SQL:**
```sql
SELECT store_nbr, ROUND(SUM(total_sales), 2) AS grocery_sales FROM weekly_store_family_summary WHERE city = 'Quito' AND family = 'GROCERY I' GROUP BY store_nbr ORDER BY grocery_sales DESC LIMIT 5
```

**Expected Result (5 row(s)):**

| store_nbr | grocery_sales |
| --- | --- |
| 44 | 16386055.04 |
| 45 | 16349751.29 |
| 47 | 15514528.49 |
| 46 | 14342262.0 |
| 3 | 12970467.98 |

## `med_17` (MEDIUM) — Answerable: Yes

**Question:** In promo_elasticity_summary, how many store-family series have negative empirical_promo_lift_pct (lower average sales on promotion days than non-promotion days)?

**Reference SQL:**
```sql
SELECT COUNT(*) AS negative_lift_series FROM promo_elasticity_summary WHERE empirical_promo_lift_pct < 0
```

**Expected Result (1 row(s)):**

| negative_lift_series |
| --- |
| 73 |

## `med_18` (MEDIUM) — Answerable: Yes

**Question:** Which 5 states have the highest number of distinct stores in weekly_store_family_summary?

**Reference SQL:**
```sql
SELECT state, COUNT(DISTINCT store_nbr) AS store_count FROM weekly_store_family_summary GROUP BY state ORDER BY store_count DESC, state ASC LIMIT 5
```

**Expected Result (5 row(s)):**

| state | store_count |
| --- | --- |
| Pichincha | 19 |
| Guayas | 11 |
| Azuay | 3 |
| Manabi | 3 |
| Santo Domingo de los Tsachilas | 3 |

## `med_19` (MEDIUM) — Answerable: Yes

**Question:** In zero_sales_day_proxy_summary, what is the average zero_sales_rate_pct for each store_type, ordered by average rate descending?

**Reference SQL:**
```sql
SELECT store_type, ROUND(AVG(zero_sales_rate_pct), 2) AS avg_zero_rate_pct FROM zero_sales_day_proxy_summary GROUP BY store_type ORDER BY avg_zero_rate_pct DESC
```

**Expected Result (5 row(s)):**

| store_type | avg_zero_rate_pct |
| --- | --- |
| C | 24.96 |
| E | 19.39 |
| D | 16.73 |
| B | 15.86 |
| A | 9.98 |

## `med_20` (MEDIUM) — Answerable: Yes

**Question:** In sim_policy_summary, what are the minimum and maximum inventory_turns across all rows for each lead_time_days?

**Reference SQL:**
```sql
SELECT lead_time_days, MIN(inventory_turns) AS min_turns, MAX(inventory_turns) AS max_turns FROM sim_policy_summary GROUP BY lead_time_days ORDER BY lead_time_days ASC
```

**Expected Result (3 row(s)):**

| lead_time_days | min_turns | max_turns |
| --- | --- | --- |
| 3 | 61.54 | 86.56 |
| 7 | 62.11 | 94.11 |
| 14 | 93.78 | 131.92 |

## `hard_01` (HARD) — Answerable: Yes

**Question:** Without double counting across product families, which 5 stores had the highest total weekly_transactions across all weeks in weekly_store_family_summary?

**Reference SQL:**
```sql
WITH store_weeks AS (  SELECT store_nbr, city, week_start_date, MAX(weekly_transactions) AS wk_tx   FROM weekly_store_family_summary   GROUP BY store_nbr, city, week_start_date) SELECT store_nbr, city, SUM(wk_tx) AS total_transactions FROM store_weeks GROUP BY store_nbr, city ORDER BY total_transactions DESC LIMIT 5
```

**Expected Result (5 row(s)):**

| store_nbr | city | total_transactions |
| --- | --- | --- |
| 44 | Quito | 7273093 |
| 47 | Quito | 6535810 |
| 45 | Quito | 6201115 |
| 46 | Quito | 5990113 |
| 3 | Quito | 5366350 |

## `hard_02` (HARD) — Answerable: Yes

**Question:** For each store_type in weekly_store_family_summary, which single store has the highest total unit sales (rank 1 per store_type)?

**Reference SQL:**
```sql
WITH store_totals AS (  SELECT store_type, store_nbr, city, ROUND(SUM(total_sales), 2) AS store_sales,   ROW_NUMBER() OVER (PARTITION BY store_type ORDER BY SUM(total_sales) DESC) AS rk   FROM weekly_store_family_summary   GROUP BY store_type, store_nbr, city) SELECT store_type, store_nbr, city, store_sales FROM store_totals WHERE rk = 1 ORDER BY store_type ASC
```

**Expected Result (5 row(s)):**

| store_type | store_nbr | city | store_sales |
| --- | --- | --- | --- |
| A | 44 | Quito | 62087553.92 |
| B | 11 | Cayambe | 28325558.75 |
| C | 40 | Machala | 18395757.61 |
| D | 3 | Quito | 50481910.58 |
| E | 28 | Guayaquil | 18383155.2 |

## `hard_03` (HARD) — Answerable: Yes

**Question:** Join promo_elasticity_summary and perishable_volatility_summary on store_nbr and family: for PERISHABLE series, what is the average empirical_promo_lift_pct and average cv_demand for each volatility_proxy_tier?

**Reference SQL:**
```sql
SELECT v.volatility_proxy_tier, COUNT(*) AS paired_series, ROUND(AVG(p.empirical_promo_lift_pct), 2) AS avg_promo_lift_pct, ROUND(AVG(v.cv_demand), 4) AS avg_cv_demand FROM promo_elasticity_summary p JOIN perishable_volatility_summary v   ON p.store_nbr = v.store_nbr AND p.family = v.family WHERE v.perishability_class = 'PERISHABLE' GROUP BY v.volatility_proxy_tier ORDER BY avg_cv_demand DESC
```

**Expected Result (2 row(s)):**

| volatility_proxy_tier | paired_series | avg_promo_lift_pct | avg_cv_demand |
| --- | --- | --- | --- |
| HIGH_VOLATILITY_PERISHABLE_PROXY | 61 | 73.45 | 1.1004 |
| MODERATE_VOLATILITY_PERISHABLE_PROXY | 366 | 20.67 | 0.4036 |

## `hard_04` (HARD) — Answerable: Yes

**Question:** Join zero_sales_day_proxy_summary and perishable_volatility_summary on store_nbr and family: which 5 HIGH_VOLATILITY_PERISHABLE_PROXY series have the highest zero_sales_rate_pct?

**Reference SQL:**
```sql
SELECT z.store_nbr, z.city, z.family, ROUND(z.zero_sales_rate_pct, 2) AS zero_sales_rate_pct, ROUND(v.cv_demand, 4) AS cv_demand FROM zero_sales_day_proxy_summary z JOIN perishable_volatility_summary v   ON z.store_nbr = v.store_nbr AND z.family = v.family WHERE v.volatility_proxy_tier = 'HIGH_VOLATILITY_PERISHABLE_PROXY' ORDER BY z.zero_sales_rate_pct DESC, v.cv_demand DESC LIMIT 5
```

**Expected Result (5 row(s)):**

| store_nbr | city | family | zero_sales_rate_pct | cv_demand |
| --- | --- | --- | --- | --- |
| 36 | Libertad | SEAFOOD | 53.529999 | 1.5248 |
| 32 | Guayaquil | SEAFOOD | 48.130001 | 1.4161 |
| 54 | El Carmen | SEAFOOD | 39.450001 | 1.2914 |
| 33 | Quevedo | SEAFOOD | 37.849998 | 1.3519 |
| 13 | Latacunga | SEAFOOD | 37.080002 | 1.198 |

## `hard_05` (HARD) — Answerable: Yes

**Question:** What share of chain-wide unit sales in weekly_store_family_summary comes from each of the top 5 product families (as a percentage of all unit sales across all families)?

**Reference SQL:**
```sql
WITH family_sales AS (  SELECT family, SUM(total_sales) AS fam_sales   FROM weekly_store_family_summary   GROUP BY family), chain AS (  SELECT SUM(fam_sales) AS grand_total FROM family_sales) SELECT f.family, ROUND(100.0 * f.fam_sales / c.grand_total, 2) AS sales_share_pct FROM family_sales f CROSS JOIN chain c ORDER BY sales_share_pct DESC LIMIT 5
```

**Expected Result (5 row(s)):**

| family | sales_share_pct |
| --- | --- |
| GROCERY I | 31.99 |
| BEVERAGES | 20.21 |
| PRODUCE | 11.43 |
| CLEANING | 9.08 |
| DAIRY | 6.01 |

## `hard_06` (HARD) — Answerable: Yes

**Question:** In sim_policy_summary, at service_level = 0.95 (where is_sensitivity_extrapolation is FALSE), how many average_inventory_units does lightgbm_point_safety_stock save compared with seasonal_naive_safety_stock for each lead_time_days?

**Reference SQL:**
```sql
WITH sn AS (  SELECT lead_time_days, average_inventory_units AS sn_inv   FROM sim_policy_summary   WHERE policy = 'seasonal_naive_safety_stock' AND ROUND(service_level, 2) = 0.95     AND is_sensitivity_extrapolation = FALSE), lgb AS (  SELECT lead_time_days, average_inventory_units AS lgb_inv   FROM sim_policy_summary   WHERE policy = 'lightgbm_point_safety_stock' AND ROUND(service_level, 2) = 0.95     AND is_sensitivity_extrapolation = FALSE) SELECT sn.lead_time_days, ROUND(sn.sn_inv - lgb.lgb_inv, 2) AS inventory_saved_units FROM sn JOIN lgb ON sn.lead_time_days = lgb.lead_time_days ORDER BY sn.lead_time_days ASC
```

**Expected Result (2 row(s)):**

| lead_time_days | inventory_saved_units |
| --- | --- |
| 3 | 334058.37 |
| 7 | 359931.89 |

## `hard_07` (HARD) — Answerable: Yes

**Question:** Using a window function or CTE over weekly_store_family_summary, what was the year-over-year percentage change in total chain-wide unit sales from 2014 to 2015 and from 2015 to 2016?

**Reference SQL:**
```sql
WITH yearly AS (  SELECT EXTRACT(YEAR FROM week_start_date) AS yr, SUM(total_sales) AS sales   FROM weekly_store_family_summary   WHERE EXTRACT(YEAR FROM week_start_date) IN (2014, 2015, 2016)   GROUP BY yr), lagged AS (  SELECT yr, sales, LAG(sales) OVER (ORDER BY yr) AS prev_sales   FROM yearly) SELECT yr, ROUND(100.0 * (sales - prev_sales) / prev_sales, 2) AS yoy_growth_pct FROM lagged WHERE prev_sales IS NOT NULL ORDER BY yr ASC
```

**Expected Result (2 row(s)):**

| yr | yoy_growth_pct |
| --- | --- |
| 2015 | 15.85 |
| 2016 | 18.75 |

## `hard_08` (HARD) — Answerable: Yes

**Question:** Compare chain-wide weekly unit sales in weeks with oil price below 50 vs weeks with oil price of 50 or above: what is the number of weeks and average weekly chain sales in each regime?

**Reference SQL:**
```sql
WITH weekly_chain AS (  SELECT week_start_date, AVG(avg_oil_price) AS oil_price,   SUM(total_sales) AS chain_weekly_sales   FROM weekly_store_family_summary   WHERE avg_oil_price IS NOT NULL   GROUP BY week_start_date) SELECT CASE WHEN oil_price < 50 THEN 'UNDER_50' ELSE 'AT_OR_ABOVE_50' END AS oil_regime, COUNT(*) AS n_weeks, ROUND(AVG(chain_weekly_sales), 2) AS avg_weekly_sales FROM weekly_chain GROUP BY oil_regime ORDER BY oil_regime ASC
```

**Expected Result (2 row(s)):**

| oil_regime | n_weeks | avg_weekly_sales |
| --- | --- | --- |
| AT_OR_ABOVE_50 | 145 | 3837920.35 |
| UNDER_50 | 97 | 5331407.42 |

## `hard_09` (HARD) — Answerable: Yes

**Question:** Across all three series-level summary tables (promo_elasticity_summary, zero_sales_day_proxy_summary, perishable_volatility_summary), how many store-family pairs appear in all three tables simultaneously?

**Reference SQL:**
```sql
SELECT COUNT(*) AS common_series_count FROM promo_elasticity_summary p JOIN zero_sales_day_proxy_summary z   ON p.store_nbr = z.store_nbr AND p.family = z.family JOIN perishable_volatility_summary v   ON p.store_nbr = v.store_nbr AND p.family = v.family
```

**Expected Result (1 row(s)):**

| common_series_count |
| --- |
| 1355 |

## `hard_10` (HARD) — Answerable: Yes

**Question:** For each city, which product family has the highest average promo_day_share_pct in promo_elasticity_summary (return the top 5 cities alphabetically with their rank-1 family)?

**Reference SQL:**
```sql
WITH city_family AS (  SELECT city, family, ROUND(AVG(promo_day_share_pct), 2) AS avg_promo_share_pct,   ROW_NUMBER() OVER (PARTITION BY city ORDER BY AVG(promo_day_share_pct) DESC, family ASC) AS rk   FROM promo_elasticity_summary   GROUP BY city, family) SELECT city, family, avg_promo_share_pct FROM city_family WHERE rk = 1 ORDER BY city ASC LIMIT 5
```

**Expected Result (5 row(s)):**

| city | family | avg_promo_share_pct |
| --- | --- | --- |
| Ambato | GROCERY I | 92.44 |
| Babahoyo | GROCERY I | 89.67 |
| Cayambe | GROCERY I | 93.25 |
| Cuenca | GROCERY I | 93.87 |
| Daule | GROCERY I | 92.2 |

## `unans_01` (UNANSWERABLE) — Answerable: No (Refusal Expected)

**Question:** What was the average unit retail price in dollars charged for PRODUCE in Quito stores during 2016?

**Expected Refusal Rationale:** Unit retail prices and dollar revenue are not recorded in the dataset; only unit sales volumes, promotions, transactions, and crude oil prices are available.

## `unans_02` (UNANSWERABLE) — Answerable: No (Refusal Expected)

**Question:** How many units of DAIRY were lost to physical spoilage and shrinkage in Guayaquil stores?

**Expected Refusal Rationale:** Physical spoilage and shrinkage are not recorded in the dataset; perishable_volatility_summary only tracks demand variability as a proxy.

## `unans_03` (UNANSWERABLE) — Answerable: No (Refusal Expected)

**Question:** Which store had the highest gross profit margin and net operating income in 2017?

**Expected Refusal Rationale:** Cost of goods sold, gross profit margins, and operating income are not present in any table.

## `unans_04` (UNANSWERABLE) — Answerable: No (Refusal Expected)

**Question:** How many unique loyalty card customers shopped at store 44 more than three times a week?

**Expected Refusal Rationale:** Customer-level identifiers and loyalty card visit frequencies are not recorded; only aggregate store-level weekly_transactions exist.

## `unans_05` (UNANSWERABLE) — Answerable: No (Refusal Expected)

**Question:** Which supplier had the longest average delivery delay for frozen foods in Ambato?

**Expected Refusal Rationale:** Supplier identifiers and actual supplier delivery logs are not recorded; sim_policy_summary only evaluates fixed simulated lead_time_days (3 and 7).
