# SmartTea-LK Component 04: Real Sri Lanka Data Pack

Real, public data for the five SmartTea estate locations (2021–2025), downloaded 8 Oct 2026.
Use it to replace or calibrate the synthetic weather and soil, and to check yield seasonality against national figures.

| # | File | Rows | What it is | Source |
|---|---|---|---|---|
| 00 | estate_locations.csv | 5 | Estate IDs, zone, requested coordinates, and the weather grid cell actually used | — |
| 01 | weather_hourly_era5_2021_2025.csv | 219,120 | Hourly weather **and soil moisture/temperature** per estate | Open-Meteo Historical API (ERA5 / ERA5-Land / ECMWF IFS, "best match") |
| 02 | weather_daily_era5_2021_2025.csv | 9,130 | Daily aggregates of file 01 | Derived |
| 03 | forecast_vs_actual_hourly_2024_2025.csv | 85,475 | Rain forecast 1/2/3/4 days ahead vs what actually fell (from 19 Jan 2024) | Open-Meteo Previous Runs API |
| 04 | forecast_vs_actual_daily_2024_2025.csv | 3,560 | Daily totals of file 03 | Derived |
| 05 | nasa_power_daily_2021_2025.csv | 9,130 | Independent daily weather + soil wetness (cross-check) | NASA POWER (MERRA-2 / CERES) |
| 06 | soilgrids_block_soil_properties.csv (+ 06b long format) | 50 | pH, total N, organic carbon, clay/sand/silt, bulk density, CEC, coarse fragments at 0–5, 5–15, 15–30 cm, with 5–95% range. 10 blocks fall on masked pixels and are filled with the estate mean (`values_filled_from_estate_mean`) | ISRIC SoilGrids 2.0 (250 m) |
| 07 | sl_tea_production_monthly_by_elevation_2021_2025.csv | 300 | National tea production (kg) per month: high / medium / low grown, green tea, total | Forbes & Walker monthly production reports |
| 08 | monthly_weather_vs_production_by_elevation.csv | 180 | Monthly weather per zone joined with national production per elevation | Derived from 02 + 07 |

## Estate locations used

| ID | Region | Zone | Weather grid elevation |
|---|---|---|---|
| E01 | Nuwara Eliya | Up-country / high grown | 1,868 m |
| E02 | Hatton / Dimbula | Up-country / high grown | 1,288 m |
| E03 | Kandy | Mid-country / medium grown | 632 m |
| E04 | Ratnapura | Low-country / low grown | 27 m |
| E05 | Deniyaya / Matara | Low-country / low grown | 424 m |

These are representative tea-growing locations, not real estate boundaries. Block coordinates for soil (file 06) are the 50 block points from the synthetic block master.

## How each file maps to the project

- **Weather (01/02):** replaces `02_weather_daily.csv` in the synthetic pack. The hourly data lets the Action-Window scheduler and the runoff model use *real* rain timing.
- **Soil moisture (01/02):** ERA5-Land soil moisture at 0–7, 7–28 and 28–100 cm is a realistic baseline for the soil-moisture "sensor" input. It is a ~9–11 km model value, not a point sensor, so add block-level variation and noise.
- **Forecast vs actual (03/04):** use it to train or test with **forecast** rain instead of perfect knowledge, and to measure how much forecast error hurts the scheduler.
- **Soil (06):** a realistic starting point for each block's pH, nitrogen and texture (field capacity can be estimated from texture).
- **Production (07/08):** a check that simulated yield follows the real seasonal pattern for each elevation.

## Quick quality notes

**Annual rainfall (ERA5, mm):**

| Estate | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|
| E01 Nuwara Eliya | 2,842 | 2,364 | 2,523 | 2,508 | 3,156 |
| E02 Hatton | 4,835 | 3,877 | 3,967 | 3,624 | 4,233 |
| E03 Kandy | 1,707 | 1,546 | 1,621 | 1,651 | 2,072 |
| E04 Ratnapura | 4,490 | 3,649 | 4,328 | 3,826 | 3,822 |
| E05 Deniyaya | 2,694 | 2,347 | 2,847 | 2,750 | 2,661 |

**Forecast skill for daily rain, 2024–2025:**

| Lead time | MAE | Bias | Agreement on ">5 mm day" | Correlation |
|---|---|---|---|---|
| 1 day ahead | 6.0 mm | −3.6 | 72% | 0.69 |
| 2 days ahead | 6.4 mm | −3.9 | 70% | 0.59 |
| 3 days ahead | 6.5 mm | −4.3 | 68% | 0.50 |
| 4 days ahead | 6.6 mm | −4.0 | 68% | 0.55 |

Forecasts under-predict rain, and skill drops after day 1. That is directly relevant to a 72–96 h Action Window.

**Production (07):** national totals are 299.5 M kg (2021), 249.9 (2022), 254.0 (2023), 260.8 (2024) and 262.8 (2025). For every month, high + medium + low + green = total, to within 2 kg.

## Limitations

- **Gridded models, not station observations.**
  - ERA5 is a reanalysis at about 9–25 km. Mountain rainfall and temperature are smoothed; Deniyaya (E05) rainfall looks low for that region.
  - NASA POWER is coarser still (0.5°): **E01 = E02 and E04 = E05 share the same cell.** Use it only as a cross-check.
- **Actual = analysis.** In files 03/04, "actual" rain is the Open-Meteo best-match analysis for 2024–2025 (same source as file 01). Forecast lead times are only available from 19 Jan 2024.
- **SoilGrids** values are model predictions at 250 m with wide uncertainty. Check the Q0.05/Q0.95 columns.
  - Nitrogen is total N (g/kg), not plant-available N (ppm).
  - pH is pH in water.
- **National production is not block yield.**
  - The monthly correlation with weather is weak at national level, about 0.1–0.3.
  - 2021–2022 production was strongly affected by Sri Lanka's chemical-fertilizer import ban and the economic crisis. That is a real fertilizer effect, but it is not weather-driven, so be careful when using 2022.
- Forbes & Walker figures are taken from their public monthly reports (latest revised figure kept). Cite Forbes & Walker Tea Brokers as the source.

## Provenance and rebuilding
- Raw downloads (including the 47 Forbes & Walker PDFs) are in `data/raw/`, with checksums in `data/raw/MANIFEST.csv`.
- `python -m src.data.build_real` rebuilds this pack from `data/raw/` into `data/interim/real_rebuilt/` (it never overwrites this folder).
- Rebuild check (2026-10-08): files 00–05 identical; 06/06b same values in a different row order (12 estate-mean cells differ by 0.001);
  07/08 differ because this frozen file mixes original and revised Forbes & Walker figures, while the script keeps the newest
  revision consistently (116 of 300 values, median 1 %). The hybrid generator does not read 07/08, so training data is unaffected.

## Sources
- Open-Meteo Historical Weather API: https://open-meteo.com/en/docs/historical-weather-api (ERA5/ERA5-Land: Copernicus Climate Change Service; data CC BY 4.0)
- Open-Meteo Previous Runs API: https://open-meteo.com/en/docs/previous-runs-api
- NASA POWER: https://power.larc.nasa.gov/
- ISRIC SoilGrids 2.0: https://docs.isric.org/globaldata/soilgrids/ (CC BY 4.0)
- Forbes & Walker Tea Brokers, Sri Lanka Tea Production monthly reports: https://www.forbestea.com/statistics-national-production
