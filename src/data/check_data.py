"""Audit every data layer and print PASS / FAIL per check. Exit code 1 if anything fails.

Usage:
    python -m src.data.check_data            # add --workbook to also check the Excel release
"""
import hashlib
import json
import os
import sys

import numpy as np
import pandas as pd

D = "data"
results, warnings = [], []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def warn(name, detail):
    """Known, documented characteristic of the data (not an error). See md_files/data/README.md 'Known characteristics'."""
    warnings.append(name)
    print(f"WARN  {name}  ({detail})")


def csv(rel, **kw):
    return pd.read_csv(os.path.join(D, rel), low_memory=False, **kw)


def main():
    # ---- raw ----
    man = csv("raw/MANIFEST.csv")
    bad = [r.file for r in man.itertuples()
           if not os.path.exists(f"{D}/raw/{r.file}")
           or hashlib.sha256(open(f"{D}/raw/{r.file}", "rb").read()).hexdigest() != r.sha256]
    on_disk = sum(len(f) for _, _, f in os.walk(f"{D}/raw")) - 1
    check("raw: all files match MANIFEST checksums", not bad and on_disk == len(man), f"{len(man)} files, {on_disk} on disk")

    # ---- interim/real ----
    expect = {"00_estate_locations.csv": 5, "01_weather_hourly_era5_2021_2025.csv": 219120,
              "02_weather_daily_era5_2021_2025.csv": 9130, "03_forecast_vs_actual_hourly_2024_2025.csv": 85475,
              "04_forecast_vs_actual_daily_2024_2025.csv": 3560, "05_nasa_power_daily_2021_2025.csv": 9130,
              "06_soilgrids_block_soil_properties.csv": 50, "06b_soilgrids_block_soil_long.csv": 1350,
              "07_sl_tea_production_monthly_by_elevation_2021_2025.csv": 300,
              "08_monthly_weather_vs_production_by_elevation.csv": 180}
    real = {f: csv(f"interim/real/{f}") for f in expect}
    check("real: row counts", all(len(real[f]) == n for f, n in expect.items()),
          ", ".join(f"{f[:2]}={len(real[f]):,}" for f in expect))
    check("real: no duplicate rows", all(not df.duplicated().any() for df in real.values()))
    w = real["02_weather_daily_era5_2021_2025.csv"]
    check("real: daily weather 5 estates × 1,826 days, no gaps",
          w.groupby("estate_id").date.nunique().eq(1826).all() and w.date.min() == "2021-01-01" and w.date.max() == "2025-12-31")
    p = real["07_sl_tea_production_monthly_by_elevation_2021_2025.csv"].pivot_table(
        index=["year", "month"], columns="elevation", values="production_kg")
    check("real: production high+medium+low+green = total (±2 kg)",
          (p[["high", "medium", "low", "green_tea"]].sum(axis=1) - p.total).abs().max() <= 2)

    # ---- processed/hybrid ----
    H = {"01_block_master.csv": 50, "02_weather_daily.csv": 9130, "03_sensor_readings_daily.csv": 91300,
         "04_yield_plucking_records.csv": 9053, "05_intervention_records.csv": 3233,
         "06_resource_usage_monthly.csv": 1200, "07_operational_constraints.csv": 25,
         "08_daily_forecasts_issued.csv": 9130, "ml_yield_training.csv": 9053, "ml_runoff_training.csv": 850}
    hy = {f: csv(f"processed/hybrid/{f}") for f in H}
    check("hybrid: row counts", all(len(hy[f]) == n for f, n in H.items()))
    check("hybrid: no duplicate rows", all(not df.duplicated().any() for df in hy.values()))
    blocks = set(hy["01_block_master.csv"].block_id)
    orphans = {f: len(set(df.block_id) - blocks) for f, df in hy.items() if "block_id" in df}
    check("hybrid: every block_id exists in the block master", not any(orphans.values()))
    s = hy["03_sensor_readings_daily.csv"]
    check("hybrid: one sensor row per block per day", not s.duplicated(["block_id", "date"]).any() and len(s) == 50 * 1826)
    sensors = ["soil_moisture_pct", "soil_ph", "soil_n_ppm", "soil_p_ppm", "soil_k_ppm", "soil_temp_c", "light_lux"]
    miss = s[sensors].isna().mean()
    check("hybrid: 7 sensor fields ≈ 1.5 % missing (deliberate); sunshine_hours complete",
          miss.between(0.01, 0.02).all() and s.sunshine_hours.notna().all(), f"{miss.min():.2%}–{miss.max():.2%}")
    rng = {"soil_ph": (3.5, 7), "soil_moisture_pct": (5, 70), "soil_temp_c": (5, 35), "soil_n_ppm": (0, 200),
           "soil_p_ppm": (0, 100), "soil_k_ppm": (0, 400), "light_lux": (0, 150000)}
    out = {c: int((~s[c].dropna().between(*r)).sum()) for c, r in rng.items()}
    check("hybrid: sensor values in physical ranges", not any(out.values()))
    iv = hy["05_intervention_records.csv"]
    counts = iv.intervention_type.value_counts().to_dict()
    check("hybrid: intervention counts", counts == {"fungicide": 1771, "fertilizer": 850, "irrigation": 611, "dolomite": 1}, str(counts))
    fert = iv[iv.intervention_type == "fertilizer"]
    check("hybrid: fertilizer amounts plausible (50-500 kg/ha)", fert.amount_per_ha.between(50, 500).all(),
          f"{fert.amount_per_ha.min():.0f}–{fert.amount_per_ha.max():.0f}")
    # historical (fixed-calendar) practice is not bound by the optimizer's rules - report how often it breaks them
    out_dose = int((~fert.amount_per_ha.between(100, 400)).sum())
    f2 = fert.assign(t=pd.to_datetime(fert.execution_datetime)).sort_values(["block_id", "t"])
    gap = int((f2.groupby("block_id").t.diff().dt.days < 45).sum())
    zone = hy["01_block_master.csv"].set_index("block_id").agro_zone
    ny = f2.assign(y=f2.t.dt.year).groupby(["block_id", "y"]).n_kg_per_ha.sum().reset_index()
    over_n = int((ny.n_kg_per_ha > ny.block_id.map(zone).map({"up": 330, "mid": 300, "low": 300})).sum())
    sp = iv[iv.intervention_type == "fungicide"]
    windy = int((sp.wind_at_exec_ms > 4).sum())
    late = int((~pd.to_datetime(iv.execution_datetime).dt.hour.between(6, 16)).sum())
    warn("historical practice breaks optimizer rules (by design, documented)",
         f"dose outside 100-400 kg/ha: {out_dose}/{len(fert)}; <45 days apart: {gap}; over annual N ceiling: {over_n}/{len(ny)} "
         f"block-years; sprays in wind >4 m/s: {windy}/{len(sp)}; irrigation at 17:00: {late}")
    check("hybrid: absorption = 100 − runoff", np.allclose(fert.absorption_efficiency_pct + fert.runoff_loss_est_pct, 100))
    yt = hy["ml_yield_training.csv"]
    check("hybrid: yield training has no missing values", not yt.isna().any().any() and not hy["ml_runoff_training.csv"].isna().any().any())

    # ---- model_ready ----
    spec = json.load(open(f"{D}/model_ready/feature_spec.json", encoding="utf-8"))
    for task, n, meta_needed in [("yield", 9053, None), ("runoff", 850, None)]:
        df = csv(f"model_ready/{task}_model_ready.csv")
        sp = spec[task]
        feats = sp["features"]
        check(f"model_ready/{task}: rows, columns match spec",
              len(df) == n and list(df.columns) == sp["meta_columns"] + [sp["target"]] + feats, f"{len(df):,} × {df.shape[1]}")
        check(f"model_ready/{task}: features numeric, no missing values",
              all(pd.api.types.is_numeric_dtype(df[c]) for c in feats) and not df[feats + [sp["target"]]].isna().any().any())
        leak = {"green_leaf_kg_per_ha", "aspect", "absorption_efficiency_pct"} & set(df.columns)
        check(f"model_ready/{task}: leakage columns absent", not leak, str(leak or ""))
        yr = df.year
        check(f"model_ready/{task}: split = train ≤2023 / val 2024 / test 2025",
              ((df.split == "train") == (yr <= 2023)).all() and ((df.split == "val") == (yr == 2024)).all()
              and ((df.split == "test") == (yr == 2025)).all(), df.split.value_counts().to_dict())
        check(f"model_ready/{task}: each block in exactly one cv_fold, 2 blocks per estate per fold",
              df.groupby("block_id").cv_fold.nunique().eq(1).all()
              and df.drop_duplicates("block_id").groupby(["cv_fold", "estate_id"]).size().eq(2).all())
        tr = sp["training_ranges"]
        check(f"model_ready/{task}: training_ranges match data",
              all(np.isclose(df[c].min(), v[0]) and np.isclose(df[c].max(), v[1]) for c, v in tr.items() if c in df))
    r = csv("model_ready/runoff_model_ready.csv")
    live = spec["runoff"]["feature_sets"]["live"]
    check("model_ready/runoff: live feature set has no hindsight rain", not any("hindsight" in c or c.startswith("rain_next") for c in live))
    check("model_ready/runoff: monotone constraints only on rain columns",
          all("rain" in c for c in spec["runoff"]["monotone_constraints"]))
    y = csv("model_ready/yield_model_ready.csv")
    check("model_ready/yield: target equals source table", np.allclose(y.green_leaf_kg_per_ha_per_day, yt.green_leaf_kg_per_ha_per_day))
    m = csv("model_ready/smarttea_master_block_daily.csv.gz")
    check("model_ready/master: 91,300 rows, one per block-day", len(m) == 91300 and not m.duplicated(["block_id", "date"]).any())
    check("model_ready/master: event totals match sources",
          m.plucked.sum() == 9053 and (m.fert_kg_per_ha > 0).sum() == 850 and (m.irrigation_mm > 0).sum() == 611
          and (m.fungicide_ml_per_ha > 0).sum() == 1771 and np.isclose(m.fert_kg_per_ha.sum(), fert.amount_per_ha.sum()))

    # ---- documentation ----
    dic = csv("data_dictionary.csv")
    tables = {}
    for t in dic.table.unique():
        tables[t] = list(pd.read_csv(t, nrows=0).columns)
    check("docs: data dictionary covers every column of every table",
          all(set(dic[dic.table == t].column) == set(c) for t, c in tables.items()), f"{len(dic)} columns, {len(tables)} tables")
    check("docs: dictionary has a description for every column", dic.description.notna().all())

    if "--workbook" in sys.argv:
        from openpyxl import load_workbook
        wb = load_workbook(f"{D}/release/SmartTea_LK_C04_Dataset.xlsx", read_only=True)
        from src.data.build_workbook import SHEETS
        rows = {n: wb[n].max_row - 1 for n in SHEETS}
        want = {n: len(pd.read_csv(f"{D}/{s[0]}", usecols=[0])) for n, s in SHEETS.items()}
        check("release: workbook has every sheet with the right row count", rows == want, f"{len(wb.sheetnames)} sheets")

    print(f"\n{sum(results)}/{len(results)} checks passed, {len(warnings)} documented warning(s)"
          + ("" if all(results) else " - SEE FAILURES ABOVE"))
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
