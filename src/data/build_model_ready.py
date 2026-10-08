"""Build the model-ready datasets in data/model_ready from the hybrid tables in data/processed/hybrid.

Outputs
  smarttea_master_block_daily.csv.gz  every source joined at block x day (one row per block per day)
  yield_model_ready.csv               yield surrogate table: meta + target + numeric features
  runoff_model_ready.csv              runoff model table:   meta + target + numeric features
  feature_spec.json                   targets, feature sets, decision variables, monotone constraints,
                                      training ranges (optimizer bounds) and split definitions

Splits are fixed here so every model is evaluated on the same rows:
  split    : time split by year -> train 2021-2023, val 2024, test 2025
  cv_fold  : 0-4, block-grouped folds (all rows of a block in one fold), 2 blocks per estate per fold

Usage:
    python -m src.data.build_model_ready --hybrid data/processed/hybrid --out data/model_ready
"""
import argparse
import json
import os

import numpy as np
import pandas as pd

SEED = 42
SPLIT_YEARS = {"train": [2021, 2022, 2023], "val": [2024], "test": [2025]}
YIELD_CATEGORICAL = ["plucking_standard", "agro_zone", "soil_type", "cultivar"]
RUNOFF_CATEGORICAL = ["agro_zone", "soil_type", "product_code"]
# Columns the optimizer can change (decision variables) - the surrogate must respond to these.
YIELD_DECISIONS = ["n_applied_60d_kg_ha", "n_applied_90d_kg_ha", "days_since_last_fertilizer", "irrigation_mm_in_round", "fungicide_sprays_14d",
                   "dolomite_last_365d"]
RUNOFF_DECISIONS = ["amount_per_ha", "n_kg_per_ha", "hour", "month", "product_code"]
# Yield features measured DURING the plucking round (after the decision) - unknown when deciding.
# n_absorbed_est_90d_kg_ha uses the true runoff loss of applications made during the round.
ROUND_HINDSIGHT = ["soil_moisture_mean", "soil_moisture_min", "soil_ph_mean", "soil_n_ppm_mean", "soil_p_ppm_mean",
                   "soil_k_ppm_mean", "soil_temp_mean", "light_lux_mean", "sunshine_hours_mean", "rain_sum_mm",
                   "rain_days", "rain_30d_mm", "temp_mean_c", "temp_max_c", "humidity_mean", "solar_rad_mean",
                   "et0_sum_mm", "n_absorbed_est_90d_kg_ha"]
FC_RAIN = ["fc_rain_next_12h_mm", "fc_rain_next_24h_mm", "fc_rain_next_48h_mm", "fc_rain_next_72h_mm"]
ACT_RAIN = ["rain_next_12h_mm", "rain_next_24h_mm", "rain_next_48h_mm", "rain_next_72h_mm"]
SAME_DAY = ["temp_at_exec_c", "humidity_at_exec_pct"]  # whole-day means of the application day (partly after it)


def split_of(year):
    return year.map({y: s for s, ys in SPLIT_YEARS.items() for y in ys})


def block_folds(block_ids):
    """Assign each block to one of 5 folds, 2 blocks per estate per fold (stratified by estate)."""
    rng = np.random.default_rng(SEED)
    fold = {}
    for est, blocks in pd.Series(sorted(set(block_ids))).groupby(lambda i: sorted(set(block_ids))[i][:3]):
        b = rng.permutation(blocks.to_numpy())
        for i, blk in enumerate(b):
            fold[blk] = i % 5
    return fold


def one_hot(df, cols):
    out = pd.get_dummies(df, columns=cols, prefix=cols, prefix_sep="__", dtype=int)
    return out


def ranges(df, cols):
    return {c: [float(df[c].min()), float(df[c].max())] for c in cols}


def yield_start_features(h, y):
    """Features known on the morning a plucking round starts (the moment a decision is made).

    start_*  : sensor / weather means over the 7 days before the round (30 days for rain)
    fc_*     : rain forecast issued that morning for day 0-3
    clim_*   : normal weather for the estate and month, from TRAIN years (2021-2023) only, scaled to the round length
    """
    s = pd.read_csv(f"{h}/03_sensor_readings_daily.csv", parse_dates=["date"])
    w = pd.read_csv(f"{h}/02_weather_daily.csv", parse_dates=["date"])
    fc = pd.read_csv(f"{h}/08_daily_forecasts_issued.csv", parse_dates=["issue_date"])
    start = pd.to_datetime(y.pluck_date) - pd.to_timedelta(y.round_days, unit="D")
    keys = pd.DataFrame({"block_id": y.block_id, "estate_id": y.estate_id, "date": start})

    sens = ["soil_moisture_pct", "soil_ph", "soil_n_ppm", "soil_p_ppm", "soil_k_ppm", "soil_temp_c", "light_lux", "sunshine_hours"]
    s = s.sort_values(["block_id", "date"])
    roll = s.groupby("block_id")[sens].transform(lambda c: c.rolling(7, min_periods=1).mean().shift(1))
    roll.columns = [f"start_{c}_7d" for c in sens]
    roll[["block_id", "date"]] = s[["block_id", "date"]]
    w = w.sort_values(["estate_id", "date"])
    g = w.groupby("estate_id")
    wr = pd.DataFrame({"estate_id": w.estate_id, "date": w.date,
                       "start_rain_7d_mm": g.rainfall_mm.transform(lambda c: c.rolling(7, min_periods=1).sum().shift(1)),
                       "start_rain_30d_mm": g.rainfall_mm.transform(lambda c: c.rolling(30, min_periods=1).sum().shift(1)),
                       "start_temp_mean_7d_c": g.temp_mean_c.transform(lambda c: c.rolling(7, min_periods=1).mean().shift(1)),
                       "start_et0_7d_mm": g.et0_mm.transform(lambda c: c.rolling(7, min_periods=1).sum().shift(1))})
    f = fc.rename(columns={"issue_date": "date"})
    f["fc_rain_next4d_mm"] = f[[f"fc_rain_day{k}_mm" for k in range(4)]].sum(axis=1, min_count=1)
    tr = w[w.date.dt.year.isin(SPLIT_YEARS["train"])].assign(month=lambda d: d.date.dt.month)
    clim = tr.groupby(["estate_id", "month"]).agg(c_rain=("rainfall_mm", "mean"), c_temp=("temp_mean_c", "mean"),
                                                  c_rad=("solar_radiation_mj_m2", "mean"), c_et0=("et0_mm", "mean")).reset_index()

    out = keys.merge(roll, on=["block_id", "date"], how="left").merge(wr, on=["estate_id", "date"], how="left")
    out = out.merge(f[["estate_id", "date", "fc_rain_next4d_mm"]], on=["estate_id", "date"], how="left")
    out["month"] = out.date.dt.month
    out = out.merge(clim, on=["estate_id", "month"], how="left")
    n = y.round_days.to_numpy()
    out["clim_rain_round_mm"] = out.c_rain * n
    out["clim_temp_mean_c"] = out.c_temp
    out["clim_solar_mj_m2_day"] = out.c_rad
    out["clim_et0_round_mm"] = out.c_et0 * n
    # a missing forecast (0.1 % of days) falls back to the climate normal for the same 4 days
    out["fc_rain_next4d_mm"] = out.fc_rain_next4d_mm.fillna(out.c_rain * 4)
    cols = [c for c in out.columns if c.startswith(("start_", "fc_", "clim_"))]
    # rounds starting in the first days of 2021 have no previous week: use the estate's train-period median
    is_train = pd.to_datetime(y.pluck_date).dt.year.isin(SPLIT_YEARS["train"]).to_numpy()
    for c in cols:
        med = out[is_train].groupby("estate_id")[c].median()
        out[c] = out[c].fillna(out.estate_id.map(med))
    return out[cols].round(3).reset_index(drop=True)


def build_yield(h, folds):
    y = pd.read_csv(f"{h}/ml_yield_training.csv")
    meta = pd.DataFrame({
        "row_id": [f"Y{i:05d}" for i in range(len(y))], "block_id": y.block_id, "estate_id": y.estate_id,
        "pluck_date": y.pluck_date, "year": pd.to_datetime(y.pluck_date).dt.year})
    meta["split"] = split_of(meta.year)
    meta["cv_fold"] = meta.block_id.map(folds)
    target = "green_leaf_kg_per_ha_per_day"
    drop = ["block_id", "estate_id", "pluck_date", target,
            "green_leaf_kg_per_ha",  # leakage: target x round length
            "aspect"]  # no effect in the generator; acts as a block identifier
    x = y.drop(columns=drop)
    x["irrigation_available"] = x.irrigation_available.astype(int)
    x = pd.concat([x, yield_start_features(h, y)], axis=1)
    raw_ranges = ranges(x, [c for c in x.columns if c not in YIELD_CATEGORICAL])
    x = one_hot(x, YIELD_CATEGORICAL)
    df = pd.concat([meta, y[[target]], x], axis=1)
    live = [c for c in x.columns if c not in ROUND_HINDSIGHT]
    spec = dict(
        target=target, target_unit="kg green leaf / ha / day", grain="one plucking round of one block",
        meta_columns=list(meta.columns), features=list(x.columns),
        feature_sets={
            "live": live,  # known when the round starts: the deployed system can use these
            "hindsight": [c for c in x.columns if not c.startswith(("start_", "fc_", "clim_"))],  # round's actual conditions
        },
        hindsight_columns=ROUND_HINDSIGHT,
        categorical_one_hot={c: [k for k in x.columns if k.startswith(c + "__")] for c in YIELD_CATEGORICAL},
        decision_variables=YIELD_DECISIONS,
        live_note="'live' uses only what is known when a round starts: block, decisions, readings from the 7 days "
                  "before, the forecast issued that morning and train-year climate normals. 'hindsight' adds the "
                  "conditions measured during the round (upper bound; not available when deciding).",
        dropped={"green_leaf_kg_per_ha": "leakage (target x round_days)", "aspect": "no causal effect; block identifier",
                 "block_id/estate_id": "identifiers (kept in meta)"},
        monotone_constraints={},
        training_ranges=raw_ranges)
    return df, spec


def build_runoff(h, folds):
    r = pd.read_csv(f"{h}/ml_runoff_training.csv")
    meta = pd.DataFrame({
        "row_id": [f"R{i:04d}" for i in range(len(r))], "intervention_id": r.intervention_id,
        "block_id": r.block_id, "estate_id": r.block_id.str[:3], "execution_datetime": r.execution_datetime,
        "year": pd.to_datetime(r.execution_datetime).dt.year, "forecast_source": r.forecast_source})
    meta["split"] = split_of(meta.year)
    meta["cv_fold"] = meta.block_id.map(folds)
    target = "runoff_loss_est_pct"
    x = r.drop(columns=["intervention_id", "block_id", "execution_datetime", "forecast_source", target,
                        "absorption_efficiency_pct"])  # = 100 - runoff_loss_est_pct exactly
    # temp_at_exec_c / humidity_at_exec_pct are whole-day means of the application day, so they include the
    # hours after application (humid when rain arrives). Live features use the previous day's values instead.
    w = pd.read_csv(f"{h}/02_weather_daily.csv", parse_dates=["date"])
    off = pd.read_csv(f"{h}/01_block_master.csv").set_index("block_id").temp_offset_c
    prev = pd.DataFrame({"estate_id": r.block_id.str[:3],
                         "date": pd.to_datetime(r.execution_datetime).dt.normalize() - pd.Timedelta(days=1)})
    prev = prev.merge(w[["estate_id", "date", "humidity_pct", "temp_mean_c"]], on=["estate_id", "date"], how="left")
    x.insert(x.columns.get_loc("temp_at_exec_c"), "temp_prev_day_c",
             (prev.temp_mean_c + r.block_id.map(off).to_numpy()).round(1).to_numpy())
    x.insert(x.columns.get_loc("humidity_at_exec_pct"), "humidity_prev_day_pct", prev.humidity_pct.round(1).to_numpy())
    x = x.rename(columns={c: f"hindsight__{c}" for c in ACT_RAIN + SAME_DAY})
    raw_ranges = ranges(x, [c for c in x.columns if c not in RUNOFF_CATEGORICAL])
    x = one_hot(x, RUNOFF_CATEGORICAL)
    hind = [f"hindsight__{c}" for c in ACT_RAIN + SAME_DAY]
    live = [c for c in x.columns if c not in hind]
    df = pd.concat([meta, r[[target]], x], axis=1)
    spec = dict(
        target=target, target_unit="% of applied fertilizer lost", grain="one fertilizer application",
        alternative_target="absorption_efficiency_pct = 100 - runoff_loss_est_pct (not stored)",
        meta_columns=list(meta.columns), features=list(x.columns),
        feature_sets={
            "live": live,  # forecast rain only: what the deployed system can know
            "hindsight": [c for c in x.columns if c not in FC_RAIN],  # actual rain after: upper bound only
        },
        categorical_one_hot={c: [k for k in x.columns if k.startswith(c + "__")] for c in RUNOFF_CATEGORICAL},
        decision_variables=RUNOFF_DECISIONS,
        monotone_constraints={c: 1 for c in FC_RAIN + [f"hindsight__{c}" for c in ACT_RAIN]},  # more rain never lowers loss
        training_ranges=raw_ranges)
    return df, spec


def build_master(h):
    s = pd.read_csv(f"{h}/03_sensor_readings_daily.csv")
    b = pd.read_csv(f"{h}/01_block_master.csv")
    w = pd.read_csv(f"{h}/02_weather_daily.csv").drop(columns=["source"])
    w = w.rename(columns={c: f"wx_{c}" for c in w.columns if c not in ("estate_id", "date")})
    fc = pd.read_csv(f"{h}/08_daily_forecasts_issued.csv").rename(columns={"issue_date": "date", "forecast_source": "fc_source"})
    iv = pd.read_csv(f"{h}/05_intervention_records.csv")
    iv["date"] = pd.to_datetime(iv.execution_datetime).dt.date.astype(str)
    yl = pd.read_csv(f"{h}/04_yield_plucking_records.csv").rename(columns={"pluck_date": "date"})

    def per_type(t, cols, prefix):
        g = iv[iv.intervention_type == t].groupby(["block_id", "date"])
        agg = {c: ("first" if iv[c].dtype == object else "sum") for c in cols}
        return g.agg(agg).rename(columns=lambda c: f"{prefix}_{c}").reset_index()

    fert = per_type("fertilizer", ["product_code", "amount_per_ha", "n_kg_per_ha", "p_kg_per_ha", "k_kg_per_ha",
                                   "runoff_loss_est_pct"], "fert")
    irr = per_type("irrigation", ["irrigation_mm"], "irr")
    fung = per_type("fungicide", ["amount_per_ha"], "fung")
    dolo = per_type("dolomite", ["amount_per_ha"], "dolo")

    m = s.merge(b, on="block_id", how="left")
    m = m.merge(w, on=["estate_id", "date"], how="left").merge(fc, on=["estate_id", "date"], how="left")
    for t in (fert, irr, fung, dolo):
        m = m.merge(t, on=["block_id", "date"], how="left")
    m = m.merge(yl.drop(columns=["estate_id"]), on=["block_id", "date"], how="left")
    m["plucked"] = m.green_leaf_kg_per_ha.notna().astype(int)
    for c in ["fert_amount_per_ha", "irr_irrigation_mm", "fung_amount_per_ha", "dolo_amount_per_ha"]:
        m[c] = m[c].fillna(0)
    m = m.rename(columns={"fert_amount_per_ha": "fert_kg_per_ha", "irr_irrigation_mm": "irrigation_mm",
                          "fung_amount_per_ha": "fungicide_ml_per_ha", "dolo_amount_per_ha": "dolomite_kg_per_ha",
                          "fert_runoff_loss_est_pct": "fert_runoff_loss_est_pct"})
    first = ["block_id", "estate_id", "date"]
    return m[first + [c for c in m.columns if c not in first]].sort_values(["block_id", "date"]).reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hybrid", default="data/processed/hybrid")
    ap.add_argument("--out", default="data/model_ready")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    blocks = pd.read_csv(f"{a.hybrid}/01_block_master.csv").block_id
    folds = block_folds(blocks.tolist())

    yd, ys = build_yield(a.hybrid, folds)
    rd, rs = build_runoff(a.hybrid, folds)
    master = build_master(a.hybrid)
    yd.to_csv(f"{a.out}/yield_model_ready.csv", index=False)
    rd.to_csv(f"{a.out}/runoff_model_ready.csv", index=False)
    master.to_csv(f"{a.out}/smarttea_master_block_daily.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})

    spec = {
        "version": "1.0", "source": a.hybrid.replace("\\", "/"), "seed": SEED,
        "splits": {"split": {k: v for k, v in SPLIT_YEARS.items()},
                   "cv_fold": "5 block-grouped folds; all rows of a block share a fold; 2 blocks per estate per fold "
                              "(= unseen blocks on known estates)",
                   "estate_id": "leave-one-estate-out (= unseen location and climate; much harder)",
                   "block_folds": {k: int(v) for k, v in sorted(folds.items())}},
        "rules": ["Never use random row splits (leakage between days and rounds of the same block).",
                  "Report the time split (test 2025), the block-grouped CV (unseen blocks) and leave-one-estate-out.",
                  "Use full one-hot encoding (as stored); drop_first encoding lowered unseen-block R2 from ~0.82 to ~0.66.",
                  "Train deployed models on feature_sets.live (both tasks); use 'hindsight' only as an upper bound.",
                  "Optimizer bounds = intersection of 07_operational_constraints.csv and training_ranges: the historical "
                  "data contains doses up to 420 kg/ha and 12 block-years over the annual N ceiling, which the "
                  "optimizer must not recommend."],
        "yield": ys, "runoff": rs,
    }
    with open(f"{a.out}/feature_spec.json", "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2)

    for name, df in [("yield_model_ready.csv", yd), ("runoff_model_ready.csv", rd),
                     ("smarttea_master_block_daily.csv.gz", master)]:
        print(f"{name:38s} {len(df):>7,} rows x {df.shape[1]:>3} cols")
    for name, df in [("yield", yd), ("runoff", rd)]:
        print(f"  {name}: split rows {df.split.value_counts().reindex(['train', 'val', 'test']).to_dict()}"
              f" | cv_fold rows {df.cv_fold.value_counts().sort_index().to_dict()}")


if __name__ == "__main__":
    main()
