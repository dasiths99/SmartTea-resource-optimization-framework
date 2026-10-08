"""Build the real data pack (data/interim/real, files 00-08) from the raw downloads in data/raw.

Replaces the older process_real.py / parse_forbes.py, which pointed at a cloud-sandbox path and needed
the external `pdftotext` tool. Everything here is pure Python.

Usage:
    python -m src.data.build_real --raw data/raw --out data/interim/real_rebuilt
"""
import argparse
import io
import json
import os
import re

import numpy as np
import pandas as pd

ESTATES = pd.DataFrame(
    [["E01", "Nuwara Eliya", "up", 6.97, 80.78], ["E02", "Hatton / Dimbula", "up", 6.89, 80.60],
     ["E03", "Kandy", "mid", 7.25, 80.65], ["E04", "Ratnapura", "low", 6.68, 80.40],
     ["E05", "Deniyaya / Matara", "low", 6.34, 80.56]],
    columns=["estate_id", "region", "agro_zone", "query_lat", "query_lon"])
ZONE_TO_ELEVATION = {"up": "high", "mid": "medium", "low": "low"}
MONTHS = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER",
          "OCTOBER", "NOVEMBER", "DECEMBER"]
SOIL_PROPERTIES = ["phh2o", "nitrogen", "soc", "clay", "sand", "silt", "bdod", "cec", "cfvo"]
SOIL_UNITS = {"bdod": "kg/dm3", "cec": "cmol(c)/kg", "cfvo": "cm3/100cm3", "clay": "%", "sand": "%",
              "silt": "%", "nitrogen": "g/kg (total N)", "phh2o": "pH (H2O)", "soc": "g/kg"}
HOURLY_RENAME = {
    "temperature_2m": "temp_c", "relative_humidity_2m": "humidity_pct", "dew_point_2m": "dew_point_c",
    "precipitation": "precip_mm", "rain": "rain_mm", "cloud_cover": "cloud_cover_pct",
    "wind_speed_10m": "wind_speed_10m_ms", "wind_gusts_10m": "wind_gust_10m_ms",
    "shortwave_radiation": "solar_radiation_wm2", "sunshine_duration": "sunshine_s",
    "et0_fao_evapotranspiration": "et0_mm", "vapour_pressure_deficit": "vpd_kpa",
    "soil_temperature_0_to_7cm": "soil_temp_0_7cm_c", "soil_moisture_0_to_7cm": "soil_moisture_0_7cm_pct",
    "soil_moisture_7_to_28cm": "soil_moisture_7_28cm_pct", "soil_moisture_28_to_100cm": "soil_moisture_28_100cm_pct"}


def weather(raw):
    """00 estate locations, 01 hourly ERA5, 02 daily ERA5."""
    h = pd.read_csv(f"{raw}/open_meteo/smarttea_openmeteo_era5_hourly_2021_2025.csv", parse_dates=["datetime_local"])
    for c in ["soil_moisture_0_to_7cm", "soil_moisture_7_to_28cm", "soil_moisture_28_to_100cm"]:
        h[c] = (h[c] * 100).round(1)  # m3/m3 -> %
    h = h.rename(columns=HOURLY_RENAME)
    grid = h.groupby("estate_id")[["grid_lat", "grid_lon", "grid_elevation_m"]].first().reset_index()
    h = h.drop(columns=["region", "grid_lat", "grid_lon", "grid_elevation_m"])

    h["date"] = h.datetime_local.dt.date
    g = h.groupby(["estate_id", "date"])
    d = pd.DataFrame({
        "rain_mm": g.precip_mm.sum().round(1), "rain_hours": g.precip_mm.apply(lambda s: (s >= 0.1).sum()),
        "temp_min_c": g.temp_c.min(), "temp_mean_c": g.temp_c.mean().round(1), "temp_max_c": g.temp_c.max(),
        "humidity_mean_pct": g.humidity_pct.mean().round(1), "humidity_min_pct": g.humidity_pct.min(),
        "cloud_cover_mean_pct": g.cloud_cover_pct.mean().round(1),
        "wind_mean_ms": g.wind_speed_10m_ms.mean().round(2), "wind_max_ms": g.wind_speed_10m_ms.max(),
        "gust_max_ms": g.wind_gust_10m_ms.max(),
        "solar_radiation_mj_m2": (g.solar_radiation_wm2.sum() * 3600 / 1e6).round(2),
        "sunshine_hours": (g.sunshine_s.sum() / 3600).round(2), "et0_mm": g.et0_mm.sum().round(2),
        "vpd_mean_kpa": g.vpd_kpa.mean().round(3), "soil_temp_0_7cm_c": g.soil_temp_0_7cm_c.mean().round(1),
        "soil_moisture_0_7cm_pct": g.soil_moisture_0_7cm_pct.mean().round(1),
        "soil_moisture_7_28cm_pct": g.soil_moisture_7_28cm_pct.mean().round(1),
        "soil_moisture_28_100cm_pct": g.soil_moisture_28_100cm_pct.mean().round(1),
    }).reset_index()
    h = h.drop(columns="date")
    est = ESTATES.merge(grid, on="estate_id")
    return est, h, d


def forecasts(raw, hourly):
    """03 hourly forecast vs actual, 04 daily totals (complete 24 h days only)."""
    fc = pd.read_csv(f"{raw}/open_meteo/smarttea_openmeteo_forecast_leadtimes_2024_2025.csv", parse_dates=["datetime_local"])
    act = hourly[["estate_id", "datetime_local", "precip_mm", "temp_c"]].rename(
        columns={"precip_mm": "precip_actual_mm", "temp_c": "temp_actual_c"})
    fc = fc.merge(act, on=["estate_id", "datetime_local"], how="left")
    fc = fc[["estate_id", "datetime_local", "precip_actual_mm", "precip_forecast_1day_ahead_mm",
             "precip_forecast_2day_ahead_mm", "precip_forecast_3day_ahead_mm", "precip_forecast_4day_ahead_mm",
             "temp_actual_c", "temp_forecast_1day_ahead_c", "wind_forecast_1day_ahead_ms"]]
    fc["date"] = fc.datetime_local.dt.date
    fd = fc.groupby(["estate_id", "date"]).agg(
        hours=("precip_actual_mm", "size"), rain_actual_mm=("precip_actual_mm", "sum"),
        **{f"rain_fc_{k}day_ahead_mm": (f"precip_forecast_{k}day_ahead_mm", "sum") for k in range(1, 5)}).reset_index()
    fd = fd[fd.hours == 24].drop(columns="hours").round(1)
    return fc.drop(columns="date"), fd


def nasa_power(raw):
    """05 NASA POWER daily (cross-check)."""
    js = json.load(open(f"{raw}/nasa_power/smarttea_nasa_power_daily_2021_2025.json"))
    parts = []
    for eid, text in js.items():
        df = pd.read_csv(io.StringIO(text.split("-END HEADER-")[1].strip()))
        df.insert(0, "estate_id", eid)
        parts.append(df)
    n = pd.concat(parts).replace(-999, np.nan)
    n.insert(1, "date", (pd.to_datetime(n.YEAR.astype(str), format="%Y") + pd.to_timedelta(n.DOY - 1, unit="D")).dt.date)
    return n.drop(columns=["YEAR", "DOY"]).rename(columns=str.lower)


def soilgrids(raw):
    """06 wide block soil table (masked blocks filled with the estate mean), 06b long table."""
    lg = pd.read_csv(f"{raw}/soilgrids/smarttea_soilgrids_blocks.csv", encoding="latin-1")
    lg["unit"] = lg.property.map(SOIL_UNITS)
    lg["_d"] = lg.depth.map({"0-5cm": 0, "5-15cm": 1, "15-30cm": 2})
    lg = lg.sort_values(["block_id", "_d", "property"]).drop(columns="_d").reset_index(drop=True)
    lg["estate_id"] = lg.block_id.str[:3]
    lg["dcol"] = lg.depth.str.replace("-", "_")
    w = lg.pivot_table(index="block_id", columns=["property", "dcol"], values=["mean", "q05", "q95"], dropna=False)
    cols = {}
    for p in SOIL_PROPERTIES:
        for stat, suffix in [("mean", ""), ("q05", "_q05"), ("q95", "_q95")]:
            for dc in sorted(lg.dcol.unique()):
                cols[f"{p}_{dc}{suffix}"] = w[(stat, p, dc)]
    wide = pd.DataFrame(cols)
    meta = lg.groupby("block_id")[["estate_id", "latitude", "longitude"]].first()
    meta[["latitude", "longitude"]] = meta[["latitude", "longitude"]].round(3)
    wide = meta.join(wide)
    masked = wide[list(cols)].isna().all(axis=1)
    est_mean = wide[~masked].groupby("estate_id")[list(cols)].mean().round(3)
    for b in wide.index[masked]:
        wide.loc[b, list(cols)] = est_mean.loc[wide.loc[b, "estate_id"]].values
    wide["values_filled_from_estate_mean"] = masked
    return wide.reset_index(), lg.drop(columns=["estate_id", "dcol"])


def production(raw):
    """07 national monthly production by elevation, parsed from the Forbes & Walker PDFs."""
    import pypdfium2 as pdfium
    rows = []
    for f in sorted(os.listdir(f"{raw}/forbes_walker")):
        if not f.endswith(".pdf"):
            continue
        y, m = f[:-4].split("-")
        y = int(y)
        pdf = pdfium.PdfDocument(f"{raw}/forbes_walker/{f}")
        text = "\n".join(pdf[i].get_textpage().get_text_range() for i in range(len(pdf)))
        for el in ["HIGH", "MEDIUM", "LOW", "GREEN TEA", "TOTAL"]:
            n = r"([\d,]+)(?:\.\d+)?"  # some reports print "3,359,406.00"
            mt = re.search(r"^\s*" + el + r"\s+" + n + r"\s+" + n + r"\s+\S+\s+\S+\s+" + n, text, re.M)
            if not mt:
                raise ValueError(f"{f}: no {el} row")
            cur, p1, p2 = (int(x.replace(",", "")) for x in mt.groups())
            for yy, v, lag in [(y, cur, 0), (y - 1, p1, 1), (y - 2, p2, 2)]:
                rows.append(dict(year=yy, month=MONTHS.index(m) + 1, elevation=el.lower().replace(" ", "_"),
                                 production_kg=v, source_report=f"{m.title()} {y}", lag=lag))
    df = pd.DataFrame(rows)
    # each month appears in up to three reports (that year, +1, +2); keep the newest = latest revised figure
    df = df.sort_values("lag", ascending=False, kind="stable").drop_duplicates(["year", "month", "elevation"], keep="first")
    df = df[df.year.between(2021, 2025)].sort_values(["year", "month", "elevation"]).drop(columns="lag")
    return df.reset_index(drop=True)


def monthly_zone(daily, prod):
    """08 monthly weather per elevation zone (mean over the zone's estates) joined with national production."""
    d = daily.copy()
    d["date"] = pd.to_datetime(d.date)
    d["year"], d["month"] = d.date.dt.year, d.date.dt.month
    d["elevation"] = d.estate_id.map(ESTATES.set_index("estate_id").agro_zone).map(ZONE_TO_ELEVATION)
    per_est = d.groupby(["elevation", "estate_id", "year", "month"]).agg(
        rain_mm=("rain_mm", "sum"), rain_days=("rain_mm", lambda s: (s >= 1).sum()),
        temp_mean_c=("temp_mean_c", "mean"), temp_max_c=("temp_max_c", "mean"),
        humidity_pct=("humidity_mean_pct", "mean"), solar_mj_m2_day=("solar_radiation_mj_m2", "mean"),
        sunshine_h_day=("sunshine_hours", "mean"), et0_mm=("et0_mm", "sum"),
        soil_moisture_7_28cm_pct=("soil_moisture_7_28cm_pct", "mean"), vpd_kpa=("vpd_mean_kpa", "mean"))
    m = per_est.groupby(["elevation", "year", "month"]).mean().reset_index()
    m = m.sort_values(["elevation", "year", "month"])
    m["rain_prev_month_mm"] = m.groupby("elevation").rain_mm.shift(1)
    m["rain_prev_3m_mm"] = m.groupby("elevation").rain_mm.transform(lambda s: s.shift(1).rolling(3).sum())
    m = m.merge(prod[["year", "month", "elevation", "production_kg"]], on=["elevation", "year", "month"])
    m["days_in_month"] = pd.to_datetime(dict(year=m.year, month=m.month, day=1)).dt.days_in_month
    m["production_kg_per_day"] = (m.production_kg / m.days_in_month).round(0)
    num = m.columns.difference(["elevation", "year", "month", "production_kg", "days_in_month"])
    m[num] = m[num].round(2)
    return m.reset_index(drop=True)


def verify_raw(raw):
    """Stop if any raw file is missing or differs from the checksum recorded in data/raw/MANIFEST.csv."""
    import hashlib
    man = pd.read_csv(os.path.join(raw, "MANIFEST.csv"))
    bad = [r.file for r in man.itertuples() if not os.path.exists(os.path.join(raw, r.file))
           or hashlib.sha256(open(os.path.join(raw, r.file), "rb").read()).hexdigest() != r.sha256]
    if bad:
        raise SystemExit(f"raw files missing or changed since download: {bad}")
    print(f"raw data verified: {len(man)} files match MANIFEST.csv checksums")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="data/interim/real_rebuilt")
    a = ap.parse_args()
    verify_raw(a.raw)
    os.makedirs(a.out, exist_ok=True)
    est, hourly, daily = weather(a.raw)
    fc_h, fc_d = forecasts(a.raw, hourly)
    soil_w, soil_l = soilgrids(a.raw)
    prod = production(a.raw)
    tables = {
        "00_estate_locations.csv": est, "01_weather_hourly_era5_2021_2025.csv": hourly,
        "02_weather_daily_era5_2021_2025.csv": daily, "03_forecast_vs_actual_hourly_2024_2025.csv": fc_h,
        "04_forecast_vs_actual_daily_2024_2025.csv": fc_d, "05_nasa_power_daily_2021_2025.csv": nasa_power(a.raw),
        "06_soilgrids_block_soil_properties.csv": soil_w, "06b_soilgrids_block_soil_long.csv": soil_l,
        "07_sl_tea_production_monthly_by_elevation_2021_2025.csv": prod,
        "08_monthly_weather_vs_production_by_elevation.csv": monthly_zone(daily, prod),
    }
    for name, df in tables.items():
        df.to_csv(os.path.join(a.out, name), index=False)
        print(f"{name:58s} {len(df):>8,} rows")


if __name__ == "__main__":
    main()
