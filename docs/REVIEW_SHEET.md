Human verification by: Aditya S Arakali  Date: 2026-10-28  Count: 15 (14 Model correct, 1 Reference correct)

## Question med_04: Which 5 store-family series in promo_elasticity_summary have the highest empirical_promo_lift_pct?

### Reference SQL
```sql
SELECT store_nbr, family, ROUND(empirical_promo_lift_pct, 2) AS empirical_promo_lift_pct FROM promo_elasticity_summary ORDER BY empirical_promo_lift_pct DESC LIMIT 5
```

### Reference Result (first 10 rows)
| store_nbr | family | empirical_promo_lift_pct |
| --- | --- | --- |
| 36 | SCHOOL AND OFFICE SUPPLIES | 7980.77001953125 |
| 54 | SCHOOL AND OFFICE SUPPLIES | 6721.43017578125 |
| 6 | SCHOOL AND OFFICE SUPPLIES | 3617.389892578125 |
| 22 | SCHOOL AND OFFICE SUPPLIES | 3605.0 |
| 10 | SCHOOL AND OFFICE SUPPLIES | 3094.1201171875 |

### Model SQL
```sql
SELECT store_nbr, city, state, store_type, store_cluster, family, empirical_promo_lift_pct FROM promo_elasticity_summary ORDER BY empirical_promo_lift_pct DESC LIMIT 5
```

### Model Result (first 10 rows)
| store_nbr | city | state | store_type | store_cluster | family | empirical_promo_lift_pct |
| --- | --- | --- | --- | --- | --- | --- |
| 36 | Libertad | Guayas | E | 10 | SCHOOL AND OFFICE SUPPLIES | 7980.77001953125 |
| 54 | El Carmen | Manabi | C | 3 | SCHOOL AND OFFICE SUPPLIES | 6721.43017578125 |
| 6 | Quito | Pichincha | D | 13 | SCHOOL AND OFFICE SUPPLIES | 3617.389892578125 |
| 22 | Puyo | Pastaza | C | 7 | SCHOOL AND OFFICE SUPPLIES | 3605.0 |
| 10 | Quito | Pichincha | C | 15 | SCHOOL AND OFFICE SUPPLIES | 3094.1201171875 |

### Difference
Model includes unrequested dimension columns (city, state, store_type, store_cluster) and omits rounding on empirical_promo_lift_pct.

Reviewer verdict: Model correct

Notes: The top five series and their ranking match. Extra store/location fields and unrounded values do not change the answer to the plain-English question.

---

## Question med_05: For each product family in promo_elasticity_summary with at least 20 evaluated series, what is the average empirical_promo_lift_pct, ordered highest first (top 5)?

### Reference SQL
```sql
SELECT family, COUNT(*) AS n_series, ROUND(AVG(empirical_promo_lift_pct), 2) AS avg_lift_pct FROM promo_elasticity_summary GROUP BY family HAVING COUNT(*) >= 20 ORDER BY avg_lift_pct DESC LIMIT 5
```

### Reference Result (first 10 rows)
| family | n_series | avg_lift_pct |
| --- | --- | --- |
| SCHOOL AND OFFICE SUPPLIES | 45 | 1958.48 |
| PET SUPPLIES | 43 | 119.28 |
| BEAUTY | 54 | 113.24 |
| LAWN AND GARDEN | 39 | 98.25 |
| PRODUCE | 53 | 93.57 |

### Model SQL
```sql
SELECT family, AVG(empirical_promo_lift_pct) AS avg_empirical_promo_lift_pct FROM promo_elasticity_summary GROUP BY family HAVING COUNT(*) >= 20 ORDER BY avg_empirical_promo_lift_pct DESC LIMIT 5
```

### Model Result (first 10 rows)
| family | avg_empirical_promo_lift_pct |
| --- | --- |
| SCHOOL AND OFFICE SUPPLIES | 1958.4846632215713 |
| PET SUPPLIES | 119.27720912667208 |
| BEAUTY | 113.2394437260098 |
| LAWN AND GARDEN | 98.24666634584085 |
| PRODUCE | 93.56603792478454 |

### Difference
Model omits the requested series count (n_series) column and omits rounding on avg_empirical_promo_lift_pct.

Reviewer verdict: Model correct

Notes: The same five families and averages are returned in the same ranking. The prompt does not require displaying n_series; the extra precision does not change the substantive answer.

---

## Question med_07: Which 5 HIGH_VELOCITY_ELEVATED_ZERO_SALES_DAYS_PROXY series in zero_sales_day_proxy_summary have the highest zero_sales_rate_pct?

### Reference SQL
```sql
SELECT store_nbr, city, family, ROUND(zero_sales_rate_pct, 2) AS zero_sales_rate_pct, ROUND(mean_daily_sales, 2) AS mean_daily_sales FROM zero_sales_day_proxy_summary WHERE zero_sales_proxy_tier = 'HIGH_VELOCITY_ELEVATED_ZERO_SALES_DAYS_PROXY' ORDER BY zero_sales_rate_pct DESC, mean_daily_sales DESC LIMIT 5
```

### Reference Result (first 10 rows)
| store_nbr | city | family | zero_sales_rate_pct | mean_daily_sales |
| --- | --- | --- | --- | --- |
| 18 | Quito | PRODUCE | 31.309999465942383 | 1117.77001953125 |
| 18 | Quito | HOME CARE | 29.190000534057617 | 139.02000427246094 |
| 25 | Salinas | HOME CARE | 25.68000030517578 | 84.12000274658203 |
| 14 | Riobamba | PRODUCE | 23.729999542236328 | 291.6499938964844 |
| 43 | Esmeraldas | PRODUCE | 23.280000686645508 | 625.8699951171875 |

### Model SQL
```sql
SELECT store_nbr, city, state, family, zero_sales_rate_pct FROM zero_sales_day_proxy_summary WHERE zero_sales_proxy_tier = 'HIGH_VELOCITY_ELEVATED_ZERO_SALES_DAYS_PROXY' ORDER BY zero_sales_rate_pct DESC LIMIT 5
```

### Model Result (first 10 rows)
| store_nbr | city | state | family | zero_sales_rate_pct |
| --- | --- | --- | --- | --- |
| 18 | Quito | Pichincha | PRODUCE | 31.309999465942383 |
| 18 | Quito | Pichincha | HOME CARE | 29.190000534057617 |
| 25 | Salinas | Santa Elena | HOME CARE | 25.68000030517578 |
| 14 | Riobamba | Chimborazo | PRODUCE | 23.729999542236328 |
| 43 | Esmeraldas | Esmeraldas | PRODUCE | 23.280000686645508 |

### Difference
Model includes state column, omits secondary sort by mean_daily_sales, and omits rounding.

Reviewer verdict: Model correct

Notes: The same five series are returned in the same order. The displayed zero_sales_rate_pct values are distinct, so omitting the secondary mean_daily_sales sort does not change these results.

---

## Question med_08: In perishable_volatility_summary, what is the average cv_demand and series count for each volatility_proxy_tier?

### Reference SQL
```sql
SELECT volatility_proxy_tier, COUNT(*) AS series_count, ROUND(AVG(cv_demand), 4) AS avg_cv_demand FROM perishable_volatility_summary GROUP BY volatility_proxy_tier ORDER BY avg_cv_demand DESC
```

### Reference Result (first 10 rows)
| volatility_proxy_tier | series_count | avg_cv_demand |
| --- | --- | --- |
| HIGH_VOLATILITY_PERISHABLE_PROXY | 61 | 1.1004 |
| NON_PERISHABLE_OR_LOW_VOLATILITY | 1095 | 0.9434 |
| MODERATE_VOLATILITY_PERISHABLE_PROXY | 369 | 0.4024 |

### Model SQL
```sql
SELECT volatility_proxy_tier, AVG(cv_demand) AS avg_cv_demand, COUNT(*) AS series_count FROM perishable_volatility_summary GROUP BY volatility_proxy_tier LIMIT 100
```

### Model Result (first 10 rows)
| volatility_proxy_tier | avg_cv_demand | series_count |
| --- | --- | --- |
| NON_PERISHABLE_OR_LOW_VOLATILITY | 0.9434487673109525 | 1095 |
| MODERATE_VOLATILITY_PERISHABLE_PROXY | 0.4023688342674638 | 369 |
| HIGH_VOLATILITY_PERISHABLE_PROXY | 1.1003721356391907 | 61 |

### Difference
Model projects columns in different order (avg_cv_demand before series_count) and omits rounding on avg_cv_demand.

Reviewer verdict: Model correct

Notes: Both requested measures are present and match. The question does not specify row order or rounding, so the different column order and greater numeric precision are harmless.

---

## Question med_09: Among PERISHABLE families in perishable_volatility_summary, what is the average cv_demand per family, ordered highest first?

### Reference SQL
```sql
SELECT family, COUNT(*) AS n_stores, ROUND(AVG(cv_demand), 4) AS avg_cv_demand FROM perishable_volatility_summary WHERE perishability_class = 'PERISHABLE' GROUP BY family ORDER BY avg_cv_demand DESC
```

### Reference Result (first 10 rows)
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

### Model SQL
```sql
SELECT family, AVG(cv_demand) AS avg_cv_demand FROM perishable_volatility_summary WHERE perishability_class = 'PERISHABLE' GROUP BY family ORDER BY avg_cv_demand DESC LIMIT 100
```

### Model Result (first 10 rows)
| family | avg_cv_demand |
| --- | --- |
| PRODUCE | 0.7192462964190377 |
| SEAFOOD | 0.6943500001843159 |
| MEATS | 0.5744981500837538 |
| EGGS | 0.4840092620363942 |
| POULTRY | 0.46208888733828507 |
| DAIRY | 0.40651666510988166 |
| DELI | 0.34227777769168216 |
| BREAD/BAKERY | 0.3352629633413421 |

### Difference
Model omits the store count (n_stores) column and omits rounding on avg_cv_demand.

Reviewer verdict: Model correct

Notes: The family averages and descending ranking match. The question asks for average cv_demand, not a displayed store count.

---

## Question med_12: In sim_policy_summary, which rows achieve a fill_rate_pct of at least 99.0 at lead_time_days = 7, ordered by average_inventory_units ascending?

### Reference SQL
```sql
SELECT policy, service_level, z_value, fill_rate_pct, average_inventory_units FROM sim_policy_summary WHERE lead_time_days = 7 AND fill_rate_pct >= 99.0 ORDER BY average_inventory_units ASC
```

### Reference Result (first 10 rows)
| policy | service_level | z_value | fill_rate_pct | average_inventory_units |
| --- | --- | --- | --- | --- |
| lightgbm_p50_safety_stock | 0.9 | 1.2815515655446004 | 99.07 | 4041625.9 |
| lightgbm_point_safety_stock | 0.9 | 1.2815515655446004 | 99.25 | 4119750.09 |
| lightgbm_p50_safety_stock | 0.95 | 1.6448536269514722 | 99.27 | 4279761.61 |
| lightgbm_point_safety_stock | 0.95 | 1.6448536269514722 | 99.39 | 4347062.97 |
| lightgbm_p50_safety_stock | 0.98 | 2.0537489106318225 | 99.43 | 4552659.84 |
| lightgbm_point_safety_stock | 0.98 | 2.0537489106318225 | 99.51 | 4606306.39 |
| seasonal_naive_safety_stock | 0.95 | 1.6448536269514722 | 99.2 | 4706994.86 |
| seasonal_naive_safety_stock | 0.98 | 2.0537489106318225 | 99.43 | 5021992.13 |

### Model SQL
```sql
SELECT * FROM sim_policy_summary WHERE lead_time_days = 7 AND fill_rate_pct >= 99.0 ORDER BY average_inventory_units ASC LIMIT 100
```

### Model Result (first 10 rows)
| policy | policy_label | stitching_rule | lead_time_days | is_sensitivity_extrapolation | service_level | z_value | fill_rate_pct | stockout_day_share_pct | average_inventory_units | inventory_turns | inventory_turns_note | total_sales_units | total_demand_units | simulation_days | evaluated_days | warmup_days_excluded | n_store_families |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| lightgbm_p50_safety_stock | LightGBM P50 + SS (90%) | reforecast | 7 | False | 0.9 | 1.2815515655446004 | 99.07 | 2.92 | 4041625.9 | 76.9 | Idealized metric under continuous fractional ordering without case packs, MOQs, or warehouse dispatch constraints. | 69824923.0 | 70483472.12 | 96 | 82 | 14 | 1782 |
| lightgbm_point_safety_stock | LightGBM Point + SS (90%) | reforecast | 7 | False | 0.9 | 1.2815515655446004 | 99.25 | 2.95 | 4119750.09 | 75.58 | Idealized metric under continuous fractional ordering without case packs, MOQs, or warehouse dispatch constraints. | 69953879.44 | 70483472.12 | 96 | 82 | 14 | 1782 |
| lightgbm_p50_safety_stock | LightGBM P50 + SS (95%) | reforecast | 7 | False | 0.95 | 1.6448536269514722 | 99.27 | 2.12 | 4279761.61 | 72.77 | Idealized metric under continuous fractional ordering without case packs, MOQs, or warehouse dispatch constraints. | 69965859.75 | 70483472.12 | 96 | 82 | 14 | 1782 |
| lightgbm_point_safety_stock | LightGBM Point + SS (95%) | reforecast | 7 | False | 0.95 | 1.6448536269514722 | 99.39 | 2.14 | 4347062.97 | 71.73 | Idealized metric under continuous fractional ordering without case packs, MOQs, or warehouse dispatch constraints. | 70052648.88 | 70483472.12 | 96 | 82 | 14 | 1782 |
| lightgbm_p50_safety_stock | LightGBM P50 + SS (98%) | reforecast | 7 | False | 0.98 | 2.0537489106318225 | 99.43 | 1.5 | 4552659.84 | 68.52 | Idealized metric under continuous fractional ordering without case packs, MOQs, or warehouse dispatch constraints. | 70083084.31 | 70483472.12 | 96 | 82 | 14 | 1782 |
| lightgbm_point_safety_stock | LightGBM Point + SS (98%) | reforecast | 7 | False | 0.98 | 2.0537489106318225 | 99.51 | 1.5 | 4606306.39 | 67.77 | Idealized metric under continuous fractional ordering without case packs, MOQs, or warehouse dispatch constraints. | 70134595.62 | 70483472.12 | 96 | 82 | 14 | 1782 |
| seasonal_naive_safety_stock | Seasonal Naive + SS (95%) | reforecast | 7 | False | 0.95 | 1.6448536269514722 | 99.2 | 1.37 | 4706994.86 | 66.12 | Idealized metric under continuous fractional ordering without case packs, MOQs, or warehouse dispatch constraints. | 69919110.19 | 70483472.12 | 96 | 82 | 14 | 1782 |
| seasonal_naive_safety_stock | Seasonal Naive + SS (98%) | reforecast | 7 | False | 0.98 | 2.0537489106318225 | 99.43 | 0.89 | 5021992.13 | 62.11 | Idealized metric under continuous fractional ordering without case packs, MOQs, or warehouse dispatch constraints. | 70079394.69 | 70483472.12 | 96 | 82 | 14 | 1782 |

### Difference
Model selects all columns (SELECT *) instead of projecting only the requested policy and performance metrics.

Reviewer verdict: Model correct

Notes: The qualifying rows and ascending inventory order match. SELECT * adds columns but still answers which rows qualify; the provided result shows no qualifying sensitivity-extrapolation rows.

---

## Question hard_01: Without double counting across product families, which 5 stores had the highest total weekly_transactions across all weeks in weekly_store_family_summary?

### Reference SQL
```sql
WITH store_weeks AS (  SELECT store_nbr, city, week_start_date, MAX(weekly_transactions) AS wk_tx   FROM weekly_store_family_summary   GROUP BY store_nbr, city, week_start_date) SELECT store_nbr, city, SUM(wk_tx) AS total_transactions FROM store_weeks GROUP BY store_nbr, city ORDER BY total_transactions DESC LIMIT 5
```

### Reference Result (first 10 rows)
| store_nbr | city | total_transactions |
| --- | --- | --- |
| 44 | Quito | 7273093 |
| 47 | Quito | 6535810 |
| 45 | Quito | 6201115 |
| 46 | Quito | 5990113 |
| 3 | Quito | 5366350 |

### Model SQL
```sql
WITH weekly_tx AS (SELECT store_nbr, week_start_date, MAX(weekly_transactions) AS week_tx FROM weekly_store_family_summary GROUP BY store_nbr, week_start_date) SELECT store_nbr, SUM(week_tx) AS total_weekly_transactions FROM weekly_tx GROUP BY store_nbr ORDER BY total_weekly_transactions DESC LIMIT 5
```

### Model Result (first 10 rows)
| store_nbr | total_weekly_transactions |
| --- | --- |
| 44 | 7273093 |
| 47 | 6535810 |
| 45 | 6201115 |
| 46 | 5990113 |
| 3 | 5366350 |

### Difference
Model groups only by store_nbr omitting city from the projection and grouping.

Reviewer verdict: Model correct

Notes: Both queries deduplicate the store-week transaction value with MAX before summing, avoiding family-level double counting. Store number identifies each store in the shown results, so omitting city does not change the ranking or totals.

---

## Question hard_02: For each store_type in weekly_store_family_summary, which single store has the highest total unit sales (rank 1 per store_type)?

### Reference SQL
```sql
WITH store_totals AS (  SELECT store_type, store_nbr, city, ROUND(SUM(total_sales), 2) AS store_sales,   ROW_NUMBER() OVER (PARTITION BY store_type ORDER BY SUM(total_sales) DESC) AS rk   FROM weekly_store_family_summary   GROUP BY store_type, store_nbr, city) SELECT store_type, store_nbr, city, store_sales FROM store_totals WHERE rk = 1 ORDER BY store_type ASC
```

### Reference Result (first 10 rows)
| store_type | store_nbr | city | store_sales |
| --- | --- | --- | --- |
| A | 44 | Quito | 62087553.92 |
| B | 11 | Cayambe | 28325558.75 |
| C | 40 | Machala | 18395757.61 |
| D | 3 | Quito | 50481910.58 |
| E | 28 | Guayaquil | 18383155.2 |

### Model SQL
```sql
WITH store_sales AS (SELECT store_type, store_nbr, SUM(total_sales) AS total_sales FROM weekly_store_family_summary GROUP BY store_type, store_nbr) SELECT store_type, store_nbr, total_sales FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY store_type ORDER BY total_sales DESC) AS rn FROM store_sales) AS t WHERE rn = 1 ORDER BY store_type LIMIT 100
```

### Model Result (first 10 rows)
| store_type | store_nbr | total_sales |
| --- | --- | --- |
| A | 44 | 62087553.92466736 |
| B | 11 | 28325558.747299194 |
| C | 40 | 18395757.613925934 |
| D | 3 | 50481910.58299255 |
| E | 28 | 18383155.196544647 |

### Difference
Model omits city column from the projection and intermediate CTE.

Reviewer verdict: Model correct

Notes: The winning store in each store_type and each total match. City is supplemental because store_nbr identifies the store; the difference in rounding is presentational. Confirm that total_sales is the intended measure for the prompt’s phrase “unit sales.”

---

## Question hard_03: Join promo_elasticity_summary and perishable_volatility_summary on store_nbr and family: for PERISHABLE series, what is the average empirical_promo_lift_pct and average cv_demand for each volatility_proxy_tier?

### Reference SQL
```sql
SELECT v.volatility_proxy_tier, COUNT(*) AS paired_series, ROUND(AVG(p.empirical_promo_lift_pct), 2) AS avg_promo_lift_pct, ROUND(AVG(v.cv_demand), 4) AS avg_cv_demand FROM promo_elasticity_summary p JOIN perishable_volatility_summary v   ON p.store_nbr = v.store_nbr AND p.family = v.family WHERE v.perishability_class = 'PERISHABLE' GROUP BY v.volatility_proxy_tier ORDER BY avg_cv_demand DESC
```

### Reference Result (first 10 rows)
| volatility_proxy_tier | paired_series | avg_promo_lift_pct | avg_cv_demand |
| --- | --- | --- | --- |
| HIGH_VOLATILITY_PERISHABLE_PROXY | 61 | 73.45 | 1.1004 |
| MODERATE_VOLATILITY_PERISHABLE_PROXY | 366 | 20.67 | 0.4036 |

### Model SQL
```sql
SELECT pvs.volatility_proxy_tier, AVG(pes.empirical_promo_lift_pct) AS avg_empirical_promo_lift_pct, AVG(pvs.cv_demand) AS avg_cv_demand FROM perishable_volatility_summary AS pvs JOIN promo_elasticity_summary AS pes ON pvs.store_nbr = pes.store_nbr AND pvs.family = pes.family WHERE pvs.perishability_class = 'PERISHABLE' GROUP BY pvs.volatility_proxy_tier ORDER BY pvs.volatility_proxy_tier LIMIT 100
```

### Model Result (first 10 rows)
| volatility_proxy_tier | avg_empirical_promo_lift_pct | avg_cv_demand |
| --- | --- | --- |
| HIGH_VOLATILITY_PERISHABLE_PROXY | 73.44950826050805 | 1.1003721356391907 |
| MODERATE_VOLATILITY_PERISHABLE_PROXY | 20.66535518758121 | 0.4035699448950304 |

### Difference
Model orders by volatility_proxy_tier instead of avg_cv_demand DESC and omits paired_series count.

Reviewer verdict: Model correct

Notes: The two averages match. paired_series is useful context but is not explicitly requested, and the question does not specify a sort order.

---

## Question hard_04: Join zero_sales_day_proxy_summary and perishable_volatility_summary on store_nbr and family: which 5 HIGH_VOLATILITY_PERISHABLE_PROXY series have the highest zero_sales_rate_pct?

### Reference SQL
```sql
SELECT z.store_nbr, z.city, z.family, ROUND(z.zero_sales_rate_pct, 2) AS zero_sales_rate_pct, ROUND(v.cv_demand, 4) AS cv_demand FROM zero_sales_day_proxy_summary z JOIN perishable_volatility_summary v   ON z.store_nbr = v.store_nbr AND z.family = v.family WHERE v.volatility_proxy_tier = 'HIGH_VOLATILITY_PERISHABLE_PROXY' ORDER BY z.zero_sales_rate_pct DESC, v.cv_demand DESC LIMIT 5
```

### Reference Result (first 10 rows)
| store_nbr | city | family | zero_sales_rate_pct | cv_demand |
| --- | --- | --- | --- | --- |
| 36 | Libertad | SEAFOOD | 53.529998779296875 | 1.5247999429702759 |
| 32 | Guayaquil | SEAFOOD | 48.130001068115234 | 1.416100025177002 |
| 54 | El Carmen | SEAFOOD | 39.45000076293945 | 1.2913999557495117 |
| 33 | Quevedo | SEAFOOD | 37.849998474121094 | 1.3518999814987183 |
| 13 | Latacunga | SEAFOOD | 37.08000183105469 | 1.1979999542236328 |

### Model SQL
```sql
SELECT z.store_nbr, z.city, z.family, z.zero_sales_rate_pct FROM zero_sales_day_proxy_summary AS z JOIN perishable_volatility_summary AS p USING (store_nbr, family) WHERE p.volatility_proxy_tier = 'HIGH_VOLATILITY_PERISHABLE_PROXY' ORDER BY z.zero_sales_rate_pct DESC LIMIT 5
```

### Model Result (first 10 rows)
| store_nbr | city | family | zero_sales_rate_pct |
| --- | --- | --- | --- |
| 36 | Libertad | SEAFOOD | 53.529998779296875 |
| 32 | Guayaquil | SEAFOOD | 48.130001068115234 |
| 54 | El Carmen | SEAFOOD | 39.45000076293945 |
| 33 | Quevedo | SEAFOOD | 37.849998474121094 |
| 13 | Latacunga | SEAFOOD | 37.08000183105469 |

### Difference
Model omits the cv_demand column from projection and secondary sort order.

Reviewer verdict: Model correct

Notes: The same five series are returned in the same order. cv_demand and its secondary sort are not required by the wording; the shown zero_sales_rate_pct values are distinct.

---

## Question hard_07: Using a window function or CTE over weekly_store_family_summary, what was the year-over-year percentage change in total chain-wide unit sales from 2014 to 2015 and from 2015 to 2016?

### Reference SQL
```sql
WITH yearly AS (  SELECT EXTRACT(YEAR FROM week_start_date) AS yr, SUM(total_sales) AS sales   FROM weekly_store_family_summary   WHERE EXTRACT(YEAR FROM week_start_date) IN (2014, 2015, 2016)   GROUP BY yr), lagged AS (  SELECT yr, sales, LAG(sales) OVER (ORDER BY yr) AS prev_sales   FROM yearly) SELECT yr, ROUND(100.0 * (sales - prev_sales) / prev_sales, 2) AS yoy_growth_pct FROM lagged WHERE prev_sales IS NOT NULL ORDER BY yr ASC
```

### Reference Result (first 10 rows)
| yr | yoy_growth_pct |
| --- | --- |
| 2015 | 15.85 |
| 2016 | 18.75 |

### Model SQL
```sql
WITH yearly_sales AS (SELECT CAST(EXTRACT(YEAR FROM week_start_date) AS INT) AS year, SUM(total_sales) AS total_sales FROM weekly_store_family_summary WHERE EXTRACT(YEAR FROM week_start_date) IN (2014, 2015, 2016) GROUP BY year) SELECT year, total_sales, LAG(total_sales) OVER (ORDER BY year) AS prev_year_sales, CASE WHEN LAG(total_sales) OVER (ORDER BY year) IS NULL THEN NULL ELSE 100.0 * (total_sales - LAG(total_sales) OVER (ORDER BY year)) / LAG(total_sales) OVER (ORDER BY year) END AS yoy_pct_change FROM yearly_sales WHERE year IN (2015, 6) /* typo intentional? Actually need 2015 and 2016 */ ORDER BY year LIMIT 100
```

### Model Result (first 10 rows)
| year | total_sales | prev_year_sales | yoy_pct_change |
| --- | --- | --- | --- |
| 2015 | 241139609.98397636 | NULL | NULL |

### Difference
Model selects intermediate columns (total_sales, prev_year_sales) and contains a filter syntax error (year IN (2015, 6)).

Reviewer verdict: Reference correct

Notes: The model filters on year IN (2015, 6), which excludes 2016. Also, filtering the yearly rows before applying LAG leaves 2015 without its 2014 predecessor, so it cannot calculate the requested comparisons. Clarify whether total_sales represents units or monetary sales.

---

## Question hard_08: Compare chain-wide weekly unit sales in weeks with oil price below 50 vs weeks with oil price of 50 or above: what is the number of weeks and average weekly chain sales in each regime?

### Reference SQL
```sql
WITH weekly_chain AS (  SELECT week_start_date, AVG(avg_oil_price) AS oil_price,   SUM(total_sales) AS chain_weekly_sales   FROM weekly_store_family_summary   WHERE avg_oil_price IS NOT NULL   GROUP BY week_start_date) SELECT CASE WHEN oil_price < 50 THEN 'UNDER_50' ELSE 'AT_OR_ABOVE_50' END AS oil_regime, COUNT(*) AS n_weeks, ROUND(AVG(chain_weekly_sales), 2) AS avg_weekly_sales FROM weekly_chain GROUP BY oil_regime ORDER BY oil_regime ASC
```

### Reference Result (first 10 rows)
| oil_regime | n_weeks | avg_weekly_sales |
| --- | --- | --- |
| AT_OR_ABOVE_50 | 145 | 3837920.35 |
| UNDER_50 | 97 | 5331407.42 |

### Model SQL
```sql
WITH weekly_chain AS (SELECT week_start_date, MAX(avg_oil_price) AS avg_oil_price, SUM(total_sales) AS week_sales FROM weekly_store_family_summary GROUP BY week_start_date) SELECT CASE WHEN avg_oil_price < 50 THEN 'below_50' ELSE '50_or_above' END AS oil_price_regime, COUNT(*) AS num_weeks, AVG(week_sales) AS avg_weekly_chain_sales FROM weekly_chain GROUP BY oil_price_regime LIMIT 100
```

### Model Result (first 10 rows)
| oil_price_regime | num_weeks | avg_weekly_chain_sales |
| --- | --- | --- |
| 50_or_above | 145 | 3837920.35060109 |
| below_50 | 97 | 5331407.41627237 |

### Difference
Model outputs lowercase regime labels (below_50 / 50_or_above) instead of UPPERCASE (UNDER_50 / AT_OR_ABOVE_50) and unrounded sales.

Reviewer verdict: Model correct

Notes: The shown weekly counts and averages match. The label wording/case and extra precision are harmless here. MAX(avg_oil_price) agrees with AVG only if oil price is constant within each week; adding an explicit non-NULL oil-price filter would make the intended regime definition more robust. Confirm that total_sales is the intended measure for “unit sales.”

---

## Question easy_01: How many total rows are in the weekly_store_family_summary table?

### Reference SQL
```sql
SELECT COUNT(*) AS row_count FROM weekly_store_family_summary
```

### Reference Result (first 10 rows)
| row_count |
| --- |
| 431244 |

### Model SQL
```sql
SELECT COUNT(*) AS total_rows FROM weekly_store_family_summary LIMIT 100
```

### Model Result (first 10 rows)
| total_rows |
| --- |
| 431244 |

### Difference
Model SQL matches reference query semantics and returns identical single-value result.

Reviewer verdict: Model correct

Notes: The count and query semantics match exactly; the output alias and LIMIT do not change this aggregate result.

---

## Question easy_02: How many distinct stores are represented in weekly_store_family_summary?

### Reference SQL
```sql
SELECT COUNT(DISTINCT store_nbr) AS store_count FROM weekly_store_family_summary
```

### Reference Result (first 10 rows)
| store_count |
| --- |
| 54 |

### Model SQL
```sql
SELECT COUNT(DISTINCT store_nbr) AS distinct_store_count FROM weekly_store_family_summary LIMIT 100
```

### Model Result (first 10 rows)
| distinct_store_count |
| --- |
| 54 |

### Difference
Model SQL matches reference query semantics and returns identical single-value result.

Reviewer verdict: Model correct

Notes: COUNT(DISTINCT store_nbr) correctly returns 54. The alias and LIMIT are harmless.

---

## Question easy_03: How many distinct product families exist in weekly_store_family_summary?

### Reference SQL
```sql
SELECT COUNT(DISTINCT family) AS family_count FROM weekly_store_family_summary
```

### Reference Result (first 10 rows)
| family_count |
| --- |
| 33 |

### Model SQL
```sql
SELECT COUNT(DISTINCT family) AS distinct_families FROM weekly_store_family_summary LIMIT 100
```

### Model Result (first 10 rows)
| distinct_families |
| --- |
| 33 |

### Difference
Model SQL matches reference query semantics and returns identical single-value result.

Reviewer verdict: Model correct

Notes: COUNT(DISTINCT family) correctly returns 33. The alias and LIMIT are harmless.

---

## Overall uncertainty note
The sheet does not define whether `total_sales` is a unit measure or a monetary measure, so confirm that terminology for hard_02, hard_07, and hard_08. In hard_08, the shown results match, but `MAX(avg_oil_price)` is equivalent to `AVG(avg_oil_price)` only if the oil price is constant within each week; explicitly excluding NULL oil-price weeks would make the regime logic clearer.
