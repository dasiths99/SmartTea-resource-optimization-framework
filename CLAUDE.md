# CLAUDE.md: SmartTea-LK Component 04 (Resource Optimization Framework)

This file gives Claude Code the full context of this project. The history behind each decision is in `docs/PROJECT_CONTEXT.md`.

## 1. What this project is
- **Project:** SmartTea-LK research initiative (Sri Lankan tea sector), **Component 04: AI-Based Tea Plantation Resource Optimization and Intervention Planning**. Owner: Dasith Sathpura (university research project, CSP 001).
- **Goal:** Take the *live* condition of tea blocks and decide **what to do next, how much, and when**:
  - fertilizer
  - irrigation
  - fungicide
  - pH correction (dolomite)

  The aim is the highest growth with the minimum physical resources, timed so the weather does not wash the inputs away.
- **Scope rule:** purely agronomic. **No cost, labour, machinery or budget variables** were removed from the original framework on purpose. Do not add them back.
- The original framework document is "SmartTea-LK Component 04: Resource Optimization Framework (Updated)" (PDF, not in this folder).

## 2. System architecture (three-tier AI pipeline)
```
Inputs ──► Tier 1: Prediction ──► Tier 2: NSGA-II optimizer ──► Tier 3: Action-Window scheduler ──► Recommendation
```
- **Tier 1: Prediction**
  - **Weather:** live forecast from the Open-Meteo API. Optionally add a local correction model (XGBoost/LSTM) that learns the API's errors.
  - **Yield surrogate:** XGBoost, predicting the growth or yield change for a candidate action under the forecast conditions.
  - **Runoff/efficiency model:** XGBoost, predicting the % of fertilizer lost given the forecast rain, slope and soil moisture.
- **Tier 2: NSGA-II** (`pymoo`), multi-objective:
  - **Objectives:** maximize predicted yield; minimize total water + fertilizer.
  - **Hard constraints:** `07_operational_constraints.csv`.
  - **Search bounds:** keep them **inside the training-data range**, because tree models cannot extrapolate.
  - **Picking one plan:** a rule is needed to choose one solution from the Pareto front.
- **Tier 3: Action Window**
  - Scans the 72–96 h forecast for the best execution time, e.g. no rain for ≥12 h after fertilizer, soil moisture inside the allowed band, wind ≤4 m/s for spraying.
  - Must work with **forecasts**, not perfect knowledge.

### Inputs
- **IoT inputs, entered manually for now:** soil condition (pH, N, P, K), soil moisture, soil temperature, light level (lux / sunshine), and the last fertilizer used (type, amount, date). There is **no IoT hardware yet**; the values are entered on the backend.
- **Design rule:** the manual-entry endpoint must accept **exactly the JSON the future IoT device will send** (e.g. `POST /api/readings`). Adding real sensors later should then only change where the data comes from.
- **Live weather:** Open-Meteo forecast API. It is free, needs no key, and returns hourly rain, rain probability, temperature, humidity, wind and radiation for a lat/lon.

### Output: a recommendation
```json
{"block_id":"E03-B07","action":"Apply fertilizer","amount_kg_per_ha":240,
 "window":"2026-10-08 06:00–10:00","reason":"Soil moisture in band; no rain next 14 h",
 "predicted_yield_change_pct":9.2,"efficiency_score":0.93}
```
- **Action types:** apply / delay fertilizer, irrigate / skip, dolomite (pH), fungicide, no action.
- **Live update:** re-run when a new reading arrives, and every hour on a scheduler as the forecast changes.

### Tech stack (fixed by the SmartTea-LK project)
| Layer | Technology |
|---|---|
| Frontend | React.js with Tailwind CSS |
| Backend | Java + Spring Boot |
| Database | MongoDB |
| ML service | Python + FastAPI (internal; XGBoost, scikit-learn, pymoo NSGA-II, Optuna, SHAP) |

The ML stays in Python because Java has no practical equivalent of XGBoost training, pymoo or SHAP. How the parts connect:
```
React (Tailwind) ──► Spring Boot ──► MongoDB   (readings, forecasts, recommendations, history)
                        │  ▲
                        ▼  │ HTTP/JSON
                  Python ML service (FastAPI): Tier 1 models + Tier 2 NSGA-II + Tier 3 Action Window
```
- **Spring Boot** is the public API. It owns MongoDB, receives IoT/manual readings, fetches the Open-Meteo forecast, and runs the hourly re-recommendation job with `@Scheduled`.
- **Python ML service** is stateless. Spring Boot sends it the block, its latest reading and the forecast; it returns the recommendation JSON. It never touches MongoDB.
- **React** talks only to Spring Boot, never to the ML service.

## 3. Folder layout
```
SmartTea resource optimization framework/
├── CLAUDE.md                         ← this file
├── docs/PROJECT_CONTEXT.md           ← full history, rationale, findings
├── data/                             ← ALL data; read data/README.md first
│   ├── raw/                          ← original downloads + MANIFEST.csv (source, URL, licence, sha256). Never edit
│   ├── interim/real/                 ← real data pack 00–08 (frozen reference)
│   ├── processed/hybrid/             ← hybrid tables 01–08 + ml_*_training.csv + validation reports
│   ├── model_ready/                  ← ★ USE THIS for model training (feed-ready tables, splits, feature_spec.json)
│   ├── archive/synthetic_v1/         ← old fully-synthetic v1 (comparison only)
│   ├── release/                      ← SmartTea_LK_C04_Dataset.xlsx: whole dataset in one file (git-ignored, rebuild)
│   ├── README.md, DATA_DICTIONARY.md, data_dictionary.csv
├── src/data/                         ← pipeline: build_real, generate_hybrid, validate_hybrid,
│                                       build_model_ready, make_data_dictionary, compare_tables, load
├── src/                              ← Python ML service
│   ├── models/                       ← Tier 1: yield + runoff surrogates (roadmap step 2)
│   ├── optimizer/                    ← Tier 2: NSGA-II (step 3)
│   ├── scheduler/                    ← Tier 3: Action Window (step 4)
│   └── api/                          ← FastAPI ML service endpoints, internal (step 5)
├── backend/                          ← Java Spring Boot + MongoDB (step 5)
├── frontend/                         ← React + Tailwind dashboard (step 6)
├── notebooks/                        ← exploration / training notebooks
├── tests/                            ← Python tests
├── artifacts/                        ← saved models, run outputs (git-ignored)
├── requirements.txt, .gitignore, .venv/ (git-ignored)
└── docs/                             ← PROJECT_CONTEXT.md, research report PDF
```
Data was reorganised into the raw → interim → processed → model_ready layout on 2026-10-08. Every stage rebuilds from the one before it (see data/README.md).

## 4. Datasets (hybrid = real environment + simulated management)
Region: 5 estate locations × 10 blocks = **50 blocks**, daily, **2021-01-01 → 2025-12-31**.

| Estate | Location | Zone |
|---|---|---|
| E01 | Nuwara Eliya | up |
| E02 | Hatton / Dimbula | up |
| E03 | Kandy | mid |
| E04 | Ratnapura | low |
| E05 | Deniyaya / Matara | low |

The estate names are fictional; the locations are real.

**Link keys:** `block_id` (e.g. `E03-B07`), `estate_id` + `date`.

| File (data/processed/hybrid) | Rows | Notes |
|---|---|---|
| 01_block_master.csv | 50 | Static block features + real SoilGrids `sg_*` soil, field capacity/wilting point (Saxton-Rawls), `temp_offset_c` |
| 02_weather_daily.csv | 9,130 | **Real** ERA5 (Open-Meteo); sunshine derived from real radiation; `era5_soil_moisture_7_28cm_pct` |
| 03_sensor_readings_daily.csv | 91,300 | Same fields as the manual input form; noise + ~1.5% missing |
| 04_yield_plucking_records.csv | 9,053 | Green leaf kg/ha per plucking round |
| 05_intervention_records.csv | 3,233 | fertilizer 850, fungicide 1,771, irrigation 611, dolomite 1; **actual** rain after (`rain_next_*`) + **forecast** rain at the time (`fc_rain_next_*`, `forecast_source`) |
| 06_resource_usage_monthly.csv | 1,200 | Allocated vs used per estate/resource |
| 07_operational_constraints.csv | 25 | NSGA-II limits + scheduler rules (soil-moisture rules are **relative to each block's FC/WP**) |
| 08_daily_forecasts_issued.csv | 9,130 | Day 0–3 rain forecast issued each morning; real from 2024-01-20, earlier simulated from the real error distribution |
| **ml_yield_training.csv** | 9,053 | Target `green_leaf_kg_per_ha_per_day` (**drop `green_leaf_kg_per_ha`** = leakage; drop `aspect` = no effect) |
| **ml_runoff_training.csv** | 850 | Target `runoff_loss_est_pct` or `absorption_efficiency_pct`. For live use, train on `fc_rain_*` and **not** `rain_next_*` |

**Real data pack sources:**
- Open-Meteo Historical (ERA5/ERA5-Land, hourly, includes soil moisture at 3 depths)
- Open-Meteo Previous Runs (forecasts at 1–4 day lead, from 2024)
- NASA POWER (coarse cross-check; E01=E02 and E04=E05 fall in the same grid cell)
- ISRIC SoilGrids 250 m
- Forbes & Walker national monthly tea production by elevation (2021–2025)

**Model-ready data (`data/model_ready/`, use this for training):**
- `yield_model_ready.csv` (9,053 rows, 58 features) and `runoff_model_ready.csv` (850 rows, 24 live features). All features are numeric, with full one-hot encoding, no missing values and leakage columns removed. Hindsight rain columns are prefixed `hindsight__`.
- Fixed evaluation columns: `split` (train 2021–23, val 2024, test 2025), `cv_fold` (unseen blocks, 2 per estate per fold), and `estate_id` (leave-one-estate-out).
- `feature_spec.json` gives the feature sets (runoff: `live` / `hindsight`), decision variables, monotone constraints and training ranges. Use the training ranges as the NSGA-II bounds.
- `smarttea_master_block_daily.csv.gz`: every source joined, one row per block per day (91,300 rows).
- Load with `from src.data.load import load_task; X, y, meta = load_task("runoff", "live")`.

**Regenerate (from the project root; always write to a new folder):**
```bash
python -m src.data.build_real                    # raw -> data/interim/real_rebuilt (verifies checksums)
python src/data/generate_hybrid.py --out data/processed/hybrid_regen --real-data data/interim/real
python -m src.data.compare_tables data/processed/hybrid data/processed/hybrid_regen
python -m src.data.build_model_ready             # -> data/model_ready
python -m src.data.make_data_dictionary
python -m src.data.build_workbook               # whole dataset in one Excel file -> data/release/
python -m src.data.check_data --workbook        # audit every layer (must end "35/35 checks passed")
python src/data/validate_hybrid.py data/processed/hybrid data/interim/real
```
- **Options:** `--seed 42`, `--blocks-per-estate 10`, `--root-zone-mm 400`, `--wp-factor 1.0`, `--missing-rate 0.015`.
- **Runtime:** about 1 min.
- **Requirements:** `requirements.txt` (pypdfium2 is needed only by `build_real`).
- **Reproducibility (2026-10-08):** the hybrid regeneration reproduces all 10 files exactly. `build_real` reproduces files 00–06. Files 07/08 differ by Forbes & Walker revisions (see `data/interim/real/README.md`).

## 5. Key results so far

**Headline (realistic): decision-time ("live") features, regularised XGBoost, settings chosen on val 2024 only** (`python -m src.models.overfit_check`, artifacts/reports/overfit_check.csv):

| Task | Train | Val 2024 | Test 2025 | Unseen blocks + future year |
|---|---|---|---|---|
| Yield (live) | 0.96 | 0.81 | **0.90** | **0.78 ± 0.08** |
| Runoff (live, forecast rain, monotone) | 0.83 | 0.72 | **0.65** | **0.51 ± 0.18** |

**Model comparison (live features, same protocol for all 7 models; `python -m src.models.compare_models`, artifacts/reports/model_comparison.csv):**

| Model | Yield val / test / unseen+future | Runoff val / test / unseen+future |
|---|---|---|
| CatBoost | **0.83 / 0.91 / 0.80 ± 0.03** ← saved | 0.71 / 0.65 / 0.54 |
| LightGBM | 0.81 / 0.91 / 0.80 | **0.73 / 0.63 / 0.54 ± 0.16** ← saved (monotone) |
| XGBoost | 0.81 / 0.90 / 0.78 | 0.72 / 0.65 / 0.51 |
| HistGradientBoosting | 0.81 / 0.90 / 0.79 | 0.71 / 0.64 / 0.52 |
| Random Forest | 0.67 / 0.85 / 0.65 | 0.71 / 0.62 / 0.52 |
| MLP | 0.62 / 0.77 / 0.36 | 0.65 / 0.23 / −0.44 |
| Ridge | 0.45 / 0.63 / 0.28 | 0.58 / 0.52 / 0.30 |

- The four boosting models are within ~0.02 of each other, which is noise; the winner is picked by val R² only.
- Saved models: `artifacts/models/yield_catboost.joblib` and `artifacts/models/runoff_lightgbm.joblib`, each with a `.json` file listing features, settings and scores. TabPFN was not run: it needs a free licence key from ux.priorlabs.ai.
- Do not tune toward a target accuracy. Choose settings on val only, and score test once.
- Unregularised runoff overfitted badly: train 0.998 vs test 0.59.

**Earlier baseline (hindsight features, default settings; data/processed/hybrid/validation_report_2026-10-08.txt):**
| Test | Result |
|---|---|
| Yield, XGBoost, test year 2025 | R² 0.94 (RF 0.90, Ridge 0.64) |
| Yield, XGBoost, **unseen blocks** (block-grouped CV) | **R² 0.82**. First reported as 0.66; that run used drop-first one-hot encoding, which cost ~0.15 R² |
| Yield, XGBoost, **unseen estate** (leave-one-estate-out) | **R² 0.12** (Kandy −1.2). New locations are not predictable. Report this |
| Runoff, actual rain after (hindsight) | R² 0.94 |
| Runoff, **forecast rain only** (how it runs live) | **R² 0.63** ← key thesis finding: forecast error limits the Action Window |
| Simulated soil moisture vs ERA5-Land | r 0.85–0.91 |
| Seasonal shape vs national production | high 0.73, low 0.68, **medium ≈ 0** (known gap) |

**Real forecast skill, 2024–25 daily rain:**
- 1-day lead: MAE 6.0 mm, 72% agreement on ">5 mm" days.
- Accuracy falls to about 68% by day 3–4.
- Forecasts **under-predict** rain (bias ≈ −4 mm/day).

## 6. Important caveats (state them in the thesis, don't hide them)
- **The data is a hybrid.** Weather, rain timing, forecasts and soil are real. Management decisions, crop response, runoff amounts and sensor noise are **simulated**. Models learn the coded rules on top of a real environment. Validation on real estate records (TRI or a plantation company) is still the main open step.
- **Agronomic parameters are approximate placeholders.** This covers fertilizer rates (~240 kg/ha mixture per application, max 400), loss coefficients, blight model, dolomite/fungicide amounts and the pre-harvest interval. They should be checked against TRI guidance.
- **Fix the PDF example.** The original framework PDF shows "15.5 kg, max 20 kg", which is unrealistic per hectare.
- **Kandy does not match national medium-grown seasonality.** Simulated mid-country blocks dip in Feb–Mar; national output peaks Mar–May. Tuning root depth (600–1000 mm) and wilting point (×0.65–0.85) did not fix it.
- **2022 national production was hit by the chemical-fertilizer ban and the economic crisis.** Treat 2022 carefully.
- **SoilGrids limits:**
  - Nitrogen is **total N** (g/kg), not available N. Available N is approximated as 1.2%.
  - pH is pH in water.
  - 10 blocks fall on masked pixels and use the estate mean (flagged).
- **Use time-based or block-grouped splits, never random ones,** because random splits leak information. Use the fixed `split` / `cv_fold` columns in `data/model_ready/`.
- **Use full one-hot encoding** (as stored in `data/model_ready/`); drop-first encoding cost ~0.15 R² on unseen blocks.

## 7. Development roadmap (next steps)
1. ~~**Repo hygiene**~~ ✔ done 2026-10-08: git, venv, folder layout, data pipeline (raw → model_ready), data dictionary, manifest.
2. **Model training notebook/scripts** (`src/models/`):
   - XGBoost yield and runoff models, with Ridge/RF/LightGBM/MLP baselines.
   - TimeSeriesSplit + Optuna (50–100 trials).
   - Learning curves and SHAP explanations.
   - Monotonic constraints where the science is clear (more rain after application must never reduce predicted runoff).
   - Save the models with joblib.
3. **Optimizer** (`src/optimizer/`): pymoo NSGA-II using the surrogate models, with bounds from the constraints table and the training range, and a rule to choose from the Pareto front.
4. **Action-Window scheduler** (`src/scheduler/`):
   - Read the Open-Meteo forecast (lat/lon in `00_estate_locations.csv`).
   - Score each candidate hour with the runoff model on **forecast** rain.
   - Apply the rules (rain-free ≥12 h, soil-moisture band, wind, working hours 06–16).
5. **Backend**:
   - **ML service** (`src/api/`, FastAPI, internal): e.g. `POST /ml/recommend` takes block + latest reading + forecast, returns the recommendation JSON.
   - **Spring Boot** (`backend/`, public API, MongoDB):
     - `POST /api/readings` (IoT-compatible schema)
     - `GET /api/blocks/{id}/recommendation`
     - `GET /api/forecast/{estate}`
     - Hourly `@Scheduled` job: refresh the Open-Meteo forecast, call the ML service, store the recommendation.
6. **Dashboard** (`frontend/`, React + Tailwind): latest readings, recommendation + reason, forecast, history.
7. **Thesis evaluation:**
   - Compare the scheduler against the fixed calendar on the hybrid data (resource saved, runoff avoided, yield).
   - Measure the impact of forecast error.
   - Run a sensitivity analysis on the key parameters.

## 8. Working conventions for Claude Code
- **Language:** the user writes informal English (sometimes with typos). Reply clearly and simply.
- **Respect the scope:** agronomy and weather only; no cost or labour variables.
- **Don't overwrite datasets in place.** Write to a new folder, or regenerate with the seed.
- **Report results honestly.** Include unseen-block and forecast-based metrics, not just the best number.
- **Keep the IoT-compatible input schema stable.**
