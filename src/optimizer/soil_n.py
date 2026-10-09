"""Soil-N response to a fertilizer application, learned from the sensor data (train years 2021-2023 only).

Impulse-response model: an application adds   alpha * N_eff * exp(-L / tau)   ppm to the soil-N reading L days later,
where N_eff = N applied x (1 - runoff loss). It is fitted on the 7-day mean soil-N sensor reading with block and
zone x month effects (season), so it only uses changes within a block over time:

    soil_n_7d(block, day) = block effect + zone-month effect + alpha * sum_e N_eff_e * exp(-(day - day_e) / tau)

tau is chosen on validation 2024; alpha by least squares. The optimizer uses it to carry an application's effect into
later plucking rounds (the yield model's top driver is the soil-N reading before the round).

Usage:
    python -m src.optimizer.soil_n          # fit, validate, write artifacts/models/soil_n_response.json
"""
import json
import os

import numpy as np
import pandas as pd

OUT = "artifacts/models/soil_n_response.json"
TAUS = [10, 15, 20, 30, 45, 60, 90, 120, 180, 270, 365]
MAX_LAG = 365


def load_series():
    d = pd.read_csv("data/model_ready/smarttea_master_block_daily.csv.gz",
                    usecols=["block_id", "date", "agro_zone", "soil_n_ppm"], parse_dates=["date"])
    d = d.sort_values(["block_id", "date"])
    d["soil_n_7d"] = d.groupby("block_id").soil_n_ppm.transform(lambda s: s.rolling(7, min_periods=4).mean())
    ev = pd.read_csv("data/processed/hybrid/05_intervention_records.csv", parse_dates=["execution_datetime"])
    f = ev[ev.intervention_type == "fertilizer"]
    f = pd.DataFrame({"block_id": f.block_id, "date": f.execution_datetime.dt.normalize(),
                      "n_eff": f.n_kg_per_ha * (1 - f.runoff_loss_est_pct / 100)})
    return d, f


def impulse(d, f, tau):
    """sum_e N_eff_e * exp(-(day - day_e)/tau) for each block-day (effect starts the day after the application)."""
    out = np.zeros(len(d))
    for b, g in d.groupby("block_id"):
        days = (g.date - g.date.min()).dt.days.to_numpy()
        x = np.zeros(days.max() + 1)
        for _, e in f[f.block_id == b].iterrows():
            t = (e.date - g.date.min()).days
            if 0 <= t <= days.max():
                lag = np.arange(1, min(MAX_LAG, days.max() - t) + 1)
                x[t + lag] += e.n_eff * np.exp(-lag / tau)
        out[g.index] = x[days]
    return out


def design(d):
    blk = pd.get_dummies(d.block_id, dtype=float)
    season = pd.get_dummies(d.agro_zone + "_" + d.date.dt.month.astype(str), dtype=float)
    return pd.concat([blk, season.iloc[:, 1:]], axis=1).to_numpy()


def fit(d, f, tau, train):
    z = impulse(d, f, tau)
    X = np.column_stack([design(d), z])
    ok = train & d.soil_n_7d.notna().to_numpy()
    coef, *_ = np.linalg.lstsq(X[ok], d.soil_n_7d.to_numpy()[ok], rcond=None)
    return coef, X @ coef


def r2(y, p):
    m = ~np.isnan(y)
    return 1 - ((y[m] - p[m]) ** 2).sum() / ((y[m] - y[m].mean()) ** 2).sum()


def main():
    d, f = load_series()
    d = d.reset_index(drop=True)
    yr = d.date.dt.year.to_numpy()
    train, val, test = yr <= 2023, yr == 2024, yr == 2025
    y = d.soil_n_7d.to_numpy()
    _, p0 = fit(d, f.iloc[:0], 30, train)     # no fertilizer term: block + season only
    print(f"baseline (block + season only): val R2 {r2(y[val], p0[val]):.3f}")
    rows = []
    for tau in TAUS:
        coef, p = fit(d, f, tau, train)
        rows.append(dict(tau=tau, alpha=coef[-1], train_r2=r2(y[train], p[train]), val_r2=r2(y[val], p[val])))
        print(f"  tau {tau:4d} d  alpha {coef[-1]:.3f} ppm per kg N_eff   train R2 {rows[-1]['train_r2']:.3f}  "
              f"val R2 {rows[-1]['val_r2']:.3f}")
    best = max(rows, key=lambda r: r["val_r2"])
    coef, p = fit(d, f, best["tau"], train)
    res = dict(alpha_ppm_per_kg_n_eff=round(float(coef[-1]), 4), tau_days=best["tau"],
               val_r2=round(best["val_r2"], 3), test_r2=round(r2(y[test], p[test]), 3),
               baseline_val_r2=round(r2(y[val], p0[val]), 3),
               fitted_on="2021-2023 (tau chosen on 2024; test 2025)",
               note="effect(L) = alpha * N_eff * exp(-L/tau); N_eff = N x (1 - runoff loss)")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(res, open(OUT, "w"), indent=2)
    print(json.dumps(res, indent=2))


def load_response(path=OUT):
    r = json.load(open(path))
    return r["alpha_ppm_per_kg_n_eff"], r["tau_days"]


if __name__ == "__main__":
    main()
