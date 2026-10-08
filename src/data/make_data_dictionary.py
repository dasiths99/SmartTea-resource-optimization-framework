"""Write data/DATA_DICTIONARY.md and data/data_dictionary.csv from the actual data files.

Every column of every table in data/interim/real, data/processed/hybrid and data/model_ready is listed with
type, unit, origin, description, missing % and observed range (or levels). Descriptions live in DESC below;
the script fails if a column has no description, so the dictionary cannot silently go out of date.

Usage:
    python -m src.data.make_data_dictionary
"""
import os
import re

import pandas as pd

D = "data"
REAL, SIM, DER, META = "real", "simulated", "derived", "meta"

# column -> (unit, description). Origin is set per table (TABLES) with per-column overrides (ORIGIN).
DESC = {
    # keys and identifiers
    "block_id": ("", "Tea block key, e.g. E03-B07 = estate E03, block 7"),
    "estate_id": ("", "Estate / location key E01-E05"),
    "estate_name": ("", "Fictional estate name (the location is real)"),
    "region": ("", "Real tea-growing region of the estate"),
    "agro_zone": ("", "Elevation zone: up (high grown), mid (medium grown), low (low grown)"),
    "elevation": ("", "Forbes & Walker elevation class: high, medium, low, green_tea, total"),
    "date": ("YYYY-MM-DD", "Calendar day (local time, Asia/Colombo)"),
    "datetime_local": ("YYYY-MM-DD HH:MM", "Hour, local time (Asia/Colombo)"),
    "issue_date": ("YYYY-MM-DD", "Morning on which the forecast was issued"),
    "year": ("", "Calendar year"), "month": ("1-12", "Calendar month"),
    "hour": ("0-23", "Hour of day the field action started"),
    "intervention_id": ("", "Unique field-action key"),
    "row_id": ("", "Row key of the model-ready table"),
    "pluck_date": ("YYYY-MM-DD", "Date the plucking round ended (leaf harvested)"),
    "execution_datetime": ("YYYY-MM-DD HH:MM", "Start time of the field action"),
    # estate locations
    "query_lat": ("deg", "Latitude requested from the weather API"), "query_lon": ("deg", "Longitude requested from the weather API"),
    "grid_lat": ("deg", "Latitude of the weather grid cell actually used"), "grid_lon": ("deg", "Longitude of the weather grid cell actually used"),
    "grid_elevation_m": ("m", "Elevation of the weather grid cell"),
    "weather_grid_elevation_m": ("m", "Elevation of the estate's weather grid cell"),
    # hourly / daily ERA5
    "temp_c": ("°C", "Air temperature at 2 m"), "humidity_pct": ("%", "Relative humidity at 2 m"),
    "dew_point_c": ("°C", "Dew point at 2 m"), "precip_mm": ("mm", "Total precipitation in the hour"),
    "rain_mm": ("mm", "Rain amount (hourly table: liquid rain in the hour; daily/monthly tables: total precipitation)"),
    "cloud_cover_pct": ("%", "Total cloud cover"), "wind_speed_10m_ms": ("m/s", "Wind speed at 10 m"),
    "wind_gust_10m_ms": ("m/s", "Wind gust at 10 m"), "solar_radiation_wm2": ("W/m²", "Shortwave radiation (hour mean)"),
    "sunshine_s": ("s", "Sunshine duration in the hour"), "et0_mm": ("mm", "FAO-56 reference evapotranspiration"),
    "vpd_kpa": ("kPa", "Vapour pressure deficit"), "vpd_mean_kpa": ("kPa", "Daily mean vapour pressure deficit"),
    "soil_temp_0_7cm_c": ("°C", "ERA5-Land soil temperature 0-7 cm"),
    "soil_moisture_0_7cm_pct": ("% vol", "ERA5-Land soil moisture 0-7 cm"),
    "soil_moisture_7_28cm_pct": ("% vol", "ERA5-Land soil moisture 7-28 cm"),
    "soil_moisture_28_100cm_pct": ("% vol", "ERA5-Land soil moisture 28-100 cm"),
    "rain_hours": ("h", "Hours in the day with ≥ 0.1 mm precipitation"),
    "temp_min_c": ("°C", "Daily minimum air temperature"), "temp_mean_c": ("°C", "Mean air temperature"),
    "temp_max_c": ("°C", "Daily maximum air temperature (monthly table: mean of daily maxima)"),
    "humidity_mean_pct": ("%", "Daily mean relative humidity"), "humidity_min_pct": ("%", "Daily minimum relative humidity"),
    "cloud_cover_mean_pct": ("%", "Daily mean cloud cover"), "wind_mean_ms": ("m/s", "Daily mean wind speed at 10 m"),
    "wind_max_ms": ("m/s", "Daily maximum hourly wind speed at 10 m"), "gust_max_ms": ("m/s", "Daily maximum gust"),
    "solar_radiation_mj_m2": ("MJ/m²/day", "Daily shortwave radiation"),
    "sunshine_hours": ("h", "Sunshine hours (real tables: from radiation via Angstrom; sensor table: simulated reading)"),
    "rainfall_mm": ("mm", "Daily precipitation (ERA5)"), "wind_speed_ms": ("m/s", "Daily mean wind speed"),
    "era5_sunshine_hours_raw": ("h", "Raw ERA5 sunshine duration (overstates bright sunshine in the hills; not used)"),
    "era5_soil_moisture_7_28cm_pct": ("% vol", "ERA5-Land soil moisture 7-28 cm (realism reference)"),
    "source": ("", "Data source label"),
    # forecasts
    "precip_actual_mm": ("mm", "Precipitation that fell in the hour (Open-Meteo best-match analysis)"),
    **{f"precip_forecast_{k}day_ahead_mm": ("mm", f"Hourly precipitation forecast issued {k} day(s) earlier") for k in range(1, 5)},
    "temp_actual_c": ("°C", "Actual air temperature in the hour"),
    "temp_forecast_1day_ahead_c": ("°C", "Temperature forecast issued 1 day earlier"),
    "wind_forecast_1day_ahead_ms": ("m/s", "Wind forecast issued 1 day earlier"),
    "rain_actual_mm": ("mm", "Daily precipitation that fell"),
    **{f"rain_fc_{k}day_ahead_mm": ("mm", f"Daily precipitation forecast issued {k} day(s) earlier") for k in range(1, 5)},
    **{f"fc_rain_day{k}_mm": ("mm", f"Rain forecast for day +{k} as issued that morning") for k in range(0, 4)},
    **{f"fc_rain_next_{h}h_mm": ("mm", f"Rain forecast for the {h} h after the action, as known when it started (live-realistic)") for h in (12, 24, 48, 72)},
    **{f"rain_next_{h}h_mm": ("mm", f"Rain that actually fell in the {h} h after the action (hindsight)") for h in (4, 12, 24, 48, 72)},
    "forecast_source": ("", "real (Open-Meteo previous runs, from 2024-01-20) or simulated from the real error distribution"),
    "fc_source": ("", "Same as forecast_source, for the forecast issued that day"),
    # NASA POWER
    "prectotcorr": ("mm/day", "NASA POWER bias-corrected precipitation"), "t2m": ("°C", "NASA POWER mean temperature at 2 m"),
    "t2m_max": ("°C", "NASA POWER maximum temperature"), "t2m_min": ("°C", "NASA POWER minimum temperature"),
    "rh2m": ("%", "NASA POWER relative humidity at 2 m"), "ws2m": ("m/s", "NASA POWER wind speed at 2 m"),
    "allsky_sfc_sw_dwn": ("MJ/m²/day", "NASA POWER all-sky surface shortwave radiation"),
    "allsky_sfc_par_tot": ("MJ/m²/day", "NASA POWER all-sky photosynthetically active radiation"),
    "clrsky_sfc_sw_dwn": ("MJ/m²/day", "NASA POWER clear-sky surface shortwave radiation"),
    "gwettop": ("0-1", "NASA POWER surface soil wetness"), "gwetroot": ("0-1", "NASA POWER root-zone soil wetness"),
    "gwetprof": ("0-1", "NASA POWER profile soil wetness"),
    "evptrns": ("see POWER docs", "NASA POWER parameter EVPTRNS (evapotranspiration)"),
    "ps": ("kPa", "NASA POWER surface pressure"),
    # SoilGrids
    "latitude": ("deg", "Block latitude"), "longitude": ("deg", "Block longitude"),
    "property": ("", "SoilGrids property code: bdod, cec, cfvo, clay, nitrogen, phh2o, sand, silt, soc"),
    "depth": ("", "SoilGrids depth interval"), "mean": ("see unit", "SoilGrids predicted mean"),
    "q05": ("see unit", "SoilGrids 5 % quantile"), "q95": ("see unit", "SoilGrids 95 % quantile"),
    "unit": ("", "Unit of the value / amount in this row"),
    "values_filled_from_estate_mean": ("bool", "True when the block fell on a masked SoilGrids pixel and got the estate mean"),
    "sg_filled_from_estate_mean": ("bool", "Same flag, carried into the block master"),
    "sg_ph_h2o": ("pH", "SoilGrids pH in water, 0-15 cm depth-weighted"),
    "sg_total_n_g_kg": ("g/kg", "SoilGrids total nitrogen, 0-15 cm (not plant-available N)"),
    "sg_soc_g_kg": ("g/kg", "SoilGrids soil organic carbon, 0-15 cm"), "sg_clay_pct": ("%", "SoilGrids clay, 0-15 cm"),
    "sg_sand_pct": ("%", "SoilGrids sand, 0-15 cm"), "sg_silt_pct": ("%", "SoilGrids silt, 0-15 cm"),
    "sg_bulk_density_kg_dm3": ("kg/dm³", "SoilGrids bulk density, 0-15 cm"),
    "sg_cec_cmol_kg": ("cmol(c)/kg", "SoilGrids cation exchange capacity, 0-15 cm"),
    # production
    "production_kg": ("kg", "National tea production in the month (Forbes & Walker)"),
    "source_report": ("", "Forbes & Walker monthly report the figure was taken from"),
    "rain_days": ("days", "Days with ≥ 1 mm rain (mean over the zone's estates)"),
    "solar_mj_m2_day": ("MJ/m²/day", "Mean daily radiation"), "sunshine_h_day": ("h/day", "Mean daily sunshine"),
    "rain_prev_month_mm": ("mm", "Zone rainfall in the previous month"), "rain_prev_3m_mm": ("mm", "Zone rainfall in the previous 3 months"),
    "days_in_month": ("days", "Days in the month"), "production_kg_per_day": ("kg/day", "production_kg / days_in_month"),
    # block master
    "area_ha": ("ha", "Block area"), "elevation_m": ("m", "Block elevation"), "slope_pct": ("%", "Block slope"),
    "aspect": ("", "Slope aspect (no effect in the generator; dropped from models)"),
    "soil_type": ("", "Soil texture class derived from SoilGrids"),
    "field_capacity_pct": ("% vol", "Field capacity (Saxton & Rawls 2006, from SoilGrids texture)"),
    "wilting_point_pct": ("% vol", "Permanent wilting point (Saxton & Rawls 2006)"),
    "cultivar": ("", "Planting material: VP clone A/B/C or seedling tea"), "bush_age_yrs": ("years", "Age of the tea bushes"),
    "shade_tree_cover_pct": ("%", "Shade-tree canopy cover"), "pruning_cycle_yrs": ("years", "Years between prunings"),
    "last_pruning_date_before_2021": ("YYYY-MM-DD", "Last pruning before the simulation start"),
    "irrigation_available": ("0/1", "Block has irrigation infrastructure"),
    "temp_offset_c": ("°C", "Block temperature correction for elevation vs weather grid (−0.65 °C per 100 m)"),
    # sensors
    "soil_moisture_pct": ("% vol", "Soil moisture reading (manual / IoT form field)"),
    "soil_ph": ("pH", "Soil pH reading"), "soil_n_ppm": ("ppm", "Plant-available soil nitrogen reading"),
    "soil_p_ppm": ("ppm", "Available phosphorus reading"), "soil_k_ppm": ("ppm", "Exchangeable potassium reading"),
    "soil_temp_c": ("°C", "Soil temperature reading"), "light_lux": ("lux", "Daytime mean light level under shade"),
    # yield
    "round_days": ("days", "Length of the plucking round (days since previous pluck)"),
    "plucking_standard": ("", "Plucking standard: fine, medium or coarse"),
    "green_leaf_kg_per_ha": ("kg/ha", "Green leaf harvested in the round (leakage for the per-day target; never a feature)"),
    "green_leaf_kg": ("kg", "Green leaf harvested from the whole block"),
    "green_leaf_kg_per_ha_per_day": ("kg/ha/day", "Yield rate = green_leaf_kg_per_ha / round_days (yield model TARGET)"),
    "days_since_pruning": ("days", "Days since the block was last pruned"),
    "plucked": ("0/1", "1 if the block was plucked that day"),
    # yield features (per round)
    "soil_moisture_mean": ("% vol", "Mean soil moisture over the round"), "soil_moisture_min": ("% vol", "Minimum soil moisture over the round"),
    "soil_ph_mean": ("pH", "Mean soil pH over the round"), "soil_n_ppm_mean": ("ppm", "Mean available N over the round"),
    "soil_p_ppm_mean": ("ppm", "Mean available P over the round"), "soil_k_ppm_mean": ("ppm", "Mean K over the round"),
    "soil_temp_mean": ("°C", "Mean soil temperature over the round"), "light_lux_mean": ("lux", "Mean light over the round"),
    "sunshine_hours_mean": ("h/day", "Mean sunshine over the round"), "rain_sum_mm": ("mm", "Rain over the round"),
    "rain_30d_mm": ("mm", "Rain in the 30 days before the pluck"), "humidity_mean": ("%", "Mean humidity over the round"),
    "solar_rad_mean": ("MJ/m²/day", "Mean radiation over the round"), "et0_sum_mm": ("mm", "Reference ET over the round"),
    "n_applied_60d_kg_ha": ("kg N/ha", "Fertilizer N applied in the 60 days before the pluck (decision)"),
    "n_applied_90d_kg_ha": ("kg N/ha", "Fertilizer N applied in the 90 days before the pluck (decision)"),
    "n_absorbed_est_90d_kg_ha": ("kg N/ha", "N applied in 90 days × (1 − runoff loss); live: use the runoff model's prediction"),
    "days_since_last_fertilizer": ("days", "Days since the last fertilizer application (365 if none)"),
    "irrigation_mm_in_round": ("mm", "Irrigation applied during the round (decision)"),
    "fungicide_sprays_14d": ("count", "Fungicide sprays in the 14 days before the pluck (decision)"),
    "dolomite_last_365d": ("0/1", "Dolomite applied in the previous 365 days (decision)"),
    # interventions
    "intervention_type": ("", "fertilizer, irrigation, fungicide or dolomite"),
    "product_code": ("", "Product: NPK_BAL, NPK_HN, UREA, FUNG_CU, WATER, DOLOMITE"),
    "product_desc": ("", "Product description"), "amount_per_ha": ("see unit", "Amount applied per hectare"),
    "total_amount": ("see unit × ha", "Amount applied to the whole block"),
    "n_kg_per_ha": ("kg N/ha", "Nitrogen content of the application"), "p_kg_per_ha": ("kg P/ha", "Phosphorus content"),
    "k_kg_per_ha": ("kg K/ha", "Potassium content"), "irrigation_mm": ("mm", "Irrigation depth applied"),
    "application_method": ("", "broadcast, sprinkler or knapsack spray"),
    "soil_moisture_at_exec": ("% vol", "Soil moisture reading when the action started"),
    "soil_ph_at_exec": ("pH", "Soil pH reading when the action started"), "temp_at_exec_c": ("°C", "Air temperature at execution"),
    "humidity_at_exec_pct": ("%", "Humidity at execution"), "wind_at_exec_ms": ("m/s", "Wind at execution (sprays only)"),
    "rain_prev_3d_mm": ("mm", "Rain in the 3 days before the action"),
    "temp_prev_day_c": ("°C", "Previous day's mean air temperature + block elevation offset (live: known at decision time)"),
    "humidity_prev_day_pct": ("%", "Previous day's mean relative humidity (live: known at decision time)"),
    "runoff_loss_est_pct": ("%", "Share of applied fertilizer lost to runoff/volatilisation (runoff model TARGET)"),
    "absorption_efficiency_pct": ("%", "100 − runoff_loss_est_pct (alternative target; identical information)"),
    "yield_before_kg_ha_day": ("kg/ha/day", "Yield rate in the rounds before the action"),
    "yield_after_kg_ha_day": ("kg/ha/day", "Yield rate in the rounds after the action"),
    "yield_delta_pct": ("%", "Yield change after the action"), "status": ("", "Execution status (all 'executed')"),
    # resource usage
    "resource_type": ("", "Resource tracked: fertilizer, fungicide, irrigation water, dolomite"),
    "stock_start": ("see unit", "Estate stock at the start of the month"), "allocated": ("see unit", "Amount allocated in the month"),
    "used": ("see unit", "Amount actually used in the month"), "wastage_pct": ("%", "(allocated − used) / allocated"),
    # constraints
    "constraint_name": ("", "Rule name"), "applies_to": ("", "Action, zone or component the rule applies to"),
    "value": ("see unit", "Rule value"), "description": ("", "What the rule means"),
    # master block-day
    "fert_product_code": ("", "Fertilizer product applied that day (empty if none)"),
    "fert_kg_per_ha": ("kg/ha", "Fertilizer mixture applied that day (0 if none)"),
    "fert_n_kg_per_ha": ("kg N/ha", "N applied that day"), "fert_p_kg_per_ha": ("kg P/ha", "P applied that day"),
    "fert_k_kg_per_ha": ("kg K/ha", "K applied that day"),
    "fert_runoff_loss_est_pct": ("%", "Runoff loss of that day's fertilizer application"),
    "fungicide_ml_per_ha": ("ml/ha", "Fungicide sprayed that day (0 if none)"),
    "dolomite_kg_per_ha": ("kg/ha", "Dolomite applied that day (0 if none)"),
    # yield live features (known when the plucking round starts)
    **{f"start_{c}_7d": (u, f"Mean {lbl} over the 7 days before the round starts (live)")
       for c, u, lbl in [("soil_moisture_pct", "% vol", "soil moisture"), ("soil_ph", "pH", "soil pH"),
                         ("soil_n_ppm", "ppm", "available N"), ("soil_p_ppm", "ppm", "available P"),
                         ("soil_k_ppm", "ppm", "K"), ("soil_temp_c", "°C", "soil temperature"),
                         ("light_lux", "lux", "light level"), ("sunshine_hours", "h/day", "sunshine")]},
    "start_rain_7d_mm": ("mm", "Rain in the 7 days before the round starts (live)"),
    "start_rain_30d_mm": ("mm", "Rain in the 30 days before the round starts (live)"),
    "start_temp_mean_7d_c": ("°C", "Mean air temperature over the 7 days before the round (live)"),
    "start_et0_7d_mm": ("mm", "Reference ET over the 7 days before the round (live)"),
    "fc_rain_next4d_mm": ("mm", "Rain forecast for day 0-3 issued the morning the round starts (live)"),
    "clim_rain_round_mm": ("mm", "Normal rain for the estate and month × round length (train years 2021-2023 only)"),
    "clim_temp_mean_c": ("°C", "Normal mean temperature for the estate and month (train years only)"),
    "clim_solar_mj_m2_day": ("MJ/m²/day", "Normal daily radiation for the estate and month (train years only)"),
    "clim_et0_round_mm": ("mm", "Normal reference ET × round length (train years only)"),
    # model-ready meta
    "split": ("", "Fixed time split: train 2021-2023, val 2024, test 2025"),
    "cv_fold": ("0-4", "Block-grouped CV fold (unseen blocks); 2 blocks per estate per fold"),
}
WX = {"rainfall_mm", "temp_min_c", "temp_mean_c", "temp_max_c", "humidity_pct", "wind_speed_ms", "solar_radiation_mj_m2",
      "sunshine_hours", "era5_sunshine_hours_raw", "et0_mm", "era5_soil_moisture_7_28cm_pct"}
for k in WX:
    u, d = DESC[k]
    DESC[f"wx_{k}"] = (u, f"Estate weather that day (ERA5): {d[0].lower() + d[1:]}")
SOIL_PROP = {"phh2o": ("pH", "pH in water"), "nitrogen": ("g/kg", "total nitrogen"), "soc": ("g/kg", "soil organic carbon"),
             "clay": ("%", "clay"), "sand": ("%", "sand"), "silt": ("%", "silt"), "bdod": ("kg/dm³", "bulk density"),
             "cec": ("cmol(c)/kg", "cation exchange capacity"), "cfvo": ("cm³/100cm³", "coarse fragments")}

TABLES = {  # folder/file -> (origin, grain, purpose)
    "interim/real/00_estate_locations.csv": (REAL, "estate", "Estate coordinates and the weather grid cell used"),
    "interim/real/01_weather_hourly_era5_2021_2025.csv": (REAL, "estate × hour", "Hourly ERA5 weather and soil (Open-Meteo)"),
    "interim/real/02_weather_daily_era5_2021_2025.csv": (DER, "estate × day", "Daily aggregates of the hourly ERA5 table"),
    "interim/real/03_forecast_vs_actual_hourly_2024_2025.csv": (REAL, "estate × hour", "Archived 1-4 day forecasts vs actual (from 2024-01-19)"),
    "interim/real/04_forecast_vs_actual_daily_2024_2025.csv": (DER, "estate × day", "Daily totals of table 03 (complete days only)"),
    "interim/real/05_nasa_power_daily_2021_2025.csv": (REAL, "estate × day", "NASA POWER cross-check (coarse 0.5° grid)"),
    "interim/real/06_soilgrids_block_soil_properties.csv": (REAL, "block", "SoilGrids properties per block, wide"),
    "interim/real/06b_soilgrids_block_soil_long.csv": (REAL, "block × property × depth", "SoilGrids properties per block, long"),
    "interim/real/07_sl_tea_production_monthly_by_elevation_2021_2025.csv": (REAL, "month × elevation", "National production (Forbes & Walker)"),
    "interim/real/08_monthly_weather_vs_production_by_elevation.csv": (DER, "month × elevation zone", "Zone weather joined with national production"),
    "processed/hybrid/01_block_master.csv": (SIM, "block", "Static block features; soil from SoilGrids"),
    "processed/hybrid/02_weather_daily.csv": (REAL, "estate × day", "Daily ERA5 weather used by the simulation"),
    "processed/hybrid/03_sensor_readings_daily.csv": (SIM, "block × day", "Daily soil/light readings = the IoT / manual input form"),
    "processed/hybrid/04_yield_plucking_records.csv": (SIM, "block × plucking round", "Green-leaf harvest per round"),
    "processed/hybrid/05_intervention_records.csv": (SIM, "field action", "Every fertilizer, irrigation, fungicide and dolomite action"),
    "processed/hybrid/06_resource_usage_monthly.csv": (SIM, "estate × month × resource", "Allocated vs used inputs"),
    "processed/hybrid/07_operational_constraints.csv": (META, "rule", "Optimizer limits and scheduler rules"),
    "processed/hybrid/08_daily_forecasts_issued.csv": (REAL, "estate × day", "Rain forecast issued each morning, day 0-3"),
    "processed/hybrid/ml_yield_training.csv": (SIM, "block × plucking round", "Yield training table (source of yield_model_ready)"),
    "processed/hybrid/ml_runoff_training.csv": (SIM, "fertilizer application", "Runoff training table (source of runoff_model_ready)"),
    "model_ready/smarttea_master_block_daily.csv.gz": (DER, "block × day", "ALL sources joined: sensors + block + weather + forecast + actions + yield"),
    "model_ready/yield_model_ready.csv": (DER, "block × plucking round", "Feed-ready yield table: meta + target + numeric features"),
    "model_ready/runoff_model_ready.csv": (DER, "fertilizer application", "Feed-ready runoff table: meta + target + numeric features"),
}
ORIGIN = {  # per-column origin overrides inside simulated tables
    **{c: REAL for c in ["latitude", "longitude", "region", "weather_grid_elevation_m"] + [c for c in DESC if c.startswith("sg_")]},
    **{c: DER for c in ["field_capacity_pct", "wilting_point_pct", "soil_type", "temp_offset_c"]},
    **{c: REAL for c in DESC if c.startswith(("rain_next_", "fc_rain_", "wx_"))},
    **{c: DER for c in DESC if c.startswith(("start_rain", "start_temp", "start_et0", "clim_"))},  # from real ERA5
    "fc_rain_next4d_mm": REAL,
    **{c: DER for c in ["rain_sum_mm", "rain_days", "rain_30d_mm", "temp_mean_c", "temp_max_c", "humidity_mean",
                         "solar_rad_mean", "et0_sum_mm", "rain_prev_3d_mm", "temp_at_exec_c", "humidity_at_exec_pct", "temp_prev_day_c", "humidity_prev_day_pct",
                         "wind_at_exec_ms"]},  # weather features computed from real ERA5
    "forecast_source": META, "fc_source": META,
    **{c: META for c in ["row_id", "split", "cv_fold", "block_id", "estate_id", "intervention_id", "date", "year", "pluck_date",
                          "execution_datetime", "estate_name", "month"]},
}


def describe(col):
    if col in DESC:
        return DESC[col]
    m = re.match(r"^(phh2o|nitrogen|soc|clay|sand|silt|bdod|cec|cfvo)_(\d+)_(\d+)cm(_q05|_q95)?$", col)
    if m:
        unit, name = SOIL_PROP[m.group(1)]
        q = {"_q05": " (5 % quantile)", "_q95": " (95 % quantile)"}.get(m.group(4), " (mean)")
        return unit, f"SoilGrids {name}, {m.group(2)}-{m.group(3)} cm{q}"
    m = re.match(r"^hindsight__(.+)$", col)
    if m:
        u, d = DESC[m.group(1)]
        return u, d + " - NOT for live use"
    m = re.match(r"^(\w+?)__(.+)$", col)
    if m:
        return "0/1", f"One-hot: {m.group(1)} = {m.group(2)}"
    raise KeyError(f"no description for column {col!r}")


def profile(s):
    miss = s.isna().mean() * 100
    if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
        rng = f"{s.min():g} – {s.max():g}" if s.notna().any() else ""
        typ = "int" if pd.api.types.is_integer_dtype(s) else "float"
    else:
        lv = s.dropna().astype(str).unique()
        rng = ", ".join(sorted(lv)[:6]) + (f" … ({len(lv)} values)" if len(lv) > 6 else "")
        typ = "bool" if pd.api.types.is_bool_dtype(s) or set(lv) <= {"True", "False"} else "text"
    return typ, round(miss, 1), rng


def main():
    rows, md = [], []
    md += ["# SmartTea-LK C04: Data Dictionary", "",
           "Generated by `python -m src.data.make_data_dictionary` from the files themselves. "
           "Origin: **real** = downloaded observation/model data; **derived** = computed from real data; "
           "**simulated** = produced by the process model (`src/data/generate_hybrid.py`); **meta** = keys, splits, labels.", "",
           "One-hot columns (`name__level`) and SoilGrids wide columns (`property_depth[_q05|_q95]`) are summarised as one line each.", ""]
    for rel, (origin, grain, purpose) in TABLES.items():
        df = pd.read_csv(os.path.join(D, rel), low_memory=False)
        md += [f"## `data/{rel}`", "", f"{purpose}. Grain: one row per **{grain}**. Rows: **{len(df):,}**, columns: {df.shape[1]}. "
               f"Default origin: **{origin}**.", "",
               "| Column | Type | Unit | Origin | Description | Missing % | Range / levels |", "|---|---|---|---|---|---|---|"]
        seen_groups = set()
        for c in df.columns:
            unit, desc = describe(c)
            typ, miss, rng = profile(df[c])
            base = re.sub(r"^hindsight__", "", c).split("__")[0]
            if rel.startswith("model_ready/"):
                org = ORIGIN.get(base, SIM)  # model-ready columns inherit the origin of their source column
            elif origin == SIM:
                org = ORIGIN.get(base, SIM)
            else:
                org = META if base in ("row_id", "split", "cv_fold") else origin
            rows.append(dict(table=f"data/{rel}", column=c, type=typ, unit=unit, origin=org, description=desc,
                             missing_pct=miss, range_or_levels=rng))
            grp = re.match(r"^(\w+?)__", c) and not c.startswith("hindsight__") and c.split("__")[0]
            sgrp = re.match(r"^(phh2o|nitrogen|soc|clay|sand|silt|bdod|cec|cfvo)_\d", c) and c.split("_")[0]
            key = grp or sgrp
            if key:
                if key in seen_groups:
                    continue
                seen_groups.add(key)
                members = [k for k in df.columns if (k.startswith(key + "__") if grp else k.startswith(key + "_"))]
                label = f"`{key}__*` ({len(members)})" if grp else f"`{key}_*` ({len(members)})"
                desc = (f"One-hot of {key}: " + ", ".join(m.split('__', 1)[1] for m in members)) if grp else \
                       f"SoilGrids {SOIL_PROP[key][1]}: 3 depths × mean/q05/q95"
                md.append(f"| {label} | {'0/1' if grp else 'float'} | {'' if grp else SOIL_PROP[key][0]} | {org} | {desc} | "
                          f"{df[members].isna().mean().mean() * 100:.1f} | |")
                continue
            md.append(f"| `{c}` | {typ} | {unit} | {org} | {desc} | {miss} | {rng} |")
        md.append("")
    pd.DataFrame(rows).to_csv(os.path.join(D, "data_dictionary.csv"), index=False)
    with open(os.path.join(D, "DATA_DICTIONARY.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"documented {len(rows)} columns in {len(TABLES)} tables")


if __name__ == "__main__":
    main()
