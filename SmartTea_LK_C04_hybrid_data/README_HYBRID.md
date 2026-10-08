# SmartTea-LK Component 04: Hybrid Datasets (real environment + simulated management)

This version replaces the made-up environment with **real Sri Lanka data**. Only plantation management and the crop's response to it are simulated.

| Part | Source |
|---|---|
| Daily weather (rain, temperature, humidity, wind, radiation, ET₀) | **Real**: ERA5 via Open-Meteo, 5 estate locations, 2021–2025 |
| Rain timing after each field action (4/12/24/48/72 h) | **Real**: hourly ERA5 rainfall |
| Rain *forecasts* available when the action was taken | **Real** Open-Meteo forecasts from 20 Jan 2024; before that, sampled from the real forecast-error distribution of the same estate (`forecast_source` column) |
| Block soil: pH, total N, organic carbon, clay/sand/silt, CEC | **Real**: ISRIC SoilGrids at each block's coordinates (10 masked blocks use the estate mean) |
| Field capacity / wilting point | Derived from real texture (Saxton & Rawls 2006) |
| Block temperature | Real estate temperature, adjusted for block elevation (−0.65 °C per 100 m) |
| Starting soil pH and available N | From SoilGrids pH and total N |
| Fertilizer / irrigation / fungicide / dolomite decisions | Simulated (historical "fixed calendar" practice) |
| Growth, yield, runoff loss, sensor noise | Simulated process model |

## Files (data/)
Same structure as the synthetic pack, plus:
- **01_block_master.csv**: adds `sg_*` SoilGrids columns, `weather_grid_elevation_m` and `temp_offset_c`.
- **02_weather_daily.csv**: real ERA5. `sunshine_hours` is derived from real radiation (Angstrom), because ERA5 sunshine duration overstates bright sunshine in the hills; the raw value is kept as `era5_sunshine_hours_raw`. Also adds `era5_soil_moisture_7_28cm_pct`.
- **05_intervention_records.csv** and **ml_runoff_training.csv**: add `fc_rain_next_12h/24h/48h/72h_mm` and `forecast_source`, i.e. what the forecast said at the time of application, next to the rain that actually fell.
- **08_daily_forecasts_issued.csv**: rain forecast for day 0–3 as issued each morning, per estate (3,545 real, 5,585 simulated days).
- **07_operational_constraints.csv**: soil-moisture rules are now *relative* to each block's own FC/WP, because the real clay soils have a much higher wilting point than the earlier defaults.

| File | Rows |
|---|---|
| Block master | 50 |
| Weather daily | 9,130 |
| Sensor readings | 91,300 |
| Yield / plucking | 9,053 |
| Interventions | 3,233 (fertilizer 850, fungicide 1,771, irrigation 611, dolomite 1) |
| ml_yield_training | 9,053 |
| ml_runoff_training | 850 |
| Daily forecasts | 9,130 |

## Validation (see validation_hybrid.txt)

| Test | Synthetic (old) | Hybrid (new) |
|---|---|---|
| Yield model, XGBoost, test year 2025 | R² 0.93 | R² 0.94 |
| Yield model, XGBoost, **unseen blocks** | R² 0.80 | **R² 0.66** (real soil and weather make blocks more different) |
| Runoff model, XGBoost, with actual rain after (hindsight) | R² 0.93 | R² 0.94 |
| Runoff model, XGBoost, with **forecast rain only** (how it runs live) | not possible | **R² 0.62** |
| Simulated soil moisture vs ERA5-Land | — | r = 0.85–0.91 |
| Seasonal shape vs national production: high grown | — | r = 0.73 |
| Seasonal shape vs national production: low grown | — | r = 0.68 |
| Seasonal shape vs national production: medium grown | — | r ≈ 0 ⚠️ |

**Key finding:** with real forecasts, runoff prediction drops from R² 0.94 to 0.62. Forecast error is the main limit on the Action-Window scheduler, and this result is worth reporting in the thesis.

**Known gap:** mid-country (one Kandy location) does not match the national medium-grown seasonal pattern. The simulated blocks dip in Feb–Mar (Kandy's dry months), while national medium-grown output peaks Mar–May. Possible reasons:
- one location cannot represent all medium-grown districts;
- the growth model's drought response or seasonal effects may be off.

Changing root depth (600–1000 mm) and wilting point (×0.65–0.85) did not fix it. Treat mid-country results with caution.

## Regenerate
```
python generate_smarttea_data.py --out ./data_hybrid --real-data "<path>/SmartTea_LK_C04_real_data"
python generate_smarttea_data.py --out ./data                      # fully synthetic mode (as before)
python validate_hybrid.py data_hybrid "<path>/SmartTea_LK_C04_real_data"
```
Options: `--seed`, `--blocks-per-estate` (soil is real for the 10 blocks per estate in the real pack; more blocks use the estate mean), `--root-zone-mm`, `--wp-factor`.

## Still simulated, so state this in the thesis
Management decisions, crop response, runoff amounts and sensor noise come from the process model. The models learn those coded rules on top of a real environment. Validation against real estate yield and fertilizer records (e.g. from TRI or a plantation company) remains the main open step.
