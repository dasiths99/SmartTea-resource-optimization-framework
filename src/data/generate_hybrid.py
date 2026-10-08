#!/usr/bin/env python3
"""
SmartTea-LK  |  Component 04  |  Synthetic dataset generator
=============================================================

Simulates tea blocks in Sri Lanka day by day and writes linked CSV
datasets for training the Component 04 models (yield surrogate,
runoff/efficiency model, NSGA-II constraints, Action-Window scheduler).

The data is SYNTHETIC. A process model links weather, soil water, soil
nutrients, pH, light, pruning, disease and field interventions to tea growth, so the
ML models have real cause-and-effect to learn:

  * rain soon after fertilizer  -> more runoff -> less N absorbed -> lower yield later
  * dry soil                    -> water stress -> lower growth
  * more N                      -> higher growth, with diminishing returns
  * low / high pH               -> growth penalty; N fertilizer slowly acidifies soil
  * wet, cloudy spells (up/mid) -> blister-blight loss unless fungicide is sprayed
  * pruning                     -> no harvest for ~2 months, then recovery

All agronomic numbers are approximate defaults, kept in the CONFIG section
so they can be calibrated against Tea Research Institute (TRI) guidance
or real estate records.

Usage:
    python generate_smarttea_data.py --out ./data --seed 42
    python generate_smarttea_data.py --blocks-per-estate 16 --start 2020-01-01 --end 2025-12-31
"""
import argparse
import os
import zlib

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
ESTATES = [
    # id,   name,                        zone,  region,                 lat,   lon,   elev range (m)
    ("E01", "Estate A (Up-country)",     "up",  "Nuwara Eliya",         6.97, 80.78, (1600, 2100)),
    ("E02", "Estate B (Up-country)",     "up",  "Hatton / Dimbula",     6.89, 80.60, (1250, 1700)),
    ("E03", "Estate C (Mid-country)",    "mid", "Kandy",                7.25, 80.65, (650, 1150)),
    ("E04", "Estate D (Low-country)",    "low", "Ratnapura",            6.68, 80.40, (80, 450)),
    ("E05", "Estate E (Low-country)",    "low", "Deniyaya / Matara",    6.34, 80.56, (250, 590)),
]

# Mean monthly rainfall (mm), Jan..Dec - approximate wet-zone climatology
MONTHLY_RAIN = {
    "up":  [120, 80, 90, 170, 200, 280, 280, 220, 200, 250, 230, 170],   # ~2,290 mm/yr
    "mid": [120, 80, 110, 200, 150, 140, 130, 110, 150, 300, 280, 200],  # ~1,970 mm/yr
    "low": [150, 140, 220, 330, 450, 380, 300, 260, 350, 420, 340, 200], # ~3,540 mm/yr
}
SW_MONSOON = {5, 6, 7, 8, 9}
NE_MONSOON = {12, 1, 2}

# Target mean annual GREEN LEAF yield (kg/ha/yr) per zone, across all blocks
ZONE_YIELD_TARGET = {"up": 7000, "mid": 6000, "low": 9500}
PLUCK_INTERVAL = {"up": (10, 14), "mid": (8, 12), "low": (6, 9)}
PRUNE_CYCLE_YRS = {"up": (4, 5), "mid": (3, 4), "low": (2, 3)}

SOILS = {
    # name: (field capacity %, wilting point %)
    "Red-Yellow Podzolic":       (38.0, 14.0),
    "Reddish Brown Latosolic":   (35.0, 13.0),
    "Immature Brown Loam":       (41.0, 15.0),
}

FERTILIZERS = {
    # code: (N %, P %, K %, description)
    "NPK_HN":  (0.27, 0.05, 0.14, "High-N tea mixture"),
    "NPK_BAL": (0.21, 0.08, 0.18, "Balanced NPK tea mixture"),
    "UREA":    (0.46, 0.00, 0.00, "Urea (straight N)"),
}
FERT_SCHEDULE_MONTHS = {"up": [3, 6, 10], "mid": [3, 6, 10], "low": [2, 5, 8, 11]}
FERT_BASE_KG_HA = {"up": 280, "mid": 260, "low": 240}     # mixture kg/ha per application

ROOT_ZONE_MM = 400.0      # effective root-zone depth (mm)
KG_HA_PER_PPM = 2.0       # ~kg/ha of nutrient per 1 ppm in 0-15 cm topsoil

START, END = "2021-01-01", "2025-12-31"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def clip(x, lo, hi):
    return max(lo, min(hi, x))


def hourly_profile(rng, month, n_days):
    """Random 24-h rainfall distribution for each day.
    Inter-monsoon months: afternoon convective peak. Monsoon months: spread out."""
    h = np.arange(24)
    if month in SW_MONSOON or month in NE_MONSOON:
        base = 1.0 + 0.4 * np.exp(-((h - 16) ** 2) / 30) + 0.3 * np.exp(-((h - 3) ** 2) / 20)
    else:
        base = 0.15 + 2.5 * np.exp(-((h - 16) ** 2) / 8)
    base = base / base.sum()
    return rng.dirichlet(base * 8 + 1e-3, size=n_days)


# ---------------------------------------------------------------------------
# 1. Weather (daily per estate, plus hourly rainfall profiles)
# ---------------------------------------------------------------------------
def generate_weather(rng, dates):
    rows, hourly = [], {}
    n = len(dates)
    years = sorted(set(dates.year))
    for est_id, _, zone, _, lat, lon, (e_lo, e_hi) in ESTATES:
        station_elev = (e_lo + e_hi) / 2
        year_factor = {y: clip(rng.normal(1.0, 0.13), 0.7, 1.3) for y in years}
        wet_prev = False
        t_anom = 0.0
        prof = np.zeros((n, 24))
        for i, d in enumerate(dates):
            m = d.month
            mean_month = MONTHLY_RAIN[zone][m - 1] * year_factor[d.year]
            p = clip(0.22 + mean_month / 550, 0.22, 0.88)
            r = 0.35
            p_wet = p + r * (1 - p) if wet_prev else p * (1 - r)
            wet = rng.random() < p_wet
            rain = 0.0
            if wet:
                mean_wet = mean_month / (d.days_in_month * p)
                rain = rng.gamma(0.8, mean_wet / 0.8)
                rain = min(rain, 280.0)
                if rain < 0.3:
                    rain, wet = 0.0, False
            wet_prev = wet

            seasonal_t = 1.0 * np.cos(2 * np.pi * (d.dayofyear - 120) / 365)
            t_anom = 0.7 * t_anom + rng.normal(0, 0.55)
            t_mean = 27.8 - 0.0062 * station_elev + seasonal_t + t_anom - (0.7 if rain > 5 else 0)
            dtr = {"up": 9.0, "mid": 8.0, "low": 7.0}[zone] - (2.5 if rain > 5 else 0) + rng.normal(0, 0.8)
            dtr = clip(dtr, 3.0, 13.0)

            ra = 34.5 + 2.0 * np.cos(2 * np.pi * (d.dayofyear - 80) / 365)  # extraterrestrial MJ/m2/d
            cloud = (0.82 + rng.normal(0, 0.06)) if rain < 1 else clip(0.68 - rain / 150 + rng.normal(0, 0.08), 0.28, 0.75)
            if zone == "up":
                cloud *= 0.93
            rs = clip(0.75 * ra * cloud, 4.0, 27.0)
            sun_hrs = clip(((rs / ra) - 0.25) / 0.5 * 12.0, 0.0, 11.5)

            rh_base = {"up": 80, "mid": 76, "low": 79}[zone]
            rh = clip(rh_base + (9 if rain > 1 else -2) + min(rain, 40) / 8 + rng.normal(0, 3.5), 50, 99)
            wind = {"up": 3.2, "mid": 2.4, "low": 1.8}[zone]
            if m in SW_MONSOON and zone in ("up", "mid"):
                wind += 2.0
            wind = clip(wind * rng.gamma(4, 0.25), 0.2, 15.0)

            et0 = 0.0135 * (t_mean + 17.8) * rs * 0.408
            et0 = max(0.5, et0 * (1 - (rh - 75) / 200))

            rows.append(dict(
                estate_id=est_id, date=d.date(), rainfall_mm=round(rain, 1),
                temp_min_c=round(t_mean - dtr / 2, 1), temp_mean_c=round(t_mean, 1),
                temp_max_c=round(t_mean + dtr / 2, 1), humidity_pct=round(rh, 1),
                wind_speed_ms=round(wind, 1), solar_radiation_mj_m2=round(rs, 2),
                sunshine_hours=round(sun_hrs, 1), et0_mm=round(et0, 2),
            ))
        # hourly rainfall profiles (month-dependent)
        for i, d in enumerate(dates):
            prof[i] = hourly_profile(rng, d.month, 1)[0]
        hourly[est_id] = prof
    wdf = pd.DataFrame(rows)
    return wdf, hourly


def rain_window(rain, prof, i, hour, hours):
    """Rain (mm) falling in [day i, hour] .. +hours, using hourly profiles."""
    total, n = 0.0, len(rain)
    h_left, day, h = hours, i, hour
    while h_left > 0 and day < n:
        take = min(24 - h, h_left)
        total += rain[day] * prof[day, h:h + take].sum()
        h_left -= take
        day, h = day + 1, 0
    return total


# ---------------------------------------------------------------------------
# 2. Block master
# ---------------------------------------------------------------------------
def generate_blocks(rng, blocks_per_estate, start_date):
    rows = []
    for est_id, est_name, zone, region, lat, lon, (e_lo, e_hi) in ESTATES:
        for b in range(1, blocks_per_estate + 1):
            bid = f"{est_id}-B{b:02d}"
            soil = rng.choice(list(SOILS), p=[0.6, 0.25, 0.15])
            cultivar = rng.choice(["VP_clone_A", "VP_clone_B", "VP_clone_C", "Seedling"], p=[0.3, 0.25, 0.2, 0.25])
            age = int(rng.choice([rng.integers(2, 6), rng.integers(6, 30), rng.integers(30, 70)], p=[0.15, 0.55, 0.30]))
            cyc = int(rng.integers(PRUNE_CYCLE_YRS[zone][0], PRUNE_CYCLE_YRS[zone][1] + 1))
            last_prune = pd.Timestamp(start_date) - pd.Timedelta(days=int(rng.integers(30, cyc * 365)))
            irrig = bool(age < 6 or rng.random() < 0.12)
            rows.append(dict(
                block_id=bid, estate_id=est_id, estate_name=est_name, agro_zone=zone,
                region=region,
                latitude=round(lat + rng.normal(0, 0.01), 4), longitude=round(lon + rng.normal(0, 0.01), 4),
                area_ha=round(float(rng.uniform(3, 25)), 1),
                elevation_m=int(rng.integers(e_lo, e_hi)),
                slope_pct=round(float(rng.uniform(5, 45)), 1),
                aspect=rng.choice(["N", "NE", "E", "SE", "S", "SW", "W", "NW"]),
                soil_type=soil, field_capacity_pct=SOILS[soil][0], wilting_point_pct=SOILS[soil][1],
                cultivar=cultivar, bush_age_yrs=age,
                shade_tree_cover_pct=int(rng.choice([0, 10, 20, 30, 40], p=[0.15, 0.25, 0.3, 0.2, 0.1])),
                pruning_cycle_yrs=cyc, last_pruning_date_before_2021=last_prune.date(),
                irrigation_available=irrig,
                mgmt_intensity=round(float(rng.uniform(0.7, 1.3)), 2),  # hidden-ish driver of dose variation
            ))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 3. Process model per block
# ---------------------------------------------------------------------------
def f_temp(t):
    if t < 12:
        return 0.2
    if t < 18:
        return 0.2 + 0.8 * (t - 12) / 6
    if t <= 26:
        return 1.0
    if t <= 32:
        return 1.0 - 0.5 * (t - 26) / 6
    return 0.5


def f_ph(ph):
    if ph < 4.2:
        return clip(0.8 - (4.2 - ph) * 0.5, 0.5, 0.8)
    if ph < 4.5:
        return 0.8 + (ph - 4.2) / 0.3 * 0.2
    if ph <= 5.5:
        return 1.0
    if ph <= 6.0:
        return 1.0 - (ph - 5.5) * 0.3
    return 0.85


def f_prune(days):
    if days < 45:
        return 0.0
    if days < 90:
        return 0.35
    if days < 180:
        return 0.75
    if days < 365:
        return 0.95
    if days < 730:
        return 1.05
    return clip(1.05 - 0.04 * (days - 730) / 365, 0.85, 1.05)


def simulate_block(rng, blk, w, prof, dates, scale):
    n = len(dates)
    zone = blk.agro_zone
    fc, wp = blk.field_capacity_pct, blk.wilting_point_pct
    rain = w["rainfall_mm"].values
    tmean = w["temp_mean_c"].values + float(getattr(blk, "temp_offset_c", 0.0) or 0.0)
    rs = w["solar_radiation_mj_m2"].values
    sun = w["sunshine_hours"].values
    et0 = w["et0_mm"].values
    wind = w["wind_speed_ms"].values
    rh = w["humidity_pct"].values

    age_f = clip(0.55 + 0.08 * blk.bush_age_yrs, 0.55, 1.0) if blk.bush_age_yrs < 6 else (0.88 if blk.bush_age_yrs > 50 else 1.0)
    cult_f = 0.78 if blk.cultivar == "Seedling" else {"VP_clone_A": 1.0, "VP_clone_B": 0.95, "VP_clone_C": 1.05}[blk.cultivar]
    shade = blk.shade_tree_cover_pct / 100

    # initial state
    sm = clip(rng.normal((fc + wp) / 2 + 5, 3), wp + 2, fc)
    ph = clip(rng.normal(4.9, 0.35), 4.1, 5.9)
    soil_n = rng.uniform(35, 80)
    if pd.notna(getattr(blk, "init_ph", np.nan)):          # hybrid mode: real SoilGrids start values
        ph = clip(rng.normal(blk.init_ph, 0.08), 4.1, 6.2)
    if pd.notna(getattr(blk, "init_soil_n_ppm", np.nan)):
        soil_n = clip(rng.normal(blk.init_soil_n_ppm, 4), 10, 120)
    n_mineral = float(getattr(blk, "n_mineralization_ppm_day", 0.10) or 0.10)
    soil_p = rng.uniform(8, 30)
    soil_k = rng.uniform(70, 180)
    soil_t = tmean[0] - 1
    env_ewma = 0.8
    blight_s = 0.0
    last_prune = pd.Timestamp(blk.last_pruning_date_before_2021)
    prune_days_cycle = blk.pruning_cycle_yrs * 365 + int(rng.integers(-40, 40))
    last_fert, last_spray, last_dolo, last_irrig = None, None, None, None
    spray_protect = 0.0
    ph_boost_days, ph_boost_rate = 0, 0.0
    sensor_ph_hist = []

    # fertilizer plan for the period (static calendar + jitter)
    plan = {}
    for y in sorted(set(dates.year)):
        for m in FERT_SCHEDULE_MONTHS[zone]:
            day = pd.Timestamp(year=y, month=m, day=1) + pd.Timedelta(days=int(rng.integers(0, 27)))
            plan[day.normalize()] = True

    sensor_rows, events, daily_growth, prune_days_arr = [], [], np.zeros(n), np.zeros(n, dtype=int)
    pending_fert = False

    for i, d in enumerate(dates):
        # pruning event
        if (d - last_prune).days >= prune_days_cycle:
            last_prune = d
            prune_days_cycle = blk.pruning_cycle_yrs * 365 + int(rng.integers(-40, 40))
        dsp = (d - last_prune).days
        prune_days_arr[i] = dsp

        # ---- sensor reading 08:00 (true state + noise) ----
        s = dict(
            block_id=blk.block_id, date=d.date(),
            soil_moisture_pct=round(sm + rng.normal(0, 1.2), 1),
            soil_ph=round(ph + rng.normal(0, 0.07), 2),
            soil_n_ppm=round(max(1, soil_n * rng.normal(1, 0.07)), 1),
            soil_p_ppm=round(max(1, soil_p * rng.normal(1, 0.08)), 1),
            soil_k_ppm=round(max(5, soil_k * rng.normal(1, 0.07)), 1),
            soil_temp_c=round(soil_t + rng.normal(0, 0.4), 1),
            light_lux=int(max(500, rs[i] * 1e6 / 43200 * 120 * (1 - shade * 0.7) * rng.normal(1, 0.06))),
            sunshine_hours=round(clip(sun[i] + rng.normal(0, 0.4), 0, 12), 1),
        )
        sensor_ph_hist.append(s["soil_ph"])

        # ---- management decisions (historical practice) ----
        today = []
        if d.normalize() in plan:
            pending_fert = True
        if pending_fert and dsp >= 30:
            if rain[i] > 30 and rng.random() < 0.8:       # managers usually avoid a downpour day
                pass
            else:
                pending_fert = False
                code = rng.choice(list(FERTILIZERS), p=[0.5, 0.35, 0.15])
                npct, ppct, kpct, desc = FERTILIZERS[code]
                kg = FERT_BASE_KG_HA[zone] * blk.mgmt_intensity * rng.normal(1, 0.12)
                if code == "UREA":
                    kg *= 0.55
                kg = clip(kg, 60, 420)
                hour = int(rng.integers(6, 16))
                r12 = rain_window(rain, prof, i, hour, 12)
                r24 = rain_window(rain, prof, i, hour, 24)
                r48 = rain_window(rain, prof, i, hour, 48)
                r72 = rain_window(rain, prof, i, hour, 72)
                rain_eff = r12 + 0.5 * (r48 - r12) + 0.2 * (r72 - r48)
                loss = 0.04 + 0.62 * (1 - np.exp(-rain_eff / 40)) * (0.7 + blk.slope_pct / 40)
                loss += 0.10 * clip((sm - fc + 3) / 6, 0, 1)                       # saturated soil
                dry_thr = wp + 0.25 * (fc - wp)
                loss += 0.08 * clip((dry_thr - sm) / 6, 0, 1) * (1.5 if code == "UREA" else 1)  # dry: volatilisation
                if 11 <= hour <= 15 and tmean[i] > 25:
                    loss += 0.02
                loss = clip(loss + rng.normal(0, 0.03), 0.02, 0.9)
                n_kg, p_kg, k_kg = kg * npct, kg * ppct, kg * kpct
                soil_n += n_kg * (1 - loss) / KG_HA_PER_PPM * 0.7
                soil_p += p_kg * (1 - loss) / KG_HA_PER_PPM * 0.25
                soil_k += k_kg * (1 - loss) / KG_HA_PER_PPM * 0.5
                ph -= 0.0004 * n_kg
                last_fert = d
                today.append(dict(
                    intervention_type="fertilizer", product_code=code, product_desc=desc,
                    amount_per_ha=round(kg, 1), unit="kg/ha", n_kg_per_ha=round(n_kg, 1),
                    p_kg_per_ha=round(p_kg, 1), k_kg_per_ha=round(k_kg, 1),
                    application_method="broadcast", hour=hour,
                    rain_next_12h_mm=round(r12, 1), rain_next_24h_mm=round(r24, 1),
                    rain_next_48h_mm=round(r48, 1), rain_next_72h_mm=round(r72, 1),
                    _true_loss=loss,
                ))

        # irrigation (only blocks with irrigation)
        if blk.irrigation_available and s["soil_moisture_pct"] < wp + 0.35 * (fc - wp):
            nxt = rain[i:i + 2].sum()
            if nxt < 5 and (last_irrig is None or (d - last_irrig).days >= 3):
                mm = clip(rng.normal(15, 4), 6, 25)
                sm += mm * 0.85 / ROOT_ZONE_MM * 100
                last_irrig = d
                hour = int(rng.choice([6, 7, 16, 17]))
                today.append(dict(
                    intervention_type="irrigation", product_code="WATER", product_desc="Sprinkler irrigation",
                    amount_per_ha=round(mm * 10000, 0), unit="L/ha", application_method="sprinkler",
                    hour=hour, irrigation_mm=round(mm, 1),
                    rain_next_12h_mm=round(rain_window(rain, prof, i, hour, 12), 1),
                    rain_next_24h_mm=round(rain_window(rain, prof, i, hour, 24), 1),
                    rain_next_48h_mm=round(rain_window(rain, prof, i, hour, 48), 1),
                    rain_next_72h_mm=round(rain_window(rain, prof, i, hour, 72), 1),
                ))

        # dolomite (pH correction), checked on 1st of month
        if d.day == 1 and len(sensor_ph_hist) >= 30 and np.mean(sensor_ph_hist[-30:]) < 4.45 \
                and (last_dolo is None or (d - last_dolo).days > 730) and rain[i] < 20:
            kg = clip(rng.normal(1250, 200), 800, 2000)
            ph_boost_days, ph_boost_rate = 90, (0.2 + kg / 5000) / 90
            last_dolo = d
            hour = int(rng.integers(7, 15))
            today.append(dict(
                intervention_type="dolomite", product_code="DOLOMITE", product_desc="Dolomite (pH correction)",
                amount_per_ha=round(kg, 0), unit="kg/ha", application_method="broadcast", hour=hour,
                rain_next_12h_mm=round(rain_window(rain, prof, i, hour, 12), 1),
                rain_next_24h_mm=round(rain_window(rain, prof, i, hour, 24), 1),
                rain_next_48h_mm=round(rain_window(rain, prof, i, hour, 48), 1),
                rain_next_72h_mm=round(rain_window(rain, prof, i, hour, 72), 1),
            ))

        # blister blight risk (elevation > 600 m) and fungicide
        if blk.elevation_m > 600 and i >= 5:
            wet5 = (rain[i - 5:i] > 1).sum() / 5
            sun5 = sun[i - 5:i].mean()
            risk = clip(wet5 * (1 - min(sun5, 6) / 6) * 1.7 * (0.8 + rh[i] / 500), 0, 1)
        else:
            risk = 0.0
        blight_s = 0.8 * blight_s + 0.2 * risk
        if blight_s > 0.35 and (last_spray is None or (d - last_spray).days >= 7) and rng.random() < 0.55 \
                and dsp >= 60:
            hour = int(rng.integers(7, 12))
            r4 = rain_window(rain, prof, i, hour, 4)
            washed = r4 > 8
            spray_protect = 0.3 if washed else 0.75
            last_spray = d
            today.append(dict(
                intervention_type="fungicide", product_code="FUNG_CU", product_desc="Copper-based fungicide (blister blight)",
                amount_per_ha=round(clip(rng.normal(1200, 150), 800, 1600), 0), unit="ml/ha",
                application_method="knapsack spray", hour=hour,
                rain_next_4h_mm=round(r4, 1),
                rain_next_12h_mm=round(rain_window(rain, prof, i, hour, 12), 1),
                rain_next_24h_mm=round(rain_window(rain, prof, i, hour, 24), 1),
                rain_next_48h_mm=round(rain_window(rain, prof, i, hour, 48), 1),
                rain_next_72h_mm=round(rain_window(rain, prof, i, hour, 72), 1),
                wind_at_exec_ms=round(clip(wind[i] * rng.normal(0.8, 0.2), 0.1, 15), 1),
                _washed_off=washed,
            ))
        if last_spray is not None and (d - last_spray).days > 10:
            spray_protect = 0.0

        for e in today:
            e.update(block_id=blk.block_id, estate_id=blk.estate_id, date=d.date(),
                     soil_moisture_at_exec=s["soil_moisture_pct"], soil_ph_at_exec=s["soil_ph"],
                     temp_at_exec_c=float(tmean[i]), humidity_at_exec_pct=float(rh[i]),
                     rain_prev_3d_mm=round(float(rain[max(0, i - 3):i].sum()), 1))
            events.append(e)

        # ---- soil water balance ----
        infil_cap = 60 * (1 - blk.slope_pct / 100)
        infil = min(rain[i] * 0.9, infil_cap + 0.4 * max(0, rain[i] - infil_cap))
        sm += infil / ROOT_ZONE_MM * 100
        ks = clip((sm - wp) / (0.6 * (fc - wp)), 0, 1)
        sm -= et0[i] * 0.9 * ks / ROOT_ZONE_MM * 100
        if sm > fc:
            sm -= 0.5 * (sm - fc)
        sm = clip(sm, wp - 1, fc + 6)
        soil_t = 0.7 * soil_t + 0.3 * (tmean[i] - 1.0 - shade * 1.5)

        # ---- growth ----
        f_w = clip((sm - wp) / (0.45 * (fc - wp)), 0.15, 1.0)
        if sm > fc + 2:
            f_w *= 0.92
        f_l = 0.7 + 0.3 * min(1.0, rs[i] * (1 - shade * 0.6) / 15)
        f_n = 0.5 + 0.5 * (1 - np.exp(-soil_n / 30))
        if soil_n > 150:
            f_n -= 0.002 * (soil_n - 150)
        f_k = 0.88 + 0.12 * (1 - np.exp(-soil_k / 70))
        f_p = 0.95 + 0.05 * (1 - np.exp(-soil_p / 10))
        env = f_temp(tmean[i]) * f_w * f_l * f_n * f_k * f_p * f_ph(ph)
        env_ewma = 0.75 * env_ewma + 0.25 * env
        blight_loss = 0.30 * blight_s * (1 - spray_protect)
        g = scale * age_f * cult_f * env_ewma * f_prune(dsp) * (1 - blight_loss) * np.exp(rng.normal(0, 0.08))
        daily_growth[i] = g

        # ---- nutrient & pH dynamics ----
        g_rel = g / scale
        soil_n += n_mineral - g_rel * 0.45 - soil_n * 0.0025 * min(rain[i] / 20, 3) - soil_n * 0.0015
        soil_n = max(soil_n, 3)
        soil_p += 0.01 - g_rel * 0.03 - soil_p * 0.0003
        soil_p = max(soil_p, 2)
        soil_k += 0.05 - g_rel * 0.22 - soil_k * 0.0008 * min(rain[i] / 20, 3)
        soil_k = max(soil_k, 20)
        if ph_boost_days > 0:
            ph += ph_boost_rate
            ph_boost_days -= 1
        ph = clip(ph + rng.normal(0, 0.002), 3.8, 6.3)

        sensor_rows.append(s)

    return sensor_rows, events, daily_growth, prune_days_arr


def make_plucking(rng, blk, dates, growth, prune_days):
    zone = blk.agro_zone
    rows, acc, last = [], 0.0, None
    nxt = int(rng.integers(0, PLUCK_INTERVAL[zone][1]))
    for i, d in enumerate(dates):
        acc += growth[i]
        if prune_days[i] < 60:            # bush not in plucking yet: growth goes to frame
            acc, last = 0.0, None
            nxt = i + int(rng.integers(*PLUCK_INTERVAL[zone]))
            continue
        if i >= nxt:
            std = rng.choice(["fine", "medium", "coarse"], p=[0.3, 0.5, 0.2])
            eff = {"fine": 0.88, "medium": 0.97, "coarse": 1.06}[std]
            kg_ha = acc * eff * rng.normal(1, 0.04)
            rows.append(dict(
                block_id=blk.block_id, estate_id=blk.estate_id, pluck_date=d.date(),
                round_days=(i - last) if last is not None else None,
                plucking_standard=std,
                green_leaf_kg_per_ha=round(kg_ha, 1),
                green_leaf_kg=round(kg_ha * blk.area_ha, 1),
                days_since_pruning=int(prune_days[i]),
            ))
            acc, last = 0.0, i
            nxt = i + int(rng.integers(PLUCK_INTERVAL[zone][0], PLUCK_INTERVAL[zone][1] + 1))
    df = pd.DataFrame(rows)
    df = df[df["round_days"].notna()].copy()
    df["round_days"] = df["round_days"].astype(int)
    df["green_leaf_kg_per_ha_per_day"] = (df["green_leaf_kg_per_ha"] / df["round_days"]).round(2)
    return df



# ---------------------------------------------------------------------------
# HYBRID MODE: real Sri Lanka data (weather, rain timing, soil, forecasts)
# ---------------------------------------------------------------------------
def load_real_weather(real_dir, dates):
    """Real daily ERA5 weather + real hourly rain timing per estate (Open-Meteo)."""
    d = pd.read_csv(os.path.join(real_dir, "02_weather_daily_era5_2021_2025.csv"), parse_dates=["date"])
    d = d[(d.date >= dates[0]) & (d.date <= dates[-1])]
    w = pd.DataFrame({
        "estate_id": d.estate_id, "date": d.date.dt.date, "rainfall_mm": d.rain_mm,
        "temp_min_c": d.temp_min_c, "temp_mean_c": d.temp_mean_c, "temp_max_c": d.temp_max_c,
        "humidity_pct": d.humidity_mean_pct, "wind_speed_ms": d.wind_mean_ms,
        "solar_radiation_mj_m2": d.solar_radiation_mj_m2,
        # ERA5 sunshine duration over-states bright sunshine in the hills; derive sunshine hours from
        # real radiation with the Angstrom relation instead (raw ERA5 value kept for reference)
        "sunshine_hours": (((d.solar_radiation_mj_m2 / (34.5 + 2.0 * np.cos(2 * np.pi * (d.date.dt.dayofyear - 80) / 365))) - 0.25)
                           / 0.5 * 12).clip(0, 11.5).round(1),
        "era5_sunshine_hours_raw": d.sunshine_hours,
        "et0_mm": d.et0_mm, "era5_soil_moisture_7_28cm_pct": d.soil_moisture_7_28cm_pct,
        "source": "ERA5 via Open-Meteo (real)",
    }).reset_index(drop=True)
    n_exp = len(dates)
    for e in w.estate_id.unique():
        assert (w.estate_id == e).sum() == n_exp, f"real weather for {e} does not cover {dates[0].date()}..{dates[-1].date()}"
    h = pd.read_csv(os.path.join(real_dir, "01_weather_hourly_era5_2021_2025.csv"),
                    usecols=["estate_id", "datetime_local", "precip_mm"], parse_dates=["datetime_local"])
    h = h[(h.datetime_local >= dates[0]) & (h.datetime_local < dates[-1] + pd.Timedelta(days=1))]
    hourly = {}
    for e, g in h.groupby("estate_id"):
        arr = g.sort_values("datetime_local").precip_mm.values.reshape(-1, 24)
        tot = arr.sum(axis=1, keepdims=True)
        prof = np.where(tot > 0, arr / np.where(tot > 0, tot, 1), 1 / 24)
        hourly[e] = prof
    loc = pd.read_csv(os.path.join(real_dir, "00_estate_locations.csv")).set_index("estate_id")
    return w, hourly, loc["grid_elevation_m"].to_dict()


def saxton_rawls(sand_pct, clay_pct, om_pct):
    """Field capacity / wilting point (% vol) from texture - Saxton & Rawls (2006)."""
    S, C, OM = sand_pct / 100, clay_pct / 100, min(om_pct, 8.0)
    t33 = -0.251 * S + 0.195 * C + 0.011 * OM + 0.006 * S * OM - 0.027 * C * OM + 0.452 * S * C + 0.299
    fc = t33 + (1.283 * t33 ** 2 - 0.374 * t33 - 0.015)
    t1500 = -0.024 * S + 0.487 * C + 0.006 * OM + 0.005 * S * OM - 0.013 * C * OM + 0.068 * S * C + 0.031
    wp = t1500 + (0.14 * t1500 - 0.02)
    return round(fc * 100, 1), round(wp * 100, 1)


def texture_class(sand, clay):
    if clay >= 40:
        return "Clay"
    if clay >= 27:
        return "Clay loam" if sand <= 45 else "Sandy clay loam"
    if clay >= 20 and sand > 45:
        return "Sandy clay loam"
    return "Loam"


WP_FACTOR = 1.0    # optional multiplier on Saxton-Rawls wilting point (tested 0.65-0.85: no better fit)


def attach_real_soil(blocks, real_dir, grid_elev):
    """Replace random soil with SoilGrids values at each block's coordinates."""
    sg = pd.read_csv(os.path.join(real_dir, "06_soilgrids_block_soil_properties.csv"))
    def top(prop):  # 0-15 cm depth-weighted mean
        return (sg[f"{prop}_0_5cm"] * 5 + sg[f"{prop}_5_15cm"] * 10) / 15
    soil = pd.DataFrame({"block_id": sg.block_id, "latitude": sg.latitude, "longitude": sg.longitude,
                         "sg_ph_h2o": top("phh2o").round(2), "sg_total_n_g_kg": top("nitrogen").round(2),
                         "sg_soc_g_kg": top("soc").round(1), "sg_clay_pct": top("clay").round(1),
                         "sg_sand_pct": top("sand").round(1), "sg_silt_pct": top("silt").round(1),
                         "sg_bulk_density_kg_dm3": top("bdod").round(2), "sg_cec_cmol_kg": top("cec").round(1),
                         "sg_filled_from_estate_mean": sg.values_filled_from_estate_mean})
    b = blocks.drop(columns=["latitude", "longitude"]).merge(soil, on="block_id", how="left")
    est_mean = soil.assign(estate_id=soil.block_id.str[:3]).groupby("estate_id").mean(numeric_only=True)
    for c in [c for c in soil.columns if c.startswith("sg_") and c != "sg_filled_from_estate_mean"] + ["latitude", "longitude"]:
        b[c] = b[c].fillna(b.estate_id.map(est_mean[c]))
    fcwp = [saxton_rawls(r.sg_sand_pct, r.sg_clay_pct, r.sg_soc_g_kg * 1.724 / 10) for r in b.itertuples()]
    b["field_capacity_pct"] = [x[0] for x in fcwp]
    b["wilting_point_pct"] = [round(x[1] * WP_FACTOR, 1) for x in fcwp]
    b["soil_type"] = [texture_class(s, c) + " (SoilGrids)" for s, c in zip(b.sg_sand_pct, b.sg_clay_pct)]
    b["init_ph"] = b.sg_ph_h2o
    b["init_soil_n_ppm"] = (b.sg_total_n_g_kg * 1000 * 0.012).clip(25, 90).round(1)   # ~1.2% of total N is plant-available
    b["n_mineralization_ppm_day"] = (0.10 * b.sg_total_n_g_kg / 4.7).round(3)
    b["weather_grid_elevation_m"] = b.estate_id.map(grid_elev)
    b["temp_offset_c"] = (-0.0065 * (b.elevation_m - b.weather_grid_elevation_m)).round(2)  # lapse rate
    return b


def build_issued_forecasts(real_dir, weather, rng):
    """Daily rain forecasts as issued on the morning of each day (lead 0-3 days).
    Real Open-Meteo forecasts where available; elsewhere sampled from the real
    forecast-error distribution of the same estate (flagged as simulated)."""
    fc = pd.read_csv(os.path.join(real_dir, "03_forecast_vs_actual_hourly_2024_2025.csv"), parse_dates=["datetime_local"])
    fc["date"] = fc.datetime_local.dt.normalize()
    cols = {k: f"precip_forecast_{k}day_ahead_mm" for k in (1, 2, 3, 4)}
    daily = fc.groupby(["estate_id", "date"]).agg(n=("precip_actual_mm", "size"), actual=("precip_actual_mm", "sum"),
                                                  **{f"L{k}": (c, lambda s: s.sum(min_count=24)) for k, c in cols.items()}).reset_index()
    daily = daily[daily.n == 24]
    w = weather[["estate_id", "date", "rainfall_mm"]].copy()
    w["date"] = pd.to_datetime(w["date"])
    bins = [-0.01, 0.5, 5, 15, 40, 1e9]
    out = []
    for e, we in w.groupby("estate_id"):
        de = daily[daily.estate_id == e].set_index("date")
        de["bin"] = pd.cut(de.actual, bins, labels=False)
        pools = {(k, b): de.loc[de.bin == b, f"L{k}"].dropna().values for k in (1, 2, 3, 4) for b in range(5)}
        rain = we.set_index("date").rainfall_mm
        dts = list(rain.index)
        for i, d in enumerate(dts):
            row, real = {"estate_id": e, "issue_date": d.date()}, True
            for lead in range(4):                      # forecast for day d+lead, issued ~day d-1 => lead+1 days ahead
                tgt = d + pd.Timedelta(days=lead)
                v = de[f"L{lead + 1}"].get(tgt, np.nan) if tgt in de.index else np.nan
                if pd.isna(v):
                    real = False
                    act = rain.get(tgt, np.nan)
                    if pd.isna(act):
                        v = np.nan
                    else:
                        pool = pools[(lead + 1, int(pd.cut([act], bins, labels=False)[0]))]
                        v = float(rng.choice(pool)) if len(pool) else act
                row[f"fc_rain_day{lead}_mm"] = round(float(v), 1) if pd.notna(v) else np.nan
            row["forecast_source"] = "real (Open-Meteo previous runs)" if real else "simulated from real error distribution"
            out.append(row)
    return pd.DataFrame(out)


def add_forecast_windows(ev, fcd):
    f = fcd.copy()
    f["issue_date"] = pd.to_datetime(f["issue_date"])
    m = ev.merge(f, left_on=["estate_id", "date"], right_on=["estate_id", "issue_date"], how="left")
    h = m["hour"].astype(float)
    d0, d1, d2, d3 = (m[f"fc_rain_day{k}_mm"] for k in range(4))
    rem = (24 - h) / 24
    m["fc_rain_next_12h_mm"] = (d0 * np.minimum(12, 24 - h) / 24 + d1 * np.maximum(0, h - 12) / 24).round(1)
    m["fc_rain_next_24h_mm"] = (d0 * rem + d1 * h / 24).round(1)
    m["fc_rain_next_48h_mm"] = (d0 * rem + d1 + d2 * h / 24).round(1)
    m["fc_rain_next_72h_mm"] = (d0 * rem + d1 + d2 + d3 * h / 24).round(1)
    return m.drop(columns=["issue_date", "fc_rain_day0_mm", "fc_rain_day1_mm", "fc_rain_day2_mm", "fc_rain_day3_mm"])

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./data")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--blocks-per-estate", type=int, default=10)
    ap.add_argument("--start", default=START)
    ap.add_argument("--end", default=END)
    ap.add_argument("--real-data", default=None, help="real data pack folder (data/interim/real) -> hybrid mode (real weather, rain timing, soil, forecasts)")
    ap.add_argument("--root-zone-mm", type=float, default=None, help="effective root-zone depth (default 400)")
    ap.add_argument("--wp-factor", type=float, default=None, help="hybrid: multiplier on Saxton-Rawls wilting point (default 1.0)")
    ap.add_argument("--missing-rate", type=float, default=0.015, help="share of sensor values set missing")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    global ROOT_ZONE_MM
    ROOT_ZONE_MM = a.root_zone_mm or 400.0
    global WP_FACTOR
    if a.wp_factor:
        WP_FACTOR = a.wp_factor

    dates = pd.date_range(a.start, a.end, freq="D")
    rng = np.random.default_rng(a.seed)
    if a.real_data:
        weather, hourly, grid_elev = load_real_weather(a.real_data, dates)
        blocks = generate_blocks(rng, a.blocks_per_estate, a.start)
        blocks = attach_real_soil(blocks, a.real_data, grid_elev)
        print("HYBRID mode: real weather + rain timing + SoilGrids soil + forecasts")
    else:
        weather, hourly = generate_weather(rng, dates)
        blocks = generate_blocks(rng, a.blocks_per_estate, a.start)
    n_years = len(dates) / 365.25

    # ---- pass 1: calibrate growth scale per zone ----
    scale = {}
    for zone in ZONE_YIELD_TARGET:
        zb = blocks[blocks.agro_zone == zone]
        totals = []
        for _, blk in zb.iterrows():
            w = weather[weather.estate_id == blk.estate_id].reset_index(drop=True)
            r = np.random.default_rng(a.seed + zlib.crc32(blk.block_id.encode()) % 100000)
            _, _, g, pdays = simulate_block(r, blk, w, hourly[blk.estate_id], dates, 1.0)
            yb1 = make_plucking(r, blk, dates, g, pdays)
            totals.append(yb1.green_leaf_kg_per_ha.sum() / n_years)
        scale[zone] = ZONE_YIELD_TARGET[zone] / np.mean(totals)

    # ---- pass 2: full simulation ----
    sensors, events, yields = [], [], []
    for _, blk in blocks.iterrows():
        w = weather[weather.estate_id == blk.estate_id].reset_index(drop=True)
        r = np.random.default_rng(a.seed + zlib.crc32(blk.block_id.encode()) % 100000)
        s, e, g, pdays = simulate_block(r, blk, w, hourly[blk.estate_id], dates, scale[blk.agro_zone])
        sensors += s
        events += e
        yields.append(make_plucking(r, blk, dates, g, pdays))

    sensor_df = pd.DataFrame(sensors)
    yield_df = pd.concat(yields, ignore_index=True)
    ev = pd.DataFrame(events)

    # sensor gaps (simulated IoT dropouts / missed manual entries)
    for c in ["soil_moisture_pct", "soil_ph", "soil_n_ppm", "soil_p_ppm", "soil_k_ppm", "soil_temp_c", "light_lux"]:
        mask = rng.random(len(sensor_df)) < a.missing_rate
        sensor_df.loc[mask, c] = np.nan

    # ---- intervention records: outcome columns ----
    ev["date"] = pd.to_datetime(ev["date"])
    ev = ev.sort_values(["block_id", "date", "hour"]).reset_index(drop=True)
    ev.insert(0, "intervention_id", [f"INT{i:06d}" for i in range(1, len(ev) + 1)])
    ev["execution_datetime"] = ev["date"] + pd.to_timedelta(ev["hour"], unit="h")
    yd = yield_df.copy()
    yd["pluck_date"] = pd.to_datetime(yd["pluck_date"])
    yb = {b: g.set_index("pluck_date")[["green_leaf_kg_per_ha", "round_days"]] for b, g in yd.groupby("block_id")}
    before, after = [], []
    for _, r in ev.iterrows():
        s_ = yb.get(r.block_id)
        d = r.date
        wb_ = s_[(s_.index >= d - pd.Timedelta(days=28)) & (s_.index < d)]
        wa_ = s_[(s_.index >= d + pd.Timedelta(days=7)) & (s_.index < d + pd.Timedelta(days=42))]
        before.append(wb_.green_leaf_kg_per_ha.sum() / wb_.round_days.sum() if len(wb_) else np.nan)
        after.append(wa_.green_leaf_kg_per_ha.sum() / wa_.round_days.sum() if len(wa_) else np.nan)
    ev["yield_before_kg_ha_day"] = np.round(before, 2)
    ev["yield_after_kg_ha_day"] = np.round(after, 2)
    ev["yield_delta_pct"] = ((ev["yield_after_kg_ha_day"] / ev["yield_before_kg_ha_day"] - 1) * 100).round(1)
    fert = ev["intervention_type"] == "fertilizer"
    ev.loc[fert, "runoff_loss_est_pct"] = (ev.loc[fert, "_true_loss"] * 100 + rng.normal(0, 2.5, fert.sum())).clip(0, 95).round(1)
    ev.loc[fert, "absorption_efficiency_pct"] = (100 - ev.loc[fert, "runoff_loss_est_pct"]).round(1)
    blk_area = blocks.set_index("block_id")["area_ha"]
    ev["total_amount"] = (ev["amount_per_ha"] * ev["block_id"].map(blk_area)).round(1)
    ev["status"] = "executed"
    fcd = None
    fc_cols = ["fc_rain_next_12h_mm", "fc_rain_next_24h_mm", "fc_rain_next_48h_mm", "fc_rain_next_72h_mm", "forecast_source"]
    if a.real_data:
        fcd = build_issued_forecasts(a.real_data, weather, rng)
        ev = add_forecast_windows(ev, fcd)
        fert = ev["intervention_type"] == "fertilizer"

    ev_cols = ["intervention_id", "block_id", "estate_id", "intervention_type", "product_code", "product_desc",
               "execution_datetime", "amount_per_ha", "unit", "total_amount", "n_kg_per_ha", "p_kg_per_ha",
               "k_kg_per_ha", "irrigation_mm", "application_method",
               "soil_moisture_at_exec", "soil_ph_at_exec", "temp_at_exec_c", "humidity_at_exec_pct",
               "wind_at_exec_ms", "rain_prev_3d_mm", "rain_next_4h_mm", "rain_next_12h_mm", "rain_next_24h_mm",
               "rain_next_48h_mm", "rain_next_72h_mm", "runoff_loss_est_pct", "absorption_efficiency_pct",
               "yield_before_kg_ha_day", "yield_after_kg_ha_day", "yield_delta_pct", "status"]
    if a.real_data:
        ev_cols = ev_cols[:-4] + fc_cols + ev_cols[-4:]
    for c in ev_cols:
        if c not in ev:
            ev[c] = np.nan
    ev["temp_at_exec_c"] = ev["temp_at_exec_c"].round(1)
    ev["humidity_at_exec_pct"] = ev["humidity_at_exec_pct"].round(1)
    interventions = ev[ev_cols]

    # ---- resource usage (monthly per estate) ----
    ev["month"] = ev["date"].dt.to_period("M")
    res_map = {"fertilizer": ("fertilizer", "kg"), "irrigation": ("water", "L"),
               "dolomite": ("dolomite", "kg"), "fungicide": ("fungicide", "ml")}
    ru = []
    months = pd.period_range(dates[0], dates[-1], freq="M")
    for est_id, *_ in ESTATES:
        e_est = ev[ev.estate_id == est_id]
        for rtype, (rname, unit) in res_map.items():
            stock = None
            for m in months:
                used = e_est[(e_est.month == m) & (e_est.intervention_type == rtype)]["total_amount"].sum()
                alloc = used * rng.uniform(1.0, 1.15) if used > 0 else 0.0
                if rname == "water":
                    stock = 3_000_000.0 * rng.uniform(0.6, 1.0) * (0.6 if m.month in (1, 2, 3) else 1.0)
                else:
                    if stock is None:
                        stock = alloc * 2 + 1000
                    if stock < alloc * 1.2:
                        stock += max(alloc * 3, 1000)       # restock
                ru.append(dict(estate_id=est_id, month=str(m), resource_type=rname, unit=unit,
                               stock_start=round(stock, 1), allocated=round(alloc, 1), used=round(used, 1),
                               wastage_pct=round((alloc - used) / alloc * 100, 1) if alloc > 0 else 0.0))
                if rname != "water":
                    stock -= used
    resource_usage = pd.DataFrame(ru)

    # ---- operational constraints ----
    cons = [
        ("max_fertilizer_kg_per_ha_per_app", "all", 400, "kg/ha", "Max mixture per single application"),
        ("min_fertilizer_kg_per_ha_per_app", "all", 100, "kg/ha", "Below this an application is not worth a field visit"),
        ("max_annual_n_kg_per_ha", "up", 330, "kg N/ha/yr", "Annual N ceiling"),
        ("max_annual_n_kg_per_ha", "mid", 300, "kg N/ha/yr", "Annual N ceiling"),
        ("max_annual_n_kg_per_ha", "low", 300, "kg N/ha/yr", "Annual N ceiling"),
        ("min_days_between_fertilizer", "all", 45, "days", "Minimum gap between applications"),
        ("min_absorption_time_hrs", "fertilizer", 12, "hours", "Rain-free period needed after fertilizer"),
        ("min_rainfree_time_hrs", "fungicide", 4, "hours", "Rain-free period needed after spraying"),
        ("max_rain_next_12h_mm", "fertilizer", 5, "mm", "Do not apply if more forecast in next 12 h"),
        ("max_rain_probability", "fertilizer", 0.30, "fraction", "Max forecast rain probability in window"),
        ("max_wind_for_spray_ms", "fungicide", 4.0, "m/s", "Spray drift limit"),
        ("soil_moisture_min_for_fertilizer", "fertilizer", 0.25, "fraction of available water", "Too dry: SM below WP + 0.25*(FC-WP) -> volatilisation (block FC/WP in block master)"),
        ("soil_moisture_max_for_fertilizer", "fertilizer", 0.85, "fraction of available water", "Too wet: SM above WP + 0.85*(FC-WP) -> runoff risk"),
        ("irrigation_trigger_soil_moisture", "irrigation", 0.35, "fraction of available water", "Irrigate below WP + 0.35*(FC-WP) (irrigated blocks only)"),
        ("max_irrigation_mm_per_event", "irrigation", 25, "mm", "Per event limit"),
        ("available_water_capacity_l_per_month", "estate", 3_000_000, "L", "Default reservoir capacity per estate"),
        ("target_soil_ph_min", "all", 4.5, "pH", "Lower bound of target pH"),
        ("target_soil_ph_max", "all", 5.5, "pH", "Upper bound of target pH"),
        ("dolomite_trigger_ph", "dolomite", 4.45, "pH", "Apply dolomite below this 30-day mean pH"),
        ("min_days_between_dolomite", "dolomite", 730, "days", "Minimum gap between dolomite applications"),
        ("pre_harvest_interval_days", "fungicide", 7, "days", "No plucking within this many days after spray (placeholder - check product label)"),
        ("no_fertilizer_after_pruning_days", "fertilizer", 30, "days", "Wait after pruning"),
        ("action_window_forecast_horizon_hrs", "scheduler", 96, "hours", "Look-ahead for Action Window scheduling"),
        ("working_hours_start", "scheduler", 6, "hour", "Earliest field work hour"),
        ("working_hours_end", "scheduler", 16, "hour", "Latest field work start hour"),
    ]
    constraints = pd.DataFrame(cons, columns=["constraint_name", "applies_to", "value", "unit", "description"])

    # ---- ML table 1: yield / growth (one row per plucking round) ----
    sd = sensor_df.copy()
    sd["date"] = pd.to_datetime(sd["date"])
    wd = weather.copy()
    wd["date"] = pd.to_datetime(wd["date"])
    blk_static = blocks.drop(columns=["estate_name", "region", "latitude", "longitude", "last_pruning_date_before_2021", "mgmt_intensity", "init_ph", "init_soil_n_ppm", "n_mineralization_ppm_day", "sg_filled_from_estate_mean"], errors="ignore")
    fert_ev = ev[ev.intervention_type == "fertilizer"][["block_id", "date", "n_kg_per_ha", "runoff_loss_est_pct"]]
    irr_ev = ev[ev.intervention_type == "irrigation"][["block_id", "date", "irrigation_mm"]]
    fun_ev = ev[ev.intervention_type == "fungicide"][["block_id", "date"]]
    dol_ev = ev[ev.intervention_type == "dolomite"][["block_id", "date"]]
    ml_rows = []
    for b, yb_ in yd.groupby("block_id"):
        sb = sd[sd.block_id == b].set_index("date")
        est = blocks.set_index("block_id").loc[b, "estate_id"]
        wb = wd[wd.estate_id == est].set_index("date")
        fb, ib, kb, db = (fert_ev[fert_ev.block_id == b], irr_ev[irr_ev.block_id == b],
                          fun_ev[fun_ev.block_id == b], dol_ev[dol_ev.block_id == b])
        for _, r in yb_.iterrows():
            end = r.pluck_date
            start = end - pd.Timedelta(days=int(r.round_days))
            s_ = sb.loc[start:end - pd.Timedelta(days=1)]
            w_ = wb.loc[start:end - pd.Timedelta(days=1)]
            w30 = wb.loc[end - pd.Timedelta(days=30):end - pd.Timedelta(days=1)]
            f60 = fb[(fb.date >= end - pd.Timedelta(days=60)) & (fb.date < end)]
            f90 = fb[(fb.date >= end - pd.Timedelta(days=90)) & (fb.date < end)]
            last_f = fb[fb.date < end]["date"].max()
            ml_rows.append(dict(
                block_id=b, pluck_date=end.date(), round_days=r.round_days, month=end.month,
                plucking_standard=r.plucking_standard, days_since_pruning=r.days_since_pruning,
                soil_moisture_mean=s_.soil_moisture_pct.mean(), soil_moisture_min=s_.soil_moisture_pct.min(),
                soil_ph_mean=s_.soil_ph.mean(), soil_n_ppm_mean=s_.soil_n_ppm.mean(),
                soil_p_ppm_mean=s_.soil_p_ppm.mean(), soil_k_ppm_mean=s_.soil_k_ppm.mean(),
                soil_temp_mean=s_.soil_temp_c.mean(), light_lux_mean=s_.light_lux.mean(),
                sunshine_hours_mean=s_.sunshine_hours.mean(),
                rain_sum_mm=w_.rainfall_mm.sum(), rain_days=(w_.rainfall_mm > 1).sum(),
                rain_30d_mm=w30.rainfall_mm.sum(),
                temp_mean_c=w_.temp_mean_c.mean(), temp_max_c=w_.temp_max_c.max(),
                humidity_mean=w_.humidity_pct.mean(), solar_rad_mean=w_.solar_radiation_mj_m2.mean(),
                et0_sum_mm=w_.et0_mm.sum(),
                n_applied_60d_kg_ha=f60.n_kg_per_ha.sum(), n_applied_90d_kg_ha=f90.n_kg_per_ha.sum(),
                n_absorbed_est_90d_kg_ha=(f90.n_kg_per_ha * (1 - f90.runoff_loss_est_pct / 100)).sum(),
                days_since_last_fertilizer=(end - last_f).days if pd.notna(last_f) else 365,
                irrigation_mm_in_round=ib[(ib.date >= start) & (ib.date < end)].irrigation_mm.sum(),
                fungicide_sprays_14d=((kb.date >= end - pd.Timedelta(days=14)) & (kb.date < end)).sum(),
                dolomite_last_365d=int(((db.date >= end - pd.Timedelta(days=365)) & (db.date < end)).any()),
                green_leaf_kg_per_ha=r.green_leaf_kg_per_ha,
                green_leaf_kg_per_ha_per_day=r.green_leaf_kg_per_ha_per_day,
            ))
    ml_yield = pd.DataFrame(ml_rows).merge(blk_static, on="block_id", how="left")
    num = ml_yield.select_dtypes("float").columns
    ml_yield[num] = ml_yield[num].round(3)

    # ---- ML table 2: fertilizer runoff / absorption ----
    f = ev[fert].merge(blocks[["block_id", "agro_zone", "slope_pct", "soil_type", "field_capacity_pct",
                               "shade_tree_cover_pct", "elevation_m"]], on="block_id")
    f["hour"] = f["execution_datetime"].dt.hour
    f["month"] = f["execution_datetime"].dt.month
    rcols = ["intervention_id", "block_id", "execution_datetime", "month", "hour", "agro_zone", "elevation_m",
                   "slope_pct", "soil_type", "field_capacity_pct", "shade_tree_cover_pct", "product_code",
                   "amount_per_ha", "n_kg_per_ha", "soil_moisture_at_exec", "temp_at_exec_c",
                   "humidity_at_exec_pct", "rain_prev_3d_mm", "rain_next_12h_mm", "rain_next_24h_mm",
                   "rain_next_48h_mm", "rain_next_72h_mm", "runoff_loss_est_pct", "absorption_efficiency_pct"]
    if a.real_data:
        rcols = rcols[:-2] + fc_cols + rcols[-2:]
    ml_runoff = f[rcols]

    # ---- write ----
    blocks_out = blocks.drop(columns=["mgmt_intensity", "init_ph", "init_soil_n_ppm", "n_mineralization_ppm_day"], errors="ignore")
    out = {
        "01_block_master.csv": blocks_out,
        "02_weather_daily.csv": weather,
        "03_sensor_readings_daily.csv": sensor_df,
        "04_yield_plucking_records.csv": yield_df,
        "05_intervention_records.csv": interventions,
        "06_resource_usage_monthly.csv": resource_usage,
        "07_operational_constraints.csv": constraints,
        "ml_yield_training.csv": ml_yield,
        "ml_runoff_training.csv": ml_runoff,
    }
    if fcd is not None:
        out["08_daily_forecasts_issued.csv"] = fcd
    for name, df in out.items():
        df.to_csv(os.path.join(a.out, name), index=False)
        print(f"{name:34s} {len(df):>8,d} rows  {df.shape[1]:>3d} cols")


if __name__ == "__main__":
    main()
