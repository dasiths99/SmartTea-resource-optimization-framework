# CLAUDE.md: SmartTea-LK Component 04 (Resource Optimization Framework)

This file gives Claude Code the full context of this project. The full project record is in `md_files/docs/SmartTea_LK_C04_Full_Project.md`. All project Markdown files live in `md_files/` (same sub-paths as before, e.g. `md_files/data/README.md`).

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
├── md_files/                         ← ALL project Markdown docs (CLAUDE.md, README.md, data READMEs, DATA_DICTIONARY.md,
│                                       docs/SmartTea_LK_C04_Full_Project.md = full project record)
├── data/                             ← ALL data; read md_files/data/README.md first
│   ├── raw/                          ← original downloads + MANIFEST.csv (source, URL, licence, sha256). Never edit
│   ├── interim/real/                 ← real data pack 00–08 (frozen reference)
│   ├── processed/hybrid/             ← hybrid tables 01–08 + ml_*_training.csv + validation reports
│   ├── model_ready/                  ← ★ USE THIS for model training (feed-ready tables, splits, feature_spec.json)
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
└── docs/                             ← SmartTea_LK_C04_Full_Project.md, RUN_DEMO.md
```
Data was reorganised into the raw → interim → processed → model_ready layout on 2026-10-08. Every stage rebuilds from the one before it (see md_files/data/README.md).

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
- `yield_model_ready.csv` (9,053 rows, 58 features) and `runoff_model_ready.csv` (850 rows, 24 live features; previous-day temperature/humidity, same-day values moved to `hindsight__`). All features are numeric, with full one-hot encoding, no missing values and leakage columns removed. Hindsight columns (actual rain after, same-day weather) are prefixed `hindsight__`.
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
- **Reproducibility (2026-10-08):** the hybrid regeneration reproduces all 10 files exactly. `build_real` reproduces files 00–06. Files 07/08 differ by Forbes & Walker revisions (see `md_files/data/interim/real/README.md`).

## 5. Key results so far

**Headline (realistic): decision-time ("live") features, best of 7 models chosen on val 2024 only** (`python -m src.models.compare_models`, artifacts/reports/model_comparison.csv). Runoff uses previous-day weather since the humidity-leak fix (2026-10-08):

| Task | Model | Train | Val 2024 | Test 2025 | Unseen blocks + future year |
|---|---|---|---|---|---|
| Yield (live) | CatBoost | 0.96 | 0.83 | **0.91** (MAE 1.63 kg/ha/day) | **0.80 ± 0.03** |
| Runoff (live, forecast rain, monotone) | XGBoost | 0.83 | 0.69 | **0.57** (MAE 9.9 pp) | **0.44 ± 0.19** |
| Runoff risk high/low (same model; cut = 23.9 %, the 2021–23 median) | XGBoost | | | **accuracy 0.81** (guessing 0.54) | **0.79 ± 0.08** |

- Training notebook: `notebooks/01_model_training.ipynb` re-trains and saves both models (~2 min); results identical to `compare_models`.
- R² is not "accuracy": say "explains 91 % of the variation".

**Model comparison (live features, same protocol for all 7 models):**

| Model | Yield val / test / unseen+future | Runoff val / test / unseen+future |
|---|---|---|
| CatBoost | **0.83 / 0.91 / 0.80 ± 0.03** ← saved | 0.67 / 0.57 / 0.46 |
| LightGBM | 0.81 / 0.91 / 0.80 | 0.69 / 0.54 / 0.43 |
| XGBoost | 0.81 / 0.90 / 0.78 | **0.69 / 0.57 / 0.44 ± 0.19** ← saved (monotone) |
| HistGradientBoosting | 0.81 / 0.90 / 0.79 | 0.69 / 0.55 / 0.45 |
| Random Forest | 0.67 / 0.85 / 0.65 | 0.68 / 0.55 / 0.45 |
| MLP | 0.62 / 0.77 / 0.36 | 0.59 / 0.04 / −0.71 |
| Ridge | 0.45 / 0.63 / 0.28 | 0.57 / 0.43 / 0.20 |

- **Humidity-leak fix:** before it, runoff (with same-day mean humidity/temperature) scored val 0.73 / test 0.63–0.65 / unseen+future 0.51–0.54 (artifacts/reports/model_comparison_before_humidity_fix.csv). The ~0.08 drop is the honest cost of using only what is known at decision time. Same-day values are kept as `hindsight__temp_at_exec_c` / `hindsight__humidity_at_exec_pct`.
- The four boosting models are within ~0.02 of each other, which is noise; the winner is picked by val R² only.
- Saved models: `artifacts/models/yield_catboost.joblib` and `artifacts/models/runoff_xgboost.joblib`, each with a `.json` file listing features, settings and scores. TabPFN was not run: it needs a free licence key from ux.priorlabs.ai.
- Do not tune toward a target accuracy. Choose settings on val only, and score test once.
- Unregularised runoff overfitted badly: train 0.998 vs test 0.59.

**Tier 2 optimizer (NSGA-II), closed-loop test on 2025, all 50 blocks** (`python -m src.optimizer.evaluate`, artifacts/reports/optimizer/):
- **How a plan is scored:** the runoff model gives the N lost under the decision-time forecast (and picks the product). The soil-N response model (`src/optimizer/soil_n.py`, fitted on 2021–23: +0.27 ppm per kg effective N, fading with τ = 45 days; true generator value 0.35) carries the effect into later rounds. The yield model scores every round in a 90-day horizon.
- **Pick rule:** maximise (horizon yield gain − `min_ae` × N). `min_ae` is the kg of green leaf each kg of N must add. Default **3.5**, the setting that keeps N near current practice.
- **NSGA-II check:** 40 × 40 reaches 100 % of the exhaustive-grid optimum, with the same dose in 95–100 % of plans (`--check-solver`, solver_check.csv).

| Per ha per year, 2025 | Historical practice | Optimizer (min_ae 3.5) |
|---|---|---|
| N applied | 198 kg | 182 kg (**−8 %**) |
| N lost to runoff (predicted/est.) | 59 kg | 36 kg (**−40 %**) |
| Applications | 3.3 | 3.0 |
| Predicted green leaf | 7,519 kg | 7,776 kg (**+3.4 %**) |
| Rule breaks (dose, 45-day gap, annual ceiling) | 0 | 0 |

- **Where the N goes:** low-soil-N blocks (12 ppm when it applies vs 22 ppm when it declines), on dry forecast days (2.6 mm in the next 24 h on average). Nuwara Eliya, with the highest soil N, gets −61 % N; Kandy gets +54 %.
- **Threshold sweep** (`--sweep`, min_ae_sweep_2025.csv/.png): min_ae 2 → N +51 %, yield +6.3 %; 3 → +19 %, +5.2 %; **3.5 → −7 %, +3.4 %**; 4 → −26 %, +2.4 %; 4.5 → −49 %, +0.3 %; 8 (no N) → −100 %, −5.1 %.

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
- **SHAP findings (`python -m src.models.explain_shap`, artifacts/reports/shap/):**
  - **Fungicide looks harmful to yield (Spearman −0.67) because of confounding.** Sprays happen in wet, cloudy blight weather: corr with sunshine −0.62, with rain +0.49. Never let NSGA-II choose fungicide through the yield surrogate; decide it by blight-risk rule + Action Window.
  - **Humidity leak (fixed 2026-10-08):** `humidity_at_exec_pct` was the application day's daily mean and the top runoff driver (20 %), partly leaking same-day rain (corr 0.40 with actual rain vs 0.23 with forecast). The live set now uses `humidity_prev_day_pct` / `temp_prev_day_c`. After the fix the runoff drivers are soil moisture 21 %, previous-3-day rain 13 %, forecast rain 24 h 12 %, slope 11 %, forecast rain 48 h 10 %; previous-day humidity 5 %. Agronomy direction check 7/8 (only fungicide, see above).
  - **Sensible effects:** forecast rain and slope raise loss; soil moisture jumps near field capacity (~40 %); soil N, N applied and soil moisture raise yield.
- **Use full one-hot encoding** (as stored in `data/model_ready/`); drop-first encoding cost ~0.15 R² on unseen blocks.
- **Optimizer limits (Tier 2):**
  - **Yields are model predictions.** The 2025 test makes soil N counterfactual, but other conditions stay as observed.
  - **A one-year test understates the harm of big N cuts.** Soil N runs down over years; even zero N shows only −5 % yield in one year. Do not pick a high `min_ae` to "save" N without a multi-year check.
  - **`min_ae` is a preference, not a fact.** Check it against TRI guidance on N response.
  - **Rounds after the current one use the current round's conditions as a proxy,** so only differences between plans are meaningful.
  - **Irrigation is not valued by the per-round yield model** (~0.3 kg leaf per mm), and the trigger allowed it at only 11 round starts. The "water saved" result is not real. Irrigation belongs in the daily Tier 3 scheduler, using the soil-moisture trigger.
  - **The first optimizer version judged each round alone** and used +65 % N for +2.5 % yield. This is why it now uses the soil-N response and the 90-day horizon.

## 7. Development roadmap (next steps)
1. ~~**Repo hygiene**~~ ✔ done 2026-10-08: git, venv, folder layout, data pipeline (raw → model_ready), data dictionary, manifest.
2. **Model training notebook/scripts** (`src/models/`, `notebooks/01_model_training.ipynb`). Done 2026-10-08 except Optuna; the notebook re-trains and saves both models in ~1.5 min:
   - XGBoost yield and runoff models, with Ridge/RF/LightGBM/MLP baselines.
   - TimeSeriesSplit + Optuna (50–100 trials).
   - Learning curves and SHAP explanations.
   - Monotonic constraints where the science is clear (more rain after application must never reduce predicted runoff).
   - Save the models with joblib.
3. ~~**Optimizer**~~ ✔ done 2026-10-09 (`src/optimizer/`):
   - `limits.py`: constraints ∩ training ranges.
   - `context.py`: block state at decision time.
   - `soil_n.py`: soil-N response model.
   - `optimize.py`: NSGA-II, 90-day horizon, efficiency pick rule, product choice by runoff.
   - `evaluate.py`: 2025 closed loop, sweep, solver check.
   - `tests/test_optimizer.py`: 9 rule tests.
   - Run: `python -m src.optimizer.soil_n`, `python -m src.optimizer.optimize --block E03-B07 --date 2025-06-01`, `python -m src.optimizer.evaluate [--sweep 2,3,3.5,4 | --check-solver]`, `python -m pytest tests -q`.
   - Open items: irrigation goes to Tier 3; fungicide by a blight-risk rule; dolomite by the pH rule; a multi-year check of N cuts.
**Steps 4–6, basic version ✔ 2026-10-15 (for the 50 % viva; how to run + demo script in `docs/RUN_DEMO.md`; three terminals: `uvicorn src.api.main:app --port 8000`, `cd backend && mvn spring-boot:run`, `cd frontend && npm run dev`):**
   - `src/api/live.py` builds the optimizer context from live readings + the raw Open-Meteo JSON (assumptions reported per response); `src/api/main.py` = FastAPI `POST /ml/recommend` (optional `what_if` = "dry"/"wet": labelled simulated weather for demos), `/ml/health`; `src/api/explain.py` = plain-language headline, rated factors, yield forecast; `src/api/export_seed.py` writes the backend seed JSON.
   - `src/scheduler/action_window.py`: rule-based Tier 3: hourly fertilizer scan (runoff model on forecast rain), 4-day best-time table, dolomite pH rule, blister-blight fungicide rule (sunshine from radiation, as in training), irrigation = the dataset's own rule (irrigated blocks, soil moisture below trigger, < 5 mm rain in 2 days, 6–25 mm, capped by the 3 million L reservoir).
   - `backend/`: Spring Boot 3.3 (Java 17+), package `lk.smarttea.c04`; MongoDB URI from root `.env` (`MONGODB_URI`, git-ignored); seeds 5 estates + 50 blocks; hourly job keeps a block's what-if weather; CORS allows localhost / 127.0.0.1 on any port.
   - `frontend/`: React 18 + Tailwind 4 + Vite, proxy `/api` → :8080 (`API_TARGET` overrides); tabs Demo scenarios (loads a scenario into the reading form), Recommendation, Enter reading (IoT), Weather forecast, History; no login yet.
   - `tests/test_live_api.py`: live-pipeline tests (22 tests in `tests/` in total).
   - **Mark as done** (collection `actions_done`, `POST /api/blocks/{id}/actions-done`): the backend sends the log to the ML service (`action_history`), which enforces dolomite 730 days, sprays 7 days + a "do not pluck before" reminder (pre-harvest interval 7 days), irrigation 3 days, and counts a marked fertilizer toward the 45-day rule. The IoT reading format is unchanged.
   - Known gaps: no uncertainty shown on predictions; the gaps rely on the user pressing Mark as done; no Java or React tests.
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
