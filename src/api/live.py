"""Live block state: builds the optimizer's BlockContext from the latest IoT/manual readings and the Open-Meteo forecast.

The training-time context (src/optimizer/context.py) reads everything from the hybrid tables. In live use the same
fields come from:
  - readings:   the IoT-compatible readings the backend stores (POST /api/readings), most recent last
  - forecast:   the raw Open-Meteo forecast JSON (hourly + daily, with ~30 past days), fetched by the backend
  - block:      static block features from 01_block_master.csv and the block's own training rounds (cultivar,
                plucking standard, typical round length); climate normals from 2021-2023 ERA5 (same rule as training)

Assumptions (stated in every response under `assumptions`):
  - start_*_7d sensor features = mean of the readings in the 7 days before now (one reading is used as is).
  - days since pruning is carried forward from the last training round on the block's pruning cycle.
  - N lost from past applications (N_eff) uses the median training runoff loss.
  - Features outside the training range are clipped to it (tree models cannot extrapolate); each clip is reported.
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from src.data.load import MODEL_READY, load_spec
from src.optimizer.context import BlockContext, forecast_windows
from src.optimizer.limits import load_limits

HYBRID = "data/processed/hybrid"
SENSORS = {"soil_moisture_pct": "start_soil_moisture_pct_7d", "soil_ph": "start_soil_ph_7d",
           "soil_n_ppm": "start_soil_n_ppm_7d", "soil_p_ppm": "start_soil_p_ppm_7d", "soil_k_ppm": "start_soil_k_ppm_7d",
           "soil_temp_c": "start_soil_temp_c_7d", "light_lux": "start_light_lux_7d",
           "sunshine_hours": "start_sunshine_hours_7d"}


class BlockStore:
    """Static block data loaded once at service start."""

    def __init__(self):
        spec = load_spec()
        self.yield_features = spec["yield"]["feature_sets"]["live"]
        self.runoff_features = spec["runoff"]["feature_sets"]["live"]
        self.yield_ranges = spec["yield"]["training_ranges"]
        self.runoff_ranges = spec["runoff"]["training_ranges"]
        self.blocks = pd.read_csv(f"{HYBRID}/01_block_master.csv").set_index("block_id")
        self.rounds = pd.read_csv(f"{MODEL_READY}/yield_model_ready.csv", parse_dates=["pluck_date"])
        w = pd.read_csv(f"{HYBRID}/02_weather_daily.csv", parse_dates=["date"])
        tr = w[w.date.dt.year <= 2023].assign(month=lambda d: d.date.dt.month)
        self.clim = tr.groupby(["estate_id", "month"]).agg(c_rain=("rainfall_mm", "mean"), c_temp=("temp_mean_c", "mean"),
                                                          c_rad=("solar_radiation_mj_m2", "mean"),
                                                          c_et0=("et0_mm", "mean"))
        self.median_loss = float(pd.read_csv(f"{MODEL_READY}/runoff_model_ready.csv").runoff_loss_est_pct.median())
        self.estates = pd.read_csv("data/interim/real/00_estate_locations.csv").set_index("estate_id")
        self.lim = load_limits()

    def block_list(self):
        b = self.blocks.reset_index()
        cols = ["block_id", "estate_id", "region", "agro_zone", "area_ha", "elevation_m", "slope_pct", "soil_type",
                "field_capacity_pct", "wilting_point_pct", "cultivar", "bush_age_yrs", "shade_tree_cover_pct",
                "pruning_cycle_yrs", "irrigation_available", "latitude", "longitude"]
        return b[cols].to_dict("records")

    def estate_list(self):
        e = self.estates.reset_index()
        return e[["estate_id", "region", "agro_zone", "query_lat", "query_lon"]].rename(
            columns={"query_lat": "latitude", "query_lon": "longitude"}).to_dict("records")


def _daily(forecast):
    d = pd.DataFrame(forecast["daily"])
    d["time"] = pd.to_datetime(d["time"])
    return d.set_index("time")


def hourly(forecast):
    h = pd.DataFrame(forecast["hourly"])
    h["time"] = pd.to_datetime(h["time"])
    return h.set_index("time").fillna(0.0)


def _clip(row, ranges, notes):
    for c, (lo, hi) in ranges.items():
        if c in row.index and not pd.isna(row[c]) and not (lo <= row[c] <= hi):
            notes.append(f"{c} = {row[c]:.2f} outside training range [{lo:g}, {hi:g}], clipped")
            row[c] = min(max(row[c], lo), hi)
    return row


def build_context(store, block_id, readings, forecast, fertilizer_history, now=None, hour=8):
    """Returns (BlockContext, info) for a live decision at `now` (default: current local time)."""
    if block_id not in store.blocks.index:
        raise KeyError(f"unknown block {block_id}")
    blk = store.blocks.loc[block_id]
    now = pd.Timestamp(now or datetime.now()).floor("h")
    today = now.normalize()
    notes, assumptions = [], []

    # --- readings: mean of the last 7 days (the training feature is a 7-day mean before the round)
    r = pd.DataFrame(readings)
    if r.empty:
        raise ValueError("no readings for this block: post one to /api/readings first")
    r["ts"] = pd.to_datetime(r["timestamp"]).dt.tz_localize(None)
    r = r.sort_values("ts")
    recent = r[r.ts >= r.ts.max() - pd.Timedelta(days=7)]
    sensor = {k: float(recent[k].dropna().mean()) for k in SENSORS if k in recent and recent[k].notna().any()}
    latest = r.iloc[-1]
    if len(recent) == 1:
        assumptions.append("one reading in the last 7 days: used as the 7-day sensor mean")

    # --- template: the block's own rounds give cultivar, plucking standard, typical round length
    br = store.rounds[store.rounds.block_id == block_id].sort_values("pluck_date")
    last = br.iloc[-1]
    same_month = br[br.pluck_date.dt.month == today.month]
    round_days = int(same_month.round_days.median()) if len(same_month) else int(last.round_days)
    y = last[store.yield_features].astype(float).copy()

    # days since pruning, carried forward on the block's pruning cycle
    elapsed = (today - last.pluck_date).days
    cycle = int(blk.pruning_cycle_yrs * 365)
    dsp = int((last.days_since_pruning + elapsed) % cycle)
    assumptions.append(f"days since pruning ({dsp}) carried forward on a {blk.pruning_cycle_yrs}-year pruning cycle")

    # --- weather from the forecast (past days = observed/analysis, today onward = forecast)
    d = _daily(forecast)
    past = d[d.index < today]
    if len(past) < 7:
        raise ValueError("forecast needs past_days >= 7 (Open-Meteo past_days parameter)")
    fc = [float(d.precipitation_sum.get(today + timedelta(days=i), 0.0) or 0.0) for i in range(4)]
    c = store.clim.loc[(blk.estate_id, today.month)]
    y.update(pd.Series({
        "round_days": round_days, "month": today.month, "days_since_pruning": dsp + round_days,
        "start_rain_7d_mm": past.precipitation_sum.tail(7).sum(),
        "start_rain_30d_mm": past.precipitation_sum.tail(30).sum(),
        "start_temp_mean_7d_c": past.temperature_2m_mean.tail(7).mean(),
        "start_et0_7d_mm": past.et0_fao_evapotranspiration.tail(7).sum(),
        "fc_rain_next4d_mm": sum(fc),
        "clim_rain_round_mm": c.c_rain * round_days, "clim_temp_mean_c": c.c_temp,
        "clim_solar_mj_m2_day": c.c_rad, "clim_et0_round_mm": c.c_et0 * round_days,
        "irrigation_mm_in_round": 0.0, "fungicide_sprays_14d": 0.0, "dolomite_last_365d": 0.0,
        **{SENSORS[k]: v for k, v in sensor.items()},
    }))

    # --- fertilizer history (from the readings' last_fertilizer fields + any history the backend sends)
    lim = store.lim
    ev = pd.DataFrame(fertilizer_history or [], columns=["date", "product_code", "amount_kg_per_ha"])
    if len(ev):
        ev["date"] = pd.to_datetime(ev.date).dt.tz_localize(None).dt.normalize()
        ev["n_kg_per_ha"] = ev.amount_kg_per_ha * ev.product_code.map(lim.n_frac).fillna(np.mean(list(lim.n_frac.values())))
        ev["n_eff"] = ev.n_kg_per_ha * (1 - store.median_loss / 100)
        ev = ev.drop_duplicates("date")
        assumptions.append(f"past N_eff uses the median training runoff loss ({store.median_loss:.1f} %)")
    else:   # no fertilizer on record (typed columns, so the date filters below still work)
        ev = pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"), "n_kg_per_ha": pd.Series(dtype=float),
                           "n_eff": pd.Series(dtype=float)})
        assumptions.append("no fertilizer on record for this block")
    end = today + timedelta(days=round_days)
    prior = ev[ev.date < today]
    last_f = prior.date.max() if len(prior) else pd.NaT
    n60 = prior[prior.date >= end - timedelta(days=60)].n_kg_per_ha.sum()
    n90 = prior[prior.date >= end - timedelta(days=90)].n_kg_per_ha.sum()
    y["n_applied_60d_kg_ha"], y["n_applied_90d_kg_ha"] = n60, n90
    y["days_since_last_fertilizer"] = min(365, (end - last_f).days) if pd.notna(last_f) else 365
    y = _clip(y, store.yield_ranges, notes)

    # --- runoff features at the planned hour (Tier 2 uses 08:00; Tier 3 rescans every hour)
    prev = past.iloc[-1]
    ro = pd.Series(0.0, index=store.runoff_features)
    ro.update(pd.Series({"month": today.month, "hour": hour, "elevation_m": blk.elevation_m, "slope_pct": blk.slope_pct,
                         "field_capacity_pct": blk.field_capacity_pct, "shade_tree_cover_pct": blk.shade_tree_cover_pct,
                         "soil_moisture_at_exec": float(latest.get("soil_moisture_pct", sensor.get("soil_moisture_pct"))),
                         "temp_prev_day_c": float(prev.temperature_2m_mean) + blk.temp_offset_c,
                         "humidity_prev_day_pct": float(prev.relative_humidity_2m_mean),
                         "rain_prev_3d_mm": past.precipitation_sum.tail(3).sum(),
                         f"agro_zone__{blk.agro_zone}": 1.0, f"soil_type__{blk.soil_type}": 1.0,
                         **forecast_windows(*fc, hour)}))
    ro = _clip(ro, {k: v for k, v in store.runoff_ranges.items() if k not in ("amount_per_ha", "n_kg_per_ha")}, notes)

    ctx = BlockContext(
        block_id=block_id, decision_date=today, round_days=round_days, agro_zone=blk.agro_zone,
        yield_row=y, runoff_row=ro, n_prior_60d=n60, n_prior_90d=n90,
        n_this_year=prior[prior.date.dt.year == today.year].n_kg_per_ha.sum(),
        days_since_fert=(today - last_f).days if pd.notna(last_f) else np.nan,
        days_since_pruning=dsp, soil_moisture=float(ro.soil_moisture_at_exec),
        field_capacity=float(blk.field_capacity_pct), wilting_point=float(blk.wilting_point_pct),
        irrigation_available=bool(blk.irrigation_available), area_ha=float(blk.area_ha),
        prior_events=prior[prior.date >= today - timedelta(days=365)][["date", "n_kg_per_ha", "n_eff"]])
    info = dict(now=now, sensor_7d=sensor, latest=latest, past=past, ph_mean=sensor.get("soil_ph"),
                notes=notes, assumptions=assumptions, lim=lim)
    return ctx, info
