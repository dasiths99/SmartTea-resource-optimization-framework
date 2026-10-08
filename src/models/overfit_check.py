"""Overfitting check: XGBoost from flexible to strongly regularised, on the live (decision-time) feature sets.

Protocol (no peeking at the test year):
  1. Fit on train (2021-2023) with early stopping on val (2024).
  2. Choose the configuration by val R2 only.
  3. Refit the chosen configuration on train+val with the early-stopped number of trees; score test (2025) once.
  4. Hardest realistic score: unseen blocks AND a future year (train on other folds' 2021-2023 rows,
     predict the held-out fold's 2025 rows).

Usage:
    python -m src.models.overfit_check            # writes artifacts/reports/overfit_check.csv
"""
import os

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, r2_score

from src.data.load import load_task, monotone_constraints

CONFIGS = {  # increasing regularisation
    "A flexible (old default)": dict(max_depth=5, min_child_weight=1, reg_lambda=1, gamma=0, subsample=0.8, colsample_bytree=0.8),
    "B moderate": dict(max_depth=4, min_child_weight=5, reg_lambda=5, gamma=0, subsample=0.8, colsample_bytree=0.7),
    "C strong": dict(max_depth=3, min_child_weight=10, reg_lambda=10, gamma=0.5, subsample=0.7, colsample_bytree=0.6),
    "D very strong": dict(max_depth=2, min_child_weight=20, reg_lambda=20, gamma=1, subsample=0.7, colsample_bytree=0.6),
}
BASE = dict(learning_rate=0.03, random_state=0, n_jobs=-1)


def model(cfg, n_estimators=2000, mono=None, early=True):
    kw = dict(BASE, **cfg, n_estimators=n_estimators)
    if early:
        kw["early_stopping_rounds"] = 100
    if mono is not None:
        kw["monotone_constraints"] = "(" + ",".join(map(str, mono)) + ")"
    return xgb.XGBRegressor(**kw)


def evaluate(task, feature_set, use_mono):
    X, y, m = load_task(task, feature_set)
    tr, va, te = (m.split == "train").to_numpy(), (m.split == "val").to_numpy(), (m.split == "test").to_numpy()
    mono = monotone_constraints(task, list(X.columns)) if use_mono else None
    rows = []
    for name, cfg in CONFIGS.items():
        es = model(cfg, mono=mono).fit(X[tr], y[tr], eval_set=[(X[va], y[va])], verbose=False)
        n = es.best_iteration + 1
        r_train, r_val = r2_score(y[tr], es.predict(X[tr])), r2_score(y[va], es.predict(X[va]))
        final = model(cfg, n, mono, early=False).fit(X[tr | va], y[tr | va])
        p = final.predict(X[te])
        cv = []
        for k in range(5):
            a, b = (m.cv_fold != k).to_numpy() & tr, (m.cv_fold == k).to_numpy() & te
            cv.append(r2_score(y[b], model(cfg, n, mono, early=False).fit(X[a], y[a]).predict(X[b])))
        rows.append(dict(task=task, features=feature_set, config=name, trees=n, train_r2=r_train, val_r2=r_val,
                         test_r2=r2_score(y[te], p), test_mae=mean_absolute_error(y[te], p),
                         unseen_block_future_r2=np.mean(cv), unseen_sd=np.std(cv), gap_train_val=r_train - r_val))
    df = pd.DataFrame(rows)
    df["chosen"] = df.val_r2 == df.val_r2.max()
    return df


def main():
    out = pd.concat([evaluate("yield", "live", False), evaluate("yield", "hindsight", False),
                     evaluate("runoff", "live", True), evaluate("runoff", "hindsight", True)], ignore_index=True)
    os.makedirs("artifacts/reports", exist_ok=True)
    out.round(3).to_csv("artifacts/reports/overfit_check.csv", index=False)
    pd.set_option("display.width", 200)
    for (t, f), g in out.groupby(["task", "features"], sort=False):
        print(f"\n== {t} / {f} ==")
        print(g.drop(columns=["task", "features"]).round(3).to_string(index=False))


if __name__ == "__main__":
    main()
