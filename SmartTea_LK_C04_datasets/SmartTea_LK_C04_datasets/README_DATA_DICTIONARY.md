# SmartTea-LK Component 04 — Synthetic Training Datasets

**Status:** SYNTHETIC data produced by a process model (`generate_smarttea_data.py`). It is not field data.
Agronomic parameters are approximate defaults. Calibrate them against Tea Research Institute (TRI) guidance or real estate records before drawing agronomic conclusions.

- **Scope:** 5 estates × 10 blocks = **50 blocks**, **2021-01-01 → 2025-12-31** (1,826 days)
- **Zones:** Up-country (E01, E02), Mid-country (E03), Low-country (E04, E05)
- **Link key:** `block_id` (e.g. `E03-B07`); weather links by `estate_id` + `date`
- **Reproducible:** `python generate_smarttea_data.py --out ./data --seed 42`
- **More data:** `--blocks-per-estate 16` (80 blocks) or `--start 2019-01-01`

## Files

| File | Rows | Grain | Used by |
|---|---|---|---|
| 01_block_master.csv | 50 | 1 per block | All models (static features) |
| 02_weather_daily.csv | 9,130 | estate × day | Weather model, feature building |
| 03_sensor_readings_daily.csv | 91,300 | block × day | The "manual IoT input" history |
| 04_yield_plucking_records.csv | 9,035 | block × plucking round | Yield target |
| 05_intervention_records.csv | 1,763 | 1 per field action | Runoff model, outcome analysis |
| 06_resource_usage_monthly.csv | 1,200 | estate × month × resource | Inventory / NSGA-II resource limits |
| 07_operational_constraints.csv | 25 | 1 per rule | NSGA-II bounds + Action-Window rules |
| **ml_yield_training.csv** | 9,035 | 1 per plucking round | **XGBoost yield surrogate** |
| **ml_runoff_training.csv** | 850 | 1 per fertilizer application | **XGBoost runoff / efficiency model** |

## Cause-and-effect built into the simulation

| Driver | Effect |
|---|---|
| Rain in the 12–72 h after fertilizer, steep slope, saturated soil | ↑ runoff loss → less N reaches the soil → lower yield later |
| Very dry soil at application (esp. urea) | ↑ volatilisation loss |
| Soil moisture below ~25% | Water stress → lower growth |
| Soil N | Growth rises with diminishing returns; small penalty when N is very high |
| pH outside 4.5–5.5 | Growth penalty. N fertilizer acidifies the soil; dolomite raises pH |
| Mean temperature outside 18–26 °C | Growth slows (up-country is cool, low-country is hot) |
| Light (radiation × shade) | Mild growth effect |
| Wet, cloudy 5-day spells above 600 m | Blister-blight loss. Fungicide protects for ~10 days unless washed off by rain within 4 h |
| Pruning cycle | No plucking for ~60 days, then recovery, a peak in year 2 and a slow decline |
| Cultivar / bush age | VP clones yield more than seedling tea; young and very old bushes yield less |

Historical fertilizer timing follows a **static calendar with random jitter**. That is the "traditional practice" the framework replaces. Because timing was not weather-aware, the data contains many good and bad application windows for the models to learn from.

## Column reference

### 01_block_master.csv
| Column | Unit | Notes |
|---|---|---|
| block_id, estate_id, estate_name | — | IDs (estate names are fictional) |
| agro_zone | up / mid / low | Elevation class |
| region, latitude, longitude | — | Approximate location. Use lat/lon for live Open-Meteo calls |
| area_ha | ha | 3–25 |
| elevation_m | m | Low <600, mid 600–1200, up >1200 |
| slope_pct | % | 5–45; drives runoff |
| aspect | — | Descriptive only; **no effect in the simulation** |
| soil_type, field_capacity_pct, wilting_point_pct | %, % | Soil water limits |
| cultivar | — | VP_clone_A/B/C or Seedling |
| bush_age_yrs | years | |
| shade_tree_cover_pct | % | Reduces light |
| pruning_cycle_yrs, last_pruning_date_before_2021 | — | Pruning schedule |
| irrigation_available | bool | Young blocks plus a few others |

### 02_weather_daily.csv
`rainfall_mm`, `temp_min_c`, `temp_mean_c`, `temp_max_c`, `humidity_pct`, `wind_speed_ms`, `solar_radiation_mj_m2`, `sunshine_hours`, `et0_mm` (reference evapotranspiration).
Seasonality follows the SW (May–Sep) and NE (Dec–Feb) monsoons and the inter-monsoon months. Each year has its own wet/dry anomaly.

### 03_sensor_readings_daily.csv — same fields as the manual input form
| Column | Unit | Notes |
|---|---|---|
| soil_moisture_pct | % vol | 08:00 reading |
| soil_ph | pH | |
| soil_n_ppm, soil_p_ppm, soil_k_ppm | ppm | Plant-available nutrients |
| soil_temp_c | °C | |
| light_lux | lux | Average daylight under canopy/shade |
| sunshine_hours | h | |

About 1.5% of values are deliberately **missing**, to mimic sensor dropouts or missed entries. Readings include measurement noise.

### 04_yield_plucking_records.csv
`pluck_date`, `round_days` (days since previous pluck), `plucking_standard` (fine/medium/coarse), `green_leaf_kg_per_ha`, `green_leaf_kg` (block total), `days_since_pruning`, `green_leaf_kg_per_ha_per_day`.
Mean annual green leaf: up ≈ 7,000, mid ≈ 6,000, low ≈ 9,500 kg/ha.

### 05_intervention_records.csv
| Column | Notes |
|---|---|
| intervention_type | fertilizer (850), fungicide (668), irrigation (212), dolomite (33) |
| product_code / product_desc | NPK_HN, NPK_BAL, UREA, WATER, FUNG_CU, DOLOMITE (generic) |
| execution_datetime | Date + hour of application |
| amount_per_ha, unit, total_amount | kg/ha, L/ha or ml/ha; total = per ha × area |
| n/p/k_kg_per_ha | Nutrients supplied (fertilizer only) |
| irrigation_mm | Irrigation only |
| soil_moisture_at_exec, soil_ph_at_exec, temp_at_exec_c, humidity_at_exec_pct, wind_at_exec_ms | Conditions at execution |
| rain_prev_3d_mm, rain_next_4h/12h/24h/48h/72h_mm | **Actual** rain before/after execution |
| runoff_loss_est_pct, absorption_efficiency_pct | Fertilizer only; estimated loss (includes measurement noise) |
| yield_before_kg_ha_day | Harvest rate in the 28 days before |
| yield_after_kg_ha_day | Harvest rate 7–42 days after |
| yield_delta_pct | Change (confounded by weather and season, like real data) |

### 06_resource_usage_monthly.csv
`stock_start`, `allocated` (planned), `used` (actual), `wastage_pct` per estate, month and resource (fertilizer kg, water L, dolomite kg, fungicide ml).

### 07_operational_constraints.csv
Hard limits and scheduling rules, such as max kg/ha per application, annual N ceiling, 12-h rain-free absorption time, max rain probability, spray wind limit, soil-moisture window, and forecast horizon. **The values are placeholders**; check them against TRI recommendations and product labels.

### ml_yield_training.csv (target: `green_leaf_kg_per_ha_per_day`)
One row per plucking round. Features:
- sensor means and minimums over the round
- weather over the round plus 30-day rain
- N applied in the last 60/90 days, estimated absorbed N, days since last fertilizer
- irrigation, fungicide sprays and dolomite
- days since pruning and plucking standard
- all block static features

⚠️ `green_leaf_kg_per_ha` is the same target in absolute form, so **drop it from the features**.

### ml_runoff_training.csv (target: `runoff_loss_est_pct` or `absorption_efficiency_pct`)
One row per fertilizer application, with block and soil features, product, dose, conditions at execution, and rain before and after.
In the live system, feed **forecast** rain into these rain-after columns to score candidate action windows.

## Baseline check (train 2021–2024, test 2025)

| Model | Yield R² | Yield MAE (kg/ha/day) | Runoff R² | Runoff MAE (%) |
|---|---|---|---|---|
| Ridge | 0.60 | 3.10 | 0.86 | 4.50 |
| Random Forest | 0.85 | 1.86 | 0.90 | 3.89 |
| XGBoost | 0.93 | 1.33 | 0.92 | 3.53 |

The data is learnable, and the expected model ranking appears. Treat these as a sanity check, not final results. Tune the models properly (TimeSeriesSplit + Optuna).

## Limitations to state in the thesis
- Synthetic: models can only learn the relationships coded into the generator.
- Daily weather; hourly rain timing is simulated for intervention windows only.
- Runoff is an estimated value; in real projects it is inferred, for example from soil and leaf N tests.
- The runoff table has 850 rows (fertilizer is only applied 3–4×/yr). Generate more blocks if needed.
