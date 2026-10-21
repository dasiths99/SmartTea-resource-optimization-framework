# SmartTea-LK Component 04: Full Project Record

**AI-Based Tea Plantation Resource Optimization and Intervention Planning**
Owner: Dasith Sathpura · University research project CSP 001 · Record compiled 2026-10-15

This file collects the whole project in one place:
- what the system does;
- where every dataset came from, with direct links;
- how the models were trained and how well they score;
- how the optimizer works;
- the known limits;
- how to run everything;
- a log of the development sessions with Claude Code (8–15 Oct 2026).

Related files:
- `CLAUDE.md`: working instructions for the code assistant.
- `md_files/data/README.md`: data details.
- `notebooks/01_model_training.ipynb`: model training with all outputs.

---

## Contents
1. [Project summary](#1-project-summary)
2. [System architecture](#2-system-architecture)
3. [Data](#3-data)
4. [Tier 1: prediction models](#4-tier-1-prediction-models)
5. [Tier 2: NSGA-II optimizer](#5-tier-2-nsga-ii-optimizer)
6. [Limits and caveats](#6-limits-and-caveats)
7. [Roadmap and status](#7-roadmap-and-status)
8. [How to run everything](#8-how-to-run-everything)
9. [File map](#9-file-map)
10. [Presenting to the panel](#10-presenting-to-the-panel)
11. [Development log (chat sessions)](#11-development-log-chat-sessions)
12. [Glossary](#12-glossary)

---

## 1. Project summary

**Problem.** Tea estates apply fertilizer, irrigation and agrochemicals on fixed calendars that ignore local weather. A monsoon downpour can wash fertilizer away; a dry spell can make a treatment useless.

**Research question.** How can each tea block get the **minimum physical resources for the highest growth**, applied at a time when the weather will not waste them?

**What the system decides** for each block, from its live condition:
- fertilizer: apply or delay, how much, which product;
- irrigation: irrigate or skip;
- fungicide;
- pH correction (dolomite);
- or no action.

It also decides **when**: the best time window in the next 72–96 hours.

**Scope rule.** The scope is purely agronomic. Cost, labour, machinery and budget variables were removed from the framework on purpose and are not used anywhere.

**Region.** 5 real tea-growing locations in Sri Lanka × 10 blocks = **50 blocks**, daily, **1 Jan 2021 – 31 Dec 2025**.

---

## 2. System architecture

### 2.1 Three-tier AI pipeline
```
Inputs ──► Tier 1: Prediction ──► Tier 2: NSGA-II optimizer ──► Tier 3: Action-Window scheduler ──► Recommendation
```
| Tier | What it does | Status |
|---|---|---|
| 1. Prediction | Yield model (CatBoost) + runoff model (XGBoost, monotone) + live weather forecast (Open-Meteo) | ✔ done |
| 2. Optimizer | pymoo NSGA-II chooses N dose and product (and irrigation where allowed) within hard rules | ✔ done |
| 3. Action Window | Scans the hourly 72–96 h forecast for the best time (rain-free ≥ 12 h, soil moisture in band, wind ≤ 4 m/s, 06:00–16:00); handles irrigation day by day | next step |

### 2.2 Inputs
- **IoT readings, entered by hand for now:** soil pH, N, P, K; soil moisture; soil temperature; light (lux / sunshine hours); and the last fertilizer (type, amount, date).
  - There is no IoT hardware yet.
  - **Design rule:** the entry endpoint (`POST /api/readings`) accepts exactly the JSON the future device will send. Adding real sensors later only changes where the data comes from.
- **Live weather:** the Open-Meteo forecast API (free, no key). It gives hourly rain, rain probability, temperature, humidity, wind and radiation.

### 2.3 Output: one recommendation per block
```json
{"block_id":"E03-B07","action":"Apply fertilizer","amount_kg_per_ha":240,
 "window":"2026-10-08 06:00–10:00","reason":"Soil moisture in band; no rain next 14 h",
 "predicted_yield_change_pct":9.2,"efficiency_score":0.93}
```
The system re-runs when a new reading arrives, and every hour as the forecast changes.

### 2.4 Technology stack (fixed by the SmartTea-LK project)
| Layer | Technology |
|---|---|
| Frontend | React.js + Tailwind CSS |
| Backend | Java + Spring Boot |
| Database | MongoDB |
| ML service | Python + FastAPI (internal): XGBoost, CatBoost, scikit-learn, pymoo NSGA-II, Optuna, SHAP |

```
React (Tailwind) ──► Spring Boot ──► MongoDB   (readings, forecasts, recommendations, history)
                        │  ▲
                        ▼  │ HTTP/JSON
                  Python ML service (FastAPI): Tier 1 models + Tier 2 NSGA-II + Tier 3 Action Window
```
- **Spring Boot** is the public API. It owns MongoDB, receives readings, fetches the forecast, and runs the hourly job (`@Scheduled`).
- **The Python ML service** is stateless. It receives a block, its latest reading and the forecast, and returns the recommendation JSON. It never touches MongoDB.
- **React** talks only to Spring Boot.
- **Why Python for ML:** Java has no practical equivalent of XGBoost training, pymoo or SHAP.

---

## 3. Data

### 3.1 Locations (real places; the estate names are fictional)
| Estate | Region | Zone | Latitude | Longitude | Weather grid elevation |
|---|---|---|---|---|---|
| E01 | Nuwara Eliya | Up-country | 6.97 | 80.78 | 1,868 m |
| E02 | Hatton / Dimbula | Up-country | 6.89 | 80.60 | 1,288 m |
| E03 | Kandy | Mid-country | 7.25 | 80.65 | 632 m |
| E04 | Ratnapura | Low-country | 6.68 | 80.40 | 27 m |
| E05 | Deniyaya / Matara | Low-country | 6.34 | 80.56 | 424 m |

- These coordinates are in `data/interim/real/00_estate_locations.csv`.
- The 50 block coordinates are in `data/processed/hybrid/01_block_master.csv`.

### 3.2 Real data sources (all public, downloaded 2026-10-08)
| Data | Platform | Licence | Files |
|---|---|---|---|
| Hourly weather + soil moisture/temperature 2021–2025 (ERA5 / ERA5-Land) | Open-Meteo Historical Weather API: https://open-meteo.com/en/docs/historical-weather-api | CC BY 4.0 | 1 |
| Real issued forecasts, 0–4 day lead, from 2024-01-19 | Open-Meteo Previous Runs API: https://open-meteo.com/en/docs/previous-runs-api | CC BY 4.0 | 1 |
| Daily weather cross-check | NASA POWER: https://power.larc.nasa.gov/ | NASA open data | 1 |
| Soil (pH, total N, clay, sand, silt, SOC, CEC, bulk density, coarse fragments; 3 depths; 50 blocks) | ISRIC SoilGrids 2.0, 250 m: https://docs.isric.org/globaldata/soilgrids/ (map: https://soilgrids.org) | CC BY 4.0 | 1 |
| National monthly tea production by elevation, 2021–2025 | Forbes & Walker Tea Brokers: https://www.forbestea.com/statistics-national-production | Public report, cite Forbes & Walker | 47 PDFs |

**Proof of origin.**
- `data/raw/MANIFEST.csv` lists all **51 raw files** with source, URL, licence, download date and SHA-256 checksum.
- `python -m src.data.check_data` re-checks the checksums. Last result: **"PASS raw: all files match MANIFEST checksums (51 files)"**.

**Live check (2026-10-15).** Weather for Nuwara Eliya, 1–7 Jan 2025, downloaded again from Open-Meteo, matched the project data **exactly**:

| Date | Rain, live | Rain, project | Temp, live | Temp, project |
|---|---|---|---|---|
| 2025-01-01 | 44.0 mm | 44.0 mm | 15.6 °C | 15.6 °C |
| 2025-01-02 | 5.6 | 5.6 | 15.1 | 15.1 |
| 2025-01-03 | 3.9 | 3.9 | 15.2 | 15.2 |
| 2025-01-04 | 4.0 | 4.0 | 15.7 | 15.7 |
| 2025-01-05 | 0.6 | 0.6 | 16.0 | 16.0 |
| 2025-01-06 | 1.0 | 1.0 | 15.2 | 15.2 |
| 2025-01-07 | 0.5 | 0.5 | 15.2 | 15.2 |

### 3.3 Direct download links (rebuilt from the raw-file variables; shown for E01)
For another estate, change `latitude` and `longitude` (table 3.1).

These links were rebuilt from the variable names in the raw files. The original download recorded only the platform pages.

**Open-Meteo ERA5, hourly** (tested 2026-10-15: OK)
```
https://archive-api.open-meteo.com/v1/archive?latitude=6.97&longitude=80.78&start_date=2021-01-01&end_date=2025-12-31&hourly=temperature_2m,relative_humidity_2m,dew_point_2m,precipitation,rain,cloud_cover,wind_speed_10m,wind_gusts_10m,shortwave_radiation,sunshine_duration,et0_fao_evapotranspiration,vapour_pressure_deficit,soil_temperature_0_to_7cm,soil_moisture_0_to_7cm,soil_moisture_7_to_28cm,soil_moisture_28_to_100cm&wind_speed_unit=ms&timezone=Asia%2FColombo&format=csv
```
**Open-Meteo Previous Runs, forecasts 1–4 days ahead** (tested: OK)
```
https://previous-runs-api.open-meteo.com/v1/forecast?latitude=6.97&longitude=80.78&start_date=2024-01-20&end_date=2025-12-31&hourly=precipitation,precipitation_previous_day1,precipitation_previous_day2,precipitation_previous_day3,precipitation_previous_day4,temperature_2m,temperature_2m_previous_day1,wind_speed_10m_previous_day1&wind_speed_unit=ms&timezone=Asia%2FColombo&format=csv
```
**NASA POWER, daily** (tested: OK)
```
https://power.larc.nasa.gov/api/temporal/daily/point?parameters=PRECTOTCORR,T2M,T2M_MAX,T2M_MIN,RH2M,WS2M,ALLSKY_SFC_SW_DWN,ALLSKY_SFC_PAR_TOT,CLRSKY_SFC_SW_DWN,GWETTOP,GWETROOT,GWETPROF,EVPTRNS,PS&community=AG&latitude=6.97&longitude=80.78&start=20210101&end=20251231&format=CSV
```
**ISRIC SoilGrids, block E01-B01**
- On 2026-10-15 the server returned error 502 (down); try again later or use https://soilgrids.org.
```
https://rest.isric.org/soilgrids/v2.0/properties/query?lon=80.7973&lat=6.9736&property=phh2o&property=nitrogen&property=clay&property=sand&property=silt&property=soc&property=cec&property=bdod&property=cfvo&depth=0-5cm&depth=5-15cm&depth=15-30cm&value=mean&value=Q0.05&value=Q0.95
```
- Project values at 0–5 cm: pH 5.4, N 5.56 g/kg, clay 32.8 %.
- The API returns these × 10 as integers (54, 556 cg/kg, 328 g/kg).

**Live demo link for a meeting** (one week, opens in a browser):
```
https://archive-api.open-meteo.com/v1/archive?latitude=6.97&longitude=80.78&start_date=2025-01-01&end_date=2025-01-07&hourly=precipitation,temperature_2m&timezone=Asia%2FColombo
```

### 3.4 Real vs simulated (the dataset is a **hybrid**)
| Real | Simulated (generated on top of the real environment) |
|---|---|
| Weather, hourly rain timing after each action | Fertilizer, irrigation, fungicide and dolomite decisions |
| Issued weather forecasts (real from 2024-01-20; before that, sampled from the real forecast-error distribution) | Crop growth / yield response |
| SoilGrids soil properties per block | Runoff / absorption amounts |
| Field capacity and wilting point (Saxton-Rawls, from real soil texture) | Sensor noise and ~1.5 % missing readings |
| National production by elevation (for checking seasonality) | |

**Why hybrid.** No public dataset has block-level tea sensors, fertilizer timing and yield for Sri Lanka. A real estate dataset (from TRI or a plantation company) is the main open step for final validation.

### 3.5 Data layers
```
data/raw/               original downloads + MANIFEST.csv (never edited)
data/interim/real/      real data pack 00–08 (frozen reference)
data/processed/hybrid/  hybrid tables 01–08 + ml_*_training.csv + validation reports
data/model_ready/       ★ feed-ready tables for training (splits, feature_spec.json)
data/release/           SmartTea_LK_C04_Dataset.xlsx: everything in one Excel file (20 sheets, ~34 MB; git-ignored, rebuild)
```
Each layer rebuilds from the one before it.

| File (data/processed/hybrid) | Rows | Content |
|---|---|---|
| 01_block_master.csv | 50 | Block features + SoilGrids soil, FC/WP, temperature offset |
| 02_weather_daily.csv | 9,130 | Real ERA5 daily weather per estate |
| 03_sensor_readings_daily.csv | 91,300 | Daily readings in the manual-entry format |
| 04_yield_plucking_records.csv | 9,053 | Green leaf kg/ha per plucking round |
| 05_intervention_records.csv | 3,233 | Fertilizer 850, fungicide 1,771, irrigation 611, dolomite 1 (with actual and forecast rain) |
| 06_resource_usage_monthly.csv | 1,200 | Allocated vs used per estate/resource |
| 07_operational_constraints.csv | 25 | Hard limits and scheduler rules |
| 08_daily_forecasts_issued.csv | 9,130 | Day 0–3 rain forecast issued each morning |

### 3.6 Model-ready data (`data/model_ready/`)
| File | Rows | Features | Target |
|---|---|---|---|
| yield_model_ready.csv | 9,053 plucking rounds | 57 live | green leaf kg/ha/day |
| runoff_model_ready.csv | 850 fertilizer applications | 24 live | % of fertilizer lost |
| smarttea_master_block_daily.csv.gz | 91,300 block-days | all sources joined | — |

- **Inputs:** all numeric, with full one-hot encoding, no missing values and leakage columns removed.
- **Live vs hindsight:** "live" features are known at decision time. Hindsight columns (actual rain after, same-day weather) are prefixed `hindsight__` and used only as an upper bound.
- **Fixed evaluation columns:**
  - `split`: train 2021–2023 / val 2024 / test 2025;
  - `cv_fold`: 5 unseen-block folds, 2 blocks per estate per fold;
  - `estate_id`: leave-one-estate-out.
- **`feature_spec.json`:** feature sets, decision variables, monotone constraints and training ranges (the optimizer bounds).
- **Loading:** `from src.data.load import load_task; X, y, meta = load_task("runoff", "live")`.

### 3.7 Data quality and reproducibility
- `python -m src.data.check_data --workbook`: **35 / 35 checks passed**, with 1 documented warning (historical practice sometimes breaks the rules, which is realistic).
- **Hybrid regeneration** (seed 42) reproduces all 10 files exactly.
- **`build_real`** reproduces files 00–06. Files 07/08 differ slightly because Forbes & Walker revised some figures; documented.
- **Data dictionary:** `md_files/data/DATA_DICTIONARY.md` and `data/data_dictionary.csv`, generated from the files. Every column has a unit, a description and an origin.

### 3.8 How the simulated part works (short)
**Soil water.** A daily bucket model with a 400 mm root zone, slope-dependent infiltration and FAO ET₀.

**Growth per day.** Temperature, water, light, N, P, K and pH factors, plus pruning cycle, cultivar, bush age and blister-blight loss.

**Nitrogen.** A Mitscherlich curve, `0.5 + 0.5·(1 − e^(−soilN/30))`. Fertilizer raises soil N by `N × (1 − loss) / 2 × 0.7` ppm.

**Fertilizer loss.**
- Base: `0.04 + 0.62·(1 − e^(−rain_eff/40))·(0.7 + slope/40)`.
- Extra loss on saturated soil, on dry soil (worse for urea) and in midday heat.

**Historical management.** A fixed fertilizer calendar, irrigation by soil-moisture trigger, a dolomite pH rule and a fungicide blight rule.

Full description: the header of `src/data/generate_hybrid.py`.

---

## 4. Tier 1: prediction models

### 4.1 Evaluation protocol (identical for every model)
1. **Live features only:** what is known when the decision is made (forecast rain, previous-day weather, last week's sensor readings).
2. **Time split:** train 2021–2023 → choose settings on validation 2024 → refit on 2021–2024 → **score 2025 once**.
3. **Hardest test:** unseen blocks **and** a future year. Train on the other blocks' 2021–23 rows, predict the held-out blocks' 2025 rows (5 folds).
4. **No random splits:** they leak information between days of the same block.
5. **No tuning toward a target accuracy.**

### 4.2 Seven models compared (`python -m src.models.compare_models`)
| Model | Yield val / test / unseen+future (R²) | Runoff val / test / unseen+future (R²) |
|---|---|---|
| **CatBoost** | **0.83 / 0.91 / 0.80 ± 0.03** ← chosen | 0.67 / 0.57 / 0.46 |
| LightGBM | 0.81 / 0.91 / 0.80 | 0.69 / 0.54 / 0.43 |
| **XGBoost** | 0.81 / 0.90 / 0.78 | **0.69 / 0.57 / 0.44 ± 0.19** ← chosen (monotone) |
| HistGradientBoosting | 0.81 / 0.90 / 0.79 | 0.69 / 0.55 / 0.45 |
| Random Forest | 0.67 / 0.85 / 0.65 | 0.68 / 0.55 / 0.45 |
| MLP | 0.62 / 0.77 / 0.36 | 0.59 / 0.04 / −0.71 |
| Ridge | 0.45 / 0.63 / 0.28 | 0.57 / 0.43 / 0.20 |

- **The four boosting models are within ~0.02–0.03 of each other,** so the winner is picked by validation R² only.
- **TabPFN was not run:** it needs a licence key.

### 4.3 Final models
| Model | Metric | Train | Val 2024 | **Test 2025** | **Unseen blocks + future year** |
|---|---|---|---|---|---|
| **Yield**, CatBoost (depth 4, l2 3, 1,947 iterations) | R² | 0.96 | 0.83 | **0.91** (MAE 1.63, RMSE 2.15 kg/ha/day) | **0.80 ± 0.03** |
| **Runoff risk, high/low**, XGBoost | Accuracy | — | — | **0.81** (guessing 0.54) | **0.79 ± 0.08** |
| Runoff risk | F1 | — | — | **0.82** (precision 0.80, recall 0.85) | **0.81 ± 0.06** |
| Runoff amount, XGBoost (depth 4, 171 iterations, monotone rain) | R² | 0.83 | 0.69 | 0.57 (MAE 9.9, RMSE 13.4 pp) | 0.44 ± 0.19 |
| Runoff amount with **actual** rain (upper bound only) | R² | — | — | 0.94 (MAE 3.8) | 0.90 |

**Notes on these numbers**
- **Runoff risk cut-off:** "high" means loss above **23.9 %**, the median of 2021–2023. It was fixed before scoring.
- **2025 confusion matrix:** 137 of 170 correct (60 + 77).
- **Yield in plain terms:** the average 2025 yield is 23 kg/ha/day, so an MAE of 1.63 is about **7 % error**. 74 % of predictions are within 10 % and 93 % within 20 %.
- **Runoff accuracy depends on the forecast:** with forecast rain, R² is 0.57; with actual rain, 0.94. **The forecast error, not the model, limits runoff prediction.** This is a key thesis finding.
- **Up-country runoff is harder:** test MAE is about 14 pp at Nuwara Eliya and Hatton, against about 8 pp elsewhere.
- **Saved models:**
  - `artifacts/models/yield_catboost.joblib` + `.json`
  - `artifacts/models/runoff_xgboost.joblib` + `.json`
  - The `.json` files hold the features, settings and scores.

### 4.4 Baselines (test 2025, R²)
| | Yield | Runoff |
|---|---|---|
| Always predict the average | −0.02 | 0.00 |
| Ridge (linear) | 0.63 | 0.43 |
| Final model | **0.91** | **0.57** |

### 4.5 Overfitting checks
- **Yield: no real overfitting.**
  - The train–val gap is 0.13, and the test score (0.91) does not collapse.
  - Learning curve: training R² falls (0.99 → 0.96) while validation rises (0.79 → 0.83). This is the healthy pattern.
- **Runoff: a moderate gap,** from few rows (680 training rows) and forecast error.
  - Learning curve: validation is still rising (0.64 → 0.69), so more data would help.
  - Without regularisation it was badly overfitted: train 0.998 vs test 0.59. Regularisation and early stopping fixed this.
- **Monotone check:** adding 10 mm of forecast rain never lowered predicted runoff (0 of 170 rows).
- **Reproducibility:** retraining from scratch gives identical models and scores.

### 4.6 Humidity leak (found by SHAP, fixed 2026-10-08)
- **The problem:** the runoff model's top driver was `humidity_at_exec_pct`, the daily mean humidity of the application day.
  - That value partly contains the same day's rain, which is not known at decision time: corr 0.40 with actual rain vs 0.23 with forecast rain.
- **The fix:** use **previous-day** humidity and temperature (`humidity_prev_day_pct`, `temp_prev_day_c`). The same-day values were moved to `hindsight__`.
- **Effect:**
  - Runoff before: val 0.73 / test 0.63–0.65 / unseen+future 0.51–0.54.
  - After: 0.69 / 0.57 / 0.44.
  - This drop is the honest cost of using only decision-time information.

### 4.7 What drives the predictions (SHAP, `python -m src.models.explain_shap`)
- **Yield:**
  - Main drivers: soil N in the week before the round (11 %), cultivar (11 %), elevation zone, plucking standard, days since pruning, weather-grid elevation, bush age, soil moisture.
  - **Agronomy direction check:** N applied, soil N and soil moisture all raise yield, as expected.
  - **Fungicide appears to lower yield** (Spearman −0.67). This is **confounding**: sprays happen in wet, cloudy blight weather. The optimizer must **never** choose fungicide through the yield model; fungicide is decided by a blight-risk rule.
- **Runoff (after the fix):**
  - Drivers: soil moisture at application 21 %, rain in the previous 3 days 13 %, forecast rain 24 h 12 %, slope 11 %, forecast rain 48 h 10 %, previous-day humidity 5 %.
  - All physically expected. The direction check agrees on 7 of 8 features; the exception is fungicide, explained above.

### 4.8 Earlier results and lessons
- **The first unseen-block yield score was 0.66.** The cause was drop-first one-hot encoding, which cost about 0.15 R² (checked with 3 seeds). Full one-hot is now used.
- **Unseen estates (leave-one-estate-out):** yield R² is only 0.12 (Kandy −1.2). **New locations are not predictable.** This is reported as a limitation.
- **Forecast skill, real 2024–25 daily rain:**
  - 1-day lead: MAE 6.0 mm, 72 % agreement on ">5 mm" days.
  - About 68 % by day 3–4.
  - Forecasts under-predict by about 4 mm/day.

### 4.9 Training notebook
`notebooks/01_model_training.ipynb` (kernel "SmartTea (.venv)", **Run All** takes about 2 minutes) contains:
- data, splits and target distributions;
- baselines;
- yield model training;
- runoff model training, with the monotone check, the forecast-vs-actual-rain comparison and the **risk accuracy with confusion matrix**;
- overfitting chart and learning curves;
- the 7-model comparison;
- SHAP;
- saving and reload check;
- summary.

It is saved with all outputs and 8 charts.

---

## 5. Tier 2: NSGA-II optimizer

### 5.1 What it decides
At the start of each plucking round, for each block:
- **N to apply now** (kg N/ha; 0 = none);
- **the product** (NPK_BAL 21 % N, NPK_HN 27 %, UREA 46 %);
- **irrigation** (mm, only where allowed).

### 5.2 Hard limits (`src/optimizer/limits.py`)
The limits are `07_operational_constraints.csv` **intersected with** the models' training ranges, because tree models cannot extrapolate:
- 100–400 kg/ha mixture per application;
- at least 45 days between applications;
- no fertilizer within 30 days after pruning;
- annual N ceiling: 330 kg N/ha up-country, 300 mid and low;
- 60/90-day N inside the training range;
- irrigation only on irrigated blocks and below the soil-moisture trigger (WP + 0.35·(FC − WP)), at most 25 mm per event, within the estate's monthly water budget.

### 5.3 How a plan is scored (all models work together)
1. **Runoff model:** % of N lost under the decision-time forecast for each allowed product. The product with the lowest loss is used. N_eff = N × (1 − loss).
2. **Soil-N response model** (`src/optimizer/soil_n.py`, fitted on 2021–2023 only):
   - Each kg of N_eff raises the soil-N reading by **0.27 ppm**, fading with **τ = 45 days**.
   - The true value in the data generator is 0.35, so the learned value is close.
   - It improved 2024 soil-N prediction from R² 0.46 to 0.54.
3. **Yield model:** predicts every plucking round in a **90-day horizon** with the raised soil N.

**Pick rule (no cost variables).** Maximise **yield gain over 90 days − min_ae × N**, where `min_ae` is the kg of green leaf each kg of N must at least add.
- Default **3.5**, the setting that keeps N close to current practice.
- If no plan beats "no action", the answer is "No action".

**Solver check.** NSGA-II (population 40, 40 generations) reaches **100 %** of the exhaustive-grid optimum, with the same dose in 95–100 % of plans. Smaller settings lose quality.

### 5.4 Result: full-year test on 2025, all 50 blocks
The test is closed-loop: each recommendation feeds into the next round, and soil N is made counterfactual.

| Per ha per year | Historical practice | Optimizer (min_ae 3.5) |
|---|---|---|
| N applied | 198 kg | 182 kg (**−8 %**) |
| N lost to runoff | 59 kg | 36 kg (**−40 %**) |
| Applications | 3.3 | 3.0 |
| Predicted green leaf | 7,519 kg | 7,776 kg (**+3.4 %**) |
| Rule breaks | 0 | **0** |

- **Where the N goes:** to low-soil-N blocks (12 ppm when it applies vs 22 ppm when it declines).
- **When:** on dry forecast days (2.6 mm in the next 24 h on average).
- **By estate:** Nuwara Eliya, with the highest soil N, gets −61 % N; Kandy gets +54 %.
- **Product choice:** urea 76, NPK_BAL 39, NPK_HN 36 applications.

### 5.5 Threshold trade-off (sensitivity sweep)
| min_ae (kg leaf per kg N) | N vs historical | Predicted yield vs historical |
|---|---|---|
| 1 | +77 % | +6.6 % |
| 2 | +51 % | +6.3 % |
| 3 | +19 % | +5.2 % |
| **3.5 (default)** | **−7 %** | **+3.4 %** |
| 4 | −26 % | +2.4 % |
| 4.5 | −49 % | +0.3 % |
| 5 | −67 % | −1.4 % |
| 8 (no N at all) | −100 % | −5.1 % |

### 5.6 Lesson from the first version
The first version judged each round alone. It used **+65 % N for only +2.5 % yield**, because almost any dose looks good for one round. Adding the soil-N response and the 90-day horizon fixed this.

### 5.7 Outputs
All in `artifacts/reports/optimizer/`:
- `recommendations_2025.csv`
- `block_totals_2025.csv`
- `summary_2025.csv`
- `min_ae_sweep_2025.csv` / `.png`
- `pareto_example.png`
- `solver_check.csv`

---

## 6. Limits and caveats
**About the data**
- **The data is a hybrid.** The models learn simulated management and crop response on top of real weather and soil. Validation on real estate records is still needed.
- **Agronomic parameters are placeholders** (fertilizer rates, loss coefficients, blight model, dolomite/fungicide amounts, pre-harvest interval). Check them against TRI guidance.
- **Kandy (mid-country) seasonality does not match national medium-grown production:** correlation ≈ 0, against 0.73 for high-grown and 0.68 for low-grown.
- **2022** national production was hit by the chemical-fertilizer ban and the economic crisis.
- **SoilGrids:** N is total N (available N approximated as 1.2 %). 10 blocks fall on masked pixels and use the estate mean.
- **The PDF example "15.5 kg, max 20 kg"** is unrealistic per hectare; real practice is about 150–350 kg/ha per application.

**About the models**
- **R² is not "accuracy".** R² 0.91 means "explains 91 % of the variation".
- **Runoff amount is limited by forecast error:** 0.57 with the forecast vs 0.94 with actual rain.
- **New estates (locations) are not predictable** (R² 0.12).

**About the optimizer**
- **Its yields are model predictions.** Only soil N is made counterfactual.
- **A one-year test understates the harm of large N cuts,** because soil N runs down over years. Do not pick a high `min_ae` without a multi-year check.
- **`min_ae` is a decision-maker preference.** Check it against TRI guidance.
- **Irrigation is not valued by the per-round yield model** (~0.3 kg leaf per mm), and the trigger allowed it at only 11 round starts, so the "water saved" figure is not real. Irrigation will be handled by the daily Tier 3 scheduler.
- **The optimizer can exploit model errors** (the "optimizer's curse"), so the +3.4 % is probably a little optimistic.
- **The 3.5 threshold was chosen after seeing 2025 results.** Choosing it on 2024 and re-testing on 2025 is a recommended follow-up.

---

## 7. Roadmap and status
| Step | Content | Status |
|---|---|---|
| 1 | Repo hygiene: git, venv, folders, data pipeline, data dictionary, manifest | ✔ 2026-10-08 |
| 2 | Tier 1 models: comparison, regularisation, monotone runoff, SHAP, learning curves, notebook | ✔ 2026-10-09 (Optuna optional, not done) |
| 3 | Tier 2 optimizer: NSGA-II, soil-N response, 2025 closed loop, sweep, tests | ✔ 2026-10-09 |
| 4 | Tier 3 Action-Window scheduler: hourly forecast, rain-free ≥ 12 h, soil-moisture band, wind, 06–16 h, daily irrigation | **next** |
| 5 | Backend: FastAPI ML service (`POST /ml/recommend`) + Spring Boot (`POST /api/readings`, `GET /api/blocks/{id}/recommendation`, `GET /api/forecast/{estate}`, hourly job) + MongoDB | to do (install JDK 25, Maven, MongoDB first) |
| 6 | Dashboard: React + Tailwind (readings, recommendation + reason, forecast, history) | to do |
| 7 | Thesis evaluation: scheduler vs fixed calendar, forecast-error impact, sensitivity analysis | to do |

**Other open items**
- Get real estate records from TRI or a plantation company.
- Fungicide by a blight-risk rule; dolomite by the pH rule.
- Choose `min_ae` on 2024.
- A multi-year N check.
- Optional: Optuna tuning, ensemble, weather-correction model.
- Write the research report from the numbers in this file (the earlier PDF report was removed: its numbers were out of date).

---

## 8. How to run everything
From the project root, with the venv active (`.venv\Scripts\activate`):

```bash
# data pipeline (always writes to new folders; frozen data is never overwritten)
python -m src.data.build_real                       # raw -> data/interim/real_rebuilt (verifies checksums)
python src/data/generate_hybrid.py --out data/processed/hybrid_regen --real-data data/interim/real
python -m src.data.compare_tables data/processed/hybrid data/processed/hybrid_regen
python -m src.data.build_model_ready                # -> data/model_ready
python -m src.data.make_data_dictionary
python -m src.data.build_workbook                   # one Excel file -> data/release/
python -m src.data.check_data --workbook            # must end "35/35 checks passed"

# Tier 1 models
python -m src.models.compare_models                 # 7 models, saves the best per task (~10 min)
python -m src.models.overfit_check
python -m src.models.explain_shap                   # SHAP charts -> artifacts/reports/shap/
# or open notebooks/01_model_training.ipynb and Run All (~2 min)

# Tier 2 optimizer
python -m src.optimizer.soil_n                      # fit the soil-N response
python -m src.optimizer.optimize --block E03-B07 --date 2025-06-01
python -m src.optimizer.evaluate                    # 2025 closed loop (~13 min)
python -m src.optimizer.evaluate --sweep 2,3,3.5,4  # threshold trade-off
python -m src.optimizer.evaluate --check-solver     # NSGA-II vs exhaustive grid

# tests
python -m pytest tests -q                           # 9 optimizer rule tests
```
**Environment:**
- Windows, Python 3.14 venv.
- Packages are in `requirements.txt`: numpy, pandas, scikit-learn, xgboost, lightgbm, catboost, pymoo, optuna, shap, matplotlib, fastapi, uvicorn, Jupyter kernel packages, pytest.
- **Git:** push with GitHub Desktop.

---

## 9. File map
```
CLAUDE.md                          instructions for the code assistant
README.md                          project overview + quick start
md_files/                          all Markdown docs (this file: md_files/docs/SmartTea_LK_C04_Full_Project.md)
data/                              raw → interim → processed → model_ready (+ release, archive), README, dictionary
src/data/                          build_real, generate_hybrid, validate_hybrid, build_model_ready,
                                   make_data_dictionary, build_workbook, check_data, compare_tables, load
src/models/                        compare_models, overfit_check, explain_shap
src/optimizer/                     limits, context, soil_n, optimize, evaluate
src/scheduler/, src/api/           (steps 4–5)
notebooks/01_model_training.ipynb  training notebook with outputs
tests/test_optimizer.py            optimizer rule tests
artifacts/                         saved models + reports (git-ignored; rebuild with the commands above)
```

---

## 10. Presenting to the panel
**Headline results (all honest and reproducible):**
- *"Trained on 2021–2024 and tested on the unseen year 2025, the yield model explains **91 %** of yield variation (R² 0.91), and **80 %** on blocks and a year it has never seen."*
- *"The runoff-risk model classifies high/low fertilizer-loss risk with **81 % accuracy (F1 0.82)** using only the weather forecast."*
- *"With the actual rain the same runoff model reaches 0.94. Forecast error is the main limit, which is why the Action Window matters."*
- *"In a full-year test the optimizer used 8 % less N, lost 40 % less N to runoff, and is predicted to give 3.4 % more green leaf, without breaking any rule."*

**Say clearly:**
- what is real and what is simulated (§3.4);
- that R² is not "accuracy";
- that the optimizer's yield gain is a model prediction.

**Proof of data:**
- `data/raw/MANIFEST.csv` (checksums);
- the live Open-Meteo demo link (§3.3);
- `python -m src.data.check_data`.

**Integrity note.** The results were not tuned toward a target accuracy, and the dataset was not changed to raise scores. Settings were chosen on 2024 only, and 2025 was scored once.

---

## 11. Development log (chat sessions)
Earlier planning (7–8 Oct 2026, Cowork) is not recorded here (the planning notes were removed). Below are the Claude Code sessions in VS Code.

### 8 Oct 2026: setup, data, reports
| # | Request | Outcome |
|---|---|---|
| 1 | Read CLAUDE.md; set up git, venv and the roadmap folders | Git repo, Python venv, folder layout (src/, backend/, frontend/, notebooks/, tests/, artifacts/) |
| 2 | Are all datasets OK? | Datasets checked; issues documented |
| 3 | Use React + Tailwind / Java Spring Boot / MongoDB | Tech stack adopted; ML stays a Python FastAPI internal service; CLAUDE.md updated |
| 4 | Create a full PDF document for the research | a PDF report (outdated; since removed) |
| 5 | Which ML models give the best accuracy? | Advice: gradient boosting (XGBoost/LightGBM/CatBoost) with Ridge/RF/MLP baselines; honest splits |
| 6 | Organise datasets professionally; one model-feed-ready dataset | raw → interim → processed → model_ready layout; manifest with checksums; build scripts; data dictionary; `model_ready/` tables + `feature_spec.json` + `load_task` |
| 7 | Which dataset to show the panel? | Recommended the model-ready tables + workbook + provenance |
| 8 | Full data in one dataset file | `data/release/SmartTea_LK_C04_Dataset.xlsx` (20 sheets, ~34 MB) |
| 9 | Final check that all datasets are OK | `check_data`: 35/35; reproducibility proven (hybrid identical; model_ready identical) |
| 10 | Push to GitHub with GitHub Desktop | Step-by-step GitHub Desktop instructions + commit message (the user pushes) |

### 8–9 Oct 2026: models
| # | Request | Outcome |
|---|---|---|
| 11 | Accuracy should look realistic, about 75–85 %, not overfitted | Regularised XGBoost; settings chosen on 2024 only; added the "unseen blocks + future year" test (yield 0.78, runoff 0.51 at that time). Agreed rule: never tune toward a target |
| 12 | Full model comparison | 7 models; CatBoost (yield) and LightGBM (runoff) chosen by val R² |
| 13 | SHAP explanations | Drivers, agronomy direction check; found fungicide confounding and the **humidity leak** |
| 14 | Fix the humidity leak | Previous-day humidity/temperature; runoff re-run (now XGBoost, test 0.57, unseen 0.44); SHAP, workbook, checks, docs updated |
| 15 | Is training finished? How much data? How many datasets? | Explained: 2 models, 9,053 + 850 rows, 2 model-ready files from 8 tables from 5 real sources |
| 16 | Create the model training ipynb | `notebooks/01_model_training.ipynb` with learning curves, executed with outputs; Jupyter kernel installed |
| 17 | What is the accuracy? | Yield R² 0.91 / 0.80; runoff R² 0.57 / 0.44 with 0.94 upper bound; explained in plain terms |

### 9 Oct 2026: optimizer
| # | Request | Outcome |
|---|---|---|
| 18 | Do next (Tier 2 optimizer) | First version: 0 rule breaks, but +65 % N for +2.5 % yield. Rejected and redesigned with the soil-N response model, 90-day horizon, efficiency pick rule and product choice by runoff. Final: N −8 %, runoff loss −40 %, yield +3.4 %, NSGA-II matches exhaustive search; 9 tests |
| 19 | Is the model overfitted? | Yield no; runoff moderate (few rows + forecast error); flagged that the optimizer threshold was chosen on 2025 and that optimizers exploit model errors |
| 20 | How to reduce overfitting? | Listed done measures and options: more data, ensemble, feature selection, monotone rules, Optuna with grouped CV, choose threshold on 2024, uncertainty penalty |
| 21 | Change the synthetic data to get 80–84 % | **Declined:** changing data to hit a target score would misrepresent the work. Instead computed the honest **runoff risk accuracy 81 %** (decision-relevant metric with a pre-fixed cut-off) |
| 22 | Change the training file and retrain | Notebook updated with the runoff-risk section and confusion matrix; models retrained (identical scores, reproducible) |
| 23 | Show results; recreate the notebook and retrain from scratch | Rebuilt from scratch; same results (fixed seeds) |
| 24 | What is Test 2025 R²? Reduce it to 0.80? | Explained R². Advised not to make the model worse; the honest 0.80 is the "unseen blocks + future year" score |
| 25 | Real "R1" score | Gave R² (0.91 / 0.57) and **F1 for runoff risk: 0.82 test, 0.81 unseen** |

### 15 Oct 2026: data proof
| # | Request | Outcome |
|---|---|---|
| 26 | Find where the datasets came from, to prove it to the panel | Locations, sources, licences, manifest checksums verified (51/51); live Open-Meteo re-download matched exactly |
| 27 | Direct links to the data platforms | Direct API links built and tested (Open-Meteo ×2, NASA POWER, Forbes & Walker OK; SoilGrids server down that day) |
| 28 | One full project MD file with everything | This document |

### Key decisions made along the way
1. **Honest evaluation first:** live features only, time + block-grouped splits, settings on 2024, test 2025 once.
2. **Full one-hot encoding** (drop-first cost ~0.15 R²).
3. **Same-day weather is hindsight**; previous-day weather is live.
4. **Fungicide is never optimized through the yield model**, because of confounding.
5. **The optimizer uses the soil-N pathway and a 90-day horizon**; it never judges a round alone.
6. **Irrigation moves to the daily Tier 3 scheduler.**
7. **No tuning toward a target score, and no changing the data to raise scores.**
8. **The user commits and pushes with GitHub Desktop.**

---

## 12. Glossary
| Term | Meaning |
|---|---|
| **R²** | Share of the variation in the real values that the model explains (1 = perfect, 0 = no better than the average) |
| **MAE** | Mean absolute error: the average size of a prediction error, in the target's units |
| **Accuracy** | Share of yes/no predictions that are correct |
| **Precision / Recall / F1** | Of the "high risk" warnings, how many were right / of the real high-risk cases, how many were caught / the balance of both |
| **Live features** | Information available when the decision is made |
| **Hindsight features** | Information known only afterwards (actual rain after an application); used only as an upper bound |
| **Unseen blocks + future year** | The hardest test: blocks and a year the model never saw in training |
| **Leakage** | When a model sees information it would not have in real use, which makes scores look too good |
| **Overfitting** | When a model memorises training data and does much worse on new data |
| **Monotone constraint** | A rule forcing the model's output to move in one direction (more rain → never less runoff) |
| **SHAP** | A method that shows how much each input pushed a prediction up or down |
| **NSGA-II** | A genetic algorithm that finds the best trade-offs between several objectives |
| **Pareto front** | The set of plans where no objective can improve without another getting worse |
| **min_ae** | Minimum agronomic efficiency: the kg of green leaf each kg of N must add before the optimizer uses it |
| **N_eff** | Effective nitrogen: N applied × (1 − runoff loss) |
| **FC / WP** | Field capacity / wilting point: the soil-water limits used for the moisture rules |
| **ERA5** | The European reanalysis of past weather, served by Open-Meteo |
