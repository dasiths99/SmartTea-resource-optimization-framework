# SmartTea-LK Component 04: Data

All data for the resource-optimization framework. It follows a one-way pipeline, and every stage can be rebuilt from the one before it:

```
raw/  ──build_real──►  interim/real/  ──generate_hybrid──►  processed/hybrid/  ──build_model_ready──►  model_ready/
downloads,             cleaned real data      real environment +                feed-ready tables,
never edited           (5 estates)            simulated management              fixed splits, spec
```

**To train a model, start in [`model_ready/`](model_ready/).** Every column of every table is described in
[`DATA_DICTIONARY.md`](DATA_DICTIONARY.md) (machine-readable: `data_dictionary.csv`).

## Layout

| Folder | What it holds | Rule |
|---|---|---|
| `raw/` | Original downloads: Open-Meteo (ERA5 + archived forecasts), NASA POWER, SoilGrids, 47 Forbes & Walker PDFs. `MANIFEST.csv` gives each file's source, URL, retrieval date, licence and SHA-256. | Never edit. Checksums are verified before every rebuild. |
| `interim/real/` | Real data pack, files 00–08: hourly/daily weather, forecast vs actual, NASA POWER, block soil, national production. See its README. | Frozen reference version. Rebuilds go to `interim/real_rebuilt/`. |
| `processed/hybrid/` | Hybrid dataset, tables 01–08 + `ml_*_training.csv`: real weather, forecasts and soil; simulated management, crop response, runoff and sensor noise. | Generator output. Regenerate into a new folder. |
| `model_ready/` | **Feed-ready data** (below). | Built from `processed/hybrid/`. |
| `archive/synthetic_v1/` | First, fully synthetic dataset. | Comparison only. |
| `release/` | **`SmartTea_LK_C04_Dataset.xlsx`**: the whole dataset in one Excel file (README, data dictionary, validation, 17 data sheets) for panels and readers. | Built with `python -m src.data.build_workbook`. Not in git (33 MB copy of the CSVs). |

## Model-ready data (`model_ready/`)

| File | Rows | Use |
|---|---|---|
| `yield_model_ready.csv` | 9,053 plucking rounds | Yield surrogate. Target `green_leaf_kg_per_ha_per_day`, 58 numeric features |
| `runoff_model_ready.csv` | 850 fertilizer applications | Runoff model. Target `runoff_loss_est_pct`, 24 live features |
| `smarttea_master_block_daily.csv.gz` | 91,300 block-days | **All sources in one table**: sensors, block, weather, forecast, actions, yield. For analysis, new features and the evaluation stage |
| `feature_spec.json` | — | Targets, feature sets, decision variables, monotone constraints, training ranges (optimizer bounds), splits |

What "feed-ready" means here:
- All features are numeric. Categories are one-hot encoded (full encoding, no dropped level). There are no missing values.
- Leakage columns are removed: `green_leaf_kg_per_ha` (target × round length) and `aspect` (block identifier).
  `absorption_efficiency_pct` is not stored because it equals 100 − runoff loss.
- Hindsight rain columns are prefixed `hindsight__` and excluded from the runoff **live** feature set.
- Fixed evaluation columns, so every model is tested on the same rows:
  - `split`: train 2021–2023, val 2024, test 2025
  - `cv_fold`: 5 block-grouped folds, 2 blocks per estate in each (unseen blocks)
  - `estate_id`: for leave-one-estate-out (unseen locations)

```python
from src.data.load import load_task, monotone_constraints
X, y, meta = load_task("runoff", feature_set="live")     # or load_task("yield")
train, test = meta.split != "test", meta.split == "test"
```

### Baseline check (XGBoost, default settings, 2026-10-08)

| Task | Test year 2025 | Unseen blocks (cv_fold) | Unseen estate |
|---|---|---|---|
| Yield | R² 0.944 | R² 0.821 ± 0.06 | R² 0.12 (Kandy −1.2) |
| Runoff, hindsight rain (upper bound) | R² 0.937 | R² 0.943 | — |
| Runoff, forecast rain (live) | R² 0.633 | R² 0.655 ± 0.06 | — |

Unseen-block yield R² was first reported as 0.66. That run used drop-first one-hot encoding, which consistently cost
about 0.15 (checked with 3 seeds). The model generalises to new blocks on known estates, **not** to new locations.

## Rebuild everything (from the project root)

```bash
python -m src.data.build_real                                    # raw -> interim/real_rebuilt (checks checksums first)
python src/data/generate_hybrid.py --out data/processed/hybrid_regen --real-data data/interim/real
python -m src.data.compare_tables data/processed/hybrid data/processed/hybrid_regen
python -m src.data.build_model_ready                             # processed/hybrid -> model_ready
python -m src.data.make_data_dictionary                          # refresh DATA_DICTIONARY.md
python -m src.data.build_workbook                                # one-file Excel release -> data/release/
python -m src.data.check_data --workbook                         # final audit: 35 checks, PASS/WARN/FAIL
python src/data/validate_hybrid.py data/processed/hybrid data/interim/real
```

Reproducibility check (2026-10-08):
- Regenerating the hybrid dataset reproduces **all 10 files exactly**.
- Rebuilding the real pack reproduces files 00–05 exactly and 06/06b to the same values.
- Files 07/08 differ by publisher revisions: the frozen file mixes original and revised Forbes & Walker figures, while the script keeps the newest revision. See `interim/real/README.md`.

## Known characteristics (checked by `python -m src.data.check_data`)

- **Historical practice sometimes breaks the rules in `07_operational_constraints.csv`.** This is by design: the simulated
  fixed-calendar practice adds random variation to doses and isn't capped. It is also the baseline the scheduler must beat.
  - 10 of 850 fertilizer doses are outside 100–400 kg/ha (82.8–420).
  - 12 of 250 block-years exceed the annual N ceiling (max 339 kg N/ha).
  - 1 fertilizer gap is under 45 days.
  - 188 of 1,771 sprays were in wind above 4 m/s.
  - 154 irrigation events start at 17:00 (evening sprinklers).
  - **Consequence:** NSGA-II bounds must be the intersection of the constraints table and `training_ranges`.
- **Missing values:** the 7 sensor fields have ~1.5 % deliberate gaps. `sunshine_hours` (derived from weather) is complete.
- **Only 1 dolomite event**, because real SoilGrids pH (~5.2) is already in the 4.5–5.5 target band. pH correction can't be learned from this data.

## Real vs simulated (state this in the thesis)

**Real:**
- weather, hourly rain timing, issued forecasts (real from 2024-01-20; sampled from the real error distribution before that)
- SoilGrids soil, with field capacity and wilting point derived from it
- national production

**Simulated:**
- management decisions, crop growth and yield, runoff loss
- sensor readings, which are the real conditions plus noise; the 7 sensor fields have ~1.5 % missing values

Models therefore learn the generator's rules on top of a real environment. Validation on real estate records is still the main open step.

## Licences and citation

- ERA5 / ERA5-Land via Open-Meteo: CC BY 4.0 (Copernicus Climate Change Service, Open-Meteo)
- SoilGrids 2.0: CC BY 4.0 (ISRIC; Poggio et al. 2021)
- NASA POWER: NASA Langley Research Center POWER Project
- Production figures: Forbes & Walker Tea Brokers, monthly Sri Lanka Tea Production reports

Cite each source when using the data. Full URLs are in `raw/MANIFEST.csv`.
